#!/usr/bin/env python3
"""Admin CLI: apply the end-of-bout rule to an ALREADY-GENERATED report.

``analyzer.scoreboard_tracker.infer_end_of_bout_touch`` recovers the last point
of a bout whose recording stopped before the scoreboard operator entered it. The
ordinary way to get that point into a report is to re-run
``scripts/analyze_led_scoreboard.py --tracked --clock-at-cut running`` and let
the merge rebuild everything.

This script exists for the reports where that is not an option — the ones
already published, already shared by token, already carrying hand-set fields —
because regenerating a continuous report is not a cheap idempotent operation.
It re-reads pose, it re-runs the exchange detector, and (see the service
CLAUDE.md) it silently drops the lamp readings a separate pass injected
afterwards. So this edits the report in place instead: one touch appended, four
fields adjusted, one warning swapped, nothing else looked at.

The scoreboard is still re-read. The rule needs ``TouchResolution``s and the
report does not contain any, so the tracked detector runs again over the
scoreboard work file named in the config — about 20 s for a 3-minute bout —
through the same :func:`~scripts.analyze_led_scoreboard.track_from_config` the
generating run used, so the resolutions this decides on are the ones the report
was built from.

    python3 scripts/apply_end_of_bout_touch.py <report_id> \\
        --config data/piste_configs/<stem>_piste3.json \\
        --bout-type pool --clock-at-cut running [--dry-run]

``--clock-at-cut`` has no ``unknown`` here, unlike the generating CLI: running
this at all is an assertion about the clock, and there is no point paying 20 s
of tracking to be told the rule cannot fire. It still refuses on every other
condition.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Import app/ and scripts/ regardless of cwd — an admin runs this from anywhere.
_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

from app.led_report_converter import (  # noqa: E402
    WARNING_LAMP_ANNULLED,
    WARNING_LAMP_UNDETERMINED,
    build_touches,
)
from app.sharing import resolve_report_path  # noqa: E402
from scripts.analyze_led_scoreboard import (  # noqa: E402
    CLOCK_AT_CUT_CHOICES,
    ConfigError,
    _clock,
    end_of_bout_event,
    extract_scoreboard_video,
    extract_tracker,
    load_piste_config,
    track_from_config,
    tracked_warnings,
)
from scripts.share_report import write_report  # noqa: E402

REPORTS_DIR = _SERVICE_ROOT / "data" / "reports"

EXIT_OK = 0
EXIT_NOT_FOUND = 2

#: Warning types the promoted event may already be reported under. Both say the
#: point could not be confirmed, which the inference has just contradicted.
SUPERSEDED_WARNING_TYPES = (WARNING_LAMP_UNDETERMINED, WARNING_LAMP_ANNULLED)


# ------------------------------------------------------------------
# Pure edits (importable, no I/O)
# ------------------------------------------------------------------


def next_touch_number(touches) -> int:
    """One past the highest ``touch_number`` present, or 1.

    Taken from the numbers rather than from ``len(touches)`` because a merged
    report's touch list is not guaranteed to be a gapless 1..n — and a duplicate
    ``touch_number`` would silently collide in every consumer that keys on it.
    """
    numbers = [t.get("touch_number") for t in touches if isinstance(t.get("touch_number"), int)]
    return max(numbers) + 1 if numbers else 1


def swap_warnings(report_warnings, before, after, clock: str):
    """Replace the superseded lamp warnings with the regenerated ones.

    ``before`` / ``after`` are :func:`tracked_warnings` run without and with the
    inference, so the difference between them is exactly what the rule changed.
    Entries the report holds verbatim are matched and replaced in place; an
    entry that has drifted from what this code would generate today (a report
    written by an older version, a different fps) is still recognised by its type
    and the promoted event's clock time, because leaving it behind would produce
    a report that counts the touch and warns it is unconfirmed at once.
    """
    removed = [w for w in before if w not in after]
    replacements = [w for w in after if w not in before]

    result = []
    pending = list(replacements)
    for warning in report_warnings:
        superseded = warning in removed or (
            warning.get("type") in SUPERSEDED_WARNING_TYPES
            and clock in (warning.get("message") or "")
        )
        if superseded:
            if pending:
                result.append(pending.pop(0))
            continue
        result.append(warning)
    result.extend(pending)
    return result


def apply_to_report(report: dict, analysis, inference, fps: float, clock_at_cut: str) -> dict:
    """Return ``report`` with the inferred point folded in.

    Touches the five things the point implies and nothing else. In particular
    ``summary.official_final_score`` is left alone: that field is what a human
    recorded off the referee's sheet, and an inference must never overwrite an
    observation.
    """
    event = end_of_bout_event(analysis, inference, fps, clock_at_cut)
    touches = list(report.get("touches") or [])
    touch = build_touches([event], fps=fps)[0]
    touch["touch_number"] = next_touch_number(touches)
    touches.append(touch)

    summary = dict(report.get("summary") or {})
    summary["final_score"] = f"{inference.score_after[0]}-{inference.score_after[1]}"
    summary["total_touches"] = len(touches)

    # scoring_frames drives the exchange/outcome matching downstream, which
    # assumes ascending order — so re-sort rather than blindly appending to the
    # tail, and de-duplicate in case this ran twice.
    scoring_frames = sorted(set(report.get("scoring_frames") or []) | {int(event.frame)})

    clock = _clock(event.frame, fps)
    warnings = swap_warnings(
        report.get("warnings") or [],
        tracked_warnings(analysis, fps=fps),
        tracked_warnings(analysis, fps=fps, inference=inference),
        clock,
    )

    updated = dict(report)
    updated["summary"] = summary
    updated["touches"] = touches
    updated["scoring_frames"] = scoring_frames
    updated["warnings"] = warnings
    return updated


def diff_lines(before: dict, after: dict) -> list:
    """Human-readable summary of what :func:`apply_to_report` changed."""
    lines = []
    old_summary = before.get("summary") or {}
    new_summary = after.get("summary") or {}
    for key in ("final_score", "total_touches"):
        lines.append(f"  summary.{key}: {old_summary.get(key)!r} -> {new_summary.get(key)!r}")

    touch = (after.get("touches") or [])[-1]
    lines.append(f"  touches: +1 (touch_number {touch['touch_number']})")
    for key in ("frame", "scorer", "score_before", "score_after", "touch_source"):
        lines.append(f"    {key}: {touch.get(key)!r}")
    lines.append(f"    inference_basis: {json.dumps(touch.get('inference_basis'), ensure_ascii=False)}")

    old_frames = list(before.get("scoring_frames") or [])
    new_frames = list(after.get("scoring_frames") or [])
    added = [f for f in new_frames if f not in old_frames]
    lines.append(f"  scoring_frames: {len(old_frames)} -> {len(new_frames)} (added {added})")

    old_warnings = before.get("warnings") or []
    new_warnings = after.get("warnings") or []
    for warning in old_warnings:
        if warning not in new_warnings:
            lines.append(f"  - [{warning.get('severity')}] {warning.get('type')}: {warning.get('message')}")
    for warning in new_warnings:
        if warning not in old_warnings:
            lines.append(f"  + [{warning.get('severity')}] {warning.get('type')}: {warning.get('message')}")
    return lines


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "report_id",
        help="report JSON stem, in data/reports/ or data/reports/private/ (.json optional)",
    )
    parser.add_argument(
        "--config", required=True,
        help="Piste config JSON naming the scoreboard work file and tracker block",
    )
    parser.add_argument(
        "--bout-type", required=True, choices=("pool", "de"),
        help="Bout format — decides the target score (pool 5, de 15)",
    )
    parser.add_argument(
        "--clock-at-cut", required=True, choices=("running", "expired"),
        help="What the match clock showed when the recording stopped. Your "
             "assertion — the tracked profile has no clock ROI.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the exact diff that would be applied; write nothing.",
    )
    return parser


def main(argv=None) -> int:
    from analyzer.scoreboard_tracker import END_OF_BOUT_TARGET, infer_end_of_bout_touch

    args = build_parser().parse_args(argv)

    report_id = args.report_id[:-5] if args.report_id.endswith(".json") else args.report_id
    report_path = resolve_report_path(REPORTS_DIR, report_id)
    if report_path is None:
        print(f"error: no such report: {report_id} (looked under {REPORTS_DIR})", file=sys.stderr)
        return EXIT_NOT_FOUND

    try:
        config = load_piste_config(args.config)
        video = extract_scoreboard_video(config)
        tracker = extract_tracker(config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_NOT_FOUND
    if not video.exists():
        print(f"error: scoreboard work file not found: {video}", file=sys.stderr)
        return EXIT_NOT_FOUND

    with open(report_path, "r", encoding="utf-8") as fh:
        report = json.load(fh)

    print(f"Report:     {report_path}")
    print(f"Scoreboard: {video}")
    print("Re-reading the scoreboard (about 20s for a 3-minute bout)...")
    # The weapon comes from the report being amended, not from a flag: this read
    # has to reproduce the one the report was built from, and under priority the
    # weapon changes what a both-sides-changed comparison resolves to.
    weapon = (report.get("summary") or {}).get("weapon")
    analysis, elapsed = track_from_config(video, tracker, weapon=weapon)
    print(
        f"  {len(analysis.events)} lamp events in {elapsed:.1f}s -> "
        f"{len(analysis.touches)} touches, {len(analysis.annulled)} annulled, "
        f"{len(analysis.undetermined)} undetermined"
    )

    inference = infer_end_of_bout_touch(
        analysis.resolutions,
        target_score=END_OF_BOUT_TARGET[args.bout_type],
        frame_count=analysis.frame_count,
        fps=analysis.fps,
        clock_running_at_cut=CLOCK_AT_CUT_CHOICES[args.clock_at_cut],
    )
    if not inference.applied:
        print(f"\nEnd-of-bout rule did not fire (reason: {inference.reason}). Nothing changed.")
        return EXIT_OK

    updated = apply_to_report(report, analysis, inference, analysis.fps, args.clock_at_cut)

    print(
        f"\nEnd-of-bout rule APPLIED: {inference.scorer} to "
        f"{inference.score_after[0]}-{inference.score_after[1]}"
    )
    for line in diff_lines(report, updated):
        print(line)

    if args.dry_run:
        print("\n  --dry-run: nothing written.")
        return EXIT_OK

    write_report(report_path, updated)
    print(f"\n  Saved: {report_path}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
