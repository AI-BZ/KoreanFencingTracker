"""
Dual DE 감지 테스트 스크립트 v3

직접 URL로 국가대표 선발전 종목 DE 페이지에 접근하여 테스트
"""
import asyncio
from playwright.async_api import async_playwright
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper.de_scraper_v4 import DEScraper


async def test_dual_de_detection():
    """알려진 국가대표 선발전 종목으로 Dual DE 테스트"""

    # 테스트 대상: 2025 전국남녀종목별오픈펜싱선수권대회 (COMPM00608)
    # 먼저 대회 페이지에 접근하여 종목 코드 확인
    base_url = "https://fencing.sports.or.kr/competition"

    print("=" * 60)
    print("Dual DE 감지 테스트 v3 - 직접 URL 접근")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            # 1. 대회 상세 페이지 직접 접근 (COMPM00608)
            print("\n📍 1. 대회 상세 페이지 로딩...")
            await page.goto(f"{base_url}/result.do?comp_idx=COMPM00608",
                          wait_until='networkidle', timeout=30000)
            await asyncio.sleep(2)
            print(f"   URL: {page.url}")

            # 2. 페이지 구조 확인
            print("\n📍 2. 페이지 구조 확인...")
            page_info = await page.evaluate("""
                () => {
                    const body = document.body;
                    return {
                        title: document.title,
                        bodyText: body ? body.innerText.substring(0, 500) : 'No body',
                        hasTable: !!document.querySelector('table'),
                        tableCount: document.querySelectorAll('table').length,
                        linkCount: document.querySelectorAll('a').length,
                        iframes: Array.from(document.querySelectorAll('iframe')).map(f => f.src)
                    };
                }
            """)
            print(f"   제목: {page_info['title']}")
            print(f"   테이블: {page_info['tableCount']}개")
            print(f"   링크: {page_info['linkCount']}개")
            if page_info['iframes']:
                print(f"   iframe: {page_info['iframes']}")
            print(f"   본문 일부: {page_info['bodyText'][:200]}...")

            # 3. 종목 목록 확인
            print("\n📍 3. 종목 목록 확인...")
            events = await page.evaluate("""
                () => {
                    // 다양한 선택자로 종목 링크 찾기
                    const selectors = [
                        'a[onclick*="fnMatch"]',
                        'a[href*="match"]',
                        'a[onclick*="evt"]',
                        '.evt_list a',
                        'table a'
                    ];

                    let allLinks = [];
                    for (const sel of selectors) {
                        const links = document.querySelectorAll(sel);
                        links.forEach(a => {
                            allLinks.push({
                                selector: sel,
                                text: a.textContent.trim(),
                                onclick: a.getAttribute('onclick') || '',
                                href: a.getAttribute('href') || ''
                            });
                        });
                    }
                    return allLinks.slice(0, 20);
                }
            """)

            if events:
                print(f"   발견된 링크: {len(events)}개")
                for evt in events[:10]:
                    print(f"     [{evt['selector']}] {evt['text'][:30]} | onclick={evt['onclick'][:50] if evt['onclick'] else 'N/A'}")

                # fnMatch 형태 링크 찾기
                fnmatch_links = [e for e in events if 'fnMatch' in e['onclick']]
                if fnmatch_links:
                    # onclick에서 evt_cd 추출
                    import re
                    for link in fnmatch_links[:3]:
                        match = re.search(r"fnMatch\('([^']+)'", link['onclick'])
                        if match:
                            link['evt_cd'] = match.group(1)
                            print(f"   ✓ evt_cd 발견: {link['evt_cd']} - {link['text']}")

                    # 첫 번째 개인전 종목 선택
                    individual = next((e for e in fnmatch_links if '(개)' in e['text'] and e.get('evt_cd')), None)
                    if not individual and fnmatch_links:
                        individual = fnmatch_links[0]
                        match = re.search(r"fnMatch\('([^']+)'", individual['onclick'])
                        if match:
                            individual['evt_cd'] = match.group(1)

                    if individual and individual.get('evt_cd'):
                        print(f"\n   선택 종목: {individual['text']}")
                        evt_cd = individual['evt_cd']

                        # 4. 종목 결과 페이지로 이동 (DE 탭)
                        print("\n📍 4. 종목 DE 페이지로 이동...")
                        de_url = f"{base_url}/match.do?evt_cd={evt_cd}&type=d"
                        await page.goto(de_url, wait_until='networkidle', timeout=30000)
                        await asyncio.sleep(2)
                        print(f"   DE URL: {page.url}")
                    else:
                        print("   evt_cd를 추출할 수 없음")
                        return
                else:
                    print("   fnMatch 링크를 찾지 못함")
                    return
            else:
                # 종목을 찾지 못하면 테이블 HTML 확인
                print("   링크를 찾지 못함. 페이지 확인 필요")
                return

            # 5. Dual DE selector 확인
            print("\n📍 5. Dual DE selector 확인...")
            selector_info = await page.evaluate("""
                () => {
                    const selector = document.querySelector('select#schEtc01');
                    if (!selector) {
                        const allSelects = Array.from(document.querySelectorAll('select')).map(s => ({
                            id: s.id || '',
                            name: s.name || '',
                            options: Array.from(s.options).map(o => o.text).slice(0, 5)
                        }));
                        return { found: false, selects: allSelects };
                    }
                    return {
                        found: true,
                        options: Array.from(selector.options).map(o => ({
                            value: o.value,
                            text: o.text
                        }))
                    };
                }
            """)

            print("\n" + "=" * 60)
            print("결과")
            print("=" * 60)

            if selector_info.get('found'):
                print("✅ schEtc01 selector 발견!")
                for opt in selector_info.get('options', []):
                    print(f"   - [{opt['value']}] {opt['text']}")

                # Dual DE 감지
                scraper = DEScraper(page)
                is_dual_de = await scraper.detect_dual_de_format()
                print(f"\n   Dual DE: {'✅ YES' if is_dual_de else '❌ NO'}")
            else:
                print("❌ schEtc01 없음")
                selects = selector_info.get('selects', [])
                if selects:
                    print(f"   기타 select 요소 {len(selects)}개:")
                    for s in selects:
                        if s['id'] or s['name']:
                            print(f"     id={s['id']}, name={s['name']}")
                            print(f"     options: {s['options']}")

            # 6. DE 대진표 테이블 존재 확인
            print("\n📍 6. DE 대진표 테이블 확인...")
            de_info = await page.evaluate("""
                () => {
                    // 대진표 테이블 확인
                    const tables = document.querySelectorAll('table');
                    const rowTables = document.querySelectorAll('.row_table');

                    // 탭 확인
                    const tabs = document.querySelectorAll('.de_tab a, [onclick*="fnGetMatch"]');

                    return {
                        tableCount: tables.length,
                        rowTableCount: rowTables.length,
                        tabCount: tabs.length,
                        tabTexts: Array.from(tabs).map(t => t.textContent.trim()).slice(0, 5)
                    };
                }
            """)
            print(f"   테이블: {de_info['tableCount']}개")
            print(f"   row_table: {de_info['rowTableCount']}개")
            print(f"   DE 탭: {de_info['tabCount']}개")
            if de_info['tabTexts']:
                print(f"   탭 내용: {de_info['tabTexts']}")

        except Exception as e:
            print(f"❌ 오류: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await browser.close()

    print("\n📍 테스트 완료")


if __name__ == "__main__":
    asyncio.run(test_dual_de_detection())
