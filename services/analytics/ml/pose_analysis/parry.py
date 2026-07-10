"""Parry (blade deflection) detection from relative wrist motion (pure function)."""

from typing import List, Optional, Tuple

from analyzer.models import PoseResult, ParryResult
from analyzer.config import (
    KP_LEFT_WRIST, KP_RIGHT_WRIST,
    PARRY_WRIST_LATERAL_MIN_PX,
    PARRY_WRIST_SPEED_MIN_PX,
)
from ml.pose_analysis.geometry import kp_valid, get_fencer_by_side
from ml.pose_analysis.body_metrics import compute_hip_center


def detect_parry(
    pose_sequence: List[PoseResult],
    side: str,
    parry_window: int,
    clean_indices: Optional[List[int]] = None,
    touch_idx: Optional[int] = None,
) -> ParryResult:
    """
    Detect parry (blade deflection) by a fencer in the frames before touch.

    Parry is detected by rapid wrist movement RELATIVE TO the body.
    This isolates defensive wrist motion from overall body movement
    during approach.  Only near-consecutive frames (gap <= 3) are
    compared to avoid false positives from camera-cut gaps.

    Args:
        pose_sequence: Pose frames (last = touch moment).
        side: "left" or "right" fencer to check for parry.
        parry_window: Number of frames before the touch to analyse.
        clean_indices: Frame indices without camera cuts.
        touch_idx: Frame index of touch moment.

    Returns:
        ParryResult with detection status and confidence.
    """
    # Determine the analysis window: frames before the touch
    end = touch_idx if touch_idx is not None else len(pose_sequence) - 1
    start = max(0, end - parry_window)

    # Filter to clean frames within the window
    if clean_indices is not None:
        frame_indices = [i for i in clean_indices if start <= i <= end]
    else:
        frame_indices = list(range(start, end + 1))

    # Weapon hand: left fencer uses right wrist (kp10), right fencer uses left wrist (kp9)
    if side == "left":
        wrist_idx = KP_RIGHT_WRIST
    else:
        wrist_idx = KP_LEFT_WRIST

    # Collect wrist Y and hip Y positions over clean frames in the window
    # We track hip Y to subtract body movement from wrist movement
    wrist_hip_positions: List[Tuple[int, float, float]] = []  # (frame_idx, wrist_y, hip_y)
    for i in frame_indices:
        pr = pose_sequence[i]
        fencer = get_fencer_by_side(pr, side)
        if fencer is None or len(fencer.keypoints) < 17:
            continue
        wrist = fencer.keypoints[wrist_idx]
        hip_center = compute_hip_center(fencer)
        if kp_valid(wrist) and hip_center is not None:
            wrist_hip_positions.append((i, wrist.y, hip_center[1]))

    if len(wrist_hip_positions) < 3:
        return ParryResult(parry_detected=False, confidence=0.0)

    # Compute max RELATIVE wrist displacement (wrist_delta - hip_delta)
    # Only between near-consecutive frames (gap <= 3) to avoid
    # large gaps from camera cuts inflating apparent movement
    max_rel_displacement = 0.0
    max_rel_speed = 0.0
    parry_frame = None

    for j in range(1, len(wrist_hip_positions)):
        prev_idx, prev_wy, prev_hy = wrist_hip_positions[j - 1]
        curr_idx, curr_wy, curr_hy = wrist_hip_positions[j]

        frame_gap = curr_idx - prev_idx
        if frame_gap > 3:
            # Too large a gap — likely camera cut remnant or missing detections
            continue

        # Relative displacement: how much wrist moved beyond body movement
        wrist_delta_y = abs(curr_wy - prev_wy)
        hip_delta_y = abs(curr_hy - prev_hy)
        relative_disp = max(0.0, wrist_delta_y - hip_delta_y)

        speed = relative_disp / max(frame_gap, 1)

        if relative_disp > max_rel_displacement:
            max_rel_displacement = relative_disp
            parry_frame = curr_idx

        if speed > max_rel_speed:
            max_rel_speed = speed

    # Parry detection: both displacement and speed must exceed thresholds
    detected = (
        max_rel_displacement >= PARRY_WRIST_LATERAL_MIN_PX
        and max_rel_speed >= PARRY_WRIST_SPEED_MIN_PX
    )

    if detected:
        # Confidence scales with displacement magnitude
        conf = min(0.95, 0.5 + (max_rel_displacement / 60.0) + (max_rel_speed / 30.0))
    else:
        conf = max(0.1, 0.3 - (max_rel_displacement / 100.0))
        parry_frame = None

    return ParryResult(
        parry_detected=detected,
        confidence=conf,
        wrist_lateral_displacement_px=max_rel_displacement,
        parry_frame_idx=parry_frame,
    )
