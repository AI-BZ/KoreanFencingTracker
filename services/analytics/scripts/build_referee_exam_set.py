#!/usr/bin/env python3
"""Cut an FIE referee video exam into one clip per question.

The exam videos share a fixed shape: a dark title slate carrying nothing but a
centred white question number, then a broadcast clip of a single phrase, then
the next slate. Segmenting it is therefore a matter of finding the slates, and
what makes a slate recognisable is not "the frame is black" — these slates are
``#212121``, brighter than plenty of real broadcast frames — but the *pair* of
properties that the frame is uniformly dark **and** its only bright pixels sit
in a small patch near the centre.

That second half matters. The closing card of the same video ("Answers are in
the description below") is exactly as dark as a question slate and would be
counted as a sixteenth question by a brightness rule alone; its text spans most
of the frame width, so the ink-span test rejects it. It is still detected as a
*slate*, which is what stops the last clip from running on into the outro.

Usage:
    cd services/analytics
    PYTHONPATH=. .venv/bin/python3 scripts/build_referee_exam_set.py \\
        --video /path/to/ref_exam_p2.mp4 \\
        --answers /path/to/ref_exam_p2_answers.json \\
        --prefix p2

Output (all under ``--out-dir``, which is gitignored — these clips are
third-party broadcast footage and must never be committed or served):

    p2_q01.mp4 ... p2_q15.mp4
    p2_manifest.json
"""

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

# Frames are reduced to this size before any statistic is taken. The tests build
# synthetic frames at full size and get the same answers, because every
# threshold below is a *fraction* rather than a pixel count.
ANALYSIS_WIDTH = 160
ANALYSIS_HEIGHT = 90

#: Grey level at or above which a pixel counts as slate ink.
INK_LEVEL = 200

#: Mean grey below which a frame is a candidate slate. Measured: the exam's
#: slates sit at 31.2-31.5 and the darkest broadcast frame at 46.9, so the
#: threshold has room on both sides without being tuned to either.
SLATE_MAX_MEAN = 45.0

#: Ink fraction bounds for a *question number*. Below the floor the frame is a
#: blank slate with no number on it (fade frames); above the ceiling it carries
#: a paragraph rather than a digit. Measured: numbers 1-15 occupy 0.0005-0.0019,
#: the outro card 0.026.
CARD_MIN_INK_FRACTION = 1e-4
CARD_MAX_INK_FRACTION = 0.010

#: Largest share of the frame the ink bounding box may span in either axis. The
#: two-digit numbers reach 0.08; the outro's wrapped sentence reaches 0.60.
CARD_MAX_INK_SPAN = 0.25

#: How far the ink centroid may sit from the frame centre, as a fraction of the
#: frame. Question numbers are centred by construction; this rejects a dark
#: broadcast frame that happens to carry a bright corner graphic.
CARD_MAX_CENTRE_OFFSET = 0.20

#: Shortest run of slate frames that counts as a real slate rather than a
#: single dark frame inside a clip. The exam's slates run 82-83 frames.
MIN_SLATE_RUN_FRAMES = 10

#: How many questions an exam part is expected to contain.
EXPECTED_QUESTIONS = 15


@dataclass(frozen=True)
class SlateMetrics:
    """The six numbers that decide whether one frame is a slate or a card.

    All are resolution-independent fractions except ``mean``, which is a grey
    level, so the same thresholds apply to any frame size.
    """

    mean: float
    ink_fraction: float
    ink_span_x: float
    ink_span_y: float
    centre_offset_x: float
    centre_offset_y: float


def slate_metrics(frame: np.ndarray) -> SlateMetrics:
    """Reduce one frame (BGR or grey) to its :class:`SlateMetrics`.

    An all-dark frame with no ink at all yields zero spans and zero offsets
    rather than raising: it is a legitimate slate, just not a numbered one.
    """
    if frame.ndim == 3:
        grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    else:
        grey = frame
    small = cv2.resize(grey, (ANALYSIS_WIDTH, ANALYSIS_HEIGHT))

    ink = small >= INK_LEVEL
    count = int(ink.sum())
    total = small.size
    if count == 0:
        return SlateMetrics(float(small.mean()), 0.0, 0.0, 0.0, 0.0, 0.0)

    ys, xs = np.nonzero(ink)
    height, width = small.shape
    span_x = (xs.max() - xs.min() + 1) / width
    span_y = (ys.max() - ys.min() + 1) / height
    offset_x = abs(float(xs.mean()) / width - 0.5)
    offset_y = abs(float(ys.mean()) / height - 0.5)
    return SlateMetrics(
        mean=float(small.mean()),
        ink_fraction=count / total,
        ink_span_x=float(span_x),
        ink_span_y=float(span_y),
        centre_offset_x=offset_x,
        centre_offset_y=offset_y,
    )


