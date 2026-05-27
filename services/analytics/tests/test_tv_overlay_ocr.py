"""Tests for TV overlay OCR and score tracking.

Tests cover:
- OverlayData/TVTouchEvent serialization
- Overlay presence detection
- Score extraction
- Name extraction
- Time extraction
- Card detection
- Score tracker debouncing
- Score tracker touch event detection
- Full video scan (optional, requires sample video)
"""

import json
import pytest

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None

if not HAS_NUMPY:
    pytest.skip("numpy not installed", allow_module_level=True)

from analyzer.tv_overlay_ocr import (
    OverlayData,
    TVTouchEvent,
    TVOverlayOCR,
    TVScoreTracker,
    OVERLAY_LAYOUTS,
)
from analyzer.config import (
    OVERLAY_BAR_Y_RATIO,
    OVERLAY_BAR_HEIGHT,
    OVERLAY_SCORE_DEBOUNCE,
    OVERLAY_OCR_SAMPLE_INTERVAL,
)

# Check if pytesseract is available for OCR tests
try:
    import pytesseract
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False

needs_tesseract = pytest.mark.skipif(
    not HAS_TESSERACT,
    reason="pytesseract not installed",
)


# ── Fixtures ──

def _make_frame(h=720, w=1280, bar_brightness=30, text_brightness=230):
    """Create a synthetic 720p frame with a dark overlay bar and bright text."""
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    # Fill with a medium gray (simulating video content)
    frame[:, :] = (80, 80, 80)

    # Dark overlay bar at the expected position
    bar_y = int(h * OVERLAY_BAR_Y_RATIO)
    bar_h = OVERLAY_BAR_HEIGHT
    frame[bar_y:bar_y + bar_h, :] = (bar_brightness, bar_brightness, bar_brightness)

    # Add white text-like pixels across the bar (>3% of bar pixels)
    # We need enough bright pixels so bright_ratio > 0.03
    # Bar area = 53 * 1280 = 67,840 pixels. 3% = ~2,035 bright pixels needed.
    # Fill contiguous bright blocks in name + score regions
    for x in range(100, 400):
        for y in range(bar_y + 10, bar_y + 40):
            frame[y, x] = (text_brightness, text_brightness, text_brightness)
    for x in range(460, 530):
        for y in range(bar_y + 10, bar_y + 40):
            frame[y, x] = (text_brightness, text_brightness, text_brightness)
    for x in range(750, 820):
        for y in range(bar_y + 10, bar_y + 40):
            frame[y, x] = (text_brightness, text_brightness, text_brightness)
    for x in range(860, 1160):
        for y in range(bar_y + 10, bar_y + 40):
            frame[y, x] = (text_brightness, text_brightness, text_brightness)

    return frame


def _make_frame_no_overlay(h=720, w=1280):
    """Frame without overlay (e.g., between bouts)."""
    frame = np.ones((h, w, 3), dtype=np.uint8) * 120
    return frame


def _make_overlay_data(left_score=3, right_score=2, period=1, time="2:15",
                       left_name="SMITH John", right_name="DOE Jane"):
    """Create an OverlayData for tracker tests."""
    return OverlayData(
        left_name=left_name,
        right_name=right_name,
        left_score=left_score,
        right_score=right_score,
        time_remaining=time,
        period=period,
        confidence=0.85,
    )


# ── OverlayData tests ──

class TestOverlayData:
    def test_defaults(self):
        data = OverlayData()
        assert data.left_name is None
        assert data.right_name is None
        assert data.left_score is None
        assert data.right_score is None
        assert data.confidence == 0.0
        assert data.yellow_card_left is False
        assert data.red_card_left is False

    def test_to_dict(self):
        data = OverlayData(
            left_name="KHOTLINE Daniel",
            right_name="GERSTMANN Max",
            left_score=5,
            right_score=3,
            time_remaining="2:30",
            period=2,
            confidence=0.9,
        )
        d = data.to_dict()
        assert d["left_name"] == "KHOTLINE Daniel"
        assert d["right_name"] == "GERSTMANN Max"
        assert d["left_score"] == 5
        assert d["right_score"] == 3
        assert d["time_remaining"] == "2:30"
        assert d["period"] == 2

    def test_serializable(self):
        data = OverlayData(left_score=10, right_score=15, confidence=0.85)
        j = json.dumps(data.to_dict())
        parsed = json.loads(j)
        assert parsed["left_score"] == 10
        assert parsed["right_score"] == 15


class TestTVTouchEvent:
    def test_to_dict(self):
        e = TVTouchEvent(
            frame=1500,
            timestamp=50.0,
            scorer="left",
            score_before="2-1",
            score_after="3-1",
            period=1,
        )
        d = e.to_dict()
        assert d["frame"] == 1500
        assert d["scorer"] == "left"
        assert d["score_before"] == "2-1"

    def test_serializable(self):
        e = TVTouchEvent(frame=100, timestamp=3.33, scorer="right",
                         score_before="0-0", score_after="0-1")
        j = json.dumps(e.to_dict())
        parsed = json.loads(j)
        assert parsed["scorer"] == "right"


