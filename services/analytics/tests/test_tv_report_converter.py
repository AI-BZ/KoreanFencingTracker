"""Tests for TV report converter.

Covers:
- Tie/draw handling (13-13 should say "draw", not pick a winner)
- match_time_remaining priority (scoreboard time over video time)
- Video truncation warnings (expected 15, actual max 13)
- Normal match (no warnings)
"""

import pytest

from app.tv_report_converter import tv_ocr_to_match_report, _generate_warnings
from analyzer.tv_overlay_ocr import TVTouchEvent


def _make_event(
    frame: int,
    timestamp: float,
    scorer: str,
    score_before: str,
    score_after: str,
    period: int = 1,
    match_time_remaining: str = None,
) -> TVTouchEvent:
    """Helper to create a TVTouchEvent."""
    return TVTouchEvent(
        frame=frame,
        timestamp=timestamp,
        scorer=scorer,
        score_before=score_before,
        score_after=score_after,
        period=period,
        match_time_remaining=match_time_remaining,
    )


class TestTieHandling:
    """Test that tied scores produce draw messages, not false winners."""

    def test_draw_13_13(self):
        """13-13 tie should produce 'draw' message, not pick a winner."""
        events = [
            _make_event(100, 3.3, "left", "0-0", "1-0"),
            _make_event(200, 6.6, "right", "1-0", "1-1"),
        ]
        summary = {
            "total_touches": 2,
            "final_score": "1-1",
            "left_touches": 1,
            "right_touches": 1,
        }

        report = tv_ocr_to_match_report(
            events=events,
            summary=summary,
            left_name="LEE",
            right_name="ESAKI",
            video_path="test.mp4",
            analysis_time_sec=10.0,
            total_frames=600,
        )

        # Find the score_flow insight
        score_flow = [i for i in report["insights"] if i["category"] == "score_flow"]
        assert len(score_flow) == 1
        assert "draw" in score_flow[0]["message"].lower()
        assert "won" not in score_flow[0]["message"].lower()

    def test_left_wins(self):
        """Left fencer winning should say they won."""
        events = [
            _make_event(100, 3.3, "left", "0-0", "1-0"),
            _make_event(200, 6.6, "left", "1-0", "2-0"),
            _make_event(300, 10.0, "right", "2-0", "2-1"),
        ]
        summary = {
            "total_touches": 3,
            "final_score": "2-1",
            "left_touches": 2,
            "right_touches": 1,
        }

        report = tv_ocr_to_match_report(
            events=events,
            summary=summary,
            left_name="LEE",
            right_name="ESAKI",
            video_path="test.mp4",
            analysis_time_sec=10.0,
            total_frames=600,
        )

        score_flow = [i for i in report["insights"] if i["category"] == "score_flow"]
        assert len(score_flow) == 1
        assert "LEE won" in score_flow[0]["message"]

    def test_right_wins(self):
        """Right fencer winning should say they won."""
        events = [
            _make_event(100, 3.3, "right", "0-0", "0-1"),
            _make_event(200, 6.6, "right", "0-1", "0-2"),
            _make_event(300, 10.0, "left", "0-2", "1-2"),
        ]
        summary = {
            "total_touches": 3,
            "final_score": "1-2",
            "left_touches": 1,
            "right_touches": 2,
        }

        report = tv_ocr_to_match_report(
            events=events,
            summary=summary,
            left_name="LEE",
            right_name="ESAKI",
            video_path="test.mp4",
            analysis_time_sec=10.0,
            total_frames=600,
        )

        score_flow = [i for i in report["insights"] if i["category"] == "score_flow"]
        assert len(score_flow) == 1
        assert "ESAKI won" in score_flow[0]["message"]