def is_slate(metrics: SlateMetrics, max_mean: float = SLATE_MAX_MEAN) -> bool:
    """True for any uniformly dark title frame, numbered or not."""
    return metrics.mean < max_mean


def is_number_card(
    metrics: SlateMetrics,
    max_mean: float = SLATE_MAX_MEAN,
    min_ink: float = CARD_MIN_INK_FRACTION,
    max_ink: float = CARD_MAX_INK_FRACTION,
    max_span: float = CARD_MAX_INK_SPAN,
    max_offset: float = CARD_MAX_CENTRE_OFFSET,
) -> bool:
    """True only for a dark slate carrying a small, centred number."""
    if not is_slate(metrics, max_mean):
        return False
    if not (min_ink <= metrics.ink_fraction <= max_ink):
        return False
    if metrics.ink_span_x > max_span or metrics.ink_span_y > max_span:
        return False
    if metrics.centre_offset_x > max_offset or metrics.centre_offset_y > max_offset:
        return False
    return True


def find_runs(flags: Sequence[bool], min_length: int = 1) -> List[Tuple[int, int]]:
    """Inclusive ``(start, end)`` spans of consecutive true values.

    Runs shorter than ``min_length`` are dropped, which is how a single dark
    frame inside a broadcast clip stops being mistaken for a title slate.
    """
    runs: List[Tuple[int, int]] = []
    start: Optional[int] = None
    for i, flag in enumerate(flags):
        if flag:
            if start is None:
                start = i
        elif start is not None:
            if i - start >= min_length:
                runs.append((start, i - 1))
            start = None
    if start is not None and len(flags) - start >= min_length:
        runs.append((start, len(flags) - 1))
    return runs


def clip_spans(
    card_runs: Sequence[Tuple[int, int]],
    slate_runs: Sequence[Tuple[int, int]],
    total_frames: int,
) -> List[Tuple[int, int]]:
    """Inclusive frame spans of the clip that follows each numbered card.

    A clip ends where the next *slate* begins, not where the next *card* begins.
    The distinction is what keeps the trailing "answers are in the description"
    outro out of question 15 — it is a slate but not a card, so it terminates
    the clip without claiming to be question 16.
    """
    spans: List[Tuple[int, int]] = []
    starts = sorted(start for start, _ in slate_runs)
    for _, card_end in card_runs:
        clip_start = card_end + 1
        following = [s for s in starts if s > card_end]
        clip_end = (following[0] - 1) if following else (total_frames - 1)
        spans.append((clip_start, clip_end))
    return spans


