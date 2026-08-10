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
    LampBarReader,
    LampEvent,
    LampReading,
    LampSideReading,
    _lamp_pattern,
)
from analyzer.config import (
    OVERLAY_BAR_Y_RATIO,
    OVERLAY_BAR_HEIGHT,
    OVERLAY_SCORE_DEBOUNCE,
    OVERLAY_OCR_SAMPLE_INTERVAL,
    LAMP_ON_FILL_THRESHOLD,
    LAMP_SAMPLE_STEP,
    LAMP_EVENT_MERGE_GAP,
    LAMP_SEARCH_LOOKBACK,
    LAMP_SEARCH_FORWARD,
    LAMP_CONF_FULL_FILL,
    LAMP_CONF_FULL_FRAMES,
    LAMP_CONF_MIN_DURATION_FACTOR,
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


# ── Clock state tracking tests ──

class TestClockStateTracking:
    """Test Allez/Halt proxy detection via clock time changes."""

    def test_time_decrease_triggers_allez(self):
        """Consecutive time decreases → allez event detected."""
        tracker = TVScoreTracker(debounce_frames=15)
        # Initial score
        tracker.update(0, _make_overlay_data(left_score=0, right_score=0, time="2:00"))

        # Clock running: time decreasing each frame
        times = ["1:59", "1:58", "1:57", "1:56", "1:55"]
        for i, t in enumerate(times):
            tracker.update(i + 1, _make_overlay_data(
                left_score=0, right_score=0, time=t,
            ))

        events = tracker.get_clock_events()
        assert len(events) >= 1
        allez_events = [e for e in events if e["event"] == "allez"]
        assert len(allez_events) == 1
        assert allez_events[0]["event"] == "allez"

    def test_time_unchanged_triggers_halt(self):
        """Consecutive unchanged time → halt event detected."""
        tracker = TVScoreTracker(debounce_frames=15)
        # Start with clock running
        tracker.update(0, _make_overlay_data(left_score=0, right_score=0, time="1:30"))
        for i in range(1, 5):
            tracker.update(i, _make_overlay_data(
                left_score=0, right_score=0, time=f"1:{30 - i:02d}",
            ))
        # Now clock should be running (allez detected)
        assert tracker._clock_state == "running"

        # Clock stops: same time for many frames
        for i in range(5, 15):
            tracker.update(i, _make_overlay_data(
                left_score=0, right_score=0, time="1:26",
            ))

        events = tracker.get_clock_events()
        halt_events = [e for e in events if e["event"] == "halt"]
        assert len(halt_events) == 1
        assert halt_events[0]["time"] == "1:26"

    def test_mixed_sequence_allez_halt_alternation(self):
        """Mixed running/stopped → correct allez/halt alternation."""
        tracker = TVScoreTracker(debounce_frames=15)
        frame = 0

        # Phase 1: clock starts (time decreasing) → allez
        times_running1 = ["2:00", "1:59", "1:58", "1:57", "1:56"]
        for t in times_running1:
            tracker.update(frame, _make_overlay_data(
                left_score=0, right_score=0, time=t,
            ))
            frame += 1

        # Phase 2: clock stops → halt
        for _ in range(7):
            tracker.update(frame, _make_overlay_data(
                left_score=0, right_score=0, time="1:56",
            ))
            frame += 1

        # Phase 3: clock resumes (time decreasing again) → allez
        times_running2 = ["1:55", "1:54", "1:53", "1:52"]
        for t in times_running2:
            tracker.update(frame, _make_overlay_data(
                left_score=0, right_score=0, time=t,
            ))
            frame += 1

        events = tracker.get_clock_events()
        event_types = [e["event"] for e in events]
        # Should have: allez, halt, allez
        assert event_types == ["allez", "halt", "allez"]

    def test_no_events_without_time_data(self):
        """No clock events when time_remaining is None."""
        tracker = TVScoreTracker(debounce_frames=15)
        data = OverlayData(
            left_score=0, right_score=0,
            left_name="A", right_name="B",
            time_remaining=None,
        )
        for i in range(10):
            tracker.update(i, data)

        events = tracker.get_clock_events()
        assert len(events) == 0


class TestParseTimeSeconds:
    """Test the _parse_time_seconds helper."""

    def test_minutes_seconds(self):
        tracker = TVScoreTracker()
        assert tracker._parse_time_seconds("2:30") == 150.0
        assert tracker._parse_time_seconds("1:00") == 60.0
        assert tracker._parse_time_seconds("0:45") == 45.0

    def test_seconds_only(self):
        tracker = TVScoreTracker()
        assert tracker._parse_time_seconds("30") == 30.0
        assert tracker._parse_time_seconds("0") == 0.0

    def test_none_returns_none(self):
        tracker = TVScoreTracker()
        assert tracker._parse_time_seconds(None) is None

    def test_invalid_returns_none(self):
        tracker = TVScoreTracker()
        assert tracker._parse_time_seconds("abc") is None
        assert tracker._parse_time_seconds("") is None


# ── Lamp bar fixtures ──

_LAMP_BGR = {
    "red": (0, 0, 255),
    "green": (0, 255, 0),
    "white": (255, 255, 255),
}


def _lamp_region_x(side, w=1280):
    """Painted x range for a side, using the same scaling as _get_region."""
    x_start, x_end = OVERLAY_LAYOUTS["usa_fencing"]["lamp_regions"][side]
    scale = w / 1280.0
    return int(x_start * scale), int(x_end * scale)


def _make_lamp_frame(left=None, right=None, left_fill=1.0, right_fill=1.0,
                     h=720, w=1280):
    """Black frame with the overlay bar painted to a given lamp fill fraction.

    `left`/`right` are "red"/"green"/"white"/None; the fill fraction is the
    fraction of the region's columns painted, over the full bar height.
    """
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    bar_h = int(OVERLAY_BAR_HEIGHT * h / 720)
    bar_y = min(int(h * OVERLAY_BAR_Y_RATIO), h - bar_h)

    for side, color, fill in (("left", left, left_fill), ("right", right, right_fill)):
        if color is None:
            continue
        x1, x2 = _lamp_region_x(side, w)
        painted = int((x2 - x1) * fill)
        frame[bar_y:bar_y + bar_h, x1:x1 + painted] = _LAMP_BGR[color]

    return frame


def _color_at(spans, idx):
    for start, end, color in spans:
        if start <= idx <= end:
            return color
    return None


def _lamp_frames(left_spans=(), right_spans=(), first=0, last=300,
                 step=LAMP_SAMPLE_STEP, h=720, w=1280):
    """Yield (frame_index, frame) over a sampling grid, lit per span."""
    for idx in range(first, last + 1, step):
        yield idx, _make_lamp_frame(
            left=_color_at(left_spans, idx),
            right=_color_at(right_spans, idx),
            h=h, w=w,
        )


def _idle_frame(h=720, w=1280):
    """Idle bar: coloured text on black, simulated as ~20% coloured pixels."""
    return _make_lamp_frame(
        left="red", right="green", left_fill=0.2, right_fill=0.2, h=h, w=w,
    )


# ── Lamp config / layout tests ──

class TestLampConfig:
    def test_on_threshold_between_idle_and_lit(self):
        assert 0.227 < LAMP_ON_FILL_THRESHOLD < 0.75

    def test_sample_step_positive(self):
        assert LAMP_SAMPLE_STEP > 0

    def test_merge_gap_above_measured_double_gap(self):
        assert LAMP_EVENT_MERGE_GAP >= 9

    def test_search_window(self):
        assert LAMP_SEARCH_LOOKBACK > LAMP_SEARCH_FORWARD > 0

    def test_confidence_shaping(self):
        assert LAMP_CONF_FULL_FILL > LAMP_ON_FILL_THRESHOLD
        assert LAMP_CONF_FULL_FRAMES > 0
        assert 0.0 < LAMP_CONF_MIN_DURATION_FACTOR < 1.0


class TestLampLayout:
    def test_lamp_regions_present(self):
        layout = OVERLAY_LAYOUTS["usa_fencing"]
        assert set(layout["lamp_regions"]) == {"left", "right"}

    def test_lamp_regions_match_name_regions(self):
        layout = OVERLAY_LAYOUTS["usa_fencing"]
        assert layout["lamp_regions"]["left"] == layout["regions"]["left_name"]
        assert layout["lamp_regions"]["right"] == layout["regions"]["right_name"]

    def test_lamp_colors(self):
        colors = OVERLAY_LAYOUTS["usa_fencing"]["lamp_colors"]
        assert colors["left"] == "red"
        assert colors["right"] == "green"


# ── Lamp dataclass tests ──

class TestLampDataclasses:
    def test_side_reading_to_dict(self):
        d = LampSideReading(state="color", peak_fill=0.76, on_frames=45).to_dict()
        assert d["state"] == "color"
        assert d["peak_fill"] == 0.76
        assert d["on_frames"] == 45

    def test_reading_defaults(self):
        reading = LampReading()
        assert reading.pattern is None
        assert reading.confidence == 0.0
        assert reading.left.state == "off"
        assert reading.right.state == "off"
        assert reading.start_frame is None
        assert reading.end_frame is None

    def test_reading_serializable(self):
        reading = LampReading(
            pattern="double",
            confidence=0.9,
            left=LampSideReading(state="color", peak_fill=0.75, on_frames=30),
            right=LampSideReading(state="color", peak_fill=0.82, on_frames=30),
            start_frame=100,
            end_frame=130,
            frames_sampled=11,
        )
        parsed = json.loads(json.dumps(reading.to_dict()))
        assert parsed["pattern"] == "double"
        assert parsed["left"]["state"] == "color"

    def test_event_to_dict(self):
        event = LampEvent(
            start_frame=10,
            end_frame=40,
            left=LampSideReading(state="color", peak_fill=0.75, on_frames=30),
            right=LampSideReading(),
            frames_sampled=11,
        )
        d = event.to_dict()
        assert d["start_frame"] == 10
        assert d["right"]["state"] == "off"


# ── LampBarReader tests ──

class TestLampBarReader:
    def test_constructs_without_pytesseract(self, monkeypatch):
        """Lamp reading is colour-fill based, so no OCR dependency is needed."""
        import analyzer.tv_overlay_ocr as module
        original = module.pytesseract
        try:
            module.pytesseract = None
            reader = LampBarReader()
            assert reader.layout is not None
        finally:
            module.pytesseract = original

    def test_invalid_layout_raises(self):
        with pytest.raises(ValueError, match="Unknown layout"):
            LampBarReader(layout="nonexistent")

    def test_read_side_fills_shape(self):
        reader = LampBarReader()
        fills = reader.read_side_fills(_idle_frame())
        assert set(fills) == {"left", "right"}
        assert set(fills["left"]) == {"red", "green", "white"}

    def test_idle_fills_below_threshold(self):
        reader = LampBarReader()
        fills = reader.read_side_fills(_idle_frame())
        assert fills["left"]["red"] == pytest.approx(0.2, abs=0.02)
        assert fills["right"]["green"] == pytest.approx(0.2, abs=0.02)
        assert fills["left"]["white"] == 0.0
        assert fills["right"]["white"] == 0.0

    def test_idle_frame_both_sides_off(self):
        reader = LampBarReader()
        assert reader.read_side_states(_idle_frame()) == ("off", "off")

    def test_red_lamp_left_only(self):
        reader = LampBarReader()
        frame = _make_lamp_frame(left="red", right="green", right_fill=0.2)
        assert reader.read_side_states(frame) == ("color", "off")

    def test_green_lamp_right_only(self):
        reader = LampBarReader()
        frame = _make_lamp_frame(left="red", left_fill=0.2, right="green")
        assert reader.read_side_states(frame) == ("off", "color")

    def test_white_lamp_both_sides(self):
        reader = LampBarReader()
        frame = _make_lamp_frame(left="white", right="white")
        assert reader.read_side_states(frame) == ("white", "white")

    def test_wrong_colour_does_not_light_a_side(self):
        """A green fill in the left region is not the left side's lamp colour."""
        reader = LampBarReader()
        frame = _make_lamp_frame(left="green", right="red")
        assert reader.read_side_states(frame) == ("off", "off")

    def test_fill_just_under_threshold_is_off(self):
        reader = LampBarReader()
        frame = _make_lamp_frame(left="red", left_fill=0.48)
        assert reader.read_side_states(frame)[0] == "off"

    def test_fill_just_over_threshold_is_on(self):
        reader = LampBarReader()
        frame = _make_lamp_frame(left="red", left_fill=0.52)
        assert reader.read_side_states(frame)[0] == "color"

    def test_no_overlay_bar_reads_off(self):
        reader = LampBarReader()
        assert reader.read_side_states(_make_frame_no_overlay()) == ("off", "off")


# ── Lamp pattern mapping ──

class TestLampPattern:
    def test_double(self):
        assert _lamp_pattern("color", "color") == "double"

    def test_single_left(self):
        assert _lamp_pattern("color", "off") == "single_left"
        assert _lamp_pattern("color", "white") == "single_left"

    def test_single_right(self):
        assert _lamp_pattern("off", "color") == "single_right"
        assert _lamp_pattern("white", "color") == "single_right"

    def test_white_only(self):
        assert _lamp_pattern("white", "white") == "white"
        assert _lamp_pattern("white", "off") == "white"
        assert _lamp_pattern("off", "white") == "white"

    def test_nothing(self):
        assert _lamp_pattern("off", "off") is None

    def test_white_event_from_scan_maps_to_white(self):
        reader = LampBarReader()
        events = reader.scan_events(_lamp_frames(
            left_spans=[(30, 60, "white")],
            right_spans=[(30, 60, "white")],
            last=90,
        ))
        assert len(events) == 1
        assert _lamp_pattern(events[0].left.state, events[0].right.state) == "white"

    def test_single_white_side_from_scan_maps_to_white(self):
        reader = LampBarReader()
        events = reader.scan_events(_lamp_frames(
            left_spans=[(30, 60, "white")],
            last=90,
        ))
        assert len(events) == 1
        assert events[0].right.state == "off"
        assert _lamp_pattern(events[0].left.state, events[0].right.state) == "white"


# ── scan_events tests ──

class TestLampScanEvents:
    def test_idle_sequence_yields_no_events(self):
        reader = LampBarReader()
        frames = ((i, _idle_frame()) for i in range(0, 60, LAMP_SAMPLE_STEP))
        assert reader.scan_events(frames) == []

    def test_single_event_bounds_and_states(self):
        reader = LampBarReader()
        events = reader.scan_events(_lamp_frames(
            left_spans=[(30, 60, "red")],
            last=120,
        ))
        assert len(events) == 1
        event = events[0]
        assert event.start_frame == 30
        assert event.end_frame == 60
        assert event.left.state == "color"
        assert event.right.state == "off"
        assert event.left.peak_fill == 1.0
        assert event.frames_sampled == 11

    def test_on_frames_counts_frames_not_samples(self):
        reader = LampBarReader()
        events = reader.scan_events(_lamp_frames(
            left_spans=[(30, 60, "red")],
            last=120,
        ))
        assert events[0].left.on_frames == 11 * LAMP_SAMPLE_STEP

    def test_sequential_double_merges_into_one_event(self):
        """Measured case: the two lamps of a double render sequentially."""
        reader = LampBarReader()
        events = reader.scan_events(_lamp_frames(
            left_spans=[(0, 6, "red")],
            right_spans=[(18, 45, "green")],
            last=120,
        ))
        assert len(events) == 1
        assert events[0].left.state == "color"
        assert events[0].right.state == "color"
        assert events[0].start_frame == 0
        assert events[0].end_frame == 45

    def test_far_apart_runs_stay_separate(self):
        reader = LampBarReader()
        events = reader.scan_events(_lamp_frames(
            left_spans=[(0, 6, "red")],
            right_spans=[(66, 90, "green")],
            last=150,
        ))
        assert len(events) == 2
        assert events[0].left.state == "color"
        assert events[0].right.state == "off"
        assert events[1].left.state == "off"
        assert events[1].right.state == "color"

    def test_merged_event_on_frames_exclude_the_gap(self):
        reader = LampBarReader()
        events = reader.scan_events(_lamp_frames(
            left_spans=[(0, 6, "red")],
            right_spans=[(18, 45, "green")],
            last=120,
        ))
        event = events[0]
        assert event.left.on_frames == 3 * LAMP_SAMPLE_STEP
        assert event.right.on_frames == 10 * LAMP_SAMPLE_STEP

    def test_union_state_prefers_color_over_white(self):
        reader = LampBarReader()
        events = reader.scan_events(_lamp_frames(
            left_spans=[(0, 15, "white"), (18, 30, "red")],
            last=90,
        ))
        assert len(events) == 1
        assert events[0].left.state == "color"


# ── read_touch_lamp tests ──

class TestReadTouchLamp:
    def test_single_left_pattern(self):
        reader = LampBarReader()
        events = reader.scan_events(_lamp_frames(
            left_spans=[(30, 90, "red")],
            last=200,
        ))
        reading = reader.read_touch_lamp(events, touch_frame=180)
        assert reading.pattern == "single_left"
        assert reading.start_frame == 30
        assert reading.end_frame == 90

    def test_single_right_pattern(self):
        reader = LampBarReader()
        events = reader.scan_events(_lamp_frames(
            right_spans=[(30, 90, "green")],
            last=200,
        ))
        reading = reader.read_touch_lamp(events, touch_frame=180)
        assert reading.pattern == "single_right"

    def test_double_pattern(self):
        reader = LampBarReader()
        events = reader.scan_events(_lamp_frames(
            left_spans=[(30, 90, "red")],
            right_spans=[(30, 90, "green")],
            last=200,
        ))
        reading = reader.read_touch_lamp(events, touch_frame=180)
        assert reading.pattern == "double"

    def test_mirroring_swaps_single_left_and_single_right(self):
        reader = LampBarReader()
        left_events = reader.scan_events(_lamp_frames(
            left_spans=[(30, 90, "red")], last=200,
        ))
        right_events = reader.scan_events(_lamp_frames(
            right_spans=[(30, 90, "green")], last=200,
        ))
        left_reading = reader.read_touch_lamp(left_events, touch_frame=180)
        right_reading = reader.read_touch_lamp(right_events, touch_frame=180)

        assert left_reading.pattern == "single_left"
        assert right_reading.pattern == "single_right"
        assert left_reading.left.to_dict() == right_reading.right.to_dict()
        assert left_reading.right.to_dict() == right_reading.left.to_dict()

    def test_no_events_returns_empty_reading(self):
        reader = LampBarReader()
        reading = reader.read_touch_lamp([], touch_frame=100)
        assert reading.pattern is None
        assert reading.confidence == 0.0
        assert reading.left.state == "off"
        assert reading.right.state == "off"
        assert reading.start_frame is None
        assert reading.end_frame is None

    def test_white_only_event_never_wins_over_colour_event(self):
        """A white-only event cannot have produced a point, however close it is."""
        reader = LampBarReader()
        events = reader.scan_events(_lamp_frames(
            left_spans=[(0, 30, "red"), (200, 230, "white")],
            right_spans=[(200, 230, "white")],
            last=300,
        ))
        assert len(events) == 2

        reading = reader.read_touch_lamp(events, touch_frame=260)
        assert reading.pattern == "single_left"
        assert reading.start_frame == 0

    def test_latest_qualifying_event_wins(self):
        reader = LampBarReader()
        events = reader.scan_events(_lamp_frames(
            left_spans=[(0, 30, "red")],
            right_spans=[(201, 231, "green")],
            last=300,
        ))
        reading = reader.read_touch_lamp(events, touch_frame=260)
        assert reading.pattern == "single_right"
        assert reading.start_frame == 201

    def test_previous_end_prevents_reusing_previous_touch_event(self):
        reader = LampBarReader()
        events = reader.scan_events(_lamp_frames(
            left_spans=[(0, 30, "red")],
            right_spans=[(201, 231, "green")],
            last=300,
        ))
        first = reader.read_touch_lamp(events, touch_frame=100)
        assert first.pattern == "single_left"

        clamped = reader.read_touch_lamp(
            events, touch_frame=100, previous_end=first.end_frame,
        )
        assert clamped.pattern is None

        second = reader.read_touch_lamp(
            events, touch_frame=260, previous_end=first.end_frame,
        )
        assert second.pattern == "single_right"
        assert second.start_frame == 201

    def test_event_beyond_lookback_is_rejected(self):
        reader = LampBarReader()
        events = reader.scan_events(_lamp_frames(
            left_spans=[(0, 30, "red")],
            last=60,
        ))
        assert reader.read_touch_lamp(events, touch_frame=400).pattern is None
        assert reader.read_touch_lamp(
            events, touch_frame=LAMP_SEARCH_LOOKBACK,
        ).pattern == "single_left"

    def test_event_beyond_forward_window_is_rejected(self):
        reader = LampBarReader()
        events = reader.scan_events(_lamp_frames(
            left_spans=[(300, 330, "red")],
            first=300, last=360,
        ))
        assert reader.read_touch_lamp(events, touch_frame=100).pattern is None


# ── Lamp confidence tests ──

class TestLampConfidence:
    def _double_events(self):
        reader = LampBarReader()
        return reader, reader.scan_events(_lamp_frames(
            left_spans=[(0, 90, "red"), (201, 288, "red")],
            right_spans=[(0, 90, "green"), (201, 207, "green")],
            last=330,
        ))

    def test_short_second_lamp_scores_lower_than_a_long_one(self):
        reader, events = self._double_events()
        assert len(events) == 2

        long_double = reader.read_touch_lamp(events, touch_frame=120)
        short_double = reader.read_touch_lamp(events, touch_frame=320)

        assert long_double.pattern == "double"
        assert short_double.pattern == "double"
        assert short_double.confidence < long_double.confidence

    def test_confidence_within_unit_range(self):
        reader, events = self._double_events()
        for touch_frame in (120, 320):
            reading = reader.read_touch_lamp(events, touch_frame=touch_frame)
            assert 0.0 <= reading.confidence <= 1.0

    def test_short_lamp_confidence_floored_by_duration_factor(self):
        reader, events = self._double_events()
        short_double = reader.read_touch_lamp(events, touch_frame=320)
        assert short_double.confidence >= LAMP_CONF_MIN_DURATION_FACTOR * 0.5

    def test_full_fill_and_duration_saturate_at_one(self):
        reader = LampBarReader()
        events = reader.scan_events(_lamp_frames(
            left_spans=[(0, 90, "red")],
            last=150,
        ))
        reading = reader.read_touch_lamp(events, touch_frame=120)
        assert reading.left.peak_fill >= LAMP_CONF_FULL_FILL
        assert reading.left.on_frames >= LAMP_CONF_FULL_FRAMES
        assert reading.confidence == 1.0

    def test_marginal_fill_lowers_confidence(self):
        reader = LampBarReader()
        strong = reader.scan_events(_lamp_frames(
            left_spans=[(0, 90, "red")], last=150,
        ))
        marginal = reader.scan_events(
            (i, _make_lamp_frame(left="red", left_fill=0.55))
            for i in range(0, 91, LAMP_SAMPLE_STEP)
        )
        strong_reading = reader.read_touch_lamp(strong, touch_frame=120)
        marginal_reading = reader.read_touch_lamp(marginal, touch_frame=120)
        assert marginal_reading.confidence < strong_reading.confidence
