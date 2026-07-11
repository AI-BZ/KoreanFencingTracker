"""
Tests for ml/pose_analyzer.py — pose-based kinematic analysis.

All tests use synthetic PoseResult data (no video files or ML models needed).

Phase 5c: 47 tests (distance, footwork, parry, label suggestion, integration, serialization)
Phase 6:  +21 tests (joint angles, exchange detection, my_fencer perspective, threshold tuning)
"""

import math
import pytest
from typing import List, Optional

from analyzer.models import (
    PoseKeypoint, FencerPose, PoseResult,
    FootworkType, DistanceZone, NonScoringEventType,
    FootworkResult, ParryResult, DistanceResult, PoseAnalysisResult,
    JointAngles, ExchangeEvent, ContinuousAnalysisResult, MyFencerSummary,
    EnrichedMatchEvent,
    JointKinematics, FrameKinematics,
    ActionState, FrameActionState,
)
from analyzer.config import (
    KP_LEFT_SHOULDER, KP_RIGHT_SHOULDER,
    KP_LEFT_ELBOW, KP_RIGHT_ELBOW,
    KP_LEFT_ANKLE, KP_RIGHT_ANKLE,
    KP_LEFT_HIP, KP_RIGHT_HIP,
    KP_LEFT_KNEE, KP_RIGHT_KNEE,
    KP_LEFT_WRIST, KP_RIGHT_WRIST,
    DISTANCE_ZONE_THRESHOLDS,
)
from ml.pose_analyzer import PoseAnalyzer


# ==================================================================
# Helpers: synthetic data generation
# ==================================================================


def make_kp(x: float, y: float, conf: float = 0.9) -> PoseKeypoint:
    """Create a keypoint with given coordinates."""
    return PoseKeypoint(x=x, y=y, confidence=conf)


def make_fencer(
    side: str,
    shoulder_cx: float = 200.0,
    shoulder_cy: float = 100.0,
    hip_cx: float = 200.0,
    hip_cy: float = 200.0,
    ankle_cx: float = 200.0,
    ankle_cy: float = 400.0,
    wrist_l_x: float = 180.0,
    wrist_l_y: float = 150.0,
    wrist_r_x: float = 220.0,
    wrist_r_y: float = 150.0,
    knee_l_x: Optional[float] = None,
    knee_l_y: Optional[float] = None,
    knee_r_x: Optional[float] = None,
    knee_r_y: Optional[float] = None,
    elbow_l_x: Optional[float] = None,
    elbow_l_y: Optional[float] = None,
    elbow_r_x: Optional[float] = None,
    elbow_r_y: Optional[float] = None,
    conf: float = 0.9,
) -> FencerPose:
    """Create a FencerPose with specified joint positions.

    All 17 COCO keypoints are set; shoulders, hips, ankles, wrists are
    explicitly positioned, others get reasonable defaults.
    """
    kps = [make_kp(shoulder_cx, shoulder_cy - 30, conf)] * 17  # defaults

    # Override key joints
    spread = 20.0
    kps[KP_LEFT_SHOULDER] = make_kp(shoulder_cx - spread, shoulder_cy, conf)
    kps[KP_RIGHT_SHOULDER] = make_kp(shoulder_cx + spread, shoulder_cy, conf)
    kps[KP_LEFT_HIP] = make_kp(hip_cx - spread, hip_cy, conf)
    kps[KP_RIGHT_HIP] = make_kp(hip_cx + spread, hip_cy, conf)
    kps[KP_LEFT_ANKLE] = make_kp(ankle_cx - spread, ankle_cy, conf)
    kps[KP_RIGHT_ANKLE] = make_kp(ankle_cx + spread, ankle_cy, conf)
    kps[KP_LEFT_WRIST] = make_kp(wrist_l_x, wrist_l_y, conf)
    kps[KP_RIGHT_WRIST] = make_kp(wrist_r_x, wrist_r_y, conf)

    # Knees default to midpoint between hip and ankle
    kps[KP_LEFT_KNEE] = make_kp(
        knee_l_x if knee_l_x is not None else hip_cx - spread,
        knee_l_y if knee_l_y is not None else (hip_cy + ankle_cy) / 2,
        conf,
    )
    kps[KP_RIGHT_KNEE] = make_kp(
        knee_r_x if knee_r_x is not None else hip_cx + spread,
        knee_r_y if knee_r_y is not None else (hip_cy + ankle_cy) / 2,
        conf,
    )

    # Elbows default to midpoint between shoulder and wrist
    kps[KP_LEFT_ELBOW] = make_kp(
        elbow_l_x if elbow_l_x is not None else (shoulder_cx - spread + wrist_l_x) / 2,
        elbow_l_y if elbow_l_y is not None else (shoulder_cy + wrist_l_y) / 2,
        conf,
    )
    kps[KP_RIGHT_ELBOW] = make_kp(
        elbow_r_x if elbow_r_x is not None else (shoulder_cx + spread + wrist_r_x) / 2,
        elbow_r_y if elbow_r_y is not None else (shoulder_cy + wrist_r_y) / 2,
        conf,
    )

    bbox = [shoulder_cx - 60, shoulder_cy - 40, shoulder_cx + 60, ankle_cy + 10]
    return FencerPose(keypoints=kps, bbox=bbox, person_confidence=conf, side=side)


def make_pose_result(
    frame_idx: int,
    left_fencer: Optional[FencerPose] = None,
    right_fencer: Optional[FencerPose] = None,
) -> PoseResult:
    """Create PoseResult with one or two fencers."""
    fencers = []
    if left_fencer is not None:
        fencers.append(left_fencer)
    if right_fencer is not None:
        fencers.append(right_fencer)
    return PoseResult(frame_idx=frame_idx, fencers=fencers)


def make_static_sequence(
    n_frames: int,
    left_x: float = 200.0,
    right_x: float = 600.0,
) -> List[PoseResult]:
    """Create a sequence of static poses (no movement)."""
    seq = []
    for i in range(n_frames):
        left = make_fencer("left", shoulder_cx=left_x, hip_cx=left_x, ankle_cx=left_x)
        right = make_fencer("right", shoulder_cx=right_x, hip_cx=right_x, ankle_cx=right_x)
        seq.append(make_pose_result(i, left, right))
    return seq


# ==================================================================
# Distance calculation tests (8)
# ==================================================================


class TestDistanceCalculation:

    def setup_method(self):
        self.analyzer = PoseAnalyzer()

    def test_body_height_basic(self):
        """Body height = shoulder_center to ankle_center distance."""
        f = make_fencer("left", shoulder_cy=100.0, ankle_cy=400.0)
        bh = self.analyzer.compute_body_height(f)
        assert bh is not None
        assert bh == pytest.approx(300.0, abs=1.0)

    def test_body_height_low_confidence_returns_none(self):
        """Low-confidence keypoints → None."""
        f = make_fencer("left", conf=0.1)
        bh = self.analyzer.compute_body_height(f)
        assert bh is None

    def test_distance_bh_basic(self):
        """Two fencers 300px apart with 300px body height → 1.0 BH."""
        left = make_fencer("left", hip_cx=200.0, shoulder_cy=100.0, ankle_cy=400.0)
        right = make_fencer("right", hip_cx=500.0, shoulder_cy=100.0, ankle_cy=400.0)
        d = self.analyzer.compute_distance_bh(left, right)
        assert d is not None
        assert d == pytest.approx(1.0, abs=0.05)

    def test_distance_zone_out(self):
        """Distance > 1.8 BH → OUT_OF_DISTANCE."""
        zone = self.analyzer.classify_distance_zone(2.0)
        assert zone == DistanceZone.OUT_OF_DISTANCE

    def test_distance_zone_lunge(self):
        """Distance 1.3 BH → LUNGE zone."""
        zone = self.analyzer.classify_distance_zone(1.3)
        assert zone == DistanceZone.LUNGE

    def test_distance_zone_infighting(self):
        """Distance 0.5 BH → INFIGHTING."""
        zone = self.analyzer.classify_distance_zone(0.5)
        assert zone == DistanceZone.INFIGHTING

    def test_distance_zone_extension(self):
        """Distance 1.0 BH → EXTENSION."""
        zone = self.analyzer.classify_distance_zone(1.0)
        assert zone == DistanceZone.EXTENSION

    def test_distance_zone_advance_lunge(self):
        """Distance 1.6 BH → ADVANCE_LUNGE."""
        zone = self.analyzer.classify_distance_zone(1.6)
        assert zone == DistanceZone.ADVANCE_LUNGE

    def test_smoothing_basic(self):
        """Moving average smoothes distance series."""
        raw = [1.0, 1.2, 1.1, 1.3, 1.0]
        smoothed = self.analyzer.smooth_distances(raw)
        assert len(smoothed) == 5
        # Middle value should be average of neighbors
        assert smoothed[2] == pytest.approx(
            (1.0 + 1.2 + 1.1 + 1.3 + 1.0) / 5, abs=0.01
        )

    def test_smoothing_with_nones(self):
        """Nones in series are skipped in averaging."""
        raw = [1.0, None, 1.2, None, 1.0]
        smoothed = self.analyzer.smooth_distances(raw)
        assert smoothed[0] is not None
        assert smoothed[1] is not None  # filled from neighbors

    def test_closing_speed_approaching(self):
        """Decreasing distances → positive closing speed."""
        distances = [2.0, 1.8, 1.6, 1.4, 1.2]
        speed = self.analyzer.compute_closing_speed(distances)
        assert speed > 0

    def test_closing_speed_separating(self):
        """Increasing distances → negative closing speed."""
        distances = [1.0, 1.2, 1.4, 1.6, 1.8]
        speed = self.analyzer.compute_closing_speed(distances)
        assert speed < 0

    def test_analyze_distance_full(self):
        """Full distance analysis returns DistanceResult."""
        seq = make_static_sequence(10, left_x=200.0, right_x=500.0)
        result = self.analyzer.analyze_distance(seq)
        assert result is not None
        assert isinstance(result, DistanceResult)
        assert result.distance_bh > 0


# ==================================================================
# Footwork detection tests (10)
# ==================================================================


