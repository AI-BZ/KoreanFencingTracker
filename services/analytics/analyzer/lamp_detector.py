"""
LED lamp detection for fencing scoring machines.

Extracted from fencing_analyzer_v3.py — detects red/green lamp
activation using brightness and HSV color analysis.
"""

import cv2
import numpy as np
from typing import Tuple, Optional, Dict

from analyzer.config import (
    LAMP_PIXEL_THRESHOLD,
    LAMP_RED_SAT_LOW,
    LAMP_RED_SAT_HIGH_1,
    LAMP_RED_SAT_LOW_2,
    LAMP_RED_SAT_HIGH_2,
    LAMP_BRIGHT_LOW,
    LAMP_BRIGHT_HIGH,
    LAMP_GREEN_LOW,
    LAMP_GREEN_HIGH,
    BRIGHTNESS_THRESHOLD,
)
from analyzer.models import LampState


class LampDetector:
    """Detects LED lamp activation on fencing scoring machines."""

    def __init__(self, pixel_threshold: int = LAMP_PIXEL_THRESHOLD):
        self.pixel_threshold = pixel_threshold

    def detect_lamp(
        self,
        frame: np.ndarray,
        roi: Optional[Tuple[int, int, int, int]],
        color: str = "red",
    ) -> Tuple[bool, int]:
        """
        Detect whether a lamp is ON in the given ROI.

        Uses two methods:
        1. Brightness-based (LED turns very bright when on)
        2. Color-based (supplementary HSV check)

        Args:
            frame: BGR video frame.
            roi: (x, y, w, h) region of interest.
            color: 'red' or 'green'.

        Returns:
            (is_on, pixel_count) tuple.
        """
        if roi is None:
            return False, 0

        x, y, w, h = roi
        roi_img = frame[y : y + h, x : x + w]

        if roi_img.size == 0:
            return False, 0

        # Method 1: Brightness-based
        gray = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
        bright_mask = cv2.inRange(gray, BRIGHTNESS_THRESHOLD, 255)
        bright_pixels = cv2.countNonZero(bright_mask)

        # Method 2: Color-based (supplementary)
        hsv = cv2.cvtColor(roi_img, cv2.COLOR_BGR2HSV)

        if color == "red":
            mask1 = cv2.inRange(hsv, LAMP_RED_SAT_LOW, LAMP_RED_SAT_HIGH_1)
            mask2 = cv2.inRange(hsv, LAMP_RED_SAT_LOW_2, LAMP_RED_SAT_HIGH_2)
            # Bright white/pink (low saturation, high value)
            mask3 = cv2.inRange(hsv, LAMP_BRIGHT_LOW, LAMP_BRIGHT_HIGH)
            color_mask = cv2.bitwise_or(mask1, mask2)
            color_mask = cv2.bitwise_or(color_mask, mask3)
        else:  # green
            mask1 = cv2.inRange(hsv, LAMP_GREEN_LOW, LAMP_GREEN_HIGH)
            mask2 = cv2.inRange(hsv, LAMP_BRIGHT_LOW, LAMP_BRIGHT_HIGH)
            color_mask = cv2.bitwise_or(mask1, mask2)

        color_pixels = cv2.countNonZero(color_mask)

        # ON if either brightness or color exceeds threshold
        total_pixels = max(bright_pixels, color_pixels)
        is_on = total_pixels > self.pixel_threshold

        return is_on, total_pixels

    def detect_both(
        self,
        frame: np.ndarray,
        rois: Dict[str, Tuple[int, int, int, int]],
    ) -> LampState:
        """
        Detect both left (red) and right (green) lamps.

        Args:
            frame: BGR video frame.
            rois: dict with 'lamp_left' and 'lamp_right' keys.

        Returns:
            LampState with detection results.
        """
        red_on, red_px = self.detect_lamp(
            frame, rois.get("lamp_left"), "red"
        )
        green_on, green_px = self.detect_lamp(
            frame, rois.get("lamp_right"), "green"
        )
        return LampState(
            red=red_on,
            green=green_on,
            red_pixels=red_px,
            green_pixels=green_px,
        )
