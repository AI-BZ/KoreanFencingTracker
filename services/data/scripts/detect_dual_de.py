"""
국가대표 대회 Dual DE 형식 감지 스크립트

목적: 각 종목의 de_format 필드를 dual_de 또는 single_de로 설정
방식: schEtc01 selector 존재 여부로 Dual DE 형식 판단 (데이터 파싱 없음)

사용법:
    # Dry-run (실제 DB 업데이트 없이 대상 확인)
    python scripts/detect_dual_de.py --dry-run

    # 1개 대회 테스트
    python scripts/detect_dual_de.py --limit 1

    # 전체 실행
    python scripts/detect_dual_de.py

    # 특정 대회만
    python scripts/detect_dual_de.py --comp-idx COMPM00608
"""
import asyncio
import os
import sys
import argparse
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from loguru import logger
from supabase import create_client, Client
from playwright.async_api import async_playwright, Page

load_dotenv()

BASE_URL = "https://fencing.sports.or.kr"


def get_supabase_client() -> Optional[Client]:
    """Supabase 클라이언트 생성"""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    if not url or not key:
        logger.error("SUPABASE_URL 또는 SUPABASE_KEY 환경변수가 설정되지 않았습니다")
        return None

    return create_client(url, key)


@dataclass
class EventInfo:
    """종목 정보"""
    event_id: int
    sub_event_cd: str
    event_name: str
    current_de_format: Optional[str]


@dataclass
class CompetitionInfo:
    """대회 정보"""
    db_id: int
    comp_idx: str
    comp_name: str
    start_date: str
    events: List[EventInfo]


async def detect_dual_de_on_page(page: Page) -> bool:
    """현재 페이지에서 Dual DE 형식 감지 (schEtc01 selector 확인)"""
    has_dual_de = await page.evaluate("""
        () => {
            const selector = document.querySelector('select#schEtc01');
            if (!selector) return false;

            const options = Array.from(selector.options || []);
            const hasFirstDE = options.some(opt =>
                opt.text.includes('면제자') || opt.text.includes('예선엘리미나시옹')
            );
            const hasSecondDE = options.some(opt =>
                opt.text.includes('본선') && opt.text.includes('64강')
            );

            return hasFirstDE && hasSecondDE;
        }
    """)
    return has_dual_de or False


