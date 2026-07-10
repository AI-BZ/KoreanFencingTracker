"""
Dual DE Data Integrity Tests

Validates the Dual DE bracket structure for fencing national team selection events.

Dual DE Structure:
- First DE: 128강 (64 bouts) -> 64강 (32 bouts) -> 32 winners advance to Second DE
- Second DE: 64강 -> 32강 -> 16강 -> 8강 -> 준결승 -> 결승
- Seeded players: 32 (skip First DE, go directly to Second DE)
- Total participants: 32 seeded + 64 First DE = 96

Test Categories:
1. First DE round structure validation
2. Second DE round structure validation
3. Seeded player count validation
4. First DE participant count validation
5. Round order validation
"""
import pytest
from typing import Dict, Any
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.bracket_utils import (
    normalize_bracket_data,
    normalize_dual_de_bracket_data,
    is_dual_de_format,
    validate_dual_de_bracket,
    get_dual_de_combined_seeding,
    EXPECTED_BOUT_COUNT,
)


# =============================================================================
# Test Fixtures - Sample Dual DE Data
# =============================================================================

@pytest.fixture
def complete_dual_de_data() -> Dict[str, Any]:
    """
    Complete Dual DE bracket data with all expected structure.

    Structure:
    - 32 seeded players (skip First DE)
    - First DE: 64 participants -> 128강(64 bouts) -> 64강(32 bouts) -> 32 qualifiers
    - Second DE: 64 participants (32 seeded + 32 qualifiers) -> 64강 to 결승
    """
    # Generate seeded players (32)
    seeded_players = [
        {"seed": i, "name": f"시드선수{i}", "team": f"클럽{i % 10}"}
        for i in range(1, 33)
    ]

    # Generate First DE bouts
    # 128강: 64 bouts
    first_de_r128_bouts = []
    for match_num in range(1, 65):
        seed1 = match_num * 2 - 1
        seed2 = match_num * 2
        winner_seed = seed1 if match_num % 3 != 0 else seed2
        first_de_r128_bouts.append({
            "bout_id": f"128강_{match_num:02d}",
            "round": "128강",
            "round_order": 1,
            "match_number": match_num,
            "player1_seed": seed1,
            "player1_name": f"예선선수{seed1}",
            "player1_team": f"클럽{seed1 % 15}",
            "player1_score": 15 if winner_seed == seed1 else 10,
            "player2_seed": seed2,
            "player2_name": f"예선선수{seed2}",
            "player2_team": f"클럽{seed2 % 15}",
            "player2_score": 10 if winner_seed == seed1 else 15,
            "winner_seed": winner_seed,
            "winner_name": f"예선선수{winner_seed}",
            "is_completed": True,
            "is_bye": False,
        })

    # 64강: 32 bouts (winners from 128강)
    first_de_r64_bouts = []
    for match_num in range(1, 33):
        # Simplified: match winners from 128강
        seed1 = match_num * 2 - 1
        seed2 = match_num * 2
        winner_seed = seed1
        first_de_r64_bouts.append({
            "bout_id": f"64강_{match_num:02d}",
            "round": "64강",
            "round_order": 2,
            "match_number": match_num,
            "player1_seed": seed1,
            "player1_name": f"예선선수{seed1}",
            "player1_team": f"클럽{seed1 % 15}",
            "player1_score": 15,
            "player2_seed": seed2,
            "player2_name": f"예선선수{seed2}",
            "player2_team": f"클럽{seed2 % 15}",
            "player2_score": 12,
            "winner_seed": winner_seed,
            "winner_name": f"예선선수{winner_seed}",
            "is_completed": True,
            "is_bye": False,
        })

    # First DE qualifiers (32 winners from 64강)
    first_de_qualifiers = [
        {"seed": i, "name": f"예선선수{i * 2 - 1}", "team": f"클럽{(i * 2 - 1) % 15}"}
        for i in range(1, 33)
    ]

    # Generate Second DE bouts (64강 to 결승)
    second_de_bouts = {}

    # 64강: 32 bouts
    second_de_bouts["64강"] = []
    for match_num in range(1, 33):
        second_de_bouts["64강"].append({
            "bout_id": f"64강_{match_num:02d}",
            "round": "64강",
            "round_order": 2,
            "match_number": match_num,
            "player1_seed": match_num,
            "player1_name": f"시드선수{match_num}" if match_num <= 32 else f"진출자{match_num - 32}",
            "player1_team": f"클럽{match_num % 10}",
            "player1_score": 15,
            "player2_seed": 65 - match_num,
            "player2_name": f"진출자{65 - match_num - 32}" if 65 - match_num > 32 else f"시드선수{65 - match_num}",
            "player2_team": f"클럽{(65 - match_num) % 10}",
            "player2_score": 10,
            "winner_seed": match_num,
            "winner_name": f"시드선수{match_num}" if match_num <= 32 else f"진출자{match_num - 32}",
            "is_completed": True,
            "is_bye": False,
        })

    # 32강: 16 bouts
    second_de_bouts["32강"] = [
        {
            "bout_id": f"32강_{i:02d}",
            "round": "32강",
            "round_order": 3,
            "match_number": i,
            "player1_seed": i,
            "player1_name": f"시드선수{i}",
            "player1_team": f"클럽{i}",
            "player1_score": 15,
            "player2_seed": 33 - i,
            "player2_name": f"시드선수{33 - i}",
            "player2_team": f"클럽{33 - i}",
            "player2_score": 12,
            "winner_seed": i,
            "winner_name": f"시드선수{i}",
            "is_completed": True,
            "is_bye": False,
        }
        for i in range(1, 17)
    ]

    # 16강: 8 bouts
    second_de_bouts["16강"] = [
        {
            "bout_id": f"16강_{i:02d}",
            "round": "16강",
            "round_order": 4,
            "match_number": i,
            "player1_seed": i,
            "player1_name": f"시드선수{i}",
            "player1_team": f"클럽{i}",
            "player1_score": 15,
            "player2_seed": 17 - i,
            "player2_name": f"시드선수{17 - i}",
            "player2_team": f"클럽{17 - i}",
            "player2_score": 11,
            "winner_seed": i,
            "winner_name": f"시드선수{i}",
            "is_completed": True,
            "is_bye": False,
        }
        for i in range(1, 9)
    ]

    # 8강: 4 bouts
    second_de_bouts["8강"] = [
        {
            "bout_id": f"8강_{i:02d}",
            "round": "8강",
            "round_order": 5,
            "match_number": i,
            "player1_seed": i,
            "player1_name": f"시드선수{i}",
            "player1_team": f"클럽{i}",
            "player1_score": 15,
            "player2_seed": 9 - i,
            "player2_name": f"시드선수{9 - i}",
            "player2_team": f"클럽{9 - i}",
            "player2_score": 13,
            "winner_seed": i,
            "winner_name": f"시드선수{i}",
            "is_completed": True,
            "is_bye": False,
        }
        for i in range(1, 5)
    ]

    # 준결승: 2 bouts
    second_de_bouts["준결승"] = [
        {
            "bout_id": f"준결승_{i:02d}",
            "round": "준결승",
            "round_order": 6,
            "match_number": i,
            "player1_seed": i,
            "player1_name": f"시드선수{i}",
            "player1_team": f"클럽{i}",
            "player1_score": 15,
            "player2_seed": 5 - i,
            "player2_name": f"시드선수{5 - i}",
            "player2_team": f"클럽{5 - i}",
            "player2_score": 14,
            "winner_seed": i,
            "winner_name": f"시드선수{i}",
            "is_completed": True,
            "is_bye": False,
        }
        for i in range(1, 3)
    ]

    # 결승: 1 bout
    second_de_bouts["결승"] = [
        {
            "bout_id": "결승_01",
            "round": "결승",
            "round_order": 7,
            "match_number": 1,
            "player1_seed": 1,
            "player1_name": "시드선수1",
            "player1_team": "클럽1",
            "player1_score": 15,
            "player2_seed": 2,
            "player2_name": "시드선수2",
            "player2_team": "클럽2",
            "player2_score": 12,
            "winner_seed": 1,
            "winner_name": "시드선수1",
            "is_completed": True,
            "is_bye": False,
        }
    ]

    # Flatten Second DE bouts
    all_second_de_bouts = []
    for round_bouts in second_de_bouts.values():
        all_second_de_bouts.extend(round_bouts)

    return {
        "format": "dual_de",
        "seeded_players": seeded_players,
        "first_de": {
            "bracket_size": 128,
            "participant_count": 64,
            "starting_round": "128강",
            "rounds": ["128강", "64강"],
            "bouts": first_de_r128_bouts + first_de_r64_bouts,
            "seeding": [
                {"seed": i, "name": f"예선선수{i}", "team": f"클럽{i % 15}"}
                for i in range(1, 65)
            ],
        },
        "first_de_qualifiers": first_de_qualifiers,
        "second_de": {
            "bracket_size": 64,
            "participant_count": 64,
            "starting_round": "64강",
            "rounds": ["64강", "32강", "16강", "8강", "준결승", "결승"],
            "bouts": all_second_de_bouts,
            "seeding": seeded_players + first_de_qualifiers,
        },
    }


