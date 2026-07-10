"""Per-frame and per-sequence action-state classification (pure functions)."""

from typing import List, Optional

from analyzer.models import (
    PoseResult, FootworkType, FootworkResult,
    ActionState, FrameActionState, FrameKinematics,
)
from analyzer.config import FOOTWORK_MIN_DISPLACEMENT_PX
from ml.pose_analysis.geometry import distance_2d, get_fencer_by_side
from ml.pose_analysis.body_metrics import compute_hip_center, compute_distance_bh
from ml.pose_analysis.footwork import detect_footwork
from ml.pose_analysis.parry import detect_parry
from ml.pose_analysis.kinematics import compute_joint_kinematics
from ml.pose_analysis.camera import filter_camera_cuts


def classify_frame_action(
    prev_frame: PoseResult,
    curr_frame: PoseResult,
    side: str,
    footwork_window: int,
    parry_window: int,
    use_ratio_based_hip_drop: bool,
    kinematics: Optional[FrameKinematics] = None,
    window_frames: Optional[List[PoseResult]] = None,
) -> FrameActionState:
    """Classify the action state for a single frame transition.

    Uses joint kinematics, footwork patterns, and parry detection
    to determine the per-frame action state.

    Args:
        prev_frame: Previous PoseResult.
        curr_frame: Current PoseResult.
        side: "left" or "right" fencer.
        footwork_window: Trailing window for footwork detection.
        parry_window: Window for parry detection.
        use_ratio_based_hip_drop: Ratio-vs-absolute hip-drop toggle.
        kinematics: Pre-computed FrameKinematics (optional).
        window_frames: Consecutive frames ending at ``curr_frame`` used to
            feed footwork/parry detection.  ``detect_footwork`` and
            ``detect_parry`` need >= 3 frames to fire LUNGE/FLECHE/PARADE;
            when only the ``prev_frame``/``curr_frame`` pair is available
            (early in a sequence, or direct 2-frame callers), this defaults
            to that pair and the hip-direction/velocity fallbacks apply.

    Returns:
        FrameActionState for the current frame.
    """
    frame_idx = curr_frame.frame_idx
    fencer = get_fencer_by_side(curr_frame, side)
    prev_fencer = get_fencer_by_side(prev_frame, side)

    if fencer is None or prev_fencer is None:
        return FrameActionState(
            frame_index=frame_idx,
            state=ActionState.UNKNOWN,
        )

    # Get velocity from kinematics or compute it
    max_vel = 0.0
    if kinematics is not None:
        max_vel = kinematics.max_velocity_px
    else:
        # Rough estimate from hip displacement
        curr_hip = compute_hip_center(fencer)
        prev_hip = compute_hip_center(prev_fencer)
        if curr_hip is not None and prev_hip is not None:
            max_vel = distance_2d(curr_hip, prev_hip)

    # Compute distance between fencers (if opponent exists)
    opp_side = "right" if side == "left" else "left"
    opp = get_fencer_by_side(curr_frame, opp_side)
    dist_bh = None
    if opp is not None:
        dist_bh = compute_distance_bh(fencer, opp)

    # Feed footwork/parry detection with the trailing consecutive-frame
    # window when available; detect_footwork/detect_parry both require >= 3
    # frames, so a bare 2-frame pair can only ever yield UNKNOWN and leaves
    # LUNGE/FLECHE/PARADE unreachable.
    detection_seq = window_frames if window_frames is not None else [prev_frame, curr_frame]
    fw = detect_footwork(detection_seq, side, footwork_window, use_ratio_based_hip_drop)

    # Detect parry
    parry = detect_parry(detection_seq, side, parry_window)

    # If footwork returned UNKNOWN due to <3 frames, use hip direction fallback
    if fw is not None and fw.footwork_type == FootworkType.UNKNOWN and max_vel >= FOOTWORK_MIN_DISPLACEMENT_PX:
        curr_hip = compute_hip_center(fencer)
        prev_hip = compute_hip_center(prev_fencer)
        if curr_hip is not None and prev_hip is not None:
            # Positive direction = toward opponent for left fencer
            direction = 1.0 if side == "left" else -1.0
            hip_disp = (curr_hip[0] - prev_hip[0]) * direction
            if hip_disp > FOOTWORK_MIN_DISPLACEMENT_PX:
                fw = FootworkResult(
                    footwork_type=FootworkType.ADVANCE,
                    confidence=0.5,
                    front_foot_displacement_px=hip_disp,
                    rear_foot_displacement_px=hip_disp,
                )
            elif hip_disp < -FOOTWORK_MIN_DISPLACEMENT_PX:
                fw = FootworkResult(
                    footwork_type=FootworkType.RETREAT,
                    confidence=0.5,
                    front_foot_displacement_px=hip_disp,
                    rear_foot_displacement_px=hip_disp,
                )

    # Classification rules (threshold-based)
    state = ActionState.UNKNOWN
    confidence = 0.5

    # 1. PARADE: wrist lateral movement detected as parry
    if parry is not None and parry.parry_detected:
        state = ActionState.PARADE
        confidence = min(0.9, 0.5 + parry.confidence * 0.4)

    # 2. FENTE (lunge pattern)
    elif fw is not None and fw.footwork_type == FootworkType.LUNGE:
        state = ActionState.FENTE
        confidence = 0.8

    # 3. FLECHE (both feet fast advance)
    elif fw is not None and fw.footwork_type == FootworkType.FLECHE:
        state = ActionState.FLECHE
        confidence = 0.8

    # 4. MARCHE (advance)
    elif fw is not None and fw.footwork_type == FootworkType.ADVANCE:
        if max_vel < FOOTWORK_MIN_DISPLACEMENT_PX * 2:
            state = ActionState.PREPARATION
            confidence = 0.6
        else:
            state = ActionState.MARCHE
            confidence = 0.7

    # 5. RETRAITE (retreat)
    elif fw is not None and fw.footwork_type == FootworkType.RETREAT:
        state = ActionState.RETRAITE
        confidence = 0.7

    # 6. EN_GARDE (stationary, moderate distance)
    elif fw is not None and fw.footwork_type == FootworkType.STATIONARY:
        state = ActionState.EN_GARDE
        confidence = 0.7

    # 7. Velocity-based fallback
    elif max_vel < FOOTWORK_MIN_DISPLACEMENT_PX:
        state = ActionState.EN_GARDE
        confidence = 0.5
    else:
        state = ActionState.PREPARATION
        confidence = 0.4

    return FrameActionState(
        frame_index=frame_idx,
        state=state,
        confidence=confidence,
        velocity_max=max_vel,
        distance_bh=dist_bh,
    )


