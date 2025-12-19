"""
Unit tests for Player Identity Resolution System

Tests cover:
1. TeamRecord and PlayerProfile dataclasses
2. PlayerIdentityResolver - identity resolution algorithm
3. Disambiguation handling (동명이인)
4. Team change tracking (소속변경)
"""

import pytest
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.player_identity import (
    TeamRecord,
    PlayerProfile,
    NameGroup,
    PlayerIdentityResolver,
)


# =============================================================================
# TeamRecord Tests
# =============================================================================

class TestTeamRecord:
    """Tests for TeamRecord dataclass"""

    def test_create_team_record(self):
        """Test basic TeamRecord creation"""
        record = TeamRecord(
            team="서울펜싱클럽",
            first_seen="2023-01-01",
            last_seen="2023-06-01",
            competition_count=5
        )
        assert record.team == "서울펜싱클럽"
        assert record.first_seen == "2023-01-01"
        assert record.last_seen == "2023-06-01"
        assert record.competition_count == 5

    def test_default_competition_count(self):
        """Test default competition count is 1"""
        record = TeamRecord(
            team="부산체고",
            first_seen="2023-01-01",
            last_seen="2023-01-01"
        )
        assert record.competition_count == 1


# =============================================================================
# PlayerProfile Tests
# =============================================================================

class TestPlayerProfile:
    """Tests for PlayerProfile dataclass"""

    def test_create_empty_profile(self):
        """Test creating empty profile"""
        profile = PlayerProfile(
            player_id="abc123",
            name="김선수"
        )
        assert profile.player_id == "abc123"
        assert profile.name == "김선수"
        assert profile.team_history == []
        assert profile.current_team == ""
        assert profile.teams == []

    def test_add_single_team(self):
        """Test adding a single team"""
        profile = PlayerProfile(player_id="test1", name="홍길동")
        profile.add_team("서울펜싱클럽", "2023-05-01")

        assert len(profile.team_history) == 1
        assert profile.current_team == "서울펜싱클럽"
        assert profile.teams == ["서울펜싱클럽"]

    def test_add_team_updates_date_range(self):
        """Test that adding same team updates date range"""
        profile = PlayerProfile(player_id="test2", name="이선수")
        profile.add_team("서울체고", "2023-01-01")
        profile.add_team("서울체고", "2023-06-01")
        profile.add_team("서울체고", "2022-06-01")  # Earlier date

        assert len(profile.team_history) == 1
        assert profile.team_history[0].first_seen == "2022-06-01"
        assert profile.team_history[0].last_seen == "2023-06-01"
        assert profile.team_history[0].competition_count == 3

    def test_add_multiple_teams(self):
        """Test adding multiple teams (team change)"""
        profile = PlayerProfile(player_id="test3", name="박선수")
        profile.add_team("중학교A", "2022-01-01")
        profile.add_team("고등학교B", "2023-03-01")

        assert len(profile.team_history) == 2
        assert profile.teams == ["중학교A", "고등학교B"]
        assert profile.current_team == "고등학교B"

    def test_teams_sorted_chronologically(self):
        """Test that teams are sorted by first_seen date"""
        profile = PlayerProfile(player_id="test4", name="최선수")
        profile.add_team("팀C", "2023-01-01")
        profile.add_team("팀A", "2021-01-01")
        profile.add_team("팀B", "2022-01-01")

        assert profile.team_history[0].team == "팀A"
        assert profile.team_history[1].team == "팀B"
        assert profile.team_history[2].team == "팀C"

    def test_add_empty_team_ignored(self):
        """Test that empty team names are ignored"""
        profile = PlayerProfile(player_id="test5", name="정선수")
        profile.add_team("", "2023-01-01")
        profile.add_team(None, "2023-01-01")

        assert len(profile.team_history) == 0


# =============================================================================
# PlayerIdentityResolver Tests
# =============================================================================

