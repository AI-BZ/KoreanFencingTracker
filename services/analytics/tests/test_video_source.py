"""
Tests for video source type detection.

These tests do NOT require actual video files or model weights.
They test data models, heuristic logic, and serialization.
"""

import pytest
import numpy as np


# ------------------------------------------------------------------
# Import tests
# ------------------------------------------------------------------

def test_import_video_source_type():
    from analyzer.video_source import VideoSourceType
    assert VideoSourceType is not None


def test_import_video_source_assessment():
    from analyzer.video_source import VideoSourceAssessment
    assert VideoSourceAssessment is not None


def test_import_video_source_detector():
    from ml.video_source_detector import VideoSourceDetector
    assert VideoSourceDetector is not None


# ------------------------------------------------------------------
# VideoSourceType enum tests
# ------------------------------------------------------------------

def test_video_source_type_values():
    from analyzer.video_source import VideoSourceType
    assert VideoSourceType.COACH.value == "coach"
    assert VideoSourceType.PARENT.value == "parent"
    assert VideoSourceType.PLAYER.value == "player"
    assert VideoSourceType.TV_BROADCAST.value == "tv_broadcast"
    assert VideoSourceType.UNKNOWN.value == "unknown"


def test_video_source_type_count():
    from analyzer.video_source import VideoSourceType
    assert len(VideoSourceType) == 5


def test_video_source_type_from_string():
    from analyzer.video_source import VideoSourceType
    assert VideoSourceType("coach") == VideoSourceType.COACH
    assert VideoSourceType("tv_broadcast") == VideoSourceType.TV_BROADCAST


# ------------------------------------------------------------------
# VideoSourceAssessment tests
# ------------------------------------------------------------------

def test_assessment_creation():
    from analyzer.video_source import VideoSourceType, VideoSourceAssessment
    assessment = VideoSourceAssessment(
        source_type=VideoSourceType.COACH,
        confidence=0.85,
        scene_cuts_per_minute=0.5,
        avg_fencer_height_ratio=0.4,
        scoreboard_detected=True,
        overlay_detected=False,
        avg_person_count=2.0,
        stability_score=0.9,
        resolution=(1920, 1080),
        fps=30.0,
        duration_sec=180.0,
    )
    assert assessment.source_type == VideoSourceType.COACH
    assert assessment.confidence == 0.85
    assert assessment.resolution == (1920, 1080)


def test_assessment_to_dict():
    from analyzer.video_source import VideoSourceType, VideoSourceAssessment
    assessment = VideoSourceAssessment(
        source_type=VideoSourceType.TV_BROADCAST,
        confidence=0.9,
        scene_cuts_per_minute=12.5,
        avg_fencer_height_ratio=0.1,
        scoreboard_detected=False,
        overlay_detected=True,
        avg_person_count=2.0,
        stability_score=0.95,
        resolution=(1920, 1080),
        fps=60.0,
        duration_sec=300.0,
    )
    d = assessment.to_dict()
    assert d["source_type"] == "tv_broadcast"
    assert d["confidence"] == 0.9
    assert d["scene_cuts_per_minute"] == 12.5
    assert d["overlay_detected"] is True
    assert d["resolution"] == [1920, 1080]
    assert d["fps"] == 60.0


def test_assessment_to_dict_rounding():
    from analyzer.video_source import VideoSourceType, VideoSourceAssessment
    assessment = VideoSourceAssessment(
        source_type=VideoSourceType.UNKNOWN,
        confidence=0.33333,
        scene_cuts_per_minute=1.23456,
        avg_fencer_height_ratio=0.12345,
        scoreboard_detected=False,
        overlay_detected=False,
        avg_person_count=1.99999,
        stability_score=0.55555,
        resolution=(640, 480),
        fps=29.97,
        duration_sec=120.123,
    )
    d = assessment.to_dict()
    assert d["confidence"] == 0.333
    assert d["scene_cuts_per_minute"] == 1.23
    assert d["avg_fencer_height_ratio"] == 0.123


# ------------------------------------------------------------------
# VideoSourceDetector heuristic tests
# ------------------------------------------------------------------

def test_detector_creation():
    from ml.video_source_detector import VideoSourceDetector
    d = VideoSourceDetector()
    assert d._pose_estimator is None


def test_detector_unknown_for_invalid_path():
    from ml.video_source_detector import VideoSourceDetector
    from analyzer.video_source import VideoSourceType
    d = VideoSourceDetector()
    result = d.detect("/nonexistent/video.mp4")
    assert result.source_type == VideoSourceType.UNKNOWN
    assert result.confidence == 0.0


def test_detector_classify_tv_broadcast():
    """TV broadcast: high cuts + overlay."""
    from ml.video_source_detector import VideoSourceDetector
    from analyzer.video_source import VideoSourceType
    d = VideoSourceDetector()
    source_type, conf = d._classify(
        cuts_per_min=15.0,
        stability=0.9,
        avg_person_count=2.0,
        avg_fencer_height=0.1,
        scoreboard_detected=False,
        overlay_detected=True,
        height=1080,
    )
    assert source_type == VideoSourceType.TV_BROADCAST


def test_detector_classify_coach():
    """Coach: stable + scoreboard + 2 fencers."""
    from ml.video_source_detector import VideoSourceDetector
    from analyzer.video_source import VideoSourceType
    d = VideoSourceDetector()
    source_type, conf = d._classify(
        cuts_per_min=0.5,
        stability=0.9,
        avg_person_count=2.0,
        avg_fencer_height=0.4,
        scoreboard_detected=True,
        overlay_detected=False,
        height=1080,
    )
    assert source_type == VideoSourceType.COACH


def test_detector_classify_parent():
    """Parent: scoreboard but not stable."""
    from ml.video_source_detector import VideoSourceDetector
    from analyzer.video_source import VideoSourceType
    d = VideoSourceDetector()
    source_type, conf = d._classify(
        cuts_per_min=1.0,
        stability=0.5,
        avg_person_count=3.0,
        avg_fencer_height=0.2,
        scoreboard_detected=True,
        overlay_detected=False,
        height=1080,
    )
    assert source_type == VideoSourceType.PARENT


def test_detector_classify_player():
    """Player: ~1 person, no scoreboard."""
    from ml.video_source_detector import VideoSourceDetector
    from analyzer.video_source import VideoSourceType
    d = VideoSourceDetector()
    source_type, conf = d._classify(
        cuts_per_min=0.0,
        stability=0.3,
        avg_person_count=1.0,
        avg_fencer_height=0.5,
        scoreboard_detected=False,
        overlay_detected=False,
        height=1080,
    )
    assert source_type == VideoSourceType.PLAYER


# ------------------------------------------------------------------
# Export tests
# ------------------------------------------------------------------

def test_analyzer_exports_video_source():
    from analyzer import VideoSourceType, VideoSourceAssessment
    assert VideoSourceType is not None
    assert VideoSourceAssessment is not None


def test_ml_exports_video_source_detector():
    from ml import VideoSourceDetector
    assert VideoSourceDetector is not None
