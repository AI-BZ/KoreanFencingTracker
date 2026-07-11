"""
FencingLab Player Analytics - Comprehensive Unit Tests
Test coverage for clutch analysis, finish type analysis, momentum, form, and edge cases.
"""

import pytest
from app.player_analytics import (
    FencingLabAnalyzer,
    MatchResult,
    PlayerAnalytics,
    make_player_key,
    parse_player_key,
    get_analytics_text,
)


class TestMatchResultProperties:
    """Test MatchResult property methods and calculations."""

    def test_score_diff_positive_win(self):
        """Test score_diff returns positive value for wins."""
        match = MatchResult(
            competition_name="Test",
            event_name="Event",
            round_name="Pool 1",
            opponent_name="Opponent",
            opponent_team="TeamB",
            player_score=5,
            opponent_score=3,
            is_win=True,
            is_pool=True,
        )
        assert match.score_diff == 2

    def test_score_diff_negative_loss(self):
        """Test score_diff returns negative value for losses."""
        match = MatchResult(
            competition_name="Test",
            event_name="Event",
            round_name="Pool 1",
            opponent_name="Opponent",
            opponent_team="TeamB",
            player_score=3,
            opponent_score=5,
            is_win=False,
            is_pool=True,
        )
        assert match.score_diff == -2

    def test_is_clutch_pool_one_point(self):
        """Test is_clutch for Pool 1-point games (5:4, 4:5)."""
        match_win = MatchResult(
            competition_name="Test",
            event_name="Event",
            round_name="Pool 1",
            opponent_name="Opponent",
            opponent_team="TeamB",
            player_score=5,
            opponent_score=4,
            is_win=True,
            is_pool=True,
        )
        match_loss = MatchResult(
            competition_name="Test",
            event_name="Event",
            round_name="Pool 1",
            opponent_name="Opponent",
            opponent_team="TeamB",
            player_score=4,
            opponent_score=5,
            is_win=False,
            is_pool=True,
        )
        assert match_win.is_clutch is True
        assert match_loss.is_clutch is True

    def test_is_clutch_de_one_point(self):
        """Test is_clutch for DE 1-point games (15:14, 14:15)."""
        match_win = MatchResult(
            competition_name="Test",
            event_name="Event",
            round_name="32강전",
            opponent_name="Opponent",
            opponent_team="TeamB",
            player_score=15,
            opponent_score=14,
            is_win=True,
            is_pool=False,
        )
        match_loss = MatchResult(
            competition_name="Test",
            event_name="Event",
            round_name="32강전",
            opponent_name="Opponent",
            opponent_team="TeamB",
            player_score=14,
            opponent_score=15,
            is_win=False,
            is_pool=False,
        )
        assert match_win.is_clutch is True
        assert match_loss.is_clutch is True

    def test_is_clutch_not_one_point(self):
        """Test is_clutch returns False for non-1-point games."""
        match = MatchResult(
            competition_name="Test",
            event_name="Event",
            round_name="Pool 1",
            opponent_name="Opponent",
            opponent_team="TeamB",
            player_score=5,
            opponent_score=3,
            is_win=True,
            is_pool=True,
        )
        assert match.is_clutch is False

    def test_is_timeout_pool(self):
        """Test is_timeout for Pool games ending before 5 points."""
        match = MatchResult(
            competition_name="Test",
            event_name="Event",
            round_name="Pool 1",
            opponent_name="Opponent",
            opponent_team="TeamB",
            player_score=4,
            opponent_score=3,
            is_win=True,
            is_pool=True,
        )
        assert match.is_timeout is True
        assert match.is_fullscore is False

    def test_is_fullscore_pool(self):
        """Test is_fullscore for Pool games reaching 5 points."""
        match = MatchResult(
            competition_name="Test",
            event_name="Event",
            round_name="Pool 1",
            opponent_name="Opponent",
            opponent_team="TeamB",
            player_score=5,
            opponent_score=4,
            is_win=True,
            is_pool=True,
        )
        assert match.is_fullscore is True
        assert match.is_timeout is False

    def test_is_timeout_de(self):
        """Test is_timeout for DE games ending before 15 points."""
        match = MatchResult(
            competition_name="Test",
            event_name="Event",
            round_name="32강전",
            opponent_name="Opponent",
            opponent_team="TeamB",
            player_score=14,
            opponent_score=13,
            is_win=True,
            is_pool=False,
        )
        assert match.is_timeout is True
        assert match.is_fullscore is False

    def test_is_fullscore_de(self):
        """Test is_fullscore for DE games reaching 15 points."""
        match = MatchResult(
            competition_name="Test",
            event_name="Event",
            round_name="32강전",
            opponent_name="Opponent",
            opponent_team="TeamB",
            player_score=15,
            opponent_score=10,
            is_win=True,
            is_pool=False,
        )
        assert match.is_fullscore is True
        assert match.is_timeout is False

    def test_tie_game_pool(self):
        """Test tie game handling in Pool (should not occur in real data)."""
        match = MatchResult(
            competition_name="Test",
            event_name="Event",
            round_name="Pool 1",
            opponent_name="Opponent",
            opponent_team="TeamB",
            player_score=4,
            opponent_score=4,
            is_win=False,  # Tie - no winner
            is_pool=True,
        )
        assert match.score_diff == 0
        assert match.is_clutch is False  # Not 1-point difference