class TestMatchTimeRemaining:
    """Test that match_time_remaining from scoreboard is preferred over video timestamp."""

    def test_match_time_used_when_available(self):
        """When match_time_remaining is set, it should be used as match_time."""
        events = [
            _make_event(100, 3.3, "left", "0-0", "1-0", match_time_remaining="2:28"),
            _make_event(200, 6.6, "right", "1-0", "1-1", match_time_remaining="1:55"),
        ]
        summary = {
            "total_touches": 2,
            "final_score": "1-1",
            "left_touches": 1,
            "right_touches": 1,
        }

        report = tv_ocr_to_match_report(
            events=events,
            summary=summary,
            left_name="A",
            right_name="B",
            video_path="test.mp4",
            analysis_time_sec=5.0,
            total_frames=300,
        )

        assert report["touches"][0]["match_time"] == "2:28"
        assert report["touches"][1]["match_time"] == "1:55"
        # video_timestamp should still be the video time
        assert report["touches"][0]["video_timestamp"] == "0:03"

    def test_video_time_fallback(self):
        """When match_time_remaining is None, video timestamp is used."""
        events = [
            _make_event(100, 3.3, "left", "0-0", "1-0", match_time_remaining=None),
        ]
        summary = {
            "total_touches": 1,
            "final_score": "1-0",
            "left_touches": 1,
            "right_touches": 0,
        }

        report = tv_ocr_to_match_report(
            events=events,
            summary=summary,
            left_name="A",
            right_name="B",
            video_path="test.mp4",
            analysis_time_sec=5.0,
            total_frames=300,
        )

        # Both should be video time when match_time_remaining is None
        assert report["touches"][0]["match_time"] == report["touches"][0]["video_timestamp"]


class TestVideoTruncationWarning:
    """Test video truncation detection and warnings."""

    def test_truncated_video_warning(self):
        """Expected 15-point DE bout, but max score is 13 → warning."""
        events = [
            _make_event(i * 100, i * 3.3, "left" if i % 2 == 0 else "right",
                        f"{i//2}-{(i-1)//2}", f"{(i+1)//2}-{i//2}")
            for i in range(5)
        ]
        summary = {
            "total_touches": 5,
            "final_score": "13-13",
            "left_touches": 3,
            "right_touches": 2,
        }

        report = tv_ocr_to_match_report(
            events=events,
            summary=summary,
            left_name="LEE",
            right_name="ESAKI",
            video_path="test.mp4",
            analysis_time_sec=10.0,
            total_frames=600,
            expected_final_score=15,
        )

        assert len(report["warnings"]) == 1
        w = report["warnings"][0]
        assert w["type"] == "video_truncated"
        assert "truncated" in w["message"].lower()
        assert "15" in w["message"]
        assert w["severity"] == "warning"

    def test_normal_match_no_warning(self):
        """15-point match reaching 15 → no warning."""
        events = [
            _make_event(100, 3.3, "left", "14-10", "15-10"),
        ]
        summary = {
            "total_touches": 1,
            "final_score": "15-10",
            "left_touches": 1,
            "right_touches": 0,
        }

        report = tv_ocr_to_match_report(
            events=events,
            summary=summary,
            left_name="A",
            right_name="B",
            video_path="test.mp4",
            analysis_time_sec=5.0,
            total_frames=300,
            expected_final_score=15,
        )

        assert report["warnings"] == []

    def test_no_expected_score_no_warning(self):
        """When expected_final_score is None, no truncation check."""
        events = [
            _make_event(100, 3.3, "left", "0-0", "1-0"),
        ]
        summary = {
            "total_touches": 1,
            "final_score": "1-0",
            "left_touches": 1,
            "right_touches": 0,
        }

        report = tv_ocr_to_match_report(
            events=events,
            summary=summary,
            left_name="A",
            right_name="B",
            video_path="test.mp4",
            analysis_time_sec=5.0,
            total_frames=300,
        )

        assert report["warnings"] == []

    def test_pool_truncation(self):
        """Pool bout expected 5, max score 3 → warning."""
        warnings = _generate_warnings("3-2", expected_final_score=5)
        assert len(warnings) == 1
        assert warnings[0]["type"] == "video_truncated"


