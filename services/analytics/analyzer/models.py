"""
Data models for the fencing video analyzer.

Phase 1: ScoreState, StableScore, LampState, MatchEvent, EventType, MatchClock
Phase 2: PoseKeypoint, FencerPose, PoseResult, FencingAction, ActionPrediction,
         ActionResult, EnrichedMatchEvent
"""

from dataclasses import dataclass, asdict, field
from enum import Enum
from typing import Optional, List


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
        return d
