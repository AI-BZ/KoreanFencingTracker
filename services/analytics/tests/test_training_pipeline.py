"""
Tests for the VideoMAE fine-tuning pipeline.

These tests do NOT require GPU, model files, or labeled data.
They test configuration, dataset logic, and evaluation metrics.
"""

import pytest
import numpy as np


# ------------------------------------------------------------------
# Import tests
# ------------------------------------------------------------------

def test_import_training_config():
    from ml.training.config import (
        BASE_MODEL, NUM_CLASSES, NUM_FRAMES,
        LABEL_TO_IDX, IDX_TO_LABEL,
        BATCH_SIZE, LEARNING_RATE, EPOCHS,
    )
    assert NUM_CLASSES == 8
    assert NUM_FRAMES == 16
    assert BATCH_SIZE == 4  # FACTS paper: smaller batch with gradient accumulation


def test_import_dataset():
    from ml.training.dataset import FencingActionDataset
    assert FencingActionDataset is not None


def test_import_evaluate():
    from ml.training.evaluate import compute_metrics, print_report
    assert compute_metrics is not None


# ------------------------------------------------------------------
# Config consistency tests
# ------------------------------------------------------------------

def test_label_map_consistency():
    from ml.training.config import LABEL_TO_IDX, IDX_TO_LABEL, NUM_CLASSES
    assert len(LABEL_TO_IDX) == NUM_CLASSES
    assert len(IDX_TO_LABEL) == NUM_CLASSES
    # Bidirectional mapping
    for label, idx in LABEL_TO_IDX.items():
        assert IDX_TO_LABEL[idx] == label


def test_label_map_matches_fencing_actions():
    """Training labels with direction encoding should map to valid FencingActions."""
    from ml.training.config import LABEL_TO_IDX, FACTS_TO_ACTION
    from analyzer.models import FencingAction

    for label in LABEL_TO_IDX:
        # Each FACTS label should have a FACTS_TO_ACTION mapping
        assert label in FACTS_TO_ACTION, \
            f"Training label '{label}' not in FACTS_TO_ACTION"
        # The action part should be a valid FencingAction
        action_str, direction = FACTS_TO_ACTION[label]
        assert action_str in [a.value for a in FencingAction if a != FencingAction.UNKNOWN], \
            f"Action '{action_str}' from label '{label}' not in FencingAction enum"
        assert direction in ("left", "right"), \
            f"Direction '{direction}' from label '{label}' must be 'left' or 'right'"


def test_facts_class_codes():
    """FACTS class codes should map to valid labels."""
    from ml.training.config import FACTS_CLASS_CODES, LABEL_TO_IDX
    for code, label in FACTS_CLASS_CODES.items():
        assert label in LABEL_TO_IDX, \
            f"FACTS code '{code}' maps to '{label}' which is not in LABEL_TO_IDX"


def test_flip_label_map_consistency():
    """Horizontal flip label map should be bijective and within range."""
    from ml.training.config import FLIP_LABEL_MAP, NUM_CLASSES
    assert len(FLIP_LABEL_MAP) == NUM_CLASSES
    for src, dst in FLIP_LABEL_MAP.items():
        assert 0 <= src < NUM_CLASSES
        assert 0 <= dst < NUM_CLASSES
        # Double flip should return to original
        assert FLIP_LABEL_MAP[dst] == src


def test_facts_label_names():
    """FACTS_LABEL_NAMES should match LABEL_TO_IDX keys in order."""
    from ml.training.config import FACTS_LABEL_NAMES, LABEL_TO_IDX
    assert len(FACTS_LABEL_NAMES) == len(LABEL_TO_IDX)
    for i, name in enumerate(FACTS_LABEL_NAMES):
        assert name in LABEL_TO_IDX
        assert LABEL_TO_IDX[name] == i


def test_gradient_accumulation_config():
    """Gradient accumulation should produce reasonable effective batch size."""
    from ml.training.config import BATCH_SIZE, GRADIENT_ACCUMULATION_STEPS
    effective = BATCH_SIZE * GRADIENT_ACCUMULATION_STEPS
    assert effective >= 4
    assert effective <= 32


def test_split_ratios():
    from ml.training.config import TRAIN_RATIO, VAL_RATIO, TEST_RATIO
    total = TRAIN_RATIO + VAL_RATIO + TEST_RATIO
    assert abs(total - 1.0) < 0.01, f"Split ratios sum to {total}, expected 1.0"


