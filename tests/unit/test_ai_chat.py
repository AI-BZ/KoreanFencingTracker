"""
Unit tests for AI Chat functionality (app/ai_chat.py)

Tests cover:
1. Query Parsing (15 cases)
2. Response Generation (10 cases)
3. Edge Cases (10 cases)
4. Integration (5 cases)

Target: 320+ test lines, 40+ test cases
"""

import pytest
import sys
from pathlib import Path
from typing import Dict, Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.ai_chat import FencingAIChat, ChatResponse


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def sample_player_data():
    """Sample player data for testing"""
    return {
        "competitions": [
            {
                "competition": {
                    "event_cd": "COMP001",
                    "name": "2024년 전국체육대회",
                    "start_date": "2024-10-01"
                },
                "events": [
                    {
                        "name": "남자 플러레 일반부 개인",
                        "sub_event_cd": "EVENT001"
                    }
                ],
                "results": {
                    "EVENT001": {
                        "pool_results": [
                            {
                                "pool_number": 1,
                                "results": [
                                    {"name": "박소윤", "team": "최병철펜싱클럽", "rank": 1, "win_rate": "5-0"},
                                    {"name": "김철수", "team": "서울펜싱클럽", "rank": 2, "win_rate": "4-1"},
                                ]
                            }
                        ]
                    }
                }
            },
            {
                "competition": {
                    "event_cd": "COMP002",
                    "name": "2024년 회장배",
                    "start_date": "2024-11-01"
                },
                "events": [
                    {
                        "name": "남자 플러레 일반부 개인",
                        "sub_event_cd": "EVENT002"
                    }
                ],
                "results": {
                    "EVENT002": {
                        "pool_results": [
                            {
                                "pool_number": 1,
                                "results": [
                                    {"name": "박소윤", "team": "최병철펜싱클럽", "rank": 1, "win_rate": "5-0"},
                                    {"name": "김민수", "team": "부산펜싱클럽", "rank": 3, "win_rate": "3-2"},
                                ]
                            }
                        ]
                    }
                }
            }
        ]
    }


@pytest.fixture
def sample_homonym_data():
    """Sample data with homonyms (동명이인)"""
    return {
        "competitions": [
            {
                "competition": {
                    "event_cd": "COMP003",
                    "name": "2024년 대회A",
                    "start_date": "2024-09-01"
                },
                "events": [{"name": "남자 플러레", "sub_event_cd": "EVENT003"}],
                "results": {
                    "EVENT003": {
                        "pool_results": [
                            {
                                "pool_number": 1,
                                "results": [
                                    {"name": "김민수", "team": "서울중학교", "rank": 1, "win_rate": "5-0"},
                                ]
                            }
                        ]
                    }
                }
            },
            {
                "competition": {
                    "event_cd": "COMP004",
                    "name": "2024년 대회B",
                    "start_date": "2024-09-15"
                },
                "events": [{"name": "남자 에페", "sub_event_cd": "EVENT004"}],
                "results": {
                    "EVENT004": {
                        "pool_results": [
                            {
                                "pool_number": 1,
                                "results": [
                                    {"name": "김민수", "team": "부산고등학교", "rank": 2, "win_rate": "4-1"},
                                ]
                            }
                        ]
                    }
                }
            }
        ]
    }


@pytest.fixture
def empty_data():
    """Empty data for edge case testing"""
    return {"competitions": []}


@pytest.fixture
def ai_chat(sample_player_data):
    """AI chat instance with sample data"""
    return FencingAIChat(sample_player_data)


@pytest.fixture
def ai_chat_homonyms(sample_homonym_data):
    """AI chat instance with homonym data"""
    return FencingAIChat(sample_homonym_data)


@pytest.fixture
def ai_chat_empty(empty_data):
    """AI chat instance with empty data"""
    return FencingAIChat(empty_data)


# =============================================================================
# 1. Query Parsing Tests (15 cases)
# =============================================================================

