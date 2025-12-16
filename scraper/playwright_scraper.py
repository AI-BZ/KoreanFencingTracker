"""
Playwright 기반 대한펜싱협회 스크래퍼
JavaScript 렌더링이 필요한 페이지 처리
"""
import asyncio
import json
import re
from datetime import datetime, date
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from playwright.async_api import async_playwright, Browser, Page
from loguru import logger
import aiohttp
from bs4 import BeautifulSoup


@dataclass
class Competition:
    """대회 정보"""
    event_cd: str
    name: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: str = ""
    location: str = ""
    category: str = ""  # 전문/동호인


@dataclass
class Event:
    """종목 정보"""
    event_cd: str
    sub_event_cd: str
    name: str
    weapon: str = ""  # 플러레/에뻬/사브르
    gender: str = ""  # 남/여
    event_type: str = ""  # 개인/단체


@dataclass
class PoolResult:
    """풀 라운드 결과"""
    pool_number: int
    piste: str
    time: str
    referee: str
    results: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class DEMatch:
    """엘리미나시옹 디렉트(본선) 경기"""
    round_name: str
    player1_name: str
    player1_team: str
    player1_score: int
    player2_name: str
    player2_team: str
    player2_score: int
    winner: str = ""


@dataclass
class FinalRanking:
    """최종 순위"""
    rank: int
    player_name: str
    team_name: str


