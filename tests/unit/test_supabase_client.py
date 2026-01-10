"""
Unit tests for database/supabase_client.py

Tests cover:
1. Connection Tests (5 cases)
2. Query Tests (5 cases)
3. Error Handling (5 cases)
4. Additional Coverage (5 cases)

Total: 20+ test cases with 150+ test lines
"""

import pytest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from datetime import date, datetime
from typing import Dict, Any

from database.supabase_client import SupabaseDB, get_supabase_client
from scraper.models import Competition, Event, Player, Match, Ranking
from scraper.models import CompetitionStatus, Weapon, Gender, MatchStatus


# ==================== Fixtures ====================

@pytest.fixture
def mock_supabase_config():
    """Mock Supabase configuration"""
    with patch("database.supabase_client.supabase_config") as mock_config:
        mock_config.supabase_url = "https://test.supabase.co"
        mock_config.supabase_key = "test_key_123"
        yield mock_config


@pytest.fixture
def mock_supabase_client():
    """Mock Supabase client with table methods"""
    client = MagicMock()

    # Mock table() method to return a chainable query builder
    table_mock = MagicMock()
    client.table.return_value = table_mock

    # Mock query methods (upsert, insert, select, eq, execute)
    table_mock.upsert.return_value = table_mock
    table_mock.insert.return_value = table_mock
    table_mock.select.return_value = table_mock
    table_mock.eq.return_value = table_mock
    table_mock.update.return_value = table_mock
    table_mock.delete.return_value = table_mock

    # Default execute response
    execute_result = MagicMock()
    execute_result.data = [{"id": 1}]
    execute_result.count = 1
    table_mock.execute.return_value = execute_result

    return client


@pytest.fixture
def sample_competition():
    """Sample competition data"""
    return Competition(
        comp_idx="COMPM00668",
        comp_name="2024년 전국중고등학교펜싱선수권대회",
        start_date=date(2024, 7, 1),
        end_date=date(2024, 7, 5),
        venue="충주",
        status=CompetitionStatus.COMPLETED,
        raw_data={"source": "test"}
    )


@pytest.fixture
def sample_event():
    """Sample event data"""
    return Event(
        event_cd="EVENT001",
        sub_event_cd="SUB001",
        event_name="남자 플뢰레 개인전",
        weapon=Weapon.FOIL,
        gender=Gender.MALE,
        category="개인전",
        age_group="일반부",
        raw_data={"source": "test"}
    )


@pytest.fixture
def sample_player():
    """Sample player data"""
    return Player(
        player_name="김철수",
        team_name="서울중학교",
        birth_year=2008,
        nationality="KOR",
        raw_data={"source": "test"}
    )


@pytest.fixture
def sample_match():
    """Sample match data"""
    return Match(
        round_name="8강",
        group_name="A조",
        match_number=1,
        player1_name="김철수",
        player1_score=15,
        player2_name="이영희",
        player2_score=10,
        match_status=MatchStatus.VICTORY,
        raw_data={"source": "test"}
    )


@pytest.fixture
def sample_ranking():
    """Sample ranking data"""
    return Ranking(
        player_name="김철수",
        team_name="서울중학교",
        rank_position=1,
        match_count=5,
        win_count=4,
        loss_count=1,
        points=20,
        raw_data={"source": "test"}
    )


# ==================== Connection Tests (5 cases) ====================

class TestConnection:
    """Connection-related tests"""

    def test_successful_connection_with_valid_credentials(self, mock_supabase_config):
        """Test successful connection with valid credentials"""
        with patch("database.supabase_client.create_client") as mock_create:
            mock_create.return_value = MagicMock()

            db = SupabaseDB()

            assert db.client is not None
            mock_create.assert_called_once_with(
                "https://test.supabase.co",
                "test_key_123"
            )

    def test_connection_failure_with_invalid_credentials(self):
        """Test connection failure with missing credentials"""
        with patch("database.supabase_client.supabase_config") as mock_config:
            mock_config.supabase_url = ""
            mock_config.supabase_key = ""

            with pytest.raises(ValueError) as exc_info:
                SupabaseDB()

            assert "SUPABASE_URL과 SUPABASE_KEY" in str(exc_info.value)

    def test_singleton_get_supabase_client(self, mock_supabase_config):
        """Test singleton pattern for get_supabase_client"""
        with patch("database.supabase_client.create_client") as mock_create:
            mock_create.return_value = MagicMock()

            # Reset singleton
            import database.supabase_client
            database.supabase_client._supabase_client = None

            # First call creates client
            client1 = get_supabase_client()
            # Second call returns same instance
            client2 = get_supabase_client()

            assert client1 is client2
            assert mock_create.call_count == 1

    def test_singleton_client_raises_on_missing_config(self):
        """Test singleton client raises error with missing config"""
        with patch("database.supabase_client.supabase_config") as mock_config:
            mock_config.supabase_url = None
            mock_config.supabase_key = None

            # Reset singleton
            import database.supabase_client
            database.supabase_client._supabase_client = None

            with pytest.raises(ValueError) as exc_info:
                get_supabase_client()

            assert "환경변수를 설정해주세요" in str(exc_info.value)

    def test_connection_timeout_handling(self, mock_supabase_config):
        """Test connection timeout handling"""
        with patch("database.supabase_client.create_client") as mock_create:
            mock_create.side_effect = TimeoutError("Connection timeout")

            with pytest.raises(TimeoutError):
                SupabaseDB()


