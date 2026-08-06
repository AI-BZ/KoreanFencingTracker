"""Regression guard for the ``no_priority_call`` outcome.

Adding a fourth ``attack_outcome`` state is only safe if it takes touches
*exclusively* from the ``unclear`` bucket. Two things must therefore not move:

1. The nine touches of the reference foil bout (Li vs Lin, ``hKUXgUsDOKE``)
   that already carry a determined verdict — ``attack_success`` /
   ``attack_failed``. A determined verdict is strictly more informative than
   "no priority ruling was made", so being downgraded to ``no_priority_call``
   would be a loss of information, not a gain in honesty.
2. Every report produced before the lamp pass existed. Six of the seven
   continuous gallery reports have no ``lamp_pattern`` on any touch; they must
   serialise and summarise exactly as they did.

The expected values are written out literally rather than derived, so that a
change in the annotation code shows up as a test failure instead of quietly
recomputing its own baseline. They are cross-checked against the real report on
disk when it is available.
"""

import copy
import json
from pathlib import Path

import pytest

from analyzer.touch_matching import (
    ATTACK_OUTCOME_KO,
    NO_PRIORITY_CALL,
    annotate_touch_lamp,
    annotate_touch_lamps,
    summarize_attack_outcomes,
)
from analyzer.tv_overlay_ocr import LampReading, LampSideReading

REPORT_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "reports"
    / "jr_foil_final_li_lin_hKUXgUsDOKE_continuous_report.json"
)

# ---------------------------------------------------------------------------
# The reference bout, transcribed from the report. 22 touches:
#   (touch_number, scorer, attacker_side, attack_outcome, lamp_pattern)
# ---------------------------------------------------------------------------

BOUT = [
    (1, "right", "left", "attack_failed", "single_right"),
    (2, "left", "right", "attack_failed", "double"),
    (3, "left", "unclear", "unclear", "double"),
    (4, "left", "unclear", "unclear", "double"),
    (5, "left", "unclear", "unclear", "single_left"),
    (6, "left", "unclear", "unclear", "single_left"),
    (7, "right", "unclear", "unclear", "single_right"),
    (8, "left", "right", "attack_failed", "single_left"),
    (9, "left", "left", "attack_success", "single_left"),
    (10, "right", "unclear", "unclear", "single_right"),
    (11, "right", "unclear", "unclear", "single_right"),
    (12, "left", None, "unclear", "double"),
    (13, "left", "unclear", "unclear", "double"),
    (14, "left", "left", "attack_success", "single_left"),
    (15, "left", "left", "attack_success", "double"),
    (16, "left", "right", "attack_failed", "single_left"),
    (17, "right", "right", "attack_success", "single_right"),
    (18, "left", "unclear", "unclear", "single_left"),
    (19, "left", "right", "attack_failed", "double"),
    (20, "right", "unclear", "unclear", "single_right"),
    (21, "right", "unclear", "unclear", "single_right"),
    (22, "left", "unclear", "unclear", "double"),
]

# The nine touches whose verdict must survive the lamp pass byte-identical.
DETERMINED = {
    1: "attack_failed",
    2: "attack_failed",
    8: "attack_failed",
    9: "attack_success",
    14: "attack_success",
    15: "attack_success",
    16: "attack_failed",
    17: "attack_success",
    19: "attack_failed",
}

# The eight unclear + single-lamp touches that become no_priority_call.
EXPECTED_PROMOTED = [5, 6, 7, 10, 11, 18, 20, 21]

# The five unclear touches that stay unclear (double lamp — a real priority
# case the referee did rule on, and we still cannot account for it).
EXPECTED_STILL_UNCLEAR = [3, 4, 12, 13, 22]


def _reading(pattern):
    states = {
        "double": ("color", "color"),
        "single_left": ("color", "off"),
        "single_right": ("off", "color"),
        "white": ("white", "off"),
        None: ("off", "off"),
    }[pattern]
    return LampReading(
        pattern=pattern,
        confidence=1.0,
        left=LampSideReading(state=states[0], peak_fill=0.8, on_frames=60),
        right=LampSideReading(state=states[1], peak_fill=0.8, on_frames=60),
        start_frame=1000,
        end_frame=1100,
        frames_sampled=40,
    )


