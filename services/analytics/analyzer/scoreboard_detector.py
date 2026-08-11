"""
Automatic scoreboard/ROI detection for fencing match videos.

Detects the physical LED scoreboard position in a video frame using
color-based segmentation (red/green LEDs, high-brightness regions).

Algorithm:
1. Sample 5-10 frames from early in the video (~30s mark)
2. HSV → red + green + high-brightness mask
3. Morphological closing to merge adjacent bright regions
4. Find largest horizontal bounding box (width > 2*height)
5. Sub-divide into lamp_left, lamp_right, score_left, score_right, clock
6. Validate with LampDetector / ScoreReader
7. Return ROIs dict or None if detection fails
"""

import cv2
import numpy as np
from typing import Optional, Dict, Tuple, List
from pathlib import Path

from analyzer.config import (
    RED_LOWER_1, RED_UPPER_1, RED_LOWER_2, RED_UPPER_2,
    GREEN_LOWER, GREEN_UPPER,
    SCOREBOARD_MIN_WIDTH_RATIO,
    SCOREBOARD_MAX_WIDTH_RATIO,
    SCOREBOARD_MIN_ASPECT,
    SCOREBOARD_DETECTION_CONFIDENCE_MIN,
    SCOREBOARD_LAMP_PAD_RATIO,
)


