"""
Tests for PoseEstimator (YOLO11-Pose wrapper).

Model-dependent tests are skipped if yolo11n-pose.pt is not available
or if ultralytics is not installed.
"""

import pytest
import numpy as np
from pathlib import Path

try:
    import ultralytics  # noqa: F401
    HAS_ULTRALYTICS = True
except ImportError:
    HAS_ULTRALYTICS = False


# ------------------------------------------------------------------
# Import tests
# ------------------------------------------------------------------

def test_import_pose_estimator():
    from ml.pose_estimator import PoseEstimator
    assert PoseEstimator is not None


def test_import_pose_models():
    from analyzer.models import PoseKeypoint, FencerPose, PoseResult
    assert PoseKeypoint is not None
    assert FencerPose is not None
    assert PoseResult is not None


# ------------------------------------------------------------------
# Config tests
# ------------------------------------------------------------------

def test_pose_config_values():
    from analyzer.config import (
        POSE_MODEL_PATH,
        POSE_CONFIDENCE_THRESHOLD,
        POSE_KEYPOINT_CONFIDENCE,
        POSE_MAX_PERSONS,
        POSE_IMGSZ,
        DEVICE_PREFERENCE,
    )
    assert POSE_CONFIDENCE_THRESHOLD == 0.5
    assert POSE_KEYPOINT_CONFIDENCE == 0.3
    assert POSE_MAX_PERSONS == 2
    assert POSE_IMGSZ == 640
    assert isinstance(POSE_MODEL_PATH, Path)
    assert DEVICE_PREFERENCE in ("mps", "cuda", "cpu")


# ------------------------------------------------------------------
# Model creation tests
# ------------------------------------------------------------------

def test_pose_estimator_creation():
    from ml.pose_estimator import PoseEstimator
    pe = PoseEstimator(device="cpu")
    assert pe.device == "cpu"
    assert pe._model is None  # Lazy loading: not loaded yet


def test_pose_estimator_custom_params():
    from ml.pose_estimator import PoseEstimator
    pe = PoseEstimator(
        confidence=0.7,
        device="cpu",
        imgsz=320,
    )
    assert pe.confidence == 0.7
    assert pe.imgsz == 320


# ------------------------------------------------------------------
# Data model serialization tests
# ------------------------------------------------------------------

def test_pose_keypoint_creation():
    from analyzer.models import PoseKeypoint
    kp = PoseKeypoint(x=100.0, y=200.0, confidence=0.95)
    assert kp.x == 100.0
    assert kp.y == 200.0
    assert kp.confidence == 0.95


def test_fencer_pose_to_dict():
    from analyzer.models import PoseKeypoint, FencerPose
    keypoints = [PoseKeypoint(x=float(i), y=float(i), confidence=0.9) for i in range(17)]
    pose = FencerPose(
        keypoints=keypoints,
        bbox=[10.0, 20.0, 100.0, 300.0],
        person_confidence=0.85,
        side="left",
    )
    d = pose.to_dict()
    assert d["side"] == "left"
    assert d["person_confidence"] == 0.85
    assert len(d["keypoints"]) == 17
    assert d["keypoints"][0] == [0.0, 0.0, 0.9]
    assert d["bbox"] == [10.0, 20.0, 100.0, 300.0]


def test_pose_result_to_dict():
    from analyzer.models import PoseKeypoint, FencerPose, PoseResult
    kps = [PoseKeypoint(x=0.0, y=0.0, confidence=0.5) for _ in range(17)]
    fencer = FencerPose(keypoints=kps, bbox=[0, 0, 100, 200], person_confidence=0.9, side="right")
    result = PoseResult(frame_idx=42, fencers=[fencer], inference_time_ms=15.3)
    d = result.to_dict()
    assert d["frame_idx"] == 42
    assert d["inference_time_ms"] == 15.3
    assert len(d["fencers"]) == 1
    assert d["fencers"][0]["side"] == "right"


def test_pose_result_empty_fencers():
    from analyzer.models import PoseResult
    result = PoseResult(frame_idx=0, fencers=[])
    d = result.to_dict()
    assert d["fencers"] == []


