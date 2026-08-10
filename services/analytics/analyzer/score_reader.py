"""
7-segment LED score reader for fencing scoring machines.

Extracted from fencing_analyzer_v3.py — reads scores from the
LED display using template matching and segment pattern analysis.
"""

import cv2
import numpy as np
import pickle
from pathlib import Path
from typing import Optional, Tuple, Dict, List

from analyzer.config import (
    SCORE_RED_LOWER_1,
    SCORE_RED_UPPER_1,
    SCORE_RED_LOWER_2,
    SCORE_RED_UPPER_2,
    DIGIT_NORM_WIDTH,
    DIGIT_NORM_HEIGHT,
    TEMPLATE_MATCH_THRESHOLD,
    SEGMENT_MIN_PIXEL_RATIO,
    DIGIT_ONE_ASPECT_THRESHOLD,
    DYNAMIC_THRESHOLD_FRACTION,
    DYNAMIC_THRESHOLD_MIN,
    SEVEN_SEGMENT_PATTERNS,
    CLOCK_RED_LOWER_1,
    CLOCK_RED_UPPER_1,
    CLOCK_RED_LOWER_2,
    CLOCK_RED_UPPER_2,
    CLOCK_BRIGHTNESS_THRESHOLD,
    COLON_ASPECT_THRESHOLD,
)

# Default template file path
_DEFAULT_TEMPLATE_PATH = Path(__file__).parent.parent / "ml" / "models" / "digit_templates.pkl"


