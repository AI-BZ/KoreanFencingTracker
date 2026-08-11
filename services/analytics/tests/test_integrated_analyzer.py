"""
Tests for IntegratedAnalyzer (2-pass enrichment).

These tests do NOT require model files.
They test EnrichedMatchEvent creation, conversion, and disabled mode.
"""

import pytest
import numpy as np


# ------------------------------------------------------------------
# Import tests
# ------------------------------------------------------------------

def test_import_integrated_analyzer():
    from ml.integrated_analyzer import IntegratedAnalyzer
    assert IntegratedAnalyzer is not None


def test_import_enriched_match_event():
    from analyzer.models import EnrichedMatchEvent
    assert EnrichedMatchEvent is not None


# ------------------------------------------------------------------
# IntegratedAnalyzer creation tests
# ------------------------------------------------------------------

def test_integrated_analyzer_disabled_mode():
    """IntegratedAnalyzer with both pose and action disabled."""
    from ml.integrated_analyzer import IntegratedAnalyzer
    ia = IntegratedAnalyzer(enable_pose=False, enable_action=False)
    assert ia.video_processor is not None
    assert ia.enable_pose is False
    assert ia.enable_action is False


def test_integrated_analyzer_default():
    """Default IntegratedAnalyzer has pose and action enabled."""
    from ml.integrated_analyzer import IntegratedAnalyzer
    ia = IntegratedAnalyzer(enable_pose=True, enable_action=True)
    assert ia.enable_pose is True
    assert ia.enable_action is True


def test_integrated_analyzer_lazy_loading():
    """Pose/action estimators should not be loaded until accessed."""
    from ml.integrated_analyzer import IntegratedAnalyzer
    ia = IntegratedAnalyzer(enable_pose=False, enable_action=False)
    assert ia._pose_estimator is None
    assert ia._action_classifier is None


# ------------------------------------------------------------------
# EnrichedMatchEvent tests
# ------------------------------------------------------------------

def test_enriched_match_event_creation():
    from analyzer.models import EnrichedMatchEvent
    e = EnrichedMatchEvent(
        frame=100,
        video_timestamp="0:03.33",
        match_time="3:00",
        event_type="left_lamp",
        lamp_red=True,
        lamp_green=False,
        score_before="0-0",
        score_after="1-0",
        scorer="left",
        description="Left lamp -> left scored",
    )
    assert e.frame == 100
    assert e.pose_left is None
    assert e.pose_right is None
    assert e.action_left is None
    assert e.action_right is None


def test_enriched_match_event_from_match_event():
    from analyzer.models import MatchEvent, EnrichedMatchEvent
    me = MatchEvent(
        frame=200,
        video_timestamp="0:06.67",
        match_time="2:45",
        event_type="right_lamp",
        lamp_red=False,
        lamp_green=True,
        score_before="1-0",
        score_after="1-1",
        scorer="right",
        description="Right lamp -> right scored",
    )
    enriched = EnrichedMatchEvent.from_match_event(me)
    assert enriched.frame == 200
    assert enriched.scorer == "right"
    assert enriched.score_after == "1-1"
    assert enriched.pose_left is None
    assert enriched.action_result is None


def test_enriched_match_event_to_dict_backward_compat():
    """to_dict should omit None pose/action fields."""
    from analyzer.models import EnrichedMatchEvent
    e = EnrichedMatchEvent(
        frame=50,
        video_timestamp="0:01.67",
        match_time="3:00",
        event_type="left_lamp",
        lamp_red=True,
        lamp_green=False,
        score_before="0-0",
        score_after="1-0",
    )
    d = e.to_dict()
    assert "frame" in d
    assert "scorer" in d
    assert "pose_left" not in d
    assert "pose_right" not in d
    assert "action_left" not in d
    assert "action_right" not in d
    assert "pose_sequence" not in d
    assert "action_result" not in d