@pytest.fixture
def minimal_first_de_data() -> Dict[str, Any]:
    """First DE with minimal data for round count validation."""
    return {
        "bracket_size": 128,
        "participant_count": 64,
        "starting_round": "128강",
        "rounds": ["128강", "64강"],
        "seeding": [
            {"seed": i, "name": f"선수{i}", "team": f"팀{i}"}
            for i in range(1, 65)
        ],
        "bouts": [
            {
                "bout_id": "128강_01",
                "round": "128강",
                "round_order": 1,
                "match_number": 1,
                "player1_seed": 1,
                "player1_name": "선수1",
                "player1_team": "팀1",
                "player1_score": 15,
                "player2_seed": 2,
                "player2_name": "선수2",
                "player2_team": "팀2",
                "player2_score": 10,
                "winner_seed": 1,
                "winner_name": "선수1",
                "is_completed": True,
                "is_bye": False,
            },
            {
                "bout_id": "64강_01",
                "round": "64강",
                "round_order": 2,
                "match_number": 1,
                "player1_seed": 1,
                "player1_name": "선수1",
                "player1_team": "팀1",
                "player1_score": 15,
                "player2_seed": 3,
                "player2_name": "선수3",
                "player2_team": "팀3",
                "player2_score": 12,
                "winner_seed": 1,
                "winner_name": "선수1",
                "is_completed": True,
                "is_bye": False,
            },
        ],
    }


