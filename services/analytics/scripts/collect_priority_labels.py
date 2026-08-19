#!/usr/bin/env python3
"""Harvest foil priority labels from a broadcast video's scoreboard and lamps.

The label comes free from the referee. When both lamps light, both hits were
valid and the referee *had* to rule on priority; the side whose score then goes
up is the side they ruled for. Single-lamp touches are skipped on purpose —
there was no priority ruling to record, so there is no answer to learn.

Unlike ``scripts/detect_touch_lamps.py``, which annotates an existing continuous
report, this script starts from raw video. It never runs pose estimation, so a
bout costs OCR plus a cheap HSV pass rather than a full analysis.

Three passes, cheapest-last-resort first:

1. **Coarse OCR** every ``--sample-interval`` frames, to find score changes.
   Tesseract is the whole cost of the run, so this interval is the only knob
   that really matters for wall-clock.
2. **Refine** each candidate with a fine OCR re-scan of its neighbourhood, to
   recover the frame the new score *first* appeared on. The coarse pass can only
   locate that to within one interval.
3. **Lamps** over the merged neighbourhoods of the refined frames. No OCR — pure
   HSV fill fractions — so this pass is nearly free.

Usage:
    cd services/analytics
    PYTHONPATH=. .venv/bin/python3 scripts/collect_priority_labels.py \\
        --video data/raw/usaf_DMMRIZJuoRY.mp4

    # arbitrary lamp rectangles, for a broadcaster the layout table lacks
    PYTHONPATH=. .venv/bin/python3 scripts/collect_priority_labels.py \\
        --video foo.mp4 --lamp-roi "left=396,652,444,694;right=836,652,884,694"
"""

import argparse
import csv
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import cv2

from analyzer.config import (
    LAMP_EVENT_MERGE_GAP,
    LAMP_SAMPLE_STEP,
    OCR_TOUCH_DELAY_MEDIAN_SEC,
)
from analyzer.tv_overlay_ocr import (
    LampBarReader,
    LampReading,
    TVOverlayOCR,
    TVScoreTracker,
    TVTouchEvent,
)
from pipeline.priority_label_rules import (
    REJECT_ORDER,
    LabelDecision,
    decide_priority_label,
)
from scripts.detect_touch_lamps import (
    merge_windows,
    read_touch_readings,
    touch_window,
)

DEFAULT_OUT_DIR = Path("data/priority_labels")

#: Coarse OCR stride. 12 frames at 30fps is 0.4s — far finer than the ~1s the
#: overlay itself takes to update, so no touch can hide between samples.
DEFAULT_SAMPLE_INTERVAL = 12
#: Stride for the refine pass. 2 keeps it near frame-exact without paying for
#: every frame.
DEFAULT_REFINE_STEP = 2

DEFAULT_CLIP_BEFORE = 6.0
DEFAULT_CLIP_AFTER = 1.0
DEFAULT_PREVIEW_COUNT = 6

#: Frames both lamps must be lit together before a "double" is believed. Foil
#: locks out the second hit 300ms (9 frames at 30fps) after the first, so any
#: real double overlaps for most of the lamp display. Measured on the Li–Lin
#: bout, genuine doubles overlapped for 48-57 frames and the one false double
#: overlapped for 0 — the gate has a wide margin.
DEFAULT_MIN_LAMP_OVERLAP = 9

CSV_HEADER = [
    "video_id",
    "clip",
    "touch_time",
    "label",
    "both_lamps",
    "score_before",
    "score_after",
    "touch_frame",
    "lamp_frame",
    "lamp_confidence",
    "lamp_overlap_frames",
]


# ── Lamp reading over arbitrary rectangles ──────────────────