def _bout_touches():
    """The bout as it stands *before* the lamp pass."""
    touches = []
    for number, scorer, attacker, outcome, _pattern in BOUT:
        defender = {"left": "right", "right": "left"}.get(attacker, attacker)
        touches.append(
            {
                "touch_number": number,
                "frame": 1000 + number * 100,
                "scorer": scorer,
                "attack_outcome": outcome,
                "attack_outcome_ko": ATTACK_OUTCOME_KO[outcome],
                "attacker_side": attacker,
                "defender_side": defender,
                "matched_exchange_number": None if number == 12 else number,
            },
        )
    return touches


def _bout_readings():
    return [_reading(pattern) for *_rest, pattern in BOUT]


@pytest.fixture
def annotated_bout():
    touches = _bout_touches()
    annotate_touch_lamps(touches, _bout_readings())
    return touches


# ---------------------------------------------------------------------------
# The hard requirement: determined verdicts are untouched
# ---------------------------------------------------------------------------


class TestDeterminedTouchesAreFrozen:
    @pytest.mark.parametrize("number,outcome", sorted(DETERMINED.items()))
    def test_each_determined_touch_keeps_its_exact_outcome(
        self, annotated_bout, number, outcome,
    ):
        touch = next(t for t in annotated_bout if t["touch_number"] == number)
        assert touch["attack_outcome"] == outcome
        assert touch["attack_outcome_ko"] == ATTACK_OUTCOME_KO[outcome]

    def test_all_nine_and_only_those_nine_are_determined(self, annotated_bout):
        determined = {
            t["touch_number"]: t["attack_outcome"]
            for t in annotated_bout
            if t["attack_outcome"] in ("attack_success", "attack_failed")
        }
        assert determined == DETERMINED

    def test_verdict_fields_are_byte_identical_before_and_after(self):
        """Full deep comparison of every verdict key on the nine touches."""
        keys = (
            "attack_outcome",
            "attack_outcome_ko",
            "attacker_side",
            "defender_side",
            "matched_exchange_number",
        )
        touches = _bout_touches()
        before = {
            t["touch_number"]: {k: copy.deepcopy(t[k]) for k in keys}
            for t in touches
            if t["touch_number"] in DETERMINED
        }
        annotate_touch_lamps(touches, _bout_readings())
        after = {
            t["touch_number"]: {k: t[k] for k in keys}
            for t in touches
            if t["touch_number"] in DETERMINED
        }
        assert after == before

    def test_attribution_never_written_for_any_touch(self):
        """No touch, promoted or not, gets a fabricated attacker."""
        keys = ("attacker_side", "defender_side", "matched_exchange_number")
        touches = _bout_touches()
        before = {t["touch_number"]: {k: t[k] for k in keys} for t in touches}
        annotate_touch_lamps(touches, _bout_readings())
        after = {t["touch_number"]: {k: t[k] for k in keys} for t in touches}
        assert after == before


# ---------------------------------------------------------------------------
# The promotion itself
# ---------------------------------------------------------------------------