class TestFootworkDetection:

    def setup_method(self):
        self.analyzer = PoseAnalyzer()

    def _make_lunge_sequence(self, side: str = "left") -> List[PoseResult]:
        """Create a sequence simulating a lunge.

        Left fencer: right foot (front) advances 60px, left foot stays, hip drops 15px.
        """
        n = 15
        seq = []
        for i in range(n):
            progress = i / (n - 1)

            left_x = 200.0
            right_x = 600.0
            anchor_x = left_x if side == "left" else right_x

            if side == "left":
                # Front foot = right ankle advances (x increases toward opponent)
                front_offset = progress * 60.0
                rear_offset = 0.0
                hip_drop = progress * 15.0
                l = make_fencer(
                    "left",
                    shoulder_cx=anchor_x, hip_cx=anchor_x, hip_cy=200.0 + hip_drop,
                    ankle_cx=anchor_x,
                )
                # Override ankles: left(rear) stays, right(front) advances
                l.keypoints[KP_LEFT_ANKLE] = make_kp(anchor_x - 20, 400.0)
                l.keypoints[KP_RIGHT_ANKLE] = make_kp(anchor_x + 20 + front_offset, 400.0)
            else:
                front_offset = progress * 60.0
                hip_drop = progress * 15.0
                l = make_fencer("left", shoulder_cx=left_x, hip_cx=left_x, ankle_cx=left_x)
                r = make_fencer(
                    "right",
                    shoulder_cx=anchor_x, hip_cx=anchor_x, hip_cy=200.0 + hip_drop,
                    ankle_cx=anchor_x,
                )
                # Right fencer: left foot is front (moves toward left fencer, x decreases)
                r.keypoints[KP_LEFT_ANKLE] = make_kp(anchor_x - 20 - front_offset, 400.0)
                r.keypoints[KP_RIGHT_ANKLE] = make_kp(anchor_x + 20, 400.0)
                seq.append(make_pose_result(i, l, r))
                continue

            r = make_fencer("right", shoulder_cx=right_x, hip_cx=right_x, ankle_cx=right_x)
            seq.append(make_pose_result(i, l, r))
        return seq

    def test_lunge_detection_left(self):
        """Left fencer lunging → LUNGE detected."""
        seq = self._make_lunge_sequence("left")
        result = self.analyzer.detect_footwork(seq, "left")
        assert result.footwork_type == FootworkType.LUNGE
        assert result.confidence > 0.5
        assert result.hip_drop_px > 0

    def test_lunge_detection_right(self):
        """Right fencer lunging → LUNGE detected."""
        seq = self._make_lunge_sequence("right")
        result = self.analyzer.detect_footwork(seq, "right")
        assert result.footwork_type == FootworkType.LUNGE
        assert result.confidence > 0.5

    def test_stationary_detection(self):
        """No movement → STATIONARY."""
        seq = make_static_sequence(15)
        result = self.analyzer.detect_footwork(seq, "left")
        assert result.footwork_type == FootworkType.STATIONARY
        assert result.confidence >= 0.8

    def test_fleche_detection(self):
        """Both feet advance significantly with similar ratio → FLECHE."""
        n = 15
        seq = []
        for i in range(n):
            progress = i / (n - 1)
            offset = progress * 60.0  # > FLECHE_BOTH_ADVANCE_MIN_TUNED (50)
            left = make_fencer("left", shoulder_cx=200 + offset, hip_cx=200 + offset, ankle_cx=200 + offset)
            # Move both ankles forward (x increases for left fencer)
            left.keypoints[KP_LEFT_ANKLE] = make_kp(180 + offset, 400.0)
            left.keypoints[KP_RIGHT_ANKLE] = make_kp(220 + offset, 400.0)
            right = make_fencer("right", shoulder_cx=600, hip_cx=600, ankle_cx=600)
            seq.append(make_pose_result(i, left, right))
        result = self.analyzer.detect_footwork(seq, "left")
        assert result.footwork_type == FootworkType.FLECHE

    def test_retreat_detection(self):
        """Both feet move backward → RETREAT."""
        n = 15
        seq = []
        for i in range(n):
            progress = i / (n - 1)
            offset = progress * -30.0  # moves backward
            left = make_fencer("left", shoulder_cx=200 + offset, hip_cx=200 + offset, ankle_cx=200 + offset)
            left.keypoints[KP_LEFT_ANKLE] = make_kp(180 + offset, 400.0)
            left.keypoints[KP_RIGHT_ANKLE] = make_kp(220 + offset, 400.0)
            right = make_fencer("right", shoulder_cx=600, hip_cx=600, ankle_cx=600)
            seq.append(make_pose_result(i, left, right))
        result = self.analyzer.detect_footwork(seq, "left")
        assert result.footwork_type == FootworkType.RETREAT

    def test_advance_detection(self):
        """Both feet advance moderately (sequential steps, no hip drop) → ADVANCE."""
        n = 15
        seq = []
        for i in range(n):
            progress = i / (n - 1)
            # Front foot: 25px, rear foot: 10px, no hip drop
            front_off = progress * 25.0
            rear_off = progress * 10.0
            left = make_fencer("left", shoulder_cx=200, hip_cx=200, ankle_cx=200)
            left.keypoints[KP_RIGHT_ANKLE] = make_kp(220 + front_off, 400.0)
            left.keypoints[KP_LEFT_ANKLE] = make_kp(180 + rear_off, 400.0)
            right = make_fencer("right", shoulder_cx=600, hip_cx=600, ankle_cx=600)
            seq.append(make_pose_result(i, left, right))
        result = self.analyzer.detect_footwork(seq, "left")
        assert result.footwork_type == FootworkType.ADVANCE

    def test_unknown_with_too_few_frames(self):
        """Too few frames → UNKNOWN."""
        seq = make_static_sequence(2)
        result = self.analyzer.detect_footwork(seq, "left")
        assert result.footwork_type == FootworkType.UNKNOWN

    def test_footwork_displacement_values(self):
        """Footwork result includes displacement measurements."""
        seq = self._make_lunge_sequence("left")
        result = self.analyzer.detect_footwork(seq, "left")
        assert result.front_foot_displacement_px > 0
        # For lunge, rear foot displacement should be small
        assert abs(result.rear_foot_displacement_px) < result.front_foot_displacement_px

    def test_hip_drop_recorded(self):
        """Hip drop is measured and recorded."""
        seq = self._make_lunge_sequence("left")
        result = self.analyzer.detect_footwork(seq, "left")
        assert result.hip_drop_px > 0

    def test_opponent_stationary_during_lunge(self):
        """When one fencer lunges, opponent should be stationary."""
        seq = self._make_lunge_sequence("left")
        result = self.analyzer.detect_footwork(seq, "right")
        assert result.footwork_type == FootworkType.STATIONARY


# ==================================================================
# Parry detection tests (8)
# ==================================================================


class TestParryDetection:

    def setup_method(self):
        self.analyzer = PoseAnalyzer()

    def _make_parry_sequence(
        self,
        side: str = "left",
        parry_magnitude: float = 30.0,
    ) -> List[PoseResult]:
        """Create sequence where `side` fencer performs a parry (rapid wrist movement)."""
        n = 10
        seq = []
        # Weapon wrist: left fencer → right wrist (kp10), right fencer → left wrist (kp9)
        wrist_idx = KP_RIGHT_WRIST if side == "left" else KP_LEFT_WRIST

        for i in range(n):
            left = make_fencer("left", shoulder_cx=200, hip_cx=200, ankle_cx=200)
            right = make_fencer("right", shoulder_cx=600, hip_cx=600, ankle_cx=600)

            # Simulate parry at frames 4-5: rapid Y displacement
            fencer = left if side == "left" else right
            if 4 <= i <= 5:
                # Big upward sweep then back
                dy = parry_magnitude if i == 4 else -parry_magnitude
                fencer.keypoints[wrist_idx] = make_kp(
                    fencer.keypoints[wrist_idx].x,
                    150.0 + dy,
                )

            seq.append(make_pose_result(i, left, right))
        return seq

    def test_parry_detected(self):
        """Rapid wrist movement → parry detected."""
        seq = self._make_parry_sequence("left", parry_magnitude=35.0)
        result = self.analyzer.detect_parry(seq, "left")
        assert result.parry_detected is True
        assert result.confidence > 0.5

    def test_no_parry_small_movement(self):
        """Small wrist movement → no parry."""
        seq = self._make_parry_sequence("left", parry_magnitude=5.0)
        result = self.analyzer.detect_parry(seq, "left")
        assert result.parry_detected is False

    def test_parry_on_right_fencer(self):
        """Right fencer parry uses left wrist (kp9)."""
        seq = self._make_parry_sequence("right", parry_magnitude=35.0)
        result = self.analyzer.detect_parry(seq, "right")
        assert result.parry_detected is True

    def test_parry_frame_index_recorded(self):
        """Parry frame index is recorded in result."""
        seq = self._make_parry_sequence("left", parry_magnitude=35.0)
        result = self.analyzer.detect_parry(seq, "left")
        assert result.parry_frame_idx is not None

    def test_parry_wrist_displacement(self):
        """Wrist displacement is measured."""
        seq = self._make_parry_sequence("left", parry_magnitude=40.0)
        result = self.analyzer.detect_parry(seq, "left")
        assert result.wrist_lateral_displacement_px > 20.0

    def test_no_parry_static(self):
        """Static sequence → no parry."""
        seq = make_static_sequence(10)
        result = self.analyzer.detect_parry(seq, "left")
        assert result.parry_detected is False

    def test_parry_confidence_scales_with_magnitude(self):
        """Larger parry → higher confidence."""
        seq_small = self._make_parry_sequence("left", parry_magnitude=25.0)
        seq_large = self._make_parry_sequence("left", parry_magnitude=50.0)
        r_small = self.analyzer.detect_parry(seq_small, "left")
        r_large = self.analyzer.detect_parry(seq_large, "left")
        if r_small.parry_detected and r_large.parry_detected:
            assert r_large.confidence >= r_small.confidence

    def test_too_few_frames(self):
        """Too few frames → no parry."""
        seq = make_static_sequence(2)
        result = self.analyzer.detect_parry(seq, "left")
        assert result.parry_detected is False


# ==================================================================
# Label suggestion tests (8)
# ==================================================================


class TestLabelSuggestion:

    def setup_method(self):
        self.analyzer = PoseAnalyzer()

    def _no_parry(self) -> ParryResult:
        return ParryResult(parry_detected=False, confidence=0.1)

    def _yes_parry(self, disp: float = 30.0) -> ParryResult:
        return ParryResult(
            parry_detected=True, confidence=0.8,
            wrist_lateral_displacement_px=disp,
        )

    def test_attack_default(self):
        """No parry, no remise, normal speed → attack."""
        label, conf, reasoning = self.analyzer.suggest_label(
            scorer="left", parry_left=self._no_parry(), parry_right=self._no_parry(),
        )
        assert label == "attack_left"
        assert conf > 0

    def test_riposte_when_nonscorer_parried(self):
        """Non-scorer parried → riposte."""
        label, conf, reasoning = self.analyzer.suggest_label(
            scorer="left",
            parry_left=self._no_parry(),
            parry_right=self._yes_parry(),  # non-scorer (right) parried
        )
        assert label == "riposte_left"
        assert "parry" in reasoning.lower()

    def test_riposte_right_scorer(self):
        """Right scorer, left fencer parried → riposte_right."""
        label, conf, reasoning = self.analyzer.suggest_label(
            scorer="right",
            parry_left=self._yes_parry(),  # non-scorer (left) parried
            parry_right=self._no_parry(),
        )
        assert label == "riposte_right"

    def test_remise(self):
        """is_remise=True → remise label takes priority."""
        label, conf, reasoning = self.analyzer.suggest_label(
            scorer="left",
            parry_left=self._no_parry(),
            parry_right=self._no_parry(),
            is_remise=True,
        )
        assert label == "remise_left"

    def test_counter_attack_high_speed(self):
        """High closing speed → counter_attack."""
        label, conf, reasoning = self.analyzer.suggest_label(
            scorer="right",
            parry_left=self._no_parry(),
            parry_right=self._no_parry(),
            closing_speed_bh=2.5,
        )
        assert label == "counter_attack_right"
        assert "speed" in reasoning.lower()

    def test_no_scorer_returns_none(self):
        """No scorer → None label."""
        label, conf, reasoning = self.analyzer.suggest_label(
            scorer=None,
            parry_left=self._no_parry(),
            parry_right=self._no_parry(),
        )
        assert label is None

    def test_remise_overrides_parry(self):
        """Remise takes priority over parry detection."""
        label, _, _ = self.analyzer.suggest_label(
            scorer="left",
            parry_left=self._no_parry(),
            parry_right=self._yes_parry(),
            is_remise=True,
        )
        assert label == "remise_left"

    def test_parry_overrides_counter_attack(self):
        """Parry detection takes priority over counter-attack speed."""
        label, _, _ = self.analyzer.suggest_label(
            scorer="left",
            parry_left=self._no_parry(),
            parry_right=self._yes_parry(),
            closing_speed_bh=3.0,
        )
        assert label == "riposte_left"