class RectLampReader(LampBarReader):
    """Read lamps from absolute frame rectangles instead of the overlay bar.

    Subclasses rather than reimplements: event grouping, pattern naming,
    confidence and touch attribution are all inherited, so a manual ROI cannot
    drift away from the semantics the layout-driven path is tested against.
    Only *where the pixels come from* changes.
    """

    def __init__(self, rois: Dict[str, Tuple[int, int, int, int]], layout: str = "usa_fencing"):
        super().__init__(layout)
        missing = {"left", "right"} - set(rois)
        if missing:
            raise ValueError(f"lamp ROI missing sides: {sorted(missing)}")
        self._rois = rois

    def read_side_fills(self, frame) -> dict:
        fills = {}
        for side in ("left", "right"):
            x0, y0, x1, y1 = self._rois[side]
            region = frame[y0:y1, x0:x1] if frame is not None and frame.size else None
            if region is not None and region.size == 0:
                region = None
            fills[side] = self._region_fills(region)
        return fills


def parse_lamp_roi(spec: str) -> Dict[str, Tuple[int, int, int, int]]:
    """Parse ``"left=x0,y0,x1,y1;right=x0,y0,x1,y1"`` into a ROI dict."""
    rois: Dict[str, Tuple[int, int, int, int]] = {}
    for chunk in spec.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise ValueError(f"bad --lamp-roi segment (expected side=x0,y0,x1,y1): {chunk!r}")
        side, coords = chunk.split("=", 1)
        side = side.strip()
        if side not in ("left", "right"):
            raise ValueError(f"unknown lamp side {side!r}; expected 'left' or 'right'")
        parts = [p.strip() for p in coords.split(",")]
        if len(parts) != 4:
            raise ValueError(f"--lamp-roi {side} needs 4 integers, got {len(parts)}")
        try:
            x0, y0, x1, y1 = (int(p) for p in parts)
        except ValueError as exc:
            raise ValueError(f"--lamp-roi {side} coordinates must be integers") from exc
        if x1 <= x0 or y1 <= y0:
            raise ValueError(f"--lamp-roi {side} must satisfy x0<x1 and y0<y1")
        rois[side] = (x0, y0, x1, y1)
    if {"left", "right"} - set(rois):
        raise ValueError("--lamp-roi must define both 'left' and 'right'")
    return rois


# ── Collected records ───────────────────────────────────────


@dataclass
class TouchRecord:
    """One detected score change and everything decided about it."""

    index: int
    touch_frame: int
    touch_time: float
    scorer: str
    score_before: str
    score_after: str
    lamp_pattern: Optional[str] = None
    lamp_confidence: float = 0.0
    lamp_frame: Optional[int] = None
    #: Frames on which both lamps read lit. None when not measured.
    overlap_frames: Optional[int] = None
    #: First frame both lamps were seen lit together — the frame a human should
    #: be shown, since the event start often catches only one of them.
    overlap_frame: Optional[int] = None
    decision: Optional[LabelDecision] = None
    clip_path: Optional[str] = None
    preview_path: Optional[str] = None

    @property
    def accepted(self) -> bool:
        return bool(self.decision and self.decision.accepted)


@dataclass
class CollectionStats:
    """Yield funnel for one video."""

    touches_detected: int = 0
    lamp_read: int = 0
    two_light: int = 0
    labels_confirmed: int = 0
    rejected: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ── Pass 1+2: score changes ─────────────────────────────────


def _ocr_scores(
    ocr: TVOverlayOCR,
    cap,
    start_frame: int,
    end_frame: int,
    step: int,
    tracker: TVScoreTracker,
    fps: float,
) -> List[TVTouchEvent]:
    """Feed a decimated frame range through the tracker, returning new events."""
    events: List[TVTouchEvent] = []
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, start_frame))
    frame_num = max(0, start_frame)
    while frame_num <= end_frame:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_num % step == 0:
            data = ocr.read_overlay(frame)
            if data is not None:
                event = tracker.update(frame_num, data, fps=fps)
                if event is not None:
                    events.append(event)
        frame_num += 1
    return events