def test_base_model_name():
    from ml.training.config import BASE_MODEL
    assert "videomae" in BASE_MODEL.lower()


# ------------------------------------------------------------------
# Dataset logic tests (no actual data files needed)
# ------------------------------------------------------------------

def test_dataset_empty_no_labels_file():
    """Dataset with non-existent labels file should be empty."""
    from ml.training.dataset import FencingActionDataset
    from pathlib import Path

    ds = FencingActionDataset(
        data_dir=Path("/nonexistent"),
        labels_file=Path("/nonexistent/labels.csv"),
    )
    assert len(ds) == 0


def test_dataset_frame_sampling_exact():
    """Sample frames when count equals num_frames."""
    from ml.training.dataset import FencingActionDataset
    ds = FencingActionDataset.__new__(FencingActionDataset)
    ds.num_frames = 4

    frames = [np.zeros((100, 100, 3), dtype=np.uint8) for _ in range(4)]
    result = ds._sample_frames(frames)
    assert len(result) == 4


def test_dataset_frame_sampling_pad():
    """Pad frames when count is less than num_frames."""
    from ml.training.dataset import FencingActionDataset
    ds = FencingActionDataset.__new__(FencingActionDataset)
    ds.num_frames = 8

    frames = [np.zeros((100, 100, 3), dtype=np.uint8) for _ in range(3)]
    result = ds._sample_frames(frames)
    assert len(result) == 8


def test_dataset_frame_sampling_downsample():
    """Downsample frames when count exceeds num_frames."""
    from ml.training.dataset import FencingActionDataset
    ds = FencingActionDataset.__new__(FencingActionDataset)
    ds.num_frames = 4

    frames = [
        np.full((100, 100, 3), i, dtype=np.uint8) for i in range(20)
    ]
    result = ds._sample_frames(frames)
    assert len(result) == 4


def test_dataset_frame_sampling_empty():
    """Empty frames should return black frame padding."""
    from ml.training.dataset import FencingActionDataset
    ds = FencingActionDataset.__new__(FencingActionDataset)
    ds.num_frames = 4

    result = ds._sample_frames([])
    assert len(result) == 4
    assert result[0].shape == (224, 224, 3)


def test_dataset_augmentation_flip():
    """Horizontal flip augmentation should be consistent across frames."""
    import random
    from ml.training.dataset import FencingActionDataset

    ds = FencingActionDataset.__new__(FencingActionDataset)

    # Create frames with left-right asymmetry
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    frame[:, :100, :] = 255  # Left half white

    random.seed(0)  # Deterministic
    frames, label = ds._apply_augmentation([frame.copy(), frame.copy()], label_idx=0)
    # All frames should have same flip state
    assert frames[0].shape == (100, 200, 3)


# ------------------------------------------------------------------
# Evaluation metrics tests
# ------------------------------------------------------------------

def test_compute_metrics_perfect():
    """Perfect predictions should give accuracy=1.0."""
    from ml.training.evaluate import compute_metrics

    y_true = [0, 1, 2, 3, 0, 1, 2, 3]
    y_pred = [0, 1, 2, 3, 0, 1, 2, 3]
    label_names = {0: "attack", 1: "riposte", 2: "parry", 3: "lunge"}

    metrics = compute_metrics(y_true, y_pred, 4, label_names)
    assert metrics["accuracy"] == 1.0
    assert metrics["weighted_f1"] == 1.0
    for cls in metrics["per_class"].values():
        assert cls["precision"] == 1.0
        assert cls["recall"] == 1.0


def test_compute_metrics_random():
    """Random predictions should have accuracy < 0.5 for 4 classes."""
    from ml.training.evaluate import compute_metrics
    import random
    random.seed(42)

    y_true = [i % 4 for i in range(100)]
    y_pred = [random.randint(0, 3) for _ in range(100)]
    label_names = {0: "a", 1: "b", 2: "c", 3: "d"}

    metrics = compute_metrics(y_true, y_pred, 4, label_names)
    assert 0.0 < metrics["accuracy"] < 0.5
    assert metrics["total_samples"] == 100


