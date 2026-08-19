#!/usr/bin/env python3
"""Read a physical LED scoreboard and write the OCR report the merge picks up.

Step 2 of the piste-selection pipeline. ``prepare_piste_video.py`` has already
produced two work files from one source video (a piste crop and a scoreboard
crop, both at 30 fps) plus a config JSON holding the five scoreboard ROIs in
*scoreboard-crop* coordinates. This script runs the v3 headless detector
(``LampDetector`` + ``ScoreReader`` + ``VideoProcessor``) over the scoreboard
work file and converts the resulting ``MatchEvent``s into
``<piste stem>_report.json``.

Usage:
    cd services/analytics
    PYTHONPATH=. .venv/bin/python3 scripts/analyze_led_scoreboard.py \\
        --config data/piste_configs/<stem>_piste3.json --weapon foil

    # inspect the detected events without writing anything
    PYTHONPATH=. .venv/bin/python3 scripts/analyze_led_scoreboard.py \\
        --config ... --weapon foil --dry-run

Why the report is named after the PISTE work file, not the scoreboard one:
``generate_continuous_report.py`` analyses the piste work file and locates its
OCR report by ``find_ocr_report(video_path.stem, output_dir)``, whose first tier
matches a candidate whose base equals the analysed video's stem. Naming the
report ``<piste stem>_report.json`` therefore hits that exact tier. Naming it
after the scoreboard file (``<piste stem>_scoreboard``) would fall through to
the looser boundary/substring tiers, where an unrelated report in the same
directory could win.

Frame indices in the output are work-file frames at 30 fps, matching the piste
work file 1:1 and matching the 120 fps source not at all — see
``app/led_report_converter``.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

from app.led_report_converter import led_events_to_match_report

#: ``services/analytics/`` — config paths like ``data/work/foo.mp4`` are written
#: relative to it, and the CLI is documented as being run from there.
SERVICE_ROOT = Path(__file__).resolve().parent.parent

#: The five ROIs ``VideoProcessor.process_video_headless`` consumes. All are
#: required: a missing ``clock`` silently produces empty match times, and a
#: missing lamp or score ROI silently produces zero touches. Failing loudly
#: sends the user back to ``prepare_piste_video.py`` instead.
REQUIRED_ROI_KEYS = ("lamp_left", "lamp_right", "score_left", "score_right", "clock")

WEAPONS = ("foil", "epee", "sabre")


class ConfigError(ValueError):
    """The piste config is missing or malformed in a way the user must fix."""


# ------------------------------------------------------------------
# Config handling (importable — no argparse, no I/O beyond the read)
# ------------------------------------------------------------------


def load_piste_config(config_path) -> dict:
    """Read and JSON-parse a piste config, with actionable errors."""
    path = Path(config_path)
    if not path.exists():
        raise ConfigError(f"config not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"config is not valid JSON: {path} ({exc})") from exc


def resolve_work_file(raw_path: str, service_root: Path = SERVICE_ROOT) -> Path:
    """Resolve a ``work_files.*`` entry to a concrete path.

    Config paths are written relative to ``services/analytics/`` but the script
    may be invoked from elsewhere, so an absolute path is used as-is, and a
    relative one is tried against the current directory first and the service
    root second. When neither exists the service-root candidate is returned so
    the "not found" message names the path the config actually meant.
    """
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate
    if candidate.exists():
        return candidate.resolve()
    return (service_root / candidate).resolve()


def extract_scoreboard_video(config: dict, service_root: Path = SERVICE_ROOT) -> Path:
    """Path to the scoreboard work file named by ``work_files.scoreboard``."""
    work_files = config.get("work_files")
    if not isinstance(work_files, dict):
        raise ConfigError("config has no 'work_files' object")
    raw = work_files.get("scoreboard")
    if not raw:
        raise ConfigError("config has no 'work_files.scoreboard' entry")
    return resolve_work_file(raw, service_root)


def extract_report_stem(config: dict) -> str:
    """Report filename stem — the PISTE work file's stem (see module docstring)."""
    work_files = config.get("work_files")
    if not isinstance(work_files, dict):
        raise ConfigError("config has no 'work_files' object")
    raw = work_files.get("piste")
    if not raw:
        raise ConfigError("config has no 'work_files.piste' entry")
    return Path(raw).stem


def extract_rois(config: dict) -> Dict[str, Tuple[int, int, int, int]]:
    """Convert ``scoreboard.rois`` lists into the tuples the detector wants.

    Values are already in scoreboard-crop coordinates — the same coordinate
    system as the frames the detector will read — so no transform is applied.
    """
    scoreboard = config.get("scoreboard")
    if not isinstance(scoreboard, dict):
        raise ConfigError("config has no 'scoreboard' object")
    rois_raw = scoreboard.get("rois")
    if not isinstance(rois_raw, dict):
        raise ConfigError("config has no 'scoreboard.rois' object")

    missing = [k for k in REQUIRED_ROI_KEYS if k not in rois_raw]
    if missing:
        raise ConfigError(
            f"scoreboard.rois is missing required keys: {', '.join(missing)}. "
            "Re-run prepare_piste_video.py and select all five regions."
        )

    rois: Dict[str, Tuple[int, int, int, int]] = {}
    for key in REQUIRED_ROI_KEYS:
        value = rois_raw[key]
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            raise ConfigError(f"scoreboard.rois['{key}'] must be [x, y, w, h]")
        try:
            x, y, w, h = (int(v) for v in value)
        except (TypeError, ValueError) as exc:
            raise ConfigError(
                f"scoreboard.rois['{key}'] must contain four integers"
            ) from exc
        if w <= 0 or h <= 0:
            raise ConfigError(
                f"scoreboard.rois['{key}'] has non-positive size: w={w}, h={h}"
            )
        rois[key] = (x, y, w, h)
    return rois


