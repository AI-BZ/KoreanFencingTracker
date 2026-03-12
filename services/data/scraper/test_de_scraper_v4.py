#!/usr/bin/env python3
"""DEScraper v4 테스트 - 8강전 탭 파싱"""

import asyncio
from playwright.async_api import async_playwright
from de_scraper_v4 import DEScraper


async def test_de_scraper():
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

        print("2. Running DEScraper...")
        scraper = DEScraper(page)
        bracket = await scraper.parse_de_bracket()

        print(f"\n3. Results:")
        print(f"   Starting round: {bracket.starting_round}")
        print(f"   Bracket size: {bracket.bracket_size}")
        print(f"   Participant count: {bracket.participant_count}")
        print(f"   Total matches: {len(bracket.matches)}")
        print(f"   Champion: {bracket.champion}")

        # Print matches by round
        matches_by_round = {}
        for m in bracket.matches:
            if m.round_name not in matches_by_round:
                matches_by_round[m.round_name] = []
            matches_by_round[m.round_name].append(m)

        print("\n4. Matches by round:")
        for round_name in ['32강', '16강', '8강', '준결승', '결승']:
            if round_name in matches_by_round:
                print(f"\n   {round_name}:")
                for m in matches_by_round[round_name]:
                    p1_name = m.player1.name if m.player1 else "BYE"
                    p2_name = m.player2.name if m.player2 else "BYE"
                    score = f"{m.player1_score}:{m.player2_score}" if m.player1_score is not None else "N/A"
                    winner_name = m.winner.name if m.winner else "N/A"
                    print(f"      {m.match_number}. {p1_name} vs {p2_name} - {score} (승자: {winner_name})")

        await browser.close()
        print("\nDone!")


if __name__ == "__main__":
    asyncio.run(test_de_scraper())
