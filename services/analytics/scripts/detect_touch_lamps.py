#!/usr/bin/env python3
"""Read the scoring-box lamps for every touch of a foil bout report.

Foil is the only weapon where the lamp pattern carries priority information: a
*double* lamp means both fencers landed a valid hit and the referee had to award
the point to the priority holder, while a single colour lamp means only one hit
was valid and no priority ruling was ever made. That distinction is what makes
the lamps worth reading at all, so this script refuses non-foil reports unless
``--force`` is given.

Usage:
    cd services/analytics
    PYTHONPATH=. .venv/bin/python3 scripts/detect_touch_lamps.py \\
        --report data/reports/<id>_continuous_report.json \\
        --video  data/raw/<id>.mp4 \\
        --labels-csv data/labels_priority_<id>.csv

    # inspect without writing anything
    PYTHONPATH=. .venv/bin/python3 scripts/detect_touch_lamps.py \\
        --report ... --video ... --dry-run

The video is *not* decoded end to end. Only the frames around each touch can
possibly hold that touch's lamp event, so the scan visits
``[frame - LAMP_SEARCH_LOOKBACK, frame + LAMP_SEARCH_FORWARD]`` per touch,
merging the windows of touches that fall close together into one sequential
pass (one seek, then sequential decode — per-frame seeking is far slower).
"""

import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from analyzer.config import (
    LAMP_SAMPLE_STEP,
    LAMP_SEARCH_FORWARD,
    LAMP_SEARCH_LOOKBACK,
)
from analyzer.touch_matching import annotate_touch_lamps, lamp_scorer_conflict
from analyzer.tv_overlay_ocr import LampBarReader

FOIL = "foil"

#: Exact header of the priority label CSV, as fixed by the priority design doc.
LABEL_CSV_HEADER = [
    "touch_number",
    "exchange_number",
    "priority_attacker",
    "lamp",
    "confidence",
    "note",
]

#: Notes are prefixed so that "needs human review" stays machine-detectable
#: without widening the six-column format the design doc fixed.
NOTE_AUTO_PREFIX = "자동 입력:"
NOTE_REVIEW_PREFIX = "검토 필요:"

_NOTE_DOUBLE = (
    f"{NOTE_AUTO_PREFIX} 양측 램프(double) — 두 유효타가 모두 성립해 심판이 우선권을 "
    "판정했고, 그 결과가 득점이므로 득점자를 우선권자로 자동 기록"
)
_NOTE_SINGLE = (
    f"{NOTE_REVIEW_PREFIX} 단독 램프({{pattern}}) — 유효타가 한쪽만 성립해 우선권 판정 "
    "자체가 없었음. 우선권 정답이 존재하지 않으므로 사람이 프레이즈를 보고 판단"
)
_NOTE_WHITE = (
    f"{NOTE_REVIEW_PREFIX} 백색 램프만 판독 — 유효타가 없어 득점이 설명되지 않음. "
    "램프-터치 매칭을 사람이 재확인"
)
_NOTE_UNREAD = (
    f"{NOTE_REVIEW_PREFIX} 램프 미판독 — 해당 구간에서 유효 램프 이벤트를 찾지 못함. "
    "사람이 영상으로 확인"
)
_NOTE_CONFLICT = (
    f"{NOTE_REVIEW_PREFIX} 단독 램프({{pattern}})가 득점자({{scorer}})와 모순 — "
    "램프 판독과 점수 OCR 중 하나가 오독. 사람이 영상으로 확인"
)

#: Every pattern the reader can produce, plus the "nothing read" bucket, so the
#: printed summary always shows a zero rather than silently omitting a category.
PATTERN_ORDER = ("double", "single_left", "single_right", "white", "unread")


# ------------------------------------------------------------------
# Scan windows
# ------------------------------------------------------------------