def classify_action_sequence(
    pose_sequence: List[PoseResult],
    side: str,
    footwork_window: int,
    parry_window: int,
    use_ratio_based_hip_drop: bool,
    sample_every_n: int = 1,
) -> List[FrameActionState]:
    """Classify action states for an entire sequence.

    Args:
        pose_sequence: List of PoseResult frames.
        side: "left" or "right" fencer.
        footwork_window: Trailing window for footwork detection.
        parry_window: Window for parry detection.
        use_ratio_based_hip_drop: Ratio-vs-absolute hip-drop toggle.
        sample_every_n: Analyze every N frames.

    Returns:
        List of FrameActionState, one per sampled frame.
    """
    if len(pose_sequence) < 2:
        return []

    # Compute kinematics for the whole sequence
    kin_list = compute_joint_kinematics(pose_sequence, side, sample_every_n)

    # Build a map of frame_index → FrameKinematics
    kin_map: dict = {}
    for fk in kin_list:
        kin_map[fk.frame_index] = fk

    # Camera cut detection
    clean_indices = set(filter_camera_cuts(pose_sequence))

    results: List[FrameActionState] = []
    sampled_indices = list(range(0, len(pose_sequence), sample_every_n))

    # Number of trailing consecutive frames to hand to footwork/parry
    # detection.  Both slice their own sub-window internally, so supply the
    # larger of the two so neither is starved.
    window_span = max(footwork_window, parry_window)

    for si, idx in enumerate(sampled_indices):
        if si == 0:
            # First frame — no previous, default to EN_GARDE
            results.append(FrameActionState(
                frame_index=pose_sequence[idx].frame_idx,
                state=ActionState.EN_GARDE,
                confidence=0.3,
            ))
            continue

        prev_idx = sampled_indices[si - 1]

        # Skip camera cuts
        if idx not in clean_indices:
            results.append(FrameActionState(
                frame_index=pose_sequence[idx].frame_idx,
                state=ActionState.UNKNOWN,
                confidence=0.0,
            ))
            continue

        kin = kin_map.get(idx)
        # Trailing consecutive frames ending at the current sample. Passing
        # the raw (un-sampled) slice keeps detect_footwork/detect_parry on the
        # consecutive frames they expect; when < 3 frames exist this stays a
        # 2-frame pair and the per-frame fallbacks take over.
        window_start = max(0, idx - window_span + 1)
        window_frames = pose_sequence[window_start:idx + 1]
        fas = classify_frame_action(
            pose_sequence[prev_idx],
            pose_sequence[idx],
            side,
            footwork_window,
            parry_window,
            use_ratio_based_hip_drop,
            kinematics=kin,
            window_frames=window_frames,
        )
        results.append(fas)

    return results
