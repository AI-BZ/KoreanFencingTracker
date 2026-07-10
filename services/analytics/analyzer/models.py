"""
Data models for the fencing video analyzer.

Phase 1: ScoreState, StableScore, LampState, MatchEvent, EventType, MatchClock
Phase 2: PoseKeypoint, FencerPose, PoseResult, FencingAction, ActionPrediction,
         ActionResult, EnrichedMatchEvent
Phase 5c: FootworkType, DistanceZone, FootworkResult, ParryResult,
          DistanceResult, PoseAnalysisResult
Phase 6:  NonScoringEventType, ExchangePhase, JointAngles, ExchangeEvent,
          MyFencerSummary, ContinuousAnalysisResult
Phase 7:  PhraseAnnotation
"""

from dataclasses import dataclass, asdict, field
from enum import Enum
from typing import Dict, Optional, List


class EventType(Enum):
    SINGLE_TOUCH = "single_touch"
    SIMULTANEOUS = "simultaneous"
    PENALTY_POINT = "penalty_point"
    INVALID_TOUCH = "invalid_touch"


@dataclass
class ScoreState:
    left: int = 0
    right: int = 0


@dataclass
class StableScore:
    """Stabilized score (starts from 0, changes only by +1)."""
    left: int = 0
    right: int = 0
    last_read_left: Optional[int] = None
    last_read_right: Optional[int] = None
    read_count_left: int = 0
    read_count_right: int = 0


@dataclass
class MatchClock:
    minutes: int = 3
    seconds: int = 0

    def __str__(self):
        return f"{self.minutes}:{self.seconds:02d}"


@dataclass
class LampState:
    red: bool = False
    green: bool = False
    red_pixels: int = 0
    green_pixels: int = 0


@dataclass
class MatchEvent:
    frame: int
    video_timestamp: str
    match_time: str
    event_type: str
    lamp_red: bool
    lamp_green: bool
    score_before: str
    score_after: str
    scorer: Optional[str]
    description: str

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------
# Phase 2: Pose Estimation models
# ------------------------------------------------------------------


@dataclass
class PoseKeypoint:
    """Single COCO 17-joint keypoint."""
    x: float
    y: float
    confidence: float


@dataclass
class FencerPose:
    """Pose data for one detected fencer."""
    keypoints: List[PoseKeypoint]  # 17 COCO joints
    bbox: List[float]  # [x1, y1, x2, y2]
    person_confidence: float
    side: Optional[str] = None  # "left" or "right" (assigned by x-center)

    def to_dict(self) -> dict:
        return {
            "keypoints": [[kp.x, kp.y, kp.confidence] for kp in self.keypoints],
            "bbox": self.bbox,
            "person_confidence": self.person_confidence,
            "side": self.side,
        }


@dataclass
class PoseResult:
    """Pose estimation result for a single frame."""
    frame_idx: int
    fencers: List[FencerPose]
    inference_time_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "frame_idx": self.frame_idx,
            "fencers": [f.to_dict() for f in self.fencers],
            "inference_time_ms": self.inference_time_ms,
        }


# ------------------------------------------------------------------
# Phase 2: Action Recognition models
# ------------------------------------------------------------------


class Weapon(Enum):
    """Fencing weapon types (3종목)."""
    FOIL = "foil"          # 플뢰레 — 유효면: 몸통, 우선권 있음
    EPEE = "epee"          # 에페 — 유효면: 전신, 우선권 없음
    SABRE = "sabre"        # 사브르 — 유효면: 상반신, 우선권 있음
    UNKNOWN = "unknown"


class FencingAction(Enum):
    """9 core fencing actions + UNKNOWN.

    Blade actions (FACTS dataset):
      ATTACK, RIPOSTE, COUNTER_ATTACK, REMISE
    Footwork/defense actions (Phase 4 pose trajectory):
      PARRY, LUNGE, FLECHE, RETREAT, ADVANCE
    """
    ATTACK = "attack"
    PARRY = "parry"
    RIPOSTE = "riposte"
    LUNGE = "lunge"
    FLECHE = "fleche"
    RETREAT = "retreat"
    ADVANCE = "advance"
    COUNTER_ATTACK = "counter_attack"
    REMISE = "remise"
    UNKNOWN = "unknown"