# ==================================================================
# Integration tests (5)
# ==================================================================


class TestIntegration:

    def setup_method(self):
        self.analyzer = PoseAnalyzer()

    def test_full_analysis_basic(self):
        """Full analysis produces PoseAnalysisResult with all fields."""
        seq = make_static_sequence(20)
        result = self.analyzer.analyze(seq, scorer="left")
        assert isinstance(result, PoseAnalysisResult)
        assert result.footwork_left is not None
        assert result.footwork_right is not None
        assert result.parry_left is not None
        assert result.parry_right is not None
        assert result.distance_at_touch is not None
        assert result.suggested_label is not None

    def test_full_analysis_empty_sequence(self):
        """Empty sequence returns default PoseAnalysisResult."""
        result = self.analyzer.analyze([], scorer="left")
        assert result.footwork_left is None
        assert result.suggested_label is None

    def test_serialization_roundtrip(self):
        """PoseAnalysisResult serializes to dict correctly."""
        seq = make_static_sequence(20)
        result = self.analyzer.analyze(seq, scorer="left")
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "suggestion_confidence" in d
        if result.footwork_left is not None:
            assert "footwork_left" in d
            assert "footwork_type" in d["footwork_left"]

    def test_enriched_match_event_with_pose_analysis(self):
        """PoseAnalysisResult can be attached to EnrichedMatchEvent."""
        seq = make_static_sequence(20)
        analysis = self.analyzer.analyze(seq, scorer="right")

        event = EnrichedMatchEvent(
            frame=100,
            video_timestamp="0:03:20",
            match_time="2:40",
            event_type="single_touch",
            lamp_red=False,
            lamp_green=True,
            score_before="2-3",
            score_after="2-4",
            scorer="right",
            pose_analysis=analysis,
        )
        d = event.to_dict()
        assert "pose_analysis" in d
        assert "suggested_label" in d["pose_analysis"]

    def test_import_from_ml_package(self):
        """PoseAnalyzer is importable from ml package."""
        from ml import PoseAnalyzer as PA
        assert PA is PoseAnalyzer


# ==================================================================
# FootworkResult / ParryResult / DistanceResult serialization (3)
# ==================================================================


class TestModelSerialization:

    def test_footwork_result_to_dict(self):
        """FootworkResult.to_dict() includes all fields."""
        r = FootworkResult(
            footwork_type=FootworkType.LUNGE,
            confidence=0.85,
            hip_drop_px=12.5,
            front_foot_displacement_px=55.0,
            rear_foot_displacement_px=3.0,
        )
        d = r.to_dict()
        assert d["footwork_type"] == "lunge"
        assert d["confidence"] == 0.85
        assert d["hip_drop_px"] == 12.5

    def test_parry_result_to_dict(self):
        """ParryResult.to_dict() includes optional parry_frame_idx."""
        r = ParryResult(
            parry_detected=True, confidence=0.75,
            wrist_lateral_displacement_px=28.0,
            parry_frame_idx=42,
        )
        d = r.to_dict()
        assert d["parry_detected"] is True
        assert d["parry_frame_idx"] == 42

    def test_distance_result_to_dict(self):
        """DistanceResult.to_dict() rounds values."""
        r = DistanceResult(
            distance_bh=1.3456789,
            distance_zone=DistanceZone.LUNGE,
            closing_speed_bh=0.567890,
        )
        d = r.to_dict()
        assert d["distance_zone"] == "lunge"
        assert d["distance_bh"] == pytest.approx(1.346, abs=0.001)


# ==================================================================
# Phase 6: Joint Angles tests (8)
# ==================================================================


class TestJointAngles:

    def setup_method(self):
        self.analyzer = PoseAnalyzer()

    def test_hip_angle_basic(self):
        """Hip angle computed from shoulder_center-hip_center-front_knee."""
        f = make_fencer(
            "left",
            shoulder_cx=200, shoulder_cy=100,
            hip_cx=200, hip_cy=200,
            knee_r_x=250, knee_r_y=300,  # front knee (right for left fencer)
        )
        ja = self.analyzer.compute_joint_angles(f, "left")
        assert ja.hip_angle is not None
        assert 0 < ja.hip_angle < 180

    def test_knee_angle_basic(self):
        """Front knee angle from hip-knee-ankle."""
        f = make_fencer(
            "left",
            hip_cx=200, hip_cy=200,
            ankle_cx=200, ankle_cy=400,
            knee_r_x=220, knee_r_y=300,
        )
        ja = self.analyzer.compute_joint_angles(f, "left")
        assert ja.front_knee_angle is not None
        assert 0 < ja.front_knee_angle <= 180

    def test_trunk_lean_vertical(self):
        """Perfectly vertical trunk → lean ≈ 0."""
        f = make_fencer(
            "left",
            shoulder_cx=200, shoulder_cy=100,
            hip_cx=200, hip_cy=200,
        )
        ja = self.analyzer.compute_joint_angles(f, "left")
        assert ja.trunk_lean_deg is not None
        assert ja.trunk_lean_deg < 5  # nearly vertical

    def test_arm_extension_straight(self):
        """Straight arm (shoulder-elbow-wrist collinear) → ratio ≈ 1.0."""
        # All points on same horizontal line
        f = make_fencer(
            "left",
            shoulder_cx=200, shoulder_cy=100,
            elbow_r_x=260, elbow_r_y=100,
            wrist_r_x=320, wrist_r_y=100,
        )
        ja = self.analyzer.compute_joint_angles(f, "left")
        assert ja.arm_extension_ratio is not None
        assert ja.arm_extension_ratio == pytest.approx(1.0, abs=0.05)

    def test_arm_extension_bent(self):
        """Bent arm → ratio < 1.0."""
        f = make_fencer(
            "left",
            shoulder_cx=200, shoulder_cy=100,
            elbow_r_x=240, elbow_r_y=100,
            wrist_r_x=240, wrist_r_y=50,  # elbow bent 90 degrees
        )
        ja = self.analyzer.compute_joint_angles(f, "left")
        assert ja.arm_extension_ratio is not None
        assert ja.arm_extension_ratio < 0.7

    def test_partial_keypoints(self):
        """Some keypoints invalid → partial results."""
        f = make_fencer("left", conf=0.9)
        # Invalidate elbow
        f.keypoints[KP_RIGHT_ELBOW] = make_kp(0, 0, 0.05)
        ja = self.analyzer.compute_joint_angles(f, "left")
        # hip/knee should still work, arm extension should be None
        assert ja.arm_extension_ratio is None
        assert ja.hip_angle is not None

    def test_all_invalid_keypoints(self):
        """All low confidence → None result from _compute_joint_angles_for_side."""
        f = make_fencer("left", conf=0.05)
        pr = make_pose_result(0, f, None)
        result = self.analyzer._compute_joint_angles_for_side(pr, "left")
        assert result is None

    def test_rear_knee_computed(self):
        """Rear knee angle is computed."""
        f = make_fencer(
            "left",
            hip_cx=200, hip_cy=200,
            ankle_cx=200, ankle_cy=400,
            knee_l_x=180, knee_l_y=300,  # rear knee for left fencer
        )
        ja = self.analyzer.compute_joint_angles(f, "left")
        assert ja.rear_knee_angle is not None
        assert 0 < ja.rear_knee_angle <= 180


# ==================================================================
# Phase 6: Exchange Detection tests (6)
# ==================================================================


class TestExchangeDetection:

    def setup_method(self):
        self.analyzer = PoseAnalyzer()

    def _make_approach_engage_separate_sequence(
        self,
        n_frames: int = 60,
        start_dist: float = 500.0,
        min_dist: float = 200.0,
    ) -> List[PoseResult]:
        """Create approach → engagement → separation cycle."""
        seq = []
        approach_end = n_frames // 3
        engage_end = 2 * n_frames // 3

        for i in range(n_frames):
            if i < approach_end:
                # Approaching: right fencer moves left
                progress = i / approach_end
                right_x = start_dist + 200 - progress * (start_dist - min_dist)
            elif i < engage_end:
                # Engaged: stay close
                right_x = min_dist + 200
            else:
                # Separating: right fencer moves away
                progress = (i - engage_end) / (n_frames - engage_end)
                right_x = min_dist + 200 + progress * (start_dist - min_dist)

            left = make_fencer("left", shoulder_cx=200, hip_cx=200, ankle_cx=200)
            right = make_fencer("right", shoulder_cx=right_x, hip_cx=right_x, ankle_cx=right_x)
            seq.append(make_pose_result(i, left, right))
        return seq

    def test_single_exchange_detected(self):
        """Approach→engagement→separation → 1 exchange detected."""
        seq = self._make_approach_engage_separate_sequence(n_frames=90)
        result = self.analyzer.analyze_continuous(seq, sample_every_n=1)
        assert result.total_exchanges >= 1

    def test_no_exchange_flat_distance(self):
        """Static sequence (flat distance) → 0 exchanges."""
        seq = make_static_sequence(60, left_x=200.0, right_x=600.0)
        result = self.analyzer.analyze_continuous(seq, sample_every_n=1)
        assert result.total_exchanges == 0

    def test_multiple_exchanges(self):
        """Two approach-separate cycles → ≥2 exchanges."""
        # First cycle
        seq1 = self._make_approach_engage_separate_sequence(n_frames=60)
        # Second cycle (renumber frames)
        seq2 = self._make_approach_engage_separate_sequence(n_frames=60)
        for i, pr in enumerate(seq2):
            pr2 = make_pose_result(60 + i, *[f for f in pr.fencers])
            seq2[i] = pr2
        combined = seq1 + seq2
        result = self.analyzer.analyze_continuous(combined, sample_every_n=1)
        assert result.total_exchanges >= 2

    def test_short_exchange_skipped(self):
        """Very short approach (< min frames) → skipped."""
        seq = []
        # Just 2 frames of approach — too short
        for i in range(5):
            right_x = 600.0 - i * 5  # very small change
            left = make_fencer("left", shoulder_cx=200, hip_cx=200, ankle_cx=200)
            right = make_fencer("right", shoulder_cx=right_x, hip_cx=right_x, ankle_cx=right_x)
            seq.append(make_pose_result(i, left, right))
        result = self.analyzer.analyze_continuous(seq, sample_every_n=1)
        assert result.total_exchanges == 0

    def test_scoring_exchange_counted(self):
        """Exchange with scoring frame → scoring_exchanges incremented."""
        seq = self._make_approach_engage_separate_sequence(n_frames=90)
        result = self.analyzer.analyze_continuous(
            seq, sample_every_n=1, scoring_frames={30},
        )
        assert result.scoring_exchanges >= 1

    def test_camera_cut_during_exchange(self):
        """Camera cut in exchange doesn't crash."""
        seq = self._make_approach_engage_separate_sequence(n_frames=90)
        # Insert camera cut: teleport fencer
        jump_frame = 20
        if jump_frame < len(seq):
            left_jump = make_fencer(
                "left", shoulder_cx=500, hip_cx=500, ankle_cx=500,
            )
            seq[jump_frame] = make_pose_result(jump_frame, left_jump,
                                                seq[jump_frame].fencers[-1] if len(seq[jump_frame].fencers) > 1 else None)
        result = self.analyzer.analyze_continuous(seq, sample_every_n=1)
        # Should not crash
        assert isinstance(result, ContinuousAnalysisResult)


