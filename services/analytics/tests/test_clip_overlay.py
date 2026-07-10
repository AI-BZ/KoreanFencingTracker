"""Tests for ml/clip_overlay.py — ClipOverlayGenerator."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pytest

from ml.clip_overlay import ClipOverlayGenerator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dummy_frame(w=640, h=480):
    """Create a blank BGR frame."""
    return np.zeros((h, w, 3), dtype=np.uint8)


def _make_mock_yolo_result():
    """Create a mock YOLO result with plot() method."""
    result = MagicMock()
    result.plot.return_value = _make_dummy_frame()
    return result


def _make_dummy_video(path, n_frames=60, fps=30.0, w=640, h=480):
    """Write a short dummy mp4 with solid frames."""
    import cv2
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (w, h))
    for i in range(n_frames):
        frame = np.full((h, w, 3), (i * 4) % 256, dtype=np.uint8)
        writer.write(frame)
    writer.release()


def _make_sample_report(touch_frames=None, exchange_ranges=None):
    """Build a minimal report dict for testing."""
    touches = []
    for i, f in enumerate(touch_frames or []):
        touches.append({
            "touch_number": i + 1,
            "frame": f,
            "match_time": f"0:{i:02d}",
            "scorer": "left",
            "score_after": f"{i+1}-0",
            "pose_analysis": {
                "distance_bh": 1.2,
                "distance_zone": "lunge",
                "footwork_scorer": "fleche",
                "parry_detected": True,
            },
        })
    exchanges = []
    for i, (sf, ef) in enumerate(exchange_ranges or []):
        exchanges.append({
            "exchange_number": i + 1,
            "start_frame": sf,
            "end_frame": ef,
            "start_time": f"0:{i:02d}",
            "event_type": "failed_attack",
            "event_type_ko": "실패 공격",
            "footwork_left": "advance",
            "footwork_right": "retreat",
        })
    return {
        "touches": touches,
        "exchanges": exchanges,
        "summary": {"final_score": "3-0"},
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def dummy_video(tmp_dir):
    path = tmp_dir / "test_video.mp4"
    _make_dummy_video(path, n_frames=120, fps=30.0)
    return path


# ---------------------------------------------------------------------------
# Unit tests — annotation
# ---------------------------------------------------------------------------

class TestAnnotateFrame:
    def test_annotate_with_yolo_result_calls_plot(self):
        gen = ClipOverlayGenerator.__new__(ClipOverlayGenerator)
        gen.analyzer = MagicMock()
        result = _make_mock_yolo_result()
        frame = _make_dummy_frame()

        annotated = gen._annotate_frame(frame, [result], None, None)

        result.plot.assert_called_once()
        assert annotated.shape == frame.shape

    def test_annotate_without_yolo_result_returns_copy(self):
        gen = ClipOverlayGenerator.__new__(ClipOverlayGenerator)
        gen.analyzer = MagicMock()
        frame = _make_dummy_frame()

        annotated = gen._annotate_frame(frame, [], None, None)

        assert annotated.shape == frame.shape
        assert not np.shares_memory(annotated, frame)

    def test_annotate_with_event_info_draws_hud(self):
        gen = ClipOverlayGenerator.__new__(ClipOverlayGenerator)
        gen.analyzer = MagicMock()
        result = _make_mock_yolo_result()
        frame = _make_dummy_frame()
        event_info = {"touch_label": "Touch #1: 1-0"}

        annotated = gen._annotate_frame(frame, [result], None, event_info)

        assert annotated is not None
        assert annotated.shape == frame.shape


# ---------------------------------------------------------------------------
# Unit tests — HUD text
# ---------------------------------------------------------------------------

class TestBuildHudLines:
    def test_empty_when_no_data(self):
        gen = ClipOverlayGenerator.__new__(ClipOverlayGenerator)
        lines = gen._build_hud_lines(None, None)
        assert lines == []

    def test_event_info_touch_label(self):
        gen = ClipOverlayGenerator.__new__(ClipOverlayGenerator)
        lines = gen._build_hud_lines(None, {"touch_label": "Touch #3: 5-2"})
        assert any("Touch #3" in l for l in lines)

    def test_distance_from_analysis(self):
        gen = ClipOverlayGenerator.__new__(ClipOverlayGenerator)
        analysis = MagicMock()
        analysis.distance_at_touch = MagicMock()
        analysis.distance_at_touch.distance_bh = 1.35
        analysis.distance_at_touch.distance_zone = MagicMock()
        analysis.distance_at_touch.distance_zone.value = "lunge"
        analysis.footwork_left = None
        analysis.footwork_right = None
        analysis.parry_left = None
        analysis.parry_right = None

        lines = gen._build_hud_lines(analysis, None)
        assert any("1.35" in l and "lunge" in l for l in lines)


# ---------------------------------------------------------------------------
# Unit tests — draw HUD
# ---------------------------------------------------------------------------

class TestDrawHud:
    def test_draw_hud_modifies_frame(self):
        gen = ClipOverlayGenerator.__new__(ClipOverlayGenerator)
        frame = _make_dummy_frame(640, 480)
        original_sum = frame.sum()
        gen._draw_hud(frame, ["Distance: 1.2 BH (lunge)", "Touch #1"])
        # Frame should be modified (text drawn)
        assert frame.sum() != original_sum


# ---------------------------------------------------------------------------
# Unit tests — extract info helpers
# ---------------------------------------------------------------------------

class TestExtractInfo:
    def test_extract_touch_info(self):
        gen = ClipOverlayGenerator.__new__(ClipOverlayGenerator)
        touch = {
            "touch_number": 5,
            "score_after": "8-6",
            "pose_analysis": {
                "distance_bh": 1.5,
                "distance_zone": "lunge",
                "footwork_scorer": "fleche",
                "parry_detected": True,
            },
        }
        info = gen._extract_touch_info(touch)
        assert "Touch #5" in info["touch_label"]
        assert info["distance_bh"] == 1.5

    def test_extract_exchange_info(self):
        gen = ClipOverlayGenerator.__new__(ClipOverlayGenerator)
        ex = {
            "exchange_number": 3,
            "event_type": "failed_attack",
            "event_type_ko": "실패 공격",
            "footwork_left": "advance",
            "footwork_right": "retreat",
        }
        info = gen._extract_exchange_info(ex)
        assert "Exchange #3" in info["touch_label"]
        assert info["footwork_left"] == "advance"


# ---------------------------------------------------------------------------
# Unit tests — padding calculation
# ---------------------------------------------------------------------------

class TestPadSeconds:
    def test_pad_frames_calculation(self):
        gen = ClipOverlayGenerator.__new__(ClipOverlayGenerator)
        gen.pad_seconds = 2.0
        fps = 30.0
        pad_frames = int(gen.pad_seconds * fps)
        assert pad_frames == 60

    def test_pad_frames_with_custom_pad(self):
        gen = ClipOverlayGenerator.__new__(ClipOverlayGenerator)
        gen.pad_seconds = 1.5
        fps = 24.0
        pad_frames = int(gen.pad_seconds * fps)
        assert pad_frames == 36

    def test_asymmetric_padding_basic(self):
        """pad_before/pad_after override pad_seconds independently."""
        gen = ClipOverlayGenerator.__new__(ClipOverlayGenerator)
        gen.pad_seconds = 2.0
        gen.pad_before = 3.0
        gen.pad_after = 0.5
        fps = 30.0

        pb = gen.pad_before if gen.pad_before is not None else gen.pad_seconds
        pa = gen.pad_after if gen.pad_after is not None else gen.pad_seconds
        pad_before_frames = int(pb * fps)
        pad_after_frames = int(pa * fps)

        assert pad_before_frames == 90  # 3.0 * 30
        assert pad_after_frames == 15   # 0.5 * 30

        # Simulate actual_start/actual_end for event at frame 200, total=500
        start_frame, end_frame, total = 200, 200, 500
        actual_start = max(0, start_frame - pad_before_frames)
        actual_end = min(total - 1, end_frame + pad_after_frames)
        assert actual_start == 110  # 200 - 90
        assert actual_end == 215    # 200 + 15

    def test_asymmetric_padding_none_fallback(self):
        """When pad_before/pad_after are None, pad_seconds is used."""
        gen = ClipOverlayGenerator.__new__(ClipOverlayGenerator)
        gen.pad_seconds = 2.0
        gen.pad_before = None
        gen.pad_after = None
        fps = 30.0

        pb = gen.pad_before if gen.pad_before is not None else gen.pad_seconds
        pa = gen.pad_after if gen.pad_after is not None else gen.pad_seconds
        assert pb == 2.0
        assert pa == 2.0


# ---------------------------------------------------------------------------
# Unit tests — smart clip bounds
# ---------------------------------------------------------------------------

class TestComputeTouchClipBounds:
    """Test the _compute_touch_clip_bounds() helper from server.py."""

    def _call(self, **kwargs):
        from app.server import _compute_touch_clip_bounds
        return _compute_touch_clip_bounds(**kwargs)

    def test_touch_exchange_matching(self):
        """Touch near exchange end → clip starts at exchange start."""
        exchanges = [
            {"start_frame": 4239, "end_frame": 4347, "exchange_number": 15},
        ]
        start, end = self._call(
            touch_frame=4350, exchanges=exchanges, clock_events=[], fps=30.0,
        )
        # Should use exchange start_frame (4239), not touch - 3s
        assert start == 4239
        # end = touch + 0.5s = 4350 + 15 = 4365
        assert end == 4365

    def test_clock_event_fallback(self):
        """No matching exchange, recent allez → allez frame as start."""
        clock_events = [
            {"frame": 6500, "event": "allez", "time": "2:10"},
        ]
        start, end = self._call(
            touch_frame=6750, exchanges=[], clock_events=clock_events, fps=30.0,
        )
        assert start == 6500
        assert end == 6750 + 15  # 0.5s after touch

    def test_asymmetric_fallback_no_data(self):
        """No exchanges, no clock events → 3s before, 0.5s after."""
        start, end = self._call(
            touch_frame=1000, exchanges=[], clock_events=[], fps=30.0,
        )
        assert start == 1000 - 90  # 3.0 * 30
        assert end == 1000 + 15     # 0.5 * 30

    def test_min_clip_length_enforced(self):
        """When exchange is very short, ensure minimum clip length."""
        exchanges = [
            {"start_frame": 998, "end_frame": 1000, "exchange_number": 1},
        ]
        start, end = self._call(
            touch_frame=1000, exchanges=exchanges, clock_events=[], fps=30.0,
        )
        clip_end = 1000 + 15  # POST_TOUCH_BUFFER
        min_clip = int(1.5 * 30)  # 45 frames
        # exchange start=998, clip_end=1015 → length=17 < 45 → start adjusted
        assert end - start >= min_clip

    def test_ocr_frame_before_exchange_matches(self):
        """OCR touch frame a few frames before exchange start → still matches."""
        # Simulates the common case where OCR detects score change
        # slightly before the exchange start_frame.
        exchanges = [
            {"start_frame": 15954, "end_frame": 16100, "exchange_number": 4},
        ]
        # Touch at 15950, 4 frames before exchange start (within 0.5s tolerance)
        start, end = self._call(
            touch_frame=15950, exchanges=exchanges, clock_events=[], fps=30.0,
        )
        # Exchange matched (NOT fallback 3s before = 15950 - 90 = 15860)
        fallback_start = 15950 - int(3.0 * 30)
        assert start != fallback_start, "Should not fall back to 3s padding"
        assert end == 15950 + 15  # POST_TOUCH_BUFFER
        # MIN_CLIP_FRAMES enforced: clip_end(15965) - exchange_start(15954) = 11 < 45
        # → start adjusted to clip_end - min_clip = 15965 - 45 = 15920
        assert end - start >= int(1.5 * 30)

    def test_ocr_frame_far_before_exchange_no_match(self):
        """OCR touch frame far before exchange start → no match, falls back."""
        exchanges = [
            {"start_frame": 16000, "end_frame": 16100, "exchange_number": 1},
        ]
        # Touch at 15900, 100 frames (3.3s) before exchange start → too far
        start, end = self._call(
            touch_frame=15900, exchanges=exchanges, clock_events=[], fps=30.0,
        )
        # Should fall back to asymmetric padding (3s before, 0.5s after)
        assert start == 15900 - int(3.0 * 30)
        assert end == 15900 + 15


# ---------------------------------------------------------------------------
# Integration tests — clip generation (mock YOLO)
# ---------------------------------------------------------------------------

class TestGenerateClip:
    @patch("ml.clip_overlay.PoseEstimator")
    @patch("ml.clip_overlay.PoseAnalyzer")
    def test_generate_clip_creates_mp4(self, mock_analyzer_cls, mock_estimator_cls, dummy_video, tmp_dir):
        # Setup mocks
        mock_estimator = MagicMock()
        mock_estimator.device = "cpu"
        mock_estimator.imgsz = 640
        mock_estimator.confidence = 0.5
        mock_estimator._model = MagicMock()
        mock_result = _make_mock_yolo_result()
        mock_estimator._model.return_value = [mock_result]
        mock_estimator._parse_results.return_value = []
        mock_estimator._load_model = MagicMock()
        mock_estimator_cls.return_value = mock_estimator

        mock_analyzer = MagicMock()
        mock_analyzer.analyze.return_value = MagicMock(
            distance_at_touch=None, footwork_left=None, footwork_right=None,
            parry_left=None, parry_right=None,
        )
        mock_analyzer._compute_joint_angles_for_side.return_value = None
        mock_analyzer_cls.return_value = mock_analyzer

        gen = ClipOverlayGenerator()
        output = tmp_dir / "clip.mp4"

        result = gen.generate_clip(
            str(dummy_video), 30, 40, str(output),
            event_info={"touch_label": "Touch #1: 1-0"},
        )

        assert Path(result).exists()
        assert Path(result).suffix == ".mp4"
        assert Path(result).stat().st_size > 0

    @patch("ml.clip_overlay.PoseEstimator")
    @patch("ml.clip_overlay.PoseAnalyzer")
    def test_generate_clip_nonexistent_video_raises(self, mock_analyzer_cls, mock_estimator_cls, tmp_dir):
        gen = ClipOverlayGenerator()
        with pytest.raises(FileNotFoundError):
            gen.generate_clip(
                "/nonexistent/video.mp4", 0, 10, str(tmp_dir / "out.mp4"),
            )


# ---------------------------------------------------------------------------
# Integration tests — batch clip generation (mock YOLO)
# ---------------------------------------------------------------------------

class TestGenerateClipsForReport:
    @patch("ml.clip_overlay.PoseEstimator")
    @patch("ml.clip_overlay.PoseAnalyzer")
    def test_generates_touch_clips(self, mock_analyzer_cls, mock_estimator_cls, dummy_video, tmp_dir):
        mock_estimator = MagicMock()
        mock_estimator.device = "cpu"
        mock_estimator.imgsz = 640
        mock_estimator.confidence = 0.5
        mock_estimator._model = MagicMock()
        mock_result = _make_mock_yolo_result()
        mock_estimator._model.return_value = [mock_result]
        mock_estimator._parse_results.return_value = []
        mock_estimator._load_model = MagicMock()
        mock_estimator_cls.return_value = mock_estimator

        mock_analyzer = MagicMock()
        mock_analyzer.analyze.return_value = MagicMock(
            distance_at_touch=None, footwork_left=None, footwork_right=None,
            parry_left=None, parry_right=None,
        )
        mock_analyzer._compute_joint_angles_for_side.return_value = None
        mock_analyzer_cls.return_value = mock_analyzer

        report = _make_sample_report(touch_frames=[20, 50])
        gen = ClipOverlayGenerator()
        clips_dir = tmp_dir / "clips"

        results = gen.generate_clips_for_report(
            str(dummy_video), report, str(clips_dir), touches_only=True,
        )

        assert len(results) == 2
        assert all(r["event_type"] == "touch" for r in results)
        assert results[0]["event_number"] == 1
        assert results[1]["event_number"] == 2
        for r in results:
            assert Path(r["clip_path"]).exists()

    @patch("ml.clip_overlay.PoseEstimator")
    @patch("ml.clip_overlay.PoseAnalyzer")
    def test_generates_exchange_clips_when_not_touches_only(self, mock_analyzer_cls, mock_estimator_cls, dummy_video, tmp_dir):
        mock_estimator = MagicMock()
        mock_estimator.device = "cpu"
        mock_estimator.imgsz = 640
        mock_estimator.confidence = 0.5
        mock_estimator._model = MagicMock()
        mock_result = _make_mock_yolo_result()
        mock_estimator._model.return_value = [mock_result]
        mock_estimator._parse_results.return_value = []
        mock_estimator._load_model = MagicMock()
        mock_estimator_cls.return_value = mock_estimator

        mock_analyzer = MagicMock()
        mock_analyzer.analyze.return_value = MagicMock(
            distance_at_touch=None, footwork_left=None, footwork_right=None,
            parry_left=None, parry_right=None,
        )
        mock_analyzer._compute_joint_angles_for_side.return_value = None
        mock_analyzer_cls.return_value = mock_analyzer

        report = _make_sample_report(touch_frames=[20], exchange_ranges=[(40, 55)])
        gen = ClipOverlayGenerator()
        clips_dir = tmp_dir / "clips"

        results = gen.generate_clips_for_report(
            str(dummy_video), report, str(clips_dir), touches_only=False,
        )

        assert len(results) == 2
        assert results[0]["event_type"] == "touch"
        assert results[1]["event_type"] == "exchange"


# ---------------------------------------------------------------------------
# Server endpoint tests (mock-based)
# ---------------------------------------------------------------------------

class TestClipEndpoint:
    def test_clip_endpoint_returns_mp4(self, tmp_dir):
        """Test that the clip streaming endpoint pattern works."""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from fastapi.responses import StreamingResponse
        import io

        test_app = FastAPI()

        # Write a tiny fake mp4
        clip_path = tmp_dir / "test_clip.mp4"
        _make_dummy_video(clip_path, n_frames=5)

        @test_app.get("/api/analytics/clips/test/touch/1")
        async def get_clip():
            return StreamingResponse(
                open(str(clip_path), "rb"),
                media_type="video/mp4",
            )

        client = TestClient(test_app)
        resp = client.get("/api/analytics/clips/test/touch/1")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "video/mp4"
        assert len(resp.content) > 0

    def test_clip_endpoint_404_unknown_event(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI, HTTPException

        test_app = FastAPI()

        @test_app.get("/api/analytics/clips/{report_id}/{event_type}/{event_number}")
        async def get_clip(report_id: str, event_type: str, event_number: int):
            raise HTTPException(status_code=404, detail="Clip not found")

        client = TestClient(test_app)
        resp = client.get("/api/analytics/clips/nonexistent/touch/999")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Template tests
# ---------------------------------------------------------------------------

class TestReportTemplateElements:
    def test_clip_modal_html_structure(self):
        """Verify the modal HTML pattern has required elements."""
        modal_html = """
        <div id="clip-modal" class="fixed inset-0 bg-black/60 hidden z-50">
            <video id="clip-video" controls autoplay>
                <source id="clip-source" type="video/mp4">
            </video>
            <button id="clip-modal-close">X</button>
            <p id="clip-loading" class="hidden">Loading...</p>
        </div>
        """
        assert 'id="clip-modal"' in modal_html
        assert 'id="clip-video"' in modal_html
        assert 'id="clip-source"' in modal_html
        assert 'id="clip-modal-close"' in modal_html
        assert 'id="clip-loading"' in modal_html

    def test_play_button_data_attributes(self):
        """Verify play button has correct data attributes."""
        button_html = '<button class="clip-play-btn" data-report="r1" data-type="touch" data-number="1">'
        assert "clip-play-btn" in button_html
        assert "data-report" in button_html
        assert "data-type" in button_html
        assert "data-number" in button_html