class TestNoTouchesGate:
    """Test the low-confidence gate: 0 touches → error-level warning.

    Regression: OCR-failed broadcast analyses were saved as trustworthy
    even when the scoreboard could not be read (0 touches detected).
    """

    def test_zero_touches_produces_error_warning(self):
        """No events + total_touches 0 → error-level no_touches_detected warning."""
        summary = {
            "total_touches": 0,
            "final_score": "0-0",
            "left_touches": 0,
            "right_touches": 0,
        }

        report = tv_ocr_to_match_report(
            events=[],
            summary=summary,
            left_name="LEE",
            right_name="ESAKI",
            video_path="test.mp4",
            analysis_time_sec=10.0,
            total_frames=600,
        )

        gate = [w for w in report["warnings"] if w["type"] == "no_touches_detected"]
        assert len(gate) == 1
        assert gate[0]["severity"] == "error"

    def test_normal_touches_no_gate_warning(self):
        """Detected touches → no no_touches_detected warning."""
        events = [
            _make_event(100, 3.3, "left", "0-0", "1-0"),
            _make_event(200, 6.6, "right", "1-0", "1-1"),
        ]
        summary = {
            "total_touches": 2,
            "final_score": "1-1",
            "left_touches": 1,
            "right_touches": 1,
        }

        report = tv_ocr_to_match_report(
            events=events,
            summary=summary,
            left_name="LEE",
            right_name="ESAKI",
            video_path="test.mp4",
            analysis_time_sec=10.0,
            total_frames=600,
        )

        gate = [w for w in report["warnings"] if w["type"] == "no_touches_detected"]
        assert gate == []

    def test_zero_touches_gate_direct(self):
        """_generate_warnings with total_touches=0 emits the error warning."""
        warnings = _generate_warnings("0-0", expected_final_score=None, total_touches=0)
        assert len(warnings) == 1
        assert warnings[0]["type"] == "no_touches_detected"
        assert warnings[0]["severity"] == "error"

    def test_gate_skipped_when_touches_none(self):
        """Direct callers omitting total_touches keep prior behavior (no gate)."""
        warnings = _generate_warnings("3-2", expected_final_score=None)
        assert warnings == []


class TestReportStructure:
    """Test that report has correct structure with new fields."""

    def test_warnings_field_exists(self):
        """Report should always have a 'warnings' key."""
        events = [
            _make_event(100, 3.3, "left", "0-0", "1-0"),
        ]
        summary = {
            "total_touches": 1,
            "final_score": "1-0",
            "left_touches": 1,
            "right_touches": 0,
        }

        report = tv_ocr_to_match_report(
            events=events,
            summary=summary,
            left_name="A",
            right_name="B",
            video_path="test.mp4",
            analysis_time_sec=5.0,
            total_frames=300,
        )

        assert "warnings" in report
        assert isinstance(report["warnings"], list)

    def test_gender_age_group_in_summary(self):
        """Summary should have gender and age_group fields."""
        events = [
            _make_event(100, 3.3, "left", "0-0", "1-0"),
        ]
        summary = {
            "total_touches": 1,
            "final_score": "1-0",
            "left_touches": 1,
            "right_touches": 0,
        }

        report = tv_ocr_to_match_report(
            events=events,
            summary=summary,
            left_name="A",
            right_name="B",
            video_path="test.mp4",
            analysis_time_sec=5.0,
            total_frames=300,
        )

        assert "gender" in report["summary"]
        assert "age_group" in report["summary"]

    def test_video_timestamp_and_match_time_separate(self):
        """Each touch should have both video_timestamp and match_time."""
        events = [
            _make_event(100, 3.3, "left", "0-0", "1-0", match_time_remaining="2:28"),
        ]
        summary = {
            "total_touches": 1,
            "final_score": "1-0",
            "left_touches": 1,
            "right_touches": 0,
        }

        report = tv_ocr_to_match_report(
            events=events,
            summary=summary,
            left_name="A",
            right_name="B",
            video_path="test.mp4",
            analysis_time_sec=5.0,
            total_frames=300,
        )

        touch = report["touches"][0]
        assert "video_timestamp" in touch
        assert "match_time" in touch
        assert touch["video_timestamp"] != touch["match_time"]