def scan_score_changes(
    video_path: Path,
    layout: str,
    sample_interval: int,
    progress_every: int = 9000,
) -> Tuple[List[TVTouchEvent], float, int]:
    """Coarse pass: every score change the overlay shows.

    The tracker's debounce is widened to two sample strides so a confirmation
    still needs three consistent reads. Left at its frame-based default, a
    coarse stride would confirm on the second read and let single-frame OCR
    noise through as touches.
    """
    ocr = TVOverlayOCR(layout=layout)
    tracker = TVScoreTracker(debounce_frames=max(1, sample_interval * 2))
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    events: List[TVTouchEvent] = []
    frame_num = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_num % sample_interval == 0:
            data = ocr.read_overlay(frame)
            if data is not None:
                event = tracker.update(frame_num, data, fps=fps)
                if event is not None:
                    events.append(event)
        if progress_every and frame_num and frame_num % progress_every == 0:
            pct = (100.0 * frame_num / total) if total else 0.0
            print(
                f"    ...frame {frame_num}/{total} ({pct:.0f}%), {len(events)} touches",
                flush=True,
            )
        frame_num += 1
    cap.release()
    return events, fps, total


def refine_touch_frames(
    video_path: Path,
    layout: str,
    events: Sequence[TVTouchEvent],
    sample_interval: int,
    refine_step: int,
) -> List[int]:
    """Recover the frame each new score *first* appeared on.

    The coarse pass reports the frame the change was first *sampled*, which can
    trail the real transition by up to one interval. Clip anchoring and lamp
    matching both key off this frame, so it is worth a short fine re-scan.
    Falls back to the coarse frame whenever the re-scan finds nothing.
    """
    if not events:
        return []
    ocr = TVOverlayOCR(layout=layout)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {video_path}")

    refined: List[int] = []
    for event in events:
        target = event.score_after
        lo = max(0, event.frame - sample_interval * 2)
        hi = event.frame + sample_interval
        found: Optional[int] = None
        cap.set(cv2.CAP_PROP_POS_FRAMES, lo)
        frame_num = lo
        while frame_num <= hi:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_num % refine_step == 0:
                data = ocr.read_overlay(frame)
                if data is not None and data.left_score is not None and data.right_score is not None:
                    if f"{data.left_score}-{data.right_score}" == target:
                        found = frame_num
                        break
            frame_num += 1
        refined.append(found if found is not None else event.frame)
    cap.release()
    return refined


# ── Pass 3: lamps ───────────────────────────────────────────


def read_lamps(
    video_path: Path,
    reader: LampBarReader,
    touch_frames: Sequence[int],
    step: int,
) -> List[Optional[LampReading]]:
    """Attribute a lamp event to each touch.

    Windows are merged before scanning so overlapping neighbourhoods decode each
    frame once and a lamp event straddling two windows is never split in half.
    """
    if not touch_frames:
        return []
    windows = merge_windows([touch_window(f) for f in touch_frames])
    events = []
    for start, end in windows:
        events.extend(reader.scan_video_events(str(video_path), start, end, step=step))
    events.sort(key=lambda e: e.start_frame)

    # Attribution and the previous_end chaining are detect_touch_lamps' —
    # reused rather than restated so the two entry points cannot disagree about
    # which lamp event explains which touch.
    return read_touch_readings(reader, events, touch_frames)


