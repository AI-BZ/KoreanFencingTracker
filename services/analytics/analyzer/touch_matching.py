"""Touch → exchange matching and attack success/failure judgment.

Shared by the clip endpoints (``app.server``) and the report generator
(``scripts.generate_continuous_report``) so that a clip's window and the
attack-outcome verdict shown next to it always describe the *same* exchange.

Background (measured on the foil bout, 22/22 touches): the OCR score change
lags the actual blade contact by a median of ~2.8s (range 0.6-4.6s, never
negative). Matching a touch back to the preceding pose exchange is therefore
the only way to know where the touch really happened — and which fencer was
advancing when it did.

Footwork decides ``attack_outcome``; the scoring-box lamps only explain it —
with one deliberate exception. In foil, a single valid-target lamp means the
referee awarded the touch outright: priority (FIE t.56-t.60) only arbitrates
when *both* valid lamps register. So a single-lamp touch was never a priority
case, and reporting it as ``unclear`` frames a non-case as a failure of our
analysis. :func:`annotate_touch_lamp` therefore promotes ``unclear`` +
single lamp to ``no_priority_call``. That is sound because which lamps lit is
a *fact about what the box recorded*, not an inference about footwork: it
tells us the priority question was never asked, while leaving "who attacked"
exactly as unknown as before. ``attacker_side`` / ``defender_side`` /
``matched_exchange_number`` are still never written by the lamp pass, and a
``attack_success`` / ``attack_failed`` verdict is never downgraded.
"""

from dataclasses import dataclass
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

# ``no_priority_call`` is not a verdict about the attack — it records that the
# question of priority never arose. See :data:`ATTACK_OUTCOME_KO` note below and
# :func:`annotate_touch_lamp`.
NO_PRIORITY_CALL = "no_priority_call"

ATTACK_OUTCOME_KO = {
    "attack_success": "공격 성공",
    "attack_failed": "공격 실패 (방어 성공)",
    "unclear": "판별 불가",
    # Only one valid-target lamp lit, so the referee awarded the touch without
    # ruling on priority. We still do not know who attacked — this says the
    # priority question was never asked, not that we answered it.
    NO_PRIORITY_CALL: "단독 유효타 (우선권 판정 없음)",
}

# Why the verdict looks the way it does, once the scoring-box lamps are known.
# The lamp explains ``attack_outcome``; it overrides it in exactly one narrow
# case (``unclear`` + single lamp → ``no_priority_call``, see
# :func:`annotate_touch_lamp`) and never otherwise. See
# :func:`classify_attack_outcome_detail`.
ATTACK_OUTCOME_DETAIL_KO = {
    "priority_won": "동시 유효타 — 우선권 인정",
    "clean_hit": "단독 유효타 — 상대 램프 없음",
    "priority_lost": "동시 유효타 — 우선권 상실",
    "attack_missed_counter_scored": "공격 불발 — 상대 단독 유효타",
    "single_lamp_no_priority_call": "단독 유효타 — 우선권 판정 없음",
    "double_lamp_referee_gave_scorer": "동시 유효타 — 심판이 득점자에게 우선권 부여",
}

# Lamp patterns that indicate exactly one fencer landed a valid hit.
_SINGLE_LAMP_SIDE = {"single_left": "left", "single_right": "right"}

# Every pattern LampReading can report; anything else counts as unread.
_LAMP_PATTERNS = ("double", "single_left", "single_right", "white")


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


# How confident we are about *who attacked* — a separate axis from
# ``attack_outcome``, which says whether that attack worked. Footwork that
# isolates a single aggressor is a determination; an arm-extension estimate is
# not, and the two must never be summed together as if they were.
CONFIDENCE_HIGH = "high"
CONFIDENCE_ESTIMATED = "estimated"
METHOD_FOOTWORK = "footwork"


