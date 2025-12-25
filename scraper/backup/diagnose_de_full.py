"""
DE 전체 브라켓 구조 확인 - 준결승/결승 위치 찾기
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.async_api import async_playwright
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_URL = "https://fencing.sports.or.kr"


async def diagnose_de_full():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        page.set_default_timeout(15000)

        competition_cd = "COMPM00662"  # 전국체육대회
        event_cd = "COMPS000000000003688"  # 18세이하부 남자 플러레(개)

        # 대회 목록에서 시작
        await page.goto(f"{BASE_URL}/game/compList?code=game", wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)

        # 대회 클릭
        await page.click(f"a[onclick*=\"{competition_cd}\"]", timeout=5000)
        await page.wait_for_timeout(1500)

        # 경기결과 탭 클릭
        result_tab = page.locator("a[onclick*='funcLeftSub']:has-text('경기결과')").first
        await result_tab.click(timeout=3000)
        await page.wait_for_timeout(1500)

        # 종목 선택
        select = page.locator("select").first
        await select.select_option(value=event_cd)
        search_btn = page.locator("a[href='#search']").first
        await search_btn.click()
        await page.wait_for_timeout(1500)

        # 엘리미나시옹디렉트 클릭
        de_tab = page.locator("a:has-text('엘리미나시옹디렉트')").first
        await de_tab.click(timeout=3000)
        await page.wait_for_timeout(1500)

        # 현재 페이지의 전체 HTML에서 결승/준결승 관련 텍스트 검색
        logger.info("=== DE 페이지에서 결승/준결승 관련 텍스트 검색 ===")

        search_result = await page.evaluate("""
            () => {
                const result = {
                    pageText: '',
                    foundKeywords: [],
                    tables: []
                };

                // 페이지 전체 텍스트에서 키워드 검색
                const pageText = document.body.innerText;
                const keywords = ['준결승', '결승', '4강', 'semifinal', 'final', '3-4위', '3위'];
                keywords.forEach(kw => {
                    if (pageText.includes(kw)) {
                        result.foundKeywords.push(kw);
                    }
                });

                // 모든 테이블의 셀에서 결승/준결승 관련 텍스트 검색
                document.querySelectorAll('table').forEach((table, tableIdx) => {
                    const cells = table.querySelectorAll('td');
                    cells.forEach((cell, cellIdx) => {
                        const text = cell.textContent.trim();
                        if (text.match(/(준결승|결승|4강|final|3-4위)/i)) {
                            result.tables.push({
                                tableIdx: tableIdx,
                                cellIdx: cellIdx,
                                text: text.substring(0, 100)
                            });
                        }
                    });
                });

                return result;
            }
        """)

        logger.info(f"발견된 키워드: {search_result['foundKeywords']}")
        logger.info(f"테이블에서 발견: {len(search_result['tables'])}개")
        for item in search_result['tables']:
            logger.info(f"  테이블 {item['tableIdx']}, 셀 {item['cellIdx']}: '{item['text']}'")

        # 스크롤하여 전체 페이지 스캔
        logger.info("\n=== 페이지 스크롤 후 우측 브라켓 검색 ===")

        # 페이지 끝까지 스크롤
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(500)

        # 우측으로 스크롤 (브라켓이 가로로 길 수 있음)
        await page.evaluate("window.scrollTo(document.body.scrollWidth, 0)")
        await page.wait_for_timeout(500)

        # 스크롤 후 다시 검색
        more_tables = await page.evaluate("""
            () => {
                const tables = [];
                const allTables = document.querySelectorAll('table table');

                allTables.forEach((table, idx) => {
                    const rect = table.getBoundingClientRect();
                    const rows = table.querySelectorAll('tr');
                    const playerCount = rows.length;

                    // 경기 수로 라운드 추정
                    const matchCount = Math.floor(playerCount / 2);

                    if (matchCount === 2 || matchCount === 1) {  // 준결승 또는 결승
                        tables.push({
                            tableIdx: idx,
                            x: rect.x,
                            matchCount: matchCount,
                            inferredRound: matchCount === 2 ? '준결승' : '결승',
                            visible: rect.x > 0 && rect.y > 0
                        });
                    }
                });

                return tables;
            }
        """)

        if more_tables:
            logger.info("경기 수 기준 준결승/결승 후보 테이블:")
            for t in more_tables:
                logger.info(f"  테이블 {t['tableIdx']}: {t['matchCount']}경기 → {t['inferredRound']} (x={t['x']:.0f}, visible={t['visible']})")
        else:
            logger.info("준결승/결승 후보 테이블 없음")

        # 최종랭킹에서 DE 순위 확인
        logger.info("\n=== 최종랭킹(DE) 확인 ===")
        ranking_tab = page.locator("a:has-text('뿔 최종 랭킹')").first
        if await ranking_tab.count() > 0:
            await ranking_tab.click(timeout=3000)
            await page.wait_for_timeout(1000)

            # 최종랭킹에서 상위 8명 확인
            rankings = await page.evaluate("""
                () => {
                    const rankings = [];
                    const tables = document.querySelectorAll('table');
                    // 마지막 테이블이 보통 랭킹 테이블
                    const lastTable = tables[tables.length - 1];
                    if (lastTable) {
                        lastTable.querySelectorAll('tr').forEach((row, idx) => {
                            if (idx === 0) return;  // 헤더 건너뛰기
                            const cells = row.querySelectorAll('td');
                            if (cells.length >= 2) {
                                rankings.push({
                                    rank: cells[0]?.textContent.trim(),
                                    name: cells[1]?.textContent.trim(),
                                    team: cells[2]?.textContent.trim() || ''
                                });
                            }
                        });
                    }
                    return rankings.slice(0, 8);
                }
            """)

            if rankings:
                logger.info("뿔 최종 랭킹 상위 8명:")
                for r in rankings:
                    logger.info(f"  {r['rank']}: {r['name']} ({r['team']})")
            else:
                logger.info("뿔 최종 랭킹 데이터 없음")

        # 스크린샷 저장
        await page.screenshot(path="data/diagnose_de_full.png", full_page=True)
        logger.info("\n스크린샷 저장: data/diagnose_de_full.png")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(diagnose_de_full())
