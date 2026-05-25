"""
Dual DE 결승 데이터 수정 스크립트 v3

전략: KFF의 Second DE 탭에서 최종 순위(final_rankings) 수집
→ rank 1 = 결승 승자, rank 2 = 결승 패자로 bout 데이터 업데이트
(KFF DE 브라켓은 결승 점수를 0-0으로 표시하므로 순위에서 추출)
"""

import asyncio
import json
import sys
import os
import httpx
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://tjfjuasvjzjawyckengv.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
KFF_BASE = "https://fencing.sports.or.kr"

AFFECTED_EVENTS = [
    {"comp_cd": "COMPM00680", "sub_event_cd": "COMPS000000000003844", "desc": "2026 오픈선수권 여자 사브르"},
    {"comp_cd": "COMPM00633", "sub_event_cd": "COMPS000000000003400", "desc": "2025 국대선발 남자 플뢰레"},
    {"comp_cd": "COMPM00608", "sub_event_cd": "COMPS000000000003281", "desc": "2025 오픈선수권 여자 플뢰레"},
    {"comp_cd": "COMPM00499", "sub_event_cd": "COMPS000000000002320", "desc": "2023 국대선발 남자 플뢰레"},
    {"comp_cd": "COMPM00456", "sub_event_cd": "COMPS000000000002088", "desc": "2022 국대선발 남자 플뢰레"},
    {"comp_cd": "COMPM00456", "sub_event_cd": "COMPS000000000002089", "desc": "2022 국대선발 남자 에페"},
    {"comp_cd": "COMPM00415", "sub_event_cd": "COMPS000000000001674", "desc": "2022 오픈선수권 남자 플뢰레"},
    {"comp_cd": "COMPM00403", "sub_event_cd": "COMPS000000000001603", "desc": "2021 국대선발 남자 플뢰레"},
    {"comp_cd": "COMPM00403", "sub_event_cd": "COMPS000000000001602", "desc": "2021 국대선발 여자 플뢰레"},
]


