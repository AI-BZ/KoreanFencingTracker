"""Pure geometric helpers for pose analysis (no state, no config beyond thresholds)."""

import math
from typing import Optional, Tuple

from analyzer.models import PoseKeypoint, FencerPose, PoseResult
from analyzer.config import POSE_KEYPOINT_CONFIDENCE


def kp_valid(kp: PoseKeypoint, min_conf: float = POSE_KEYPOINT_CONFIDENCE) -> bool:
    """Check if a keypoint has sufficient confidence."""
    return kp.confidence >= min_conf


def midpoint(a: PoseKeypoint, b: PoseKeypoint) -> Tuple[float, float]:
    """Midpoint of two keypoints (x, y)."""
    return ((a.x + b.x) / 2, (a.y + b.y) / 2)


def distance_2d(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """Euclidean distance between two 2D points."""
    return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)


def angle_between_points(
    a: Tuple[float, float],
    b: Tuple[float, float],
    c: Tuple[float, float],
) -> float:
    """
    Compute angle at point b formed by segments ba and bc (degrees, 0-180).
    """
    ba = (a[0] - b[0], a[1] - b[1])
    bc = (c[0] - b[0], c[1] - b[1])
    dot = ba[0] * bc[0] + ba[1] * bc[1]
    mag_ba = math.sqrt(ba[0] ** 2 + ba[1] ** 2)
    mag_bc = math.sqrt(bc[0] ** 2 + bc[1] ** 2)
    if mag_ba == 0 or mag_bc == 0:
        return 0.0
    cos_angle = max(-1.0, min(1.0, dot / (mag_ba * mag_bc)))
    return math.degrees(math.acos(cos_angle))


def angle_from_vertical(
    top: Tuple[float, float],
    bottom: Tuple[float, float],
) -> float:
    """
    Compute angle (degrees) of the vector top→bottom from vertical downward.

    0 = perfectly vertical, 90 = horizontal.
    """
    dx = bottom[0] - top[0]
    dy = bottom[1] - top[1]
    length = math.sqrt(dx * dx + dy * dy)
    if length == 0:
        return 0.0
    # Vertical is (0, 1) in image coords (y increases downward)
    cos_angle = max(-1.0, min(1.0, dy / length))
    return math.degrees(math.acos(cos_angle))


def get_fencer_by_side(
    pose_result: PoseResult,
    side: str,
) -> Optional[FencerPose]:
    """Get fencer with matching side from a PoseResult."""
    for f in pose_result.fencers:
        if f.side == side:
            return f
    return None