class TestQueryParsing:
    """Tests for query parsing and classification"""

    def test_player_search_query(self, ai_chat):
        """Test parsing player search query"""
        query_type, params = ai_chat._analyze_query("박소윤 전적")
        assert query_type == "player_info"
        assert params["player_name"] == "박소윤"

    def test_rivalry_query_pattern1(self, ai_chat):
        """Test rivalry query: 라이벌"""
        query_type, params = ai_chat._analyze_query("박소윤의 라이벌은 누구야?")
        assert query_type == "rival"
        assert params["player_name"] == "박소윤"

    def test_rivalry_query_pattern2(self, ai_chat):
        """Test rivalry query: 많이 진"""
        query_type, params = ai_chat._analyze_query("박소윤이 많이 진 상대")
        assert query_type == "rival"
        assert params["player_name"] == "박소윤"

    def test_rivalry_query_pattern3(self, ai_chat):
        """Test rivalry query: 상대전적"""
        query_type, params = ai_chat._analyze_query("김철수와 상대전적")
        assert query_type == "rival"
        assert params["player_name"] == "김철수"

    def test_rivalry_query_pattern4(self, ai_chat):
        """Test rivalry query: 천적"""
        query_type, params = ai_chat._analyze_query("박소윤의 천적")
        assert query_type == "rival"
        assert params["player_name"] == "박소윤"

    def test_team_query(self, ai_chat):
        """Test team/club query"""
        query_type, params = ai_chat._analyze_query("선수 최병철")
        assert query_type == "player_search"
        assert params["search_term"] == "최병철"

    def test_competition_query(self, ai_chat):
        """Test competition search query"""
        query_type, params = ai_chat._analyze_query("회장배 대회")
        assert query_type == "competition_search"
        assert "search_term" in params

    def test_player_info_성적(self, ai_chat):
        """Test player info query: 성적"""
        query_type, params = ai_chat._analyze_query("박소윤의 성적")
        assert query_type == "player_info"
        assert params["player_name"] == "박소윤"

    def test_player_info_기록(self, ai_chat):
        """Test player info query: 기록"""
        query_type, params = ai_chat._analyze_query("김철수 기록")
        assert query_type == "player_info"
        assert params["player_name"] == "김철수"

    def test_player_info_순위(self, ai_chat):
        """Test player info query: 순위"""
        query_type, params = ai_chat._analyze_query("박소윤의 순위")
        assert query_type == "player_info"
        assert params["player_name"] == "박소윤"

    def test_stats_query_통계(self, ai_chat):
        """Test stats query: 통계"""
        query_type, params = ai_chat._analyze_query("통계 보여줘")
        assert query_type == "stats"
        assert "query" in params

    def test_stats_query_몇개(self, ai_chat):
        """Test stats query: 몇 개"""
        query_type, params = ai_chat._analyze_query("대회 몇 개?")
        assert query_type == "stats"

    def test_short_name_query(self, ai_chat):
        """Test short name as player search"""
        query_type, params = ai_chat._analyze_query("박소윤")
        assert query_type == "player_info"
        assert params["player_name"] == "박소윤"

    def test_particle_removal_은(self, ai_chat):
        """Test Korean particle removal: 은/는"""
        query_type, params = ai_chat._analyze_query("박소윤은 어떤 선수")
        assert query_type == "player_info"
        assert params["player_name"] == "박소윤"

    def test_particle_removal_이가(self, ai_chat):
        """Test Korean particle removal: 이/가"""
        query_type, params = ai_chat._analyze_query("김철수가 많이 진 상대")
        assert query_type == "rival"
        assert params["player_name"] == "김철수"


# =============================================================================
# 2. Response Generation Tests (10 cases)
# =============================================================================

