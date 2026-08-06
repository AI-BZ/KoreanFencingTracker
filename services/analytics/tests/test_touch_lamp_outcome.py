"""Tests for the lamp-informed attack-outcome detail (foil priority).

The scoring-box lamps explain *why* a verdict is what it is; they never change
it. These tests pin that boundary down: ``attack_outcome`` and the exchange
attribution must survive lamp annotation byte-identical, a touch with no lamp
must serialise exactly as it does today plus the new keys, and a single lamp
that contradicts the OCR scorer must be quarantined rather than believed.
"""

import copy

import pytest

from analyzer.touch_matching import (
    ATTACK_OUTCOME_DETAIL_KO,
    ATTACK_OUTCOME_KO,
    NO_PRIORITY_CALL,
    annotate_touch_lamp,
    annotate_touch_lamps,
    annotate_touch_outcome,
    classify_attack_outcome_detail,
    lamp_scorer_conflict,
    summarize_attack_outcomes,
)
from analyzer.tv_overlay_ocr import LampReading, LampSideReading

# Keys owned by annotate_touch_outcome; lamp code must never write them.
VERDICT_KEYS = (
    "attack_outcome",
    "attack_outcome_ko",
    "attacker_side",
    "defender_side",
    "matched_exchange_number",
)

# Keys annotate_touch_lamp is allowed to add.
LAMP_KEYS = (
    "lamp_pattern",
    "lamp_confidence",
    "lamp_detail",
    "lamp_scorer_conflict",
    "attack_outcome_detail",
    "attack_outcome_detail_ko",
)


def _ex(number, start, end, fw_left=None, fw_right=None):
    return {
        "exchange_number": number,
        "start_frame": start,
        "end_frame": end,
        "min_distance_frame": end - 10,
        "footwork_left": fw_left,
        "footwork_right": fw_right,
    }


def _reading(pattern, *, confidence=0.8, start_frame=4100, end_frame=4160):
    """A LampReading with side states consistent with ``pattern``."""
    states = {
        "double": ("color", "color"),
        "single_left": ("color", "off"),
        "single_right": ("off", "color"),
        "white": ("white", "off"),
        None: ("off", "off"),
    }[pattern]
    return LampReading(
        pattern=pattern,
        confidence=confidence,
        left=LampSideReading(state=states[0], peak_fill=0.7, on_frames=30),
        right=LampSideReading(state=states[1], peak_fill=0.7, on_frames=30),
        start_frame=start_frame,
        end_frame=end_frame,
        frames_sampled=20,
    )


def _touch(scorer, attacker, outcome, frame=4160):
    """A touch already annotated by annotate_touch_outcome."""
    defender = {"left": "right", "right": "left"}.get(attacker, "unclear")
    return {
        "touch_number": 1,
        "frame": frame,
        "scorer": scorer,
        "attack_outcome": outcome,
        "attack_outcome_ko": ATTACK_OUTCOME_KO[outcome],
        "attacker_side": attacker,
        "defender_side": defender,
        "matched_exchange_number": 12,
    }


def _mirror_side(side):
    return {"left": "right", "right": "left"}.get(side, side)


def _mirror_pattern(pattern):
    return {"single_left": "single_right", "single_right": "single_left"}.get(
        pattern, pattern,
    )


# ---------------------------------------------------------------------------
# classify_attack_outcome_detail — the rule table
# ---------------------------------------------------------------------------


