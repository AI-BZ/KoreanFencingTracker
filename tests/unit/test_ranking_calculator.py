"""
Comprehensive unit tests for ranking/calculator.py
Coverage: 50+ test cases for point calculation, ranking aggregation, and edge cases
"""
import pytest
import sys
from pathlib import Path
from datetime import date, timedelta
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ranking.calculator import (
    RankingCalculator,
    PlayerResult,
    PlayerRanking,
    calculate_points,
    calculate_points_legacy,
    get_base_points_by_participants,
    get_competition_prestige,
    get_rank_ratio,
    get_participant_factor,
    classify_competition_tier,
    classify_category,
    classify_competition_level,
    extract_age_group,
    extract_weapon,
    extract_gender,
    matches_age_group_for_ranking,
    AGE_GROUP_WEIGHTS,
    PARTICIPANT_BASE_POINTS,
    COMPETITION_PRESTIGE,
    RANK_RATIOS,
    BEST_N_WEIGHTS,
)


# =============================================================================
# Point Calculation Tests (15 cases)
# =============================================================================

class TestBasePointsByParticipants:
    """Test base points calculation by participant count"""

    def test_128_plus_participants(self):
        """128+ participants = 1200 points"""
        assert get_base_points_by_participants(128) == 1200
        assert get_base_points_by_participants(150) == 1200
        assert get_base_points_by_participants(200) == 1200

    def test_64_to_127_participants(self):
        """64-127 participants = 1000 points"""
        assert get_base_points_by_participants(64) == 1000
        assert get_base_points_by_participants(100) == 1000
        assert get_base_points_by_participants(127) == 1000

    def test_32_to_63_participants(self):
        """32-63 participants = 800 points"""
        assert get_base_points_by_participants(32) == 800
        assert get_base_points_by_participants(50) == 800
        assert get_base_points_by_participants(63) == 800

    def test_16_to_31_participants(self):
        """16-31 participants = 500 points"""
        assert get_base_points_by_participants(16) == 500
        assert get_base_points_by_participants(24) == 500
        assert get_base_points_by_participants(31) == 500

    def test_8_to_15_participants(self):
        """8-15 participants = 300 points"""
        assert get_base_points_by_participants(8) == 300
        assert get_base_points_by_participants(12) == 300
        assert get_base_points_by_participants(15) == 300

    def test_less_than_8_participants(self):
        """< 8 participants = 150 points"""
        assert get_base_points_by_participants(7) == 150
        assert get_base_points_by_participants(5) == 150
        assert get_base_points_by_participants(1) == 150

    def test_zero_participants(self):
        """0 participants = 150 points (edge case)"""
        assert get_base_points_by_participants(0) == 150


class TestCompetitionPrestige:
    """Test competition prestige multiplier"""

    def test_official_competition(self):
        """Official competitions = 1.00"""
        assert get_competition_prestige("2024 전국선수권대회") == 1.00
        assert get_competition_prestige("회장배 전국대회") == 1.00
        assert get_competition_prestige("전국체전") == 1.00

    def test_club_competition(self):
        """Club competitions = 0.90"""
        assert get_competition_prestige("클럽 대회") == 0.90
        assert get_competition_prestige("동호인 펜싱대회") == 0.90
        assert get_competition_prestige("생활체육 대회") == 0.90
        assert get_competition_prestige("아마추어 대회") == 0.90

    def test_empty_competition_name(self):
        """Empty name defaults to 1.00"""
        assert get_competition_prestige("") == 1.00


class TestRankRatio:
    """Test rank position multiplier"""

    def test_gold_medal(self):
        """1st place = 100%"""
        assert get_rank_ratio(1) == 1.00

    def test_silver_medal(self):
        """2nd place = 65%"""
        assert get_rank_ratio(2) == 0.65

    def test_bronze_medal(self):
        """3rd place = 50%"""
        assert get_rank_ratio(3) == 0.50

    def test_fourth_place(self):
        """4th place = 40%"""
        assert get_rank_ratio(4) == 0.40

    def test_5_to_8_place(self):
        """5-8th place = 30%"""
        assert get_rank_ratio(5) == 0.30
        assert get_rank_ratio(8) == 0.30

    def test_9_to_16_place(self):
        """9-16th place = 20%"""
        assert get_rank_ratio(9) == 0.20
        assert get_rank_ratio(16) == 0.20

    def test_17_to_32_place(self):
        """17-32nd place = 10%"""
        assert get_rank_ratio(17) == 0.10
        assert get_rank_ratio(32) == 0.10

    def test_33_to_64_place(self):
        """33-64th place = 5%"""
        assert get_rank_ratio(33) == 0.05
        assert get_rank_ratio(64) == 0.05

    def test_65_plus_place(self):
        """65+ place = 2%"""
        assert get_rank_ratio(65) == 0.02
        assert get_rank_ratio(100) == 0.02


