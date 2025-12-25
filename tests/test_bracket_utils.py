"""
Unit tests for DE Bracket Data Normalization Utility v2
Tests: normalize_bracket_data, round ordering, match pairing, bout structure
"""

import pytest
from app.bracket_utils import (
    normalize_bracket_data,
    normalize_round_name,
    get_round_order,
    extract_score,
    get_bracket_size,
    get_starting_round,
    calculate_expected_matches,
    validate_bracket,
    BracketBout,
    NormalizedBracket,
    ROUND_ORDER,
    ROUND_DISPLAY_NAMES,
)


class TestRoundNameNormalization:
    """Test round name normalization"""

    def test_normalize_round_name_with_jeon_suffix(self):
        """'전' suffix should be removed"""
        assert normalize_round_name("32강전") == "32강"
        assert normalize_round_name("16강전") == "16강"
        assert normalize_round_name("8강전") == "8강"
        assert normalize_round_name("결승전") == "결승"

    def test_normalize_round_name_already_clean(self):
        """Already clean names should pass through"""
        assert normalize_round_name("32강") == "32강"
        assert normalize_round_name("준결승") == "준결승"
        assert normalize_round_name("결승") == "결승"

    def test_normalize_round_name_4gang_to_semifinal(self):
        """4강전 should normalize to 준결승"""
        assert normalize_round_name("4강전") == "준결승"
        assert normalize_round_name("4강") == "준결승"

    def test_normalize_round_name_3rd_place_match(self):
        """3rd place match variants should normalize"""
        assert normalize_round_name("3-4위전") == "3-4위"
        assert normalize_round_name("3위결정전") == "3-4위"

    def test_normalize_round_name_unknown(self):
        """Unknown names should pass through unchanged"""
        assert normalize_round_name("예선라운드") == "예선라운드"


class TestRoundOrdering:
    """Test round ordering for tournament progression"""

    def test_round_order_progression(self):
        """Rounds should be ordered from early to late"""
        assert get_round_order("128강") < get_round_order("64강")
        assert get_round_order("64강") < get_round_order("32강")
        assert get_round_order("32강") < get_round_order("16강")
        assert get_round_order("16강") < get_round_order("8강")
        assert get_round_order("8강") < get_round_order("준결승")
        assert get_round_order("준결승") < get_round_order("결승")

    def test_round_order_with_jeon_suffix(self):
        """Rounds with 전 suffix should have same order"""
        assert get_round_order("32강전") == get_round_order("32강")
        assert get_round_order("결승전") == get_round_order("결승")

    def test_unknown_round_order(self):
        """Unknown rounds should get high order number"""
        assert get_round_order("알수없는라운드") == 99


class TestScoreExtraction:
    """Test score extraction from various formats"""

    def test_extract_score_from_dict(self):
        """Extract scores from dictionary format"""
        score_dict = {"winner_score": 15, "loser_score": 12}
        winner, loser = extract_score(score_dict)
        assert winner == 15
        assert loser == 12

    def test_extract_score_from_string(self):
        """Extract scores from string format like '15-12'"""
        winner, loser = extract_score("15-12")
        assert winner == 15
        assert loser == 12

        winner, loser = extract_score("15:10")
        assert winner == 15
        assert loser == 10

    def test_extract_score_from_int(self):
        """Extract score from integer"""
        winner, loser = extract_score(15)
        assert winner == 15
        assert loser is None

    def test_extract_score_none(self):
        """None input should return None, None"""
        winner, loser = extract_score(None)
        assert winner is None
        assert loser is None

    def test_extract_score_invalid_string(self):
        """Invalid string should return None, None"""
        winner, loser = extract_score("invalid")
        assert winner is None
        assert loser is None


class TestBracketSize:
    """Test bracket size calculation"""

    def test_bracket_size_power_of_2(self):
        """Bracket size should be next power of 2"""
        assert get_bracket_size(3) == 4
        assert get_bracket_size(5) == 8
        assert get_bracket_size(10) == 16
        assert get_bracket_size(20) == 32
        assert get_bracket_size(50) == 64
        assert get_bracket_size(100) == 128

    def test_bracket_size_exact_power(self):
        """Exact power of 2 participants"""
        assert get_bracket_size(8) == 8
        assert get_bracket_size(16) == 16
        assert get_bracket_size(32) == 32

    def test_bracket_size_max(self):
        """Very large participant counts should cap at 128"""
        assert get_bracket_size(200) == 128


class TestStartingRound:
    """Test starting round determination"""

    def test_starting_round_by_bracket_size(self):
        """Starting round should match bracket size"""
        assert get_starting_round(8) == "8강"
        assert get_starting_round(16) == "16강"
        assert get_starting_round(32) == "32강"
        assert get_starting_round(64) == "64강"
        assert get_starting_round(128) == "128강"