def scan_video(video_path: Path) -> Tuple[List[SlateMetrics], float, int]:
    """Per-frame metrics for the whole video, plus fps and frame count."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise SystemExit(f"ERROR: cannot open video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    metrics: List[SlateMetrics] = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        metrics.append(slate_metrics(frame))
    cap.release()
    return metrics, float(fps), len(metrics)


def cut_clip(
    video_path: Path,
    out_path: Path,
    start_sec: float,
    end_sec: float,
    crf: int = 20,
) -> None:
    """Re-encode ``[start_sec, end_sec)`` into ``out_path``.

    Output-side seeking (``-ss`` after ``-i``) is deliberate: it decodes from
    the start of the file and cuts on the exact frame asked for, where
    input-side seeking would snap to the nearest keyframe and drag a slice of
    the neighbouring slate into the clip. The exam is two minutes long, so the
    cost of decoding from zero is irrelevant next to getting the boundary right.
    """
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(video_path),
        "-ss", f"{start_sec:.4f}",
        "-to", f"{end_sec:.4f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-an",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            f"ERROR: ffmpeg failed for {out_path.name}\n{result.stderr.strip()}"
        )


def build_manifest(
    video_path: Path,
    prefix: str,
    fps: float,
    total_frames: int,
    card_runs: Sequence[Tuple[int, int]],
    spans: Sequence[Tuple[int, int]],
    answers: dict,
) -> dict:
    """The manifest that the evaluator reads instead of re-deriving boundaries."""
    questions = []
    for i, ((card_start, card_end), (start, end)) in enumerate(
        zip(card_runs, spans), start=1
    ):
        questions.append({
            "question": i,
            "clip": f"{prefix}_q{i:02d}.mp4",
            "card_start_frame": card_start,
            "card_end_frame": card_end,
            "start_frame": start,
            "end_frame": end,
            "start_sec": round(start / fps, 4),
            # Half a frame past the last frame we want. ``ffmpeg -to`` keeps
            # every frame whose timestamp is at or below the bound, so asking
            # for (end + 1)/fps hands back one extra frame — which here is the
            # first frame of the *next* title slate, a black frame glued to the
            # end of every clip. Measured: q01 came back 188 frames with a
            # slate at the end instead of 187.
            "end_sec": round((end + 0.5) / fps, 4),
            "duration_sec": round((end - start + 1) / fps, 3),
            "answer": answers.get("answers", {}).get(str(i)),
        })
    return {
        "source_video": video_path.name,
        "source": answers.get("source"),
        "provided_by": answers.get("provided_by"),
        "weapon": answers.get("weapon", "foil"),
        "fps": fps,
        "total_frames": total_frames,
        "question_count": len(questions),
        "questions": questions,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--video", required=True, help="Exam video file")
    parser.add_argument(
        "--answers", required=True,
        help="JSON with {'answers': {'1': 'left', ...}} — merged into the manifest",
    )
    parser.add_argument("--prefix", default="p2", help="Clip filename prefix")
    parser.add_argument(
        "--out-dir", default="data/ref_exam",
        help="Output directory (gitignored: the clips are third-party footage)",
    )
    parser.add_argument(
        "--expect", type=int, default=EXPECTED_QUESTIONS,
        help="Number of question cards this exam must contain",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Detect and report boundaries without writing clips",
    )
    args = parser.parse_args(argv)

    video_path = Path(args.video)
    if not video_path.exists():
        print(f"ERROR: video not found: {video_path}", file=sys.stderr)
        return 1
    answers_path = Path(args.answers)
    if not answers_path.exists():
        print(f"ERROR: answers not found: {answers_path}", file=sys.stderr)
        return 1
    answers = json.loads(answers_path.read_text(encoding="utf-8"))

    print(f"Scanning {video_path.name} ...")
    metrics, fps, total_frames = scan_video(video_path)
    print(f"  {total_frames} frames @ {fps:.2f}fps")

    slate_runs = find_runs([is_slate(m) for m in metrics], MIN_SLATE_RUN_FRAMES)
    card_runs = find_runs(
        [is_number_card(m) for m in metrics], MIN_SLATE_RUN_FRAMES,
    )
    print(f"  slate runs: {len(slate_runs)}   numbered cards: {len(card_runs)}")

    if len(card_runs) != args.expect:
        print(
            f"\nERROR: expected {args.expect} numbered cards, detected "
            f"{len(card_runs)}. Detected card runs (frame ranges):",
            file=sys.stderr,
        )
        for start, end in card_runs:
            print(
                f"  {start}-{end}  ({start / fps:.2f}s-{end / fps:.2f}s)",
                file=sys.stderr,
            )
        print(
            "Segmentation aborted — question numbers are assigned by order, so "
            "a wrong card count would mislabel every clip.",
            file=sys.stderr,
        )
        return 2

    spans = clip_spans(card_runs, slate_runs, total_frames)
    manifest = build_manifest(
        video_path, args.prefix, fps, total_frames, card_runs, spans, answers,
    )

    print("\n  Q  clip frames        seconds            dur    answer")
    for q in manifest["questions"]:
        print(
            f"  {q['question']:>2}  {q['start_frame']:>5}-{q['end_frame']:<5}  "
            f"{q['start_sec']:>7.2f}-{q['end_sec']:<7.2f}  "
            f"{q['duration_sec']:>5.2f}s  {q['answer']}"
        )

    missing = [q["question"] for q in manifest["questions"] if not q["answer"]]
    if missing:
        print(f"\n  WARNING: no answer supplied for question(s) {missing}")

    if args.dry_run:
        print("\n--dry-run: no clips written.")
        return 0

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print()
    for q in manifest["questions"]:
        out_path = out_dir / q["clip"]
        cut_clip(video_path, out_path, q["start_sec"], q["end_sec"])
        size_kb = out_path.stat().st_size / 1024
        print(f"  wrote {out_path}  ({size_kb:.0f}KB)")

    manifest_path = out_dir / f"{args.prefix}_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    print(f"\n  wrote {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