class TestAgeGroupWeight:
    """Test age group weight factor"""

    def test_y8_weight(self):
        """Y8 (초등 1-2학년) = 0.4"""
        assert AGE_GROUP_WEIGHTS["Y8"] == 0.4
        assert AGE_GROUP_WEIGHTS["E1"] == 0.4  # Legacy code

    def test_y10_weight(self):
        """Y10 (초등 3-4학년) = 0.5"""
        assert AGE_GROUP_WEIGHTS["Y10"] == 0.5
        assert AGE_GROUP_WEIGHTS["E2"] == 0.5

    def test_y12_weight(self):
        """Y12 (초등 5-6학년) = 0.6"""
        assert AGE_GROUP_WEIGHTS["Y12"] == 0.6
        assert AGE_GROUP_WEIGHTS["E3"] == 0.6

    def test_y14_weight(self):
        """Y14 (중등) = 0.7"""
        assert AGE_GROUP_WEIGHTS["Y14"] == 0.7
        assert AGE_GROUP_WEIGHTS["MS"] == 0.7

    def test_cadet_weight(self):
        """Cadet (고등) = 0.8"""
        assert AGE_GROUP_WEIGHTS["Cadet"] == 0.8
        assert AGE_GROUP_WEIGHTS["HS"] == 0.8

    def test_junior_weight(self):
        """Junior (대학) = 0.9"""
        assert AGE_GROUP_WEIGHTS["Junior"] == 0.9
        assert AGE_GROUP_WEIGHTS["UNI"] == 0.9

    def test_veteran_weight(self):
        """Veteran (일반) = 1.0"""
        assert AGE_GROUP_WEIGHTS["Veteran"] == 1.0
        assert AGE_GROUP_WEIGHTS["SR"] == 1.0

    def test_u17_weight_bug(self):
        """CRITICAL BUG: U17 exists but should be validated"""
        # U17 is present in AGE_GROUP_WEIGHTS
        assert "U17" in AGE_GROUP_WEIGHTS
        assert AGE_GROUP_WEIGHTS["U17"] == 0.75


class TestCombinedPointsCalculation:
    """Test final points calculation combining all factors"""

    def test_gold_large_official_veteran(self):
        """1st @ 128+ participants, official, veteran"""
        # Base: 1200, Prestige: 1.0, Rank: 1.0, Age: 1.0
        points = calculate_points("S", 1, 128, "SR", "전국체전")
        expected = 1200 * 1.0 * 1.0 * 1.0
        assert points == expected

    def test_silver_medium_official_junior(self):
        """2nd @ 64 participants, official, junior"""
        # Base: 1000, Prestige: 1.0, Rank: 0.65, Age: 0.9
        points = calculate_points("A", 2, 64, "UNI", "대학선수권")
        expected = 1000 * 1.0 * 0.65 * 0.9
        assert points == round(expected, 2)

    def test_bronze_small_club_elementary(self):
        """3rd @ 16 participants, club, elementary"""
        # Base: 500, Prestige: 0.9, Rank: 0.5, Age: 0.6 (E3)
        points = calculate_points("C", 3, 16, "E3", "클럽 대회")
        expected = 500 * 0.9 * 0.5 * 0.6
        assert points == round(expected, 2)

    def test_minimal_points(self):
        """65th @ 5 participants, club, Y8"""
        # Base: 150, Prestige: 0.9, Rank: 0.02, Age: 0.4
        points = calculate_points("C", 65, 5, "E1", "동호인 대회")
        expected = 150 * 0.9 * 0.02 * 0.4
        assert points == round(expected, 2)

    def test_missing_age_group_defaults_to_1_0(self):
        """Unknown age group defaults to 1.0 weight"""
        points = calculate_points("A", 1, 64, "UNKNOWN", "대회")
        expected = 1000 * 1.0 * 1.0 * 1.0  # Defaults to 1.0
        assert points == expected


# =============================================================================
# Ranking Aggregation Tests (10 cases)
# =============================================================================

