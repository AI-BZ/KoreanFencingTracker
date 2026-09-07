"""Tests for correcting the fencers' names on an already-generated report.

Two things are worth asserting here and one of them is not obvious.

The obvious one: the correction has to reach *both* files. The names live in
the OCR report and in the continuous report, and writing only the second looks
fixed right up until the report is regenerated, at which point the stale OCR
name comes back.

The less obvious one: the CLI and ``generate_continuous_report.py`` have to
agree about how an OCR name becomes a continuous-report name. They do it by
calling the same function, so the tests below check the shared rule *and* check
that both callers really are holding the same object — an identity assertion
looks pedantic until someone "tidies up" one caller into its own copy and the
two paths start disagreeing only for bouts with no name on the scoreboard.
"""

import json

import pytest

from app.led_report_converter import (
    DEFAULT_LEFT_NAME,
    DEFAULT_RIGHT_NAME,
    merge_fencer_names,
)
from scripts import set_fencer_names as sfn
from scripts.set_fencer_names import (
    EXIT_INVALID,
    EXIT_NOT_FOUND,
    EXIT_OK,
    NameUpdateError,
    ReportNotFoundError,
    main,
    normalise_report_id,
    set_fencer_names,
)


# Neutral stems only — the real reports on disk carry minors' names.
STEM = "260815_pool_home_vs_away"
STEM_MISSING = "260816_venue2_bout"

TOKEN = "pytestTokenAAAABBBBCCCC"
OFFICIAL_SCORE = "5-2"
RECORDING_NOTE = "녹화가 경기 종료 전 중단"

#: What a continuous report calls its fencers before any OCR name is merged.
CONTINUOUS_DEFAULT_LEFT = "Left Fencer"
CONTINUOUS_DEFAULT_RIGHT = "Right Fencer"


def _fencer(name: str) -> dict:
    return {
        "name": name,
        "club": "",
        "handedness": None,
        "total_touches_scored": 0,
        "total_touches_conceded": 0,
        "most_common_action": None,
        "most_common_action_pct": 0,
        "action_distribution": [],
    }


def _touch(frame: int, scorer: str, lamp: str) -> dict:
    return {
        "frame": frame,
        "timestamp": "0:05",
        "scorer": scorer,
        "lamp_pattern": lamp,
        "lamp_confidence": 0.9,
    }


def _ocr_report(left: str, right: str) -> dict:
    """The LED-scoreboard report: the source of the names, and of the lamps."""
    return {
        "summary": {
            "final_score": "2-0",
            "total_touches": 2,
            "match_duration": "0:30",
            "weapon": "foil",
            "bout_type": "pool",
            "official_final_score": OFFICIAL_SCORE,
            "recording_note": RECORDING_NOTE,
        },
        "touches": [
            _touch(100, "left", "single_left"),
            _touch(400, "right", "single_right"),
        ],
        "left_fencer": _fencer(left),
        "right_fencer": _fencer(right),
        "warnings": [],
        "meta": {"phase": 5, "share_token": TOKEN, "visibility": "unlisted"},
    }


def _continuous_report(
    left: str = CONTINUOUS_DEFAULT_LEFT,
    right: str = CONTINUOUS_DEFAULT_RIGHT,
) -> dict:
    """The report the web page renders. Carries the share token that gates it."""
    return {
        "summary": {
            "final_score": "연속 분석",
            "total_touches": 2,
            "match_duration": "0:30",
            "weapon": "foil",
            "bout_type": "pool",
            "official_final_score": OFFICIAL_SCORE,
            "recording_note": RECORDING_NOTE,
        },
        "touches": [
            _touch(100, "left", "single_left"),
            _touch(400, "right", "single_right"),
        ],
        "exchanges": [],
        "continuous_summary": {"total_exchanges": 0},
        "left_fencer": _fencer(left),
        "right_fencer": _fencer(right),
        "insights": [],
        "warnings": [],
        "meta": {
            "phase": 6,
            "share_token": TOKEN,
            "visibility": "unlisted",
            "analysis_mode": "continuous_with_ocr",
        },
    }


@pytest.fixture
def reports_dir(tmp_path):
    """A reports root holding one bout's pair of files under ``private/``.

    Private rather than public on purpose: every report this tool exists for is
    an unlisted bout, so the fixture exercises the same resolution order the
    server uses.
    """
    private = tmp_path / "private"
    private.mkdir(parents=True)
    _write(private / f"{STEM}_report.json", _ocr_report(DEFAULT_LEFT_NAME, DEFAULT_RIGHT_NAME))
    _write(private / f"{STEM}_continuous_report.json", _continuous_report())
    return tmp_path