class TestExpectedMatches:
    """Test expected match calculation per round"""

    def test_expected_matches_16_bracket(self):
        """16-player bracket should have correct match counts"""
        expected = calculate_expected_matches(16)
        assert expected.get("16강") == 8
        assert expected.get("8강") == 4
        assert expected.get("준결승") == 2
        assert expected.get("결승") == 1
        assert "32강" not in expected

    def test_expected_matches_32_bracket(self):
        """32-player bracket should have correct match counts"""
        expected = calculate_expected_matches(32)
        assert expected.get("32강") == 16
        assert expected.get("16강") == 8
        assert expected.get("8강") == 4

    def test_expected_matches_64_bracket(self):
        """64-player bracket should have correct match counts"""
        expected = calculate_expected_matches(64)
        assert expected.get("64강") == 32
        assert expected.get("32강") == 16


class TestNormalizeBracketDataNewFormat:
    """Test bracket normalization with new bouts format"""

    def test_normalize_empty_data(self):
        """Empty data should return empty bracket"""
        result = normalize_bracket_data({})
        assert isinstance(result, NormalizedBracket)
        assert result.rounds == []
        assert result.bouts == []
        assert result.seeding == []
        assert result.participant_count == 0

    def test_normalize_with_new_bouts_format(self):
        """New bouts format should be processed correctly"""
        data = {
            "bracket_size": 8,
            "seeding": [
                {"seed": 1, "name": "김철수", "team": "서울"},
                {"seed": 2, "name": "이영희", "team": "부산"},
                {"seed": 3, "name": "박민수", "team": "대전"},
                {"seed": 4, "name": "최지영", "team": "인천"},
            ],
            "bouts": [
                {
                    "bout_id": "8강_01",
                    "round": "8강",
                    "round_order": 5,
                    "matchNumber": 1,
                    "player1": {"seed": 1, "name": "김철수", "team": "서울", "score": 15},
                    "player2": {"seed": 4, "name": "최지영", "team": "인천", "score": 10},
                    "winnerSeed": 1,
                    "winnerName": "김철수",
                    "isCompleted": True,
                    "isBye": False
                },
                {
                    "bout_id": "8강_02",
                    "round": "8강",
                    "round_order": 5,
                    "matchNumber": 2,
                    "player1": {"seed": 2, "name": "이영희", "team": "부산", "score": 15},
                    "player2": {"seed": 3, "name": "박민수", "team": "대전", "score": 12},
                    "winnerSeed": 2,
                    "winnerName": "이영희",
                    "isCompleted": True,
                    "isBye": False
                },
            ]
        }

        result = normalize_bracket_data(data)

        assert len(result.seeding) == 4
        assert len(result.bouts) == 2
        assert "8강" in result.bouts_by_round
        assert len(result.bouts_by_round["8강"]) == 2

        # Check bout structure
        bout = result.bouts[0]
        assert bout.player1_seed == 1
        assert bout.player1_name == "김철수"
        assert bout.player2_seed == 4
        assert bout.player2_name == "최지영"
        assert bout.winner_seed == 1
        assert bout.is_completed == True


class TestNormalizeBracketDataLegacyFormat:
    """Test bracket normalization with legacy results_by_round format"""

    def test_normalize_with_legacy_format(self, sample_de_bracket_data):
        """Legacy results_by_round should be converted to bouts"""
        result = normalize_bracket_data(sample_de_bracket_data)

        assert len(result.seeding) == 8
        assert len(result.bouts) > 0
        assert len(result.rounds) > 0

    def test_normalize_rounds_order(self, sample_de_bracket_data):
        """Rounds should be ordered from early to late"""
        result = normalize_bracket_data(sample_de_bracket_data)

        assert len(result.rounds) > 0
        for i in range(len(result.rounds) - 1):
            current = get_round_order(result.rounds[i])
            next_round = get_round_order(result.rounds[i + 1])
            assert current <= next_round


class TestBracketBoutDataclass:
    """Test BracketBout dataclass"""

    def test_bout_to_dict(self):
        """BracketBout.to_dict should return all fields"""
        bout = BracketBout(
            bout_id="8강_01",
            round="8강",
            round_order=5,
            match_number=1,
            player1_seed=1,
            player1_name="김철수",
            player1_team="서울",
            player1_score=15,
            player2_seed=8,
            player2_name="이영희",
            player2_team="부산",
            player2_score=12,
            winner_seed=1,
            winner_name="김철수",
            is_completed=True,
            is_bye=False
        )

        result = bout.to_dict()
        assert result["bout_id"] == "8강_01"
        assert result["player1_name"] == "김철수"
        assert result["player2_name"] == "이영희"
        assert result["winner_name"] == "김철수"
        assert result["player1_score"] == 15
        assert result["player2_score"] == 12


