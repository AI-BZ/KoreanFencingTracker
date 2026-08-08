"""Touch → exchange matching and attack success/failure judgment.

Shared by the clip endpoints (``app.server``) and the report generator
(``scripts.generate_continuous_report``) so that a clip's window and the
attack-outcome verdict shown next to it always describe the *same* exchange.

Background (measured on the foil bout, 22/22 touches): the OCR score change
lags the actual blade contact by a median of ~2.8s (range 0.6-4.6s, never
negative). Matching a touch back to the preceding pose exchange is therefore
the only way to know where the touch really happened — and which fencer was
advancing when it did.
"""

from typing import Optional, Tuple

from analyzer.config import (
    EXCHANGE_ATTACK_FOOTWORK_TYPES,
    EXCHANGE_MATCH_DELAY_SEC,
    OCR_TOUCH_DELAY_MEDIAN_SEC,
    PHRASE_MAX_LEAD_SEC,
)

# Pose exchange end can land a few frames after the OCR touch (pose sampling is
# non-deterministic); allow a small forward tolerance so we don't drop the
# exchange that actually produced the touch.
_FORWARD_TOL_SEC = 0.5
_POST_TOUCH_BUFFER_SEC = 0.3
_MIN_CLIP_SEC = 1.5

# Footwork that indicates giving ground rather than committing forward.
RETREAT_FOOTWORK = "retreat"

ATTACK_OUTCOME_KO = {
    "attack_success": "공격 성공",
    "attack_failed": "공격 실패 (방어 성공)",
    "unclear": "판별 불가",
}


# ------------------------------------------------------------------
# Touch → exchange matching
# ------------------------------------------------------------------


def match_touch_to_exchange(
    touch_frame: int,
    exchanges: list,
    fps: float = 30.0,
) -> Tuple[Optional[dict], Optional[int]]:
    """Return the pose exchange that produced ``touch_frame`` (or None).

    An exchange qualifies when its ``end_frame`` sits at or just before the OCR
    touch, within ``EXCHANGE_MATCH_DELAY_SEC``. Among the candidates the one
    whose end is closest to the touch wins.

    Returns ``(exchange, gap_frames)`` where ``gap_frames = touch_frame -
    end_frame`` (negative when the pose end trails the OCR frame slightly).
    """
    if touch_frame is None:
        return (None, None)

    delay_frames = int(EXCHANGE_MATCH_DELAY_SEC * fps)
    forward_tol = int(_FORWARD_TOL_SEC * fps)

    best_exchange = None
    best_gap = None
    for ex in exchanges:
        ef = ex.get("end_frame", 0)
        gap = touch_frame - ef
        if -forward_tol <= gap <= delay_frames:
            if best_gap is None or abs(gap) < abs(best_gap):
                best_gap = gap
                best_exchange = ex

    return (best_exchange, best_gap)


def compute_touch_clip_bounds(
    touch_frame: int,
    exchanges: list,
    clock_events: list,
    fps: float = 30.0,
) -> tuple:
    """Compute clip start/end anchored on the REAL touch, not the OCR score change.

    Priority:
    1. Preceding exchange matched by :func:`match_touch_to_exchange` →
       ``[exchange start .. min_distance_frame + 0.3s]``. Start is clamped to at
       most ``PHRASE_MAX_LEAD_SEC`` before the end (guards degenerate ~36s
       exchanges); a recent allez clock event, if present, is preferred as the
       start.
    2. Fallback (no matching exchange): ``[touch - median delay .. touch]`` —
       low confidence, real-touch position unknown.

    Returns ``(start_frame, end_frame)``.
    """
    post_touch_buffer = int(_POST_TOUCH_BUFFER_SEC * fps)
    max_lead_frames = int(PHRASE_MAX_LEAD_SEC * fps)
    fallback_lead = int(OCR_TOUCH_DELAY_MEDIAN_SEC * fps)
    min_clip_frames = int(_MIN_CLIP_SEC * fps)

    best_exchange, _gap = match_touch_to_exchange(touch_frame, exchanges, fps)

    if best_exchange is not None:
        # Anchor the clip END on the real touch (min-distance frame) + a small
        # buffer. Fall back to the exchange end if the anchor is unavailable.
        anchor = best_exchange.get("min_distance_frame")
        if anchor is None:
            clip_end = int(best_exchange.get("end_frame", touch_frame))
        else:
            clip_end = int(anchor) + post_touch_buffer

        # Clip START: exchange start, or a recent allez clock event if one exists.
        clip_start = int(best_exchange.get("start_frame", clip_end))
        if clock_events:
            recent_allez = None
            for ce in clock_events:
                if ce.get("event") == "allez" and ce.get("frame", 0) < clip_end:
                    if recent_allez is None or ce["frame"] > recent_allez["frame"]:
                        recent_allez = ce
            if recent_allez is not None:
                clip_start = int(recent_allez["frame"])

        # Lead-in cap: guard against degenerate long exchanges.
        if clip_end - clip_start > max_lead_frames:
            clip_start = clip_end - max_lead_frames
        # Minimum clip length.
        if clip_end - clip_start < min_clip_frames:
            clip_start = clip_end - min_clip_frames
        return (max(0, clip_start), max(0, clip_end))

    # Fallback: no preceding exchange matched. Anchor on the OCR touch with the
    # measured median delay as lead-in (low confidence — real touch unknown).
    clip_end = touch_frame
    clip_start = touch_frame - fallback_lead
    if clip_end - clip_start < min_clip_frames:
        clip_start = clip_end - min_clip_frames
    return (max(0, clip_start), max(0, clip_end))