class DualDEDetector:
    """Dual DE 형식 감지기"""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.db = get_supabase_client()
        self.browser = None
        self.stats = {
            "competitions_processed": 0,
            "events_checked": 0,
            "dual_de_detected": 0,
            "single_de_detected": 0,
            "events_updated": 0,
            "errors": 0,
        }

    async def __aenter__(self):
        """컨텍스트 매니저 진입"""
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(headless=self.headless)
        logger.info("✅ DualDEDetector 초기화 완료")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """컨텍스트 매니저 종료"""
        if self.browser:
            await self.browser.close()

        logger.info(f"""
📊 Dual DE 감지 완료 통계:
   대회: {self.stats['competitions_processed']}
   종목 확인: {self.stats['events_checked']}
   Dual DE: {self.stats['dual_de_detected']}
   Single DE: {self.stats['single_de_detected']}
   DB 업데이트: {self.stats['events_updated']}
   오류: {self.stats['errors']}
        """)

    def get_national_team_competitions(
        self, comp_idx: Optional[str] = None, limit: Optional[int] = None
    ) -> List[CompetitionInfo]:
        """국가대표 대회 목록 조회 (competition_code가 있는 대회)"""
        query = self.db.table('competitions').select(
            'id, comp_idx, comp_name, start_date, competition_code'
        ).not_.is_('competition_code', 'null')

        if comp_idx:
            query = query.eq('comp_idx', comp_idx)

        result = query.order('start_date', desc=True).execute()

        competitions = []
        for row in result.data:
            # 해당 대회의 개인전 이벤트만 조회 (event_name에 (개) 포함)
            events_result = self.db.table('events').select(
                'id, sub_event_cd, event_name, de_format'
            ).eq('competition_id', row['id']).execute()

            # event_name에 '(개)' 포함된 것만 필터링 (개인전)
            events = [
                EventInfo(
                    event_id=e['id'],
                    sub_event_cd=e['sub_event_cd'],
                    event_name=e['event_name'],
                    current_de_format=e.get('de_format'),
                )
                for e in events_result.data
                if '(개)' in e.get('event_name', '')
            ]

            if events:  # 개인전 종목이 있는 대회만
                competitions.append(CompetitionInfo(
                    db_id=row['id'],
                    comp_idx=row['comp_idx'],
                    comp_name=row['comp_name'],
                    start_date=row['start_date'],
                    events=events,
                ))

        if limit:
            competitions = competitions[:limit]

        return competitions

    async def find_competition_page(self, page: Page, comp_idx: str, max_pages: int = 20) -> int:
        """대회가 위치한 페이지 번호를 찾습니다."""
        await page.goto(f"{BASE_URL}/game/compList?code=game", wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(1500)

        for page_num in range(1, max_pages + 1):
            link = page.locator(f"a[onclick*=\"{comp_idx}\"]")
            link_count = await link.count()

            if link_count > 0:
                logger.debug(f"  대회 {comp_idx} 발견: 페이지 {page_num}")
                return page_num

            # 다음 페이지로 이동
            try:
                next_btn = page.locator("a:has-text('다음페이지')")
                is_visible = await next_btn.is_visible()
                if not is_visible:
                    break
                await next_btn.click(timeout=5000)
                await page.wait_for_timeout(1500)
            except Exception:
                break

        logger.warning(f"  대회 {comp_idx}를 {max_pages} 페이지 내에서 찾지 못함")
        return 0

    async def navigate_to_event_de_tab(
        self, page: Page, comp_idx: str, sub_event_cd: str, page_num: int
    ) -> bool:
        """특정 종목의 DE 탭으로 이동"""
        try:
            # 1. 대회 목록 페이지로
            await page.goto(f"{BASE_URL}/game/compList?code=game", wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(1000)

            # 2. 해당 페이지로 이동
            for i in range(page_num - 1):
                next_btn = page.locator("a:has-text('다음페이지')")
                await next_btn.click(timeout=5000)
                await page.wait_for_timeout(1000)

            # 3. 대회 클릭
            link = page.locator(f"a[onclick*=\"{comp_idx}\"]")
            await link.first.click(timeout=5000)
            await page.wait_for_timeout(2000)

            # 4. 경기결과 탭 클릭
            result_tab = page.locator("a[onclick*='funcLeftSub']:has-text('경기결과')").first
            if await result_tab.count() > 0:
                await result_tab.click(timeout=5000)
                await page.wait_for_timeout(1500)

            # 5. 종목 선택
            select = page.locator("select").first
            await select.select_option(value=sub_event_cd)
            await page.wait_for_timeout(1000)

            # 6. 검색 버튼 클릭
            search_btn = page.locator("a[href='#search']").first
            await search_btn.click()
            await page.wait_for_timeout(2000)

            # 7. 대진표 탭 클릭
            bracket_tab = page.locator("a[onclick*='funcLeftSub']:has-text('대진표')").first
            if await bracket_tab.count() > 0:
                await bracket_tab.click(timeout=5000)
                await page.wait_for_timeout(1500)

            # 8. 엘리미나시옹디렉트 탭 클릭
            de_tab = page.locator("a:has-text('엘리미나시옹디렉트')").first
            if await de_tab.count() > 0:
                await de_tab.click(timeout=5000)
                await page.wait_for_timeout(2000)
                return True

            return False

        except Exception as e:
            logger.error(f"  탭 이동 실패: {e}")
            return False

    async def detect_competition_dual_de(
        self, comp: CompetitionInfo, dry_run: bool = False
    ) -> Dict[str, Any]:
        """대회의 모든 종목에 대해 Dual DE 형식 감지"""
        result = {
            "comp_idx": comp.comp_idx,
            "comp_name": comp.comp_name,
            "events_checked": 0,
            "dual_de_events": [],
            "single_de_events": [],
            "errors": [],
        }

        page = await self.browser.new_page()
        page.set_default_timeout(15000)

        try:
            # 대회 페이지 번호 찾기
            page_num = await self.find_competition_page(page, comp.comp_idx)
            if page_num == 0:
                result["errors"].append(f"대회를 찾을 수 없음: {comp.comp_idx}")
                self.stats["errors"] += 1
                return result

            logger.info(f"🔄 대회 {comp.comp_name} - {len(comp.events)}개 종목 확인 (페이지 {page_num})")

            for event in comp.events:
                try:
                    # DE 탭으로 이동
                    success = await self.navigate_to_event_de_tab(
                        page, comp.comp_idx, event.sub_event_cd, page_num
                    )

                    if not success:
                        result["errors"].append(f"종목 탭 이동 실패: {event.event_name}")
                        self.stats["errors"] += 1
                        continue

                    # Dual DE 감지
                    is_dual_de = await detect_dual_de_on_page(page)
                    self.stats["events_checked"] += 1
                    result["events_checked"] += 1

                    de_format = "dual_de" if is_dual_de else "single_de"

                    if is_dual_de:
                        self.stats["dual_de_detected"] += 1
                        result["dual_de_events"].append(event.event_name)
                        logger.info(f"  🎯 Dual DE: {event.event_name}")
                    else:
                        self.stats["single_de_detected"] += 1
                        result["single_de_events"].append(event.event_name)
                        logger.debug(f"  📄 Single DE: {event.event_name}")

                    # DB 업데이트 (dry_run이 아닐 때만)
                    if not dry_run and event.current_de_format != de_format:
                        self.db.table('events').update({
                            "de_format": de_format,
                            "validated_at": datetime.now().isoformat(),
                        }).eq('id', event.event_id).execute()
                        self.stats["events_updated"] += 1
                        logger.debug(f"    → DB 업데이트: {event.current_de_format} → {de_format}")

                except Exception as e:
                    error_msg = f"종목 확인 오류 ({event.event_name}): {e}"
                    result["errors"].append(error_msg)
                    logger.error(f"  ❌ {error_msg}")
                    self.stats["errors"] += 1

            self.stats["competitions_processed"] += 1

        finally:
            await page.close()

        return result

    async def run(
        self,
        comp_idx: Optional[str] = None,
        limit: Optional[int] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """감지 실행"""
        competitions = self.get_national_team_competitions(comp_idx, limit)

        print("=" * 70)
        print("국가대표 대회 Dual DE 형식 감지")
        print("=" * 70)
        print(f"대상 대회: {len(competitions)}개")
        print(f"모드: {'DRY-RUN (DB 업데이트 없음)' if dry_run else '실제 실행'}")
        print()

        for i, comp in enumerate(competitions):
            print(f"[{i+1}] {comp.comp_idx}: {comp.comp_name}")
            print(f"    기간: {comp.start_date}")
            print(f"    개인전 종목: {len(comp.events)}개")
            print()

        if dry_run:
            print("=" * 70)
            print("DRY-RUN 모드 - DB 업데이트를 수행하지 않습니다.")
            print("=" * 70)

        results = []
        for i, comp in enumerate(competitions):
            print(f"\n[{i+1}/{len(competitions)}] {comp.comp_name}")

            result = await self.detect_competition_dual_de(comp, dry_run)
            results.append(result)

            # 진행 상황 출력
            dual_count = len(result.get("dual_de_events", []))
            single_count = len(result.get("single_de_events", []))
            error_count = len(result.get("errors", []))

            if dual_count > 0:
                print(f"   ✅ Dual DE: {dual_count}개 종목")
            if single_count > 0:
                print(f"   📄 Single DE: {single_count}개 종목")
            if error_count > 0:
                print(f"   ⚠️ 오류: {error_count}개")

        return {
            "total_competitions": len(competitions),
            "results": results,
            "stats": self.stats,
        }


async def main():
    parser = argparse.ArgumentParser(description="국가대표 대회 Dual DE 형식 감지")
    parser.add_argument("--dry-run", action="store_true", help="대상만 출력 (DB 업데이트 안함)")
    parser.add_argument("--limit", type=int, default=None, help="처리할 대회 수 제한")
    parser.add_argument("--comp-idx", type=str, default=None, help="특정 대회만 처리")
    parser.add_argument("--headless", action="store_true", default=True, help="헤드리스 모드")
    parser.add_argument("--headful", action="store_true", help="GUI 브라우저 모드")

    args = parser.parse_args()

    headless = not args.headful

    async with DualDEDetector(headless=headless) as detector:
        await detector.run(
            comp_idx=args.comp_idx,
            limit=args.limit,
            dry_run=args.dry_run
        )


if __name__ == "__main__":
    asyncio.run(main())