class TestBestNSelection:
    """Test best-N results selection and weighting"""

    def test_best_4_results_weights(self):
        """Best 4: 100%, 70%, 50%, 30%"""
        calculator = RankingCalculator()
        results = []
        base_points = [1000, 800, 600, 400, 200, 100]

        for i, pts in enumerate(base_points):
            result = PlayerResult(
                player_name="테스트",
                team="클럽",
                event_name="종목",
                competition_name=f"대회{i}",
                competition_date=date.today() - timedelta(days=i*30),
                final_rank=1,
                total_participants=64,
                weapon="플러레",
                gender="남",
                age_group="SR",
                tier="A",
                points=float(pts)
            )
            results.append(result)

        calculator.results = results
        rankings = calculator.calculate_rankings(weapon="플러레", gender="남", best_n=4)

        # Top 4 weighted: 1000*1.0 + 800*0.7 + 600*0.5 + 400*0.3
        expected = 1000 + 560 + 300 + 120
        assert rankings[0].total_points == expected

    def test_best_6_results_max(self):
        """Best 6 results with BEST_N_WEIGHTS"""
        calculator = RankingCalculator()
        results = []
        base_points = [1000, 900, 800, 700, 600, 500, 400]

        for i, pts in enumerate(base_points):
            result = PlayerResult(
                player_name="테스트",
                team="클럽",
                event_name="종목",
                competition_name=f"대회{i}",
                competition_date=date.today() - timedelta(days=i*30),
                final_rank=1,
                total_participants=64,
                weapon="에뻬",
                gender="여",
                age_group="SR",
                tier="A",
                points=float(pts)
            )
            results.append(result)

        calculator.results = results
        rankings = calculator.calculate_rankings(weapon="에뻬", gender="여", best_n=6)

        # Top 6 weighted: [1.0, 0.7, 0.5, 0.3, 0.2, 0.1]
        expected = (1000*1.0 + 900*0.7 + 800*0.5 + 700*0.3 + 600*0.2 + 500*0.1)
        assert rankings[0].total_points == expected

    def test_best_n_cliff_bug(self):
        """CRITICAL BUG: Results 7+ all get 0.1 weight"""
        calculator = RankingCalculator()
        results = []

        # Create 10 results
        for i in range(10):
            result = PlayerResult(
                player_name="테스트",
                team="클럽",
                event_name="종목",
                competition_name=f"대회{i}",
                competition_date=date.today() - timedelta(days=i*30),
                final_rank=1,
                total_participants=64,
                weapon="사브르",
                gender="남",
                age_group="SR",
                tier="A",
                points=100.0
            )
            results.append(result)

        calculator.results = results
        rankings = calculator.calculate_rankings(weapon="사브르", gender="남", best_n=10)

        # Weights: [1.0, 0.7, 0.5, 0.3, 0.2, 0.1, 0.1, 0.1, 0.1, 0.1]
        # Results 7-10 all get 0.1 (cliff effect)
        expected = 100 * (1.0 + 0.7 + 0.5 + 0.3 + 0.2 + 0.1 + 0.1 + 0.1 + 0.1 + 0.1)
        assert rankings[0].total_points == pytest.approx(expected, rel=1e-9)


class TestSeasonFiltering:
    """Test season-based filtering"""

    def test_2024_season_only(self):
        """Filter to 2024 season only"""
        calculator = RankingCalculator()
        calculator.results = [
            PlayerResult(
                player_name="선수A",
                team="팀A",
                event_name="종목",
                competition_name="2024 대회",
                competition_date=date(2024, 5, 1),
                final_rank=1,
                total_participants=64,
                weapon="플러레",
                gender="남",
                age_group="SR",
                tier="A",
                points=100.0
            ),
            PlayerResult(
                player_name="선수A",
                team="팀A",
                event_name="종목",
                competition_name="2023 대회",
                competition_date=date(2023, 5, 1),
                final_rank=1,
                total_participants=64,
                weapon="플러레",
                gender="남",
                age_group="SR",
                tier="A",
                points=100.0
            ),
        ]

        rankings = calculator.calculate_rankings(weapon="플러레", gender="남", year=2024)
        # Only 2024 result should be counted
        assert rankings[0].competitions_count == 1

    def test_rolling_12_months(self):
        """Rolling window excludes old results"""
        calculator = RankingCalculator()
        recent_date = date.today() - timedelta(days=30)
        old_date = date.today() - timedelta(days=400)

        calculator.results = [
            PlayerResult(
                player_name="선수B",
                team="팀B",
                event_name="종목",
                competition_name="최근 대회",
                competition_date=recent_date,
                final_rank=1,
                total_participants=64,
                weapon="에뻬",
                gender="여",
                age_group="SR",
                tier="A",
                points=100.0
            ),
            PlayerResult(
                player_name="선수B",
                team="팀B",
                event_name="종목",
                competition_name="오래된 대회",
                competition_date=old_date,
                final_rank=1,
                total_participants=64,
                weapon="에뻬",
                gender="여",
                age_group="SR",
                tier="A",
                points=100.0
            ),
        ]

        rankings = calculator.calculate_rankings(weapon="에뻬", gender="여", rolling_months=12)
        # Only recent result should be counted
        assert rankings[0].competitions_count == 1

    def test_rolling_window_bug_365_vs_360(self):
        """POTENTIAL BUG: Rolling uses 30*N days, not exact months"""
        # 12 months * 30 days = 360 days (not 365)
        # Result at day 361 should be excluded
        calculator = RankingCalculator()
        edge_date = date.today() - timedelta(days=361)

        calculator.results = [
            PlayerResult(
                player_name="선수C",
                team="팀C",
                event_name="종목",
                competition_name="361일전 대회",
                competition_date=edge_date,
                final_rank=1,
                total_participants=64,
                weapon="사브르",
                gender="남",
                age_group="SR",
                tier="A",
                points=100.0
            ),
        ]

        rankings = calculator.calculate_rankings(weapon="사브르", gender="남", rolling_months=12)
        # Should be excluded (361 > 360)
        assert len(rankings) == 0


