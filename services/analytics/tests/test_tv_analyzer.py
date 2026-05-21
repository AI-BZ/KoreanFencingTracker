"""
Tests for TV broadcast analyzer.

These tests do NOT require actual video files or GPU.
They test data models, grouping logic, and endpoint existence.
"""

import pytest


# ------------------------------------------------------------------
# Import tests
# ------------------------------------------------------------------

def test_import_tv_models():
    from analyzer.tv_models import TechniqueClip, TechniqueCollection, TVAnalysisResult
    assert TechniqueClip is not None
    assert TechniqueCollection is not None
    assert TVAnalysisResult is not None


def test_import_tv_analyzer():
    from ml.tv_analyzer import TVBroadcastAnalyzer
    assert TVBroadcastAnalyzer is not None


# ------------------------------------------------------------------
# TechniqueClip tests
# ------------------------------------------------------------------

def test_technique_clip_creation():
    from analyzer.tv_models import TechniqueClip
    clip = TechniqueClip(
        start_frame=100,
        end_frame=200,
        duration_sec=3.33,
        action="attack",
        confidence=0.85,
        fencer_side="left",
        camera_angle="wide",
        quality_score=0.68,
    )
    assert clip.start_frame == 100
    assert clip.end_frame == 200
    assert clip.action == "attack"
    assert clip.fencer_side == "left"


def test_technique_clip_to_dict():
    from analyzer.tv_models import TechniqueClip
    clip = TechniqueClip(
        start_frame=0,
        end_frame=30,
        duration_sec=1.0,
        action="riposte",
        confidence=0.9123,
        fencer_side="right",
        quality_score=0.7298,
    )
    d = clip.to_dict()
    assert d["action"] == "riposte"
    assert d["confidence"] == 0.912
    assert d["quality_score"] == 0.73
    assert d["duration_sec"] == 1.0
    assert d["fencer_side"] == "right"


# ------------------------------------------------------------------
# TechniqueCollection tests
# ------------------------------------------------------------------

def test_technique_collection_creation():
    from analyzer.tv_models import TechniqueClip, TechniqueCollection
    clips = [
        TechniqueClip(0, 30, 1.0, "attack", 0.8, "left"),
        TechniqueClip(60, 90, 1.0, "attack", 0.9, "right"),
    ]
    tc = TechniqueCollection(
        action="attack",
        clips=clips,
        best_example_idx=1,
        count=2,
    )
    assert tc.action == "attack"
    assert tc.count == 2
    assert tc.best_example_idx == 1


def test_technique_collection_to_dict():
    from analyzer.tv_models import TechniqueCollection
    tc = TechniqueCollection(action="riposte", count=0)
    d = tc.to_dict()
    assert d["action"] == "riposte"
    assert d["count"] == 0
    assert d["clips"] == []


# ------------------------------------------------------------------
# TVAnalysisResult tests
# ------------------------------------------------------------------

def test_tv_analysis_result_creation():
    from analyzer.tv_models import TVAnalysisResult
    result = TVAnalysisResult(video_path="test.mp4")
    assert result.video_path == "test.mp4"
    assert result.total_bout_segments == 0
    assert result.total_techniques_extracted == 0
    assert result.techniques == []


def test_tv_analysis_result_to_dict():
    from analyzer.tv_models import TVAnalysisResult
    result = TVAnalysisResult(
        video_path="match.mp4",
        total_bout_segments=5,
        total_techniques_extracted=12,
        action_distribution={"attack": 7, "riposte": 5},
        scene_cuts=[30, 60, 90],
        bout_segments=[(0, 30), (60, 90)],
    )
    d = result.to_dict()
    assert d["video_path"] == "match.mp4"
    assert d["total_bout_segments"] == 5
    assert d["total_techniques_extracted"] == 12
    assert d["scene_cuts_count"] == 3
    assert d["bout_segments_count"] == 2
    assert d["action_distribution"]["attack"] == 7


# ------------------------------------------------------------------
# TVBroadcastAnalyzer tests
# ------------------------------------------------------------------

def test_tv_analyzer_creation():
    from ml.tv_analyzer import TVBroadcastAnalyzer
    analyzer = TVBroadcastAnalyzer()
    assert analyzer._pose_estimator is None
    assert analyzer._action_classifier is None


def test_tv_analyzer_nonexistent_video():
    """Non-existent video should return empty result."""
    from ml.tv_analyzer import TVBroadcastAnalyzer
    analyzer = TVBroadcastAnalyzer()
    result = analyzer.analyze_broadcast("/nonexistent/video.mp4")
    assert result.video_path == "/nonexistent/video.mp4"
    assert result.total_bout_segments == 0
    assert result.total_techniques_extracted == 0


def test_tv_analyzer_group_by_action():
    """Test technique grouping logic."""
    from ml.tv_analyzer import TVBroadcastAnalyzer
    from analyzer.tv_models import TechniqueClip

    clips = [
        TechniqueClip(0, 30, 1.0, "attack", 0.8, "left", quality_score=0.6),
        TechniqueClip(60, 90, 1.0, "attack", 0.9, "right", quality_score=0.9),
        TechniqueClip(120, 150, 1.0, "riposte", 0.7, "left", quality_score=0.5),
    ]

    collections = TVBroadcastAnalyzer._group_by_action(clips)
    assert len(collections) == 2

    attack_col = next(c for c in collections if c.action == "attack")
    assert attack_col.count == 2
    assert attack_col.best_example_idx == 1  # Higher quality_score

    riposte_col = next(c for c in collections if c.action == "riposte")
    assert riposte_col.count == 1


def test_tv_analyzer_estimate_camera_angle():
    """Test camera angle estimation heuristic."""
    import numpy as np
    from ml.tv_analyzer import TVBroadcastAnalyzer

    # Wide aspect (e.g. 640×200)
    wide_frame = np.zeros((200, 640, 3), dtype=np.uint8)
    assert TVBroadcastAnalyzer._estimate_camera_angle([wide_frame]) == "wide"

    # Close aspect (e.g. 640×600)
    close_frame = np.zeros((600, 640, 3), dtype=np.uint8)
    assert TVBroadcastAnalyzer._estimate_camera_angle([close_frame]) == "close"

    # Medium aspect (e.g. 640×400)
    medium_frame = np.zeros((400, 640, 3), dtype=np.uint8)
    assert TVBroadcastAnalyzer._estimate_camera_angle([medium_frame]) == "medium"

    # Empty
    assert TVBroadcastAnalyzer._estimate_camera_angle([]) == "wide"


# ------------------------------------------------------------------
# Export tests
# ------------------------------------------------------------------

def test_analyzer_exports_tv_models():
    from analyzer import TechniqueClip, TechniqueCollection, TVAnalysisResult
    assert TechniqueClip is not None
    assert TechniqueCollection is not None
    assert TVAnalysisResult is not None


def test_ml_exports_tv_analyzer():
    from ml import TVBroadcastAnalyzer
    assert TVBroadcastAnalyzer is not None


# ------------------------------------------------------------------
# Server endpoint tests
# ------------------------------------------------------------------

def test_server_broadcast_endpoint_exists():
    from app.server import app
    routes = [r.path for r in app.routes]
    assert "/api/analytics/analyze-broadcast" in routes
