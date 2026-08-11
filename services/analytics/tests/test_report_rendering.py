"""Tests for report rendering (HTML) and PDF export (Phase 4)."""

import builtins
import pytest
from unittest.mock import patch

from analyzer.touch_matching import NO_PRIORITY_CALL
from app.report_renderer import (
    ACTION_KR,
    LAMP_CONFLICT_KO,
    LAMP_LABEL_KO,
    OUTCOME_REASON_MUTUAL,
    OUTCOME_REASON_NO_ADVANCE,
    OUTCOME_REASON_NO_EXCHANGE,
    OUTCOME_REASON_PRIORITY_RULED_PREFIX,
    SIDE_LABEL_KO,
    ReportRenderer,
    annotate_lamp_labels,
    annotate_outcome_reasons,
    prepare_report_view,
)


# ------------------------------------------------------------------
# Shared test data
# ------------------------------------------------------------------

SAMPLE_REPORT = {
    "summary": {
        "video_path": "test.mp4",
        "final_score": "5-3",
        "total_touches": 8,
        "match_duration": "3:00",
        "weapon": "foil",
        "total_frames_analyzed": 5400,
        "analysis_time_sec": 88.5,
    },
    "touches": [
        {
            "touch_number": 1, "frame": 150, "video_timestamp": "0:05",
            "match_time": "2:55", "scorer": "left", "score_after": "1-0",
            "action_scorer": "attack", "action_confidence": 0.85,
            "action_opponent": "parry", "opponent_confidence": 0.62,
            "description": "Left scores with attack",
        },
        {
            "touch_number": 2, "frame": 450, "video_timestamp": "0:15",
            "match_time": "2:45", "scorer": "right", "score_after": "1-1",
            "action_scorer": "riposte", "action_confidence": 0.78,
            "action_opponent": None, "opponent_confidence": 0.0,
            "description": "Right scores with riposte",
        },
    ],
    "left_fencer": {
        "side": "left", "total_touches_scored": 5, "total_touches_conceded": 3,
        "action_distribution": [
            {"action": "attack", "count": 3, "percentage": 60.0},
            {"action": "riposte", "count": 2, "percentage": 40.0},
        ],
        "most_common_action": "attack", "most_common_action_pct": 60.0,
    },
    "right_fencer": {
        "side": "right", "total_touches_scored": 3, "total_touches_conceded": 5,
        "action_distribution": [
            {"action": "riposte", "count": 2, "percentage": 66.7},
            {"action": "counter_attack", "count": 1, "percentage": 33.3},
        ],
        "most_common_action": "riposte", "most_common_action_pct": 66.7,
    },
    "insights": [
        {
            "category": "action_pattern", "target": "left",
            "message": "Left 선수: 공격(attack) 비율 60%",
            "severity": "warning", "evidence": "5회 득점 중 attack 60%",
        },
    ],
    "meta": {
        "phase": 2, "pose_model": "yolo11n-pose",
        "action_model": "videomae-kinetics400",
        "pose_enabled": True, "action_enabled": True,
        "confidence_threshold": 0.4,
    },
}


# ------------------------------------------------------------------
# ReportRenderer tests
# ------------------------------------------------------------------


def test_render_html_basic():
    """render_html should produce non-empty HTML with summary section."""
    renderer = ReportRenderer()
    html = renderer.render_html(SAMPLE_REPORT)
    assert isinstance(html, str)
    assert len(html) > 100
    assert "경기 요약" in html


def test_render_html_contains_score():
    """Final score should appear in rendered HTML."""
    renderer = ReportRenderer()
    html = renderer.render_html(SAMPLE_REPORT)
    assert "5-3" in html


def test_render_html_contains_touches():
    """Touch details should be present in rendered HTML."""
    renderer = ReportRenderer()
    html = renderer.render_html(SAMPLE_REPORT)
    assert "터치 상세" in html
    assert "1-0" in html
    assert "1-1" in html


def test_render_html_contains_insights():
    """Coaching insights should be rendered."""
    renderer = ReportRenderer()
    html = renderer.render_html(SAMPLE_REPORT)
    assert "코칭 인사이트" in html
    assert "공격(attack) 비율 60%" in html


def test_render_html_korean_labels():
    """Korean action names should be present in output."""
    renderer = ReportRenderer()
    html = renderer.render_html(SAMPLE_REPORT)
    assert "공격" in html        # attack → 공격
    assert "리포스트" in html    # riposte → 리포스트


