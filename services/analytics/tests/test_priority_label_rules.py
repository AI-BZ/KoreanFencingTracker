"""Tests for the two-light priority label rules.

The rule under test is the whole premise of the collection pipeline: a foil
touch carries a usable priority label *only* when both lamps lit and the
scoreboard then moved by one point on one side. These tests pin both halves —
what gets labelled, and what gets thrown away and why.
"""

import pytest

from pipeline.priority_label_rules import (
    DOUBLE,
    REJECT_LAMP_UNREAD,
    REJECT_LAMP_WHITE,
    REJECT_LOW_CONFIDENCE,
    REJECT_NOT_SIMULTANEOUS,
    REJECT_ORDER,
    REJECT_SCORE_BOTH_INCREASED,
    REJECT_SCORE_DECREASED,
    REJECT_SCORE_JUMP,
    REJECT_SCORE_UNCHANGED,
    REJECT_SCORE_UNPARSEABLE,
    REJECT_SCORER_MISMATCH,
    REJECT_SINGLE_LAMP,
    SINGLE_LEFT,
    SINGLE_RIGHT,
    WHITE,
    decide_priority_label,
    is_double,
    parse_score,
    scoring_side,
)


class TestParseScore:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("0-0", (0, 0)),
            ("3-1", (3, 1)),
            ("15-14", (15, 14)),
            (" 7-2 ", (7, 2)),
        ],
    )
    def test_valid(self, text, expected):
        assert parse_score(text) == expected

    @pytest.mark.parametrize(
        "text",
        ["", "3", "3-", "-1", "a-1", "3-b", "3-1-2", "3:1", None, 31, "3 1"],
    )
    def test_rejected(self, text):
        assert parse_score(text) is None

    def test_negative_rejected(self):
        # "-1--2" splits into more than two parts; a lone negative cannot be
        # produced by the overlay and must not be accepted as a score.
        assert parse_score("1--2") is None


class TestScoringSide:
    def test_left_gains(self):
        assert scoring_side("2-1", "3-1") == ("left", None)

    def test_right_gains(self):
        assert scoring_side("2-1", "2-2") == ("right", None)

    def test_both_increased_rejected(self):
        # Foil never awards both fencers a point on one action, so this is an
        # OCR misread. The upstream tracker does not catch it.
        side, reason = scoring_side("2-1", "3-2")
        assert side is None
        assert reason == REJECT_SCORE_BOTH_INCREASED

    def test_decrease_rejected(self):
        assert scoring_side("3-1", "2-1")[1] == REJECT_SCORE_DECREASED

    def test_unchanged_rejected(self):
        assert scoring_side("3-1", "3-1")[1] == REJECT_SCORE_UNCHANGED

    def test_jump_rejected(self):
        assert scoring_side("1-0", "3-0")[1] == REJECT_SCORE_JUMP

    @pytest.mark.parametrize("before,after", [("x", "1-0"), ("1-0", "x"), (None, "1-0")])
    def test_unparseable_rejected(self, before, after):
        assert scoring_side(before, after)[1] == REJECT_SCORE_UNPARSEABLE


class TestIsDouble:
    def test_only_double_counts(self):
        assert is_double(DOUBLE)
        for pattern in (SINGLE_LEFT, SINGLE_RIGHT, WHITE, None, "", "DOUBLE"):
            assert not is_double(pattern)


class TestAcceptedLabels:
    def test_double_left_scores_labels_left(self):
        d = decide_priority_label(DOUBLE, "2-1", "3-1", scorer="left")
        assert d.accepted
        assert d.label == "left"
        assert d.both_lamps is True
        assert d.reject_reason is None

    def test_double_right_scores_labels_right(self):
        d = decide_priority_label(DOUBLE, "2-1", "2-2", scorer="right")
        assert d.accepted
        assert d.label == "right"

    def test_scorer_optional(self):
        # The scoreboard alone is sufficient; the tracker's scorer is only a
        # cross-check when supplied.
        d = decide_priority_label(DOUBLE, "0-0", "1-0")
        assert d.accepted and d.label == "left"

    def test_mirror_symmetry(self):
        left = decide_priority_label(DOUBLE, "4-2", "5-2", scorer="left")
        right = decide_priority_label(DOUBLE, "2-4", "2-5", scorer="right")
        assert left.accepted and right.accepted
        assert left.label == "left" and right.label == "right"


