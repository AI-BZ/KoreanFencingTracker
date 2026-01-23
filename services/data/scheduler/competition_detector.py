"""
대회 공고 감지 및 이벤트 기반 스크래핑 스케줄러

- 새 대회 공고 감지 (주 1회)
- 대회 일정 기반 자동 스크래핑:
  - 대회 1주일 전: 참가자 명단 스크래핑
  - 대회 당일 00:00 ~ 종료: 실시간 스크래핑 (1시간 간격)
  - 대회 종료 후: 최종 결과 스크래핑
"""
import asyncio
import os
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass
from enum import Enum
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

# Supabase
from supabase import create_client, Client

# 싱글톤 Supabase 클라이언트
_supabase_client: Optional[Client] = None


def get_supabase_client() -> Optional[Client]:
    """Supabase 클라이언트 싱글톤"""
    global _supabase_client
    if _supabase_client is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if url and key:
            _supabase_client = create_client(url, key)
        else:
            logger.error("SUPABASE_URL 또는 SUPABASE_KEY가 설정되지 않았습니다")
    return _supabase_client


# Playwright for scraping
try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class CompetitionStatus(Enum):
    """대회 상태"""
    ANNOUNCED = "공고"      # 공고됨 (접수 전)
    REGISTRATION = "접수중"  # 접수 중
    CLOSED = "접수마감"      # 접수 마감
    UPCOMING = "예정"       # 대회 예정 (1주일 이내)
    ONGOING = "진행"        # 대회 진행 중
    COMPLETED = "종료"      # 대회 종료


@dataclass
class DetectedCompetition:
    """감지된 대회 정보"""
    name: str
    start_date: date
    end_date: date
    status: str
    site_status: str  # 사이트에서 가져온 원본 상태


