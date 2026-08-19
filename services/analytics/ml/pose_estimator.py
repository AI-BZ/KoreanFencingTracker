"""
Pose estimation using YOLO11-Pose for fencer tracking.

Detects up to 2 fencers per frame and assigns left/right sides
based on bounding box x-center position.

Coordinate systems
------------------
Three pixel coordinate systems coexist in the multi-piste pipeline and must
never be mixed:

1. **4K source** — the original camera file (e.g. 3840x2160).
2. **Piste work file** — the cropped + downscaled video that is actually fed to
   this estimator (e.g. 1280 wide). Everything in this module — bboxes,
   keypoints, and :class:`PisteGate` bounds — is in *work-file* pixels.
3. **Scoreboard crop** — a separate 4K-resolution crop used by the LED/OCR path.

Conversion between them happens in exactly one place (the piste preparation
script), never here.
"""

import time
import numpy as np
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Tuple

from analyzer.models import PoseKeypoint, FencerPose, PoseResult
from analyzer.config import (
    POSE_MODEL_PATH,
    POSE_CONFIDENCE_THRESHOLD,
    POSE_KEYPOINT_CONFIDENCE,
    POSE_MAX_PERSONS,
    POSE_IMGSZ,
    DEVICE_PREFERENCE,
)

# COCO keypoint indices for the ankles (used to derive a person's foot line).
_LEFT_ANKLE_IDX = 15
_RIGHT_ANKLE_IDX = 16

# A bbox whose bottom edge is within this many pixels of the frame bottom is
# treated as clipped by the frame border (i.e. a foreground person).
_BOTTOM_CLIP_MARGIN = 2.0