# ------------------------------------------------------------------
# Inference tests (require model file)
# ------------------------------------------------------------------

YOLO_MODEL_PATH = Path(__file__).resolve().parent.parent / "ml" / "models" / "yolo11n-pose.pt"


@pytest.mark.skipif(
    not HAS_ULTRALYTICS or not YOLO_MODEL_PATH.exists(),
    reason="ultralytics not installed or yolo11n-pose.pt not available",
)
def test_pose_estimator_black_frame():
    from ml.pose_estimator import PoseEstimator
    pe = PoseEstimator(device="cpu")
    black = np.zeros((480, 640, 3), dtype=np.uint8)
    result = pe.estimate_pose(black, frame_idx=0)
    assert result.frame_idx == 0
    assert isinstance(result.fencers, list)
    assert result.inference_time_ms >= 0


@pytest.mark.skipif(
    not HAS_ULTRALYTICS or not YOLO_MODEL_PATH.exists(),
    reason="ultralytics not installed or yolo11n-pose.pt not available",
)
def test_pose_estimator_batch():
    from ml.pose_estimator import PoseEstimator
    pe = PoseEstimator(device="cpu")
    frames = [np.zeros((480, 640, 3), dtype=np.uint8) for _ in range(3)]
    results = pe.estimate_poses_batch(frames, start_idx=10)
    assert len(results) == 3
    assert results[0].frame_idx == 10
    assert results[2].frame_idx == 12


# ------------------------------------------------------------------
# PisteGate — synthetic YOLO results (no model required)
#
# All coordinates below are piste WORK-FILE pixels, matching PisteGate.
# The synthetic frame mimics a 1280x300 piste crop.
# ------------------------------------------------------------------

FRAME_W = 1280
FRAME_H = 300

# Foot-band groups measured on the reference clip: background piste people sit
# well above the band, the target fencers inside it, referee/scorekeeper below.
BAND = (130.0, 215.0)


class _FakeTensor:
    """Stands in for a torch tensor: supports .cpu().numpy()."""

    def __init__(self, array):
        self._array = np.asarray(array, dtype=np.float32)

    def cpu(self):
        return self

    def numpy(self):
        return self._array


class _FakeField:
    def __init__(self, array):
        self.data = _FakeTensor(array)


class _FakeResult:
    """Minimal stand-in for an ultralytics Results object."""

    def __init__(self, keypoints, boxes, orig_shape=(FRAME_H, FRAME_W)):
        self.keypoints = _FakeField(keypoints) if keypoints is not None else None
        self.boxes = _FakeField(boxes) if boxes is not None else None
        if orig_shape is not None:
            self.orig_shape = orig_shape


def _make_person(foot_y, cx, conf=0.8, ankle_conf=0.9, y2=None, half_w=25.0):
    """
    Build one (keypoints, box) pair.

    Args:
        foot_y: y of both ankle keypoints.
        cx: bbox x-center.
        conf: person detection confidence.
        ankle_conf: ankle keypoint confidence (<= 0.3 makes them unusable).
        y2: bbox bottom; defaults to foot_y.
    """
    kps = np.zeros((17, 3), dtype=np.float32)
    for idx in range(15):
        kps[idx] = (cx, foot_y - 100.0, 0.9)
    kps[15] = (cx - 5.0, foot_y, ankle_conf)
    kps[16] = (cx + 5.0, foot_y, ankle_conf)

    bottom = foot_y if y2 is None else y2
    box = [cx - half_w, bottom - 120.0, cx + half_w, bottom, conf, 0.0]
    return kps, box


def _fake_results(people, orig_shape=(FRAME_H, FRAME_W)):
    """Wrap _make_person outputs into a list-of-Results like YOLO returns."""
    keypoints = np.stack([p[0] for p in people])
    boxes = np.asarray([p[1] for p in people], dtype=np.float32)
    return [_FakeResult(keypoints, boxes, orig_shape=orig_shape)]