class TestPlayerIdentityResolver:
    """Tests for PlayerIdentityResolver class"""

    @pytest.fixture
    def resolver(self):
        """Create empty resolver"""
        return PlayerIdentityResolver()

    @pytest.fixture
    def sample_competition_data(self):
        """Sample competition data for testing"""
        return {
            "competition": {
                "event_cd": "COMP001",
                "name": "2023년 전국대회",
                "start_date": "2023-05-01"
            },
            "events": [
                {
                    "name": "남자 플러레 중등부 개인",
                    "weapon": "플러레",
                    "pool_rounds": [
                        {
                            "results": [
                                {"name": "김철수", "team": "서울중학교", "rank": 1},
                                {"name": "이영희", "team": "부산중학교", "rank": 2},
                            ]
                        }
                    ],
                    "final_rankings": [
                        {"name": "김철수", "team": "서울중학교", "rank": 1},
                        {"name": "이영희", "team": "부산중학교", "rank": 2},
                    ]
                }
            ]
        }

    def test_add_competition_data(self, resolver, sample_competition_data):
        """Test adding competition data"""
        resolver.add_competition_data(sample_competition_data)

        assert "김철수" in resolver.name_groups
        assert "이영희" in resolver.name_groups
        assert len(resolver.name_groups["김철수"].records) > 0

    def test_resolve_single_person_identity(self, resolver, sample_competition_data):
        """Test resolving identity for single person"""
        resolver.add_competition_data(sample_competition_data)
        resolver.resolve_identities()

        assert "김철수" in resolver.name_to_profiles
        assert len(resolver.name_to_profiles["김철수"]) == 1

        profiles = resolver.get_players_by_name("김철수")
        assert len(profiles) == 1
        assert profiles[0].name == "김철수"
        assert profiles[0].current_team == "서울중학교"

    def test_disambiguation_same_competition(self, resolver):
        """Test disambiguation when same name appears with different teams in same competition"""
        # Same competition, same name, different teams = different people
        data = {
            "competition": {
                "event_cd": "COMP001",
                "name": "2023년 대회",
                "start_date": "2023-05-01"
            },
            "events": [
                {
                    "name": "남자 플러레 개인",
                    "weapon": "플러레",
                    "pool_rounds": [
                        {
                            "results": [
                                {"name": "김민수", "team": "서울팀", "rank": 1},
                            ]
                        },
                        {
                            "results": [
                                {"name": "김민수", "team": "부산팀", "rank": 1},
                            ]
                        }
                    ],
                    "final_rankings": []
                }
            ]
        }

        resolver.add_competition_data(data)
        resolver.resolve_identities()

        # Should create 2 profiles for 김민수 (동명이인)
        assert "김민수" in resolver.name_to_profiles
        assert len(resolver.name_to_profiles["김민수"]) == 2
        assert resolver.has_disambiguation("김민수")

    def test_no_disambiguation_team_change(self, resolver):
        """Test that team changes don't create disambiguation (different competitions)"""
        # Different competitions, same name, different teams = same person, team change
        data1 = {
            "competition": {
                "event_cd": "COMP001",
                "name": "2022년 대회",
                "start_date": "2022-05-01"
            },
            "events": [{
                "name": "남자 플러레 개인",
                "weapon": "플러레",
                "pool_rounds": [{"results": [{"name": "박진수", "team": "서울중학교", "rank": 1}]}],
                "final_rankings": [{"name": "박진수", "team": "서울중학교", "rank": 1}]
            }]
        }

        data2 = {
            "competition": {
                "event_cd": "COMP002",
                "name": "2023년 대회",
                "start_date": "2023-05-01"
            },
            "events": [{
                "name": "남자 플러레 개인",
                "weapon": "플러레",
                "pool_rounds": [{"results": [{"name": "박진수", "team": "서울고등학교", "rank": 1}]}],
                "final_rankings": [{"name": "박진수", "team": "서울고등학교", "rank": 1}]
            }]
        }

        resolver.add_competition_data(data1)
        resolver.add_competition_data(data2)
        resolver.resolve_identities()

        # Should create 1 profile with team history
        assert "박진수" in resolver.name_to_profiles
        assert len(resolver.name_to_profiles["박진수"]) == 1
        assert not resolver.has_disambiguation("박진수")

        profile = resolver.get_players_by_name("박진수")[0]
        assert len(profile.team_history) == 2
        assert "서울중학교" in profile.teams
        assert "서울고등학교" in profile.teams

    def test_search_players(self, resolver, sample_competition_data):
        """Test player search functionality"""
        resolver.add_competition_data(sample_competition_data)
        resolver.resolve_identities()

        results = resolver.search_players("김")
        assert len(results) >= 1
        assert any(p.name == "김철수" for p in results)

        results = resolver.search_players("철수")
        assert len(results) == 1
        assert results[0].name == "김철수"

        results = resolver.search_players("없는선수")
        assert len(results) == 0

    def test_get_player_by_id(self, resolver, sample_competition_data):
        """Test getting player by ID"""
        resolver.add_competition_data(sample_competition_data)
        resolver.resolve_identities()

        profiles = resolver.get_players_by_name("김철수")
        player_id = profiles[0].player_id

        profile = resolver.get_player_by_id(player_id)
        assert profile is not None
        assert profile.name == "김철수"

        # Test invalid ID
        assert resolver.get_player_by_id("invalid_id") is None

    def test_to_dict_export(self, resolver, sample_competition_data):
        """Test exporting resolver state to dictionary"""
        resolver.add_competition_data(sample_competition_data)
        resolver.resolve_identities()

        export = resolver.to_dict()

        assert "profiles" in export
        assert "name_index" in export
        assert "ambiguous_names" in export
        assert len(export["profiles"]) > 0

    def test_weapon_tracking(self, resolver):
        """Test weapon tracking in profiles"""
        data = {
            "competition": {
                "event_cd": "COMP001",
                "name": "2023년 대회",
                "start_date": "2023-05-01"
            },
            "events": [
                {
                    "name": "남자 플러레",
                    "weapon": "플러레",
                    "pool_rounds": [{"results": [{"name": "테스트선수", "team": "A팀", "rank": 1}]}],
                    "final_rankings": []
                },
                {
                    "name": "남자 에뻬",
                    "weapon": "에뻬",
                    "pool_rounds": [{"results": [{"name": "테스트선수", "team": "A팀", "rank": 1}]}],
                    "final_rankings": []
                }
            ]
        }

        resolver.add_competition_data(data)
        resolver.resolve_identities()

        profile = resolver.get_players_by_name("테스트선수")[0]
        assert "플러레" in profile.weapons
        assert "에뻬" in profile.weapons

    def test_age_group_extraction(self, resolver):
        """Test age group extraction from event names"""
        data = {
            "competition": {
                "event_cd": "COMP001",
                "name": "2023년 대회",
                "start_date": "2023-05-01"
            },
            "events": [
                {
                    "name": "남자 플러레 중등부",
                    "weapon": "플러레",
                    "pool_rounds": [{"results": [{"name": "중등선수", "team": "A팀", "rank": 1}]}],
                    "final_rankings": []
                },
                {
                    "name": "남자 플러레 고등부",
                    "weapon": "플러레",
                    "pool_rounds": [{"results": [{"name": "고등선수", "team": "B팀", "rank": 1}]}],
                    "final_rankings": []
                }
            ]
        }

        resolver.add_competition_data(data)
        resolver.resolve_identities()

        profile1 = resolver.get_players_by_name("중등선수")[0]
        assert "중등부" in profile1.age_groups

        profile2 = resolver.get_players_by_name("고등선수")[0]
        assert "고등부" in profile2.age_groups

    def test_podium_tracking(self, resolver):
        """Test podium count tracking by season"""
        data = {
            "competition": {
                "event_cd": "COMP001",
                "name": "2023년 대회",
                "start_date": "2023-05-01"
            },
            "events": [{
                "name": "남자 플러레",
                "weapon": "플러레",
                "pool_rounds": [],
                "final_rankings": [
                    {"name": "금메달선수", "team": "A팀", "rank": 1},
                    {"name": "은메달선수", "team": "B팀", "rank": 2},
                    {"name": "동메달선수", "team": "C팀", "rank": 3},
                ]
            }]
        }

        resolver.add_competition_data(data)
        resolver.resolve_identities()

        gold = resolver.get_players_by_name("금메달선수")[0]
        assert gold.podium_by_season.get("2023", {}).get("gold", 0) == 1

        silver = resolver.get_players_by_name("은메달선수")[0]
        assert silver.podium_by_season.get("2023", {}).get("silver", 0) == 1

        bronze = resolver.get_players_by_name("동메달선수")[0]
        assert bronze.podium_by_season.get("2023", {}).get("bronze", 0) == 1


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling"""

    def test_empty_data(self):
        """Test handling empty data"""
        resolver = PlayerIdentityResolver()
        resolver.resolve_identities()

        assert len(resolver.profiles) == 0
        assert len(resolver.name_to_profiles) == 0

    def test_missing_fields(self):
        """Test handling missing fields in data"""
        resolver = PlayerIdentityResolver()
        data = {
            "competition": {
                "event_cd": "COMP001",
                # Missing name and start_date
            },
            "events": [{
                "name": "이벤트",
                # Missing weapon
                "pool_rounds": [{
                    "results": [{"name": "선수", "team": "팀"}]  # Missing rank
                }],
                "final_rankings": []
            }]
        }

        # Should not raise exception
        resolver.add_competition_data(data)
        resolver.resolve_identities()

        assert "선수" in resolver.name_to_profiles

    def test_empty_name_ignored(self):
        """Test that empty names are ignored"""
        resolver = PlayerIdentityResolver()
        data = {
            "competition": {
                "event_cd": "COMP001",
                "name": "대회",
                "start_date": "2023-01-01"
            },
            "events": [{
                "name": "이벤트",
                "weapon": "플러레",
                "pool_rounds": [{
                    "results": [
                        {"name": "", "team": "팀1", "rank": 1},
                        {"name": "-", "team": "팀2", "rank": 2},
                        {"name": "실제선수", "team": "팀3", "rank": 3},
                    ]
                }],
                "final_rankings": []
            }]
        }

        resolver.add_competition_data(data)
        resolver.resolve_identities()

        assert "" not in resolver.name_to_profiles
        assert "-" not in resolver.name_to_profiles
        assert "실제선수" in resolver.name_to_profiles

    def test_special_characters_in_name(self):
        """Test handling special characters in names"""
        resolver = PlayerIdentityResolver()
        data = {
            "competition": {
                "event_cd": "COMP001",
                "name": "대회",
                "start_date": "2023-01-01"
            },
            "events": [{
                "name": "이벤트",
                "weapon": "플러레",
                "pool_rounds": [{
                    "results": [
                        {"name": "김 선수", "team": "팀", "rank": 1},
                        {"name": "이(외국인)", "team": "팀", "rank": 2},
                    ]
                }],
                "final_rankings": []
            }]
        }

        resolver.add_competition_data(data)
        resolver.resolve_identities()

        assert "김 선수" in resolver.name_to_profiles
        assert "이(외국인)" in resolver.name_to_profiles


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests for complete workflows"""

    def test_full_workflow(self):
        """Test complete workflow from data ingestion to query"""
        resolver = PlayerIdentityResolver()

        # Add multiple competitions
        comp1 = {
            "competition": {
                "event_cd": "2023COMP1",
                "name": "2023년 1차 대회",
                "start_date": "2023-03-01"
            },
            "events": [{
                "name": "남자 플러레 중등부",
                "weapon": "플러레",
                "pool_rounds": [{
                    "results": [
                        {"name": "홍길동", "team": "서울중", "rank": 1},
                        {"name": "임꺽정", "team": "부산중", "rank": 2},
                    ]
                }],
                "final_rankings": [
                    {"name": "홍길동", "team": "서울중", "rank": 1},
                    {"name": "임꺽정", "team": "부산중", "rank": 2},
                ]
            }]
        }

        comp2 = {
            "competition": {
                "event_cd": "2023COMP2",
                "name": "2023년 2차 대회",
                "start_date": "2023-06-01"
            },
            "events": [{
                "name": "남자 플러레 중등부",
                "weapon": "플러레",
                "pool_rounds": [{
                    "results": [
                        {"name": "홍길동", "team": "서울중", "rank": 2},  # Same team
                        {"name": "임꺽정", "team": "대구중", "rank": 1},  # Team change
                    ]
                }],
                "final_rankings": [
                    {"name": "임꺽정", "team": "대구중", "rank": 1},
                    {"name": "홍길동", "team": "서울중", "rank": 2},
                ]
            }]
        }

        resolver.add_competition_data(comp1)
        resolver.add_competition_data(comp2)
        resolver.resolve_identities()

        # Test 홍길동 - same team throughout
        hong = resolver.get_players_by_name("홍길동")[0]
        assert hong.current_team == "서울중"
        assert len(hong.team_history) == 1
        assert len(hong.competition_ids) == 2

        # Test 임꺽정 - team change
        lim = resolver.get_players_by_name("임꺽정")[0]
        assert len(lim.team_history) == 2
        assert "부산중" in lim.teams
        assert "대구중" in lim.teams
        assert lim.current_team == "대구중"  # Most recent

        # Test search
        results = resolver.search_players("홍")
        assert len(results) == 1

        # Test export
        export = resolver.to_dict()
        assert len(export["profiles"]) == 2
        assert len(export["ambiguous_names"]) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