@dataclass(frozen=True)
class AttackerResolution:
    """Who attacked, how sure we are, and how we decided."""

    side: str = "unclear"
    confidence: Optional[str] = None
    method: Optional[str] = None
    detail: Optional[dict] = None
    reason: Optional[str] = None


def resolve_attacker(exchange: dict, judge=None) -> AttackerResolution:
    """Attacker for an exchange, footwork first and priority estimation second.

    The cascade is strictly ordered so the weaker signal can never overwrite the
    stronger one:

    1. :func:`determine_attacker` — one side alone committing forward. Anything
       it decides is final and carries :data:`CONFIDENCE_HIGH`.
    2. ``judge`` (a weapon priority judge, foil only) — runs *only* on what step
       1 left unclear, and is marked :data:`CONFIDENCE_ESTIMATED`.
    3. Neither — ``"unclear"``, exactly as before.

    ``judge=None`` reproduces the pre-priority behaviour byte for byte, which is
    what every non-foil weapon and every report predating the arm series gets.

    ``judge`` is duck-typed rather than imported: it needs a ``method`` string
    and a ``judge(exchange)`` returning an object with ``attacker`` / ``grade`` /
    ``reason`` / ``detail``. Keeping it injected is what lets this module stay
    free of any dependency on ``ml``, so the analyzer layer does not have to know
    which weapons have judges — and a sabre judge can be added without touching
    this file.
    """
    footwork_side = determine_attacker(exchange)
    if footwork_side in ("left", "right"):
        return AttackerResolution(
            side=footwork_side,
            confidence=CONFIDENCE_HIGH,
            method=METHOD_FOOTWORK,
        )

    if judge is None:
        return AttackerResolution()

    call = judge.judge(exchange)
    if call.attacker in ("left", "right"):
        return AttackerResolution(
            side=call.attacker,
            confidence=call.grade,
            method=judge.method,
            detail=call.detail,
            reason=call.reason,
        )
    return AttackerResolution(detail=call.detail, reason=call.reason)


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


def annotate_touch_outcome(
    touch: dict,
    exchanges: list,
    fps: float = 30.0,
    judge=None,
) -> dict:
    """Add ``attack_outcome`` / ``attacker_side`` / ``matched_exchange_number`` in place.

    Returns the same dict for convenience. A touch that cannot be matched to a
    preceding exchange gets ``attack_outcome="unclear"`` and
    ``matched_exchange_number=None`` — never a guess.

    With a ``judge`` (see :func:`resolve_attacker`) three more keys appear:
    ``attacker_confidence``, ``attacker_method`` and, when the judge produced
    numbers, ``priority_detail`` / ``priority_reason``. They are written
    unconditionally — including as ``None`` — so a touch dict's shape does not
    depend on which weapon it came from.
    """
    exchange, _gap = match_touch_to_exchange(touch.get("frame"), exchanges, fps)

    if exchange is None:
        resolution = AttackerResolution()
        attacker_side = None
        defender_side = None
        matched_number = None
        outcome = "unclear"
    else:
        resolution = resolve_attacker(exchange, judge=judge)
        attacker = resolution.side
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
    touch["attacker_confidence"] = resolution.confidence
    touch["attacker_method"] = resolution.method
    touch["priority_detail"] = resolution.detail
    touch["priority_reason"] = resolution.reason
    return touch


def annotate_touch_outcomes(
    touches: list,
    exchanges: list,
    fps: float = 30.0,
    judge=None,
) -> list:
    """Annotate every touch in ``touches`` (in place) and return the list."""
    for t in touches:
        annotate_touch_outcome(t, exchanges, fps, judge=judge)
    return touches


# ------------------------------------------------------------------
# Lamp-informed detail (foil priority)
# ------------------------------------------------------------------


