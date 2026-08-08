"""
Data models for TV broadcast fencing analysis.

TV broadcast analysis extracts technique clips from professional
bouts for educational purposes, rather than match scoring.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple


@dataclass
class TechniqueClip:
    """A single technique extracted from a TV broadcast segment."""
    start_frame: int
    end_frame: int
    duration_sec: float
    action: str                    # FencingAction value
    confidence: float
    fencer_side: str               # "left" or "right"
    camera_angle: str = "wide"     # "wide", "medium", "close"
    quality_score: float = 0.0     # 0-1 usability for education

    def to_dict(self) -> dict:
        return {
            "start_frame": self.start_frame,
            "end_frame": self.end_frame,
            "duration_sec": round(self.duration_sec, 2),
            "action": self.action,
            "confidence": round(self.confidence, 3),
            "fencer_side": self.fencer_side,
            "camera_angle": self.camera_angle,
            "quality_score": round(self.quality_score, 2),
        }


@dataclass
class TechniqueCollection:
    """Grouped techniques of the same action type."""
    action: str                    # FencingAction value
    clips: List[TechniqueClip] = field(default_factory=list)
    best_example_idx: int = 0     # Index of highest quality clip
    count: int = 0

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "count": self.count,
            "best_example_idx": self.best_example_idx,
            "clips": [c.to_dict() for c in self.clips],
        }


@dataclass
class TVAnalysisResult:
    """Complete analysis result from a TV broadcast video."""
    video_path: str
    total_bout_segments: int = 0
    total_techniques_extracted: int = 0
    techniques: List[TechniqueCollection] = field(default_factory=list)
    action_distribution: Dict[str, int] = field(default_factory=dict)
    scene_cuts: List[int] = field(default_factory=list)
    bout_segments: List[Tuple[int, int]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "video_path": self.video_path,
            "total_bout_segments": self.total_bout_segments,
            "total_techniques_extracted": self.total_techniques_extracted,
            "techniques": [t.to_dict() for t in self.techniques],
            "action_distribution": self.action_distribution,
            "scene_cuts_count": len(self.scene_cuts),
            "bout_segments_count": len(self.bout_segments),
        }
