"""
Sync Service - 데이터 서비스 동기화 비즈니스 로직

전략:
1. members 테이블에서 학생 회원 조회
2. 1회 HTTP 호출로 클럽명 검색 → 전체 선수 데이터 수집
3. 이름 매칭으로 member ↔ player 연결
4. 매칭된 선수의 상세 프로필을 배치로 조회 (asyncio.gather, 최대 5개 동시)
5. app_player_cache에 upsert
6. app_sync_logs에 결과 기록
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

import httpx
from loguru import logger

from ..database import get_supabase_client
from .. import config
from .models import SyncStatus, SyncType


# 동시 HTTP 요청 제한
MAX_CONCURRENT_REQUESTS = 5


class SyncService:
    """선수 데이터 동기화 서비스"""

    def __init__(self):
        self._supabase = None

    @property
    def supabase(self):
        if self._supabase is None:
            self._supabase = get_supabase_client()
        return self._supabase

    # =============================================
    # 메인 동기화
    # =============================================

    async def sync_club_players(self, org_id: int, org_name: str) -> dict:
        """
        클럽 선수 데이터 배치 동기화

        1. members 테이블에서 학생 조회
        2. 1회 HTTP: GET /api/players/search?q={org_name}&limit=200
        3. 이름 매칭 member ↔ player
        4. 매칭 선수 상세 프로필 배치 조회 (asyncio.gather)
        5. app_player_cache upsert
        6. app_sync_logs 기록
        """
        started_at = datetime.now(timezone.utc)

        # 동기화 로그 시작
        sync_log = self._create_sync_log(org_id, SyncType.player_cache, started_at)
        sync_id = sync_log["id"] if sync_log else None

        total_processed = 0
        total_updated = 0
        total_errors = 0
        error_details: List[str] = []

        try:
            # 동기화 상태를 running으로 업데이트
            if sync_id:
                self._update_sync_log(sync_id, status=SyncStatus.running)

            # Step 1: 학생 회원 목록 조회
            members = self._get_student_members(org_id)
            if not members:
                logger.info("동기화: org_id={} 학생 회원 없음", org_id)
                self._complete_sync_log(
                    sync_id, SyncStatus.completed, 0, 0, 0, started_at
                )
                return self._build_result(
                    sync_id, org_id, SyncStatus.completed, 0, 0, 0, [], started_at
                )

            total_processed = len(members)
            logger.info(
                "동기화 시작: org_id={}, org_name={}, members={}",
                org_id, org_name, total_processed,
            )

            # Step 2: 클럽명으로 선수 일괄 검색 (1회 HTTP)
            search_results = await self._search_players_by_org(org_name)
            logger.info(
                "동기화: data 서비스에서 {}명 검색됨 (org_name={})",
                len(search_results), org_name,
            )

            # Step 3: 이름 기반 매칭
            matched = self._match_members_to_players(members, search_results)
            logger.info("동기화: {}명 매칭됨 / {}명 중", len(matched), total_processed)

            # Step 4: 매칭된 선수 상세 프로필 배치 조회
            player_ids_to_fetch = [
                m["player_id"] for m in matched.values() if m.get("player_id")
            ]
            profiles = await self._batch_fetch_profiles(player_ids_to_fetch)

            # Step 5: app_player_cache에 upsert
            for member in members:
                member_id = member["id"]
                member_name = member["full_name"]

                try:
                    match_data = matched.get(member_id)
                    if match_data and match_data.get("player_id"):
                        player_id = match_data["player_id"]
                        profile = profiles.get(player_id, {})

                        cache_entry = self._build_cache_entry(
                            org_id, member_id, member_name, match_data, profile
                        )
                    else:
                        # 매칭 안 된 회원: 기본 정보만 캐시
                        cache_entry = {
                            "organization_id": org_id,
                            "member_id": member_id,
                            "player_id": None,
                            "player_name": member_name,
                            "current_team": None,
                            "weapons": None,
                            "age_group": None,
                            "competition_count": 0,
                            "last_competition_date": None,
                            "recent_result": None,
                            "medals": {"gold": 0, "silver": 0, "bronze": 0},
                            "last_synced_at": datetime.now(timezone.utc).isoformat(),
                        }

                    self._upsert_player_cache(cache_entry)
                    total_updated += 1

                except Exception as e:
                    total_errors += 1
                    error_msg = f"{member_name}: {str(e)}"
                    error_details.append(error_msg)
                    logger.error("동기화 에러 (member={}): {}", member_name, e)

            # Step 6: 로그 완료
            status = SyncStatus.completed if total_errors == 0 else SyncStatus.completed
            self._complete_sync_log(
                sync_id, status, total_processed, total_updated,
                total_errors, started_at, error_details or None,
            )

            logger.info(
                "동기화 완료: org_id={}, processed={}, updated={}, errors={}",
                org_id, total_processed, total_updated, total_errors,
            )

        except Exception as e:
            logger.error("동기화 실패: org_id={}, error={}", org_id, e)
            total_errors += 1
            error_details.append(f"동기화 실패: {str(e)}")
            self._complete_sync_log(
                sync_id, SyncStatus.failed, total_processed,
                total_updated, total_errors, started_at, error_details,
            )

        return self._build_result(
            sync_id, org_id,
            SyncStatus.completed if total_errors < total_processed else SyncStatus.failed,
            total_processed, total_updated, total_errors, error_details, started_at,
        )

    # =============================================
    # 상태 조회
    # =============================================

    async def get_sync_status(self, org_id: int) -> Optional[dict]:
        """최근 동기화 로그 조회"""
        try:
            result = self.supabase.table("app_sync_logs").select(
                "*"
            ).eq(
                "organization_id", org_id
            ).order(
                "started_at", desc=True
            ).limit(1).execute()

            if result.data:
                return result.data[0]
            return None

        except Exception as e:
            logger.error("동기화 상태 조회 실패: org_id={}, error={}", org_id, e)
            return None

    async def get_sync_history(self, org_id: int, limit: int = 10) -> List[dict]:
        """동기화 이력 조회"""
        try:
            result = self.supabase.table("app_sync_logs").select(
                "*"
            ).eq(
                "organization_id", org_id
            ).order(
                "started_at", desc=True
            ).limit(limit).execute()

            return result.data or []

        except Exception as e:
            logger.error("동기화 이력 조회 실패: org_id={}, error={}", org_id, e)
            return []

    # =============================================
    # 캐시된 로스터 조회
    # =============================================

    async def get_cached_roster(self, org_id: int) -> List[dict]:
        """
        app_player_cache에서 로스터 조회 (HTTP 호출 없음, 즉시 응답)
        """
        try:
            result = self.supabase.table("app_player_cache").select(
                "*"
            ).eq(
                "organization_id", org_id
            ).order(
                "player_name"
            ).execute()

            return result.data or []

        except Exception as e:
            logger.error("캐시 로스터 조회 실패: org_id={}, error={}", org_id, e)
            return []

    # =============================================
    # 내부 헬퍼: 회원 조회
    # =============================================

    def _get_student_members(self, org_id: int) -> List[dict]:
        """학생 회원 목록 조회 (코치/대표 제외)"""
        result = self.supabase.table("members").select(
            "id, full_name, player_id, club_role, member_status"
        ).eq(
            "organization_id", org_id
        ).eq(
            "club_role", "student"
        ).in_(
            "member_status", ["active", None]
        ).execute()

        return result.data or []

    # =============================================
    # 내부 헬퍼: data 서비스 HTTP 호출
    # =============================================

    async def _search_players_by_org(self, org_name: str) -> List[dict]:
        """
        data 서비스에서 클럽명으로 선수 일괄 검색
        1회 HTTP 호출로 클럽 소속 전체 선수를 가져옴
        """
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{config.DATA_SERVICE_URL}/api/players/search",
                    params={"q": org_name, "limit": 200},
                )
                if response.status_code == 200:
                    data = response.json()
                    return data.get("results", [])
                else:
                    logger.warning(
                        "선수 검색 실패: status={}, org_name={}",
                        response.status_code, org_name,
                    )
                    return []

        except httpx.TimeoutException:
            logger.error("선수 검색 타임아웃: org_name={}", org_name)
            return []
        except Exception as e:
            logger.error("선수 검색 에러: org_name={}, error={}", org_name, e)
            return []

    async def _fetch_player_profile(
        self, client: httpx.AsyncClient, player_id: str
    ) -> Optional[dict]:
        """단일 선수 프로필 조회"""
        try:
            response = await client.get(
                f"{config.DATA_SERVICE_URL}/api/players/by-id/{player_id}",
            )
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            logger.warning("프로필 조회 실패: player_id={}, error={}", player_id, e)
            return None

    async def _batch_fetch_profiles(
        self, player_ids: List[str]
    ) -> Dict[str, dict]:
        """
        여러 선수의 상세 프로필을 배치로 조회
        asyncio.Semaphore로 최대 동시 요청 수 제한
        """
        if not player_ids:
            return {}

        profiles: Dict[str, dict] = {}
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

        async def fetch_with_semaphore(
            client: httpx.AsyncClient, pid: str
        ) -> None:
            async with semaphore:
                result = await self._fetch_player_profile(client, pid)
                if result:
                    profiles[pid] = result

        async with httpx.AsyncClient(timeout=10.0) as client:
            tasks = [
                fetch_with_semaphore(client, pid) for pid in player_ids
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

        logger.info(
            "프로필 배치 조회: 요청={}, 성공={}",
            len(player_ids), len(profiles),
        )
        return profiles

    # =============================================
    # 내부 헬퍼: 매칭
    # =============================================

    def _match_members_to_players(
        self, members: List[dict], search_results: List[dict]
    ) -> Dict[str, dict]:
        """
        회원 이름 ↔ 검색 결과 매칭

        Returns: {member_id: {player_id, name, current_team, weapons, ...}}
        """
        # 이름으로 인덱싱 (동명이인 처리: 첫 번째 매칭 사용)
        player_by_name: Dict[str, dict] = {}
        for result in search_results:
            name = result.get("name", "")
            if name and name not in player_by_name:
                player_by_name[name] = result

        matched: Dict[str, dict] = {}
        for member in members:
            member_id = member["id"]
            member_name = member["full_name"]

            if member_name in player_by_name:
                player_data = player_by_name[member_name]
                matched[member_id] = {
                    "player_id": player_data.get("player_id"),
                    "name": player_data.get("name"),
                    "current_team": player_data.get("current_team"),
                    "weapons": player_data.get("weapons", []),
                    "record_count": player_data.get("record_count", 0),
                    "age_groups": player_data.get("age_groups", []),
                }

        return matched

    # =============================================
    # 내부 헬퍼: 캐시 엔트리 빌드
    # =============================================

    def _build_cache_entry(
        self,
        org_id: int,
        member_id: str,
        member_name: str,
        match_data: dict,
        profile: dict,
    ) -> dict:
        """매칭된 선수 정보 + 프로필 데이터로 캐시 엔트리 생성"""
        now_iso = datetime.now(timezone.utc).isoformat()

        # 무기 목록
        weapons = match_data.get("weapons", []) or profile.get("weapons", [])

        # 나이그룹 (검색 결과 또는 프로필에서)
        age_groups = match_data.get("age_groups", []) or profile.get("age_groups", [])
        age_group = self._classify_age_group(age_groups)

        # 대회 수
        competition_count = (
            profile.get("competition_count", 0)
            or match_data.get("record_count", 0)
        )

        # 최근 대회일
        last_competition_date = profile.get("last_competition_date")

        # 최근 결과 (메달 정보)
        recent_result = self._extract_recent_result(profile)

        # 메달 집계
        medals = self._extract_medals(profile)

        return {
            "organization_id": org_id,
            "member_id": member_id,
            "player_id": match_data.get("player_id"),
            "player_name": member_name,
            "current_team": match_data.get("current_team") or profile.get("current_team"),
            "weapons": weapons if weapons else None,
            "age_group": age_group,
            "competition_count": competition_count,
            "last_competition_date": last_competition_date,
            "recent_result": recent_result,
            "medals": medals,
            "last_synced_at": now_iso,
        }

    def _classify_age_group(self, age_groups: List[str]) -> Optional[str]:
        """나이그룹 분류"""
        if not age_groups:
            return None

        category_mapping = {
            "초등": ["초등부", "초등저", "초등고", "U9", "U11", "U13", "Y9", "Y11", "Y13"],
            "중등": ["중등부", "U14", "Y14", "여중", "남중"],
            "고등": ["고등부", "U17", "Y17", "여고", "남고"],
            "대학": ["대학부", "U20", "Y20", "청년부", "대학", "여대", "남대"],
            "일반": ["일반부", "일반", "시니어"],
        }

        found_categories = []
        for ag in age_groups:
            for category, patterns in category_mapping.items():
                for pattern in patterns:
                    if pattern in ag:
                        found_categories.append(category)
                        break

        if found_categories:
            priority = ["초등", "중등", "고등", "대학", "일반"]
            for p in reversed(priority):
                if p in found_categories:
                    return p

        return None

    def _extract_recent_result(self, profile: dict) -> Optional[str]:
        """프로필에서 최근 대회 결과 추출"""
        podium = profile.get("podium_by_season", {})
        if not podium:
            comp_count = profile.get("competition_count", 0)
            if comp_count > 0:
                return f"대회 {comp_count}회 출전"
            return None

        latest_season = max(podium.keys()) if podium else None
        if not latest_season:
            return None

        season_data = podium[latest_season]
        gold = season_data.get("gold", 0)
        silver = season_data.get("silver", 0)
        bronze = season_data.get("bronze", 0)

        if gold > 0 or silver > 0 or bronze > 0:
            medals = []
            if gold > 0:
                medals.append(f"\U0001f947{gold}")
            if silver > 0:
                medals.append(f"\U0001f948{silver}")
            if bronze > 0:
                medals.append(f"\U0001f949{bronze}")
            return f"{latest_season} {' '.join(medals)}"

        comp_count = profile.get("competition_count", 0)
        if comp_count > 0:
            return f"대회 {comp_count}회 출전"

        return None

    def _extract_medals(self, profile: dict) -> Dict[str, int]:
        """프로필에서 전체 메달 집계"""
        medals = {"gold": 0, "silver": 0, "bronze": 0}

        podium = profile.get("podium_by_season", {})
        if not podium:
            return medals

        for season_data in podium.values():
            if isinstance(season_data, dict):
                medals["gold"] += season_data.get("gold", 0)
                medals["silver"] += season_data.get("silver", 0)
                medals["bronze"] += season_data.get("bronze", 0)

        return medals

    # =============================================
    # 내부 헬퍼: Supabase 캐시 upsert
    # =============================================

    def _upsert_player_cache(self, entry: dict) -> None:
        """app_player_cache에 upsert (organization_id, member_id 충돌 시 업데이트)"""
        self.supabase.table("app_player_cache").upsert(
            entry,
            on_conflict="organization_id,member_id",
        ).execute()

    # =============================================
    # 내부 헬퍼: 동기화 로그
    # =============================================

    def _create_sync_log(
        self, org_id: int, sync_type: SyncType, started_at: datetime
    ) -> Optional[dict]:
        """동기화 로그 생성"""
        try:
            result = self.supabase.table("app_sync_logs").insert({
                "organization_id": org_id,
                "sync_type": sync_type.value,
                "status": SyncStatus.started.value,
                "started_at": started_at.isoformat(),
            }).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error("동기화 로그 생성 실패: {}", e)
            return None

    def _update_sync_log(self, sync_id: str, status: SyncStatus) -> None:
        """동기화 로그 상태 업데이트"""
        try:
            self.supabase.table("app_sync_logs").update({
                "status": status.value,
            }).eq("id", sync_id).execute()
        except Exception as e:
            logger.error("동기화 로그 업데이트 실패: {}", e)

    def _complete_sync_log(
        self,
        sync_id: Optional[str],
        status: SyncStatus,
        total_processed: int,
        total_updated: int,
        total_errors: int,
        started_at: datetime,
        error_details: Optional[List[str]] = None,
    ) -> None:
        """동기화 로그 완료 기록"""
        if not sync_id:
            return

        completed_at = datetime.now(timezone.utc)
        try:
            update_data: Dict[str, Any] = {
                "status": status.value,
                "total_processed": total_processed,
                "total_updated": total_updated,
                "total_errors": total_errors,
                "completed_at": completed_at.isoformat(),
            }
            if error_details:
                update_data["error_details"] = error_details

            self.supabase.table("app_sync_logs").update(
                update_data
            ).eq("id", sync_id).execute()

        except Exception as e:
            logger.error("동기화 로그 완료 기록 실패: {}", e)

    # =============================================
    # 내부 헬퍼: 결과 빌드
    # =============================================

    def _build_result(
        self,
        sync_id: Optional[str],
        org_id: int,
        status: SyncStatus,
        total_processed: int,
        total_updated: int,
        total_errors: int,
        error_details: List[str],
        started_at: datetime,
    ) -> dict:
        """동기화 결과 dict 생성"""
        completed_at = datetime.now(timezone.utc)
        duration = (completed_at - started_at).total_seconds()

        return {
            "sync_id": sync_id or "",
            "organization_id": org_id,
            "sync_type": SyncType.player_cache.value,
            "status": status.value,
            "total_processed": total_processed,
            "total_updated": total_updated,
            "total_errors": total_errors,
            "error_details": error_details[:20] if error_details else None,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "duration_seconds": round(duration, 2),
        }


# 싱글톤 인스턴스
sync_service = SyncService()