def lamp_scorer_conflict(pattern: Optional[str], scorer: Optional[str]) -> bool:
    """True when a single-lamp reading contradicts the OCR scorer.

    You cannot score without your own colour lamp, so ``single_left`` with a
    right-side scorer (or vice versa) is physically impossible: one of the two
    readings is wrong. The caller must then ignore the lamp entirely rather than
    pick a winner between two sources it cannot arbitrate.
    """
    lamp_side = _SINGLE_LAMP_SIDE.get(pattern)
    if lamp_side is None:
        return False
    if scorer not in ("left", "right"):
        return False
    return scorer != lamp_side


def classify_attack_outcome_detail(
    attack_outcome: Optional[str],
    attacker_side: Optional[str],
    scorer: Optional[str],
    pattern: Optional[str],
) -> Optional[str]:
    """Refine an already-decided ``attack_outcome`` with the lamp pattern.

    Returns a key of :data:`ATTACK_OUTCOME_DETAIL_KO`, or ``None`` when the
    lamps say nothing usable (white / unread / contradicting the scorer).

    ``double`` means both fencers landed and the referee applied priority, so the
    scorer is the referee-recognised priority holder; a single colour lamp means
    no priority ruling was needed at all.

    ``unclear`` and :data:`NO_PRIORITY_CALL` are handled identically: the second
    is the first once the lamp has been read, so classifying an already-promoted
    touch a second time yields the same detail (idempotence).
    """
    if pattern is None or pattern == "white":
        return None
    if lamp_scorer_conflict(pattern, scorer):
        return None

    lamp_side = _SINGLE_LAMP_SIDE.get(pattern)

    if attack_outcome == "attack_success":
        if pattern == "double":
            return "priority_won"
        if lamp_side is not None and lamp_side == attacker_side:
            return "clean_hit"
        return None

    if attack_outcome == "attack_failed":
        if pattern == "double":
            return "priority_lost"
        if lamp_side is not None and lamp_side == scorer and scorer != attacker_side:
            return "attack_missed_counter_scored"
        return None

    if attack_outcome in ("unclear", NO_PRIORITY_CALL):
        if pattern == "double":
            return "double_lamp_referee_gave_scorer"
        if lamp_side is not None:
            return "single_lamp_no_priority_call"

    return None


