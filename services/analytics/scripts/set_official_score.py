#!/usr/bin/env python3
"""Admin CLI to record the official final score of a bout by hand.

``summary.final_score`` is an *observation*: it is whatever the scoreboard read
in the footage we actually have. Our own recordings routinely start after the
first touches or stop before the last one — a phone fills up, a parent starts
filming once the bout looks interesting, someone hits stop when the fencers
salute early. So the number the video ends on is frequently not the number the
bout ended on.

Overwriting ``final_score`` with the real result is the obvious fix and the
wrong one, for two reasons:

* Every other figure in the report — touch count, the per-touch timeline, each
  fencer's scored/conceded totals — is derived from what was seen. A headline
  score that disagreed with its own touch list would read as an analysis bug
  rather than as a short recording, and a coach would stop trusting the whole
  page over it.
* The correction would be irreversible. Once the observed value is gone, nobody
  can tell whether the analyzer missed touches or the camera did — which is
  exactly the question the gap between the two numbers answers.

So the coach's number is *added* beside the observed one, never on top of it::

    summary.final_score                  "4-2"   what the video showed (untouched)
    summary.official_final_score         "5-2"   what the bout ended on (manual)
    summary.official_final_score_source  "manual"
    summary.recording_note               why the two differ (free text, optional)

The report page then shows the official score as the result and the observed one
directly beneath it, so the gap is visible rather than hidden.

``final_score`` is sometimes the literal label ``"연속 분석"`` on pose-only
reports — not a score at all. An official score attaches to those too, and the
label is left exactly as it is.

    python3 scripts/set_official_score.py 260815_pool_home_vs_away 5-2
    python3 scripts/set_official_score.py 260815_bout_b 15-9 --note "녹화가 경기 종료 전 중단"
    python3 scripts/set_official_score.py 260816_venue2_bout --clear

The report is found in either ``data/reports/`` or ``data/reports/private/``, so
an id works no matter where the file currently sits. This CLI is the forerunner
of a coach-facing web form; the field logic lives in ``set_official_score`` /
``clear_official_score`` so that form can call it without going through argv.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Import app.sharing regardless of cwd — an admin runs this from anywhere.
_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

from app.sharing import private_dir, resolve_report_path  # noqa: E402

# Reused rather than copied: these reports run to several hundred KB, and a
# second implementation of the atomic write would be free to drift from the
# first one's serialization without anything noticing.
from scripts.share_report import write_report  # noqa: E402

#: Resolved from the script's own location, not the cwd, for the same reason.
REPORTS_DIR = _SERVICE_ROOT / "data" / "reports"

#: Explicit [0-9] rather than \d — \d also matches non-ASCII digits, which the
#: template's .isdigit() check would accept and no scoreboard ever shows.
SCORE_PATTERN = re.compile(r"^[0-9]{1,2}-[0-9]{1,2}$")

KEY_SCORE = "official_final_score"
KEY_SOURCE = "official_final_score_source"
KEY_NOTE = "recording_note"
SOURCE_MANUAL = "manual"

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_NOT_FOUND = 2

#: Sentinel so a legitimately-stored ``None`` still counts as "was present".
_MISSING = object()


def normalize_report_id(report_id: str) -> str:
    """Strip a typed-out ``.json`` so both spellings of an id work."""
    return report_id[:-5] if report_id.endswith(".json") else report_id


def load_report(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def validate_score(score) -> str:
    """Return the canonical ``"N-M"`` form of ``score``, or raise ``ValueError``.

    Deliberately strict. A free-text score would let ``"5:2"``, ``"5 - 2"`` or a
    half-typed ``"5-"`` reach the report, where the template's numeric guard
    would silently fall back to rendering it as a label — the failure would look
    like a display quirk instead of bad data.
    """
    candidate = (score or "").strip() if isinstance(score, str) else ""
    if not SCORE_PATTERN.match(candidate):
        raise ValueError(
            f"invalid score {score!r}: expected \"N-M\", one or two digits each "
            "side, left fencer first (e.g. 5-2)"
        )
    return candidate


def observed_score(report: dict) -> str:
    """The score the video showed, as a display string (may be a label)."""
    summary = report.get("summary")
    if not isinstance(summary, dict):
        return ""
    return str(summary.get("final_score") or "")


def set_official_score(report: dict, score, note: str | None = None) -> str:
    """Record ``score`` as the bout's official result and return it.

    ``final_score`` is never read or written here — that is the entire point of
    the field pair. The new keys are appended to ``summary``, so the existing
    key order of the report survives the round trip.

    ``note`` is only touched when one is passed: re-running to fix a typo in the
    score must not silently drop the note explaining why the recording is short.
    Passing an empty ``--note`` removes it.
    """
    canonical = validate_score(score)
    summary = report.setdefault("summary", {})
    summary[KEY_SCORE] = canonical
    summary[KEY_SOURCE] = SOURCE_MANUAL
    if note is not None:
        text = note.strip()
        if text:
            summary[KEY_NOTE] = text
        else:
            summary.pop(KEY_NOTE, None)
    return canonical


def clear_official_score(report: dict) -> bool:
    """Remove all three manual keys. True if any of them was there to remove."""
    summary = report.get("summary")
    if not isinstance(summary, dict):
        return False
    removed = [summary.pop(key, _MISSING) for key in (KEY_SCORE, KEY_SOURCE, KEY_NOTE)]
    return any(value is not _MISSING for value in removed)


def cmd_set(path: Path, score: str, note: str | None) -> int:
    report = load_report(path)
    observed = observed_score(report)
    previous = report.get("summary", {}).get(KEY_SCORE)

    official = set_official_score(report, score, note)
    write_report(path, report)

    print(f"{path.stem}: official final score recorded.")
    print(f"  observed (final_score, from the video): {observed or '(none)'}")
    was = f"   (was {previous})" if previous and previous != official else ""
    print(f"  official (manual coach entry):          {official}{was}")
    recorded_note = report["summary"].get(KEY_NOTE)
    if recorded_note:
        print(f"  recording note: {recorded_note}")
    return EXIT_OK


def cmd_clear(path: Path) -> int:
    report = load_report(path)
    observed = observed_score(report)
    previous = report.get("summary", {}).get(KEY_SCORE)

    if not clear_official_score(report):
        print(f"{path.stem}: no official score recorded, nothing to clear.")
        print(f"  observed (final_score, unchanged): {observed or '(none)'}")
        return EXIT_OK

    write_report(path, report)
    print(f"{path.stem}: official final score cleared (was {previous}).")
    print(f"  observed (final_score, unchanged): {observed or '(none)'}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "report_id",
        help="report JSON stem, in data/reports/ or data/reports/private/ (.json optional)",
    )
    parser.add_argument(
        "score",
        nargs="?",
        help='the bout\'s official final score as "N-M", left fencer first (e.g. 5-2)',
    )
    parser.add_argument(
        "--note",
        help='why the recording differs from the bout, e.g. "녹화가 경기 종료 전 중단"',
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="remove the official score, source and note again",
    )
    args = parser.parse_args(argv)

    if args.clear and args.score is not None:
        parser.error("--clear takes no score")
    if args.clear and args.note is not None:
        parser.error("--clear takes no --note")
    if not args.clear and args.score is None:
        parser.error("a score is required (e.g. 5-2); use --clear to remove one")

    # Reject a malformed score before the filesystem is touched at all, so a
    # typo cannot half-apply or leave a temp file behind.
    if args.score is not None:
        try:
            validate_score(args.score)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_INVALID

    report_id = normalize_report_id(args.report_id)
    path = resolve_report_path(REPORTS_DIR, report_id)
    if path is None:
        # Exit 2, never create: a typo must not conjure an empty report.
        print(
            f"error: no such report: {report_id} "
            f"(looked in {private_dir(REPORTS_DIR)} and {REPORTS_DIR})",
            file=sys.stderr,
        )
        return EXIT_NOT_FOUND

    if args.clear:
        return cmd_clear(path)
    return cmd_set(path, args.score, args.note)


if __name__ == "__main__":
    sys.exit(main())