# ------------------------------------------------------------------
# Presentation helpers (importable, pure)
# ------------------------------------------------------------------


def format_event_line(event) -> str:
    """One-line dump of a ``MatchEvent`` for ``--dry-run``."""
    lamps = []
    if getattr(event, "lamp_red", False):
        lamps.append("RED")
    if getattr(event, "lamp_green", False):
        lamps.append("GREEN")
    lamp_str = "+".join(lamps) if lamps else "-"
    return (
        f"  frame {getattr(event, 'frame', 0):>7}  "
        f"video {getattr(event, 'video_timestamp', ''):>9}  "
        f"clock {getattr(event, 'match_time', '') or '?':>6}  "
        f"lamp {lamp_str:<10} "
        f"{getattr(event, 'score_before', '') or '?'} -> "
        f"{(getattr(event, 'score_after', '') or '?'):<6} "
        f"scorer={getattr(event, 'scorer', None)}"
    )


def summary_lines(report: dict) -> List[str]:
    """Human-readable run summary from a converted report dict."""
    summary = report.get("summary", {})
    touches = report.get("touches", [])
    left = report.get("left_fencer", {}).get("total_touches_scored", 0)
    right = report.get("right_fencer", {}).get("total_touches_scored", 0)

    lines = [
        f"  Total touches: {len(touches)}",
        f"  Final score:   {summary.get('final_score')}",
        f"  Per side:      left {left}, right {right}",
    ]
    warnings = report.get("warnings", [])
    if warnings:
        lines.append(f"  Warnings:      {len(warnings)}")
        for w in warnings:
            lines.append(f"    [{w.get('severity')}] {w.get('type')}: {w.get('message')}")
    else:
        lines.append("  Warnings:      none")
    return lines


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read a physical LED scoreboard into an OCR report JSON.",
    )
    parser.add_argument(
        "--config", required=True,
        help="Piste config JSON written by prepare_piste_video.py",
    )
    parser.add_argument(
        "--weapon", required=True, choices=WEAPONS,
        help="Weapon. Required — the foil priority cascade is gated on it and "
             "an unrecognised value silently disables it.",
    )
    parser.add_argument(
        "--bout-type", default="pool", choices=("pool", "de"),
        help="Bout format (default: pool)",
    )
    parser.add_argument(
        "--output-dir", default="data/reports",
        help="Where to write <piste stem>_report.json (default: data/reports)",
    )
    parser.add_argument("--left-name", default=None, help="Left fencer name")
    parser.add_argument("--right-name", default=None, help="Right fencer name")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print detected events and the derived score; write nothing.",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    try:
        config = load_piste_config(args.config)
        video = extract_scoreboard_video(config)
        rois = extract_rois(config)
        stem = extract_report_stem(config)
    except ConfigError as exc:
        print(f"ERROR: {exc}")
        return 1

    if not video.exists():
        print(f"ERROR: scoreboard work file not found: {video}")
        print("       Run prepare_piste_video.py first.")
        return 1

    # Imported late: cv2/numpy pull in a heavy stack that the config-parsing
    # helpers above (and their tests) do not need.
    try:
        import cv2
    except ImportError:
        print("ERROR: opencv-python required.")
        return 1
    from analyzer.video_processor import VideoProcessor

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        print(f"ERROR: cannot open scoreboard video: {video}")
        return 1
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    print("LED scoreboard analysis")
    print(f"  Config:     {args.config}")
    print(f"  Scoreboard: {video}")
    print(f"  Frames:     {total_frames} @ {fps:.2f}fps")
    print(f"  ROIs:       {', '.join(f'{k}={v}' for k, v in rois.items())}")

    started = time.time()
    events = VideoProcessor().process_video_headless(str(video), rois)
    elapsed = time.time() - started
    print(f"  Detected {len(events)} lamp events in {elapsed:.1f}s")

    report = led_events_to_match_report(
        events,
        video_path=str(video),
        weapon=args.weapon,
        bout_type=args.bout_type,
        left_name=args.left_name,
        right_name=args.right_name,
        fps=fps,
        total_frames=total_frames,
        analysis_time_sec=elapsed,
    )

    if args.dry_run:
        print("\nAll MatchEvents (including non-scoring):")
        if not events:
            print("  (none)")
        for event in events:
            print(format_event_line(event))
        print("\nDerived:")
        for line in summary_lines(report):
            print(line)
        print("\n  --dry-run: nothing written.")
        return 0

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{stem}_report.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n  Saved: {output_path}")
    for line in summary_lines(report):
        print(line)
    print(
        f"\n  generate_continuous_report.py will auto-match this report when it "
        f"analyses a video whose stem is '{stem}'."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