async def scrape_second_de_rankings(page, comp_cd: str, sub_event_cd: str) -> Optional[List[Dict]]:
    """KFF 사이트에서 Second DE 최종 순위 추출

    Flow (full_scraper.py와 동일):
    1. compList → funcView → competition detail
    2. 경기결과 탭 → 종목 선택 → 검색
    3. 엘리미나시옹디렉트 sub-tab
    4. Second DE 드롭다운 선택
    5. 순위 테이블 파싱
    """
    # 1. compList 이동 + funcView 호출
    await page.goto(f"{KFF_BASE}/game/compList?code=game", wait_until="networkidle", timeout=20000)
    await page.wait_for_timeout(2000)

    await page.evaluate(f"funcView('{comp_cd}', '2')")
    await page.wait_for_timeout(3000)

    # 2. 경기결과 탭 클릭
    result_tab = page.locator("a[onclick*='funcLeftSub']:has-text('경기결과')").first
    if await result_tab.count() > 0:
        await result_tab.click(timeout=5000)
        await page.wait_for_timeout(1500)
    else:
        print(f"    경기결과 탭 없음")
        return None

    # 3. 종목 선택 + 검색
    selected = await page.evaluate(f"""
        () => {{
            const selects = document.querySelectorAll('select');
            for (const sel of selects) {{
                for (const opt of sel.options) {{
                    if (opt.value === '{sub_event_cd}') {{
                        sel.value = opt.value;
                        sel.dispatchEvent(new Event('change'));
                        return opt.textContent.trim();
                    }}
                }}
            }}
            return null;
        }}
    """)
    if not selected:
        print(f"    종목 선택 실패")
        return None
    print(f"    종목: {selected}")
    await page.wait_for_timeout(1000)

    # 검색 버튼 클릭 (full_scraper.py와 동일 - a[href='#search'])
    try:
        search_btn = page.locator("a[href='#search']").first
        if await search_btn.count() > 0:
            await search_btn.click()
            await page.wait_for_timeout(1500)
    except:
        pass

    # 4. 엘리미나시옹디렉트 sub-tab 클릭
    try:
        # 팝업 닫기
        await page.evaluate("""
            const popups = document.querySelectorAll('.layer_pop, #layer_final_ranking, [id*="layer"]');
            popups.forEach(p => p.style.display = 'none');
        """)
        await page.wait_for_timeout(300)

        de_tab = page.locator("a:has-text('엘리미나시옹디렉트')").first
        await de_tab.click(timeout=5000, force=True)
        await page.wait_for_timeout(2000)
        print(f"    엘리미나시옹디렉트 탭 클릭")
    except Exception as e:
        print(f"    엘리미나시옹디렉트 탭 실패: {e}")
        return None

    # 5. Dual DE selector 확인 및 Second DE 선택
    has_dual = await page.evaluate("() => !!document.querySelector('select#schEtc01')")
    if not has_dual:
        # 잠시 더 대기 후 재확인
        await page.wait_for_timeout(2000)
        has_dual = await page.evaluate("() => !!document.querySelector('select#schEtc01')")

    if has_dual:
        print(f"    Dual DE 감지 → Second DE 전환")
        await page.evaluate("""
            () => {
                const sel = document.querySelector('select#schEtc01');
                if (sel && sel.options.length >= 2) {
                    sel.selectedIndex = 1;
                    if (typeof fnChangeRuls === 'function') {
                        fnChangeRuls();
                    } else {
                        sel.dispatchEvent(new Event('change', {bubbles: true}));
                    }
                }
            }
        """)
        await page.wait_for_timeout(3000)
    else:
        print(f"    ⚠️ Dual DE selector 없음 (단일 DE일 수 있음)")

    # 6. 순위 테이블 파싱 (full_scraper._parse_final_rankings_v2 방식)
    rankings = await page.evaluate("""
        () => {
            const results = [];

            // 방법 1: 테이블에서 순위/이름/소속 헤더 찾기
            const tables = document.querySelectorAll('table');
            for (const table of tables) {
                const headers = Array.from(table.querySelectorAll('th, thead td'))
                    .map(th => th.textContent.trim());
                const headerTexts = headers.join(' ');

                if (headerTexts.includes('순위') && headerTexts.includes('이름') && headerTexts.includes('소속')) {
                    const rows = table.querySelectorAll('tbody tr');
                    for (const row of rows) {
                        const cells = Array.from(row.querySelectorAll('td')).map(td => td.textContent.trim());
                        if (cells.length >= 3) {
                            const rank = parseInt(cells[0]);
                            if (!isNaN(rank) && rank > 0) {
                                results.push({rank, name: cells[1], team: cells[2]});
                            }
                        }
                    }
                    if (results.length > 0) break;
                }
            }

            // 방법 2: 순위 패턴 ("1위", "2위") 찾기
            if (results.length === 0) {
                for (const table of tables) {
                    const rows = table.querySelectorAll('tr');
                    for (const row of rows) {
                        const cells = Array.from(row.querySelectorAll('td')).map(td => td.textContent.trim());
                        if (cells.length >= 2) {
                            const match = cells[0].match(/^(\\d+)위?$/);
                            if (match) {
                                results.push({
                                    rank: parseInt(match[1]),
                                    name: cells[1],
                                    team: cells.length > 2 ? cells[2] : ''
                                });
                            }
                        }
                    }
                    if (results.length >= 4) break;
                }
            }

            // 방법 3: 순위가 숫자로 시작하는 행 찾기 (더 넓은 검색)
            if (results.length === 0) {
                for (const table of tables) {
                    const rows = table.querySelectorAll('tr');
                    for (const row of rows) {
                        const cells = Array.from(row.querySelectorAll('td'));
                        if (cells.length >= 3) {
                            const firstText = cells[0].textContent.trim();
                            const rank = parseInt(firstText);
                            if (!isNaN(rank) && rank >= 1 && rank <= 100) {
                                const name = cells[1].textContent.trim();
                                const team = cells[2].textContent.trim();
                                // 이름이 합리적인 길이 (한국 이름 2-4자)
                                if (name.length >= 2 && name.length <= 10) {
                                    results.push({rank, name, team});
                                }
                            }
                        }
                    }
                    if (results.length >= 4) break;
                }
            }

            return results.slice(0, 10);
        }
    """)

    if rankings:
        print(f"    순위 데이터: {len(rankings)}명")
        for r in rankings[:5]:
            print(f"      {r['rank']}위: {r['name']} ({r['team']})")
        return rankings
    else:
        print(f"    순위 데이터 없음")

        # 디버그: 페이지에 있는 테이블들 확인
        debug_info = await page.evaluate("""
            () => {
                const tables = document.querySelectorAll('table');
                return Array.from(tables).map((t, i) => ({
                    index: i,
                    classes: t.className,
                    headers: Array.from(t.querySelectorAll('th')).map(th => th.textContent.trim()).join(', '),
                    rowCount: t.querySelectorAll('tr').length,
                    preview: t.innerHTML.substring(0, 200)
                }));
            }
        """)
        print(f"    페이지 테이블 수: {len(debug_info)}")
        for t in debug_info[:3]:
            print(f"      table[{t['index']}]: class='{t['classes']}', headers='{t['headers']}', rows={t['rowCount']}")

        return None