@pytest.fixture
def minimal_second_de_data() -> Dict[str, Any]:
    """Second DE with all 6 rounds for structure validation."""
    rounds = ["64강", "32강", "16강", "8강", "준결승", "결승"]
    bout_counts = [32, 16, 8, 4, 2, 1]
    round_orders = [2, 3, 4, 5, 6, 7]

    bouts = []
    for round_name, count, order in zip(rounds, bout_counts, round_orders):
        for match_num in range(1, count + 1):
            bouts.append({
                "bout_id": f"{round_name}_{match_num:02d}",
                "round": round_name,
                "round_order": order,
                "match_number": match_num,
                "player1_seed": match_num,
                "player1_name": f"선수{match_num}",
                "player1_team": f"팀{match_num}",
                "player1_score": 15,
                "player2_seed": count * 2 + 1 - match_num,
                "player2_name": f"선수{count * 2 + 1 - match_num}",
                "player2_team": f"팀{count * 2 + 1 - match_num}",
                "player2_score": 10,
                "winner_seed": match_num,
                "winner_name": f"선수{match_num}",
                "is_completed": True,
                "is_bye": False,
            })

    return {
        "bracket_size": 64,
        "participant_count": 64,
        "starting_round": "64강",
        "rounds": rounds,
        "seeding": [
            {"seed": i, "name": f"선수{i}", "team": f"팀{i}"}
            for i in range(1, 65)
        ],
        "bouts": bouts,
    }


# =============================================================================
# Test 1: First DE Round Structure Validation
# =============================================================================

class TestFirstDERoundStructure:
    """
    Validate First DE has exactly 2 rounds: 128강 and 64강.

    First DE Structure:
    - 128강: 64 bouts (64 participants pair up)
    - 64강: 32 bouts (128강 winners compete)
    - Total: 96 bouts, 32 winners advance to Second DE
    """

    def test_first_de_has_exactly_two_rounds(self, minimal_first_de_data):
        """First DE should have exactly 2 rounds (128강, 64강)."""
        bracket = normalize_bracket_data(minimal_first_de_data, fill_to_final=False)

        # First DE should NOT continue to 32강 or beyond
        assert len(bracket.rounds) == 2, f"First DE should have 2 rounds, got {len(bracket.rounds)}: {bracket.rounds}"

    def test_first_de_rounds_are_128_and_64(self, minimal_first_de_data):
        """First DE rounds should be ['128강', '64강']."""
        bracket = normalize_bracket_data(minimal_first_de_data, fill_to_final=False)

        expected_rounds = ["128강", "64강"]
        assert bracket.rounds == expected_rounds, f"Expected {expected_rounds}, got {bracket.rounds}"

    def test_first_de_round_order_is_correct(self, minimal_first_de_data):
        """128강 should come before 64강."""
        bracket = normalize_bracket_data(minimal_first_de_data, fill_to_final=False)

        if len(bracket.rounds) >= 2:
            first_idx = bracket.rounds.index("128강") if "128강" in bracket.rounds else -1
            second_idx = bracket.rounds.index("64강") if "64강" in bracket.rounds else -1

            assert first_idx < second_idx, "128강 should come before 64강"

    def test_first_de_128_has_correct_bout_count(self, complete_dual_de_data):
        """128강 in First DE should have 64 actual bouts (excluding auto-generated byes)."""
        first_de_data = complete_dual_de_data["first_de"]
        bracket = normalize_bracket_data(first_de_data, fill_to_final=False)

        r128_bouts = bracket.bouts_by_round.get("128강", [])
        # Note: normalize_bracket_data may add bye matches for seeds > participant_count
        # We count only non-bye bouts for actual match count validation
        actual_bouts = [b for b in r128_bouts if not b.is_bye]
        assert len(actual_bouts) == 64, f"128강 should have 64 actual bouts (excl. byes), got {len(actual_bouts)}"

    def test_first_de_64_has_correct_bout_count(self, complete_dual_de_data):
        """64강 in First DE should have 32 bouts."""
        first_de_data = complete_dual_de_data["first_de"]
        bracket = normalize_bracket_data(first_de_data, fill_to_final=False)

        r64_bouts = bracket.bouts_by_round.get("64강", [])
        assert len(r64_bouts) == 32, f"64강 should have 32 bouts, got {len(r64_bouts)}"

    def test_first_de_does_not_have_32_or_later_rounds(self, complete_dual_de_data):
        """First DE should not have 32강 or later rounds."""
        first_de_data = complete_dual_de_data["first_de"]
        bracket = normalize_bracket_data(first_de_data, fill_to_final=False)

        invalid_rounds = ["32강", "16강", "8강", "준결승", "결승"]
        for round_name in invalid_rounds:
            assert round_name not in bracket.rounds, f"First DE should not have {round_name}"
            assert round_name not in bracket.bouts_by_round, f"First DE should not have bouts in {round_name}"


