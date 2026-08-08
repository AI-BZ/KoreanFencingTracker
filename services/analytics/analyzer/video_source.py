"""
Video source type classification for fencing match videos.

Defines video source categories and assessment data for routing
to the appropriate analysis pipeline.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple, List


class VideoSourceType(Enum):
    """Classification of fencing video source types."""
    COACH = "coach"              # Piste-side tripod, stable, full scoreboard
    PARENT = "parent"            # Spectator stand, phone, partial view
    PLAYER = "player"            # Self-recorded, 1 person, no scoreboard
    TV_BROADCAST = "tv_broadcast"  # FIE/competition broadcast, scene cuts
    UNKNOWN = "unknown"


@dataclass
class VideoSourceAssessment:
    """Assessment result from video source detection."""
    source_type: VideoSourceType
    confidence: float
    scene_cuts_per_minute: float
    avg_fencer_height_ratio: float  # Fencer height / frame height
    scoreboard_detected: bool
    overlay_detected: bool
    avg_person_count: float
    stability_score: float       # 0=shaky, 1=tripod-stable
    resolution: Tuple[int, int]  # (width, height)
    fps: float
    duration_sec: float

    def to_dict(self) -> dict:
        return {
            "source_type": self.source_type.value,
            "confidence": round(self.confidence, 3),
            "scene_cuts_per_minute": round(self.scene_cuts_per_minute, 2),
            "avg_fencer_height_ratio": round(self.avg_fencer_height_ratio, 3),
            "scoreboard_detected": self.scoreboard_detected,
            "overlay_detected": self.overlay_detected,
            "avg_person_count": round(self.avg_person_count, 2),
            "stability_score": round(self.stability_score, 3),
            "resolution": list(self.resolution),
            "fps": round(self.fps, 2),
            "duration_sec": round(self.duration_sec, 2),
        }
