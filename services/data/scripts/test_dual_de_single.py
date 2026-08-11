"""
단일 국가대표 대회 Dual DE 테스트 스크립트

full_scraper의 기능을 활용하여 특정 대회의 Dual DE 감지를 테스트합니다.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.async_api import async_playwright
from scraper.de_scraper_v4 import DEScraper
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BASE_URL = "https://fencing.sports.or.kr"


async def test_single_competition(comp_idx: str = "COMPM00608"):
    """단일 대회의 Dual DE 감지 테스트"""

    print("=" * 60)
    print(f"Dual DE 테스트 - {comp_idx}")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # GUI 모드
        page = await browser.new_page()

        try:
            # 1. 대회 목록 페이지로 이동
            print("\n📍 1. 대회 목록 페이지 로딩...")
            await page.goto(f"{BASE_URL}/game/compList?code=game", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)
            print(f"   URL: {page.url}")

            # 2. 해당 대회 찾기 (최근 대회는 첫 페이지에 있음)
            print(f"\n📍 2. 대회 {comp_idx} 클릭...")
            comp_link = page.locator(f"a[onclick*=\"{comp_idx}\"]")
            if await comp_link.count() > 0:
                await comp_link.first.click(timeout=5000)
                await page.wait_for_timeout(2000)
                print("   대회 클릭 완료")
            else:
                # 페이지 이동 필요
                print("   첫 페이지에 없음 - 검색 필요")
                # 검색어로 찾기
                search_input = page.locator("input[name='searchKeyword']")
                if await search_input.count() > 0:
                    await search_input.fill("국가대표")
                    await page.locator("a[href='#search']").first.click()
                    await page.wait_for_timeout(2000)

                    comp_link = page.locator(f"a[onclick*=\"{comp_idx}\"]")
                    if await comp_link.count() > 0:
                        await comp_link.first.click(timeout=5000)
                        await page.wait_for_timeout(2000)
                        print("   검색 후 대회 클릭 완료")
                    else:
                        print("   ❌ 대회를 찾을 수 없음")
                        return
                else:
                    print("   ❌ 검색 필드를 찾을 수 없음")
                    return

            # 3. 경기결과 탭 클릭
            print("\n📍 3. 경기결과 탭 클릭...")
            result_tab = page.locator("a[onclick*='funcLeftSub']:has-text('경기결과')").first
            await result_tab.click(timeout=5000)
            await page.wait_for_timeout(2000)
            print("   경기결과 탭 클릭 완료")

            # 4. 종목 목록 확인
            print("\n📍 4. 종목 목록 확인...")
            events = await page.evaluate("""
                () => {
                    const select = document.querySelector('select');
                    if (!select) return [];
                    return Array.from(select.options).map(opt => ({
                        value: opt.value,
                        text: opt.text
                    })).filter(o => o.value);
                }
            """)

            if events:
                print(f"   종목 {len(events)}개 발견:")
                for evt in events[:6]:
                    print(f"     - [{evt['value']}] {evt['text']}")

                # 첫 번째 개인전 종목 선택
                individual = next((e for e in events if '(개)' in e['text']), events[0])
                print(f"\n   선택 종목: {individual['text']}")

                # 종목 선택
                select = page.locator("select").first
                await select.select_option(value=individual['value'])
                await page.wait_for_timeout(1000)

                # 검색 버튼 클릭
                search_btn = page.locator("a[href='#search']").first
                await search_btn.click()
                await page.wait_for_timeout(2000)
            else:
                print("   종목을 찾을 수 없음")
                return

            # 5. 대진표 탭 클릭
            print("\n📍 5. 대진표 탭 클릭...")
            bracket_tab = page.locator("a[onclick*='funcLeftSub']:has-text('대진표')").first
            await bracket_tab.click(timeout=5000)
            await page.wait_for_timeout(2000)
            print("   대진표 탭 클릭 완료")

            # 6. 엘리미나시옹디렉트 탭 클릭
            print("\n📍 6. 엘리미나시옹디렉트 탭 클릭...")
            de_tab = page.locator("a:has-text('엘리미나시옹디렉트')").first
            await de_tab.click(timeout=5000)
            await page.wait_for_timeout(2000)
            print("   엘리미나시옹디렉트 탭 클릭 완료")

            # 7. Dual DE selector 확인
            print("\n📍 7. Dual DE selector 확인...")
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

                # DEScraper로 Dual DE 감지
                scraper = DEScraper(page)
                is_dual_de = await scraper.detect_dual_de_format()
                print(f"\n   Dual DE: {'✅ YES' if is_dual_de else '❌ NO'}")

                if is_dual_de:
                    print("\n🎉 Dual DE 형식 감지 성공!")
                    print("   재스크래핑 시 de_format='dual_de' 설정됨")
            else:
                print("❌ schEtc01 없음 - 일반 DE 형식")
                selects = selector_info.get('selects', [])
                if selects:
                    print(f"   기타 select 요소 {len(selects)}개:")
                    for s in selects[:3]:
                        if s['id'] or s['name']:
                            print(f"     id={s['id']}, name={s['name']}")

            # 8. 페이지 상태 확인을 위해 잠시 대기
            print("\n📍 8. 브라우저 확인 (10초간 유지)...")
            await page.wait_for_timeout(10000)

        except Exception as e:
            print(f"❌ 오류: {e}")
            import traceback
            traceback.print_exc()
            # 오류 시에도 브라우저 확인 가능하도록
            await page.wait_for_timeout(5000)
        finally:
            await browser.close()

    print("\n📍 테스트 완료")


if __name__ == "__main__":
    comp_idx = sys.argv[1] if len(sys.argv) > 1 else "COMPM00608"
    asyncio.run(test_single_competition(comp_idx))