class TestClassifyAttackOutcomeDetail:
    def test_success_with_double_is_priority_won(self):
        assert (
            classify_attack_outcome_detail("attack_success", "left", "left", "double")
            == "priority_won"
        )

    def test_success_with_matching_single_is_clean_hit(self):
        assert (
            classify_attack_outcome_detail(
                "attack_success", "left", "left", "single_left",
            )
            == "clean_hit"
        )
        assert (
            classify_attack_outcome_detail(
                "attack_success", "right", "right", "single_right",
            )
            == "clean_hit"
        )

    def test_failed_with_double_is_priority_lost(self):
        assert (
            classify_attack_outcome_detail("attack_failed", "left", "right", "double")
            == "priority_lost"
        )

    def test_failed_with_single_on_scorer_is_counter_scored(self):
        assert (
            classify_attack_outcome_detail(
                "attack_failed", "left", "right", "single_right",
            )
            == "attack_missed_counter_scored"
        )

    def test_unclear_with_single_is_no_priority_call(self):
        assert (
            classify_attack_outcome_detail("unclear", "unclear", "right", "single_right")
            == "single_lamp_no_priority_call"
        )

    def test_unclear_with_double_is_referee_gave_scorer(self):
        assert (
            classify_attack_outcome_detail("unclear", "unclear", "right", "double")
            == "double_lamp_referee_gave_scorer"
        )

    @pytest.mark.parametrize("outcome", ["attack_success", "attack_failed", "unclear"])
    def test_white_and_unread_yield_nothing(self, outcome):
        assert classify_attack_outcome_detail(outcome, "left", "left", "white") is None
        assert classify_attack_outcome_detail(outcome, "left", "left", None) is None

    def test_conflicting_single_yields_nothing(self):
        # scorer right but only the left lamp lit — impossible, so no detail.
        assert (
            classify_attack_outcome_detail(
                "attack_failed", "left", "right", "single_left",
            )
            is None
        )

    def test_every_detail_value_has_korean(self):
        produced = {
            classify_attack_outcome_detail(*args)
            for args in [
                ("attack_success", "left", "left", "double"),
                ("attack_success", "left", "left", "single_left"),
                ("attack_failed", "left", "right", "double"),
                ("attack_failed", "left", "right", "single_right"),
                ("unclear", "unclear", "right", "single_right"),
                ("unclear", "unclear", "right", "double"),
            ]
        }
        assert produced == set(ATTACK_OUTCOME_DETAIL_KO)
        assert all(isinstance(v, str) and v for v in ATTACK_OUTCOME_DETAIL_KO.values())

    def test_existing_outcome_korean_strings_untouched(self):
        """The three original verdicts keep their exact wording.

        ``no_priority_call`` was added alongside them; it must not have been
        implemented by re-wording an existing key.
        """
        for key, expected in {
            "attack_success": "공격 성공",
            "attack_failed": "공격 실패 (방어 성공)",
            "unclear": "판별 불가",
        }.items():
            assert ATTACK_OUTCOME_KO[key] == expected

    def test_no_priority_call_is_the_only_addition(self):
        assert set(ATTACK_OUTCOME_KO) == {
            "attack_success",
            "attack_failed",
            "unclear",
            NO_PRIORITY_CALL,
        }

    def test_no_priority_call_korean_does_not_claim_a_verdict(self):
        text = ATTACK_OUTCOME_KO[NO_PRIORITY_CALL]
        assert text == "단독 유효타 (우선권 판정 없음)"
        # Must not imply we decided whether the attack worked.
        assert "성공" not in text
        assert "실패" not in text
        # Must not read as an analysis failure either.
        assert "판별 불가" not in text


# ---------------------------------------------------------------------------
# lamp_scorer_conflict
# ---------------------------------------------------------------------------


class TestLampScorerConflict:
    def test_single_lamp_opposite_scorer_is_conflict(self):
        assert lamp_scorer_conflict("single_left", "right") is True
        assert lamp_scorer_conflict("single_right", "left") is True

    def test_single_lamp_matching_scorer_is_fine(self):
        assert lamp_scorer_conflict("single_left", "left") is False
        assert lamp_scorer_conflict("single_right", "right") is False

    def test_double_white_and_unread_are_never_conflicts(self):
        for pattern in ("double", "white", None):
            assert lamp_scorer_conflict(pattern, "left") is False
            assert lamp_scorer_conflict(pattern, "right") is False

    def test_unknown_scorer_is_not_a_conflict(self):
        assert lamp_scorer_conflict("single_left", None) is False
        assert lamp_scorer_conflict("single_left", "both") is False


# ---------------------------------------------------------------------------
# annotate_touch_lamp
# ---------------------------------------------------------------------------