# ==================== Query Tests (5 cases) ====================

class TestQueries:
    """Database query tests"""

    @pytest.mark.asyncio
    async def test_select_query_competitions(self, mock_supabase_config, mock_supabase_client):
        """Test SELECT query for competitions"""
        with patch("database.supabase_client.create_client", return_value=mock_supabase_client):
            db = SupabaseDB()

            # Mock response data
            mock_supabase_client.table().execute.return_value.data = [
                {"id": 1, "comp_idx": "COMP001", "status": "진행중"}
            ]

            result = await db.get_active_competitions()

            assert len(result) == 1
            assert result[0]["comp_idx"] == "COMP001"
            mock_supabase_client.table.assert_called_with("competitions")

    @pytest.mark.asyncio
    async def test_insert_query_competition(
        self, mock_supabase_config, mock_supabase_client, sample_competition
    ):
        """Test INSERT/UPSERT query for competition"""
        with patch("database.supabase_client.create_client", return_value=mock_supabase_client):
            db = SupabaseDB()

            # Mock upsert response
            mock_supabase_client.table().execute.return_value.data = [{"id": 100}]

            result = await db.upsert_competition(sample_competition)

            assert result == 100
            mock_supabase_client.table.assert_called_with("competitions")

    @pytest.mark.asyncio
    async def test_update_query_scrape_log(self, mock_supabase_config, mock_supabase_client):
        """Test UPDATE query for scrape logs"""
        with patch("database.supabase_client.create_client", return_value=mock_supabase_client):
            db = SupabaseDB()

            result = await db.update_scrape_log(
                log_id=1,
                status="completed",
                competitions_processed=10,
                events_processed=50,
                matches_processed=200
            )

            assert result is True
            mock_supabase_client.table.assert_called_with("scrape_logs")

    @pytest.mark.asyncio
    async def test_delete_query_event_matches(self, mock_supabase_config, mock_supabase_client):
        """Test DELETE query for event matches"""
        with patch("database.supabase_client.create_client", return_value=mock_supabase_client):
            db = SupabaseDB()

            result = await db.delete_event_matches(event_id=1)

            assert result is True
            mock_supabase_client.table.assert_called_with("matches")

    @pytest.mark.asyncio
    async def test_complex_join_query_with_filtering(
        self, mock_supabase_config, mock_supabase_client
    ):
        """Test complex query with multiple conditions"""
        with patch("database.supabase_client.create_client", return_value=mock_supabase_client):
            db = SupabaseDB()

            # Mock event_id lookup
            mock_supabase_client.table().execute.return_value.data = [{"id": 5}]

            event_id = await db.get_event_id(
                competition_id=1,
                event_cd="EVENT001",
                sub_event_cd="SUB001"
            )

            assert event_id == 5
            # Verify multiple eq() calls were chained
            assert mock_supabase_client.table().eq.call_count >= 2


# ==================== Error Handling Tests (5 cases) ====================

