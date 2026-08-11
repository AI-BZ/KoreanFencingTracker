"""
국가대표 대회 재스크래핑 스크립트

목적: Dual DE 형식 감지 및 de_format='dual_de' 설정
대상: competition_code가 있는 국가대표 선발전 관련 대회

사용법:
    # Dry-run (실제 스크래핑 없이 대상 확인)
    python scripts/rescrape_national_team.py --dry-run

    # 1개 대회 테스트 (가장 최근 대회)
    python scripts/rescrape_national_team.py --limit 1

    # 전체 실행
    python scripts/rescrape_national_team.py

    # 특정 대회만
    python scripts/rescrape_national_team.py --comp-idx COMPM00680
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

from scraper.full_scraper import KFFFullScraper, Competition

load_dotenv()


def get_supabase_client() -> Optional[Client]:
    """Supabase 클라이언트 생성"""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    if not url or not key:
        logger.error("SUPABASE_URL 또는 SUPABASE_KEY 환경변수가 설정되지 않았습니다")
        return None

    return create_client(url, key)


@dataclass
class NationalTeamCompetition:
    """국가대표 대회 정보"""
    db_id: int
    comp_idx: str
    comp_name: str
    start_date: str
    end_date: str
    competition_code: str
    event_count: int


class NationalTeamRescraper:
    """국가대표 대회 재스크래퍼"""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.db = get_supabase_client()
        self.scraper: Optional[KFFFullScraper] = None
        self.stats = {
            "competitions_processed": 0,
            "events_updated": 0,
            "dual_de_detected": 0,
            "errors": 0,
        }

    async def __aenter__(self):
        """컨텍스트 매니저 진입"""
        self.scraper = KFFFullScraper(headless=self.headless)
        await self.scraper.__aenter__()
        logger.info("✅ NationalTeamRescraper 초기화 완료")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """컨텍스트 매니저 종료"""
        if self.scraper:
            await self.scraper.__aexit__(exc_type, exc_val, exc_tb)

        logger.info(f"""