class TestPromotedTouches:
    def test_exactly_the_expected_touches_are_promoted(self, annotated_bout):
        promoted = [
            t["touch_number"]
            for t in annotated_bout
            if t["attack_outcome"] == NO_PRIORITY_CALL
        ]
        assert promoted == EXPECTED_PROMOTED

    def test_double_lamp_unclear_touches_stay_unclear(self, annotated_bout):
        still_unclear = [
            t["touch_number"]
            for t in annotated_bout
            if t["attack_outcome"] == "unclear"
        ]
        assert still_unclear == EXPECTED_STILL_UNCLEAR

    def test_promoted_touches_carry_the_new_korean(self, annotated_bout):
        for t in annotated_bout:
            if t["attack_outcome"] == NO_PRIORITY_CALL:
                assert t["attack_outcome_ko"] == "단독 유효타 (우선권 판정 없음)"
                assert t["attack_outcome_detail"] == "single_lamp_no_priority_call"

    def test_promotion_is_the_only_outcome_change(self):
        touches = _bout_touches()
        before = {t["touch_number"]: t["attack_outcome"] for t in touches}
        annotate_touch_lamps(touches, _bout_readings())
        changed = {
            t["touch_number"]
            for t in touches
            if t["attack_outcome"] != before[t["touch_number"]]
        }
        assert changed == set(EXPECTED_PROMOTED)
        # Everything that changed came out of the unclear bucket.
        assert all(before[n] == "unclear" for n in changed)

    def test_annotating_twice_is_stable(self):
        touches = _bout_touches()
        annotate_touch_lamps(touches, _bout_readings())
        once = copy.deepcopy(touches)
        annotate_touch_lamps(touches, _bout_readings())
        assert touches == once


# ---------------------------------------------------------------------------
# Summary numbers
# ---------------------------------------------------------------------------


class TestBoutSummary:
    def test_unchanged_counters_match_the_pre_change_values(self, annotated_bout):
        """These are the numbers the report already publishes. None may move."""
        s = summarize_attack_outcomes(annotated_bout)
        assert s["left"] == {
            "attack_attempts": 4,
            "attack_success": 3,
            "attack_failed": 1,
            "attack_success_rate": 75.0,
            "defense_success": 4,
        }
        assert s["right"] == {
            "attack_attempts": 5,
            "attack_success": 1,
            "attack_failed": 4,
            "attack_success_rate": 20.0,
            "defense_success": 1,
        }
        assert s["total_touches"] == 22
        assert s["matched_touches"] == 21

    def test_unclear_is_split_five_and_eight(self, annotated_bout):
        s = summarize_attack_outcomes(annotated_bout)
        assert s["unclear_touches"] == 5           # was 13 before the split
        assert s["no_priority_call_touches"] == 8
        assert s["unclear_touches"] + s["no_priority_call_touches"] == 13

    def test_priority_sub_dict(self, annotated_bout):
        assert summarize_attack_outcomes(annotated_bout)["priority"] == {
            "ruled": 8,
            "not_required": 14,
            "ruled_unclear": 5,
            "ruled_unclear_rate": 62.5,
            "unexplained": 5,
            "unexplained_rate": 22.7,
        }

    def test_the_two_rates_differ_and_are_both_reported(self, annotated_bout):
        """62.5% is accuracy on real priority cases; 22.7% is bout coverage.

        They are different measurements, not two estimates of one thing, so the
        summary must expose both — quoting either alone misrepresents the bout.
        """
        s = summarize_attack_outcomes(annotated_bout)
        p = s["priority"]
        assert p["ruled_unclear_rate"] == 62.5
        assert p["unexplained_rate"] == 22.7
        # Different denominators is the whole point: 5/8 vs 5/22.
        assert p["ruled"] == 8
        assert p["ruled"] != s["total_touches"]
        assert p["ruled"] + p["not_required"] == s["total_touches"]

    def test_buckets_partition_the_bout(self, annotated_bout):
        s = summarize_attack_outcomes(annotated_bout)
        assert (
            s["left"]["attack_attempts"]
            + s["right"]["attack_attempts"]
            + s["unclear_touches"]
            + s["no_priority_call_touches"]
        ) == s["total_touches"]


# ---------------------------------------------------------------------------
# Reports without lamp data must not regress
# ---------------------------------------------------------------------------


