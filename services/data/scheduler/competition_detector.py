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

# 풀 순위 계산 및 비교
from app.pool_calculator import calculate_pool_total_ranking, compare_pool_rankings, enrich_with_advancement_status

load_dotenv()


def _has_actual_de_data(de_bracket: dict) -> bool:
    """DE bracket에 실제 데이터가 있는지 확인 (is_in_progress만 있는 빈 bracket 제외)"""
    if not de_bracket or not isinstance(de_bracket, dict):
        return False
    # is_in_progress만 있는 빈 bracket은 False
    if de_bracket.get("is_in_progress"):
        return False
    # dual_de 구조
    if de_bracket.get("format") == "dual_de":
        return bool(de_bracket.get("first_de") or de_bracket.get("second_de"))
    # 일반 bracket: bouts/full_bouts에 실제 점수가 있는 경기가 있어야 실제 데이터
    bouts = de_bracket.get("full_bouts") or de_bracket.get("bouts") or []
    if bouts:
        return _has_scored_bouts(bouts)
    # bouts가 없어도 seeding만 있으면 데이터 있음 (DE 시작 전 시드 배정 단계)
    return bool(de_bracket.get("seeding"))


def _has_scored_bouts(bouts: list) -> bool:
    """bout 리스트에 실제 점수가 있는 경기가 존재하는지 확인"""
    if not bouts:
        return False
    for b in bouts:
        # 점수가 있거나, is_bye가 아닌 경기에 선수 이름이 있으면 유효
        p1_score = b.get("player1_score", 0) or 0
        p2_score = b.get("player2_score", 0) or 0
        if p1_score > 0 or p2_score > 0:
            return True
        # is_bye가 아닌 경기에 양쪽 선수 이름이 있으면 유효 (진행 중 경기)
        if not b.get("is_bye") and b.get("player1_name") and b.get("player2_name"):
            return True
    return False