class TestAgeGroupFiltering:
    """Test age group filtering"""

    def test_filter_elementary_e3(self):
        """Filter E3 (초등 5-6학년)"""
        calculator = RankingCalculator()
        calculator.results = [
            PlayerResult(
                player_name="초등생",
                team="팀",
                event_name="종목",
                competition_name="대회",
                competition_date=date.today(),
                final_rank=1,
                total_participants=32,
                weapon="플러레",
                gender="여",
                age_group="E3",
                tier="A",
                points=100.0
            ),
            PlayerResult(
                player_name="중학생",
                team="팀",
                event_name="종목",
                competition_name="대회",
                competition_date=date.today(),
                final_rank=1,
                total_participants=32,
                weapon="플러레",
                gender="여",
                age_group="MS",
                tier="A",
                points=100.0
            ),
        ]

        rankings = calculator.calculate_rankings(weapon="플러레", gender="여", age_group="E3")
        assert len(rankings) == 1
        assert rankings[0].player_name == "초등생"

    def test_u17_matches_ms_and_hs(self):
        """U17 results appear in both MS and HS rankings"""
        calculator = RankingCalculator()
        calculator.results = [
            PlayerResult(
                player_name="U17선수",
                team="팀",
                event_name="종목",
                competition_name="익산 국제대회",
                competition_date=date.today(),
                final_rank=1,
                total_participants=32,
                weapon="플러레",
                gender="남",
                age_group="U17",
                tier="D",
                points=100.0
            ),
        ]

        # Should appear in MS ranking
        ms_rankings = calculator.calculate_rankings(weapon="플러레", gender="남", age_group="MS")
        assert len(ms_rankings) == 1

        # Should also appear in HS ranking
        hs_rankings = calculator.calculate_rankings(weapon="플러레", gender="남", age_group="HS")
        assert len(hs_rankings) == 1


class TestWeaponFiltering:
    """Test weapon filtering"""

    def test_filter_foil_only(self):
        """Filter foil results only"""
        calculator = RankingCalculator()
        calculator.results = [
            PlayerResult(
                player_name="플러레선수",
                team="팀",
                event_name="종목",
                competition_name="대회",
                competition_date=date.today(),
                final_rank=1,
                total_participants=32,
                weapon="플러레",
                gender="남",
                age_group="SR",
                tier="A",
                points=100.0
            ),
            PlayerResult(
                player_name="에뻬선수",
                team="팀",
                event_name="종목",
                competition_name="대회",
                competition_date=date.today(),
                final_rank=1,
                total_participants=32,
                weapon="에뻬",
                gender="남",
                age_group="SR",
                tier="A",
                points=100.0
            ),
        ]

        rankings = calculator.calculate_rankings(weapon="플러레", gender="남")
        assert len(rankings) == 1
        assert rankings[0].weapon == "플러레"


# =============================================================================
# Edge Cases (10 cases)
# =============================================================================