def _gated_estimator(band=BAND, max_det=8):
    from ml.pose_estimator import PoseEstimator, PisteGate
    return PoseEstimator(
        device="cpu",
        max_det=max_det,
        piste_gate=PisteGate(foot_y_min=band[0], foot_y_max=band[1]),
    )


def test_pose_estimator_gate_defaults():
    """Constructor defaults must reproduce the pre-gate behaviour."""
    from ml.pose_estimator import PoseEstimator
    from analyzer.config import POSE_MAX_PERSONS

    pe = PoseEstimator(device="cpu")
    assert pe.max_det == POSE_MAX_PERSONS
    assert pe.piste_gate is None


def test_piste_gate_dataclass_fields():
    from ml.pose_estimator import PisteGate
    gate = PisteGate(foot_y_min=130.0, foot_y_max=215.0)
    assert gate.foot_y_min == 130.0
    assert gate.foot_y_max == 215.0


def test_piste_gate_keeps_inside_band_rejects_outside():
    """Only people whose foot_y falls inside the band survive."""
    pe = _gated_estimator()
    results = _fake_results([
        _make_person(foot_y=40.0, cx=300.0),    # background piste — too high
        _make_person(foot_y=150.0, cx=400.0),   # target fencer
        _make_person(foot_y=190.0, cx=900.0),   # target fencer
        _make_person(foot_y=240.0, cx=600.0),   # foreground referee — too low
    ])

    fencers = pe._parse_results(results)

    assert len(fencers) == 2
    assert {f.bbox[3] for f in fencers} == {150.0, 190.0}
    assert {f.side for f in fencers} == {"left", "right"}


def test_piste_gate_rejects_bottom_clipped_person():
    """
    Low-confidence ankles + bbox touching the frame bottom => foreground person,
    rejected outright even though the bbox bottom would fall inside the band.
    """
    pe = _gated_estimator()
    clipped = _make_person(
        foot_y=200.0, cx=600.0, ankle_conf=0.05, y2=float(FRAME_H)
    )
    results = _fake_results([
        _make_person(foot_y=160.0, cx=300.0),
        clipped,
    ])

    fencers = pe._parse_results(results)

    assert len(fencers) == 1
    assert fencers[0].bbox[3] == 160.0


def test_piste_gate_picks_smallest_foot_y_not_highest_confidence():
    """
    Regression guard: the intruder with the HIGHEST confidence must lose.
    Measured foreground referees score 0.84-0.90 vs 0.55-0.85 for real fencers,
    so any confidence-based tie-break would select the referee.
    """
    pe = _gated_estimator()
    results = _fake_results([
        _make_person(foot_y=150.0, cx=350.0, conf=0.55),   # fencer
        _make_person(foot_y=175.0, cx=880.0, conf=0.62),   # fencer
        _make_person(foot_y=210.0, cx=640.0, conf=0.95),   # referee, top conf
    ])

    fencers = pe._parse_results(results)

    assert len(fencers) == 2
    assert sorted(f.bbox[3] for f in fencers) == [150.0, 175.0]
    assert 0.95 not in {f.person_confidence for f in fencers}


def test_piste_gate_single_survivor_side_left():
    """One survivor left of the frame midpoint is assigned 'left'."""
    pe = _gated_estimator()
    results = _fake_results([
        _make_person(foot_y=160.0, cx=200.0),   # left half (< 640)
        _make_person(foot_y=300.0, cx=700.0),   # below the band
    ])

    fencers = pe._parse_results(results)

    assert len(fencers) == 1
    assert fencers[0].side == "left"


def test_piste_gate_single_survivor_side_right():
    """One survivor right of the frame midpoint is assigned 'right'."""
    pe = _gated_estimator()
    results = _fake_results([
        _make_person(foot_y=160.0, cx=1100.0),  # right half (> 640)
        _make_person(foot_y=300.0, cx=200.0),   # below the band
    ])

    fencers = pe._parse_results(results)

    assert len(fencers) == 1
    assert fencers[0].side == "right"


