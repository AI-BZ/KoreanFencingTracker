"""Correct the fencers' names on an already-generated report.

A bout filmed with a physical LED scoreboard carries no names on the box, so
``analyze_led_scoreboard.py`` records whatever ``--left-name``/``--right-name``
it was given — and when those flags are forgotten, the report ends up with the
placeholders ``Left``/``Right`` and the continuous report keeps its own
``Left Fencer``/``Right Fencer`` defaults. That happens often enough (a whole
competition's footage at a time) that fixing it by hand-editing JSON is both
tedious and easy to get half-right.

Half-right is the real hazard. The names live in *two* files:

    data/reports/[private/]{id}_report.json              OCR report, the source
    data/reports/[private/]{id}_continuous_report.json   what the web page reads

Editing only the second one looks fixed until the report is regenerated, at
which point the OCR report's stale name comes straight back. So this script
always writes both, and it copies the OCR name into the continuous report
through :func:`app.led_report_converter.merge_fencer_names` — the very function
``generate_continuous_report.py`` uses — so a report corrected here and a report
regenerated from scratch carry the same names.

Everything other than ``name`` and ``club`` is left alone, and that is checked
rather than assumed: these reports carry a ``meta.share_token`` that is the only
way to open an unlisted bout, plus hand-entered fields like
``summary.official_final_score``. Rewriting one of those while fixing a typo
would be silent and unrecoverable.

Usage:
    cd services/analytics

    # give both names
    PYTHONPATH=. .venv/bin/python3 scripts/set_fencer_names.py \\
        260816_Sena,HongVsSoyun_piste12 --left-name 홍세나 --right-name 박소윤

    # names already correct in the OCR report — just re-propagate them
    PYTHONPATH=. .venv/bin/python3 scripts/set_fencer_names.py \\
        260816_Sena,HongVsSoyun_piste12

    # see what would change without writing
    PYTHONPATH=. .venv/bin/python3 scripts/set_fencer_names.py <id> \\
        --left-name 임채린 --dry-run
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

# Import app.* regardless of cwd — an admin runs this from anywhere. Same
# bootstrap as scripts/set_official_score.py, the sibling admin CLI.
_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

from app.led_report_converter import NAME_SENTINELS, merge_fencer_names  # noqa: E402
from app.sharing import resolve_report_path  # noqa: E402

# Reused rather than copied, for the reason set_official_score.py gives: these
# reports run to several hundred KB and are the only copy of an unlisted bout,
# so the write has to be atomic, and a second implementation of it would be
# free to drift from the first one's serialization without anything noticing.
from scripts.share_report import write_report  # noqa: E402

#: Resolved from the script's own location, not the cwd, for the same reason.
REPORTS_DIR = _SERVICE_ROOT / "data" / "reports"

#: Filename suffixes for the two reports a bout produces. The OCR report is the
#: source of the names; the continuous report is what the web page renders.
OCR_SUFFIX = "_report"
CONTINUOUS_SUFFIX = "_continuous_report"

#: The only fields this script is allowed to touch, per fencer.
EDITABLE_FIELDS = ("name", "club")

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_NOT_FOUND = 2


class NameUpdateError(Exception):
    """A correction could not be applied. Carries a message fit for the user."""

    exit_code = EXIT_INVALID


class ReportNotFoundError(NameUpdateError):
    """One or both of a bout's two report files are missing.

    Distinct from the base class so a mistyped id exits differently from a
    rejected name: a caller scripting a batch of corrections can tell "that
    bout is not here" from "that name is not allowed".
    """

    exit_code = EXIT_NOT_FOUND


def normalise_report_id(report_id: str) -> str:
    """Strip a report-file suffix off ``report_id``, leaving the bout's base id.

    The base id (``260816_Sena,HongVsSoyun_piste12``) names *both* files, but
    the id people have in front of them is usually the continuous report's —
    it is what appears in a saved-report URL and in a directory listing.
    Accepting either spelling means a pasted id works instead of failing with
    "no such report" for a report that plainly exists.
    """
    for suffix in (CONTINUOUS_SUFFIX, OCR_SUFFIX):
        if report_id.endswith(suffix):
            return report_id[: -len(suffix)]
    return report_id


def locate_reports(reports_dir, report_id: str) -> "tuple[Path, Path]":
    """Return the (OCR, continuous) report paths for ``report_id``.

    Resolution goes through :func:`app.sharing.resolve_report_path`, so the
    private directory wins exactly as it does for the server — correcting the
    public copy of a report that has since been shared would edit a file
    nothing reads.

    Raises :class:`NameUpdateError` if either file is missing. Both are
    required: with no OCR report there is nowhere to record the name durably,
    and with no continuous report there is nothing for the page to show.
    """
    base = normalise_report_id(report_id)
    ocr_path = resolve_report_path(reports_dir, f"{base}{OCR_SUFFIX}")
    continuous_path = resolve_report_path(reports_dir, f"{base}{CONTINUOUS_SUFFIX}")

    missing = []
    if ocr_path is None:
        missing.append(f"{base}{OCR_SUFFIX}.json")
    if continuous_path is None:
        missing.append(f"{base}{CONTINUOUS_SUFFIX}.json")
    if missing:
        raise ReportNotFoundError(
            f"report '{base}': not found under {reports_dir} "
            f"(missing: {', '.join(missing)})"
        )
    return ocr_path, continuous_path


def apply_names(ocr_report: dict, left_name=None, right_name=None) -> dict:
    """Write ``left_name``/``right_name`` into an OCR report's fencer blocks.

    A name of ``None`` leaves that side as it stands, which is what makes a
    run with no ``--left-name``/``--right-name`` a pure re-propagation of names
    the OCR report already holds.

    Mutates and returns ``ocr_report``.
    """
    for side, name in (("left_fencer", left_name), ("right_fencer", right_name)):
        if name is None:
            continue
        ocr_report.setdefault(side, {})["name"] = name
    return ocr_report


def assert_only_names_changed(before: dict, after: dict, label: str) -> None:
    """Fail unless ``after`` differs from ``before`` only in name/club fields.

    The guard is written as "rebuild what the result should have been" rather
    than as a diff of the fields we meant to write, because those are not the
    same check. A diff only inspects the fields it thinks about; this compares
    the whole document, so a touch list reordered by a future refactor, or a
    ``share_token`` dropped by a bad merge, fails here instead of shipping.
    """
    expected = copy.deepcopy(before)
    for side in ("left_fencer", "right_fencer"):
        after_side = after.get(side)
        if after_side is None:
            continue
        expected_side = expected.setdefault(side, {})
        for field in EDITABLE_FIELDS:
            if field in after_side:
                expected_side[field] = after_side[field]
            else:
                expected_side.pop(field, None)
    if expected != after:
        raise NameUpdateError(
            f"{label}: refusing to write — the update changed fields other "
            f"than {'/'.join(EDITABLE_FIELDS)}"
        )


def describe_names(report: dict) -> "dict[str, object]":
    """The four name/club values of ``report``, for before/after printing."""
    described = {}
    for side in ("left_fencer", "right_fencer"):
        fencer = report.get(side) or {}
        for field in EDITABLE_FIELDS:
            described[f"{side}.{field}"] = fencer.get(field)
    return described


def _load(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def set_fencer_names(
    reports_dir,
    report_id: str,
    left_name=None,
    right_name=None,
    dry_run: bool = False,
) -> dict:
    """Correct the names on one bout's OCR and continuous reports.

    Returns a summary dict with the resolved paths and the before/after name
    values of both files, so a caller (or the CLI below) can show what changed
    without re-reading the files.
    """
    for label, name in (("--left-name", left_name), ("--right-name", right_name)):
        if name is not None and name in NAME_SENTINELS:
            raise NameUpdateError(
                f"{label}={name!r} is the pipeline's 'no name was read' "
                f"placeholder, which the merge deliberately ignores. Pass a "
                f"real name, or omit the flag to leave that side unchanged."
            )
        if name is not None and not name.strip():
            raise NameUpdateError(f"{label}: name must not be blank")

    ocr_path, continuous_path = locate_reports(reports_dir, report_id)

    ocr_before = _load(ocr_path)
    continuous_before = _load(continuous_path)

    ocr_after = apply_names(copy.deepcopy(ocr_before), left_name, right_name)
    # The continuous report takes its names from the *updated* OCR report and
    # by the generator's own rule, so this run and a regeneration agree.
    continuous_after = merge_fencer_names(copy.deepcopy(continuous_before), ocr_after)

    assert_only_names_changed(ocr_before, ocr_after, ocr_path.name)
    assert_only_names_changed(continuous_before, continuous_after, continuous_path.name)

    if not dry_run:
        write_report(ocr_path, ocr_after)
        write_report(continuous_path, continuous_after)

    return {
        "ocr_path": ocr_path,
        "continuous_path": continuous_path,
        "dry_run": dry_run,
        "ocr_before": describe_names(ocr_before),
        "ocr_after": describe_names(ocr_after),
        "continuous_before": describe_names(continuous_before),
        "continuous_after": describe_names(continuous_after),
    }


def _print_change(label: str, before: dict, after: dict) -> None:
    print(f"  {label}")
    for key in before:
        old, new = before[key], after[key]
        marker = " " if old == new else "*"
        arrow = "" if old == new else f"  ->  {new!r}"
        print(f"   {marker} {key}: {old!r}{arrow}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Correct the fencers' names on a generated report.",
    )
    parser.add_argument(
        "report_id",
        help=(
            "Bout id, e.g. 260816_Sena,HongVsSoyun_piste12. A trailing "
            "_report or _continuous_report is stripped, so the id from a "
            "saved-report URL works too."
        ),
    )
    parser.add_argument("--left-name", help="Name of the left fencer.")
    parser.add_argument("--right-name", help="Name of the right fencer.")
    parser.add_argument(
        "--reports-dir", default=str(REPORTS_DIR),
        help="Report root; the private/ subdirectory is searched first.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would change without writing.",
    )
    args = parser.parse_args(argv)

    try:
        result = set_fencer_names(
            args.reports_dir,
            args.report_id,
            left_name=args.left_name,
            right_name=args.right_name,
            dry_run=args.dry_run,
        )
    except NameUpdateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exc.exit_code

    print(f"{'Would update' if result['dry_run'] else 'Updated'}:")
    _print_change(
        str(result["ocr_path"]), result["ocr_before"], result["ocr_after"]
    )
    _print_change(
        str(result["continuous_path"]),
        result["continuous_before"],
        result["continuous_after"],
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