class KFFPlaywrightScraper:
    """대한펜싱협회 Playwright 스크래퍼"""

    BASE_URL = "https://fencing.sports.or.kr"

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._browser: Optional[Browser] = None
        self._playwright = None

    async def __aenter__(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    # ==================== 대회 목록 (HTML 파싱) ====================

    async def get_competitions(self, page: int = 1, status: str = "") -> Tuple[List[Competition], int]:
        """대회 목록 조회 (aiohttp 사용 - JavaScript 불필요)"""
        url = f"{self.BASE_URL}/game/compList"
        params = {"code": "game", "pageNum": page}
        if status:
            params["searchStatus"] = status

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                html = await resp.text()

        return self._parse_competition_list(html)

    def _parse_competition_list(self, html: str) -> Tuple[List[Competition], int]:
        """대회 목록 HTML 파싱"""
        soup = BeautifulSoup(html, "lxml")
        competitions = []

        table = soup.find("table", class_="list")
        if not table:
            return [], 0

        rows = table.find_all("tr")[1:]  # 헤더 제외
        for row in rows:
            cols = row.find_all("td")
            if len(cols) >= 3:
                try:
                    # <a> 태그의 onclick에서 eventCd 추출
                    link = row.find("a")
                    onclick = link.get("onclick", "") if link else ""
                    event_cd = self._extract_event_cd(onclick)

                    # 상태 추출 (span class="stat_txt")
                    status_span = cols[1].find("span")
                    status = status_span.get_text(strip=True) if status_span else ""

                    # 대회명
                    name = link.get_text(strip=True) if link else cols[1].get_text(strip=True)

                    # 날짜
                    date_range = cols[2].get_text(strip=True)
                    start_date, end_date = self._parse_date_range(date_range)

                    if event_cd:
                        competitions.append(Competition(
                            event_cd=event_cd,
                            name=name,
                            start_date=start_date,
                            end_date=end_date,
                            status=status
                        ))
                except Exception as e:
                    logger.error(f"대회 파싱 오류: {e}")

        # 총 페이지 수
        total_pages = self._extract_total_pages(soup)

        return competitions, total_pages

    def _extract_event_cd(self, onclick: str) -> str:
        """onclick에서 eventCd 추출"""
        match = re.search(r"funcView\(['\"]?(\w+)['\"]?", onclick)
        return match.group(1) if match else ""

    def _parse_date_range(self, date_range: str) -> Tuple[Optional[date], Optional[date]]:
        """날짜 범위 파싱 (YYYY.MM.DD 또는 YYYY-MM-DD)"""
        # YYYY-MM-DD 형식
        match = re.search(r"(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})", date_range)
        if match:
            start = datetime.strptime(match.group(1), "%Y-%m-%d").date()
            end = datetime.strptime(match.group(2), "%Y-%m-%d").date()
            return start, end

        # YYYY.MM.DD 형식
        match = re.search(r"(\d{4}\.\d{2}\.\d{2})\s*~\s*(\d{4}\.\d{2}\.\d{2})", date_range)
        if match:
            start = datetime.strptime(match.group(1), "%Y.%m.%d").date()
            end = datetime.strptime(match.group(2), "%Y.%m.%d").date()
            return start, end

        return None, None

    def _extract_total_pages(self, soup: BeautifulSoup) -> int:
        """총 페이지 수 추출"""
        # 마지막페이지 링크 찾기
        last_link = soup.find("a", string=re.compile("마지막"))
        if last_link:
            onclick = last_link.get("onclick", "")
            match = re.search(r"funcPage\((\d+)\)", onclick)
            if match:
                return int(match.group(1))
        return 1

    async def get_all_competitions(self, start_year: int = None, end_year: int = None) -> List[Competition]:
        """Playwright로 모든 페이지에서 대회 목록 수집 (연도 제한 없음)"""
        all_competitions = []
        page_obj = await self._browser.new_page()
        consecutive_empty_pages = 0
        MAX_EMPTY_PAGES = 3  # 연속 빈 페이지 최대 허용 횟수

        try:
            await page_obj.goto(f"{self.BASE_URL}/game/compList?code=game", wait_until="networkidle")
            page_num = 1

            while True:
                # 현재 페이지 대회 수집
                comps_data = await page_obj.evaluate("""
                    () => {
                        const rows = document.querySelectorAll('table.list tr');
                        const results = [];

                        rows.forEach((row) => {
                            const cells = row.querySelectorAll('td');
                            if (cells.length >= 3) {
                                const link = row.querySelector('a');
                                const onclick = link?.getAttribute('onclick') || '';
                                const match = onclick.match(/funcView\\(['"]?(\\w+)['"]?/);
                                const eventCd = match ? match[1] : '';

                                // 상태 추출
                                const statusSpan = cells[1].querySelector('span');
                                const status = statusSpan?.textContent?.trim() || '';

                                results.push({
                                    eventCd: eventCd,
                                    name: link?.textContent?.trim() || '',
                                    date: cells[2]?.textContent?.trim() || '',
                                    status: status
                                });
                            }
                        });

                        return results;
                    }
                """)

                # Competition 객체로 변환
                for data in comps_data:
                    if data['eventCd']:
                        start_date, end_date = self._parse_date_range(data['date'])
                        all_competitions.append(Competition(
                            event_cd=data['eventCd'],
                            name=data['name'],
                            start_date=start_date,
                            end_date=end_date,
                            status=data['status']
                        ))

                logger.info(f"페이지 {page_num}: {len(comps_data)}개 대회")

                # 빈 페이지 체크 - 연속 빈 페이지가 MAX_EMPTY_PAGES 이상이면 종료
                if len(comps_data) == 0:
                    consecutive_empty_pages += 1
                    if consecutive_empty_pages >= MAX_EMPTY_PAGES:
                        logger.info(f"연속 {MAX_EMPTY_PAGES}개 빈 페이지 - 수집 완료")
                        break
                else:
                    consecutive_empty_pages = 0  # 리셋

                # 다음 페이지로 이동
                try:
                    next_btn = page_obj.locator("a:has-text('다음페이지')")
                    is_visible = await next_btn.is_visible()

                    if not is_visible:
                        break

                    await next_btn.click()
                    await page_obj.wait_for_timeout(1500)
                    page_num += 1

                except Exception as e:
                    logger.debug(f"마지막 페이지 도달: {e}")
                    break

        except Exception as e:
            logger.error(f"대회 목록 수집 오류: {e}")
        finally:
            await page_obj.close()

        # 연도 필터링 (선택적)
        if start_year and end_year:
            filtered = [
                c for c in all_competitions
                if c.start_date and start_year <= c.start_date.year <= end_year
            ]
            logger.info(f"총 {len(filtered)}개 대회 ({start_year}-{end_year})")
            return filtered

        logger.info(f"총 {len(all_competitions)}개 대회 (전체)")
        return all_competitions

    # ==================== 종목 조회 (Playwright) ====================

    async def get_events(self, event_cd: str, page_num: int = 1) -> List[Event]:
        """대회의 종목 목록 조회 (Playwright 사용)

        Args:
            event_cd: 대회 코드
            page_num: 대회가 있는 페이지 번호 (1부터 시작)
        """
        page = await self._browser.new_page()
        events = []

        # 짧은 타임아웃 설정 (10초)
        page.set_default_timeout(10000)

        try:
            # 대회 목록 페이지에서 시작 (JavaScript 상태 유지를 위해)
            await page.goto(f"{self.BASE_URL}/game/compList?code=game", wait_until="domcontentloaded", timeout=10000)

            # 해당 페이지로 이동 (1페이지가 아닌 경우)
            if page_num > 1:
                for _ in range(page_num - 1):
                    try:
                        next_btn = page.locator("a:has-text('다음페이지')")
                        await next_btn.click(timeout=3000)
                        await page.wait_for_timeout(1000)
                    except:
                        break

            # 해당 대회 클릭 (eventCd로 찾기)
            try:
                # onclick 속성에 eventCd가 있는 링크 클릭
                await page.click(f"a[onclick*=\"{event_cd}\"]", timeout=5000)
                await page.wait_for_timeout(1500)
            except Exception as click_err:
                logger.debug(f"클릭 실패 (page {page_num}): {click_err}")
                # 현재 페이지에 없으면 다음 페이지에서 시도
                try:
                    next_btn = page.locator("a:has-text('다음페이지')")
                    await next_btn.click(timeout=3000)
                    await page.wait_for_timeout(1000)
                    await page.click(f"a[onclick*=\"{event_cd}\"]", timeout=5000)
                    await page.wait_for_timeout(1500)
                except:
                    # 마지막 수단: URL 직접 이동 (작동 안 할 수 있음)
                    return events

            # 경기결과 탭 클릭 (종목 SELECT가 나타남)
            try:
                result_tab = page.locator("a:has-text('경기결과')")
                await result_tab.click(timeout=3000)
                await page.wait_for_timeout(1500)
            except:
                pass  # 탭이 없을 수 있음

            # SELECT 옵션에서 종목 코드 추출 (COMPS로 시작하는 것만)
            options = await page.evaluate("""
                () => {
                    const selects = document.querySelectorAll('select');
                    for (const select of selects) {
                        const opts = Array.from(select.options)
                            .map(opt => ({ value: opt.value, text: opt.textContent.trim() }))
                            .filter(opt => opt.value && opt.value.startsWith('COMPS'));
                        if (opts.length > 0) return opts;
                    }
                    return [];
                }
            """)

            for opt in options:
                sub_event_cd = opt["value"]
                name = opt["text"]

                # 종목 정보 파싱 (예: "남대 플러레(개)")
                weapon, gender, event_type = self._parse_event_name(name)

                events.append(Event(
                    event_cd=event_cd,
                    sub_event_cd=sub_event_cd,
                    name=name,
                    weapon=weapon,
                    gender=gender,
                    event_type=event_type
                ))

        except Exception as e:
            logger.error(f"종목 조회 오류 ({event_cd}): {e}")
        finally:
            await page.close()

        return events

    def _parse_event_name(self, name: str) -> Tuple[str, str, str]:
        """종목명에서 무기/성별/유형 추출"""
        weapon = ""
        gender = ""
        event_type = ""

        if "플러레" in name:
            weapon = "플러레"
        elif "에뻬" in name:
            weapon = "에뻬"
        elif "사브르" in name:
            weapon = "사브르"

        if "남" in name:
            gender = "남"
        elif "여" in name:
            gender = "여"

        if "(개)" in name or "개인" in name:
            event_type = "개인"
        elif "(단)" in name or "단체" in name:
            event_type = "단체"

        return weapon, gender, event_type

    # ==================== 경기 결과 조회 (Playwright) ====================

    async def get_match_results(self, event_cd: str, sub_event_cd: str) -> Dict[str, Any]:
        """종목별 경기 결과 조회"""
        page = await self._browser.new_page()
        results = {
            "pool_results": [],
            "de_matches": [],
            "final_rankings": []
        }

        try:
            # 대회 상세 페이지 접속
            url = f"{self.BASE_URL}/game/compListView?eventCd={event_cd}&sMenu=2"
            await page.goto(url, wait_until="networkidle")

            # 경기결과 탭 클릭
            try:
                result_tab = page.locator("a:has-text('경기결과')")
                await result_tab.click()
                await page.wait_for_timeout(500)
            except:
                pass

            # 종목 선택
            try:
                select = page.locator("select").first
                await select.select_option(value=sub_event_cd)
                await page.wait_for_timeout(1000)

                # 검색 버튼 클릭
                search_btn = page.locator("a:has-text('검색')")
                await search_btn.click()
                await page.wait_for_timeout(1000)
            except Exception as e:
                logger.debug(f"종목 선택 중 오류: {e}")

            # 풀 라운드 결과 파싱
            results["pool_results"] = await self._parse_pool_results(page)

            # 엘리미나시옹 디렉트 결과 (별도 탭)
            try:
                de_tab = page.locator("a:has-text('엘리미나시옹디렉트')")
                await de_tab.click()
                await page.wait_for_timeout(1000)
                results["de_matches"] = await self._parse_de_results(page)
            except:
                pass

            # 최종 순위
            try:
                rank_link = page.locator("a:has-text('뿔 최종 랭킹')")
                await rank_link.click()
                await page.wait_for_timeout(500)
                results["final_rankings"] = await self._parse_final_rankings(page)
            except:
                pass

        except Exception as e:
            logger.error(f"경기 결과 조회 오류 ({event_cd}/{sub_event_cd}): {e}")
        finally:
            await page.close()

        return results

    async def _parse_pool_results(self, page: Page) -> List[Dict]:
        """풀 라운드 결과 파싱"""
        pools = []

        try:
            # 페이지의 모든 풀 테이블 파싱
            pool_data = await page.evaluate("""
                () => {
                    const pools = [];
                    const tables = document.querySelectorAll('table');

                    tables.forEach((table, idx) => {
                        // 풀 결과 테이블인지 확인 (헤더에 No, 이름, 소속팀 등이 있는지)
                        const headers = table.querySelectorAll('th');
                        const headerTexts = Array.from(headers).map(h => h.textContent.trim());

                        if (headerTexts.includes('이름') && headerTexts.includes('소속팀')) {
                            const results = [];
                            const rows = table.querySelectorAll('tbody tr, tr:not(:first-child)');

                            rows.forEach(row => {
                                const cells = row.querySelectorAll('td');
                                if (cells.length >= 5) {
                                    results.push({
                                        no: cells[0]?.textContent?.trim() || '',
                                        name: cells[1]?.textContent?.trim() || '',
                                        team: cells[2]?.textContent?.trim() || '',
                                        win_rate: cells[cells.length - 4]?.textContent?.trim() || '',
                                        index: cells[cells.length - 3]?.textContent?.trim() || '',
                                        score: cells[cells.length - 2]?.textContent?.trim() || '',
                                        rank: cells[cells.length - 1]?.textContent?.trim() || ''
                                    });
                                }
                            });

                            if (results.length > 0) {
                                pools.push({ pool_number: pools.length + 1, results: results });
                            }
                        }
                    });

                    return pools;
                }
            """)

            pools = pool_data

        except Exception as e:
            logger.error(f"풀 결과 파싱 오류: {e}")

        return pools

    async def _parse_de_results(self, page: Page) -> List[Dict]:
        """엘리미나시옹 디렉트 결과 파싱"""
        matches = []

        try:
            match_data = await page.evaluate("""
                () => {
                    const matches = [];
                    // DE 결과 파싱 로직
                    // 토너먼트 구조에 따라 다르게 처리 필요
                    return matches;
                }
            """)
            matches = match_data
        except Exception as e:
            logger.error(f"DE 결과 파싱 오류: {e}")

        return matches

    async def _parse_final_rankings(self, page: Page) -> List[Dict]:
        """최종 순위 파싱"""
        rankings = []

        try:
            ranking_data = await page.evaluate("""
                () => {
                    const rankings = [];
                    // 최종 랭킹 모달/레이어 파싱
                    const modal = document.querySelector('[id*="ranking"], [class*="ranking"]');
                    if (modal) {
                        const rows = modal.querySelectorAll('tr');
                        rows.forEach(row => {
                            const cells = row.querySelectorAll('td');
                            if (cells.length >= 3) {
                                rankings.push({
                                    rank: cells[0]?.textContent?.trim() || '',
                                    name: cells[1]?.textContent?.trim() || '',
                                    team: cells[2]?.textContent?.trim() || ''
                                });
                            }
                        });
                    }
                    return rankings;
                }
            """)
            rankings = ranking_data
        except Exception as e:
            logger.error(f"최종 순위 파싱 오류: {e}")

        return rankings

    # ==================== 전체 데이터 수집 ====================

    async def scrape_competition(self, comp: Competition) -> Dict[str, Any]:
        """단일 대회의 전체 데이터 수집"""
        data = {
            "competition": asdict(comp),
            "events": [],
            "results": {}
        }

        # 종목 목록 조회
        events = await self.get_events(comp.event_cd)
        data["events"] = [asdict(e) for e in events]

        # 각 종목별 경기 결과 수집
        for event in events:
            logger.info(f"  종목: {event.name}")
            results = await self.get_match_results(comp.event_cd, event.sub_event_cd)
            data["results"][event.sub_event_cd] = results
            await asyncio.sleep(0.5)  # 서버 부하 방지

        return data

    async def scrape_all(self, start_year: int = None, end_year: int = None,
                         output_file: str = "fencing_data.json",
                         events_only: bool = False,
                         start_index: int = None, end_index: int = None) -> None:
        """전체 대회 데이터 수집 및 저장

        Args:
            start_year: 시작 연도 (None이면 전체)
            end_year: 종료 연도 (None이면 전체)
            output_file: 출력 파일 경로
            events_only: True면 경기 결과 없이 종목만 수집 (빠름)
            start_index: 시작 인덱스 (1부터 시작, None이면 처음부터)
            end_index: 끝 인덱스 (포함, None이면 끝까지)
        """
        # 대회 목록 조회
        competitions = await self.get_all_competitions(start_year, end_year)

        # 인덱스로 필터링 (1-based index)
        original_start_idx = 0
        if start_index is not None or end_index is not None:
            original_start_idx = (start_index - 1) if start_index else 0
            end_idx = end_index if end_index else len(competitions)
            competitions = competitions[original_start_idx:end_idx]
            logger.info(f"인덱스 필터링: {start_index or 1}-{end_index or '끝'} ({len(competitions)}개)")

        year_range = f"{start_year}-{end_year}" if start_year and end_year else "전체"
        all_data = {
            "meta": {
                "scraped_at": datetime.now().isoformat(),
                "year_range": year_range,
                "index_range": f"{start_index or 1}-{end_index or 'end'}",
                "total_competitions": len(competitions),
                "events_only": events_only
            },
            "competitions": []
        }

        # 각 대회별 데이터 수집
        for i, comp in enumerate(competitions):
            # 실제 원본 인덱스 계산 (페이지 번호용)
            original_idx = original_start_idx + i
            # 페이지 번호 계산 (10개씩)
            page_num = (original_idx // 10) + 1
            logger.info(f"[{original_idx+1}/236] {comp.name} (page {page_num})")

            try:
                if events_only:
                    # 종목만 수집 (빠름)
                    comp_data = {
                        "competition": asdict(comp),
                        "events": [],
                        "results": {}
                    }
                    events = await self.get_events(comp.event_cd, page_num=page_num)
                    comp_data["events"] = [asdict(e) for e in events]
                    logger.info(f"  -> {len(events)}개 종목")
                else:
                    # 전체 결과 수집 (느림)
                    comp_data = await self.scrape_competition(comp)

                all_data["competitions"].append(comp_data)

                # 중간 저장 (10개마다)
                if (i + 1) % 10 == 0:
                    with open(output_file, "w", encoding="utf-8") as f:
                        json.dump(all_data, f, ensure_ascii=False, indent=2, default=str)
                    logger.info(f"중간 저장 완료: {output_file}")

            except Exception as e:
                logger.error(f"대회 스크래핑 실패 ({comp.name}): {e}")

            await asyncio.sleep(0.5)  # 서버 부하 방지

        # 최종 저장
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(all_data, f, ensure_ascii=False, indent=2, default=str)

        logger.info(f"스크래핑 완료: {output_file}")


# CLI 실행
async def main():
    """메인 실행 함수"""
    import argparse

    parser = argparse.ArgumentParser(description="대한펜싱협회 대회 데이터 스크래퍼")
    parser.add_argument("--start-year", type=int, default=None, help="시작 연도 (없으면 전체)")
    parser.add_argument("--end-year", type=int, default=None, help="종료 연도 (없으면 전체)")
    parser.add_argument("--start-index", type=int, default=None, help="시작 인덱스 (1부터, 예: 108)")
    parser.add_argument("--end-index", type=int, default=None, help="끝 인덱스 (포함, 예: 236)")
    parser.add_argument("--output", type=str, default="fencing_data.json", help="출력 파일")
    parser.add_argument("--headless", action="store_true", default=True, help="헤드리스 모드")
    parser.add_argument("--events-only", action="store_true", help="종목만 수집 (경기결과 제외, 빠름)")

    args = parser.parse_args()

    async with KFFPlaywrightScraper(headless=args.headless) as scraper:
        await scraper.scrape_all(
            start_year=args.start_year,
            end_year=args.end_year,
            output_file=args.output,
            events_only=args.events_only,
            start_index=args.start_index,
            end_index=args.end_index
        )


if __name__ == "__main__":
    asyncio.run(main())