class TestAnnotateTouchLamp:
    def test_returns_same_dict(self):
        touch = _touch("left", "left", "attack_success")
        assert annotate_touch_lamp(touch, _reading("double")) is touch

    def test_sets_pattern_confidence_and_detail(self):
        touch = _touch("left", "left", "attack_success")
        annotate_touch_lamp(touch, _reading("double", confidence=0.62))
        assert touch["lamp_pattern"] == "double"
        assert touch["lamp_confidence"] == pytest.approx(0.62)
        assert touch["attack_outcome_detail"] == "priority_won"
        assert touch["attack_outcome_detail_ko"] == ATTACK_OUTCOME_DETAIL_KO["priority_won"]
        assert touch["lamp_scorer_conflict"] is False

    def test_lamp_detail_carries_reading_fields_plus_lead_frames(self):
        reading = _reading("single_left", start_frame=4100)
        touch = _touch("left", "left", "attack_success", frame=4160)
        annotate_touch_lamp(touch, reading)
        detail = touch["lamp_detail"]
        for key, value in reading.to_dict().items():
            assert detail[key] == value
        assert detail["lead_frames"] == 60

    def test_lead_frames_none_when_frames_unavailable(self):
        touch = _touch("left", "left", "attack_success")
        annotate_touch_lamp(touch, _reading("single_left", start_frame=None))
        assert touch["lamp_detail"]["lead_frames"] is None

        touch2 = _touch("left", "left", "attack_success")
        touch2.pop("frame")
        annotate_touch_lamp(touch2, _reading("single_left"))
        assert touch2["lamp_detail"]["lead_frames"] is None

    def test_lamp_detail_does_not_alias_the_reading(self):
        reading = _reading("double")
        touch = _touch("left", "left", "attack_success")
        annotate_touch_lamp(touch, reading)
        touch["lamp_detail"]["pattern"] = "tampered"
        assert reading.pattern == "double"

    def test_no_reading_leaves_null_lamp_fields(self):
        touch = _touch("left", "left", "attack_success")
        annotate_touch_lamp(touch, None)
        assert touch["lamp_pattern"] is None
        assert touch["lamp_confidence"] == 0.0
        assert touch["lamp_detail"] is None
        assert touch["lamp_scorer_conflict"] is False
        assert touch["attack_outcome_detail"] is None
        assert touch["attack_outcome_detail_ko"] is None

    def test_unread_reading_still_records_detail_dict(self):
        """A LampReading that found nothing is not the same as no reading."""
        touch = _touch("left", "left", "attack_success")
        annotate_touch_lamp(touch, LampReading())
        assert touch["lamp_pattern"] is None
        assert touch["lamp_confidence"] == 0.0
        assert touch["lamp_detail"] is not None
        assert touch["lamp_detail"]["lead_frames"] is None
        assert touch["attack_outcome_detail"] is None

    def test_white_lamp_yields_no_detail(self):
        touch = _touch("left", "left", "attack_success")
        annotate_touch_lamp(touch, _reading("white"))
        assert touch["lamp_pattern"] == "white"
        assert touch["attack_outcome_detail"] is None
        assert touch["lamp_scorer_conflict"] is False

    def test_conflict_flag_set_and_detail_suppressed(self):
        touch = _touch("right", "left", "attack_failed")
        annotate_touch_lamp(touch, _reading("single_left"))
        assert touch["lamp_scorer_conflict"] is True
        assert touch["lamp_pattern"] == "single_left"   # still reported
        assert touch["attack_outcome_detail"] is None
        assert touch["attack_outcome_detail_ko"] is None

    def test_missing_outcome_annotation_is_tolerated(self):
        touch = {"frame": 4160, "scorer": "left"}
        annotate_touch_lamp(touch, _reading("double"))
        assert touch["lamp_pattern"] == "double"
        assert touch["attack_outcome_detail"] is None


