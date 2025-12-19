"""
Unit tests for Server functionality

Tests cover:
1. DE bracket data transformation
2. Competition data access
3. Filter option building
4. Player search functionality
"""

import pytest
import sys
from pathlib import Path
from datetime import date

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


# =============================================================================
# DE Bracket Transformation Tests
# =============================================================================

class TestTransformDeBracket:
    """Tests for DE bracket data transformation"""

    def test_empty_de_bracket(self):
        """Test handling empty DE bracket data"""
        from app.server import transform_de_bracket

        event_data = {"name": "Test Event", "de_bracket": {}}
        result = transform_de_bracket(event_data)

        assert result["name"] == "Test Event"
        assert result.get("de_bracket") == {}

    def test_no_de_bracket(self):
        """Test handling event without DE bracket"""
        from app.server import transform_de_bracket

        event_data = {"name": "Test Event", "pool_rounds": []}
        result = transform_de_bracket(event_data)

        assert result["name"] == "Test Event"
        assert "de_bracket" not in result or result.get("de_bracket") is None

    def test_seeding_extraction(self):
        """Test that seeding data is properly extracted"""
        from app.server import transform_de_bracket

        event_data = {
            "name": "Test Event",
            "de_bracket": {
                "seeding": [
                    {"seed": 1, "name": "Player A", "team": "Team 1"},
                    {"seed": 2, "name": "Player B", "team": "Team 2"},
                    {"seed": 3, "name": "Player C", "team": "Team 3"},
                    {"seed": 4, "name": "Player D", "team": "Team 4"},
                ],
                "results_by_round": {}
            }
        }

        result = transform_de_bracket(event_data)

        assert "de_seeding" in result
        assert len(result["de_seeding"]) == 4
        assert result["de_seeding"][0]["name"] == "Player A"

    def test_round_name_normalization(self):
        """Test that round names are normalized correctly"""
        from app.server import transform_de_bracket

        event_data = {
            "name": "Test Event",
            "de_bracket": {
                "seeding": [
                    {"seed": 1, "name": "Player A", "team": "Team 1"},
                    {"seed": 2, "name": "Player B", "team": "Team 2"},
                ],
                "results_by_round": {
                    "32강전": [{"seed": 1, "name": "Player A", "score": {"winner_score": 15, "loser_score": 10}}],
                    "16강전": [{"seed": 1, "name": "Player A", "score": {"winner_score": 15, "loser_score": 8}}],
                    "8강전": [{"seed": 1, "name": "Player A", "score": {"winner_score": 15, "loser_score": 5}}],
                    "준결승": [{"seed": 1, "name": "Player A", "score": {"winner_score": 15, "loser_score": 12}}],
                    "결승": [{"seed": 1, "name": "Player A", "score": {"winner_score": 15, "loser_score": 14}}],
                }
            }
        }

        result = transform_de_bracket(event_data)

        # Check normalized round names
        assert "32강" in result["de_bracket"]
        assert "16강" in result["de_bracket"]
        assert "8강" in result["de_bracket"]
        assert "준결승" in result["de_bracket"]
        assert "결승" in result["de_bracket"]

        # Original names should not be present
        assert "32강전" not in result["de_bracket"]
        assert "16강전" not in result["de_bracket"]

    def test_match_transformation(self):
        """Test that match data is properly transformed"""
        from app.server import transform_de_bracket

        event_data = {
            "name": "Test Event",
            "de_bracket": {
                "seeding": [
                    {"seed": 1, "name": "김철수", "team": "서울중"},
                    {"seed": 2, "name": "이영희", "team": "부산중"},
                ],
                "results_by_round": {
                    "결승": [{
                        "seed": 1,
                        "name": "김철수",
                        "score": {"winner_score": 15, "loser_score": 12}
                    }]
                }
            }
        }

        result = transform_de_bracket(event_data)

        match = result["de_bracket"]["결승"][0]
        assert match["player1_seed"] == 1
        assert match["player1_name"] == "김철수"
        assert match["player1_team"] == "서울중"
        assert match["player1_score"] == 15
        assert match["player2_score"] == 12
        assert match["winner_seed"] == 1
        assert match["winner_name"] == "김철수"

    def test_missing_score_handling(self):
        """Test handling missing score data"""
        from app.server import transform_de_bracket

        event_data = {
            "name": "Test Event",
            "de_bracket": {
                "seeding": [{"seed": 1, "name": "Player A", "team": "Team 1"}],
                "results_by_round": {
                    "결승": [{
                        "seed": 1,
                        "name": "Player A",
                        # No score field
                    }]
                }
            }
        }

        result = transform_de_bracket(event_data)

        match = result["de_bracket"]["결승"][0]
        assert match["player1_score"] == 0
        assert match["player2_score"] == 0

    def test_duplicate_seed_handling(self):
        """Test handling duplicate seeds in seeding (first one wins)"""
        from app.server import transform_de_bracket

        event_data = {
            "name": "Test Event",
            "de_bracket": {
                "seeding": [
                    {"seed": 1, "name": "First Player", "team": "Team 1"},
                    {"seed": 1, "name": "Duplicate Player", "team": "Team 2"},  # Duplicate
                ],
                "results_by_round": {}
            }
        }

        result = transform_de_bracket(event_data)

        # The original seeding is preserved
        assert len(result["de_seeding"]) == 2