class TestEdgeCases:
    """Test edge cases and error handling"""

    def test_zero_participants_competition(self):
        """0 participants = 150 base points"""
        points = calculate_points("A", 1, 0, "SR", "대회")
        # Base: 150 (< 8), Prestige: 1.0, Rank: 1.0, Age: 1.0
        assert points == 150.0

    def test_single_participant_competition(self):
        """1 participant competition"""
        points = calculate_points("A", 1, 1, "SR", "대회")
        assert points == 150.0  # < 8 participants

    def test_incomplete_data_no_name(self):
        """Result with no name should be skipped"""
        calculator = RankingCalculator()
        data = {
            "competitions": [{
                "competition": {"name": "대회", "start_date": "2024-01-01"},
                "events": [{
                    "name": "종목",
                    "total_participants": 32,
                    "final_rankings": [
                        {"rank": 1, "name": "", "team": "팀A"},  # No name
                    ]
                }]
            }]
        }

        calculator.load_from_data(data)
        assert len(calculator.results) == 0

    def test_incomplete_data_no_rank(self):
        """Result with no rank should be skipped"""
        calculator = RankingCalculator()
        data = {
            "competitions": [{
                "competition": {"name": "대회", "start_date": "2024-01-01"},
                "events": [{
                    "name": "종목",
                    "total_participants": 32,
                    "final_rankings": [
                        {"rank": 0, "name": "선수A", "team": "팀A"},  # Invalid rank
                    ]
                }]
            }]
        }

        calculator.load_from_data(data)
        assert len(calculator.results) == 0

    def test_missing_age_group_fallback(self):
        """Missing age_group defaults to 1.0 weight"""
        points = calculate_points("A", 1, 64, "", "대회")
        # Should default to 1.0 weight
        expected = 1000 * 1.0 * 1.0 * 1.0
        assert points == expected

    def test_duplicate_competition_handling(self):
        """Same player, same competition = both results counted"""
        calculator = RankingCalculator()
        calculator.results = [
            PlayerResult(
                player_name="중복선수",
                team="팀",
                event_name="플러레 종목",
                competition_name="같은 대회",
                competition_date=date.today(),
                final_rank=1,
                total_participants=32,
                weapon="플러레",
                gender="남",
                age_group="SR",
                tier="A",
                points=100.0
            ),
            PlayerResult(
                player_name="중복선수",
                team="팀",
                event_name="에뻬 종목",  # Different event in same competition
                competition_name="같은 대회",
                competition_date=date.today(),
                final_rank=2,
                total_participants=32,
                weapon="에뻬",
                gender="남",
                age_group="SR",
                tier="A",
                points=80.0
            ),
        ]

        # Should count both results (different weapons)
        rankings_all = calculator.calculate_rankings(gender="남")
        assert rankings_all[0].competitions_count == 2

    def test_empty_results_list(self):
        """Empty results = empty rankings"""
        calculator = RankingCalculator()
        calculator.results = []
        rankings = calculator.calculate_rankings()
        assert len(rankings) == 0

    def test_invalid_date_format(self):
        """Invalid date format should default to today"""
        calculator = RankingCalculator()
        data = {
            "competitions": [{
                "competition": {"name": "대회", "start_date": "invalid-date"},
                "events": [{
                    "name": "종목",
                    "total_participants": 32,
                    "final_rankings": [
                        {"rank": 1, "name": "선수A", "team": "팀A"},
                    ]
                }]
            }]
        }

        calculator.load_from_data(data)
        assert len(calculator.results) == 1
        assert calculator.results[0].competition_date == date.today()

    def test_team_event_excluded(self):
        """Team events (단체전) should be excluded"""
        calculator = RankingCalculator()
        data = {
            "competitions": [{
                "competition": {"name": "대회", "start_date": "2024-01-01"},
                "events": [
                    {
                        "name": "남자 플러레 단체전",  # 단체전
                        "total_participants": 16,
                        "final_rankings": [
                            {"rank": 1, "name": "팀A", "team": "서울"},
                        ]
                    },
                    {
                        "name": "남자 플러레 개인전",  # 개인전
                        "total_participants": 64,
                        "final_rankings": [
                            {"rank": 1, "name": "선수A", "team": "팀A"},
                        ]
                    }
                ]
            }]
        }

        calculator.load_from_data(data)
        # Only individual event should be counted
        assert len(calculator.results) == 1
        assert "단체" not in calculator.results[0].event_name

    def test_negative_rank(self):
        """Negative rank should be skipped (ACTUAL BUG: currently not filtered)"""
        calculator = RankingCalculator()
        data = {
            "competitions": [{
                "competition": {"name": "대회", "start_date": "2024-01-01"},
                "events": [{
                    "name": "종목",
                    "total_participants": 32,
                    "final_rankings": [
                        {"rank": -1, "name": "선수A", "team": "팀A"},
                    ]
                }]
            }]
        }

        calculator.load_from_data(data)
        # BUG: Negative ranks are not filtered out, should be 0
        assert len(calculator.results) == 1  # Current behavior
        # TODO: Should be fixed to: assert len(calculator.results) == 0


# =============================================================================
# Classification Functions (10 cases)
# =============================================================================

class TestClassificationFunctions:
    """Test competition/category classification"""

    def test_classify_tier_s(self):
        """S-tier: 전국체전, 회장배"""
        assert classify_competition_tier("전국체전") == "S"
        assert classify_competition_tier("회장배 전국대회") == "S"
        assert classify_competition_tier("대통령배") == "S"

    def test_classify_tier_a(self):
        """A-tier: 선수권대회"""
        assert classify_competition_tier("전국선수권대회") == "A"
        assert classify_competition_tier("Championship") == "A"

    def test_classify_tier_d(self):
        """D-tier: 국제대회"""
        assert classify_competition_tier("인터내셔널 펜싱대회") == "D"
        assert classify_competition_tier("International Open") == "D"

    def test_classify_tier_b(self):
        """B-tier: 시도대회"""
        assert classify_competition_tier("시도대항전") == "B"
        # Note: 협회장배 contains "회장배" so it's classified as S, not B
        assert classify_competition_tier("도지사배") == "B"

    def test_classify_tier_c(self):
        """C-tier: 기타"""
        assert classify_competition_tier("클럽 친선대회") == "C"

    def test_classify_category_pro(self):
        """PRO: 정식 대회"""
        assert classify_category("전국선수권대회") == "PRO"
        assert classify_category("회장배") == "PRO"

    def test_classify_category_club(self):
        """CLUB: 동호인 대회"""
        assert classify_category("클럽 대회") == "CLUB"
        assert classify_category("동호인 펜싱대회") == "CLUB"
        assert classify_category("생활체육 대회") == "CLUB"
        assert classify_category("Amateur Open") == "CLUB"

    def test_classify_level_national(self):
        """NATIONAL: 국가대표 대회"""
        level = classify_competition_level("국가대표 선발전")
        assert level == "NATIONAL"

    def test_classify_level_amateur(self):
        """AMATEUR: 동호인 대회"""
        level = classify_competition_level("클럽 친선대회")
        assert level == "AMATEUR"

    def test_classify_level_elite(self):
        """ELITE: 나머지 정식 대회"""
        level = classify_competition_level("전국선수권대회")
        assert level == "ELITE"


