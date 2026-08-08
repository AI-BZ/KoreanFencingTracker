"""Tests for analyzer.touch_matching — touch→exchange matching and Part B
attack success/failure judgment.

The clip bounds themselves are covered by tests/test_clip_overlay.py
(TestComputeTouchClipBounds); here we cover the matcher those bounds are built
on, plus the attacker/outcome rules layered on top of it.
"""

import pytest

from analyzer.touch_matching import (
    annotate_touch_outcome,
    annotate_touch_outcomes,
    classify_attack_outcome,
    classify_exchange_sides,
    compute_touch_clip_bounds,
    determine_attacker,
    match_touch_to_exchange,
    summarize_attack_outcomes,
)


def _ex(number, start, end, fw_left=None, fw_right=None, min_dist=None):
    d = {
        "exchange_number": number,
        "start_frame": start,
        "end_frame": end,
        "min_distance_frame": min_dist if min_dist is not None else end - 10,
    }
    if fw_left is not None:
        d["footwork_left"] = fw_left
    if fw_right is not None:
        d["footwork_right"] = fw_right
    return d


# ---------------------------------------------------------------------------
# match_touch_to_exchange
# ---------------------------------------------------------------------------


class TestMatchTouchToExchange:
    def test_picks_preceding_exchange_within_delay(self):
        exchanges = [_ex(1, 4000, 4100)]
        ex, gap = match_touch_to_exchange(4100 + int(2.8 * 30), exchanges, fps=30.0)
        assert ex is not None and ex["exchange_number"] == 1
        assert gap == int(2.8 * 30)

    def test_closest_end_wins_among_candidates(self):
        exchanges = [_ex(1, 4000, 4050), _ex(2, 4060, 4150)]
        ex, _ = match_touch_to_exchange(4160, exchanges, fps=30.0)
        assert ex["exchange_number"] == 2

    def test_beyond_delay_window_no_match(self):
        exchanges = [_ex(1, 900, 1000)]
        ex, gap = match_touch_to_exchange(1000 + int(4.0 * 30) + 1, exchanges, fps=30.0)
        assert ex is None and gap is None

    def test_forward_tolerance_for_late_pose_end(self):
        """Pose end a few frames after the OCR touch still matches (0.5s tol)."""
        exchanges = [_ex(4, 15900, 15954)]
        ex, gap = match_touch_to_exchange(15950, exchanges, fps=30.0)
        assert ex is not None and ex["exchange_number"] == 4
        assert gap == -4

    def test_exchange_after_touch_beyond_tolerance_not_matched(self):
        exchanges = [_ex(1, 5000, 5100)]
        ex, _ = match_touch_to_exchange(5000, exchanges, fps=30.0)
        assert ex is None

    def test_empty_inputs(self):
        assert match_touch_to_exchange(1000, [], fps=30.0) == (None, None)
        assert match_touch_to_exchange(None, [_ex(1, 0, 100)], fps=30.0) == (None, None)

    def test_matching_shared_with_clip_bounds(self):
        """The clip window is anchored on the same exchange the matcher returns."""
        exchanges = [_ex(7, 4000, 4100, min_dist=4090)]
        touch = 4100 + int(2.0 * 30)
        ex, _ = match_touch_to_exchange(touch, exchanges, fps=30.0)
        start, end = compute_touch_clip_bounds(touch, exchanges, [], fps=30.0)
        assert start == ex["start_frame"]
        assert end == ex["min_distance_frame"] + int(0.3 * 30)


# ---------------------------------------------------------------------------
# Attacker determination
# ---------------------------------------------------------------------------


