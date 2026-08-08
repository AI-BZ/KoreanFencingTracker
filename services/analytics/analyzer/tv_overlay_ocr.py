"""
TV broadcast overlay OCR for USA Fencing style score bars.

Extracts fencer names, scores, time, period, and card information
from the bottom overlay bar of TV broadcast footage. Designed for
USA Fencing YouTube streams (1280x720, 30fps).

Overlay structure (USA Fencing):
    [flag] LASTNAME First  L_SCORE  TIME  R_SCORE  LASTNAME First [flag]
                                   PERIOD
"""

import cv2
import numpy as np
from dataclasses import dataclass, field, asdict
from typing import Optional, Tuple, List

try:
    import pytesseract
except ImportError:
    pytesseract = None

from analyzer.config import (
    OVERLAY_BAR_Y_RATIO,
    OVERLAY_BAR_HEIGHT,
    OVERLAY_SCORE_DEBOUNCE,
    OVERLAY_OCR_SAMPLE_INTERVAL,
    OVERLAY_MIN_SCORE_CONFIDENCE,
    OVERLAY_TEXT_SCALE,
    OVERLAY_WHITE_LOWER,
    OVERLAY_WHITE_UPPER,
    OVERLAY_RED_LOWER_1,
    OVERLAY_RED_UPPER_1,
    OVERLAY_RED_LOWER_2,
    OVERLAY_RED_UPPER_2,
    OVERLAY_GREEN_LOWER,
    OVERLAY_GREEN_UPPER,
    OVERLAY_YELLOW_LOWER,
    OVERLAY_YELLOW_UPPER,
    OVERLAY_BLUE_LOWER,
    OVERLAY_BLUE_UPPER,
    CLOCK_RUNNING_CONFIRM_FRAMES,
    CLOCK_STOPPED_CONFIRM_FRAMES,
)


# ── Layout presets ──────────────────────────────────────────

OVERLAY_LAYOUTS = {
    "usa_fencing": {
        "bar_y_ratio": OVERLAY_BAR_Y_RATIO,
        "bar_height": OVERLAY_BAR_HEIGHT,
        "regions": {
            # x_start, x_end pixel ranges at 1280 width
            # left_name starts at 120 to skip the flag icon (~70-110)
            "left_name":   (120, 440),
            "left_score":  (440, 540),
            "center":      (540, 740),
            "right_score": (740, 840),
            # right_name ends at 1175 to skip the flag icon (~1180-1210)
            "right_name":  (840, 1175),
        },
        "text_colors": {
            "name_primary": "white",
            "name_secondary": "red",
            "score": ["white", "green"],
            "time": ["white", "green", "red", "blue"],
        },
    },
}


# ── Data classes ────────────────────────────────────────────

@dataclass
class OverlayData:
    """Parsed data from a single frame's TV overlay bar."""
    left_name: Optional[str] = None
    right_name: Optional[str] = None
    left_score: Optional[int] = None
    right_score: Optional[int] = None
    time_remaining: Optional[str] = None   # "M:SS" or "S"
    period: Optional[int] = None
    yellow_card_left: bool = False
    yellow_card_right: bool = False
    red_card_left: bool = False
    red_card_right: bool = False
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TVTouchEvent:
    """A scoring event detected from overlay score changes."""
    frame: int
    timestamp: float
    scorer: str               # "left" or "right"
    score_before: str         # "2-1"
    score_after: str          # "3-1"
    period: Optional[int] = None
    match_time_remaining: Optional[str] = None  # "2:28" from scoreboard

    def to_dict(self) -> dict:
        return asdict(self)


def _valid_clock_text(text: str) -> bool:
    """Validate an OCR'd match clock reading: "M:SS", "MM:SS" or bare seconds.

    A fencing scoreboard clock always shows two seconds digits, so a reading
    like "2:3" or "2:" means the OCR dropped a digit — the true value cannot be
    recovered, so it must be rejected rather than stored as a broken time.
    """
    if ":" in text:
        parts = text.split(":")
        return (
            len(parts) == 2
            and parts[0].isdigit() and 1 <= len(parts[0]) <= 2
            and parts[1].isdigit() and len(parts[1]) == 2
            and int(parts[1]) < 60
        )
    if text.isdigit():
        return 0 <= int(text) <= 180  # 3 minutes max
    return False


# ── TVOverlayOCR ────────────────────────────────────────────