def touch_window(
    frame: int,
    lookback: int = LAMP_SEARCH_LOOKBACK,
    forward: int = LAMP_SEARCH_FORWARD,
) -> Tuple[int, int]:
    """Frame range that can hold the lamp event for a touch at ``frame``.

    Mirrors the acceptance window of
    :meth:`LampBarReader.read_touch_lamp` — scanning wider would only produce
    events the matcher then discards.
    """
    return (max(0, int(frame) - lookback), int(frame) + forward)


def merge_windows(windows: Sequence[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """Collapse overlapping windows so each frame is decoded at most once.

    Consecutive touches often sit closer together than the 11-second lookback,
    so their windows overlap heavily; scanning them separately would decode the
    same frames repeatedly and — worse — could split one lamp event across two
    scans.
    """
    ordered = sorted((int(a), int(b)) for a, b in windows)
    merged: List[Tuple[int, int]] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            prev_start, prev_end = merged[-1]
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def scan_windows(
    reader: LampBarReader,
    video_path,
    windows: Sequence[Tuple[int, int]],
    step: int = LAMP_SAMPLE_STEP,
) -> list:
    """Scan each merged window once and return all lamp events, ordered."""
    events: list = []
    for start, end in windows:
        events.extend(reader.scan_video_events(video_path, start, end, step))
    events.sort(key=lambda e: e.start_frame)
    return events


def read_touch_readings(
    reader: LampBarReader,
    events: list,
    touch_frames: Sequence[int],
) -> list:
    """Attribute one lamp event per touch, in touch order.

    ``previous_end`` is chained forward so a touch can never be explained by the
    lamp event that already produced an earlier touch — without the chain, two
    touches close together both match the same (later, brighter) event.

    A touch that reads nothing leaves the chain where it was: the last *matched*
    event is still the boundary the next touch must clear.
    """
    readings = []
    previous_end: Optional[int] = None
    for frame in touch_frames:
        reading = reader.read_touch_lamp(events, int(frame), previous_end=previous_end)
        readings.append(reading)
        if reading is not None and reading.end_frame is not None:
            previous_end = reading.end_frame
    return readings


# ------------------------------------------------------------------
# JSON round-trip style
# ------------------------------------------------------------------


@dataclass
class JsonStyle:
    """How an existing JSON file is formatted, so a rewrite can match it.

    These reports are served to a live UI and read by humans in diffs; a rewrite
    that reflows every line or escapes every Korean string would be an unrelated
    change smuggled into a lamp annotation.
    """

    indent: Optional[int] = 2
    ensure_ascii: bool = False
    trailing_newline: bool = False


def detect_json_style(text: str) -> JsonStyle:
    """Infer indent / ensure_ascii / trailing newline from a JSON document."""
    lines = text.splitlines()

    indent: Optional[int] = None
    for line in lines[1:]:
        stripped = line.lstrip(" ")
        if stripped:
            width = len(line) - len(stripped)
            if width:
                indent = width
            break

    # Any literal non-ASCII byte proves the writer did not escape. A file that
    # is pure ASCII *and* carries \uXXXX escapes proves it did. Otherwise the
    # two settings are indistinguishable from the file alone, so follow this
    # project's convention (generate_continuous_report writes ensure_ascii=False).
    if any(ord(ch) > 127 for ch in text):
        ensure_ascii = False
    elif "\\u" in text:
        ensure_ascii = True
    else:
        ensure_ascii = False

    return JsonStyle(
        indent=indent,
        ensure_ascii=ensure_ascii,
        trailing_newline=text.endswith("\n"),
    )


def dumps_json(data, style: JsonStyle) -> str:
    """Serialise ``data`` in ``style``, preserving key order as given."""
    text = json.dumps(data, indent=style.indent, ensure_ascii=style.ensure_ascii)
    if style.trailing_newline:
        text += "\n"
    return text


# ------------------------------------------------------------------
# Reporting helpers
# ------------------------------------------------------------------


def lamp_scorer_consistency(
    pattern: Optional[str],
    scorer: Optional[str],
) -> Optional[bool]:
    """Whether the lamp pattern can coexist with the OCR scorer.

    ``None`` when there is nothing to check (no pattern, a white-only reading,
    or no scorer). A ``double`` is always consistent — either side may hold
    priority — while a single colour lamp pins the scorer to that side.
    """
    if pattern is None or pattern == "white":
        return None
    if scorer not in ("left", "right"):
        return None
    return not lamp_scorer_conflict(pattern, scorer)


def pattern_counts(readings: Sequence) -> dict:
    """Count readings per pattern, with unread folded in as its own bucket."""
    counts = {key: 0 for key in PATTERN_ORDER}
    for reading in readings:
        pattern = getattr(reading, "pattern", None) if reading is not None else None
        counts[pattern if pattern in counts else "unread"] += 1
    return counts


def format_touch_table(touches: Sequence[dict], readings: Sequence) -> str:
    """Render the per-touch result table printed to stdout."""
    header = (
        f"{'#':>3}  {'scorer':<6}  {'lamp':<13}  {'conf':>6}  "
        f"{'lamp_start':>10}  {'lead':>6}  {'consistent':<10}"
    )
    rows = [header, "-" * len(header)]

    for touch, reading in zip(touches, readings):
        pattern = getattr(reading, "pattern", None) if reading is not None else None
        confidence = getattr(reading, "confidence", 0.0) if reading is not None else 0.0
        start = getattr(reading, "start_frame", None) if reading is not None else None
        frame = touch.get("frame")
        lead = frame - start if frame is not None and start is not None else None
        consistent = lamp_scorer_consistency(pattern, touch.get("scorer"))

        rows.append(
            f"{touch.get('touch_number', '?'):>3}  "
            f"{str(touch.get('scorer') or '-'):<6}  "
            f"{pattern or '-':<13}  "
            f"{confidence:>6.3f}  "
            f"{'-' if start is None else start:>10}  "
            f"{'-' if lead is None else lead:>6}  "
            f"{'-' if consistent is None else ('yes' if consistent else 'NO'):<10}"
        )

    return "\n".join(rows)


# ------------------------------------------------------------------
# Priority label CSV
# ------------------------------------------------------------------


def build_label_row(touch: dict, reading) -> dict:
    """One priority-label row for a touch.

    ``priority_attacker`` is auto-filled *only* for a double lamp. Both hits
    landed, so the referee necessarily made a priority ruling and expressed it by
    awarding the point — the scorer is therefore the referee's own answer, and
    the referee's call is the ground truth this dataset is calibrated against.

    A single colour lamp is left blank on purpose: only one hit was valid, so no
    priority ruling was made and there is no ground truth to record. Filling in
    the scorer there would fabricate labels for phrases the referee never judged.
    """
    pattern = getattr(reading, "pattern", None) if reading is not None else None
    confidence = getattr(reading, "confidence", 0.0) if reading is not None else 0.0
    scorer = touch.get("scorer")
    exchange = touch.get("matched_exchange_number")

    if pattern == "double":
        priority = scorer or ""
        note = _NOTE_DOUBLE
    elif pattern in ("single_left", "single_right"):
        priority = ""
        if lamp_scorer_conflict(pattern, scorer):
            note = _NOTE_CONFLICT.format(pattern=pattern, scorer=scorer)
        else:
            note = _NOTE_SINGLE.format(pattern=pattern)
    elif pattern == "white":
        priority = ""
        note = _NOTE_WHITE
    else:
        priority = ""
        note = _NOTE_UNREAD

    return {
        "touch_number": touch.get("touch_number", ""),
        "exchange_number": "" if exchange is None else exchange,
        "priority_attacker": priority,
        "lamp": pattern or "",
        "confidence": f"{float(confidence):.3f}",
        "note": note,
    }


def build_label_rows(touches: Sequence[dict], readings: Sequence) -> List[dict]:
    """Priority-label rows for every touch, in order."""
    return [build_label_row(t, r) for t, r in zip(touches, readings)]


def row_needs_review(row: dict) -> bool:
    """Whether a label row still needs a human decision."""
    return str(row.get("note", "")).startswith(NOTE_REVIEW_PREFIX)


def write_label_csv(path, rows: Sequence[dict]) -> None:
    """Write the six-column priority label CSV."""
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LABEL_CSV_HEADER)
        writer.writeheader()
        writer.writerows(rows)


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Detect foil scoring-box lamps for the touches of a report.",
    )
    parser.add_argument("--report", required=True, help="continuous report JSON")
    parser.add_argument("--video", required=True, help="source bout video")
    parser.add_argument("--labels-csv", default=None, help="priority label CSV output")
    parser.add_argument(
        "--step",
        type=int,
        default=LAMP_SAMPLE_STEP,
        help=f"frame sampling step inside a window (default {LAMP_SAMPLE_STEP})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print results without writing the report or the CSV",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="run even when the report's weapon is not foil",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    report_path = Path(args.report)
    video_path = Path(args.video)

    if not report_path.exists():
        print(f"ERROR: report not found: {report_path}", file=sys.stderr)
        return 1
    if not video_path.exists():
        print(f"ERROR: video not found: {video_path}", file=sys.stderr)
        return 1

    raw = report_path.read_text(encoding="utf-8")
    style = detect_json_style(raw)
    report = json.loads(raw)

    weapon = (report.get("summary") or {}).get("weapon")
    if weapon != FOIL and not args.force:
        print(
            f"ERROR: report weapon is {weapon!r}, not 'foil'. Lamp priority "
            "semantics are foil-specific — a double lamp only implies a priority "
            "ruling in foil (and sabre uses a different overlay), so reading "
            "these lamps as priority evidence would be wrong. Pass --force to "
            "override.",
            file=sys.stderr,
        )
        return 2

    touches = report.get("touches") or []
    if not touches:
        print(f"ERROR: report has no touches: {report_path}", file=sys.stderr)
        return 1

    touch_frames = [t.get("frame") for t in touches]
    if any(f is None for f in touch_frames):
        print("ERROR: every touch must have a 'frame'", file=sys.stderr)
        return 1

    windows = merge_windows([touch_window(f) for f in touch_frames])
    total_frames = sum(end - start + 1 for start, end in windows)
    print(
        f"Scanning {len(windows)} merged window(s) "
        f"({total_frames} frames, step {args.step}) for {len(touches)} touches..."
    )

    reader = LampBarReader()
    scan_started = time.time()
    events = scan_windows(reader, video_path, windows, step=args.step)
    scan_seconds = time.time() - scan_started
    print(f"  {len(events)} lamp event(s) in {scan_seconds:.1f}s")

    readings = read_touch_readings(reader, events, touch_frames)
    annotate_touch_lamps(touches, readings)

    print()
    print(format_touch_table(touches, readings))
    print()

    counts = pattern_counts(readings)
    read = len(touches) - counts["unread"]
    rate = read / len(touches) * 100 if touches else 0.0
    print(f"Read rate: {read}/{len(touches)} patterns ({rate:.1f}%)")
    print("  " + ", ".join(f"{key} {counts[key]}" for key in PATTERN_ORDER))

    inconsistent = [
        t.get("touch_number")
        for t, r in zip(touches, readings)
        if lamp_scorer_consistency(
            getattr(r, "pattern", None) if r is not None else None, t.get("scorer"),
        ) is False
    ]
    if inconsistent:
        print(f"  lamp/scorer conflicts: touches {inconsistent}")
    else:
        print("  lamp/scorer conflicts: none")

    rows = build_label_rows(touches, readings)
    review = sum(1 for row in rows if row_needs_review(row))
    auto = len(rows) - review

    if args.dry_run:
        print(f"\n[dry-run] report not written: {report_path}")
        if args.labels_csv:
            print(f"[dry-run] labels not written: {args.labels_csv}")
    else:
        report_path.write_text(dumps_json(report, style), encoding="utf-8")
        print(f"\nReport updated: {report_path}")
        if args.labels_csv:
            write_label_csv(Path(args.labels_csv), rows)
            print(f"Labels written: {args.labels_csv}")

    print(f"Labels: {auto} auto-filled, {review} need human review")
    return 0


if __name__ == "__main__":
    sys.exit(main())