class ScoreboardDetector:
    """
    Detects the physical LED scoreboard region in fencing match videos.

    Uses color-based segmentation to find bright red/green LED regions
    that form a horizontal strip (the scoreboard).
    """

    def __init__(
        self,
        sample_count: int = 8,
        sample_start_sec: float = 30.0,
        morph_kernel_size: int = 5,
    ):
        self.sample_count = sample_count
        self.sample_start_sec = sample_start_sec
        self.morph_kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT, (morph_kernel_size, morph_kernel_size)
        )

    def detect_from_video(
        self,
        video_path: str,
    ) -> Optional[Dict[str, Tuple[int, int, int, int]]]:
        """
        Detect scoreboard ROIs from a video file.

        Args:
            video_path: Path to the video file.

        Returns:
            Dict with ROI keys (lamp_left, lamp_right, score_left, score_right, clock)
            as (x, y, w, h) tuples, or None if detection fails.
        """
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return None

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        if total_frames < 10:
            cap.release()
            return None

        # Sample frames from around the start point
        start_frame = int(self.sample_start_sec * fps)
        # Clamp: if video is shorter than 30s, sample from the first half
        if start_frame >= total_frames:
            start_frame = max(0, total_frames // 4)

        sample_interval = max(1, int(fps * 2))  # every ~2 seconds
        frames = self._sample_frames(cap, start_frame, sample_interval)
        cap.release()

        if not frames:
            return None

        # Try to detect scoreboard from sampled frames
        return self._detect_from_frames(frames)

    def detect_from_frame(
        self,
        frame: np.ndarray,
    ) -> Optional[Dict[str, Tuple[int, int, int, int]]]:
        """
        Detect scoreboard ROIs from a single frame.

        Args:
            frame: BGR video frame.

        Returns:
            ROI dict or None.
        """
        return self._detect_from_frames([frame])

    def _sample_frames(
        self,
        cap: cv2.VideoCapture,
        start_frame: int,
        interval: int,
    ) -> List[np.ndarray]:
        """Sample frames from video capture."""
        frames = []
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        for i in range(self.sample_count):
            target = start_frame + i * interval
            if target >= total:
                break
            cap.set(cv2.CAP_PROP_POS_FRAMES, target)
            ret, frame = cap.read()
            if ret:
                frames.append(frame)

        return frames

    def _detect_from_frames(
        self,
        frames: List[np.ndarray],
    ) -> Optional[Dict[str, Tuple[int, int, int, int]]]:
        """
        Detect scoreboard from multiple frames using consensus.

        Tries each frame and returns the first successful detection.
        Multiple-frame consensus improves reliability.
        """
        # Accumulate masks from all frames
        if not frames:
            return None

        h, w = frames[0].shape[:2]
        accumulated_mask = np.zeros((h, w), dtype=np.float32)

        for frame in frames:
            mask = self._create_bright_mask(frame)
            accumulated_mask += mask.astype(np.float32) / 255.0

        # Threshold: pixels that appear bright in at least 50% of frames
        threshold = len(frames) * 0.5
        consensus_mask = (accumulated_mask >= threshold).astype(np.uint8) * 255

        # Find scoreboard bounding box
        bbox = self._find_scoreboard_bbox(consensus_mask, w, h)
        if bbox is None:
            # Fallback: try individual frames
            for frame in frames:
                mask = self._create_bright_mask(frame)
                bbox = self._find_scoreboard_bbox(mask, w, h)
                if bbox is not None:
                    break

        if bbox is None:
            return None

        # Sub-divide into ROI regions
        rois = self._subdivide_scoreboard(bbox, w, h)

        # Validate detection confidence
        confidence = self._validate_rois(frames[0], rois)
        if confidence < SCOREBOARD_DETECTION_CONFIDENCE_MIN:
            return None

        return rois

    def _create_bright_mask(self, frame: np.ndarray) -> np.ndarray:
        """Create mask of bright red/green/white regions (scoreboard indicators)."""
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        # Red mask (two ranges for hue wrap-around)
        red_mask1 = cv2.inRange(hsv, RED_LOWER_1, RED_UPPER_1)
        red_mask2 = cv2.inRange(hsv, RED_LOWER_2, RED_UPPER_2)
        red_mask = cv2.bitwise_or(red_mask1, red_mask2)

        # Green mask
        green_mask = cv2.inRange(hsv, GREEN_LOWER, GREEN_UPPER)

        # High-brightness mask (V > 200)
        bright_mask = cv2.inRange(
            hsv,
            np.array([0, 0, 200]),
            np.array([180, 255, 255]),
        )

        # Combine all
        combined = cv2.bitwise_or(red_mask, green_mask)
        combined = cv2.bitwise_or(combined, bright_mask)

        # Morphological closing to merge adjacent regions
        combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, self.morph_kernel)

        return combined

    def _find_scoreboard_bbox(
        self,
        mask: np.ndarray,
        frame_w: int,
        frame_h: int,
    ) -> Optional[Tuple[int, int, int, int]]:
        """
        Find the scoreboard bounding box from a binary mask.

        Looks for the largest horizontal region (aspect ratio > 2:1)
        within expected size range.
        """
        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        if not contours:
            return None

        min_w = int(frame_w * SCOREBOARD_MIN_WIDTH_RATIO)
        max_w = int(frame_w * SCOREBOARD_MAX_WIDTH_RATIO)

        candidates = []
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)

            # Must be horizontally oriented
            if h == 0 or w / h < SCOREBOARD_MIN_ASPECT:
                continue

            # Must be within expected width range
            if w < min_w or w > max_w:
                continue

            # Prefer regions in upper or lower portion of frame
            # (scoreboards are typically at top or bottom)
            center_y = y + h // 2
            y_ratio = center_y / frame_h
            edge_bonus = 1.0 if (y_ratio < 0.3 or y_ratio > 0.7) else 0.5

            area = w * h * edge_bonus
            candidates.append((area, (x, y, w, h)))

        if not candidates:
            return None

        # Return the candidate with largest weighted area
        candidates.sort(key=lambda c: c[0], reverse=True)
        return candidates[0][1]

    def _subdivide_scoreboard(
        self,
        bbox: Tuple[int, int, int, int],
        frame_w: int,
        frame_h: int,
    ) -> Dict[str, Tuple[int, int, int, int]]:
        """
        Subdivide the scoreboard bounding box into sub-ROIs.

        Layout (left to right):
            [lamp_left] [score_left] [clock] [score_right] [lamp_right]

        Each region is a fraction of the total scoreboard width.
        """
        x, y, w, h = bbox
        pad = int(w * SCOREBOARD_LAMP_PAD_RATIO)

        # Lamp regions: leftmost and rightmost portions
        lamp_w = max(int(w * 0.12), 20)
        lamp_h = h

        # Score regions: between lamp and center
        score_w = max(int(w * 0.18), 30)

        # Clock: center region
        clock_w = max(int(w * 0.20), 40)

        # Calculate positions
        lamp_left_x = x
        score_left_x = x + lamp_w + int(w * 0.02)
        clock_x = x + w // 2 - clock_w // 2
        score_right_x = x + w - lamp_w - score_w - int(w * 0.02)
        lamp_right_x = x + w - lamp_w

        return {
            "lamp_left": (lamp_left_x, y, lamp_w, lamp_h),
            "score_left": (score_left_x, y, score_w, h),
            "clock": (clock_x, y, clock_w, h),
            "score_right": (score_right_x, y, score_w, h),
            "lamp_right": (lamp_right_x, y, lamp_w, lamp_h),
        }

    def _validate_rois(
        self,
        frame: np.ndarray,
        rois: Dict[str, Tuple[int, int, int, int]],
    ) -> float:
        """
        Validate detected ROIs using lamp detection and score reading.

        Returns confidence score 0.0 - 1.0.
        """
        confidence = 0.0

        # Check that lamp ROIs contain some bright colored pixels
        for lamp_key in ("lamp_left", "lamp_right"):
            roi = rois.get(lamp_key)
            if roi is None:
                continue
            x, y, w, h = roi
            if x < 0 or y < 0 or x + w > frame.shape[1] or y + h > frame.shape[0]:
                continue

            roi_img = frame[y:y+h, x:x+w]
            if roi_img.size == 0:
                continue

            # Check for bright pixels in lamp region
            hsv = cv2.cvtColor(roi_img, cv2.COLOR_BGR2HSV)
            bright = cv2.inRange(hsv, np.array([0, 0, 150]), np.array([180, 255, 255]))
            ratio = cv2.countNonZero(bright) / (w * h) if w * h > 0 else 0
            if ratio > 0.05:
                confidence += 0.25

        # Check that score regions have some content
        for score_key in ("score_left", "score_right"):
            roi = rois.get(score_key)
            if roi is None:
                continue
            x, y, w, h = roi
            if x < 0 or y < 0 or x + w > frame.shape[1] or y + h > frame.shape[0]:
                continue

            roi_img = frame[y:y+h, x:x+w]
            if roi_img.size == 0:
                continue

            gray = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
            # Score region should have some contrast (digits)
            std = np.std(gray)
            if std > 20:
                confidence += 0.25

        return min(confidence, 1.0)