class TestLampNeverChangesVerdict:
    """Hard requirement 1: the lamp explains, it does not overrule footwork.

    The single documented exception — ``unclear`` + single lamp becomes
    ``no_priority_call`` — is pinned in :class:`TestNoPriorityCallPromotion`.
    Everything else, including the attribution keys, must survive untouched.
    """

    @pytest.mark.parametrize(
        "pattern", ["double", "single_left", "single_right", "white", None],
    )
    @pytest.mark.parametrize(
        "scorer,attacker,outcome",
        [
            ("left", "left", "attack_success"),
            ("right", "left", "attack_failed"),
            ("left", "unclear", "unclear"),
            ("right", "right", "attack_success"),
        ],
    )
    def test_attribution_keys_survive_every_combination(
        self, pattern, scorer, attacker, outcome,
    ):
        """``attacker_side`` / ``defender_side`` / exchange are never written."""
        touch = _touch(scorer, attacker, outcome)
        keys = ("attacker_side", "defender_side", "matched_exchange_number")
        before = {k: touch[k] for k in keys}
        annotate_touch_lamp(touch, _reading(pattern))
        assert {k: touch[k] for k in keys} == before

    @pytest.mark.parametrize(
        "pattern", ["double", "single_left", "single_right", "white", None],
    )
    @pytest.mark.parametrize(
        "scorer,attacker,outcome",
        [
            ("left", "left", "attack_success"),
            ("right", "left", "attack_failed"),
            ("right", "right", "attack_success"),
        ],
    )
    def test_determined_verdicts_are_never_downgraded(
        self, pattern, scorer, attacker, outcome,
    ):
        touch = _touch(scorer, attacker, outcome)
        before = {k: touch[k] for k in VERDICT_KEYS}
        annotate_touch_lamp(touch, _reading(pattern))
        assert {k: touch[k] for k in VERDICT_KEYS} == before

    @pytest.mark.parametrize("pattern", ["double", "white", None])
    def test_unclear_survives_non_single_lamps(self, pattern):
        touch = _touch("left", "unclear", "unclear")
        before = {k: touch[k] for k in VERDICT_KEYS}
        annotate_touch_lamp(touch, _reading(pattern))
        assert {k: touch[k] for k in VERDICT_KEYS} == before

    def test_conflict_does_not_change_outcome(self):
        touch = _touch("right", "left", "attack_failed")
        before = copy.deepcopy(touch)
        annotate_touch_lamp(touch, _reading("single_left"))
        assert touch["lamp_scorer_conflict"] is True
        for key in VERDICT_KEYS:
            assert touch[key] == before[key]

    def test_only_lamp_keys_are_added(self):
        exchanges = [_ex(12, 4000, 4100, "lunge", "retreat")]
        touch = {"frame": 4160, "scorer": "left"}
        annotate_touch_outcome(touch, exchanges, fps=30.0)
        before = copy.deepcopy(touch)
        annotate_touch_lamp(touch, _reading("double"))
        assert set(touch) - set(before) == set(LAMP_KEYS)
        for key in before:
            assert touch[key] == before[key]