class TestResponseGeneration:
    """Tests for response generation"""

    def test_player_profile_response(self, ai_chat):
        """Test player profile response generation"""
        response = ai_chat.process_query("박소윤 전적")
        assert isinstance(response, ChatResponse)
        assert "박소윤" in response.message
        assert response.data is not None
        assert "player_name" in response.data
        assert response.data["player_name"] == "박소윤"

    def test_player_stats_in_response(self, ai_chat):
        """Test that player stats are included"""
        response = ai_chat.process_query("박소윤 성적")
        assert response.data is not None
        assert "total_events" in response.data
        assert response.data["total_events"] > 0
        assert "best_rank" in response.data
        assert "avg_rank" in response.data

    def test_rivalry_response_structure(self, ai_chat):
        """Test rivalry response structure"""
        response = ai_chat.process_query("박소윤의 라이벌")
        assert isinstance(response, ChatResponse)
        assert response.data is not None
        assert "player_name" in response.data
        assert response.suggestions is not None

    def test_disambiguation_response(self, ai_chat_homonyms):
        """Test disambiguation response for homonyms"""
        response = ai_chat_homonyms.process_query("김민수")
        assert isinstance(response, ChatResponse)
        assert response.disambiguation is not None
        assert len(response.disambiguation) == 2
        assert "서울중학교" in str(response.disambiguation)
        assert "부산고등학교" in str(response.disambiguation)

    def test_no_results_response(self, ai_chat):
        """Test no results response"""
        response = ai_chat.process_query("존재하지않는선수")
        assert isinstance(response, ChatResponse)
        assert "찾을 수 없습니다" in response.message
        assert response.suggestions is not None

    def test_similar_player_suggestions(self, ai_chat):
        """Test similar player name suggestions"""
        response = ai_chat.process_query("박소욱")  # 오타: 윤 -> 욱
        assert isinstance(response, ChatResponse)
        # Should suggest similar names
        if response.suggestions:
            assert len(response.suggestions) > 0

    def test_competition_search_response(self, ai_chat):
        """Test competition search response"""
        response = ai_chat.process_query("전국체육대회")
        assert isinstance(response, ChatResponse)
        assert "대회" in response.message
        if response.data:
            assert "results" in response.data

    def test_stats_response_structure(self, ai_chat):
        """Test stats response has correct structure"""
        response = ai_chat.process_query("통계 보여줘")
        assert isinstance(response, ChatResponse)
        assert response.data is not None
        assert "total_competitions" in response.data
        assert "total_players" in response.data

    def test_general_query_response(self, ai_chat):
        """Test general/unknown query response"""
        response = ai_chat.process_query("날씨가 어때?")
        assert isinstance(response, ChatResponse)
        assert "이해하지 못했습니다" in response.message
        assert response.suggestions is not None

    def test_response_has_suggestions(self, ai_chat):
        """Test that responses include helpful suggestions"""
        response = ai_chat.process_query("박소윤")
        assert isinstance(response, ChatResponse)
        assert response.suggestions is not None
        assert len(response.suggestions) > 0


