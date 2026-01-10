"""
Club Player Data Integration Tests

선수 데이터 연동 테스트
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, date

from app.club.players.service import PlayerService


class TestPlayerSearch:
    """선수 검색 테스트"""

    @pytest.mark.asyncio
    async def test_search_by_name(self):
        """이름으로 선수 검색"""
        service = PlayerService()

        mock_supabase = MagicMock()
        search_response = MagicMock()
        search_response.data = [
            {
                "id": 1,
                "name": "박소윤",
                "team": "최병철펜싱클럽",
                "weapon": "foil",
                "birth_year": 2010,
            }
        ]

        mock_supabase.table = MagicMock(return_value=mock_supabase)
        mock_supabase.select = MagicMock(return_value=mock_supabase)
        mock_supabase.or_ = MagicMock(return_value=mock_supabase)
        mock_supabase.limit = MagicMock(return_value=mock_supabase)
        mock_supabase.execute = MagicMock(return_value=search_response)

        # Mocking dependencies
        with patch.object(service, "supabase", mock_supabase):
            with patch.object(service, "_get_competition_count", AsyncMock(return_value=15)):
                with patch.object(service, "_check_player_linked", AsyncMock(return_value=False)):
                    results = await service.search_players("박소윤")

                    assert len(results) == 1
                    assert results[0]["name"] == "박소윤"
                    assert results[0]["competition_count"] == 15
                    assert results[0]["is_linked"] is False

    @pytest.mark.asyncio
    async def test_search_with_weapon_filter(self):
        """무기 필터링 검색"""
        service = PlayerService()

        mock_supabase = MagicMock()
        search_response = MagicMock()
        search_response.data = [
            {
                "id": 1,
                "name": "박소윤",
                "team": "최병철펜싱클럽",
                "weapon": "foil",
                "birth_year": 2010,
            }
        ]

        mock_supabase.table = MagicMock(return_value=mock_supabase)
        mock_supabase.select = MagicMock(return_value=mock_supabase)
        mock_supabase.or_ = MagicMock(return_value=mock_supabase)
        mock_supabase.eq = MagicMock(return_value=mock_supabase)
        mock_supabase.limit = MagicMock(return_value=mock_supabase)
        mock_supabase.execute = MagicMock(return_value=search_response)

        with patch.object(service, "supabase", mock_supabase):
            with patch.object(service, "_get_competition_count", AsyncMock(return_value=15)):
                with patch.object(service, "_check_player_linked", AsyncMock(return_value=False)):
                    results = await service.search_players("박소윤", weapon="foil")

                    assert len(results) == 1
                    assert results[0]["weapon"] == "foil"


class TestPlayerLinking:
    """회원-선수 연결 테스트"""

    @pytest.mark.asyncio
    async def test_link_player_success(self, test_organization_id):
        """선수 연결 성공"""
        service = PlayerService()

        member_id = "member123"
        player_id = 1

        mock_supabase = MagicMock()

        # Member 확인
        member_response = MagicMock()
        member_response.data = {
            "id": member_id,
            "organization_id": test_organization_id,
        }

        # Update 성공
        update_response = MagicMock()
        update_response.data = [{"id": member_id}]

        mock_supabase.table = MagicMock(return_value=mock_supabase)
        mock_supabase.select = MagicMock(return_value=mock_supabase)
        mock_supabase.eq = MagicMock(return_value=mock_supabase)
        mock_supabase.single = MagicMock(return_value=mock_supabase)
        mock_supabase.update = MagicMock(return_value=mock_supabase)

        execute_calls = [member_response, update_response]
        mock_supabase.execute = MagicMock(side_effect=execute_calls)

        with patch.object(service, "supabase", mock_supabase):
            result = await service.link_player_to_member(
                member_id, player_id, test_organization_id
            )

            assert result is True

    @pytest.mark.asyncio
    async def test_link_player_member_not_found(self, test_organization_id):
        """회원을 찾을 수 없음"""
        service = PlayerService()

        mock_supabase = MagicMock()
        member_response = MagicMock()
        member_response.data = None

        mock_supabase.table = MagicMock(return_value=mock_supabase)
        mock_supabase.select = MagicMock(return_value=mock_supabase)
        mock_supabase.eq = MagicMock(return_value=mock_supabase)
        mock_supabase.single = MagicMock(return_value=mock_supabase)
        mock_supabase.execute = MagicMock(return_value=member_response)

        with patch.object(service, "supabase", mock_supabase):
            with pytest.raises(ValueError, match="회원을 찾을 수 없습니다"):
                await service.link_player_to_member("member123", 1, test_organization_id)

    @pytest.mark.asyncio
    async def test_link_player_wrong_organization(self, test_organization_id):
        """다른 조직의 회원"""
        service = PlayerService()

        mock_supabase = MagicMock()
        member_response = MagicMock()
        member_response.data = {
            "id": "member123",
            "organization_id": test_organization_id + 1,  # 다른 조직
        }

        mock_supabase.table = MagicMock(return_value=mock_supabase)
        mock_supabase.select = MagicMock(return_value=mock_supabase)
        mock_supabase.eq = MagicMock(return_value=mock_supabase)
        mock_supabase.single = MagicMock(return_value=mock_supabase)
        mock_supabase.execute = MagicMock(return_value=member_response)

        with patch.object(service, "supabase", mock_supabase):
            with pytest.raises(ValueError, match="다른 조직의 회원입니다"):
                await service.link_player_to_member("member123", 1, test_organization_id)


class TestPlayerProfile:
    """선수 프로필 테스트"""

    @pytest.mark.asyncio
    async def test_get_player_profile_success(self, player_profile_data):
        """선수 프로필 조회 성공"""
        service = PlayerService()

        mock_supabase = MagicMock()
        player_response = MagicMock()
        player_response.data = {
            "id": 1,
            "name": "박소윤",
            "team": "최병철펜싱클럽",
            "weapon": "foil",
            "birth_year": 2010,
            "nationality": "KOR",
        }

        mock_supabase.table = MagicMock(return_value=mock_supabase)
        mock_supabase.select = MagicMock(return_value=mock_supabase)
        mock_supabase.eq = MagicMock(return_value=mock_supabase)
        mock_supabase.single = MagicMock(return_value=mock_supabase)
        mock_supabase.execute = MagicMock(return_value=player_response)

        # Mock stats and medals
        stats_data = {
            "total_competitions": 15,
            "total_events": 20,
            "pool_total_bouts": 100,
            "pool_wins": 75,
        }

        medals_data = {"gold": 3, "silver": 5, "bronze": 7}
        rankings_data = [
            {"weapon": "foil", "gender": "female", "age_group": "중등부", "rank": 5}
        ]

        with patch.object(service, "supabase", mock_supabase):
            with patch.object(service, "get_player_stats", AsyncMock(return_value=stats_data)):
                with patch.object(service, "_get_medal_counts", AsyncMock(return_value=medals_data)):
                    with patch.object(service, "_get_current_rankings", AsyncMock(return_value=rankings_data)):
                        profile = await service.get_player_profile(1)

                        assert profile["player_id"] == 1
                        assert profile["name"] == "박소윤"
                        assert profile["gold_medals"] == 3
                        assert profile["total_competitions"] == 15

    @pytest.mark.asyncio
    async def test_get_player_profile_not_found(self):
        """선수를 찾을 수 없음"""
        service = PlayerService()

        mock_supabase = MagicMock()
        player_response = MagicMock()
        player_response.data = None

        mock_supabase.table = MagicMock(return_value=mock_supabase)
        mock_supabase.select = MagicMock(return_value=mock_supabase)
        mock_supabase.eq = MagicMock(return_value=mock_supabase)
        mock_supabase.single = MagicMock(return_value=mock_supabase)
        mock_supabase.execute = MagicMock(return_value=player_response)

        with patch.object(service, "supabase", mock_supabase):
            profile = await service.get_player_profile(999)

            assert profile is None


class TestPlayerStats:
    """선수 통계 테스트"""

    @pytest.mark.asyncio
    async def test_calculate_pool_stats(self):
        """Pool 통계 계산"""
        service = PlayerService()

        mock_supabase = MagicMock()
        matches_response = MagicMock()
        matches_response.data = [
            {
                "player1_id": 1,
                "player2_id": 2,
                "player1_score": 5,
                "player2_score": 3,
                "bout_type": "pool",
            },
            {
                "player1_id": 1,
                "player2_id": 3,
                "player1_score": 5,
                "player2_score": 2,
                "bout_type": "pool",
            },
            {
                "player1_id": 4,
                "player2_id": 1,
                "player1_score": 3,
                "player2_score": 5,
                "bout_type": "pool",
            },
        ]

        mock_supabase.table = MagicMock(return_value=mock_supabase)
        mock_supabase.select = MagicMock(return_value=mock_supabase)
        mock_supabase.eq = MagicMock(return_value=mock_supabase)
        mock_supabase.or_ = MagicMock(return_value=mock_supabase)
        mock_supabase.execute = MagicMock(return_value=matches_response)

        with patch.object(service, "supabase", mock_supabase):
            stats = await service._calculate_pool_stats(1)

            assert stats["pool_total_bouts"] == 3
            assert stats["pool_wins"] == 3
            assert stats["pool_losses"] == 0
            assert stats["pool_win_rate"] == 100.0
            assert stats["pool_touches_scored"] == 15  # 5+5+5
            assert stats["pool_touches_received"] == 8  # 3+2+3
            assert stats["pool_indicator"] == 7  # 15-8


class TestHeadToHead:
    """상대 전적 테스트"""

    @pytest.mark.asyncio
    async def test_head_to_head_success(self):
        """상대 전적 조회 성공"""
        service = PlayerService()

        mock_supabase = MagicMock()

        # 상대 정보
        opponent_response = MagicMock()
        opponent_response.data = {
            "id": 2,
            "name": "김학생",
            "team": "다른클럽",
        }

        # 대결 기록
        matches_response = MagicMock()
        matches_response.data = [
            {
                "event_id": 1,
                "bout_type": "pool",
                "round_name": "Pool 1",
                "player1_id": 1,
                "player2_id": 2,
                "player1_score": 5,
                "player2_score": 3,
            },
            {
                "event_id": 2,
                "bout_type": "de",
                "round_name": "16강",
                "player1_id": 2,
                "player2_id": 1,
                "player1_score": 15,
                "player2_score": 10,
            },
        ]

        mock_supabase.table = MagicMock(return_value=mock_supabase)
        mock_supabase.select = MagicMock(return_value=mock_supabase)
        mock_supabase.eq = MagicMock(return_value=mock_supabase)
        mock_supabase.or_ = MagicMock(return_value=mock_supabase)
        mock_supabase.single = MagicMock(return_value=mock_supabase)

        execute_calls = [opponent_response, matches_response]
        mock_supabase.execute = MagicMock(side_effect=execute_calls)

        # Mock event info
        event_info = {
            "event_name": "남자 플러레 중등부",
            "competition_name": "2024 회장배",
            "competition_date": "2024-07-01",
        }

        with patch.object(service, "supabase", mock_supabase):
            with patch.object(service, "_get_event_info", AsyncMock(return_value=event_info)):
                h2h = await service.get_head_to_head(1, 2)

                assert h2h["opponent_id"] == 2
                assert h2h["opponent_name"] == "김학생"
                assert h2h["total_bouts"] == 2
                assert h2h["wins"] == 1
                assert h2h["losses"] == 1
                assert h2h["win_rate"] == 50.0

    @pytest.mark.asyncio
    async def test_head_to_head_opponent_not_found(self):
        """상대를 찾을 수 없음"""
        service = PlayerService()

        mock_supabase = MagicMock()
        opponent_response = MagicMock()
        opponent_response.data = None

        mock_supabase.table = MagicMock(return_value=mock_supabase)
        mock_supabase.select = MagicMock(return_value=mock_supabase)
        mock_supabase.eq = MagicMock(return_value=mock_supabase)
        mock_supabase.single = MagicMock(return_value=mock_supabase)
        mock_supabase.execute = MagicMock(return_value=opponent_response)

        with patch.object(service, "supabase", mock_supabase):
            with pytest.raises(ValueError, match="상대 선수를 찾을 수 없습니다"):
                await service.get_head_to_head(1, 999)


class TestTeamRoster:
    """팀 로스터 테스트"""

    @pytest.mark.asyncio
    async def test_get_team_roster_success(self, test_organization_id, test_organization_name):
        """팀 로스터 조회 성공"""
        service = PlayerService()

        mock_supabase = MagicMock()

        # 조직 정보
        org_response = MagicMock()
        org_response.data = {
            "id": test_organization_id,
            "name": test_organization_name,
        }

        # 회원 목록 (학생만)
        members_response = MagicMock()
        members_response.data = [
            {
                "id": "member1",
                "full_name": "박소윤",
                "club_role": "student",
                "member_status": "active",
                "player_id": 1,
            },
            {
                "id": "member2",
                "full_name": "김학생",
                "club_role": "student",
                "member_status": "active",
                "player_id": None,
            },
            {
                "id": "member3",
                "full_name": "김코치",
                "club_role": "coach",  # 코치는 제외
                "member_status": "active",
                "player_id": None,
            },
        ]

        mock_supabase.table = MagicMock(return_value=mock_supabase)
        mock_supabase.select = MagicMock(return_value=mock_supabase)
        mock_supabase.eq = MagicMock(return_value=mock_supabase)
        mock_supabase.in_ = MagicMock(return_value=mock_supabase)
        mock_supabase.single = MagicMock(return_value=mock_supabase)

        execute_calls = [org_response, members_response]
        mock_supabase.execute = MagicMock(side_effect=execute_calls)

        with patch.object(service, "supabase", mock_supabase):
            # httpx 호출 Mock
            with patch("httpx.AsyncClient") as mock_client:
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json = MagicMock(return_value={"results": []})

                mock_client_instance = AsyncMock()
                mock_client_instance.get = AsyncMock(return_value=mock_response)
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=None)
                mock_client.return_value = mock_client_instance

                roster = await service.get_team_roster(test_organization_id)

                assert roster["organization_id"] == test_organization_id
                assert roster["total_members"] == 2  # 학생만 (코치 제외)
                assert len(roster["players"]) == 2  # 학생만 포함


class TestCompetitionHistory:
    """대회 히스토리 테스트"""

    @pytest.mark.asyncio
    async def test_get_competition_history(self):
        """대회 출전 히스토리 조회"""
        service = PlayerService()

        mock_supabase = MagicMock()

        # 참가한 종목
        matches_response = MagicMock()
        matches_response.data = [
            {"event_id": 1},
            {"event_id": 1},
            {"event_id": 2},
        ]

        # 종목 정보
        events_response = MagicMock()
        events_response.data = [
            {
                "id": 1,
                "competition_id": 100,
                "name": "남자 플러레 중등부",
                "weapon": "foil",
            },
            {
                "id": 2,
                "competition_id": 101,
                "name": "남자 플러레 고등부",
                "weapon": "foil",
            },
        ]

        # 대회 정보
        comps_response = MagicMock()
        comps_response.data = [
            {
                "id": 100,
                "name": "2024 회장배",
                "start_date": "2024-07-01",
            },
            {
                "id": 101,
                "name": "2024 전국체전",
                "start_date": "2024-10-01",
            },
        ]

        mock_supabase.table = MagicMock(return_value=mock_supabase)
        mock_supabase.select = MagicMock(return_value=mock_supabase)
        mock_supabase.or_ = MagicMock(return_value=mock_supabase)
        mock_supabase.in_ = MagicMock(return_value=mock_supabase)

        execute_calls = [matches_response, events_response, comps_response]
        mock_supabase.execute = MagicMock(side_effect=execute_calls)

        # Mock event performance and final rank
        event_stats = {
            "pool_wins": 5,
            "pool_losses": 0,
            "de_rounds_won": 2,
        }

        with patch.object(service, "supabase", mock_supabase):
            with patch.object(service, "_get_event_performance", AsyncMock(return_value=event_stats)):
                with patch.object(service, "_get_final_rank", AsyncMock(return_value=3)):
                    history = await service.get_competition_history(1)

                    assert len(history) == 2
                    assert history[0]["competition_name"] == "2024 전국체전"  # 최근순
                    assert history[0]["pool_wins"] == 5


class TestEdgeCases:
    """엣지 케이스 테스트"""

    @pytest.mark.asyncio
    async def test_player_with_no_matches(self):
        """경기 기록이 없는 선수"""
        service = PlayerService()

        mock_supabase = MagicMock()
        matches_response = MagicMock()
        matches_response.data = []

        mock_supabase.table = MagicMock(return_value=mock_supabase)
        mock_supabase.select = MagicMock(return_value=mock_supabase)
        mock_supabase.or_ = MagicMock(return_value=mock_supabase)
        mock_supabase.execute = MagicMock(return_value=matches_response)

        with patch.object(service, "supabase", mock_supabase):
            stats = await service._calculate_pool_stats(999)

            assert stats["pool_total_bouts"] == 0
            assert stats["pool_win_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_member_without_player_link(self, test_organization_id):
        """선수 연결이 없는 회원 (대회 미출전 신규 회원)"""
        service = PlayerService()

        mock_supabase = MagicMock()

        org_response = MagicMock()
        org_response.data = {"id": test_organization_id, "name": "테스트클럽"}

        members_response = MagicMock()
        members_response.data = [
            {
                "id": "member1",
                "full_name": "신규선수",
                "club_role": "student",
                "member_status": "active",
                "player_id": None,  # 연결 없음
            }
        ]

        mock_supabase.table = MagicMock(return_value=mock_supabase)
        mock_supabase.select = MagicMock(return_value=mock_supabase)
        mock_supabase.eq = MagicMock(return_value=mock_supabase)
        mock_supabase.in_ = MagicMock(return_value=mock_supabase)
        mock_supabase.single = MagicMock(return_value=mock_supabase)

        execute_calls = [org_response, members_response]
        mock_supabase.execute = MagicMock(side_effect=execute_calls)

        with patch.object(service, "supabase", mock_supabase):
            with patch("httpx.AsyncClient") as mock_client:
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json = MagicMock(return_value={"results": []})

                mock_client_instance = AsyncMock()
                mock_client_instance.get = AsyncMock(return_value=mock_response)
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=None)
                mock_client.return_value = mock_client_instance

                roster = await service.get_team_roster(test_organization_id)

                assert len(roster["players"]) == 1
                # player_id가 없어도 roster에 포함됨
                assert roster["players"][0]["player_id"] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
