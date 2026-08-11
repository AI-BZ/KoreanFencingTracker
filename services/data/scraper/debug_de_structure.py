#!/usr/bin/env python3
"""DE 브래킷 HTML 구조 디버깅"""

import asyncio
from playwright.async_api import async_playwright


async def debug_de_structure():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        page.set_default_timeout(15000)

        print("1. Navigating to competition list...")
        await page.goto('https://fencing.sports.or.kr/game/compList?code=game', wait_until='domcontentloaded')
        await page.wait_for_timeout(2000)

        print("2. Clicking on 2025 FILA배...")
        await page.click('a[onclick*="COMPM00659"]', timeout=5000)
        await page.wait_for_timeout(2000)

        print("3. Clicking 경기결과 tab...")
        result_tab = page.locator("a[onclick*='funcLeftSub']:has-text('경기결과')").first
        await result_tab.click(timeout=3000)
        await page.wait_for_timeout(1500)

        print("4. Selecting event...")
        select = page.locator("select").first
        await select.select_option(value="COMPS000000000003661")
        await page.wait_for_timeout(500)

        search_btn = page.locator("a[href='#search']").first
        await search_btn.click()
        await page.wait_for_timeout(1500)

        print("5. Clicking 대진표 tab...")
        bracket_main_tab = page.locator("a:has-text('대진표')").first
        await bracket_main_tab.click(timeout=5000, force=True)
        await page.wait_for_timeout(1500)

        select = page.locator("select").first
        await select.select_option(value="COMPS000000000003661")
        await page.wait_for_timeout(500)
        search_btn = page.locator("a[href='#search']").first
        await search_btn.click()
        await page.wait_for_timeout(1500)

        print("6. Clicking 엘리미나시옹디렉트 tab...")
        de_tab = page.locator("a:has-text('엘리미나시옹디렉트')").first
        await de_tab.click(timeout=5000, force=True)
        await page.wait_for_timeout(2000)

        print("7. Switching to 8강전 tab...")
        await page.evaluate("fnGetMatch(3)")
        await page.wait_for_timeout(2000)

        # Get HTML for row02 (준결승)
        print("\n8. Extracting row02 (준결승) player data with scores...")

        js_code = """
        () => {
            const aTable = document.querySelector('#A_table');
            if (!aTable) return { error: 'No A_table' };

            const result = { rows: {} };

            for (let rowIdx = 1; rowIdx <= 4; rowIdx++) {
                const col = aTable.querySelector('td.row_table.row0' + rowIdx);
                if (!col) continue;

                const userBoxes = col.querySelectorAll('tr.user_box');
                const players = [];

                userBoxes.forEach((box, idx) => {
                    const userName = box.querySelector('.user_name');
                    const userAff = box.querySelector('.user_aff');
                    const num = box.querySelector('.num');

                    // Try to find score in various locations
                    const scoreSpan = box.querySelector('.score span');
                    const infoDiv = box.querySelector('.info');
                    const tdElement = box.querySelector('td');

                    players.push({
                        index: idx,
                        seed: num ? num.textContent.trim() : null,
                        name: userName ? userName.textContent.trim() : null,
                        team: userAff ? userAff.textContent.trim() : null,
                        score_span: scoreSpan ? scoreSpan.textContent.trim() : null,
                        info_text: infoDiv ? infoDiv.textContent.trim() : null,
                        td_text: tdElement ? tdElement.textContent.trim() : null
                    });
                });

                result.rows['row0' + rowIdx] = players;
            }

            return result;
        }
        """

        data = await page.evaluate(js_code)

        import json
        print(json.dumps(data, indent=2, ensure_ascii=False))

        await browser.close()
        print("\nDone!")


if __name__ == "__main__":
    asyncio.run(debug_de_structure())