class TestNoPriorityCallPromotion:
    """The one narrow case where the lamp is allowed to write attack_outcome."""

    @pytest.mark.parametrize(
        "scorer,pattern", [("left", "single_left"), ("right", "single_right")],
    )
    def test_unclear_plus_single_lamp_becomes_no_priority_call(self, scorer, pattern):
        touch = _touch(scorer, "unclear", "unclear")
        annotate_touch_lamp(touch, _reading(pattern))
        assert touch["attack_outcome"] == NO_PRIORITY_CALL
        assert touch["attack_outcome_ko"] == ATTACK_OUTCOME_KO[NO_PRIORITY_CALL]
        assert touch["attack_outcome_detail"] == "single_lamp_no_priority_call"

    @pytest.mark.parametrize(
        "scorer,pattern", [("left", "single_left"), ("right", "single_right")],
    )
    def test_promotion_leaves_the_attacker_unknown(self, scorer, pattern):
        """We still do not know who attacked — only that priority never arose."""
        touch = _touch(scorer, "unclear", "unclear")
        annotate_touch_lamp(touch, _reading(pattern))
        assert touch["attacker_side"] == "unclear"
        assert touch["defender_side"] == "unclear"
        assert touch["matched_exchange_number"] == 12

    @pytest.mark.parametrize("pattern", ["double", "white", None])
    def test_no_promotion_for_double_white_or_unread(self, pattern):
        touch = _touch("left", "unclear", "unclear")
        annotate_touch_lamp(touch, _reading(pattern))
        assert touch["attack_outcome"] == "unclear"
        assert touch["attack_outcome_ko"] == ATTACK_OUTCOME_KO["unclear"]

    def test_no_promotion_when_reading_is_missing_entirely(self):
        touch = _touch("left", "unclear", "unclear")
        annotate_touch_lamp(touch, None)
        assert touch["attack_outcome"] == "unclear"

    def test_no_promotion_when_lamp_conflicts_with_scorer(self):
        """A lamp we cannot trust must not be allowed to relabel the touch."""
        touch = _touch("right", "unclear", "unclear")
        annotate_touch_lamp(touch, _reading("single_left"))
        assert touch["lamp_scorer_conflict"] is True
        assert touch["attack_outcome"] == "unclear"
        assert touch["attack_outcome_detail"] is None

    @pytest.mark.parametrize("outcome", ["attack_success", "attack_failed"])
    @pytest.mark.parametrize("pattern", ["single_left", "single_right"])
    def test_determined_outcomes_are_never_downgraded(self, outcome, pattern):
        scorer = "left" if pattern == "single_left" else "right"
        attacker = scorer if outcome == "attack_success" else _mirror_side(scorer)
        touch = _touch(scorer, attacker, outcome)
        annotate_touch_lamp(touch, _reading(pattern))
        assert touch["attack_outcome"] == outcome
        assert touch["attack_outcome_ko"] == ATTACK_OUTCOME_KO[outcome]

    @pytest.mark.parametrize("pattern", ["single_left", "single_right"])
    def test_promotion_is_idempotent(self, pattern):
        scorer = "left" if pattern == "single_left" else "right"
        touch = _touch(scorer, "unclear", "unclear")
        reading = _reading(pattern)
        annotate_touch_lamp(touch, reading)
        once = copy.deepcopy(touch)
        annotate_touch_lamp(touch, reading)
        annotate_touch_lamp(touch, reading)
        assert touch == once

    def test_promotion_adds_no_keys_beyond_the_lamp_set(self):
        exchanges = [_ex(12, 4000, 4100, "fleche", "fleche")]   # mutual → unclear
        touch = {"frame": 4160, "scorer": "left"}
        annotate_touch_outcome(touch, exchanges, fps=30.0)
        assert touch["attack_outcome"] == "unclear"
        before = copy.deepcopy(touch)
        annotate_touch_lamp(touch, _reading("single_left"))
        assert set(touch) - set(before) == set(LAMP_KEYS)
        for key in before:
            if key in ("attack_outcome", "attack_outcome_ko"):
                continue
            assert touch[key] == before[key]

    def test_mirrored_promotion_is_symmetric(self):
        left = _touch("left", "unclear", "unclear")
        right = _touch("right", "unclear", "unclear")
        annotate_touch_lamp(left, _reading("single_left"))
        annotate_touch_lamp(right, _reading("single_right"))
        assert left["attack_outcome"] == right["attack_outcome"] == NO_PRIORITY_CALL


class TestSerialisationParity:
    """Hard requirement 2: no-lamp touches must not regress."""

    def test_annotate_touch_outcome_alone_is_unchanged(self):
        exchanges = [_ex(12, 4000, 4100, "lunge", "retreat")]
        touch = {"frame": 4160, "scorer": "right"}
        annotate_touch_outcome(touch, exchanges, fps=30.0)
        assert touch == {
            "frame": 4160,
            "scorer": "right",
            "attack_outcome": "attack_failed",
            "attack_outcome_ko": "공격 실패 (방어 성공)",
            "attacker_side": "left",
            "defender_side": "right",
            "matched_exchange_number": 12,
        }

    def test_none_reading_adds_only_null_valued_keys(self):
        exchanges = [_ex(12, 4000, 4100, "lunge", "retreat")]
        touch = {"frame": 4160, "scorer": "right"}
        annotate_touch_outcome(touch, exchanges, fps=30.0)
        before = copy.deepcopy(touch)
        annotate_touch_lamp(touch, None)
        assert set(touch) - set(before) == set(LAMP_KEYS)
        assert all(touch[k] == before[k] for k in before)
        assert touch["lamp_confidence"] == 0.0
        assert all(
            touch[k] is None
            for k in LAMP_KEYS
            if k not in ("lamp_confidence", "lamp_scorer_conflict")
        )