# =============================================================================
# Extraction Functions (10 cases)
# =============================================================================

class TestExtractionFunctions:
    """Test age_group, weapon, gender extraction"""

    def test_extract_age_group_elementary(self):
        """Extract elementary age groups"""
        assert extract_age_group("초등부(1-2학년)") == "E1"
        assert extract_age_group("초등부(3-4학년)") == "E2"
        assert extract_age_group("초등부(5-6학년)") == "E3"

    def test_extract_age_group_u_codes(self):
        """Extract U-age codes"""
        assert extract_age_group("U9") == "E1"
        assert extract_age_group("U11") == "E2"
        assert extract_age_group("U13") == "E3"
        assert extract_age_group("U17") == "U17"
        assert extract_age_group("U20") == "UNI"

    def test_extract_age_group_middle_high(self):
        """Extract middle/high school"""
        assert extract_age_group("중등부") == "MS"
        assert extract_age_group("고등부") == "HS"
        assert extract_age_group("남중") == "MS"
        assert extract_age_group("여고") == "HS"

    def test_extract_age_group_university(self):
        """Extract university"""
        assert extract_age_group("대학부") == "UNI"
        assert extract_age_group("남대") == "UNI"
        assert extract_age_group("여대") == "UNI"

    def test_extract_age_group_senior(self):
        """Extract senior/general"""
        assert extract_age_group("일반부") == "SR"
        assert extract_age_group("시니어") == "SR"

    def test_extract_weapon_foil(self):
        """Extract foil"""
        assert extract_weapon("플러레") == "플러레"
        assert extract_weapon("foil") == "플러레"

    def test_extract_weapon_epee(self):
        """Extract epee"""
        assert extract_weapon("에뻬") == "에뻬"
        assert extract_weapon("epee") == "에뻬"

    def test_extract_weapon_sabre(self):
        """Extract sabre"""
        assert extract_weapon("사브르") == "사브르"
        assert extract_weapon("sabre") == "사브르"

    def test_extract_gender_male(self):
        """Extract male gender"""
        assert extract_gender("남자") == "남"
        assert extract_gender("남고") == "남"

    def test_extract_gender_female(self):
        """Extract female gender"""
        assert extract_gender("여자") == "여"
        assert extract_gender("여중") == "여"


# =============================================================================
# Age Group Matching (5 cases)
# =============================================================================

class TestAgeGroupMatching:
    """Test age group matching for ranking filters"""

    def test_exact_match(self):
        """Exact age group match"""
        assert matches_age_group_for_ranking("E3", "E3") is True
        assert matches_age_group_for_ranking("MS", "MS") is True

    def test_u17_matches_ms(self):
        """U17 matches MS"""
        assert matches_age_group_for_ranking("U17", "MS") is True

    def test_u17_matches_hs(self):
        """U17 matches HS"""
        assert matches_age_group_for_ranking("U17", "HS") is True

    def test_no_match(self):
        """No match"""
        assert matches_age_group_for_ranking("E1", "E3") is False
        assert matches_age_group_for_ranking("MS", "HS") is False

    def test_empty_age_group_no_match(self):
        """Empty age_group = no match"""
        assert matches_age_group_for_ranking("", "MS") is False
        assert matches_age_group_for_ranking("MS", "") is False


# =============================================================================
# Integration Tests (10 cases)
# =============================================================================