class TestClutchAnalysis:
    """Test clutch analysis functionality (10+ cases)."""

    def test_clutch_strong_above_60_percent(self):
        """Test clutch grade 'strong' for 60%+ win rate."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        matches = [
            MatchResult("Comp", "Event", "Pool 1", "Opp1", "TeamB", 5, 4, True, True),
            MatchResult("Comp", "Event", "Pool 2", "Opp2", "TeamC", 5, 4, True, True),
            MatchResult("Comp", "Event", "Pool 3", "Opp3", "TeamD", 5, 4, True, True),
            MatchResult("Comp", "Event", "Pool 4", "Opp4", "TeamE", 4, 5, False, True),
        ]  # 3 wins, 1 loss = 75% win rate

        analyzer._analyze_clutch(analytics, matches)

        assert analytics.clutch_matches == 4
        assert analytics.clutch_wins == 3
        assert analytics.clutch_losses == 1
        assert analytics.clutch_rate == 75.0
        assert analytics.clutch_grade == "강심장"
        assert "3승 1패" in analytics.clutch_insight

    def test_clutch_strong_exactly_60_percent(self):
        """Test clutch grade 'strong' at exactly 60%."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        matches = [
            MatchResult("Comp", "Event", "Pool 1", "Opp1", "TeamB", 5, 4, True, True),
            MatchResult("Comp", "Event", "Pool 2", "Opp2", "TeamC", 5, 4, True, True),
            MatchResult("Comp", "Event", "Pool 3", "Opp3", "TeamD", 5, 4, True, True),
            MatchResult("Comp", "Event", "Pool 4", "Opp4", "TeamE", 4, 5, False, True),
            MatchResult("Comp", "Event", "Pool 5", "Opp5", "TeamF", 4, 5, False, True),
        ]  # 3 wins, 2 losses = 60% win rate

        analyzer._analyze_clutch(analytics, matches)

        assert analytics.clutch_rate == 60.0
        assert analytics.clutch_grade == "강심장"

    def test_clutch_average_40_to_59_percent(self):
        """Test clutch grade 'average' for 40-59% win rate."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        matches = [
            MatchResult("Comp", "Event", "Pool 1", "Opp1", "TeamB", 5, 4, True, True),
            MatchResult("Comp", "Event", "Pool 2", "Opp2", "TeamC", 5, 4, True, True),
            MatchResult("Comp", "Event", "Pool 3", "Opp3", "TeamD", 4, 5, False, True),
            MatchResult("Comp", "Event", "Pool 4", "Opp4", "TeamE", 4, 5, False, True),
        ]  # 2 wins, 2 losses = 50% win rate

        analyzer._analyze_clutch(analytics, matches)

        assert analytics.clutch_rate == 50.0
        assert analytics.clutch_grade == "평균"
        assert "2승 2패" in analytics.clutch_insight

    def test_clutch_weak_below_40_percent(self):
        """Test clutch grade 'weak' for below 40% win rate."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        matches = [
            MatchResult("Comp", "Event", "Pool 1", "Opp1", "TeamB", 5, 4, True, True),
            MatchResult("Comp", "Event", "Pool 2", "Opp2", "TeamC", 4, 5, False, True),
            MatchResult("Comp", "Event", "Pool 3", "Opp3", "TeamD", 4, 5, False, True),
            MatchResult("Comp", "Event", "Pool 4", "Opp4", "TeamE", 4, 5, False, True),
        ]  # 1 win, 3 losses = 25% win rate

        analyzer._analyze_clutch(analytics, matches)

        assert analytics.clutch_rate == 25.0
        assert analytics.clutch_grade == "접전 취약"
        assert "1승 3패" in analytics.clutch_insight

    def test_clutch_insufficient_data_2_matches(self):
        """Test clutch grade 'insufficient' for < 3 close matches."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        matches = [
            MatchResult("Comp", "Event", "Pool 1", "Opp1", "TeamB", 5, 4, True, True),
            MatchResult("Comp", "Event", "Pool 2", "Opp2", "TeamC", 4, 5, False, True),
        ]  # Only 2 clutch matches

        analyzer._analyze_clutch(analytics, matches)

        assert analytics.clutch_matches == 2
        assert analytics.clutch_grade == "데이터 부족"
        assert "2회" in analytics.clutch_insight

    def test_clutch_no_close_matches(self):
        """Test clutch analysis with no close matches."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        matches = [
            MatchResult("Comp", "Event", "Pool 1", "Opp1", "TeamB", 5, 2, True, True),
            MatchResult("Comp", "Event", "Pool 2", "Opp2", "TeamC", 5, 1, True, True),
        ]  # No clutch matches (all 3+ point differences)

        analyzer._analyze_clutch(analytics, matches)

        assert analytics.clutch_matches == 0
        assert analytics.clutch_grade == "데이터 부족"

    def test_clutch_all_close_matches(self):
        """Test clutch analysis when ALL matches are close (1-point)."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        matches = [
            MatchResult("Comp", "Event", "32강", "Opp1", "TeamB", 15, 14, True, False),
            MatchResult("Comp", "Event", "16강", "Opp2", "TeamC", 15, 14, True, False),
            MatchResult("Comp", "Event", "8강", "Opp3", "TeamD", 15, 14, True, False),
            MatchResult("Comp", "Event", "4강", "Opp4", "TeamE", 14, 15, False, False),
        ]  # All 4 matches are clutch

        analyzer._analyze_clutch(analytics, matches)

        assert analytics.clutch_matches == 4
        assert analytics.clutch_wins == 3
        assert analytics.clutch_rate == 75.0

    def test_clutch_calculation_accuracy(self):
        """Test clutch rate calculation precision."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        matches = [
            MatchResult("Comp", "Event", "Pool 1", "Opp1", "TeamB", 5, 4, True, True),
            MatchResult("Comp", "Event", "Pool 2", "Opp2", "TeamC", 5, 4, True, True),
            MatchResult("Comp", "Event", "Pool 3", "Opp3", "TeamD", 4, 5, False, True),
            MatchResult("Comp", "Event", "Pool 4", "Opp4", "TeamE", 4, 5, False, True),
            MatchResult("Comp", "Event", "Pool 5", "Opp5", "TeamF", 4, 5, False, True),
            MatchResult("Comp", "Event", "Pool 6", "Opp6", "TeamG", 4, 5, False, True),
        ]  # 2 wins, 4 losses = 33.33%

        analyzer._analyze_clutch(analytics, matches)

        assert analytics.clutch_rate == 33.3  # Rounded to 1 decimal

    def test_clutch_english_translation(self):
        """Test clutch analysis with English language."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        matches = [
            MatchResult("Comp", "Event", "Pool 1", "Opp1", "TeamB", 5, 4, True, True),
            MatchResult("Comp", "Event", "Pool 2", "Opp2", "TeamC", 5, 4, True, True),
            MatchResult("Comp", "Event", "Pool 3", "Opp3", "TeamD", 4, 5, False, True),
        ]

        analyzer._analyze_clutch(analytics, matches, lang="en")

        assert analytics.clutch_grade == "Clutch"
        assert "2W 1L" in analytics.clutch_insight


class TestFinishTypeAnalysis:
    """Test finish type analysis functionality (8+ cases)."""

    def test_fullscore_win_rate_calculation(self):
        """Test full-score win rate calculation."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        matches = [
            MatchResult("Comp", "Event", "Pool 1", "Opp1", "TeamB", 5, 3, True, True),
            MatchResult("Comp", "Event", "Pool 2", "Opp2", "TeamC", 5, 4, True, True),
            MatchResult("Comp", "Event", "Pool 3", "Opp3", "TeamD", 3, 5, False, True),
        ]  # 2 wins, 1 loss in fullscore = 66.7%

        analyzer._analyze_finish_type(analytics, matches)

        assert analytics.fullscore_matches == 3
        assert analytics.fullscore_wins == 2
        assert analytics.fullscore_win_rate == 66.7

    def test_timeout_win_rate_calculation(self):
        """Test timeout win rate calculation."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        matches = [
            MatchResult("Comp", "Event", "Pool 1", "Opp1", "TeamB", 4, 3, True, True),
            MatchResult("Comp", "Event", "Pool 2", "Opp2", "TeamC", 4, 2, True, True),
            MatchResult("Comp", "Event", "Pool 3", "Opp3", "TeamD", 3, 4, False, True),
            MatchResult("Comp", "Event", "Pool 4", "Opp4", "TeamE", 2, 4, False, True),
        ]  # 2 wins, 2 losses in timeout = 50%

        analyzer._analyze_finish_type(analytics, matches)

        assert analytics.timeout_matches == 4
        assert analytics.timeout_wins == 2
        assert analytics.timeout_win_rate == 50.0

    def test_division_by_zero_protection(self):
        """Test division by zero when no fullscore or timeout matches."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        matches = []  # No matches

        analyzer._analyze_finish_type(analytics, matches)

        assert analytics.fullscore_matches == 0
        assert analytics.fullscore_wins == 0
        assert analytics.fullscore_win_rate == 0.0
        assert analytics.timeout_matches == 0
        assert analytics.timeout_wins == 0
        assert analytics.timeout_win_rate == 0.0

    def test_fullscore_strong_insight(self):
        """Test insight for strong fullscore performance (15%+ difference)."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        matches = [
            # Fullscore: 100% (5/5)
            MatchResult("Comp", "Event", "Pool 1", "Opp1", "TeamB", 5, 3, True, True),
            MatchResult("Comp", "Event", "Pool 2", "Opp2", "TeamC", 5, 4, True, True),
            MatchResult("Comp", "Event", "Pool 3", "Opp3", "TeamD", 5, 2, True, True),
            MatchResult("Comp", "Event", "Pool 4", "Opp4", "TeamE", 5, 1, True, True),
            MatchResult("Comp", "Event", "Pool 5", "Opp5", "TeamF", 5, 0, True, True),
            # Timeout: 50% (2/4)
            MatchResult("Comp", "Event", "Pool 6", "Opp6", "TeamG", 4, 3, True, True),
            MatchResult("Comp", "Event", "Pool 7", "Opp7", "TeamH", 4, 2, True, True),
            MatchResult("Comp", "Event", "Pool 8", "Opp8", "TeamI", 3, 4, False, True),
            MatchResult("Comp", "Event", "Pool 9", "Opp9", "TeamJ", 2, 4, False, True),
        ]

        analyzer._analyze_finish_type(analytics, matches)

        assert analytics.fullscore_win_rate == 100.0
        assert analytics.timeout_win_rate == 50.0
        assert "풀스코어" in analytics.finish_type_insight
        assert "50%p" in analytics.finish_type_insight  # 100 - 50 = 50%p

    def test_timeout_strong_insight(self):
        """Test insight for strong timeout performance (15%+ difference)."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        matches = [
            # Fullscore: 33.3% (1/3)
            MatchResult("Comp", "Event", "Pool 1", "Opp1", "TeamB", 5, 3, True, True),
            MatchResult("Comp", "Event", "Pool 2", "Opp2", "TeamC", 3, 5, False, True),
            MatchResult("Comp", "Event", "Pool 3", "Opp3", "TeamD", 2, 5, False, True),
            # Timeout: 100% (3/3)
            MatchResult("Comp", "Event", "Pool 4", "Opp4", "TeamE", 4, 3, True, True),
            MatchResult("Comp", "Event", "Pool 5", "Opp5", "TeamF", 4, 2, True, True),
            MatchResult("Comp", "Event", "Pool 6", "Opp6", "TeamG", 4, 1, True, True),
        ]

        analyzer._analyze_finish_type(analytics, matches)

        assert analytics.timeout_win_rate == 100.0
        assert analytics.fullscore_win_rate == 33.3
        assert "시간종료" in analytics.finish_type_insight
        assert "67%p" in analytics.finish_type_insight  # 100 - 33.3 ≈ 67%p

    def test_finish_balanced_insight(self):
        """Test balanced insight when difference < 15%."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        matches = [
            # Fullscore: 66.7% (2/3)
            MatchResult("Comp", "Event", "Pool 1", "Opp1", "TeamB", 5, 3, True, True),
            MatchResult("Comp", "Event", "Pool 2", "Opp2", "TeamC", 5, 4, True, True),
            MatchResult("Comp", "Event", "Pool 3", "Opp3", "TeamD", 3, 5, False, True),
            # Timeout: 66.7% (2/3)
            MatchResult("Comp", "Event", "Pool 4", "Opp4", "TeamE", 4, 3, True, True),
            MatchResult("Comp", "Event", "Pool 5", "Opp5", "TeamF", 4, 2, True, True),
            MatchResult("Comp", "Event", "Pool 6", "Opp6", "TeamG", 2, 4, False, True),
        ]

        analyzer._analyze_finish_type(analytics, matches)

        assert analytics.finish_type_insight == "종료 유형에 따른 승률 차이가 크지 않습니다."

    def test_mixed_finish_types(self):
        """Test analysis with mixed Pool and DE finish types."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        matches = [
            # Pool fullscore (5 points)
            MatchResult("Comp", "Event", "Pool 1", "Opp1", "TeamB", 5, 3, True, True),
            # Pool timeout (< 5 points)
            MatchResult("Comp", "Event", "Pool 2", "Opp2", "TeamC", 4, 3, True, True),
            # DE fullscore (15 points)
            MatchResult("Comp", "Event", "32강", "Opp3", "TeamD", 15, 10, True, False),
            # DE timeout (< 15 points)
            MatchResult("Comp", "Event", "16강", "Opp4", "TeamE", 14, 13, True, False),
        ]

        analyzer._analyze_finish_type(analytics, matches)

        assert analytics.fullscore_matches == 2  # Pool + DE fullscore
        assert analytics.timeout_matches == 2  # Pool + DE timeout

    def test_tie_game_handling(self):
        """Test handling of tie games (10:10) - BUG FIX."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        # Note: Real data shouldn't have ties, but test for edge case
        matches = [
            MatchResult("Comp", "Event", "Pool 1", "Opp1", "TeamB", 4, 4, False, True),
            # This is a timeout game (< 5 points) and a tie
        ]

        analyzer._analyze_finish_type(analytics, matches)

        # Tie game should be counted as timeout (not fullscore)
        assert analytics.timeout_matches == 1
        assert analytics.fullscore_matches == 0


class TestMomentumAnalysis:
    """Test momentum and form analysis (5+ cases)."""

    def test_margin_analysis_avg_win_margin(self):
        """Test average win margin calculation."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        matches = [
            MatchResult("Comp", "Event", "Pool 1", "Opp1", "TeamB", 5, 3, True, True),
            MatchResult("Comp", "Event", "Pool 2", "Opp2", "TeamC", 5, 2, True, True),
            MatchResult("Comp", "Event", "Pool 3", "Opp3", "TeamD", 5, 4, True, True),
        ]  # Margins: 2, 3, 1 → avg = 2.0

        analyzer._analyze_margin(analytics, matches)

        assert analytics.avg_win_margin == 2.0

    def test_margin_analysis_avg_loss_margin(self):
        """Test average loss margin calculation."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        matches = [
            MatchResult("Comp", "Event", "Pool 1", "Opp1", "TeamB", 2, 5, False, True),
            MatchResult("Comp", "Event", "Pool 2", "Opp2", "TeamC", 1, 5, False, True),
            MatchResult("Comp", "Event", "Pool 3", "Opp3", "TeamD", 3, 5, False, True),
        ]  # Margins: -3, -4, -2 → avg abs = 3.0

        analyzer._analyze_margin(analytics, matches)

        assert analytics.avg_loss_margin == 3.0

    def test_blowout_wins_pool(self):
        """Test blowout win detection in Pool (3+ points)."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        matches = [
            MatchResult("Comp", "Event", "Pool 1", "Opp1", "TeamB", 5, 2, True, True),  # 3 diff
            MatchResult("Comp", "Event", "Pool 2", "Opp2", "TeamC", 5, 1, True, True),  # 4 diff
            MatchResult("Comp", "Event", "Pool 3", "Opp3", "TeamD", 5, 4, True, True),  # 1 diff
        ]

        analyzer._analyze_margin(analytics, matches)

        assert analytics.blowout_wins == 2  # Only first two

    def test_blowout_wins_de(self):
        """Test blowout win detection in DE (5+ points)."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        matches = [
            MatchResult("Comp", "Event", "32강", "Opp1", "TeamB", 15, 10, True, False),  # 5 diff
            MatchResult("Comp", "Event", "16강", "Opp2", "TeamC", 15, 8, True, False),  # 7 diff
            MatchResult("Comp", "Event", "8강", "Opp3", "TeamD", 15, 14, True, False),  # 1 diff
        ]

        analyzer._analyze_margin(analytics, matches)

        assert analytics.blowout_wins == 2  # Only first two

    def test_blowout_losses_de(self):
        """Test blowout loss detection in DE (5+ points)."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        matches = [
            MatchResult("Comp", "Event", "32강", "Opp1", "TeamB", 10, 15, False, False),  # -5
            MatchResult("Comp", "Event", "16강", "Opp2", "TeamC", 5, 15, False, False),  # -10
            MatchResult("Comp", "Event", "8강", "Opp3", "TeamD", 14, 15, False, False),  # -1
        ]

        analyzer._analyze_margin(analytics, matches)

        assert analytics.blowout_losses == 2  # Only first two


