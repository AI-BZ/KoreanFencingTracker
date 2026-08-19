"""Joint angles, per-joint velocity/acceleration, and handedness (pure functions)."""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from analyzer.models import (
    PoseResult, FencerPose, JointAngles, JointKinematics, FrameKinematics,
)
from analyzer.config import (
    KP_LEFT_SHOULDER, KP_RIGHT_SHOULDER,
    KP_LEFT_ELBOW, KP_RIGHT_ELBOW,
    KP_LEFT_WRIST, KP_RIGHT_WRIST,
    KP_LEFT_HIP, KP_RIGHT_HIP,
    KP_LEFT_KNEE, KP_RIGHT_KNEE,
    KP_LEFT_ANKLE, KP_RIGHT_ANKLE,
    CAMERA_CUT_HIP_JUMP_PX,
    KINEMATICS_TRACKED_JOINTS,
    KINEMATICS_JOINT_TO_KP,
)
from ml.pose_analysis.geometry import (
    kp_valid, midpoint, angle_between_points, angle_from_vertical,
    get_fencer_by_side,
)
from ml.pose_analysis.body_metrics import compute_body_height, compute_hip_center


def compute_joint_angles(fencer: FencerPose, side: str) -> JointAngles:
    """
    Compute 2D joint angles from COCO keypoints.

    Args:
        fencer: FencerPose with 17 COCO keypoints.
        side: "left" or "right" fencer (determines front/rear leg).

    Returns:
        JointAngles with hip, knee, trunk, and arm extension values.
    """
    kps = fencer.keypoints
    if len(kps) < 17:
        return JointAngles()

    result = JointAngles()

    # Shoulder center and hip center
    l_sh, r_sh = kps[KP_LEFT_SHOULDER], kps[KP_RIGHT_SHOULDER]
    l_hip, r_hip = kps[KP_LEFT_HIP], kps[KP_RIGHT_HIP]

    sh_center = None
    hip_center = None
    if kp_valid(l_sh) and kp_valid(r_sh):
        sh_center = midpoint(l_sh, r_sh)
    if kp_valid(l_hip) and kp_valid(r_hip):
        hip_center = midpoint(l_hip, r_hip)

    # Trunk lean: angle from vertical of shoulder_center → hip_center
    if sh_center is not None and hip_center is not None:
        result.trunk_lean_deg = angle_from_vertical(sh_center, hip_center)

    # Determine front/rear leg
    if side == "left":
        front_knee_idx, front_ankle_idx = KP_RIGHT_KNEE, KP_RIGHT_ANKLE
        rear_knee_idx, rear_ankle_idx = KP_LEFT_KNEE, KP_LEFT_ANKLE
        front_hip_idx, rear_hip_idx = KP_RIGHT_HIP, KP_LEFT_HIP
    else:
        front_knee_idx, front_ankle_idx = KP_LEFT_KNEE, KP_LEFT_ANKLE
        rear_knee_idx, rear_ankle_idx = KP_RIGHT_KNEE, KP_RIGHT_ANKLE
        front_hip_idx, rear_hip_idx = KP_LEFT_HIP, KP_RIGHT_HIP

    # Hip angle: shoulder_center — hip_center — front_knee
    front_knee = kps[front_knee_idx]
    if sh_center is not None and hip_center is not None and kp_valid(front_knee):
        result.hip_angle = angle_between_points(
            sh_center, hip_center, (front_knee.x, front_knee.y),
        )

    # Front knee angle: front_hip — front_knee — front_ankle
    front_hip_kp = kps[front_hip_idx]
    front_ankle_kp = kps[front_ankle_idx]
    if kp_valid(front_hip_kp) and kp_valid(front_knee) and kp_valid(front_ankle_kp):
        result.front_knee_angle = angle_between_points(
            (front_hip_kp.x, front_hip_kp.y),
            (front_knee.x, front_knee.y),
            (front_ankle_kp.x, front_ankle_kp.y),
        )

    # Rear knee angle: rear_hip — rear_knee — rear_ankle
    rear_hip_kp = kps[rear_hip_idx]
    rear_knee_kp = kps[rear_knee_idx]
    rear_ankle_kp = kps[rear_ankle_idx]
    if kp_valid(rear_hip_kp) and kp_valid(rear_knee_kp) and kp_valid(rear_ankle_kp):
        result.rear_knee_angle = angle_between_points(
            (rear_hip_kp.x, rear_hip_kp.y),
            (rear_knee_kp.x, rear_knee_kp.y),
            (rear_ankle_kp.x, rear_ankle_kp.y),
        )

    # Arm extension ratio: weapon arm elbow angle / 180
    if side == "left":
        shoulder_idx, elbow_idx, wrist_idx = KP_RIGHT_SHOULDER, KP_RIGHT_ELBOW, KP_RIGHT_WRIST
    else:
        shoulder_idx, elbow_idx, wrist_idx = KP_LEFT_SHOULDER, KP_LEFT_ELBOW, KP_LEFT_WRIST

    sh_kp = kps[shoulder_idx]
    elb_kp = kps[elbow_idx]
    wr_kp = kps[wrist_idx]
    if kp_valid(sh_kp) and kp_valid(elb_kp) and kp_valid(wr_kp):
        elbow_angle = angle_between_points(
            (sh_kp.x, sh_kp.y),
            (elb_kp.x, elb_kp.y),
            (wr_kp.x, wr_kp.y),
        )
        result.arm_extension_ratio = elbow_angle / 180.0

    return result


