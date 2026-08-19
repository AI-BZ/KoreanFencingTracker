"""Decide which touches carry a referee priority ruling we can label.

The idea this module encodes: in foil, a **two-light touch** is the only touch
where the referee had to *rule on priority*. Both fencers landed a valid hit, so
the point could have gone either way, and the side whose score went up is the
side the referee gave priority to. That makes the scoreboard the referee's own
written answer — a free ground-truth label.

A single light means only one hit was valid. The referee awarded the point on
validity alone and never ruled on priority, so there is no priority answer to
learn from. Those touches are *not* weak labels; they are non-labels, and mixing
them in would teach a priority model to predict "whoever happened to land".

Everything here is pure: strings and dataclasses in, a decision out. No video,
no OCR, no filesystem. The video-facing driver is
``scripts/collect_priority_labels.py``.
"""

from dataclasses import dataclass
from typing import Optional, Tuple

#: Lamp pattern that means "both hits valid, referee ruled on priority".
#: Matches ``analyzer.tv_overlay_ocr._lamp_pattern`` output.
DOUBLE = "double"
SINGLE_LEFT = "single_left"
SINGLE_RIGHT = "single_right"
WHITE = "white"

SIDES = ("left", "right")

# ── Rejection reasons ───────────────────────────────────────
# Every discarded touch carries exactly one of these, so the yield report can
# say *why* a touch produced no label rather than only how many did not.

#: The score strings did not parse as "N-M".
REJECT_SCORE_UNPARSEABLE = "score_unparseable"
#: A side's score went down. One of the two OCR reads is wrong.
REJECT_SCORE_DECREASED = "score_decreased"
#: Both sides gained. Impossible in foil — a double touch with no clear
#: priority scores for nobody — so this is an OCR misread, not a real touch.
REJECT_SCORE_BOTH_INCREASED = "score_both_increased"
#: Neither side gained. Nothing to attribute.
REJECT_SCORE_UNCHANGED = "score_unchanged"
#: A side gained more than one point at once. Either a missed touch upstream or
#: an OCR misread; either way the touch this label would describe is ambiguous.
REJECT_SCORE_JUMP = "score_jump"
#: The tracker's scorer disagrees with the side the score says gained.
REJECT_SCORER_MISMATCH = "scorer_score_mismatch"
#: No lamp event could be attributed to this touch.
REJECT_LAMP_UNREAD = "lamp_unread"
#: Only the off-target (white) lamp was read — no valid hit explains the point.
REJECT_LAMP_WHITE = "lamp_white_only"
#: One valid hit. The referee never ruled on priority, so no answer exists.
REJECT_SINGLE_LAMP = "single_lamp_no_priority_call"
#: The lamp read was too weak to trust as a two-light reading.
REJECT_LOW_CONFIDENCE = "lamp_confidence_below_threshold"
#: Both lamps lit during the event, but never at the same time. Foil locks out
#: the second hit 300ms after the first, so a genuine double shows both lamps
#: overlapping. Two lamps lit *in sequence* are two different things — usually a
#: single hit followed by the overlay's point-award highlight — and the event
#: grouper cannot tell them apart because it only records a peak state per side.
REJECT_NOT_SIMULTANEOUS = "lamp_not_simultaneous"

#: Order used when printing the yield table, so the report reads as a funnel.
REJECT_ORDER = (
    REJECT_SINGLE_LAMP,
    REJECT_LAMP_UNREAD,
    REJECT_LAMP_WHITE,
    REJECT_NOT_SIMULTANEOUS,
    REJECT_LOW_CONFIDENCE,
    REJECT_SCORE_BOTH_INCREASED,
    REJECT_SCORE_JUMP,
    REJECT_SCORE_DECREASED,
    REJECT_SCORE_UNCHANGED,
    REJECT_SCORE_UNPARSEABLE,
    REJECT_SCORER_MISMATCH,
)


@dataclass(frozen=True)
class LabelDecision:
    """Outcome of applying the label rules to one touch."""

    accepted: bool
    #: "left" | "right" — the side the referee gave priority to. Set only when
    #: ``accepted``; a rejected touch has no priority answer, not a guessed one.
    label: Optional[str] = None
    reject_reason: Optional[str] = None
    #: True when the lamp pattern was a genuine two-light. Reported even for
    #: rejected touches so the funnel can separate "not a double" from
    #: "a double we still had to throw away".
    both_lamps: bool = False
    #: The side the *scoreboard* says gained, independent of the tracker.
    scoring_side: Optional[str] = None


