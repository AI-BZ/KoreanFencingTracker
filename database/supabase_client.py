"""
Supabase 데이터베이스 클라이언트
"""
from typing import List, Optional, Dict, Any
from supabase import create_client, Client
from loguru import logger

from scraper.config import supabase_config
from scraper.models import Competition, Event, Player, Match, Ranking


# 싱글톤 클라이언트 (Club SaaS용)
_supabase_client: Optional[Client] = None


def get_supabase_client() -> Client:
    """
    Supabase 클라이언트 인스턴스 반환 (싱글톤)
    Club Management SaaS에서 사용
    """
    global _supabase_client
    if _supabase_client is None:
        if not supabase_config.supabase_url or not supabase_config.supabase_key:
            raise ValueError("SUPABASE_URL과 SUPABASE_KEY 환경변수를 설정해주세요")
        _supabase_client = create_client(
            supabase_config.supabase_url,
            supabase_config.supabase_key
        )
    return _supabase_client


class SupabaseDB:
    """Supabase 데이터베이스 클라이언트"""

    def __init__(self):
        if not supabase_config.supabase_url or not supabase_config.supabase_key:
            raise ValueError("SUPABASE_URL과 SUPABASE_KEY 환경변수를 설정해주세요")

        self.client: Client = create_client(
            supabase_config.supabase_url,
            supabase_config.supabase_key
        )

    # ==================== 대회 관련 ====================

    async def upsert_competition(self, competition: Competition) -> Optional[int]:
        """대회 정보 저장/업데이트"""
        data = {
            "comp_idx": competition.comp_idx,
            "comp_name": competition.comp_name,
            "start_date": competition.start_date.isoformat() if competition.start_date else None,
            "end_date": competition.end_date.isoformat() if competition.end_date else None,
            "venue": competition.venue,
            "status": competition.status,
            "raw_data": competition.raw_data
        }

        try:
            result = self.client.table("competitions").upsert(
                data,
                on_conflict="comp_idx"
            ).execute()

            if result.data:
                return result.data[0].get("id")
            return None
        except Exception as e:
            logger.error(f"대회 저장 오류: {e}")
            return None

    async def upsert_competitions(self, competitions: List[Competition]) -> int:
        """대회 목록 일괄 저장"""
        success_count = 0
        for comp in competitions:
            if await self.upsert_competition(comp):
                success_count += 1
        return success_count

    async def get_competition_id(self, comp_idx: str) -> Optional[int]:
        """comp_idx로 대회 DB ID 조회"""
        try:
            result = self.client.table("competitions").select("id").eq(
                "comp_idx", comp_idx
            ).execute()

            if result.data:
                return result.data[0].get("id")
            return None
        except Exception as e:
            logger.error(f"대회 ID 조회 오류: {e}")
            return None

    async def get_active_competitions(self) -> List[Dict[str, Any]]:
        """진행중인 대회 목록 조회"""
        try:
            result = self.client.table("competitions").select("*").eq(
                "status", "진행중"
            ).execute()
            return result.data or []
        except Exception as e:
            logger.error(f"진행중 대회 조회 오류: {e}")
            return []

    # ==================== 종목 관련 ====================

    async def upsert_event(self, event: Event, competition_id: int) -> Optional[int]:
        """종목 정보 저장/업데이트"""
        data = {
            "competition_id": competition_id,
            "event_cd": event.event_cd,
            "sub_event_cd": event.sub_event_cd,
            "event_name": event.event_name,
            "weapon": event.weapon,
            "gender": event.gender,
            "category": event.category,
            "age_group": event.age_group,
            "raw_data": event.raw_data
        }

        try:
            result = self.client.table("events").upsert(
                data,
                on_conflict="competition_id,event_cd,sub_event_cd"
            ).execute()

            if result.data:
                return result.data[0].get("id")
            return None
        except Exception as e:
            logger.error(f"종목 저장 오류: {e}")
            return None

    async def get_event_id(
        self,
        competition_id: int,
        event_cd: str,
        sub_event_cd: str
    ) -> Optional[int]:
        """종목 DB ID 조회"""
        try:
            query = self.client.table("events").select("id").eq(
                "competition_id", competition_id
            ).eq("event_cd", event_cd)

            if sub_event_cd:
                query = query.eq("sub_event_cd", sub_event_cd)

            result = query.execute()

            if result.data:
                return result.data[0].get("id")
            return None
        except Exception as e:
            logger.error(f"종목 ID 조회 오류: {e}")
            return None

    # ==================== 선수 관련 ====================

    async def upsert_player(self, player: Player) -> Optional[int]:
        """선수 정보 저장/업데이트"""
        data = {
            "player_name": player.player_name,
            "team_name": player.team_name,
            "birth_year": player.birth_year,
            "nationality": player.nationality,
            "raw_data": player.raw_data
        }

        try:
            result = self.client.table("players").upsert(
                data,
                on_conflict="player_name,team_name"
            ).execute()

            if result.data:
                return result.data[0].get("id")
            return None
        except Exception as e:
            logger.error(f"선수 저장 오류: {e}")
            return None

    async def get_or_create_player(self, player_name: str, team_name: Optional[str] = None) -> Optional[int]:
        """선수 조회 또는 생성"""
        try:
            # 기존 선수 조회
            query = self.client.table("players").select("id").eq("player_name", player_name)
            if team_name:
                query = query.eq("team_name", team_name)

            result = query.execute()
            if result.data:
                return result.data[0].get("id")

            # 없으면 생성
            player = Player(player_name=player_name, team_name=team_name)
            return await self.upsert_player(player)
        except Exception as e:
            logger.error(f"선수 조회/생성 오류: {e}")
            return None

    # ==================== 경기 결과 관련 ====================

    async def upsert_match(self, match: Match, event_id: int) -> Optional[int]:
        """경기 결과 저장/업데이트"""
        # 선수 ID 조회/생성
        player1_id = None
        player2_id = None
        winner_id = None

        if match.player1_name:
            player1_id = await self.get_or_create_player(match.player1_name)
        if match.player2_name:
            player2_id = await self.get_or_create_player(match.player2_name)

        # 승자 결정
        if match.player1_score and match.player2_score:
            if match.player1_score > match.player2_score:
                winner_id = player1_id
            elif match.player2_score > match.player1_score:
                winner_id = player2_id

        data = {
            "event_id": event_id,
            "round_name": match.round_name,
            "group_name": match.group_name,
            "match_number": match.match_number,
            "player1_id": player1_id,
            "player1_name": match.player1_name,
            "player1_score": match.player1_score,
            "player2_id": player2_id,
            "player2_name": match.player2_name,
            "player2_score": match.player2_score,
            "winner_id": winner_id,
            "match_status": match.match_status,
            "raw_data": match.raw_data
        }

        try:
            result = self.client.table("matches").insert(data).execute()
            if result.data:
                return result.data[0].get("id")
            return None
        except Exception as e:
            logger.error(f"경기 저장 오류: {e}")
            return None

    async def delete_event_matches(self, event_id: int) -> bool:
        """종목의 모든 경기 결과 삭제 (재수집용)"""
        try:
            self.client.table("matches").delete().eq("event_id", event_id).execute()
            return True
        except Exception as e:
            logger.error(f"경기 삭제 오류: {e}")
            return False

    # ==================== 순위 관련 ====================

    async def upsert_ranking(self, ranking: Ranking, event_id: int) -> Optional[int]:
        """순위 정보 저장/업데이트"""
        # 선수 ID 조회/생성
        player_id = None
        if ranking.player_name:
            player_id = await self.get_or_create_player(ranking.player_name, ranking.team_name)

        data = {
            "event_id": event_id,
            "player_id": player_id,
            "player_name": ranking.player_name,
            "team_name": ranking.team_name,
            "rank_position": ranking.rank_position,
            "match_count": ranking.match_count,
            "win_count": ranking.win_count,
            "loss_count": ranking.loss_count,
            "points": ranking.points,
            "raw_data": ranking.raw_data
        }

        try:
            result = self.client.table("rankings").upsert(
                data,
                on_conflict="event_id,player_id"
            ).execute()

            if result.data:
                return result.data[0].get("id")
            return None
        except Exception as e:
            logger.error(f"순위 저장 오류: {e}")
            return None

    # ==================== 로그 관련 ====================

    async def create_scrape_log(
        self,
        scrape_type: str,
        status: str = "running"
    ) -> Optional[int]:
        """스크래핑 로그 생성"""
        data = {
            "scrape_type": scrape_type,
            "status": status
        }

        try:
            result = self.client.table("scrape_logs").insert(data).execute()
            if result.data:
                return result.data[0].get("id")
            return None
        except Exception as e:
            logger.error(f"로그 생성 오류: {e}")
            return None

    async def update_scrape_log(
        self,
        log_id: int,
        status: str,
        competitions_processed: int = 0,
        events_processed: int = 0,
        matches_processed: int = 0,
        error_message: Optional[str] = None
    ) -> bool:
        """스크래핑 로그 업데이트"""
        data = {
            "status": status,
            "competitions_processed": competitions_processed,
            "events_processed": events_processed,
            "matches_processed": matches_processed,
            "completed_at": "now()" if status in ["completed", "failed"] else None,
            "error_message": error_message
        }

        try:
            self.client.table("scrape_logs").update(data).eq("id", log_id).execute()
            return True
        except Exception as e:
            logger.error(f"로그 업데이트 오류: {e}")
            return False

    # ==================== 통계 조회 ====================

    async def get_stats(self) -> Dict[str, int]:
        """데이터베이스 통계 조회"""
        stats = {}

        tables = ["competitions", "events", "players", "matches", "rankings"]
        for table in tables:
            try:
                result = self.client.table(table).select("id", count="exact").execute()
                stats[table] = result.count or 0
            except Exception as e:
                logger.error(f"{table} 통계 조회 오류: {e}")
                stats[table] = 0

        return stats