def compute_joint_angles_for_side(
    pose_result: PoseResult,
    side: str,
) -> Optional[JointAngles]:
    """Compute joint angles for a fencer from a single frame."""
    fencer = get_fencer_by_side(pose_result, side)
    if fencer is None:
        return None
    ja = compute_joint_angles(fencer, side)
    # Return None if nothing was computed
    if (ja.hip_angle is None and ja.front_knee_angle is None
            and ja.trunk_lean_deg is None and ja.arm_extension_ratio is None):
        return None
    return ja


def compute_forward_arm_extension(fencer: FencerPose, side: str) -> Optional[float]:
    """Extension ratio (0-1) of the arm held toward the opponent, or None.

    :func:`compute_joint_angles` assumes the weapon arm is the anatomical arm
    nearest the opponent (right arm for the left-hand fencer). That assumption
    breaks for left-handers, and handedness detection is not always able to
    settle the question — on the reference foil final it returned ``None`` for
    both fencers at confidence 0.03-0.04.

    Rather than trust the assumption, pick per frame whichever wrist is further
    toward the opponent and measure that arm. A fencer's weapon hand leads; the
    rear arm trails behind the body. This makes the signal independent of
    handedness, and it also survives the occlusion case where the far-side arm
    disappears while the near-side one is visible.

    ``compute_joint_angles().arm_extension_ratio`` is deliberately left alone —
    the clip overlay renders it and must keep showing the same number.

    Returns ``None`` when neither arm has a confident shoulder/elbow/wrist
    triple.
    """
    kps = fencer.keypoints
    if len(kps) < 17:
        return None

    # Left-of-frame fencer faces right, so larger x is toward the opponent.
    toward_opponent = 1.0 if side == "left" else -1.0

    best_ratio: Optional[float] = None
    best_reach: Optional[float] = None

    for shoulder_idx, elbow_idx, wrist_idx in (
        (KP_LEFT_SHOULDER, KP_LEFT_ELBOW, KP_LEFT_WRIST),
        (KP_RIGHT_SHOULDER, KP_RIGHT_ELBOW, KP_RIGHT_WRIST),
    ):
        sh, elb, wr = kps[shoulder_idx], kps[elbow_idx], kps[wrist_idx]
        if not (kp_valid(sh) and kp_valid(elb) and kp_valid(wr)):
            continue
        reach = toward_opponent * wr.x
        if best_reach is None or reach > best_reach:
            best_reach = reach
            angle = angle_between_points(
                (sh.x, sh.y), (elb.x, elb.y), (wr.x, wr.y),
            )
            best_ratio = angle / 180.0

    return best_ratio


