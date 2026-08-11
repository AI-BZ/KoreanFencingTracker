"""
Pose estimation using YOLO11-Pose for fencer tracking.

Detects up to 2 fencers per frame and assigns left/right sides
based on bounding box x-center position.
"""

import time
import numpy as np
from pathlib import Path
from typing import Optional, List

from analyzer.models import PoseKeypoint, FencerPose, PoseResult
from analyzer.config import (
    POSE_MODEL_PATH,
    POSE_CONFIDENCE_THRESHOLD,
    POSE_KEYPOINT_CONFIDENCE,
    POSE_MAX_PERSONS,
    POSE_IMGSZ,
    DEVICE_PREFERENCE,
)


class PoseEstimator:
    """
    YOLO11-Pose wrapper for fencing pose estimation.

    Uses lazy loading: the model is only loaded on the first call
    to estimate_pose() or estimate_poses_batch().
    """

    def __init__(
        self,
        model_path: Optional[Path] = None,
        confidence: float = POSE_CONFIDENCE_THRESHOLD,
        device: Optional[str] = None,
        imgsz: int = POSE_IMGSZ,
    ):
        self.model_path = Path(model_path) if model_path else POSE_MODEL_PATH
        self.confidence = confidence
        self.device = device or self._resolve_device()
        self.imgsz = imgsz
        self._model = None

    @staticmethod
    def _resolve_device() -> str:
        """Auto-select best available device: MPS > CUDA > CPU."""
        try:
            import torch
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return "mps"
            if torch.cuda.is_available():
                return "cuda"
        except ImportError:
            pass
        return "cpu"

    def _load_model(self):
        """Load YOLO11-Pose model on first use."""
        if self._model is not None:
            return

        from ultralytics import YOLO
        self._model = YOLO(str(self.model_path))

    def estimate_pose(
        self,
        frame: np.ndarray,
        frame_idx: int = 0,
    ) -> PoseResult:
        """
        Estimate poses for a single frame.

        Args:
            frame: BGR image (H, W, 3).
            frame_idx: Frame number for the result.

        Returns:
            PoseResult with detected fencers.
        """
        self._load_model()

        t0 = time.perf_counter()
        results = self._model(
            frame,
            device=self.device,
            imgsz=self.imgsz,
            conf=self.confidence,
            max_det=POSE_MAX_PERSONS,
            verbose=False,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000

        fencers = self._parse_results(results)
        return PoseResult(
            frame_idx=frame_idx,
            fencers=fencers,
            inference_time_ms=round(elapsed_ms, 2),
        )

    def estimate_poses_batch(
        self,
        frames: List[np.ndarray],
        start_idx: int = 0,
    ) -> List[PoseResult]:
        """
        Estimate poses for a batch of frames.

        Args:
            frames: List of BGR images.
            start_idx: Frame index of the first frame.

        Returns:
            List of PoseResult, one per frame.
        """
        results = []
        for i, frame in enumerate(frames):
            result = self.estimate_pose(frame, frame_idx=start_idx + i)
            results.append(result)
        return results

    def _parse_results(self, yolo_results) -> List[FencerPose]:
        """
        Parse YOLO results into FencerPose objects.

        Assigns left/right side based on bbox x-center.
        """
        fencers: List[FencerPose] = []

        if not yolo_results or len(yolo_results) == 0:
            return fencers

        result = yolo_results[0]

        if result.keypoints is None or result.boxes is None:
            return fencers

        keypoints_data = result.keypoints.data.cpu().numpy()
        boxes_data = result.boxes.data.cpu().numpy()

        for person_idx in range(min(len(keypoints_data), POSE_MAX_PERSONS)):
            kps = keypoints_data[person_idx]  # (17, 3): x, y, conf
            box = boxes_data[person_idx]  # x1, y1, x2, y2, conf, cls

            keypoints = []
            for joint_idx in range(min(len(kps), 17)):
                kp = kps[joint_idx]
                keypoints.append(PoseKeypoint(
                    x=float(kp[0]),
                    y=float(kp[1]),
                    confidence=float(kp[2]),
                ))

            bbox = [float(box[0]), float(box[1]), float(box[2]), float(box[3])]
            person_conf = float(box[4])

            fencers.append(FencerPose(
                keypoints=keypoints,
                bbox=bbox,
                person_confidence=person_conf,
            ))

        # Assign left/right by x-center of bbox
        if len(fencers) == 2:
            cx0 = (fencers[0].bbox[0] + fencers[0].bbox[2]) / 2
            cx1 = (fencers[1].bbox[0] + fencers[1].bbox[2]) / 2
            if cx0 <= cx1:
                fencers[0].side = "left"
                fencers[1].side = "right"
            else:
                fencers[0].side = "right"
                fencers[1].side = "left"
        elif len(fencers) == 1:
            # Single detection: assign based on frame midpoint
            cx = (fencers[0].bbox[0] + fencers[0].bbox[2]) / 2
            fencers[0].side = "left"  # default; caller may override

        return fencers
