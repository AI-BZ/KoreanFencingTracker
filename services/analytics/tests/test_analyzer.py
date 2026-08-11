"""
Basic tests for the analytics analyzer modules.

Tests module imports and data model instantiation.
Video processing tests require actual video files and are skipped
in CI environments.
"""

import pytest
import numpy as np


# ------------------------------------------------------------------
# Module import tests
# ------------------------------------------------------------------

def test_import_models():
    from analyzer.models import ScoreState, StableScore, LampState, MatchEvent, EventType, MatchClock
    assert ScoreState is not None
    assert StableScore is not None
    assert LampState is not None
    assert MatchEvent is not None
    assert EventType is not None
    assert MatchClock is not None


def test_import_config():
    from analyzer.config import (
        LAMP_PIXEL_THRESHOLD,
        SEVEN_SEGMENT_PATTERNS,
        DEBOUNCE_FRAMES,
    )
    assert LAMP_PIXEL_THRESHOLD == 300
    assert len(SEVEN_SEGMENT_PATTERNS) == 10
    assert DEBOUNCE_FRAMES == 30


def test_import_lamp_detector():
    from analyzer.lamp_detector import LampDetector
    detector = LampDetector()
    assert detector.pixel_threshold == 300


def test_import_score_reader():
    from analyzer.score_reader import ScoreReader
    reader = ScoreReader()
    assert reader is not None


def test_import_video_processor():
    from analyzer.video_processor import VideoProcessor
    processor = VideoProcessor()
    assert processor is not None


def test_import_pipeline_downloader():
    from pipeline.downloader import VideoDownloader, DownloadResult
    assert VideoDownloader is not None
    assert DownloadResult is not None


def test_import_pipeline_clip_cutter():
    from pipeline.clip_cutter import ClipCutter, TouchEvent, ClipInfo
    assert ClipCutter is not None
    assert TouchEvent is not None
    assert ClipInfo is not None


def test_import_pipeline_auto_labeler():
    from pipeline.auto_labeler import AutoLabeler, LabeledClip
    assert AutoLabeler is not None
    assert LabeledClip is not None


def test_import_pipeline_data_augmentor():
    from pipeline.data_augmentor import DataAugmentor, AugmentedClip
    assert DataAugmentor is not None
    assert AugmentedClip is not None


# ------------------------------------------------------------------
# Model instantiation tests
# ------------------------------------------------------------------

def test_score_state():
    from analyzer.models import ScoreState
    s = ScoreState()
    assert s.left == 0
    assert s.right == 0
    s.left = 5
    assert s.left == 5


def test_stable_score():
    from analyzer.models import StableScore
    s = StableScore()
    assert s.left == 0
    assert s.read_count_left == 0
    assert s.last_read_left is None


def test_lamp_state():
    from analyzer.models import LampState
    lamp = LampState(red=True, green=False, red_pixels=500, green_pixels=10)
    assert lamp.red is True
    assert lamp.green is False


def test_match_event_to_dict():
    from analyzer.models import MatchEvent
    e = MatchEvent(
        frame=100,
        video_timestamp="0:03.33",
        match_time="3:00",
        event_type="left_lamp",
        lamp_red=True,
        lamp_green=False,
        score_before="0-0",
        score_after="1-0",
        scorer="left",
        description="Left lamp → left scored",
    )
    d = e.to_dict()
    assert d["frame"] == 100
    assert d["scorer"] == "left"


def test_match_clock_str():
    from analyzer.models import MatchClock
    c = MatchClock(minutes=2, seconds=5)
    assert str(c) == "2:05"


# ------------------------------------------------------------------
# 7-segment pattern tests
# ------------------------------------------------------------------

def test_seven_segment_patterns_complete():
    from analyzer.config import SEVEN_SEGMENT_PATTERNS
    # All digits 0-9 must be present
    digits = set(SEVEN_SEGMENT_PATTERNS.values())
    assert digits == {0, 1, 2, 3, 4, 5, 6, 7, 8, 9}


def test_seven_segment_pattern_8_all_on():
    from analyzer.config import SEVEN_SEGMENT_PATTERNS
    # Digit 8 has all segments on
    all_on = (True, True, True, True, True, True, True)
    assert SEVEN_SEGMENT_PATTERNS[all_on] == 8


def test_seven_segment_pattern_0_no_g():
    from analyzer.config import SEVEN_SEGMENT_PATTERNS
    # Digit 0 is all segments on except g
    zero = (True, True, True, True, True, True, False)
    assert SEVEN_SEGMENT_PATTERNS[zero] == 0


# ------------------------------------------------------------------
# Lamp detector unit tests
# ------------------------------------------------------------------

def test_lamp_detector_no_roi():
    from analyzer.lamp_detector import LampDetector
    detector = LampDetector()
    is_on, px = detector.detect_lamp(np.zeros((100, 100, 3), dtype=np.uint8), None)
    assert is_on is False
    assert px == 0


def test_lamp_detector_empty_roi():
    from analyzer.lamp_detector import LampDetector
    detector = LampDetector()
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    # ROI with zero width
    is_on, px = detector.detect_lamp(frame, (10, 10, 0, 0))
    assert is_on is False


def test_lamp_detector_bright_red():
    from analyzer.lamp_detector import LampDetector
    detector = LampDetector(pixel_threshold=10)
    # Create frame with bright red region
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    frame[20:40, 20:40] = [0, 0, 255]  # BGR red
    is_on, px = detector.detect_lamp(frame, (15, 15, 30, 30), "red")
    assert is_on is True
    assert px > 10


# ------------------------------------------------------------------
# Score reader unit tests
# ------------------------------------------------------------------

def test_score_reader_no_roi():
    from analyzer.score_reader import ScoreReader
    reader = ScoreReader()
    result = reader.read_7segment_digit(np.zeros((100, 100, 3), dtype=np.uint8), None)
    assert result is None


def test_score_reader_get_mask_no_roi():
    from analyzer.score_reader import ScoreReader
    reader = ScoreReader()
    mask = reader.get_score_roi_mask(np.zeros((100, 100, 3), dtype=np.uint8), None)
    assert mask is None


# ------------------------------------------------------------------
# Data augmentor label flip
# ------------------------------------------------------------------

def test_augmentor_label_flip():
    from pipeline.data_augmentor import DataAugmentor
    assert DataAugmentor.LABEL_FLIP_MAP["L"] == "R"
    assert DataAugmentor.LABEL_FLIP_MAP["R"] == "L"
    assert DataAugmentor.LABEL_FLIP_MAP["T"] == "T"


# ------------------------------------------------------------------
# Auto labeler logic
# ------------------------------------------------------------------

def test_labeler_determine_label():
    from pipeline.auto_labeler import AutoLabeler
    labeler = AutoLabeler(rois={})

    # On-On, left scored
    assert labeler.determine_label("On-On", 3, 2, 4, 2) == "L"
    # On-On, right scored
    assert labeler.determine_label("On-On", 3, 2, 3, 3) == "R"
    # On-On, neither scored
    assert labeler.determine_label("On-On", 3, 2, 3, 2) == "T"
    # None values
    assert labeler.determine_label("On-On", None, 2, 4, 2) == "X"