def compute_forward_arm_extension_for_side(
    pose_result: PoseResult,
    side: str,
) -> Optional[float]:
    """:func:`compute_forward_arm_extension` for a whole frame; None if absent."""
    fencer = get_fencer_by_side(pose_result, side)
    if fencer is None:
        return None
    return compute_forward_arm_extension(fencer, side)


def detect_handedness(
    pose_sequence: List[PoseResult],
    side: str,
    min_frames: int = 30,
) -> Tuple[Optional[str], float]:
    """Detect fencer handedness by comparing arm extension asymmetry.

    Weapon arm (dominant hand) shows higher average extension ratio
    because fencers extend their weapon arm forward during en garde,
    attacks, and most fencing actions.

    Args:
        pose_sequence: Full-bout pose frames.
        side: "left" or "right" fencer to analyze.
        min_frames: Minimum valid frames required for reliable detection.

    Returns:
        (handedness, confidence): e.g., ("right", 0.85) or (None, 0.0)
        handedness: "right" | "left" | None (insufficient data)
    """
    left_extensions: List[float] = []
    right_extensions: List[float] = []

    for pr in pose_sequence:
        fencer = get_fencer_by_side(pr, side)
        if fencer is None or len(fencer.keypoints) < 17:
            continue

        # Left arm extension
        lsh = fencer.keypoints[KP_LEFT_SHOULDER]
        lel = fencer.keypoints[KP_LEFT_ELBOW]
        lwr = fencer.keypoints[KP_LEFT_WRIST]
        if kp_valid(lsh) and kp_valid(lel) and kp_valid(lwr):
            angle = angle_between_points(
                (lsh.x, lsh.y), (lel.x, lel.y), (lwr.x, lwr.y)
            )
            left_extensions.append(angle / 180.0)

        # Right arm extension
        rsh = fencer.keypoints[KP_RIGHT_SHOULDER]
        rel = fencer.keypoints[KP_RIGHT_ELBOW]
        rwr = fencer.keypoints[KP_RIGHT_WRIST]
        if kp_valid(rsh) and kp_valid(rel) and kp_valid(rwr):
            angle = angle_between_points(
                (rsh.x, rsh.y), (rel.x, rel.y), (rwr.x, rwr.y)
            )
            right_extensions.append(angle / 180.0)

    if len(left_extensions) < min_frames or len(right_extensions) < min_frames:
        return (None, 0.0)

    avg_left = sum(left_extensions) / len(left_extensions)
    avg_right = sum(right_extensions) / len(right_extensions)

    diff = avg_right - avg_left  # positive = right arm more extended
    max_ext = max(avg_left, avg_right)
    ratio = abs(diff) / max_ext if max_ext > 0 else 0.0

    THRESHOLD = 0.05  # 5% difference required for a call
    if ratio < THRESHOLD:
        return (None, ratio)  # too similar to distinguish

    handedness = "right" if diff > 0 else "left"
    confidence = min(ratio / 0.15, 1.0)  # 15% diff → confidence 1.0
    return (handedness, round(confidence, 2))


# ------------------------------------------------------------------
# Handedness v2 — which anatomical limb leads toward the opponent
# ------------------------------------------------------------------

#: The four torso joints that define a fencer's centre and vertical span.
_HANDEDNESS_TORSO_KPS = (
    KP_LEFT_SHOULDER, KP_RIGHT_SHOULDER, KP_LEFT_HIP, KP_RIGHT_HIP,
)

#: Limb pairs that vote, with the weight each carries. Ankles outweigh wrists
#: because the front foot stays in frame for the whole bout while the weapon
#: hand vanishes behind the fencer's own body, the opponent, or the guard for
#: long stretches — a wrist vote is the same signal measured on worse data.
_HANDEDNESS_LIMBS: Tuple[Tuple[str, int, int, float], ...] = (
    ("ankle", KP_LEFT_ANKLE, KP_RIGHT_ANKLE, 1.0),
    ("wrist", KP_LEFT_WRIST, KP_RIGHT_WRIST, 0.5),
)

