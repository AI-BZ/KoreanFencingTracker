"""
Pose-based kinematic analyzer for fencing actions.

Analyzes YOLO11-Pose joint coordinates to detect:
- Footwork type (lunge, fleche, advance, retreat, stationary)
- Parry (blade-contact defense by non-scorer)
- Distance between fencers (in Body Height units)
- Suggested action label based on kinematic rules
- Joint angles (hip, knee, trunk lean, arm extension)
- Continuous analysis: exchange detection, non-scoring events
- My-fencer perspective narratives

No ML model required — pure geometric/kinematic calculations on keypoints.
"""

import math
from typing import List, Optional, Set, Tuple

from analyzer.models import (
    PoseResult, FencerPose, PoseKeypoint,
    FootworkType, DistanceZone, NonScoringEventType, ExchangePhase,
    FootworkResult, ParryResult, DistanceResult, PoseAnalysisResult,
    JointAngles, ExchangeEvent, MyFencerSummary, ContinuousAnalysisResult,
    JointKinematics, FrameKinematics,
    ActionState, FrameActionState,
)
from analyzer.config import (
    KP_LEFT_SHOULDER, KP_RIGHT_SHOULDER,
    KP_LEFT_ELBOW, KP_RIGHT_ELBOW,
    KP_LEFT_WRIST, KP_RIGHT_WRIST,
    KP_LEFT_HIP, KP_RIGHT_HIP,
    KP_LEFT_KNEE, KP_RIGHT_KNEE,
    KP_LEFT_ANKLE, KP_RIGHT_ANKLE,
    DISTANCE_ZONE_THRESHOLDS,
    DISTANCE_SMOOTHING_WINDOW,
    FOOTWORK_LUNGE_HIP_DROP_MIN,
    FOOTWORK_LUNGE_FRONT_FOOT_RATIO,
    FOOTWORK_FLECHE_BOTH_ADVANCE_MIN,
    FOOTWORK_MIN_DISPLACEMENT_PX,
    FOOTWORK_ANALYSIS_WINDOW,
    PARRY_WRIST_LATERAL_MIN_PX,
    PARRY_WRIST_SPEED_MIN_PX,
    PARRY_DETECTION_WINDOW,
    POSE_ANALYSIS_FPS,
    POSE_ANALYSIS_REMISE_WINDOW_SEC,
    POSE_KEYPOINT_CONFIDENCE,
    CAMERA_CUT_HIP_JUMP_PX,
    EXCHANGE_MIN_APPROACH_FRAMES,
    EXCHANGE_MIN_DISTANCE_CHANGE_BH,
    EXCHANGE_MERGE_SEPARATION_FRAMES,
    CONTINUOUS_SAMPLE_EVERY_N,
    CONTINUOUS_MAX_FRAMES,
    FOOTWORK_LUNGE_HIP_DROP_RATIO_MIN,
    FOOTWORK_FLECHE_BOTH_ADVANCE_MIN_TUNED,
    FOOTWORK_FLECHE_MAX_RATIO,
    FOOTWORK_USE_RATIO_BASED_HIP_DROP,
    KINEMATICS_TRACKED_JOINTS,
    KINEMATICS_JOINT_TO_KP,
    SCORING_FRAME_TOLERANCE_SEC,
)


def _kp_valid(kp: PoseKeypoint, min_conf: float = POSE_KEYPOINT_CONFIDENCE) -> bool:
    """Check if a keypoint has sufficient confidence."""
    return kp.confidence >= min_conf


def _midpoint(a: PoseKeypoint, b: PoseKeypoint) -> Tuple[float, float]:
    """Midpoint of two keypoints (x, y)."""
    return ((a.x + b.x) / 2, (a.y + b.y) / 2)


def _distance_2d(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """Euclidean distance between two 2D points."""
    return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)


