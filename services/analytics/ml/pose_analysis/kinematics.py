"""Joint angles, per-joint velocity/acceleration, and handedness (pure functions)."""

import math
from typing import List, Optional, Tuple

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
