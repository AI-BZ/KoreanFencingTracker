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

PoseAnalyzer is a thin façade: the actual calculations live as stateless
functions in the ml/pose_analysis/ package (geometry, body_metrics, camera,
footwork, parry, kinematics, labeling, action_state, exchanges). The class
holds only configuration (fps, window sizes) and orchestrates the functions.
"""

from typing import List, Optional, Set, Tuple

from analyzer.models import (
    PoseResult, FencerPose,
    NonScoringEventType,
    DistanceResult, PoseAnalysisResult,
    JointAngles, ExchangeEvent, ContinuousAnalysisResult,
    FrameKinematics, FrameActionState,
)
from analyzer.config import (
    DISTANCE_SMOOTHING_WINDOW,
    FOOTWORK_ANALYSIS_WINDOW,
    PARRY_DETECTION_WINDOW,
    POSE_ANALYSIS_FPS,
    CONTINUOUS_SAMPLE_EVERY_N,
    CONTINUOUS_MAX_FRAMES,
    FOOTWORK_USE_RATIO_BASED_HIP_DROP,
    SCORING_FRAME_TOLERANCE_SEC,
)

# Pure-function modules (behavior-preserving extractions)
from ml.pose_analysis.geometry import (
    kp_valid as _kp_valid,
    midpoint as _midpoint,
    distance_2d as _distance_2d,
    get_fencer_by_side,
)
from ml.pose_analysis import body_metrics
from ml.pose_analysis import camera
from ml.pose_analysis import kinematics as kin
from ml.pose_analysis import exchanges as exch
from ml.pose_analysis.footwork import detect_footwork as _detect_footwork
from ml.pose_analysis.parry import detect_parry as _detect_parry
from ml.pose_analysis.labeling import suggest_label as _suggest_label
from ml.pose_analysis.labeling import build_touch_narrative as _build_touch_narrative
from ml.pose_analysis.action_state import (
    classify_frame_action as _classify_frame_action,
    classify_action_sequence as _classify_action_sequence,
)


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

    def filter_camera_cuts(self, pose_sequence: List[PoseResult]) -> List[int]:
        """Detect frames without a camera cut from the previous frame."""
        return camera.filter_camera_cuts(pose_sequence)

    def find_touch_moment(
        self,
        pose_sequence: List[PoseResult],
        clean_indices: Optional[List[int]] = None,
    ) -> int:
        """Find the frame index where fencers are closest (touch moment)."""
        return camera.find_touch_moment(pose_sequence, clean_indices)

    # ------------------------------------------------------------------
    # Body Height / hip center / distance
    # ------------------------------------------------------------------

    def compute_body_height(self, fencer: FencerPose) -> Optional[float]:
        """Body height in pixels: shoulder_center to ankle_center."""
        return body_metrics.compute_body_height(fencer)

    def compute_hip_center(self, fencer: FencerPose) -> Optional[Tuple[float, float]]:
        """Hip center from left/right hip keypoints."""
        return body_metrics.compute_hip_center(fencer)

    def compute_distance_bh(
        self,
        fencer_a: FencerPose,
        fencer_b: FencerPose,
    ) -> Optional[float]:
        """Distance between two fencers in Body Height units."""
        return body_metrics.compute_distance_bh(fencer_a, fencer_b)

    def classify_distance_zone(self, distance_bh: float):
        """Classify a BH distance into a DistanceZone."""
        return body_metrics.classify_distance_zone(distance_bh)

    def compute_distance_series(
        self,
        pose_sequence: List[PoseResult],
    ) -> List[Optional[float]]:
        """Distance BH per frame (None where not computable)."""
        return body_metrics.compute_distance_series(pose_sequence)

    def smooth_distances(
        self,
        distances: List[Optional[float]],
    ) -> List[Optional[float]]:
        """Moving-average smoothing of a distance series."""
        return body_metrics.smooth_distances(distances, self.smoothing_window)

    def compute_closing_speed(
        self,
        distances: List[Optional[float]],
    ) -> float:
        """Closing speed (BH/sec) from a distance series."""
        return body_metrics.compute_closing_speed(distances, self.fps)

    def analyze_distance(
        self,
        pose_sequence: List[PoseResult],
        touch_idx: Optional[int] = None,
    ) -> Optional[DistanceResult]:
        """
        Analyze distance between fencers at the touch moment.

        If touch_idx is provided, uses that frame's distance.
        Otherwise falls back to the last valid smoothed distance.
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
    # Footwork / parry detection
    # ------------------------------------------------------------------

    def detect_footwork(self, pose_sequence: List[PoseResult], side: str):
        """Detect footwork type for a fencer over the analysis window."""
        return _detect_footwork(
            pose_sequence, side,
            self.footwork_window,
            FOOTWORK_USE_RATIO_BASED_HIP_DROP,
        )

    def detect_parry(
        self,
        pose_sequence: List[PoseResult],
        side: str,
        clean_indices: Optional[List[int]] = None,
        touch_idx: Optional[int] = None,
    ):
        """Detect parry (blade deflection) in the frames before touch."""
        return _detect_parry(
            pose_sequence, side, self.parry_window,
            clean_indices=clean_indices, touch_idx=touch_idx,
        )

    # ------------------------------------------------------------------
    # Label suggestion
    # ------------------------------------------------------------------

    def suggest_label(
        self,
        scorer: Optional[str],
        parry_left,
        parry_right,
        is_remise: bool = False,
        closing_speed_bh: float = 0.0,
    ) -> Tuple[Optional[str], float, str]:
        """Suggest an action label based on kinematic analysis."""
        return _suggest_label(
            scorer, parry_left, parry_right,
            is_remise=is_remise, closing_speed_bh=closing_speed_bh,
        )

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
            narrative = _build_touch_narrative(
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
    # Joint angles / kinematics
    # ------------------------------------------------------------------

    def compute_joint_angles(self, fencer: FencerPose, side: str) -> JointAngles:
        """Compute 2D joint angles from COCO keypoints."""
        return kin.compute_joint_angles(fencer, side)

    def _compute_joint_angles_for_side(
        self,
        pose_result: PoseResult,
        side: str,
    ) -> Optional[JointAngles]:
        """Compute joint angles for a fencer from a single frame."""
        return kin.compute_joint_angles_for_side(pose_result, side)

    def detect_handedness(
        self,
        pose_sequence: List[PoseResult],
        side: str,
        min_frames: int = 30,
    ) -> Tuple[Optional[str], float]:
        """Detect fencer handedness by arm extension asymmetry."""
        return kin.detect_handedness(pose_sequence, side, min_frames=min_frames)

    def compute_joint_kinematics(
        self,
        pose_sequence: List[PoseResult],
        side: str,
        sample_every_n: int = 1,
    ) -> List[FrameKinematics]:
        """Compute per-joint velocity and acceleration for a fencer."""
        return kin.compute_joint_kinematics(pose_sequence, side, sample_every_n)

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
        """Classify the action state for a single frame transition."""
        return _classify_frame_action(
            prev_frame, curr_frame, side,
            self.footwork_window, self.parry_window,
            FOOTWORK_USE_RATIO_BASED_HIP_DROP,
            kinematics=kinematics,
        )

    def classify_action_sequence(
        self,
        pose_sequence: List[PoseResult],
        side: str,
        sample_every_n: int = 1,
    ) -> List[FrameActionState]:
        """Classify action states for an entire sequence."""
        return _classify_action_sequence(
            pose_sequence, side,
            self.footwork_window, self.parry_window,
            FOOTWORK_USE_RATIO_BASED_HIP_DROP,
            sample_every_n=sample_every_n,
        )

    # ------------------------------------------------------------------
    # Continuous analysis
    # ------------------------------------------------------------------

    def analyze_continuous(
        self,
        pose_sequence: List[PoseResult],
        sample_every_n: int = CONTINUOUS_SAMPLE_EVERY_N,
        my_fencer: Optional[str] = None,
        scoring_frames: Optional[Set[int]] = None,
        lamp_white_frames: Optional[Set[int]] = None,
    ) -> ContinuousAnalysisResult:
        """Analyze the full bout to detect exchanges (scoring and non-scoring)."""
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
            left = get_fencer_by_side(pr, "left")
            right = get_fencer_by_side(pr, "right")
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
        """State machine to detect exchanges from a sampled distance series."""
        return exch.detect_exchanges(sampled)

    def _classify_exchange(
        self,
        sub_seq: List[PoseResult],
        is_scoring: bool,
        start_frame: int,
        end_frame: int,
        lamp_white_frames: Set[int],
    ) -> NonScoringEventType:
        """Classify an exchange as scoring or non-scoring event type."""
        return exch.classify_exchange(
            sub_seq, is_scoring, start_frame, end_frame, lamp_white_frames,
            self.footwork_window, self.parry_window,
            FOOTWORK_USE_RATIO_BASED_HIP_DROP,
        )

    def _build_my_fencer_summary(
        self,
        exchanges: List[ExchangeEvent],
        my_fencer: str,
        scoring_frames: Set[int],
    ):
        """Build stats summary from my_fencer's perspective."""
        return exch.build_my_fencer_summary(
            exchanges, my_fencer, scoring_frames, self.fps,
        )

    # ------------------------------------------------------------------
    # Helpers (kept for backward-compatible access)
    # ------------------------------------------------------------------

    @staticmethod
    def _get_fencer_by_side(
        pose_result: PoseResult,
        side: str,
    ) -> Optional[FencerPose]:
        """Get fencer with matching side from a PoseResult."""
        return get_fencer_by_side(pose_result, side)
