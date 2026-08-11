"""
익산 인터내셔널 대회 전용 스텔스 스크래퍼 v2
- 스텔스 모드: 긴 딜레이(5-10초), User-Agent 로테이션
- 국제대회 연령 매핑 (U17, U20 등)
- 진행 중/완료 대회 구분 처리
- 새로운 협회 사이트 URL 구조 지원 (2024-2025)
"""
import asyncio
import json
import re
import random
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict, field
from playwright.async_api import async_playwright, Browser, Page
from loguru import logger
from bs4 import BeautifulSoup

# ============================================
# 스텔스 설정 (봇 탐지 회피)
# ============================================
STEALTH_DELAY_MIN = 5.0   # 최소 대기 시간 (초)
STEALTH_DELAY_MAX = 10.0  # 최대 대기 시간 (초)
PAGE_LOAD_DELAY = 3.0     # 페이지 로드 후 대기 (초)

# 익산 대회 코드
IKSAN_COMPETITIONS = {
    'U17_U20': 'COMPM00666',  # 2025-12-16 ~ 2025-12-21 (진행중)
    'U13_U11_U9': 'COMPM00673',  # 2025-12-20 ~ 2025-12-21 (접수마감)
}

# User-Agent 로테이션 풀
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
]

# 국제대회 연령 매핑
INTERNATIONAL_AGE_MAPPING = {
    'U9': 'Y8',
    'U11': 'Y10',
    'U13': 'Y12',
    'U17': ['Y14', 'Cadet'],  # 선수별 판단 필요
    'U20': 'Junior',
}

# 익산 대회 키워드
IKSAN_KEYWORDS = ['익산', '인터내셔널', 'iksan', 'international', '코리아']


async def stealth_delay():
    """스텔스 모드 랜덤 딜레이"""
    delay = random.uniform(STEALTH_DELAY_MIN, STEALTH_DELAY_MAX)
    logger.debug(f"스텔스 딜레이: {delay:.1f}초 대기")
    await asyncio.sleep(delay)


def get_random_user_agent() -> str:
    """랜덤 User-Agent 반환"""
    return random.choice(USER_AGENTS)


def map_international_age_group(age_category: str, player_birth_year: Optional[int] = None) -> str:
    """
    국제대회 연령 카테고리를 한국 연령대로 매핑

    Args:
        age_category: U9, U11, U13, U17, U20 등
        player_birth_year: 선수 출생연도 (U17 판단용)

    Returns:
        한국 연령대 (Y8, Y10, Y12, Y14, Cadet, Junior)
    """
    # 대문자로 정규화
    age_key = age_category.upper().strip()

    if age_key in INTERNATIONAL_AGE_MAPPING:
        mapped = INTERNATIONAL_AGE_MAPPING[age_key]

        # U17은 Y14/Cadet 판단 필요
        if age_key == 'U17' and isinstance(mapped, list):
            if player_birth_year:
                current_year = datetime.now().year
                age = current_year - player_birth_year
                # 15세 이하: Y14, 16세 이상: Cadet
                return 'Y14' if age <= 15 else 'Cadet'
            # 출생연도 없으면 기본값 Cadet
            return 'Cadet'

        return mapped

    # 매핑 없으면 원본 반환
    return age_category


def detect_age_category_from_event(event_name: str) -> Optional[str]:
    """이벤트명에서 연령 카테고리 추출"""
    # U9, U11, U13, U17, U20 패턴 찾기
    match = re.search(r'U\s*(\d+)', event_name, re.IGNORECASE)
    if match:
        return f"U{match.group(1)}"
    return None


@dataclass
class IksanCompetition:
    """익산 대회 정보"""
    event_cd: str
    name: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: str = ""  # 진행중, 종료
    age_category: str = ""  # U17, U20, U13 등


@dataclass
class IksanEvent:
    """익산 종목 정보"""
    event_cd: str
    sub_event_cd: str
    name: str
    weapon: str = ""
    gender: str = ""
    age_category: str = ""
    mapped_age_group: str = ""  # 한국 연령대로 매핑된 값
    status: str = ""  # 예선중, 본선중, 종료


