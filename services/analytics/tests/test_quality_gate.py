"""
Tests for video quality gate.

These tests do NOT require actual video files or GPU.
They test data models, profiles, and gate logic.
"""

import pytest


# ------------------------------------------------------------------
# Import tests
# ------------------------------------------------------------------

def test_import_quality_gate():
    from ml.quality_gate import QualityGate
    assert QualityGate is not None


def test_import_quality_assessment():
    from ml.quality_gate import VideoQualityAssessment
    assert VideoQualityAssessment is not None


# ------------------------------------------------------------------
# VideoQualityAssessment tests
# ------------------------------------------------------------------

def test_quality_assessment_creation():
    from ml.quality_gate import VideoQualityAssessment
    qa = VideoQualityAssessment(
        resolution_ok=True,
        fps_ok=True,
        duration_ok=True,
        brightness_ok=True,
        blur_score=150.0,
        fencer_detection_rate=0.8,
        overall_score=1.0,
        can_analyze=True,
    )
    assert qa.can_analyze is True
    assert qa.overall_score == 1.0
    assert qa.rejection_reasons == []


def test_quality_assessment_to_dict():
    from ml.quality_gate import VideoQualityAssessment
    qa = VideoQualityAssessment(
        resolution_ok=True,
        fps_ok=False,
        duration_ok=True,
        brightness_ok=True,
        blur_score=123.456,
        fencer_detection_rate=0.66666,
        overall_score=0.8,
        can_analyze=False,
        rejection_reasons=["FPS too low"],
        recommendations=["Record at 24fps minimum"],
    )
    d = qa.to_dict()
    assert d["resolution_ok"] is True
    assert d["fps_ok"] is False
    assert d["blur_score"] == 123.46
    assert d["fencer_detection_rate"] == 0.667
    assert d["can_analyze"] is False
    assert len(d["rejection_reasons"]) == 1
    assert len(d["recommendations"]) == 1


# ------------------------------------------------------------------
# QualityGate tests
# ------------------------------------------------------------------

def test_quality_gate_creation():
    from ml.quality_gate import QualityGate
    qg = QualityGate()
    assert qg._pose_estimator is None


def test_quality_gate_invalid_video():
    """Non-existent video should fail quality gate."""
    from ml.quality_gate import QualityGate
    qg = QualityGate()
    result = qg.assess("/nonexistent/video.mp4", "coach")
    assert result.can_analyze is False
    assert len(result.rejection_reasons) > 0


def test_quality_gate_profiles_exist():
    """All source types should have quality profiles."""
    from ml.quality_gate import _QUALITY_PROFILES
    assert "coach" in _QUALITY_PROFILES
    assert "parent" in _QUALITY_PROFILES
    assert "player" in _QUALITY_PROFILES
    assert "tv_broadcast" in _QUALITY_PROFILES


def test_quality_gate_profile_keys():
    """Each profile should have required keys."""
    from ml.quality_gate import _QUALITY_PROFILES
    required_keys = [
        "min_resolution", "min_fps", "min_duration",
        "max_duration", "min_brightness", "min_blur_score",
        "min_fencer_rate",
    ]
    for source_type, profile in _QUALITY_PROFILES.items():
        for key in required_keys:
            assert key in profile, f"Missing '{key}' in {source_type} profile"


def test_quality_gate_player_lower_requirements():
    """Player profile should have lower requirements than coach."""
    from ml.quality_gate import _QUALITY_PROFILES
    coach = _QUALITY_PROFILES["coach"]
    player = _QUALITY_PROFILES["player"]
    assert player["min_fencer_rate"] < coach["min_fencer_rate"]
    assert player["min_duration"] <= coach["min_duration"]


def test_quality_gate_tv_longer_duration():
    """TV broadcast should allow longer duration."""
    from ml.quality_gate import _QUALITY_PROFILES
    coach = _QUALITY_PROFILES["coach"]
    tv = _QUALITY_PROFILES["tv_broadcast"]
    assert tv["max_duration"] > coach["max_duration"]


# ------------------------------------------------------------------
# Server endpoint tests
# ------------------------------------------------------------------

def test_server_quality_check_endpoint_exists():
    from app.server import app
    routes = [r.path for r in app.routes]
    assert "/api/analytics/quality-check" in routes


def test_server_filming_guide_endpoint_exists():
    from app.server import app
    routes = [r.path for r in app.routes]
    assert "/api/analytics/filming-guide" in routes
