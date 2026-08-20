#!/usr/bin/env python3
"""Cut 4K frame windows around blade actions, for hand-labelling guard and tip.

Foil priority hangs on one thing the pipeline cannot see today: during a parry,
did the blades actually touch? The 1280-wide work file cannot answer it — a
blade there is ~68px long and one or two px wide, thinner than the JPEG noise.
On the 4K original the same blade is ~200px long, which a human can point at.

So this script goes back to the untouched 4K recording. It never reads the work
file; it only borrows its *coordinates*, which is where the three frames of
reference in this pipeline meet:

  * report frame numbers  - work file, 30fps, 1280px wide
  * keypoint coordinates  - work file pixel space (1280 x 250)
  * everything this writes- 4K source pixel space (3840 x 2160), 60fps

The bridge is time, never a frame count: work frame N is at t = N / work_fps,
and the 4K frame at that instant is round(t * source_fps). Frame *numbers* do
not convert directly — the container reports 59.97 average fps even though its
timestamps are an exact 1/60 grid — so a count-based mapping drifts by ~8
frames over a 5-minute bout while the time-based one stays exact. Verified by
re-deriving work frames 281/311/341/355 from the 4K source and diffing against
the work file: mean abs error 2.4/255 at offset 0 versus 3.2+ one frame either
way, at both ends of the recording.

Windows come from two places:

  * every touch, over [t - 2.0s, t + 0.5s] — the phrase that earned the light
  * every exchange the report flagged with a parry, whether or not it scored —
    those are the ones that carry a blade contact to judge

Overlapping windows merge, so a touch inside a parried exchange is one window
carrying both reasons rather than two overlapping extractions of the same
frames.

Usage:
    cd services/analytics

    PYTHONPATH=. .venv/bin/python3 scripts/extract_blade_windows.py \\
        --report data/reports/private/260716_de64_s1_piste3_continuous_report.json \\
        --config data/piste_configs/260716_de64_s1_piste3.json \\
        --source "/Volumes/Film/Fencing/2026/07/260716_...MOV" \\
        --out data/blade_labels/260716_de64_s1_piste3

    # fewer frames per second of window (source fps must divide evenly)
    ... --sample-fps 15
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------

MANIFEST_VERSION = 1

#: Window around a touch. The lead is long enough to contain the preparation
#: and the parry that preceded the light; the tail only has to survive the
#: lamp's own latency.
TOUCH_LEAD_SEC = 2.0
TOUCH_TAIL_SEC = 0.5

DEFAULT_SAMPLE_FPS = 30

#: Crop padding around the two fencers, in 4K pixels. Derived from this piste's
#: measured scale of ~226 px/m (fitted from the report's hip-position metres
#: against the sidecar's hip pixels): a 90cm blade is ~203px, so 320px sideways
#: leaves the tip inside the crop even fully extended in a lunge, and 260px
#: above covers a blade held high in sixte or a salute. Below the fencers there
#: is only floor, so that side stays tight.
MARGIN_X_PX = 320
MARGIN_TOP_PX = 260
MARGIN_BOTTOM_PX = 100

#: Keypoints below this confidence are ignored when sizing a crop — a stray
#: low-confidence joint on the far side of the hall would blow the box up.
#: Sidecar confidences are ints scaled by ``conf_scale``.
MIN_KEYPOINT_CONF = 0.3

#: JPEG quality for ffmpeg's -q:v (2 is ~95; the blade is the point, so this
#: never goes lower). Frames are written at 4K crop resolution, never resized.
JPEG_QSCALE = 2

WINDOW_DIR_FMT = "window_{:03d}"
FRAME_FILE_FMT = "frame_{:06d}.jpg"
MANIFEST_NAME = "manifest.json"


# ----------------------------------------------------------------------
# Pure helpers: windows
# ----------------------------------------------------------------------


@dataclass
class Window:
    """A contiguous span of the bout to extract, in seconds of source time."""

    start_sec: float
    end_sec: float
    reasons: List[str] = field(default_factory=list)

    def overlaps(self, other: "Window") -> bool:
        # Touching ends count as overlapping: two windows that meet exactly
        # would otherwise produce a duplicated boundary frame.
        return self.start_sec <= other.end_sec and other.start_sec <= self.end_sec


def work_frame_to_seconds(frame: int, work_fps: float) -> float:
    """Work-file frame number -> seconds. The only sanctioned bridge."""
    if work_fps <= 0:
        raise ValueError(f"work_fps must be positive, got {work_fps}")
    return frame / float(work_fps)


def seconds_to_source_frame(seconds: float, source_fps: float) -> int:
    """Seconds -> 4K source frame index, on the source's own timestamp grid."""
    if source_fps <= 0:
        raise ValueError(f"source_fps must be positive, got {source_fps}")
    return int(round(seconds * float(source_fps)))


