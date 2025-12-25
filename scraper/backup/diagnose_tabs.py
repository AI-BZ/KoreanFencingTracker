"""
페이지에서 라운드 탭 구조 진단
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.async_api import async_playwright
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_URL = "https://fencing.sports.or.kr"


async def diagnose_tabs():
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
            await select.select_option(value=event_cd)
            await page.wait_for_timeout(500)
            search_btn = page.locator("a[href='#search']").first
            await search_btn.click()
            await page.wait_for_timeout(1000)
        except:
            pass

        # 엘리미나시옹디렉트 탭 클릭
        de_bracket_tab = page.locator("a:has-text('엘리미나시옹디렉트')").first
        await de_bracket_tab.click(timeout=5000, force=True)
        await page.wait_for_timeout(1500)

        # 모든 링크 텍스트 수집
        all_links = await page.evaluate("""
            () => {
                const links = [];
                document.querySelectorAll('a').forEach((link, idx) => {
                    const text = link.textContent.trim();
                    const href = link.getAttribute('href');
                    const onclick = link.getAttribute('onclick');
                    if (text && text.length < 50) {
                        links.push({
                            index: idx,
                            text: text,
                            href: href,
                            onclick: onclick ? onclick.substring(0, 100) : null
                        });
                    }
                });
                return links;
            }
        """)

        logger.info(f"총 {len(all_links)}개의 링크 발견")
        logger.info("\n=== 라운드 관련 링크 ===")

        for link in all_links:
            text = link['text']
            # 강전, 준결승, 결승, 4강 등 라운드 관련 키워드
            if any(kw in text for kw in ['강전', '결승', '준결승', '4강', 'Final', 'Semi']):
                logger.info(f"  [{link['index']}] '{text}' - onclick: {link.get('onclick', 'N/A')}")

        logger.info("\n=== ul li a 링크 (탭 후보) ===")
        ul_links = await page.evaluate("""
            () => {
                const links = [];
                document.querySelectorAll('ul li a').forEach((link, idx) => {
                    const text = link.textContent.trim();
                    links.push({index: idx, text: text});
                });
                return links;
            }
        """)

        for link in ul_links:
            text = link['text']
            if any(kw in text for kw in ['강전', '결승', '준결승', '4강', '엘리미나시옹']):
                logger.info(f"  [{link['index']}] '{text}'")

        # 스크린샷 저장
        await page.screenshot(path="data/diagnose_de_tabs.png", full_page=True)
        logger.info("스크린샷 저장: data/diagnose_de_tabs.png")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(diagnose_tabs())
