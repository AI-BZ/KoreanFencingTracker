"""
Integrated analyzer combining Phase 1 (LED/score) with Phase 2 (pose/action).

Uses a 2-pass strategy:
  Pass 1: VideoProcessor.process_video_headless() -> MatchEvent list
  Pass 2: Extract frames around each event -> Pose + Action -> EnrichedMatchEvent

Does NOT modify VideoProcessor. All enrichment is additive.
"""

import json
import cv2
import numpy as np
from pathlib import Path
from typing import Optional, List, Dict, Tuple

from analyzer.models import (
    MatchEvent,
    EnrichedMatchEvent,
    PoseResult,
    FencerPose,
)
from analyzer.config import (
    ENRICHED_POSE_WINDOW_BEFORE,
    ENRICHED_POSE_WINDOW_AFTER,
)
from analyzer.video_processor import VideoProcessor
from analyzer.video_source import VideoSourceType, VideoSourceAssessment


class IntegratedAnalyzer:
    """
    2-pass analyzer: Phase 1 scoring events + Phase 2 pose/action enrichment.

    Usage:
        ia = IntegratedAnalyzer(enable_pose=True, enable_action=True)
        events = ia.analyze_video(video_path, rois)
    """

    def __init__(
        self,
        template_path: Optional[Path] = None,
        pose_estimator=None,
        action_classifier=None,
        enable_pose: bool = True,
        enable_action: bool = True,
    ):
        self.video_processor = VideoProcessor(template_path=template_path)
        self.enable_pose = enable_pose
        self.enable_action = enable_action

        # Lazy initialization: only create if enabled and not provided
        self._pose_estimator = pose_estimator
        self._action_classifier = action_classifier

    @property
    def pose_estimator(self):
        """Lazy-load PoseEstimator on first access."""
        if self._pose_estimator is None and self.enable_pose:
            from ml.pose_estimator import PoseEstimator
            self._pose_estimator = PoseEstimator()
        return self._pose_estimator

    @property
    def action_classifier(self):
        """Lazy-load ActionClassifier on first access."""
        if self._action_classifier is None and self.enable_action:
            from ml.action_classifier import ActionClassifier
            self._action_classifier = ActionClassifier()
        return self._action_classifier

    def analyze_video(
        self,
        video_path: str,
        rois: Dict[str, Tuple[int, int, int, int]],
        start_frame: int = 0,
        output_dir: Optional[str] = None,
    ) -> List[EnrichedMatchEvent]:
        """
        Full 2-pass analysis of a fencing match video.

        Pass 1: Run VideoProcessor.process_video_headless() for scoring events.
        Pass 2: For each event, extract surrounding frames and run pose/action.

        Args:
            video_path: Path to the video file.
            rois: Pre-defined ROIs for lamp/score detection.
            start_frame: Frame to start Phase 1 analysis from.
            output_dir: Directory for result files.

        Returns:
            List of EnrichedMatchEvent with pose and action data.
        """
        video_path = str(video_path)

        # --- Pass 1: Phase 1 scoring events ---
        events = self.video_processor.process_video_headless(
            video_path, rois, start_frame,
        )

        if not events:
            return []

        # --- Pass 2: Enrich with pose and action ---
        enriched_events = []
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            # Fallback: return un-enriched events
            return [EnrichedMatchEvent.from_match_event(e) for e in events]

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        for event in events:
            enriched = EnrichedMatchEvent.from_match_event(event)

            if self.enable_pose or self.enable_action:
                window_start = max(0, event.frame - ENRICHED_POSE_WINDOW_BEFORE)
                window_end = min(total_frames, event.frame + ENRICHED_POSE_WINDOW_AFTER)

                frames = self._extract_frames(cap, window_start, window_end)

                if frames and self.enable_pose and self.pose_estimator is not None:
                    pose_results = self.pose_estimator.estimate_poses_batch(
                        frames, start_idx=window_start,
                    )
                    enriched.pose_sequence = pose_results

                    # Find closest pose result to event frame for summary
                    closest_idx = self._find_closest_frame(
                        pose_results, event.frame,
                    )
                    if closest_idx is not None:
                        pose = pose_results[closest_idx]
                        for fencer in pose.fencers:
                            if fencer.side == "left":
                                enriched.pose_left = fencer
                            elif fencer.side == "right":
                                enriched.pose_right = fencer

                if frames and self.enable_action and self.action_classifier is not None:
                    action_result = self.action_classifier.classify_action(
                        frames, start_frame=window_start,
                    )
                    enriched.action_result = action_result

                    # Per-fencer action classification
                    if self.enable_pose and enriched.pose_left is not None:
                        left_bboxes = self._track_fencer_bboxes(
                            frames, window_start, "left",
                        )
                        if left_bboxes:
                            enriched.action_left = (
                                self.action_classifier.classify_per_fencer(
                                    frames, left_bboxes, window_start, "left",
                                )
                            )

                    if self.enable_pose and enriched.pose_right is not None:
                        right_bboxes = self._track_fencer_bboxes(
                            frames, window_start, "right",
                        )
                        if right_bboxes:
                            enriched.action_right = (
                                self.action_classifier.classify_per_fencer(
                                    frames, right_bboxes, window_start, "right",
                                )
                            )

            enriched_events.append(enriched)

        cap.release()

        if output_dir:
            self._save_enriched_results(video_path, enriched_events, output_dir)

        return enriched_events

    def analyze_video_auto(
        self,
        video_path: str,
        source_type: Optional[str] = None,
        rois: Optional[Dict[str, Tuple[int, int, int, int]]] = None,
        start_frame: int = 0,
        output_dir: Optional[str] = None,
    ):
        """
        Auto-detect video source type and route to appropriate pipeline.

        Args:
            video_path: Path to the video file.
            source_type: Override source type ("coach", "parent", "player",
                        "tv_broadcast"). If None, auto-detects.
            rois: Pre-defined ROIs (for coach/parent pipeline).
            start_frame: Frame to start from.
            output_dir: Directory for result files.

        Returns:
            Dict with 'source_assessment' and analysis results.
            Result type depends on detected source:
              - coach/parent: List[EnrichedMatchEvent]
              - player: List[PoseResult]
              - tv_broadcast: TVAnalysisResult (when available)
        """
        # Detect or parse source type
        if source_type:
            try:
                detected_type = VideoSourceType(source_type)
            except ValueError:
                detected_type = VideoSourceType.UNKNOWN
            assessment = VideoSourceAssessment(
                source_type=detected_type,
                confidence=1.0,
                scene_cuts_per_minute=0.0,
                avg_fencer_height_ratio=0.0,
                scoreboard_detected=False,
                overlay_detected=False,
                avg_person_count=0.0,
                stability_score=0.0,
                resolution=(0, 0),
                fps=0.0,
                duration_sec=0.0,
            )
        else:
            from ml.video_source_detector import VideoSourceDetector
            detector = VideoSourceDetector(
                pose_estimator=self.pose_estimator if self.enable_pose else None,
            )
            assessment = detector.detect(video_path)
            detected_type = assessment.source_type

        result: dict = {
            "source_assessment": assessment.to_dict(),
        }

        # Route to appropriate pipeline
        if detected_type == VideoSourceType.PLAYER:
            poses = self.analyze_video_pose_only(
                video_path, start_frame=start_frame,
            )
            result["pipeline"] = "pose_only"
            result["pose_results"] = [p.to_dict() for p in poses]

        elif detected_type == VideoSourceType.TV_BROADCAST:
            # Route to TVBroadcastAnalyzer (Step 5)
            try:
                from ml.tv_analyzer import TVBroadcastAnalyzer
                tv = TVBroadcastAnalyzer(pose_estimator=self.pose_estimator)
                tv_result = tv.analyze_broadcast(video_path)
                result["pipeline"] = "tv_broadcast"
                result["tv_result"] = tv_result.to_dict()
            except ImportError:
                # Fallback to pose-only if TV analyzer not yet available
                poses = self.analyze_video_pose_only(
                    video_path, start_frame=start_frame,
                )
                result["pipeline"] = "pose_only_fallback"
                result["pose_results"] = [p.to_dict() for p in poses]

        else:
            # COACH, PARENT, UNKNOWN → standard 2-pass pipeline
            if rois is None:
                rois = {}
            events = self.analyze_video(
                video_path, rois, start_frame, output_dir,
            )
            result["pipeline"] = "full_analysis"
            result["events"] = [e.to_dict() for e in events]

        return result

    def analyze_video_pose_only(
        self,
        video_path: str,
        start_frame: int = 0,
        end_frame: Optional[int] = None,
        every_n: int = 1,
    ) -> List[PoseResult]:
        """
        Run pose estimation only (no Phase 1, no action classification).

        Useful for pose visualization or pose data collection.

        Args:
            video_path: Path to the video file.
            start_frame: First frame to process.
            end_frame: Last frame to process (None = end of video).
            every_n: Process every N-th frame (1 = all frames).

        Returns:
            List of PoseResult.
        """
        if not self.enable_pose or self.pose_estimator is None:
            return []

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return []

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if end_frame is None:
            end_frame = total_frames

        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        results = []
        frame_idx = start_frame

        while frame_idx < end_frame:
            ret, frame = cap.read()
            if not ret:
                break

            if (frame_idx - start_frame) % every_n == 0:
                result = self.pose_estimator.estimate_pose(frame, frame_idx)
                results.append(result)

            frame_idx += 1

        cap.release()
        return results

    def _extract_frames(
        self,
        cap: cv2.VideoCapture,
        start: int,
        end: int,
    ) -> List[np.ndarray]:
        """Extract frames from an open VideoCapture."""
        frames = []
        cap.set(cv2.CAP_PROP_POS_FRAMES, start)

        for _ in range(end - start):
            ret, frame = cap.read()
            if not ret:
                break
            frames.append(frame)

        return frames

    def _track_fencer_bboxes(
        self,
        frames: List[np.ndarray],
        start_frame: int,
        side: str,
    ) -> List[List[float]]:
        """
        Get bounding boxes for a specific fencer across frames.

        Uses pose_sequence if available, otherwise runs pose estimation.
        """
        if not self.enable_pose or self.pose_estimator is None:
            return []

        bboxes = []
        pose_results = self.pose_estimator.estimate_poses_batch(
            frames, start_idx=start_frame,
        )

        for pose_result in pose_results:
            bbox_found = False
            for fencer in pose_result.fencers:
                if fencer.side == side:
                    bboxes.append(fencer.bbox)
                    bbox_found = True
                    break
            if not bbox_found:
                # Use full frame as fallback
                if frames:
                    h, w = frames[0].shape[:2]
                    bboxes.append([0.0, 0.0, float(w), float(h)])
                else:
                    bboxes.append([0.0, 0.0, 640.0, 480.0])

        return bboxes

    @staticmethod
    def _find_closest_frame(
        pose_results: List[PoseResult],
        target_frame: int,
    ) -> Optional[int]:
        """Find index of PoseResult closest to target frame."""
        if not pose_results:
            return None

        min_dist = float("inf")
        best_idx = 0
        for i, pr in enumerate(pose_results):
            dist = abs(pr.frame_idx - target_frame)
            if dist < min_dist:
                min_dist = dist
                best_idx = i
        return best_idx

    @staticmethod
    def _save_enriched_results(
        video_path: str,
        events: List[EnrichedMatchEvent],
        output_dir: str,
    ):
        """Save enriched analysis results as JSON."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        base_name = Path(video_path).stem
        json_path = out / f"{base_name}_enriched.json"

        data = {
            "video": str(video_path),
            "phase": 2,
            "enrichment": {
                "pose_estimation": True,
                "action_recognition": True,
            },
            "events": [e.to_dict() for e in events],
        }

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, ensure_ascii=False, indent=2, fp=f)
