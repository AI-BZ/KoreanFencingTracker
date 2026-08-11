"""Body-height, hip-center and inter-fencer distance metrics (pure functions)."""

from typing import List, Optional, Tuple

from analyzer.models import PoseResult, FencerPose, DistanceZone
from analyzer.config import (
    KP_LEFT_SHOULDER, KP_RIGHT_SHOULDER,
    KP_LEFT_HIP, KP_RIGHT_HIP,
    KP_LEFT_ANKLE, KP_RIGHT_ANKLE,
    DISTANCE_ZONE_THRESHOLDS,
)
from ml.pose_analysis.geometry import (
    kp_valid, midpoint, distance_2d, get_fencer_by_side,
)


def compute_body_height(fencer: FencerPose) -> Optional[float]:
    """
    Compute body height in pixels: shoulder_center to ankle_center.

    Uses COCO keypoints 5,6 (shoulders) and 15,16 (ankles).
    Returns None if keypoints have low confidence.
    """
    kps = fencer.keypoints
    if len(kps) < 17:
        return None

    l_sh, r_sh = kps[KP_LEFT_SHOULDER], kps[KP_RIGHT_SHOULDER]
    l_ank, r_ank = kps[KP_LEFT_ANKLE], kps[KP_RIGHT_ANKLE]

    if not (kp_valid(l_sh) and kp_valid(r_sh)):
        return None
    if not (kp_valid(l_ank) and kp_valid(r_ank)):
        return None

    shoulder_center = midpoint(l_sh, r_sh)
    ankle_center = midpoint(l_ank, r_ank)

    height = distance_2d(shoulder_center, ankle_center)
    return height if height > 0 else None


def compute_hip_center(fencer: FencerPose) -> Optional[Tuple[float, float]]:
    """Compute hip center from left/right hip keypoints."""
    kps = fencer.keypoints
    if len(kps) < 17:
        return None

    l_hip, r_hip = kps[KP_LEFT_HIP], kps[KP_RIGHT_HIP]
    if not (kp_valid(l_hip) and kp_valid(r_hip)):
        return None

    return midpoint(l_hip, r_hip)


def compute_distance_bh(
    fencer_a: FencerPose,
    fencer_b: FencerPose,
) -> Optional[float]:
    """
    Compute distance between two fencers in Body Height units.

    Uses X-axis distance between hip centers (side-view camera),
    normalized by average body height.
    """
    hip_a = compute_hip_center(fencer_a)
    hip_b = compute_hip_center(fencer_b)
    if hip_a is None or hip_b is None:
        return None

    bh_a = compute_body_height(fencer_a)
    bh_b = compute_body_height(fencer_b)
    if bh_a is None or bh_b is None:
        return None

    avg_bh = (bh_a + bh_b) / 2
    if avg_bh <= 0:
        return None

    # Side-view: use X-axis distance only
    x_distance = abs(hip_a[0] - hip_b[0])
    return x_distance / avg_bh


def classify_distance_zone(distance_bh: float) -> DistanceZone:
    """Classify a BH distance into a DistanceZone."""
    thresholds = DISTANCE_ZONE_THRESHOLDS
    if distance_bh > thresholds["out"]:
        return DistanceZone.OUT_OF_DISTANCE
    elif distance_bh > thresholds["adv_lunge"]:
        return DistanceZone.ADVANCE_LUNGE
    elif distance_bh > thresholds["lunge"]:
        return DistanceZone.LUNGE
    elif distance_bh > thresholds["extension"]:
        return DistanceZone.EXTENSION
    else:
        return DistanceZone.INFIGHTING


def compute_distance_series(
    pose_sequence: List[PoseResult],
) -> List[Optional[float]]:
    """
    Compute distance BH for each frame in a pose sequence.

    Returns list of distances (None if not computable for that frame).
    """
    distances: List[Optional[float]] = []
    for pose_result in pose_sequence:
        left = get_fencer_by_side(pose_result, "left")
        right = get_fencer_by_side(pose_result, "right")
        if left is not None and right is not None:
            d = compute_distance_bh(left, right)
            distances.append(d)
        else:
            distances.append(None)
    return distances


def smooth_distances(
    distances: List[Optional[float]],
    smoothing_window: int,
) -> List[Optional[float]]:
    """Apply moving average smoothing to distance series."""
    n = len(distances)
    smoothed: List[Optional[float]] = []
    half_w = smoothing_window // 2

    for i in range(n):
        start = max(0, i - half_w)
        end = min(n, i + half_w + 1)
        valid = [d for d in distances[start:end] if d is not None]
        if valid:
            smoothed.append(sum(valid) / len(valid))
        else:
            smoothed.append(None)
    return smoothed


def compute_closing_speed(
    distances: List[Optional[float]],
    fps: float,
) -> float:
    """
    Compute closing speed in BH/sec from a distance series.

    Positive = approaching, negative = separating.
    Uses first and last valid distances.
    """
    valid_pairs = [
        (i, d) for i, d in enumerate(distances) if d is not None
    ]
    if len(valid_pairs) < 2:
        return 0.0

    first_idx, first_d = valid_pairs[0]
    last_idx, last_d = valid_pairs[-1]

    frame_diff = last_idx - first_idx
    if frame_diff <= 0:
        return 0.0

    time_diff = frame_diff / fps
    # Positive = closing (distance decreasing)
    return (first_d - last_d) / time_diff