@dataclass
class ActionPrediction:
    """Single action prediction with confidence."""
    action: FencingAction
    confidence: float
    direction: Optional[str] = None  # "left" or "right" (from FACTS encoding)

    def to_dict(self) -> dict:
        d: dict = {
            "action": self.action.value,
            "confidence": self.confidence,
        }
        if self.direction is not None:
            d["direction"] = self.direction
        return d


@dataclass
class ActionResult:
    """Action classification result for a clip segment."""
    start_frame: int
    end_frame: int
    left_fencer: Optional[ActionPrediction] = None
    right_fencer: Optional[ActionPrediction] = None

    def to_dict(self) -> dict:
        d: dict = {
            "start_frame": self.start_frame,
            "end_frame": self.end_frame,
        }
        if self.left_fencer is not None:
            d["left_fencer"] = self.left_fencer.to_dict()
        if self.right_fencer is not None:
            d["right_fencer"] = self.right_fencer.to_dict()
        return d


# ------------------------------------------------------------------
# Phase 2: Enriched Match Event
# ------------------------------------------------------------------


@dataclass
class EnrichedMatchEvent:
    """
    MatchEvent enriched with pose and action data.

    Does NOT inherit from MatchEvent (dataclass default field ordering).
    Use from_match_event() factory to convert.
    """
    # Base fields (from MatchEvent)
    frame: int
    video_timestamp: str
    match_time: str
    event_type: str
    lamp_red: bool
    lamp_green: bool
    score_before: str
    score_after: str
    scorer: Optional[str] = None
    description: str = ""

    # Weapon type (종목)
    weapon: Optional[Weapon] = None

    # Phase 2 enrichment
    pose_left: Optional[FencerPose] = None
    pose_right: Optional[FencerPose] = None
    action_left: Optional[ActionPrediction] = None
    action_right: Optional[ActionPrediction] = None
    pose_sequence: List[PoseResult] = field(default_factory=list)
    action_result: Optional[ActionResult] = None

    @classmethod
    def from_match_event(cls, event: MatchEvent) -> "EnrichedMatchEvent":
        """Create EnrichedMatchEvent from an existing MatchEvent."""
        return cls(
            frame=event.frame,
            video_timestamp=event.video_timestamp,
            match_time=event.match_time,
            event_type=event.event_type,
            lamp_red=event.lamp_red,
            lamp_green=event.lamp_green,
            score_before=event.score_before,
            score_after=event.score_after,
            scorer=event.scorer,
            description=event.description,
        )

    # Phase 5c: Pose-based analysis
    pose_analysis: Optional["PoseAnalysisResult"] = None

    def to_dict(self) -> dict:
        """Serialize to dict. Omits None pose/action fields for backward compat."""
        d: dict = {
            "frame": self.frame,
            "video_timestamp": self.video_timestamp,
            "match_time": self.match_time,
            "event_type": self.event_type,
            "lamp_red": self.lamp_red,
            "lamp_green": self.lamp_green,
            "score_before": self.score_before,
            "score_after": self.score_after,
            "scorer": self.scorer,
            "description": self.description,
        }
        if self.weapon is not None:
            d["weapon"] = self.weapon.value
        if self.pose_left is not None:
            d["pose_left"] = self.pose_left.to_dict()
        if self.pose_right is not None:
            d["pose_right"] = self.pose_right.to_dict()
        if self.action_left is not None:
            d["action_left"] = self.action_left.to_dict()
        if self.action_right is not None:
            d["action_right"] = self.action_right.to_dict()
        if self.pose_sequence:
            d["pose_sequence"] = [p.to_dict() for p in self.pose_sequence]
        if self.action_result is not None:
            d["action_result"] = self.action_result.to_dict()
        if self.pose_analysis is not None:
            d["pose_analysis"] = self.pose_analysis.to_dict()
        return d


# ------------------------------------------------------------------
# Phase 5c: Pose-based Analysis models (footwork, parry, distance)
# ------------------------------------------------------------------


class FootworkType(Enum):
    """Footwork classification from pose trajectory."""
    LUNGE = "lunge"            # Rear foot fixed + front foot forward + hip drop
    FLECHE = "fleche"          # Both feet advance + body lean + running
    ADVANCE = "advance"        # Sequential forward steps
    RETREAT = "retreat"        # Sequential backward steps
    STATIONARY = "stationary"  # No movement
    UNKNOWN = "unknown"