class TestClassifyExchangeSides:
    @pytest.mark.parametrize("fw", ["advance", "lunge", "fleche"])
    def test_each_aggressive_footwork_makes_attacker(self, fw):
        assert classify_exchange_sides(fw, "retreat") == ("left", "right")
        assert classify_exchange_sides("retreat", fw) == ("right", "left")

    def test_both_aggressive_is_both(self):
        assert classify_exchange_sides("fleche", "advance") == ("both", "both")

    def test_neither_aggressive_is_unknown(self):
        assert classify_exchange_sides("retreat", "retreat") == ("unknown", "unknown")
        assert classify_exchange_sides("stationary", "retreat") == ("unknown", "unknown")

    def test_missing_footwork_is_unknown(self):
        assert classify_exchange_sides(None, None) == ("unknown", "unknown")

    def test_attacker_against_stationary_opponent(self):
        """Defender need not retreat — a lone aggressor still owns the attack."""
        assert classify_exchange_sides("lunge", "stationary") == ("left", "right")


class TestDetermineAttacker:
    def test_single_aggressor(self):
        assert determine_attacker(_ex(1, 0, 100, "lunge", "retreat")) == "left"
        assert determine_attacker(_ex(1, 0, 100, "retreat", "fleche")) == "right"

    def test_mutual_attack_is_unclear(self):
        assert determine_attacker(_ex(1, 0, 100, "advance", "advance")) == "unclear"

    def test_no_aggressor_is_unclear(self):
        assert determine_attacker(_ex(1, 0, 100, "retreat", "stationary")) == "unclear"
        assert determine_attacker(_ex(1, 0, 100)) == "unclear"


# ---------------------------------------------------------------------------
# Outcome rule
# ---------------------------------------------------------------------------


class TestClassifyAttackOutcome:
    def test_attacker_scores_is_success(self):
        assert classify_attack_outcome("left", "left") == "attack_success"
        assert classify_attack_outcome("right", "right") == "attack_success"

    def test_defender_scores_is_failed_attack(self):
        assert classify_attack_outcome("right", "left") == "attack_failed"
        assert classify_attack_outcome("left", "right") == "attack_failed"

    def test_unclear_attacker_is_unclear(self):
        assert classify_attack_outcome("left", "unclear") == "unclear"
        assert classify_attack_outcome("left", None) == "unclear"

    def test_unknown_scorer_is_unclear(self):
        assert classify_attack_outcome(None, "left") == "unclear"
        assert classify_attack_outcome("both", "left") == "unclear"


# ---------------------------------------------------------------------------
# Per-touch annotation
# ---------------------------------------------------------------------------


class TestAnnotateTouchOutcome:
    def test_attacker_scores(self):
        exchanges = [_ex(12, 4000, 4100, "lunge", "retreat")]
        touch = {"frame": 4100 + 60, "scorer": "left"}
        annotate_touch_outcome(touch, exchanges, fps=30.0)
        assert touch["attack_outcome"] == "attack_success"
        assert touch["attacker_side"] == "left"
        assert touch["defender_side"] == "right"
        assert touch["matched_exchange_number"] == 12
        assert touch["attack_outcome_ko"] == "공격 성공"

    def test_defender_scores(self):
        exchanges = [_ex(12, 4000, 4100, "lunge", "retreat")]
        touch = {"frame": 4100 + 60, "scorer": "right"}
        annotate_touch_outcome(touch, exchanges, fps=30.0)
        assert touch["attack_outcome"] == "attack_failed"
        assert touch["attacker_side"] == "left"
        assert touch["defender_side"] == "right"

    def test_both_attacking_is_unclear_but_still_matched(self):
        exchanges = [_ex(12, 4000, 4100, "fleche", "fleche")]
        touch = {"frame": 4100 + 60, "scorer": "left"}
        annotate_touch_outcome(touch, exchanges, fps=30.0)
        assert touch["attack_outcome"] == "unclear"
        assert touch["attacker_side"] == "unclear"
        assert touch["defender_side"] == "unclear"
        assert touch["matched_exchange_number"] == 12

    def test_no_matching_exchange_fallback(self):
        exchanges = [_ex(1, 900, 1000, "lunge", "retreat")]
        touch = {"frame": 3000, "scorer": "left"}
        annotate_touch_outcome(touch, exchanges, fps=30.0)
        assert touch["attack_outcome"] == "unclear"
        assert touch["attacker_side"] is None
        assert touch["matched_exchange_number"] is None

    def test_missing_frame_is_unclear(self):
        touch = {"scorer": "left"}
        annotate_touch_outcome(touch, [_ex(1, 0, 100, "lunge", "retreat")], fps=30.0)
        assert touch["attack_outcome"] == "unclear"
        assert touch["matched_exchange_number"] is None

    def test_legacy_exchange_without_footwork(self):
        exchanges = [{"exchange_number": 3, "start_frame": 100, "end_frame": 200}]
        touch = {"frame": 230, "scorer": "left"}
        annotate_touch_outcome(touch, exchanges, fps=30.0)
        assert touch["attack_outcome"] == "unclear"
        assert touch["matched_exchange_number"] == 3

    def test_annotate_many_returns_same_list(self):
        exchanges = [_ex(1, 0, 100, "advance", "retreat"), _ex(2, 300, 400, "retreat", "advance")]
        touches = [{"frame": 130, "scorer": "left"}, {"frame": 430, "scorer": "left"}]
        out = annotate_touch_outcomes(touches, exchanges, fps=30.0)
        assert out is touches
        assert [t["attack_outcome"] for t in touches] == ["attack_success", "attack_failed"]


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