class TestFormAnalysis:
    """Test recent form and trend analysis (5+ cases)."""

    def test_recent_6_win_rate(self):
        """Test recent 6 matches win rate calculation."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        sorted_matches = [
            MatchResult("Comp", "Event", "Pool 1", "Opp1", "TeamB", 5, 3, True, True, date="2025-01-06"),
            MatchResult("Comp", "Event", "Pool 2", "Opp2", "TeamC", 5, 2, True, True, date="2025-01-05"),
            MatchResult("Comp", "Event", "Pool 3", "Opp3", "TeamD", 5, 4, True, True, date="2025-01-04"),
            MatchResult("Comp", "Event", "Pool 4", "Opp4", "TeamE", 3, 5, False, True, date="2025-01-03"),
            MatchResult("Comp", "Event", "Pool 5", "Opp5", "TeamF", 5, 2, True, True, date="2025-01-02"),
            MatchResult("Comp", "Event", "Pool 6", "Opp6", "TeamG", 2, 5, False, True, date="2025-01-01"),
        ]  # 4 wins, 2 losses = 66.7%

        analyzer._analyze_recent_6(analytics, sorted_matches)

        assert analytics.recent_6_wins == 4
        assert analytics.recent_6_losses == 2
        assert analytics.recent_6_win_rate == 66.7

    def test_recent_6_trend_upward(self):
        """Test upward trend detection (recent > previous by 10%+)."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        sorted_matches = [
            # Recent 6: 5 wins, 1 loss = 83.3%
            MatchResult("Comp", "Event", "Pool 1", "Opp1", "TeamB", 5, 3, True, True, date="2025-01-12"),
            MatchResult("Comp", "Event", "Pool 2", "Opp2", "TeamC", 5, 2, True, True, date="2025-01-11"),
            MatchResult("Comp", "Event", "Pool 3", "Opp3", "TeamD", 5, 4, True, True, date="2025-01-10"),
            MatchResult("Comp", "Event", "Pool 4", "Opp4", "TeamE", 5, 1, True, True, date="2025-01-09"),
            MatchResult("Comp", "Event", "Pool 5", "Opp5", "TeamF", 5, 2, True, True, date="2025-01-08"),
            MatchResult("Comp", "Event", "Pool 6", "Opp6", "TeamG", 3, 5, False, True, date="2025-01-07"),
            # Previous 6: 2 wins, 4 losses = 33.3%
            MatchResult("Comp", "Event", "Pool 7", "Opp7", "TeamH", 5, 3, True, True, date="2025-01-06"),
            MatchResult("Comp", "Event", "Pool 8", "Opp8", "TeamI", 2, 5, False, True, date="2025-01-05"),
            MatchResult("Comp", "Event", "Pool 9", "Opp9", "TeamJ", 3, 5, False, True, date="2025-01-04"),
            MatchResult("Comp", "Event", "Pool 10", "Opp10", "TeamK", 1, 5, False, True, date="2025-01-03"),
            MatchResult("Comp", "Event", "Pool 11", "Opp11", "TeamL", 5, 2, True, True, date="2025-01-02"),
            MatchResult("Comp", "Event", "Pool 12", "Opp12", "TeamM", 2, 5, False, True, date="2025-01-01"),
        ]

        analyzer._analyze_recent_6(analytics, sorted_matches)

        assert analytics.recent_6_trend == "상승"  # 83.3 - 33.3 = 50% > 10%

    def test_recent_6_trend_downward(self):
        """Test downward trend detection (recent < previous by 10%+)."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        sorted_matches = [
            # Recent 6: 1 win, 5 losses = 16.7%
            MatchResult("Comp", "Event", "Pool 1", "Opp1", "TeamB", 5, 3, True, True, date="2025-01-12"),
            MatchResult("Comp", "Event", "Pool 2", "Opp2", "TeamC", 2, 5, False, True, date="2025-01-11"),
            MatchResult("Comp", "Event", "Pool 3", "Opp3", "TeamD", 3, 5, False, True, date="2025-01-10"),
            MatchResult("Comp", "Event", "Pool 4", "Opp4", "TeamE", 1, 5, False, True, date="2025-01-09"),
            MatchResult("Comp", "Event", "Pool 5", "Opp5", "TeamF", 2, 5, False, True, date="2025-01-08"),
            MatchResult("Comp", "Event", "Pool 6", "Opp6", "TeamG", 3, 5, False, True, date="2025-01-07"),
            # Previous 6: 5 wins, 1 loss = 83.3%
            MatchResult("Comp", "Event", "Pool 7", "Opp7", "TeamH", 5, 3, True, True, date="2025-01-06"),
            MatchResult("Comp", "Event", "Pool 8", "Opp8", "TeamI", 5, 2, True, True, date="2025-01-05"),
            MatchResult("Comp", "Event", "Pool 9", "Opp9", "TeamJ", 5, 4, True, True, date="2025-01-04"),
            MatchResult("Comp", "Event", "Pool 10", "Opp10", "TeamK", 5, 1, True, True, date="2025-01-03"),
            MatchResult("Comp", "Event", "Pool 11", "Opp11", "TeamL", 5, 2, True, True, date="2025-01-02"),
            MatchResult("Comp", "Event", "Pool 12", "Opp12", "TeamM", 2, 5, False, True, date="2025-01-01"),
        ]

        analyzer._analyze_recent_6(analytics, sorted_matches)

        assert analytics.recent_6_trend == "하락"  # 16.7 - 83.3 = -66.6% < -10%

    def test_recent_6_trend_stable(self):
        """Test stable trend detection (difference < 10%)."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        sorted_matches = [
            # Recent 6: 3 wins, 3 losses = 50%
            MatchResult("Comp", "Event", "Pool 1", "Opp1", "TeamB", 5, 3, True, True, date="2025-01-12"),
            MatchResult("Comp", "Event", "Pool 2", "Opp2", "TeamC", 2, 5, False, True, date="2025-01-11"),
            MatchResult("Comp", "Event", "Pool 3", "Opp3", "TeamD", 5, 4, True, True, date="2025-01-10"),
            MatchResult("Comp", "Event", "Pool 4", "Opp4", "TeamE", 3, 5, False, True, date="2025-01-09"),
            MatchResult("Comp", "Event", "Pool 5", "Opp5", "TeamF", 5, 2, True, True, date="2025-01-08"),
            MatchResult("Comp", "Event", "Pool 6", "Opp6", "TeamG", 2, 5, False, True, date="2025-01-07"),
            # Previous 6: 3 wins, 3 losses = 50%
            MatchResult("Comp", "Event", "Pool 7", "Opp7", "TeamH", 5, 3, True, True, date="2025-01-06"),
            MatchResult("Comp", "Event", "Pool 8", "Opp8", "TeamI", 2, 5, False, True, date="2025-01-05"),
            MatchResult("Comp", "Event", "Pool 9", "Opp9", "TeamJ", 5, 4, True, True, date="2025-01-04"),
            MatchResult("Comp", "Event", "Pool 10", "Opp10", "TeamK", 3, 5, False, True, date="2025-01-03"),
            MatchResult("Comp", "Event", "Pool 11", "Opp11", "TeamL", 5, 2, True, True, date="2025-01-02"),
            MatchResult("Comp", "Event", "Pool 12", "Opp12", "TeamM", 2, 5, False, True, date="2025-01-01"),
        ]

        analyzer._analyze_recent_6(analytics, sorted_matches)

        assert analytics.recent_6_trend == "유지"  # 50 - 50 = 0% < 10%

    def test_recent_6_insufficient_data(self):
        """Test recent 6 analysis with < 12 total matches."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        sorted_matches = [
            MatchResult("Comp", "Event", "Pool 1", "Opp1", "TeamB", 5, 3, True, True, date="2025-01-06"),
            MatchResult("Comp", "Event", "Pool 2", "Opp2", "TeamC", 5, 2, True, True, date="2025-01-05"),
            MatchResult("Comp", "Event", "Pool 3", "Opp3", "TeamD", 5, 4, True, True, date="2025-01-04"),
        ]  # Only 3 matches total

        analyzer._analyze_recent_6(analytics, sorted_matches)

        assert analytics.recent_6_trend == "데이터 부족"
        assert len(analytics.recent_6_matches) == 3


class TestEdgeCases:
    """Test edge cases and boundary conditions (5+ cases)."""

    def test_zero_matches(self):
        """Test analysis with zero matches."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        matches = []

        analyzer._analyze_clutch(analytics, matches)
        analyzer._analyze_finish_type(analytics, matches)
        analyzer._analyze_margin(analytics, matches)
        analyzer._analyze_recent_6(analytics, matches)

        assert analytics.total_matches == 0
        assert analytics.clutch_matches == 0
        assert analytics.fullscore_matches == 0
        assert analytics.timeout_matches == 0
        assert analytics.avg_win_margin == 0.0
        assert analytics.avg_loss_margin == 0.0

    def test_single_match(self):
        """Test analysis with only 1 match."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        sorted_matches = [
            MatchResult("Comp", "Event", "Pool 1", "Opp1", "TeamB", 5, 4, True, True, date="2025-01-01"),
        ]

        analyzer._analyze_clutch(analytics, sorted_matches)
        analyzer._analyze_recent_6(analytics, sorted_matches)

        assert analytics.clutch_matches == 1
        assert analytics.clutch_grade == "데이터 부족"  # < 3 matches
        assert len(analytics.recent_6_matches) == 1

    def test_all_wins(self):
        """Test analysis with 100% win rate."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        matches = [
            MatchResult("Comp", "Event", "Pool 1", "Opp1", "TeamB", 5, 3, True, True),
            MatchResult("Comp", "Event", "Pool 2", "Opp2", "TeamC", 5, 2, True, True),
            MatchResult("Comp", "Event", "Pool 3", "Opp3", "TeamD", 5, 4, True, True),
        ]

        analyzer._analyze_margin(analytics, matches)

        assert analytics.avg_win_margin > 0
        assert analytics.avg_loss_margin == 0.0  # No losses

    def test_all_losses(self):
        """Test analysis with 0% win rate."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        matches = [
            MatchResult("Comp", "Event", "Pool 1", "Opp1", "TeamB", 2, 5, False, True),
            MatchResult("Comp", "Event", "Pool 2", "Opp2", "TeamC", 1, 5, False, True),
            MatchResult("Comp", "Event", "Pool 3", "Opp3", "TeamD", 3, 5, False, True),
        ]

        analyzer._analyze_margin(analytics, matches)

        assert analytics.avg_win_margin == 0.0  # No wins
        assert analytics.avg_loss_margin > 0

    def test_missing_score_data(self):
        """Test handling of matches with missing or invalid scores."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})
        analytics = PlayerAnalytics(player_name="Test", team="TeamA")

        # Edge case: 0-0 score (should not occur in real data)
        matches = [
            MatchResult("Comp", "Event", "Pool 1", "Opp1", "TeamB", 0, 0, False, True),
        ]

        analyzer._analyze_finish_type(analytics, matches)

        # 0-0 is technically a timeout (< 5 points)
        assert analytics.timeout_matches == 1