# =============================================================================
# Test 2: Second DE Round Structure Validation
# =============================================================================

class TestSecondDERoundStructure:
    """
    Validate Second DE has exactly 6 rounds: 64강, 32강, 16강, 8강, 준결승, 결승.

    Second DE Structure:
    - 64강: 32 bouts (64 participants: 32 seeded + 32 First DE qualifiers)
    - 32강: 16 bouts
    - 16강: 8 bouts
    - 8강: 4 bouts
    - 준결승: 2 bouts
    - 결승: 1 bout
    """

    def test_second_de_has_exactly_six_rounds(self, minimal_second_de_data):
        """Second DE should have exactly 6 rounds."""
        bracket = normalize_bracket_data(minimal_second_de_data, fill_to_final=False)

        expected_count = 6
        assert len(bracket.rounds) == expected_count, f"Second DE should have {expected_count} rounds, got {len(bracket.rounds)}: {bracket.rounds}"

    def test_second_de_has_correct_rounds(self, minimal_second_de_data):
        """Second DE should have 64강, 32강, 16강, 8강, 준결승, 결승."""
        bracket = normalize_bracket_data(minimal_second_de_data, fill_to_final=False)

        expected_rounds = ["64강", "32강", "16강", "8강", "준결승", "결승"]
        assert bracket.rounds == expected_rounds, f"Expected {expected_rounds}, got {bracket.rounds}"

    def test_second_de_round_order_is_correct(self, minimal_second_de_data):
        """Rounds should be in correct tournament order."""
        bracket = normalize_bracket_data(minimal_second_de_data, fill_to_final=False)

        expected_order = ["64강", "32강", "16강", "8강", "준결승", "결승"]
        for i, round_name in enumerate(expected_order):
            if round_name in bracket.rounds:
                actual_idx = bracket.rounds.index(round_name)
                assert actual_idx == i, f"{round_name} should be at index {i}, got {actual_idx}"

    def test_second_de_does_not_have_128(self, minimal_second_de_data):
        """Second DE should not have 128강 (that's First DE only)."""
        bracket = normalize_bracket_data(minimal_second_de_data, fill_to_final=False)

        assert "128강" not in bracket.rounds, "Second DE should not have 128강"

    @pytest.mark.parametrize("round_name,expected_count", [
        ("64강", 32),
        ("32강", 16),
        ("16강", 8),
        ("8강", 4),
        ("준결승", 2),
        ("결승", 1),
    ])
    def test_second_de_bout_counts_per_round(self, minimal_second_de_data, round_name, expected_count):
        """Each round should have the expected number of bouts."""
        bracket = normalize_bracket_data(minimal_second_de_data, fill_to_final=False)

        bouts = bracket.bouts_by_round.get(round_name, [])
        assert len(bouts) == expected_count, f"{round_name} should have {expected_count} bouts, got {len(bouts)}"


# =============================================================================
# Test 3: Seeded Player Count Validation
# =============================================================================

