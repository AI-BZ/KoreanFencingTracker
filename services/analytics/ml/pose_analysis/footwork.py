"""Footwork type detection from ankle/hip trajectories (pure function)."""

from typing import List

from analyzer.models import PoseResult, FootworkType, FootworkResult
from analyzer.config import (
    KP_LEFT_ANKLE, KP_RIGHT_ANKLE,
    FOOTWORK_LUNGE_HIP_DROP_MIN,
    FOOTWORK_LUNGE_FRONT_FOOT_RATIO,
    FOOTWORK_FLECHE_BOTH_ADVANCE_MIN,
    FOOTWORK_MIN_DISPLACEMENT_PX,
    FOOTWORK_LUNGE_HIP_DROP_RATIO_MIN,
    FOOTWORK_FLECHE_BOTH_ADVANCE_MIN_TUNED,
    FOOTWORK_FLECHE_MAX_RATIO,
)
from ml.pose_analysis.geometry import kp_valid, get_fencer_by_side
from ml.pose_analysis.body_metrics import compute_hip_center, compute_body_height


def detect_footwork(
    pose_sequence: List[PoseResult],
    side: str,
    footwork_window: int,
    use_ratio_based_hip_drop: bool,
) -> FootworkResult:
    """
    Detect footwork type for a fencer over the analysis window.

    Args:
        pose_sequence: Pose frames (last frame = touch moment).
        side: "left" or "right" fencer.
        footwork_window: Number of trailing frames to analyse.
        use_ratio_based_hip_drop: Toggle for ratio- vs absolute-based hip
            drop thresholding (read from the module global by the façade so
            it remains monkeypatchable).

    Returns:
        FootworkResult with type and confidence.
    """
    # Extract fencer poses for the analysis window
    window = pose_sequence[-footwork_window:]
    fencer_poses = []
    for pr in window:
        f = get_fencer_by_side(pr, side)
        if f is not None:
            fencer_poses.append(f)

    if len(fencer_poses) < 3:
        return FootworkResult(
            footwork_type=FootworkType.UNKNOWN,
            confidence=0.0,
        )

    first = fencer_poses[0]
    last = fencer_poses[-1]

    # Determine front/rear foot based on fencer side
    # Left fencer: right foot is front (closer to opponent)
    # Right fencer: left foot is front
    if side == "left":
        front_ankle_idx = KP_RIGHT_ANKLE
        rear_ankle_idx = KP_LEFT_ANKLE
    else:
        front_ankle_idx = KP_LEFT_ANKLE
        rear_ankle_idx = KP_RIGHT_ANKLE

    # Get ankle positions (first and last frame)
    first_kps = first.keypoints
    last_kps = last.keypoints
    if len(first_kps) < 17 or len(last_kps) < 17:
        return FootworkResult(
            footwork_type=FootworkType.UNKNOWN, confidence=0.0,
        )

    front_first = first_kps[front_ankle_idx]
    front_last = last_kps[front_ankle_idx]
    rear_first = first_kps[rear_ankle_idx]
    rear_last = last_kps[rear_ankle_idx]

    if not all(kp_valid(k) for k in [front_first, front_last, rear_first, rear_last]):
        return FootworkResult(
            footwork_type=FootworkType.UNKNOWN, confidence=0.0,
        )

    # Compute displacements (X-axis: positive = toward opponent for left fencer)
    direction = 1.0 if side == "left" else -1.0
    front_disp = (front_last.x - front_first.x) * direction
    rear_disp = (rear_last.x - rear_first.x) * direction

    front_disp_abs = abs(front_disp)
    rear_disp_abs = abs(rear_disp)

    # Hip drop: compare first vs last hip Y (higher Y = lower position in image)
    hip_first = compute_hip_center(first)
    hip_last = compute_hip_center(last)
    hip_drop = 0.0
    if hip_first is not None and hip_last is not None:
        hip_drop = hip_last[1] - hip_first[1]  # positive = dropped

    # Classification logic
    both_small = (front_disp_abs < FOOTWORK_MIN_DISPLACEMENT_PX
                  and rear_disp_abs < FOOTWORK_MIN_DISPLACEMENT_PX)

    if both_small:
        return FootworkResult(
            footwork_type=FootworkType.STATIONARY,
            confidence=0.9,
            hip_drop_px=hip_drop,
            front_foot_displacement_px=front_disp,
            rear_foot_displacement_px=rear_disp,
        )

    # Both feet retreating
    if front_disp < -FOOTWORK_MIN_DISPLACEMENT_PX and rear_disp < -FOOTWORK_MIN_DISPLACEMENT_PX:
        return FootworkResult(
            footwork_type=FootworkType.RETREAT,
            confidence=0.8,
            hip_drop_px=hip_drop,
            front_foot_displacement_px=front_disp,
            rear_foot_displacement_px=rear_disp,
        )

    # Compute front/rear ratio for lunge vs fleche distinction
    if rear_disp_abs > 0:
        ratio = front_disp_abs / max(rear_disp_abs, 1.0)
    else:
        ratio = front_disp_abs  # rear foot didn't move

    # Lunge: front foot advances much more than rear + hip drops
    # Check BEFORE fleche — a lunge with camera panning can look like fleche
    if use_ratio_based_hip_drop:
        bh = compute_body_height(last)
        hip_drop_ok = False
        if bh is not None and bh > 0:
            hip_drop_ok = (hip_drop / bh) >= FOOTWORK_LUNGE_HIP_DROP_RATIO_MIN
        else:
            hip_drop_ok = hip_drop >= FOOTWORK_LUNGE_HIP_DROP_MIN
    else:
        hip_drop_ok = hip_drop >= FOOTWORK_LUNGE_HIP_DROP_MIN

    if (front_disp > FOOTWORK_MIN_DISPLACEMENT_PX
            and ratio >= FOOTWORK_LUNGE_FRONT_FOOT_RATIO
            and hip_drop_ok):
        conf = min(0.9, 0.5 + (hip_drop / 40.0) + (ratio / 20.0))
        return FootworkResult(
            footwork_type=FootworkType.LUNGE,
            confidence=conf,
            hip_drop_px=hip_drop,
            front_foot_displacement_px=front_disp,
            rear_foot_displacement_px=rear_disp,
        )

    # Fleche: both feet advance significantly AND ratio is low (both move similarly)
    # If ratio is high, it's more likely a lunge without sufficient hip drop
    fleche_threshold = (
        FOOTWORK_FLECHE_BOTH_ADVANCE_MIN_TUNED
        if use_ratio_based_hip_drop
        else FOOTWORK_FLECHE_BOTH_ADVANCE_MIN
    )
    if (front_disp > fleche_threshold
            and rear_disp > fleche_threshold
            and ratio < FOOTWORK_FLECHE_MAX_RATIO):
        return FootworkResult(
            footwork_type=FootworkType.FLECHE,
            confidence=0.75,
            hip_drop_px=hip_drop,
            front_foot_displacement_px=front_disp,
            rear_foot_displacement_px=rear_disp,
        )

    # Advance: both feet move forward (sequential), hip stays level
    if front_disp > FOOTWORK_MIN_DISPLACEMENT_PX and rear_disp > 0:
        return FootworkResult(
            footwork_type=FootworkType.ADVANCE,
            confidence=0.7,
            hip_drop_px=hip_drop,
            front_foot_displacement_px=front_disp,
            rear_foot_displacement_px=rear_disp,
        )

    # Default: if front foot advanced but doesn't match lunge criteria
    if front_disp > FOOTWORK_MIN_DISPLACEMENT_PX:
        return FootworkResult(
            footwork_type=FootworkType.ADVANCE,
            confidence=0.5,
            hip_drop_px=hip_drop,
            front_foot_displacement_px=front_disp,
            rear_foot_displacement_px=rear_disp,
        )

    return FootworkResult(
        footwork_type=FootworkType.UNKNOWN,
        confidence=0.3,
        hip_drop_px=hip_drop,
        front_foot_displacement_px=front_disp,
        rear_foot_displacement_px=rear_disp,
    )