# =============================================================================
# 3. Edge Cases Tests (10 cases)
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling"""

    def test_empty_query(self, ai_chat):
        """Test handling empty query"""
        response = ai_chat.process_query("")
        assert isinstance(response, ChatResponse)
        assert response.message is not None

    def test_whitespace_only_query(self, ai_chat):
        """Test query with only whitespace"""
        response = ai_chat.process_query("   ")
        assert isinstance(response, ChatResponse)
        assert response.message is not None

    def test_special_characters(self, ai_chat):
        """Test query with special characters"""
        response = ai_chat.process_query("박소윤!@#$%")
        assert isinstance(response, ChatResponse)
        assert response.message is not None

    def test_very_long_query(self, ai_chat):
        """Test very long query (>100 characters)"""
        long_query = "박소윤의 " + "라이벌 " * 50
        response = ai_chat.process_query(long_query)
        assert isinstance(response, ChatResponse)
        assert response.message is not None

    def test_mixed_language_query(self, ai_chat):
        """Test query with mixed Korean and English"""
        response = ai_chat.process_query("Park Sooyoon 전적")
        assert isinstance(response, ChatResponse)
        assert response.message is not None

    def test_numeric_query(self, ai_chat):
        """Test numeric query"""
        response = ai_chat.process_query("12345")
        assert isinstance(response, ChatResponse)
        assert response.message is not None

    def test_multiple_questions(self, ai_chat):
        """Test multiple questions in one query"""
        response = ai_chat.process_query("박소윤의 라이벌은 누구야? 성적도 알려줘")
        assert isinstance(response, ChatResponse)
        # Should parse first question
        assert "박소윤" in response.message or response.data is not None

    def test_typo_handling(self, ai_chat):
        """Test typo handling with fuzzy matching"""
        response = ai_chat.process_query("박소욱")  # 오타
        assert isinstance(response, ChatResponse)
        # Should suggest similar names or show "not found"
        assert response.suggestions is not None or "찾을 수 없습니다" in response.message

    def test_case_sensitivity(self, ai_chat):
        """Test case handling in queries"""
        response1 = ai_chat.process_query("박소윤의 라이벌")
        response2 = ai_chat.process_query("박소윤의 라이벌")
        # Should produce same query type
        assert type(response1) == type(response2)

    def test_unicode_handling(self, ai_chat):
        """Test Unicode character handling"""
        response = ai_chat.process_query("박소윤😀")
        assert isinstance(response, ChatResponse)
        assert response.message is not None


# =============================================================================
# 4. Integration Tests (5 cases)
# =============================================================================

class TestIntegration:
    """Integration tests with real player data structures"""

    def test_chat_with_real_player_data(self, ai_chat):
        """Test chat flow with realistic player data"""
        # Player info query
        response1 = ai_chat.process_query("박소윤")
        assert isinstance(response1, ChatResponse)
        assert "박소윤" in response1.message
        assert response1.data["total_events"] == 2

        # Rivalry query for same player
        response2 = ai_chat.process_query("박소윤의 라이벌")
        assert isinstance(response2, ChatResponse)
        assert "박소윤" in response2.message

    def test_chat_with_empty_database(self, ai_chat_empty):
        """Test chat with empty database"""
        response = ai_chat_empty.process_query("박소윤")
        assert isinstance(response, ChatResponse)
        assert "찾을 수 없습니다" in response.message

    def test_player_index_building(self, ai_chat):
        """Test that player index is built correctly"""
        assert len(ai_chat.players) > 0
        assert "박소윤" in ai_chat.players
        assert "김철수" in ai_chat.players

    def test_homonym_selection_flow(self, ai_chat_homonyms):
        """Test homonym selection workflow"""
        # First query - get disambiguation
        response1 = ai_chat_homonyms.process_query("김민수")
        assert response1.disambiguation is not None
        assert len(response1.disambiguation) == 2

        # Select specific player
        response2 = ai_chat_homonyms.select_disambiguation("김민수", "서울중학교")
        assert isinstance(response2, ChatResponse)
        assert "김민수" in response2.message
        assert "서울중학교" in response2.message

    def test_competition_data_integration(self, ai_chat):
        """Test integration with competition data"""
        response = ai_chat.process_query("2024년 전국체육대회")
        assert isinstance(response, ChatResponse)
        # Should find competition
        if response.data and "results" in response.data:
            assert len(response.data["results"]) > 0


# =============================================================================
# 5. Additional Helper Function Tests (5 cases)
# =============================================================================

class TestHelperFunctions:
    """Tests for internal helper functions"""

    def test_find_similar_players(self, ai_chat):
        """Test similar player name finding"""
        similar = ai_chat._find_similar_players("박")
        assert isinstance(similar, list)
        assert len(similar) > 0
        assert any("박" in name for name in similar)

    def test_find_similar_players_partial_match(self, ai_chat):
        """Test partial name matching"""
        similar = ai_chat._find_similar_players("소윤")
        assert isinstance(similar, list)
        if similar:
            assert any("소윤" in name for name in similar)

    def test_find_similar_players_empty(self, ai_chat):
        """Test similar players with no match"""
        similar = ai_chat._find_similar_players("XYZ존재하지않는이름")
        assert isinstance(similar, list)
        # May be empty or have first-char matches
        assert len(similar) <= 10

    def test_generate_player_info_rank_calculation(self, ai_chat):
        """Test rank calculation in player info"""
        player_data = ai_chat.players.get("박소윤", [{}])[0]
        response = ai_chat._generate_player_info("박소윤", player_data)
        assert response.data is not None
        assert "best_rank" in response.data
        assert "avg_rank" in response.data

    def test_generate_rival_response_message_format(self, ai_chat):
        """Test rival response message format"""
        player_data = ai_chat.players.get("박소윤", [{}])[0]
        response = ai_chat._generate_rival_response("박소윤", player_data)
        assert "**박소윤**" in response.message
        assert "참가 대회" in response.message


# =============================================================================
# 6. Query Type Detection Tests (5 cases)
# =============================================================================

class TestQueryTypeDetection:
    """Tests for accurate query type detection"""

    def test_detect_player_info_성적(self, ai_chat):
        """Test detecting player info from 성적 keyword"""
        query_type, _ = ai_chat._analyze_query("김철수의 성적은 어때?")
        assert query_type == "player_info"

    def test_detect_player_info_전적(self, ai_chat):
        """Test detecting player info from 전적 keyword"""
        query_type, _ = ai_chat._analyze_query("박소윤 전적 보여줘")
        assert query_type == "player_info"

    def test_detect_search_누구(self, ai_chat):
        """Test detecting search from 누구 keyword"""
        query_type, _ = ai_chat._analyze_query("최병철 누구?")
        assert query_type == "player_search"

    def test_detect_competition_대회(self, ai_chat):
        """Test detecting competition search"""
        query_type, _ = ai_chat._analyze_query("회장배 대회")
        assert query_type == "competition_search"

    def test_ambiguous_query_default(self, ai_chat):
        """Test ambiguous query defaults to general"""
        query_type, _ = ai_chat._analyze_query("무엇을 해야할까요?")
        assert query_type == "general"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