class DistanceZone(Enum):
    """Distance zone between fencers in Body Height (BH) units."""
    OUT_OF_DISTANCE = "out_of_distance"    # >1.8 BH — safe, preparation
    ADVANCE_LUNGE = "advance_lunge"        # 1.5-1.8 BH — attack initiation
    LUNGE = "lunge"                        # 1.2-1.5 BH — danger zone
    EXTENSION = "extension"                # 0.8-1.2 BH — arm extension only
    INFIGHTING = "infighting"              # <0.8 BH — corps-a-corps risk


@dataclass
class FootworkResult:
    """Footwork detection result for one fencer."""
    footwork_type: FootworkType
    confidence: float
    hip_drop_px: float = 0.0
    front_foot_displacement_px: float = 0.0
    rear_foot_displacement_px: float = 0.0

    def to_dict(self) -> dict:
        return {
            "footwork_type": self.footwork_type.value,
            "confidence": round(self.confidence, 3),
            "hip_drop_px": round(self.hip_drop_px, 1),
            "front_foot_displacement_px": round(self.front_foot_displacement_px, 1),
            "rear_foot_displacement_px": round(self.rear_foot_displacement_px, 1),
        }


@dataclass
class ParryResult:
    """Parry detection result for one fencer."""
    parry_detected: bool
    confidence: float
    wrist_lateral_displacement_px: float = 0.0
    parry_frame_idx: Optional[int] = None

    def to_dict(self) -> dict:
        d: dict = {
            "parry_detected": self.parry_detected,
            "confidence": round(self.confidence, 3),
            "wrist_lateral_displacement_px": round(self.wrist_lateral_displacement_px, 1),
        }
        if self.parry_frame_idx is not None:
            d["parry_frame_idx"] = self.parry_frame_idx
        return d


@dataclass
class DistanceResult:
    """Distance measurement between two fencers."""
    distance_bh: float
    distance_zone: DistanceZone
    closing_speed_bh: float = 0.0  # BH/sec, positive=closing

    def to_dict(self) -> dict:
        return {
            "distance_bh": round(self.distance_bh, 3),
            "distance_zone": self.distance_zone.value,
            "closing_speed_bh": round(self.closing_speed_bh, 3),
        }


@dataclass
class JointAngles:
    """2D joint angles computed from COCO keypoints (degrees)."""
    hip_angle: Optional[float] = None            # shoulder-hip-knee angle
    front_knee_angle: Optional[float] = None     # hip-knee-ankle (front leg)
    rear_knee_angle: Optional[float] = None      # hip-knee-ankle (rear leg)
    trunk_lean_deg: Optional[float] = None       # trunk deviation from vertical
    arm_extension_ratio: Optional[float] = None  # elbow angle / 180 (0~1)

    def to_dict(self) -> dict:
        d: dict = {}
        if self.hip_angle is not None:
            d["hip_angle"] = round(self.hip_angle, 1)
        if self.front_knee_angle is not None:
            d["front_knee_angle"] = round(self.front_knee_angle, 1)
        if self.rear_knee_angle is not None:
            d["rear_knee_angle"] = round(self.rear_knee_angle, 1)
        if self.trunk_lean_deg is not None:
            d["trunk_lean_deg"] = round(self.trunk_lean_deg, 1)
        if self.arm_extension_ratio is not None:
            d["arm_extension_ratio"] = round(self.arm_extension_ratio, 3)
        return d


@dataclass
class JointKinematics:
    """Per-joint velocity and acceleration for a frame pair."""
    joint_name: str
    velocity_px: float = 0.0      # px/frame
    velocity_bh: float = 0.0      # BH/frame (normalized)
    acceleration_px: float = 0.0  # px/frame²

    def to_dict(self) -> dict:
        return {
            "joint_name": self.joint_name,
            "velocity_px": round(self.velocity_px, 2),
            "velocity_bh": round(self.velocity_bh, 3),
            "acceleration_px": round(self.acceleration_px, 2),
        }


@dataclass
class FrameKinematics:
    """Kinematics for all tracked joints at a given frame."""
    frame_index: int
    joints: Dict[str, JointKinematics] = field(default_factory=dict)
    max_velocity_px: float = 0.0
    dominant_joint: str = ""  # joint with max velocity

    def to_dict(self) -> dict:
        return {
            "frame_index": self.frame_index,
            "joints": {k: v.to_dict() for k, v in self.joints.items()},
            "max_velocity_px": round(self.max_velocity_px, 2),
            "dominant_joint": self.dominant_joint,
        }


