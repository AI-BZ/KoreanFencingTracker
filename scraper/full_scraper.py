"""
개선된 대한펜싱협회 스크래퍼 v2.0
- 풀 결과 점수 매트릭스 전체 파싱
- 최종 순위 파싱
- 풀 개별 경기(bout) 추출
- 선수 정규화
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
            except:
                return events

            # 경기결과 탭 클릭
            try:
                result_tab = page.locator("a:has-text('경기결과')")
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

            # 경기결과 탭 클릭
            result_tab = page.locator("a:has-text('경기결과')")
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

            # 엘리미나시옹디렉트 탭 클릭 → 최종 순위
            try:
                de_tab = page.locator("a:has-text('엘리미나시옹디렉트')")
                await de_tab.click(timeout=3000)
                await page.wait_for_timeout(1000)

                results["final_rankings"] = await self._parse_final_rankings_v2(page)
                results["total_participants"] = len(results["final_rankings"])
            except:
                pass

        except Exception as e:
            logger.error(f"결과 조회 오류 ({event_cd}/{sub_event_cd}): {e}")
        finally:
            await page.close()

        return results

    async def _parse_pool_results_v2(self, page: Page) -> List[Dict]:
        """개선된 풀 결과 파싱 - 점수 매트릭스 포함"""
        try:
            pool_data = await page.evaluate("""
                () => {
                    const pools = [];
                    const container = document.querySelector('[class*="result"], [id*="result"]') || document.body;

                    // 풀 정보 리스트와 테이블 찾기
                    const poolInfoLists = container.querySelectorAll('ul');
                    const poolTables = container.querySelectorAll('table');

                    let poolNumber = 0;
                    let roundNumber = 1;

                    poolTables.forEach((table, tableIdx) => {
                        const headers = table.querySelectorAll('th');
                        const headerTexts = Array.from(headers).map(h => h.textContent.trim());

                        // 풀 결과 테이블 확인 (No, 이름, 소속팀, 승률 컬럼 필요)
                        if (headerTexts.includes('이름') && headerTexts.includes('소속팀') && headerTexts.includes('승률')) {
                            poolNumber++;

                            // 풀 메타 정보 찾기 (이전 ul에서)
                            let poolInfo = { piste: '', time: '', referee: '' };
                            if (tableIdx > 0) {
                                // 테이블 바로 앞의 ul 찾기
                                let prevSibling = table.previousElementSibling;
                                while (prevSibling && prevSibling.tagName !== 'UL') {
                                    prevSibling = prevSibling.previousElementSibling;
                                }
                                if (prevSibling && prevSibling.tagName === 'UL') {
                                    const items = prevSibling.querySelectorAll('li');
                                    items.forEach(item => {
                                        const text = item.textContent.trim();
                                        if (text.includes('삐스트')) poolInfo.piste = text.replace('삐스트', '').trim();
                                        if (text.includes('시간')) poolInfo.time = text.replace('시간', '').trim();
                                        if (text.includes('심판')) poolInfo.referee = text.replace('심판', '').trim();
                                    });
                                }
                            }

                            const results = [];
                            const bouts = [];
                            const rows = table.querySelectorAll('tbody tr, tr:not(:first-child)');
                            const players = [];  // 선수 목록 저장

                            rows.forEach((row, rowIdx) => {
                                const cells = row.querySelectorAll('td');
                                if (cells.length >= 11) {  // No, 이름, 소속팀, 1-7, 승률, 지수, 득점, 랭킹
                                    const no = parseInt(cells[0]?.textContent?.trim()) || rowIdx + 1;
                                    const name = cells[1]?.textContent?.trim() || '';
                                    const team = cells[2]?.textContent?.trim() || '';

                                    // 점수 배열 추출 (1-7번 컬럼)
                                    const scores = [];
                                    const numOpponents = Math.min(7, cells.length - 7);  // 상대 수

                                    for (let i = 0; i < numOpponents; i++) {
                                        const scoreCell = cells[3 + i];
                                        let scoreText = scoreCell?.textContent?.trim() || '';

                                        if (i === rowIdx) {
                                            scores.push(null);  // 자기 자신
                                        } else if (scoreText === '' || scoreText === '-') {
                                            scores.push(null);
                                        } else if (scoreText.startsWith('V')) {
                                            // V 또는 V4 등
                                            const vScore = scoreText === 'V' ? 5 : parseInt(scoreText.replace('V', '')) || 5;
                                            scores.push({ type: 'V', score: vScore });
                                        } else {
                                            scores.push({ type: 'L', score: parseInt(scoreText) || 0 });
                                        }
                                    }

                                    // 승률 파싱
                                    const winRateText = cells[cells.length - 4]?.textContent?.trim() || '0/0';
                                    const [wins, total] = winRateText.split('/').map(s => parseInt(s) || 0);
                                    const losses = total - wins;

                                    const indicator = parseInt(cells[cells.length - 3]?.textContent?.trim()) || 0;
                                    const touches = parseInt(cells[cells.length - 2]?.textContent?.trim()) || 0;
                                    const rank = parseInt(cells[cells.length - 1]?.textContent?.trim()) || 0;

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
                                }
                            });

                            // 개별 bout 추출 (상위 삼각형만)
                            for (let i = 0; i < players.length; i++) {
                                for (let j = i + 1; j < players.length; j++) {
                                    const p1 = players[i];
                                    const p2 = players[j];

                                    if (p1.scores[j] !== null && p1.scores[j] !== undefined) {
                                        const score1 = p1.scores[j].type === 'V' ? p1.scores[j].score : p1.scores[j].score;
                                        const score2 = p2.scores[i] ? (p2.scores[i].type === 'V' ? p2.scores[i].score : p2.scores[i].score) : 0;
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
                        }
                    });

                    return pools;
                }
            """)

            return pool_data

        except Exception as e:
            logger.error(f"풀 결과 파싱 오류: {e}")
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
            event_data["final_rankings"] = results["final_rankings"]
            event_data["total_participants"] = results["total_participants"]

            data["events"].append(event_data)

            await asyncio.sleep(0.5)

        return data

    async def scrape_all_full(self, start_year: int = 2019, end_year: int = 2025,
                              output_file: str = "data/fencing_full_data.json",
                              limit: int = None,
                              status_filter: str = None) -> None:
        """전체 데이터 수집 (풀 결과 + 순위 포함)"""
        competitions = await self.get_all_competitions(start_year, end_year)

        # 상태 필터링 (종료된 대회만)
        if status_filter:
            competitions = [c for c in competitions if c.status == status_filter]
            logger.info(f"상태 필터 적용 ({status_filter}): {len(competitions)}개 대회")

        if limit:
            competitions = competitions[:limit]

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

        for i, comp in enumerate(competitions):
            page_num = (i // 10) + 1
            logger.info(f"[{i+1}/{len(competitions)}] {comp.name} (page {page_num})")

            try:
                comp_data = await self.scrape_competition_full(comp, page_num=page_num)
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

            await asyncio.sleep(0.5)

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

    args = parser.parse_args()

    async with KFFFullScraper(headless=args.headless) as scraper:
        await scraper.scrape_all_full(
            start_year=args.start_year,
            end_year=args.end_year,
            output_file=args.output,
            limit=args.limit,
            status_filter=args.status
        )


if __name__ == "__main__":
    asyncio.run(main())
