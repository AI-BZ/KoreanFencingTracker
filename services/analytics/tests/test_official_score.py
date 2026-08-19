"""Tests for the manually-recorded official final score.

``summary.final_score`` is what the camera saw; ``summary.official_final_score``
is what the bout ended on. They are kept as two separate fields on purpose (see
``scripts/set_official_score.py``), so most of what is asserted here is a
negative: the observed value survives every write, and neither the CLI nor the
report page ever presents one of the two numbers as the other.
"""

import json
import re

import pytest
from fastapi.testclient import TestClient

from app import sharing
from scripts import set_official_score as sos
from scripts.set_official_score import (
    EXIT_INVALID,
    EXIT_NOT_FOUND,
    EXIT_OK,
    KEY_NOTE,
    KEY_SCORE,
    KEY_SOURCE,
    SOURCE_MANUAL,
    clear_official_score,
    main,
    set_official_score,
    validate_score,
)


# Neutral stems only — the real reports on disk carry minors' names.
STEM_PUBLIC = "260815_pool_home_vs_away"
STEM_PRIVATE = "260815_bout_b"
STEM_MISSING = "260816_venue2_bout"

NOTE_STOPPED_EARLY = "녹화가 경기 종료 전 중단"
NOTE_STARTED_LATE = "녹화가 4-0 시점부터 시작"

#: The pose-only reports store a label here rather than a score.
CONTINUOUS_LABEL = "연속 분석"


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


def _report(final_score: str = "4-2") -> dict:
    """Smallest report the template actually renders, with no touches.

    Mirrors ``tests/test_report_sharing._minimal_report``: if it goes stale the
    rendering tests below start failing on a template error rather than on the
    score block they exist to check.
    """
    return {
        "summary": {
            "final_score": final_score,
            "total_touches": 0,
            "match_duration": "00:30",
            "total_frames_analyzed": 900,
            "analysis_time_sec": 1.0,
            "weapon": "foil",
            "bout_type": "pool",
            "gender": None,
            "age_group": None,
        },
        "touches": [],
        "exchanges": [],
        "continuous_summary": {
            "total_exchanges": 0,
            "scoring_exchanges": 0,
            "non_scoring_exchanges": 0,
            "type_distribution": {},
            "fencer_stats": {
                "left": {"attacks": 0, "defenses": 0},
                "right": {"attacks": 0, "defenses": 0},
            },
        },
        "left_fencer": _fencer("Left Fencer"),
        "right_fencer": _fencer("Right Fencer"),
        "insights": [],
        "warnings": [],
        "meta": {"phase": 6, "fps": 30.0, "analysis_mode": "continuous_only"},
    }


# ------------------------------------------------------------------
# Score format validation
# ------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("5-2", "5-2"),
        ("0-0", "0-0"),
        ("15-9", "15-9"),
        ("15-14", "15-14"),
        ("  5-2  ", "5-2"),
        ("05-02", "05-02"),
    ],
)
def test_validate_score_accepts_a_scoreboard_score(raw, expected):
    assert validate_score(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "5",
        "5-",
        "-2",
        "5-2-1",
        "5:2",
        "5 - 2",
        "5–2",          # en dash, not a hyphen
        "100-9",        # three digits: no fencing scoreboard reaches it
        "5-100",
        "a-b",
        CONTINUOUS_LABEL,
        "５-２",         # full-width digits: \d would have accepted these
        None,
        5,
    ],
)
def test_validate_score_rejects_anything_else(raw):
    with pytest.raises(ValueError, match="invalid score"):
        validate_score(raw)


def test_validate_score_message_names_the_expected_shape():
    """The operator has to be able to fix the typo from the message alone."""
    with pytest.raises(ValueError) as exc:
        validate_score("5:2")
    assert "N-M" in str(exc.value)
    assert "left fencer first" in str(exc.value)


# ------------------------------------------------------------------
# The writer — add, never overwrite
# ------------------------------------------------------------------


def test_set_official_score_leaves_final_score_untouched():
    report = _report("4-2")
    set_official_score(report, "5-2")

    assert report["summary"]["final_score"] == "4-2"
    assert report["summary"][KEY_SCORE] == "5-2"


def test_set_official_score_records_the_source_as_manual():
    report = _report()
    set_official_score(report, "5-2")
    assert report["summary"][KEY_SOURCE] == SOURCE_MANUAL


def test_set_official_score_preserves_every_other_field():
    report = _report()
    before = json.loads(json.dumps(report))

    set_official_score(report, "5-2", NOTE_STOPPED_EARLY)

    for key in (KEY_SCORE, KEY_SOURCE, KEY_NOTE):
        report["summary"].pop(key)
    assert report == before