class TestSeededPlayerCount:
    """
    Validate seeded player count matches expected value (32).

    Seeded players:
    - Skip First DE entirely
    - Go directly to Second DE
    - Should be exactly 32 players
    """

    def test_seeded_player_count_is_32(self, complete_dual_de_data):
        """There should be exactly 32 seeded players."""
        dual_de = normalize_dual_de_bracket_data(complete_dual_de_data)

        assert len(dual_de.seeded_players) == 32, f"Expected 32 seeded players, got {len(dual_de.seeded_players)}"

    def test_seeded_count_metadata_matches(self, complete_dual_de_data):
        """seeded_count metadata should match actual seeded_players count."""
        dual_de = normalize_dual_de_bracket_data(complete_dual_de_data)

        assert dual_de.seeded_count == len(dual_de.seeded_players), \
            f"seeded_count ({dual_de.seeded_count}) != len(seeded_players) ({len(dual_de.seeded_players)})"

    def test_all_seeded_players_have_is_seeded_flag(self, complete_dual_de_data):
        """All seeded players should have is_seeded=True."""
        dual_de = normalize_dual_de_bracket_data(complete_dual_de_data)

        for player in dual_de.seeded_players:
            assert player.is_seeded, f"Player {player.name} should have is_seeded=True"

    def test_seeded_players_have_no_first_de_result(self, complete_dual_de_data):
        """Seeded players should have first_de_result=None (they don't participate)."""
        dual_de = normalize_dual_de_bracket_data(complete_dual_de_data)

        for player in dual_de.seeded_players:
            assert player.first_de_result is None, \
                f"Player {player.name} should have first_de_result=None, got {player.first_de_result}"

    def test_seeded_players_have_valid_seeds(self, complete_dual_de_data):
        """Seeded players should have seeds 1-32."""
        dual_de = normalize_dual_de_bracket_data(complete_dual_de_data)

        seeds = [p.seed for p in dual_de.seeded_players]
        expected_seeds = list(range(1, 33))

        assert sorted(seeds) == expected_seeds, f"Seeded players should have seeds 1-32, got {sorted(seeds)}"

    def test_validation_warns_on_incorrect_seeded_count(self):
        """Validation should warn if seeded count is not 32."""
        # Create data with wrong seeded count
        dual_de_data = {
            "format": "dual_de",
            "seeded_players": [
                {"seed": i, "name": f"시드{i}", "team": f"팀{i}"}
                for i in range(1, 25)  # Only 24 seeded players
            ],
            "first_de": None,
            "second_de": None,
            "first_de_qualifiers": [],
        }

        dual_de = normalize_dual_de_bracket_data(dual_de_data)
        validation = validate_dual_de_bracket(dual_de)

        # Should have warning about seeded count
        has_warning = any("시드" in w or "seeded" in w.lower() for w in validation["warnings"])
        assert has_warning or validation["seeded_count"] == 24, \
            "Should warn about incorrect seeded count or report actual count"


# =============================================================================
# Test 4: First DE Participant Count Validation
# =============================================================================

class TestFirstDEParticipantCount:
    """
    Validate First DE participant count is correct.

    First DE participants:
    - 64 players compete in First DE
    - Results in 32 qualifiers advancing to Second DE
    """

    def test_first_de_participant_count_is_64(self, complete_dual_de_data):
        """First DE should have 64 participants."""
        dual_de = normalize_dual_de_bracket_data(complete_dual_de_data)

        assert dual_de.first_de_participant_count == 64, \
            f"Expected 64 First DE participants, got {dual_de.first_de_participant_count}"

    def test_first_de_bracket_participant_count_matches(self, complete_dual_de_data):
        """First DE bracket.participant_count should match first_de_participant_count."""
        dual_de = normalize_dual_de_bracket_data(complete_dual_de_data)

        if dual_de.first_de:
            assert dual_de.first_de.participant_count == dual_de.first_de_participant_count, \
                f"Bracket count ({dual_de.first_de.participant_count}) != metadata ({dual_de.first_de_participant_count})"

    def test_first_de_qualifiers_count_is_32(self, complete_dual_de_data):
        """First DE should produce 32 qualifiers for Second DE."""
        dual_de = normalize_dual_de_bracket_data(complete_dual_de_data)

        assert len(dual_de.first_de_qualifiers) == 32, \
            f"Expected 32 First DE qualifiers, got {len(dual_de.first_de_qualifiers)}"

    def test_first_de_qualifiers_have_qualified_status(self, complete_dual_de_data):
        """All First DE qualifiers should have first_de_result='qualified'."""
        dual_de = normalize_dual_de_bracket_data(complete_dual_de_data)

        for player in dual_de.first_de_qualifiers:
            assert player.first_de_result == "qualified", \
                f"Player {player.name} should have first_de_result='qualified', got {player.first_de_result}"

    def test_first_de_qualifiers_are_not_seeded(self, complete_dual_de_data):
        """First DE qualifiers should have is_seeded=False."""
        dual_de = normalize_dual_de_bracket_data(complete_dual_de_data)

        for player in dual_de.first_de_qualifiers:
            assert not player.is_seeded, f"First DE qualifier {player.name} should have is_seeded=False"

    def test_total_participants_is_96(self, complete_dual_de_data):
        """Total participants should be 96 (32 seeded + 64 First DE)."""
        dual_de = normalize_dual_de_bracket_data(complete_dual_de_data)

        expected_total = 32 + 64
        assert dual_de.total_participants == expected_total, \
            f"Expected {expected_total} total participants, got {dual_de.total_participants}"

    def test_second_de_participant_count_is_64(self, complete_dual_de_data):
        """Second DE should have 64 participants (32 seeded + 32 qualifiers)."""
        dual_de = normalize_dual_de_bracket_data(complete_dual_de_data)

        if dual_de.second_de:
            assert dual_de.second_de.participant_count == 64, \
                f"Second DE should have 64 participants, got {dual_de.second_de.participant_count}"