# ------------------------------------------------------------------
# Attacker / defender from footwork
# ------------------------------------------------------------------


def classify_exchange_sides(
    footwork_left: Optional[str],
    footwork_right: Optional[str],
) -> Tuple[str, str]:
    """Map the two fencers' footwork to ``(attacker, defender)``.

    A fencer counts as attacking when their footwork is one of
    ``EXCHANGE_ATTACK_FOOTWORK_TYPES`` (advance / lunge / fleche). Exactly one
    aggressor gives a clean attacker/defender pair; otherwise the sides are
    ``"both"`` (mutual attack) or ``"unknown"`` (no committed approach).
    """
    left_attacking = footwork_left in EXCHANGE_ATTACK_FOOTWORK_TYPES
    right_attacking = footwork_right in EXCHANGE_ATTACK_FOOTWORK_TYPES

    if left_attacking and not right_attacking:
        return ("left", "right")
    if right_attacking and not left_attacking:
        return ("right", "left")
    if left_attacking and right_attacking:
        return ("both", "both")
    return ("unknown", "unknown")


def determine_attacker(exchange: dict) -> str:
    """Attacker side for an exchange dict: ``"left"``, ``"right"`` or ``"unclear"``.

    Mutual attacks and exchanges with no committed approach collapse to
    ``"unclear"`` — the attack outcome is only reported when one side is
    unambiguously the aggressor.
    """
    attacker, _defender = classify_exchange_sides(
        exchange.get("footwork_left"), exchange.get("footwork_right"),
    )
    return attacker if attacker in ("left", "right") else "unclear"


def classify_attack_outcome(scorer: Optional[str], attacker_side: Optional[str]) -> str:
    """Compare the OCR scorer with the attacker: success / failed / unclear."""
    if attacker_side not in ("left", "right"):
        return "unclear"
    if scorer not in ("left", "right"):
        return "unclear"
    return "attack_success" if scorer == attacker_side else "attack_failed"


# ------------------------------------------------------------------
# Per-touch annotation + aggregation
# ------------------------------------------------------------------


def annotate_touch_outcome(touch: dict, exchanges: list, fps: float = 30.0) -> dict:
    """Add ``attack_outcome`` / ``attacker_side`` / ``matched_exchange_number`` in place.

    Returns the same dict for convenience. A touch that cannot be matched to a
    preceding exchange gets ``attack_outcome="unclear"`` and
    ``matched_exchange_number=None`` — never a guess.
    """
    exchange, _gap = match_touch_to_exchange(touch.get("frame"), exchanges, fps)

    if exchange is None:
        attacker_side = None
        defender_side = None
        matched_number = None
        outcome = "unclear"
    else:
        attacker = determine_attacker(exchange)
        attacker_side = attacker
        if attacker == "left":
            defender_side = "right"
        elif attacker == "right":
            defender_side = "left"
        else:
            defender_side = "unclear"
        matched_number = exchange.get("exchange_number")
        outcome = classify_attack_outcome(touch.get("scorer"), attacker)

    touch["attack_outcome"] = outcome
    touch["attack_outcome_ko"] = ATTACK_OUTCOME_KO[outcome]
    touch["attacker_side"] = attacker_side
    touch["defender_side"] = defender_side
    touch["matched_exchange_number"] = matched_number
    return touch


def annotate_touch_outcomes(touches: list, exchanges: list, fps: float = 30.0) -> list:
    """Annotate every touch in ``touches`` (in place) and return the list."""
    for t in touches:
        annotate_touch_outcome(t, exchanges, fps)
    return touches


def summarize_attack_outcomes(touches: list) -> dict:
    """Aggregate per-fencer attack attempts / successes from annotated touches.

    ``attack_attempts`` counts touches where that side was the identified
    attacker (whether or not they scored); ``attack_success`` counts the subset
    where they also scored. ``defense_success`` counts touches where the *other*
    side attacked and this side scored — the same events as the opponent's
    failed attacks, from the defender's perspective.
    """
    stats = {
        side: {
            "attack_attempts": 0,
            "attack_success": 0,
            "attack_failed": 0,
            "attack_success_rate": 0.0,
            "defense_success": 0,
        }
        for side in ("left", "right")
    }
    matched = 0
    unclear = 0

    for t in touches:
        outcome = t.get("attack_outcome", "unclear")
        attacker = t.get("attacker_side")
        if t.get("matched_exchange_number") is not None:
            matched += 1
        if outcome == "unclear" or attacker not in ("left", "right"):
            unclear += 1
            continue

        defender = "right" if attacker == "left" else "left"
        stats[attacker]["attack_attempts"] += 1
        if outcome == "attack_success":
            stats[attacker]["attack_success"] += 1
        else:
            stats[attacker]["attack_failed"] += 1
            stats[defender]["defense_success"] += 1

    for side in ("left", "right"):
        attempts = stats[side]["attack_attempts"]
        if attempts:
            stats[side]["attack_success_rate"] = round(
                stats[side]["attack_success"] / attempts * 100, 1,
            )

    return {
        "left": stats["left"],
        "right": stats["right"],
        "total_touches": len(touches),
        "matched_touches": matched,
        "unclear_touches": unclear,
    }