def test_render_html_empty_report():
    """Empty touches should be handled gracefully (no crash, no touch table)."""
    renderer = ReportRenderer()
    empty = {"summary": {"final_score": "0-0"}, "touches": [], "insights": []}
    html = renderer.render_html(empty)
    assert "0-0" in html
    # No touch table rendered when there are no touches
    assert "터치 상세" not in html


def test_render_html_standalone():
    """Standalone mode should include full HTML document structure."""
    renderer = ReportRenderer()
    html = renderer.render_html(SAMPLE_REPORT, standalone=True)
    assert "<!DOCTYPE html>" in html
    assert "<html" in html
    assert "</html>" in html
    assert "<title>" in html
    assert "<head>" in html
    assert "<body>" in html


# ------------------------------------------------------------------
# PDFExporter tests
# ------------------------------------------------------------------


def test_pdf_exporter_import_error():
    """PDFExporter should raise RuntimeError when weasyprint is missing."""
    from app.pdf_exporter import PDFExporter

    exporter = PDFExporter()

    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "weasyprint":
            raise ImportError("No module named 'weasyprint'")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        with pytest.raises(RuntimeError, match="weasyprint"):
            exporter.export(SAMPLE_REPORT)


# ------------------------------------------------------------------
# Edge cases
# ------------------------------------------------------------------


def test_render_html_no_fencer_stats():
    """None fencer stats should be handled gracefully."""
    renderer = ReportRenderer()
    report = {
        "summary": {"final_score": "0-0"},
        "touches": [],
        "left_fencer": None,
        "right_fencer": None,
        "insights": [],
    }
    html = renderer.render_html(report)
    assert isinstance(html, str)
    # Should not contain fencer stats section headings
    assert "왼쪽 선수" not in html
    assert "오른쪽 선수" not in html


# ------------------------------------------------------------------
# annotate_lamp_labels — display strings for the foil lamp pattern
# ------------------------------------------------------------------


def _lamp_touch(**overrides) -> dict:
    """A lamp-annotated touch as analyzer.touch_matching would leave it."""
    touch = {
        "touch_number": 1,
        "scorer": "left",
        "attack_outcome": "attack_success",
        "attacker_side": "left",
        "lamp_pattern": "double",
        "lamp_confidence": 1.0,
        "lamp_scorer_conflict": False,
        "attack_outcome_detail": "priority_won",
        "attack_outcome_detail_ko": "동시 유효타 — 우선권 인정",
    }
    touch.update(overrides)
    return touch


@pytest.mark.parametrize(
    "pattern,expected",
    [
        ("double", "양 램프"),
        ("single_left", "왼쪽 단독 램프"),
        ("single_right", "오른쪽 단독 램프"),
        ("white", "백색 램프"),
    ],
)
def test_annotate_lamp_labels_labels_every_pattern(pattern, expected):
    """Each lamp pattern gets its referee-language Korean label."""
    report = {"touches": [_lamp_touch(lamp_pattern=pattern)]}
    annotate_lamp_labels(report)
    assert report["touches"][0]["lamp_label"] == expected
    assert LAMP_LABEL_KO[pattern] == expected


def test_annotate_lamp_labels_noop_without_lamp_fields():
    """Reports predating the lamp pass (every non-foil report) are untouched."""
    plain = {
        "touch_number": 1, "scorer": "left", "attack_outcome": "unclear",
        "match_time": "2:55",
    }
    before = dict(plain)
    report = {"touches": [plain]}

    annotate_lamp_labels(report)

    assert report["touches"][0] == before
    for key in (
        "lamp_label", "lamp_confidence_pct",
        "lamp_low_confidence", "lamp_conflict_note",
    ):
        assert key not in report["touches"][0]


def test_annotate_lamp_labels_noop_on_unread_lamp():
    """A touch whose lamp could not be read gets no lamp display strings."""
    report = {"touches": [_lamp_touch(lamp_pattern=None, lamp_confidence=0.0)]}
    annotate_lamp_labels(report)
    assert "lamp_label" not in report["touches"][0]