#: Minimum horizontal gap between the two fencers' centres, in pixels. Closer
#: than this and they overlap in x, so "toward the opponent" has no direction
#: to point in and every limb reading from that frame is noise.
_HANDEDNESS_MIN_CENTROID_GAP_PX = 5.0

#: A limb separated by many times the floor is not more informative than one at
#: three times it — the extra reach is a lunge, not extra certainty — so the
#: per-frame weight stops growing here.
_HANDEDNESS_SEPARATION_CAP = 3.0


@dataclass
class HandednessVerdict:
    """Outcome of :func:`detect_handedness_v2` for one fencer."""
    handedness: Optional[str]      # "left" | "right" | None
    confidence: float              # 0.0-1.0
    frames_used: int               # frames contributing >= 1 limb vote
    left_weight: float
    right_weight: float
    #: limb name -> (call, confidence, frames) for that limb pair alone, so a
    #: caller can see whether ankles and wrists agree.
    per_limb: Dict[str, Tuple[Optional[str], float, int]] = field(default_factory=dict)


def _handedness_torso_centroid_x(fencer: FencerPose) -> Optional[float]:
    """Mean x of the four torso joints, or None if the pose is too short."""
    kps = fencer.keypoints
    if len(kps) < 17:
        return None
    return sum(kps[i].x for i in _HANDEDNESS_TORSO_KPS) / len(_HANDEDNESS_TORSO_KPS)


def _handedness_body_scale(fencer: FencerPose) -> Optional[float]:
    """Vertical span of the confident torso joints, in pixels, or None.

    Separations are divided by this so the thresholds mean the same thing for a
    fencer filmed near the camera and one at the far end of the piste. Two
    confident joints are the minimum that can span anything; a degenerate span
    would divide the ratio up to infinity.
    """
    kps = fencer.keypoints
    ys = [kps[i].y for i in _HANDEDNESS_TORSO_KPS if kp_valid(kps[i])]
    if len(ys) < 2:
        return None
    span = max(ys) - min(ys)
    return span if span > 1.0 else None