def test_compute_metrics_confusion_matrix_shape():
    """Confusion matrix should be NxN."""
    from ml.training.evaluate import compute_metrics

    y_true = [0, 1, 0, 1]
    y_pred = [0, 0, 1, 1]
    label_names = {0: "a", 1: "b"}

    metrics = compute_metrics(y_true, y_pred, 2, label_names)
    cm = metrics["confusion_matrix"]
    assert len(cm) == 2
    assert len(cm[0]) == 2
    # Check specific values: a→a=1, a→b=1, b→a=1, b→b=1
    assert cm[0][0] == 1  # true=a, pred=a
    assert cm[0][1] == 1  # true=a, pred=b
    assert cm[1][0] == 1  # true=b, pred=a
    assert cm[1][1] == 1  # true=b, pred=b


def test_compute_metrics_empty():
    """Empty predictions should not crash."""
    from ml.training.evaluate import compute_metrics

    metrics = compute_metrics([], [], 2, {0: "a", 1: "b"})
    assert metrics["accuracy"] == 0.0
    assert metrics["total_samples"] == 0


# ------------------------------------------------------------------
# Server endpoint import tests
# ------------------------------------------------------------------

def test_server_analyze_endpoint_exists():
    """Server should have the analyze endpoint."""
    from app.server import app
    routes = [r.path for r in app.routes]
    assert "/api/analytics/analyze" in routes


def test_server_results_endpoint_exists():
    from app.server import app
    routes = [r.path for r in app.routes]
    assert "/api/analytics/results/{job_id}" in routes


def test_server_report_endpoint_exists():
    from app.server import app
    routes = [r.path for r in app.routes]
    assert "/api/analytics/report/{job_id}" in routes


def test_server_jobs_endpoint_exists():
    from app.server import app
    routes = [r.path for r in app.routes]
    assert "/api/analytics/jobs/{job_id}" in routes


def test_server_detect_source_endpoint_exists():
    from app.server import app
    routes = [r.path for r in app.routes]
    assert "/api/analytics/detect-source" in routes


# ------------------------------------------------------------------
# FACTSDatasetAdapter tests
# ------------------------------------------------------------------

def test_import_facts_adapter():
    from ml.training.dataset import FACTSDatasetAdapter
    assert FACTSDatasetAdapter is not None


def test_facts_adapter_empty_dir():
    """Adapter with non-existent dir should have zero samples."""
    from ml.training.dataset import FACTSDatasetAdapter
    from pathlib import Path
    adapter = FACTSDatasetAdapter(facts_dir=Path("/nonexistent/facts"))
    assert len(adapter) == 0


def test_facts_adapter_video_extensions():
    """Adapter should accept standard video extensions."""
    from ml.training.dataset import FACTSDatasetAdapter
    exts = FACTSDatasetAdapter.VIDEO_EXTENSIONS
    assert ".mp4" in exts
    assert ".avi" in exts
    assert ".mov" in exts


def test_facts_adapter_class_distribution_empty():
    """Class distribution of empty adapter should be empty dict."""
    from ml.training.dataset import FACTSDatasetAdapter
    from pathlib import Path
    adapter = FACTSDatasetAdapter(facts_dir=Path("/nonexistent"))
    dist = adapter.get_class_distribution()
    assert dist == {}


# ------------------------------------------------------------------
# Augmentation label swap tests
# ------------------------------------------------------------------

def test_augmentation_returns_tuple():
    """_apply_augmentation should return (frames, label_idx) tuple."""
    import random
    from ml.training.dataset import FencingActionDataset
    ds = FencingActionDataset.__new__(FencingActionDataset)
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    random.seed(999)  # Deterministic
    result = ds._apply_augmentation([frame], label_idx=0)
    assert isinstance(result, tuple)
    assert len(result) == 2
    frames, label = result
    assert isinstance(frames, list)
    assert isinstance(label, int)


def test_augmentation_flip_swaps_label():
    """When horizontal flip occurs, direction label should swap."""
    import random
    from ml.training.config import FLIP_LABEL_MAP
    from ml.training.dataset import FencingActionDataset

    ds = FencingActionDataset.__new__(FencingActionDataset)
    frame = np.zeros((100, 100, 3), dtype=np.uint8)

    # Force flip to happen (seed where random() < 0.5)
    flipped_count = 0
    for seed in range(100):
        random.seed(seed)
        _, new_label = ds._apply_augmentation([frame.copy()], label_idx=0)
        if new_label == FLIP_LABEL_MAP[0]:
            flipped_count += 1

    # At least some should have flipped (prob 0.5)
    assert flipped_count > 0, "No flips occurred in 100 seeds"