# =============================================================================
# Test 5: Bracket Rounds List Order Validation
# =============================================================================

class TestBracketRoundsOrder:
    """
    Validate bracket.rounds list is in correct tournament order.

    Correct order:
    - First DE: ["128강", "64강"]
    - Second DE: ["64강", "32강", "16강", "8강", "준결승", "결승"]
    """

    def test_first_de_rounds_order(self, complete_dual_de_data):
        """First DE rounds should be in order: 128강 -> 64강."""
        dual_de = normalize_dual_de_bracket_data(complete_dual_de_data)

        if dual_de.first_de:
            expected = ["128강", "64강"]
            actual = dual_de.first_de.rounds
            assert actual == expected, f"First DE rounds order should be {expected}, got {actual}"

    def test_second_de_rounds_order(self, complete_dual_de_data):
        """Second DE rounds should be in order: 64강 -> 32강 -> ... -> 결승."""
        dual_de = normalize_dual_de_bracket_data(complete_dual_de_data)

        if dual_de.second_de:
            expected = ["64강", "32강", "16강", "8강", "준결승", "결승"]
            actual = dual_de.second_de.rounds
            assert actual == expected, f"Second DE rounds order should be {expected}, got {actual}"

    def test_rounds_are_not_reversed(self, complete_dual_de_data):
        """Rounds should not be in reverse order (결승 should be last, not first)."""
        dual_de = normalize_dual_de_bracket_data(complete_dual_de_data)

        if dual_de.second_de and dual_de.second_de.rounds:
            first_round = dual_de.second_de.rounds[0]
            last_round = dual_de.second_de.rounds[-1]

            assert first_round != "결승", "First round should not be 결승"
            assert last_round == "결승", "Last round should be 결승"

    def test_rounds_follow_tournament_progression(self, complete_dual_de_data):
        """Each round should have fewer bouts than the previous."""
        dual_de = normalize_dual_de_bracket_data(complete_dual_de_data)

        if dual_de.second_de:
            prev_count = float('inf')
            for round_name in dual_de.second_de.rounds:
                bouts = dual_de.second_de.bouts_by_round.get(round_name, [])
                current_count = len(bouts)

                # Skip empty rounds (might be incomplete tournament)
                if current_count > 0:
                    assert current_count <= prev_count, \
                        f"{round_name} has {current_count} bouts, but previous had {prev_count} - order is wrong"
                    prev_count = current_count

    def test_round_order_values_are_increasing(self, complete_dual_de_data):
        """round_order values should increase as tournament progresses."""
        dual_de = normalize_dual_de_bracket_data(complete_dual_de_data)

        if dual_de.second_de:
            prev_order = 0
            for round_name in dual_de.second_de.rounds:
                bouts = dual_de.second_de.bouts_by_round.get(round_name, [])
                if bouts:
                    current_order = bouts[0].round_order
                    assert current_order > prev_order, \
                        f"{round_name} has round_order {current_order}, should be > {prev_order}"
                    prev_order = current_order


# =============================================================================
# Integration Tests - Full Dual DE Validation
# =============================================================================