def measure_overlap(
    video_path: Path,
    reader: LampBarReader,
    reading: Optional[LampReading],
    step: int,
) -> Tuple[Optional[int], Optional[int]]:
    """Count frames on which both lamps were lit at once.

    ``LampEvent`` stores a peak state per side over the whole event, which
    cannot distinguish "both lamps on together" from "one lamp, then the other".
    Foil's 300ms lockout means a real double overlaps; a sequence does not. So
    the frames are re-read — only the event's own span, which is under two
    seconds — to recover the simultaneity the event model dropped.

    Returns ``(overlap_frames, first_overlap_frame)``. The frame is where both
    lamps were first seen lit together, which is the only frame worth showing a
    human: the event's own start frame usually catches just one lamp, because
    the two fire up to a lockout apart. Both are ``None`` when the overlap could
    not be measured (no event, or the video would not seek).
    """
    if reading is None or reading.start_frame is None or reading.end_frame is None:
        return (None, None)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return (None, None)
    # Look a merge-gap before the event start. The event's start_frame is the
    # first frame *this* touch's event was sampled on, and when two lamp events
    # sit close together the matcher can hand back the later one while the
    # lamps were already on just before it. Scanning strictly inside the event
    # then measures zero overlap for a genuine double — observed on
    # usaf_gdOdpDyaWrw touch 15, whose lamps overlapped 13 frames before the
    # reported start.
    start = int(reading.start_frame) - LAMP_EVENT_MERGE_GAP
    end = int(reading.end_frame)
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, start))
    frame_num = max(0, start)
    overlap = 0
    first: Optional[int] = None
    step = max(1, step)
    while frame_num <= end:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_num % step == 0:
            left_state, right_state = reader.read_side_states(frame)
            if left_state == "color" and right_state == "color":
                overlap += step
                if first is None:
                    first = frame_num
        frame_num += 1
    cap.release()
    return (overlap, first)


# ── Clips and previews ──────────────────────────────────────


def clip_start_frame(record: TouchRecord, fps: float) -> int:
    """Frame the clip should open on.

    Anchors on the lamp, not the scoreboard. The lamps fire at the moment of the
    touch; the overlay score trails it by about a second while the referee
    awards the point, so anchoring on the score frame would push the phrase
    itself out of the front of the clip.
    """
    anchor = record.lamp_frame
    if anchor is None:
        anchor = int(record.touch_frame - OCR_TOUCH_DELAY_MEDIAN_SEC * fps)
    return max(0, anchor)


