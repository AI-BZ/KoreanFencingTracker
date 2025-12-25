"""
개선된 대한펜싱협회 스크래퍼 v2.1
- 풀 결과 점수 매트릭스 전체 파싱
- 최종 순위 파싱
- 풀 개별 경기(bout) 추출
- 선수 정규화
- 스로틀링 적용 (3-5초 간격)
"""
import asyncio
import json
import re
import random
from datetime import datetime, date
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from playwright.async_api import async_playwright, Browser, Page
from loguru import logger
import aiohttp
from bs4 import BeautifulSoup

# DE Scraper v4 import
from scraper.de_scraper_v4 import DEScraper

# ============================================
# 스로틀링 설정 (봇 차단 방지)
# ============================================
REQUEST_DELAY_MIN = 3.0  # 최소 대기 시간 (초)
REQUEST_DELAY_MAX = 5.0  # 최대 대기 시간 (초)
PAGE_LOAD_DELAY = 2.0    # 페이지 로드 후 대기 (초)


async def throttle_request():
    """요청 간 랜덤 딜레이 (사람처럼 보이게)"""
    delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
    logger.debug(f"스로틀링: {delay:.1f}초 대기")
    await asyncio.sleep(delay)


@dataclass
class Competition:
    """대회 정보"""
    event_cd: str
    name: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: str = ""
    location: str = ""
    category: str = ""
    page_num: int = 1  # 이 대회가 위치한 페이지 번호


@dataclass
class Event:
    """종목 정보"""
    event_cd: str
    sub_event_cd: str
    name: str
    weapon: str = ""
    gender: str = ""
    event_type: str = ""
    age_group: str = ""
    total_participants: int = 0


@dataclass
class PoolResult:
    """풀 라운드 선수 결과"""
    position: int
    name: str
    team: str
    scores: List[Optional[str]]  # [None, "V", 4, "V", ...] - 자기 자신은 None
    wins: int
    losses: int
    indicator: int
    touches: int
    rank: int


@dataclass
class PoolBout:
    """풀 개별 경기"""
    player1_name: str
    player1_team: str
    player2_name: str
    player2_team: str
    player1_score: int
    player2_score: int
    winner_name: str


@dataclass
class Pool:
    """풀 정보"""
    round_number: int
    pool_number: int
    piste: str
    time: str
    referee: str
    results: List[PoolResult] = field(default_factory=list)
    bouts: List[PoolBout] = field(default_factory=list)


@dataclass
class FinalRanking:
    """최종 순위"""
    rank: int
    name: str
    team: str


@dataclass
class DEMatch:
    """엘리미나시옹디렉트 개별 경기"""
    round_name: str  # 64강, 32강, 16강, 8강, 준결승, 결승
    match_number: int
    player1_seed: int
    player1_name: str
    player1_team: str
    player2_seed: int
    player2_name: str
    player2_team: str
    player1_score: int
    player2_score: int
    winner_name: str
    winner_seed: int