class TestBracketValidation:
    """Test bracket validation"""

    def test_validate_complete_bracket(self):
        """Complete bracket should pass validation"""
        data = {
            "bracket_size": 4,
            "seeding": [
                {"seed": 1, "name": "A", "team": "X"},
                {"seed": 2, "name": "B", "team": "Y"},
                {"seed": 3, "name": "C", "team": "Z"},
                {"seed": 4, "name": "D", "team": "W"},
            ],
            "bouts": [
                {"bout_id": "SF_01", "round": "준결승", "round_order": 6, "matchNumber": 1,
                 "player1": {"seed": 1, "name": "A", "score": 15},
                 "player2": {"seed": 4, "name": "D", "score": 10},
                 "winnerSeed": 1, "winnerName": "A", "isCompleted": True, "isBye": False},
                {"bout_id": "SF_02", "round": "준결승", "round_order": 6, "matchNumber": 2,
                 "player1": {"seed": 2, "name": "B", "score": 15},
                 "player2": {"seed": 3, "name": "C", "score": 12},
                 "winnerSeed": 2, "winnerName": "B", "isCompleted": True, "isBye": False},
                {"bout_id": "F_01", "round": "결승", "round_order": 7, "matchNumber": 1,
                 "player1": {"seed": 1, "name": "A", "score": 15},
                 "player2": {"seed": 2, "name": "B", "score": 13},
                 "winnerSeed": 1, "winnerName": "A", "isCompleted": True, "isBye": False},
            ]
        }

        result = normalize_bracket_data(data)
        validation = validate_bracket(result)

        assert validation['total_bouts'] == 3
        assert validation['incomplete_bouts'] == 0
        assert "준결승" in validation['rounds_found']
        assert "결승" in validation['rounds_found']


class TestRealDataScenarios:
    """Test with realistic data scenarios from fencing tournaments"""

    def test_large_bracket_64_players(self):
        """Test with 64-player tournament data"""
        seeding = [
            {"seed": i, "name": f"선수{i}", "team": f"팀{i % 10}"}
            for i in range(1, 65)
        ]

        bouts = []
        bout_id = 1

        # 64강 경기 (32개)
        for i in range(1, 33):
            bouts.append({
                "bout_id": f"64강_{bout_id:02d}",
                "round": "64강",
                "round_order": 2,
                "matchNumber": i,
                "player1": {"seed": i, "name": f"선수{i}", "score": 15},
                "player2": {"seed": 65 - i, "name": f"선수{65 - i}", "score": 10},
                "winnerSeed": i,
                "winnerName": f"선수{i}",
                "isCompleted": True,
                "isBye": False
            })
            bout_id += 1

        data = {
            "seeding": seeding,
            "bouts": bouts
        }

        result = normalize_bracket_data(data)

        assert result.participant_count == 64
        assert result.bracket_size == 64
        assert "64강" in result.rounds

    def test_bye_handling(self):
        """Bye matches should be processed correctly"""
        data = {
            "seeding": [
                {"seed": 1, "name": "김철수", "team": "서울"},
            ],
            "bouts": [
                {
                    "bout_id": "R1_01",
                    "round": "8강",
                    "round_order": 5,
                    "matchNumber": 1,
                    "player1": {"seed": 1, "name": "김철수", "team": "서울", "score": None},
                    "player2": None,
                    "winnerSeed": 1,
                    "winnerName": "김철수",
                    "isCompleted": True,
                    "isBye": True
                }
            ]
        }

        result = normalize_bracket_data(data)
        assert len(result.bouts) == 1
        assert result.bouts[0].is_bye == True
        assert result.bouts[0].player2_seed is None


class TestNormalizedBracketToDict:
    """Test NormalizedBracket.to_dict serialization"""

    def test_to_dict_structure(self):
        """to_dict should return complete serializable structure"""
        data = {
            "bracket_size": 8,
            "seeding": [{"seed": 1, "name": "A", "team": "X"}],
            "bouts": [
                {"bout_id": "QF_01", "round": "8강", "round_order": 5, "matchNumber": 1,
                 "player1": {"seed": 1, "name": "A", "score": 15},
                 "player2": {"seed": 2, "name": "B", "score": 10},
                 "winnerSeed": 1, "winnerName": "A", "isCompleted": True, "isBye": False}
            ]
        }

        result = normalize_bracket_data(data)
        result_dict = result.to_dict()

        assert isinstance(result_dict, dict)
        assert "bracket_size" in result_dict
        assert "rounds" in result_dict
        assert "bouts" in result_dict
        assert "bouts_by_round" in result_dict
        assert "seeding" in result_dict
        assert "participant_count" in result_dict
