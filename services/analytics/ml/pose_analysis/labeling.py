"""Action-label suggestion and my-fencer narrative (pure functions)."""

from typing import Optional, Tuple

from analyzer.models import ParryResult, DistanceResult, FootworkResult
from analyzer.config import POSE_ANALYSIS_REMISE_WINDOW_SEC


def suggest_label(
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


def build_touch_narrative(
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