class TestErrorHandling:
    """Error handling tests"""

    @pytest.mark.asyncio
    async def test_network_error_handling(self, mock_supabase_config, mock_supabase_client):
        """Test network error handling"""
        with patch("database.supabase_client.create_client", return_value=mock_supabase_client):
            db = SupabaseDB()

            # Mock network error
            mock_supabase_client.table().execute.side_effect = ConnectionError("Network error")

            result = await db.get_active_competitions()

            assert result == []  # Should return empty list on error

    @pytest.mark.asyncio
    async def test_query_syntax_error(
        self, mock_supabase_config, mock_supabase_client, sample_competition
    ):
        """Test query syntax error handling"""
        with patch("database.supabase_client.create_client", return_value=mock_supabase_client):
            db = SupabaseDB()

            # Mock syntax error
            mock_supabase_client.table().execute.side_effect = Exception("Syntax error in query")

            result = await db.upsert_competition(sample_competition)

            assert result is None  # Should return None on error

    @pytest.mark.asyncio
    async def test_rate_limiting_error(self, mock_supabase_config, mock_supabase_client):
        """Test rate limiting error handling"""
        with patch("database.supabase_client.create_client", return_value=mock_supabase_client):
            db = SupabaseDB()

            # Mock rate limit error
            mock_supabase_client.table().execute.side_effect = Exception("Rate limit exceeded")

            result = await db.create_scrape_log(scrape_type="full", status="running")

            assert result is None

    @pytest.mark.asyncio
    async def test_timeout_error_on_stats(self, mock_supabase_config, mock_supabase_client):
        """Test timeout error on statistics query"""
        with patch("database.supabase_client.create_client", return_value=mock_supabase_client):
            db = SupabaseDB()

            # Mock timeout on one table
            def execute_side_effect(*args, **kwargs):
                raise TimeoutError("Query timeout")

            mock_supabase_client.table().execute.side_effect = execute_side_effect

            result = await db.get_stats()

            # Should return stats with 0 counts on error
            assert isinstance(result, dict)
            assert all(count == 0 for count in result.values())

    @pytest.mark.asyncio
    async def test_data_validation_error(
        self, mock_supabase_config, mock_supabase_client, sample_player
    ):
        """Test data validation error handling"""
        with patch("database.supabase_client.create_client", return_value=mock_supabase_client):
            db = SupabaseDB()

            # Mock validation error
            mock_supabase_client.table().execute.side_effect = ValueError("Invalid data format")

            result = await db.upsert_player(sample_player)

            assert result is None


# ==================== Additional Coverage Tests (5+ cases) ====================