📊 재스크래핑 완료 통계:
   대회: {self.stats['competitions_processed']}
   종목 업데이트: {self.stats['events_updated']}
   Dual DE 감지: {self.stats['dual_de_detected']}
   오류: {self.stats['errors']}
        """)

    def get_national_team_competitions(
        self, comp_idx: Optional[str] = None, limit: Optional[int] = None
    ) -> List[NationalTeamCompetition]:
        """
        국가대표 대회 목록 조회 (competition_code가 있는 대회)
        """
        query = self.db.table('competitions').select(
            'id, comp_idx, comp_name, start_date, end_date, competition_code'
        ).not_.is_('competition_code', 'null')

        if comp_idx:
            query = query.eq('comp_idx', comp_idx)

        result = query.order('start_date', desc=True).execute()

        competitions = []
        for row in result.data:
            # 해당 대회의 이벤트 수 조회
            events_result = self.db.table('events').select(
                'id', count='exact'
            ).eq('competition_id', row['id']).execute()

            competitions.append(NationalTeamCompetition(
                db_id=row['id'],
                comp_idx=row['comp_idx'],
                comp_name=row['comp_name'],
                start_date=row['start_date'],
                end_date=row['end_date'],
                competition_code=row['competition_code'],
                event_count=events_result.count or 0,
            ))

        if limit:
            competitions = competitions[:limit]

        return competitions

    async def _find_competition_page(self, comp_idx: str, max_pages: int = 20) -> int:
        """
        대회가 위치한 페이지 번호를 찾습니다.

        Args:
            comp_idx: 대회 코드 (COMPM00608 등)
            max_pages: 최대 탐색 페이지 수

        Returns:
            페이지 번호 (1-based), 찾지 못하면 0
        """
        page = await self.scraper._browser.new_page()
        page.set_default_timeout(15000)

        try:
            BASE_URL = "https://fencing.sports.or.kr"
            await page.goto(f"{BASE_URL}/game/compList?code=game", wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(1500)

            for page_num in range(1, max_pages + 1):
                # 현재 페이지에서 대회 링크 찾기
                link = page.locator(f"a[onclick*=\"{comp_idx}\"]")
                link_count = await link.count()

                if link_count > 0:
                    logger.info(f"  📍 대회 {comp_idx} 발견: 페이지 {page_num}")
                    return page_num

                # 다음 페이지로 이동
                try:
                    next_btn = page.locator("a:has-text('다음페이지')")
                    is_visible = await next_btn.is_visible()
                    if not is_visible:
                        logger.warning(f"  ⚠️ 다음 페이지 버튼 없음 (페이지 {page_num})")
                        break
                    await next_btn.click(timeout=5000)
                    await page.wait_for_timeout(1500)
                except Exception as e:
                    logger.warning(f"  ⚠️ 페이지 이동 실패: {e}")
                    break

            logger.warning(f"  ❌ 대회 {comp_idx}를 {max_pages} 페이지 내에서 찾지 못함")
            return 0

        finally:
            await page.close()

    async def rescrape_competition(self, comp: NationalTeamCompetition) -> Dict[str, Any]:
        """
        단일 대회 재스크래핑

        1. 웹에서 종목 데이터 스크래핑
        2. Dual DE 감지
        3. DB 업데이트 (de_format, has_first_de, has_second_de)
        """
        result = {
            "comp_idx": comp.comp_idx,
            "comp_name": comp.comp_name,
            "events_updated": 0,
            "dual_de_count": 0,
            "errors": [],
        }

        try:
            # 대회가 위치한 페이지 번호 찾기
            page_num = await self._find_competition_page(comp.comp_idx)
            if page_num == 0:
                result["errors"].append(f"대회를 찾을 수 없음: {comp.comp_idx}")
                self.stats["errors"] += 1
                return result

            # Competition 객체 생성
            from datetime import date
            competition = Competition(
                event_cd=comp.comp_idx,
                name=comp.comp_name,
                start_date=date.fromisoformat(comp.start_date) if comp.start_date else None,
                end_date=date.fromisoformat(comp.end_date) if comp.end_date else None,
                status="종료",
                location="",
                page_num=page_num,  # 찾은 페이지 번호 사용
            )

            # 스크래핑 실행
            logger.info(f"🔄 스크래핑 시작: {comp.comp_name} (페이지 {page_num})")
            comp_data = await self.scraper.scrape_competition_full(competition, page_num=page_num)

            # 각 종목 처리
            for event_data in comp_data.get("events", []):
                try:
                    updated = await self._update_event_de_format(comp.db_id, event_data)
                    if updated:
                        result["events_updated"] += 1
                        self.stats["events_updated"] += 1

                        # Dual DE 감지 여부
                        de_bracket = event_data.get("de_bracket", {})
                        if de_bracket.get("format") == "dual_de":
                            result["dual_de_count"] += 1
                            self.stats["dual_de_detected"] += 1

                except Exception as e:
                    error_msg = f"종목 처리 오류 ({event_data.get('name', 'Unknown')}): {e}"
                    result["errors"].append(error_msg)
                    logger.error(error_msg)
                    self.stats["errors"] += 1

            self.stats["competitions_processed"] += 1

        except Exception as e:
            error_msg = f"대회 스크래핑 오류: {e}"
            result["errors"].append(error_msg)
            logger.error(error_msg)
            self.stats["errors"] += 1

        return result

    async def _update_event_de_format(
        self, competition_id: int, event_data: Dict[str, Any]
    ) -> bool:
        """
        종목의 de_format 업데이트

        - de_bracket.format이 'dual_de'면 de_format='dual_de' 설정
        - has_first_de, has_second_de 플래그 설정
        """
        try:
            de_bracket = event_data.get("de_bracket", {})
            de_format = de_bracket.get("format", "single_de")
            has_first_de = de_bracket.get("first_de") is not None
            has_second_de = de_bracket.get("second_de") is not None

            sub_event_cd = event_data.get("sub_event_cd", "")
            event_cd = event_data.get("event_cd", "")

            if de_format == "dual_de":
                logger.info(f"🎯 Dual DE 감지: {event_data.get('name', 'Unknown')}")

            # 기존 이벤트 조회
            existing = self.db.table('events').select('id').eq(
                'competition_id', competition_id
            ).eq('sub_event_cd', sub_event_cd).execute()

            if existing.data:
                # 업데이트
                update_data = {
                    "de_format": de_format,
                    "has_first_de": has_first_de,
                    "has_second_de": has_second_de,
                    "raw_data": {
                        "pool_rounds": event_data.get("pool_rounds", []),
                        "pool_total_ranking": event_data.get("pool_total_ranking", []),
                        "de_bracket": de_bracket,
                        "final_rankings": event_data.get("final_rankings", []),
                    },
                    "validated_at": datetime.now().isoformat(),
                }

                self.db.table('events').update(update_data).eq(
                    'id', existing.data[0]['id']
                ).execute()

                return True
            else:
                logger.warning(f"이벤트를 찾을 수 없음: {sub_event_cd}")
                return False

        except Exception as e:
            logger.error(f"이벤트 업데이트 오류: {e}")
            return False

    async def run(
        self,
        comp_idx: Optional[str] = None,
        limit: Optional[int] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        재스크래핑 실행

        Args:
            comp_idx: 특정 대회만 처리
            limit: 처리할 대회 수 제한
            dry_run: True면 대상만 출력하고 실제 스크래핑 안함
        """
        competitions = self.get_national_team_competitions(comp_idx, limit)

        print("=" * 70)
        print("국가대표 대회 재스크래핑")
        print("=" * 70)
        print(f"대상 대회: {len(competitions)}개")
        print(f"모드: {'DRY-RUN (실제 스크래핑 없음)' if dry_run else '실제 실행'}")
        print()

        for i, comp in enumerate(competitions):
            print(f"[{i+1}] {comp.comp_idx}: {comp.comp_name}")
            print(f"    기간: {comp.start_date} ~ {comp.end_date}")
            print(f"    코드: {comp.competition_code}")
            print(f"    종목: {comp.event_count}개")
            print()

        if dry_run:
            print("DRY-RUN 모드 - 실제 스크래핑을 수행하지 않습니다.")
            return {"dry_run": True, "competitions": len(competitions)}

        # 실제 스크래핑 실행
        print("=" * 70)
        print("스크래핑 시작...")
        print("=" * 70)

        results = []
        for i, comp in enumerate(competitions):
            print(f"\n[{i+1}/{len(competitions)}] {comp.comp_name}")

            result = await self.rescrape_competition(comp)
            results.append(result)

            # 진행 상황 출력
            if result["dual_de_count"] > 0:
                print(f"   ✅ Dual DE {result['dual_de_count']}개 감지")
            else:
                print(f"   📄 일반 DE (종목 {result['events_updated']}개 업데이트)")

            if result["errors"]:
                print(f"   ⚠️ 오류: {len(result['errors'])}개")

        return {
            "total_competitions": len(competitions),
            "results": results,
            "stats": self.stats,
        }


async def main():
    parser = argparse.ArgumentParser(description="국가대표 대회 재스크래핑")
    parser.add_argument("--dry-run", action="store_true", help="대상만 출력 (실제 스크래핑 안함)")
    parser.add_argument("--limit", type=int, default=None, help="처리할 대회 수 제한")
    parser.add_argument("--comp-idx", type=str, default=None, help="특정 대회만 처리")
    parser.add_argument("--headless", action="store_true", default=True, help="헤드리스 모드")
    parser.add_argument("--headful", action="store_true", help="GUI 브라우저 모드")

    args = parser.parse_args()

    headless = not args.headful

    async with NationalTeamRescraper(headless=headless) as rescraper:
        await rescraper.run(
            comp_idx=args.comp_idx,
            limit=args.limit,
            dry_run=args.dry_run
        )


if __name__ == "__main__":
    asyncio.run(main())