class CompetitionDetector:
    """
    대회 공고 감지기

    대한펜싱협회 사이트에서 새 대회를 감지하고 DB에 등록
    """

    BASE_URL = "https://fencing.sports.or.kr"
    COMP_LIST_URL = f"{BASE_URL}/game/compList?code=game"

    def __init__(self):
        self.db: Optional[Client] = None
        self._existing_comps: Set[tuple] = set()  # (대회명, 시작일) 튜플 집합

    def _init_db(self) -> bool:
        """Supabase 클라이언트 초기화 (싱글톤 사용)"""
        self.db = get_supabase_client()
        return self.db is not None

    async def _load_existing_competitions(self) -> None:
        """DB에서 기존 대회 목록 로드"""
        try:
            # 최근 2년간 대회만 로드 (메모리 효율)
            two_years_ago = (date.today() - timedelta(days=730)).isoformat()

            result = self.db.table("competitions").select(
                "comp_name, start_date"
            ).gte("start_date", two_years_ago).execute()

            # (대회명, 시작일) 튜플로 저장 - 동일 이름 다른 연도 대회 구분
            self._existing_comps = {
                (row["comp_name"], row["start_date"][:10] if row.get("start_date") else None)
                for row in result.data
            }
            logger.info(f"기존 대회 {len(self._existing_comps)}개 로드됨")

        except Exception as e:
            logger.error(f"기존 대회 로드 실패: {e}")

    async def _scrape_competition_list(self) -> List[DetectedCompetition]:
        """협회 사이트에서 대회 목록 스크래핑"""
        if not PLAYWRIGHT_AVAILABLE:
            logger.error("Playwright가 설치되지 않았습니다")
            return []

        competitions = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            try:
                await page.goto(self.COMP_LIST_URL, timeout=30000)
                await page.wait_for_selector("table", timeout=10000)

                # 대회 목록 테이블 파싱
                rows = await page.query_selector_all("table tbody tr")

                for row in rows:
                    try:
                        cells = await row.query_selector_all("td")
                        if len(cells) < 4:
                            continue

                        # 대회명
                        name_cell = cells[1]
                        name_link = await name_cell.query_selector("a")
                        if not name_link:
                            continue
                        name = (await name_link.inner_text()).strip()

                        # 기간
                        period_text = (await cells[2].inner_text()).strip()
                        start_date, end_date = self._parse_period(period_text)

                        if not start_date:
                            continue

                        # 상태
                        status_text = (await cells[3].inner_text()).strip()

                        competitions.append(DetectedCompetition(
                            name=name,
                            start_date=start_date,
                            end_date=end_date or start_date,
                            status=self._determine_status(start_date, end_date, status_text),
                            site_status=status_text
                        ))

                    except Exception as e:
                        logger.debug(f"행 파싱 오류: {e}")
                        continue

                logger.info(f"사이트에서 {len(competitions)}개 대회 감지")

            except Exception as e:
                logger.error(f"대회 목록 스크래핑 오류: {e}")
            finally:
                await browser.close()

        return competitions

    def _parse_period(self, period_text: str) -> tuple:
        """기간 텍스트 파싱 (예: '2026-01-14 ~ 2026-01-22')"""
        try:
            parts = period_text.split("~")
            start_str = parts[0].strip()
            end_str = parts[1].strip() if len(parts) > 1 else start_str

            start_date = date.fromisoformat(start_str)
            end_date = date.fromisoformat(end_str)

            return start_date, end_date
        except (ValueError, IndexError, AttributeError):
            return None, None

    def _determine_status(self, start_date: date, end_date: date, site_status: str) -> str:
        """대회 상태 결정"""
        today = date.today()

        if today > end_date:
            return CompetitionStatus.COMPLETED.value
        elif today >= start_date:
            return CompetitionStatus.ONGOING.value
        elif today >= start_date - timedelta(days=7):
            return CompetitionStatus.UPCOMING.value
        elif site_status in ["접수마감", "마감"]:
            return CompetitionStatus.CLOSED.value
        elif site_status in ["접수중", "접수"]:
            return CompetitionStatus.REGISTRATION.value
        else:
            return CompetitionStatus.ANNOUNCED.value

    async def detect_new_competitions(self) -> List[DetectedCompetition]:
        """새 대회 감지"""
        if not self._init_db():
            return []

        await self._load_existing_competitions()

        # 사이트에서 대회 목록 가져오기
        site_competitions = await self._scrape_competition_list()

        # 새 대회 필터링 (대회명 + 시작일로 중복 체크)
        new_competitions = []
        for comp in site_competitions:
            comp_key = (comp.name, comp.start_date.isoformat())
            if comp_key not in self._existing_comps:
                new_competitions.append(comp)
                logger.info(f"🆕 새 대회 발견: {comp.name} ({comp.start_date} ~ {comp.end_date})")

        return new_competitions

    async def register_new_competitions(self, competitions: List[DetectedCompetition]) -> int:
        """새 대회를 DB에 등록"""
        if not self.db or not competitions:
            return 0

        registered = 0

        for comp in competitions:
            try:
                data = {
                    "comp_name": comp.name,
                    "start_date": comp.start_date.isoformat(),
                    "end_date": comp.end_date.isoformat(),
                    "status": comp.status,
                    "detected_at": datetime.now().isoformat(),
                    "scrape_scheduled": False,  # 아직 스크래핑 스케줄 안됨
                }

                result = self.db.table("competitions").insert(data).execute()

                if result.data:
                    registered += 1
                    logger.info(f"✅ 대회 등록: {comp.name}")

            except Exception as e:
                logger.error(f"대회 등록 실패 ({comp.name}): {e}")

        return registered

    async def run(self) -> Dict[str, Any]:
        """대회 감지 실행"""
        logger.info("=== 대회 공고 감지 시작 ===")

        new_comps = await self.detect_new_competitions()
        registered = await self.register_new_competitions(new_comps)

        result = {
            "detected": len(new_comps),
            "registered": registered,
            "competitions": [
                {
                    "name": c.name,
                    "start_date": c.start_date.isoformat(),
                    "end_date": c.end_date.isoformat(),
                    "status": c.status,
                }
                for c in new_comps
            ],
            "checked_at": datetime.now().isoformat(),
        }

        if new_comps:
            logger.info(f"✅ {len(new_comps)}개 새 대회 감지, {registered}개 등록됨")
        else:
            logger.info("새 대회 없음")

        return result


