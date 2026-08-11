"""
Tests for ActionClassifier (VideoMAE wrapper).

These tests do NOT require model files or GPU.
They test data models, config, and frame sampling logic.
"""

import pytest
import numpy as np


# ------------------------------------------------------------------
# Import tests
# ------------------------------------------------------------------

def test_import_action_classifier():
    from ml.action_classifier import ActionClassifier
    assert ActionClassifier is not None


def test_import_action_models():
    from analyzer.models import FencingAction, ActionPrediction, ActionResult
    assert FencingAction is not None
    assert ActionPrediction is not None
    assert ActionResult is not None


# ------------------------------------------------------------------
# FencingAction enum tests
# ------------------------------------------------------------------

def test_fencing_action_values():
    from analyzer.models import FencingAction
    assert FencingAction.ATTACK.value == "attack"
    assert FencingAction.PARRY.value == "parry"
    assert FencingAction.RIPOSTE.value == "riposte"
    assert FencingAction.LUNGE.value == "lunge"
    assert FencingAction.FLECHE.value == "fleche"
    assert FencingAction.RETREAT.value == "retreat"
    assert FencingAction.ADVANCE.value == "advance"
    assert FencingAction.COUNTER_ATTACK.value == "counter_attack"
    assert FencingAction.UNKNOWN.value == "unknown"


def test_fencing_action_count():
    from analyzer.models import FencingAction
    assert len(FencingAction) == 10  # 9 actions + UNKNOWN


def test_fencing_action_from_string():
    from analyzer.models import FencingAction
    assert FencingAction("attack") == FencingAction.ATTACK
    assert FencingAction("unknown") == FencingAction.UNKNOWN
    assert FencingAction("remise") == FencingAction.REMISE


def test_fencing_action_remise():
    """REMISE should be a valid FencingAction."""
    from analyzer.models import FencingAction
    assert FencingAction.REMISE.value == "remise"
    assert FencingAction.REMISE != FencingAction.UNKNOWN


# ------------------------------------------------------------------
# Config tests
# ------------------------------------------------------------------

def test_action_config_values():
    from analyzer.config import (
        ACTION_MODEL_NAME,
        ACTION_WINDOW_SIZE,
        ACTION_STRIDE,
        ACTION_CONFIDENCE_THRESHOLD,
        ACTION_LABEL_MAP,
        ACTION_LABEL_MAP_KR,
    )
    assert ACTION_MODEL_NAME == "MCG-NJU/videomae-base-finetuned-kinetics"
    assert ACTION_WINDOW_SIZE == 16
    assert ACTION_STRIDE == 8
    assert ACTION_CONFIDENCE_THRESHOLD == 0.4
    assert len(ACTION_LABEL_MAP) == 8
    assert len(ACTION_LABEL_MAP_KR) == 9  # 9 actions (without UNKNOWN)


def test_action_label_map_facts_direction():
    """ACTION_LABEL_MAP uses FACTS direction-encoded labels."""
    from analyzer.config import ACTION_LABEL_MAP
    values = list(ACTION_LABEL_MAP.values())
    assert "attack_left" in values
    assert "attack_right" in values
    assert "remise_left" in values
    assert "remise_right" in values


def test_facts_to_action_mapping():
    """FACTS_TO_ACTION strips direction from labels."""
    from analyzer.config import FACTS_TO_ACTION
    assert FACTS_TO_ACTION["attack_left"] == ("attack", "left")
    assert FACTS_TO_ACTION["attack_right"] == ("attack", "right")
    assert FACTS_TO_ACTION["remise_left"] == ("remise", "left")
    assert FACTS_TO_ACTION["remise_right"] == ("remise", "right")
    assert len(FACTS_TO_ACTION) == 8


def test_action_label_map_kr_has_remise():
    """Korean translation map should include remise."""
    from analyzer.config import ACTION_LABEL_MAP_KR
    assert "remise" in ACTION_LABEL_MAP_KR
    assert ACTION_LABEL_MAP_KR["remise"] == "르미즈"