@dataclass
class PoolResult:
    """풀 결과"""
    position: int
    name: str
    team: str
    scores: List[str]
    win_rate: str
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
    pool_number: int
    piste: str = ""
    time: str = ""
    referee: str = ""
    results: List[PoolResult] = field(default_factory=list)
    bouts: List[PoolBout] = field(default_factory=list)


@dataclass
class EventResults:
    """종목 결과 - full_scraper와 동일한 구조"""
    event_cd: str
    sub_event_cd: str
    event_name: str
    age_category: str
    mapped_age_group: str
    # Pool 데이터
    pool_rounds: List[Dict] = field(default_factory=list)  # 풀 라운드별 결과
    pool_total_ranking: List[Dict] = field(default_factory=list)  # 풀 종합 순위
    # DE 데이터
    de_bracket: Dict = field(default_factory=dict)  # DE 대진표 트리
    de_matches: List[Dict] = field(default_factory=list)  # DE 경기 결과
    final_rankings: List[Dict] = field(default_factory=list)  # 최종 순위
    # 메타
    total_participants: int = 0
    status: str = ""  # pool_complete, de_in_progress, complete
    # 하위 호환
    pools: List[Pool] = field(default_factory=list)  # 기존 호환용


class IksanStealthScraper:
    """익산 인터내셔널 대회 스텔스 스크래퍼 v2"""

    BASE_URL = "https://fencing.sports.or.kr"

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._browser: Optional[Browser] = None
        self._playwright = None
        self._user_agent = get_random_user_agent()

    async def __aenter__(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def _new_page(self) -> Page:
        """스텔스 설정된 새 페이지 생성"""
        context = await self._browser.new_context(
            user_agent=self._user_agent,
            viewport={'width': 1920, 'height': 1080},
            locale='ko-KR',
        )
        page = await context.new_page()

        # 웹드라이버 탐지 우회
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        return page

    async def get_competition_events(self, event_cd: str) -> List[IksanEvent]:
        """대회의 종목 목록 수집 (새 URL 구조)"""
        page = await self._new_page()
        events = []

        try:
            # 새로운 URL 구조
            url = f"{self.BASE_URL}/game/compListView?code=game&eventCd={event_cd}&gubun=2&pageNum=1"
            logger.info(f"종목 수집: {url}")
            await page.goto(url, wait_until="networkidle")
            await asyncio.sleep(PAGE_LOAD_DELAY)

            await stealth_delay()

            # 대진표 탭 클릭
            bracket_tab = page.locator('a:has-text("대진표")')
            if await bracket_tab.count() > 0:
                await bracket_tab.first.click()
                await asyncio.sleep(2)

            # 종목 SELECT 드롭다운 찾기
            select = page.locator('select').first
            if await select.count() == 0:
                logger.warning("종목 드롭다운을 찾을 수 없습니다")
                return events

            # 모든 옵션 수집
            options = await select.locator('option').all()

            for opt in options:
                text = await opt.inner_text()
                if not text.strip():
                    continue

                # 연령대 파싱
                age_cat = None
                if '17세이하' in text:
                    age_cat = 'U17'
                elif '20세이하' in text:
                    age_cat = 'U20'
                elif '13세이하' in text:
                    age_cat = 'U13'
                elif '11세이하' in text:
                    age_cat = 'U11'
                elif '9세이하' in text:
                    age_cat = 'U9'

                # 무기 파싱
                weapon = ""
                if '플러레' in text or '플뢰레' in text:
                    weapon = "플뢰레"
                elif '에뻬' in text or '에페' in text:
                    weapon = "에페"
                elif '사브르' in text:
                    weapon = "사브르"

                # 성별 파싱
                gender = ""
                if '남자' in text:
                    gender = "남"
                elif '여자' in text:
                    gender = "여"

                mapped_age = map_international_age_group(age_cat) if age_cat else ""

                event = IksanEvent(
                    event_cd=event_cd,
                    sub_event_cd=text.strip(),  # 옵션 텍스트를 식별자로 사용
                    name=text.strip(),
                    weapon=weapon,
                    gender=gender,
                    age_category=age_cat or "",
                    mapped_age_group=mapped_age,
                )
                events.append(event)
                logger.info(f"  종목: {text} → {mapped_age or '기본'}")

        except Exception as e:
            logger.error(f"종목 수집 실패: {e}")
        finally:
            await page.close()

        return events

    async def _parse_pool_total_ranking(self, page: Page) -> List[Dict]:
        """풀 최종 랭킹 (Pool Total) 파싱 - 진출자 + 탈락자 모두 추출"""
        try:
            all_rankings = []

            # 뿔 최종 랭킹 링크 클릭
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

            # 2단계: 탈락자랭킹 선택
            try:
                await page.evaluate("""
                    () => {
                        const popup = document.querySelector('#layer_final_ranking');
                        if (!popup) return;

                        const selects = popup.querySelectorAll('select');
                        for (const select of selects) {
                            const options = select.querySelectorAll('option');
                            for (const option of options) {
                                if (option.textContent.includes('탈락자') || option.value.includes('elim')) {
                                    select.value = option.value;
                                    select.dispatchEvent(new Event('change', { bubbles: true }));
                                    return;
                                }
                            }
                        }
                    }
                """)
                await page.wait_for_timeout(500)

                # 탈락자랭킹 데이터 추출
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

            logger.info(f"풀 최종 랭킹 총 {len(all_rankings)}명")
            return all_rankings

        except Exception as e:
            logger.debug(f"풀 최종 랭킹 파싱 오류: {e}")
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

                            break;
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

            # 엘리미나시옹디렉트 대진표 전체를 파싱
            bracket_result = await page.evaluate("""
                () => {
                    const result = {
                        rounds: [],
                        seeding: [],
                        match_results: [],
                        round_headers: [],
                        full_bouts: []
                    };

                    // 라운드 탭 수집
                    const tabLinks = document.querySelectorAll('ul li a');
                    tabLinks.forEach(link => {
                        const text = link.textContent.trim();
                        if (text.match(/\\d+강전|준결승|결승/)) {
                            if (!result.rounds.includes(text)) {
                                result.rounds.push(text);
                            }
                        }
                    });

                    // 라운드 헤더 수집
                    const headerCells = document.querySelectorAll('table td');
                    headerCells.forEach(cell => {
                        const text = cell.textContent.trim();
                        if (text.match(/^\\d+\\s*엘리미나시옹디렉트$/)) {
                            result.round_headers.push(text);
                        }
                    });

                    // 선수 정보 추출 헬퍼
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

                    // 모든 중첩 테이블에서 선수 정보 추출
                    const nestedTables = document.querySelectorAll('table table');
                    let tableIndex = 0;

                    nestedTables.forEach(nestedTable => {
                        const rows = Array.from(nestedTable.querySelectorAll('tr'));
                        const players = [];

                        rows.forEach(row => {
                            const cell = row.querySelector('td');
                            const player = extractPlayerFromCell(cell);
                            if (player) {
                                players.push(player);
                            }
                        });

                        // 2명씩 묶어서 경기 매칭
                        for (let i = 0; i < players.length; i += 2) {
                            const player1 = players[i];
                            const player2 = players[i + 1];

                            if (!player1) continue;

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

                            let winner = null, loser = null;
                            if (player1.is_winner) {
                                winner = player1;
                                loser = player2;
                            } else if (player2.is_winner) {
                                winner = player2;
                                loser = player1;
                            }

                            if (winner && loser) {
                                result.full_bouts.push({
                                    table_index: tableIndex,
                                    winner: {
                                        seed: winner.seed,
                                        name: winner.name,
                                        team: winner.team || loser.team,
                                        score: winner.score.winner_score
                                    },
                                    loser: {
                                        seed: loser.seed,
                                        name: loser.name,
                                        team: loser.team || winner.team,
                                        score: winner.score.loser_score
                                    },
                                    score: winner.score
                                });

                                result.match_results.push({
                                    table_index: tableIndex,
                                    seed: winner.seed,
                                    name: winner.name,
                                    team: winner.team,
                                    score: winner.score,
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

            # 시딩은 첫 번째 테이블만
            all_seeding = bracket_result.get("seeding", [])
            initial_seeding = [s for s in all_seeding if s.get("table_index") == 0]
            bracket_data["seeding"] = initial_seeding

            # 경기 결과에 라운드명 추가
            all_match_results = bracket_result.get("match_results", [])

            tables_with_matches = {}
            for match in all_match_results:
                table_idx = match.get("table_index", 0)
                if table_idx not in tables_with_matches:
                    tables_with_matches[table_idx] = []
                tables_with_matches[table_idx].append(match)

            sorted_tables = sorted(tables_with_matches.keys())

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

            table_to_round = {}
            for table_idx in sorted_tables:
                match_count = len(tables_with_matches[table_idx])
                table_to_round[table_idx] = get_round_name(match_count)

            for match in all_match_results:
                table_idx = match.get("table_index", 0)
                match["round"] = table_to_round.get(table_idx, f"라운드 {table_idx}")

            bracket_data["match_results"] = all_match_results

            # full_bouts에도 라운드 정보 추가
            all_full_bouts = bracket_result.get("full_bouts", [])

            name_to_team = {}
            for s in initial_seeding:
                name = s.get("name", "")
                team = s.get("team", "")
                if name and team:
                    name_to_team[name] = team

            for bout in all_full_bouts:
                table_idx = bout.get("table_index", 0)
                bout["round"] = table_to_round.get(table_idx, f"라운드 {table_idx}")

                winner = bout.get("winner", {})
                loser = bout.get("loser", {})

                if not winner.get("team") and winner.get("name") in name_to_team:
                    winner["team"] = name_to_team[winner["name"]]
                if not loser.get("team") and loser.get("name") in name_to_team:
                    loser["team"] = name_to_team[loser["name"]]

            bracket_data["full_bouts"] = all_full_bouts

            # 라운드별 결과 그룹화
            results_by_round = {}
            for match in all_match_results:
                round_name = match.get("round", "Unknown")
                if round_name not in results_by_round:
                    results_by_round[round_name] = []
                results_by_round[round_name].append(match)
            bracket_data["results_by_round"] = results_by_round

            logger.info(f"대진표 시딩: {len(initial_seeding)}개, 경기결과: {len(all_match_results)}개, 완전경기: {len(all_full_bouts)}개")

            return bracket_data

        except Exception as e:
            logger.error(f"대진표 파싱 오류: {e}")
            return {"rounds": [], "matches": [], "bracket_tree": {}, "seeding": [], "match_results": []}

    async def _parse_pool_results_v2(self, page: Page) -> List[Dict]:
        """풀 결과 파싱 - full_scraper 호환 형식"""
        pool_rounds = []

        try:
            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')

            tables = soup.find_all('table')
            pool_num = 1

            for table in tables:
                rows = table.find_all('tr')
                if len(rows) < 2:
                    continue

                header = rows[0]
                cols = header.find_all(['th', 'td'])
                if len(cols) < 5:
                    continue

                header_text = ' '.join([c.get_text() for c in cols])
                if '승률' not in header_text or '랭킹' not in header_text:
                    continue

                pool_data = {
                    "pool_number": pool_num,
                    "piste": "",
                    "time": "",
                    "referee": "",
                    "results": [],
                    "bouts": []
                }

                for row in rows[1:]:
                    cells = row.find_all('td')
                    if len(cells) < 4:
                        continue

                    try:
                        pos = int(cells[0].get_text().strip()) if cells[0].get_text().strip().isdigit() else 0
                        name = cells[1].get_text().strip()
                        team = cells[2].get_text().strip()

                        scores = []
                        for i in range(3, len(cells) - 4):
                            score_text = cells[i].get_text().strip()
                            scores.append(score_text)

                        win_rate = cells[-4].get_text().strip()
                        indicator_text = cells[-3].get_text().strip()
                        touches_text = cells[-2].get_text().strip()
                        rank_text = cells[-1].get_text().strip()

                        indicator = int(indicator_text) if indicator_text.lstrip('-').isdigit() else 0
                        touches = int(touches_text) if touches_text.isdigit() else 0
                        rank = int(rank_text) if rank_text.isdigit() else 0

                        # win_rate에서 wins/losses 추출
                        wins = 0
                        losses = 0
                        if '/' in win_rate:
                            parts = win_rate.split('/')
                            if len(parts) == 2:
                                try:
                                    wins = int(parts[0])
                                    losses = int(parts[1])
                                except:
                                    pass

                        pool_data["results"].append({
                            "position": pos,
                            "name": name,
                            "team": team,
                            "scores": scores,
                            "win_rate": win_rate,
                            "wins": wins,
                            "losses": losses,
                            "indicator": indicator,
                            "touches": touches,
                            "rank": rank
                        })

                    except Exception as e:
                        logger.debug(f"행 파싱 오류: {e}")
                        continue

                if pool_data["results"]:
                    pool_rounds.append(pool_data)
                    pool_num += 1

        except Exception as e:
            logger.error(f"풀 결과 파싱 오류: {e}")

        return pool_rounds

    async def scrape_event_results(self, event_cd: str, event_name: str) -> EventResults:
        """종목 결과 수집 - full_scraper 호환 구조"""
        page = await self._new_page()

        # 연령대 파싱
        age_cat = None
        if '17세이하' in event_name:
            age_cat = 'U17'
        elif '20세이하' in event_name:
            age_cat = 'U20'
        elif '13세이하' in event_name:
            age_cat = 'U13'
        elif '11세이하' in event_name:
            age_cat = 'U11'
        elif '9세이하' in event_name:
            age_cat = 'U9'
        mapped_age = map_international_age_group(age_cat) if age_cat else ""

        results = EventResults(
            event_cd=event_cd,
            sub_event_cd=event_name,
            event_name=event_name,
            age_category=age_cat or "",
            mapped_age_group=mapped_age,
        )

        target_value = None

        try:
            # 새로운 URL 구조
            url = f"{self.BASE_URL}/game/compListView?code=game&eventCd={event_cd}&gubun=2&pageNum=1"
            logger.info(f"결과 수집: {event_name}")
            await page.goto(url, wait_until="networkidle")
            await asyncio.sleep(PAGE_LOAD_DELAY)

            await stealth_delay()

            # 경기결과 탭 클릭
            result_tab = page.locator('a:has-text("경기결과")')
            if await result_tab.count() > 0:
                await result_tab.first.click()
                await asyncio.sleep(2)

            # 종목 선택 (value 기반 + 검색 버튼 클릭)
            select = page.locator('select').first
            if await select.count() > 0:
                options = await select.locator('option').all()
                for opt in options:
                    opt_text = await opt.text_content()
                    if opt_text and event_name in opt_text:
                        target_value = await opt.get_attribute('value')
                        break

                if target_value:
                    await select.select_option(value=target_value)
                else:
                    await select.select_option(label=event_name)
                await asyncio.sleep(1)

                search_btn = page.locator("a[href='#search']").first
                if await search_btn.count() > 0:
                    await search_btn.click()
                    await asyncio.sleep(2)

            await stealth_delay()

            # ============================================================
            # 1. 풀 결과 파싱 (pool_rounds)
            # ============================================================
            pool_rounds = await self._parse_pool_results_v2(page)
            results.pool_rounds = pool_rounds
            logger.info(f"  풀 라운드 {len(pool_rounds)}개 수집")

            # ============================================================
            # 2. 풀 최종 랭킹 파싱 (pool_total_ranking)
            # ============================================================
            try:
                pool_total = await self._parse_pool_total_ranking(page)
                results.pool_total_ranking = pool_total
                logger.info(f"  풀 최종 랭킹 {len(pool_total)}명 수집")
            except Exception as e:
                logger.debug(f"풀 최종 랭킹 파싱 오류: {e}")

            # ============================================================
            # 3. 최종 순위 파싱 (경기결과 → 엘리미나시옹디렉트)
            # ============================================================
            try:
                # 팝업 닫기
                await page.evaluate("""
                    const popups = document.querySelectorAll('.layer_pop, #layer_final_ranking, [id*="layer"]');
                    popups.forEach(p => p.style.display = 'none');
                """)
                await page.wait_for_timeout(300)

                de_tab = page.locator("a:has-text('엘리미나시옹디렉트')").first
                await de_tab.click(timeout=5000, force=True)
                await page.wait_for_timeout(1000)

                final_rankings = await self._parse_final_rankings_v2(page)
                results.final_rankings = final_rankings
                results.total_participants = len(final_rankings)
                logger.info(f"  최종 순위 {len(final_rankings)}명 수집")
            except Exception as e:
                logger.debug(f"최종 순위 파싱 오류: {e}")

            # ============================================================
            # 4. DE 대진표 파싱 (대진표 탭 → 엘리미나시옹디렉트)
            # ============================================================
            try:
                await stealth_delay()

                # 팝업 닫기
                await page.evaluate("""
                    const popups = document.querySelectorAll('.layer_pop, #layer_final_ranking, [id*="layer"]');
                    popups.forEach(p => p.style.display = 'none');
                """)
                await page.wait_for_timeout(300)

                # "대진표" 메인 탭 클릭
                bracket_main_tab = page.locator("a:has-text('대진표')").first
                await bracket_main_tab.click(timeout=5000, force=True)
                await page.wait_for_timeout(1500)
                logger.info("  대진표 메인 탭 클릭 완료")

                # 종목 다시 선택
                try:
                    select = page.locator('select').first
                    if target_value:
                        await select.select_option(value=target_value)
                    else:
                        await select.select_option(label=event_name)
                    await page.wait_for_timeout(500)

                    search_btn = page.locator("a[href='#search']").first
                    await search_btn.click()
                    await page.wait_for_timeout(1000)
                except Exception as e:
                    logger.debug(f"대진표 탭에서 종목 선택 오류: {e}")

                # "엘리미나시옹디렉트" 서브 탭 클릭
                de_bracket_tab = page.locator("a:has-text('엘리미나시옹디렉트')").first
                await de_bracket_tab.click(timeout=5000, force=True)
                await page.wait_for_timeout(1500)
                logger.info("  엘리미나시옹디렉트 대진표 탭 클릭 완료")

                # 대진표 데이터 수집
                bracket_data = await self._parse_de_bracket(page)
                results.de_bracket = bracket_data

                # match_results를 de_matches로 복사
                de_matches = bracket_data.get("match_results", [])
                results.de_matches = de_matches

                logger.info(f"  DE 대진표 수집 완료: {len(de_matches)}개 경기, 시드: {len(bracket_data.get('seeding', []))}명")

            except Exception as e:
                logger.debug(f"DE 대진표 파싱 오류: {e}")

            # 결과 상태 판단
            if results.final_rankings:
                results.status = 'complete'
            elif results.de_matches:
                results.status = 'de_in_progress'
            elif results.pool_rounds:
                results.status = 'pool_complete'
            else:
                results.status = 'no_results'

            logger.info(f"  종합 상태: {results.status}")

        except Exception as e:
            logger.error(f"결과 수집 실패: {e}")
            results.status = 'error'
        finally:
            await page.close()

        return results


async def scrape_iksan_now():
    """익산 대회 즉시 수집 - U17/U20 + U13/U11/U9"""
    logger.info("=" * 50)
    logger.info("익산 인터내셔널 대회 스텔스 수집 시작")
    logger.info("=" * 50)

    async with IksanStealthScraper(headless=True) as scraper:
        all_competitions_data = []

        # 수집할 대회 목록
        competitions_to_scrape = [
            ('U17_U20', '2025 코리아 익산 인터내셔널 펜싱선수권대회(U17,U20)'),
            ('U13_U11_U9', '2025 코리아 익산 인터내셔널 펜싱선수권대회(U13,U11,U9)'),
        ]

        for comp_key, comp_name in competitions_to_scrape:
            event_cd = IKSAN_COMPETITIONS[comp_key]
            logger.info(f"\n{'=' * 50}")
            logger.info(f"=== {comp_name} ({event_cd}) ===")
            logger.info("=" * 50)

            all_results = []

            # 1. 종목 목록 수집
            events = await scraper.get_competition_events(event_cd)
            logger.info(f"총 {len(events)}개 종목 발견")

            if len(events) == 0:
                logger.warning(f"{comp_key}: 종목이 없습니다 (아직 등록 안됨)")
                continue

            # 2. 각 종목 결과 수집
            for event in events:
                await stealth_delay()
                result = await scraper.scrape_event_results(event_cd, event.name)

                # 결과를 딕셔너리로 변환 - full_scraper 호환 구조
                result_dict = {
                    'event_cd': result.event_cd,
                    'sub_event_cd': result.sub_event_cd,
                    'event_name': result.event_name,
                    'age_category': result.age_category,
                    'mapped_age_group': result.mapped_age_group,
                    'status': result.status,
                    # Pool 데이터
                    'pool_rounds': result.pool_rounds,
                    'pool_total_ranking': result.pool_total_ranking,
                    # DE 데이터
                    'de_bracket': result.de_bracket,
                    'de_matches': result.de_matches,
                    # 최종 순위
                    'final_rankings': result.final_rankings,
                    'total_participants': result.total_participants,
                }

                all_results.append(result_dict)

            # 대회별 데이터 저장
            comp_data = {
                'competition_key': comp_key,
                'competition_name': comp_name,
                'event_cd': event_cd,
                'events': [asdict(e) for e in events],
                'results': all_results,
            }
            all_competitions_data.append(comp_data)

        # 3. 통합 결과 저장
        output_file = 'data/iksan_international_2025.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump({
                'scraped_at': datetime.now().isoformat(),
                'competitions': all_competitions_data,
            }, f, ensure_ascii=False, indent=2)

        logger.info(f"\n{'=' * 50}")
        logger.info(f"저장 완료: {output_file}")

        # 요약 출력
        for comp_data in all_competitions_data:
            comp_name = comp_data['competition_name']
            events = comp_data['events']
            results = comp_data['results']

            total_pool_entries = 0
            total_de_matches = 0
            total_final_rankings = 0
            for result in results:
                for pool in result.get('pool_rounds', []):
                    total_pool_entries += len(pool.get('results', []))
                total_de_matches += len(result.get('de_matches', []))
                total_final_rankings += len(result.get('final_rankings', []))

            logger.info(f"\n📊 {comp_name}")
            logger.info(f"  종목: {len(events)}개, 결과: {len(results)}개")
            logger.info(f"  풀 선수 데이터: {total_pool_entries}건")
            logger.info(f"  DE 경기: {total_de_matches}건")
            logger.info(f"  최종 순위: {total_final_rankings}명")


async def check_iksan_updates():
    """익산 대회 업데이트 확인 (스케줄러용)"""
    logger.info("익산 대회 업데이트 확인 중...")

    async with IksanStealthScraper(headless=True) as scraper:
        event_cd = IKSAN_COMPETITIONS['U17_U20']

        # 기존 데이터 로드
        existing_file = 'data/iksan_international_2025.json'
        try:
            with open(existing_file, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        except FileNotFoundError:
            logger.info("기존 데이터 없음, 전체 수집 시작")
            await scrape_iksan_now()
            return

        # 각 종목의 새 결과 확인
        events = existing.get('events', [])
        updates_found = 0

        for event_data in events[:3]:  # 처음 3개 종목만 확인 (스텔스)
            event_name = event_data['name']
            await stealth_delay()

            result = await scraper.scrape_event_results(event_cd, event_name)

            # 기존 결과와 비교
            old_result = next(
                (r for r in existing.get('results', []) if r['event_name'] == event_name),
                None
            )

            if old_result:
                old_pool_count = len(old_result.get('pool_rounds', []))
                new_pool_count = len(result.pool_rounds)
                old_de_count = len(old_result.get('de_matches', []))
                new_de_count = len(result.de_matches)

                if new_pool_count > old_pool_count:
                    logger.info(f"  {event_name}: 새로운 풀 결과 발견!")
                    updates_found += 1
                elif new_de_count > old_de_count:
                    logger.info(f"  {event_name}: 새로운 DE 경기 발견!")
                    updates_found += 1

        if updates_found > 0:
            logger.info(f"총 {updates_found}개 업데이트 발견, 전체 수집 시작")
            await scrape_iksan_now()
        else:
            logger.info("새로운 업데이트 없음")


if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == '--check':
        asyncio.run(check_iksan_updates())
    else:
        asyncio.run(scrape_iksan_now())