def parse_score(text: Optional[str]) -> Optional[Tuple[int, int]]:
    """Parse a ``"3-1"`` overlay score string into ``(left, right)``.

    Returns ``None`` for anything that is not two non-negative integers joined
    by a single hyphen — an OCR read of ``"3-"`` or ``"B-1"`` must not be
    silently coerced into a number.
    """
    if not isinstance(text, str):
        return None
    parts = text.strip().split("-")
    if len(parts) != 2:
        return None
    try:
        left, right = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if left < 0 or right < 0:
        return None
    return (left, right)


def scoring_side(
    score_before: Optional[str],
    score_after: Optional[str],
) -> Tuple[Optional[str], Optional[str]]:
    """Which side gained the point, by reading the scoreboard alone.

    This is the self-consistency gate. The tracker already derives a scorer from
    the same numbers, so re-deriving it here is deliberate redundancy: it is the
    only place that rejects a "both sides gained" read, which the tracker's
    decrease/jump guards let through.

    Returns:
        ``(side, None)`` on success, or ``(None, reject_reason)``.
    """
    before = parse_score(score_before)
    after = parse_score(score_after)
    if before is None or after is None:
        return (None, REJECT_SCORE_UNPARSEABLE)

    d_left = after[0] - before[0]
    d_right = after[1] - before[1]

    if d_left < 0 or d_right < 0:
        return (None, REJECT_SCORE_DECREASED)
    if d_left > 0 and d_right > 0:
        return (None, REJECT_SCORE_BOTH_INCREASED)
    if d_left == 0 and d_right == 0:
        return (None, REJECT_SCORE_UNCHANGED)
    if d_left > 1 or d_right > 1:
        return (None, REJECT_SCORE_JUMP)

    return ("left" if d_left == 1 else "right", None)


def is_double(lamp_pattern: Optional[str]) -> bool:
    """True only for a genuine two-light reading."""
    return lamp_pattern == DOUBLE


def decide_priority_label(
    lamp_pattern: Optional[str],
    score_before: Optional[str],
    score_after: Optional[str],
    scorer: Optional[str] = None,
    lamp_confidence: float = 1.0,
    min_confidence: float = 0.0,
    overlap_frames: Optional[int] = None,
    min_overlap_frames: int = 0,
) -> LabelDecision:
    """Apply the two-light rule to one touch.

    A label is produced only when *both* independent signals agree that a
    priority ruling happened and say who won it:

    1. the lamps show two lights — a ruling was necessary, and
    2. the scoreboard moved by exactly one point on exactly one side — the
       ruling's outcome is legible.

    Args:
        lamp_pattern: ``"double"``/``"single_left"``/``"single_right"``/
            ``"white"``/``None``, as produced by the lamp reader.
        score_before: Overlay score before the touch, ``"N-M"``.
        score_after: Overlay score after the touch, ``"N-M"``.
        scorer: The tracker's own attribution, cross-checked against the score
            when supplied.
        lamp_confidence: Confidence of the lamp reading, 0..1.
        min_confidence: Reject two-light reads below this. Default 0.0 keeps the
            gate inert unless a caller opts in.
        overlap_frames: Frames on which *both* lamps read lit. ``None`` means
            not measured, in which case the simultaneity gate cannot fire.
        min_overlap_frames: Require at least this much overlap. Default 0 keeps
            the gate inert unless a caller opts in.

    Returns:
        A :class:`LabelDecision`. Rejected touches carry ``label=None``.
    """
    double = is_double(lamp_pattern)

    side, score_reject = scoring_side(score_before, score_after)
    if score_reject is not None:
        return LabelDecision(
            accepted=False, reject_reason=score_reject, both_lamps=double
        )

    if scorer in SIDES and scorer != side:
        return LabelDecision(
            accepted=False,
            reject_reason=REJECT_SCORER_MISMATCH,
            both_lamps=double,
            scoring_side=side,
        )

    if lamp_pattern is None:
        reject = REJECT_LAMP_UNREAD
    elif lamp_pattern == WHITE:
        reject = REJECT_LAMP_WHITE
    elif lamp_pattern in (SINGLE_LEFT, SINGLE_RIGHT):
        reject = REJECT_SINGLE_LAMP
    elif not double:
        reject = REJECT_LAMP_UNREAD
    elif (
        min_overlap_frames > 0
        and overlap_frames is not None
        and overlap_frames < min_overlap_frames
    ):
        reject = REJECT_NOT_SIMULTANEOUS
    elif lamp_confidence < min_confidence:
        reject = REJECT_LOW_CONFIDENCE
    else:
        reject = None

    if reject is not None:
        return LabelDecision(
            accepted=False, reject_reason=reject, both_lamps=double, scoring_side=side
        )

    return LabelDecision(
        accepted=True, label=side, both_lamps=True, scoring_side=side
    )