def test_set_official_score_appends_without_reordering_summary():
    """A several-hundred-KB report must survive the round trip recognisable."""
    report = _report()
    original_order = list(report["summary"])

    set_official_score(report, "5-2", NOTE_STOPPED_EARLY)
    keys = list(report["summary"])

    assert keys[: len(original_order)] == original_order
    assert keys[len(original_order):] == [KEY_SCORE, KEY_SOURCE, KEY_NOTE]


def test_set_official_score_works_when_final_score_is_a_label():
    """Pose-only reports store "연속 분석" there — still a valid target."""
    report = _report(CONTINUOUS_LABEL)
    set_official_score(report, "15-9")

    assert report["summary"]["final_score"] == CONTINUOUS_LABEL
    assert report["summary"][KEY_SCORE] == "15-9"


def test_set_official_score_stores_the_note():
    report = _report()
    set_official_score(report, "5-2", NOTE_STOPPED_EARLY)
    assert report["summary"][KEY_NOTE] == NOTE_STOPPED_EARLY


def test_set_official_score_keeps_an_existing_note_when_none_is_given():
    """Correcting a typo in the score must not drop why the recording is short."""
    report = _report()
    set_official_score(report, "5-2", NOTE_STOPPED_EARLY)
    set_official_score(report, "5-3")

    assert report["summary"][KEY_NOTE] == NOTE_STOPPED_EARLY
    assert report["summary"][KEY_SCORE] == "5-3"


def test_set_official_score_replaces_a_note_when_a_new_one_is_given():
    report = _report()
    set_official_score(report, "5-2", NOTE_STOPPED_EARLY)
    set_official_score(report, "5-2", NOTE_STARTED_LATE)
    assert report["summary"][KEY_NOTE] == NOTE_STARTED_LATE


def test_set_official_score_drops_the_note_when_given_an_empty_one():
    report = _report()
    set_official_score(report, "5-2", NOTE_STOPPED_EARLY)
    set_official_score(report, "5-2", "   ")
    assert KEY_NOTE not in report["summary"]


def test_set_official_score_rejects_a_bad_score_without_mutating():
    report = _report()
    with pytest.raises(ValueError):
        set_official_score(report, "5:2", NOTE_STOPPED_EARLY)

    assert report["summary"] == _report()["summary"]


def test_clear_removes_all_three_keys_and_nothing_else():
    report = _report("4-2")
    set_official_score(report, "5-2", NOTE_STOPPED_EARLY)

    assert clear_official_score(report) is True
    assert report["summary"] == _report("4-2")["summary"]


def test_clear_reports_when_there_was_nothing_to_clear():
    report = _report()
    assert clear_official_score(report) is False


def test_clear_on_a_report_without_a_summary_is_a_no_op():
    assert clear_official_score({}) is False


# ------------------------------------------------------------------
# CLI — file resolution, atomic write, exit codes
# ------------------------------------------------------------------


@pytest.fixture
def reports_dir(tmp_path, monkeypatch):
    """Point the CLI at a throwaway reports directory.

    The real data/reports/ holds the bouts we filmed ourselves; these tests must
    never write there, so the module global the CLI resolves against is swapped
    for tmp_path.
    """
    monkeypatch.setattr(sos, "REPORTS_DIR", tmp_path)
    return tmp_path