def test_piste_gate_falls_back_to_bbox_y2_when_ankles_low_confidence():
    """
    Unconfident ankles but not clipped by the frame bottom: the bbox bottom is
    used as foot_y, so band membership is decided by y2.
    """
    pe = _gated_estimator()
    results = _fake_results([
        # ankles unusable; y2=170 lands inside the band -> kept
        _make_person(foot_y=999.0, cx=300.0, ankle_conf=0.1, y2=170.0),
        # ankles unusable; y2=250 is below the band -> rejected
        _make_person(foot_y=999.0, cx=900.0, ankle_conf=0.1, y2=250.0),
    ])

    fencers = pe._parse_results(results)

    assert len(fencers) == 1
    assert fencers[0].bbox[3] == 170.0
    assert fencers[0].side == "left"


def test_piste_gate_missing_orig_shape_skips_clip_rejection():
    """
    Without orig_shape the bottom-edge test cannot run, so a person whose bbox
    reaches the frame bottom is judged on the band alone.

    The same person is rejected when orig_shape IS present, which isolates the
    clipping rule from the band rule (here the frame is 200px tall, so a bbox
    bottom of 200 is both inside the band and flush with the frame edge).
    """
    person = _make_person(foot_y=999.0, cx=300.0, ankle_conf=0.05, y2=200.0)

    # No orig_shape -> clipping cannot be detected -> band decides -> kept.
    kept = _gated_estimator()._parse_results(_fake_results([person], orig_shape=None))
    assert len(kept) == 1
    assert kept[0].bbox[3] == 200.0

    # orig_shape says the frame is 200px tall -> bbox is clipped -> rejected.
    clipped = _gated_estimator()._parse_results(
        _fake_results([person], orig_shape=(200, FRAME_W))
    )
    assert clipped == []


def test_piste_gate_none_preserves_two_person_behaviour():
    """gate=None: unchanged top-2 parse and x-center side assignment."""
    from ml.pose_estimator import PoseEstimator

    pe = PoseEstimator(device="cpu")
    results = _fake_results([
        _make_person(foot_y=240.0, cx=900.0),   # would fail the band
        _make_person(foot_y=40.0, cx=300.0),    # would fail the band
    ])

    fencers = pe._parse_results(results)

    assert len(fencers) == 2
    assert fencers[0].side == "right"   # cx 900 > cx 300
    assert fencers[1].side == "left"


def test_piste_gate_none_keeps_single_person_left_default():
    """gate=None: the historical unconditional 'left' default is untouched."""
    from ml.pose_estimator import PoseEstimator

    pe = PoseEstimator(device="cpu")
    # cx well right of the midpoint; the non-gate path still says "left".
    results = _fake_results([_make_person(foot_y=160.0, cx=1200.0)])

    fencers = pe._parse_results(results)

    assert len(fencers) == 1
    assert fencers[0].side == "left"


def test_piste_gate_none_caps_at_pose_max_persons():
    """gate=None: more candidates than POSE_MAX_PERSONS are still truncated."""
    from ml.pose_estimator import PoseEstimator
    from analyzer.config import POSE_MAX_PERSONS

    pe = PoseEstimator(device="cpu")
    results = _fake_results([
        _make_person(foot_y=150.0, cx=200.0),
        _make_person(foot_y=160.0, cx=600.0),
        _make_person(foot_y=170.0, cx=1000.0),
    ])

    fencers = pe._parse_results(results)

    assert len(fencers) == POSE_MAX_PERSONS


def test_estimate_pose_passes_self_max_det_to_yolo():
    """The YOLO call must use self.max_det, not the module constant."""
    from ml.pose_estimator import PoseEstimator

    captured = {}

    def fake_model(frame, **kwargs):
        captured.update(kwargs)
        return _fake_results([_make_person(foot_y=160.0, cx=300.0)])

    pe = PoseEstimator(device="cpu", max_det=8)
    pe._model = fake_model
    pe._load_model = lambda: None

    result = pe.estimate_pose(np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8))

    assert captured["max_det"] == 8
    assert result.frame_idx == 0
