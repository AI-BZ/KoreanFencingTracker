#!/usr/bin/env python3
"""tournament_table 구조 멀티탭 디버깅"""

import asyncio
from playwright.async_api import async_playwright


async def debug_multi_tab():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        page.set_default_timeout(15000)

        print("1. Navigating to competition...")
        await page.goto('https://fencing.sports.or.kr/game/compList?code=game', wait_until='domcontentloaded')
        await page.wait_for_timeout(2000)

        await page.click('a[onclick*="COMPM00659"]', timeout=5000)
        await page.wait_for_timeout(2000)

        result_tab = page.locator("a[onclick*='funcLeftSub']:has-text('경기결과')").first
        await result_tab.click(timeout=3000)
        await page.wait_for_timeout(1500)

        select = page.locator("select").first
        await select.select_option(value="COMPS000000000003661")
        await page.wait_for_timeout(500)

        search_btn = page.locator("a[href='#search']").first
        await search_btn.click()
        await page.wait_for_timeout(1500)

        bracket_main_tab = page.locator("a:has-text('대진표')").first
        await bracket_main_tab.click(timeout=5000, force=True)
        await page.wait_for_timeout(1500)

        select = page.locator("select").first
        await select.select_option(value="COMPS000000000003661")
        await page.wait_for_timeout(500)
        search_btn = page.locator("a[href='#search']").first
        await search_btn.click()
        await page.wait_for_timeout(1500)

        de_tab = page.locator("a:has-text('엘리미나시옹디렉트')").first
        await de_tab.click(timeout=5000, force=True)
        await page.wait_for_timeout(2000)

        # Check what's on 32강전 tab
        print("\n2. Checking 32강전 tab (default)...")
        data_32 = await page.evaluate("""
            () => {
                const boxes = document.querySelectorAll('.user_box');
                const xpositions = new Set();
                boxes.forEach(box => {
                    xpositions.add(box.getAttribute('xposition'));
                });
                return {
                    box_count: boxes.length,
                    xpositions: Array.from(xpositions).sort((a, b) => parseInt(b) - parseInt(a))
                };
            }
        """)
        print(f"   32강전 tab: {data_32}")

        # Switch to 8강전 tab and check
        print("\n3. Switching to 8강전 tab (fnGetMatch(3))...")
        await page.evaluate("fnGetMatch(3)")
        await page.wait_for_timeout(2000)

        data_8 = await page.evaluate("""
            () => {
                const boxes = document.querySelectorAll('.user_box');
                const xpositions = new Set();
                const matchesByXpos = {};

                boxes.forEach(box => {
                    const xpos = box.getAttribute('xposition');
                    xpositions.add(xpos);

                    if (!matchesByXpos[xpos]) {
                        matchesByXpos[xpos] = [];
                    }

                    const name = box.querySelector('.user_name span')?.textContent?.trim() || '';
                    const score = box.getAttribute('score') || '';
                    const wingbn = box.getAttribute('wingbn');
                    const sym = box.getAttribute('compmatsym');

                    matchesByXpos[xpos].push({
                        name,
                        score,
                        isWinner: wingbn === '1',
                        sym
                    });
                });

                return {
                    box_count: boxes.length,
                    xpositions: Array.from(xpositions).sort((a, b) => parseInt(b) - parseInt(a)),
                    matchesByXpos
                };
            }
        """)
        print(f"   8강전 tab box_count: {data_8['box_count']}")
        print(f"   8강전 tab xpositions: {data_8['xpositions']}")

        # Show matches for each xposition
        import json
        for xpos in sorted(data_8['matchesByXpos'].keys(), key=lambda x: int(x), reverse=True):
            matches = data_8['matchesByXpos'][xpos]
            print(f"\n   xposition {xpos}:")
            for m in matches:
                winner_mark = "🏆" if m['isWinner'] else "  "
                print(f"     {winner_mark} {m['name']} (score: {m['score']}) [sym: {m['sym']}]")

        await browser.close()
        print("\nDone!")


if __name__ == "__main__":
    asyncio.run(debug_multi_tab())