def detect_handedness_v2(
    pose_sequence: List[PoseResult],
    side: str,
    min_frames: int = 30,
    min_keypoint_confidence: float = 0.4,
    min_separation_ratio: float = 0.15,
) -> HandednessVerdict:
    """Detect handedness from which anatomical limb leads toward the opponent.

    Both fencers stand side-on with the weapon arm and the front foot pointed
    at each other — that is what en garde *is*, and no fencer holds it any other
    way for more than an instant. So the limb nearer the opponent names the
    weapon side directly: if the anatomical *left* ankle is the forward one, the
    fencer is left-handed, whichever side of the frame they occupy.

    This replaces nothing. :func:`detect_handedness` infers the same thing from
    arm-extension asymmetry, which on real footage returned confidences of
    0.03-0.38 — a bent rear arm and an extended weapon arm differ by less than
    pose noise once the fencer turns. Limb *position* along the piste axis is a
    much larger quantity than limb *angle* difference, so it survives the same
    noise.

    Every frame with both fencers casts a weighted vote, and the bout-long
    majority wins. Per frame the vote is skipped when the geometry cannot
    support it: fencers overlapping in x (no forward direction), an unmeasurable
    body scale, low-confidence keypoints, or feet too close together to say
    which is in front.

    Args:
        pose_sequence: Full-bout pose frames.
        side: "left" or "right" fencer to analyze.
        min_frames: Frames that must contribute a vote before a call is made.
        min_keypoint_confidence: Both keypoints of a limb pair must reach this.
        min_separation_ratio: Limb separation, as a fraction of body scale,
            below which the frame cannot tell the two limbs apart.

    Returns:
        A :class:`HandednessVerdict`; ``handedness`` is None with 0.0 confidence
        when the evidence does not clear ``min_frames``.
    """
    opponent_side = "right" if side == "left" else "left"

    # limb -> [left tally, right tally, frames voted]
    tallies: Dict[str, List[float]] = {
        name: [0.0, 0.0, 0] for name, _, _, _ in _HANDEDNESS_LIMBS
    }
    frames_used = 0

    for pr in pose_sequence:
        fencer = get_fencer_by_side(pr, side)
        opponent = get_fencer_by_side(pr, opponent_side)
        if fencer is None or opponent is None:
            continue

        own_cx = _handedness_torso_centroid_x(fencer)
        opp_cx = _handedness_torso_centroid_x(opponent)
        if own_cx is None or opp_cx is None:
            continue
        if abs(opp_cx - own_cx) < _HANDEDNESS_MIN_CENTROID_GAP_PX:
            continue

        # +1 when the opponent lies at greater x, so multiplying by it turns
        # any x-difference into "how far toward the opponent".
        sign = 1.0 if opp_cx > own_cx else -1.0

        body_scale = _handedness_body_scale(fencer)
        if body_scale is None:
            continue

        kps = fencer.keypoints
        voted_this_frame = False

        for name, left_idx, right_idx, limb_weight in _HANDEDNESS_LIMBS:
            left_kp, right_kp = kps[left_idx], kps[right_idx]
            if (left_kp.confidence < min_keypoint_confidence
                    or right_kp.confidence < min_keypoint_confidence):
                continue

            d = (left_kp.x - right_kp.x) * sign
            separation = abs(d) / body_scale
            if separation < min_separation_ratio:
                # Feet square or hands together: no limb is leading.
                continue

            w = (
                min(left_kp.confidence, right_kp.confidence)
                * min(separation / min_separation_ratio, _HANDEDNESS_SEPARATION_CAP)
                * limb_weight
            )
            tally = tallies[name]
            # d > 0 means the anatomical left limb is the nearer one.
            tally[0 if d > 0 else 1] += w
            tally[2] += 1
            voted_this_frame = True

        if voted_this_frame:
            frames_used += 1

    per_limb: Dict[str, Tuple[Optional[str], float, int]] = {}
    left_total = 0.0
    right_total = 0.0
    for name, (limb_left, limb_right, limb_frames) in tallies.items():
        left_total += limb_left
        right_total += limb_right
        per_limb[name] = _handedness_call(limb_left, limb_right) + (limb_frames,)

    if frames_used < min_frames:
        return HandednessVerdict(
            handedness=None,
            confidence=0.0,
            frames_used=frames_used,
            left_weight=round(left_total, 3),
            right_weight=round(right_total, 3),
            per_limb=per_limb,
        )

    handedness, confidence = _handedness_call(left_total, right_total)
    return HandednessVerdict(
        handedness=handedness,
        confidence=confidence,
        frames_used=frames_used,
        left_weight=round(left_total, 3),
        right_weight=round(right_total, 3),
        per_limb=per_limb,
    )


def _handedness_call(
    left_total: float,
    right_total: float,
) -> Tuple[Optional[str], float]:
    """Winner and margin of a left/right vote tally.

    The margin is the share of the total weight the winner holds over the
    loser, so a unanimous bout reads 1.0 and an evenly split one reads 0.0
    regardless of how many frames went into it.
    """
    total = left_total + right_total
    if total <= 0.0:
        return (None, 0.0)
    confidence = round(abs(left_total - right_total) / total, 3)
    return ("left" if left_total > right_total else "right", confidence)


