"""
모든 탭 진단 - 준결승/결승 데이터 위치 찾기
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


async def diagnose_all_tabs():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        page.set_default_timeout(15000)

        competition_cd = "COMPM00663"
        event_cd = "COMPS000000000003727"

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

        logger.info("=== 경기결과 탭에서 사용 가능한 서브탭 ===")

        # 경기결과 하위의 탭들 확인
        sub_tabs = await page.evaluate("""
            () => {
                const tabs = [];
                document.querySelectorAll('a').forEach((a, idx) => {
                    const text = a.textContent.trim();
                    const onclick = a.getAttribute('onclick') || '';
                    if (text && text.length < 30) {
                        // 관련 키워드 포함된 탭만
                        if (text.includes('예선') || text.includes('최종') ||
                            text.includes('결승') || text.includes('엘리미나시옹') ||
                            text.includes('랭킹') || text.includes('경기') ||
                            text.includes('대진') || text.includes('결과')) {
                            tabs.push({index: idx, text: text, onclick: onclick.substring(0, 80)});
                        }
                    }
                });
                return tabs;
            }
        """)

        for tab in sub_tabs:
            logger.info(f"  [{tab['index']}] '{tab['text']}' - {tab['onclick']}")

        # 엘리미나시옹디렉트 탭 클릭
        de_tab = page.locator("a:has-text('엘리미나시옹디렉트')").first
        if await de_tab.count() > 0:
            await de_tab.click(timeout=3000)
            await page.wait_for_timeout(1500)
            logger.info("\n'엘리미나시옹디렉트' 클릭 후 탭 구조:")

            sub_tabs2 = await page.evaluate("""
                () => {
                    const tabs = [];
                    document.querySelectorAll('ul li a').forEach((a, idx) => {
                        const text = a.textContent.trim();
                        if (text.length < 30) {
                            tabs.push({index: idx, text: text});
                        }
                    });
                    return tabs;
                }
            """)
            for tab in sub_tabs2:
                logger.info(f"  [{tab['index']}] '{tab['text']}'")

        # 최종랭킹 탭 확인
        logger.info("\n=== 최종랭킹 탭 확인 ===")
        ranking_tab = page.locator("a:has-text('최종랭킹')").first
        if await ranking_tab.count() > 0:
            await ranking_tab.click(timeout=3000)
            await page.wait_for_timeout(1500)

            # 최종랭킹 데이터
            ranking_data = await page.evaluate("""
                () => {
                    const rankings = [];
                    const rows = document.querySelectorAll('table tr');
                    rows.forEach((row, idx) => {
                        const cells = row.querySelectorAll('td');
                        if (cells.length >= 3) {
                            rankings.push({
                                rank: cells[0]?.textContent.trim(),
                                name: cells[1]?.textContent.trim(),
                                team: cells[2]?.textContent.trim()
                            });
                        }
                    });
                    return rankings.slice(0, 8);  // 상위 8명만
                }
            """)

            for r in ranking_data:
                logger.info(f"  {r['rank']}위: {r['name']} ({r['team']})")

        # 대진표 탭 클릭하고 확인
        logger.info("\n=== 대진표 탭 확인 ===")
        bracket_tab = page.locator("a:has-text('대진표')").first
        if await bracket_tab.count() > 0:
            await bracket_tab.click(timeout=5000, force=True)
            await page.wait_for_timeout(1500)

            # 종목 다시 선택
            select = page.locator("select").first
            await select.select_option(value=event_cd)
            search_btn = page.locator("a[href='#search']").first
            await search_btn.click()
            await page.wait_for_timeout(1000)

            # 대진표 하위 탭들
            bracket_sub_tabs = await page.evaluate("""
                () => {
                    const tabs = [];
                    document.querySelectorAll('ul li a').forEach((a, idx) => {
                        const text = a.textContent.trim();
                        if (text.length < 30) {
                            tabs.push({index: idx, text: text});
                        }
                    });
                    return tabs;
                }
            """)

            logger.info("대진표 하위 탭:")
            for tab in bracket_sub_tabs:
                if any(kw in tab['text'] for kw in ['엘리미나시옹', '예선', '강전', '결승', '경기']):
                    logger.info(f"  [{tab['index']}] '{tab['text']}'")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(diagnose_all_tabs())