def test_annotate_lamp_labels_flags_low_confidence():
    """A 0.40 reading is flagged so the reader can tell it apart from a 1.00."""
    report = {"touches": [
        _lamp_touch(touch_number=1, lamp_confidence=0.4),
        _lamp_touch(touch_number=2, lamp_confidence=1.0),
    ]}

    annotate_lamp_labels(report)
    low, high = report["touches"]

    assert low["lamp_low_confidence"] is True
    assert low["lamp_confidence_pct"] == 40
    assert high["lamp_low_confidence"] is False
    assert high["lamp_confidence_pct"] == 100


def test_annotate_lamp_labels_handles_missing_confidence():
    """A missing/non-numeric confidence is reported as unknown, not as 0%."""
    report = {"touches": [_lamp_touch(lamp_confidence=None)]}
    annotate_lamp_labels(report)
    touch = report["touches"][0]
    assert touch["lamp_confidence_pct"] is None
    assert touch["lamp_low_confidence"] is False


def test_annotate_lamp_labels_notes_scorer_conflict():
    """A lamp contradicting the scorer is labelled contradictory, not factual."""
    report = {"touches": [_lamp_touch(
        scorer="right", lamp_pattern="single_left", lamp_scorer_conflict=True,
        attack_outcome_detail=None, attack_outcome_detail_ko=None,
    )]}

    annotate_lamp_labels(report)
    touch = report["touches"][0]

    assert touch["lamp_conflict_note"] == LAMP_CONFLICT_KO
    assert touch["lamp_label"] == "왼쪽 단독 램프"


def test_annotate_lamp_labels_no_conflict_note_when_consistent():
    """No contradiction warning when lamp and scorer agree."""
    report = {"touches": [_lamp_touch()]}
    annotate_lamp_labels(report)
    assert report["touches"][0]["lamp_conflict_note"] is None


def test_annotate_lamp_labels_never_changes_judgment_fields():
    """Presentation only — the verdict fields are read, never rewritten."""
    judgment_keys = (
        "attack_outcome", "attacker_side", "scorer", "lamp_pattern",
        "lamp_confidence", "lamp_scorer_conflict", "attack_outcome_detail",
        "attack_outcome_detail_ko",
    )
    touch = _lamp_touch(lamp_pattern="single_right", scorer="right",
                        attack_outcome="attack_failed", attacker_side="left")
    before = {k: touch[k] for k in judgment_keys}

    annotate_lamp_labels({"touches": [touch]})

    assert {k: touch[k] for k in judgment_keys} == before


def test_annotate_lamp_labels_empty_report():
    """A report with no touches at all is handled without error."""
    assert annotate_lamp_labels({}) == {}
    assert annotate_lamp_labels({"touches": None}) == {"touches": None}


def test_prepare_report_view_annotates_lamps():
    """The lamp labels are attached by the standard view-prep entry point."""
    report = {"touches": [_lamp_touch(match_time="2:55")]}
    prepare_report_view(report)
    assert report["touches"][0]["lamp_label"] == "양 램프"


# ------------------------------------------------------------------
# annotate_outcome_reasons — lamp-informed reasons
#
# Three populations, kept apart because they mean different things:
# a single lamp (no priority ruling was ever made), a double lamp (the referee
# ruled and we could not reconstruct it), and no lamp data at all (every
# non-foil report, whose wording must not move).
# ------------------------------------------------------------------


def _named_report(touches: list, exchanges: list = None) -> dict:
    return {
        "summary": {"left_name": "LIN Youlong", "right_name": "LI Richard"},
        "touches": touches,
        "exchanges": exchanges if exchanges is not None else [],
    }


def _npc_touch(pattern: str) -> dict:
    """A touch as the lamp pass leaves it once a lone valid lamp is read."""
    return {
        "touch_number": 1,
        "scorer": "left" if pattern == "single_left" else "right",
        "attack_outcome": NO_PRIORITY_CALL,
        "attack_outcome_ko": "단독 유효타 (우선권 판정 없음)",
        "attacker_side": "unclear",
        "lamp_pattern": pattern,
        "matched_exchange_number": 1,
    }


@pytest.mark.parametrize(
    "pattern,expected_name",
    [("single_left", "LIN Youlong"), ("single_right", "LI Richard")],
)
def test_no_priority_call_reason_names_the_lone_lamp(pattern, expected_name):
    """The reason says whose single valid hit registered."""
    report = _named_report([_npc_touch(pattern)])
    annotate_outcome_reasons(report)
    reason = report["touches"][0]["outcome_reason"]
    assert reason.startswith(expected_name)
    assert "우선권을 판정할 필요가 없었습니다" in reason