class TestUtilityFunctions:
    """Test utility functions (player key, i18n, etc.)."""

    def test_make_player_key(self):
        """Test player key generation."""
        key = make_player_key("박소윤", "최병철펜싱클럽")
        assert key == "박소윤|최병철펜싱클럽"

    def test_parse_player_key(self):
        """Test player key parsing."""
        name, team = parse_player_key("박소윤|최병철펜싱클럽")
        assert name == "박소윤"
        assert team == "최병철펜싱클럽"

    def test_parse_player_key_no_team(self):
        """Test player key parsing without team."""
        name, team = parse_player_key("박소윤")
        assert name == "박소윤"
        assert team == ""

    def test_get_analytics_text_korean(self):
        """Test Korean analytics text retrieval."""
        text = get_analytics_text("grade_strong", lang="ko")
        assert text == "강심장"

    def test_get_analytics_text_english(self):
        """Test English analytics text retrieval."""
        text = get_analytics_text("grade_strong", lang="en")
        assert text == "Clutch"

    def test_get_analytics_text_with_format(self):
        """Test analytics text with format parameters."""
        text = get_analytics_text("clutch_strong", lang="ko", wins=3, losses=1)
        assert "3승 1패" in text

    def test_get_analytics_text_fallback(self):
        """Test fallback to Korean for unknown language."""
        text = get_analytics_text("grade_strong", lang="unknown")
        assert text == "강심장"  # Should fallback to Korean


