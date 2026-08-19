"""Tests for ml/clip_overlay.py — ClipOverlayGenerator."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pytest

from ml.clip_overlay import ClipOverlayGenerator
from ml.pose_estimator import PisteGate, PoseEstimator


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


def _make_piste_config(
    foot_band_work=(140, 225), pose_conf=0.35, pose_imgsz=1280, pose_max_det=8,
):
    """Build a piste config dict matching data/piste_configs/*.json."""
    piste = {
        "crop": {"x": 0, "y": 830, "w": 3840, "h": 990},
        "scale_width": 1280,
    }
    if foot_band_work is not None:
        piste["foot_band_work"] = list(foot_band_work)
    if pose_conf is not None:
        piste["pose_conf"] = pose_conf
    if pose_imgsz is not None:
        piste["pose_imgsz"] = pose_imgsz
    if pose_max_det is not None:
        piste["pose_max_det"] = pose_max_det
    return {
        "schema_version": 1,
        "source": "manual",
        "piste_number": 3,
        "source_fps": 120.0,
        "work_fps": 30,
        "piste": piste,
        "work_files": {"piste": "data/raw/own/bout_piste3.mp4"},
    }


def _write_piste_config(path, **kwargs):
    """Write a piste config JSON to `path` and return the path."""
    Path(path).write_text(
        json.dumps(_make_piste_config(**kwargs)), encoding="utf-8",
    )
    return path


def _piste_report(config_path):
    """A report dict analysed in piste mode, as generate_continuous_report writes it."""
    return {
        "meta": {
            "source_type": "coach",
            "piste_config": str(config_path),
            "video_path": "data/raw/own/bout_piste3.mp4",
        },
        "touches": [],
        "exchanges": [],
    }


def _tv_report():
    """A TV-broadcast report — no meta.piste_config at all."""
    return {
        "meta": {"source_type": "tv_broadcast", "video_path": "data/raw/tv.mp4"},
        "touches": [],
        "exchanges": [],
    }


def _make_real_yolo_result(bboxes, h=250, w=1280):
    """Build a genuine ultralytics Results with the given xyxy boxes."""
    import torch
    from ultralytics.engine.results import Results

    boxes = torch.tensor(
        [[float(x1), float(y1), float(x2), float(y2), 0.9, 0.0]
         for (x1, y1, x2, y2) in bboxes],
        dtype=torch.float32,
    ).reshape(-1, 6)
    kpts = torch.zeros((len(bboxes), 17, 3), dtype=torch.float32)
    return Results(
        np.zeros((h, w, 3), dtype=np.uint8),
        path="synthetic.jpg",
        names={0: "person"},
        boxes=boxes,
        keypoints=kpts,
    )


def _fencer_with_bbox(bbox):
    """A FencerPose carrying the given bbox (what _parse_results returns)."""
    from analyzer.models import FencerPose, PoseKeypoint

    return FencerPose(
        keypoints=[PoseKeypoint(x=0.0, y=0.0, confidence=0.0) for _ in range(17)],
        bbox=[float(v) for v in bbox],
        person_confidence=0.9,
    )


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


# ---------------------------------------------------------------------------
# Construction — pose settings plumbed to the estimator
# ---------------------------------------------------------------------------

class TestEstimatorConstruction:
    """The generator owns the pose settings that decide WHO gets a skeleton.

    A multi-piste recording puts a referee and scorekeepers in the foreground at
    higher confidence than the fencers, so these settings are the difference
    between overlaying the fencers and overlaying the referee.
    """

    @patch("ml.clip_overlay.PoseAnalyzer")
    @patch("ml.clip_overlay.PoseEstimator")
    def test_default_construction_passes_only_model_path(
        self, mock_estimator_cls, mock_analyzer_cls,
    ):
        """No new argument supplied → the estimator call is exactly as before."""
        ClipOverlayGenerator()

        mock_estimator_cls.assert_called_once_with(model_path=None)

    @patch("ml.clip_overlay.PoseAnalyzer")
    @patch("ml.clip_overlay.PoseEstimator")
    def test_existing_callers_still_pass_only_model_path(
        self, mock_estimator_cls, mock_analyzer_cls,
    ):
        """app/server.py's pad-only calls must not change the estimator."""
        ClipOverlayGenerator(pad_before=0.5, pad_after=0.0)

        mock_estimator_cls.assert_called_once_with(model_path=None)

    def test_default_construction_matches_bare_pose_estimator(self):
        """Real (unpatched) construction: attributes equal PoseEstimator()'s.

        Verifies the claim that the default path is unchanged rather than
        asserting it — nothing here loads model weights (PoseEstimator is lazy).
        """
        reference = PoseEstimator(model_path=None)
        est = ClipOverlayGenerator().estimator

        assert est.confidence == reference.confidence
        assert est.imgsz == reference.imgsz
        assert est.max_det == reference.max_det
        assert est.piste_gate is None and reference.piste_gate is None
        assert est.model_path == reference.model_path

    @patch("ml.clip_overlay.PoseAnalyzer")
    @patch("ml.clip_overlay.PoseEstimator")
    def test_explicit_params_reach_estimator(
        self, mock_estimator_cls, mock_analyzer_cls,
    ):
        gate = PisteGate(140.0, 225.0)
        ClipOverlayGenerator(
            piste_gate=gate, imgsz=1280, max_det=8, confidence=0.35,
        )

        mock_estimator_cls.assert_called_once_with(
            model_path=None, confidence=0.35, imgsz=1280, max_det=8,
            piste_gate=gate,
        )

    @patch("ml.clip_overlay.PoseAnalyzer")
    @patch("ml.clip_overlay.PoseEstimator")
    def test_only_supplied_params_are_forwarded(
        self, mock_estimator_cls, mock_analyzer_cls,
    ):
        """A partially-specified call must not pass None for the rest."""
        ClipOverlayGenerator(confidence=0.35)

        mock_estimator_cls.assert_called_once_with(
            model_path=None, confidence=0.35,
        )

    @patch("ml.clip_overlay.PoseAnalyzer")
    @patch("ml.clip_overlay.PoseEstimator")
    def test_padding_arguments_keep_their_positions(
        self, mock_estimator_cls, mock_analyzer_cls,
    ):
        """Positional order of the pre-existing parameters is preserved."""
        gen = ClipOverlayGenerator("weights.pt", 3.0, 1.5, 0.5)

        assert gen.pad_seconds == 3.0
        assert gen.pad_before == 1.5
        assert gen.pad_after == 0.5
        mock_estimator_cls.assert_called_once_with(model_path="weights.pt")


# ---------------------------------------------------------------------------
# for_report — reproduce the settings the report was analysed with
# ---------------------------------------------------------------------------

class TestForReport:
    @patch("ml.clip_overlay.PoseAnalyzer")
    @patch("ml.clip_overlay.PoseEstimator")
    def test_piste_report_applies_config_settings(
        self, mock_estimator_cls, mock_analyzer_cls, tmp_dir,
    ):
        cfg = _write_piste_config(tmp_dir / "bout_piste3.json")

        ClipOverlayGenerator.for_report(_piste_report(cfg))

        kwargs = mock_estimator_cls.call_args.kwargs
        assert kwargs["confidence"] == 0.35
        assert kwargs["imgsz"] == 1280
        assert kwargs["max_det"] == 8
        gate = kwargs["piste_gate"]
        assert isinstance(gate, PisteGate)
        assert (gate.foot_y_min, gate.foot_y_max) == (140.0, 225.0)

    @patch("ml.clip_overlay.PoseAnalyzer")
    @patch("ml.clip_overlay.PoseEstimator")
    def test_gate_matches_foot_band_work_from_config(
        self, mock_estimator_cls, mock_analyzer_cls, tmp_dir,
    ):
        """The gate is built from the config's band, not from a constant."""
        cfg = _write_piste_config(
            tmp_dir / "other.json", foot_band_work=(170, 255),
        )

        ClipOverlayGenerator.for_report(_piste_report(cfg))

        gate = mock_estimator_cls.call_args.kwargs["piste_gate"]
        assert (gate.foot_y_min, gate.foot_y_max) == (170.0, 255.0)

    @patch("ml.clip_overlay.PoseAnalyzer")
    @patch("ml.clip_overlay.PoseEstimator")
    def test_tv_report_yields_default_generator(
        self, mock_estimator_cls, mock_analyzer_cls,
    ):
        """No meta.piste_config → byte-identical to today's TV clip path."""
        ClipOverlayGenerator.for_report(_tv_report())

        mock_estimator_cls.assert_called_once_with(model_path=None)

    @patch("ml.clip_overlay.PoseAnalyzer")
    @patch("ml.clip_overlay.PoseEstimator")
    def test_report_without_meta_yields_default_generator(
        self, mock_estimator_cls, mock_analyzer_cls,
    ):
        ClipOverlayGenerator.for_report({"touches": [], "exchanges": []})

        mock_estimator_cls.assert_called_once_with(model_path=None)

    @patch("ml.clip_overlay.PoseAnalyzer")
    @patch("ml.clip_overlay.PoseEstimator")
    def test_relative_path_resolved_against_base_dir(
        self, mock_estimator_cls, mock_analyzer_cls, tmp_dir,
    ):
        """meta.piste_config is stored as typed on the CLI, so often relative."""
        cfg_dir = tmp_dir / "data" / "piste_configs"
        cfg_dir.mkdir(parents=True)
        _write_piste_config(cfg_dir / "bout_piste3.json")
        report = _piste_report("data/piste_configs/bout_piste3.json")

        ClipOverlayGenerator.for_report(report, base_dir=tmp_dir)

        assert mock_estimator_cls.call_args.kwargs["imgsz"] == 1280

    @patch("ml.clip_overlay.PoseAnalyzer")
    @patch("ml.clip_overlay.PoseEstimator")
    def test_passes_padding_through(
        self, mock_estimator_cls, mock_analyzer_cls, tmp_dir,
    ):
        cfg = _write_piste_config(tmp_dir / "bout_piste3.json")

        gen = ClipOverlayGenerator.for_report(
            _piste_report(cfg), pad_before=0.5, pad_after=0.0,
        )

        assert gen.pad_before == 0.5
        assert gen.pad_after == 0.0
        assert mock_estimator_cls.call_args.kwargs["max_det"] == 8

    @patch("ml.clip_overlay.PoseAnalyzer")
    @patch("ml.clip_overlay.PoseEstimator")
    def test_padding_passes_through_on_the_degraded_path_too(
        self, mock_estimator_cls, mock_analyzer_cls,
    ):
        gen = ClipOverlayGenerator.for_report(
            _piste_report("/nowhere/gone.json"), pad_before=0.5, pad_after=0.3,
        )

        assert (gen.pad_before, gen.pad_after) == (0.5, 0.3)
        mock_estimator_cls.assert_called_once_with(model_path=None)


class TestForReportDegradesGracefully:
    """Reports outlive their config files, and this runs inside a web request.

    Every one of these must return a usable generator: a clip drawn with default
    pose settings is a degraded clip, an exception is a 500.
    """

    @patch("ml.clip_overlay.PoseAnalyzer")
    @patch("ml.clip_overlay.PoseEstimator")
    def test_missing_config_file(
        self, mock_estimator_cls, mock_analyzer_cls, tmp_dir, caplog,
    ):
        missing = tmp_dir / "deleted_piste3.json"

        with caplog.at_level("WARNING", logger="ml.clip_overlay"):
            gen = ClipOverlayGenerator.for_report(_piste_report(missing))

        assert isinstance(gen, ClipOverlayGenerator)
        mock_estimator_cls.assert_called_once_with(model_path=None)
        assert "deleted_piste3.json" in caplog.text

    @patch("ml.clip_overlay.PoseAnalyzer")
    @patch("ml.clip_overlay.PoseEstimator")
    def test_malformed_json(
        self, mock_estimator_cls, mock_analyzer_cls, tmp_dir, caplog,
    ):
        cfg = tmp_dir / "broken.json"
        cfg.write_text('{"piste": {"foot_band_work": [140,', encoding="utf-8")

        with caplog.at_level("WARNING", logger="ml.clip_overlay"):
            gen = ClipOverlayGenerator.for_report(_piste_report(cfg))

        assert isinstance(gen, ClipOverlayGenerator)
        mock_estimator_cls.assert_called_once_with(model_path=None)
        assert "broken.json" in caplog.text

    @patch("ml.clip_overlay.PoseAnalyzer")
    @patch("ml.clip_overlay.PoseEstimator")
    def test_piste_block_absent(
        self, mock_estimator_cls, mock_analyzer_cls, tmp_dir, caplog,
    ):
        cfg = tmp_dir / "no_piste.json"
        cfg.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")

        with caplog.at_level("WARNING", logger="ml.clip_overlay"):
            gen = ClipOverlayGenerator.for_report(_piste_report(cfg))

        assert isinstance(gen, ClipOverlayGenerator)
        mock_estimator_cls.assert_called_once_with(model_path=None)
        assert "no_piste.json" in caplog.text

    @patch("ml.clip_overlay.PoseAnalyzer")
    @patch("ml.clip_overlay.PoseEstimator")
    def test_foot_band_missing_falls_back_entirely(
        self, mock_estimator_cls, mock_analyzer_cls, tmp_dir, caplog,
    ):
        """A raised max_det with no gate is worse than the default, not better."""
        cfg = _write_piste_config(tmp_dir / "no_band.json", foot_band_work=None)

        with caplog.at_level("WARNING", logger="ml.clip_overlay"):
            ClipOverlayGenerator.for_report(_piste_report(cfg))

        mock_estimator_cls.assert_called_once_with(model_path=None)
        assert "no_band.json" in caplog.text

    @pytest.mark.parametrize("band", [
        [140],                 # too short
        [140, 225, 300],       # too long
        [225, 140],            # inverted
        [140, 140],            # empty band
        "140,225",             # string
        [None, 225],           # non-numeric
        [True, False],         # bools are not pixel rows
    ])
    @patch("ml.clip_overlay.PoseAnalyzer")
    @patch("ml.clip_overlay.PoseEstimator")
    def test_unusable_foot_band_values(
        self, mock_estimator_cls, mock_analyzer_cls, band, tmp_dir,
    ):
        cfg = _write_piste_config(tmp_dir / "bad_band.json", foot_band_work=band)

        gen = ClipOverlayGenerator.for_report(_piste_report(cfg))

        assert isinstance(gen, ClipOverlayGenerator)
        mock_estimator_cls.assert_called_once_with(model_path=None)

    @patch("ml.clip_overlay.PoseAnalyzer")
    @patch("ml.clip_overlay.PoseEstimator")
    def test_missing_pose_tunables_use_piste_defaults(
        self, mock_estimator_cls, mock_analyzer_cls, tmp_dir,
    ):
        """foot_band_work alone is enough — the analysis defaults the rest.

        generate_continuous_report.py fills pose_conf/imgsz/max_det from its own
        PISTE_DEFAULT_* constants, so reproducing plain PoseEstimator defaults
        here would not match how the report was analysed.
        """
        cfg = _write_piste_config(
            tmp_dir / "band_only.json",
            pose_conf=None, pose_imgsz=None, pose_max_det=None,
        )

        ClipOverlayGenerator.for_report(_piste_report(cfg))

        kwargs = mock_estimator_cls.call_args.kwargs
        assert kwargs["confidence"] == 0.35
        assert kwargs["imgsz"] == 1280
        assert kwargs["max_det"] == 8
        assert isinstance(kwargs["piste_gate"], PisteGate)

    @pytest.mark.parametrize("bad", ["high", -1, 0, None, True])
    @patch("ml.clip_overlay.PoseAnalyzer")
    @patch("ml.clip_overlay.PoseEstimator")
    def test_unusable_pose_tunable_keeps_the_gate(
        self, mock_estimator_cls, mock_analyzer_cls, bad, tmp_dir,
    ):
        """A junk tunable must not throw away the gate — the gate is the fix."""
        cfg = _write_piste_config(tmp_dir / "bad_conf.json", pose_max_det=bad)

        ClipOverlayGenerator.for_report(_piste_report(cfg))

        kwargs = mock_estimator_cls.call_args.kwargs
        assert kwargs["max_det"] == 8
        assert isinstance(kwargs["piste_gate"], PisteGate)

    @pytest.mark.parametrize("report", [
        {}, {"meta": None}, {"meta": {"piste_config": None}},
        {"meta": {"piste_config": ""}}, {"meta": []}, {"meta": {}},
    ])
    @patch("ml.clip_overlay.PoseAnalyzer")
    @patch("ml.clip_overlay.PoseEstimator")
    def test_malformed_report_meta_never_raises(
        self, mock_estimator_cls, mock_analyzer_cls, report,
    ):
        gen = ClipOverlayGenerator.for_report(report)

        assert isinstance(gen, ClipOverlayGenerator)
        mock_estimator_cls.assert_called_once_with(model_path=None)

    @patch("ml.clip_overlay.PoseAnalyzer")
    @patch("ml.clip_overlay.PoseEstimator")
    def test_config_path_is_a_directory(
        self, mock_estimator_cls, mock_analyzer_cls, tmp_dir,
    ):
        """A path that exists but cannot be read as JSON still degrades."""
        gen = ClipOverlayGenerator.for_report(_piste_report(tmp_dir))

        assert isinstance(gen, ClipOverlayGenerator)
        mock_estimator_cls.assert_called_once_with(model_path=None)


# ---------------------------------------------------------------------------
# Regression guard — the inline YOLO call inside generate_clip
# ---------------------------------------------------------------------------

class TestInlineYoloCallMaxDet:
    """generate_clip does not go through estimate_pose; it calls _model directly.

    max_det is a YOLO *call* argument, so a hardcoded 2 makes YOLO return only
    the two highest-confidence people — the foreground referee and scorer — and
    the fencers can never be recovered downstream. Re-introducing that literal
    is exactly what a later refactor would do, hence the source-level guard.
    """

    def _generate_clip_ast(self):
        import ast
        import inspect
        import textwrap

        import ml.clip_overlay as mod

        source = textwrap.dedent(inspect.getsource(mod.ClipOverlayGenerator.generate_clip))
        return ast.parse(source)

    def _model_call_keywords(self):
        import ast

        tree = self._generate_clip_ast()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            # self.estimator._model(...)
            if (isinstance(func, ast.Attribute) and func.attr == "_model"
                    and isinstance(func.value, ast.Attribute)
                    and func.value.attr == "estimator"):
                return {kw.arg: kw.value for kw in node.keywords}
        raise AssertionError("no self.estimator._model(...) call in generate_clip")

    def test_max_det_comes_from_the_estimator_not_a_literal(self):
        import ast

        max_det = self._model_call_keywords()["max_det"]

        assert not isinstance(max_det, ast.Constant), (
            "max_det must not be a hardcoded literal — it must be "
            "self.estimator.max_det, or the piste gate is starved of candidates"
        )
        assert isinstance(max_det, ast.Attribute)
        assert max_det.attr == "max_det"
        assert isinstance(max_det.value, ast.Attribute)
        assert max_det.value.attr == "estimator"

    def test_conf_and_imgsz_also_come_from_the_estimator(self):
        import ast

        keywords = self._model_call_keywords()
        for arg, attr in (("conf", "confidence"), ("imgsz", "imgsz")):
            node = keywords[arg]
            assert isinstance(node, ast.Attribute), f"{arg} must not be a literal"
            assert node.attr == attr
            assert node.value.attr == "estimator"

    def test_no_inference_setting_is_hardcoded(self):
        """Only `verbose` may be a literal; every setting comes from the estimator.

        Stated as a whitelist so a newly hardcoded setting fails here rather
        than waiting for someone to watch a clip.
        """
        import ast

        hardcoded = {
            arg for arg, node in self._model_call_keywords().items()
            if arg != "verbose" and isinstance(node, ast.Constant)
        }
        assert hardcoded == set(), (
            f"hardcoded inference settings in generate_clip: {sorted(hardcoded)}"
        )

    @patch("ml.clip_overlay.PoseAnalyzer")
    @patch("ml.clip_overlay.PoseEstimator")
    def test_runtime_call_uses_the_estimators_max_det(
        self, mock_estimator_cls, mock_analyzer_cls, dummy_video, tmp_dir,
    ):
        mock_estimator = MagicMock()
        mock_estimator.device = "cpu"
        mock_estimator.imgsz = 1280
        mock_estimator.confidence = 0.35
        mock_estimator.max_det = 8
        mock_estimator.piste_gate = None
        mock_estimator._model = MagicMock(return_value=[_make_mock_yolo_result()])
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

        gen = ClipOverlayGenerator(
            piste_gate=PisteGate(140.0, 225.0), imgsz=1280, max_det=8,
            confidence=0.35,
        )
        gen.generate_clip(str(dummy_video), 30, 35, str(tmp_dir / "clip.mp4"))

        assert mock_estimator._model.call_count > 0
        for call in mock_estimator._model.call_args_list:
            assert call.kwargs["max_det"] == 8
            assert call.kwargs["imgsz"] == 1280
            assert call.kwargs["conf"] == 0.35


# ---------------------------------------------------------------------------
# Overlay is drawn for the gated fencers only
# ---------------------------------------------------------------------------

class TestGatedYoloResults:
    """Results.plot() draws EVERY detection it holds.

    Raising max_det for the gate therefore widens what gets drawn too, so the
    plotted result is re-indexed down to the people the gate kept.
    """

    def _generator(self, gate):
        gen = ClipOverlayGenerator.__new__(ClipOverlayGenerator)
        gen.estimator = MagicMock()
        gen.estimator.piste_gate = gate
        return gen

    def test_without_gate_results_pass_through_untouched(self):
        gen = self._generator(None)
        results = [_make_real_yolo_result([(0, 0, 10, 10), (20, 0, 30, 10)])]

        assert gen._gated_yolo_results(results, []) is results

    def test_gate_keeps_only_the_parsed_fencers(self):
        gen = self._generator(PisteGate(140.0, 225.0))
        boxes = [
            (10, 100, 60, 200),    # fencer
            (300, 10, 340, 80),    # background piste
            (700, 150, 780, 250),  # foreground referee
        ]
        results = [_make_real_yolo_result(boxes)]
        kept = [_fencer_with_bbox(boxes[0])]

        filtered = gen._gated_yolo_results(results, kept)

        assert len(filtered) == 1
        data = filtered[0].boxes.data.cpu().numpy()
        assert data.shape[0] == 1
        assert tuple(float(v) for v in data[0][:4]) == tuple(
            float(v) for v in boxes[0]
        )
        assert filtered[0].keypoints.data.shape[0] == 1

    def test_gate_keeping_both_fencers_drops_the_rest(self):
        gen = self._generator(PisteGate(140.0, 225.0))
        boxes = [
            (10, 100, 60, 200), (400, 100, 460, 200), (700, 150, 780, 250),
        ]
        results = [_make_real_yolo_result(boxes)]
        kept = [_fencer_with_bbox(boxes[0]), _fencer_with_bbox(boxes[1])]

        filtered = gen._gated_yolo_results(results, kept)

        assert filtered[0].boxes.data.shape[0] == 2

    def test_empty_gate_result_draws_no_skeleton(self):
        """Halt/occlusion: better a bare frame than someone else's skeleton."""
        gen = self._generator(PisteGate(140.0, 225.0))
        results = [_make_real_yolo_result([(700, 150, 780, 250)])]

        filtered = gen._gated_yolo_results(results, [])

        assert filtered == []
        # _annotate_frame takes the "no results" branch for this
        gen.analyzer = MagicMock()
        frame = _make_dummy_frame()
        annotated = gen._annotate_frame(frame, filtered, None, None)
        assert annotated.shape == frame.shape

    def test_all_detections_kept_returns_the_original_object(self):
        gen = self._generator(PisteGate(140.0, 225.0))
        boxes = [(10, 100, 60, 200), (400, 100, 460, 200)]
        results = [_make_real_yolo_result(boxes)]
        kept = [_fencer_with_bbox(b) for b in boxes]

        assert gen._gated_yolo_results(results, kept) is results

    def test_unfilterable_result_falls_back_to_drawing_everything(self):
        """A clip with extra skeletons beats a crashed clip."""
        gen = self._generator(PisteGate(140.0, 225.0))
        broken = MagicMock()
        type(broken).boxes = PropertyMock(side_effect=RuntimeError("boom"))
        results = [broken]

        assert gen._gated_yolo_results(results, []) is results

    def test_empty_input_is_returned_as_is(self):
        gen = self._generator(PisteGate(140.0, 225.0))

        assert gen._gated_yolo_results([], []) == []
        assert gen._gated_yolo_results(None, []) is None


class TestHudFootworkPrefersReport:
    """The HUD footwork line must come from the report, not the single frame.

    `generate_clip` analyses one frame at a time, and footwork is temporal —
    advance vs retreat is undecidable from a still — so the live values are
    effectively always None. The HUD therefore rendered "FW L:unknown R:unknown"
    even for exchanges the report had labelled fleche/advance. Observed on
    260815_Pool exchange #1 (report: fleche/advance, clip HUD: unknown/unknown).
    """

    def _lines(self, event_info, pose_analysis=None):
        from ml.clip_overlay import ClipOverlayGenerator

        gen = ClipOverlayGenerator.__new__(ClipOverlayGenerator)
        return gen._build_hud_lines(
            pose_analysis, event_info, joint_angles_left=None, joint_angles_right=None,
        )

    def test_report_footwork_is_rendered(self):
        lines = self._lines({"footwork_left": "fleche", "footwork_right": "advance"})
        assert any("fleche" in ln and "advance" in ln for ln in lines), lines

    def test_report_footwork_beats_live_analysis(self):
        class _FW:
            def __init__(self, v):
                self.footwork_type = type("T", (), {"value": v})()

        class _PA:
            footwork_left = _FW("unknown")
            footwork_right = _FW("unknown")

        lines = self._lines(
            {"footwork_left": "lunge", "footwork_right": "retreat"}, _PA(),
        )
        fw = [ln for ln in lines if ln.startswith("FW")]
        assert fw and "lunge" in fw[0] and "retreat" in fw[0], fw
        assert "unknown" not in fw[0], fw

    def test_one_side_missing_renders_placeholder(self):
        lines = self._lines({"footwork_left": "advance"})
        fw = [ln for ln in lines if ln.startswith("FW")]
        assert fw and "advance" in fw[0] and "?" in fw[0], fw

    def test_no_footwork_anywhere_emits_no_fw_line(self):
        lines = self._lines({"touch_label": "Exchange #1"})
        assert not [ln for ln in lines if ln.startswith("FW")], lines