def test_no_priority_call_reason_keeps_the_attacker_caveat():
    """It must not read as a full explanation — we still don't know who attacked."""
    report = _named_report([_npc_touch("single_left")])
    annotate_outcome_reasons(report)
    assert "공격을 시작한 선수는 특정하지 못했습니다" in report["touches"][0]["outcome_reason"]


def test_no_priority_call_reason_is_not_a_failure_message():
    """The whole point of the state: it stops being reported as 판별 불가."""
    report = _named_report([_npc_touch("single_right")])
    annotate_outcome_reasons(report)
    assert "판별 불가" not in report["touches"][0]["outcome_reason"]


def test_no_priority_call_reason_falls_back_to_position_label():
    """A report with no fencer names prints the side, never a bare None."""
    report = {"touches": [_npc_touch("single_left")], "exchanges": []}
    annotate_outcome_reasons(report)
    reason = report["touches"][0]["outcome_reason"]
    assert reason.startswith(SIDE_LABEL_KO["left"])
    assert "None" not in reason


@pytest.mark.parametrize(
    "attacker,matched,cause",
    [
        ("both", 1, OUTCOME_REASON_MUTUAL),
        ("unknown", 1, OUTCOME_REASON_NO_ADVANCE),
        ("both", None, OUTCOME_REASON_NO_EXCHANGE),
    ],
)
def test_double_lamp_unclear_says_the_referee_did_rule(attacker, matched, cause):
    """A genuine priority case we failed on — prefixed, with the cause kept."""
    touch = {
        "touch_number": 1, "scorer": "left", "attack_outcome": "unclear",
        "lamp_pattern": "double", "matched_exchange_number": matched,
    }
    report = _named_report(
        [touch], [{"exchange_number": 1, "attacker": attacker}],
    )
    annotate_outcome_reasons(report)
    reason = report["touches"][0]["outcome_reason"]

    assert reason == OUTCOME_REASON_PRIORITY_RULED_PREFIX + cause
    # The referee's ruling and our failure to reconstruct it are both stated.
    assert "심판이 우선권을 판정한" in reason
    assert cause in reason


@pytest.mark.parametrize(
    "attacker,matched,expected",
    [
        ("both", 1, OUTCOME_REASON_MUTUAL),
        ("unknown", 1, OUTCOME_REASON_NO_ADVANCE),
        ("both", None, OUTCOME_REASON_NO_EXCHANGE),
    ],
)
def test_unclear_without_lamp_data_is_byte_identical(attacker, matched, expected):
    """Six non-foil gallery reports have no lamps — their wording must not move."""
    touch = {
        "touch_number": 1, "scorer": "left", "attack_outcome": "unclear",
        "matched_exchange_number": matched,
    }
    report = _named_report(
        [touch], [{"exchange_number": 1, "attacker": attacker}],
    )
    annotate_outcome_reasons(report)
    assert report["touches"][0]["outcome_reason"] == expected


def test_single_lamp_unclear_is_not_treated_as_no_priority_call():
    """Only the analyzer promotes the state; the renderer must not second-guess it."""
    touch = {
        "touch_number": 1, "scorer": "left", "attack_outcome": "unclear",
        "lamp_pattern": "single_left", "matched_exchange_number": 1,
    }
    report = _named_report(
        [touch], [{"exchange_number": 1, "attacker": "both"}],
    )
    annotate_outcome_reasons(report)
    assert report["touches"][0]["outcome_reason"] == OUTCOME_REASON_MUTUAL


def test_determined_outcomes_get_no_reason():
    """Success/failure explain themselves; no reason is attached."""
    report = _named_report([{
        "touch_number": 1, "scorer": "left", "attack_outcome": "attack_success",
        "attacker_side": "left", "lamp_pattern": "double",
    }])
    annotate_outcome_reasons(report)
    assert "outcome_reason" not in report["touches"][0]


def test_annotate_outcome_reasons_never_writes_judgment_fields():
    """Presentation only — the verdict fields are read, never rewritten."""
    judgment_keys = ("attack_outcome", "attacker_side", "scorer", "lamp_pattern")
    touch = _npc_touch("single_right")
    before = {k: touch[k] for k in judgment_keys}

    annotate_outcome_reasons(_named_report([touch]))

    assert {k: touch[k] for k in judgment_keys} == before