class ScoreReader:
    """Reads scores from 7-segment LED displays on fencing scoring machines."""

    def __init__(self, template_path: Optional[Path] = None):
        self.template_path = template_path or _DEFAULT_TEMPLATE_PATH
        self.digit_templates: Dict[str, Dict[int, list]] = {"left": {}, "right": {}}
        self.show_segment_debug = False
        self.load_templates()

    # ------------------------------------------------------------------
    # Template management
    # ------------------------------------------------------------------

    def load_templates(self):
        """Load saved digit templates from pickle file."""
        if self.template_path.exists():
            try:
                with open(self.template_path, "rb") as f:
                    self.digit_templates = pickle.load(f)
            except Exception:
                self.digit_templates = {"left": {}, "right": {}}

    def save_templates(self):
        """Merge and save digit templates to pickle file."""
        try:
            with open(self.template_path, "rb") as f:
                existing = pickle.load(f)
        except Exception:
            existing = {"left": {}, "right": {}}

        for side in ["left", "right"]:
            if side not in existing:
                existing[side] = {}
            if side in self.digit_templates:
                for digit, features in self.digit_templates[side].items():
                    if digit not in existing[side]:
                        existing[side][digit] = []
                    existing[side][digit].extend(features)

        self.template_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.template_path, "wb") as f:
            pickle.dump(existing, f)

    # ------------------------------------------------------------------
    # Feature extraction
    # ------------------------------------------------------------------

    def extract_digit_features(self, mask: np.ndarray) -> Optional[dict]:
        """Extract features from a digit mask for template matching."""
        if mask is None or mask.size == 0:
            return None

        resized = cv2.resize(mask, (DIGIT_NORM_WIDTH, DIGIT_NORM_HEIGHT), interpolation=cv2.INTER_AREA)
        h, w = resized.shape

        features = {
            "total": cv2.countNonZero(resized) / resized.size,
            "top": cv2.countNonZero(resized[0:10, :]) / (10 * w),
            "mid": cv2.countNonZero(resized[10:20, :]) / (10 * w),
            "bot": cv2.countNonZero(resized[20:30, :]) / (10 * w),
            "left": cv2.countNonZero(resized[:, 0:10]) / (h * 10),
            "right": cv2.countNonZero(resized[:, 10:20]) / (h * 10),
            "center": cv2.countNonZero(resized[10:20, 5:15]) / (10 * 10),
            "template": resized.copy(),
        }
        return features

    def match_digit_template(self, mask: Optional[np.ndarray], side: str) -> Optional[int]:
        """Match a digit mask against saved templates."""
        if mask is None or side not in self.digit_templates:
            return None

        features = self.extract_digit_features(mask)
        if features is None:
            return None

        best_digit = None
        best_score = 0.0

        for digit, template_list in self.digit_templates[side].items():
            for tmpl in template_list:
                if "template" in tmpl and tmpl["template"] is not None:
                    result = cv2.matchTemplate(
                        features["template"],
                        tmpl["template"],
                        cv2.TM_CCOEFF_NORMED,
                    )
                    score = result[0][0] if result.size > 0 else 0
                    if score > best_score and score > TEMPLATE_MATCH_THRESHOLD:
                        best_score = score
                        best_digit = digit

        return best_digit

    def learn_digit(
        self,
        frame: np.ndarray,
        roi: Tuple[int, int, int, int],
        side: str,
        digit: int,
    ) -> bool:
        """Learn a digit template from the current frame ROI."""
        mask = self.get_score_roi_mask(frame, roi)
        if mask is None:
            return False

        features = self.extract_digit_features(mask)
        if features is None:
            return False

        if side not in self.digit_templates:
            self.digit_templates[side] = {}
        if digit not in self.digit_templates[side]:
            self.digit_templates[side][digit] = []

        self.digit_templates[side][digit].append(features)
        self.save_templates()
        return True

    # ------------------------------------------------------------------
    # LED mask extraction
    # ------------------------------------------------------------------

    def get_score_roi_mask(self, frame: np.ndarray, roi: Optional[Tuple[int, int, int, int]]) -> Optional[np.ndarray]:
        """
        Extract LED mask from a score ROI.

        1. HSV color filtering (red LED)
        2. Gentle morphological closing (connect broken segments without merging digits)
        """
        if roi is None:
            return None

        x, y, w, h = roi
        roi_img = frame[y : y + h, x : x + w]
        if roi_img.size == 0:
            return None

        hsv = cv2.cvtColor(roi_img, cv2.COLOR_BGR2HSV)
        mask1 = cv2.inRange(hsv, SCORE_RED_LOWER_1, SCORE_RED_UPPER_1)
        mask2 = cv2.inRange(hsv, SCORE_RED_LOWER_2, SCORE_RED_UPPER_2)
        mask = cv2.bitwise_or(mask1, mask2)

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        return mask

    # ------------------------------------------------------------------
    # 7-segment digit reading
    # ------------------------------------------------------------------

    def read_7segment_digit(
        self,
        frame: np.ndarray,
        roi: Optional[Tuple[int, int, int, int]],
        align: str = "right",
    ) -> Optional[int]:
        """
        Read a 7-segment LED number from a frame ROI.

        Uses contour detection to find individual digits, then
        analyzes each via segment pattern matching.
        """
        if roi is None:
            return None

        x, y, w, h = roi
        roi_img = frame[y : y + h, x : x + w]
        if roi_img.size == 0:
            return None

        mask = self.get_score_roi_mask(frame, roi)
        if mask is None:
            return None

        total_pixels = cv2.countNonZero(mask)
        if total_pixels < 5:
            return None

        # Find digit regions by contour
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        h_roi, w_roi = mask.shape
        digit_regions: List[Tuple[int, int, int, int, int]] = []

        for cnt in contours:
            bx, by, bw, bh = cv2.boundingRect(cnt)
            area = cv2.contourArea(cnt)
            if area > 15 and bh > h_roi * 0.3:
                digit_regions.append((bx, by, bw, bh, area))

        if not digit_regions:
            coords = cv2.findNonZero(mask)
            if coords is None:
                return None
            bx, by, bw, bh = cv2.boundingRect(coords)
            digit_regions = [(bx, by, bw, bh, total_pixels)]

        digit_regions.sort(key=lambda r: r[0])

        digits: List[int] = []
        for bx, by, bw, bh, area in digit_regions:
            digit_mask = mask[by : by + bh, bx : bx + bw]
            aspect = bw / bh if bh > 0 else 1
            if aspect < DIGIT_ONE_ASPECT_THRESHOLD:
                digits.append(1)
                continue
            digit = self._analyze_digit_pattern(digit_mask)
            if digit is not None:
                digits.append(digit)

        if not digits:
            return None
        elif len(digits) == 1:
            return digits[0]
        elif len(digits) == 2:
            return digits[0] * 10 + digits[1]
        else:
            # 3+ regions: take the two largest by area
            digit_regions.sort(key=lambda r: r[4], reverse=True)
            top2 = digit_regions[:2]
            top2.sort(key=lambda r: r[0])
            result_digits: List[int] = []
            for bx, by, bw, bh, _ in top2:
                digit_mask = mask[by : by + bh, bx : bx + bw]
                aspect = bw / bh if bh > 0 else 1
                if aspect < DIGIT_ONE_ASPECT_THRESHOLD:
                    result_digits.append(1)
                else:
                    d = self._analyze_digit_pattern(digit_mask)
                    if d is not None:
                        result_digits.append(d)
            if len(result_digits) == 2:
                return result_digits[0] * 10 + result_digits[1]
            elif len(result_digits) == 1:
                return result_digits[0]
            return None

    def read_score_from_display(
        self,
        frame: np.ndarray,
        rois: Dict[str, Tuple[int, int, int, int]],
    ) -> Tuple[Optional[int], Optional[int]]:
        """Read left and right scores from the display."""
        left_score = self.read_7segment_digit(frame, rois.get("score_left"))
        right_score = self.read_7segment_digit(frame, rois.get("score_right"))
        return left_score, right_score

    # ------------------------------------------------------------------
    # Match clock reading
    # ------------------------------------------------------------------

    def read_match_time(
        self,
        frame: np.ndarray,
        rois: Dict[str, Tuple[int, int, int, int]],
    ) -> Optional[str]:
        """Read match time (M:SS) from the clock ROI."""
        clock_roi = rois.get("clock")
        if clock_roi is None:
            return None

        x, y, w, h = clock_roi
        roi_img = frame[y : y + h, x : x + w]
        if roi_img.size == 0:
            return None

        # Red LED extraction
        hsv = cv2.cvtColor(roi_img, cv2.COLOR_BGR2HSV)
        mask1 = cv2.inRange(hsv, CLOCK_RED_LOWER_1, CLOCK_RED_UPPER_1)
        mask2 = cv2.inRange(hsv, CLOCK_RED_LOWER_2, CLOCK_RED_UPPER_2)
        red_mask = cv2.bitwise_or(mask1, mask2)

        gray = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
        _, bright_mask = cv2.threshold(gray, CLOCK_BRIGHTNESS_THRESHOLD, 255, cv2.THRESH_BINARY)
        mask = cv2.bitwise_or(red_mask, bright_mask)

        kernel = np.ones((2, 2), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        h_roi, w_roi = mask.shape

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        bboxes = []
        for cnt in contours:
            bx, by, bw, bh = cv2.boundingRect(cnt)
            if bw > w_roi * 0.05 and bh > h_roi * 0.3:
                bboxes.append((bx, by, bw, bh))

        bboxes.sort(key=lambda b: b[0])

        digits: List[str] = []
        for bx, by, bw, bh in bboxes:
            aspect_ratio = bw / bh if bh > 0 else 0
            if aspect_ratio < COLON_ASPECT_THRESHOLD:
                digits.append(":")
                continue
            digit_mask = mask[by : by + bh, bx : bx + bw]
            digit = self._recognize_digit_from_mask(digit_mask)
            if digit is not None:
                digits.append(str(digit))

        if not digits:
            return None

        time_str = "".join(digits)
        if ":" in time_str:
            return time_str
        elif len(time_str) >= 3:
            return f"{time_str[:-2]}:{time_str[-2:]}"

        return time_str if time_str else None

    # ------------------------------------------------------------------
    # Internal segment analysis
    # ------------------------------------------------------------------

    def _analyze_digit_pattern(self, digit_mask: np.ndarray) -> Optional[int]:
        """Analyze segment pattern to recognize a digit. Special handling for 0 vs 8."""
        if digit_mask is None or digit_mask.size == 0:
            return None

        h_roi, w_roi = digit_mask.shape
        if h_roi < 3 or w_roi < 2:
            return None

        total_pixels = cv2.countNonZero(digit_mask)
        pixel_ratio = total_pixels / digit_mask.size
        if pixel_ratio < SEGMENT_MIN_PIXEL_RATIO:
            return None

        def get_ratio(y1, y2, x1, x2):
            y1i, y2i = int(h_roi * y1), int(h_roi * y2)
            x1i, x2i = int(w_roi * x1), int(w_roi * x2)
            if y2i <= y1i or x2i <= x1i:
                return 0
            region = digit_mask[y1i:y2i, x1i:x2i]
            if region.size == 0:
                return 0
            return cv2.countNonZero(region) / region.size

        # 0 vs 8: check center hole
        center = get_ratio(0.30, 0.70, 0.30, 0.70)
        outer_top = get_ratio(0.0, 0.25, 0.2, 0.8)
        outer_bottom = get_ratio(0.75, 1.0, 0.2, 0.8)
        outer_left = get_ratio(0.2, 0.8, 0.0, 0.3)
        outer_right = get_ratio(0.2, 0.8, 0.7, 1.0)
        outer_avg = (outer_top + outer_bottom + outer_left + outer_right) / 4

        if outer_avg > 0.25 and center < outer_avg * 0.5:
            return 0

        ratios = {
            "a": get_ratio(0.0, 0.20, 0.15, 0.85),
            "b": get_ratio(0.05, 0.50, 0.60, 1.0),
            "c": get_ratio(0.50, 0.95, 0.60, 1.0),
            "d": get_ratio(0.80, 1.0, 0.15, 0.85),
            "e": get_ratio(0.50, 0.95, 0.0, 0.40),
            "f": get_ratio(0.05, 0.50, 0.0, 0.40),
            "g": get_ratio(0.40, 0.60, 0.20, 0.80),
        }

        max_ratio = max(ratios.values())
        if max_ratio < 0.10:
            return None
        threshold = max(DYNAMIC_THRESHOLD_MIN, max_ratio * DYNAMIC_THRESHOLD_FRACTION)

        status = tuple(ratios[k] > threshold for k in ["a", "b", "c", "d", "e", "f", "g"])

        if self.show_segment_debug:
            print(
                f"  Seg: a={ratios['a']:.2f} b={ratios['b']:.2f} c={ratios['c']:.2f} "
                f"d={ratios['d']:.2f} e={ratios['e']:.2f} f={ratios['f']:.2f} g={ratios['g']:.2f}"
            )

        # Exact match
        if status in SEVEN_SEGMENT_PATTERNS:
            return SEVEN_SEGMENT_PATTERNS[status]

        # Fuzzy match (1-bit difference)
        best = None
        min_diff = 2
        for pattern, digit in SEVEN_SEGMENT_PATTERNS.items():
            diff = sum(1 for a, b in zip(status, pattern) if a != b)
            if diff < min_diff:
                min_diff = diff
                best = digit

        return best

    def _recognize_digit_from_mask(self, mask: np.ndarray) -> Optional[int]:
        """Recognize a digit from a binary mask (used for clock digits)."""
        if mask.size == 0:
            return None

        h_roi, w_roi = mask.shape

        segments = {
            "a": (int(w_roi * 0.15), int(h_roi * 0.0), int(w_roi * 0.7), int(h_roi * 0.15)),
            "b": (int(w_roi * 0.65), int(h_roi * 0.05), int(w_roi * 0.3), int(h_roi * 0.4)),
            "c": (int(w_roi * 0.65), int(h_roi * 0.55), int(w_roi * 0.3), int(h_roi * 0.4)),
            "d": (int(w_roi * 0.15), int(h_roi * 0.85), int(w_roi * 0.7), int(h_roi * 0.15)),
            "e": (int(w_roi * 0.0), int(h_roi * 0.55), int(w_roi * 0.3), int(h_roi * 0.4)),
            "f": (int(w_roi * 0.0), int(h_roi * 0.05), int(w_roi * 0.3), int(h_roi * 0.4)),
            "g": (int(w_roi * 0.15), int(h_roi * 0.42), int(w_roi * 0.7), int(h_roi * 0.16)),
        }

        seg_status = {}
        threshold_ratio = 0.15

        for seg_name, (sx, sy, sw, sh) in segments.items():
            if sw <= 0 or sh <= 0:
                seg_status[seg_name] = False
                continue
            if sy + sh <= h_roi and sx + sw <= w_roi:
                seg_roi = mask[sy : sy + sh, sx : sx + sw]
            else:
                seg_status[seg_name] = False
                continue
            if seg_roi.size == 0:
                seg_status[seg_name] = False
                continue
            ratio = cv2.countNonZero(seg_roi) / seg_roi.size
            seg_status[seg_name] = ratio > threshold_ratio

        current_pattern = (
            seg_status.get("a", False),
            seg_status.get("b", False),
            seg_status.get("c", False),
            seg_status.get("d", False),
            seg_status.get("e", False),
            seg_status.get("f", False),
            seg_status.get("g", False),
        )

        if current_pattern in SEVEN_SEGMENT_PATTERNS:
            return SEVEN_SEGMENT_PATTERNS[current_pattern]

        # Fuzzy match
        best_match = None
        min_diff = 3
        for pattern, digit in SEVEN_SEGMENT_PATTERNS.items():
            diff = sum(1 for a, b in zip(current_pattern, pattern) if a != b)
            if diff < min_diff:
                min_diff = diff
                best_match = digit

        return best_match

    # ------------------------------------------------------------------
    # Score pixel utilities
    # ------------------------------------------------------------------

    def get_score_pixel_count(
        self,
        frame: np.ndarray,
        roi: Optional[Tuple[int, int, int, int]],
    ) -> int:
        """Return LED pixel count for a score ROI."""
        mask = self.get_score_roi_mask(frame, roi)
        if mask is None:
            return 0
        return cv2.countNonZero(mask)

    def get_mask_features(
        self,
        frame: np.ndarray,
        roi: Optional[Tuple[int, int, int, int]],
    ) -> Optional[dict]:
        """Extract mask features for change detection."""
        if roi is None:
            return None

        mask = self.get_score_roi_mask(frame, roi)
        if mask is None:
            return None

        pixel_count = cv2.countNonZero(mask)
        if pixel_count < 5:
            return None

        coords = cv2.findNonZero(mask)
        if coords is None:
            return None

        bx, by, bw, bh = cv2.boundingRect(coords)
        aspect = bw / bh if bh > 0 else 1
        density = pixel_count / (bw * bh) if (bw * bh) > 0 else 0

        return {
            "pixels": pixel_count,
            "width": bw,
            "height": bh,
            "aspect": aspect,
            "density": density,
            "is_narrow": aspect < 0.5,
        }