class KFFFullScraper:
    """개선된 대한펜싱협회 스크래퍼"""

    BASE_URL = "https://fencing.sports.or.kr"

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._browser: Optional[Browser] = None
        self._playwright = None
        self._players: Dict[str, int] = {}  # "이름_팀" -> player_id
        self._player_counter = 0

    async def __aenter__(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    def _get_player_id(self, name: str, team: str) -> int:
        """선수 고유 ID 반환 (이름+팀 조합)"""
        key = f"{name}_{team}"
        if key not in self._players:
            self._player_counter += 1
            self._players[key] = self._player_counter
        return self._players[key]

    # ==================== 대회 목록 ====================

    async def get_all_competitions(self, start_year: int = None, end_year: int = None) -> List[Competition]:
        """모든 대회 목록 수집"""
        all_competitions = []
        page_obj = await self._browser.new_page()
        consecutive_empty_pages = 0
        MAX_EMPTY_PAGES = 3

        try:
            await page_obj.goto(f"{self.BASE_URL}/game/compList?code=game", wait_until="networkidle")
            page_num = 1

            while True:
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

                for data in comps_data:
                    if data['eventCd']:
                        start_date, end_date = self._parse_date_range(data['date'])
                        all_competitions.append(Competition(
                            event_cd=data['eventCd'],
                            name=data['name'],
                            start_date=start_date,
                            end_date=end_date,
                            status=data['status'],
                            page_num=page_num  # 이 대회가 위치한 실제 페이지 번호 저장
                        ))

                logger.info(f"페이지 {page_num}: {len(comps_data)}개 대회")

                if len(comps_data) == 0:
                    consecutive_empty_pages += 1
                    if consecutive_empty_pages >= MAX_EMPTY_PAGES:
                        break
                else:
                    consecutive_empty_pages = 0

                try:
                    next_btn = page_obj.locator("a:has-text('다음페이지')")
                    is_visible = await next_btn.is_visible()
                    if not is_visible:
                        break
                    await next_btn.click()
                    await page_obj.wait_for_timeout(1500)
                    await throttle_request()  # 스로틀링 적용
                    page_num += 1
                except:
                    break

        finally:
            await page_obj.close()

        # 연도 필터링
        if start_year and end_year:
            filtered = [c for c in all_competitions if c.start_date and start_year <= c.start_date.year <= end_year]
            logger.info(f"총 {len(filtered)}개 대회 ({start_year}-{end_year})")
            return filtered

        logger.info(f"총 {len(all_competitions)}개 대회")
        return all_competitions

    def _parse_date_range(self, date_range: str) -> Tuple[Optional[date], Optional[date]]:
        """날짜 범위 파싱"""
        match = re.search(r"(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})", date_range)
        if match:
            return (datetime.strptime(match.group(1), "%Y-%m-%d").date(),
                    datetime.strptime(match.group(2), "%Y-%m-%d").date())

        match = re.search(r"(\d{4}\.\d{2}\.\d{2})\s*~\s*(\d{4}\.\d{2}\.\d{2})", date_range)
        if match:
            return (datetime.strptime(match.group(1), "%Y.%m.%d").date(),
                    datetime.strptime(match.group(2), "%Y.%m.%d").date())

        return None, None

    # ==================== 종목 조회 ====================

    async def get_events(self, event_cd: str, page_num: int = 1) -> List[Event]:
        """대회의 종목 목록 조회"""
        page = await self._browser.new_page()
        events = []
        page.set_default_timeout(15000)

        try:
            logger.debug(f"get_events: {event_cd}, page_num={page_num}")
            await page.goto(f"{self.BASE_URL}/game/compList?code=game", wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(1500)

            # 페이지 이동
            if page_num > 1:
                for i in range(page_num - 1):
                    try:
                        next_btn = page.locator("a:has-text('다음페이지')")
                        await next_btn.click(timeout=5000)
                        await page.wait_for_timeout(1500)
                        logger.debug(f"  페이지 {i+2}로 이동")
                    except Exception as e:
                        logger.warning(f"  페이지 이동 실패: {e}")
                        break

            # 대회 클릭
            try:
                link = page.locator(f"a[onclick*=\"{event_cd}\"]")
                link_count = await link.count()
                logger.debug(f"  대회 링크 수: {link_count}")
                if link_count == 0:
                    logger.warning(f"  대회 링크 없음: {event_cd}")
                    return events
                await link.first.click(timeout=7000)
                await page.wait_for_timeout(2000)
                await throttle_request()  # 스로틀링 적용
            except Exception as e:
                logger.warning(f"  대회 클릭 실패 ({event_cd}): {e}")
                return events

            # 경기결과 탭 클릭 (onclick 속성으로 정확히 탭만 선택)
            try:
                result_tab = page.locator("a[onclick*='funcLeftSub']:has-text('경기결과')").first
                tab_count = await result_tab.count()
                if tab_count > 0:
                    await result_tab.click(timeout=5000)
                    await page.wait_for_timeout(2000)
                    logger.debug(f"  경기결과 탭 클릭 성공")
                else:
                    logger.debug(f"  경기결과 탭 없음")
            except Exception as e:
                logger.debug(f"  경기결과 탭 클릭 실패: {e}")

            # SELECT에서 종목 추출
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
            logger.debug(f"  종목 수: {len(options)}")

            for opt in options:
                weapon, gender, event_type, age_group = self._parse_event_name(opt["text"])
                events.append(Event(
                    event_cd=event_cd,
                    sub_event_cd=opt["value"],
                    name=opt["text"],
                    weapon=weapon,
                    gender=gender,
                    event_type=event_type,
                    age_group=age_group
                ))

        except Exception as e:
            logger.error(f"종목 조회 오류 ({event_cd}): {e}")
        finally:
            await page.close()

        return events

    def _parse_event_name(self, name: str) -> Tuple[str, str, str, str]:
        """종목명 파싱: 무기, 성별, 유형, 연령대"""
        weapon = ""
        gender = ""
        event_type = ""
        age_group = ""

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

        # 연령대 추출
        age_patterns = ["U9", "U11", "U13", "U17", "U20"]
        for ap in age_patterns:
            if ap in name:
                age_group = ap
                break
        if not age_group:
            if "대" in name:
                age_group = "대학"
            elif "일반" in name or "시니어" in name:
                age_group = "일반"

        return weapon, gender, event_type, age_group

    # ==================== 경기 결과 조회 ====================

    async def get_full_results(self, event_cd: str, sub_event_cd: str, page_num: int = 1) -> Dict[str, Any]:
        """종목별 전체 경기 결과 조회 (풀 + 순위)"""
        page = await self._browser.new_page()
        page.set_default_timeout(15000)

        results = {
            "pool_rounds": [],
            "pool_total_ranking": [],
            "de_bracket": {},
            "de_matches": [],
            "final_rankings": [],
            "total_participants": 0
        }

        try:
            # 대회 목록에서 시작
            await page.goto(f"{self.BASE_URL}/game/compList?code=game", wait_until="domcontentloaded", timeout=10000)

            # 페이지 이동
            if page_num > 1:
                for _ in range(page_num - 1):
                    try:
                        next_btn = page.locator("a:has-text('다음페이지')")
                        await next_btn.click(timeout=3000)
                        await page.wait_for_timeout(1000)
                    except:
                        break

            # 대회 클릭
            await page.click(f"a[onclick*=\"{event_cd}\"]", timeout=5000)
            await page.wait_for_timeout(1500)
            await throttle_request()  # 스로틀링 적용

            # 경기결과 탭 클릭 (onclick 속성으로 정확히 탭만 선택, PDF 링크 제외)
            result_tab = page.locator("a[onclick*='funcLeftSub']:has-text('경기결과')").first
            await result_tab.click(timeout=3000)
            await page.wait_for_timeout(1500)

            # 종목 선택
            try:
                select = page.locator("select").first
                await select.select_option(value=sub_event_cd)
                await page.wait_for_timeout(1000)

                # 첫 번째 검색 버튼 클릭 (href="#search" 속성)
                search_btn = page.locator("a[href='#search']").first
                await search_btn.click()
                await page.wait_for_timeout(1500)
            except Exception as e:
                logger.debug(f"종목 선택 오류: {e}")

            # 풀 결과 파싱
            pool_data = await self._parse_pool_results_v2(page)
            results["pool_rounds"] = pool_data

            # 뿔 최종 랭킹 (Pool Total) 파싱
            pool_total = await self._parse_pool_total_ranking(page)
            results["pool_total_ranking"] = pool_total

            # ============================================================
            # 1. "경기결과" → "엘리미나시옹디렉트" 에서 최종 순위 수집
            # ============================================================
            try:
                # 먼저 팝업이 열려있으면 닫기
                await page.evaluate("""
                    const popups = document.querySelectorAll('.layer_pop, #layer_final_ranking, [id*="layer"]');
                    popups.forEach(p => p.style.display = 'none');
                """)
                await page.wait_for_timeout(300)

                de_tab = page.locator("a:has-text('엘리미나시옹디렉트')").first
                await de_tab.click(timeout=5000, force=True)
                await page.wait_for_timeout(1000)

                # 최종 순위 수집 (경기결과 탭의 엘리미나시옹디렉트 하위)
                results["final_rankings"] = await self._parse_final_rankings_v2(page)
                results["total_participants"] = len(results["final_rankings"])
                logger.info(f"최종 순위 수집: {len(results['final_rankings'])}명")
            except Exception as e:
                logger.debug(f"최종 순위 파싱 오류: {e}")

            # ============================================================
            # 2. "대진표" 탭 클릭 → "엘리미나시옹디렉트" 에서 실제 대진표 트리 수집
            # ============================================================
            try:
                # 팝업 닫기
                await page.evaluate("""
                    const popups = document.querySelectorAll('.layer_pop, #layer_final_ranking, [id*="layer"]');
                    popups.forEach(p => p.style.display = 'none');
                """)
                await page.wait_for_timeout(300)

                # "대진표" 메인 탭 클릭 (경기결과, 대진표 중 대진표 선택)
                bracket_main_tab = page.locator("a:has-text('대진표')").first
                await bracket_main_tab.click(timeout=5000, force=True)
                await page.wait_for_timeout(1500)
                logger.info("대진표 메인 탭 클릭 완료")

                # 종목 다시 선택 (탭 전환 시 초기화될 수 있음)
                try:
                    select = page.locator("select").first
                    await select.select_option(value=sub_event_cd)
                    await page.wait_for_timeout(500)

                    search_btn = page.locator("a[href='#search']").first
                    await search_btn.click()
                    await page.wait_for_timeout(1000)
                except Exception as e:
                    logger.debug(f"대진표 탭에서 종목 선택 오류: {e}")

                # "엘리미나시옹디렉트" 서브 탭 클릭 (대진표 탭 하위)
                de_bracket_tab = page.locator("a:has-text('엘리미나시옹디렉트')").first
                await de_bracket_tab.click(timeout=5000, force=True)
                await page.wait_for_timeout(1500)
                logger.info("Direct Elimination 대진표 탭 클릭 완료")

                # 실제 대진표 트리 데이터 수집 (v3: 전체 브래킷 구조 분석)
                bracket_data = await self._parse_de_bracket_v3(page)
                results["de_bracket"] = bracket_data

                # bouts를 de_matches로도 저장 (호환성 유지)
                bouts = bracket_data.get("bouts", [])
                de_matches = bracket_data.get("match_results", [])
                results["de_matches"] = de_matches

                rounds_found = bracket_data.get("rounds", [])
                logger.info(f"엘리미나시옹디렉트 대진표 수집 완료: {len(bouts)}개 경기, 라운드: {rounds_found}, 시드: {len(bracket_data.get('seeding', []))}명")
            except Exception as e:
                logger.debug(f"대진표 파싱 오류: {e}")

        except Exception as e:
            logger.error(f"결과 조회 오류 ({event_cd}/{sub_event_cd}): {e}")
        finally:
            await page.close()

        return results

    async def get_de_only(self, event_cd: str, sub_event_cd: str, page_num: int = 1) -> Dict[str, Any]:
        """DE 데이터만 수집 (보완 스크래핑용)"""
        results = {
            "de_bracket": {},
            "de_matches": []
        }

        page = await self._browser.new_page()
        page.set_default_timeout(15000)

        try:
            # 대회 목록에서 시작 (get_full_results와 동일)
            await page.goto(f"{self.BASE_URL}/game/compList?code=game", wait_until="domcontentloaded", timeout=10000)

            # 페이지 이동
            if page_num > 1:
                for _ in range(page_num - 1):
                    try:
                        next_btn = page.locator("a:has-text('다음페이지')")
                        await next_btn.click(timeout=3000)
                        await page.wait_for_timeout(1000)
                    except:
                        break

            # 대회 클릭
            await page.click(f"a[onclick*=\"{event_cd}\"]", timeout=5000)
            await page.wait_for_timeout(1500)

            # 경기결과 탭 클릭
            result_tab = page.locator("a[onclick*='funcLeftSub']:has-text('경기결과')").first
            await result_tab.click(timeout=3000)
            await page.wait_for_timeout(1500)

            # 종목 선택
            select = page.locator("select").first
            await select.select_option(value=sub_event_cd)
            await page.wait_for_timeout(500)

            search_btn = page.locator("a[href='#search']").first
            await search_btn.click()
            await page.wait_for_timeout(1500)

            # 대진표 탭 클릭
            bracket_main_tab = page.locator("a:has-text('대진표')").first
            await bracket_main_tab.click(timeout=5000, force=True)
            await page.wait_for_timeout(1500)

            # 종목 다시 선택
            try:
                select = page.locator("select").first
                await select.select_option(value=sub_event_cd)
                await page.wait_for_timeout(500)

                search_btn = page.locator("a[href='#search']").first
                await search_btn.click()
                await page.wait_for_timeout(1000)
            except Exception:
                pass

            # 엘리미나시옹디렉트 탭 클릭
            de_bracket_tab = page.locator("a:has-text('엘리미나시옹디렉트')").first
            await de_bracket_tab.click(timeout=5000, force=True)
            await page.wait_for_timeout(1500)

            # DE 데이터 파싱 (v3: 전체 브래킷 구조 분석)
            bracket_data = await self._parse_de_bracket_v3(page)
            results["de_bracket"] = bracket_data
            results["de_matches"] = bracket_data.get("match_results", [])

            bouts = bracket_data.get("bouts", [])
            rounds_found = bracket_data.get("rounds", [])
            logger.debug(f"DE 수집: {len(bouts)}개 경기, 라운드: {rounds_found}")

        except Exception as e:
            logger.debug(f"DE 수집 오류 ({event_cd}/{sub_event_cd}): {e}")
        finally:
            await page.close()

        return results

    async def _parse_pool_results_v2(self, page: Page) -> List[Dict]:
        """개선된 풀 결과 파싱 v3 - 정확한 풀 구분 및 점수 매트릭스"""
        try:
            pool_data = await page.evaluate("""
                () => {
                    const pools = [];
                    let roundNumber = 1;

                    // 풀 헤더 UL 요소들 찾기 (뿔 N 텍스트를 포함하는 UL)
                    const allUls = document.querySelectorAll('ul');
                    const poolHeaders = [];

                    allUls.forEach(ul => {
                        const firstLi = ul.querySelector('li');
                        if (firstLi) {
                            const text = firstLi.textContent.trim();
                            // "뿔" 텍스트와 숫자가 포함된 UL만 선택
                            const poolMatch = text.match(/뿔\\s*(\\d+)/);
                            if (poolMatch) {
                                poolHeaders.push({
                                    ul: ul,
                                    poolNumber: parseInt(poolMatch[1])
                                });
                            }
                        }
                    });

                    // 각 풀 헤더에 대해 바로 다음 테이블 파싱
                    poolHeaders.forEach(({ ul, poolNumber }) => {
                        // 풀 메타 정보 추출
                        let poolInfo = { piste: '', time: '', referee: '' };
                        const items = ul.querySelectorAll('li');
                        items.forEach(item => {
                            const text = item.textContent.trim();
                            if (text.includes('삐스트')) {
                                poolInfo.piste = text.replace(/삐스트\\s*/, '').trim();
                            }
                            if (text.includes('시간')) {
                                poolInfo.time = text.replace(/시간\\s*/, '').trim();
                            }
                            if (text.includes('심판')) {
                                poolInfo.referee = text.replace(/심판\\s*/, '').trim();
                            }
                        });

                        // UL 바로 다음 테이블 찾기
                        let nextElem = ul.nextElementSibling;
                        while (nextElem && nextElem.tagName !== 'TABLE') {
                            nextElem = nextElem.nextElementSibling;
                        }

                        if (!nextElem || nextElem.tagName !== 'TABLE') return;

                        const table = nextElem;
                        const results = [];
                        const players = [];

                        // 테이블 헤더 확인
                        const headers = table.querySelectorAll('th');
                        const headerTexts = Array.from(headers).map(h => h.textContent.trim());

                        // 풀 결과 테이블인지 확인
                        if (!headerTexts.includes('이름') || !headerTexts.includes('승률')) return;

                        // 상대 수 계산 (헤더에서 숫자 컬럼 개수)
                        const numericHeaders = headerTexts.filter(h => /^\\d+$/.test(h));
                        const numOpponents = numericHeaders.length;

                        // tbody의 tr만 선택 (thead 제외)
                        let rows;
                        const tbody = table.querySelector('tbody');
                        if (tbody) {
                            rows = tbody.querySelectorAll('tr');
                        } else {
                            // tbody가 없으면 th가 없는 tr만 선택
                            rows = Array.from(table.querySelectorAll('tr')).filter(
                                tr => tr.querySelector('td') && !tr.querySelector('th')
                            );
                        }

                        rows.forEach((row, rowIdx) => {
                            const cells = row.querySelectorAll('td');
                            if (cells.length < 10) return; // 최소 컬럼 수 확인

                            const no = parseInt(cells[0]?.textContent?.trim()) || rowIdx + 1;
                            const name = cells[1]?.textContent?.trim() || '';
                            const team = cells[2]?.textContent?.trim() || '';

                            // 이름이 비어있거나 숫자만 있으면 건너뛰기
                            if (!name || /^\\d+$/.test(name)) return;

                            // 점수 배열 추출 (3번 인덱스부터 상대 수만큼)
                            const scores = [];
                            for (let i = 0; i < numOpponents; i++) {
                                const scoreCell = cells[3 + i];
                                let scoreText = scoreCell?.textContent?.trim() || '';

                                // 대각선 위치 (자기 자신)는 항상 null - 위치 기반으로만 판단
                                // i는 0-indexed, no는 1-indexed이므로 i === (no - 1)
                                if (i === (no - 1)) {
                                    scores.push(null);  // 자기 자신 (대각선)
                                } else if (scoreText.toUpperCase().startsWith('V')) {
                                    // V, V3, V5 등 (승리)
                                    const vScore = scoreText.length === 1 ? 5 : parseInt(scoreText.substring(1)) || 5;
                                    scores.push({ type: 'V', score: vScore });
                                } else if (scoreText === '' || scoreText === '-') {
                                    // 빈 셀 (대각선 아님) - 패배 0점 또는 경기 미진행으로 처리
                                    scores.push({ type: 'L', score: 0 });
                                } else {
                                    // 숫자 (패배 점수)
                                    scores.push({ type: 'L', score: parseInt(scoreText) || 0 });
                                }
                            }

                            // 승률, 지수, 득점, 랭킹 파싱 (마지막 4개 컬럼)
                            const lastCells = Array.from(cells).slice(-4);
                            const winRateText = lastCells[0]?.textContent?.trim() || '0/0';
                            const winRateParts = winRateText.split('/');
                            const wins = parseInt(winRateParts[0]) || 0;
                            const total = parseInt(winRateParts[1]) || 0;
                            const losses = total - wins;

                            const indicator = parseInt(lastCells[1]?.textContent?.trim()) || 0;
                            const touches = parseInt(lastCells[2]?.textContent?.trim()) || 0;
                            const rank = parseInt(lastCells[3]?.textContent?.trim()) || 0;

                            players.push({ no, name, team, scores });

                            results.push({
                                position: no,
                                name: name,
                                team: team,
                                scores: scores,
                                wins: wins,
                                losses: losses,
                                indicator: indicator,
                                touches: touches,
                                rank: rank
                            });
                        });

                        // 개별 bout 추출
                        const bouts = [];
                        for (let i = 0; i < players.length; i++) {
                            for (let j = i + 1; j < players.length; j++) {
                                const p1 = players[i];
                                const p2 = players[j];

                                // p1의 j번째 상대 점수 확인
                                if (p1.scores[j] && p1.scores[j] !== null) {
                                    const score1 = p1.scores[j].score;
                                    const score2 = (p2.scores[i] && p2.scores[i] !== null) ? p2.scores[i].score : 0;
                                    const winner = p1.scores[j].type === 'V' ? p1.name : p2.name;

                                    bouts.push({
                                        player1_name: p1.name,
                                        player1_team: p1.team,
                                        player2_name: p2.name,
                                        player2_team: p2.team,
                                        player1_score: score1,
                                        player2_score: score2,
                                        winner_name: winner
                                    });
                                }
                            }
                        }

                        pools.push({
                            round_number: roundNumber,
                            pool_number: poolNumber,
                            piste: poolInfo.piste,
                            time: poolInfo.time,
                            referee: poolInfo.referee,
                            results: results,
                            bouts: bouts
                        });
                    });

                    // 풀 번호로 정렬
                    pools.sort((a, b) => a.pool_number - b.pool_number);

                    return pools;
                }
            """)

            return pool_data

        except Exception as e:
            logger.error(f"풀 결과 파싱 오류: {e}")
            return []

    async def _parse_pool_total_ranking(self, page: Page) -> List[Dict]:
        """뿔 최종 랭킹 (Pool Total) 파싱 - 최종랭킹(진출) + 탈락자랭킹 모두 추출"""
        try:
            all_rankings = []

            # 뿔 최종 랭킹 링크 클릭하여 팝업 열기
            pool_total_link = page.locator("a:has-text('뿔 최종 랭킹')")
            await pool_total_link.click(timeout=3000)
            await page.wait_for_timeout(500)

            # 1단계: 최종랭킹 (DE 진출자) 추출
            qualified_rankings = await page.evaluate("""
                () => {
                    const rankings = [];
                    const popup = document.querySelector('#layer_final_ranking');
                    if (!popup) return rankings;

                    const tables = popup.querySelectorAll('table');
                    for (const table of tables) {
                        const rows = table.querySelectorAll('tbody tr');
                        rows.forEach(row => {
                            const cells = row.querySelectorAll('td');
                            if (cells.length >= 3) {
                                const rankText = cells[0]?.textContent?.trim() || '';
                                const rank = parseInt(rankText) || 0;
                                const name = cells[1]?.textContent?.trim() || '';
                                const team = cells[2]?.textContent?.trim() || '';

                                if (rank > 0 && name) {
                                    rankings.push({
                                        rank: rank,
                                        name: name,
                                        team: team,
                                        status: '진출'
                                    });
                                }
                            }
                        });
                        if (rankings.length > 0) break;
                    }
                    return rankings;
                }
            """)
            all_rankings.extend(qualified_rankings)
            logger.debug(f"최종랭킹(진출자): {len(qualified_rankings)}명")

            # 2단계: 탈락자랭킹 선택 (구분 드롭다운에서)
            try:
                # 구분 select 찾아서 탈락자랭킹 선택
                await page.evaluate("""
                    () => {
                        const popup = document.querySelector('#layer_final_ranking');
                        if (!popup) return;

                        // select 요소 찾기 (구분 드롭다운)
                        const selects = popup.querySelectorAll('select');
                        for (const select of selects) {
                            const options = select.querySelectorAll('option');
                            for (const option of options) {
                                if (option.textContent.includes('탈락자') || option.value.includes('elim')) {
                                    select.value = option.value;
                                    // change 이벤트 발생
                                    select.dispatchEvent(new Event('change', { bubbles: true }));
                                    return;
                                }
                            }
                        }
                    }
                """)
                await page.wait_for_timeout(500)

                # 3단계: 탈락자랭킹 데이터 추출
                eliminated_rankings = await page.evaluate("""
                    () => {
                        const rankings = [];
                        const popup = document.querySelector('#layer_final_ranking');
                        if (!popup) return rankings;

                        const tables = popup.querySelectorAll('table');
                        for (const table of tables) {
                            const rows = table.querySelectorAll('tbody tr');
                            rows.forEach(row => {
                                const cells = row.querySelectorAll('td');
                                if (cells.length >= 3) {
                                    const rankText = cells[0]?.textContent?.trim() || '';
                                    const rank = parseInt(rankText) || 0;
                                    const name = cells[1]?.textContent?.trim() || '';
                                    const team = cells[2]?.textContent?.trim() || '';

                                    if (rank > 0 && name) {
                                        rankings.push({
                                            rank: rank,
                                            name: name,
                                            team: team,
                                            status: '탈락'
                                        });
                                    }
                                }
                            });
                            if (rankings.length > 0) break;
                        }
                        return rankings;
                    }
                """)
                all_rankings.extend(eliminated_rankings)
                logger.debug(f"탈락자랭킹: {len(eliminated_rankings)}명")

            except Exception as e:
                logger.debug(f"탈락자랭킹 추출 오류 (무시): {e}")

            # 팝업 닫기
            try:
                close_btn = page.locator("#layer_final_ranking a:has-text('닫기')")
                await close_btn.click(timeout=2000)
                await page.wait_for_timeout(300)
            except:
                try:
                    await page.evaluate("document.querySelector('#layer_final_ranking').style.display = 'none'")
                except:
                    try:
                        await page.keyboard.press("Escape")
                        await page.wait_for_timeout(300)
                    except:
                        pass

            # 최종 확인: 팝업 강제 숨기기
            try:
                await page.evaluate("""
                    const popup = document.querySelector('#layer_final_ranking');
                    if (popup) popup.style.display = 'none';
                """)
            except:
                pass

            logger.info(f"뿔 최종 랭킹 총 {len(all_rankings)}명 (진출: {len(qualified_rankings)}, 탈락: {len([r for r in all_rankings if r.get('status') == '탈락'])})")
            return all_rankings

        except Exception as e:
            logger.debug(f"뿔 최종 랭킹 파싱 오류: {e}")
            return []

    async def _parse_final_rankings_v2(self, page: Page) -> List[Dict]:
        """개선된 최종 순위 파싱"""
        try:
            rankings = await page.evaluate("""
                () => {
                    const rankings = [];
                    const tables = document.querySelectorAll('table');

                    for (const table of tables) {
                        const headers = table.querySelectorAll('th');
                        const headerTexts = Array.from(headers).map(h => h.textContent.trim());

                        // 순위 테이블 확인
                        if (headerTexts.includes('순위') && headerTexts.includes('이름') && headerTexts.includes('소속팀')) {
                            const rows = table.querySelectorAll('tbody tr, tr:not(:first-child)');

                            rows.forEach(row => {
                                const cells = row.querySelectorAll('td');
                                if (cells.length >= 3) {
                                    const rankText = cells[0]?.textContent?.trim() || '';
                                    const rank = parseInt(rankText.replace('위', '')) || 0;

                                    if (rank > 0) {
                                        rankings.push({
                                            rank: rank,
                                            name: cells[1]?.textContent?.trim() || '',
                                            team: cells[2]?.textContent?.trim() || ''
                                        });
                                    }
                                }
                            });

                            break;  // 첫 번째 순위 테이블만
                        }
                    }

                    return rankings;
                }
            """)

            return rankings

        except Exception as e:
            logger.error(f"최종 순위 파싱 오류: {e}")
            return []

    async def _parse_de_bracket(self, page: Page) -> Dict[str, Any]:
        """엘리미나시옹디렉트 대진표 파싱 - 전체 토너먼트 트리 구조"""
        try:
            bracket_data = {
                "rounds": [],
                "matches": [],
                "bracket_tree": {},
                "seeding": [],
                "results_by_round": {}
            }

            # 엘리미나시옹디렉트 대진표 전체를 파싱 (패자 정보 포함)
            bracket_result = await page.evaluate("""
                () => {
                    const result = {
                        rounds: [],
                        seeding: [],
                        match_results: [],
                        round_headers: [],
                        full_bouts: []  // 승자+패자 정보가 포함된 완전한 경기 기록
                    };

                    // 라운드 탭 수집 (32강전, 8강전 등)
                    const tabLinks = document.querySelectorAll('ul li a');
                    tabLinks.forEach(link => {
                        const text = link.textContent.trim();
                        if (text.match(/\\d+강전|준결승|결승/)) {
                            if (!result.rounds.includes(text)) {
                                result.rounds.push(text);
                            }
                        }
                    });

                    // 라운드 헤더 수집 (64 엘리미나시옹디렉트, 32 엘리미나시옹디렉트 등)
                    const headerCells = document.querySelectorAll('table td');
                    headerCells.forEach(cell => {
                        const text = cell.textContent.trim();
                        if (text.match(/^\\d+\\s*엘리미나시옹디렉트$/)) {
                            result.round_headers.push(text);
                        }
                    });

                    // 셀에서 선수 정보 추출하는 헬퍼 함수
                    function extractPlayerFromCell(cell) {
                        if (!cell) return null;

                        const divs = cell.querySelectorAll(':scope > div');
                        if (divs.length < 2) return null;

                        const seedDiv = divs[0];
                        const seed = parseInt(seedDiv.textContent.trim());
                        if (!seed || isNaN(seed)) return null;

                        const infoDiv = divs[1];
                        const paragraphs = infoDiv.querySelectorAll('p');
                        if (paragraphs.length < 1) return null;

                        const name = paragraphs[0].textContent.trim();
                        if (!name) return null;

                        let affText = '';
                        if (paragraphs.length >= 2) {
                            affText = paragraphs[1].textContent.trim();
                        }

                        const scoreMatch = affText.match(/(\\d+)\\s*:\\s*(\\d+)/);

                        return {
                            seed: seed,
                            name: name,
                            team: scoreMatch ? '' : affText,
                            score: scoreMatch ? {
                                winner_score: parseInt(scoreMatch[1]),
                                loser_score: parseInt(scoreMatch[2])
                            } : null,
                            is_winner: !!scoreMatch
                        };
                    }

                    // 모든 중첩 테이블에서 선수 정보 추출 (2행씩 묶어서 한 경기로)
                    const nestedTables = document.querySelectorAll('table table');
                    let tableIndex = 0;

                    nestedTables.forEach(nestedTable => {
                        const rows = Array.from(nestedTable.querySelectorAll('tr'));
                        const players = [];

                        // 먼저 모든 선수 정보 추출
                        rows.forEach(row => {
                            const cell = row.querySelector('td');
                            const player = extractPlayerFromCell(cell);
                            if (player) {
                                players.push(player);
                            }
                        });

                        // 인접한 2명씩 묶어서 경기 매칭 (대진표 구조)
                        for (let i = 0; i < players.length; i += 2) {
                            const player1 = players[i];
                            const player2 = players[i + 1];

                            if (!player1) continue;

                            // player2가 없는 경우 (부전승)
                            if (!player2) {
                                if (player1.is_winner) {
                                    result.match_results.push({
                                        table_index: tableIndex,
                                        seed: player1.seed,
                                        name: player1.name,
                                        team: player1.team,
                                        score: player1.score,
                                        is_match_result: true
                                    });
                                } else {
                                    result.seeding.push({
                                        table_index: tableIndex,
                                        seed: player1.seed,
                                        name: player1.name,
                                        team: player1.team,
                                        score: null,
                                        is_match_result: false
                                    });
                                }
                                continue;
                            }

                            // 경기 결과가 있는 경우 (승자/패자 매칭)
                            let winner = null, loser = null;
                            if (player1.is_winner) {
                                winner = player1;
                                loser = player2;
                            } else if (player2.is_winner) {
                                winner = player2;
                                loser = player1;
                            }

                            if (winner && loser) {
                                // full_bouts에 완전한 경기 정보 저장
                                result.full_bouts.push({
                                    table_index: tableIndex,
                                    winner: {
                                        seed: winner.seed,
                                        name: winner.name,
                                        team: winner.team || loser.team,  // 승자 팀이 없으면 패자 팀으로 추론
                                        score: winner.score.winner_score
                                    },
                                    loser: {
                                        seed: loser.seed,
                                        name: loser.name,
                                        team: loser.team || winner.team,  // 패자 팀이 없으면 승자 팀으로 추론 (동일 팀 가정 안함)
                                        score: winner.score.loser_score
                                    },
                                    score: winner.score
                                });

                                // 기존 match_results도 유지 (하위 호환)
                                result.match_results.push({
                                    table_index: tableIndex,
                                    seed: winner.seed,
                                    name: winner.name,
                                    team: winner.team,
                                    score: winner.score,
                                    is_match_result: true
                                });
                            } else {
                                // 아직 경기 전인 경우 (seeding)
                                result.seeding.push({
                                    table_index: tableIndex,
                                    seed: player1.seed,
                                    name: player1.name,
                                    team: player1.team,
                                    score: null,
                                    is_match_result: false
                                });
                                result.seeding.push({
                                    table_index: tableIndex,
                                    seed: player2.seed,
                                    name: player2.name,
                                    team: player2.team,
                                    score: null,
                                    is_match_result: false
                                });
                            }
                        }

                        tableIndex++;
                    });

                    return result;
                }
            """)

            bracket_data["rounds"] = bracket_result.get("rounds", [])
            bracket_data["round_headers"] = bracket_result.get("round_headers", [])

            # Filter seeding to only include first table (table_index=0 is initial bracket)
            all_seeding = bracket_result.get("seeding", [])
            initial_seeding = [s for s in all_seeding if s.get("table_index") == 0]
            bracket_data["seeding"] = initial_seeding

            # Process match results with round names
            all_match_results = bracket_result.get("match_results", [])

            # Group by table index first to count matches per table
            tables_with_matches = {}
            for match in all_match_results:
                table_idx = match.get("table_index", 0)
                if table_idx not in tables_with_matches:
                    tables_with_matches[table_idx] = []
                tables_with_matches[table_idx].append(match)

            # Sort table indices and map to rounds based on match count pattern
            # Standard bracket: 32->16->8->4->2->1 matches per round
            sorted_tables = sorted(tables_with_matches.keys())

            # Map round by match count
            def get_round_name(match_count: int) -> str:
                if match_count >= 24:
                    return "32강전"
                elif match_count >= 12:
                    return "16강전"
                elif match_count >= 6:
                    return "8강전"
                elif match_count >= 3:
                    return "준결승"
                elif match_count >= 2:
                    return "결승"
                else:
                    return "3-4위전"

            # Create table_to_round mapping based on match counts
            table_to_round = {}
            for table_idx in sorted_tables:
                match_count = len(tables_with_matches[table_idx])
                table_to_round[table_idx] = get_round_name(match_count)

            # Add round name to each match result
            for match in all_match_results:
                table_idx = match.get("table_index", 0)
                match["round"] = table_to_round.get(table_idx, f"라운드 {table_idx}")

            bracket_data["match_results"] = all_match_results

            # full_bouts에도 라운드 정보 추가 (패자 정보 포함)
            all_full_bouts = bracket_result.get("full_bouts", [])

            # seeding에서 선수 이름 → 팀 매핑 생성
            name_to_team = {}
            for s in initial_seeding:
                name = s.get("name", "")
                team = s.get("team", "")
                if name and team:
                    name_to_team[name] = team

            # full_bouts에 라운드 및 팀 정보 보완
            for bout in all_full_bouts:
                table_idx = bout.get("table_index", 0)
                bout["round"] = table_to_round.get(table_idx, f"라운드 {table_idx}")

                # 승자/패자 팀 정보 보완
                winner = bout.get("winner", {})
                loser = bout.get("loser", {})

                if not winner.get("team") and winner.get("name") in name_to_team:
                    winner["team"] = name_to_team[winner["name"]]
                if not loser.get("team") and loser.get("name") in name_to_team:
                    loser["team"] = name_to_team[loser["name"]]

            bracket_data["full_bouts"] = all_full_bouts

            # Group results by round for easier access
            results_by_round = {}
            for match in all_match_results:
                round_name = match.get("round", "Unknown")
                if round_name not in results_by_round:
                    results_by_round[round_name] = []
                results_by_round[round_name].append(match)
            bracket_data["results_by_round"] = results_by_round

            logger.debug(f"발견된 라운드: {bracket_data['rounds']}")
            logger.debug(f"라운드 헤더: {bracket_data['round_headers']}")
            logger.info(f"대진표 시딩: {len(initial_seeding)}개, 경기결과: {len(all_match_results)}개, 완전경기: {len(all_full_bouts)}개")

            return bracket_data

        except Exception as e:
            logger.error(f"대진표 파싱 오류: {e}")
            return {"rounds": [], "matches": [], "bracket_tree": {}, "seeding": [], "match_results": []}

    async def _parse_de_bracket_v3(self, page: Page) -> Dict[str, Any]:
        """
        DE 대진표 파싱 v3 → v4로 위임

        v4 개선사항:
        1. fnGetMatch() 함수로 탭 로드
        2. row_table 컬럼 기반 파싱
        3. 다음 라운드에서 점수 추출
        4. 멀티 탭 병합 (32강전 + 8강전)
        """
        try:
            # DEScraper v4 사용
            scraper = DEScraper(page)
            bracket = await scraper.parse_de_bracket()
            return bracket.to_dict()
        except Exception as e:
            logger.warning(f"DE v4 파싱 실패, v3 fallback 시도: {e}")

        # Fallback to original v3 logic
        try:
            bracket_data = {
                "bracket_size": 0,
                "participant_count": 0,
                "starting_round": "",
                "rounds": [],
                "seeding": [],
                "bouts": [],
                "bouts_by_round": {},
                "final_ranking": [],
                "results_by_round": {},
                "match_results": [],
                "full_bouts": []
            }

            # 1. 전체 브래킷 테이블 구조 파싱 (모든 라운드 컬럼을 한 번에)
            # v3.2: 더 강력한 테이블 찾기 로직
            all_columns_data = await page.evaluate("""
                () => {
                    const result = {
                        columns: [],
                        round_names: [],
                        debug: {
                            totalCells: 0,
                            nonEmptyCells: 0,
                            emptyCells: 0,
                            foundBracketTable: false,
                            tableCount: 0
                        }
                    };

                    // 라운드 헤더 찾기
                    const allCells = document.querySelectorAll('table td, table th');
                    const roundHeaders = [];

                    allCells.forEach(cell => {
                        const text = cell.textContent.trim();
                        let match = text.match(/^(\\d+)\\s*엘리미나시옹디렉트$/);
                        if (match) {
                            roundHeaders.push({
                                size: parseInt(match[1]),
                                name: match[1] + '강전'
                            });
                        }
                        else if (/^(8강전|준결승|결승)$/.test(text)) {
                            let size = 8;
                            if (text === '준결승') size = 4;
                            if (text === '결승') size = 2;
                            roundHeaders.push({ size: size, name: text });
                        }
                    });

                    result.round_names = roundHeaders.map(h => h.name);

                    // DE 브래킷 테이블 찾기 v3.3 - rowgroup 구조 지원
                    // 전략: 1) 테이블 텍스트에 "엘리미나시옹디렉트" 포함 2) 중첩 테이블 3개 이상
                    const tables = document.querySelectorAll('table');
                    result.debug.tableCount = tables.length;
                    let bracketTable = null;

                    for (const table of tables) {
                        const tableText = table.textContent || '';
                        // 테이블이 DE 관련 텍스트를 포함하는지 확인
                        if (!tableText.includes('엘리미나시옹디렉트') && !tableText.includes('8강전')) {
                            continue;
                        }

                        // 중첩 테이블이 3개 이상 있어야 브래킷 테이블
                        const nestedTables = table.querySelectorAll('table');
                        if (nestedTables.length >= 3) {
                            // 시드 번호(1-64)가 있는지 확인
                            let hasData = false;
                            nestedTables.forEach(nt => {
                                const divs = nt.querySelectorAll('div');
                                divs.forEach(div => {
                                    const num = parseInt(div.textContent.trim());
                                    if (num >= 1 && num <= 64) {
                                        hasData = true;
                                    }
                                });
                            });

                            if (hasData) {
                                bracketTable = table;
                                break;  // 첫 번째 유효한 테이블 사용
                            }
                        }
                    }

                    if (!bracketTable) {
                        result.debug.foundBracketTable = false;
                        return result;
                    }

                    result.debug.foundBracketTable = true;

                    // 데이터 행 찾기 - 중첩 테이블을 포함하는 행
                    // rowgroup 구조: table > tbody/rowgroup > tr 또는 table > tr
                    const allRows = bracketTable.querySelectorAll('tr');
                    let dataRow = null;
                    let maxNestedTables = 0;

                    for (const row of allRows) {
                        const cells = row.querySelectorAll(':scope > td');
                        let nestedCount = 0;
                        cells.forEach(cell => {
                            if (cell.querySelector('table')) nestedCount++;
                        });

                        // 중첩 테이블이 가장 많은 행 = 데이터 행
                        if (nestedCount > maxNestedTables) {
                            maxNestedTables = nestedCount;
                            dataRow = row;
                        }
                    }

                    if (!dataRow) {
                        return result;
                    }

                    const cells = dataRow.querySelectorAll(':scope > td');
                    result.debug.totalCells = cells.length;

                    let columnIndex = 0;

                    cells.forEach((cell, cellIdx) => {
                        const nestedTable = cell.querySelector('table');
                        if (!nestedTable) {
                            result.debug.emptyCells++;
                            return;
                        }

                        const columnData = {
                            tableIndex: columnIndex,
                            cellIndex: cellIdx,
                            entries: []
                        };

                        // 중첩 테이블의 모든 행 파싱
                        const tableRows = nestedTable.querySelectorAll('tr');
                        let hasValidEntry = false;

                        tableRows.forEach((row, rowIdx) => {
                            const td = row.querySelector('td');
                            if (!td) return;

                            // div 기반 파싱 (seed_div + info_div)
                            const divs = td.querySelectorAll(':scope > div');
                            if (divs.length < 2) return;

                            const posDiv = divs[0];
                            const posText = posDiv.textContent.trim();
                            const position = parseInt(posText);
                            if (!position || isNaN(position)) return;

                            const infoDiv = divs[1];
                            const paragraphs = infoDiv.querySelectorAll('p');
                            if (paragraphs.length < 1) return;

                            // 이름 추출 (paragraph 내부의 span 또는 직접 텍스트)
                            let name = '';
                            const nameEl = paragraphs[0].querySelector('span, generic') || paragraphs[0];
                            name = nameEl.textContent.trim();
                            if (!name) return;

                            let team = '';
                            let score = null;
                            let hasScore = false;

                            if (paragraphs.length >= 2) {
                                const infoEl = paragraphs[1].querySelector('span, generic') || paragraphs[1];
                                const infoText = infoEl.textContent.trim();
                                const scoreMatch = infoText.match(/(\\d+)\\s*:\\s*(\\d+)/);

                                if (scoreMatch) {
                                    score = {
                                        winner: parseInt(scoreMatch[1]),
                                        loser: parseInt(scoreMatch[2])
                                    };
                                    hasScore = true;
                                } else {
                                    team = infoText;
                                }
                            }

                            columnData.entries.push({
                                rowIndex: rowIdx,
                                position: position,
                                name: name,
                                team: team,
                                score: score,
                                hasScore: hasScore
                            });
                            hasValidEntry = true;
                        });

                        if (hasValidEntry && columnData.entries.length > 0) {
                            result.columns.push(columnData);
                            result.debug.nonEmptyCells++;
                            columnIndex++;
                        } else {
                            result.debug.emptyCells++;
                        }
                    });

                    return result;
                }
            """)

            columns = all_columns_data.get("columns", [])
            debug_info = all_columns_data.get("debug", {})

            if not columns:
                logger.debug(f"DE 컬럼 데이터 없음 (debug: {debug_info}), 기존 방식으로 fallback")
                return await self._parse_de_bracket_v2_fallback(page)

            logger.debug(f"DE v3.1 파싱: 총 셀 {debug_info.get('totalCells', '?')}개, 데이터 셀 {debug_info.get('nonEmptyCells', '?')}개, 빈 셀 {debug_info.get('emptyCells', '?')}개")
            logger.debug(f"파싱된 컬럼 수: {len(columns)} (라운드: {all_columns_data.get('round_names', [])})")

            # 2. 첫 번째 컬럼 분석 (시딩 라운드)
            first_column = columns[0]
            seeding_entries = first_column['entries']

            # 시딩 정보 저장
            seeding_list = []
            for entry in seeding_entries:
                if not entry['hasScore']:  # 점수가 없는 엔트리 = 시딩
                    seeding_list.append({
                        'seed': entry['position'],
                        'name': entry['name'],
                        'team': entry['team']
                    })

            # 시드 순으로 정렬
            seeding_list.sort(key=lambda x: x['seed'])
            bracket_data["seeding"] = seeding_list
            bracket_data["participant_count"] = len(seeding_list)

            # 브래킷 크기 결정
            pc = len(seeding_list)
            for size in [8, 16, 32, 64, 128]:
                if pc <= size:
                    bracket_data["bracket_size"] = size
                    break

            # 3. 라운드별 경기 생성
            all_bouts = []
            bout_id_counter = 1

            # bracket_pos -> match 매핑 (각 라운드별)
            # Key: (round_idx, bracket_pos), Value: {player1, player2}
            bracket_pos_to_match = {}

            # 첫 번째 컬럼에서 초기 대진 생성 (인접 2명씩)
            first_round_entries = seeding_entries
            first_round_name = self._get_round_name_by_size(len(first_round_entries))

            for i in range(0, len(first_round_entries), 2):
                p1_entry = first_round_entries[i] if i < len(first_round_entries) else None
                p2_entry = first_round_entries[i + 1] if (i + 1) < len(first_round_entries) else None

                if not p1_entry:
                    continue

                # 브래킷 포지션 = 두 시드 중 작은 값
                seed1 = p1_entry['position']
                seed2 = p2_entry['position'] if p2_entry else seed1
                bracket_pos = min(seed1, seed2)

                # 첫 라운드 매칭 저장
                bracket_pos_to_match[(0, bracket_pos)] = {
                    'player1': {
                        'seed': p1_entry['position'],
                        'name': p1_entry['name'],
                        'team': p1_entry['team']
                    },
                    'player2': {
                        'seed': p2_entry['position'] if p2_entry else None,
                        'name': p2_entry['name'] if p2_entry else None,
                        'team': p2_entry['team'] if p2_entry else None
                    } if p2_entry else None
                }

            # 4. 이후 컬럼(라운드) 순회하며 경기 결과 매칭
            # 브래킷 크기 기준으로 라운드 이름 계산
            bracket_size = bracket_data["bracket_size"]
            for col_idx, column in enumerate(columns):
                entries = column['entries']
                # col_idx 0 = 시딩 컬럼 (점수 없음)
                # col_idx 1 = 첫 라운드 결과 (32강 결과, bracket_size명 경쟁)
                # col_idx 2 = 16강 결과 (bracket_size/2명 경쟁)
                # 공식: col_idx=1부터 실제 라운드 결과, 라운드 크기 = bracket_size / (2^(col_idx-1))
                if col_idx == 0:
                    round_size = bracket_size  # 시딩 라운드
                else:
                    round_size = bracket_size // (2 ** (col_idx - 1))
                round_name = self._get_round_name_by_size(round_size)

                for entry in entries:
                    if not entry['hasScore']:
                        continue  # 점수 없으면 스킵

                    bracket_pos = entry['position']
                    winner_name = entry['name']
                    score = entry['score']

                    # 이전 라운드에서 이 bracket_pos의 대진 찾기
                    prev_match = None
                    for prev_col_idx in range(col_idx, -1, -1):
                        if (prev_col_idx, bracket_pos) in bracket_pos_to_match:
                            prev_match = bracket_pos_to_match[(prev_col_idx, bracket_pos)]
                            break

                    if not prev_match:
                        # 이전 대진을 못 찾으면 시딩에서 찾기
                        prev_match = self._find_match_by_bracket_pos(bracket_pos, seeding_list)

                    if not prev_match:
                        logger.debug(f"이전 대진 찾기 실패: bracket_pos={bracket_pos}, winner={winner_name}")
                        continue

                    # 승자/패자 결정
                    p1 = prev_match.get('player1', {})
                    p2 = prev_match.get('player2', {})

                    if p1 and p1.get('name') == winner_name:
                        winner = p1
                        loser = p2
                    elif p2 and p2.get('name') == winner_name:
                        winner = p2
                        loser = p1
                    else:
                        # 이름 매칭 실패 시 부분 매칭 시도
                        winner = {'name': winner_name, 'seed': bracket_pos, 'team': ''}
                        loser = p2 if p1.get('name') == winner_name else p1
                        logger.debug(f"이름 매칭 부정확: {winner_name} vs ({p1.get('name')}, {p2.get('name') if p2 else 'None'})")

                    # bout 생성
                    bout = {
                        'bout_id': f"{round_name}_{bout_id_counter:02d}",
                        'round': round_name.replace('전', ''),
                        'round_order': self._get_round_order(round_name),
                        'matchNumber': bout_id_counter,
                        'tableIndex': col_idx,
                        'bracket_pos': bracket_pos,
                        'player1': {
                            'seed': winner.get('seed'),
                            'name': winner.get('name'),
                            'team': winner.get('team', ''),
                            'score': score['winner'] if score else None
                        },
                        'player2': {
                            'seed': loser.get('seed') if loser else None,
                            'name': loser.get('name') if loser else None,
                            'team': loser.get('team', '') if loser else '',
                            'score': score['loser'] if score else None
                        } if loser else None,
                        'winnerSeed': winner.get('seed'),
                        'winnerName': winner.get('name'),
                        'isCompleted': True,
                        'isBye': loser is None
                    }
                    all_bouts.append(bout)
                    bout_id_counter += 1

                    # 다음 라운드용 매핑 업데이트
                    next_bracket_pos = bracket_pos  # 승자는 같은 bracket_pos 유지
                    bracket_pos_to_match[(col_idx + 1, next_bracket_pos)] = {
                        'player1': winner,
                        'player2': None  # 다음 상대는 아직 미정
                    }

            # 5. 중복 bout 제거 및 라운드 재계산
            # 같은 bracket_pos + 같은 선수 조합은 중복 → 가장 마지막(정확한) 것만 유지
            unique_bouts = {}
            for bout in all_bouts:
                bp = bout['bracket_pos']
                p1_name = bout.get('player1', {}).get('name', '')
                p2_name = bout.get('player2', {}).get('name', '') if bout.get('player2') else 'BYE'
                key = (bp, p1_name, p2_name)

                # 같은 키가 있으면 tableIndex가 더 큰 것(나중 라운드)으로 업데이트
                if key not in unique_bouts or bout['tableIndex'] > unique_bouts[key]['tableIndex']:
                    unique_bouts[key] = bout

            # 중복 제거된 bouts
            deduped_bouts = list(unique_bouts.values())

            # 6. tableIndex 기반으로 라운드 이름 재계산
            # tableIndex 0 = 시딩 컬럼 (점수 없음, bouts에 포함 안됨)
            # tableIndex 1 = 32강 결과 (32명 경쟁)
            # tableIndex 2 = 16강 결과 (16명 경쟁)
            # tableIndex 3 = 8강 결과 (8명 경쟁)
            for bout in deduped_bouts:
                col_idx = bout['tableIndex']
                # col_idx=1부터 점수 있는 컬럼, 라운드 크기 = bracket_size / 2^(col_idx-1)
                if col_idx == 0:
                    round_size = bracket_size
                else:
                    round_size = bracket_size // (2 ** (col_idx - 1))
                round_name = self._get_round_name_by_size(round_size)
                bout['round'] = round_name.replace('전', '')
                bout['round_order'] = self._get_round_order(round_name)
                bout['bout_id'] = f"{round_name}_{bout['matchNumber']:02d}"

            bracket_data["bouts"] = deduped_bouts

            # 7. 라운드별 그룹화
            rounds_found = sorted(
                set(b['round'] for b in deduped_bouts),
                key=lambda r: self._get_round_order(r + '전')
            )
            bracket_data["rounds"] = rounds_found

            if rounds_found:
                bracket_data["starting_round"] = rounds_found[0]

            bouts_by_round = {}
            for bout in deduped_bouts:
                r = bout['round']
                if r not in bouts_by_round:
                    bouts_by_round[r] = []
                bouts_by_round[r].append(bout)
            bracket_data["bouts_by_round"] = bouts_by_round

            # 하위 호환성
            bracket_data["results_by_round"] = self._convert_bouts_to_legacy(deduped_bouts)
            bracket_data["match_results"] = self._flatten_bouts_to_results(deduped_bouts)
            bracket_data["full_bouts"] = self._convert_to_full_bouts(deduped_bouts)

            logger.info(f"DE v3 파싱 완료: {len(deduped_bouts)}개 경기 (중복제거 전 {len(all_bouts)}개), {len(rounds_found)}개 라운드, 시딩: {len(seeding_list)}명")
            return bracket_data

        except Exception as e:
            logger.error(f"DE v3 파싱 오류: {e}")
            import traceback
            traceback.print_exc()
            return {"rounds": [], "bouts": [], "seeding": [], "bouts_by_round": {}}

    def _get_round_name_by_size(self, size: int) -> str:
        """참가자 수로 라운드 이름 결정"""
        if size >= 64:
            return "64강전"
        elif size >= 32:
            return "32강전"
        elif size >= 16:
            return "16강전"
        elif size >= 8:
            return "8강전"
        elif size >= 4:
            return "준결승"
        elif size >= 2:
            return "결승"
        return "3-4위전"

    def _get_round_order(self, round_name: str) -> int:
        """라운드 순서 반환"""
        order = {
            '128강전': 1, '64강전': 2, '32강전': 3, '16강전': 4,
            '8강전': 5, '준결승': 6, '결승': 7, '3-4위전': 8
        }
        return order.get(round_name, order.get(round_name.replace('전', '') + '전', 99))

    def _find_match_by_bracket_pos(self, bracket_pos: int, seeding_list: List[Dict]) -> Optional[Dict]:
        """
        시딩 리스트에서 bracket_pos에 해당하는 대진 찾기

        FIE 시딩 규칙:
        - 32강: 1v32, 17v16, 9v24, 25v8, 5v28, 21v12, 13v20, 29v4, ...
        - bracket_pos = min(seed1, seed2)
        """
        # 표준 FIE 시딩 페어링
        bracket_size = len(seeding_list)
        if bracket_size <= 0:
            return None

        # bracket_pos에 해당하는 상대 시드 계산
        opponent_seed = bracket_size + 1 - bracket_pos

        p1 = next((s for s in seeding_list if s['seed'] == bracket_pos), None)
        p2 = next((s for s in seeding_list if s['seed'] == opponent_seed), None)

        if p1:
            return {
                'player1': p1,
                'player2': p2
            }
        return None

    async def _parse_de_bracket_v2_fallback(self, page: Page) -> Dict[str, Any]:
        """v3 실패 시 기존 v2 로직으로 fallback"""
        return await self._parse_de_bracket_v2_original(page)

    async def _parse_de_bracket_v2_original(self, page: Page) -> Dict[str, Any]:
        """기존 _parse_de_bracket_v2 로직 (fallback용) - 라운드 탭 순회"""
        try:
            bracket_data = {
                "bracket_size": 0,
                "participant_count": 0,
                "starting_round": "",
                "rounds": [],
                "seeding": [],
                "bouts": [],
                "bouts_by_round": {},
                "final_ranking": [],
                "results_by_round": {},
                "match_results": [],
                "full_bouts": []
            }

            # 라운드 탭 목록 수집
            round_tabs = await page.evaluate("""
                () => {
                    const tabs = [];
                    const links = document.querySelectorAll('ul li a');
                    links.forEach((link, idx) => {
                        const text = link.textContent.trim();
                        if (text.match(/^\\d+강전$|^준결승$|^결승$/)) {
                            tabs.push({ text: text, index: idx });
                        }
                    });
                    return tabs;
                }
            """)

            if not round_tabs:
                return await self._parse_de_bracket(page)

            ROUND_ORDER = {
                '128강전': 1, '64강전': 2, '32강전': 3, '16강전': 4,
                '8강전': 5, '준결승': 6, '결승': 7
            }
            round_tabs.sort(key=lambda x: ROUND_ORDER.get(x['text'], 99))

            all_bouts = []
            all_seeding = []
            bout_id_counter = 1

            for tab_info in round_tabs:
                round_name = tab_info['text']
                round_order = ROUND_ORDER.get(round_name, 99)

                try:
                    tab_selector = f"ul li a:has-text('{round_name}')"
                    await page.click(tab_selector, timeout=3000)
                    await page.wait_for_timeout(800)

                    round_bouts = await page.evaluate("""
                        (roundName) => {
                            const bouts = [];
                            const tables = document.querySelectorAll('table table');

                            tables.forEach((table, tableIdx) => {
                                const rows = table.querySelectorAll('tr');
                                const players = [];

                                rows.forEach(row => {
                                    const cell = row.querySelector('td');
                                    if (!cell) return;

                                    const divs = cell.querySelectorAll(':scope > div');
                                    if (divs.length < 2) return;

                                    const seed = parseInt(divs[0].textContent.trim());
                                    if (!seed || isNaN(seed)) return;

                                    const paragraphs = divs[1].querySelectorAll('p');
                                    if (paragraphs.length < 1) return;

                                    const name = paragraphs[0].textContent.trim();
                                    if (!name) return;

                                    let team = '', score = null, isWinner = false;
                                    if (paragraphs.length >= 2) {
                                        const infoText = paragraphs[1].textContent.trim();
                                        const scoreMatch = infoText.match(/(\\d+)\\s*:\\s*(\\d+)/);
                                        if (scoreMatch) {
                                            score = { winner_score: parseInt(scoreMatch[1]), loser_score: parseInt(scoreMatch[2]) };
                                            isWinner = true;
                                        } else {
                                            team = infoText;
                                        }
                                    }

                                    players.push({ seed, name, team, score, isWinner });
                                });

                                for (let i = 0; i < players.length; i += 2) {
                                    const p1 = players[i];
                                    const p2 = players[i + 1];
                                    if (!p1) continue;

                                    if (!p2) {
                                        if (p1.isWinner) {
                                            bouts.push({
                                                tableIndex: tableIdx, matchNumber: Math.floor(i / 2) + 1,
                                                player1: p1, player2: null, winnerSeed: p1.seed, winnerName: p1.name,
                                                isBye: true, isCompleted: true
                                            });
                                        }
                                        continue;
                                    }

                                    let winner = null, loser = null;
                                    if (p1.isWinner) { winner = p1; loser = p2; }
                                    else if (p2.isWinner) { winner = p2; loser = p1; }

                                    bouts.push({
                                        tableIndex: tableIdx, matchNumber: Math.floor(i / 2) + 1,
                                        player1: { seed: p1.seed, name: p1.name, team: p1.team || p2.team || '',
                                                   score: winner && winner.seed === p1.seed ? winner.score?.winner_score : (winner ? winner.score?.loser_score : null) },
                                        player2: { seed: p2.seed, name: p2.name, team: p2.team || p1.team || '',
                                                   score: winner && winner.seed === p2.seed ? winner.score?.winner_score : (winner ? winner.score?.loser_score : null) },
                                        winnerSeed: winner ? winner.seed : null, winnerName: winner ? winner.name : null,
                                        isBye: false, isCompleted: !!winner
                                    });
                                }
                            });
                            return bouts;
                        }
                    """, round_name)

                    for bout in round_bouts:
                        bout['round'] = round_name.replace('전', '')
                        bout['round_order'] = round_order
                        bout['bout_id'] = f"{bout['round']}_{bout_id_counter:02d}"
                        bout_id_counter += 1
                        all_bouts.append(bout)

                except Exception as e:
                    logger.warning(f"  {round_name} 탭 파싱 오류: {e}")

            bracket_data["bouts"] = all_bouts
            rounds_found = sorted(set(b['round'] for b in all_bouts), key=lambda r: ROUND_ORDER.get(r + '전', 99))
            bracket_data["rounds"] = rounds_found

            if rounds_found:
                bracket_data["starting_round"] = rounds_found[0]

            bouts_by_round = {}
            for bout in all_bouts:
                r = bout['round']
                if r not in bouts_by_round:
                    bouts_by_round[r] = []
                bouts_by_round[r].append(bout)
            bracket_data["bouts_by_round"] = bouts_by_round

            bracket_data["results_by_round"] = self._convert_bouts_to_legacy(all_bouts)
            bracket_data["match_results"] = self._flatten_bouts_to_results(all_bouts)
            bracket_data["full_bouts"] = self._convert_to_full_bouts(all_bouts)

            return bracket_data

        except Exception as e:
            logger.error(f"DE v2 original 파싱 오류: {e}")
            return {"rounds": [], "bouts": [], "seeding": [], "bouts_by_round": {}}

    async def _parse_de_bracket_v2(self, page: Page) -> Dict[str, Any]:
        """
        DE 대진표 파싱 v2 - 라운드 탭 순회 방식

        각 라운드 탭(32강전, 16강전, 8강전, 준결승, 결승)을 클릭하며 데이터 수집.
        완전한 경기(bout) 정보를 수집: 양 선수 정보 + 점수 + 승패
        """
        try:
            bracket_data = {
                "bracket_size": 0,
                "participant_count": 0,
                "starting_round": "",
                "rounds": [],
                "seeding": [],
                "bouts": [],
                "bouts_by_round": {},
                "final_ranking": [],
                # 하위 호환성을 위한 기존 필드
                "results_by_round": {},
                "match_results": [],
                "full_bouts": []
            }

            # 1. 먼저 라운드 탭 목록 수집
            round_tabs = await page.evaluate("""
                () => {
                    const tabs = [];
                    const links = document.querySelectorAll('ul li a');

                    links.forEach((link, idx) => {
                        const text = link.textContent.trim();
                        // 라운드 탭 패턴: N강전, 준결승, 결승
                        if (text.match(/^\\d+강전$|^준결승$|^결승$/)) {
                            tabs.push({
                                text: text,
                                index: idx
                            });
                        }
                    });

                    return tabs;
                }
            """)

            logger.debug(f"발견된 라운드 탭: {round_tabs}")

            if not round_tabs:
                # 탭이 없으면 현재 페이지에서 직접 파싱 시도
                logger.debug("라운드 탭 없음, 단일 페이지 파싱 시도")
                return await self._parse_de_single_page(page)

            # 라운드 순서 정의
            ROUND_ORDER = {
                '128강전': 1, '64강전': 2, '32강전': 3, '16강전': 4,
                '8강전': 5, '준결승': 6, '결승': 7
            }

            # 탭을 라운드 순서대로 정렬
            round_tabs.sort(key=lambda x: ROUND_ORDER.get(x['text'], 99))

            all_bouts = []
            all_seeding = []
            bout_id_counter = 1

            # 2. 각 라운드 탭을 클릭하며 데이터 수집
            for tab_info in round_tabs:
                round_name = tab_info['text']
                round_order = ROUND_ORDER.get(round_name, 99)

                try:
                    # 라운드 탭 클릭
                    tab_selector = f"ul li a:has-text('{round_name}')"
                    await page.click(tab_selector, timeout=3000)
                    await page.wait_for_timeout(800)

                    # 현재 라운드의 경기 데이터 파싱
                    round_bouts = await page.evaluate("""
                        (roundName) => {
                            const bouts = [];

                            // 대진표 테이블에서 선수 정보 추출
                            // 각 경기는 연속된 2개 행으로 구성
                            const tables = document.querySelectorAll('table table');

                            tables.forEach((table, tableIdx) => {
                                const rows = table.querySelectorAll('tr');
                                const players = [];

                                rows.forEach(row => {
                                    const cell = row.querySelector('td');
                                    if (!cell) return;

                                    const divs = cell.querySelectorAll(':scope > div');
                                    if (divs.length < 2) return;

                                    // 시드 번호
                                    const seedDiv = divs[0];
                                    const seed = parseInt(seedDiv.textContent.trim());
                                    if (!seed || isNaN(seed)) return;

                                    // 선수 정보
                                    const infoDiv = divs[1];
                                    const paragraphs = infoDiv.querySelectorAll('p');
                                    if (paragraphs.length < 1) return;

                                    const name = paragraphs[0].textContent.trim();
                                    if (!name) return;

                                    // 소속/점수 파싱
                                    let team = '';
                                    let score = null;
                                    let isWinner = false;

                                    if (paragraphs.length >= 2) {
                                        const infoText = paragraphs[1].textContent.trim();
                                        const scoreMatch = infoText.match(/(\\d+)\\s*:\\s*(\\d+)/);

                                        if (scoreMatch) {
                                            // 점수가 있으면 승자
                                            score = {
                                                winner_score: parseInt(scoreMatch[1]),
                                                loser_score: parseInt(scoreMatch[2])
                                            };
                                            isWinner = true;
                                        } else {
                                            // 점수가 없으면 소속
                                            team = infoText;
                                        }
                                    }

                                    players.push({
                                        seed: seed,
                                        name: name,
                                        team: team,
                                        score: score,
                                        isWinner: isWinner
                                    });
                                });

                                // 2명씩 경기로 매칭
                                for (let i = 0; i < players.length; i += 2) {
                                    const p1 = players[i];
                                    const p2 = players[i + 1];

                                    if (!p1) continue;

                                    // 부전승 처리
                                    if (!p2) {
                                        if (p1.isWinner) {
                                            bouts.push({
                                                tableIndex: tableIdx,
                                                matchNumber: Math.floor(i / 2) + 1,
                                                player1: p1,
                                                player2: null,
                                                winnerSeed: p1.seed,
                                                winnerName: p1.name,
                                                isBye: true,
                                                isCompleted: true
                                            });
                                        }
                                        continue;
                                    }

                                    // 승자/패자 결정
                                    let winner = null, loser = null;
                                    if (p1.isWinner) {
                                        winner = p1;
                                        loser = p2;
                                    } else if (p2.isWinner) {
                                        winner = p2;
                                        loser = p1;
                                    }

                                    const bout = {
                                        tableIndex: tableIdx,
                                        matchNumber: Math.floor(i / 2) + 1,
                                        player1: {
                                            seed: p1.seed,
                                            name: p1.name,
                                            team: p1.team || p2.team || '',
                                            score: winner && winner.seed === p1.seed ?
                                                   winner.score?.winner_score :
                                                   (winner ? winner.score?.loser_score : null)
                                        },
                                        player2: {
                                            seed: p2.seed,
                                            name: p2.name,
                                            team: p2.team || p1.team || '',
                                            score: winner && winner.seed === p2.seed ?
                                                   winner.score?.winner_score :
                                                   (winner ? winner.score?.loser_score : null)
                                        },
                                        winnerSeed: winner ? winner.seed : null,
                                        winnerName: winner ? winner.name : null,
                                        isBye: false,
                                        isCompleted: !!winner
                                    };

                                    bouts.push(bout);
                                }
                            });

                            return bouts;
                        }
                    """, round_name)

                    # 라운드 정보 추가
                    for bout in round_bouts:
                        bout['round'] = round_name.replace('전', '')  # "32강전" -> "32강"
                        bout['round_order'] = round_order
                        bout['bout_id'] = f"{bout['round']}_{bout_id_counter:02d}"
                        bout_id_counter += 1
                        all_bouts.append(bout)

                    logger.debug(f"  {round_name}: {len(round_bouts)}개 경기 수집")

                except Exception as e:
                    logger.warning(f"  {round_name} 탭 클릭/파싱 오류: {e}")
                    continue

            # 3. 시딩 정보 수집 (첫 번째 라운드에서)
            if round_tabs:
                first_round = round_tabs[0]['text']
                try:
                    await page.click(f"ul li a:has-text('{first_round}')", timeout=3000)
                    await page.wait_for_timeout(500)

                    seeding = await page.evaluate("""
                        () => {
                            const players = [];
                            const tables = document.querySelectorAll('table table');

                            tables.forEach(table => {
                                const rows = table.querySelectorAll('tr');

                                rows.forEach(row => {
                                    const cell = row.querySelector('td');
                                    if (!cell) return;

                                    const divs = cell.querySelectorAll(':scope > div');
                                    if (divs.length < 2) return;

                                    const seed = parseInt(divs[0].textContent.trim());
                                    if (!seed || isNaN(seed)) return;

                                    const paragraphs = divs[1].querySelectorAll('p');
                                    const name = paragraphs[0]?.textContent.trim() || '';

                                    let team = '';
                                    if (paragraphs.length >= 2) {
                                        const text = paragraphs[1].textContent.trim();
                                        if (!text.match(/\\d+\\s*:\\s*\\d+/)) {
                                            team = text;
                                        }
                                    }

                                    if (name) {
                                        players.push({ seed, name, team });
                                    }
                                });
                            });

                            // 중복 제거
                            const unique = [];
                            const seen = new Set();
                            players.forEach(p => {
                                if (!seen.has(p.seed)) {
                                    seen.add(p.seed);
                                    unique.push(p);
                                }
                            });

                            return unique.sort((a, b) => a.seed - b.seed);
                        }
                    """)

                    all_seeding = seeding
                    logger.debug(f"시딩 정보: {len(all_seeding)}명")
                except Exception as e:
                    logger.warning(f"시딩 수집 오류: {e}")

            # 4. 결과 구성
            bracket_data["seeding"] = all_seeding
            bracket_data["bouts"] = all_bouts
            bracket_data["participant_count"] = len(all_seeding)

            # 라운드 목록 (순서대로)
            rounds_found = sorted(
                set(b['round'] for b in all_bouts),
                key=lambda r: ROUND_ORDER.get(r + '전', ROUND_ORDER.get(r, 99))
            )
            bracket_data["rounds"] = rounds_found

            # 브래킷 크기 결정
            if all_seeding:
                pc = len(all_seeding)
                for size in [8, 16, 32, 64, 128]:
                    if pc <= size:
                        bracket_data["bracket_size"] = size
                        break
                else:
                    bracket_data["bracket_size"] = 128

            # 시작 라운드 결정
            if rounds_found:
                bracket_data["starting_round"] = rounds_found[0]

            # 5. 준결승/결승이 없으면 최종랭킹에서 추론
            if '준결승' not in rounds_found or '결승' not in rounds_found:
                try:
                    final_ranking = await self._get_de_final_ranking(page)
                    if final_ranking:
                        bracket_data["final_ranking"] = final_ranking
                        # 최종랭킹에서 준결승/결승 경기 추론
                        inferred_bouts = self._infer_semifinal_final_bouts(final_ranking, bout_id_counter)
                        for bout in inferred_bouts:
                            all_bouts.append(bout)
                            if bout['round'] not in rounds_found:
                                rounds_found.append(bout['round'])
                        # 라운드 재정렬
                        rounds_found = sorted(
                            set(b['round'] for b in all_bouts),
                            key=lambda r: ROUND_ORDER.get(r + '전', ROUND_ORDER.get(r, 99))
                        )
                        bracket_data["rounds"] = rounds_found
                        bracket_data["bouts"] = all_bouts
                        logger.info(f"최종랭킹에서 {len(inferred_bouts)}개 경기 추론 완료")
                except Exception as e:
                    logger.debug(f"최종랭킹 추론 오류: {e}")

            # 라운드별 그룹화
            bouts_by_round = {}
            for bout in all_bouts:
                r = bout['round']
                if r not in bouts_by_round:
                    bouts_by_round[r] = []
                bouts_by_round[r].append(bout)
            bracket_data["bouts_by_round"] = bouts_by_round

            # 하위 호환성: 기존 형식으로도 저장
            bracket_data["results_by_round"] = self._convert_bouts_to_legacy(all_bouts)
            bracket_data["match_results"] = self._flatten_bouts_to_results(all_bouts)
            bracket_data["full_bouts"] = self._convert_to_full_bouts(all_bouts)

            logger.info(f"DE v2 파싱 완료: {len(all_bouts)}개 경기, {len(rounds_found)}개 라운드")
            return bracket_data

        except Exception as e:
            logger.error(f"DE v2 파싱 오류: {e}")
            import traceback
            traceback.print_exc()
            return {"rounds": [], "bouts": [], "seeding": [], "bouts_by_round": {}}

    async def _parse_de_single_page(self, page: Page) -> Dict[str, Any]:
        """단일 페이지에서 DE 파싱 (탭이 없는 경우)"""
        return await self._parse_de_bracket(page)

    def _convert_bouts_to_legacy(self, bouts: List[Dict]) -> Dict[str, List[Dict]]:
        """새 bout 형식을 기존 results_by_round 형식으로 변환"""
        results_by_round = {}
        for bout in bouts:
            round_name = bout['round'] + '전'  # "32강" -> "32강전"
            if round_name not in results_by_round:
                results_by_round[round_name] = []

            # 각 선수를 개별 레코드로
            if bout.get('player1'):
                p1 = bout['player1']
                results_by_round[round_name].append({
                    'seed': p1['seed'],
                    'name': p1['name'],
                    'team': p1.get('team', ''),
                    'score': {
                        'winner_score': p1.get('score') if bout.get('winnerSeed') == p1['seed'] else None,
                        'loser_score': p1.get('score') if bout.get('winnerSeed') != p1['seed'] else None
                    } if p1.get('score') else None,
                    'is_match_result': bout.get('isCompleted', False),
                    'table_index': bout.get('tableIndex', 0)
                })

            if bout.get('player2'):
                p2 = bout['player2']
                results_by_round[round_name].append({
                    'seed': p2['seed'],
                    'name': p2['name'],
                    'team': p2.get('team', ''),
                    'score': {
                        'winner_score': p2.get('score') if bout.get('winnerSeed') == p2['seed'] else None,
                        'loser_score': p2.get('score') if bout.get('winnerSeed') != p2['seed'] else None
                    } if p2.get('score') else None,
                    'is_match_result': bout.get('isCompleted', False),
                    'table_index': bout.get('tableIndex', 0)
                })

        return results_by_round

    def _flatten_bouts_to_results(self, bouts: List[Dict]) -> List[Dict]:
        """bout 리스트를 match_results 리스트로 평탄화"""
        results = []
        for bout in bouts:
            if not bout.get('isCompleted'):
                continue

            winner_seed = bout.get('winnerSeed')
            if bout.get('player1') and bout['player1']['seed'] == winner_seed:
                winner = bout['player1']
            elif bout.get('player2') and bout['player2']['seed'] == winner_seed:
                winner = bout['player2']
            else:
                continue

            # player2가 None인 경우 (부전승) 처리
            p1 = bout.get('player1')
            p2 = bout.get('player2')
            loser_score = None
            if winner.get('score') and p1 and p2:
                loser_score = p2.get('score') if p1['seed'] == winner_seed else p1.get('score')

            results.append({
                'seed': winner['seed'],
                'name': winner['name'],
                'team': winner.get('team', ''),
                'score': {
                    'winner_score': winner.get('score'),
                    'loser_score': loser_score
                } if winner.get('score') else None,
                'is_match_result': True,
                'round': bout['round'] + '전',
                'table_index': bout.get('tableIndex', 0)
            })

        return results

    def _convert_to_full_bouts(self, bouts: List[Dict]) -> List[Dict]:
        """새 bout 형식을 full_bouts 형식으로 변환"""
        full_bouts = []
        for bout in bouts:
            if not bout.get('isCompleted') or bout.get('isBye'):
                continue

            winner_seed = bout.get('winnerSeed')
            p1, p2 = bout.get('player1'), bout.get('player2')

            if not p1 or not p2:
                continue

            if p1['seed'] == winner_seed:
                winner, loser = p1, p2
            else:
                winner, loser = p2, p1

            full_bouts.append({
                'table_index': bout.get('tableIndex', 0),
                'round': bout['round'] + '전',
                'winner': {
                    'seed': winner['seed'],
                    'name': winner['name'],
                    'team': winner.get('team', ''),
                    'score': winner.get('score')
                },
                'loser': {
                    'seed': loser['seed'],
                    'name': loser['name'],
                    'team': loser.get('team', ''),
                    'score': loser.get('score')
                },
                'score': {
                    'winner_score': winner.get('score'),
                    'loser_score': loser.get('score')
                }
            })

        return full_bouts

    async def _get_de_final_ranking(self, page: Page) -> List[Dict]:
        """DE 최종 랭킹 수집 (준결승/결승 추론용)"""
        try:
            # "최종랭킹" 또는 "엘리미나시옹디렉트" 섹션에서 랭킹 데이터 추출
            ranking = await page.evaluate("""
                () => {
                    const rankings = [];

                    // 테이블에서 순위 데이터 찾기
                    const tables = document.querySelectorAll('table');

                    for (const table of tables) {
                        const rows = table.querySelectorAll('tr');
                        let foundRanking = false;

                        rows.forEach((row, idx) => {
                            const cells = row.querySelectorAll('td');
                            if (cells.length < 2) return;

                            const firstCellText = cells[0]?.textContent.trim();
                            const secondCellText = cells[1]?.textContent.trim();

                            // 순위 패턴: "1위", "2위", "3위" 등
                            if (firstCellText && firstCellText.match(/^\\d+위?$/)) {
                                foundRanking = true;
                                const rank = parseInt(firstCellText);
                                rankings.push({
                                    rank: rank,
                                    name: secondCellText,
                                    team: cells[2]?.textContent.trim() || ''
                                });
                            }
                        });

                        if (foundRanking && rankings.length >= 4) {
                            break;  // 충분한 데이터 수집됨
                        }
                    }

                    return rankings.slice(0, 8);  // 상위 8명만
                }
            """)

            return ranking
        except Exception as e:
            logger.debug(f"최종랭킹 수집 오류: {e}")
            return []

    def _infer_semifinal_final_bouts(self, final_ranking: List[Dict], bout_id_start: int) -> List[Dict]:
        """최종 랭킹에서 준결승/결승 경기 추론

        DE 토너먼트 구조:
        - 1위: 결승 승자
        - 2위: 결승 패자
        - 3위, 4위: 준결승 패자들 (동률 3위인 경우 rank==3이 2명)
        """
        inferred_bouts = []

        if len(final_ranking) < 4:
            return inferred_bouts

        # 1위, 2위 찾기
        rank1 = next((p for p in final_ranking if p['rank'] == 1), None)
        rank2 = next((p for p in final_ranking if p['rank'] == 2), None)

        # 준결승 패자들: 3위가 2명이면 둘 다, 아니면 3위와 4위
        rank3_players = [p for p in final_ranking if p['rank'] == 3]
        if len(rank3_players) < 2:
            # 3위가 1명이면 4위도 포함
            rank4 = next((p for p in final_ranking if p['rank'] == 4), None)
            if rank4:
                rank3_players.append(rank4)

        if not rank1 or not rank2:
            return inferred_bouts

        bout_id = bout_id_start

        # 결승 경기 생성
        final_bout = {
            'bout_id': f"결승_{bout_id:02d}",
            'round': '결승',
            'round_order': 7,
            'matchNumber': 1,
            'tableIndex': 0,
            'player1': {
                'seed': None,
                'name': rank1['name'],
                'team': rank1.get('team', ''),
                'score': None  # 점수는 알 수 없음
            },
            'player2': {
                'seed': None,
                'name': rank2['name'],
                'team': rank2.get('team', ''),
                'score': None
            },
            'winnerSeed': None,
            'winnerName': rank1['name'],
            'isCompleted': True,
            'isBye': False,
            'isInferred': True  # 추론된 경기임을 표시
        }
        inferred_bouts.append(final_bout)
        bout_id += 1

        # 준결승 경기 생성 (3위 선수가 2명이면)
        if len(rank3_players) >= 2:
            # 준결승 1: 1위 vs 3위 첫 번째
            semifinal1 = {
                'bout_id': f"준결승_{bout_id:02d}",
                'round': '준결승',
                'round_order': 6,
                'matchNumber': 1,
                'tableIndex': 0,
                'player1': {
                    'seed': None,
                    'name': rank1['name'],
                    'team': rank1.get('team', ''),
                    'score': None
                },
                'player2': {
                    'seed': None,
                    'name': rank3_players[0]['name'],
                    'team': rank3_players[0].get('team', ''),
                    'score': None
                },
                'winnerSeed': None,
                'winnerName': rank1['name'],
                'isCompleted': True,
                'isBye': False,
                'isInferred': True
            }
            inferred_bouts.append(semifinal1)
            bout_id += 1

            # 준결승 2: 2위 vs 3위 두 번째
            semifinal2 = {
                'bout_id': f"준결승_{bout_id:02d}",
                'round': '준결승',
                'round_order': 6,
                'matchNumber': 2,
                'tableIndex': 0,
                'player1': {
                    'seed': None,
                    'name': rank2['name'],
                    'team': rank2.get('team', ''),
                    'score': None
                },
                'player2': {
                    'seed': None,
                    'name': rank3_players[1]['name'],
                    'team': rank3_players[1].get('team', ''),
                    'score': None
                },
                'winnerSeed': None,
                'winnerName': rank2['name'],
                'isCompleted': True,
                'isBye': False,
                'isInferred': True
            }
            inferred_bouts.append(semifinal2)

        return inferred_bouts

    async def _parse_de_bracket_simple(self, page: Page) -> List[Dict]:
        """간단한 엘리미나시옹디렉트 대진표 파싱 - 개별 경기 결과만"""
        try:
            matches = await page.evaluate("""
                () => {
                    const matches = [];

                    // 대진표 테이블 내의 모든 셀 파싱
                    const cells = document.querySelectorAll('table td');

                    cells.forEach((cell, idx) => {
                        const text = cell.textContent.trim();
                        if (!text) return;

                        // 점수가 있는 엔트리만 (승자)
                        // 패턴: "시드 이름 점수:점수" 또는 "시드 이름 팀 점수:점수"
                        const scoreMatch = text.match(/(\\d+)\\s*:\\s*(\\d+)/);
                        if (!scoreMatch) return;

                        // 시드와 이름 추출 (한글 또는 영문)
                        const beforeScore = text.substring(0, text.indexOf(scoreMatch[0])).trim();
                        const seedMatch = beforeScore.match(/^(\\d+)\\s+([가-힣a-zA-Z]+)\\s*(.*)$/);

                        if (seedMatch) {
                            matches.push({
                                seed: parseInt(seedMatch[1]),
                                name: seedMatch[2],
                                team: seedMatch[3].trim(),
                                winner_score: parseInt(scoreMatch[1]),
                                loser_score: parseInt(scoreMatch[2]),
                                cell_index: idx
                            });
                        }
                    });

                    return matches;
                }
            """)

            return matches

        except Exception as e:
            logger.error(f"간단한 대진표 파싱 오류: {e}")
            return []

    # ==================== 전체 수집 ====================

    async def scrape_competition_full(self, comp: Competition, page_num: int = 1) -> Dict[str, Any]:
        """단일 대회 전체 데이터 수집"""
        data = {
            "competition": asdict(comp),
            "events": []
        }

        # 종목 목록 조회
        events = await self.get_events(comp.event_cd, page_num=page_num)

        for event in events:
            logger.info(f"  종목: {event.name}")

            # 전체 결과 수집
            results = await self.get_full_results(comp.event_cd, event.sub_event_cd, page_num=page_num)

            event_data = asdict(event)
            event_data["pool_rounds"] = results["pool_rounds"]
            event_data["pool_total_ranking"] = results.get("pool_total_ranking", [])
            event_data["de_bracket"] = results.get("de_bracket", {})
            event_data["de_matches"] = results.get("de_matches", [])
            event_data["final_rankings"] = results["final_rankings"]
            event_data["total_participants"] = results["total_participants"]

            data["events"].append(event_data)

            await throttle_request()  # 종목 간 스로틀링

        return data

    async def scrape_all_full(self, start_year: int = 2019, end_year: int = 2025,
                              output_file: str = "data/fencing_full_data.json",
                              limit: int = None,
                              status_filter: str = None,
                              start_comp: int = 0,
                              resume_file: str = None) -> None:
        """전체 데이터 수집 (풀 결과 + 순위 포함)

        Args:
            start_comp: 시작할 대회 인덱스 (0-based), 이전 대회는 스킵
            resume_file: 기존 데이터 파일에서 이어서 수집 (새로 수집한 데이터로 덮어쓰기)
        """
        competitions = await self.get_all_competitions(start_year, end_year)

        # 상태 필터링 (종료된 대회만)
        if status_filter:
            competitions = [c for c in competitions if c.status == status_filter]
            logger.info(f"상태 필터 적용 ({status_filter}): {len(competitions)}개 대회")

        if limit:
            competitions = competitions[:limit]

        # 기존 데이터 로드 (resume 모드)
        if resume_file:
            try:
                with open(resume_file, 'r', encoding='utf-8') as f:
                    all_data = json.load(f)
                logger.info(f"기존 데이터 로드: {len(all_data.get('competitions', []))}개 대회")
            except Exception as e:
                logger.warning(f"기존 데이터 로드 실패: {e}, 새로 시작")
                all_data = None
        else:
            all_data = None

        if all_data is None:
            all_data = {
                "meta": {
                    "scraped_at": datetime.now().isoformat(),
                    "version": "2.0",
                    "year_range": f"{start_year}-{end_year}",
                    "total_competitions": len(competitions)
                },
                "competitions": [],
                "players": []
            }

        # start_comp 적용
        if start_comp > 0:
            logger.info(f"대회 {start_comp}번부터 시작 (이전 {start_comp}개 스킵)")

        for i, comp in enumerate(competitions):
            # start_comp 이전 대회는 스킵
            if i < start_comp:
                continue

            # comp.page_num 사용 - 대회가 실제로 위치한 페이지
            logger.info(f"[{i+1}/{len(competitions)}] {comp.name} (page {comp.page_num})")

            try:
                comp_data = await self.scrape_competition_full(comp, page_num=comp.page_num)

                # resume 모드: 기존 대회 데이터 업데이트
                if resume_file and i < len(all_data.get("competitions", [])):
                    all_data["competitions"][i] = comp_data
                else:
                    all_data["competitions"].append(comp_data)

                # 중간 저장
                if (i + 1) % 5 == 0:
                    # 선수 목록 업데이트
                    all_data["players"] = [
                        {"id": pid, "name": key.split("_")[0], "team": "_".join(key.split("_")[1:])}
                        for key, pid in self._players.items()
                    ]

                    with open(output_file, "w", encoding="utf-8") as f:
                        json.dump(all_data, f, ensure_ascii=False, indent=2, default=str)
                    logger.info(f"중간 저장: {output_file}")

            except Exception as e:
                logger.error(f"대회 스크래핑 실패 ({comp.name}): {e}")

            await throttle_request()  # 대회 간 스로틀링

        # 최종 저장
        all_data["players"] = [
            {"id": pid, "name": key.split("_")[0], "team": "_".join(key.split("_")[1:])}
            for key, pid in self._players.items()
        ]

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(all_data, f, ensure_ascii=False, indent=2, default=str)

        logger.info(f"수집 완료: {output_file}")
        logger.info(f"총 대회: {len(all_data['competitions'])}개")
        logger.info(f"총 선수: {len(all_data['players'])}명")


# CLI 실행
async def main():
    import argparse

    parser = argparse.ArgumentParser(description="대한펜싱협회 전체 데이터 스크래퍼 v2.0")
    parser.add_argument("--start-year", type=int, default=2019, help="시작 연도")
    parser.add_argument("--end-year", type=int, default=2025, help="종료 연도")
    parser.add_argument("--output", type=str, default="data/fencing_full_data.json", help="출력 파일")
    parser.add_argument("--limit", type=int, default=None, help="수집할 대회 수 제한 (테스트용)")
    parser.add_argument("--status", type=str, default=None, help="상태 필터 (종료, 진행중, 접수마감 등)")
    parser.add_argument("--headless", action="store_true", default=False, help="헤드리스 모드 (기본: headful)")
    parser.add_argument("--headful", action="store_true", default=False, help="헤드풀 모드 (GUI 브라우저)")
    parser.add_argument("--start-comp", type=int, default=0, help="시작할 대회 인덱스 (0-based)")
    parser.add_argument("--resume", type=str, default=None, help="기존 데이터 파일에서 이어서 수집")

    args = parser.parse_args()

    async with KFFFullScraper(headless=args.headless) as scraper:
        await scraper.scrape_all_full(
            start_year=args.start_year,
            end_year=args.end_year,
            output_file=args.output,
            limit=args.limit,
            status_filter=args.status,
            start_comp=args.start_comp,
            resume_file=args.resume
        )


if __name__ == "__main__":
    asyncio.run(main())
