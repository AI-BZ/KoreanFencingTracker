"""
Video source type detector using heuristic analysis.

Classifies fencing videos into source types (coach, parent, player,
TV broadcast) based on scene stability, cut frequency, person count,
and scoreboard presence. No ML model needed — pure heuristics.
"""

import cv2
import numpy as np
from typing import List, Optional, Tuple

from analyzer.video_source import VideoSourceType, VideoSourceAssessment


# Detection thresholds
_SCENE_CUT_THRESHOLD = 30.0       # Frame diff threshold for scene cut
_STABILITY_SAMPLE_FRAMES = 10     # Frames to sample for stability
_PERSON_SAMPLE_FRAMES = 5         # Frames to sample for person detection
_TV_CUTS_PER_MINUTE = 6.0         # >6 cuts/min → likely TV broadcast
_COACH_MIN_STABILITY = 0.8        # High stability → tripod → coach
_COACH_MIN_FENCER_RATE = 0.5      # >50% frames with 2 fencers
_PLAYER_MAX_PERSONS = 1.2         # Avg ≤1.2 persons → likely player
_FENCER_HEIGHT_COACH = (0.3, 0.7) # Coach: fencer 30-70% of frame
_FENCER_HEIGHT_TV = (0.05, 0.25)  # TV: fencer 5-25% of frame