class TestAdditionalCoverage:
    """Additional test coverage for comprehensive testing"""

    @pytest.mark.asyncio
    async def test_upsert_competitions_batch(
        self, mock_supabase_config, mock_supabase_client, sample_competition
    ):
        """Test batch upsert of multiple competitions"""
        with patch("database.supabase_client.create_client", return_value=mock_supabase_client):
            db = SupabaseDB()

            # Mock successful upserts
            mock_supabase_client.table().execute.return_value.data = [{"id": 1}]

            competitions = [sample_competition, sample_competition, sample_competition]
            success_count = await db.upsert_competitions(competitions)

            assert success_count == 3

    @pytest.mark.asyncio
    async def test_get_or_create_player_existing(
        self, mock_supabase_config, mock_supabase_client
    ):
        """Test get_or_create_player with existing player"""
        with patch("database.supabase_client.create_client", return_value=mock_supabase_client):
            db = SupabaseDB()

            # Mock existing player
            mock_supabase_client.table().execute.return_value.data = [{"id": 42}]

            player_id = await db.get_or_create_player("김철수", "서울중학교")

            assert player_id == 42

    @pytest.mark.asyncio
    async def test_get_or_create_player_new(
        self, mock_supabase_config, mock_supabase_client
    ):
        """Test get_or_create_player creating new player"""
        with patch("database.supabase_client.create_client", return_value=mock_supabase_client):
            db = SupabaseDB()

            # Mock no existing player, then creation
            execute_results = [
                MagicMock(data=[]),  # No existing player
                MagicMock(data=[{"id": 99}])  # New player created
            ]
            mock_supabase_client.table().execute.side_effect = execute_results

            player_id = await db.get_or_create_player("박민수", "부산중학교")

            assert player_id == 99

    @pytest.mark.asyncio
    async def test_upsert_event_with_competition_id(
        self, mock_supabase_config, mock_supabase_client, sample_event
    ):
        """Test event upsert with competition ID"""
        with patch("database.supabase_client.create_client", return_value=mock_supabase_client):
            db = SupabaseDB()

            mock_supabase_client.table().execute.return_value.data = [{"id": 10}]

            event_id = await db.upsert_event(sample_event, competition_id=1)

            assert event_id == 10

    @pytest.mark.asyncio
    async def test_upsert_match_with_winner_calculation(
        self, mock_supabase_config, mock_supabase_client, sample_match
    ):
        """Test match upsert with automatic winner calculation"""
        with patch("database.supabase_client.create_client", return_value=mock_supabase_client):
            db = SupabaseDB()

            # Mock player ID lookups
            execute_results = [
                MagicMock(data=[]),  # player1 doesn't exist
                MagicMock(data=[{"id": 1}]),  # player1 created
                MagicMock(data=[]),  # player2 doesn't exist
                MagicMock(data=[{"id": 2}]),  # player2 created
                MagicMock(data=[{"id": 100}])  # match inserted
            ]
            mock_supabase_client.table().execute.side_effect = execute_results

            match_id = await db.upsert_match(sample_match, event_id=1)

            assert match_id == 100

    @pytest.mark.asyncio
    async def test_upsert_ranking_with_player_creation(
        self, mock_supabase_config, mock_supabase_client, sample_ranking
    ):
        """Test ranking upsert with player creation"""
        with patch("database.supabase_client.create_client", return_value=mock_supabase_client):
            db = SupabaseDB()

            # Mock player creation and ranking upsert
            execute_results = [
                MagicMock(data=[]),  # player doesn't exist
                MagicMock(data=[{"id": 50}]),  # player created
                MagicMock(data=[{"id": 200}])  # ranking created
            ]
            mock_supabase_client.table().execute.side_effect = execute_results

            ranking_id = await db.upsert_ranking(sample_ranking, event_id=1)

            assert ranking_id == 200

    @pytest.mark.asyncio
    async def test_get_competition_id_not_found(
        self, mock_supabase_config, mock_supabase_client
    ):
        """Test get_competition_id when competition not found"""
        with patch("database.supabase_client.create_client", return_value=mock_supabase_client):
            db = SupabaseDB()

            # Mock empty result
            mock_supabase_client.table().execute.return_value.data = []

            comp_id = await db.get_competition_id("NONEXISTENT")

            assert comp_id is None

    @pytest.mark.asyncio
    async def test_get_stats_all_tables(self, mock_supabase_config, mock_supabase_client):
        """Test statistics query for all tables"""
        with patch("database.supabase_client.create_client", return_value=mock_supabase_client):
            db = SupabaseDB()

            # Mock different counts for each table
            counts = [100, 500, 1000, 5000, 200]
            execute_results = [
                MagicMock(data=[], count=count) for count in counts
            ]
            mock_supabase_client.table().execute.side_effect = execute_results

            stats = await db.get_stats()

            assert stats["competitions"] == 100
            assert stats["events"] == 500
            assert stats["players"] == 1000
            assert stats["matches"] == 5000
            assert stats["rankings"] == 200

    @pytest.mark.asyncio
    async def test_create_scrape_log_success(self, mock_supabase_config, mock_supabase_client):
        """Test successful scrape log creation"""
        with patch("database.supabase_client.create_client", return_value=mock_supabase_client):
            db = SupabaseDB()

            mock_supabase_client.table().execute.return_value.data = [{"id": 1}]

            log_id = await db.create_scrape_log(scrape_type="incremental", status="running")

            assert log_id == 1

    @pytest.mark.asyncio
    async def test_update_scrape_log_with_error_message(
        self, mock_supabase_config, mock_supabase_client
    ):
        """Test scrape log update with error message"""
        with patch("database.supabase_client.create_client", return_value=mock_supabase_client):
            db = SupabaseDB()

            result = await db.update_scrape_log(
                log_id=1,
                status="failed",
                error_message="Connection timeout during scraping"
            )

            assert result is True

    @pytest.mark.asyncio
    async def test_delete_event_matches_failure(
        self, mock_supabase_config, mock_supabase_client
    ):
        """Test delete event matches with failure"""
        with patch("database.supabase_client.create_client", return_value=mock_supabase_client):
            db = SupabaseDB()

            # Mock delete failure
            mock_supabase_client.table().execute.side_effect = Exception("Delete failed")

            result = await db.delete_event_matches(event_id=999)

            assert result is False

    @pytest.mark.asyncio
    async def test_get_event_id_with_optional_sub_event(
        self, mock_supabase_config, mock_supabase_client
    ):
        """Test get_event_id with optional sub_event_cd"""
        with patch("database.supabase_client.create_client", return_value=mock_supabase_client):
            db = SupabaseDB()

            # Mock event found
            mock_supabase_client.table().execute.return_value.data = [{"id": 15}]

            # Test with sub_event_cd
            event_id = await db.get_event_id(
                competition_id=1,
                event_cd="EVENT001",
                sub_event_cd="SUB001"
            )
            assert event_id == 15

            # Test without sub_event_cd (empty string)
            event_id = await db.get_event_id(
                competition_id=1,
                event_cd="EVENT001",
                sub_event_cd=""
            )
            assert event_id == 15

    @pytest.mark.asyncio
    async def test_upsert_match_without_scores(
        self, mock_supabase_config, mock_supabase_client
    ):
        """Test match upsert without scores (no winner)"""
        with patch("database.supabase_client.create_client", return_value=mock_supabase_client):
            db = SupabaseDB()

            # Create match without scores
            match = Match(
                round_name="예선",
                player1_name="선수A",
                player2_name="선수B",
                match_status=MatchStatus.UNKNOWN
            )

            # Mock player creation
            execute_results = [
                MagicMock(data=[]),
                MagicMock(data=[{"id": 1}]),
                MagicMock(data=[]),
                MagicMock(data=[{"id": 2}]),
                MagicMock(data=[{"id": 99}])
            ]
            mock_supabase_client.table().execute.side_effect = execute_results

            match_id = await db.upsert_match(match, event_id=1)

            assert match_id == 99