def _de_data_quality_score(de_bracket: dict) -> int:
    """DE 데이터 품질 점수 (높을수록 좋음, 0=데이터 없음)

    점수 체계:
    0: 데이터 없음 / is_in_progress / 빈 골격만 있음
    1: seeding만 있음 (실제 선수 이름 포함)
    2: bout에 선수 이름은 있지만 점수 없음
    3: 실제 점수가 있는 bout 존재
    """
    if not de_bracket or not isinstance(de_bracket, dict):
        return 0
    if de_bracket.get("is_in_progress"):
        return 0

    # full_bouts, bouts, bouts_by_round 모두 확인
    bouts = de_bracket.get("full_bouts") or de_bracket.get("bouts") or []
    if not bouts:
        # bouts_by_round에만 데이터가 있을 수 있음
        bouts_by_round = de_bracket.get("bouts_by_round", {})
        if bouts_by_round:
            for round_bouts in bouts_by_round.values():
                if isinstance(round_bouts, list):
                    bouts.extend(round_bouts)

    if bouts and _has_scored_bouts(bouts):
        return 3
    if bouts:
        # bout이 있지만 점수 없음 → 실제 선수 데이터가 있는지 확인
        # 모든 bout이 빈 placeholder (이름 없음, is_bye)면 quality 0
        has_real_player = False
        for b in bouts:
            p1 = b.get("player1_name", "") or ""
            p2 = b.get("player2_name", "") or ""
            if (p1.strip() or p2.strip()) and not b.get("is_bye"):
                has_real_player = True
                break
        if has_real_player:
            return 2
        # 빈 placeholder bout만 있음 → 골격에 불과, quality 0
    # seeding 확인: 실제 선수 이름이 있는 seeding만 quality 1
    seeding = de_bracket.get("seeding", [])
    if seeding:
        named_seeds = [s for s in seeding if s.get("name")]
        if named_seeds:
            return 1
    return 0


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
    comp_idx: str = ""  # KFF 대회 코드 (예: COMPM00692)


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
                "comp_name, start_date, comp_idx"
            ).gte("start_date", two_years_ago).execute()

            # (대회명, 시작일) 튜플 + comp_idx 집합 - 이중 중복 체크
            self._existing_comps = {
                (row["comp_name"], row["start_date"][:10] if row.get("start_date") else None)
                for row in result.data
            }
            self._existing_comp_idxs = {
                row["comp_idx"] for row in result.data if row.get("comp_idx")
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
                        if len(cells) < 3:
                            continue

                        # 대회명 (cells[1]에 상태 뱃지 + 링크 포함)
                        name_cell = cells[1]
                        name_link = await name_cell.query_selector("a")
                        if not name_link:
                            continue
                        name = (await name_link.inner_text()).strip()

                        # comp_idx 추출: onclick="funcView('COMPM00692', '2')"
                        comp_idx = ""
                        onclick = await name_link.get_attribute("onclick") or ""
                        if "funcView" in onclick:
                            import re
                            m = re.search(r"funcView\('(COMP[^']+)'", onclick)
                            if m:
                                comp_idx = m.group(1)

                        # 상태 뱃지 (대회명 셀 내부 span/div)
                        status_text = ""
                        status_badge = await name_cell.query_selector("span, div:not(a)")
                        if status_badge:
                            badge_text = (await status_badge.inner_text()).strip()
                            # 상태 키워드만 추출 (대회명이 아닌 짧은 텍스트)
                            if badge_text and len(badge_text) <= 10:
                                status_text = badge_text

                        # 기간 (마지막 셀)
                        period_cell = cells[-1]
                        period_text = (await period_cell.inner_text()).strip()
                        start_date, end_date = self._parse_period(period_text)

                        if not start_date:
                            continue

                        competitions.append(DetectedCompetition(
                            name=name,
                            start_date=start_date,
                            end_date=end_date or start_date,
                            status=self._determine_status(start_date, end_date, status_text),
                            site_status=status_text,
                            comp_idx=comp_idx,
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

        # 새 대회 필터링 (comp_idx 또는 대회명+시작일로 중복 체크)
        new_competitions = []
        for comp in site_competitions:
            # comp_idx로 먼저 체크 (가장 정확)
            if comp.comp_idx and comp.comp_idx in self._existing_comp_idxs:
                continue
            comp_key = (comp.name, comp.start_date.isoformat())
            if comp_key not in self._existing_comps:
                new_competitions.append(comp)
                logger.info(f"🆕 새 대회 발견: {comp.name} ({comp.start_date} ~ {comp.end_date}) [{comp.comp_idx}]")

        return new_competitions

    async def register_new_competitions(self, competitions: List[DetectedCompetition]) -> int:
        """새 대회를 DB에 등록"""
        if not self.db or not competitions:
            return 0

        registered = 0

        for comp in competitions:
            try:
                data = {
                    "comp_idx": comp.comp_idx,
                    "comp_name": comp.name,
                    "start_date": comp.start_date.isoformat(),
                    "end_date": comp.end_date.isoformat(),
                    "status": comp.status,
                }

                result = self.db.table("competitions").insert(data).execute()

                if result.data:
                    registered += 1
                    logger.info(f"✅ 대회 등록: {comp.name}")

            except Exception as e:
                logger.error(f"대회 등록 실패 ({comp.name}): {e}")

        return registered

    async def run(self) -> Dict[str, Any]:
        """대회 감지 실행

        1. 새 대회 감지 → DB 등록
        2. 등록 성공 시 즉시 경량 종목+참가자 수집 (EventBasedScraper 사용)
        """
        logger.info("=== 대회 공고 감지 시작 ===")

        new_comps = await self.detect_new_competitions()
        registered = await self.register_new_competitions(new_comps)

        # 신규 대회 즉시 경량 수집 (종목 + 참가자)
        initial_events_created = 0
        if registered > 0:
            logger.info(f"📡 신규 대회 {registered}개 종목+참가자 즉시 수집 시작...")
            scraper = EventBasedScraper()

            # 등록된 대회를 DB에서 다시 조회 (id 포함)
            for comp in new_comps:
                try:
                    db_comp = self.db.table("competitions").select("*").eq(
                        "comp_idx", comp.comp_idx
                    ).execute()

                    if db_comp.data:
                        comp_data = db_comp.data[0]
                        created = await scraper._fetch_events_lightweight(comp_data)
                        initial_events_created += created
                        if created > 0:
                            await scraper._fetch_participants_force(comp_data)
                except Exception as e:
                    logger.warning(f"신규 대회 초기 수집 오류 ({comp.name}): {e}")

        result = {
            "detected": len(new_comps),
            "registered": registered,
            "initial_events_created": initial_events_created,
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
            logger.info(
                f"✅ {len(new_comps)}개 새 대회 감지, {registered}개 등록됨, "
                f"{initial_events_created}개 종목 즉시 수집"
            )
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
        """스크래핑할 대회 목록 조회

        카테고리:
        - upcoming: 7일 이내 시작 (이벤트 미등록 → 종목 목록 + 참가자 수집)
        - pre_competition: D-1/D-day (풀 대진표 수집)
        - ongoing: 진행 중 (실시간 스크래핑)
        - just_ended: 어제~3일 전 종료 (최종 결과)
        """
        if not self.db:
            self.db = get_supabase_client()
            if not self.db:
                return {"upcoming": [], "pre_competition": [], "ongoing": [], "just_ended": []}

        today = date.today()
        tomorrow = today + timedelta(days=1)
        week_later = today + timedelta(days=7)

        result = {
            "upcoming": [],         # 7일 이내 시작 (종목/참가자 사전 수집)
            "pre_competition": [],  # 내일 시작 또는 오늘 시작 (대진표 수집용)
            "ongoing": [],          # 진행 중 (실시간 스크래핑)
            "just_ended": [],       # 최근 종료 (최종 결과 스크래핑)
        }

        try:
            # 7일 이내 시작하는 대회 (종목 목록 + 참가자 사전 수집)
            upcoming = self.db.table("competitions").select("*").gt(
                "start_date", today.isoformat()
            ).lte(
                "start_date", week_later.isoformat()
            ).execute()
            result["upcoming"] = upcoming.data

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

            # 최근 3일 내 종료된 대회 (최종 결과 확정, 기존 1일→3일 확장)
            three_days_ago = today - timedelta(days=3)
            just_ended = self.db.table("competitions").select("*").lt(
                "end_date", today.isoformat()
            ).gte(
                "end_date", three_days_ago.isoformat()
            ).execute()
            result["just_ended"] = just_ended.data

            logger.info(
                f"📊 대회 현황: 예정={len(result['upcoming'])}, "
                f"대진표={len(result['pre_competition'])}, "
                f"진행중={len(result['ongoing'])}, "
                f"종료={len(result['just_ended'])}"
            )

        except Exception as e:
            logger.error(f"대회 조회 오류: {e}")

        return result

    async def _scrape_competition_direct(self, comp: Dict, scrape_type: str = "full") -> Dict[str, Any]:
        """
        comp_idx를 사용해 특정 대회만 직접 스크래핑 (전체 스캔 없이)

        Args:
            comp: 대회 정보 (comp_idx 필수)
            scrape_type: "full" (전체), "pool_only" (Pool 대진표만),
                         "results_only" (결과만), "events_only" (종목 목록만 - 경량)

        Returns:
            스크래핑 결과
        """
        comp_idx = comp.get("comp_idx")
        comp_name = comp.get("comp_name", "Unknown")
        comp_id = comp.get("id")

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

                # events_only 모드: 종목 레코드만 DB에 생성 (빈 raw_data)
                if scrape_type == "events_only":
                    events_saved = 0
                    for event in events:
                        try:
                            event_data = {
                                "competition_id": comp_id,
                                "event_cd": comp_idx,
                                "sub_event_cd": event.sub_event_cd,
                                "event_name": event.name,
                                "weapon": getattr(event, "weapon", ""),
                                "gender": getattr(event, "gender", ""),
                                "age_group": getattr(event, "age_group", ""),
                                "category": getattr(event, "event_type", "개인"),
                                "raw_data": {},
                            }
                            result = self.db.table("events").upsert(
                                event_data,
                                on_conflict="competition_id,event_cd,sub_event_cd"
                            ).execute()
                            if result.data:
                                events_saved += 1
                        except Exception as e:
                            logger.warning(f"  종목 저장 오류 ({event.name}): {e}")
                    return {
                        "success": True,
                        "comp_name": comp_name,
                        "events_found": len(events),
                        "events_saved": events_saved,
                    }

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
                        has_de = _has_actual_de_data(results.get("de_bracket", {}))
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

                # 기존 DB 데이터 조회 (participants, de_bracket 보존용)
                existing_raw = {}
                existing_de_format = None
                existing = self.db.table("events").select("raw_data, de_format").eq(
                    "competition_id", comp_id
                ).eq("sub_event_cd", event.sub_event_cd).execute()
                if existing.data:
                    existing_raw = existing.data[0].get("raw_data") or {}
                    existing_de_format = existing.data[0].get("de_format")
                    if isinstance(existing_raw, str):
                        import json
                        existing_raw = json.loads(existing_raw)

                # DE 데이터 보존 로직: 새 데이터가 기존보다 품질이 낮으면 기존 유지
                new_de_bracket = results.get("de_bracket", {})
                existing_de_bracket = existing_raw.get("de_bracket", {})
                new_quality = _de_data_quality_score(new_de_bracket)
                existing_quality = _de_data_quality_score(existing_de_bracket)

                if new_quality == 0 and existing_quality == 0:
                    # 양쪽 다 빈 데이터 → 빈 골격 저장 방지, 빈 dict로 유지
                    logger.debug(f"    ⏭️ DE 데이터 없음 (양쪽 품질=0) → 빈 bracket 유지 ({event.name})")
                    de_bracket_to_save = {}
                elif existing_quality > new_quality and new_quality < 3:
                    logger.warning(
                        f"    ⚠️ DE 데이터 보존: 기존(품질={existing_quality}) > 새(품질={new_quality}) "
                        f"→ 기존 DE 데이터 유지 ({event.name})"
                    )
                    de_bracket_to_save = existing_de_bracket
                elif new_quality == 0 and existing_quality > 0:
                    # 새 데이터가 빈 골격, 기존에 뭔가 있음 → 기존 유지
                    logger.warning(
                        f"    ⚠️ 새 DE 빈 데이터(품질=0), 기존(품질={existing_quality}) 유지 ({event.name})"
                    )
                    de_bracket_to_save = existing_de_bracket
                else:
                    de_bracket_to_save = new_de_bracket

                # === 풀 데이터 보존 정책 ===
                # KFF는 풀 종료 후 본선 미진출자를 삭제하므로,
                # 기존 풀 데이터가 더 완전하면 보존한다.
                new_pool_rounds = results.get("pool_rounds", [])
                new_pool_ranking = results.get("pool_total_ranking", [])
                existing_pool_rounds = existing_raw.get("pool_rounds", [])
                existing_pool_ranking = existing_raw.get("pool_total_ranking", [])

                # pool_rounds 보존: 기존이 있고 새것이 비거나 더 적으면 → 기존 유지
                if existing_pool_rounds and (
                    not new_pool_rounds or len(new_pool_rounds) < len(existing_pool_rounds)
                ):
                    logger.info(
                        f"    🛡️ pool_rounds 보존: 기존 {len(existing_pool_rounds)}개 풀 "
                        f"> 새 {len(new_pool_rounds)}개 ({event.name})"
                    )
                    pool_rounds_to_save = existing_pool_rounds
                else:
                    pool_rounds_to_save = new_pool_rounds

                # === 풀 종합 순위 정책 (2026-03-25) ===
                # pool_rounds가 있으면 자체 계산이 primary source (KFF는 탈락자 삭제하므로)
                # 스크래핑 데이터는 "진출" 상태 마킹에만 사용
                if pool_rounds_to_save:
                    calculated_ranking = calculate_pool_total_ranking(pool_rounds_to_save)
                    if calculated_ranking:
                        # 스크래핑 데이터에서 진출 상태 정보 병합
                        scraped_for_status = new_pool_ranking or existing_pool_ranking
                        if scraped_for_status:
                            calculated_ranking = enrich_with_advancement_status(
                                calculated_ranking, scraped_for_status
                            )
                        pool_ranking_to_save = calculated_ranking
                        logger.info(
                            f"    📊 pool_total_ranking 자체 계산: {len(calculated_ranking)}명 "
                            f"(스크래핑: {len(new_pool_ranking)}명) ({event.name})"
                        )
                    else:
                        # 계산 실패 시 기존 보존 정책 적용
                        if existing_pool_ranking and (
                            not new_pool_ranking or len(new_pool_ranking) < len(existing_pool_ranking)
                        ):
                            pool_ranking_to_save = existing_pool_ranking
                        else:
                            pool_ranking_to_save = new_pool_ranking
                else:
                    # pool_rounds 없으면 기존 보존 정책 적용
                    if existing_pool_ranking and (
                        not new_pool_ranking or len(new_pool_ranking) < len(existing_pool_ranking)
                    ):
                        logger.info(
                            f"    🛡️ pool_total_ranking 보존: 기존 {len(existing_pool_ranking)}명 "
                            f"> 새 {len(new_pool_ranking)}명 ({event.name})"
                        )
                        pool_ranking_to_save = existing_pool_ranking
                    else:
                        pool_ranking_to_save = new_pool_ranking

                # final_rankings 보존: 기존이 있고 새것이 비면 → 기존 유지
                new_final = results.get("final_rankings", [])
                existing_final = existing_raw.get("final_rankings", [])
                if existing_final and not new_final:
                    logger.info(
                        f"    🛡️ final_rankings 보존: 기존 {len(existing_final)}명 유지 ({event.name})"
                    )
                    final_to_save = existing_final
                else:
                    final_to_save = new_final

                # raw_data 구성
                raw_data = {
                    "pool_rounds": pool_rounds_to_save,
                    "pool_total_ranking": pool_ranking_to_save,
                    "de_bracket": de_bracket_to_save,
                    "de_matches": results.get("de_matches", []),
                    "final_rankings": final_to_save,
                }

                # Layer 3: 스크래핑 메타데이터 저장
                raw_data["_scrape_metadata"] = {
                    "scraped_at": datetime.now().isoformat(),
                    "scraper_version": "3.1",
                    "pool_diagnostics": results.get("_pool_diagnostics", {}),
                    "scrape_warnings": results.get("_scrape_warnings", []),
                    "duration_ms": results.get("_duration_ms", 0),
                }

                # 기존 DB 데이터에서 participants 보존
                if existing_raw.get("participants"):
                    raw_data["participants"] = existing_raw["participants"]

                # de_format 결정: 새 bracket에서 감지 or 기존 값 보존
                de_format = None
                if de_bracket_to_save.get("format") == "dual_de":
                    de_format = "dual_de"
                elif existing_de_format:
                    de_format = existing_de_format

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
                if de_format:
                    event_data["de_format"] = de_format

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

                # Layer 5: ERROR급 스크래핑 경고 시 Discord 알림
                scrape_warnings = results.get("_scrape_warnings", [])
                error_warnings = [w for w in scrape_warnings if w.get('severity') == 'ERROR']
                if error_warnings:
                    comp_name_for_alert = comp.get("name", "알 수 없는 대회")
                    for w in error_warnings:
                        try:
                            from app.discord_notify import send_alert
                            await send_alert(
                                severity="warning",
                                title="스크래핑 데이터 불완전",
                                message=w['message'],
                                fields=[
                                    {"name": "대회", "value": comp_name_for_alert, "inline": True},
                                    {"name": "종목", "value": w.get('event_name', ''), "inline": True},
                                    {"name": "유형", "value": w.get('type', ''), "inline": True},
                                ],
                            )
                        except Exception as notify_err:
                            logger.debug(f"Discord 알림 오류: {notify_err}")

            # 풀 종합 순위 비교 검증
            for item in events_to_save:
                event = item["event"]
                results = item["results"]
                scraped_pool_total = results.get("pool_total_ranking", [])
                pool_rounds = results.get("pool_rounds", [])

                if scraped_pool_total and pool_rounds:
                    try:
                        calculated = calculate_pool_total_ranking(pool_rounds)
                        comparison = compare_pool_rankings(calculated, scraped_pool_total)

                        if comparison["match"]:
                            logger.info(f"  ✅ 풀 순위 일치: {event.name} ({comparison['total_calculated']}명)")
                        else:
                            diffs = comparison["differences"]
                            missing_calc = comparison["missing_in_calculated"]
                            missing_scr = comparison["missing_in_scraped"]
                            logger.warning(
                                f"  ⚠️ 풀 순위 불일치: {event.name} | "
                                f"순위 차이 {len(diffs)}건, "
                                f"계산 누락 {len(missing_calc)}명, "
                                f"스크래핑 누락 {len(missing_scr)}명"
                            )
                            for d in diffs[:5]:  # 상위 5건만 로그
                                logger.warning(f"    {d['detail']}")
                    except Exception as e:
                        logger.debug(f"  풀 순위 비교 오류 ({event.name}): {e}")

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
            server_port = os.getenv("SERVER_PORT", "9071")
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"http://localhost:{server_port}/api/refresh-data",
                    headers={"X-Internal-Token": os.getenv("INTERNAL_API_TOKEN", "")},
                    timeout=60.0  # 데이터 로드에 시간이 걸릴 수 있음
                )
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"🔄 서버 캐시 새로고침 완료: {result.get('competitions', 0)}개 대회, {result.get('events', 0)}개 종목")
                else:
                    logger.warning(f"서버 캐시 새로고침 실패: {response.status_code}")
        except Exception as e:
            logger.warning(f"서버 캐시 새로고침 오류 (서버 접근 불가): {e}")

    @staticmethod
    def _parse_event_name(name: str) -> Dict[str, str]:
        """종목명에서 무기/성별/종류/나이그룹 파싱 (full_scraper 패턴 재사용)"""
        result = {"weapon": "", "gender": "", "event_type": "개인", "age_group": ""}

        if "플뢰레" in name or "플러레" in name:
            result["weapon"] = "foil"
        elif "에페" in name or "에뻬" in name:
            result["weapon"] = "epee"
        elif "사브르" in name:
            result["weapon"] = "sabre"

        if "남" in name:
            result["gender"] = "남"
        elif "여" in name:
            result["gender"] = "여"

        if "(단)" in name or "단체" in name:
            result["event_type"] = "단체"
        elif "(개)" in name or "개인" in name:
            result["event_type"] = "개인"

        for ap in ["U9", "U11", "U13", "U17", "U20"]:
            if ap in name:
                result["age_group"] = ap
                break
        if not result["age_group"]:
            if "대" in name:
                result["age_group"] = "대학"
            elif "일반" in name or "시니어" in name:
                result["age_group"] = "일반"

        return result

    async def _fetch_events_lightweight(self, comp: Dict) -> int:
        """종목 수집 (Playwright로 KFF 웹사이트의 SELECT 요소에서 추출)

        KFF API(SUB_EVENT_LIST_CNT)는 종목 수만 반환하고 리스트는 안 주므로,
        Playwright로 대회 페이지를 열어 <select> 요소에서 종목 목록을 추출한다.

        Args:
            comp: 대회 정보 (comp_idx, id 필수)

        Returns:
            생성/업데이트된 종목 수
        """
        comp_idx = comp.get("comp_idx")
        comp_id = comp.get("id")
        comp_name = comp.get("comp_name", "Unknown")

        if not comp_idx or not comp_id or not self.db:
            return 0

        if not PLAYWRIGHT_AVAILABLE:
            logger.warning(f"📡 {comp_name}: Playwright 미설치, 종목 수집 불가")
            return 0

        try:
            from scraper.full_scraper import KFFFullScraper

            async with KFFFullScraper(headless=True) as scraper:
                events = await scraper.get_events_direct(comp_idx)

            if not events:
                logger.debug(f"📡 {comp_name}: 종목 없음 (Playwright)")
                return 0

            events_saved = 0
            for event in events:
                try:
                    event_data = {
                        "competition_id": comp_id,
                        "event_cd": comp_idx,
                        "sub_event_cd": event.sub_event_cd,
                        "event_name": event.name,
                        "weapon": getattr(event, "weapon", ""),
                        "gender": getattr(event, "gender", ""),
                        "age_group": getattr(event, "age_group", ""),
                        "category": getattr(event, "event_type", "개인"),
                        "raw_data": {},
                    }
                    result = self.db.table("events").upsert(
                        event_data,
                        on_conflict="competition_id,event_cd,sub_event_cd"
                    ).execute()
                    if result.data:
                        events_saved += 1
                except Exception as e:
                    logger.warning(f"  종목 저장 오류 ({event.name}): {e}")

            # event_count 업데이트
            if events_saved > 0:
                self.db.table("competitions").update({
                    "event_count": events_saved,
                    "updated_at": datetime.now().isoformat(),
                }).eq("id", comp_id).execute()
                logger.info(f"📡 {comp_name}: {events_saved}개 종목 수집 (Playwright)")

            return events_saved

        except Exception as e:
            logger.warning(f"📡 종목 수집 오류 ({comp_name}): {e}")
            return 0

    @staticmethod
    def _participants_changed(old_participants: list, new_participants: list) -> bool:
        """참가자 리스트 변경 여부 비교 ({(name, team)} 집합 비교)"""
        old_set = {(p.get("name", ""), p.get("team", "")) for p in old_participants}
        new_set = {(p.get("name", ""), p.get("team", "")) for p in new_participants}
        return old_set != new_set

    async def _fetch_participants_force(self, comp: Dict) -> int:
        """참가자 강제 재수집 (이미 참가자가 있는 종목도 재수집)

        기존 _fetch_participants()와 달리, 기존 참가자가 있어도 재수집하고
        변경된 경우에만 DB를 업데이트한다.

        Args:
            comp: 대회 정보 (comp_idx, id 필수)

        Returns:
            업데이트된 종목 수
        """
        import json as json_module

        comp_idx = comp.get("comp_idx")
        comp_id = comp.get("id")
        comp_name = comp.get("comp_name", "Unknown")

        if not comp_idx or not comp_id or not self.db:
            return 0

        try:
            from scraper.client import KFFClient
            from scraper.config import Endpoints

            events = self.db.table("events").select(
                "id, event_name, sub_event_cd, raw_data"
            ).eq("competition_id", comp_id).execute()

            if not events.data:
                return 0

            updated = 0

            async with KFFClient() as client:
                for event in events.data:
                    try:
                        data = {"eventCd": comp_idx, "subEventCd": event["sub_event_cd"]}
                        response = await client._post(Endpoints.ENTER_PLAYER_LIST, data)
                        parsed = json_module.loads(response)

                        if isinstance(parsed, dict):
                            player_list = parsed.get("_TfEnterPlayerList", [])
                        elif isinstance(parsed, list):
                            player_list = parsed
                        else:
                            continue

                        # 새 참가자 리스트 구성
                        new_participants = []
                        for i, item in enumerate(player_list, 1):
                            name = item.get("plyNm", "")
                            team = item.get("teamNm", "")
                            if name:
                                new_participants.append({
                                    "num": str(i),
                                    "name": name,
                                    "team": team,
                                })

                        # 기존 참가자와 비교
                        raw_data = event.get("raw_data") or {}
                        if isinstance(raw_data, str):
                            raw_data = json_module.loads(raw_data)
                        old_participants = raw_data.get("participants", [])

                        # 참가자가 없으면 새 데이터만 있어도 저장, 있으면 변경 시에만
                        if not new_participants and not old_participants:
                            continue
                        if old_participants and not self._participants_changed(old_participants, new_participants):
                            continue

                        # 변경됨 → DB 업데이트
                        raw_data["participants"] = new_participants
                        self.db.table("events").update({
                            "raw_data": raw_data,
                        }).eq("id", event["id"]).execute()

                        updated += 1
                        await asyncio.sleep(0.3)

                    except Exception as e:
                        logger.warning(f"  참가자 재수집 오류 ({event['event_name']}): {e}")

            if updated > 0:
                logger.info(f"📡 {comp_name}: {updated}개 종목 참가자 업데이트")

            return updated

        except Exception as e:
            logger.warning(f"📡 참가자 강제 수집 오류 ({comp_name}): {e}")
            return 0

    async def monitor_future_competitions(self) -> Dict[str, Any]:
        """미래 대회 전체 모니터링

        start_date > today인 모든 대회를 조회하여:
        - 종목 없으면 → _fetch_events_lightweight() 호출
        - 종목 있으면 → _fetch_participants_force() 호출

        Returns:
            모니터링 결과 {competitions_checked, events_created, participants_updated, ...}
        """
        if not self.db:
            self.db = get_supabase_client()
            if not self.db:
                return {"error": "DB not available"}

        today = date.today()

        try:
            future_comps = self.db.table("competitions").select("*").gt(
                "start_date", today.isoformat()
            ).order("start_date").execute()

            if not future_comps.data:
                logger.debug("📡 미래 대회 없음")
                return {"competitions_checked": 0, "events_created": 0, "participants_updated": 0}

            logger.info(f"📡 미래 대회 모니터링: {len(future_comps.data)}개 대회")

            total_events_created = 0
            total_participants_updated = 0
            details = []

            for comp in future_comps.data:
                comp_name = comp.get("comp_name", "Unknown")
                comp_id = comp.get("id")
                comp_idx = comp.get("comp_idx")

                if not comp_idx or not comp_id:
                    continue

                # DB에서 이 대회의 종목 수 확인
                events = self.db.table("events").select("id").eq(
                    "competition_id", comp_id
                ).execute()

                event_count = len(events.data) if events.data else 0

                if event_count == 0:
                    # 종목 없음 → 경량 종목 수집
                    created = await self._fetch_events_lightweight(comp)
                    total_events_created += created
                    if created > 0:
                        # 종목 생성 후 참가자도 수집 시도
                        updated = await self._fetch_participants_force(comp)
                        total_participants_updated += updated
                    details.append({
                        "comp_name": comp_name,
                        "action": "events_created",
                        "events_created": created,
                    })
                else:
                    # 종목 있음 → 참가자 강제 재수집 (변경 감지)
                    updated = await self._fetch_participants_force(comp)
                    total_participants_updated += updated
                    details.append({
                        "comp_name": comp_name,
                        "action": "participants_checked",
                        "participants_updated": updated,
                    })

                # 대회 간 딜레이 (예의)
                await asyncio.sleep(1.0)

            result = {
                "competitions_checked": len(future_comps.data),
                "events_created": total_events_created,
                "participants_updated": total_participants_updated,
                "details": details,
                "checked_at": datetime.now().isoformat(),
            }

            if total_events_created > 0 or total_participants_updated > 0:
                logger.info(
                    f"📡 모니터링 완료: {len(future_comps.data)}개 대회, "
                    f"{total_events_created}개 종목 생성, "
                    f"{total_participants_updated}개 종목 참가자 업데이트"
                )
            else:
                logger.info(f"📡 모니터링 완료: {len(future_comps.data)}개 대회, 변경 없음")

            return result

        except Exception as e:
            logger.error(f"📡 미래 대회 모니터링 오류: {e}")
            return {"error": str(e)}

    async def scrape_pre_competition(self, competitions: List[Dict]) -> Dict[str, Any]:
        """
        대회 전 Pool 대진표 스크래핑
        - 대회 전날 또는 당일 09:00 이전에 실행
        - Pool 대진표 (참가자 명단, 풀 배정) 수집
        - 참가선수 명단도 함께 가져옴
        """
        if not competitions:
            return {"scraped": 0, "type": "pre_competition"}

        logger.info(f"📋 {len(competitions)}개 대회 대진표 사전 스크래핑")

        results = []

        for comp in competitions:
            # 1. 참가선수 명단 가져오기 (풀 대진표 전에 먼저)
            await self._fetch_participants(comp)

            # 2. Pool 대진표 스크래핑
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

    async def _fetch_participants(self, comp: Dict) -> None:
        """대회의 참가선수 명단 가져오기 (KFF API 직접 호출)"""
        import json as json_module
        comp_idx = comp.get("comp_idx")
        comp_id = comp.get("id")
        comp_name = comp.get("comp_name", "Unknown")

        if not comp_idx or not comp_id or not self.db:
            return

        try:
            from scraper.client import KFFClient
            from scraper.config import Endpoints

            # 참가자 없는 종목 조회
            events = self.db.table("events").select(
                "id, event_name, sub_event_cd, raw_data"
            ).eq("competition_id", comp_id).execute()

            if not events.data:
                return

            events_to_fetch = []
            for event in events.data:
                raw_data = event.get("raw_data") or {}
                if isinstance(raw_data, str):
                    raw_data = json_module.loads(raw_data)
                participants = raw_data.get("participants")
                if not participants or len(participants) == 0:
                    events_to_fetch.append(event)

            if not events_to_fetch:
                logger.debug(f"📋 {comp_name}: 모든 종목 참가자 데이터 있음")
                return

            logger.info(f"👤 {comp_name}: {len(events_to_fetch)}개 종목 참가자 가져오기")

            async with KFFClient() as client:
                fetched = 0
                for event in events_to_fetch:
                    try:
                        data = {"eventCd": comp_idx, "subEventCd": event["sub_event_cd"]}
                        response = await client._post(Endpoints.ENTER_PLAYER_LIST, data)
                        parsed = json_module.loads(response)

                        if isinstance(parsed, dict):
                            player_list = parsed.get("_TfEnterPlayerList", [])
                        elif isinstance(parsed, list):
                            player_list = parsed
                        else:
                            continue

                        if not player_list:
                            continue

                        participants = []
                        for i, item in enumerate(player_list, 1):
                            name = item.get("plyNm", "")
                            team = item.get("teamNm", "")
                            if name:
                                participants.append({
                                    "num": str(i),
                                    "name": name,
                                    "team": team
                                })

                        if not participants:
                            continue

                        # raw_data에 participants 추가 (기존 데이터 보존)
                        raw_data = event.get("raw_data") or {}
                        if isinstance(raw_data, str):
                            raw_data = json_module.loads(raw_data)
                        raw_data["participants"] = participants

                        self.db.table("events").update({
                            "raw_data": raw_data
                        }).eq("id", event["id"]).execute()

                        fetched += 1
                        await asyncio.sleep(0.3)

                    except Exception as e:
                        logger.warning(f"  참가자 가져오기 오류 ({event['event_name']}): {e}")

                if fetched > 0:
                    logger.info(f"  ✅ {comp_name}: {fetched}개 종목 참가자 저장")

        except Exception as e:
            logger.warning(f"참가자 가져오기 전체 오류 ({comp_name}): {e}")

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
                        has_de = _has_actual_de_data(results.get("de_bracket", {}))
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
                        has_de = _has_actual_de_data(results.get("de_bracket", {}))
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

        # 스크래핑 완료 후 서버 캐시 자동 새로고침
        if total_events > 0:
            await self._refresh_server_cache()

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