# =============================================================================
# Competition Data Access Tests
# =============================================================================

class TestCompetitionDataAccess:
    """Tests for competition data access functions"""

    @pytest.fixture(autouse=True)
    def setup_data(self):
        """Ensure data is loaded before tests"""
        from app.server import load_data
        load_data()

    def test_get_competitions_returns_list(self):
        """Test that get_competitions returns a list"""
        from app.server import get_competitions

        comps = get_competitions()
        assert isinstance(comps, list)

    def test_get_competition_by_valid_id(self):
        """Test getting competition by valid ID"""
        from app.server import get_competitions, get_competition

        comps = get_competitions()
        if comps:
            first_comp = comps[0]
            # Data structure: {"competition": {...}, "events": [...]}
            event_cd = first_comp.get("competition", {}).get("event_cd")

            comp = get_competition(event_cd)
            assert comp is not None
            assert comp.get("competition", {}).get("event_cd") == event_cd

    def test_get_competition_by_invalid_id(self):
        """Test getting competition by invalid ID"""
        from app.server import get_competition

        comp = get_competition("INVALID_ID_12345")
        assert comp is None

    def test_filter_options_structure(self):
        """Test that filter options have correct structure"""
        from app.server import _filter_options

        assert "weapons" in _filter_options
        assert "genders" in _filter_options
        assert "age_groups" in _filter_options
        assert "years" in _filter_options


# =============================================================================
# Player Index Tests
# =============================================================================

class TestPlayerIndex:
    """Tests for player index functionality"""

    @pytest.fixture(autouse=True)
    def setup_data(self):
        """Ensure data is loaded before tests"""
        from app.server import load_data
        load_data()

    def test_player_index_built(self):
        """Test that player index is built"""
        from app.server import _player_index

        assert isinstance(_player_index, dict)
        # Should have players indexed
        assert len(_player_index) > 0

    def test_player_index_has_korean_names(self):
        """Test that player index contains Korean names"""
        from app.server import _player_index

        # Find at least one player with Korean name (contains 김, 이, 박, etc.)
        korean_players = [name for name in _player_index.keys()
                         if any(char in name for char in "김이박최정강조윤")]
        assert len(korean_players) > 0

    def test_player_record_structure(self):
        """Test that player records have correct structure"""
        from app.server import _player_index

        # Get first player's records
        for name, records in list(_player_index.items())[:5]:
            for record in records[:1]:  # Check first record
                assert "competition_name" in record
                assert "rank" in record


# =============================================================================
# Data Validation Tests
# =============================================================================

class TestDataValidation:
    """Tests for data validation and integrity"""

    @pytest.fixture(autouse=True)
    def setup_data(self):
        """Ensure data is loaded before tests"""
        from app.server import load_data
        load_data()

    def test_competition_has_required_fields(self):
        """Test that competitions have required fields"""
        from app.server import get_competitions

        comps = get_competitions()
        for comp_data in comps[:10]:  # Check first 10
            # Data structure: {"competition": {...}, "events": [...]}
            comp = comp_data.get("competition", {})
            assert "event_cd" in comp
            assert "name" in comp or "comp_name" in comp

    def test_event_has_required_fields(self):
        """Test that events have required fields"""
        from app.server import get_competitions

        comps = get_competitions()
        for comp_data in comps[:5]:  # Check first 5 competitions
            events = comp_data.get("events", [])
            for event in events[:3]:  # Check first 3 events
                assert "name" in event or "event_name" in event


# =============================================================================
# DE Data Statistics Tests
# =============================================================================

class TestDEDataStatistics:
    """Tests for DE data availability and statistics"""

    @pytest.fixture(autouse=True)
    def setup_data(self):
        """Ensure data is loaded before tests"""
        from app.server import load_data
        load_data()

    def test_de_data_exists(self):
        """Test that DE data exists in at least some events"""
        from app.server import get_competitions

        comps = get_competitions()
        de_count = 0
        total_events = 0

        for comp_data in comps:
            for event in comp_data.get("events", []):
                total_events += 1
                de_bracket = event.get("de_bracket", {})
                # Check for any DE data (seeding, results_by_round, or match_results)
                if de_bracket and (
                    de_bracket.get("seeding") or
                    de_bracket.get("results_by_round") or
                    de_bracket.get("match_results")
                ):
                    de_count += 1

        # At least 10% of events should have DE data (adjusted for reality)
        assert total_events > 0
        de_ratio = de_count / total_events
        print(f"\nDE data ratio: {de_count}/{total_events} = {de_ratio:.1%}")
        assert de_ratio > 0.1, f"DE data ratio too low: {de_ratio:.1%}"

    def test_de_seeding_format(self):
        """Test that DE seeding has correct format when present"""
        from app.server import get_competitions

        comps = get_competitions()
        seeding_found = False

        for comp_data in comps[:20]:
            for event in comp_data.get("events", []):
                de_bracket = event.get("de_bracket", {})
                seeding = de_bracket.get("seeding", [])

                if seeding:
                    seeding_found = True
                    for player in seeding[:5]:  # Check first 5 players
                        assert "seed" in player
                        assert "name" in player

        # At least some events should have seeding
        assert seeding_found, "No seeding data found in any events"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