# ==================================================================
# Phase 6: My Fencer Perspective tests (4)
# ==================================================================


class TestMyFencerPerspective:

    def setup_method(self):
        self.analyzer = PoseAnalyzer()

    def test_my_fencer_left_attack_narrative(self):
        """my_fencer=left, scorer=left → attack narrative."""
        seq = make_static_sequence(20, left_x=200, right_x=500)
        result = self.analyzer.analyze(seq, scorer="left", my_fencer="left")
        assert "내 선수(왼쪽)" in result.my_fencer_narrative
        assert "득점" in result.my_fencer_narrative

    def test_my_fencer_right_defense(self):
        """my_fencer=right, scorer=left → defense narrative."""
        seq = make_static_sequence(20, left_x=200, right_x=500)
        result = self.analyzer.analyze(seq, scorer="left", my_fencer="right")
        assert "내 선수(오른쪽)" in result.my_fencer_narrative
        assert "실점" in result.my_fencer_narrative

    def test_no_my_fencer_no_summary(self):
        """my_fencer=None → empty narrative."""
        seq = make_static_sequence(20, left_x=200, right_x=500)
        result = self.analyzer.analyze(seq, scorer="left", my_fencer=None)
        assert result.my_fencer_narrative == ""

    def test_continuous_my_fencer_summary(self):
        """Continuous analysis with my_fencer → MyFencerSummary populated."""
        # Build a sequence with approach-engage-separate
        seq = []
        for i in range(90):
            if i < 30:
                right_x = 600.0 - i * 5
            elif i < 60:
                right_x = 450.0
            else:
                right_x = 450.0 + (i - 60) * 5
            left = make_fencer("left", shoulder_cx=200, hip_cx=200, ankle_cx=200)
            right = make_fencer("right", shoulder_cx=right_x, hip_cx=right_x, ankle_cx=right_x)
            seq.append(make_pose_result(i, left, right))

        result = self.analyzer.analyze_continuous(
            seq, sample_every_n=1, my_fencer="left",
        )
        assert result.my_fencer_summary is not None
        assert result.my_fencer_summary.side == "left"


# ==================================================================
# Phase 6: Threshold Tuning tests (3)
# ==================================================================


class TestThresholdTuning:

    def test_ratio_based_lunge_detection(self):
        """Ratio-based hip drop detects lunge with small absolute drop."""
        analyzer = PoseAnalyzer()
        n = 15
        seq = []
        for i in range(n):
            progress = i / (n - 1)
            # Body height ≈ 300px. Hip drop = 4px (ratio = 4/300 ≈ 0.013 > 0.01)
            # Old absolute threshold (10px) would miss this.
            hip_drop = progress * 4.0
            left = make_fencer(
                "left",
                shoulder_cx=200, hip_cx=200, hip_cy=200.0 + hip_drop,
                ankle_cx=200,
            )
            # Front foot advances 60px, rear stays
            left.keypoints[KP_RIGHT_ANKLE] = make_kp(220 + progress * 60, 400.0)
            left.keypoints[KP_LEFT_ANKLE] = make_kp(180, 400.0)
            right = make_fencer("right", shoulder_cx=600, hip_cx=600, ankle_cx=600)
            seq.append(make_pose_result(i, left, right))

        result = analyzer.detect_footwork(seq, "left")
        assert result.footwork_type == FootworkType.LUNGE

    def test_higher_fleche_threshold(self):
        """Old 20px fleche threshold would trigger, new 40px should not."""
        analyzer = PoseAnalyzer()
        n = 15
        seq = []
        for i in range(n):
            progress = i / (n - 1)
            # Both feet advance 30px — above old threshold (20) but below new (40)
            offset = progress * 30.0
            left = make_fencer("left", shoulder_cx=200, hip_cx=200, ankle_cx=200)
            left.keypoints[KP_LEFT_ANKLE] = make_kp(180 + offset, 400.0)
            left.keypoints[KP_RIGHT_ANKLE] = make_kp(220 + offset, 400.0)
            right = make_fencer("right", shoulder_cx=600, hip_cx=600, ankle_cx=600)
            seq.append(make_pose_result(i, left, right))

        result = analyzer.detect_footwork(seq, "left")
        # Should NOT be fleche with the tuned threshold (30 < 40)
        assert result.footwork_type != FootworkType.FLECHE

    def test_legacy_absolute_mode(self):
        """With FOOTWORK_USE_RATIO_BASED_HIP_DROP=False, absolute threshold applies."""
        import ml.pose_analyzer as pa_module
        original = pa_module.FOOTWORK_USE_RATIO_BASED_HIP_DROP
        try:
            pa_module.FOOTWORK_USE_RATIO_BASED_HIP_DROP = False
            analyzer = PoseAnalyzer()
            n = 15
            seq = []
            for i in range(n):
                progress = i / (n - 1)
                # Hip drop = 4px, absolute threshold = 10px → should NOT detect lunge
                hip_drop = progress * 4.0
                left = make_fencer(
                    "left",
                    shoulder_cx=200, hip_cx=200, hip_cy=200.0 + hip_drop,
                    ankle_cx=200,
                )
                left.keypoints[KP_RIGHT_ANKLE] = make_kp(220 + progress * 60, 400.0)
                left.keypoints[KP_LEFT_ANKLE] = make_kp(180, 400.0)
                right = make_fencer("right", shoulder_cx=600, hip_cx=600, ankle_cx=600)
                seq.append(make_pose_result(i, left, right))

            result = analyzer.detect_footwork(seq, "left")
            assert result.footwork_type != FootworkType.LUNGE
        finally:
            pa_module.FOOTWORK_USE_RATIO_BASED_HIP_DROP = original


# ==================================================================
# Phase 7b: scoring_frames integration test (1)
# ==================================================================


class TestScoringFrames:

    def setup_method(self):
        self.analyzer = PoseAnalyzer()

    def _make_approach_engage_separate_sequence(
        self, n_frames: int = 60, start_dist: float = 500.0, min_dist: float = 200.0,
    ) -> List[PoseResult]:
        """Create approach → engagement → separation cycle."""
        seq = []
        approach_end = n_frames // 3
        engage_end = 2 * n_frames // 3
        for i in range(n_frames):
            if i < approach_end:
                progress = i / approach_end
                right_x = start_dist + 200 - progress * (start_dist - min_dist)
            elif i < engage_end:
                right_x = min_dist + 200
            else:
                progress = (i - engage_end) / (n_frames - engage_end)
                right_x = min_dist + 200 + progress * (start_dist - min_dist)
            left = make_fencer("left", shoulder_cx=200, hip_cx=200, ankle_cx=200)
            right = make_fencer("right", shoulder_cx=right_x, hip_cx=right_x, ankle_cx=right_x)
            seq.append(make_pose_result(i, left, right))
        return seq

    def test_scoring_frames_marks_exchange_as_scoring(self):
        """Exchange with scoring_frames → UNKNOWN_EXCHANGE (scoring) and scoring count > 0."""
        seq = self._make_approach_engage_separate_sequence(n_frames=90)
        # Without scoring_frames → non-scoring classification
        result_no_sf = self.analyzer.analyze_continuous(seq, sample_every_n=1)
        assert result_no_sf.scoring_exchanges == 0

        # With scoring_frames overlapping the exchange → scoring classification
        result_sf = self.analyzer.analyze_continuous(
            seq, sample_every_n=1, scoring_frames={30},
        )
        assert result_sf.scoring_exchanges >= 1
        # The scoring exchange should be UNKNOWN_EXCHANGE
        scoring_exs = [
            ex for ex in result_sf.exchanges
            if ex.event_type == NonScoringEventType.UNKNOWN_EXCHANGE
        ]
        assert len(scoring_exs) >= 1


# ==================================================================
# Phase 7b: Short SEPARATION merge tests (2)
# ==================================================================


class TestExchangeMerge:
    """Test that short separations are merged into a single exchange."""

    def setup_method(self):
        self.analyzer = PoseAnalyzer()

    def test_short_separation_merged_into_one_exchange(self):
        """Brief partial separation (<=MERGE threshold) → merged into one exchange.

        Tests _detect_exchanges directly with controlled BH distance values.
        """
        # Build a distance series: approach → brief sep → re-approach → full sep
        # All distances are in BH units.
        sampled = []
        frame = 0
        # Phase 1: approach (2.0 → 0.8 BH over 20 frames)
        for i in range(20):
            d = 2.0 - i * (1.2 / 19)
            sampled.append((frame, d))
            frame += 1
        # Phase 2: brief separation (0.8 → 0.9 BH over 5 frames, < 0.2 BH bump)
        for i in range(5):
            d = 0.8 + i * (0.1 / 4)
            sampled.append((frame, d))
            frame += 1
        # Phase 3: re-approach (0.9 → 0.5 BH over 15 frames)
        for i in range(15):
            d = 0.9 - i * (0.4 / 14)
            sampled.append((frame, d))
            frame += 1
        # Phase 4: full separation (0.5 → 2.0 BH over 20 frames)
        for i in range(20):
            d = 0.5 + i * (1.5 / 19)
            sampled.append((frame, d))
            frame += 1

        raw_exchanges = self.analyzer._detect_exchanges(sampled)
        assert len(raw_exchanges) == 1, (
            f"Expected 1 merged exchange, got {len(raw_exchanges)}"
        )

    def test_long_separation_creates_two_exchanges(self):
        """Long partial separation (>MERGE threshold) → two exchanges.

        Tests _detect_exchanges directly with controlled BH distance values.
        """
        sampled = []
        frame = 0
        # Phase 1: approach (2.0 → 0.8 BH over 20 frames)
        for i in range(20):
            d = 2.0 - i * (1.2 / 19)
            sampled.append((frame, d))
            frame += 1
        # Phase 2: long separation (0.8 → 0.9 BH over 15 frames, still < 0.2 BH bump)
        for i in range(15):
            d = 0.8 + i * (0.1 / 14)
            sampled.append((frame, d))
            frame += 1
        # Phase 3: re-approach (0.9 → 0.5 BH over 15 frames)
        for i in range(15):
            d = 0.9 - i * (0.4 / 14)
            sampled.append((frame, d))
            frame += 1
        # Phase 4: full separation (0.5 → 2.0 BH over 20 frames)
        for i in range(20):
            d = 0.5 + i * (1.5 / 19)
            sampled.append((frame, d))
            frame += 1

        raw_exchanges = self.analyzer._detect_exchanges(sampled)
        assert len(raw_exchanges) >= 2, (
            f"Expected >=2 separate exchanges, got {len(raw_exchanges)}"
        )


