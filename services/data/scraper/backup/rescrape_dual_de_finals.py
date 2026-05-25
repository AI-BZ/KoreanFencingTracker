#!/usr/bin/env python3
"""
Dual DE 결승 데이터 재스크래핑 스크립트

9개 이벤트의 Second DE 결승 bout에 winner_name=null 문제를 수정.
KFF 사이트에서 Second DE 브라켓을 재스크래핑하여 결승 결과를 업데이트.

Usage:
    cd services/data
    PYTHONPATH=".:../../packages" python scripts/rescrape_dual_de_finals.py
"""

import asyncio
import json
import logging
import os
import sys
from typing import Dict, List, Optional, Tuple

# Path setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "packages"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env"))

from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# 결승 winner=null인 9개 이벤트
AFFECTED_EVENTS = [
    # (comp_cd, sub_event_cd, comp_name, event_name)
    ("COMPM00403", "COMPS000000000001603", "2021 국가대표선수 선발대회", "남자 플러레(개)"),
    ("COMPM00403", "COMPS000000000001602", "2021 국가대표선수 선발대회", "여자 플러레(개)"),
    ("COMPM00415", "COMPS000000000001674", "2022 오픈선수권 겸 국대선발", "남자 플러레(개)"),
    ("COMPM00456", "COMPS000000000002088", "2022 국가대표선수 선발대회", "남자 플러레(개)"),
    ("COMPM00456", "COMPS000000000002089", "2022 국가대표선수 선발대회", "남자 에뻬(개)"),
    ("COMPM00499", "COMPS000000000002320", "2023 국가대표선수 선발대회", "남자 플러레(개)"),
    ("COMPM00608", "COMPS000000000003281", "2025 오픈선수권 겸 국대선발", "여자 플러레(개)"),
    ("COMPM00633", "COMPS000000000003400", "2025 국가대표선수 선발대회", "남자 플러레(개)"),
    ("COMPM00680", "COMPS000000000003844", "2026 오픈선수권 겸 국대선발", "여자 사브르(개)"),
]

KFF_BASE = "https://fencing.sports.or.kr"
COMP_LIST_URL = f"{KFF_BASE}/game/compList?code=game"