class TestSingleLampIsNotALabel:
    @pytest.mark.parametrize("pattern", [SINGLE_LEFT, SINGLE_RIGHT])
    def test_single_lamp_rejected(self, pattern):
        d = decide_priority_label(pattern, "2-1", "3-1", scorer="left")
        assert not d.accepted
        assert d.reject_reason == REJECT_SINGLE_LAMP
        assert d.both_lamps is False

    def test_single_lamp_agreeing_with_scorer_still_rejected(self):
        # A single lamp on the scoring side is a *correct* reading, not an
        # error — but the referee never ruled on priority, so there is still no
        # answer to record.
        d = decide_priority_label(SINGLE_LEFT, "2-1", "3-1", scorer="left")
        assert not d.accepted
        assert d.reject_reason == REJECT_SINGLE_LAMP

    def test_white_rejected(self):
        d = decide_priority_label(WHITE, "2-1", "3-1", scorer="left")
        assert d.reject_reason == REJECT_LAMP_WHITE
        assert not d.accepted

    def test_unread_rejected(self):
        d = decide_priority_label(None, "2-1", "3-1", scorer="left")
        assert d.reject_reason == REJECT_LAMP_UNREAD
        assert not d.accepted

    def test_unknown_pattern_treated_as_unread(self):
        d = decide_priority_label("sparkler", "2-1", "3-1")
        assert d.reject_reason == REJECT_LAMP_UNREAD
        assert not d.accepted


class TestConsistencyGate:
    def test_two_light_with_both_scores_up_is_discarded(self):
        # The touch really was a double, but the score read is self-
        # contradictory, so it must not become a label.
        d = decide_priority_label(DOUBLE, "2-1", "3-2", scorer="left")
        assert not d.accepted
        assert d.reject_reason == REJECT_SCORE_BOTH_INCREASED
        # Still counted as a two-light for the yield funnel.
        assert d.both_lamps is True

    def test_scorer_disagreeing_with_score_is_discarded(self):
        d = decide_priority_label(DOUBLE, "2-1", "3-1", scorer="right")
        assert not d.accepted
        assert d.reject_reason == REJECT_SCORER_MISMATCH
        assert d.scoring_side == "left"

    def test_unknown_scorer_does_not_trigger_mismatch(self):
        for scorer in (None, "", "unclear", "both"):
            d = decide_priority_label(DOUBLE, "2-1", "3-1", scorer=scorer)
            assert d.accepted, scorer

    def test_score_gate_runs_before_lamp_gate(self):
        # An unreadable score means we cannot trust anything about the touch,
        # so it is reported as a score problem rather than a lamp problem.
        d = decide_priority_label(None, "??", "3-1")
        assert d.reject_reason == REJECT_SCORE_UNPARSEABLE

    @pytest.mark.parametrize(
        "before,after,reason",
        [
            ("3-1", "2-1", REJECT_SCORE_DECREASED),
            ("3-1", "3-1", REJECT_SCORE_UNCHANGED),
            ("1-0", "3-0", REJECT_SCORE_JUMP),
        ],
    )
    def test_bad_score_transitions_discarded_even_when_double(self, before, after, reason):
        d = decide_priority_label(DOUBLE, before, after)
        assert not d.accepted
        assert d.reject_reason == reason


class TestConfidenceGate:
    def test_inert_by_default(self):
        d = decide_priority_label(DOUBLE, "0-0", "1-0", lamp_confidence=0.0)
        assert d.accepted

    def test_below_threshold_rejected(self):
        d = decide_priority_label(
            DOUBLE, "0-0", "1-0", lamp_confidence=0.30, min_confidence=0.50
        )
        assert not d.accepted
        assert d.reject_reason == REJECT_LOW_CONFIDENCE
        assert d.both_lamps is True

    def test_at_threshold_accepted(self):
        d = decide_priority_label(
            DOUBLE, "0-0", "1-0", lamp_confidence=0.50, min_confidence=0.50
        )
        assert d.accepted

    def test_threshold_does_not_rescue_single_lamp(self):
        d = decide_priority_label(
            SINGLE_LEFT, "0-0", "1-0", lamp_confidence=1.0, min_confidence=0.5
        )
        assert d.reject_reason == REJECT_SINGLE_LAMP


