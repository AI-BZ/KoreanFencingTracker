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
                            status=data['status']
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
        page.set_default_timeout(10000)

        try:
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
            try:
                await page.click(f"a[onclick*=\"{event_cd}\"]", timeout=5000)
                await page.wait_for_timeout(1500)
                await throttle_request()  # 스로틀링 적용
            except:
                return events

            # 경기결과 탭 클릭 (onclick 속성으로 정확히 탭만 선택)
            try:
                result_tab = page.locator("a[onclick*='funcLeftSub']:has-text('경기결과')").first
                await result_tab.click(timeout=3000)
                await page.wait_for_timeout(1500)
            except:
                pass

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

                # 실제 대진표 트리 데이터 수집
                bracket_data = await self._parse_de_bracket(page)
                results["de_bracket"] = bracket_data

                # match_results를 de_matches로 복사 (호환성 유지)
                de_matches = bracket_data.get("match_results", [])
                results["de_matches"] = de_matches

                logger.info(f"엘리미나시옹디렉트 대진표 수집 완료: {len(de_matches)}개 경기, 시드: {len(bracket_data.get('seeding', []))}명")
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

            # DE 데이터 파싱
            bracket_data = await self._parse_de_bracket(page)
            results["de_bracket"] = bracket_data
            results["de_matches"] = bracket_data.get("match_results", [])

            logger.debug(f"DE 수집: {len(results['de_matches'])}개 경기")

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

            page_num = (i // 10) + 1
            logger.info(f"[{i+1}/{len(competitions)}] {comp.name} (page {page_num})")

            try:
                comp_data = await self.scrape_competition_full(comp, page_num=page_num)

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
    parser.add_argument("--headless", action="store_true", default=True, help="헤드리스 모드")
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
