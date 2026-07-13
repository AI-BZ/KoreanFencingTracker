"""Regression tests for the "final-complete" gate on event final rankings.

Bug: in-progress events showed premature 1/2/3 because the competition detail
render computed final_rankings from partial DE brackets with no check that the
final (결승) bout was played. Fix: `_is_de_final_complete()` gates the
render-time compute paths.

These tests pin `_is_de_final_complete` behavior. The gate itself
(server.py: competition_detail_page) uses:

    can_finalize = _is_de_final_complete(de_bracket) or bool(existing_rankings)

so that FINISHED events (which have DB-stored KFA rankings) are never hidden —
critical because some finished events have self-bout placeholder brackets where
bracket detection alone returns False (see test_self_bout_placeholder_final).
"""
import pytest

from app.de_transforms import _is_de_final_complete


def _bracket(bouts):
    return {"full_bouts": bouts}


class TestFinalComplete:
    def test_final_with_winner_name(self):
        b = _bracket([
            {"round_name": "준결승", "winner_name": "A", "player1_name": "A", "player2_name": "B",
             "player1_score": 15, "player2_score": 10},
            {"round_name": "결승", "winner_name": "A", "player1_name": "A", "player2_name": "C",
             "player1_score": 15, "player2_score": 12},
        ])
        assert _is_de_final_complete(b) is True

    def test_final_decided_by_score_only(self):
        b = _bracket([
            {"round_name": "결승", "player1_name": "A", "player2_name": "C",
             "player1_score": 15, "player2_score": 13},
        ])
        assert _is_de_final_complete(b) is True


class TestFinalIncomplete:
    def test_semifinal_only_no_final_bout(self):
        b = _bracket([
            {"round_name": "준결승", "winner_name": "A", "player1_name": "A", "player2_name": "B",
             "player1_score": 15, "player2_score": 10},
            {"round_name": "준결승", "winner_name": "C", "player1_name": "C", "player2_name": "D",
             "player1_score": 15, "player2_score": 9},
        ])
        assert _is_de_final_complete(b) is False

    def test_final_bout_pending_no_winner_no_score(self):
        b = _bracket([
            {"round_name": "결승", "player1_name": "A", "player2_name": "C"},
        ])
        assert _is_de_final_complete(b) is False

    def test_final_tied_score_not_decisive(self):
        b = _bracket([
            {"round_name": "결승", "player1_name": "A", "player2_name": "C",
             "player1_score": 10, "player2_score": 10},
        ])
        assert _is_de_final_complete(b) is False

    def test_self_bout_placeholder_final(self):
        # Some FINISHED events store placeholder self-bouts (p1==p2, no winner)
        # in full_bouts while the real result lives in KFA-scraped final_rankings.
        # _get_full_bouts_from_de_bracket filters self-bouts, so no 결승 remains.
        # The gate must rely on existing_rankings for these — this documents why.
        b = _bracket([
            {"round_name": "준결승", "player1_name": "정효정", "player2_name": "정효정"},
            {"round_name": "결승", "player1_name": "정효정", "player2_name": "정효정"},
        ])
        assert _is_de_final_complete(b) is False


class TestEdgeCases:
    def test_empty_bracket(self):
        assert _is_de_final_complete({}) is False

    def test_none_bracket(self):
        assert _is_de_final_complete(None) is False

    def test_non_dict_bracket(self):
        assert _is_de_final_complete("not a dict") is False

    def test_dual_de_final_in_second_de(self):
        # Dual DE: qualifying (first_de) has no final; the real 결승 is in second_de.
        b = {
            "format": "dual_de",
            "first_de": {"full_bouts": [
                {"round_name": "64강", "winner_name": "A", "player1_name": "A", "player2_name": "B",
                 "player1_score": 15, "player2_score": 8},
            ]},
            "second_de": {"full_bouts": [
                {"round_name": "결승", "winner_name": "A", "player1_name": "A", "player2_name": "C",
                 "player1_score": 15, "player2_score": 11},
            ]},
        }
        assert _is_de_final_complete(b) is True

    def test_dual_de_second_de_final_pending(self):
        b = {
            "format": "dual_de",
            "first_de": {"full_bouts": [
                {"round_name": "64강", "winner_name": "A", "player1_name": "A", "player2_name": "B",
                 "player1_score": 15, "player2_score": 8},
            ]},
            "second_de": {"full_bouts": [
                {"round_name": "준결승", "winner_name": "A", "player1_name": "A", "player2_name": "C",
                 "player1_score": 15, "player2_score": 9},
            ]},
        }
        assert _is_de_final_complete(b) is False