def touch_windows(
    touches: Sequence[dict],
    work_fps: float,
    lead_sec: float = TOUCH_LEAD_SEC,
    tail_sec: float = TOUCH_TAIL_SEC,
) -> List[Window]:
    """One window per touch, clamped at zero so the first touch stays usable."""
    windows: List[Window] = []
    for touch in touches:
        frame = touch.get("frame")
        if frame is None:
            continue
        t = work_frame_to_seconds(int(frame), work_fps)
        number = touch.get("touch_number", len(windows) + 1)
        windows.append(
            Window(
                start_sec=max(0.0, t - lead_sec),
                end_sec=t + tail_sec,
                reasons=[f"touch_{number}"],
            )
        )
    return windows


def parry_windows(exchanges: Sequence[dict], work_fps: float) -> List[Window]:
    """One window per exchange the report flagged with a parry, on either side.

    The whole exchange span is kept rather than a slice around some estimated
    contact instant: the report does not record *when* the parry happened, only
    that the arm trace looked like one, so guessing a centre would drop the
    contact as often as it framed it.
    """
    windows: List[Window] = []
    for ex in exchanges:
        if not (ex.get("parry_left") or ex.get("parry_right")):
            continue
        start = ex.get("start_frame")
        end = ex.get("end_frame")
        if start is None or end is None:
            continue
        number = ex.get("exchange_number", len(windows) + 1)
        windows.append(
            Window(
                start_sec=max(0.0, work_frame_to_seconds(int(start), work_fps)),
                end_sec=work_frame_to_seconds(int(end), work_fps),
                reasons=[f"exchange_{number}"],
            )
        )
    return windows


def merge_windows(windows: Sequence[Window]) -> List[Window]:
    """Union overlapping spans, keeping every reason that fed the result."""
    ordered = sorted(windows, key=lambda w: (w.start_sec, w.end_sec))
    merged: List[Window] = []
    for window in ordered:
        if merged and merged[-1].overlaps(window):
            current = merged[-1]
            current.end_sec = max(current.end_sec, window.end_sec)
            for reason in window.reasons:
                if reason not in current.reasons:
                    current.reasons.append(reason)
        else:
            merged.append(Window(window.start_sec, window.end_sec, list(window.reasons)))
    return merged


def window_source_frames(
    window: Window,
    source_fps: float,
    sample_fps: int,
    total_source_frames: Optional[int] = None,
) -> List[int]:
    """Source frame indices to extract, on the source's own frame grid.

    The first index is snapped to a multiple of the sampling step so a window
    always lands on the same frames whatever its start time rounds to — two
    overlapping runs of this script agree, and a frame keeps its identity
    across re-extractions.
    """
    step = sampling_step(source_fps, sample_fps)
    first = seconds_to_source_frame(window.start_sec, source_fps)
    last = seconds_to_source_frame(window.end_sec, source_fps)
    first = int(math.ceil(first / step) * step)
    frames = list(range(first, last + 1, step))
    if total_source_frames is not None:
        frames = [f for f in frames if f < total_source_frames]
    return frames


def sampling_step(source_fps: float, sample_fps: int) -> int:
    """How many source frames per emitted frame. Must divide evenly.

    A non-integer step would put emitted frames off the source's timestamp
    grid, and every downstream frame number would then be a rounding of a
    rounding. Refusing is better than silently drifting.
    """
    if sample_fps <= 0:
        raise ValueError(f"--sample-fps must be positive, got {sample_fps}")
    ratio = float(source_fps) / float(sample_fps)
    step = int(round(ratio))
    if step < 1 or abs(ratio - step) > 1e-6:
        raise ValueError(
            f"--sample-fps {sample_fps} does not divide the source's {source_fps:g} fps evenly "
            f"(ratio {ratio:.4f}); pick a divisor such as {_divisor_hint(source_fps)}"
        )
    return step