# ── TVOverlayOCR tests ──

class TestTVOverlayOCR:
    @needs_tesseract
    def test_init_default_layout(self):
        ocr = TVOverlayOCR()
        assert ocr.layout is not None

    @needs_tesseract
    def test_init_invalid_layout_raises(self):
        with pytest.raises(ValueError, match="Unknown layout"):
            TVOverlayOCR(layout="nonexistent")

    def test_import_error_without_pytesseract(self, monkeypatch):
        """TVOverlayOCR should raise ImportError if pytesseract is missing."""
        import analyzer.tv_overlay_ocr as module
        original = module.pytesseract
        try:
            module.pytesseract = None
            with pytest.raises(ImportError, match="pytesseract"):
                TVOverlayOCR()
        finally:
            module.pytesseract = original

    @needs_tesseract
    def test_detect_overlay_presence_with_bar(self):
        ocr = TVOverlayOCR()
        frame = _make_frame()
        assert ocr.detect_overlay_presence(frame) == True

    @needs_tesseract
    def test_detect_overlay_absence(self):
        ocr = TVOverlayOCR()
        frame = _make_frame_no_overlay()
        assert ocr.detect_overlay_presence(frame) == False

    @needs_tesseract
    def test_read_overlay_no_bar(self):
        ocr = TVOverlayOCR()
        frame = _make_frame_no_overlay()
        result = ocr.read_overlay(frame)
        assert result is None

    @needs_tesseract
    def test_read_overlay_with_bar(self):
        """Smoke test: reading a synthetic frame should return OverlayData."""
        ocr = TVOverlayOCR()
        frame = _make_frame()
        result = ocr.read_overlay(frame)
        # With synthetic data, OCR may not extract meaningful text,
        # but should return an OverlayData (not None)
        assert result is not None
        assert isinstance(result, OverlayData)

    @needs_tesseract
    def test_preprocess_region_returns_binary(self):
        ocr = TVOverlayOCR()
        # Create a small test region
        region = np.zeros((50, 100, 3), dtype=np.uint8)
        region[10:40, 20:80] = (255, 255, 255)  # white text-like area
        processed = ocr._preprocess_region(region, text_colors=["white"], scale=2)
        assert processed.ndim == 2  # binary/grayscale
        assert processed.shape[0] == 100  # scaled 2x
        assert processed.shape[1] == 200

    @needs_tesseract
    def test_detect_cards_no_cards(self):
        ocr = TVOverlayOCR()
        # Dark bar with white text but no yellow/red cards
        bar = np.zeros((53, 1280, 3), dtype=np.uint8)
        bar[:, :] = (30, 30, 30)
        yl, yr, rl, rr = ocr._detect_cards(bar)
        assert yl == False
        assert yr == False
        assert rl == False
        assert rr == False

    @needs_tesseract
    def test_detect_cards_yellow_left(self):
        ocr = TVOverlayOCR()
        bar = np.zeros((53, 1280, 3), dtype=np.uint8)
        bar[:, :] = (30, 30, 30)
        # Add a yellow block on the left side (BGR: ~0,200,255 → HSV yellow)
        bar[10:40, 100:150] = (0, 255, 255)  # bright yellow in BGR
        yl, yr, rl, rr = ocr._detect_cards(bar)
        assert yl == True
        assert yr == False


# ── TVScoreTracker tests ──