def annotate_touch_lamp(touch: dict, reading) -> dict:
    """Add the lamp fields to an *already outcome-annotated* touch, in place.

    Run this after :func:`annotate_touch_outcome`. ``reading`` is a
    ``LampReading`` (``analyzer.tv_overlay_ocr``) or ``None`` when no lamp event
    could be attributed to the touch.

    Sets ``lamp_pattern``, ``lamp_confidence``, ``lamp_detail``,
    ``attack_outcome_detail`` (+ ``_ko``) and ``lamp_scorer_conflict``.

    It never writes ``attacker_side`` / ``defender_side`` /
    ``matched_exchange_number`` — footwork alone decides who attacked.

    It writes ``attack_outcome`` (+ ``_ko``) in exactly one case: an
    ``unclear`` touch whose lamp pattern is ``single_left`` / ``single_right``
    with no scorer conflict becomes :data:`NO_PRIORITY_CALL`. Only one valid
    hit registered, so the referee awarded the touch without ruling on
    priority — that is a fact about what the scoring box recorded, not an
    inference about footwork, and it leaves "who attacked" as unknown as it
    was. ``attack_success`` / ``attack_failed`` are strictly more informative
    and are never downgraded; ``double``, ``white``, an unread lamp and a
    scorer conflict all leave ``attack_outcome`` alone.

    Idempotent: annotating twice with the same reading is a no-op.

    Returns the same dict for convenience.
    """
    if reading is None:
        touch["lamp_pattern"] = None
        touch["lamp_confidence"] = 0.0
        touch["lamp_detail"] = None
        touch["lamp_scorer_conflict"] = False
        touch["attack_outcome_detail"] = None
        touch["attack_outcome_detail_ko"] = None
        return touch

    pattern = reading.pattern
    scorer = touch.get("scorer")
    conflict = lamp_scorer_conflict(pattern, scorer)

    detail_dict = reading.to_dict()
    touch_frame = touch.get("frame")
    start_frame = reading.start_frame
    detail_dict["lead_frames"] = (
        touch_frame - start_frame
        if touch_frame is not None and start_frame is not None
        else None
    )

    outcome = touch.get("attack_outcome")

    if conflict:
        detail = None
    else:
        # The one permitted write-back: a single valid lamp means no priority
        # ruling was made, so "unclear" misdescribes the touch as an analysis
        # failure. Determined verdicts are strictly more informative and are
        # left alone. Re-running is stable — NO_PRIORITY_CALL is not "unclear".
        #
        # An *estimated* verdict is withdrawn here too, and this is the only
        # place a verdict is ever taken back. Priority estimation runs before the
        # lamps are read, so it can guess an attacker for a touch the referee
        # never had to rule on. The lamp is direct evidence about that: one
        # valid hit means the priority question was never asked, which outranks
        # our inference about who was attacking. Leaving the estimate would print
        # a priority holder directly beside the words "no priority ruling". The
        # footwork verdict is not withdrawn — it describes who advanced, which is
        # true regardless of how many lamps lit.
        estimated = touch.get("attacker_confidence") == CONFIDENCE_ESTIMATED
        if pattern in _SINGLE_LAMP_SIDE and (outcome == "unclear" or estimated):
            touch["attack_outcome"] = NO_PRIORITY_CALL
            touch["attack_outcome_ko"] = ATTACK_OUTCOME_KO[NO_PRIORITY_CALL]
            if estimated:
                touch["attacker_side"] = "unclear"
                touch["defender_side"] = "unclear"
                touch["attacker_confidence"] = None
                touch["attacker_method"] = None
                touch["priority_reason"] = "withdrawn_single_lamp"

        # Classified from the post-write-back state so a withdrawn estimate is
        # described as the single-lamp non-case it is, not as the clean hit its
        # retracted attacker would have implied.
        detail = classify_attack_outcome_detail(
            touch.get("attack_outcome"), touch.get("attacker_side"), scorer, pattern,
        )

    touch["lamp_pattern"] = pattern
    touch["lamp_confidence"] = float(reading.confidence)
    touch["lamp_detail"] = detail_dict
    touch["lamp_scorer_conflict"] = conflict
    touch["attack_outcome_detail"] = detail
    touch["attack_outcome_detail_ko"] = (
        ATTACK_OUTCOME_DETAIL_KO[detail] if detail is not None else None
    )
    return touch


def annotate_touch_lamps(touches: list, readings: list) -> list:
    """Annotate parallel lists of touches and lamp readings; returns ``touches``.

    ``readings[i]`` is the reading for ``touches[i]`` and may be ``None``. The
    lists must be the same length — a silent zip-truncation would mis-attribute
    every lamp after the first missing one.
    """
    if len(touches) != len(readings):
        raise ValueError(
            f"touches ({len(touches)}) and readings ({len(readings)}) must be "
            "parallel lists of the same length",
        )
    for touch, reading in zip(touches, readings):
        annotate_touch_lamp(touch, reading)
    return touches


def _pct(numerator: int, denominator: int) -> float:
    """``numerator / denominator`` as a 1dp percentage; 0.0 when nothing to divide."""
    if not denominator:
        return 0.0
    return round(numerator / denominator * 100, 1)