class TestNoLampDataUnaffected:
    """Six of the seven continuous gallery reports have no lamp fields at all."""

    def test_touch_without_lamp_fields_is_untouched_by_summary(self):
        touches = [
            {
                "touch_number": 1,
                "scorer": "left",
                "attack_outcome": "attack_success",
                "attacker_side": "left",
                "matched_exchange_number": 3,
            },
            {
                "touch_number": 2,
                "scorer": "right",
                "attack_outcome": "unclear",
                "attacker_side": "unclear",
                "matched_exchange_number": 5,
            },
        ]
        frozen = copy.deepcopy(touches)
        s = summarize_attack_outcomes(touches)
        assert touches == frozen                      # summary reads only
        assert s["unclear_touches"] == 1
        assert s["no_priority_call_touches"] == 0
        assert s["lamp"]["unread"] == 2
        assert s["priority"] == {
            "ruled": 0,
            "not_required": 0,
            "ruled_unclear": 0,
            "ruled_unclear_rate": 0.0,
            "unexplained": 1,
            "unexplained_rate": 50.0,
        }

    def test_none_reading_never_promotes(self):
        touch = {
            "touch_number": 1,
            "frame": 100,
            "scorer": "left",
            "attack_outcome": "unclear",
            "attack_outcome_ko": ATTACK_OUTCOME_KO["unclear"],
            "attacker_side": "unclear",
            "defender_side": "unclear",
            "matched_exchange_number": 2,
        }
        annotate_touch_lamp(touch, None)
        assert touch["attack_outcome"] == "unclear"
        assert touch["attack_outcome_ko"] == "판별 불가"

    @pytest.mark.parametrize(
        "name",
        [
            "usaf_B6k6SoJFAr8_continuous_report.json",
            "usaf_Jiq1kQLftjw_continuous_report.json",
            "usaf_UzQ8Ci7lft8_continuous_report.json",
            "usaf_hKUXgUsDOKE_continuous_report.json",
            "usaf_zTsHbehQrC0_continuous_report.json",
            "nac_y12wf_lee_esaki_k-spxGdlWfo_continuous_report.json",
        ],
    )
    def test_lampless_gallery_report_has_no_promoted_touches(self, name):
        path = REPORT_PATH.parent / name
        if not path.exists():
            pytest.skip(f"{name} not present")
        touches = json.loads(path.read_text())["touches"]
        assert all("lamp_pattern" not in t for t in touches)
        s = summarize_attack_outcomes(touches)
        assert s["no_priority_call_touches"] == 0
        assert s["priority"]["ruled"] == 0
        assert s["priority"]["not_required"] == 0


# ---------------------------------------------------------------------------
# Cross-check the literal fixture against the report actually on disk
# ---------------------------------------------------------------------------


class TestFixtureMatchesRealReport:
    @pytest.fixture
    def real_touches(self):
        if not REPORT_PATH.exists():
            pytest.skip("reference foil report not present")
        return json.loads(REPORT_PATH.read_text())["touches"]

    def test_transcription_is_faithful(self, real_touches):
        """If the report is regenerated, this fixture must be updated with it."""
        actual = [
            (
                t["touch_number"],
                t["scorer"],
                t["attacker_side"],
                t["attack_outcome"],
                t["lamp_pattern"],
            )
            for t in real_touches
        ]
        # BOUT records the pre-promotion outcomes, which is what the rest of
        # this module exercises. The stored report has since been regenerated
        # through the lamp pass, so it holds the promoted outcomes — applying
        # the promotion rule to BOUT must reproduce it exactly.
        expected = [
            (
                number,
                scorer,
                attacker,
                NO_PRIORITY_CALL
                if outcome == "unclear" and lamp in ("single_left", "single_right")
                else outcome,
                lamp,
            )
            for number, scorer, attacker, outcome, lamp in BOUT
        ]
        assert actual == expected

    def test_real_report_promotes_the_same_eight(self, real_touches):
        touches = copy.deepcopy(real_touches)
        readings = [_reading(t["lamp_pattern"]) for t in touches]
        annotate_touch_lamps(touches, readings)
        promoted = [
            t["touch_number"]
            for t in touches
            if t["attack_outcome"] == NO_PRIORITY_CALL
        ]
        assert promoted == EXPECTED_PROMOTED