class EventBasedScraper:
    """
    이벤트 기반 스크래핑 관리자 (최적화 버전)

    대회 일정에 따라 자동으로 스크래핑 실행:
    - 대회 전날/당일 오전: Pool 대진표 스크래핑 (pre_competition)
    - 대회 당일: 실시간 결과 스크래핑 (1시간 간격) - comp_idx로 직접 접근
    - 대회 종료 후: 최종 결과 스크래핑

    ⚡ 최적화: 전체 대회 목록 스캔 대신 comp_idx로 특정 대회만 직접 스크래핑
    """

    BASE_URL = "https://fencing.sports.or.kr"

    def __init__(self):
        self.db: Optional[Client] = get_supabase_client()

    async def get_competitions_to_scrape(self) -> Dict[str, List[Dict]]:
        """스크래핑할 대회 목록 조회"""
        if not self.db:
            self.db = get_supabase_client()
            if not self.db:
                return {"pre_competition": [], "ongoing": [], "just_ended": []}

        today = date.today()
        tomorrow = today + timedelta(days=1)
        yesterday = today - timedelta(days=1)

        result = {
            "pre_competition": [],  # 내일 시작 또는 오늘 시작 (대진표 수집용)
            "ongoing": [],          # 진행 중 (실시간 스크래핑)
            "just_ended": [],       # 어제 종료 (최종 결과 스크래핑)
        }

        try:
            # 내일 시작하는 대회 (전날 대진표 수집)
            tomorrow_start = self.db.table("competitions").select("*").eq(
                "start_date", tomorrow.isoformat()
            ).execute()
            result["pre_competition"].extend(tomorrow_start.data)

            # 오늘 시작하는 대회 중 아직 스크래핑 안된 것 (당일 오전 대진표)
            today_start = self.db.table("competitions").select("*").eq(
                "start_date", today.isoformat()
            ).execute()
            # 오전 9시 이전이면 pre_competition에 추가
            if datetime.now().hour < 9:
                result["pre_competition"].extend(today_start.data)

            # 현재 진행 중인 대회 (오늘 시작~오늘 종료 범위)
            ongoing = self.db.table("competitions").select("*").lte(
                "start_date", today.isoformat()
            ).gte(
                "end_date", today.isoformat()
            ).execute()
            result["ongoing"] = ongoing.data

            # 어제 종료된 대회 (최종 결과 확정)
            just_ended = self.db.table("competitions").select("*").eq(
                "end_date", yesterday.isoformat()
            ).execute()
            result["just_ended"] = just_ended.data

            logger.info(f"📊 대회 현황: 대진표={len(result['pre_competition'])}, "
                       f"진행중={len(result['ongoing'])}, 종료={len(result['just_ended'])}")

        except Exception as e:
            logger.error(f"대회 조회 오류: {e}")

        return result

    async def _scrape_competition_direct(self, comp: Dict, scrape_type: str = "full") -> Dict[str, Any]:
        """
        comp_idx를 사용해 특정 대회만 직접 스크래핑 (전체 스캔 없이)

        Args:
            comp: 대회 정보 (comp_idx 필수)
            scrape_type: "full" (전체), "pool_only" (Pool 대진표만), "results_only" (결과만)

        Returns:
            스크래핑 결과
        """
        comp_idx = comp.get("comp_idx")
        comp_name = comp.get("comp_name", "Unknown")

        if not comp_idx:
            logger.error(f"comp_idx 없음: {comp_name}")
            return {"success": False, "error": "comp_idx missing", "events_saved": 0}

        logger.info(f"🎯 직접 스크래핑: {comp_name} (comp_idx={comp_idx}, type={scrape_type})")

        try:
            from scraper.full_scraper import KFFFullScraper
            from scraper.models import Competition

            async with KFFFullScraper(headless=True) as scraper:
                # 1. 해당 대회의 종목 목록 가져오기 (직접 URL 접근 - 최적화)
                events = await scraper.get_events_direct(comp_idx)

                if not events:
                    logger.warning(f"  종목 없음: {comp_name}")
                    return {"success": True, "events_saved": 0, "message": "no events"}

                logger.info(f"  {len(events)}개 종목 발견")

                events_saved = 0
                event_results = []
                events_to_save = []  # 실제 저장할 데이터

                for event in events:
                    try:
                        # 전체 결과 수집 (pool_only든 full이든 일단 전체 가져옴)
                        results = await scraper.get_full_results(
                            comp_idx, event.sub_event_cd, page_num=1
                        )

                        if not results:
                            continue

                        has_pool = bool(results.get("pool_rounds"))
                        has_de = bool(results.get("de_bracket"))
                        has_rankings = bool(results.get("final_rankings"))

                        # pool_only 모드면 Pool 데이터만 있어야 저장
                        if scrape_type == "pool_only" and not (has_pool or results.get("pool_total_ranking")):
                            continue

                        # 저장할 데이터 구성
                        events_to_save.append({
                            "event": event,
                            "results": results,
                        })

                        event_results.append({
                            "event_name": event.name,
                            "sub_event_cd": event.sub_event_cd,
                            "has_pool": has_pool,
                            "has_de": has_de,
                            "has_rankings": has_rankings,
                        })
                        events_saved += 1

                    except Exception as e:
                        logger.warning(f"  종목 스크래핑 오류 ({event.name}): {e}")
                        continue

                # DB에 저장
                if events_to_save:
                    await self._save_scraped_data(comp, events_to_save)

                return {
                    "success": True,
                    "comp_name": comp_name,
                    "events_found": len(events),
                    "events_saved": events_saved,
                    "results": event_results,
                }

        except Exception as e:
            logger.error(f"직접 스크래핑 오류 ({comp_name}): {e}")
            return {"success": False, "error": str(e), "events_saved": 0}

    async def _save_scraped_data(self, comp: Dict, events_to_save: list) -> None:
        """스크래핑 데이터를 DB에 저장 (종목 데이터 포함)"""
        if not self.db:
            logger.error("DB 클라이언트 없음")
            return

        comp_id = comp.get("id")
        comp_idx = comp.get("comp_idx", "")
        if not comp_id:
            logger.error("competition id 없음")
            return

        events_saved = 0

        try:
            for item in events_to_save:
                event = item["event"]
                results = item["results"]

                # raw_data 구성
                raw_data = {
                    "pool_rounds": results.get("pool_rounds", []),
                    "pool_total_ranking": results.get("pool_total_ranking", []),
                    "de_bracket": results.get("de_bracket", {}),
                    "de_matches": results.get("de_matches", []),
                    "final_rankings": results.get("final_rankings", []),
                }

                # 종목 데이터 구성
                event_data = {
                    "competition_id": comp_id,
                    "event_cd": comp_idx,
                    "sub_event_cd": event.sub_event_cd,
                    "event_name": event.name,
                    "weapon": getattr(event, "weapon", ""),
                    "gender": getattr(event, "gender", ""),
                    "age_group": getattr(event, "age_group", ""),
                    "category": getattr(event, "event_type", "개인"),
                    "raw_data": raw_data,
                    "updated_at": datetime.now().isoformat(),
                }

                # upsert (있으면 업데이트, 없으면 삽입)
                try:
                    result = self.db.table("events").upsert(
                        event_data,
                        on_conflict="competition_id,event_cd,sub_event_cd"
                    ).execute()

                    if result.data:
                        events_saved += 1
                        logger.debug(f"    종목 저장: {event.name}")
                except Exception as e:
                    logger.warning(f"    종목 저장 오류 ({event.name}): {e}")

            # 대회 상태 업데이트
            self.db.table("competitions").update({
                "status": CompetitionStatus.ONGOING.value,
                "event_count": events_saved,
                "updated_at": datetime.now().isoformat()
            }).eq("id", comp_id).execute()

            logger.info(f"  ✅ DB 저장 완료: {events_saved}개 종목")

        except Exception as e:
            logger.error(f"DB 저장 오류: {e}")

    async def _refresh_server_cache(self):
        """서버 데이터 캐시 새로고침 (스크래핑 완료 후 자동 호출)"""
        import httpx

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:71/api/refresh-data",
                    timeout=60.0  # 데이터 로드에 시간이 걸릴 수 있음
                )
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"🔄 서버 캐시 새로고침 완료: {result.get('competitions', 0)}개 대회, {result.get('events', 0)}개 종목")
                else:
                    logger.warning(f"서버 캐시 새로고침 실패: {response.status_code}")
        except Exception as e:
            logger.warning(f"서버 캐시 새로고침 오류 (서버 접근 불가): {e}")

    async def scrape_pre_competition(self, competitions: List[Dict]) -> Dict[str, Any]:
        """
        대회 전 Pool 대진표 스크래핑
        - 대회 전날 또는 당일 09:00 이전에 실행
        - Pool 대진표 (참가자 명단, 풀 배정) 수집
        """
        if not competitions:
            return {"scraped": 0, "type": "pre_competition"}

        logger.info(f"📋 {len(competitions)}개 대회 대진표 사전 스크래핑")

        results = []

        for comp in competitions:
            result = await self._scrape_competition_direct(comp, scrape_type="pool_only")
            results.append({
                "comp_name": comp.get("comp_name"),
                "comp_idx": comp.get("comp_idx"),
                **result
            })

        total_events = sum(r.get("events_saved", 0) for r in results)
        logger.info(f"✅ 대진표 스크래핑 완료: {len(results)}개 대회, {total_events}개 종목")

        return {
            "scraped": len(results),
            "type": "pre_competition",
            "total_events": total_events,
            "results": results
        }

    async def scrape_specific_events(
        self,
        comp: Dict,
        specific_event_codes: List[str]
    ) -> Dict[str, Any]:
        """
        🎯 특정 종목만 선택적으로 스크래핑 (변경 감지 시스템용)

        변경 감지 시스템에서 변경된 종목 코드만 전달받아
        해당 종목만 스크래핑합니다.

        Args:
            comp: 대회 정보 (comp_idx, comp_name, id 등)
            specific_event_codes: 스크래핑할 종목 코드 목록 (예: ['COMPS001', 'COMPS003'])

        Returns:
            스크래핑 결과 (events_saved, event_results 등)
        """
        comp_idx = comp.get("comp_idx")
        comp_name = comp.get("comp_name", "Unknown")

        if not comp_idx:
            logger.error(f"comp_idx 없음: {comp_name}")
            return {"success": False, "error": "comp_idx missing", "events_saved": 0}

        if not specific_event_codes:
            logger.warning(f"스크래핑할 종목 없음: {comp_name}")
            return {"success": True, "events_saved": 0, "message": "no events to scrape"}

        logger.info(
            f"🎯 선택적 스크래핑 시작: {comp_name} - "
            f"{len(specific_event_codes)}개 종목"
        )

        try:
            from scraper.full_scraper import KFFFullScraper

            async with KFFFullScraper(headless=True) as scraper:
                # 1. 종목 목록 가져오기
                all_events = await scraper.get_events_direct(comp_idx)

                if not all_events:
                    return {"success": True, "events_saved": 0, "message": "no events"}

                # 2. 변경된 종목만 필터링
                target_events = [
                    e for e in all_events
                    if e.sub_event_cd in specific_event_codes
                ]

                if not target_events:
                    logger.warning(
                        f"변경된 종목을 찾을 수 없음: {specific_event_codes}"
                    )
                    return {"success": True, "events_saved": 0, "message": "no matching events"}

                logger.info(
                    f"🎯 {len(target_events)}개 종목 스크래핑: "
                    f"{[e.name for e in target_events]}"
                )

                events_saved = 0
                event_results = []
                events_to_save = []

                for event in target_events:
                    try:
                        # 결과 수집
                        results = await scraper.get_full_results(
                            comp_idx, event.sub_event_cd, page_num=1
                        )

                        if not results:
                            continue

                        has_pool = bool(results.get("pool_rounds"))
                        has_de = bool(results.get("de_bracket"))
                        has_rankings = bool(results.get("final_rankings"))

                        events_to_save.append({
                            "event": event,
                            "results": results,
                        })

                        event_results.append({
                            "event_name": event.name,
                            "sub_event_cd": event.sub_event_cd,
                            "has_pool": has_pool,
                            "has_de": has_de,
                            "has_rankings": has_rankings,
                        })
                        events_saved += 1

                    except Exception as e:
                        logger.warning(f"🎯 종목 스크래핑 오류 ({event.name}): {e}")
                        continue

                # DB 저장
                if events_to_save:
                    await self._save_scraped_data(comp, events_to_save)

                logger.info(
                    f"🎯 선택적 스크래핑 완료: {comp_name} - "
                    f"{events_saved}/{len(specific_event_codes)}개 종목 저장"
                )

                return {
                    "success": True,
                    "comp_name": comp_name,
                    "requested_events": len(specific_event_codes),
                    "events_found": len(target_events),
                    "events_saved": events_saved,
                    "results": event_results,
                }

        except Exception as e:
            logger.error(f"🎯 선택적 스크래핑 오류 ({comp_name}): {e}")
            return {"success": False, "error": str(e), "events_saved": 0}

    async def scrape_ongoing(self, competitions: List[Dict]) -> Dict[str, Any]:
        """
        진행 중 대회 실시간 스크래핑 (최적화 버전)
        - comp_idx로 특정 대회만 직접 스크래핑
        - 전체 대회 목록 스캔 없음
        """
        if not competitions:
            return {"scraped": 0, "type": "ongoing"}

        logger.info(f"🔴 {len(competitions)}개 진행 중 대회 실시간 스크래핑")

        results = []

        for comp in competitions:
            result = await self._scrape_competition_direct(comp, scrape_type="full")
            results.append({
                "comp_name": comp.get("comp_name"),
                "comp_idx": comp.get("comp_idx"),
                **result
            })

        total_events = sum(r.get("events_saved", 0) for r in results)
        logger.info(f"✅ 실시간 스크래핑 완료: {len(results)}개 대회, {total_events}개 종목")

        return {
            "scraped": len(results),
            "type": "ongoing",
            "total_events": total_events,
            "results": results
        }

    async def scrape_ongoing_stealth(self, competitions: List[Dict]) -> Dict[str, Any]:
        """
        진행 중 대회 스텔스 스크래핑 (30분 간격, 사람처럼)

        봇 탐지 회피를 위한 스텔스 기능:
        - 종목 간 랜덤 딜레이 (8~15초)
        - 대회 간 긴 딜레이 (15~30초)
        - 활동 로그 최소화
        """
        import random

        if not competitions:
            return {"scraped": 0, "type": "stealth_ongoing"}

        # 스텔스 설정 로드
        try:
            from scraper.config import stealth_config
        except ImportError:
            # 기본값 사용
            class DefaultConfig:
                stealth_delay_min = 5.0
                stealth_delay_max = 12.0
                between_events_delay_min = 8.0
                between_events_delay_max = 15.0
            stealth_config = DefaultConfig()

        logger.info(f"🥷 스텔스 스크래핑: {len(competitions)}개 진행 중 대회")

        results = []

        for idx, comp in enumerate(competitions):
            comp_name = comp.get("comp_name", "Unknown")

            # 🥷 대회 간 랜덤 딜레이 (첫 번째 제외)
            if idx > 0:
                between_comp_delay = random.uniform(15, 30)
                logger.debug(f"🥷 대회 간 딜레이: {between_comp_delay:.0f}초")
                await asyncio.sleep(between_comp_delay)

            logger.info(f"🥷 [{idx+1}/{len(competitions)}] {comp_name} 스크래핑 시작")

            try:
                result = await self._scrape_competition_stealth(comp)
                results.append({
                    "comp_name": comp_name,
                    "comp_idx": comp.get("comp_idx"),
                    **result
                })
            except Exception as e:
                logger.error(f"🥷 스텔스 스크래핑 오류 ({comp_name}): {e}")
                results.append({
                    "comp_name": comp_name,
                    "comp_idx": comp.get("comp_idx"),
                    "success": False,
                    "error": str(e)
                })

        total_events = sum(r.get("events_saved", 0) for r in results)
        logger.info(f"🥷 스텔스 스크래핑 완료: {len(results)}개 대회, {total_events}개 종목")

        # 스크래핑 완료 후 서버 캐시 자동 새로고침
        if total_events > 0:
            await self._refresh_server_cache()

        return {
            "scraped": len(results),
            "type": "stealth_ongoing",
            "total_events": total_events,
            "results": results
        }

    async def _scrape_competition_stealth(self, comp: Dict) -> Dict[str, Any]:
        """
        단일 대회 스텔스 스크래핑

        사람처럼 행동:
        - 종목 간 랜덤 딜레이
        - 페이지 로드 후 읽는 시간 시뮬레이션
        """
        import random

        comp_idx = comp.get("comp_idx")
        comp_name = comp.get("comp_name", "Unknown")

        if not comp_idx:
            logger.error(f"comp_idx 없음: {comp_name}")
            return {"success": False, "error": "comp_idx missing", "events_saved": 0}

        try:
            from scraper.config import stealth_config
        except ImportError:
            class DefaultConfig:
                stealth_delay_min = 5.0
                stealth_delay_max = 12.0
                between_events_delay_min = 8.0
                between_events_delay_max = 15.0
            stealth_config = DefaultConfig()

        try:
            from scraper.full_scraper import KFFFullScraper
            from scraper.models import Competition

            async with KFFFullScraper(headless=True) as scraper:
                # 1. 종목 목록 가져오기
                events = await scraper.get_events_direct(comp_idx)

                if not events:
                    return {"success": True, "events_saved": 0, "message": "no events"}

                logger.debug(f"🥷 {len(events)}개 종목 발견")

                events_saved = 0
                event_results = []
                events_to_save = []

                for event_idx, event in enumerate(events):
                    try:
                        # 🥷 종목 간 스텔스 딜레이
                        if event_idx > 0:
                            delay = random.uniform(
                                stealth_config.between_events_delay_min,
                                stealth_config.between_events_delay_max
                            )
                            logger.debug(f"🥷 종목 간 딜레이: {delay:.1f}초")
                            await asyncio.sleep(delay)

                        # 결과 수집
                        results = await scraper.get_full_results(
                            comp_idx, event.sub_event_cd, page_num=1
                        )

                        if not results:
                            continue

                        has_pool = bool(results.get("pool_rounds"))
                        has_de = bool(results.get("de_bracket"))
                        has_rankings = bool(results.get("final_rankings"))

                        events_to_save.append({
                            "event": event,
                            "results": results,
                        })

                        event_results.append({
                            "event_name": event.name,
                            "sub_event_cd": event.sub_event_cd,
                            "has_pool": has_pool,
                            "has_de": has_de,
                            "has_rankings": has_rankings,
                        })
                        events_saved += 1

                    except Exception as e:
                        logger.warning(f"🥷 종목 오류 ({event.name}): {e}")
                        continue

                # DB 저장
                if events_to_save:
                    await self._save_scraped_data(comp, events_to_save)

                return {
                    "success": True,
                    "comp_name": comp_name,
                    "events_found": len(events),
                    "events_saved": events_saved,
                    "results": event_results,
                }

        except Exception as e:
            logger.error(f"🥷 스텔스 스크래핑 오류 ({comp_name}): {e}")
            return {"success": False, "error": str(e), "events_saved": 0}

    async def scrape_just_ended(self, competitions: List[Dict]) -> Dict[str, Any]:
        """
        종료된 대회 최종 결과 스크래핑 (최적화 버전)
        - comp_idx로 특정 대회만 직접 스크래핑
        """
        if not competitions:
            return {"scraped": 0, "type": "just_ended"}

        logger.info(f"🏁 {len(competitions)}개 종료 대회 최종 결과 스크래핑")

        results = []

        for comp in competitions:
            result = await self._scrape_competition_direct(comp, scrape_type="full")
            results.append({
                "comp_name": comp.get("comp_name"),
                "comp_idx": comp.get("comp_idx"),
                **result
            })

            # 대회 상태를 완료로 업데이트
            if result.get("success") and self.db:
                try:
                    self.db.table("competitions").update({
                        "status": CompetitionStatus.COMPLETED.value,
                        "updated_at": datetime.now().isoformat()
                    }).eq("id", comp.get("id")).execute()
                except Exception as e:
                    logger.error(f"상태 업데이트 오류: {e}")

        total_events = sum(r.get("events_saved", 0) for r in results)
        logger.info(f"✅ 최종 결과 스크래핑 완료: {len(results)}개 대회, {total_events}개 종목")

        return {
            "scraped": len(results),
            "type": "just_ended",
            "total_events": total_events,
            "results": results
        }

    async def run(self) -> Dict[str, Any]:
        """이벤트 기반 스크래핑 실행"""
        logger.info("=== 이벤트 기반 스크래핑 시작 ===")

        comps = await self.get_competitions_to_scrape()

        results = {
            "pre_competition": await self.scrape_pre_competition(comps["pre_competition"]),
            "ongoing": await self.scrape_ongoing(comps["ongoing"]),
            "just_ended": await self.scrape_just_ended(comps["just_ended"]),
            "checked_at": datetime.now().isoformat(),
        }

        total_scraped = sum(r.get("scraped", 0) for r in results.values() if isinstance(r, dict))
        logger.info(f"✅ 이벤트 기반 스크래핑 완료: {total_scraped}개 대회 처리")

        return results


# CLI 테스트용
async def main():
    import argparse

    parser = argparse.ArgumentParser(description="대회 감지 및 이벤트 기반 스크래핑")
    parser.add_argument("--detect", action="store_true", help="새 대회 감지")
    parser.add_argument("--scrape", action="store_true", help="이벤트 기반 스크래핑")
    parser.add_argument("--all", action="store_true", help="감지 + 스크래핑")

    args = parser.parse_args()

    if args.detect or args.all:
        detector = CompetitionDetector()
        result = await detector.run()
        print(f"\n감지 결과: {result}")

    if args.scrape or args.all:
        scraper = EventBasedScraper()
        result = await scraper.run()
        print(f"\n스크래핑 결과: {result}")


if __name__ == "__main__":
    asyncio.run(main())