class TestIdempotence:
    """Hard requirement 3."""

    @pytest.mark.parametrize(
        "pattern", ["double", "single_left", "single_right", "white", None],
    )
    def test_twice_with_same_reading_is_identical(self, pattern):
        touch = _touch("left", "left", "attack_success")
        reading = _reading(pattern)
        annotate_touch_lamp(touch, reading)
        once = copy.deepcopy(touch)
        annotate_touch_lamp(touch, reading)
        assert touch == once

    def test_twice_with_no_reading_is_identical(self):
        touch = _touch("left", "left", "attack_success")
        annotate_touch_lamp(touch, None)
        once = copy.deepcopy(touch)
        annotate_touch_lamp(touch, None)
        assert touch == once

    def test_conflict_case_is_idempotent(self):
        touch = _touch("right", "left", "attack_failed")
        reading = _reading("single_left")
        annotate_touch_lamp(touch, reading)
        once = copy.deepcopy(touch)
        annotate_touch_lamp(touch, reading)
        assert touch == once


class TestLeftRightSymmetry:
    """Hard requirement 4: mirroring the bout mirrors nothing but the sides."""

    @pytest.mark.parametrize(
        "scorer,attacker,outcome,pattern",
        [
            ("left", "left", "attack_success", "double"),
            ("left", "left", "attack_success", "single_left"),
            ("right", "left", "attack_failed", "double"),
            ("right", "left", "attack_failed", "single_right"),
            ("right", "unclear", "unclear", "single_right"),
            ("right", "unclear", "unclear", "double"),
            ("left", "left", "attack_success", "white"),
            ("right", "left", "attack_failed", "single_left"),   # conflict
        ],
    )
    def test_mirrored_touch_gets_mirrored_detail(
        self, scorer, attacker, outcome, pattern,
    ):
        touch = _touch(scorer, attacker, outcome)
        mirrored = _touch(
            _mirror_side(scorer), _mirror_side(attacker), outcome,
        )
        annotate_touch_lamp(touch, _reading(pattern))
        annotate_touch_lamp(mirrored, _reading(_mirror_pattern(pattern)))

        assert mirrored["attack_outcome_detail"] == touch["attack_outcome_detail"]
        assert mirrored["lamp_scorer_conflict"] == touch["lamp_scorer_conflict"]
        assert mirrored["lamp_pattern"] == _mirror_pattern(touch["lamp_pattern"])


# ---------------------------------------------------------------------------
# annotate_touch_lamps
# ---------------------------------------------------------------------------


class TestAnnotateTouchLamps:
    def test_parallel_lists_annotated_in_order(self):
        touches = [
            _touch("left", "left", "attack_success"),
            _touch("right", "left", "attack_failed"),
            _touch("left", "unclear", "unclear"),
        ]
        readings = [_reading("double"), _reading("single_right"), None]
        out = annotate_touch_lamps(touches, readings)
        assert out is touches
        assert [t["attack_outcome_detail"] for t in touches] == [
            "priority_won",
            "attack_missed_counter_scored",
            None,
        ]
        assert [t["lamp_pattern"] for t in touches] == ["double", "single_right", None]

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError, match="parallel lists"):
            annotate_touch_lamps([_touch("left", "left", "attack_success")], [])

    def test_empty_lists(self):
        assert annotate_touch_lamps([], []) == []


# ---------------------------------------------------------------------------
# summarize_attack_outcomes — additive "lamp" sub-dict
# ---------------------------------------------------------------------------


def _annotated_bout():
    exchanges = [
        _ex(1, 0, 100, "advance", "retreat"),      # left attacks
        _ex(2, 300, 400, "advance", "retreat"),    # left attacks
        _ex(3, 600, 700, "retreat", "lunge"),      # right attacks
        _ex(4, 900, 1000, "fleche", "fleche"),     # mutual → unclear
    ]
    touches = [
        {"frame": 130, "scorer": "left"},
        {"frame": 430, "scorer": "right"},
        {"frame": 730, "scorer": "right"},
        {"frame": 1030, "scorer": "left"},
        {"frame": 9999, "scorer": "left"},
    ]
    for t in touches:
        annotate_touch_outcome(t, exchanges, fps=30.0)
    return touches


