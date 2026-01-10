"""
증분 스크래퍼 (Incremental Scraper)
- Supabase에 없는 새 대회만 스크래핑
- 새 대회 데이터를 Supabase에 직접 저장
- 스케줄러와 연동하여 자동 업데이트
"""
import asyncio
import random
import os
from datetime import datetime
from typing import List, Dict, Any, Optional, Set
from playwright.async_api import async_playwright, Browser, Page
from loguru import logger
from supabase import create_client, Client

# 환경변수
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://tjfjuasvjzjawyckengv.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# 스로틀링 설정
REQUEST_DELAY_MIN = 3.0
REQUEST_DELAY_MAX = 5.0
PAGE_LOAD_DELAY = 2.0


async def throttle_request():
    """봇 탐지 방지를 위한 랜덤 딜레이"""
    delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
    logger.debug(f"스로틀링: {delay:.1f}초 대기")
    await asyncio.sleep(delay)


class IncrementalScraper:
    """증분 스크래퍼 - 새 대회만 스크래핑하여 Supabase에 저장"""

    BASE_URL = "https://fencing.sports.or.kr"

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._browser: Optional[Browser] = None
        self._playwright = None
        self._supabase: Optional[Client] = None
        self._existing_comps: Set[str] = set()  # 이미 DB에 있는 comp_idx들

    async def __aenter__(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)

        # Supabase 연결
        if SUPABASE_KEY:
            self._supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            await self._load_existing_competitions()
        else:
            logger.warning("SUPABASE_KEY가 설정되지 않았습니다. Supabase 저장이 비활성화됩니다.")

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def _load_existing_competitions(self):
        """Supabase에서 기존 대회 목록 로드"""
        try:
            result = self._supabase.table("competitions").select("comp_idx").execute()
            self._existing_comps = {row["comp_idx"] for row in result.data}
            logger.info(f"기존 대회 {len(self._existing_comps)}개 로드됨")
        except Exception as e:
            logger.error(f"기존 대회 로드 실패: {e}")

    async def get_competition_list_from_site(self, start_year: int = 2025, end_year: int = 2025) -> List[Dict[str, Any]]:
        """펜싱협회 사이트에서 대회 목록 가져오기"""
        competitions = []
        context = await self._browser.new_context()
        page = await context.new_page()

        try:
            await page.goto(f"{self.BASE_URL}/game/compList", timeout=30000)
            await asyncio.sleep(PAGE_LOAD_DELAY)

            for year in range(start_year, end_year + 1):
                logger.info(f"{year}년도 대회 목록 수집 중...")

                # 연도 선택
                await page.select_option("select[name='yyyy']", str(year))
                await throttle_request()

                # 대회 목록 파싱
                rows = await page.query_selector_all("table tbody tr")
                for row in rows:
                    try:
                        link = await row.query_selector("a[href*='compListView']")
                        if not link:
                            continue

                        href = await link.get_attribute("href")
                        comp_idx = self._extract_comp_idx(href)
                        if not comp_idx:
                            continue

                        name_elem = await row.query_selector("td:nth-child(2)")
                        date_elem = await row.query_selector("td:nth-child(3)")
                        venue_elem = await row.query_selector("td:nth-child(4)")

                        name = await name_elem.inner_text() if name_elem else ""
                        date_text = await date_elem.inner_text() if date_elem else ""
                        venue = await venue_elem.inner_text() if venue_elem else ""

                        start_date, end_date = self._parse_date_range(date_text)

                        competitions.append({
                            "comp_idx": comp_idx,
                            "comp_name": name.strip(),
                            "start_date": start_date,
                            "end_date": end_date,
                            "venue": venue.strip(),
                            "year": year
                        })
                    except Exception as e:
                        logger.warning(f"대회 행 파싱 오류: {e}")
                        continue

            logger.info(f"총 {len(competitions)}개 대회 발견")

        except Exception as e:
            logger.error(f"대회 목록 수집 오류: {e}")
        finally:
            await context.close()

        return competitions

    def _extract_comp_idx(self, href: str) -> Optional[str]:
        """href에서 eventCd 추출"""
        import re
        match = re.search(r'eventCd=([A-Z0-9]+)', href)
        return match.group(1) if match else None

    def _parse_date_range(self, date_text: str) -> tuple:
        """날짜 범위 파싱 (예: '2025.12.15 ~ 2025.12.21')"""
        import re
        dates = re.findall(r'(\d{4})\.(\d{2})\.(\d{2})', date_text)
        if len(dates) >= 2:
            start = f"{dates[0][0]}-{dates[0][1]}-{dates[0][2]}"
            end = f"{dates[1][0]}-{dates[1][1]}-{dates[1][2]}"
            return start, end
        elif len(dates) == 1:
            date = f"{dates[0][0]}-{dates[0][1]}-{dates[0][2]}"
            return date, date
        return None, None

    def find_new_competitions(self, site_comps: List[Dict]) -> List[Dict]:
        """사이트 대회 목록에서 Supabase에 없는 새 대회 찾기"""
        new_comps = []
        for comp in site_comps:
            if comp["comp_idx"] not in self._existing_comps:
                new_comps.append(comp)
                logger.info(f"새 대회 발견: {comp['comp_name']} ({comp['comp_idx']})")

        logger.info(f"새 대회 {len(new_comps)}개 / 전체 {len(site_comps)}개")
        return new_comps

    async def scrape_competition(self, comp: Dict) -> Dict[str, Any]:
        """개별 대회 스크래핑 (종목, 결과 포함)"""
        context = await self._browser.new_context()
        page = await context.new_page()

        result = {
            "competition": comp,
            "events": [],
            "matches": [],
            "rankings": []
        }

        try:
            url = f"{self.BASE_URL}/game/compListView?code=game&eventCd={comp['comp_idx']}&gubun=2&pageNum=1"
            await page.goto(url, timeout=30000)
            await asyncio.sleep(PAGE_LOAD_DELAY)

            # 종목 목록 수집
            events = await self._scrape_events(page, comp["comp_idx"])
            result["events"] = events

            # 각 종목별 결과 수집
            for event in events[:10]:  # 최대 10개 종목만 (속도 고려)
                await throttle_request()
                event_result = await self._scrape_event_results(page, event)
                result["matches"].extend(event_result.get("matches", []))
                result["rankings"].extend(event_result.get("rankings", []))

            logger.info(f"대회 스크래핑 완료: {comp['comp_name']} - 종목 {len(events)}개, 경기 {len(result['matches'])}개")

        except Exception as e:
            logger.error(f"대회 스크래핑 오류 ({comp['comp_idx']}): {e}")
        finally:
            await context.close()

        return result

    async def _scrape_events(self, page: Page, comp_idx: str) -> List[Dict]:
        """종목 목록 스크래핑"""
        events = []
        try:
            options = await page.query_selector_all("select#subEventCd option")
            for opt in options:
                value = await opt.get_attribute("value")
                text = await opt.inner_text()
                if value and value != "":
                    weapon, gender, age_group = self._parse_event_name(text)
                    events.append({
                        "event_cd": comp_idx,
                        "sub_event_cd": value,
                        "event_name": text.strip(),
                        "weapon": weapon,
                        "gender": gender,
                        "age_group": age_group
                    })
        except Exception as e:
            logger.warning(f"종목 목록 파싱 오류: {e}")
        return events

    def _parse_event_name(self, name: str) -> tuple:
        """종목명에서 무기/성별/연령대 추출"""
        weapon = ""
        gender = ""
        age_group = ""

        if "플러레" in name or "플뢰레" in name:
            weapon = "플뢰레"
        elif "에뻬" in name or "에페" in name:
            weapon = "에페"
        elif "사브르" in name:
            weapon = "사브르"

        if "남" in name:
            gender = "남"
        elif "여" in name:
            gender = "여"

        if "초등" in name:
            age_group = "초등"
        elif "중등" in name or "중학" in name:
            age_group = "중등"
        elif "고등" in name or "고교" in name:
            age_group = "고등"
        elif "대학" in name:
            age_group = "대학"
        elif "일반" in name or "실업" in name:
            age_group = "일반"

        return weapon, gender, age_group

    async def _scrape_event_results(self, page: Page, event: Dict) -> Dict:
        """종목별 결과 스크래핑 (간소화된 버전)"""
        result = {"matches": [], "rankings": []}

        try:
            # 종목 선택
            await page.select_option("select#subEventCd", event["sub_event_cd"])
            await asyncio.sleep(1)

            # 최종 순위 탭 클릭 및 파싱
            final_tab = await page.query_selector("button:has-text('순위'), a:has-text('순위')")
            if final_tab:
                await final_tab.click()
                await asyncio.sleep(0.5)

                rows = await page.query_selector_all("table tbody tr")
                for row in rows:
                    cols = await row.query_selector_all("td")
                    if len(cols) >= 3:
                        rank = await cols[0].inner_text()
                        name = await cols[1].inner_text()
                        team = await cols[2].inner_text() if len(cols) > 2 else ""

                        try:
                            result["rankings"].append({
                                "event_cd": event["event_cd"],
                                "sub_event_cd": event["sub_event_cd"],
                                "rank": int(rank.strip()) if rank.strip().isdigit() else 0,
                                "name": name.strip(),
                                "team": team.strip()
                            })
                        except:
                            continue

        except Exception as e:
            logger.warning(f"종목 결과 파싱 오류 ({event['sub_event_cd']}): {e}")

        return result

    async def save_to_supabase(self, data: Dict) -> bool:
        """스크래핑 결과를 Supabase에 저장"""
        if not self._supabase:
            logger.warning("Supabase 연결이 없어 저장을 건너뜁니다.")
            return False

        try:
            comp = data["competition"]

            # 1. 대회 저장
            comp_data = {
                "comp_idx": comp["comp_idx"],
                "comp_name": comp["comp_name"],
                "start_date": comp.get("start_date"),
                "end_date": comp.get("end_date"),
                "venue": comp.get("venue"),
                "status": "completed"
            }

            result = self._supabase.table("competitions").upsert(
                comp_data, on_conflict="comp_idx"
            ).execute()

            if not result.data:
                logger.error(f"대회 저장 실패: {comp['comp_idx']}")
                return False

            comp_id = result.data[0]["id"]
            logger.info(f"대회 저장됨: {comp['comp_name']} (ID: {comp_id})")

            # 2. 종목 저장
            events_saved = 0
            event_id_map = {}  # sub_event_cd -> event_id

            for event in data["events"]:
                event_data = {
                    "competition_id": comp_id,
                    "event_cd": event["event_cd"],
                    "sub_event_cd": event["sub_event_cd"],
                    "event_name": event["event_name"],
                    "weapon": event.get("weapon"),
                    "gender": event.get("gender"),
                    "age_group": event.get("age_group")
                }

                try:
                    result = self._supabase.table("events").upsert(
                        event_data, on_conflict="competition_id,event_cd,sub_event_cd"
                    ).execute()

                    if result.data:
                        event_id_map[event["sub_event_cd"]] = result.data[0]["id"]
                        events_saved += 1
                except Exception as e:
                    logger.warning(f"종목 저장 오류: {e}")

            logger.info(f"종목 {events_saved}개 저장됨")

            # 3. 순위 저장
            rankings_saved = 0
            for ranking in data["rankings"]:
                event_id = event_id_map.get(ranking["sub_event_cd"])
                if not event_id:
                    continue

                # 선수 조회/생성
                player_result = self._supabase.table("players").upsert(
                    {"player_name": ranking["name"], "team_name": ranking["team"]},
                    on_conflict="player_name,team_name"
                ).execute()

                player_id = player_result.data[0]["id"] if player_result.data else None

                ranking_data = {
                    "event_id": event_id,
                    "player_id": player_id,
                    "player_name": ranking["name"],
                    "team_name": ranking["team"],
                    "rank_position": ranking["rank"]
                }

                try:
                    self._supabase.table("rankings").upsert(
                        ranking_data, on_conflict="event_id,player_id"
                    ).execute()
                    rankings_saved += 1
                except Exception as e:
                    logger.warning(f"순위 저장 오류: {e}")

            logger.info(f"순위 {rankings_saved}개 저장됨")

            # 기존 대회 목록에 추가
            self._existing_comps.add(comp["comp_idx"])

            return True

        except Exception as e:
            logger.error(f"Supabase 저장 오류: {e}")
            return False

    async def run_incremental_scrape(self, start_year: int = 2025, end_year: int = 2025) -> Dict[str, Any]:
        """증분 스크래핑 실행"""
        stats = {
            "started_at": datetime.now().isoformat(),
            "new_competitions_found": 0,
            "competitions_scraped": 0,
            "competitions_saved": 0,
            "events_scraped": 0,
            "errors": []
        }

        try:
            # 1. 사이트에서 대회 목록 가져오기
            logger.info(f"대회 목록 수집 중... ({start_year}-{end_year})")
            site_comps = await self.get_competition_list_from_site(start_year, end_year)

            # 2. 새 대회 필터링
            new_comps = self.find_new_competitions(site_comps)
            stats["new_competitions_found"] = len(new_comps)

            if not new_comps:
                logger.info("새 대회가 없습니다.")
                return stats

            # 3. 각 새 대회 스크래핑 및 저장
            for comp in new_comps:
                try:
                    logger.info(f"스크래핑: {comp['comp_name']}")
                    data = await self.scrape_competition(comp)
                    stats["competitions_scraped"] += 1
                    stats["events_scraped"] += len(data["events"])

                    # Supabase에 저장
                    if await self.save_to_supabase(data):
                        stats["competitions_saved"] += 1

                    await throttle_request()

                except Exception as e:
                    error_msg = f"대회 처리 오류 ({comp['comp_idx']}): {e}"
                    logger.error(error_msg)
                    stats["errors"].append(error_msg)

        except Exception as e:
            logger.error(f"증분 스크래핑 실패: {e}")
            stats["errors"].append(str(e))

        stats["completed_at"] = datetime.now().isoformat()
        logger.info(f"증분 스크래핑 완료: {stats}")

        return stats


async def run_incremental_update(start_year: int = 2025, end_year: int = 2025):
    """증분 업데이트 실행 (외부 호출용)"""
    async with IncrementalScraper() as scraper:
        return await scraper.run_incremental_scrape(start_year, end_year)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="증분 스크래퍼")
    parser.add_argument("--start-year", type=int, default=2025, help="시작 연도")
    parser.add_argument("--end-year", type=int, default=2025, help="종료 연도")
    args = parser.parse_args()

    asyncio.run(run_incremental_update(args.start_year, args.end_year))