class TestSummarizeAttackOutcomes:
    def _annotated(self):
        exchanges = [
            _ex(1, 0, 100, "advance", "retreat"),      # left attacks
            _ex(2, 300, 400, "advance", "retreat"),    # left attacks
            _ex(3, 600, 700, "retreat", "lunge"),      # right attacks
            _ex(4, 900, 1000, "fleche", "fleche"),     # mutual → unclear
        ]
        touches = [
            {"frame": 130, "scorer": "left"},    # left attack → success
            {"frame": 430, "scorer": "right"},   # left attack → failed / right defends
            {"frame": 730, "scorer": "right"},   # right attack → success
            {"frame": 1030, "scorer": "left"},   # unclear
            {"frame": 9999, "scorer": "left"},   # unmatched → unclear
        ]
        return annotate_touch_outcomes(touches, exchanges, fps=30.0)

    def test_counts_and_rates(self):
        s = summarize_attack_outcomes(self._annotated())
        assert s["left"]["attack_attempts"] == 2
        assert s["left"]["attack_success"] == 1
        assert s["left"]["attack_failed"] == 1
        assert s["left"]["attack_success_rate"] == 50.0
        assert s["right"]["attack_attempts"] == 1
        assert s["right"]["attack_success"] == 1
        assert s["right"]["attack_success_rate"] == 100.0

    def test_defense_success_mirrors_opponent_failed_attack(self):
        s = summarize_attack_outcomes(self._annotated())
        assert s["right"]["defense_success"] == s["left"]["attack_failed"] == 1
        assert s["left"]["defense_success"] == s["right"]["attack_failed"] == 0

    def test_totals_and_unclear(self):
        s = summarize_attack_outcomes(self._annotated())
        assert s["total_touches"] == 5
        assert s["matched_touches"] == 4      # 4 matched, 1 beyond the delay window
        assert s["unclear_touches"] == 2      # mutual attack + unmatched

    def test_empty_touches(self):
        s = summarize_attack_outcomes([])
        assert s["total_touches"] == 0
        assert s["left"]["attack_success_rate"] == 0.0
        assert s["right"]["attack_attempts"] == 0

    def test_no_division_by_zero_without_attempts(self):
        touches = annotate_touch_outcomes(
            [{"frame": 130, "scorer": "left"}],
            [_ex(1, 0, 100, "fleche", "fleche")],
            fps=30.0,
        )
        s = summarize_attack_outcomes(touches)
        assert s["left"]["attack_success_rate"] == 0.0