# Summary keys that are *supposed* to move when lamp readings arrive.
LAMP_DERIVED_SUMMARY_KEYS = ("lamp", "priority", "no_priority_call_touches")


class TestSummaryLampSubDict:
    def test_existing_keys_keep_their_values_without_lamps(self):
        touches = _annotated_bout()
        baseline = summarize_attack_outcomes(touches)
        annotate_touch_lamps(touches, [None] * len(touches))
        after = summarize_attack_outcomes(touches)
        for key, value in baseline.items():
            if key in LAMP_DERIVED_SUMMARY_KEYS:
                continue
            assert after[key] == value

    def test_lamps_do_not_move_any_existing_counter(self):
        touches = _annotated_bout()
        baseline = summarize_attack_outcomes(touches)
        annotate_touch_lamps(
            touches,
            [
                _reading("double"),
                _reading("single_right"),
                _reading("single_right"),
                _reading("double"),
                _reading("white"),
            ],
        )
        after = summarize_attack_outcomes(touches)
        for key, value in baseline.items():
            if key in LAMP_DERIVED_SUMMARY_KEYS:
                continue
            assert after[key] == value

    def test_lamp_counts(self):
        touches = _annotated_bout()
        annotate_touch_lamps(
            touches,
            [
                _reading("double"),
                _reading("single_right"),
                _reading("single_left"),   # scorer is right → conflict
                _reading("white"),
                None,
            ],
        )
        lamp = summarize_attack_outcomes(touches)["lamp"]
        assert lamp == {
            "double": 1,
            "single_left": 1,
            "single_right": 1,
            "white": 1,
            "unread": 1,
            "conflict": 1,
        }

    def test_pattern_buckets_sum_to_total_touches(self):
        touches = _annotated_bout()
        annotate_touch_lamps(
            touches,
            [_reading("double"), _reading("single_right"), None, None, _reading("white")],
        )
        s = summarize_attack_outcomes(touches)
        lamp = s["lamp"]
        assert (
            lamp["double"]
            + lamp["single_left"]
            + lamp["single_right"]
            + lamp["white"]
            + lamp["unread"]
        ) == s["total_touches"]

    def test_unannotated_touches_all_count_as_unread(self):
        s = summarize_attack_outcomes(_annotated_bout())
        assert s["lamp"] == {
            "double": 0,
            "single_left": 0,
            "single_right": 0,
            "white": 0,
            "unread": 5,
            "conflict": 0,
        }

    def test_empty_touches(self):
        s = summarize_attack_outcomes([])
        assert s["lamp"]["unread"] == 0
        assert s["lamp"]["conflict"] == 0


# ---------------------------------------------------------------------------
# summarize_attack_outcomes — no_priority_call split + priority sub-dict
# ---------------------------------------------------------------------------


class TestSummaryNoPriorityCallSplit:
    """A no-priority-call touch must not be silently counted as unclear."""

    def test_split_between_unclear_and_no_priority_call(self):
        touches = _annotated_bout()
        # index 3 (mutual attack) and index 4 (unmatched) are the unclear ones.
        annotate_touch_lamps(
            touches,
            [
                _reading("double"),
                _reading("single_right"),
                _reading("single_right"),
                _reading("single_left"),   # unclear + single → promoted
                _reading("double"),        # unclear + double → stays unclear
            ],
        )
        s = summarize_attack_outcomes(touches)
        assert s["no_priority_call_touches"] == 1
        assert s["unclear_touches"] == 1

    def test_buckets_partition_the_bout(self):
        touches = _annotated_bout()
        annotate_touch_lamps(
            touches,
            [
                _reading("double"),
                _reading("single_right"),
                _reading("single_right"),
                _reading("single_left"),
                _reading("double"),
            ],
        )
        s = summarize_attack_outcomes(touches)
        assert (
            s["left"]["attack_attempts"]
            + s["right"]["attack_attempts"]
            + s["unclear_touches"]
            + s["no_priority_call_touches"]
        ) == s["total_touches"]

    def test_no_priority_call_does_not_become_an_attack_attempt(self):
        touches = _annotated_bout()
        baseline = summarize_attack_outcomes(touches)
        annotate_touch_lamps(
            touches,
            [
                _reading("double"),
                _reading("single_right"),
                _reading("single_right"),
                _reading("single_left"),
                _reading("double"),
            ],
        )
        after = summarize_attack_outcomes(touches)
        for side in ("left", "right"):
            assert after[side] == baseline[side]
        assert after["matched_touches"] == baseline["matched_touches"]
        assert after["total_touches"] == baseline["total_touches"]

    def test_zero_without_any_lamp_data(self):
        s = summarize_attack_outcomes(_annotated_bout())
        assert s["no_priority_call_touches"] == 0
        assert s["unclear_touches"] == 2


