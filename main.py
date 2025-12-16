"""
대한펜싱협회 경기결과 스크래퍼 메인
"""
import asyncio
import sys
from datetime import datetime
from typing import Optional
from loguru import logger

from scraper.client import KFFClient
from scraper.models import ScrapeResult
from database.supabase_client import SupabaseDB
from scheduler.scheduler import FencingScheduler


# 로깅 설정
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO"
)
logger.add(
    "logs/scraper_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="30 days",
    level="DEBUG"
)


class FencingScraper:
    """펜싱 데이터 스크래퍼"""

    def __init__(self):
        self.db: Optional[SupabaseDB] = None
        self._initialized = False

    async def initialize(self):
        """초기화"""
        try:
            self.db = SupabaseDB()
            self._initialized = True
            logger.info("스크래퍼 초기화 완료")
        except Exception as e:
            logger.error(f"초기화 오류: {e}")
            raise

    async def full_sync(self) -> ScrapeResult:
        """전체 데이터 동기화"""
        if not self._initialized:
            await self.initialize()

        result = ScrapeResult()
        start_time = datetime.now()

        # 로그 생성
        log_id = await self.db.create_scrape_log("full_sync")

        try:
            async with KFFClient() as client:
                # 1. 대회 목록 수집
                logger.info("대회 목록 수집 중...")
                competitions = await client.get_all_competitions()
                result.competitions_count = len(competitions)
                logger.info(f"총 {len(competitions)}개 대회 발견")

                # 2. 대회 저장
                for comp in competitions:
                    comp_id = await self.db.upsert_competition(comp)
                    if not comp_id:
                        continue

                    # 3. 종목 수집
                    events = await client.get_events(comp.comp_idx)
                    result.events_count += len(events)

                    for event in events:
                        event_id = await self.db.upsert_event(event, comp_id)
                        if not event_id or not event.sub_event_cd:
                            continue

                        # 4. 경기 결과 수집
                        matches = await client.get_match_results(
                            comp.comp_idx,
                            event.sub_event_cd
                        )
                        result.matches_count += len(matches)

                        # 기존 경기 삭제 후 재저장
                        await self.db.delete_event_matches(event_id)
                        for match in matches:
                            await self.db.upsert_match(match, event_id)

                        # 5. 순위 수집
                        rankings = await client.get_rankings(
                            comp.comp_idx,
                            event.sub_event_cd
                        )
                        result.rankings_count += len(rankings)

                        for ranking in rankings:
                            await self.db.upsert_ranking(ranking, event_id)

                        # 선수 수 (경기에서 추출)
                        players = await client.get_players(
                            comp.comp_idx,
                            event.sub_event_cd
                        )
                        result.players_count += len(players)

            result.success = True
            result.duration_seconds = (datetime.now() - start_time).total_seconds()

            # 로그 업데이트
            await self.db.update_scrape_log(
                log_id,
                status="completed",
                competitions_processed=result.competitions_count,
                events_processed=result.events_count,
                matches_processed=result.matches_count
            )

            logger.info(f"전체 동기화 완료: {result.duration_seconds:.1f}초")
            logger.info(f"  대회: {result.competitions_count}개")
            logger.info(f"  종목: {result.events_count}개")
            logger.info(f"  경기: {result.matches_count}개")
            logger.info(f"  순위: {result.rankings_count}개")
            logger.info(f"  선수: {result.players_count}명")

        except Exception as e:
            result.success = False
            result.errors.append(str(e))
            result.duration_seconds = (datetime.now() - start_time).total_seconds()

            await self.db.update_scrape_log(
                log_id,
                status="failed",
                error_message=str(e)
            )

            logger.error(f"전체 동기화 오류: {e}")

        return result

    async def update_active_competitions(self) -> ScrapeResult:
        """진행중인 대회만 업데이트"""
        if not self._initialized:
            await self.initialize()

        result = ScrapeResult()
        start_time = datetime.now()

        log_id = await self.db.create_scrape_log("incremental")

        try:
            # 진행중인 대회 조회
            active_comps = await self.db.get_active_competitions()
            logger.info(f"진행중인 대회: {len(active_comps)}개")

            async with KFFClient() as client:
                for comp_data in active_comps:
                    comp_idx = comp_data.get("comp_idx")
                    comp_id = comp_data.get("id")

                    if not comp_idx or not comp_id:
                        continue

                    events = await client.get_events(comp_idx)

                    for event in events:
                        event_id = await self.db.get_event_id(
                            comp_id,
                            event.event_cd,
                            event.sub_event_cd
                        )

                        if not event_id or not event.sub_event_cd:
                            continue

                        # 경기 결과 업데이트
                        matches = await client.get_match_results(
                            comp_idx,
                            event.sub_event_cd
                        )
                        result.matches_count += len(matches)

                        await self.db.delete_event_matches(event_id)
                        for match in matches:
                            await self.db.upsert_match(match, event_id)

                        # 순위 업데이트
                        rankings = await client.get_rankings(
                            comp_idx,
                            event.sub_event_cd
                        )
                        result.rankings_count += len(rankings)

                        for ranking in rankings:
                            await self.db.upsert_ranking(ranking, event_id)

            result.success = True
            result.duration_seconds = (datetime.now() - start_time).total_seconds()

            await self.db.update_scrape_log(
                log_id,
                status="completed",
                matches_processed=result.matches_count
            )

            logger.info(f"증분 업데이트 완료: {result.duration_seconds:.1f}초")

        except Exception as e:
            result.success = False
            result.errors.append(str(e))

            await self.db.update_scrape_log(
                log_id,
                status="failed",
                error_message=str(e)
            )

            logger.error(f"증분 업데이트 오류: {e}")

        return result

    async def get_stats(self) -> dict:
        """데이터베이스 통계 조회"""
        if not self._initialized:
            await self.initialize()
        return await self.db.get_stats()


async def main():
    """메인 함수"""
    import argparse

    parser = argparse.ArgumentParser(description="대한펜싱협회 경기결과 스크래퍼")
    parser.add_argument(
        "--mode",
        choices=["sync", "update", "stats", "scheduler"],
        default="sync",
        help="실행 모드"
    )
    parser.add_argument(
        "--no-scheduler",
        action="store_true",
        help="스케줄러 없이 단일 실행"
    )

    args = parser.parse_args()

    scraper = FencingScraper()

    if args.mode == "sync":
        # 전체 동기화
        result = await scraper.full_sync()
        if not result.success:
            sys.exit(1)

    elif args.mode == "update":
        # 진행중 대회 업데이트
        result = await scraper.update_active_competitions()
        if not result.success:
            sys.exit(1)

    elif args.mode == "stats":
        # 통계 조회
        stats = await scraper.get_stats()
        print("\n=== 데이터베이스 통계 ===")
        for table, count in stats.items():
            print(f"  {table}: {count}개")

    elif args.mode == "scheduler":
        # 스케줄러 모드
        await scraper.initialize()

        scheduler = FencingScheduler(
            scraper_func=scraper.full_sync,
            active_update_func=scraper.update_active_competitions
        )
        scheduler.start()

        logger.info("스케줄러 모드로 실행 중... (Ctrl+C로 종료)")

        try:
            # 무한 대기
            while True:
                await asyncio.sleep(60)
                status = scheduler.get_status()
                logger.debug(f"스케줄러 상태: {status}")
        except KeyboardInterrupt:
            scheduler.stop()
            logger.info("스케줄러 종료됨")


if __name__ == "__main__":
    asyncio.run(main())
