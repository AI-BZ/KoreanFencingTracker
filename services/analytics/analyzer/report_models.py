"""
Data models for fencing match analysis reports.

Converts raw EnrichedMatchEvent data into structured report format
suitable for rendering as HTML dashboard, PDF export, or JSON API response.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict


@dataclass
class TouchDetail:
    """Single touch (scoring event) detail for report."""
    touch_number: int
    frame: int
    video_timestamp: str
    match_time: str
    scorer: Optional[str]          # "left" or "right"
    score_after: str               # e.g. "3-2"
    action_scorer: Optional[str]   # FencingAction value: "lunge", "attack", etc.
    action_confidence: float = 0.0
    action_opponent: Optional[str] = None
    opponent_confidence: float = 0.0
    description: str = ""


@dataclass
class ActionDistribution:
    """Action frequency distribution for a fencer."""
    action: str        # FencingAction value
    count: int
    percentage: float  # 0-100


@dataclass
class FencerStats:
    """Per-fencer statistics derived from match analysis."""
    side: str  # "left" or "right"
    total_touches_scored: int = 0
    total_touches_conceded: int = 0

    # Action distribution
    action_distribution: List[ActionDistribution] = field(default_factory=list)
    most_common_action: Optional[str] = None
    most_common_action_pct: float = 0.0

    # Pose-derived metrics
    avg_distance_at_touch: Optional[float] = None  # pixels between fencers

    def to_dict(self) -> dict:
        d: dict = {
            "side": self.side,
            "total_touches_scored": self.total_touches_scored,
            "total_touches_conceded": self.total_touches_conceded,
            "action_distribution": [
                {"action": a.action, "count": a.count, "percentage": a.percentage}
                for a in self.action_distribution
            ],
            "most_common_action": self.most_common_action,
            "most_common_action_pct": self.most_common_action_pct,
        }
        if self.avg_distance_at_touch is not None:
            d["avg_distance_at_touch"] = self.avg_distance_at_touch
        return d


@dataclass
class CoachingInsight:
    """Auto-generated coaching point from pattern detection."""
    category: str     # "action_pattern", "defense_weakness", "distance", "tempo"
    target: str       # "left" or "right" fencer
    message: str      # Human-readable insight
    severity: str     # "info", "warning", "suggestion"
    evidence: str     # Data backing the insight

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "target": self.target,
            "message": self.message,
            "severity": self.severity,
            "evidence": self.evidence,
        }


@dataclass
class MatchSummary:
    """High-level match overview."""
    video_path: str
    weapon: Optional[str] = None   # "foil", "epee", "sabre", or None
    final_score_left: int = 0
    final_score_right: int = 0
    total_touches: int = 0
    match_duration: str = ""       # "3:00" or total match time
    total_frames_analyzed: int = 0
    analysis_time_sec: float = 0.0

    def to_dict(self) -> dict:
        d: dict = {
            "video_path": self.video_path,
            "final_score": f"{self.final_score_left}-{self.final_score_right}",
            "total_touches": self.total_touches,
            "match_duration": self.match_duration,
            "total_frames_analyzed": self.total_frames_analyzed,
            "analysis_time_sec": self.analysis_time_sec,
        }
        if self.weapon:
            d["weapon"] = self.weapon
        return d


@dataclass
class ReportMeta:
    """Analysis metadata for reproducibility."""
    phase: int = 2
    pose_model: str = "yolo11n-pose"
    action_model: str = "videomae-kinetics400"
    pose_enabled: bool = True
    action_enabled: bool = True
    confidence_threshold: float = 0.4
    source_type: Optional[str] = None  # Video source type used for analysis

    def to_dict(self) -> dict:
        d: dict = {
            "phase": self.phase,
            "pose_model": self.pose_model,
            "action_model": self.action_model,
            "pose_enabled": self.pose_enabled,
            "action_enabled": self.action_enabled,
            "confidence_threshold": self.confidence_threshold,
        }
        if self.source_type is not None:
            d["source_type"] = self.source_type
        return d


@dataclass
class MatchReport:
    """
    Complete match analysis report.

    Central data structure that feeds into all output formats:
    JSON API, HTML dashboard, PDF export.
    """
    summary: MatchSummary
    touches: List[TouchDetail] = field(default_factory=list)
    left_fencer: Optional[FencerStats] = None
    right_fencer: Optional[FencerStats] = None
    insights: List[CoachingInsight] = field(default_factory=list)
    meta: ReportMeta = field(default_factory=ReportMeta)

    def to_dict(self) -> dict:
        d: dict = {
            "summary": self.summary.to_dict(),
            "touches": [
                {
                    "touch_number": t.touch_number,
                    "frame": t.frame,
                    "video_timestamp": t.video_timestamp,
                    "match_time": t.match_time,
                    "scorer": t.scorer,
                    "score_after": t.score_after,
                    "action_scorer": t.action_scorer,
                    "action_confidence": t.action_confidence,
                    "action_opponent": t.action_opponent,
                    "opponent_confidence": t.opponent_confidence,
                    "description": t.description,
                }
                for t in self.touches
            ],
            "meta": self.meta.to_dict(),
        }
        if self.left_fencer is not None:
            d["left_fencer"] = self.left_fencer.to_dict()
        if self.right_fencer is not None:
            d["right_fencer"] = self.right_fencer.to_dict()
        if self.insights:
            d["insights"] = [i.to_dict() for i in self.insights]
        return d
