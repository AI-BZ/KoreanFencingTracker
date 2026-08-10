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