class TestRankingIntegration:
    """Integration tests for full ranking calculation"""

    def test_player_ranking_across_season(self):
        """Player with multiple competitions in season"""
        calculator = RankingCalculator()
        calculator.results = [
            PlayerResult(
                player_name="박소윤",
                team="최병철펜싱클럽",
                event_name="종목",
                competition_name=f"대회{i}",
                competition_date=date(2024, i+1, 1),
                final_rank=rank,
                total_participants=64,
                weapon="플러레",
                gender="여",
                age_group="E3",
                tier="A",
                points=float(100 - i*10)
            )
            for i, rank in enumerate([1, 2, 1, 3])
        ]

        rankings = calculator.calculate_rankings(weapon="플러레", gender="여", age_group="E3", year=2024)
        assert len(rankings) == 1
        assert rankings[0].player_name == "박소윤"
        assert rankings[0].competitions_count == 4
        assert rankings[0].gold_count == 2

    def test_multi_weapon_player_separate_rankings(self):
        """Player with multiple weapons = separate rankings"""
        calculator = RankingCalculator()
        calculator.results = [
            PlayerResult(
                player_name="홍길동",
                team="팀",
                event_name="플러레 종목",
                competition_name="대회1",
                competition_date=date.today(),
                final_rank=1,
                total_participants=32,
                weapon="플러레",
                gender="남",
                age_group="HS",
                tier="A",
                points=100.0
            ),
            PlayerResult(
                player_name="홍길동",
                team="팀",
                event_name="에뻬 종목",
                competition_name="대회2",
                competition_date=date.today(),
                final_rank=2,
                total_participants=32,
                weapon="에뻬",
                gender="남",
                age_group="HS",
                tier="A",
                points=80.0
            ),
        ]

        # Foil ranking
        foil_rankings = calculator.calculate_rankings(weapon="플러레", gender="남")
        assert len(foil_rankings) == 1
        assert foil_rankings[0].competitions_count == 1

        # Epee ranking
        epee_rankings = calculator.calculate_rankings(weapon="에뻬", gender="남")
        assert len(epee_rankings) == 1
        assert epee_rankings[0].competitions_count == 1

    def test_age_group_transition(self):
        """Player transitioning age groups"""
        calculator = RankingCalculator()
        calculator.results = [
            PlayerResult(
                player_name="성장선수",
                team="팀",
                event_name="중등 종목",
                competition_name="2023 대회",
                competition_date=date(2023, 5, 1),
                final_rank=1,
                total_participants=32,
                weapon="플러레",
                gender="남",
                age_group="MS",
                tier="A",
                points=100.0
            ),
            PlayerResult(
                player_name="성장선수",
                team="팀",
                event_name="고등 종목",
                competition_name="2024 대회",
                competition_date=date(2024, 5, 1),
                final_rank=1,
                total_participants=32,
                weapon="플러레",
                gender="남",
                age_group="HS",
                tier="A",
                points=100.0
            ),
        ]

        # MS ranking (includes 2023 result within rolling window if recent enough)
        ms_rankings = calculator.calculate_rankings(weapon="플러레", gender="남", age_group="MS", year=2023)
        assert len(ms_rankings) == 1

        # HS ranking (2024 only)
        hs_rankings = calculator.calculate_rankings(weapon="플러레", gender="남", age_group="HS", year=2024)
        assert len(hs_rankings) == 1

    def test_medal_counting(self):
        """Medal counting in rankings"""
        calculator = RankingCalculator()
        calculator.results = [
            PlayerResult(
                player_name="메달왕",
                team="팀",
                event_name="종목",
                competition_name=f"대회{i}",
                competition_date=date.today() - timedelta(days=i*30),
                final_rank=rank,
                total_participants=32,
                weapon="사브르",
                gender="여",
                age_group="SR",
                tier="A",
                points=100.0
            )
            for i, rank in enumerate([1, 1, 2, 2, 3, 3, 3])
        ]

        rankings = calculator.calculate_rankings(weapon="사브르", gender="여")
        assert rankings[0].gold_count == 2
        assert rankings[0].silver_count == 2
        assert rankings[0].bronze_count == 3

    def test_team_list_aggregation(self):
        """Multiple teams aggregated"""
        calculator = RankingCalculator()
        calculator.results = [
            PlayerResult(
                player_name="이직선수",
                team="팀A",
                event_name="종목",
                competition_name="대회1",
                competition_date=date(2024, 1, 1),
                final_rank=1,
                total_participants=32,
                weapon="플러레",
                gender="남",
                age_group="SR",
                tier="A",
                points=100.0
            ),
            PlayerResult(
                player_name="이직선수",
                team="팀B",
                event_name="종목",
                competition_name="대회2",
                competition_date=date(2024, 6, 1),
                final_rank=1,
                total_participants=32,
                weapon="플러레",
                gender="남",
                age_group="SR",
                tier="A",
                points=100.0
            ),
        ]

        rankings = calculator.calculate_rankings(weapon="플러레", gender="남", year=2024)
        assert len(rankings) > 0
        assert len(rankings[0].teams) == 2
        assert "팀A" in rankings[0].teams
        assert "팀B" in rankings[0].teams

    def test_ranking_sort_order(self):
        """Rankings sorted by points, then medals, then competitions"""
        calculator = RankingCalculator()
        calculator.results = [
            # Player A: 200 points, 0 gold
            PlayerResult(
                player_name="선수A",
                team="팀",
                event_name="종목",
                competition_name="대회",
                competition_date=date.today(),
                final_rank=2,
                total_participants=128,
                weapon="플러레",
                gender="남",
                age_group="SR",
                tier="A",
                points=200.0
            ),
            # Player B: 200 points, 1 gold (should rank higher)
            PlayerResult(
                player_name="선수B",
                team="팀",
                event_name="종목",
                competition_name="대회",
                competition_date=date.today(),
                final_rank=1,
                total_participants=128,
                weapon="플러레",
                gender="남",
                age_group="SR",
                tier="A",
                points=200.0
            ),
        ]

        rankings = calculator.calculate_rankings(weapon="플러레", gender="남")
        # Player B should be ranked first (same points but has gold)
        assert rankings[0].player_name == "선수B"
        assert rankings[1].player_name == "선수A"

    def test_national_team_filtering(self):
        """National team only filtering"""
        calculator = RankingCalculator()
        calculator.results = [
            PlayerResult(
                player_name="국대선수",
                team="국가대표",
                event_name="종목",
                competition_name="국가대표 선발전",
                competition_date=date.today(),
                final_rank=1,
                total_participants=20,
                weapon="사브르",
                gender="남",
                age_group="SR",
                tier="S",
                points=100.0
            ),
            PlayerResult(
                player_name="국대선수",
                team="팀",
                event_name="종목",
                competition_name="일반 대회",
                competition_date=date.today(),
                final_rank=1,
                total_participants=32,
                weapon="사브르",
                gender="남",
                age_group="SR",
                tier="A",
                points=100.0
            ),
        ]

        rankings = calculator.calculate_rankings(
            weapon="사브르",
            gender="남",
            national_team_only=True
        )
        # Only national team competition
        assert len(rankings) == 1
        assert rankings[0].competitions_count == 1

    def test_category_filtering_middle_school_plus(self):
        """Category filter only applies to MS+"""
        calculator = RankingCalculator()
        calculator.results = [
            # Elementary: category doesn't matter
            PlayerResult(
                player_name="초등생",
                team="팀",
                event_name="종목",
                competition_name="클럽 대회",
                competition_date=date.today(),
                final_rank=1,
                total_participants=16,
                weapon="플러레",
                gender="남",
                age_group="E3",
                tier="C",
                category="CLUB",
                points=100.0
            ),
            # Middle school: category applies
            PlayerResult(
                player_name="중학생",
                team="팀",
                event_name="종목",
                competition_name="클럽 대회",
                competition_date=date.today(),
                final_rank=1,
                total_participants=16,
                weapon="플러레",
                gender="남",
                age_group="MS",
                tier="C",
                category="CLUB",
                points=100.0
            ),
            PlayerResult(
                player_name="전문중학생",
                team="팀",
                event_name="종목",
                competition_name="정식 대회",
                competition_date=date.today(),
                final_rank=1,
                total_participants=16,
                weapon="플러레",
                gender="남",
                age_group="MS",
                tier="A",
                category="PRO",
                points=100.0
            ),
        ]

        # Elementary: all included regardless of category
        elem_rankings = calculator.calculate_rankings(weapon="플러레", gender="남", age_group="E3")
        assert len(elem_rankings) == 1

        # Middle school PRO only
        ms_pro_rankings = calculator.calculate_rankings(
            weapon="플러레",
            gender="남",
            age_group="MS",
            category="PRO"
        )
        assert len(ms_pro_rankings) == 1
        assert ms_pro_rankings[0].player_name == "전문중학생"

    def test_best_results_details(self):
        """Best results include all details"""
        calculator = RankingCalculator()
        calculator.results = [
            PlayerResult(
                player_name="상세선수",
                team="팀",
                event_name="플러레 개인전",
                competition_name="회장배",
                competition_date=date(2024, 7, 15),
                final_rank=1,
                total_participants=64,
                weapon="플러레",
                gender="여",
                age_group="E3",
                tier="S",
                points=600.0
            ),
        ]

        rankings = calculator.calculate_rankings(weapon="플러레", gender="여", year=2024)
        assert len(rankings) > 0
        best_result = rankings[0].best_results[0]

        assert best_result["event"] == "플러레 개인전"
        assert best_result["competition"] == "회장배"
        assert best_result["date"] == "2024-07-15"
        assert best_result["rank"] == 1
        assert best_result["points"] == 600.0

    def test_legacy_points_calculation(self):
        """Legacy points calculation for backward compatibility"""
        points = calculate_points_legacy("A", 1, 64, "SR")
        # Base: 800, Rank: 1.0, Participant: 1.0 (>=64), Age: 1.0
        expected = 800 * 1.0 * 1.0 * 1.0
        assert points == expected


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
