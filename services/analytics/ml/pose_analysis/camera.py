"""Camera-cut detection and touch-moment finding (pure functions)."""

from typing import List, Optional

from analyzer.models import PoseResult
from analyzer.config import CAMERA_CUT_HIP_JUMP_PX
from ml.pose_analysis.geometry import get_fencer_by_side
from ml.pose_analysis.body_metrics import compute_hip_center, compute_distance_bh


def filter_camera_cuts(pose_sequence: List[PoseResult]) -> List[int]:
    """
    Detect frames where a camera cut likely occurred.

    Camera cuts cause sudden jumps in fencer hip positions (>100px between
    consecutive frames). Returns list of frame indices that are clean
    (no camera cut from previous frame).
    """
    if not pose_sequence:
        return []

    clean_indices = [0]  # first frame is always "clean"

    for i in range(1, len(pose_sequence)):
        jump = False
        for side in ("left", "right"):
            prev_f = get_fencer_by_side(pose_sequence[i - 1], side)
            curr_f = get_fencer_by_side(pose_sequence[i], side)
            if prev_f is None or curr_f is None:
                continue

            prev_hip = compute_hip_center(prev_f)
            curr_hip = compute_hip_center(curr_f)
            if prev_hip is None or curr_hip is None:
                continue

            dx = abs(curr_hip[0] - prev_hip[0])
            dy = abs(curr_hip[1] - prev_hip[1])
            if dx > CAMERA_CUT_HIP_JUMP_PX or dy > CAMERA_CUT_HIP_JUMP_PX:
                jump = True
                break

        if not jump:
            clean_indices.append(i)

    return clean_indices


def find_touch_moment(
    pose_sequence: List[PoseResult],
    clean_indices: Optional[List[int]] = None,
) -> int:
    """
    Find the frame index where fencers are closest (likely touch moment).

    Uses minimum distance between hip centers across clean frames.
    Falls back to last frame if distance can't be computed.
    """
    if not pose_sequence:
        return 0

    indices = clean_indices if clean_indices else list(range(len(pose_sequence)))
    min_dist = float("inf")
    touch_idx = indices[-1] if indices else len(pose_sequence) - 1

    for i in indices:
        pr = pose_sequence[i]
        left = get_fencer_by_side(pr, "left")
        right = get_fencer_by_side(pr, "right")
        if left is None or right is None:
            continue

        d = compute_distance_bh(left, right)
        if d is not None and d < min_dist:
            min_dist = d
            touch_idx = i

    return touch_idx