async def navigate_to_de_bracket(page: Page, comp_cd: str, sub_event_cd: str) -> bool:
    """KFF 사이트에서 특정 이벤트의 DE 브라켓 페이지로 이동"""

    # 1. 대회 목록으로 이동
    logger.info(f"  대회 목록 페이지 이동...")
    await page.goto(COMP_LIST_URL, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(2000)

    # 연도별 검색이 필요할 수 있음 - 대회 링크 찾기
    comp_link = page.locator(f"a[onclick*=\"'{comp_cd}'\"]").first
    try:
        await comp_link.wait_for(timeout=5000)
    except PlaywrightTimeout:
        # 대회가 현재 페이지에 없으면 연도별로 검색
        logger.info(f"  대회 {comp_cd}가 목록에 없음, 연도별 검색 시도...")
        # Try searching by year
        for year in range(2026, 2020, -1):
            try:
                year_tab = page.locator(f"a:has-text('{year}')").first
                await year_tab.click(timeout=3000)
                await page.wait_for_timeout(2000)
                comp_link = page.locator(f"a[onclick*=\"'{comp_cd}'\"]").first
                await comp_link.wait_for(timeout=3000)
                break
            except PlaywrightTimeout:
                continue
        else:
            logger.error(f"  대회 {comp_cd}를 찾을 수 없음!")
            return False

    # 2. 대회 클릭
    logger.info(f"  대회 클릭...")
    await comp_link.click(timeout=5000)
    await page.wait_for_timeout(2000)

    # 3. "경기결과" 탭 클릭
    logger.info(f"  경기결과 탭 클릭...")
    try:
        result_tab = page.locator("a[onclick*='funcLeftSub']:has-text('경기결과')").first
        await result_tab.click(timeout=5000)
        await page.wait_for_timeout(2000)
    except PlaywrightTimeout:
        logger.error(f"  경기결과 탭을 찾을 수 없음!")
        return False

    # 4. 종목 선택
    logger.info(f"  종목 선택: {sub_event_cd}")
    try:
        select = page.locator("select").first
        await select.select_option(value=sub_event_cd, timeout=5000)
        await page.wait_for_timeout(1000)

        search_btn = page.locator("a[href='#search']").first
        await search_btn.click(timeout=5000)
        await page.wait_for_timeout(2000)
    except PlaywrightTimeout:
        logger.error(f"  종목 선택 실패!")
        return False

    # 5. "대진표" 메인 탭 클릭
    logger.info(f"  대진표 탭 클릭...")
    try:
        bracket_tab = page.locator("a:has-text('대진표')").first
        await bracket_tab.click(timeout=5000, force=True)
        await page.wait_for_timeout(2000)
    except PlaywrightTimeout:
        logger.error(f"  대진표 탭을 찾을 수 없음!")
        return False

    # 6. 종목 재선택 (탭 전환 시 리셋될 수 있음)
    try:
        select = page.locator("select").first
        await select.select_option(value=sub_event_cd, timeout=3000)
        await page.wait_for_timeout(500)
        search_btn = page.locator("a[href='#search']").first
        await search_btn.click(timeout=3000)
        await page.wait_for_timeout(1500)
    except Exception:
        pass

    # 7. "엘리미나시옹디렉트" 서브탭 클릭
    logger.info(f"  엘리미나시옹디렉트 탭 클릭...")
    try:
        de_tab = page.locator("a:has-text('엘리미나시옹디렉트')").first
        await de_tab.click(timeout=5000, force=True)
        await page.wait_for_timeout(3000)
    except PlaywrightTimeout:
        logger.error(f"  엘리미나시옹디렉트 탭을 찾을 수 없음!")
        return False

    # 8. Second DE로 전환
    logger.info(f"  Second DE로 전환...")
    try:
        has_dual = await page.evaluate("""
            () => !!document.querySelector('select#schEtc01')
        """)
        if not has_dual:
            logger.error(f"  Dual DE 셀렉터(#schEtc01)가 없음!")
            return False

        await page.evaluate("""
            () => {
                const selector = document.querySelector('select#schEtc01');
                if (selector && selector.options.length >= 2) {
                    selector.selectedIndex = 1;
                    if (typeof fnChangeRuls === 'function') {
                        fnChangeRuls();
                    } else {
                        selector.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }
            }
        """)
        await page.wait_for_timeout(3000)
    except Exception as e:
        logger.error(f"  Second DE 전환 실패: {e}")
        return False

    return True


async def extract_final_bout(page: Page) -> Optional[Dict]:
    """현재 페이지의 DE 브라켓에서 결승 bout 데이터 추출"""

    result = await page.evaluate("""
        () => {
            // 결승 라운드 탭 찾기
            const tabs = document.querySelectorAll('#A_table td.row_table, .de_tit li a, .tab_area li a');
            let finalTabText = null;

            // 탭 기반으로 결승 찾기
            for (const tab of tabs) {
                const text = (tab.textContent || '').trim();
                if (text.includes('결승') || text.includes('우승') || text.includes('Final')) {
                    finalTabText = text;
                    break;
                }
            }

            // A_table에서 직접 결승 컬럼 찾기
            const allCols = document.querySelectorAll('#A_table td.row_table');
            let finalCol = null;
            let finalColIdx = -1;

            for (let i = 0; i < allCols.length; i++) {
                const text = (allCols[i].textContent || '').trim();
                // 마지막 컬럼이 결승/우승자
                if (text.includes('우승자') || text.includes('결승') || text.includes('Final')) {
                    finalCol = allCols[i];
                    finalColIdx = i;
                }
            }

            // 결승 데이터를 user_box에서 추출
            // 결승은 보통 마지막 두 user_box
            const allUserBoxes = document.querySelectorAll('#A_table tr.user_box');
            if (allUserBoxes.length < 2) {
                return { error: 'user_box_not_found', count: allUserBoxes.length };
            }

            // 마지막 두 user_box가 결승 선수 (브라켓 구조상)
            // 하지만 정확하려면 컬럼 위치로 필터링해야 함
            // 각 컬럼의 user_box 수: 32강=32, 16강=16, 8강=8, 준결승=4, 결승=2
            // 결승은 마지막 2개

            // 각 라운드별 user_box 수 계산
            const totalBoxes = allUserBoxes.length;

            // 결승 2개 = 마지막 2개
            const finalBox1 = allUserBoxes[totalBoxes - 2];
            const finalBox2 = allUserBoxes[totalBoxes - 1];

            function extractPlayer(box) {
                if (!box) return null;
                const nameEl = box.querySelector('.info .user_name, .user_name');
                const affEl = box.querySelector('.info .user_aff, .user_aff');
                const seedEl = box.querySelector('.num');

                const name = nameEl ? nameEl.textContent.trim() : '';
                const affText = affEl ? affEl.textContent.trim() : '';
                const seed = seedEl ? parseInt(seedEl.textContent.trim()) || 0 : 0;

                // 소속 vs 점수 구분
                // 점수 형태: "15 : 10", "V 15 : 10", "15:10"
                const scoreMatch = affText.match(/(V\\s*)?(\\d+)\\s*:\\s*(\\d+)/);
                let score = null;
                let team = '';

                if (scoreMatch) {
                    score = {
                        score1: parseInt(scoreMatch[2]),
                        score2: parseInt(scoreMatch[3]),
                        hasV: !!scoreMatch[1]
                    };
                } else {
                    team = affText;
                }

                return { name, team, seed, score, rawAff: affText };
            }

            const p1 = extractPlayer(finalBox1);
            const p2 = extractPlayer(finalBox2);

            if (!p1 || !p2 || !p1.name || !p2.name) {
                return { error: 'player_extraction_failed', p1, p2 };
            }

            // 승자 결정: 점수가 있으면 높은 쪽이 승자
            // 또는 V 마크가 있는 쪽이 승자
            // 또는 CSS 클래스로 구분 (user_box에 win 클래스)
            let winner = null;
            let p1Score = 0, p2Score = 0;

            // 방법 1: 점수 비교
            if (p1.score && p2.score) {
                p1Score = p1.score.score1;
                p2Score = p2.score.score1;
                if (p1.score.hasV) winner = p1.name;
                else if (p2.score.hasV) winner = p2.name;
                else if (p1Score > p2Score) winner = p1.name;
                else if (p2Score > p1Score) winner = p2.name;
            }

            // 방법 2: win 클래스 확인
            if (!winner) {
                if (finalBox1.classList.contains('win') || finalBox1.querySelector('.win'))
                    winner = p1.name;
                else if (finalBox2.classList.contains('win') || finalBox2.querySelector('.win'))
                    winner = p2.name;
            }

            // 방법 3: 배경색 or 볼드 확인
            if (!winner) {
                const style1 = window.getComputedStyle(finalBox1);
                const style2 = window.getComputedStyle(finalBox2);
                const nameEl1 = finalBox1.querySelector('.user_name');
                const nameEl2 = finalBox2.querySelector('.user_name');
                if (nameEl1 && nameEl2) {
                    const w1 = parseInt(window.getComputedStyle(nameEl1).fontWeight) || 400;
                    const w2 = parseInt(window.getComputedStyle(nameEl2).fontWeight) || 400;
                    if (w1 > w2) winner = p1.name;
                    else if (w2 > w1) winner = p2.name;
                }
            }

            return {
                player1: { name: p1.name, team: p1.team || '', seed: p1.seed, score: p1Score },
                player2: { name: p2.name, team: p2.team || '', seed: p2.seed, score: p2Score },
                winner: winner,
                debug: {
                    totalUserBoxes: totalBoxes,
                    p1_raw: p1,
                    p2_raw: p2,
                    finalTabText: finalTabText,
                    colCount: allCols.length
                }
            };
        }
    """)

    if not result or result.get("error"):
        logger.error(f"  결승 데이터 추출 실패: {result}")
        return None

    return result


async def update_db_final_bout(sub_event_cd: str, final_data: Dict) -> bool:
    """DB의 결승 bout 데이터 업데이트"""
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        logger.error("SUPABASE_URL/KEY not set")
        return False

    sb = create_client(url, key)

    # 현재 이벤트 데이터 가져오기
    result = sb.table("events").select("raw_data").eq("sub_event_cd", sub_event_cd).execute()
    if not result.data:
        logger.error(f"  이벤트 {sub_event_cd}를 DB에서 찾을 수 없음")
        return False

    raw_data = result.data[0]["raw_data"]
    second_de = raw_data.get("de_bracket", {}).get("second_de", {})
    bouts = second_de.get("bouts", [])

    # 결승 bout 찾아서 업데이트
    updated = False
    for i, bout in enumerate(bouts):
        if bout.get("round_name") == "결승":
            winner_name = final_data.get("winner", "")
            p1 = final_data.get("player1", {})
            p2 = final_data.get("player2", {})

            bout["winner_name"] = winner_name
            bout["player1_score"] = p1.get("score", 0)
            bout["player2_score"] = p2.get("score", 0)

            # player name도 업데이트 (혹시 비어있을 수 있으므로)
            if p1.get("name"):
                bout["player1_name"] = p1["name"]
            if p2.get("name"):
                bout["player2_name"] = p2["name"]
            if p1.get("team"):
                bout["player1_team"] = p1["team"]
            if p2.get("team"):
                bout["player2_team"] = p2["team"]

            # winner_seed 결정
            if winner_name == bout.get("player1_name"):
                bout["winner_seed"] = bout.get("player1_seed")
            elif winner_name == bout.get("player2_name"):
                bout["winner_seed"] = bout.get("player2_seed")

            updated = True
            logger.info(f"  결승 bout 업데이트: {bout['player1_name']} vs {bout['player2_name']} → 승: {winner_name} ({p1.get('score', '?')}:{p2.get('score', '?')})")
            break

    if not updated:
        # 결승 bout이 없는 경우 (COMPS000000000003281 등) - 새로 추가
        if final_data.get("winner"):
            p1 = final_data.get("player1", {})
            p2 = final_data.get("player2", {})
            new_bout = {
                "bout_id": f"결승_{len(bouts) + 1:02d}",
                "round_name": "결승",
                "match_number": len(bouts) + 1,
                "is_bye": False,
                "player1_name": p1.get("name", ""),
                "player1_team": p1.get("team", ""),
                "player1_seed": p1.get("seed", 0),
                "player1_score": p1.get("score", 0),
                "player2_name": p2.get("name", ""),
                "player2_team": p2.get("team", ""),
                "player2_seed": p2.get("seed", 0),
                "player2_score": p2.get("score", 0),
                "winner_name": final_data["winner"],
                "winner_seed": p1.get("seed") if final_data["winner"] == p1.get("name") else p2.get("seed"),
            }
            bouts.append(new_bout)
            updated = True
            logger.info(f"  결승 bout 신규 추가: {p1.get('name')} vs {p2.get('name')} → 승: {final_data['winner']}")

    if updated:
        second_de["bouts"] = bouts
        raw_data["de_bracket"]["second_de"] = second_de

        sb.table("events").update({"raw_data": raw_data}).eq("sub_event_cd", sub_event_cd).execute()
        logger.info(f"  ✅ DB 업데이트 완료")
        return True

    logger.error(f"  결승 bout을 찾을 수 없음")
    return False


async def main():
    logger.info("=" * 60)
    logger.info("Dual DE 결승 재스크래핑 시작")
    logger.info(f"대상: {len(AFFECTED_EVENTS)}개 이벤트")
    logger.info("=" * 60)

    results = {"success": [], "failed": [], "skipped": []}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="ko-KR",
        )
        page = await context.new_page()

        prev_comp_cd = None

        for comp_cd, sub_event_cd, comp_name, event_name in AFFECTED_EVENTS:
            logger.info(f"\n{'─' * 50}")
            logger.info(f"처리 중: {comp_name} - {event_name}")
            logger.info(f"  comp_cd={comp_cd}, sub_event_cd={sub_event_cd}")

            try:
                # DE 브라켓 페이지로 이동
                success = await navigate_to_de_bracket(page, comp_cd, sub_event_cd)
                if not success:
                    logger.error(f"  ❌ 네비게이션 실패")
                    results["failed"].append((sub_event_cd, event_name, "navigation_failed"))
                    continue

                # 결승 데이터 추출
                final_data = await extract_final_bout(page)
                if not final_data:
                    logger.error(f"  ❌ 결승 데이터 추출 실패")
                    results["failed"].append((sub_event_cd, event_name, "extraction_failed"))
                    continue

                winner = final_data.get("winner")
                if not winner:
                    logger.warning(f"  ⚠️ 결승 승자를 결정할 수 없음 (KFF에도 데이터 없을 수 있음)")
                    logger.info(f"  디버그: {json.dumps(final_data.get('debug', {}), ensure_ascii=False)}")
                    results["failed"].append((sub_event_cd, event_name, "no_winner"))
                    continue

                p1 = final_data.get("player1", {})
                p2 = final_data.get("player2", {})
                logger.info(f"  🏆 결승: {p1.get('name')} vs {p2.get('name')} → 승: {winner} ({p1.get('score', '?')}:{p2.get('score', '?')})")

                # DB 업데이트
                db_success = await update_db_final_bout(sub_event_cd, final_data)
                if db_success:
                    results["success"].append((sub_event_cd, event_name, winner))
                else:
                    results["failed"].append((sub_event_cd, event_name, "db_update_failed"))

                prev_comp_cd = comp_cd

            except Exception as e:
                logger.error(f"  ❌ 예외 발생: {e}", exc_info=True)
                results["failed"].append((sub_event_cd, event_name, str(e)))

            # Rate limiting
            await page.wait_for_timeout(2000)

        await browser.close()

    # 결과 요약
    logger.info(f"\n{'=' * 60}")
    logger.info("재스크래핑 완료 요약")
    logger.info(f"{'=' * 60}")
    logger.info(f"  ✅ 성공: {len(results['success'])}건")
    for sub, name, winner in results["success"]:
        logger.info(f"     - {name}: 1위 {winner}")
    logger.info(f"  ❌ 실패: {len(results['failed'])}건")
    for sub, name, reason in results["failed"]:
        logger.info(f"     - {name}: {reason}")
    logger.info(f"  ⏭️ 건너뜀: {len(results['skipped'])}건")


if __name__ == "__main__":
    asyncio.run(main())
