"""Weapon-specific interpretation layered on top of the shared pose analysis.

The layer below (``PoseEstimator`` → ``PoseAnalyzer`` → exchanges) records what
happened without knowing the weapon. Everything that depends on the rules of a
particular weapon lives here, reading the serialized exchange dicts rather than
pose objects so that it can also run against a stored report.

Foil is the only weapon implemented. Sabre also has priority but is a separate
judge, not a re-parameterised foil one: its phrases routinely finish inside 0.5s,
which is the same order as the pipeline's sampling-plus-smoothing resolution, and
its priority turns on blade actions this pipeline cannot see. Epee has no
priority at all and is excluded permanently.
"""

from ml.weapon_analyzers.foil import (
    FoilPriorityJudge,
    PriorityCall,
    build_priority_judge,
    compute_session_baselines,
)

__all__ = [
    "FoilPriorityJudge",
    "PriorityCall",
    "build_priority_judge",
    "compute_session_baselines",
]