@dataclass
class PoseAnalysisResult:
    """Complete pose-based analysis result for a touch event."""
    footwork_left: Optional[FootworkResult] = None
    footwork_right: Optional[FootworkResult] = None
    parry_left: Optional[ParryResult] = None
    parry_right: Optional[ParryResult] = None
    distance_at_touch: Optional[DistanceResult] = None
    suggested_label: Optional[str] = None
    suggestion_confidence: float = 0.0
    suggestion_reasoning: str = ""
    # Phase 6: joint angles and my_fencer narrative
    joint_angles_left: Optional[JointAngles] = None
    joint_angles_right: Optional[JointAngles] = None
    my_fencer_narrative: str = ""

    def to_dict(self) -> dict:
        d: dict = {}
        if self.footwork_left is not None:
            d["footwork_left"] = self.footwork_left.to_dict()
        if self.footwork_right is not None:
            d["footwork_right"] = self.footwork_right.to_dict()
        if self.parry_left is not None:
            d["parry_left"] = self.parry_left.to_dict()
        if self.parry_right is not None:
            d["parry_right"] = self.parry_right.to_dict()
        if self.distance_at_touch is not None:
            d["distance_at_touch"] = self.distance_at_touch.to_dict()
        if self.suggested_label is not None:
            d["suggested_label"] = self.suggested_label
        d["suggestion_confidence"] = round(self.suggestion_confidence, 3)
        if self.suggestion_reasoning:
            d["suggestion_reasoning"] = self.suggestion_reasoning
        if self.joint_angles_left is not None:
            d["joint_angles_left"] = self.joint_angles_left.to_dict()
        if self.joint_angles_right is not None:
            d["joint_angles_right"] = self.joint_angles_right.to_dict()
        if self.my_fencer_narrative:
            d["my_fencer_narrative"] = self.my_fencer_narrative
        return d


# ------------------------------------------------------------------
# Phase 6: Continuous Analysis models (exchange, non-scoring events)
# ------------------------------------------------------------------


class NonScoringEventType(Enum):
    """Exchange outcome labels.

    Most values describe non-scoring exchanges. Two are special:
      UNKNOWN_EXCHANGE — a scoring exchange (a touch landed) whose scorer
        attribution is not resolved here; the scoring label lives in the
        touch analysis. It is NOT a low-confidence marker.
      NEUTRAL — a low-confidence non-scoring exchange with no clear aggressor
        (both fencers stationary/unknown, or the window is too short to
        analyse). Excluded from attack/defense stats so noise exchanges do
        not get counted as failed attacks or successful defenses.
    """
    FAILED_ATTACK = "failed_attack"
    SUCCESSFUL_DEFENSE = "successful_defense"
    MUTUAL_RETREAT = "mutual_retreat"
    OFF_TARGET = "off_target"
    MISSED_ENTIRELY = "missed_entirely"
    UNKNOWN_EXCHANGE = "unknown_exchange"
    NEUTRAL = "neutral"


class ExchangePhase(Enum):
    """State machine phases for exchange detection."""
    APPROACH = "approach"
    ENGAGEMENT = "engagement"
    SEPARATION = "separation"


@dataclass
class ExchangeEvent:
    """A single exchange (scoring or non-scoring) between fencers."""
    start_frame: int
    end_frame: int
    min_distance_frame: int
    min_distance_bh: float
    event_type: NonScoringEventType
    footwork_left: Optional[FootworkResult] = None
    footwork_right: Optional[FootworkResult] = None
    parry_left: Optional[ParryResult] = None
    parry_right: Optional[ParryResult] = None
    joint_angles_left: Optional[JointAngles] = None
    joint_angles_right: Optional[JointAngles] = None
    kinematics_left: Optional[List[FrameKinematics]] = None
    kinematics_right: Optional[List[FrameKinematics]] = None

    def to_dict(self) -> dict:
        d: dict = {
            "start_frame": self.start_frame,
            "end_frame": self.end_frame,
            "min_distance_frame": self.min_distance_frame,
            "min_distance_bh": round(self.min_distance_bh, 3),
            "event_type": self.event_type.value,
        }
        if self.footwork_left is not None:
            d["footwork_left"] = self.footwork_left.to_dict()
        if self.footwork_right is not None:
            d["footwork_right"] = self.footwork_right.to_dict()
        if self.parry_left is not None:
            d["parry_left"] = self.parry_left.to_dict()
        if self.parry_right is not None:
            d["parry_right"] = self.parry_right.to_dict()
        if self.joint_angles_left is not None:
            d["joint_angles_left"] = self.joint_angles_left.to_dict()
        if self.joint_angles_right is not None:
            d["joint_angles_right"] = self.joint_angles_right.to_dict()
        if self.kinematics_left is not None:
            d["kinematics_left"] = [fk.to_dict() for fk in self.kinematics_left]
        if self.kinematics_right is not None:
            d["kinematics_right"] = [fk.to_dict() for fk in self.kinematics_right]
        return d