class TVOverlayOCR:
    """Extract scores, names, time from USA Fencing style TV overlay bars."""

    def __init__(self, layout: str = "usa_fencing"):
        if pytesseract is None:
            raise ImportError(
                "pytesseract is required for TVOverlayOCR. "
                "Install with: pip install pytesseract"
            )
        if layout not in OVERLAY_LAYOUTS:
            raise ValueError(f"Unknown layout: {layout}. Available: {list(OVERLAY_LAYOUTS.keys())}")
        self.layout = OVERLAY_LAYOUTS[layout]
        self._scale = OVERLAY_TEXT_SCALE

    # ── Public API ──

    def read_overlay(self, frame: np.ndarray) -> Optional[OverlayData]:
        """Extract overlay data from a single frame.

        Args:
            frame: BGR image (e.g., from cv2.VideoCapture).

        Returns:
            OverlayData if overlay is detected, None otherwise.
        """
        if not self.detect_overlay_presence(frame):
            return None

        bar = self._crop_overlay_bar(frame)
        if bar is None or bar.size == 0:
            return None

        left_score, right_score, score_conf = self._extract_scores(bar)
        left_name, right_name = self._extract_names(bar)
        time_str, period = self._extract_time(bar)
        yl, yr, rl, rr = self._detect_cards(bar)

        # Overall confidence: weighted by score extraction quality
        confidences = [score_conf]
        if left_name:
            confidences.append(0.8)
        if time_str:
            confidences.append(0.8)
        overall = sum(confidences) / len(confidences) if confidences else 0.0

        return OverlayData(
            left_name=left_name,
            right_name=right_name,
            left_score=left_score,
            right_score=right_score,
            time_remaining=time_str,
            period=period,
            yellow_card_left=yl,
            yellow_card_right=yr,
            red_card_left=rl,
            red_card_right=rr,
            confidence=round(overall, 3),
        )

    def detect_overlay_presence(self, frame: np.ndarray) -> bool:
        """Detect whether the overlay bar is present in the frame.

        Checks for a dark horizontal bar in the expected region with
        enough bright (white/colored) text pixels.
        """
        h, w = frame.shape[:2]
        bar_y = int(h * self.layout["bar_y_ratio"])
        bar_h = self.layout["bar_height"]

        # Scale bar_h if frame isn't 720p
        bar_h = int(bar_h * h / 720)
        bar_y = min(bar_y, h - bar_h)

        if bar_y < 0 or bar_h <= 0:
            return False

        bar = frame[bar_y:bar_y + bar_h, :, :]
        if bar.size == 0:
            return False

        # The overlay bar is typically dark with bright text on top
        gray = cv2.cvtColor(bar, cv2.COLOR_BGR2GRAY)
        mean_brightness = gray.mean()
        bright_ratio = (gray > 180).sum() / gray.size

        # Dark bar (mean < 100) with some bright text pixels (> 3%)
        return bool(mean_brightness < 120 and bright_ratio > 0.03)

    # ── Internal methods ──

    def _crop_overlay_bar(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """Crop the overlay bar region from the frame."""
        h, w = frame.shape[:2]
        bar_y = int(h * self.layout["bar_y_ratio"])
        bar_h = int(self.layout["bar_height"] * h / 720)
        bar_y = min(bar_y, h - bar_h)

        if bar_y < 0 or bar_h <= 0:
            return None

        bar = frame[bar_y:bar_y + bar_h, :, :]

        # Scale x regions proportionally if not 1280 wide
        # The bar is returned at original width; _get_region handles scaling
        return bar

    def _get_region(self, bar: np.ndarray, region_name: str) -> Optional[np.ndarray]:
        """Crop a named region from the overlay bar, scaling for frame width."""
        regions = self.layout["regions"]
        if region_name not in regions:
            return None

        x_start, x_end = regions[region_name]
        # Scale x coordinates relative to 1280-wide reference
        bar_w = bar.shape[1]
        scale_x = bar_w / 1280.0
        x1 = int(x_start * scale_x)
        x2 = int(x_end * scale_x)
        x1 = max(0, min(x1, bar_w - 1))
        x2 = max(x1 + 1, min(x2, bar_w))

        return bar[:, x1:x2]

    def _extract_scores(self, bar: np.ndarray) -> Tuple[Optional[int], Optional[int], float]:
        """Extract left and right scores from the overlay bar.

        Returns:
            (left_score, right_score, confidence)
        """
        left_region = self._get_region(bar, "left_score")
        right_region = self._get_region(bar, "right_score")

        left_score, left_conf = self._ocr_score(left_region)
        right_score, right_conf = self._ocr_score(right_region)

        confidence = (left_conf + right_conf) / 2 if left_conf + right_conf > 0 else 0.0
        return left_score, right_score, confidence

    def _ocr_score(self, region: Optional[np.ndarray]) -> Tuple[Optional[int], float]:
        """OCR a single score region. Returns (score, confidence).

        Tries HSV color-filtered approach first, then falls back to
        adaptive (Otsu) thresholding if the color approach fails.
        """
        if region is None or region.size == 0:
            return None, 0.0

        tesseract_config = "--psm 7 -c tessedit_char_whitelist=0123456789"

        # Primary: HSV color-filtered approach
        processed = self._preprocess_region(
            region,
            text_colors=["white", "green", "blue", "yellow"],
            scale=self._scale,
        )

        score = self._parse_score_text(processed, tesseract_config)
        if score is not None:
            return score, 0.9

        # Fallback: Otsu adaptive thresholding (handles unknown text colors)
        processed_otsu = self._preprocess_name_region(region, scale=self._scale)
        score = self._parse_score_text(processed_otsu, tesseract_config)
        if score is not None:
            return score, 0.7  # lower confidence for fallback

        return None, 0.0

    def _parse_score_text(self, processed: np.ndarray, config: str) -> Optional[int]:
        """Run Tesseract on a preprocessed image and parse as score."""
        try:
            text = pytesseract.image_to_string(processed, config=config).strip()
            if text and text.isdigit():
                score = int(text)
                if 0 <= score <= 45:  # reasonable fencing score range
                    return score
            return None
        except Exception:
            return None

    def _extract_names(self, bar: np.ndarray) -> Tuple[Optional[str], Optional[str]]:
        """Extract left and right fencer names."""
        left_region = self._get_region(bar, "left_name")
        right_region = self._get_region(bar, "right_name")

        left_name = self._ocr_name(left_region)
        right_name = self._ocr_name(right_region)

        return left_name, right_name

    def _ocr_name(self, region: Optional[np.ndarray]) -> Optional[str]:
        """OCR a single name region.

        Uses adaptive (Otsu) thresholding instead of HSV color filtering
        to handle varying backgrounds: black (normal), red (scoring
        highlight on left), green (right side background).
        """
        if region is None or region.size == 0:
            return None

        processed = self._preprocess_name_region(region, scale=self._scale)

        try:
            text = pytesseract.image_to_string(
                processed,
                config="--psm 7",
            ).strip()

            # Clean up OCR artifacts
            text = text.replace("|", "").replace("\\", "").strip()
            # Strip leading non-alpha chars (flag residue, OCR garbage like =, ], [)
            import re
            text = re.sub(r'^[^A-Za-z]+', '', text)
            text = re.sub(r'[^A-Za-z\s]+$', '', text).strip()
            # Filter out very short or garbage results
            if len(text) >= 3 and any(c.isalpha() for c in text):
                return text
            return None
        except Exception:
            return None

    def _preprocess_name_region(self, crop: np.ndarray, scale: int = 3) -> np.ndarray:
        """Preprocess a name region using adaptive thresholding.

        Unlike _preprocess_region which uses HSV color masks, this uses
        Otsu thresholding on the grayscale image. This adapts to any
        background color (black, red highlight, green) automatically.
        """
        h, w = crop.shape[:2]
        scaled = cv2.resize(crop, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)

        gray = cv2.cvtColor(scaled, cv2.COLOR_BGR2GRAY)
        # Otsu automatically finds the optimal threshold between
        # dark background and bright text, regardless of background color
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # Invert if needed: text should be white (255) on black (0)
        # If more than half the pixels are white, the image is inverted
        if binary.mean() > 127:
            binary = cv2.bitwise_not(binary)

        # Morphological close to connect broken characters
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

        return binary

    def _extract_time(self, bar: np.ndarray) -> Tuple[Optional[str], Optional[int]]:
        """Extract remaining time and period number."""
        center = self._get_region(bar, "center")
        if center is None or center.size == 0:
            return None, None

        # Time is in the upper portion of center, period below
        h = center.shape[0]
        time_region = center[:int(h * 0.65), :]
        period_region = center[int(h * 0.65):, :]

        time_str = self._ocr_time(time_region)
        period = self._ocr_period(period_region)

        return time_str, period

    def _ocr_time(self, region: Optional[np.ndarray]) -> Optional[str]:
        """OCR the time display (M:SS or seconds)."""
        if region is None or region.size == 0:
            return None

        # Time text can be white, green, red, or blue/cyan depending
        # on the broadcast state (running, stopped, penalty, etc.)
        processed = self._preprocess_region(
            region,
            text_colors=["white", "green", "red", "blue"],
            scale=self._scale,
        )

        try:
            text = pytesseract.image_to_string(
                processed,
                config="--psm 7 -c tessedit_char_whitelist=0123456789:",
            ).strip()

            if not text:
                return None
            if _valid_clock_text(text):
                return text
            return None
        except Exception:
            return None

    def _ocr_period(self, region: Optional[np.ndarray]) -> Optional[int]:
        """OCR the period number."""
        if region is None or region.size == 0:
            return None

        processed = self._preprocess_region(
            region,
            text_colors=["white", "red", "blue"],
            scale=self._scale,
        )

        try:
            text = pytesseract.image_to_string(
                processed,
                config="--psm 10 -c tessedit_char_whitelist=0123456789",
            ).strip()

            if text and text.isdigit():
                p = int(text)
                if 1 <= p <= 3:
                    return p
            return None
        except Exception:
            return None

    def _detect_cards(self, bar: np.ndarray) -> Tuple[bool, bool, bool, bool]:
        """Detect yellow and red cards.

        Returns:
            (yellow_left, yellow_right, red_left, red_right)
        """
        hsv = cv2.cvtColor(bar, cv2.COLOR_BGR2HSV)
        bar_w = bar.shape[1]
        mid = bar_w // 2

        # Yellow card detection
        yellow_mask = cv2.inRange(
            hsv,
            np.array(OVERLAY_YELLOW_LOWER),
            np.array(OVERLAY_YELLOW_UPPER),
        )
        left_yellow = yellow_mask[:, :mid]
        right_yellow = yellow_mask[:, mid:]

        # Threshold: at least 50 yellow pixels in a region
        yl = bool(left_yellow.sum() / 255 > 50)
        yr = bool(right_yellow.sum() / 255 > 50)

        # Red card: use the existing red HSV ranges
        red_mask1 = cv2.inRange(
            hsv,
            np.array(OVERLAY_RED_LOWER_1),
            np.array(OVERLAY_RED_UPPER_1),
        )
        red_mask2 = cv2.inRange(
            hsv,
            np.array(OVERLAY_RED_LOWER_2),
            np.array(OVERLAY_RED_UPPER_2),
        )
        red_mask = cv2.bitwise_or(red_mask1, red_mask2)

        # Red cards are small blocks near the name areas; use a higher
        # threshold to avoid false positives from red name text
        # Look for concentrated red blocks (not scattered text)
        left_red = red_mask[:, :int(bar_w * 0.05)]
        right_red = red_mask[:, int(bar_w * 0.95):]

        rl = bool(left_red.sum() / 255 > 30)
        rr = bool(right_red.sum() / 255 > 30)

        return yl, yr, rl, rr

    def _preprocess_region(
        self,
        crop: np.ndarray,
        text_colors: list,
        scale: int = 3,
    ) -> np.ndarray:
        """Preprocess a crop for OCR: scale up + color filter + binarize.

        Args:
            crop: BGR image region.
            text_colors: List of color names to extract ("white", "red", "green").
            scale: Scale factor for upsampling.

        Returns:
            Binary (white text on black) image ready for Tesseract.
        """
        # Scale up for better OCR
        h, w = crop.shape[:2]
        scaled = cv2.resize(crop, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)

        # Convert to HSV for color filtering
        hsv = cv2.cvtColor(scaled, cv2.COLOR_BGR2HSV)

        # Build combined mask for all requested text colors
        mask = np.zeros(hsv.shape[:2], dtype=np.uint8)

        for color in text_colors:
            if color == "white":
                m = cv2.inRange(hsv, np.array(OVERLAY_WHITE_LOWER), np.array(OVERLAY_WHITE_UPPER))
                mask = cv2.bitwise_or(mask, m)
            elif color == "red":
                m1 = cv2.inRange(hsv, np.array(OVERLAY_RED_LOWER_1), np.array(OVERLAY_RED_UPPER_1))
                m2 = cv2.inRange(hsv, np.array(OVERLAY_RED_LOWER_2), np.array(OVERLAY_RED_UPPER_2))
                mask = cv2.bitwise_or(mask, cv2.bitwise_or(m1, m2))
            elif color == "green":
                m = cv2.inRange(hsv, np.array(OVERLAY_GREEN_LOWER), np.array(OVERLAY_GREEN_UPPER))
                mask = cv2.bitwise_or(mask, m)
            elif color == "blue":
                m = cv2.inRange(hsv, np.array(OVERLAY_BLUE_LOWER), np.array(OVERLAY_BLUE_UPPER))
                mask = cv2.bitwise_or(mask, m)
            elif color == "yellow":
                m = cv2.inRange(hsv, np.array(OVERLAY_YELLOW_LOWER), np.array(OVERLAY_YELLOW_UPPER))
                mask = cv2.bitwise_or(mask, m)

        # Morphological operations to connect broken characters
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        return mask


# ── TVScoreTracker ──────────────────────────────────────────

class TVScoreTracker:
    """Track overlay scores across frames to detect touch events.

    Uses debouncing to filter OCR noise: a score change is only
    confirmed after it remains stable for `debounce_frames` frames.
    """

    def __init__(self, debounce_frames: int = OVERLAY_SCORE_DEBOUNCE):
        self._debounce = debounce_frames
        self._confirmed_score: Tuple[Optional[int], Optional[int]] = (None, None)
        self._pending_score: Optional[Tuple[int, int]] = None
        self._pending_since: int = 0
        self._pending_period: Optional[int] = None
        self._pending_time_remaining: Optional[str] = None
        self._events: List[TVTouchEvent] = []
        self._last_fps: float = 30.0
        # Clock state tracking (Allez/Halt proxy)
        self._clock_state: str = "unknown"  # "running" | "stopped" | "unknown"
        self._clock_consecutive_same: int = 0
        self._clock_consecutive_diff: int = 0
        self._clock_last_seconds: Optional[float] = None
        self._clock_events: List[dict] = []

    def update(self, frame_num: int, data: OverlayData, fps: float = 30.0) -> Optional[TVTouchEvent]:
        """Process a new frame's overlay data.

        Args:
            frame_num: Current frame number.
            data: Parsed overlay data from TVOverlayOCR.
            fps: Video FPS for timestamp calculation.

        Returns:
            TVTouchEvent if a new touch is confirmed, None otherwise.
        """
        self._last_fps = fps
        self._update_clock_state(frame_num, data)
        left = data.left_score
        right = data.right_score

        # Ignore frames where OCR failed on scores
        if left is None or right is None:
            return None

        current = (left, right)

        # First reading: initialize
        if self._confirmed_score == (None, None):
            self._confirmed_score = current
            return None

        # Same as confirmed: reset pending
        if current == self._confirmed_score:
            self._pending_score = None
            return None

        # Score decreased from confirmed? OCR error, ignore
        cl, cr = self._confirmed_score
        if cl is not None and cr is not None:
            if left < cl or right < cr:
                return None
            # In fencing, each touch scores exactly 1 point per side.
            # A jump of more than 2 points per side is an OCR error.
            if (left - cl) > 2 or (right - cr) > 2:
                return None

        # New potential score change
        if current != self._pending_score:
            self._pending_score = current
            self._pending_since = frame_num
            self._pending_period = data.period
            self._pending_time_remaining = data.time_remaining
            return None

        # Same pending score: check debounce window
        if frame_num - self._pending_since >= self._debounce:
            event = self._create_event(frame_num, current, data.period)
            self._confirmed_score = current
            self._pending_score = None
            return event

        return None

    def get_all_events(self) -> List[TVTouchEvent]:
        """Return all confirmed touch events."""
        return list(self._events)

    def get_match_summary(self) -> dict:
        """Generate a match summary from detected events."""
        events = self._events
        if not events:
            return {
                "total_touches": 0,
                "final_score": "0-0",
                "events": [],
            }

        last = events[-1]
        final = last.score_after

        # Count by scorer
        left_touches = sum(1 for e in events if e.scorer == "left")
        right_touches = sum(1 for e in events if e.scorer == "right")

        # Period breakdown
        periods: dict = {}
        for e in events:
            p = e.period or 0
            if p not in periods:
                periods[p] = {"left": 0, "right": 0}
            periods[p][e.scorer] += 1

        return {
            "total_touches": len(events),
            "final_score": final,
            "left_touches": left_touches,
            "right_touches": right_touches,
            "period_breakdown": periods,
            "events": [e.to_dict() for e in events],
        }

    def reset(self):
        """Reset tracker state for a new match."""
        self._confirmed_score = (None, None)
        self._pending_score = None
        self._pending_since = 0
        self._pending_period = None
        self._pending_time_remaining = None
        self._events = []
        self._clock_state = "unknown"
        self._clock_consecutive_same = 0
        self._clock_consecutive_diff = 0
        self._clock_last_seconds = None
        self._clock_events = []

    # ── Clock state tracking ──

    def _parse_time_seconds(self, time_str: Optional[str]) -> Optional[float]:
        """Convert time string ("M:SS" or "SS") to seconds.

        Args:
            time_str: Time string from overlay OCR.

        Returns:
            Time in seconds, or None if unparseable.
        """
        if not time_str:
            return None
        if ":" in time_str:
            parts = time_str.split(":")
            if len(parts) == 2 and all(p and p.isdigit() for p in parts):
                return int(parts[0]) * 60 + int(parts[1])
        elif time_str.isdigit():
            return float(time_str)
        return None

    def _update_clock_state(self, frame_num: int, data: OverlayData) -> None:
        """Track clock running/stopped transitions from time_remaining changes.

        Clock running (time decreasing) → "allez" event proxy.
        Clock stopped (time unchanged) → "halt" event proxy.
        """
        seconds = self._parse_time_seconds(data.time_remaining)
        if seconds is None:
            return

        if self._clock_last_seconds is None:
            self._clock_last_seconds = seconds
            return

        if seconds < self._clock_last_seconds:
            # Time decreased → clock is running
            self._clock_consecutive_diff += 1
            self._clock_consecutive_same = 0
            if (self._clock_consecutive_diff >= CLOCK_RUNNING_CONFIRM_FRAMES
                    and self._clock_state != "running"):
                self._clock_state = "running"
                self._clock_events.append({
                    "frame": frame_num,
                    "event": "allez",
                    "time": data.time_remaining,
                })
        elif seconds == self._clock_last_seconds:
            # Time unchanged → clock may be stopped
            self._clock_consecutive_same += 1
            self._clock_consecutive_diff = 0
            if (self._clock_consecutive_same >= CLOCK_STOPPED_CONFIRM_FRAMES
                    and self._clock_state != "stopped"):
                self._clock_state = "stopped"
                self._clock_events.append({
                    "frame": frame_num,
                    "event": "halt",
                    "time": data.time_remaining,
                })
        else:
            # Time increased → OCR error or period change, reset counters
            self._clock_consecutive_same = 0
            self._clock_consecutive_diff = 0

        self._clock_last_seconds = seconds

    def get_clock_events(self) -> List[dict]:
        """Return clock state change events (Allez/Halt proxy).

        Returns:
            List of {"frame": int, "event": "allez"|"halt", "time": str}
        """
        return list(self._clock_events)

    def _create_event(
        self,
        frame_num: int,
        new_score: Tuple[int, int],
        period: Optional[int],
    ) -> TVTouchEvent:
        """Create a touch event from a confirmed score change."""
        old_l, old_r = self._confirmed_score
        new_l, new_r = new_score

        # Determine who scored
        left_diff = (new_l - old_l) if old_l is not None and new_l is not None else 0
        right_diff = (new_r - old_r) if old_r is not None and new_r is not None else 0

        if left_diff > right_diff:
            scorer = "left"
        elif right_diff > left_diff:
            scorer = "right"
        else:
            scorer = "left"  # tie-break: shouldn't happen often

        score_before = f"{old_l or 0}-{old_r or 0}"
        score_after = f"{new_l}-{new_r}"

        event = TVTouchEvent(
            frame=self._pending_since,  # frame where change first appeared
            timestamp=self._pending_since / self._last_fps,
            scorer=scorer,
            score_before=score_before,
            score_after=score_after,
            period=period,
            match_time_remaining=self._pending_time_remaining,
        )
        self._events.append(event)
        return event