# ------------------------------------------------------------------
# Report page — no_priority_call must render in both places
# ------------------------------------------------------------------


NO_PRIORITY_CALL_KO = "단독 유효타 (우선권 판정 없음)"

# The two rendering sites, identified by markup only they produce.
_TIMELINE_MARKER = '<span class="text-gray-400 text-xs"'
_TABLE_MARKER = 'bg-white/10 text-gray-300 border border-white/15'


def _no_priority_call_report() -> dict:
    """A one-touch foil report whose only touch had a lone valid lamp."""
    return {
        "summary": {
            "final_score": "0-1", "total_touches": 1, "match_duration": "3:00",
            "weapon": "foil", "bout_type": "de", "analysis_time_sec": 1.0,
            "total_frames_analyzed": 100,
            "left_name": "LIN Youlong", "right_name": "LI Richard",
        },
        "touches": [{
            "touch_number": 1, "frame": 900, "video_timestamp": "0:30",
            "match_time": "2:46", "scorer": "right", "score_after": "0-1",
            "attack_outcome": NO_PRIORITY_CALL,
            "attack_outcome_ko": NO_PRIORITY_CALL_KO,
            "attacker_side": "unclear", "defender_side": None,
            "matched_exchange_number": 1,
            "lamp_pattern": "single_right", "lamp_confidence": 1.0,
            "lamp_scorer_conflict": False,
            "attack_outcome_detail": "single_lamp_no_priority_call",
            "attack_outcome_detail_ko": "단독 유효타 — 우선권 판정 없음",
        }],
        "exchanges": [{
            "exchange_number": 1, "start_frame": 800, "end_frame": 880,
            "start_time": "0:26", "end_time": "0:29",
            "event_type": "unknown_exchange", "event_type_ko": "분류 미정",
            "attacker": "both", "defender": "both",
        }],
        "left_fencer": {"name": "LIN Youlong", "total_touches_scored": 0,
                        "total_touches_conceded": 1, "action_distribution": []},
        "right_fencer": {"name": "LI Richard", "total_touches_scored": 1,
                         "total_touches_conceded": 0, "action_distribution": []},
        "insights": [],
        "meta": {"phase": "7b", "pose_model": "yolo11n-pose",
                 "action_model": "rule", "fps": 30},
    }


@pytest.fixture()
def npc_report_html():
    from fastapi.testclient import TestClient
    from app.server import _jobs, app

    _jobs["npc-render-001"] = {
        "status": "completed", "progress_pct": 100.0,
        "result": _no_priority_call_report(), "mock_mode": False,
    }
    try:
        resp = TestClient(app).get("/report/npc-render-001")
        assert resp.status_code == 200
        yield resp.text
    finally:
        _jobs.pop("npc-render-001", None)


def test_page_never_calls_no_priority_call_undecidable(npc_report_html):
    """The exact string this reclassification exists to remove."""
    assert "판별 불가" not in npc_report_html


def test_timeline_renders_the_no_priority_call_label(npc_report_html):
    """Timeline card gets a positive label, not the else-branch fallback."""
    timeline_at = npc_report_html.index(_TIMELINE_MARKER)
    assert NO_PRIORITY_CALL_KO in npc_report_html[timeline_at:timeline_at + 400]


def test_detail_table_renders_the_no_priority_call_label(npc_report_html):
    """Detail table gets its own badge rather than falling through."""
    table_at = npc_report_html.index(_TABLE_MARKER)
    assert NO_PRIORITY_CALL_KO in npc_report_html[table_at:table_at + 400]


@pytest.mark.parametrize("marker", [_TIMELINE_MARKER, _TABLE_MARKER])
def test_page_keeps_the_attacker_caveat_in_both_places(npc_report_html, marker):
    """Neither site may present the touch as fully explained.

    Scoped to each rendering site — the caveat also travels in the embedded
    report JSON, so a document-wide count would pass on one site alone.
    """
    at = npc_report_html.index(marker)
    assert "공격을 시작한 선수는 특정하지 못했습니다" in npc_report_html[at:at + 400]


def test_page_does_not_render_it_as_success_or_failure(npc_report_html):
    """It is neither — the success/failure badge copy must not appear."""
    assert "공격 성공</span>" not in npc_report_html
    assert "공격 실패</span>" not in npc_report_html