def test_action_label_map_facts_consistency():
    """All FACTS direction labels should have corresponding FACTS_TO_ACTION entries."""
    from analyzer.config import ACTION_LABEL_MAP, FACTS_TO_ACTION
    for idx, label in ACTION_LABEL_MAP.items():
        assert label in FACTS_TO_ACTION, f"FACTS label '{label}' missing in FACTS_TO_ACTION"


# ------------------------------------------------------------------
# Frame sampling tests
# ------------------------------------------------------------------

def test_sample_frames_exact():
    from ml.action_classifier import ActionClassifier
    ac = ActionClassifier(window_size=4, device="cpu")
    frames = [np.zeros((10, 10, 3)) for _ in range(4)]
    sampled = ac._sample_frames(frames)
    assert len(sampled) == 4


def test_sample_frames_pad():
    from ml.action_classifier import ActionClassifier
    ac = ActionClassifier(window_size=8, device="cpu")
    frames = [np.zeros((10, 10, 3)) for _ in range(3)]
    sampled = ac._sample_frames(frames)
    assert len(sampled) == 8


def test_sample_frames_downsample():
    from ml.action_classifier import ActionClassifier
    ac = ActionClassifier(window_size=4, device="cpu")
    frames = [np.ones((10, 10, 3)) * i for i in range(20)]
    sampled = ac._sample_frames(frames)
    assert len(sampled) == 4


def test_sample_frames_empty():
    from ml.action_classifier import ActionClassifier
    ac = ActionClassifier(window_size=16, device="cpu")
    sampled = ac._sample_frames([])
    assert len(sampled) == 0


# ------------------------------------------------------------------
# ActionPrediction / ActionResult serialization tests
# ------------------------------------------------------------------

def test_action_prediction_to_dict():
    from analyzer.models import FencingAction, ActionPrediction
    pred = ActionPrediction(action=FencingAction.LUNGE, confidence=0.87)
    d = pred.to_dict()
    assert d["action"] == "lunge"
    assert d["confidence"] == 0.87
    assert "direction" not in d  # None direction omitted


def test_action_prediction_with_direction():
    """ActionPrediction with FACTS direction field."""
    from analyzer.models import FencingAction, ActionPrediction
    pred = ActionPrediction(
        action=FencingAction.ATTACK, confidence=0.92, direction="left",
    )
    d = pred.to_dict()
    assert d["action"] == "attack"
    assert d["direction"] == "left"
    assert d["confidence"] == 0.92


def test_action_result_to_dict():
    from analyzer.models import FencingAction, ActionPrediction, ActionResult
    left = ActionPrediction(action=FencingAction.ATTACK, confidence=0.9)
    right = ActionPrediction(action=FencingAction.PARRY, confidence=0.7)
    result = ActionResult(
        start_frame=100,
        end_frame=115,
        left_fencer=left,
        right_fencer=right,
    )
    d = result.to_dict()
    assert d["start_frame"] == 100
    assert d["end_frame"] == 115
    assert d["left_fencer"]["action"] == "attack"
    assert d["right_fencer"]["action"] == "parry"


def test_action_result_to_dict_none_fencers():
    from analyzer.models import ActionResult
    result = ActionResult(start_frame=0, end_frame=15)
    d = result.to_dict()
    assert "left_fencer" not in d
    assert "right_fencer" not in d
    assert d["start_frame"] == 0


# ------------------------------------------------------------------
# Classifier creation test
# ------------------------------------------------------------------

def test_action_classifier_creation():
    from ml.action_classifier import ActionClassifier
    ac = ActionClassifier(device="cpu")
    assert ac.device == "cpu"
    assert ac._model is None  # Lazy loading
    assert ac.window_size == 16
    assert ac.stride == 8