def test_enriched_match_event_to_dict_with_pose():
    """to_dict should include pose data when present."""
    from analyzer.models import (
        EnrichedMatchEvent,
        PoseKeypoint,
        FencerPose,
    )
    keypoints = [PoseKeypoint(x=0.0, y=0.0, confidence=0.9) for _ in range(17)]
    pose = FencerPose(
        keypoints=keypoints,
        bbox=[10.0, 20.0, 100.0, 300.0],
        person_confidence=0.85,
        side="left",
    )
    e = EnrichedMatchEvent(
        frame=100,
        video_timestamp="0:03.33",
        match_time="3:00",
        event_type="left_lamp",
        lamp_red=True,
        lamp_green=False,
        score_before="0-0",
        score_after="1-0",
        pose_left=pose,
    )
    d = e.to_dict()
    assert "pose_left" in d
    assert d["pose_left"]["side"] == "left"
    assert "pose_right" not in d


def test_enriched_match_event_to_dict_with_action():
    """to_dict should include action data when present."""
    from analyzer.models import (
        EnrichedMatchEvent,
        FencingAction,
        ActionPrediction,
    )
    pred = ActionPrediction(action=FencingAction.LUNGE, confidence=0.87)
    e = EnrichedMatchEvent(
        frame=100,
        video_timestamp="0:03.33",
        match_time="3:00",
        event_type="left_lamp",
        lamp_red=True,
        lamp_green=False,
        score_before="0-0",
        score_after="1-0",
        action_left=pred,
    )
    d = e.to_dict()
    assert "action_left" in d
    assert d["action_left"]["action"] == "lunge"
    assert d["action_left"]["confidence"] == 0.87
    assert "action_right" not in d


# ------------------------------------------------------------------
# Config tests
# ------------------------------------------------------------------

def test_enriched_config_values():
    from analyzer.config import (
        ENRICHED_POSE_WINDOW_BEFORE,
        ENRICHED_POSE_WINDOW_AFTER,
    )
    assert ENRICHED_POSE_WINDOW_BEFORE == 30
    assert ENRICHED_POSE_WINDOW_AFTER == 15


# ------------------------------------------------------------------
# analyze_video_auto tests
# ------------------------------------------------------------------

def test_integrated_analyzer_has_auto_method():
    """IntegratedAnalyzer should have analyze_video_auto method."""
    from ml.integrated_analyzer import IntegratedAnalyzer
    ia = IntegratedAnalyzer(enable_pose=False, enable_action=False)
    assert hasattr(ia, "analyze_video_auto")


def test_integrated_analyzer_auto_imports_video_source():
    """analyze_video_auto should handle VideoSourceType."""
    from analyzer.video_source import VideoSourceType
    assert VideoSourceType.COACH.value == "coach"
    assert VideoSourceType.TV_BROADCAST.value == "tv_broadcast"


def test_integrated_analyzer_auto_with_explicit_player():
    """When source_type='player' is given, should route to pose-only."""
    from ml.integrated_analyzer import IntegratedAnalyzer
    ia = IntegratedAnalyzer(enable_pose=False, enable_action=False)
    # With a non-existent file, pose_only returns empty
    result = ia.analyze_video_auto(
        "/nonexistent/video.mp4",
        source_type="player",
    )
    assert result["pipeline"] == "pose_only"
    assert result["source_assessment"]["source_type"] == "player"


def test_integrated_analyzer_auto_with_explicit_coach():
    """When source_type='coach' is given, should route to full analysis."""
    from ml.integrated_analyzer import IntegratedAnalyzer
    ia = IntegratedAnalyzer(enable_pose=False, enable_action=False)
    # With non-existent file, returns empty events
    result = ia.analyze_video_auto(
        "/nonexistent/video.mp4",
        source_type="coach",
    )
    assert result["pipeline"] == "full_analysis"
    assert result["source_assessment"]["source_type"] == "coach"