def _write(path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_cli_writes_the_official_score(reports_dir):
    path = reports_dir / f"{STEM_PUBLIC}.json"
    _write(path, _report("4-2"))

    assert main([STEM_PUBLIC, "5-2"]) == EXIT_OK

    summary = _read(path)["summary"]
    assert summary[KEY_SCORE] == "5-2"
    assert summary[KEY_SOURCE] == SOURCE_MANUAL
    assert summary["final_score"] == "4-2"


def test_cli_writes_the_note(reports_dir):
    path = reports_dir / f"{STEM_PUBLIC}.json"
    _write(path, _report())

    assert main([STEM_PUBLIC, "5-2", "--note", NOTE_STOPPED_EARLY]) == EXIT_OK
    assert _read(path)["summary"][KEY_NOTE] == NOTE_STOPPED_EARLY


def test_cli_accepts_an_id_typed_with_the_json_suffix(reports_dir):
    path = reports_dir / f"{STEM_PUBLIC}.json"
    _write(path, _report())

    assert main([f"{STEM_PUBLIC}.json", "5-2"]) == EXIT_OK
    assert _read(path)["summary"][KEY_SCORE] == "5-2"


def test_cli_finds_a_report_in_the_private_dir(reports_dir):
    path = sharing.private_dir(reports_dir) / f"{STEM_PRIVATE}.json"
    _write(path, _report())

    assert main([STEM_PRIVATE, "15-9"]) == EXIT_OK
    assert _read(path)["summary"][KEY_SCORE] == "15-9"
    assert not (reports_dir / f"{STEM_PRIVATE}.json").exists()


def test_cli_rejects_a_bad_score_and_writes_nothing(reports_dir, capsys):
    path = reports_dir / f"{STEM_PUBLIC}.json"
    _write(path, _report())
    before = path.read_bytes()

    assert main([STEM_PUBLIC, "5:2"]) == EXIT_INVALID

    assert path.read_bytes() == before
    assert "invalid score" in capsys.readouterr().err


def test_cli_rejects_a_bad_score_before_looking_for_the_report(reports_dir, capsys):
    """Order matters: the format complaint is the actionable one."""
    assert main([STEM_MISSING, "5:2"]) == EXIT_INVALID
    assert "invalid score" in capsys.readouterr().err


def test_cli_exits_2_when_the_report_does_not_exist(reports_dir, capsys):
    assert main([STEM_MISSING, "5-2"]) == EXIT_NOT_FOUND

    err = capsys.readouterr().err
    assert "no such report" in err
    assert not list(reports_dir.iterdir())


def test_cli_clear_removes_the_keys(reports_dir):
    path = reports_dir / f"{STEM_PUBLIC}.json"
    _write(path, _report("4-2"))
    main([STEM_PUBLIC, "5-2", "--note", NOTE_STOPPED_EARLY])

    assert main([STEM_PUBLIC, "--clear"]) == EXIT_OK

    assert _read(path)["summary"] == _report("4-2")["summary"]


def test_cli_clear_on_a_report_with_no_official_score_is_a_no_op(reports_dir):
    path = reports_dir / f"{STEM_PUBLIC}.json"
    _write(path, _report())
    before = path.read_bytes()

    assert main([STEM_PUBLIC, "--clear"]) == EXIT_OK
    assert path.read_bytes() == before


def test_cli_clear_rejects_a_score(reports_dir):
    with pytest.raises(SystemExit):
        main([STEM_PUBLIC, "5-2", "--clear"])


def test_cli_requires_a_score_when_not_clearing(reports_dir):
    with pytest.raises(SystemExit):
        main([STEM_PUBLIC])


def test_cli_prints_both_the_observed_and_the_official_score(reports_dir, capsys):
    path = reports_dir / f"{STEM_PUBLIC}.json"
    _write(path, _report("4-2"))

    main([STEM_PUBLIC, "5-2", "--note", NOTE_STOPPED_EARLY])
    out = capsys.readouterr().out

    assert "4-2" in out
    assert "5-2" in out
    assert NOTE_STOPPED_EARLY in out


def test_cli_serialization_matches_share_report(reports_dir):
    """Same indent, same unescaped Korean, same trailing newline."""
    path = reports_dir / f"{STEM_PUBLIC}.json"
    _write(path, _report())

    main([STEM_PUBLIC, "5-2", "--note", NOTE_STOPPED_EARLY])
    text = path.read_text(encoding="utf-8")

    assert text.endswith("\n")
    assert NOTE_STOPPED_EARLY in text          # ensure_ascii=False
    assert '\n  "summary": {' in text          # indent=2
    assert text == json.dumps(_read(path), ensure_ascii=False, indent=2) + "\n"


def test_cli_leaves_no_temp_file_behind(reports_dir):
    path = reports_dir / f"{STEM_PUBLIC}.json"
    _write(path, _report())

    main([STEM_PUBLIC, "5-2"])

    assert [p.name for p in reports_dir.iterdir()] == [path.name]


# ------------------------------------------------------------------
# Report page — the official score is the result, the observed one is context
# ------------------------------------------------------------------


def _render(report: dict) -> str:
    from app.server import _jobs, app

    job_id = "official-score-render"
    _jobs[job_id] = {
        "status": "completed",
        "progress_pct": 100.0,
        "result": report,
        "mock_mode": False,
    }
    try:
        resp = TestClient(app, raise_server_exceptions=False).get(f"/report/{job_id}")
        assert resp.status_code == 200, resp.text[:2000]
        return resp.text
    finally:
        _jobs.pop(job_id, None)


#: The score card, isolated so document-wide assertions cannot pass on some
#: other part of the page (the embedded report JSON, for one, carries both
#: numbers as plain text).
_SCORE_BLOCK_START = '<!-- Score -->'
_SCORE_BLOCK_END = '<!-- Right fencer -->'

_TAG = re.compile(r"<[^>]+>")
_HANGUL = re.compile(r"[가-힣]")
#: Any element carrying .fm-num, whatever the tag — .fm-num is Barlow
#: Condensed, a digits-only face, so Korean inside one renders in a fallback.
_FM_NUM = re.compile(r'<(\w+)[^>]*\bclass="[^"]*\bfm-num\b[^"]*"[^>]*>(.*?)</\1>', re.S)


def _score_block(html: str) -> str:
    start = html.index(_SCORE_BLOCK_START)
    return html[start:html.index(_SCORE_BLOCK_END, start)]


def _text(html: str) -> str:
    """Visible text of a fragment, with runs of whitespace collapsed.

    Tags are dropped rather than replaced by a space: the numerals sit in inline
    spans, so substituting a space would invent one before the closing paren and
    hide the fact that the reader sees "(영상 내 4-2)".
    """
    return " ".join(_TAG.sub("", html).split())


@pytest.fixture
def official_html():
    report = _report("4-2")
    report["summary"][KEY_SCORE] = "5-2"
    report["summary"][KEY_SOURCE] = SOURCE_MANUAL
    report["summary"][KEY_NOTE] = NOTE_STOPPED_EARLY
    return _render(report)


def test_page_puts_the_official_score_in_the_big_numerals(official_html):
    block = _score_block(official_html)
    numerals = [m.group(2) for m in _FM_NUM.finditer(block) if "text-5xl" in m.group(0)]
    assert numerals == ["5", "2"]


def test_page_labels_both_scores_beneath(official_html):
    """The wording that tells a coach which number is which."""
    assert "경기 최종 5-2 (영상 내 4-2)" in _text(_score_block(official_html))


def test_page_marks_the_official_score_as_a_manual_entry(official_html):
    block = _score_block(official_html)
    assert "코치가 직접 입력한 공식 최종 점수입니다" in block
    assert "영상 분석 결과가 아닙니다" in block


def test_page_shows_the_recording_note(official_html):
    assert NOTE_STOPPED_EARLY in _text(_score_block(official_html))


def test_page_without_an_official_score_is_unchanged():
    block = _score_block(_render(_report("4-2")))
    numerals = [m.group(2) for m in _FM_NUM.finditer(block) if "text-5xl" in m.group(0)]

    assert numerals == ["4", "2"]
    assert "경기 최종" not in block
    assert "영상 내" not in block
    assert "코치가 직접 입력한" not in block


def test_page_keeps_the_non_numeric_label_guard():
    """A pose-only report still gets the badge, not numerals reading "연속"."""
    block = _score_block(_render(_report(CONTINUOUS_LABEL)))

    assert CONTINUOUS_LABEL in _text(block)
    assert "text-5xl" not in block


def test_page_drops_the_parenthetical_once_the_two_scores_agree():
    """The end-of-bout rule can lift the observed score up to the official one.

    Printing "(영상 내 5-2)" next to "경기 최종 5-2" would flag a gap between the
    recording and the result that has just been closed.
    """
    report = _report("5-2")
    report["summary"][KEY_SCORE] = "5-2"
    report["summary"][KEY_SOURCE] = SOURCE_MANUAL
    block = _score_block(_render(report))

    assert "경기 최종 5-2" in _text(block)
    assert "영상 내" not in block
    assert [m.group(2) for m in _FM_NUM.finditer(block) if "text-5xl" in m.group(0)] == ["5", "2"]


def test_page_renders_a_label_observed_score_beside_an_official_one():
    report = _report(CONTINUOUS_LABEL)
    report["summary"][KEY_SCORE] = "15-9"
    report["summary"][KEY_SOURCE] = SOURCE_MANUAL
    block = _score_block(_render(report))

    assert f"경기 최종 15-9 (영상 내 {CONTINUOUS_LABEL})" in _text(block)
    assert [m.group(2) for m in _FM_NUM.finditer(block) if "text-5xl" in m.group(0)] == ["15", "9"]


@pytest.mark.parametrize("final_score", ["4-2", CONTINUOUS_LABEL])
def test_no_korean_text_ends_up_inside_an_fm_num_element(final_score):
    """.fm-num is Barlow Condensed — digits only, never Korean."""
    report = _report(final_score)
    report["summary"][KEY_SCORE] = "5-2"
    report["summary"][KEY_SOURCE] = SOURCE_MANUAL
    report["summary"][KEY_NOTE] = NOTE_STOPPED_EARLY

    offenders = [
        m.group(0) for m in _FM_NUM.finditer(_render(report))
        if _HANGUL.search(_text(m.group(2)))
    ]
    assert offenders == []