class VideoSourceDetector:
    """
    Heuristic-based video source type detector.

    Analyzes video metadata and sampled frames to classify
    the recording source type without ML models.
    """

    def __init__(self, pose_estimator=None):
        """
        Args:
            pose_estimator: Optional PoseEstimator instance for person detection.
                          If None, falls back to frame-based heuristics.
        """
        self._pose_estimator = pose_estimator

    def detect(self, video_path: str) -> VideoSourceAssessment:
        """
        Detect video source type from a video file.

        Args:
            video_path: Path to the video file.

        Returns:
            VideoSourceAssessment with classification and metrics.
        """
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return self._unknown_assessment()

        # 1. Basic metadata
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration_sec = total_frames / fps if fps > 0 else 0.0

        if total_frames < 2 or duration_sec < 1.0:
            cap.release()
            return self._unknown_assessment(
                resolution=(width, height), fps=fps, duration_sec=duration_sec,
            )

        # 2. Scene stability (optical flow variance)
        stability = self._analyze_stability(cap, total_frames)

        # 3. Scene cut detection
        cuts = self._detect_scene_cuts(cap, total_frames)
        duration_min = duration_sec / 60.0 if duration_sec > 0 else 1.0
        cuts_per_min = len(cuts) / duration_min if duration_min > 0 else 0.0

        # 4. Person detection (using YOLO if available)
        avg_person_count, avg_fencer_height = self._analyze_persons(
            cap, total_frames, height,
        )

        # 5. Scoreboard detection
        scoreboard_detected = self._detect_scoreboard(cap, total_frames)
        overlay_detected = self._detect_overlay(cap, total_frames)

        cap.release()

        # 6. Heuristic classification
        source_type, confidence = self._classify(
            cuts_per_min=cuts_per_min,
            stability=stability,
            avg_person_count=avg_person_count,
            avg_fencer_height=avg_fencer_height,
            scoreboard_detected=scoreboard_detected,
            overlay_detected=overlay_detected,
            height=height,
        )

        return VideoSourceAssessment(
            source_type=source_type,
            confidence=confidence,
            scene_cuts_per_minute=cuts_per_min,
            avg_fencer_height_ratio=avg_fencer_height,
            scoreboard_detected=scoreboard_detected,
            overlay_detected=overlay_detected,
            avg_person_count=avg_person_count,
            stability_score=stability,
            resolution=(width, height),
            fps=fps,
            duration_sec=duration_sec,
        )

    def _analyze_stability(
        self, cap: cv2.VideoCapture, total_frames: int,
    ) -> float:
        """Compute stability score from optical flow variance (0=shaky, 1=stable)."""
        sample_indices = np.linspace(
            0, total_frames - 2, min(_STABILITY_SAMPLE_FRAMES, total_frames - 1),
            dtype=int,
        )

        flow_magnitudes: List[float] = []
        for idx in sample_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret1, frame1 = cap.read()
            ret2, frame2 = cap.read()
            if not ret1 or not ret2:
                continue

            gray1 = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)
            gray2 = cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY)

            # Use simple frame difference as proxy for motion
            diff = cv2.absdiff(gray1, gray2)
            flow_magnitudes.append(float(np.mean(diff)))

        if not flow_magnitudes:
            return 0.5

        avg_motion = np.mean(flow_magnitudes)
        # Map: low motion → high stability (typical range 0-30)
        stability = max(0.0, min(1.0, 1.0 - (avg_motion / 30.0)))
        return float(stability)

    def _detect_scene_cuts(
        self, cap: cv2.VideoCapture, total_frames: int,
    ) -> List[int]:
        """Detect scene cuts by frame-to-frame histogram difference."""
        cuts: List[int] = []
        sample_step = max(1, total_frames // 300)  # Sample ~300 pairs

        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        ret, prev_frame = cap.read()
        if not ret:
            return cuts

        prev_hist = self._frame_histogram(prev_frame)
        frame_idx = 1

        while frame_idx < total_frames:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret:
                break

            curr_hist = self._frame_histogram(frame)
            diff = cv2.compareHist(prev_hist, curr_hist, cv2.HISTCMP_BHATTACHARYYA)

            if diff > 0.5:  # High Bhattacharyya distance → scene cut
                cuts.append(frame_idx)

            prev_hist = curr_hist
            frame_idx += sample_step

        return cuts

    @staticmethod
    def _frame_histogram(frame: np.ndarray) -> np.ndarray:
        """Compute normalized color histogram for a frame."""
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [30, 32], [0, 180, 0, 256])
        cv2.normalize(hist, hist)
        return hist

    def _analyze_persons(
        self, cap: cv2.VideoCapture, total_frames: int, frame_height: int,
    ) -> Tuple[float, float]:
        """Detect average person count and fencer height ratio."""
        sample_indices = np.linspace(
            0, total_frames - 1, min(_PERSON_SAMPLE_FRAMES, total_frames),
            dtype=int,
        )

        person_counts: List[int] = []
        height_ratios: List[float] = []

        if self._pose_estimator is not None:
            for idx in sample_indices:
                cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                ret, frame = cap.read()
                if not ret:
                    continue

                result = self._pose_estimator.estimate_pose(frame, int(idx))
                person_counts.append(len(result.fencers))

                for fencer in result.fencers:
                    bbox_height = fencer.bbox[3] - fencer.bbox[1]
                    if frame_height > 0:
                        height_ratios.append(bbox_height / frame_height)
        else:
            # Fallback: no person detection available
            return 2.0, 0.4  # Assume coach-like defaults

        avg_count = float(np.mean(person_counts)) if person_counts else 0.0
        avg_height = float(np.mean(height_ratios)) if height_ratios else 0.0

        return avg_count, avg_height

    def _detect_scoreboard(
        self, cap: cv2.VideoCapture, total_frames: int,
    ) -> bool:
        """Detect physical LED scoreboard presence (bright red/green regions)."""
        # Sample a frame from early part of video
        sample_idx = min(30, total_frames - 1)
        cap.set(cv2.CAP_PROP_POS_FRAMES, sample_idx)
        ret, frame = cap.read()
        if not ret:
            return False

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        h, w = frame.shape[:2]

        # Look for bright red/green LED regions in top portion
        top_region = hsv[:h // 3, :, :]

        # Red LED
        red_mask1 = cv2.inRange(top_region, np.array([0, 100, 150]), np.array([10, 255, 255]))
        red_mask2 = cv2.inRange(top_region, np.array([170, 100, 150]), np.array([180, 255, 255]))
        red_pixels = int(np.sum(red_mask1 > 0) + np.sum(red_mask2 > 0))

        # Green LED
        green_mask = cv2.inRange(top_region, np.array([35, 100, 150]), np.array([85, 255, 255]))
        green_pixels = int(np.sum(green_mask > 0))

        # Scoreboard present if sufficient LED pixels in top region
        min_pixels = (h * w) // 1000  # 0.1% of frame
        return red_pixels > min_pixels or green_pixels > min_pixels

    def _detect_overlay(
        self, cap: cv2.VideoCapture, total_frames: int,
    ) -> bool:
        """Detect TV-style scoreboard overlay (sharp-edged graphics on top of video)."""
        sample_idx = min(30, total_frames - 1)
        cap.set(cv2.CAP_PROP_POS_FRAMES, sample_idx)
        ret, frame = cap.read()
        if not ret:
            return False

        h, w = frame.shape[:2]
        # Overlays typically in bottom or top bar with uniform regions
        # Check for high-contrast horizontal bands
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Check bottom 15% for overlay bar
        bottom_strip = gray[int(h * 0.85):, :]
        if bottom_strip.size == 0:
            return False

        # Overlays have low variance rows (solid color bars)
        row_vars = np.var(bottom_strip.astype(float), axis=1)
        low_var_ratio = float(np.mean(row_vars < 100))

        # Check top 10% as well
        top_strip = gray[:int(h * 0.10), :]
        if top_strip.size > 0:
            top_row_vars = np.var(top_strip.astype(float), axis=1)
            top_low_var = float(np.mean(top_row_vars < 100))
            low_var_ratio = max(low_var_ratio, top_low_var)

        return low_var_ratio > 0.5

    def _classify(
        self,
        cuts_per_min: float,
        stability: float,
        avg_person_count: float,
        avg_fencer_height: float,
        scoreboard_detected: bool,
        overlay_detected: bool,
        height: int,
    ) -> Tuple[VideoSourceType, float]:
        """Cascade heuristic classification."""
        # Rule 1: TV broadcast (many scene cuts + overlay)
        if cuts_per_min > _TV_CUTS_PER_MINUTE and overlay_detected:
            return VideoSourceType.TV_BROADCAST, 0.85

        if cuts_per_min > _TV_CUTS_PER_MINUTE * 2:
            return VideoSourceType.TV_BROADCAST, 0.75

        # Rule 2: Coach (stable + scoreboard + 2 fencers)
        if (
            stability >= _COACH_MIN_STABILITY
            and scoreboard_detected
            and avg_person_count >= 1.5
        ):
            return VideoSourceType.COACH, 0.85

        # Rule 3: Coach (stable + good fencer height ratio)
        if (
            stability >= _COACH_MIN_STABILITY
            and _FENCER_HEIGHT_COACH[0] <= avg_fencer_height <= _FENCER_HEIGHT_COACH[1]
            and avg_person_count >= 1.5
        ):
            return VideoSourceType.COACH, 0.70

        # Rule 4: Parent (scoreboard visible but less stable)
        if scoreboard_detected and stability < _COACH_MIN_STABILITY:
            return VideoSourceType.PARENT, 0.70

        # Rule 5: Player (mostly 1 person, no scoreboard)
        if avg_person_count <= _PLAYER_MAX_PERSONS and not scoreboard_detected:
            return VideoSourceType.PLAYER, 0.70

        # Rule 6: Parent fallback (multiple people, no scoreboard, unstable)
        if avg_person_count > _PLAYER_MAX_PERSONS and not scoreboard_detected:
            return VideoSourceType.PARENT, 0.50

        return VideoSourceType.UNKNOWN, 0.30

    @staticmethod
    def _unknown_assessment(
        resolution: Tuple[int, int] = (0, 0),
        fps: float = 0.0,
        duration_sec: float = 0.0,
    ) -> VideoSourceAssessment:
        """Return a default unknown assessment."""
        return VideoSourceAssessment(
            source_type=VideoSourceType.UNKNOWN,
            confidence=0.0,
            scene_cuts_per_minute=0.0,
            avg_fencer_height_ratio=0.0,
            scoreboard_detected=False,
            overlay_detected=False,
            avg_person_count=0.0,
            stability_score=0.0,
            resolution=resolution,
            fps=fps,
            duration_sec=duration_sec,
        )
