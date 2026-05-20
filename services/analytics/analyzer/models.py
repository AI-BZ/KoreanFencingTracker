"""
Data models for the fencing video analyzer.

Extracted from fencing_analyzer_v3.py — all dataclasses and enums
used across the analyzer modules.
"""

from dataclasses import dataclass, asdict
from enum import Enum
from typing import Optional


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