def summarize_attack_outcomes(touches: list) -> dict:
    """Aggregate per-fencer attack attempts / successes from annotated touches.

    ``attack_attempts`` counts touches where that side was the identified
    attacker (whether or not they scored); ``attack_success`` counts the subset
    where they also scored. ``defense_success`` counts touches where the *other*
    side attacked and this side scored — the same events as the opponent's
    failed attacks, from the defender's perspective.

    ``unclear_touches`` counts *only* genuinely unclear touches.
    :data:`NO_PRIORITY_CALL` touches are counted separately in
    ``no_priority_call_touches`` — they are not analysis failures, they are
    touches where no priority ruling was ever made. ``attack_attempts`` and
    everything derived from it are unaffected by the split: a
    ``no_priority_call`` touch still has no identified attacker.

    The ``"lamp"`` sub-dict tallies the scoring-box readings added by
    :func:`annotate_touch_lamp`. ``double`` + ``single_left`` + ``single_right``
    + ``white`` + ``unread`` always sums to ``total_touches``; ``conflict`` is a
    cross-cutting count of single-lamp readings that contradict the scorer, so it
    overlaps the two ``single_*`` buckets rather than adding to them.

    The ``"priority"`` sub-dict reports **two different denominators on
    purpose**, because they answer different questions and either one quoted
    alone would mislead:

    * ``ruled_unclear_rate`` = ``ruled_unclear / ruled`` — how often we fail on
      a *genuine* priority case (double lamp, where the referee really did have
      to rule). This measures accuracy on the hard problem.
    * ``unexplained_rate`` = ``unexplained / total_touches`` — how much of the
      whole bout we leave without any account at all. This measures coverage.

    On the reference foil bout these read 62.5% and 22.7%. They are *not*
    competing estimates of one quantity: the first is high because the double-
    lamp subset is exactly the hard subset, the second is lower because most
    touches never needed a priority call. Both are returned so neither can be
    cited as "the" error rate.

    ``ruled`` (double lamp) and ``not_required`` (single lamp) are the two
    denominators themselves. ``unexplained`` counts touches with neither a
    determined outcome nor a no-priority-call explanation — by construction the
    same set as ``unclear_touches``, repeated here so the rate sits next to the
    denominator it is computed from.
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
    lamp = {
        "double": 0,
        "single_left": 0,
        "single_right": 0,
        "white": 0,
        "unread": 0,
        "conflict": 0,
    }
    matched = 0
    unclear = 0
    no_priority_call = 0
    ruled_unclear = 0
    estimated = 0

    for t in touches:
        pattern = t.get("lamp_pattern")
        lamp[pattern if pattern in _LAMP_PATTERNS else "unread"] += 1
        if t.get("lamp_scorer_conflict"):
            lamp["conflict"] += 1
        if pattern == "double" and t.get("attack_outcome") == "unclear":
            ruled_unclear += 1

    for t in touches:
        outcome = t.get("attack_outcome", "unclear")
        attacker = t.get("attacker_side")
        if t.get("matched_exchange_number") is not None:
            matched += 1
        # Checked before the unclear test: a no-priority-call touch has no
        # identified attacker either, so it would otherwise be swallowed by the
        # `attacker not in (...)` guard and silently reported as unclear.
        if outcome == NO_PRIORITY_CALL:
            no_priority_call += 1
            continue
        if outcome == "unclear" or attacker not in ("left", "right"):
            unclear += 1
            continue

        if t.get("attacker_confidence") == CONFIDENCE_ESTIMATED:
            estimated += 1

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

    ruled = lamp["double"]
    not_required = lamp["single_left"] + lamp["single_right"]
    total = len(touches)

    return {
        "left": stats["left"],
        "right": stats["right"],
        "total_touches": total,
        "matched_touches": matched,
        "unclear_touches": unclear,
        "no_priority_call_touches": no_priority_call,
        # Subset of the counted attacks whose attacker came from priority
        # estimation rather than footwork. The per-side totals deliberately do
        # not split on it — an attack is an attack — but the count is published
        # so a reader can see how much of the statistic rests on an estimate.
        "estimated_touches": estimated,
        "lamp": lamp,
        "priority": {
            "ruled": ruled,
            "not_required": not_required,
            "ruled_unclear": ruled_unclear,
            "ruled_unclear_rate": _pct(ruled_unclear, ruled),
            "unexplained": unclear,
            "unexplained_rate": _pct(unclear, total),
        },
    }