def _divisor_hint(source_fps: float) -> str:
    rounded = int(round(source_fps))
    options = [rounded // n for n in (1, 2, 3, 4, 6) if rounded % n == 0]
    return ", ".join(str(o) for o in options)


# ----------------------------------------------------------------------
# Pure helpers: coordinates
# ----------------------------------------------------------------------


def work_to_source_scale(piste_crop: dict, scale_width: int) -> float:
    """Pixels of 4K source per pixel of work file.

    ``prepare_piste_video.py`` builds the work file as ``crop`` then
    ``scale=scale_width:-2``, so one work pixel is ``crop.w / scale_width``
    source pixels in *both* axes (the scale keeps the aspect ratio).
    """
    if scale_width <= 0:
        raise ValueError(f"scale_width must be positive, got {scale_width}")
    return float(piste_crop["w"]) / float(scale_width)


def work_to_source_xy(x: float, y: float, piste_crop: dict, scale_width: int) -> Tuple[float, float]:
    """Work-file pixel -> 4K source pixel. Inverse of crop-then-scale."""
    scale = work_to_source_scale(piste_crop, scale_width)
    return x * scale + float(piste_crop["x"]), y * scale + float(piste_crop["y"])


def decode_pose_sample(flat: Optional[Sequence[int]], conf_scale: float, min_conf: float) -> List[Tuple[float, float]]:
    """One sidecar sample -> confident (x, y) joints in work coordinates."""
    if not flat:
        return []
    points: List[Tuple[float, float]] = []
    for i in range(0, len(flat) - 2, 3):
        conf = float(flat[i + 2]) / float(conf_scale)
        if conf >= min_conf:
            points.append((float(flat[i]), float(flat[i + 1])))
    return points


def keypoints_in_window(
    sidecar: dict,
    start_work_frame: int,
    end_work_frame: int,
    min_conf: float = MIN_KEYPOINT_CONF,
) -> List[Tuple[float, float]]:
    """Every confident joint of both fencers across a window, work coordinates."""
    sample_every = max(1, int(sidecar.get("sample_every", 1)))
    conf_scale = float(sidecar.get("conf_scale", 100)) or 100.0
    poses = sidecar.get("poses", {})
    first = start_work_frame // sample_every
    last = end_work_frame // sample_every
    collected: List[Tuple[float, float]] = []
    for side in ("left", "right"):
        samples = poses.get(side) or []
        for index in range(max(0, first), min(len(samples) - 1, last) + 1):
            collected.extend(decode_pose_sample(samples[index], conf_scale, min_conf))
    return collected


def crop_box_for_points(
    points: Sequence[Tuple[float, float]],
    piste_crop: dict,
    scale_width: int,
    source_resolution: Tuple[int, int],
    margin_x: int = MARGIN_X_PX,
    margin_top: int = MARGIN_TOP_PX,
    margin_bottom: int = MARGIN_BOTTOM_PX,
) -> Optional[Dict[str, int]]:
    """Fixed 4K crop covering every given joint plus blade room.

    Returns ``None`` when there is nothing to fit, so the caller can fall back.
    The box is clamped to the full 4K frame, not to the piste band — a blade
    raised in sixte reaches above the band, and there is no reason to cut it off
    when the source frame has those pixels. Width and height are forced even
    because ffmpeg's crop filter rejects odd dimensions on yuv420 input.
    """
    if not points:
        return None
    src_w, src_h = int(source_resolution[0]), int(source_resolution[1])
    xs, ys = [], []
    for x, y in points:
        sx, sy = work_to_source_xy(x, y, piste_crop, scale_width)
        xs.append(sx)
        ys.append(sy)

    left = int(math.floor(min(xs))) - margin_x
    right = int(math.ceil(max(xs))) + margin_x
    top = int(math.floor(min(ys))) - margin_top
    bottom = int(math.ceil(max(ys))) + margin_bottom

    left = max(0, left)
    top = max(0, top)
    right = min(src_w, right)
    bottom = min(src_h, bottom)

    width = max(2, (right - left) // 2 * 2)
    height = max(2, (bottom - top) // 2 * 2)
    return {"x": left, "y": top, "w": width, "h": height}


def piste_fallback_box(piste_crop: dict, source_resolution: Tuple[int, int]) -> Dict[str, int]:
    """The whole piste band — what to use when a window has no keypoints at all."""
    src_w, src_h = int(source_resolution[0]), int(source_resolution[1])
    x = max(0, int(piste_crop["x"]))
    y = max(0, int(piste_crop["y"]))
    w = min(src_w - x, int(piste_crop["w"])) // 2 * 2
    h = min(src_h - y, int(piste_crop["h"])) // 2 * 2
    return {"x": x, "y": y, "w": w, "h": h}


# ----------------------------------------------------------------------
# Source probing and extraction
# ----------------------------------------------------------------------


def probe_source(path: Path) -> dict:
    """Resolution, frame count and the *timestamp* fps of the 4K original.

    ``avg_frame_rate`` is deliberately not trusted for the grid: on this camera
    it reads 59.97 while the packet timestamps are an exact 1/60 apart (the
    container's duration runs slightly past the last frame). ``r_frame_rate``
    is the one that matches the timestamps, and timestamps are what seeking
    uses.
    """
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,avg_frame_rate,nb_frames,duration",
        "-of", "json", str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {proc.stderr.strip()}")
    stream = json.loads(proc.stdout)["streams"][0]

    def _rate(value: str) -> float:
        if not value or value in ("0/0", "N/A"):
            return 0.0
        if "/" in value:
            num, den = value.split("/", 1)
            return float(num) / float(den) if float(den) else 0.0
        return float(value)

    fps = _rate(stream.get("r_frame_rate", "")) or _rate(stream.get("avg_frame_rate", ""))
    nb_frames = int(stream["nb_frames"]) if str(stream.get("nb_frames", "")).isdigit() else None
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": fps,
        "nb_frames": nb_frames,
        "duration_sec": float(stream["duration"]) if stream.get("duration") else None,
    }


def build_extract_command(
    source: Path,
    first_source_frame: int,
    frame_count: int,
    step: int,
    crop: Dict[str, int],
    source_fps: float,
    out_pattern: str,
    qscale: int = JPEG_QSCALE,
) -> List[str]:
    """ffmpeg command extracting one window's frames at native resolution.

    Input seeking (``-ss`` before ``-i``) is accurate in modern ffmpeg, so after
    the seek the decoder's frame counter ``n`` starts at 0 on exactly the frame
    whose timestamp is ``first_source_frame / source_fps``. Sub-sampling is then
    ``select`` on that counter, which keeps every emitted frame on the source's
    own grid.

    The ``fps`` filter was tried first and rejected: even with ``-copyts`` and
    ``start_time=0`` its output drifted off the grid within a second of the
    window start (frames 30/60 of a 75-frame window matched work frames 5 and 6
    away from where they belonged), while ``select`` matched exactly at every
    offset tested.
    """
    start_sec = first_source_frame / float(source_fps)
    crop_filter = f"crop={crop['w']}:{crop['h']}:{crop['x']}:{crop['y']}"
    select = "select='not(mod(n\\," + str(step) + "))'" if step > 1 else "select=1"
    return [
        "ffmpeg", "-nostdin", "-v", "error", "-y",
        "-ss", f"{start_sec:.6f}",
        "-i", str(source),
        "-frames:v", str(frame_count),
        "-vf", f"{select},{crop_filter}",
        "-fps_mode", "passthrough",
        "-q:v", str(qscale),
        "-start_number", "0",
        out_pattern,
    ]


def extract_window(
    source: Path,
    window_dir: Path,
    source_frames: Sequence[int],
    step: int,
    crop: Dict[str, int],
    source_fps: float,
) -> List[Path]:
    """Extract one window and rename the output to its source frame numbers.

    ffmpeg can only write a sequential ``%d`` pattern, so the files land as
    ``_tmp_00000.jpg`` and get renamed here. Renaming (rather than naming
    directly) also makes a short extraction obvious: the loop stops at whatever
    ffmpeg actually produced and the caller sees the count.
    """
    window_dir.mkdir(parents=True, exist_ok=True)
    for stale in window_dir.glob("_tmp_*.jpg"):
        stale.unlink()

    cmd = build_extract_command(
        source=source,
        first_source_frame=source_frames[0],
        frame_count=len(source_frames),
        step=step,
        crop=crop,
        source_fps=source_fps,
        out_pattern=str(window_dir / "_tmp_%05d.jpg"),
    )
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed for {window_dir.name}: {proc.stderr.strip()}")

    written: List[Path] = []
    for index, source_frame in enumerate(source_frames):
        tmp = window_dir / f"_tmp_{index:05d}.jpg"
        if not tmp.exists():
            break
        final = window_dir / FRAME_FILE_FMT.format(source_frame)
        tmp.replace(final)
        written.append(final)
    for leftover in window_dir.glob("_tmp_*.jpg"):
        leftover.unlink()
    return written


# ----------------------------------------------------------------------
# Manifest
# ----------------------------------------------------------------------


def build_manifest(
    *,
    report_id: str,
    source: Path,
    source_info: dict,
    config: dict,
    sample_fps: int,
    step: int,
    window_records: List[dict],
) -> dict:
    piste = config["piste"]
    return {
        "version": MANIFEST_VERSION,
        "report_id": report_id,
        "source_video": str(source),
        "source_fps": source_info["fps"],
        "source_resolution": [source_info["width"], source_info["height"]],
        "work_fps": config.get("work_fps"),
        "work_scale_width": piste.get("scale_width"),
        "piste_crop": piste["crop"],
        "work_to_source_scale": work_to_source_scale(piste["crop"], piste["scale_width"]),
        "sample_fps": sample_fps,
        "sampling_step": step,
        "touch_lead_sec": TOUCH_LEAD_SEC,
        "touch_tail_sec": TOUCH_TAIL_SEC,
        "windows": window_records,
    }


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract 4K frame windows around touches and parries for blade labelling.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--report", required=True, type=Path, help="continuous report JSON")
    parser.add_argument("--config", required=True, type=Path, help="piste config JSON")
    parser.add_argument("--source", required=True, type=Path, help="4K original video")
    parser.add_argument("--out", required=True, type=Path, help="output directory")
    parser.add_argument(
        "--keypoints", type=Path, default=None,
        help="keypoint sidecar (default: <report dir>/keypoints/<report name>)",
    )
    parser.add_argument(
        "--sample-fps", type=int, default=DEFAULT_SAMPLE_FPS,
        help=f"frames per second to extract; must divide the source fps (default {DEFAULT_SAMPLE_FPS})",
    )
    parser.add_argument("--margin-x", type=int, default=MARGIN_X_PX, help="crop padding left/right, 4K px")
    parser.add_argument("--margin-top", type=int, default=MARGIN_TOP_PX, help="crop padding above, 4K px")
    parser.add_argument("--margin-bottom", type=int, default=MARGIN_BOTTOM_PX, help="crop padding below, 4K px")
    parser.add_argument("--limit", type=int, default=None, help="stop after N windows (smoke tests)")
    parser.add_argument("--dry-run", action="store_true", help="plan windows and print stats, extract nothing")
    return parser.parse_args(argv)


def default_keypoints_path(report_path: Path) -> Path:
    return report_path.parent / "keypoints" / report_path.name


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        print("ffmpeg/ffprobe not found on PATH", file=sys.stderr)
        return 2
    for path in (args.report, args.config, args.source):
        if not path.exists():
            print(f"missing input: {path}", file=sys.stderr)
            return 2

    report = json.loads(args.report.read_text(encoding="utf-8"))
    config = json.loads(args.config.read_text(encoding="utf-8"))
    keypoints_path = args.keypoints or default_keypoints_path(args.report)
    sidecar = json.loads(keypoints_path.read_text(encoding="utf-8")) if keypoints_path.exists() else {}
    if not sidecar:
        print(f"WARNING: no keypoint sidecar at {keypoints_path} — every crop falls back to the piste band")

    work_fps = float(config.get("work_fps") or report.get("meta", {}).get("fps") or 30.0)
    piste = config["piste"]
    source_info = probe_source(args.source)
    step = sampling_step(source_info["fps"], args.sample_fps)

    windows = merge_windows(
        touch_windows(report.get("touches", []), work_fps)
        + parry_windows(report.get("exchanges", []), work_fps)
    )
    if args.limit:
        windows = windows[: args.limit]

    print(f"  Report:      {args.report}")
    print(f"  Source:      {args.source}")
    print(f"  Source:      {source_info['width']}x{source_info['height']} @ {source_info['fps']:g}fps "
          f"({source_info['nb_frames']} frames)")
    print(f"  Work fps:    {work_fps:g}  scale_width={piste['scale_width']}  "
          f"scale={work_to_source_scale(piste['crop'], piste['scale_width']):g}x")
    print(f"  Sample fps:  {args.sample_fps} (every {step} source frames)")
    print(f"  Windows:     {len(windows)} merged, "
          f"{sum(w.end_sec - w.start_sec for w in windows):.1f}s total")

    args.out.mkdir(parents=True, exist_ok=True)
    fallback = piste_fallback_box(piste["crop"], (source_info["width"], source_info["height"]))

    records: List[dict] = []
    total_frames = 0
    for index, window in enumerate(windows, start=1):
        window_id = WINDOW_DIR_FMT.format(index)
        start_work = int(math.floor(window.start_sec * work_fps))
        end_work = int(math.ceil(window.end_sec * work_fps))
        points = keypoints_in_window(sidecar, start_work, end_work) if sidecar else []
        crop = crop_box_for_points(
            points, piste["crop"], piste["scale_width"],
            (source_info["width"], source_info["height"]),
            margin_x=args.margin_x, margin_top=args.margin_top, margin_bottom=args.margin_bottom,
        )
        crop_source = "keypoints"
        if crop is None:
            crop = fallback
            crop_source = "piste_fallback"

        source_frames = window_source_frames(
            window, source_info["fps"], args.sample_fps, source_info["nb_frames"]
        )
        if not source_frames:
            print(f"  {window_id}: empty after clamping, skipped")
            continue

        record = {
            "window_id": window_id,
            "reasons": window.reasons,
            "start_sec": round(window.start_sec, 4),
            "end_sec": round(window.end_sec, 4),
            "start_work_frame": start_work,
            "end_work_frame": end_work,
            "crop": crop,
            "crop_source": crop_source,
            "keypoint_samples": len(points),
            "frames": [],
        }

        if args.dry_run:
            record["frames"] = [
                {
                    "file": FRAME_FILE_FMT.format(f),
                    "source_frame": f,
                    "work_frame": int(round(f / source_info["fps"] * work_fps)),
                    "time_sec": round(f / source_info["fps"], 4),
                }
                for f in source_frames
            ]
        else:
            written = extract_window(
                args.source, args.out / window_id, source_frames, step, crop, source_info["fps"]
            )
            if len(written) != len(source_frames):
                print(f"  {window_id}: WARNING ffmpeg produced {len(written)}/{len(source_frames)} frames")
            for path, source_frame in zip(written, source_frames):
                record["frames"].append({
                    "file": path.name,
                    "source_frame": source_frame,
                    "work_frame": int(round(source_frame / source_info["fps"] * work_fps)),
                    "time_sec": round(source_frame / source_info["fps"], 4),
                })

        total_frames += len(record["frames"])
        records.append(record)
        print(f"  {window_id}: {window.start_sec:7.2f}-{window.end_sec:7.2f}s  "
              f"{len(record['frames']):4d} frames  crop {crop['w']}x{crop['h']}+{crop['x']}+{crop['y']} "
              f"({crop_source})  {','.join(window.reasons)}")

    manifest = build_manifest(
        report_id=args.report.stem,
        source=args.source,
        source_info=source_info,
        config=config,
        sample_fps=args.sample_fps,
        step=step,
        window_records=records,
    )
    manifest_path = args.out / MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    disk = sum(p.stat().st_size for p in args.out.rglob("*.jpg"))
    print(f"\n  Windows:     {len(records)}")
    print(f"  Frames:      {total_frames}")
    print(f"  Disk:        {disk / (1024 ** 2):.1f} MB")
    print(f"  Manifest:    {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