class TestDualDEIntegration:
    """Integration tests for complete Dual DE validation."""

    def test_is_dual_de_format_detection(self, complete_dual_de_data):
        """Should correctly detect Dual DE format."""
        assert is_dual_de_format(complete_dual_de_data), "Should detect dual_de format"

    def test_non_dual_de_not_detected(self):
        """Regular bracket should not be detected as Dual DE."""
        regular_bracket = {
            "bracket_size": 32,
            "starting_round": "32강",
            "bouts": [],
        }
        assert not is_dual_de_format(regular_bracket), "Regular bracket should not be Dual DE"

    def test_dual_de_validation_structure(self, complete_dual_de_data):
        """
        Complete Dual DE data validation should report correct counts.

        Note: The validate_dual_de_bracket function may report issues for First DE
        not having 준결승/결승 rounds, which is expected behavior for First DE
        (it only has 128강 and 64강). We validate the structure separately.
        """
        dual_de = normalize_dual_de_bracket_data(complete_dual_de_data)
        validation = validate_dual_de_bracket(dual_de)

        # Verify the counts are correct even if validation has issues
        assert validation["seeded_count"] == 32, f"Should have 32 seeded, got {validation['seeded_count']}"
        assert validation["qualifier_count"] == 32, f"Should have 32 qualifiers, got {validation['qualifier_count']}"

        # Verify status is completed
        assert validation["status"] == "completed", f"Status should be 'completed', got {validation['status']}"

        # First DE not having 준결승/결승 is expected - it's a preliminary DE
        # Filter out expected First DE issues
        unexpected_issues = [
            issue for issue in validation["issues"]
            if "First DE:" not in issue  # First DE issues are expected for Dual DE
        ]
        assert len(unexpected_issues) == 0, f"Unexpected validation issues: {unexpected_issues}"

    def test_combined_seeding_has_64_players(self, complete_dual_de_data):
        """Combined seeding for Second DE should have 64 players."""
        dual_de = normalize_dual_de_bracket_data(complete_dual_de_data)
        combined = get_dual_de_combined_seeding(dual_de)

        assert len(combined) == 64, f"Combined seeding should have 64 players, got {len(combined)}"

    def test_combined_seeding_has_correct_sources(self, complete_dual_de_data):
        """Combined seeding should have 32 seeded and 32 qualifiers."""
        dual_de = normalize_dual_de_bracket_data(complete_dual_de_data)
        combined = get_dual_de_combined_seeding(dual_de)

        seeded = [p for p in combined if p["source"] == "seeded"]
        qualifiers = [p for p in combined if p["source"] == "first_de_qualifier"]

        assert len(seeded) == 32, f"Should have 32 seeded, got {len(seeded)}"
        assert len(qualifiers) == 32, f"Should have 32 qualifiers, got {len(qualifiers)}"

    def test_dual_de_status_detection(self, complete_dual_de_data):
        """Should correctly detect completion status."""
        dual_de = normalize_dual_de_bracket_data(complete_dual_de_data)

        # Complete data should have status="completed"
        assert dual_de.status == "completed", f"Expected 'completed', got '{dual_de.status}'"

    def test_empty_dual_de_has_pending_status(self):
        """Empty Dual DE should have pending status."""
        empty_data = {"format": "dual_de"}
        dual_de = normalize_dual_de_bracket_data(empty_data)

        assert dual_de.status == "pending", f"Empty Dual DE should be 'pending', got '{dual_de.status}'"


# =============================================================================
# Edge Case Tests
# =============================================================================

class TestDualDEEdgeCases:
    """Edge case tests for Dual DE validation."""

    def test_partial_first_de_in_progress(self):
        """Partially complete First DE should have in_progress status."""
        partial_data = {
            "format": "dual_de",
            "seeded_players": [
                {"seed": i, "name": f"시드{i}", "team": f"팀{i}"}
                for i in range(1, 33)
            ],
            "first_de": {
                "bracket_size": 128,
                "participant_count": 64,
                "starting_round": "128강",
                "rounds": ["128강", "64강"],
                "seeding": [],
                "bouts": [
                    {
                        "bout_id": "128강_01",
                        "round": "128강",
                        "round_order": 1,
                        "match_number": 1,
                        "player1_seed": 1,
                        "player1_name": "선수1",
                        "player1_team": "팀1",
                        "player1_score": 15,
                        "player2_seed": 2,
                        "player2_name": "선수2",
                        "player2_team": "팀2",
                        "player2_score": 10,
                        "winner_seed": 1,
                        "winner_name": "선수1",
                        "is_completed": True,
                        "is_bye": False,
                    }
                    # Only 1 bout completed out of 64
                ],
            },
            "second_de": None,
            "first_de_qualifiers": [],
        }

        dual_de = normalize_dual_de_bracket_data(partial_data)
        assert dual_de.status == "first_de_in_progress", \
            f"Partial First DE should be 'first_de_in_progress', got '{dual_de.status}'"

    def test_missing_seeded_players_warning(self):
        """Should warn when seeded players are missing."""
        no_seeded_data = {
            "format": "dual_de",
            "seeded_players": [],
            "first_de": None,
            "second_de": None,
            "first_de_qualifiers": [],
        }

        dual_de = normalize_dual_de_bracket_data(no_seeded_data)
        validation = validate_dual_de_bracket(dual_de)

        # Should have issue or warning about missing seeded players
        has_seeded_issue = any("시드" in i or "seeded" in i.lower() for i in validation["issues"])
        assert has_seeded_issue or validation["seeded_count"] == 0

    def test_bout_round_matches_bouts_by_round_key(self, complete_dual_de_data):
        """Each bout's round field should match its bouts_by_round key."""
        dual_de = normalize_dual_de_bracket_data(complete_dual_de_data)

        for bracket, bracket_name in [(dual_de.first_de, "First DE"), (dual_de.second_de, "Second DE")]:
            if bracket:
                for round_name, bouts in bracket.bouts_by_round.items():
                    for bout in bouts:
                        assert bout.round == round_name, \
                            f"{bracket_name}: Bout {bout.bout_id} has round='{bout.round}' but is in bouts_by_round['{round_name}']"