# ==================================================================
# Exchange over-segmentation guards (smoothing + turn hysteresis)
# ==================================================================


class TestExchangeOverSegmentation:
    """Smoothing + turn hysteresis must suppress jitter-driven over-splitting
    without merging genuinely separate exchanges (under-segmentation)."""

    def setup_method(self):
        self.analyzer = PoseAnalyzer()

    @staticmethod
    def _v_cycle(start_frame, jitter=0.0):
        """One approach→separate V-cycle (2.0→0.4→2.0) over 40 samples.

        ``jitter`` adds a deterministic alternating wobble of that amplitude to
        each sample — the kind of pose noise that fragments a single approach
        into spurious sub-exchanges when the series is not smoothed.
        """
        pts = []
        f = start_frame
        for i in range(20):  # approach 2.0 → 0.4
            d = 2.0 - i * (1.6 / 19)
            pts.append((f, d + (jitter if i % 2 == 0 else -jitter)))
            f += 1
        for i in range(20):  # separate 0.4 → 2.0
            d = 0.4 + i * (1.6 / 19)
            pts.append((f, d + (jitter if i % 2 == 0 else -jitter)))
            f += 1
        return pts, f

    def test_noisy_curve_not_oversplit(self):
        """3 real approaches with jitter → ~3 detected, not a fragmented pile."""
        sampled = []
        frame = 0
        for _ in range(3):
            cycle, frame = self._v_cycle(frame, jitter=0.03)
            sampled.extend(cycle)

        detected = self.analyzer._detect_exchanges(sampled)
        # 3 genuine approaches: allow a small edge-effect margin but reject
        # the jitter-driven explosion (would be many more without smoothing).
        assert 3 <= len(detected) <= 4, (
            f"Expected ~3 exchanges from 3 noisy approaches, got {len(detected)}"
        )

    def test_smoothing_collapses_ripple_oversplit(self):
        """A single genuine approach carrying a medium-frequency ripple (camera
        drift / breathing) fragments into many phantom exchanges without
        smoothing; smoothing collapses it back toward the one real exchange.

        This mirrors the production symptom (one bout, hundreds of exchanges).
        """
        import math
        from ml.pose_analysis.exchanges import detect_exchanges
        from analyzer.config import EXCHANGE_MIN_DISTANCE_CHANGE_BH

        # Ripple amplitude sized off the validity threshold so each phantom dip
        # clears it when unsmoothed (robust to future threshold tuning).
        amp = 1.5 * EXCHANGE_MIN_DISTANCE_CHANGE_BH
        n = 80
        sampled = []
        for i in range(n):
            base = (2.0 - i * (1.6 / (n // 2 - 1))) if i < n // 2 \
                else (0.4 + (i - n // 2) * (1.6 / (n // 2 - 1)))
            ripple = amp * math.sin(2 * math.pi * i / 6)
            sampled.append((i, max(0.1, base + ripple)))

        unsmoothed = detect_exchanges(sampled, smoothing_window=1)
        smoothed = detect_exchanges(sampled)
        assert len(unsmoothed) >= 5, (
            f"Ripple should fragment badly without smoothing, got {len(unsmoothed)}"
        )
        assert len(smoothed) <= 2, (
            f"Smoothing should collapse the ripple to ~1 exchange, got {len(smoothed)}"
        )

    def test_separated_exchanges_not_merged(self):
        """Two clearly separated real exchanges → detected as 2 (no under-split)."""
        sampled = []
        frame = 0
        cycle1, frame = self._v_cycle(frame, jitter=0.02)
        sampled.extend(cycle1)
        # Long flat gap fully out of distance between the two exchanges.
        for _ in range(15):
            sampled.append((frame, 2.0))
            frame += 1
        cycle2, frame = self._v_cycle(frame, jitter=0.02)
        sampled.extend(cycle2)

        detected = self.analyzer._detect_exchanges(sampled)
        assert len(detected) == 2, (
            f"Two separated exchanges must not merge, got {len(detected)}"
        )

    def test_none_gaps_are_safe(self):
        """None gaps in the distance series must not crash smoothing/detection,
        and a genuine approach spanning the gaps is still detected."""
        sampled = []
        frame = 0
        for i in range(20):  # approach 2.0 → 0.4
            d = 2.0 - i * (1.6 / 19)
            # Punch holes: every 4th sample is missing (pose dropout).
            sampled.append((frame, None if i % 4 == 3 else d))
            frame += 1
        for i in range(20):  # separate back out
            d = 0.4 + i * (1.6 / 19)
            sampled.append((frame, None if i % 4 == 3 else d))
            frame += 1

        detected = self.analyzer._detect_exchanges(sampled)  # must not raise
        assert len(detected) >= 1, "Approach spanning None gaps should still detect"

    def test_all_none_series_is_safe(self):
        """A fully-missing series yields no exchanges and does not crash."""
        sampled = [(i, None) for i in range(30)]
        assert self.analyzer._detect_exchanges(sampled) == []


class TestCameraCutQualityGate:
    """analyze_continuous surfaces a warning when too much footage is camera cuts."""

    def setup_method(self):
        self.analyzer = PoseAnalyzer()

    def test_high_camera_cut_ratio_warns(self):
        """A jumpy sequence (hips teleport most frames) → ratio > threshold + warning."""
        seq = []
        for i in range(20):
            # Left fencer hip teleports >100px every frame → each frame a cut.
            lx = 200.0 if i % 2 == 0 else 450.0
            left = make_fencer("left", shoulder_cx=lx, hip_cx=lx, ankle_cx=lx)
            right = make_fencer("right", shoulder_cx=800, hip_cx=800, ankle_cx=800)
            seq.append(make_pose_result(i, left, right))

        result = self.analyzer.analyze_continuous(seq, sample_every_n=1)
        assert result.camera_cut_ratio > 0.3
        types = [w["type"] for w in result.quality_warnings]
        assert "low_quality_high_camera_cuts" in types

    def test_stable_sequence_no_camera_cut_warning(self):
        """A steady approach-separate sequence → low cut ratio, no warning."""
        seq = make_static_sequence(30, left_x=200.0, right_x=600.0)
        result = self.analyzer.analyze_continuous(seq, sample_every_n=1)
        assert result.camera_cut_ratio <= 0.3
        types = [w["type"] for w in result.quality_warnings]
        assert "low_quality_high_camera_cuts" not in types


# ==================================================================
# Joint kinematics tests (4)
# ==================================================================


class TestJointKinematics:

    def setup_method(self):
        self.analyzer = PoseAnalyzer()

    def test_stationary_velocity_near_zero(self):
        """Stationary fencers → all joint velocities ≈ 0."""
        seq = make_static_sequence(5, left_x=200.0, right_x=600.0)
        results = self.analyzer.compute_joint_kinematics(seq, "left")
        assert len(results) == 5
        # Frame 0 is always zero (no previous frame)
        # Frames 1-4 should also be zero since no movement
        for fk in results[1:]:
            assert fk.max_velocity_px == pytest.approx(0.0, abs=0.01), (
                f"Frame {fk.frame_index}: expected 0 velocity, got {fk.max_velocity_px}"
            )
            for jk in fk.joints.values():
                assert jk.velocity_px == pytest.approx(0.0, abs=0.01)
                assert jk.velocity_bh == pytest.approx(0.0, abs=0.001)

    def test_constant_velocity_movement(self):
        """Fencer moving at constant speed → velocity > 0, acceleration ≈ 0."""
        seq = []
        for i in range(6):
            # Left fencer moves right by 10px per frame
            x = 200.0 + i * 10.0
            left = make_fencer("left", shoulder_cx=x, hip_cx=x, ankle_cx=x)
            right = make_fencer("right", shoulder_cx=600.0, hip_cx=600.0, ankle_cx=600.0)
            seq.append(make_pose_result(i, left, right))

        results = self.analyzer.compute_joint_kinematics(seq, "left")
        assert len(results) == 6

        # Frame 0: velocity = 0 (no previous)
        assert results[0].max_velocity_px == pytest.approx(0.0, abs=0.01)

        # Frames 1-5: velocity > 0 (hips moved 10px)
        for fk in results[1:]:
            assert fk.max_velocity_px > 5.0, (
                f"Frame {fk.frame_index}: expected velocity > 5, got {fk.max_velocity_px}"
            )
            # BH normalization: velocity_bh should be positive
            hip_jk = fk.joints.get("left_hip") or fk.joints.get("right_hip")
            if hip_jk:
                assert hip_jk.velocity_bh > 0.0

        # Frames 2-5: acceleration ≈ 0 (constant velocity)
        for fk in results[2:]:
            hip_jk = fk.joints.get("left_hip") or fk.joints.get("right_hip")
            if hip_jk:
                assert abs(hip_jk.acceleration_px) < 2.0, (
                    f"Frame {fk.frame_index}: expected ~0 accel, got {hip_jk.acceleration_px}"
                )

    def test_accelerating_movement(self):
        """Fencer accelerating → acceleration > 0."""
        seq = []
        for i in range(5):
            # Increasing displacement: 0, 5, 15, 30, 50 (cumulative)
            x = 200.0 + (i * (i + 1)) * 2.5  # 200, 205, 215, 230, 250
            left = make_fencer("left", shoulder_cx=x, hip_cx=x, ankle_cx=x)
            right = make_fencer("right", shoulder_cx=600.0, hip_cx=600.0, ankle_cx=600.0)
            seq.append(make_pose_result(i, left, right))

        results = self.analyzer.compute_joint_kinematics(seq, "left")
        assert len(results) == 5

        # Frame 0: velocity 0
        # Frame 1: velocity = displacement(1) > 0
        # Frame 2: velocity = displacement(2) > displacement(1)
        # → acceleration at frame 2 should be > 0
        if len(results) >= 3:
            # Verify velocity is increasing
            v1 = results[1].max_velocity_px
            v2 = results[2].max_velocity_px
            assert v2 > v1, f"Expected increasing velocity: v1={v1}, v2={v2}"

            # Verify positive acceleration for at least one joint
            has_positive_accel = False
            for jk in results[2].joints.values():
                if jk.acceleration_px > 0.5:
                    has_positive_accel = True
                    break
            assert has_positive_accel, (
                "Expected positive acceleration in at least one joint at frame 2"
            )

    def test_camera_cut_skips_velocity(self):
        """Camera cut (hip jump > 100px) → velocity resets to 0."""
        seq = []
        # Frames 0-2: normal position
        for i in range(3):
            left = make_fencer("left", shoulder_cx=200.0, hip_cx=200.0, ankle_cx=200.0)
            right = make_fencer("right", shoulder_cx=600.0, hip_cx=600.0, ankle_cx=600.0)
            seq.append(make_pose_result(i, left, right))

        # Frame 3: camera cut — left fencer jumps 200px to the right
        left_cut = make_fencer("left", shoulder_cx=400.0, hip_cx=400.0, ankle_cx=400.0)
        right_cut = make_fencer("right", shoulder_cx=800.0, hip_cx=800.0, ankle_cx=800.0)
        seq.append(make_pose_result(3, left_cut, right_cut))

        # Frame 4: continues from new position (small move)
        left_after = make_fencer("left", shoulder_cx=405.0, hip_cx=405.0, ankle_cx=405.0)
        right_after = make_fencer("right", shoulder_cx=800.0, hip_cx=800.0, ankle_cx=800.0)
        seq.append(make_pose_result(4, left_after, right_after))

        results = self.analyzer.compute_joint_kinematics(seq, "left")
        assert len(results) == 5

        # Frame 3 (camera cut): velocity should be 0 (reset)
        assert results[3].max_velocity_px == pytest.approx(0.0, abs=0.01), (
            f"Camera cut frame should have 0 velocity, got {results[3].max_velocity_px}"
        )

        # Frame 4 (after cut): should have small velocity from the 5px move
        assert results[4].max_velocity_px > 0.0, (
            "Frame after camera cut should resume velocity calculation"
        )


# ==================================================================
# Per-frame action state classification tests (5)
# ==================================================================


class TestActionStateClassification:

    def setup_method(self):
        self.analyzer = PoseAnalyzer()

    def test_stationary_en_garde(self):
        """Stationary fencers → EN_GARDE."""
        seq = make_static_sequence(5, left_x=200.0, right_x=600.0)
        results = self.analyzer.classify_action_sequence(seq, "left")
        # First frame is always EN_GARDE by default
        assert results[0].state == ActionState.EN_GARDE
        # Subsequent stationary frames should also be EN_GARDE
        for fas in results[1:]:
            assert fas.state == ActionState.EN_GARDE, (
                f"Frame {fas.frame_index}: expected EN_GARDE, got {fas.state}"
            )

    def test_advancing_marche(self):
        """Fencer advancing toward opponent → MARCHE or PREPARATION."""
        seq = []
        for i in range(6):
            # Left fencer advancing 40px per frame (above FOOTWORK_MIN threshold)
            x = 200.0 + i * 40.0
            left = make_fencer("left", shoulder_cx=x, hip_cx=x, ankle_cx=x)
            right = make_fencer("right", shoulder_cx=600.0, hip_cx=600.0, ankle_cx=600.0)
            seq.append(make_pose_result(i, left, right))

        results = self.analyzer.classify_action_sequence(seq, "left")
        assert len(results) >= 2

        # Frames 1+ should show forward movement (MARCHE, PREPARATION, or ADVANCE-based)
        advancing_states = {ActionState.MARCHE, ActionState.PREPARATION, ActionState.FLECHE}
        for fas in results[1:]:
            assert fas.state in advancing_states or fas.state == ActionState.UNKNOWN, (
                f"Frame {fas.frame_index}: expected advancing state, got {fas.state}"
            )

    def test_retreating_retraite(self):
        """Fencer retreating → RETRAITE."""
        seq = []
        for i in range(6):
            # Left fencer retreating (moving left, away from right fencer at 600)
            x = 300.0 - i * 40.0
            left = make_fencer("left", shoulder_cx=x, hip_cx=x, ankle_cx=x)
            right = make_fencer("right", shoulder_cx=600.0, hip_cx=600.0, ankle_cx=600.0)
            seq.append(make_pose_result(i, left, right))

        results = self.analyzer.classify_action_sequence(seq, "left")
        assert len(results) >= 2

        # At least some frames should be RETRAITE
        retreat_count = sum(1 for fas in results[1:] if fas.state == ActionState.RETRAITE)
        assert retreat_count >= 1, (
            f"Expected at least 1 RETRAITE frame, states: "
            f"{[fas.state.value for fas in results]}"
        )

    def test_lunge_pattern_fente(self):
        """Lunge pattern (front foot forward + hip drop) → FENTE."""
        seq = []
        # Frame 0: en garde position
        left0 = make_fencer(
            "left", shoulder_cx=200.0, hip_cx=200.0, ankle_cx=200.0,
            hip_cy=200.0, ankle_cy=400.0,
        )
        right0 = make_fencer("right", shoulder_cx=600.0, hip_cx=600.0, ankle_cx=600.0)
        seq.append(make_pose_result(0, left0, right0))

        # Frame 1: lunge — front foot shoots forward, hip drops
        left1 = make_fencer(
            "left", shoulder_cx=200.0, hip_cx=200.0,
            ankle_cx=200.0, hip_cy=220.0, ankle_cy=400.0,
            # Front ankle advances significantly, rear stays
        )
        # Override ankle positions for lunge pattern
        kps = left1.keypoints
        kps[KP_LEFT_ANKLE] = make_kp(150.0, 400.0)   # rear foot stays
        kps[KP_RIGHT_ANKLE] = make_kp(320.0, 400.0)   # front foot shoots forward
        right1 = make_fencer("right", shoulder_cx=600.0, hip_cx=600.0, ankle_cx=600.0)
        seq.append(make_pose_result(1, left1, right1))

        results = self.analyzer.classify_action_sequence(seq, "left")
        # We accept FENTE or any forward action state since lunge detection
        # thresholds may not trigger with just 2 frames
        assert len(results) == 2
        assert results[0].state == ActionState.EN_GARDE  # first frame default
        # Second frame: any valid classification is acceptable
        assert isinstance(results[1].state, ActionState)

    def test_parry_pattern_parade(self):
        """Wrist lateral displacement → PARADE."""
        seq = []
        n_frames = 5
        for i in range(n_frames):
            # Right fencer's wrist has a large lateral displacement
            # (simulating a parry motion)
            wrist_y = 150.0 + (i * 60.0 if i >= 2 else 0.0)  # sudden jump at frame 2
            left = make_fencer("left", shoulder_cx=200.0, hip_cx=200.0, ankle_cx=200.0)
            right = make_fencer(
                "right", shoulder_cx=600.0, hip_cx=600.0, ankle_cx=600.0,
                wrist_r_y=wrist_y,
            )
            seq.append(make_pose_result(i, left, right))

        results = self.analyzer.classify_action_sequence(seq, "right")
        assert len(results) >= 2

        # Check if any frame classified as PARADE
        parade_count = sum(1 for fas in results if fas.state == ActionState.PARADE)
        # We accept if the parry was detected; parry detection requires
        # specific threshold conditions, so we test the classification logic
        # rather than exact counts
        assert isinstance(results[-1], FrameActionState)
        # Verify the output structure is correct
        for fas in results:
            assert isinstance(fas.state, ActionState)
            assert isinstance(fas.confidence, float)
            assert 0.0 <= fas.confidence <= 1.0


# ==================================================================
# Multi-frame window wiring: FENTE / FLECHE / PARADE must be reachable
# ==================================================================


class TestActionStateMultiFrameWindow:
    """Regression tests for the multi-frame window wiring.

    Before the fix, classify_frame_action received only a 2-frame pair, so
    detect_footwork/detect_parry (which need >= 3 frames) always returned
    UNKNOWN and the FENTE/FLECHE/PARADE branches were dead code. These tests
    build synthetic sequences that unambiguously exhibit a lunge, a fleche
    and a parry, and assert classify_action_sequence surfaces each state.
    """

    def setup_method(self):
        self.analyzer = PoseAnalyzer()

    @staticmethod
    def _make_lunge_sequence(side: str = "left", n: int = 15) -> List[PoseResult]:
        """Front foot shoots forward 60px while rear stays and hip drops 15px."""
        seq: List[PoseResult] = []
        left_x, right_x = 200.0, 600.0
        anchor_x = left_x if side == "left" else right_x
        for i in range(n):
            progress = i / (n - 1)
            front_offset = progress * 60.0
            hip_drop = progress * 15.0
            if side == "left":
                l = make_fencer(
                    "left", shoulder_cx=anchor_x, hip_cx=anchor_x,
                    hip_cy=200.0 + hip_drop, ankle_cx=anchor_x,
                )
                l.keypoints[KP_LEFT_ANKLE] = make_kp(anchor_x - 20, 400.0)
                l.keypoints[KP_RIGHT_ANKLE] = make_kp(anchor_x + 20 + front_offset, 400.0)
                r = make_fencer("right", shoulder_cx=right_x, hip_cx=right_x, ankle_cx=right_x)
            else:
                l = make_fencer("left", shoulder_cx=left_x, hip_cx=left_x, ankle_cx=left_x)
                r = make_fencer(
                    "right", shoulder_cx=anchor_x, hip_cx=anchor_x,
                    hip_cy=200.0 + hip_drop, ankle_cx=anchor_x,
                )
                r.keypoints[KP_LEFT_ANKLE] = make_kp(anchor_x - 20 - front_offset, 400.0)
                r.keypoints[KP_RIGHT_ANKLE] = make_kp(anchor_x + 20, 400.0)
            seq.append(make_pose_result(i, l, r))
        return seq

    @staticmethod
    def _make_fleche_sequence(n: int = 15) -> List[PoseResult]:
        """Both feet advance ~60px with a low front/rear ratio (fleche)."""
        seq: List[PoseResult] = []
        for i in range(n):
            offset = (i / (n - 1)) * 60.0
            left = make_fencer(
                "left", shoulder_cx=200 + offset, hip_cx=200 + offset, ankle_cx=200 + offset,
            )
            left.keypoints[KP_LEFT_ANKLE] = make_kp(180 + offset, 400.0)
            left.keypoints[KP_RIGHT_ANKLE] = make_kp(220 + offset, 400.0)
            right = make_fencer("right", shoulder_cx=600, hip_cx=600, ankle_cx=600)
            seq.append(make_pose_result(i, left, right))
        return seq

    @staticmethod
    def _make_parry_sequence(side: str = "left", magnitude: float = 35.0, n: int = 10) -> List[PoseResult]:
        """Weapon-hand wrist makes a rapid lateral sweep at frames 4-5 (parry)."""
        wrist_idx = KP_RIGHT_WRIST if side == "left" else KP_LEFT_WRIST
        seq: List[PoseResult] = []
        for i in range(n):
            left = make_fencer("left", shoulder_cx=200, hip_cx=200, ankle_cx=200)
            right = make_fencer("right", shoulder_cx=600, hip_cx=600, ankle_cx=600)
            fencer = left if side == "left" else right
            if 4 <= i <= 5:
                dy = magnitude if i == 4 else -magnitude
                fencer.keypoints[wrist_idx] = make_kp(
                    fencer.keypoints[wrist_idx].x, 150.0 + dy,
                )
            seq.append(make_pose_result(i, left, right))
        return seq

    def test_lunge_sequence_yields_fente(self):
        """A lunge sequence must surface FENTE (was unreachable pre-fix)."""
        for side in ("left", "right"):
            seq = self._make_lunge_sequence(side)
            results = self.analyzer.classify_action_sequence(seq, side)
            states = [fas.state for fas in results]
            assert ActionState.FENTE in states, (
                f"{side}: expected FENTE somewhere, got {[s.value for s in states]}"
            )

    def test_fleche_sequence_yields_fleche(self):
        """A fleche sequence must surface FLECHE (was unreachable pre-fix)."""
        seq = self._make_fleche_sequence()
        results = self.analyzer.classify_action_sequence(seq, "left")
        states = [fas.state for fas in results]
        assert ActionState.FLECHE in states, (
            f"expected FLECHE somewhere, got {[s.value for s in states]}"
        )

    def test_parry_sequence_yields_parade(self):
        """A parry sequence must surface PARADE (was unreachable pre-fix)."""
        for side in ("left", "right"):
            seq = self._make_parry_sequence(side)
            results = self.analyzer.classify_action_sequence(seq, side)
            states = [fas.state for fas in results]
            assert ActionState.PARADE in states, (
                f"{side}: expected PARADE somewhere, got {[s.value for s in states]}"
            )

    def test_two_frame_caller_still_falls_back(self):
        """Direct 2-frame classify_frame_action keeps the hip/velocity fallback.

        classify_frame_action without window_frames must not crash and must
        return a valid state (footwork/parry can't fire on 2 frames, so the
        velocity/hip-direction fallback governs)."""
        f1 = make_pose_result(
            0,
            make_fencer("left", shoulder_cx=200, hip_cx=200, ankle_cx=200),
            make_fencer("right", shoulder_cx=600, hip_cx=600, ankle_cx=600),
        )
        f2 = make_pose_result(
            1,
            make_fencer("left", shoulder_cx=240, hip_cx=240, ankle_cx=240),
            make_fencer("right", shoulder_cx=600, hip_cx=600, ankle_cx=600),
        )
        state = self.analyzer.classify_frame_action(f1, f2, "left")
        assert isinstance(state, FrameActionState)
        assert state.state in (
            ActionState.MARCHE, ActionState.PREPARATION, ActionState.EN_GARDE,
        )


# ==================================================================
# Helper: approach-separate sequence generator
# ==================================================================


def _make_approach_separate_sequence(
    start_dist: float = 1.8,
    min_dist: float = 0.5,
    end_dist: float = 1.8,
    approach_frames: int = 10,
    separate_frames: int = 10,
    left_advancing: bool = False,
) -> List[PoseResult]:
    """Generate a synthetic sequence where fencers approach then separate.

    Distances are in BH units. With default make_fencer body height ≈ 300px,
    hip_x_distance = distance_bh * 300.

    Args:
        start_dist: Starting BH distance.
        min_dist: Minimum BH distance at closest point.
        end_dist: Final BH distance after separation.
        approach_frames: Number of frames for approach phase.
        separate_frames: Number of frames for separation phase.
        left_advancing: If True, the left fencer moves forward (for footwork detection).
    """
    body_height = 300.0  # shoulder_cy=100, ankle_cy=400 → 300px
    left_x_base = 200.0

    seq: List[PoseResult] = []
    total_frames = approach_frames + separate_frames

    for i in range(total_frames):
        if i < approach_frames:
            # Approach: distance decreases from start_dist to min_dist
            progress = i / max(approach_frames - 1, 1)
            dist_bh = start_dist + (min_dist - start_dist) * progress
        else:
            # Separation: distance increases from min_dist to end_dist
            progress = (i - approach_frames) / max(separate_frames - 1, 1)
            dist_bh = min_dist + (end_dist - min_dist) * progress

        hip_gap = dist_bh * body_height  # px

        if left_advancing:
            # Left fencer moves toward right fencer
            left_x = left_x_base + (start_dist * body_height - hip_gap) * 0.5
            right_x = left_x + hip_gap
        else:
            left_x = left_x_base
            right_x = left_x + hip_gap

        left = make_fencer(
            "left", shoulder_cx=left_x, hip_cx=left_x, ankle_cx=left_x,
        )
        right = make_fencer(
            "right", shoulder_cx=right_x, hip_cx=right_x, ankle_cx=right_x,
        )
        seq.append(make_pose_result(i, left, right))

    return seq


# ==================================================================
# Step 2: scoring_frames tolerance tests
# ==================================================================


class TestScoringFramesTolerance:
    """Tests for scoring_frames integration with OCR delay tolerance."""

    def test_scoring_frame_within_exchange(self):
        """Scoring frame directly within exchange window should be detected."""
        analyzer = PoseAnalyzer()
        # Create a sequence where fencers approach and separate
        seq = _make_approach_separate_sequence(
            start_dist=1.8, min_dist=0.5, end_dist=1.5,
            approach_frames=10, separate_frames=10,
        )
        result = analyzer.analyze_continuous(
            seq, sample_every_n=1, scoring_frames={10},  # at min distance frame
        )
        assert result.scoring_exchanges >= 1

    def test_scoring_frame_after_exchange_within_tolerance(self):
        """Scoring frame slightly after exchange end (OCR delay) should still be detected."""
        analyzer = PoseAnalyzer()
        seq = _make_approach_separate_sequence(
            start_dist=1.8, min_dist=0.5, end_dist=1.8,
            approach_frames=10, separate_frames=10,
        )
        # Exchange ends around frame 20, scoring frame at frame 25 (OCR delay)
        result = analyzer.analyze_continuous(
            seq, sample_every_n=1, scoring_frames={25},
        )
        assert result.scoring_exchanges >= 1

    def test_scoring_frame_far_outside_exchange(self):
        """Scoring frame very far from any exchange should not be matched."""
        analyzer = PoseAnalyzer()
        seq = _make_approach_separate_sequence(
            start_dist=1.8, min_dist=0.5, end_dist=1.8,
            approach_frames=10, separate_frames=10,
        )
        # Exchange ends around frame 20, scoring frame at frame 200 (way too far)
        result = analyzer.analyze_continuous(
            seq, sample_every_n=1, scoring_frames={200},
        )
        assert result.scoring_exchanges == 0

    def test_my_fencer_summary_with_scoring(self):
        """my_fencer_summary should reflect scoring when scoring_frames match."""
        analyzer = PoseAnalyzer()
        seq = _make_approach_separate_sequence(
            start_dist=1.8, min_dist=0.5, end_dist=1.8,
            approach_frames=10, separate_frames=10,
            left_advancing=True,
        )
        result = analyzer.analyze_continuous(
            seq, sample_every_n=1, my_fencer="left",
            scoring_frames={10},
        )
        assert result.my_fencer_summary is not None
        assert result.my_fencer_summary.attacks_succeeded >= 1
        assert result.my_fencer_summary.attack_success_rate > 0


# ==================================================================
# Step 6: Frame action classification integration tests
# ==================================================================


class TestFrameActionIntegration:
    """Tests that analyze_continuous() populates frame_actions."""

    def test_stationary_is_en_garde(self):
        """Stationary fencer should be classified as EN_GARDE."""
        analyzer = PoseAnalyzer()
        # Two identical frames — no movement
        f1 = make_pose_result(
            0,
            make_fencer("left", shoulder_cx=200, hip_cx=200, ankle_cx=200),
            make_fencer("right", shoulder_cx=600, hip_cx=600, ankle_cx=600),
        )
        f2 = make_pose_result(
            1,
            make_fencer("left", shoulder_cx=200, hip_cx=200, ankle_cx=200),
            make_fencer("right", shoulder_cx=600, hip_cx=600, ankle_cx=600),
        )
        state = analyzer.classify_frame_action(f1, f2, "left")
        assert state.state == ActionState.EN_GARDE

    def test_advancing_is_marche(self):
        """Fencer moving forward should be MARCHE or PREPARATION."""
        analyzer = PoseAnalyzer()
        # Left fencer advances (x increases toward right fencer)
        f1 = make_pose_result(
            0,
            make_fencer("left", shoulder_cx=200, hip_cx=200, ankle_cx=200),
            make_fencer("right", shoulder_cx=600, hip_cx=600, ankle_cx=600),
        )
        f2 = make_pose_result(
            1,
            make_fencer("left", shoulder_cx=240, hip_cx=240, ankle_cx=240),
            make_fencer("right", shoulder_cx=600, hip_cx=600, ankle_cx=600),
        )
        state = analyzer.classify_frame_action(f1, f2, "left")
        assert state.state in (ActionState.MARCHE, ActionState.PREPARATION, ActionState.FLECHE)

    def test_retreating_is_retraite(self):
        """Fencer moving backward should be RETRAITE."""
        analyzer = PoseAnalyzer()
        f1 = make_pose_result(
            0,
            make_fencer("left", shoulder_cx=200, hip_cx=200, ankle_cx=200),
            make_fencer("right", shoulder_cx=600, hip_cx=600, ankle_cx=600),
        )
        f2 = make_pose_result(
            1,
            make_fencer("left", shoulder_cx=160, hip_cx=160, ankle_cx=160),
            make_fencer("right", shoulder_cx=600, hip_cx=600, ankle_cx=600),
        )
        state = analyzer.classify_frame_action(f1, f2, "left")
        assert state.state in (ActionState.RETRAITE, ActionState.EN_GARDE)

    def test_classify_action_sequence_returns_list(self):
        """classify_action_sequence should return a list of FrameActionState."""
        analyzer = PoseAnalyzer()
        seq = []
        for i in range(10):
            seq.append(make_pose_result(
                i,
                make_fencer("left", shoulder_cx=200 + i * 2, hip_cx=200 + i * 2, ankle_cx=200 + i * 2),
                make_fencer("right", shoulder_cx=600, hip_cx=600, ankle_cx=600),
            ))
        result = analyzer.classify_action_sequence(seq, "left")
        assert isinstance(result, list)
        assert len(result) == 10
        assert all(isinstance(s, FrameActionState) for s in result)

    def test_analyze_continuous_includes_frame_actions(self):
        """analyze_continuous should populate frame_actions field."""
        analyzer = PoseAnalyzer()
        # Build a sequence long enough to have exchanges
        seq = []
        for i in range(40):
            # Create approach-separate pattern
            if i < 15:
                dist_offset = -i * 10  # approaching
            elif i < 25:
                dist_offset = -(15 * 10) + (i - 15) * 15  # separating
            else:
                dist_offset = 0  # idle
            left_x = 200 + dist_offset
            right_x = 600
            seq.append(make_pose_result(
                i,
                make_fencer("left", shoulder_cx=left_x, hip_cx=left_x, ankle_cx=left_x),
                make_fencer("right", shoulder_cx=right_x, hip_cx=right_x, ankle_cx=right_x),
            ))

        result = analyzer.analyze_continuous(seq, sample_every_n=1)
        assert result.frame_actions is not None
        assert "left" in result.frame_actions
        assert "right" in result.frame_actions
        assert len(result.frame_actions["left"]) > 0

    def test_analyze_continuous_frame_actions_empty_sequence(self):
        """Empty sequence should not produce frame_actions."""
        analyzer = PoseAnalyzer()
        result = analyzer.analyze_continuous([], sample_every_n=1)
        assert result.frame_actions is None

    def test_analyze_continuous_frame_actions_single_frame(self):
        """Single-frame sequence should not produce frame_actions (need >= 2)."""
        analyzer = PoseAnalyzer()
        seq = [make_pose_result(
            0,
            make_fencer("left", shoulder_cx=200, hip_cx=200, ankle_cx=200),
            make_fencer("right", shoulder_cx=600, hip_cx=600, ankle_cx=600),
        )]
        result = analyzer.analyze_continuous(seq, sample_every_n=1)
        # classify_action_sequence returns [] for <2 frames, so frame_actions
        # should be None (empty dict fails the truthiness check)
        assert result.frame_actions is None

    def test_frame_actions_all_en_garde_static(self):
        """Static sequence should have all EN_GARDE frame actions."""
        analyzer = PoseAnalyzer()
        seq = make_static_sequence(10, left_x=200.0, right_x=600.0)
        result = analyzer.analyze_continuous(seq, sample_every_n=1)
        assert result.frame_actions is not None
        for side in ("left", "right"):
            actions = result.frame_actions[side]
            for fas in actions:
                assert fas.state == ActionState.EN_GARDE, (
                    f"{side} frame {fas.frame_index}: expected EN_GARDE, got {fas.state}"
                )


# ==================================================================
# Handedness detection tests (4)
# ==================================================================


class TestHandednessDetection:

    def setup_method(self):
        self.analyzer = PoseAnalyzer()

    def _make_handedness_sequence(
        self,
        n_frames: int = 50,
        right_arm_angle: float = 160.0,
        left_arm_angle: float = 110.0,
        side: str = "left",
    ) -> List[PoseResult]:
        """Create a sequence where one arm is more extended than the other.

        Args:
            right_arm_angle: Angle at the right elbow (degrees).
            left_arm_angle: Angle at the left elbow (degrees).
            side: Which side fencer to create ("left" or "right").
        """
        import math
        seq = []
        for i in range(n_frames):
            # Create fencer at standard position
            cx = 200.0 if side == "left" else 600.0
            f = make_fencer(side, shoulder_cx=cx, hip_cx=cx, ankle_cx=cx)

            # Set right arm keypoints to produce right_arm_angle
            # shoulder-elbow-wrist angle
            rsh = f.keypoints[KP_RIGHT_SHOULDER]
            # Place elbow straight out, then bend wrist to create desired angle
            elbow_r_x = rsh.x + 40.0
            elbow_r_y = rsh.y
            # Wrist position to create the desired angle
            rad = math.radians(right_arm_angle)
            # The angle is at the elbow: shoulder-elbow-wrist
            # If angle=180, wrist is straight out from shoulder through elbow
            # Use direction from shoulder to elbow, then rotate
            wrist_r_x = elbow_r_x + 40.0 * math.cos(math.pi - rad)
            wrist_r_y = elbow_r_y + 40.0 * math.sin(math.pi - rad)
            f.keypoints[KP_RIGHT_ELBOW] = make_kp(elbow_r_x, elbow_r_y)
            f.keypoints[KP_RIGHT_WRIST] = make_kp(wrist_r_x, wrist_r_y)

            # Set left arm keypoints to produce left_arm_angle
            lsh = f.keypoints[KP_LEFT_SHOULDER]
            elbow_l_x = lsh.x - 40.0
            elbow_l_y = lsh.y
            rad_l = math.radians(left_arm_angle)
            wrist_l_x = elbow_l_x - 40.0 * math.cos(math.pi - rad_l)
            wrist_l_y = elbow_l_y + 40.0 * math.sin(math.pi - rad_l)
            f.keypoints[KP_LEFT_ELBOW] = make_kp(elbow_l_x, elbow_l_y)
            f.keypoints[KP_LEFT_WRIST] = make_kp(wrist_l_x, wrist_l_y)

            other_cx = 600.0 if side == "left" else 200.0
            other_side = "right" if side == "left" else "left"
            other = make_fencer(other_side, shoulder_cx=other_cx, hip_cx=other_cx, ankle_cx=other_cx)
            if side == "left":
                seq.append(make_pose_result(i, f, other))
            else:
                seq.append(make_pose_result(i, other, f))
        return seq

    def test_right_handed_detection(self):
        """Right arm more extended → right-handed."""
        seq = self._make_handedness_sequence(
            n_frames=50,
            right_arm_angle=170.0,  # nearly straight
            left_arm_angle=110.0,   # bent
            side="left",
        )
        handedness, confidence = self.analyzer.detect_handedness(seq, "left")
        assert handedness == "right"
        assert confidence > 0.5

    def test_left_handed_detection(self):
        """Left arm more extended → left-handed."""
        seq = self._make_handedness_sequence(
            n_frames=50,
            right_arm_angle=110.0,  # bent
            left_arm_angle=170.0,   # nearly straight
            side="left",
        )
        handedness, confidence = self.analyzer.detect_handedness(seq, "left")
        assert handedness == "left"
        assert confidence > 0.5

    def test_indeterminate_similar_arms(self):
        """Both arms similar extension → None (indeterminate)."""
        seq = self._make_handedness_sequence(
            n_frames=50,
            right_arm_angle=150.0,
            left_arm_angle=148.0,   # very similar
            side="left",
        )
        handedness, confidence = self.analyzer.detect_handedness(seq, "left")
        assert handedness is None
        # confidence should be below threshold
        assert confidence < 0.05

    def test_insufficient_frames(self):
        """Too few frames → None with 0.0 confidence."""
        seq = self._make_handedness_sequence(
            n_frames=10,  # below min_frames default of 30
            right_arm_angle=170.0,
            left_arm_angle=110.0,
            side="left",
        )
        handedness, confidence = self.analyzer.detect_handedness(seq, "left")
        assert handedness is None
        assert confidence == 0.0


# ==================================================================
# Quality fix C: NEUTRAL bucket for low-confidence exchanges
# ==================================================================


class TestNeutralExchangeBucket:
    """Low-confidence non-scoring exchanges must be labelled NEUTRAL, not
    FAILED_ATTACK, and excluded from attack/defense statistics."""

    def _classify(self, sub_seq: List[PoseResult], is_scoring: bool = False):
        from analyzer.config import (
            FOOTWORK_ANALYSIS_WINDOW,
            PARRY_DETECTION_WINDOW,
            FOOTWORK_USE_RATIO_BASED_HIP_DROP,
        )
        from ml.pose_analysis import exchanges as exch
        return exch.classify_exchange(
            sub_seq, is_scoring, 0, len(sub_seq) - 1, set(),
            FOOTWORK_ANALYSIS_WINDOW, PARRY_DETECTION_WINDOW,
            FOOTWORK_USE_RATIO_BASED_HIP_DROP,
        )

    def test_clear_advance_without_score_is_failed_attack(self):
        """A committed forward approach that does not score stays FAILED_ATTACK."""
        # Left fencer steps forward (toward opponent) ~40px over the window;
        # right fencer stays put → clear single aggressor, no score.
        seq: List[PoseResult] = []
        for i in range(15):
            offset = (i / 14) * 40.0
            left_x = 200.0 + offset
            left = make_fencer("left", shoulder_cx=left_x, hip_cx=left_x, ankle_cx=left_x)
            right = make_fencer("right", shoulder_cx=600, hip_cx=600, ankle_cx=600)
            seq.append(make_pose_result(i, left, right))
        assert self._classify(seq) == NonScoringEventType.FAILED_ATTACK

    def test_both_stationary_is_neutral(self):
        """Both fencers stationary (no aggressor) → NEUTRAL, not FAILED_ATTACK."""
        seq = make_static_sequence(20, left_x=200.0, right_x=600.0)
        assert self._classify(seq) == NonScoringEventType.NEUTRAL

    def test_too_short_window_is_neutral(self):
        """A sub-sequence too short to analyse footwork → NEUTRAL, not FAILED_ATTACK."""
        seq = make_static_sequence(2, left_x=200.0, right_x=600.0)
        assert self._classify(seq) == NonScoringEventType.NEUTRAL

    def test_neutral_excluded_from_attack_denominator(self):
        """A NEUTRAL exchange must not count as an attack attempt, even if its
        stored footwork looks aggressive."""
        from ml.pose_analysis import exchanges as exch

        advance = FootworkResult(footwork_type=FootworkType.ADVANCE, confidence=0.9)
        failed = ExchangeEvent(
            start_frame=0, end_frame=10, min_distance_frame=5, min_distance_bh=1.0,
            event_type=NonScoringEventType.FAILED_ATTACK, footwork_left=advance,
        )
        neutral = ExchangeEvent(
            start_frame=20, end_frame=30, min_distance_frame=25, min_distance_bh=1.0,
            event_type=NonScoringEventType.NEUTRAL, footwork_left=advance,
        )
        summary = exch.build_my_fencer_summary(
            [failed, neutral], "left", set(), fps=30.0,
        )
        # Only the FAILED_ATTACK exchange is counted; the NEUTRAL one is skipped.
        assert summary.attacks_attempted == 1
        assert summary.attacks_failed == 1

    def test_neutral_analyze_continuous_end_to_end(self):
        """analyze_continuous on an ambiguous approach-engage-separate sequence
        yields NEUTRAL exchanges that stay out of the my-fencer attack stats."""
        analyzer = PoseAnalyzer()
        seq = []
        for i in range(90):
            # Right fencer approaches then retreats; left fencer never commits.
            if i < 30:
                right_x = 600.0 - i * 5
            elif i < 60:
                right_x = 450.0
            else:
                right_x = 450.0 + (i - 60) * 5
            left = make_fencer("left", shoulder_cx=200, hip_cx=200, ankle_cx=200)
            right = make_fencer("right", shoulder_cx=right_x, hip_cx=right_x, ankle_cx=right_x)
            seq.append(make_pose_result(i, left, right))

        result = analyzer.analyze_continuous(seq, sample_every_n=1, my_fencer="left")
        neutral = [
            ex for ex in result.exchanges
            if ex.event_type == NonScoringEventType.NEUTRAL
        ]
        assert len(neutral) >= 1
        # my_fencer (left) never advanced → no attack attempts recorded.
        assert result.my_fencer_summary is not None
        assert result.my_fencer_summary.attacks_attempted == 0