class TestTVScoreTracker:
    def test_initial_reading(self):
        tracker = TVScoreTracker()
        data = _make_overlay_data(left_score=0, right_score=0)
        event = tracker.update(1, data)
        assert event is None  # first reading, no event
        assert tracker.get_all_events() == []

    def test_same_score_no_event(self):
        tracker = TVScoreTracker()
        data = _make_overlay_data(left_score=2, right_score=1)
        tracker.update(1, data)
        # Same score 20 times
        for i in range(2, 22):
            event = tracker.update(i, data)
            assert event is None

    def test_debounce_filters_transient(self):
        tracker = TVScoreTracker(debounce_frames=10)
        # Initial score
        data_init = _make_overlay_data(left_score=2, right_score=1)
        tracker.update(1, data_init)

        # Transient change for only 5 frames (less than debounce)
        data_change = _make_overlay_data(left_score=3, right_score=1)
        for i in range(2, 7):
            tracker.update(i, data_change)

        # Revert to original
        for i in range(7, 20):
            event = tracker.update(i, data_init)
            assert event is None

        # No event should have been generated
        assert len(tracker.get_all_events()) == 0

    def test_debounce_confirms_stable_change(self):
        tracker = TVScoreTracker(debounce_frames=10)
        data_init = _make_overlay_data(left_score=2, right_score=1)
        tracker.update(1, data_init)

        # Score changes and stays stable
        data_change = _make_overlay_data(left_score=3, right_score=1)
        event = None
        for i in range(2, 20):
            result = tracker.update(i, data_change)
            if result is not None:
                event = result

        assert event is not None
        assert event.scorer == "left"
        assert event.score_before == "2-1"
        assert event.score_after == "3-1"

    def test_right_scorer_detected(self):
        tracker = TVScoreTracker(debounce_frames=5)
        data_init = _make_overlay_data(left_score=3, right_score=4)
        tracker.update(1, data_init)

        data_change = _make_overlay_data(left_score=3, right_score=5)
        event = None
        for i in range(2, 15):
            result = tracker.update(i, data_change)
            if result is not None:
                event = result

        assert event is not None
        assert event.scorer == "right"
        assert event.score_after == "3-5"

    def test_score_decrease_ignored(self):
        """Score going down is treated as OCR error."""
        tracker = TVScoreTracker(debounce_frames=5)
        data_init = _make_overlay_data(left_score=5, right_score=3)
        tracker.update(1, data_init)

        # Score decreases (OCR error)
        data_bad = _make_overlay_data(left_score=4, right_score=3)
        for i in range(2, 20):
            event = tracker.update(i, data_bad)
            assert event is None

    def test_large_score_increase_ignored(self):
        """Score jumping by more than 2 is treated as OCR error."""
        tracker = TVScoreTracker(debounce_frames=5)
        data_init = _make_overlay_data(left_score=10, right_score=13)
        tracker.update(1, data_init)

        # Right score jumps from 13 to 43 (OCR misread)
        data_bad = _make_overlay_data(left_score=10, right_score=43)
        for i in range(2, 20):
            event = tracker.update(i, data_bad)
            assert event is None

        # Confirmed score unchanged
        assert tracker._confirmed_score == (10, 13)

    def test_none_scores_ignored(self):
        """Frames where OCR returns None should be skipped."""
        tracker = TVScoreTracker(debounce_frames=5)
        data_init = _make_overlay_data(left_score=1, right_score=0)
        tracker.update(1, data_init)

        # Frames with None scores
        data_none = OverlayData(left_score=None, right_score=None)
        for i in range(2, 10):
            event = tracker.update(i, data_none)
            assert event is None

        # Original score still confirmed
        assert tracker._confirmed_score == (1, 0)

    def test_multiple_touches(self):
        tracker = TVScoreTracker(debounce_frames=3)

        scores = [
            (0, 0), (0, 0), (0, 0),   # initial
            (1, 0), (1, 0), (1, 0), (1, 0), (1, 0),  # touch 1: left scores
            (1, 1), (1, 1), (1, 1), (1, 1), (1, 1),  # touch 2: right scores
            (2, 1), (2, 1), (2, 1), (2, 1), (2, 1),  # touch 3: left scores
        ]

        for i, (ls, rs) in enumerate(scores):
            data = _make_overlay_data(left_score=ls, right_score=rs)
            tracker.update(i, data)

        events = tracker.get_all_events()
        assert len(events) == 3
        assert events[0].scorer == "left"
        assert events[0].score_after == "1-0"
        assert events[1].scorer == "right"
        assert events[1].score_after == "1-1"
        assert events[2].scorer == "left"
        assert events[2].score_after == "2-1"

    def test_get_match_summary(self):
        tracker = TVScoreTracker(debounce_frames=3)

        # Build up a few touches
        scores = [
            (0, 0), (0, 0), (0, 0),
            (1, 0), (1, 0), (1, 0), (1, 0),
            (1, 1), (1, 1), (1, 1), (1, 1),
        ]
        for i, (ls, rs) in enumerate(scores):
            data = _make_overlay_data(left_score=ls, right_score=rs, period=1)
            tracker.update(i, data)

        summary = tracker.get_match_summary()
        assert summary["total_touches"] == 2
        assert summary["final_score"] == "1-1"
        assert summary["left_touches"] == 1
        assert summary["right_touches"] == 1

    def test_reset(self):
        tracker = TVScoreTracker(debounce_frames=3)
        data = _make_overlay_data(left_score=5, right_score=3)
        tracker.update(1, data)
        assert tracker._confirmed_score == (5, 3)

        tracker.reset()
        assert tracker._confirmed_score == (None, None)
        assert tracker.get_all_events() == []


# ── Layout config tests ──

class TestOverlayLayouts:
    def test_usa_fencing_layout_exists(self):
        assert "usa_fencing" in OVERLAY_LAYOUTS

    def test_usa_fencing_regions(self):
        layout = OVERLAY_LAYOUTS["usa_fencing"]
        assert "regions" in layout
        regions = layout["regions"]
        assert "left_name" in regions
        assert "left_score" in regions
        assert "center" in regions
        assert "right_score" in regions
        assert "right_name" in regions


# ── Config constants tests ──

class TestOverlayConfig:
    def test_bar_y_ratio(self):
        assert 0.8 < OVERLAY_BAR_Y_RATIO < 1.0

    def test_bar_height(self):
        assert 20 < OVERLAY_BAR_HEIGHT < 100

    def test_debounce(self):
        assert OVERLAY_SCORE_DEBOUNCE > 0

    def test_sample_interval(self):
        assert OVERLAY_OCR_SAMPLE_INTERVAL > 0