def _write(path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read(reports_dir, suffix) -> dict:
    path = reports_dir / "private" / f"{STEM}{suffix}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _names(report) -> tuple:
    return report["left_fencer"]["name"], report["right_fencer"]["name"]


# ------------------------------------------------------------------
# The shared rule: one function, two callers
# ------------------------------------------------------------------


def test_generator_and_cli_share_one_merge_function():
    """Both paths must hold the *same* function, not two copies of the rule.

    If this fails, a hand-corrected report and a regenerated one can disagree,
    and the disagreement shows up only for bouts whose scoreboard had no names.
    """
    from scripts import generate_continuous_report as gcr

    assert gcr.merge_fencer_names is merge_fencer_names
    assert sfn.merge_fencer_names is merge_fencer_names


@pytest.mark.parametrize("sentinel", [DEFAULT_LEFT_NAME, DEFAULT_RIGHT_NAME])
def test_merge_ignores_the_no_name_sentinels(sentinel):
    """A sentinel is "no name was read", so it must not overwrite a real one."""
    target = _continuous_report()
    merge_fencer_names(target, _ocr_report(sentinel, sentinel))

    assert _names(target) == (CONTINUOUS_DEFAULT_LEFT, CONTINUOUS_DEFAULT_RIGHT)


def test_merge_copies_a_real_name_over_the_default():
    target = _continuous_report()
    merge_fencer_names(target, _ocr_report("홍세나", "박소윤"))

    assert _names(target) == ("홍세나", "박소윤")


def test_merge_does_not_erase_a_club_with_a_blank_one():
    """An empty OCR club is "not read", not "no club"."""
    target = _continuous_report()
    target["left_fencer"]["club"] = "최병철펜싱클럽"
    merge_fencer_names(target, _ocr_report("홍세나", "박소윤"))

    assert target["left_fencer"]["club"] == "최병철펜싱클럽"


# ------------------------------------------------------------------
# The correction reaches both files
# ------------------------------------------------------------------


def test_names_land_in_both_reports(reports_dir):
    set_fencer_names(reports_dir, STEM, left_name="홍세나", right_name="박소윤")

    assert _names(_read(reports_dir, "_report")) == ("홍세나", "박소윤")
    assert _names(_read(reports_dir, "_continuous_report")) == ("홍세나", "박소윤")


def test_one_sided_correction_leaves_the_other_side_alone(reports_dir):
    _write(
        reports_dir / "private" / f"{STEM}_report.json",
        _ocr_report(DEFAULT_LEFT_NAME, "박소윤"),
    )

    set_fencer_names(reports_dir, STEM, left_name="홍세나")

    assert _names(_read(reports_dir, "_report")) == ("홍세나", "박소윤")
    assert _names(_read(reports_dir, "_continuous_report")) == ("홍세나", "박소윤")


def test_no_names_given_republishes_the_ocr_names(reports_dir):
    """The 'the OCR file was right all along' case.

    A wrong name can reach the continuous report on its own — it is the file
    people edit — and re-running with no flags is how that gets undone.
    """
    _write(
        reports_dir / "private" / f"{STEM}_report.json",
        _ocr_report("홍세나", "박소윤"),
    )
    _write(
        reports_dir / "private" / f"{STEM}_continuous_report.json",
        _continuous_report("세나 홍", "박소윤"),
    )

    set_fencer_names(reports_dir, STEM)

    assert _names(_read(reports_dir, "_continuous_report")) == ("홍세나", "박소윤")


def test_a_sentinel_ocr_name_leaves_the_continuous_defaults_standing(reports_dir):
    """Same rule as the generator's, exercised end to end through the files."""
    set_fencer_names(reports_dir, STEM)

    assert _names(_read(reports_dir, "_continuous_report")) == (
        CONTINUOUS_DEFAULT_LEFT,
        CONTINUOUS_DEFAULT_RIGHT,
    )


def test_correcting_twice_is_idempotent(reports_dir):
    set_fencer_names(reports_dir, STEM, left_name="홍세나", right_name="박소윤")
    first = _read(reports_dir, "_continuous_report")

    set_fencer_names(reports_dir, STEM, left_name="홍세나", right_name="박소윤")

    assert _read(reports_dir, "_continuous_report") == first


# ------------------------------------------------------------------
# Everything else survives
# ------------------------------------------------------------------


def test_share_token_survives_the_correction(reports_dir):
    """Losing this unlocks nothing — it makes the bout unreachable for good."""
    set_fencer_names(reports_dir, STEM, left_name="홍세나", right_name="박소윤")

    for suffix in ("_report", "_continuous_report"):
        meta = _read(reports_dir, suffix)["meta"]
        assert meta["share_token"] == TOKEN
        assert meta["visibility"] == "unlisted"


def test_every_field_but_the_names_is_preserved(reports_dir):
    before = {s: _read(reports_dir, s) for s in ("_report", "_continuous_report")}

    set_fencer_names(reports_dir, STEM, left_name="홍세나", right_name="박소윤")

    for suffix, original in before.items():
        after = _read(reports_dir, suffix)
        for side in ("left_fencer", "right_fencer"):
            original[side]["name"] = after[side]["name"]
        assert after == original


def test_hand_entered_score_and_note_are_untouched(reports_dir):
    """Named explicitly because these two are typed in by a human, once."""
    set_fencer_names(reports_dir, STEM, left_name="홍세나", right_name="박소윤")

    for suffix in ("_report", "_continuous_report"):
        summary = _read(reports_dir, suffix)["summary"]
        assert summary["official_final_score"] == OFFICIAL_SCORE
        assert summary["recording_note"] == RECORDING_NOTE


def test_touches_and_lamp_readings_are_untouched(reports_dir):
    set_fencer_names(reports_dir, STEM, left_name="홍세나", right_name="박소윤")

    for suffix in ("_report", "_continuous_report"):
        touches = _read(reports_dir, suffix)["touches"]
        assert len(touches) == 2
        assert [t["lamp_pattern"] for t in touches] == ["single_left", "single_right"]


def test_dry_run_writes_nothing(reports_dir):
    before = {s: _read(reports_dir, s) for s in ("_report", "_continuous_report")}

    result = set_fencer_names(
        reports_dir, STEM, left_name="홍세나", right_name="박소윤", dry_run=True
    )

    assert result["dry_run"] is True
    assert result["ocr_after"]["left_fencer.name"] == "홍세나"
    for suffix, original in before.items():
        assert _read(reports_dir, suffix) == original


# ------------------------------------------------------------------
# Failure modes
# ------------------------------------------------------------------


def test_unknown_report_id_fails(reports_dir):
    with pytest.raises(ReportNotFoundError, match=STEM_MISSING):
        set_fencer_names(reports_dir, STEM_MISSING, left_name="홍세나")


def test_ocr_report_without_a_continuous_report_fails(reports_dir):
    """Half a bout is not correctable: the page would keep the old name."""
    (reports_dir / "private" / f"{STEM}_continuous_report.json").unlink()

    with pytest.raises(ReportNotFoundError, match="_continuous_report.json"):
        set_fencer_names(reports_dir, STEM, left_name="홍세나")


def test_continuous_report_without_an_ocr_report_fails(reports_dir):
    """The reverse: nowhere to record the name so a regeneration keeps it."""
    (reports_dir / "private" / f"{STEM}_report.json").unlink()

    with pytest.raises(ReportNotFoundError, match=f"{STEM}_report.json"):
        set_fencer_names(reports_dir, STEM, left_name="홍세나")


def test_a_failed_lookup_writes_nothing(reports_dir):
    """Resolution happens before any write, so a half-applied pair is impossible."""
    before = _read(reports_dir, "_report")
    (reports_dir / "private" / f"{STEM}_continuous_report.json").unlink()

    with pytest.raises(ReportNotFoundError):
        set_fencer_names(reports_dir, STEM, left_name="홍세나")

    assert _read(reports_dir, "_report") == before


@pytest.mark.parametrize("sentinel", [DEFAULT_LEFT_NAME, DEFAULT_RIGHT_NAME])
def test_passing_a_sentinel_as_a_name_is_rejected(reports_dir, sentinel):
    """It would be silently dropped by the merge, which reads as "it worked"."""
    with pytest.raises(NameUpdateError, match="placeholder"):
        set_fencer_names(reports_dir, STEM, left_name=sentinel)


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_name_is_rejected(reports_dir, blank):
    with pytest.raises(NameUpdateError, match="blank"):
        set_fencer_names(reports_dir, STEM, right_name=blank)


# ------------------------------------------------------------------
# Report id spellings
# ------------------------------------------------------------------


@pytest.mark.parametrize(
    "spelling",
    [STEM, f"{STEM}_report", f"{STEM}_continuous_report"],
)
def test_every_spelling_of_the_id_resolves_to_the_same_bout(spelling):
    assert normalise_report_id(spelling) == STEM


def test_the_id_from_a_saved_report_url_works(reports_dir):
    """That id is the continuous stem, which is what people have to hand."""
    set_fencer_names(
        reports_dir, f"{STEM}_continuous_report", left_name="홍세나", right_name="박소윤"
    )

    assert _names(_read(reports_dir, "_report")) == ("홍세나", "박소윤")


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------


def test_cli_applies_the_correction(reports_dir, capsys):
    code = main(
        [STEM, "--left-name", "홍세나", "--right-name", "박소윤",
         "--reports-dir", str(reports_dir)]
    )

    assert code == EXIT_OK
    assert _names(_read(reports_dir, "_continuous_report")) == ("홍세나", "박소윤")
    assert "홍세나" in capsys.readouterr().out


def test_cli_exits_not_found_for_an_unknown_id(reports_dir, capsys):
    code = main([STEM_MISSING, "--reports-dir", str(reports_dir)])

    assert code == EXIT_NOT_FOUND
    assert "ERROR" in capsys.readouterr().err


def test_cli_exits_invalid_for_a_rejected_name(reports_dir, capsys):
    code = main(
        [STEM, "--left-name", DEFAULT_LEFT_NAME, "--reports-dir", str(reports_dir)]
    )

    assert code == EXIT_INVALID
    assert "ERROR" in capsys.readouterr().err
