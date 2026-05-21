"""Tests for report rendering (HTML) and PDF export (Phase 4)."""

import builtins
import pytest
from unittest.mock import patch

from app.report_renderer import ReportRenderer, ACTION_KR


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
