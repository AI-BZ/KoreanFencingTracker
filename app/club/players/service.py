"""
Player Data Service

선수 데이터 연동 서비스 - 클럽 관리 SaaS의 핵심 기능
기존 players, competitions, events, matches 테이블의 데이터를 활용
"""

from typing import Optional, List, Dict, Any
from datetime import date, datetime
import httpx
from database.supabase_client import get_supabase_client


class PlayerService:
    """선수 데이터 서비스"""

    def __init__(self):
        self.supabase = get_supabase_client()

    # =============================================
    # 선수 검색 및 연결
    # =============================================

    async def search_players(
        self,
        query: str,
        weapon: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        선수 검색
        - 이름, 소속팀으로 검색
        - 무기 필터 옵션
        """
        search_query = self.supabase.table("players").select(
            "id, name, team, weapon, birth_year"
        )

        # 이름 또는 팀으로 검색
        search_query = search_query.or_(
            f"name.ilike.%{query}%,team.ilike.%{query}%"
        )

        if weapon:
            search_query = search_query.eq("weapon", weapon)

        response = search_query.limit(limit).execute()

        results = []
        for player in response.data or []:
            # 대회 참가 수 조회
            comp_count = await self._get_competition_count(player["id"])

            # 이미 연결된 회원이 있는지 확인
            is_linked = await self._check_player_linked(player["id"])

            results.append({
                "player_id": player["id"],
                "name": player["name"],
                "team": player.get("team"),
                "weapon": player.get("weapon"),
                "birth_year": player.get("birth_year"),
                "competition_count": comp_count,
                "is_linked": is_linked
            })

        return results

    async def _get_competition_count(self, player_id: int) -> int:
        """선수의 대회 참가 수"""
        # matches 테이블에서 해당 선수가 참가한 종목 수 계산
        response = self.supabase.table("matches").select(
            "event_id", count="exact"
        ).or_(
            f"player1_id.eq.{player_id},player2_id.eq.{player_id}"
        ).execute()

        # 고유 event_id 수 반환 (실제로는 distinct count 필요)
        return response.count if response.count else 0

    async def _check_player_linked(self, player_id: int) -> bool:
        """선수가 이미 클럽 회원과 연결되어 있는지 확인"""
        response = self.supabase.table("members").select(
            "id"
        ).eq("player_id", player_id).limit(1).execute()

        return len(response.data or []) > 0

    async def link_player_to_member(
        self,
        member_id: str,
        player_id: int,
        organization_id: int
    ) -> bool:
        """
        회원에 선수 연결
        - 같은 조직의 회원만 연결 가능
        """
        # 회원이 해당 조직 소속인지 확인
        member_response = self.supabase.table("members").select(
            "id, organization_id"
        ).eq("id", member_id).single().execute()

        if not member_response.data:
            raise ValueError("회원을 찾을 수 없습니다")

        if member_response.data["organization_id"] != organization_id:
            raise ValueError("다른 조직의 회원입니다")

        # 선수 연결
        update_response = self.supabase.table("members").update({
            "player_id": player_id
        }).eq("id", member_id).execute()

        return len(update_response.data or []) > 0

    async def unlink_player_from_member(
        self,
        member_id: str,
        organization_id: int
    ) -> bool:
        """회원의 선수 연결 해제"""
        update_response = self.supabase.table("members").update({
            "player_id": None
        }).eq("id", member_id).eq("organization_id", organization_id).execute()

        return len(update_response.data or []) > 0

    # =============================================
    # 선수 프로필 및 통계
    # =============================================

    async def get_player_profile(self, player_id: int) -> Optional[Dict[str, Any]]:
        """
        선수 전체 프로필
        - 기본 정보 + 통계 + 최근 랭킹
        """
        # 기본 정보
        player_response = self.supabase.table("players").select(
            "id, name, team, weapon, birth_year, nationality"
        ).eq("id", player_id).single().execute()

        if not player_response.data:
            return None

        player = player_response.data

        # 통계 계산
        stats = await self.get_player_stats(player_id)

        # 메달 수 계산
        medals = await self._get_medal_counts(player_id)

        # 최근 랭킹
        rankings = await self._get_current_rankings(player_id)

        return {
            "player_id": player["id"],
            "name": player["name"],
            "team": player.get("team"),
            "weapon": player.get("weapon"),
            "birth_year": player.get("birth_year"),
            "nationality": player.get("nationality"),
            "total_competitions": stats.get("total_competitions", 0),
            "total_events": stats.get("total_events", 0),
            "gold_medals": medals.get("gold", 0),
            "silver_medals": medals.get("silver", 0),
            "bronze_medals": medals.get("bronze", 0),
            "current_rankings": rankings
        }

    async def get_player_stats(self, player_id: int) -> Dict[str, Any]:
        """
        선수 성과 지표
        - Pool 승률, DE 진출률 등
        """
        # Pool 경기 통계
        pool_stats = await self._calculate_pool_stats(player_id)

        # DE 통계
        de_stats = await self._calculate_de_stats(player_id)

        # 전체 대회/종목 수
        competitions = await self._get_unique_competitions(player_id)

        return {
            "player_id": player_id,
            "total_competitions": len(competitions.get("competition_ids", [])),
            "total_events": len(competitions.get("event_ids", [])),
            **pool_stats,
            **de_stats
        }

    async def _calculate_pool_stats(self, player_id: int) -> Dict[str, Any]:
        """Pool 경기 통계 계산"""
        # Pool 경기만 조회
        response = self.supabase.table("matches").select(
            "player1_id, player2_id, player1_score, player2_score, bout_type"
        ).eq("bout_type", "pool").or_(
            f"player1_id.eq.{player_id},player2_id.eq.{player_id}"
        ).execute()

        matches = response.data or []

        total_bouts = 0
        wins = 0
        touches_scored = 0
        touches_received = 0

        for match in matches:
            total_bouts += 1
            is_player1 = match["player1_id"] == player_id

            if is_player1:
                my_score = match.get("player1_score", 0) or 0
                opp_score = match.get("player2_score", 0) or 0
            else:
                my_score = match.get("player2_score", 0) or 0
                opp_score = match.get("player1_score", 0) or 0

            touches_scored += my_score
            touches_received += opp_score

            if my_score > opp_score:
                wins += 1

        win_rate = (wins / total_bouts * 100) if total_bouts > 0 else 0.0

        return {
            "pool_total_bouts": total_bouts,
            "pool_wins": wins,
            "pool_losses": total_bouts - wins,
            "pool_win_rate": round(win_rate, 1),
            "pool_touches_scored": touches_scored,
            "pool_touches_received": touches_received,
            "pool_indicator": touches_scored - touches_received
        }

    async def _calculate_de_stats(self, player_id: int) -> Dict[str, Any]:
        """DE 경기 통계 계산"""
        # DE 경기만 조회
        response = self.supabase.table("matches").select(
            "event_id, round_name, player1_id, player2_id, player1_score, player2_score"
        ).eq("bout_type", "de").or_(
            f"player1_id.eq.{player_id},player2_id.eq.{player_id}"
        ).execute()

        matches = response.data or []

        # 종목별 그룹화
        events: Dict[int, List] = {}
        for match in matches:
            event_id = match["event_id"]
            if event_id not in events:
                events[event_id] = []
            events[event_id].append(match)

        total_events = len(events)
        total_rounds_won = 0

        for event_id, event_matches in events.items():
            for match in event_matches:
                is_player1 = match["player1_id"] == player_id
                if is_player1:
                    my_score = match.get("player1_score", 0) or 0
                    opp_score = match.get("player2_score", 0) or 0
                else:
                    my_score = match.get("player2_score", 0) or 0
                    opp_score = match.get("player1_score", 0) or 0

                if my_score > opp_score:
                    total_rounds_won += 1

        avg_rounds = (total_rounds_won / total_events) if total_events > 0 else 0.0

        return {
            "de_total_events": total_events,
            "de_rounds_won": total_rounds_won,
            "de_avg_rounds_won": round(avg_rounds, 2)
        }

    async def _get_medal_counts(self, player_id: int) -> Dict[str, int]:
        """메달 수 계산 (1~3위)"""
        # rankings 테이블에서 최종 순위 조회
        response = self.supabase.table("rankings").select(
            "final_rank"
        ).eq("player_id", player_id).in_("final_rank", [1, 2, 3]).execute()

        ranks = [r["final_rank"] for r in (response.data or [])]

        return {
            "gold": ranks.count(1),
            "silver": ranks.count(2),
            "bronze": ranks.count(3)
        }

    async def _get_current_rankings(self, player_id: int) -> List[Dict[str, Any]]:
        """현재 랭킹 조회"""
        # 가장 최근 랭킹 정보
        response = self.supabase.table("rankings").select(
            "weapon, gender, age_group, rank, points, year"
        ).eq("player_id", player_id).order(
            "year", desc=True
        ).limit(5).execute()

        return response.data or []

    async def _get_unique_competitions(self, player_id: int) -> Dict[str, List[int]]:
        """참가한 고유 대회/종목 ID 목록"""
        response = self.supabase.table("matches").select(
            "event_id"
        ).or_(
            f"player1_id.eq.{player_id},player2_id.eq.{player_id}"
        ).execute()

        event_ids = list(set(m["event_id"] for m in (response.data or [])))

        # 종목에서 대회 ID 조회
        if event_ids:
            events_response = self.supabase.table("events").select(
                "competition_id"
            ).in_("id", event_ids).execute()
            competition_ids = list(set(
                e["competition_id"] for e in (events_response.data or [])
            ))
        else:
            competition_ids = []

        return {
            "event_ids": event_ids,
            "competition_ids": competition_ids
        }

    # =============================================
    # 대회 히스토리
    # =============================================

    async def get_competition_history(
        self,
        player_id: int,
        year: Optional[int] = None,
        weapon: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        대회 출전 히스토리
        - 종목별 결과, 순위, Pool/DE 성적
        """
        # 참가한 종목 조회
        matches_query = self.supabase.table("matches").select(
            "event_id"
        ).or_(
            f"player1_id.eq.{player_id},player2_id.eq.{player_id}"
        )

        matches_response = matches_query.execute()
        event_ids = list(set(m["event_id"] for m in (matches_response.data or [])))

        if not event_ids:
            return []

        # 종목 상세 정보
        events_query = self.supabase.table("events").select(
            "id, competition_id, name, weapon, gender, age_group"
        ).in_("id", event_ids)

        if weapon:
            events_query = events_query.eq("weapon", weapon)

        events_response = events_query.execute()
        events = {e["id"]: e for e in (events_response.data or [])}

        # 대회 정보
        competition_ids = list(set(e["competition_id"] for e in events.values()))
        comps_response = self.supabase.table("competitions").select(
            "id, name, start_date, end_date"
        ).in_("id", competition_ids).execute()
        competitions = {c["id"]: c for c in (comps_response.data or [])}

        # 결과 조합
        history = []
        for event_id in event_ids:
            if event_id not in events:
                continue

            event = events[event_id]
            comp = competitions.get(event["competition_id"], {})

            # 해당 종목에서의 성적 계산
            event_stats = await self._get_event_performance(player_id, event_id)

            # 최종 순위 조회
            final_rank = await self._get_final_rank(player_id, event_id)

            history.append({
                "competition_id": event["competition_id"],
                "competition_name": comp.get("name", ""),
                "competition_date": comp.get("start_date"),
                "event_name": event["name"],
                "event_id": event_id,
                "weapon": event.get("weapon"),
                "final_rank": final_rank,
                **event_stats
            })

        # 날짜순 정렬
        history.sort(key=lambda x: x.get("competition_date") or "", reverse=True)

        if year:
            history = [h for h in history if h.get("competition_date", "").startswith(str(year))]

        return history[:limit]

    async def _get_event_performance(
        self,
        player_id: int,
        event_id: int
    ) -> Dict[str, Any]:
        """특정 종목에서의 성적"""
        response = self.supabase.table("matches").select(
            "bout_type, round_name, player1_id, player2_id, player1_score, player2_score"
        ).eq("event_id", event_id).or_(
            f"player1_id.eq.{player_id},player2_id.eq.{player_id}"
        ).execute()

        matches = response.data or []

        pool_wins = 0
        pool_losses = 0
        de_rounds_won = 0

        for match in matches:
            is_player1 = match["player1_id"] == player_id
            if is_player1:
                my_score = match.get("player1_score", 0) or 0
                opp_score = match.get("player2_score", 0) or 0
            else:
                my_score = match.get("player2_score", 0) or 0
                opp_score = match.get("player1_score", 0) or 0

            if match["bout_type"] == "pool":
                if my_score > opp_score:
                    pool_wins += 1
                else:
                    pool_losses += 1
            elif match["bout_type"] == "de":
                if my_score > opp_score:
                    de_rounds_won += 1

        return {
            "pool_wins": pool_wins,
            "pool_losses": pool_losses,
            "de_rounds_won": de_rounds_won
        }

    async def _get_final_rank(self, player_id: int, event_id: int) -> Optional[int]:
        """종목 최종 순위"""
        response = self.supabase.table("rankings").select(
            "final_rank"
        ).eq("player_id", player_id).eq("event_id", event_id).single().execute()

        if response.data:
            return response.data.get("final_rank")
        return None

    # =============================================
    # 상대 전적
    # =============================================

    async def get_head_to_head(
        self,
        player_id: int,
        opponent_id: int
    ) -> Dict[str, Any]:
        """
        특정 상대와의 전적
        - 전체 승패 + 최근 경기 기록
        """
        # 상대 정보
        opponent_response = self.supabase.table("players").select(
            "id, name, team"
        ).eq("id", opponent_id).single().execute()

        if not opponent_response.data:
            raise ValueError("상대 선수를 찾을 수 없습니다")

        opponent = opponent_response.data

        # 직접 대결 경기 조회
        response = self.supabase.table("matches").select(
            "event_id, bout_type, round_name, player1_id, player2_id, player1_score, player2_score"
        ).or_(
            f"and(player1_id.eq.{player_id},player2_id.eq.{opponent_id}),"
            f"and(player1_id.eq.{opponent_id},player2_id.eq.{player_id})"
        ).execute()

        matches = response.data or []

        wins = 0
        losses = 0
        recent_bouts = []

        for match in matches:
            is_player1 = match["player1_id"] == player_id
            if is_player1:
                my_score = match.get("player1_score", 0) or 0
                opp_score = match.get("player2_score", 0) or 0
            else:
                my_score = match.get("player2_score", 0) or 0
                opp_score = match.get("player1_score", 0) or 0

            is_winner = my_score > opp_score
            if is_winner:
                wins += 1
            else:
                losses += 1

            # 종목/대회 정보 조회
            event_info = await self._get_event_info(match["event_id"])

            recent_bouts.append({
                "competition_name": event_info.get("competition_name", ""),
                "competition_date": event_info.get("competition_date"),
                "round_type": match["bout_type"],
                "round_name": match.get("round_name", ""),
                "score": f"{my_score}-{opp_score}",
                "is_winner": is_winner
            })

        total_bouts = wins + losses
        win_rate = (wins / total_bouts * 100) if total_bouts > 0 else 0.0

        # 최근 순서로 정렬
        recent_bouts.sort(
            key=lambda x: x.get("competition_date") or "",
            reverse=True
        )

        return {
            "opponent_id": opponent_id,
            "opponent_name": opponent["name"],
            "opponent_team": opponent.get("team"),
            "total_bouts": total_bouts,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 1),
            "recent_bouts": recent_bouts[:10]  # 최근 10경기
        }

    async def _get_event_info(self, event_id: int) -> Dict[str, Any]:
        """종목 및 대회 정보"""
        response = self.supabase.table("events").select(
            "id, name, competition_id"
        ).eq("id", event_id).single().execute()

        if not response.data:
            return {}

        event = response.data

        comp_response = self.supabase.table("competitions").select(
            "name, start_date"
        ).eq("id", event["competition_id"]).single().execute()

        comp = comp_response.data or {}

        return {
            "event_name": event["name"],
            "competition_name": comp.get("name", ""),
            "competition_date": comp.get("start_date")
        }

    async def get_all_opponents(
        self,
        player_id: int,
        min_bouts: int = 2
    ) -> List[Dict[str, Any]]:
        """
        모든 상대 전적 목록
        - 최소 n번 이상 대결한 상대만
        """
        # 모든 경기에서 상대 목록 추출
        response = self.supabase.table("matches").select(
            "player1_id, player2_id"
        ).or_(
            f"player1_id.eq.{player_id},player2_id.eq.{player_id}"
        ).execute()

        opponent_counts: Dict[int, int] = {}

        for match in (response.data or []):
            if match["player1_id"] == player_id:
                opp_id = match["player2_id"]
            else:
                opp_id = match["player1_id"]

            if opp_id:
                opponent_counts[opp_id] = opponent_counts.get(opp_id, 0) + 1

        # 최소 경기 수 필터
        frequent_opponents = [
            opp_id for opp_id, count in opponent_counts.items()
            if count >= min_bouts
        ]

        # 상대별 전적 조회
        results = []
        for opp_id in frequent_opponents:
            h2h = await self.get_head_to_head(player_id, opp_id)
            results.append(h2h)

        # 대결 횟수로 정렬
        results.sort(key=lambda x: x["total_bouts"], reverse=True)

        return results

    # =============================================
    # 팀 로스터
    # =============================================

    async def get_team_roster(self, organization_id: int) -> Dict[str, Any]:
        """
        클럽 소속 선수 전체 현황
        - 연결된 선수들의 대회 성적, 랭킹 포함
        - 메인 API에서 선수 데이터 조회
        - 학생만 카운트 (코치/대표 제외)
        """
        # 조직 정보
        org_response = self.supabase.table("organizations").select(
            "id, name"
        ).eq("id", organization_id).single().execute()

        if not org_response.data:
            raise ValueError("조직을 찾을 수 없습니다")

        org = org_response.data
        org_name = org["name"]  # 예: "최병철펜싱클럽"

        # 조직의 회원 목록 (활성 회원만)
        members_response = self.supabase.table("members").select(
            "id, full_name, club_role, member_status, player_id"
        ).eq("organization_id", organization_id).in_(
            "member_status", ["active", None]
        ).execute()

        members = members_response.data or []

        roster = []
        student_count = 0  # 학생만 카운트

        for member in members:
            # 학생 역할인지 확인 (코치/대표/보조코치는 로스터에서 제외)
            club_role = member.get("club_role", "student")
            # assistant는 보조 코치이므로 코치 그룹 (학생 아님)
            is_student = club_role == "student"

            # 코치/대표/보조코치는 로스터에 포함하지 않음
            if not is_student:
                continue

            student_count += 1

            player_data = {
                "player_id": None,
                "weapon": None,
                "competition_count": 0,
                "current_rank": None,
                "recent_result": None
            }

            # 이름으로 메인 API에서 선수 데이터 조회
            # DB members 테이블에 등록된 선수 = 우리 클럽 소속
            # current_team 필터링 제거 (선수의 현재 소속과 과거 소속이 다를 수 있음)
            player_name = member["full_name"]
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"http://localhost:71/api/players/search",
                        params={"q": player_name},
                        timeout=5.0
                    )
                    if response.status_code == 200:
                        data = response.json()
                        results = data.get("results", [])

                        # 이름이 정확히 일치하는 선수 찾기 (current_team 필터 제거)
                        for result in results:
                            if result.get("name") == player_name:
                                weapons = result.get("weapons", [])

                                # 최근 대회 결과 조회
                                recent_result = await self._get_recent_competition_result(
                                    result.get("player_id")
                                )

                                player_data = {
                                    "player_id": result.get("player_id"),  # KOP00000 형식
                                    "weapon": weapons[0] if weapons else None,
                                    "competition_count": result.get("record_count", 0),
                                    "current_rank": None,
                                    "recent_result": recent_result
                                }
                                break
            except Exception as e:
                # 실패해도 무시하고 기본값 사용
                pass

            roster.append({
                "member_id": member["id"],
                "player_id": player_data.get("player_id") or member.get("player_id"),
                "name": member["full_name"],
                "club_role": club_role,
                "status": member.get("member_status", "active"),
                "weapon": player_data.get("weapon"),
                "competition_count": player_data.get("competition_count", 0),
                "current_rank": player_data.get("current_rank"),
                "recent_result": player_data.get("recent_result")
            })

        return {
            "organization_id": org["id"],
            "organization_name": org["name"],
            "total_members": student_count,  # 학생만 카운트 (코치 제외)
            "players": roster  # 학생만 포함 (코치/대표 제외)
        }

    async def _get_recent_competition_result(self, player_id: str) -> Optional[str]:
        """선수의 최근 대회 결과 조회"""
        if not player_id:
            return None

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"http://localhost:71/api/players/by-id/{player_id}",
                    timeout=5.0
                )
                if response.status_code == 200:
                    data = response.json()

                    # podium_by_season에서 최근 시즌 결과 확인
                    podium = data.get("podium_by_season", {})
                    if podium:
                        # 가장 최근 시즌
                        latest_season = max(podium.keys()) if podium else None
                        if latest_season:
                            season_data = podium[latest_season]
                            gold = season_data.get("gold", 0)
                            silver = season_data.get("silver", 0)
                            bronze = season_data.get("bronze", 0)

                            if gold > 0 or silver > 0 or bronze > 0:
                                medals = []
                                if gold > 0:
                                    medals.append(f"🥇{gold}")
                                if silver > 0:
                                    medals.append(f"🥈{silver}")
                                if bronze > 0:
                                    medals.append(f"🥉{bronze}")
                                return f"{latest_season} {' '.join(medals)}"

                    # 메달이 없으면 대회 수만 표시
                    comp_count = data.get("competition_count", 0)
                    if comp_count > 0:
                        return f"대회 {comp_count}회 출전"

        except Exception:
            pass

        return None


# 싱글톤 인스턴스
player_service = PlayerService()