def compute_joint_kinematics(
    pose_sequence: List[PoseResult],
    side: str,
    sample_every_n: int = 1,
) -> List[FrameKinematics]:
    """Compute per-joint velocity and acceleration for a fencer.

    Velocity = displacement between consecutive frames in px/frame.
    Acceleration = velocity[i] - velocity[i-1] in px/frame².
    BH normalization: velocity_px / avg_body_height.

    Camera cuts (hip jump > threshold) are skipped.

    Args:
        pose_sequence: List of PoseResult frames.
        side: "left" or "right" fencer.
        sample_every_n: Analyze every N frames.

    Returns:
        List of FrameKinematics, one per analysed frame (first frame
        has zero velocity; first two frames have zero acceleration).
    """
    if not pose_sequence:
        return []

    # Sample frames
    sampled_indices = list(range(0, len(pose_sequence), sample_every_n))
    if not sampled_indices:
        return []

    # Compute average body height for BH normalization
    bh_values: List[float] = []
    for idx in sampled_indices:
        fencer = get_fencer_by_side(pose_sequence[idx], side)
        if fencer is not None:
            bh = compute_body_height(fencer)
            if bh is not None and bh > 0:
                bh_values.append(bh)
    avg_bh = sum(bh_values) / len(bh_values) if bh_values else 1.0

    results: List[FrameKinematics] = []
    prev_positions: Optional[dict] = None  # joint_name -> (x, y)
    prev_velocities: Optional[dict] = None  # joint_name -> velocity_px
    prev_hip_center: Optional[Tuple[float, float]] = None

    for si, idx in enumerate(sampled_indices):
        fencer = get_fencer_by_side(pose_sequence[idx], side)
        fk = FrameKinematics(frame_index=idx)

        if fencer is None or len(fencer.keypoints) < 17:
            # No data for this frame — reset state
            prev_positions = None
            prev_velocities = None
            prev_hip_center = None
            results.append(fk)
            continue

        # Camera cut detection via hip center jump
        curr_hip = compute_hip_center(fencer)
        is_camera_cut = False
        if prev_hip_center is not None and curr_hip is not None:
            dx = abs(curr_hip[0] - prev_hip_center[0])
            dy = abs(curr_hip[1] - prev_hip_center[1])
            if dx > CAMERA_CUT_HIP_JUMP_PX or dy > CAMERA_CUT_HIP_JUMP_PX:
                is_camera_cut = True

        # Extract current joint positions
        curr_positions: dict = {}
        for joint_name in KINEMATICS_TRACKED_JOINTS:
            kp_idx = KINEMATICS_JOINT_TO_KP[joint_name]
            kp = fencer.keypoints[kp_idx]
            if kp_valid(kp):
                curr_positions[joint_name] = (kp.x, kp.y)

        if is_camera_cut or prev_positions is None:
            # First frame or camera cut: velocity = 0
            for joint_name in KINEMATICS_TRACKED_JOINTS:
                fk.joints[joint_name] = JointKinematics(joint_name=joint_name)
            prev_positions = curr_positions
            prev_velocities = {j: 0.0 for j in KINEMATICS_TRACKED_JOINTS}
            prev_hip_center = curr_hip
            results.append(fk)
            continue

        # Compute velocities
        curr_velocities: dict = {}
        max_vel = 0.0
        dominant = ""

        for joint_name in KINEMATICS_TRACKED_JOINTS:
            vel_px = 0.0
            if joint_name in curr_positions and joint_name in prev_positions:
                px, py = curr_positions[joint_name]
                ppx, ppy = prev_positions[joint_name]
                vel_px = math.sqrt((px - ppx) ** 2 + (py - ppy) ** 2)

            vel_bh = vel_px / avg_bh if avg_bh > 0 else 0.0

            # Acceleration
            acc_px = 0.0
            if prev_velocities is not None and joint_name in prev_velocities:
                acc_px = vel_px - prev_velocities[joint_name]

            fk.joints[joint_name] = JointKinematics(
                joint_name=joint_name,
                velocity_px=vel_px,
                velocity_bh=vel_bh,
                acceleration_px=acc_px,
            )
            curr_velocities[joint_name] = vel_px

            if vel_px > max_vel:
                max_vel = vel_px
                dominant = joint_name

        fk.max_velocity_px = max_vel
        fk.dominant_joint = dominant

        prev_positions = curr_positions
        prev_velocities = curr_velocities
        prev_hip_center = curr_hip
        results.append(fk)

    return results