class TestSummaryPrioritySubDict:
    def test_denominators_and_rates(self):
        touches = _annotated_bout()
        annotate_touch_lamps(
            touches,
            [
                _reading("double"),        # determined
                _reading("single_right"),  # determined
                _reading("single_right"),  # determined
                _reading("single_left"),   # unclear → no_priority_call
                _reading("double"),        # unclear, double → ruled_unclear
            ],
        )
        assert summarize_attack_outcomes(touches)["priority"] == {
            "ruled": 2,
            "not_required": 3,
            "ruled_unclear": 1,
            "ruled_unclear_rate": 50.0,
            "unexplained": 1,
            "unexplained_rate": 20.0,
        }

    def test_ruled_plus_not_required_matches_the_lamp_buckets(self):
        touches = _annotated_bout()
        annotate_touch_lamps(
            touches,
            [
                _reading("double"),
                _reading("single_right"),
                None,
                _reading("white"),
                _reading("double"),
            ],
        )
        s = summarize_attack_outcomes(touches)
        assert s["priority"]["ruled"] == s["lamp"]["double"]
        assert s["priority"]["not_required"] == (
            s["lamp"]["single_left"] + s["lamp"]["single_right"]
        )

    def test_unexplained_equals_unclear_touches(self):
        touches = _annotated_bout()
        annotate_touch_lamps(
            touches,
            [
                _reading("double"),
                _reading("single_right"),
                _reading("single_right"),
                _reading("single_left"),
                _reading("double"),
            ],
        )
        s = summarize_attack_outcomes(touches)
        assert s["priority"]["unexplained"] == s["unclear_touches"]

    def test_rates_are_zero_when_denominator_is_zero(self):
        s = summarize_attack_outcomes([])
        assert s["priority"] == {
            "ruled": 0,
            "not_required": 0,
            "ruled_unclear": 0,
            "ruled_unclear_rate": 0.0,
            "unexplained": 0,
            "unexplained_rate": 0.0,
        }

    def test_no_double_lamps_gives_zero_ruled_rate_not_a_crash(self):
        touches = _annotated_bout()
        annotate_touch_lamps(touches, [_reading("single_left")] * 5)
        p = summarize_attack_outcomes(touches)["priority"]
        assert p["ruled"] == 0
        assert p["ruled_unclear_rate"] == 0.0

    def test_the_two_rates_are_independent_measures(self):
        """They use different denominators and must not be collapsed into one.

        Constructed so accuracy-on-priority-cases is bad (100% of the ruled
        touches are unclear) while overall coverage is comparatively fine —
        quoting either number alone would misrepresent the bout.
        """
        touches = _annotated_bout()
        annotate_touch_lamps(
            touches,
            [
                _reading("single_left"),   # determined
                _reading("single_right"),  # determined
                _reading("single_right"),  # determined
                _reading("double"),        # unclear + double
                _reading("single_left"),   # unclear + single → promoted
            ],
        )
        p = summarize_attack_outcomes(touches)["priority"]
        assert p["ruled"] == 1
        assert p["ruled_unclear"] == 1
        assert p["ruled_unclear_rate"] == 100.0
        assert p["unexplained"] == 1
        assert p["unexplained_rate"] == 20.0
        assert p["ruled_unclear_rate"] != p["unexplained_rate"]
