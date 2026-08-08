"""
TV broadcast analyzer for educational technique extraction.

Processes FIE/international competition broadcast footage:
1. Detects scene cuts (camera transitions)
2. Filters for actual bout segments (2-fencer action)
3. Extracts individual techniques per segment
4. Groups by action type for educational use

Unlike IntegratedAnalyzer (which scores matches), this module
focuses on extracting technique examples for coaching education.
"""

from collections import defaultdict
from pathlib import Path
from typing import List, Tuple, Optional

import cv2
import numpy as np

from analyzer.tv_models import (
    TechniqueClip,
    TechniqueCollection,
    TVAnalysisResult,
)


# Scene cut detection threshold (mean absolute frame difference)
_SCENE_CUT_THRESHOLD = 30.0
# Minimum bout segment duration in frames (at 30fps ≈ 1 second)
_MIN_BOUT_FRAMES = 30
# Maximum frames to sample for person detection per segment
_PERSON_SAMPLE_COUNT = 5


class TVBroadcastAnalyzer:
    """
    Analyzes TV broadcast fencing footage for technique extraction.

    Usage:
        analyzer = TVBroadcastAnalyzer()
        result = analyzer.analyze_broadcast("match.mp4")
    """

    def __init__(
        self,
        enable_pose: bool = True,
        enable_action: bool = True,
        scene_cut_threshold: float = _SCENE_CUT_THRESHOLD,
        min_bout_frames: int = _MIN_BOUT_FRAMES,
    ):
        self._enable_pose = enable_pose
        self._enable_action = enable_action
        self._scene_cut_threshold = scene_cut_threshold
        self._min_bout_frames = min_bout_frames
        self._pose_estimator = None
        self._action_classifier = None

    def analyze_broadcast(self, video_path: str) -> TVAnalysisResult:
        """
        Run full broadcast analysis pipeline.

        1. detect_scene_cuts → frame indices
        2. filter_bout_segments → (start, end) pairs
        3. extract_techniques → TechniqueClip list
        4. group_by_action → TechniqueCollection list

        Args:
            video_path: Path to broadcast video file.

        Returns:
            TVAnalysisResult with extracted techniques.
        """
        path = Path(video_path)
        if not path.exists():
            return TVAnalysisResult(video_path=video_path)

        # Step 1: Detect scene cuts
        scene_cuts = self.detect_scene_cuts(video_path)

        # Step 2: Filter for bout segments
        bout_segments = self.filter_bout_segments(video_path, scene_cuts)

        # Step 3: Extract techniques from each segment
        all_clips: List[TechniqueClip] = []
        for start, end in bout_segments:
            clips = self._extract_techniques_from_segment(
                video_path, start, end,
            )
            all_clips.extend(clips)

        # Step 4: Group by action
        techniques = self._group_by_action(all_clips)

        # Build distribution
        action_dist: dict = {}
        for tc in techniques:
            action_dist[tc.action] = tc.count

        return TVAnalysisResult(
            video_path=video_path,
            total_bout_segments=len(bout_segments),
            total_techniques_extracted=len(all_clips),
            techniques=techniques,
            action_distribution=action_dist,
            scene_cuts=scene_cuts,
            bout_segments=bout_segments,
        )

    def detect_scene_cuts(
        self,
        video_path: str,
        threshold: Optional[float] = None,
    ) -> List[int]:
        """
        Detect scene transitions via frame difference.

        Args:
            video_path: Path to video file.
            threshold: Mean absolute difference threshold.
                       Defaults to instance threshold.

        Returns:
            List of frame indices where scene cuts occur.
        """
        if threshold is None:
            threshold = self._scene_cut_threshold

        cuts: List[int] = []
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return cuts

        ret, prev_frame = cap.read()
        if not ret:
            cap.release()
            return cuts

        prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
        frame_idx = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frame_idx += 1

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            diff = np.mean(np.abs(
                gray.astype(np.float32) - prev_gray.astype(np.float32),
            ))

            if diff > threshold:
                cuts.append(frame_idx)

            prev_gray = gray

        cap.release()
        return cuts

    def filter_bout_segments(
        self,
        video_path: str,
        scene_cuts: List[int],
    ) -> List[Tuple[int, int]]:
        """
        Filter scene segments to find actual bout action.

        A segment is considered a bout segment if:
        - It is long enough (>= min_bout_frames)
        - At least 2 persons are detected in sampled frames

        Args:
            video_path: Path to video file.
            scene_cuts: Scene cut frame indices.

        Returns:
            List of (start_frame, end_frame) tuples.
        """
        if not scene_cuts:
            return []

        # Build segment boundaries
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return []

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()

        boundaries = [0] + scene_cuts + [total_frames]
        segments: List[Tuple[int, int]] = []

        for i in range(len(boundaries) - 1):
            start = boundaries[i]
            end = boundaries[i + 1]
            duration = end - start

            if duration < self._min_bout_frames:
                continue

            # Check for 2-person presence
            if self._has_two_fencers(video_path, start, end):
                segments.append((start, end))

        return segments

    def _has_two_fencers(
        self,
        video_path: str,
        start_frame: int,
        end_frame: int,
    ) -> bool:
        """Check if segment has 2 fencers using pose estimator."""
        if not self._enable_pose:
            # Without pose, assume all long segments are bouts
            return True

        try:
            if self._pose_estimator is None:
                from ml.pose_estimator import PoseEstimator
                self._pose_estimator = PoseEstimator()
        except ImportError:
            return True

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return False

        duration = end_frame - start_frame
        sample_indices = np.linspace(
            start_frame, end_frame - 1,
            min(_PERSON_SAMPLE_COUNT, duration),
            dtype=int,
        )

        detections_with_two = 0
        for idx in sample_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if not ret:
                continue

            result = self._pose_estimator.estimate(frame)
            if result and len(result.fencers) >= 2:
                detections_with_two += 1

        cap.release()

        # At least half of sampled frames should have 2 fencers
        return detections_with_two >= len(sample_indices) / 2

    def _extract_techniques_from_segment(
        self,
        video_path: str,
        start_frame: int,
        end_frame: int,
    ) -> List[TechniqueClip]:
        """Extract individual technique clips from a bout segment."""
        if not self._enable_action:
            return []

        try:
            if self._action_classifier is None:
                from ml.action_classifier import ActionClassifier
                self._action_classifier = ActionClassifier()
        except ImportError:
            return []

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return []

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        clips: List[TechniqueClip] = []

        # Read frames for the segment
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        frames: list = []
        for _ in range(end_frame - start_frame):
            ret, frame = cap.read()
            if not ret:
                break
            frames.append(frame[:, :, ::-1].copy())  # BGR → RGB

        cap.release()

        if not frames:
            return []

        # Classify the segment as a whole
        result = self._action_classifier.classify_window(frames)
        if result is None:
            return []

        # Extract per-fencer predictions
        for side, pred in [("left", result.left_fencer), ("right", result.right_fencer)]:
            if pred is None:
                continue
            if pred.action.value == "unknown":
                continue

            duration_sec = len(frames) / fps
            clips.append(TechniqueClip(
                start_frame=start_frame,
                end_frame=end_frame,
                duration_sec=duration_sec,
                action=pred.action.value,
                confidence=pred.confidence,
                fencer_side=side,
                camera_angle=self._estimate_camera_angle(frames),
                quality_score=pred.confidence * 0.8,  # Base quality from confidence
            ))

        return clips

    @staticmethod
    def _estimate_camera_angle(frames: list) -> str:
        """Heuristic to estimate camera angle from frame content."""
        if not frames:
            return "wide"

        # Simple heuristic: check frame aspect ratio and content
        h, w = frames[0].shape[:2]
        aspect = w / max(h, 1)

        if aspect > 2.0:
            return "wide"
        elif aspect < 1.2:
            return "close"
        return "medium"

    @staticmethod
    def _group_by_action(
        clips: List[TechniqueClip],
    ) -> List[TechniqueCollection]:
        """Group technique clips by action type."""
        groups: dict = defaultdict(list)
        for clip in clips:
            groups[clip.action].append(clip)

        collections: List[TechniqueCollection] = []
        for action, action_clips in sorted(groups.items()):
            # Find best example (highest quality score)
            best_idx = 0
            best_score = 0.0
            for i, c in enumerate(action_clips):
                if c.quality_score > best_score:
                    best_score = c.quality_score
                    best_idx = i

            collections.append(TechniqueCollection(
                action=action,
                clips=action_clips,
                best_example_idx=best_idx,
                count=len(action_clips),
            ))

        return collections