@dataclass
class MyFencerSummary:
    """Aggregated stats from my_fencer's perspective."""
    side: str  # "left" or "right"
    attacks_attempted: int = 0
    attacks_succeeded: int = 0
    attacks_failed: int = 0
    defenses_attempted: int = 0
    defenses_succeeded: int = 0
    attack_success_rate: float = 0.0
    defense_success_rate: float = 0.0
    narratives: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "side": self.side,
            "attacks_attempted": self.attacks_attempted,
            "attacks_succeeded": self.attacks_succeeded,
            "attacks_failed": self.attacks_failed,
            "defenses_attempted": self.defenses_attempted,
            "defenses_succeeded": self.defenses_succeeded,
            "attack_success_rate": round(self.attack_success_rate, 3),
            "defense_success_rate": round(self.defense_success_rate, 3),
            "narratives": self.narratives,
        }


class ActionState(Enum):
    """Per-frame action state classification."""
    EN_GARDE = "en_garde"
    MARCHE = "marche"
    RETRAITE = "retraite"
    FENTE = "fente"
    FLECHE = "fleche"
    PARADE = "parade"
    RIPOSTE = "riposte"
    PREPARATION = "preparation"
    RECOVERY = "recovery"
    UNKNOWN = "unknown"


@dataclass
class FrameActionState:
    """Action state for a single frame."""
    frame_index: int
    state: ActionState
    confidence: float = 0.0
    velocity_max: float = 0.0
    distance_bh: Optional[float] = None

    def to_dict(self) -> dict:
        d: dict = {
            "frame_index": self.frame_index,
            "state": self.state.value,
            "confidence": round(self.confidence, 2),
        }
        if self.distance_bh is not None:
            d["distance_bh"] = round(self.distance_bh, 3)
        return d


@dataclass
class ContinuousAnalysisResult:
    """Result of analyzing the full bout (not just scoring moments)."""
    exchanges: List[ExchangeEvent] = field(default_factory=list)
    total_exchanges: int = 0
    scoring_exchanges: int = 0
    non_scoring_exchanges: int = 0
    my_fencer_summary: Optional[MyFencerSummary] = None
    frame_actions: Optional[Dict[str, List[FrameActionState]]] = None

    def to_dict(self) -> dict:
        d: dict = {
            "total_exchanges": self.total_exchanges,
            "scoring_exchanges": self.scoring_exchanges,
            "non_scoring_exchanges": self.non_scoring_exchanges,
            "exchanges": [e.to_dict() for e in self.exchanges],
        }
        if self.my_fencer_summary is not None:
            d["my_fencer_summary"] = self.my_fencer_summary.to_dict()
        if self.frame_actions is not None:
            d["frame_actions"] = {
                side: [fa.to_dict() for fa in states]
                for side, states in self.frame_actions.items()
            }
        return d


# ==================================================================
# Phase 7: Phrase Boundary Annotation
# ==================================================================


@dataclass
class PhraseAnnotation:
    """A single phrase d'armes annotation for dataset generation."""
    video_id: str
    phrase_id: int
    start_frame: int
    end_frame: int
    start_time: str           # "M:SS"
    end_time: str
    trigger: str              # "distance", "clock", "scoring"
    outcome: str              # "touch_left", "touch_right", "halt", "off_target"
    action_sequence: List[str] = field(default_factory=list)
    confidence: float = 0.0
    reviewed: bool = False    # human review status

    def to_dict(self) -> dict:
        return asdict(self)