def cut_clip(
    video_path: Path,
    out_path: Path,
    start_sec: float,
    duration: float,
) -> bool:
    """Extract one clip with ffmpeg. Returns True on success."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{max(0.0, start_sec):.3f}",
        "-i", str(video_path),
        "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-an",
        str(out_path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=120)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        print(f"    clip failed ({out_path.name}): {exc}", file=sys.stderr)
        return False
    if proc.returncode != 0:
        print(f"    clip failed ({out_path.name}): {proc.stderr.decode()[:200]}", file=sys.stderr)
        return False
    return True


def write_preview(
    video_path: Path,
    out_path: Path,
    lamp_frame: Optional[int],
    score_frame: int,
    caption: str,
) -> bool:
    """Save a two-panel JPEG for human verification.

    One panel alone is never enough: at the lamp frame both lights are visible
    but the score has not moved yet, and by the time the score has moved the
    lamps are usually out. Stacking the two puts the whole claim — *these* two
    lamps, *that* point — in one image.
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return False
    panels = []
    for frame_idx, tag in ((lamp_frame, "LAMPS"), (score_frame, "SCORE")):
        if frame_idx is None:
            continue
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame_idx))
        ok, frame = cap.read()
        if not ok:
            continue
        labelled = frame.copy()
        cv2.putText(labelled, f"{tag} f={frame_idx}", (12, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(labelled, f"{tag} f={frame_idx}", (12, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2, cv2.LINE_AA)
        panels.append(labelled)
    cap.release()
    if not panels:
        return False

    stacked = panels[0] if len(panels) == 1 else cv2.vconcat(panels)
    banner = stacked.copy()
    cv2.rectangle(banner, (0, 0), (banner.shape[1], 44), (0, 0, 0), -1)
    cv2.putText(banner, caption, (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                (255, 255, 255), 2, cv2.LINE_AA)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    return bool(cv2.imwrite(str(out_path), banner))


def select_preview_indices(records: Sequence[TouchRecord], count: int) -> List[int]:
    """Spread previews across the bout instead of taking the first N.

    The first few touches of a bout share lighting, camera framing and score
    geometry; sampling them alone would verify one situation N times.
    """
    accepted = [i for i, r in enumerate(records) if r.accepted]
    if not accepted or count <= 0:
        return []
    if len(accepted) <= count:
        return accepted
    stride = (len(accepted) - 1) / (count - 1) if count > 1 else 1
    return [accepted[int(round(i * stride))] for i in range(count)]


# ── Reporting ───────────────────────────────────────────────


def build_stats(records: Sequence[TouchRecord]) -> CollectionStats:
    stats = CollectionStats(touches_detected=len(records))
    for record in records:
        if record.lamp_pattern is not None:
            stats.lamp_read += 1
        if record.decision and record.decision.both_lamps:
            stats.two_light += 1
        if record.accepted:
            stats.labels_confirmed += 1
        elif record.decision and record.decision.reject_reason:
            reason = record.decision.reject_reason
            stats.rejected[reason] = stats.rejected.get(reason, 0) + 1
    return stats


def format_stats(stats: CollectionStats) -> str:
    total = stats.touches_detected or 1
    lines = [
        "",
        "  Yield",
        "  " + "-" * 52,
        f"  touches detected      {stats.touches_detected:4d}",
        f"  lamp read             {stats.lamp_read:4d}  ({100*stats.lamp_read/total:5.1f}%)",
        f"  two-light (double)    {stats.two_light:4d}  ({100*stats.two_light/total:5.1f}%)",
        f"  labels confirmed      {stats.labels_confirmed:4d}  ({100*stats.labels_confirmed/total:5.1f}%)",
        "",
        "  Discarded",
        "  " + "-" * 52,
    ]
    ordered = [r for r in REJECT_ORDER if r in stats.rejected]
    ordered += [r for r in sorted(stats.rejected) if r not in REJECT_ORDER]
    if not ordered:
        lines.append("  (none)")
    for reason in ordered:
        n = stats.rejected[reason]
        lines.append(f"  {reason:<34s} {n:4d}  ({100*n/total:5.1f}%)")
    return "\n".join(lines)


def write_labels_csv(path: Path, records: Sequence[TouchRecord], video_id: str) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_HEADER)
        for record in records:
            if not record.accepted:
                continue
            writer.writerow([
                video_id,
                record.clip_path or "",
                f"{record.touch_time:.2f}",
                record.decision.label,
                "true",
                record.score_before,
                record.score_after,
                record.touch_frame,
                record.lamp_frame if record.lamp_frame is not None else "",
                f"{record.lamp_confidence:.3f}",
                record.overlap_frames if record.overlap_frames is not None else "",
            ])
            rows += 1
    return rows


# ── Download ────────────────────────────────────────────────


def download_video(url: str, out_dir: Path, video_id: str) -> Path:
    """Fetch a YouTube video with the flags this project needs.

    ``--js-runtimes node`` is required: without a JS runtime yt-dlp cannot solve
    the player challenge and the download fails with a signature error.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{video_id}.mp4"
    cmd = [
        "yt-dlp", "--js-runtimes", "node",
        "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        "--merge-output-format", "mp4", "--no-playlist",
        "-o", str(out_dir / f"{video_id}.%(ext)s"),
        url,
    ]
    print(f"  downloading {url} -> {target}", flush=True)
    proc = subprocess.run(cmd, capture_output=True, timeout=3600)
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {proc.stderr.decode()[-500:]}")
    if not target.exists():
        raise RuntimeError(f"download reported success but {target} is missing")
    return target


# ── CLI ─────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    src = p.add_argument_group("source")
    src.add_argument("--video", type=Path, help="broadcast video file")
    src.add_argument("--url", help="YouTube URL to download first")
    src.add_argument("--video-id", help="output id (default: video filename stem)")

    scan = p.add_argument_group("scanning")
    scan.add_argument("--layout", default="usa_fencing", help="overlay layout name")
    scan.add_argument("--sample-interval", type=int, default=DEFAULT_SAMPLE_INTERVAL,
                      help=f"coarse OCR stride (default {DEFAULT_SAMPLE_INTERVAL})")
    scan.add_argument("--refine-step", type=int, default=DEFAULT_REFINE_STEP,
                      help=f"fine OCR stride (default {DEFAULT_REFINE_STEP})")
    scan.add_argument("--lamp-step", type=int, default=LAMP_SAMPLE_STEP,
                      help=f"lamp sampling stride (default {LAMP_SAMPLE_STEP})")
    scan.add_argument("--lamp-roi", help='absolute lamp rectangles, '
                                         '"left=x0,y0,x1,y1;right=x0,y0,x1,y1"')
    scan.add_argument("--min-lamp-confidence", type=float, default=0.0,
                      help="discard two-light reads below this confidence")
    scan.add_argument("--min-lamp-overlap", type=int, default=DEFAULT_MIN_LAMP_OVERLAP,
                      help="frames both lamps must be lit together for a double "
                           f"to count (default {DEFAULT_MIN_LAMP_OVERLAP}; 0 disables). "
                           "Guards against two sequential single lamps being "
                           "merged into one apparent double.")

    out = p.add_argument_group("output")
    out.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    out.add_argument("--clip-before", type=float, default=DEFAULT_CLIP_BEFORE)
    out.add_argument("--clip-after", type=float, default=DEFAULT_CLIP_AFTER)
    out.add_argument("--preview-count", type=int, default=DEFAULT_PREVIEW_COUNT)
    out.add_argument("--no-clips", action="store_true", help="skip clip extraction")
    out.add_argument("--dry-run", action="store_true", help="scan and report, write nothing")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    started = time.time()

    if not args.video and not args.url:
        print("error: one of --video or --url is required", file=sys.stderr)
        return 1

    lamp_rois = None
    if args.lamp_roi:
        try:
            lamp_rois = parse_lamp_roi(args.lamp_roi)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    video_id = args.video_id
    if args.url and not args.video:
        if not video_id:
            video_id = args.url.rsplit("=", 1)[-1].rsplit("/", 1)[-1]
        try:
            video_path = download_video(args.url, Path("data/raw"), video_id)
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    else:
        video_path = args.video
        if not video_path.exists():
            print(f"error: video not found: {video_path}", file=sys.stderr)
            return 1
        video_id = video_id or video_path.stem

    print(f"Video    : {video_path}")
    print(f"Video id : {video_id}")

    try:
        reader = (
            RectLampReader(lamp_rois, layout=args.layout)
            if lamp_rois else LampBarReader(layout=args.layout)
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # Pass 1
    print(f"\n[1/3] coarse OCR (every {args.sample_interval} frames)...", flush=True)
    t0 = time.time()
    try:
        events, fps, total_frames = scan_score_changes(
            video_path, args.layout, args.sample_interval
        )
    except (RuntimeError, ValueError, ImportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"      {len(events)} score changes in {time.time()-t0:.0f}s "
          f"({total_frames} frames @ {fps:.0f}fps)")

    # Pass 2
    print(f"\n[2/3] refining touch frames (step {args.refine_step})...", flush=True)
    t0 = time.time()
    refined = refine_touch_frames(
        video_path, args.layout, events, args.sample_interval, args.refine_step
    )
    moved = sum(1 for e, r in zip(events, refined) if r != e.frame)
    print(f"      {moved}/{len(events)} frames moved in {time.time()-t0:.0f}s")

    # Pass 3
    print(f"\n[3/3] reading lamps (step {args.lamp_step})...", flush=True)
    t0 = time.time()
    readings = read_lamps(video_path, reader, refined, args.lamp_step)
    print(f"      done in {time.time()-t0:.0f}s")

    # Decide
    records: List[TouchRecord] = []
    for i, (event, frame, reading) in enumerate(zip(events, refined, readings), start=1):
        record = TouchRecord(
            index=i,
            touch_frame=frame,
            touch_time=frame / fps if fps else 0.0,
            scorer=event.scorer,
            score_before=event.score_before,
            score_after=event.score_after,
            lamp_pattern=reading.pattern if reading else None,
            lamp_confidence=reading.confidence if reading else 0.0,
            lamp_frame=reading.start_frame if reading else None,
        )
        # Only doubles need the simultaneity check, and it costs a seek, so it
        # is not paid for touches that are already going to be rejected.
        if record.lamp_pattern == "double" and args.min_lamp_overlap > 0:
            record.overlap_frames, record.overlap_frame = measure_overlap(
                video_path, reader, reading, args.lamp_step
            )
        record.decision = decide_priority_label(
            lamp_pattern=record.lamp_pattern,
            score_before=record.score_before,
            score_after=record.score_after,
            scorer=record.scorer,
            lamp_confidence=record.lamp_confidence,
            min_confidence=args.min_lamp_confidence,
            overlap_frames=record.overlap_frames,
            min_overlap_frames=args.min_lamp_overlap,
        )
        records.append(record)

    stats = build_stats(records)

    out_dir = args.out_dir / video_id
    preview_idx = set(select_preview_indices(records, args.preview_count))

    if not args.dry_run:
        n_clip = 0
        for i, record in enumerate(records):
            if not record.accepted:
                continue
            start_frame = clip_start_frame(record, fps)
            start_sec = max(0.0, start_frame / fps - args.clip_before)
            duration = args.clip_before + args.clip_after
            clip_name = f"clip_{record.index:03d}.mp4"
            if not args.no_clips:
                if cut_clip(video_path, out_dir / clip_name, start_sec, duration):
                    record.clip_path = clip_name
                    n_clip += 1
            if i in preview_idx:
                caption = (
                    f"{video_id} #{record.index}  "
                    f"{record.score_before}->{record.score_after}  "
                    f"priority={record.decision.label}  conf={record.lamp_confidence:.2f}"
                )
                name = f"preview_{record.index:03d}.jpg"
                lamp_panel = record.overlap_frame or record.lamp_frame
                if write_preview(video_path, out_dir / name,
                                 lamp_panel, record.touch_frame, caption):
                    record.preview_path = name
        print(f"\n  clips written  : {n_clip}")
        print(f"  previews written: {sum(1 for r in records if r.preview_path)}")

        csv_path = out_dir / "labels.csv"
        rows = write_labels_csv(csv_path, records, video_id)
        summary = {
            "video_id": video_id,
            "video_path": str(video_path),
            "fps": fps,
            "total_frames": total_frames,
            "duration_sec": total_frames / fps if fps else 0.0,
            "sample_interval": args.sample_interval,
            "elapsed_sec": round(time.time() - started, 1),
            "stats": stats.to_dict(),
            "touches": [
                {
                    "index": r.index,
                    "touch_frame": r.touch_frame,
                    "touch_time": round(r.touch_time, 2),
                    "score": f"{r.score_before}->{r.score_after}",
                    "scorer": r.scorer,
                    "lamp": r.lamp_pattern,
                    "lamp_confidence": r.lamp_confidence,
                    "lamp_overlap_frames": r.overlap_frames,
                    "lamp_overlap_frame": r.overlap_frame,
                    "accepted": r.accepted,
                    "label": r.decision.label if r.decision else None,
                    "reject_reason": r.decision.reject_reason if r.decision else None,
                }
                for r in records
            ],
        }
        (out_dir / "summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"  labels.csv     : {csv_path} ({rows} rows)")
        print(f"  summary.json   : {out_dir / 'summary.json'}")

    print(format_stats(stats))
    print(f"\n  elapsed: {time.time()-started:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
