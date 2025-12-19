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
from datetime import datetime, date
from typing import List, Dict, Any, Optional, Tuple
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
    """종목 결과"""
    event_cd: str
    sub_event_cd: str
    event_name: str
    age_category: str
    mapped_age_group: str
    pools: List[Pool] = field(default_factory=list)
    final_ranking: List[Dict] = field(default_factory=list)
    de_matches: List[Dict] = field(default_factory=list)
    status: str = ""  # pool_complete, de_in_progress, complete


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

    async def scrape_event_results(self, event_cd: str, event_name: str) -> EventResults:
        """종목 결과 수집"""
        page = await self._new_page()

        # 연령대 파싱
        age_cat = None
        if '17세이하' in event_name:
            age_cat = 'U17'
        elif '20세이하' in event_name:
            age_cat = 'U20'
        mapped_age = map_international_age_group(age_cat) if age_cat else ""

        results = EventResults(
            event_cd=event_cd,
            sub_event_cd=event_name,
            event_name=event_name,
            age_category=age_cat or "",
            mapped_age_group=mapped_age,
        )

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

            # 종목 선택
            select = page.locator('select').first
            if await select.count() > 0:
                await select.select_option(label=event_name)
                await asyncio.sleep(2)

            await stealth_delay()

            # HTML 파싱
            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')

            # 풀 결과 테이블 파싱
            tables = soup.find_all('table')
            pool_num = 1

            for table in tables:
                rows = table.find_all('tr')
                if len(rows) < 2:
                    continue

                # 헤더 확인
                header = rows[0]
                cols = header.find_all(['th', 'td'])
                if len(cols) < 5:
                    continue

                # 풀 결과 테이블인지 확인 (승률, 지수, 득점, 랭킹 컬럼)
                header_text = ' '.join([c.get_text() for c in cols])
                if '승률' not in header_text or '랭킹' not in header_text:
                    continue

                pool = Pool(pool_number=pool_num)

                for row in rows[1:]:
                    cells = row.find_all('td')
                    if len(cells) < 4:
                        continue

                    try:
                        # No, 이름, 소속팀, 점수들..., 승률, 지수, 득점, 랭킹
                        pos = int(cells[0].get_text().strip()) if cells[0].get_text().strip().isdigit() else 0
                        name = cells[1].get_text().strip()
                        team = cells[2].get_text().strip()

                        # 점수 추출 (3번 컬럼부터 승률 컬럼 전까지)
                        scores = []
                        for i in range(3, len(cells) - 4):
                            score_text = cells[i].get_text().strip()
                            scores.append(score_text)

                        # 마지막 4개 컬럼: 승률, 지수, 득점, 랭킹
                        win_rate = cells[-4].get_text().strip()
                        indicator_text = cells[-3].get_text().strip()
                        touches_text = cells[-2].get_text().strip()
                        rank_text = cells[-1].get_text().strip()

                        indicator = int(indicator_text) if indicator_text.lstrip('-').isdigit() else 0
                        touches = int(touches_text) if touches_text.isdigit() else 0
                        rank = int(rank_text) if rank_text.isdigit() else 0

                        pool_result = PoolResult(
                            position=pos,
                            name=name,
                            team=team,
                            scores=scores,
                            win_rate=win_rate,
                            indicator=indicator,
                            touches=touches,
                            rank=rank,
                        )
                        pool.results.append(pool_result)

                        # 풀 경기(bout) 추출
                        for j, score in enumerate(scores):
                            if not score:
                                continue
                            opponent_idx = j
                            if opponent_idx >= len(pool.results) - 1:
                                continue

                            # V 또는 숫자 점수
                            is_win = score.startswith('V')
                            if is_win:
                                p1_score = 5
                                # 다른 선수의 점수 찾기
                                p2_score = 0
                            else:
                                try:
                                    p1_score = int(score)
                                    p2_score = 5  # 상대가 이김
                                except:
                                    continue

                    except Exception as e:
                        logger.debug(f"행 파싱 오류: {e}")
                        continue

                if pool.results:
                    results.pools.append(pool)
                    pool_num += 1

            # 결과 상태 판단
            if results.pools:
                results.status = 'pool_complete'
            else:
                results.status = 'no_results'

            logger.info(f"  풀 {len(results.pools)}개 수집, 상태: {results.status}")

        except Exception as e:
            logger.error(f"결과 수집 실패: {e}")
            results.status = 'error'
        finally:
            await page.close()

        return results


async def scrape_iksan_now():
    """익산 대회 즉시 수집"""
    logger.info("=" * 50)
    logger.info("익산 인터내셔널 대회 스텔스 수집 시작")
    logger.info("=" * 50)

    async with IksanStealthScraper(headless=True) as scraper:
        all_results = []

        # U17/U20 대회 (진행중)
        event_cd = IKSAN_COMPETITIONS['U17_U20']
        logger.info(f"\n=== 2025 익산 인터내셔널 U17/U20 ({event_cd}) ===")

        # 1. 종목 목록 수집
        events = await scraper.get_competition_events(event_cd)
        logger.info(f"총 {len(events)}개 종목 발견")

        # 2. 각 종목 결과 수집
        for event in events:
            await stealth_delay()
            result = await scraper.scrape_event_results(event_cd, event.name)

            # 결과를 딕셔너리로 변환
            result_dict = {
                'event_cd': result.event_cd,
                'sub_event_cd': result.sub_event_cd,
                'event_name': result.event_name,
                'age_category': result.age_category,
                'mapped_age_group': result.mapped_age_group,
                'status': result.status,
                'pools': [],
            }

            for pool in result.pools:
                pool_dict = {
                    'pool_number': pool.pool_number,
                    'referee': pool.referee,
                    'results': [asdict(r) for r in pool.results],
                }
                result_dict['pools'].append(pool_dict)

            all_results.append(result_dict)

        # 3. 결과 저장
        output_file = 'data/iksan_international_2025.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump({
                'scraped_at': datetime.now().isoformat(),
                'competition_name': '2025 코리아 익산 인터내셔널 펜싱선수권대회(U17,U20)',
                'event_cd': event_cd,
                'events': [asdict(e) for e in events],
                'results': all_results,
            }, f, ensure_ascii=False, indent=2)

        logger.info(f"\n저장 완료: {output_file}")
        logger.info(f"종목: {len(events)}개, 결과: {len(all_results)}개")

        # 요약 출력
        total_players = 0
        for result in all_results:
            for pool in result['pools']:
                total_players += len(pool['results'])

        logger.info(f"총 선수 데이터: {total_players}명")


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
                old_pool_count = len(old_result.get('pools', []))
                new_pool_count = len(result.pools)

                if new_pool_count > old_pool_count:
                    logger.info(f"  {event_name}: 새로운 풀 결과 발견!")
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