class TestSimultaneityGate:
    """Both lamps lit, but not at the same time, is not a double.

    Measured on the Li-Lin bout: seven genuine doubles overlapped for 48-57
    frames, while one apparent double — the right lamp, then the left one 51
    frames later — overlapped for zero and was the only wrong label in the set.
    """

    def test_inert_by_default(self):
        d = decide_priority_label(DOUBLE, "0-0", "1-0", overlap_frames=0)
        assert d.accepted

    def test_sequential_lamps_rejected(self):
        d = decide_priority_label(
            DOUBLE, "0-0", "1-0", overlap_frames=0, min_overlap_frames=9
        )
        assert not d.accepted
        assert d.reject_reason == REJECT_NOT_SIMULTANEOUS
        assert d.both_lamps is True
        assert d.label is None

    def test_genuine_overlap_accepted(self):
        d = decide_priority_label(
            DOUBLE, "0-0", "1-0", overlap_frames=54, min_overlap_frames=9
        )
        assert d.accepted and d.label == "left"

    def test_at_threshold_accepted(self):
        d = decide_priority_label(
            DOUBLE, "0-0", "1-0", overlap_frames=9, min_overlap_frames=9
        )
        assert d.accepted

    def test_just_below_threshold_rejected(self):
        d = decide_priority_label(
            DOUBLE, "0-0", "1-0", overlap_frames=8, min_overlap_frames=9
        )
        assert d.reject_reason == REJECT_NOT_SIMULTANEOUS

    def test_unmeasured_overlap_cannot_reject(self):
        # None means "not measured", which must not be read as "zero overlap".
        d = decide_priority_label(
            DOUBLE, "0-0", "1-0", overlap_frames=None, min_overlap_frames=9
        )
        assert d.accepted

    def test_gate_does_not_apply_to_single_lamp(self):
        d = decide_priority_label(
            SINGLE_LEFT, "0-0", "1-0", overlap_frames=0, min_overlap_frames=9
        )
        assert d.reject_reason == REJECT_SINGLE_LAMP

    def test_runs_before_confidence_gate(self):
        # A sequential pair can still score a high per-side confidence, since
        # confidence is computed per side and never compares the two.
        d = decide_priority_label(
            DOUBLE, "0-0", "1-0",
            overlap_frames=0, min_overlap_frames=9,
            lamp_confidence=0.1, min_confidence=0.5,
        )
        assert d.reject_reason == REJECT_NOT_SIMULTANEOUS


class TestInvariants:
    def test_rejected_never_carries_a_label(self):
        cases = [
            (SINGLE_LEFT, "2-1", "3-1"),
            (WHITE, "2-1", "3-1"),
            (None, "2-1", "3-1"),
            (DOUBLE, "2-1", "3-2"),
            (DOUBLE, "3-1", "3-1"),
            (DOUBLE, "junk", "3-1"),
        ]
        for pattern, before, after in cases:
            d = decide_priority_label(pattern, before, after)
            assert not d.accepted
            assert d.label is None, (pattern, before, after)

    def test_accepted_label_always_matches_scoring_side(self):
        for before, after, side in [("0-0", "1-0", "left"), ("0-0", "0-1", "right")]:
            d = decide_priority_label(DOUBLE, before, after)
            assert d.accepted
            assert d.label == side == d.scoring_side

    def test_every_reject_reason_appears_in_report_order(self):
        # The yield table iterates REJECT_ORDER; a reason missing from it would
        # be silently dropped from the funnel.
        produced = set()
        for pattern in (DOUBLE, SINGLE_LEFT, WHITE, None):
            for before, after in [
                ("2-1", "3-1"), ("2-1", "3-2"), ("3-1", "2-1"),
                ("3-1", "3-1"), ("1-0", "3-0"), ("junk", "3-1"),
            ]:
                d = decide_priority_label(pattern, before, after, scorer="left")
                if d.reject_reason:
                    produced.add(d.reject_reason)
        produced.add(REJECT_SCORER_MISMATCH)
        produced.add(REJECT_LOW_CONFIDENCE)
        produced.add(REJECT_NOT_SIMULTANEOUS)
        assert produced <= set(REJECT_ORDER)

    def test_decision_is_immutable(self):
        d = decide_priority_label(DOUBLE, "0-0", "1-0")
        with pytest.raises(Exception):
            d.label = "right"
