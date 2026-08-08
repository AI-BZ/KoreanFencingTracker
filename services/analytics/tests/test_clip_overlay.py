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
    """Test the _compute_touch_clip_bounds() helper from server.py.

    New behavior (real-touch anchoring): the OCR score change lags the actual
    touch by a measured median of ~2.8s, so the clip is anchored on the preceding
    exchange's min_distance_frame (real touch), not the delayed OCR score frame.

    fps=30 constants: DELAY=120, FORWARD_TOL=15, POST_TOUCH_BUFFER=9,
    MAX_LEAD=240, FALLBACK_LEAD=84, MIN_CLIP=45.
    """

    def _call(self, **kwargs):
        from app.server import _compute_touch_clip_bounds
        return _compute_touch_clip_bounds(**kwargs)

    def test_delayed_touch_matches_preceding_exchange(self):
        """(a) A touch delayed ~2.8s matches the preceding exchange, and the clip
        END lands on min_distance_frame (real touch), before the OCR score frame."""
        exchanges = [
            {"start_frame": 4000, "end_frame": 4100,
             "min_distance_frame": 4090, "exchange_number": 15},
        ]
        touch = 4100 + int(2.8 * 30)  # 4184: score change 2.8s after exchange end
        start, end = self._call(
            touch_frame=touch, exchanges=exchanges, clock_events=[], fps=30.0,
        )
        # END anchored on real touch (min_distance_frame + 0.3s buffer), NOT touch
        assert end == 4090 + 9
        assert end < touch, "clip must end at real touch, before delayed OCR frame"
        # START at exchange start
        assert start == 4000

    def test_no_matching_exchange_fallback(self):
        """(b) No exchange within the delay window → fallback [touch-2.8s .. touch]."""
        exchanges = [
            {"start_frame": 900, "end_frame": 1000,
             "min_distance_frame": 990, "exchange_number": 1},
        ]
        # Touch 1000 frames (33s) after the only exchange → no match
        start, end = self._call(
            touch_frame=2000, exchanges=exchanges, clock_events=[], fps=30.0,
        )
        assert end == 2000                 # anchored on the OCR frame (low confidence)
        assert start == 2000 - int(2.8 * 30)  # median-delay lead-in

    def test_lead_in_cap_clamps_long_exchange(self):
        """(c) Degenerate long (~36s) exchange → start clamped to END - 8s."""
        exchanges = [
            {"start_frame": 0, "end_frame": 1080,          # 36s @30fps
             "min_distance_frame": 1070, "exchange_number": 1},
        ]
        touch = 1080 + 30  # 1s delay
        start, end = self._call(
            touch_frame=touch, exchanges=exchanges, clock_events=[], fps=30.0,
        )
        assert end == 1070 + 9
        # lead-in capped at PHRASE_MAX_LEAD_SEC (8s = 240 frames)
        assert end - start == int(8.0 * 30)
        assert start == end - int(8.0 * 30)

    def test_match_delay_boundary(self):
        """(d) Touch exactly at the 4s delay boundary matches; just beyond falls back."""
        exchanges = [
            {"start_frame": 4900, "end_frame": 5000,
             "min_distance_frame": 4990, "exchange_number": 1},
        ]
        # Exactly at boundary (gap == 4.0s) → match
        start_in, end_in = self._call(
            touch_frame=5000 + int(4.0 * 30), exchanges=exchanges,
            clock_events=[], fps=30.0,
        )
        assert start_in == 4900
        assert end_in == 4990 + 9
        # One frame beyond → no match → fallback
        touch_out = 5000 + int(4.0 * 30) + 1
        start_out, end_out = self._call(
            touch_frame=touch_out, exchanges=exchanges, clock_events=[], fps=30.0,
        )
        assert end_out == touch_out
        assert start_out == touch_out - int(2.8 * 30)

    def test_clock_event_preferred_as_start(self):
        """Matched exchange + recent allez → allez frame becomes the clip start."""
        exchanges = [
            {"start_frame": 6000, "end_frame": 6100,
             "min_distance_frame": 6090, "exchange_number": 1},
        ]
        clock_events = [
            {"frame": 6050, "event": "allez", "time": "2:10"},
            {"frame": 6200, "event": "allez", "time": "2:05"},  # after end → ignored
        ]
        start, end = self._call(
            touch_frame=6150, exchanges=exchanges,
            clock_events=clock_events, fps=30.0,
        )
        assert start == 6050          # allez preferred over exchange start (6000)
        assert end == 6090 + 9

    def test_asymmetric_fallback_no_data(self):
        """No exchanges, no clock events → [touch-2.8s .. touch]."""
        start, end = self._call(
            touch_frame=1000, exchanges=[], clock_events=[], fps=30.0,
        )
        assert start == 1000 - int(2.8 * 30)
        assert end == 1000

    def test_min_clip_length_enforced(self):
        """When the anchored window is very short, ensure minimum clip length."""
        exchanges = [
            {"start_frame": 998, "end_frame": 1000,
             "min_distance_frame": 999, "exchange_number": 1},
        ]
        start, end = self._call(
            touch_frame=1010, exchanges=exchanges, clock_events=[], fps=30.0,
        )
        assert end - start >= int(1.5 * 30)

    def test_exchange_without_min_distance_frame_uses_end(self):
        """Legacy exchange dict lacking min_distance_frame → END = exchange end."""
        exchanges = [
            {"start_frame": 4239, "end_frame": 4347, "exchange_number": 15},
        ]
        start, end = self._call(
            touch_frame=4350, exchanges=exchanges, clock_events=[], fps=30.0,
        )
        assert start == 4239
        assert end == 4347  # falls back to exchange end (no real-touch anchor)

    def test_pose_end_slightly_after_touch_still_matches(self):
        """Pose exchange end a few frames after the OCR touch → forward tolerance."""
        exchanges = [
            {"start_frame": 15900, "end_frame": 15954,
             "min_distance_frame": 15948, "exchange_number": 4},
        ]
        touch = 15950  # 4 frames before the pose exchange end (within 0.5s tol)
        start, end = self._call(
            touch_frame=touch, exchanges=exchanges, clock_events=[], fps=30.0,
        )
        # Matched (NOT the fallback lead-in of touch - 2.8s)
        assert start == 15900
        assert end == 15948 + 9


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