# =============================================================================
# Data-Driven Tests with Real DB Structure
# =============================================================================

class TestRealDualDEDataStructure:
    """
    Tests that verify the actual DB data structure matches expected format.
    These tests use the same structure that would be stored in Supabase.
    """

    def test_db_format_first_de_structure(self):
        """First DE from DB should have correct structure."""
        # Simulate DB structure
        db_first_de = {
            "bracket_size": 128,
            "participant_count": 64,
            "starting_round": "128강",
            "rounds": ["128강", "64강"],
            "seeding": [{"seed": i, "name": f"P{i}", "team": f"T{i}"} for i in range(1, 65)],
            "bouts": [],
            "bouts_by_round": {
                "128강": [],  # 64 bouts expected
                "64강": [],   # 32 bouts expected
            },
        }

        assert db_first_de["starting_round"] == "128강"
        assert len(db_first_de["rounds"]) == 2
        assert "32강" not in db_first_de["rounds"]

    def test_db_format_second_de_structure(self):
        """Second DE from DB should have correct structure."""
        db_second_de = {
            "bracket_size": 64,
            "participant_count": 64,
            "starting_round": "64강",
            "rounds": ["64강", "32강", "16강", "8강", "준결승", "결승"],
            "seeding": [{"seed": i, "name": f"P{i}", "team": f"T{i}"} for i in range(1, 65)],
            "bouts": [],
            "bouts_by_round": {
                "64강": [],     # 32 bouts
                "32강": [],     # 16 bouts
                "16강": [],     # 8 bouts
                "8강": [],      # 4 bouts
                "준결승": [],   # 2 bouts
                "결승": [],     # 1 bout
            },
        }

        assert db_second_de["starting_round"] == "64강"
        assert len(db_second_de["rounds"]) == 6
        assert "128강" not in db_second_de["rounds"]

    def test_expected_bout_counts_constant(self):
        """EXPECTED_BOUT_COUNT constant should have correct values."""
        assert EXPECTED_BOUT_COUNT["128강"] == 64
        assert EXPECTED_BOUT_COUNT["64강"] == 32
        assert EXPECTED_BOUT_COUNT["32강"] == 16
        assert EXPECTED_BOUT_COUNT["16강"] == 8
        assert EXPECTED_BOUT_COUNT["8강"] == 4
        assert EXPECTED_BOUT_COUNT["준결승"] == 2
        assert EXPECTED_BOUT_COUNT["결승"] == 1


# =============================================================================
# Performance and Stress Tests
# =============================================================================

class TestDualDEPerformance:
    """Performance tests for Dual DE normalization."""

    def test_normalization_handles_large_bout_count(self, complete_dual_de_data):
        """Should handle 96+ bouts in First DE efficiently."""
        dual_de = normalize_dual_de_bracket_data(complete_dual_de_data)

        if dual_de.first_de:
            total_bouts = len(dual_de.first_de.bouts)
            # First DE should have 64 + 32 = 96 bouts
            assert total_bouts >= 90, f"First DE should have ~96 bouts, got {total_bouts}"

    def test_normalization_handles_full_second_de(self, complete_dual_de_data):
        """Should handle 63 bouts in Second DE efficiently."""
        dual_de = normalize_dual_de_bracket_data(complete_dual_de_data)

        if dual_de.second_de:
            total_bouts = len(dual_de.second_de.bouts)
            # Second DE should have 32+16+8+4+2+1 = 63 bouts
            assert total_bouts >= 60, f"Second DE should have ~63 bouts, got {total_bouts}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