def update_db_with_rankings(sub_event_cd: str, rankings: List[Dict]) -> bool:
    """순위 데이터로 결승 bout 및 champion 업데이트"""
    # rank 1 = 결승 승자, rank 2 = 결승 패자
    rank1 = next((r for r in rankings if r['rank'] == 1), None)
    rank2 = next((r for r in rankings if r['rank'] == 2), None)

    if not rank1:
        print(f"    ❌ rank 1 없음 (순위 시작: {rankings[0]['rank'] if rankings else 'N/A'})")
        return False

    champion_name = rank1['name']
    champion_team = rank1.get('team', '')
    print(f"    🏆 Champion: {champion_name} ({champion_team})")

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }

    # Get current event data
    url = f"{SUPABASE_URL}/rest/v1/events?sub_event_cd=eq.{sub_event_cd}&select=id,raw_data"
    resp = httpx.get(url, headers=headers)
    events = resp.json()
    if not events:
        print(f"    ❌ Event not found in DB")
        return False

    raw_data = events[0]["raw_data"]
    second_de = raw_data.get("de_bracket", {}).get("second_de", {})
    if not second_de:
        print(f"    ❌ No second_de data")
        return False

    # Find the 결승 bout and check if it matches the rankings
    bouts = second_de.get("bouts", [])
    final_bout = None
    for bout in bouts:
        if bout.get("round_name") == "결승":
            final_bout = bout
            break

    if final_bout:
        p1 = final_bout.get("player1_name")
        p2 = final_bout.get("player2_name")
        print(f"    결승: {p1} vs {p2}")

        # Determine winner from rankings
        if champion_name == p1:
            winner_seed = final_bout.get("player1_seed")
            loser_name = p2
        elif champion_name == p2:
            winner_seed = final_bout.get("player2_seed")
            loser_name = p1
        else:
            print(f"    ⚠️ Champion '{champion_name}' not in 결승 bout ({p1} vs {p2})")
            # Still set it based on ranking
            winner_seed = None
            loser_name = None

        # Update the bout (we don't have exact scores, but we know the winner)
        # Use 15-0 as placeholder scores (DE final is 15-touch)
        final_bout["winner_name"] = champion_name
        final_bout["winner_seed"] = winner_seed

        # Also update bouts_by_round
        for fb in second_de.get("bouts_by_round", {}).get("결승", []):
            fb["winner_name"] = champion_name
            fb["winner_seed"] = winner_seed
    else:
        print(f"    ⚠️ 결승 bout 없음 (순위에서 champion만 설정)")

    # Update champion
    champion_obj = {
        "name": champion_name,
        "team": champion_team,
        "seed": final_bout.get("player1_seed") if final_bout and champion_name == final_bout.get("player1_name") else (final_bout.get("player2_seed") if final_bout else None),
        "is_bye": False
    }
    second_de["champion"] = champion_obj
    raw_data["de_bracket"]["champion"] = champion_obj

    # Also update the overall final_rankings if they're from First DE
    # Add rank 1 and 2 from Second DE at the top
    current_final = raw_data.get("final_rankings", [])
    if current_final:
        first_rank = current_final[0].get("rank") if current_final else None
        # Check if current final_rankings already has this as rank 1
        first_name = current_final[0].get("name") if current_final else None
        if first_name != champion_name:
            print(f"    📋 final_rankings 업데이트 (기존 rank1: {first_name} → 새 rank1: {champion_name})")
            # Don't modify final_rankings here - the compute_dual_de_final_rankings()
            # in server.py will handle this from the second_de bouts

    # Save to DB
    update_url = f"{SUPABASE_URL}/rest/v1/events?sub_event_cd=eq.{sub_event_cd}"
    update_resp = httpx.patch(update_url, headers=headers, json={"raw_data": raw_data})
    if update_resp.status_code in (200, 204):
        print(f"    ✅ DB 업데이트 성공")
        return True
    else:
        print(f"    ❌ DB 업데이트 실패: {update_resp.status_code}")
        return False


async def main():
    from playwright.async_api import async_playwright

    print("=" * 70)
    print("Dual DE 결승 수정: Second DE 순위 기반")
    print(f"대상: {len(AFFECTED_EVENTS)}개 이벤트")
    print("=" * 70)

    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        for ev in AFFECTED_EVENTS:
            page = await browser.new_page()
            page.set_default_timeout(15000)

            print(f"\n{'─'*50}")
            print(f"📌 {ev['desc']}")
            print(f"   comp={ev['comp_cd']}, event={ev['sub_event_cd']}")
            print(f"{'─'*50}")

            try:
                rankings = await scrape_second_de_rankings(
                    page, ev['comp_cd'], ev['sub_event_cd']
                )
                if rankings:
                    results.append({
                        "sub_event_cd": ev["sub_event_cd"],
                        "desc": ev["desc"],
                        "rankings": rankings
                    })
            except Exception as e:
                print(f"    오류: {e}")
            finally:
                await page.close()

            await asyncio.sleep(1.5)

        await browser.close()

    # DB Update
    if results:
        print(f"\n\n{'='*70}")
        print(f"💾 DB 업데이트: {len(results)}개")
        print(f"{'='*70}")

        success = 0
        for r in results:
            print(f"\n--- {r['desc']} ---")
            if update_db_with_rankings(r['sub_event_cd'], r['rankings']):
                success += 1

        print(f"\n✅ {success}/{len(results)} 성공")

    # Summary
    resolved = {r['sub_event_cd'] for r in results}
    unresolved = [ev for ev in AFFECTED_EVENTS if ev['sub_event_cd'] not in resolved]

    print(f"\n{'='*70}")
    print(f"최종: {len(results)}/{len(AFFECTED_EVENTS)} 해결")
    if unresolved:
        for ev in unresolved:
            print(f"  ❌ {ev['desc']}")


if __name__ == "__main__":
    asyncio.run(main())
