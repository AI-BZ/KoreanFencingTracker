"""
브라켓 DOM 구조 진단 - 라운드 감지 방법 파악
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


async def diagnose_bracket_structure():
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

        # 대진표 탭 클릭
        bracket_main_tab = page.locator("a:has-text('대진표')").first
        await bracket_main_tab.click(timeout=5000, force=True)
        await page.wait_for_timeout(1500)

        # 종목 다시 선택
        select = page.locator("select").first
        await select.select_option(value=event_cd)
        search_btn = page.locator("a[href='#search']").first
        await search_btn.click()
        await page.wait_for_timeout(1000)

        # 엘리미나시옹디렉트 탭 클릭
        de_bracket_tab = page.locator("a:has-text('엘리미나시옹디렉트')").first
        await de_bracket_tab.click(timeout=5000, force=True)
        await page.wait_for_timeout(1500)

        # 브라켓 구조 분석
        structure = await page.evaluate("""
            () => {
                const result = {
                    roundHeaders: [],
                    tables: [],
                    columnStructure: []
                };

                // 1. "N 엘리미나시옹디렉트" 라운드 헤더 찾기
                const allCells = document.querySelectorAll('table td');
                allCells.forEach((cell, idx) => {
                    const text = cell.textContent.trim();
                    if (text.match(/^\\d+\\s*엘리미나시옹디렉트$/)) {
                        const rect = cell.getBoundingClientRect();
                        result.roundHeaders.push({
                            text: text,
                            index: idx,
                            x: rect.x,
                            y: rect.y,
                            width: rect.width
                        });
                    }
                    // 결승, 준결승 헤더도 찾기
                    if (text.match(/^(결승|준결승|3-4위전)$/)) {
                        const rect = cell.getBoundingClientRect();
                        result.roundHeaders.push({
                            text: text,
                            index: idx,
                            x: rect.x,
                            y: rect.y,
                            width: rect.width
                        });
                    }
                });

                // 2. 중첩 테이블 분석 (각 열의 경기 수로 라운드 추론)
                const nestedTables = document.querySelectorAll('table table');
                nestedTables.forEach((table, idx) => {
                    const rect = table.getBoundingClientRect();
                    const rows = table.querySelectorAll('tr');
                    const players = [];

                    rows.forEach(row => {
                        const cell = row.querySelector('td');
                        if (!cell) return;

                        const divs = cell.querySelectorAll(':scope > div');
                        if (divs.length >= 2) {
                            const seed = parseInt(divs[0].textContent.trim());
                            const name = divs[1].querySelector('p')?.textContent.trim() || '';
                            if (seed && name) {
                                players.push({seed, name});
                            }
                        }
                    });

                    if (players.length > 0) {
                        result.tables.push({
                            tableIndex: idx,
                            x: rect.x,
                            y: rect.y,
                            playerCount: players.length,
                            matchCount: Math.floor(players.length / 2),
                            samplePlayers: players.slice(0, 4)
                        });
                    }
                });

                // 3. X 좌표로 그룹화하여 열(라운드) 구조 파악
                const xGroups = {};
                result.tables.forEach(t => {
                    const xKey = Math.round(t.x / 50) * 50;  // 50px 단위로 그룹화
                    if (!xGroups[xKey]) {
                        xGroups[xKey] = [];
                    }
                    xGroups[xKey].push(t);
                });

                Object.keys(xGroups).sort((a, b) => parseInt(a) - parseInt(b)).forEach((x, colIdx) => {
                    const tables = xGroups[x];
                    const totalMatches = tables.reduce((sum, t) => sum + t.matchCount, 0);
                    result.columnStructure.push({
                        columnIndex: colIdx,
                        x: parseInt(x),
                        tableCount: tables.length,
                        totalMatches: totalMatches,
                        inferredRound: totalMatches >= 32 ? '64강' :
                                      totalMatches >= 16 ? '32강' :
                                      totalMatches >= 8 ? '16강' :
                                      totalMatches >= 4 ? '8강' :
                                      totalMatches >= 2 ? '준결승' :
                                      totalMatches >= 1 ? '결승' : '?'
                    });
                });

                return result;
            }
        """)

        logger.info("\n=== 라운드 헤더 ===")
        for h in structure['roundHeaders']:
            logger.info(f"  '{h['text']}' at x={h['x']:.0f}")

        logger.info("\n=== 열 구조 (X 좌표별) ===")
        for col in structure['columnStructure']:
            logger.info(f"  열 {col['columnIndex']}: x={col['x']}, {col['totalMatches']} 경기 → {col['inferredRound']}")

        logger.info("\n=== 테이블 상세 ===")
        for t in structure['tables'][:10]:
            logger.info(f"  테이블 {t['tableIndex']}: x={t['x']:.0f}, {t['matchCount']}경기, 선수: {t['samplePlayers']}")

        # 결과 저장
        with open("data/bracket_structure.json", "w", encoding="utf-8") as f:
            json.dump(structure, f, ensure_ascii=False, indent=2)
        logger.info("\n결과 저장: data/bracket_structure.json")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(diagnose_bracket_structure())