@dataclass
class PisteGate:
    """
    Target-piste person gate, in WORK-FILE pixel coordinates (not 4K source).

    In a multi-piste venue the camera sees background fencers, foreground
    referees and scorekeepers in addition to the two fencers being analysed.
    They separate cleanly by foot height: people further from the camera have a
    smaller foot ``y``, people in the foreground a larger one. The gate keeps
    only detections whose foot ``y`` falls inside the band of the target piste.

    Both bounds are pixel rows of the **piste work file** (the cropped and
    downscaled video handed to :class:`PoseEstimator`), *not* rows of the 4K
    source and not of the scoreboard crop.
    """
    foot_y_min: float
    foot_y_max: float


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
        max_det: int = POSE_MAX_PERSONS,
        piste_gate: Optional[PisteGate] = None,
    ):
        """
        Args:
            model_path: YOLO11-Pose weights. Defaults to POSE_MODEL_PATH.
            confidence: Detection confidence threshold.
            device: Torch device; auto-resolved when omitted.
            imgsz: YOLO inference size.
            max_det: Maximum detections YOLO may return per frame. The default
                reproduces the historical behaviour (top-2 by confidence). Raise
                it when using `piste_gate`, which needs a wide candidate pool:
                `max_det` is a YOLO call argument, so anyone filtered out here
                is never returned and cannot be recovered downstream.
            piste_gate: Optional target-piste foot-band gate. Bounds are in
                **work-file pixels** (see module docstring). `None` keeps the
                original single-piste code path byte-for-byte.
        """
        self.model_path = Path(model_path) if model_path else POSE_MODEL_PATH
        self.confidence = confidence
        self.device = device or self._resolve_device()
        self.imgsz = imgsz
        self.max_det = max_det
        self.piste_gate = piste_gate
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
            max_det=self.max_det,
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

        When `self.piste_gate` is set, the candidate list is first filtered down
        to the people standing on the target piste (see `_apply_piste_gate`);
        all coordinates involved are work-file pixels. With `piste_gate=None`
        the original code path runs unchanged.
        """
        fencers: List[FencerPose] = []

        if not yolo_results or len(yolo_results) == 0:
            return fencers

        result = yolo_results[0]

        if result.keypoints is None or result.boxes is None:
            return fencers

        keypoints_data = result.keypoints.data.cpu().numpy()
        boxes_data = result.boxes.data.cpu().numpy()

        # Cap by self.max_det rather than the module constant so the gate path
        # sees every candidate YOLO returned. Behaviour is unchanged by default:
        # self.max_det defaults to POSE_MAX_PERSONS, and YOLO already returned
        # at most max_det boxes, so the cap is a no-op either way.
        for person_idx in range(min(len(keypoints_data), self.max_det)):
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

        if self.piste_gate is not None:
            frame_h, frame_w = self._frame_shape(result, fencers)
            return self._apply_piste_gate(fencers, frame_h, frame_w)

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

    # ------------------------------------------------------------------
    # Piste gate (work-file pixel coordinates)
    # ------------------------------------------------------------------

    @staticmethod
    def _frame_shape(result, candidates: List[FencerPose]) -> Tuple[Optional[float], Optional[float]]:
        """
        Resolve (frame_h, frame_w) in work-file pixels.

        ultralytics `Results` carries `orig_shape` as (h, w); this handles it
        being absent or malformed so the gate also works with synthetic results.

        Fallbacks when `orig_shape` is unusable:
          - `frame_h` stays None, which disables *only* the bottom-edge clipping
            rejection (we cannot tell where the bottom edge is; the foot band
            itself still applies).
          - `frame_w` is estimated as the largest bbox right edge among all
            candidates. On a wide piste crop several people span the frame, so
            this is close to the true width. It is a lower bound, so the derived
            midpoint is biased slightly left — acceptable because this path only
            triggers on non-ultralytics results.
        """
        orig_shape = getattr(result, "orig_shape", None)
        if orig_shape is not None and len(orig_shape) >= 2:
            return float(orig_shape[0]), float(orig_shape[1])

        frame_w = max((f.bbox[2] for f in candidates), default=None)
        return None, (float(frame_w) if frame_w is not None else None)

    @staticmethod
    def _foot_y(fencer: FencerPose, frame_h: Optional[float]) -> Optional[float]:
        """
        Lowest confident foot position of a person, in work-file pixels.

        Uses the lower (larger y) of the two ankle keypoints that clear
        POSE_KEYPOINT_CONFIDENCE. If neither ankle is confident, falls back to
        the bbox bottom edge — unless that edge sits at the frame bottom, which
        means the person is cut off by the frame and is therefore in the
        foreground (referee / scorekeeper). Those are rejected outright by
        returning None, without a band test.
        """
        ankle_ys = [
            fencer.keypoints[idx].y
            for idx in (_LEFT_ANKLE_IDX, _RIGHT_ANKLE_IDX)
            if idx < len(fencer.keypoints)
            and fencer.keypoints[idx].confidence > POSE_KEYPOINT_CONFIDENCE
        ]
        if ankle_ys:
            return max(ankle_ys)

        y2 = fencer.bbox[3]
        if frame_h is not None and y2 >= frame_h - _BOTTOM_CLIP_MARGIN:
            return None
        return y2

    @staticmethod
    def _assign_pair_sides(first: FencerPose, second: FencerPose) -> None:
        """Assign left/right to exactly two people by bbox x-center."""
        cx0 = (first.bbox[0] + first.bbox[2]) / 2
        cx1 = (second.bbox[0] + second.bbox[2]) / 2
        if cx0 <= cx1:
            first.side = "left"
            second.side = "right"
        else:
            first.side = "right"
            second.side = "left"

    def _apply_piste_gate(
        self,
        candidates: List[FencerPose],
        frame_h: Optional[float],
        frame_w: Optional[float],
    ) -> List[FencerPose]:
        """
        Keep only the people standing on the target piste, then assign sides.

        All coordinates are work-file pixels. Selection is by foot height only:
        when more than two people pass the band, the two with the *smallest*
        foot_y win. Confidence is deliberately never used as a tie-break —
        measured foreground referees score 0.84-0.90 while the real fencers
        score 0.55-0.85, so a confidence rule picks the referee.
        """
        gate = self.piste_gate

        survivors: List[Tuple[float, FencerPose]] = []
        for fencer in candidates:
            foot_y = self._foot_y(fencer, frame_h)
            if foot_y is None:
                continue  # clipped at the bottom edge → foreground person
            if gate.foot_y_min <= foot_y <= gate.foot_y_max:
                survivors.append((foot_y, fencer))

        # Ascending foot_y: intruders into the band always come from the
        # foreground, i.e. they have the largest foot_y.
        survivors.sort(key=lambda pair: pair[0])
        kept = [fencer for _, fencer in survivors[:POSE_MAX_PERSONS]]

        if len(kept) == 2:
            self._assign_pair_sides(kept[0], kept[1])
        elif len(kept) == 1:
            if frame_w is None:
                # No width available at all (unreachable while a candidate
                # exists, since _frame_shape estimates from bboxes). Match the
                # non-gate path's default rather than guess.
                kept[0].side = "left"
            else:
                cx = (kept[0].bbox[0] + kept[0].bbox[2]) / 2
                kept[0].side = "left" if cx < frame_w / 2 else "right"

        return kept