class TestMonthlyHistory:
    """Test monthly match history building."""

    def test_build_match_history(self):
        """Test monthly match history aggregation."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})

        matches = [
            MatchResult("Comp", "Event", "Pool 1", "Opp1", "TeamB", 5, 3, True, True, date="2025-01-15"),
            MatchResult("Comp", "Event", "Pool 2", "Opp2", "TeamC", 5, 2, True, True, date="2025-01-20"),
            MatchResult("Comp", "Event", "Pool 3", "Opp3", "TeamD", 3, 5, False, True, date="2025-01-25"),
            MatchResult("Comp", "Event", "Pool 4", "Opp4", "TeamE", 5, 4, True, True, date="2025-02-10"),
        ]

        history = analyzer._build_match_history(matches)

        assert len(history) == 2  # January and February
        assert history[0]["month"] == "2025-01"
        assert history[0]["wins"] == 2
        assert history[0]["losses"] == 1
        assert history[0]["total"] == 3
        assert history[0]["win_rate"] == 66.7

        assert history[1]["month"] == "2025-02"
        assert history[1]["wins"] == 1
        assert history[1]["losses"] == 0
        assert history[1]["total"] == 1
        assert history[1]["win_rate"] == 100.0

    def test_build_match_history_unknown_dates(self):
        """Test handling of matches with missing dates."""
        analyzer = FencingLabAnalyzer(data={"competitions": []})

        matches = [
            MatchResult("Comp", "Event", "Pool 1", "Opp1", "TeamB", 5, 3, True, True, date=""),
            MatchResult("Comp", "Event", "Pool 2", "Opp2", "TeamC", 5, 2, True, True, date="2025-01-15"),
        ]

        history = analyzer._build_match_history(matches)

        # Unknown dates should be filtered out
        assert len(history) == 1
        assert history[0]["month"] == "2025-01"


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