class PoseAnalyzer:
    """
    Kinematic analyzer for fencing pose sequences.

    Analyzes joint trajectories to determine footwork, parry,
    distance, and suggest action labels.
    """

    def __init__(
        self,
        fps: float = POSE_ANALYSIS_FPS,
        footwork_window: int = FOOTWORK_ANALYSIS_WINDOW,
        parry_window: int = PARRY_DETECTION_WINDOW,
        smoothing_window: int = DISTANCE_SMOOTHING_WINDOW,
    ):
        self.fps = fps
        self.footwork_window = footwork_window
        self.parry_window = parry_window
        self.smoothing_window = smoothing_window

    # ------------------------------------------------------------------
    # Camera cut detection + touch moment finding
    # ------------------------------------------------------------------

    def filter_camera_cuts(
        self,
        pose_sequence: List[PoseResult],
    ) -> List[int]:
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
                prev_f = self._get_fencer_by_side(pose_sequence[i - 1], side)
                curr_f = self._get_fencer_by_side(pose_sequence[i], side)
                if prev_f is None or curr_f is None:
                    continue

                prev_hip = self.compute_hip_center(prev_f)
                curr_hip = self.compute_hip_center(curr_f)
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
        self,
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
            left = self._get_fencer_by_side(pr, "left")
            right = self._get_fencer_by_side(pr, "right")
            if left is None or right is None:
                continue

            d = self.compute_distance_bh(left, right)
            if d is not None and d < min_dist:
                min_dist = d
                touch_idx = i

        return touch_idx

    # ------------------------------------------------------------------
    # Body Height calculation
    # ------------------------------------------------------------------

    def compute_body_height(self, fencer: FencerPose) -> Optional[float]:
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

        if not (_kp_valid(l_sh) and _kp_valid(r_sh)):
            return None
        if not (_kp_valid(l_ank) and _kp_valid(r_ank)):
            return None

        shoulder_center = _midpoint(l_sh, r_sh)
        ankle_center = _midpoint(l_ank, r_ank)

        height = _distance_2d(shoulder_center, ankle_center)
        return height if height > 0 else None

    # ------------------------------------------------------------------
    # Hip center
    # ------------------------------------------------------------------

    def compute_hip_center(self, fencer: FencerPose) -> Optional[Tuple[float, float]]:
        """Compute hip center from left/right hip keypoints."""
        kps = fencer.keypoints
        if len(kps) < 17:
            return None

        l_hip, r_hip = kps[KP_LEFT_HIP], kps[KP_RIGHT_HIP]
        if not (_kp_valid(l_hip) and _kp_valid(r_hip)):
            return None

        return _midpoint(l_hip, r_hip)

    # ------------------------------------------------------------------
    # Distance (BH units)
    # ------------------------------------------------------------------

    def compute_distance_bh(
        self,
        fencer_a: FencerPose,
        fencer_b: FencerPose,
    ) -> Optional[float]:
        """
        Compute distance between two fencers in Body Height units.

        Uses X-axis distance between hip centers (side-view camera),
        normalized by average body height.
        """
        hip_a = self.compute_hip_center(fencer_a)
        hip_b = self.compute_hip_center(fencer_b)
        if hip_a is None or hip_b is None:
            return None

        bh_a = self.compute_body_height(fencer_a)
        bh_b = self.compute_body_height(fencer_b)
        if bh_a is None or bh_b is None:
            return None

        avg_bh = (bh_a + bh_b) / 2
        if avg_bh <= 0:
            return None

        # Side-view: use X-axis distance only
        x_distance = abs(hip_a[0] - hip_b[0])
        return x_distance / avg_bh

    def classify_distance_zone(self, distance_bh: float) -> DistanceZone:
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
        self,
        pose_sequence: List[PoseResult],
    ) -> List[Optional[float]]:
        """
        Compute distance BH for each frame in a pose sequence.

        Returns list of distances (None if not computable for that frame).
        """
        distances: List[Optional[float]] = []
        for pose_result in pose_sequence:
            left = self._get_fencer_by_side(pose_result, "left")
            right = self._get_fencer_by_side(pose_result, "right")
            if left is not None and right is not None:
                d = self.compute_distance_bh(left, right)
                distances.append(d)
            else:
                distances.append(None)
        return distances

    def smooth_distances(
        self,
        distances: List[Optional[float]],
    ) -> List[Optional[float]]:
        """Apply moving average smoothing to distance series."""
        n = len(distances)
        smoothed: List[Optional[float]] = []
        half_w = self.smoothing_window // 2

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
        self,
        distances: List[Optional[float]],
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

        time_diff = frame_diff / self.fps
        # Positive = closing (distance decreasing)
        return (first_d - last_d) / time_diff

    def analyze_distance(
        self,
        pose_sequence: List[PoseResult],
        touch_idx: Optional[int] = None,
    ) -> Optional[DistanceResult]:
        """
        Analyze distance between fencers at the touch moment.

        If touch_idx is provided, uses that frame's distance.
        Otherwise falls back to the last valid smoothed distance.

        Returns DistanceResult with smoothed distance, zone, and closing speed.
        """
        raw = self.compute_distance_series(pose_sequence)
        smoothed = self.smooth_distances(raw)

        # Get distance at touch moment
        touch_distance = None

        # Try touch_idx first
        if touch_idx is not None and 0 <= touch_idx < len(smoothed):
            touch_distance = smoothed[touch_idx]

        # Fallback: last valid value
        if touch_distance is None:
            for d in reversed(smoothed):
                if d is not None:
                    touch_distance = d
                    break

        if touch_distance is None:
            return None

        zone = self.classify_distance_zone(touch_distance)

        # Compute closing speed leading up to the touch
        if touch_idx is not None:
            # Use frames leading up to touch, not after
            speed_window = smoothed[:touch_idx + 1]
        else:
            speed_window = smoothed

        speed = self.compute_closing_speed(speed_window)

        return DistanceResult(
            distance_bh=touch_distance,
            distance_zone=zone,
            closing_speed_bh=speed,
        )

    # ------------------------------------------------------------------
    # Footwork detection
    # ------------------------------------------------------------------

    def detect_footwork(
        self,
        pose_sequence: List[PoseResult],
        side: str,
    ) -> FootworkResult:
        """
        Detect footwork type for a fencer over the analysis window.

        Args:
            pose_sequence: Pose frames (last frame = touch moment).
            side: "left" or "right" fencer.

        Returns:
            FootworkResult with type and confidence.
        """
        # Extract fencer poses for the analysis window
        window = pose_sequence[-self.footwork_window:]
        fencer_poses = []
        for pr in window:
            f = self._get_fencer_by_side(pr, side)
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

        if not all(_kp_valid(k) for k in [front_first, front_last, rear_first, rear_last]):
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
        hip_first = self.compute_hip_center(first)
        hip_last = self.compute_hip_center(last)
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
        if FOOTWORK_USE_RATIO_BASED_HIP_DROP:
            bh = self.compute_body_height(last)
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
            if FOOTWORK_USE_RATIO_BASED_HIP_DROP
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

    # ------------------------------------------------------------------
    # Parry detection
    # ------------------------------------------------------------------

    def detect_parry(
        self,
        pose_sequence: List[PoseResult],
        side: str,
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
            clean_indices: Frame indices without camera cuts.
            touch_idx: Frame index of touch moment.

        Returns:
            ParryResult with detection status and confidence.
        """
        # Determine the analysis window: frames before the touch
        end = touch_idx if touch_idx is not None else len(pose_sequence) - 1
        start = max(0, end - self.parry_window)

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
            fencer = self._get_fencer_by_side(pr, side)
            if fencer is None or len(fencer.keypoints) < 17:
                continue
            wrist = fencer.keypoints[wrist_idx]
            hip_center = self.compute_hip_center(fencer)
            if _kp_valid(wrist) and hip_center is not None:
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

    # ------------------------------------------------------------------
    # Label suggestion
    # ------------------------------------------------------------------

    def suggest_label(
        self,
        scorer: Optional[str],
        parry_left: ParryResult,
        parry_right: ParryResult,
        is_remise: bool = False,
        closing_speed_bh: float = 0.0,
    ) -> Tuple[Optional[str], float, str]:
        """
        Suggest an action label based on kinematic analysis.

        Rules:
        1. Non-scorer performed parry → scorer did RIPOSTE
        2. Same scorer within 2s → REMISE
        3. Both fencers fast approach → COUNTER_ATTACK possibility
        4. Default → ATTACK

        Args:
            scorer: "left" or "right" (who scored).
            parry_left: Parry result for left fencer.
            parry_right: Parry result for right fencer.
            is_remise: Whether this is a re-touch within 2s by same scorer.
            closing_speed_bh: Closing speed (BH/sec), high = both approaching.

        Returns:
            (label, confidence, reasoning) tuple.
        """
        if scorer is None:
            return (None, 0.0, "No scorer identified")

        direction = scorer  # scorer direction for label

        # Rule 1: Remise
        if is_remise:
            label = f"remise_{direction}"
            return (label, 0.8, f"Same scorer re-touch within {POSE_ANALYSIS_REMISE_WINDOW_SEC}s window")

        # Rule 2: Non-scorer parried → scorer's action is riposte
        non_scorer_parry = parry_right if scorer == "left" else parry_left
        if non_scorer_parry.parry_detected:
            label = f"riposte_{direction}"
            conf = min(0.9, non_scorer_parry.confidence * 0.9 + 0.1)
            return (
                label,
                conf,
                f"Non-scorer ({('right' if scorer == 'left' else 'left')}) parry detected "
                f"(wrist disp={non_scorer_parry.wrist_lateral_displacement_px:.0f}px) "
                f"→ scorer riposted",
            )

        # Rule 3: High closing speed → counter-attack possibility
        # Threshold: > 1.5 BH/sec means both fencers are rushing
        if closing_speed_bh > 1.5:
            label = f"counter_attack_{direction}"
            conf = min(0.7, 0.4 + (closing_speed_bh - 1.5) * 0.2)
            return (
                label,
                conf,
                f"High closing speed ({closing_speed_bh:.1f} BH/s) suggests counter-attack",
            )

        # Rule 4: Default → attack
        label = f"attack_{direction}"
        return (label, 0.6, "Default: no parry, no remise, normal speed → attack")

    # ------------------------------------------------------------------
    # Full analysis
    # ------------------------------------------------------------------

    def analyze(
        self,
        pose_sequence: List[PoseResult],
        scorer: Optional[str] = None,
        is_remise: bool = False,
        my_fencer: Optional[str] = None,
    ) -> PoseAnalysisResult:
        """
        Run full pose-based analysis on a touch event's pose sequence.

        For TV broadcast clips, applies camera cut filtering and finds the
        actual touch moment (minimum distance frame) instead of assuming
        the last frame is the touch.

        Args:
            pose_sequence: List of PoseResult frames around the touch event.
            scorer: "left" or "right" (who scored). None if unknown.
            is_remise: True if same scorer touched again within 2s.
            my_fencer: "left" or "right" — generate narrative from this
                fencer's perspective. None to skip.

        Returns:
            Complete PoseAnalysisResult.
        """
        if not pose_sequence:
            return PoseAnalysisResult()

        # Step 1: Detect camera cuts and find clean frames
        clean_indices = self.filter_camera_cuts(pose_sequence)

        # Step 2: Find touch moment (minimum distance frame among clean frames)
        touch_idx = self.find_touch_moment(pose_sequence, clean_indices)

        # Step 3: Use frames up to touch moment for analysis
        # (frames after the touch are post-action and shouldn't affect analysis)
        analysis_sequence = pose_sequence[:touch_idx + 1]

        # Distance analysis at the touch moment
        distance = self.analyze_distance(pose_sequence, touch_idx=touch_idx)

        # Footwork detection using frames before touch
        fw_left = self.detect_footwork(analysis_sequence, "left")
        fw_right = self.detect_footwork(analysis_sequence, "right")

        # Parry detection using clean frames before touch
        parry_left = self.detect_parry(
            pose_sequence, "left",
            clean_indices=clean_indices, touch_idx=touch_idx,
        )
        parry_right = self.detect_parry(
            pose_sequence, "right",
            clean_indices=clean_indices, touch_idx=touch_idx,
        )

        # Label suggestion
        closing_speed = distance.closing_speed_bh if distance else 0.0
        label, conf, reasoning = self.suggest_label(
            scorer=scorer,
            parry_left=parry_left,
            parry_right=parry_right,
            is_remise=is_remise,
            closing_speed_bh=closing_speed,
        )

        # Joint angles at touch moment
        touch_pr = pose_sequence[touch_idx]
        ja_left = self._compute_joint_angles_for_side(touch_pr, "left")
        ja_right = self._compute_joint_angles_for_side(touch_pr, "right")

        # My-fencer narrative
        narrative = ""
        if my_fencer in ("left", "right"):
            narrative = self._build_touch_narrative(
                my_fencer=my_fencer,
                scorer=scorer,
                label=label,
                distance=distance,
                fw_left=fw_left,
                fw_right=fw_right,
            )

        return PoseAnalysisResult(
            footwork_left=fw_left,
            footwork_right=fw_right,
            parry_left=parry_left,
            parry_right=parry_right,
            distance_at_touch=distance,
            suggested_label=label,
            suggestion_confidence=conf,
            suggestion_reasoning=reasoning,
            joint_angles_left=ja_left,
            joint_angles_right=ja_right,
            my_fencer_narrative=narrative,
        )

    # ------------------------------------------------------------------
    # Joint angle computation (Phase 6)
    # ------------------------------------------------------------------

    @staticmethod
    def _angle_between_points(
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

    @staticmethod
    def _angle_from_vertical(
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

    def compute_joint_angles(
        self,
        fencer: FencerPose,
        side: str,
    ) -> JointAngles:
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
        if _kp_valid(l_sh) and _kp_valid(r_sh):
            sh_center = _midpoint(l_sh, r_sh)
        if _kp_valid(l_hip) and _kp_valid(r_hip):
            hip_center = _midpoint(l_hip, r_hip)

        # Trunk lean: angle from vertical of shoulder_center → hip_center
        if sh_center is not None and hip_center is not None:
            result.trunk_lean_deg = self._angle_from_vertical(sh_center, hip_center)

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
        if sh_center is not None and hip_center is not None and _kp_valid(front_knee):
            result.hip_angle = self._angle_between_points(
                sh_center, hip_center, (front_knee.x, front_knee.y),
            )

        # Front knee angle: front_hip — front_knee — front_ankle
        front_hip_kp = kps[front_hip_idx]
        front_ankle_kp = kps[front_ankle_idx]
        if _kp_valid(front_hip_kp) and _kp_valid(front_knee) and _kp_valid(front_ankle_kp):
            result.front_knee_angle = self._angle_between_points(
                (front_hip_kp.x, front_hip_kp.y),
                (front_knee.x, front_knee.y),
                (front_ankle_kp.x, front_ankle_kp.y),
            )

        # Rear knee angle: rear_hip — rear_knee — rear_ankle
        rear_hip_kp = kps[rear_hip_idx]
        rear_knee_kp = kps[rear_knee_idx]
        rear_ankle_kp = kps[rear_ankle_idx]
        if _kp_valid(rear_hip_kp) and _kp_valid(rear_knee_kp) and _kp_valid(rear_ankle_kp):
            result.rear_knee_angle = self._angle_between_points(
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
        if _kp_valid(sh_kp) and _kp_valid(elb_kp) and _kp_valid(wr_kp):
            elbow_angle = self._angle_between_points(
                (sh_kp.x, sh_kp.y),
                (elb_kp.x, elb_kp.y),
                (wr_kp.x, wr_kp.y),
            )
            result.arm_extension_ratio = elbow_angle / 180.0

        return result

    def _compute_joint_angles_for_side(
        self,
        pose_result: PoseResult,
        side: str,
    ) -> Optional[JointAngles]:
        """Compute joint angles for a fencer from a single frame."""
        fencer = self._get_fencer_by_side(pose_result, side)
        if fencer is None:
            return None
        ja = self.compute_joint_angles(fencer, side)
        # Return None if nothing was computed
        if (ja.hip_angle is None and ja.front_knee_angle is None
                and ja.trunk_lean_deg is None and ja.arm_extension_ratio is None):
            return None
        return ja

    # ------------------------------------------------------------------
    # Handedness detection (arm extension asymmetry)
    # ------------------------------------------------------------------

    def detect_handedness(
        self,
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
            fencer = self._get_fencer_by_side(pr, side)
            if fencer is None or len(fencer.keypoints) < 17:
                continue

            # Left arm extension
            lsh = fencer.keypoints[KP_LEFT_SHOULDER]
            lel = fencer.keypoints[KP_LEFT_ELBOW]
            lwr = fencer.keypoints[KP_LEFT_WRIST]
            if _kp_valid(lsh) and _kp_valid(lel) and _kp_valid(lwr):
                angle = self._angle_between_points(
                    (lsh.x, lsh.y), (lel.x, lel.y), (lwr.x, lwr.y)
                )
                left_extensions.append(angle / 180.0)

            # Right arm extension
            rsh = fencer.keypoints[KP_RIGHT_SHOULDER]
            rel = fencer.keypoints[KP_RIGHT_ELBOW]
            rwr = fencer.keypoints[KP_RIGHT_WRIST]
            if _kp_valid(rsh) and _kp_valid(rel) and _kp_valid(rwr):
                angle = self._angle_between_points(
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
    # My-fencer narrative (Phase 6)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_touch_narrative(
        my_fencer: str,
        scorer: Optional[str],
        label: Optional[str],
        distance: Optional[DistanceResult],
        fw_left: FootworkResult,
        fw_right: FootworkResult,
    ) -> str:
        """Build a Korean narrative from my_fencer's perspective."""
        side_kr = "왼쪽" if my_fencer == "left" else "오른쪽"
        fw = fw_left if my_fencer == "left" else fw_right
        fw_name = fw.footwork_type.value if fw else "unknown"

        dist_str = ""
        if distance is not None:
            dist_str = f", 거리 {distance.distance_bh:.2f} BH"

        if scorer == my_fencer:
            action_name = "공격"
            if label and "riposte" in label:
                action_name = "리포스트"
            elif label and "counter_attack" in label:
                action_name = "콘트르아탁"
            elif label and "remise" in label:
                action_name = "르미즈"
            return f"내 선수({side_kr})가 {fw_name}으로 {action_name} 득점{dist_str}"
        elif scorer is not None:
            return f"내 선수({side_kr})가 실점 — 상대 득점{dist_str}"
        else:
            return f"내 선수({side_kr}) 분석{dist_str}"

    # ------------------------------------------------------------------
    # Joint kinematics (velocity / acceleration)
    # ------------------------------------------------------------------

    def compute_joint_kinematics(
        self,
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
            fencer = self._get_fencer_by_side(pose_sequence[idx], side)
            if fencer is not None:
                bh = self.compute_body_height(fencer)
                if bh is not None and bh > 0:
                    bh_values.append(bh)
        avg_bh = sum(bh_values) / len(bh_values) if bh_values else 1.0

        results: List[FrameKinematics] = []
        prev_positions: Optional[dict] = None  # joint_name -> (x, y)
        prev_velocities: Optional[dict] = None  # joint_name -> velocity_px
        prev_hip_center: Optional[Tuple[float, float]] = None

        for si, idx in enumerate(sampled_indices):
            fencer = self._get_fencer_by_side(pose_sequence[idx], side)
            fk = FrameKinematics(frame_index=idx)

            if fencer is None or len(fencer.keypoints) < 17:
                # No data for this frame — reset state
                prev_positions = None
                prev_velocities = None
                prev_hip_center = None
                results.append(fk)
                continue

            # Camera cut detection via hip center jump
            curr_hip = self.compute_hip_center(fencer)
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
                if _kp_valid(kp):
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

    # ------------------------------------------------------------------
    # Per-frame action state classification
    # ------------------------------------------------------------------

    def classify_frame_action(
        self,
        prev_frame: PoseResult,
        curr_frame: PoseResult,
        side: str,
        kinematics: Optional[FrameKinematics] = None,
    ) -> FrameActionState:
        """Classify the action state for a single frame transition.

        Uses joint kinematics, footwork patterns, and parry detection
        to determine the per-frame action state.

        Args:
            prev_frame: Previous PoseResult.
            curr_frame: Current PoseResult.
            side: "left" or "right" fencer.
            kinematics: Pre-computed FrameKinematics (optional).

        Returns:
            FrameActionState for the current frame.
        """
        frame_idx = curr_frame.frame_idx
        fencer = self._get_fencer_by_side(curr_frame, side)
        prev_fencer = self._get_fencer_by_side(prev_frame, side)

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
            curr_hip = self.compute_hip_center(fencer)
            prev_hip = self.compute_hip_center(prev_fencer)
            if curr_hip is not None and prev_hip is not None:
                max_vel = _distance_2d(curr_hip, prev_hip)

        # Compute distance between fencers (if opponent exists)
        opp_side = "right" if side == "left" else "left"
        opp = self._get_fencer_by_side(curr_frame, opp_side)
        dist_bh = None
        if opp is not None:
            dist_bh = self.compute_distance_bh(fencer, opp)

        # Detect footwork — use 2-frame pair if that's all we have
        sub_seq = [prev_frame, curr_frame]
        fw = self.detect_footwork(sub_seq, side)

        # Detect parry
        parry = self.detect_parry(sub_seq, side)

        # If footwork returned UNKNOWN due to <3 frames, use hip direction fallback
        if fw is not None and fw.footwork_type == FootworkType.UNKNOWN and max_vel >= FOOTWORK_MIN_DISPLACEMENT_PX:
            curr_hip = self.compute_hip_center(fencer)
            prev_hip = self.compute_hip_center(prev_fencer)
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
        self,
        pose_sequence: List[PoseResult],
        side: str,
        sample_every_n: int = 1,
    ) -> List[FrameActionState]:
        """Classify action states for an entire sequence.

        Args:
            pose_sequence: List of PoseResult frames.
            side: "left" or "right" fencer.
            sample_every_n: Analyze every N frames.

        Returns:
            List of FrameActionState, one per sampled frame.
        """
        if len(pose_sequence) < 2:
            return []

        # Compute kinematics for the whole sequence
        kin_list = self.compute_joint_kinematics(pose_sequence, side, sample_every_n)

        # Build a map of frame_index → FrameKinematics
        kin_map: dict = {}
        for fk in kin_list:
            kin_map[fk.frame_index] = fk

        # Camera cut detection
        clean_indices = set(self.filter_camera_cuts(pose_sequence))

        results: List[FrameActionState] = []
        sampled_indices = list(range(0, len(pose_sequence), sample_every_n))

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
            fas = self.classify_frame_action(
                pose_sequence[prev_idx],
                pose_sequence[idx],
                side,
                kinematics=kin,
            )
            results.append(fas)

        return results

    # ------------------------------------------------------------------
    # Continuous analysis (Phase 6)
    # ------------------------------------------------------------------

    def analyze_continuous(
        self,
        pose_sequence: List[PoseResult],
        sample_every_n: int = CONTINUOUS_SAMPLE_EVERY_N,
        my_fencer: Optional[str] = None,
        scoring_frames: Optional[Set[int]] = None,
        lamp_white_frames: Optional[Set[int]] = None,
    ) -> ContinuousAnalysisResult:
        """
        Analyze the full bout to detect exchanges (scoring and non-scoring).

        Args:
            pose_sequence: Full bout pose frames.
            sample_every_n: Analyze every N frames.
            my_fencer: "left" or "right" for perspective summary.
            scoring_frames: Set of frame indices where a point was scored.
            lamp_white_frames: Set of frame indices where white lamp was on.

        Returns:
            ContinuousAnalysisResult with exchange events.
        """
        if not pose_sequence:
            return ContinuousAnalysisResult()

        scoring_frames = scoring_frames or set()
        lamp_white_frames = lamp_white_frames or set()

        # Cap analysis length
        seq = pose_sequence[:CONTINUOUS_MAX_FRAMES]

        # Camera cut filtering
        clean_indices = self.filter_camera_cuts(seq)
        clean_set = set(clean_indices)

        # Compute sampled distance series
        sampled: List[Tuple[int, Optional[float]]] = []  # (frame_idx, distance_bh)
        for i in range(0, len(seq), sample_every_n):
            if i not in clean_set:
                continue
            pr = seq[i]
            left = self._get_fencer_by_side(pr, "left")
            right = self._get_fencer_by_side(pr, "right")
            if left is not None and right is not None:
                d = self.compute_distance_bh(left, right)
                sampled.append((i, d))
            else:
                sampled.append((i, None))

        # Detect exchanges from distance curve
        raw_exchanges = self._detect_exchanges(sampled)

        # Classify each exchange
        exchanges: List[ExchangeEvent] = []
        scoring_count = 0
        non_scoring_count = 0

        for (start_frame, end_frame, min_frame, min_dist) in raw_exchanges:
            # Build a sub-sequence for this exchange
            sub_start = max(0, start_frame)
            sub_end = min(len(seq), end_frame + 1)
            sub_seq = seq[sub_start:sub_end]

            # Check if any scoring frame falls within this exchange
            # Add tolerance for OCR delay (scoring changes appear 0.5-2sec after touch)
            scoring_tolerance = int(SCORING_FRAME_TOLERANCE_SEC * (self.fps / max(sample_every_n, 1)))
            exchange_scoring = any(
                start_frame - scoring_tolerance <= sf <= end_frame + scoring_tolerance
                for sf in scoring_frames
            )

            # Classify event type
            event_type = self._classify_exchange(
                sub_seq, exchange_scoring, start_frame, end_frame,
                lamp_white_frames,
            )

            # Footwork & parry for the exchange
            fw_l = self.detect_footwork(sub_seq, "left") if len(sub_seq) >= 3 else None
            fw_r = self.detect_footwork(sub_seq, "right") if len(sub_seq) >= 3 else None

            # Joint angles at min distance frame
            ja_l = None
            ja_r = None
            if 0 <= min_frame < len(seq):
                ja_l = self._compute_joint_angles_for_side(seq[min_frame], "left")
                ja_r = self._compute_joint_angles_for_side(seq[min_frame], "right")

            # Parry (simplified — use sub_seq)
            p_l = self.detect_parry(sub_seq, "left") if len(sub_seq) >= 3 else None
            p_r = self.detect_parry(sub_seq, "right") if len(sub_seq) >= 3 else None

            # Joint kinematics for the exchange
            kin_l = self.compute_joint_kinematics(sub_seq, "left") if len(sub_seq) >= 2 else None
            kin_r = self.compute_joint_kinematics(sub_seq, "right") if len(sub_seq) >= 2 else None
            # Only store if non-empty
            kin_l = kin_l if kin_l else None
            kin_r = kin_r if kin_r else None

            ex = ExchangeEvent(
                start_frame=start_frame,
                end_frame=end_frame,
                min_distance_frame=min_frame,
                min_distance_bh=min_dist,
                event_type=event_type,
                footwork_left=fw_l,
                footwork_right=fw_r,
                parry_left=p_l,
                parry_right=p_r,
                joint_angles_left=ja_l,
                joint_angles_right=ja_r,
                kinematics_left=kin_l,
                kinematics_right=kin_r,
            )
            exchanges.append(ex)

            if exchange_scoring:
                scoring_count += 1
            else:
                non_scoring_count += 1

        # Compute frame action states (for phrase boundary detection)
        frame_actions = None
        if len(seq) >= 2:
            frame_actions_left = self.classify_action_sequence(seq, "left", sample_every_n)
            frame_actions_right = self.classify_action_sequence(seq, "right", sample_every_n)
            if frame_actions_left or frame_actions_right:
                frame_actions = {}
                if frame_actions_left:
                    frame_actions["left"] = frame_actions_left
                if frame_actions_right:
                    frame_actions["right"] = frame_actions_right

        # Build my-fencer summary
        my_summary = None
        if my_fencer in ("left", "right"):
            my_summary = self._build_my_fencer_summary(exchanges, my_fencer, scoring_frames)

        return ContinuousAnalysisResult(
            exchanges=exchanges,
            total_exchanges=len(exchanges),
            scoring_exchanges=scoring_count,
            non_scoring_exchanges=non_scoring_count,
            my_fencer_summary=my_summary,
            frame_actions=frame_actions,
        )

    def _detect_exchanges(
        self,
        sampled: List[Tuple[int, Optional[float]]],
    ) -> List[Tuple[int, int, int, float]]:
        """
        State machine to detect exchanges from sampled distance series.

        Returns list of (start_frame, end_frame, min_distance_frame, min_distance_bh).
        """
        exchanges: List[Tuple[int, int, int, float]] = []
        state = "IDLE"
        approach_start = 0
        approach_count = 0
        min_dist = float("inf")
        min_dist_frame = 0
        start_dist = 0.0

        for i in range(len(sampled)):
            frame_idx, dist = sampled[i]
            if dist is None:
                continue

            if state == "IDLE":
                # Check if distance is decreasing
                if i > 0:
                    _, prev_dist = sampled[i - 1]
                    if prev_dist is not None and dist < prev_dist:
                        state = "APPROACH"
                        approach_start = frame_idx
                        approach_count = 1
                        start_dist = prev_dist
                        min_dist = dist
                        min_dist_frame = frame_idx

            elif state == "APPROACH":
                if dist <= min_dist:
                    min_dist = dist
                    min_dist_frame = frame_idx
                    approach_count += 1
                else:
                    # Distance started increasing → engagement → separation
                    if (approach_count >= EXCHANGE_MIN_APPROACH_FRAMES
                            and (start_dist - min_dist) >= EXCHANGE_MIN_DISTANCE_CHANGE_BH):
                        # Valid exchange
                        state = "SEPARATION"
                    else:
                        # Too short — reset
                        state = "IDLE"

            elif state == "SEPARATION":
                sep_frames = frame_idx - min_dist_frame
                if i > 0:
                    _, prev_dist = sampled[i - 1]
                    if prev_dist is not None and dist < prev_dist:
                        if sep_frames <= EXCHANGE_MERGE_SEPARATION_FRAMES:
                            # Short separation → merge into same exchange (back to APPROACH)
                            state = "APPROACH"
                            approach_count += 1
                            if dist <= min_dist:
                                min_dist = dist
                                min_dist_frame = frame_idx
                        else:
                            # Long separation → end current exchange, start new one
                            exchanges.append((approach_start, frame_idx, min_dist_frame, min_dist))
                            state = "APPROACH"
                            approach_start = frame_idx
                            approach_count = 1
                            start_dist = prev_dist if prev_dist is not None else dist
                            min_dist = dist
                            min_dist_frame = frame_idx
                    # else still separating
                    elif (dist - min_dist) > EXCHANGE_MIN_DISTANCE_CHANGE_BH:
                        # Sufficiently separated — exchange complete
                        exchanges.append((approach_start, frame_idx, min_dist_frame, min_dist))
                        state = "IDLE"

        # Handle unfinished exchange
        if state in ("APPROACH", "SEPARATION") and approach_count >= EXCHANGE_MIN_APPROACH_FRAMES:
            last_frame = sampled[-1][0] if sampled else 0
            if (start_dist - min_dist) >= EXCHANGE_MIN_DISTANCE_CHANGE_BH:
                exchanges.append((approach_start, last_frame, min_dist_frame, min_dist))

        return exchanges

    def _classify_exchange(
        self,
        sub_seq: List[PoseResult],
        is_scoring: bool,
        start_frame: int,
        end_frame: int,
        lamp_white_frames: Set[int],
    ) -> NonScoringEventType:
        """Classify an exchange as scoring or non-scoring event type."""
        if is_scoring:
            # Scoring exchanges use existing PoseAnalysisResult labels
            # Mark as UNKNOWN_EXCHANGE (the scoring label is in the touch analysis)
            return NonScoringEventType.UNKNOWN_EXCHANGE

        # Check for white lamp (off-target)
        if any(start_frame <= wf <= end_frame for wf in lamp_white_frames):
            return NonScoringEventType.OFF_TARGET

        # Check for parry in sub-sequence
        has_parry = False
        if len(sub_seq) >= 3:
            for s in ("left", "right"):
                pr = self.detect_parry(sub_seq, s)
                if pr.parry_detected:
                    has_parry = True
                    break

        # Check for mutual retreat: both fencers moving backward
        both_retreat = False
        if len(sub_seq) >= 3:
            fw_l = self.detect_footwork(sub_seq, "left")
            fw_r = self.detect_footwork(sub_seq, "right")
            both_retreat = (
                fw_l.footwork_type == FootworkType.RETREAT
                and fw_r.footwork_type == FootworkType.RETREAT
            )

        if both_retreat:
            return NonScoringEventType.MUTUAL_RETREAT
        if has_parry:
            return NonScoringEventType.SUCCESSFUL_DEFENSE
        # Default: approach then separation without scoring = failed attack
        return NonScoringEventType.FAILED_ATTACK

    def _build_my_fencer_summary(
        self,
        exchanges: List[ExchangeEvent],
        my_fencer: str,
        scoring_frames: Set[int],
    ) -> MyFencerSummary:
        """Build stats summary from my_fencer's perspective."""
        summary = MyFencerSummary(side=my_fencer)
        narratives: List[str] = []

        # Same tolerance as analyze_continuous for OCR delay
        scoring_tolerance = int(SCORING_FRAME_TOLERANCE_SEC * self.fps)

        for ex in exchanges:
            is_scoring = any(
                ex.start_frame - scoring_tolerance <= sf <= ex.end_frame + scoring_tolerance
                for sf in scoring_frames
            )

            # Determine if my fencer was attacking (approaching toward opponent)
            my_fw = ex.footwork_left if my_fencer == "left" else ex.footwork_right
            opp_fw = ex.footwork_right if my_fencer == "left" else ex.footwork_left

            my_attacking = (
                my_fw is not None
                and my_fw.footwork_type in (
                    FootworkType.LUNGE, FootworkType.FLECHE,
                    FootworkType.ADVANCE,
                )
            )
            opp_attacking = (
                opp_fw is not None
                and opp_fw.footwork_type in (
                    FootworkType.LUNGE, FootworkType.FLECHE,
                    FootworkType.ADVANCE,
                )
            )

            if my_attacking:
                summary.attacks_attempted += 1
                if is_scoring:
                    summary.attacks_succeeded += 1
                else:
                    summary.attacks_failed += 1
                    if ex.event_type == NonScoringEventType.FAILED_ATTACK:
                        narratives.append(
                            f"프레임 {ex.start_frame}-{ex.end_frame}: "
                            f"공격 실패 (거리 {ex.min_distance_bh:.2f} BH)"
                        )

            if opp_attacking and not my_attacking:
                summary.defenses_attempted += 1
                if ex.event_type == NonScoringEventType.SUCCESSFUL_DEFENSE:
                    summary.defenses_succeeded += 1
                    narratives.append(
                        f"프레임 {ex.start_frame}-{ex.end_frame}: "
                        f"방어 성공"
                    )

        # Compute rates
        if summary.attacks_attempted > 0:
            summary.attack_success_rate = summary.attacks_succeeded / summary.attacks_attempted
        if summary.defenses_attempted > 0:
            summary.defense_success_rate = summary.defenses_succeeded / summary.defenses_attempted

        summary.narratives = narratives
        return summary

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_fencer_by_side(
        pose_result: PoseResult,
        side: str,
    ) -> Optional[FencerPose]:
        """Get fencer with matching side from a PoseResult."""
        for f in pose_result.fencers:
            if f.side == side:
                return f
        return None
