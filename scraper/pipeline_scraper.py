"""
파이프라인 통합 스크래퍼

KFFFullScraper + DataPipeline + Supabase 통합
- 스크래핑 → 검증 → 저장 파이프라인
- 실시간 검증 및 품질 모니터링
"""
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import asdict
from loguru import logger

# 스크래퍼
from scraper.full_scraper import KFFFullScraper, Competition

# 데이터 파이프라인
from data_pipeline import (
    DataPipeline,
    DataQualityMonitor,
    DataSynchronizer,
    ValidationResult,
)

# Supabase
from database.supabase_client import get_supabase_client


class PipelineScraper:
    """
    파이프라인 통합 스크래퍼

    스크래핑 → 검증 → 저장 → 동기화
    """

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.scraper: Optional[KFFFullScraper] = None
        self.pipeline: Optional[DataPipeline] = None
        self.monitor: Optional[DataQualityMonitor] = None
        self.syncer: Optional[DataSynchronizer] = None
        self.db = None

        # 통계
        self.stats = {
            "competitions_scraped": 0,
            "events_scraped": 0,
            "events_validated": 0,
            "events_saved": 0,
            "validation_errors": 0,
            "validation_warnings": 0,
        }

    async def __aenter__(self):
        """컨텍스트 매니저 진입"""
        # Supabase 클라이언트
        self.db = get_supabase_client()

        # 파이프라인 초기화
        self.pipeline = DataPipeline(db_client=self.db)
        self.monitor = DataQualityMonitor(db_client=self.db)
        self.syncer = DataSynchronizer(db_client=self.db)

        # 스크래퍼 초기화
        self.scraper = KFFFullScraper(headless=self.headless)
        await self.scraper.__aenter__()

        logger.info("✅ PipelineScraper 초기화 완료")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """컨텍스트 매니저 종료"""
        if self.scraper:
            await self.scraper.__aexit__(exc_type, exc_val, exc_tb)

        # 최종 통계 로그
        logger.info(f"""
📊 스크래핑 완료 통계:
   대회: {self.stats['competitions_scraped']}
   종목: {self.stats['events_scraped']}
   검증 통과: {self.stats['events_validated']}
   저장 성공: {self.stats['events_saved']}
   검증 오류: {self.stats['validation_errors']}
   경고: {self.stats['validation_warnings']}
        """)

    # ==================== 메인 스크래핑 메서드 ====================

    async def scrape_and_save(
        self,
        start_year: int = 2024,
        end_year: int = 2025,
        limit: Optional[int] = None,
        status_filter: str = "종료"
    ) -> Dict[str, Any]:
        """
        전체 스크래핑 + 검증 + 저장 파이프라인

        Args:
            start_year: 시작 연도
            end_year: 종료 연도
            limit: 대회 수 제한 (테스트용)
            status_filter: 상태 필터 (종료, 진행중 등)

        Returns:
            처리 결과
        """
        # 대회 목록 수집
        competitions = await self.scraper.get_all_competitions(start_year, end_year)

        if status_filter:
            competitions = [c for c in competitions if c.status == status_filter]

        if limit:
            competitions = competitions[:limit]

        logger.info(f"📋 처리할 대회: {len(competitions)}개")

        results = []

        for i, comp in enumerate(competitions):
            logger.info(f"[{i+1}/{len(competitions)}] {comp.name}")

            try:
                result = await self._process_competition(comp)
                results.append(result)
                self.stats["competitions_scraped"] += 1
            except Exception as e:
                logger.error(f"대회 처리 실패 ({comp.name}): {e}")
                results.append({
                    "competition": asdict(comp),
                    "success": False,
                    "error": str(e)
                })

        # 품질 메트릭 수집
        await self._collect_quality_metrics()

        return {
            "total_competitions": len(competitions),
            "results": results,
            "stats": self.stats,
        }

    async def _process_competition(self, comp: Competition) -> Dict[str, Any]:
        """
        단일 대회 처리 (스크래핑 → 검증 → 저장)
        """
        result = {
            "competition": asdict(comp),
            "events_processed": 0,
            "events_saved": 0,
            "errors": [],
            "warnings": [],
        }

        # 1. 대회 저장/조회
        comp_id = await self._upsert_competition(comp)
        if not comp_id:
            result["errors"].append("대회 저장 실패")
            return result

        result["competition_id"] = comp_id

        # 2. 종목 스크래핑
        try:
            comp_data = await self.scraper.scrape_competition_full(
                comp, page_num=comp.page_num
            )
        except Exception as e:
            result["errors"].append(f"스크래핑 실패: {e}")
            return result

        # 3. 각 종목 처리
        for event_data in comp_data.get("events", []):
            self.stats["events_scraped"] += 1

            try:
                event_result = await self._process_event(comp_id, event_data)

                if event_result["saved"]:
                    result["events_saved"] += 1
                    self.stats["events_saved"] += 1
                else:
                    result["errors"].extend(event_result.get("errors", []))

                result["warnings"].extend(event_result.get("warnings", []))
                result["events_processed"] += 1

            except Exception as e:
                result["errors"].append(f"종목 처리 오류: {e}")
                self.stats["validation_errors"] += 1

        return result

    async def _process_event(
        self,
        competition_id: int,
        event_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        단일 종목 처리 (검증 → 저장)
        """
        result = {
            "event_name": event_data.get("name", "Unknown"),
            "saved": False,
            "errors": [],
            "warnings": [],
        }

        # 검증용 데이터 구성
        validation_data = {
            "name": event_data.get("name", ""),
            "weapon": event_data.get("weapon", ""),
            "gender": event_data.get("gender", ""),
            "age_group": event_data.get("age_group", ""),
            "event_type": event_data.get("event_type", "개인"),
            "competition_id": competition_id,
        }

        # 검증 실행
        tech_result, biz_result = self.pipeline.validate_data(
            validation_data, "event"
        )

        # 검증 결과 처리
        if tech_result.errors:
            result["errors"].extend([e.message for e in tech_result.errors])
            self.stats["validation_errors"] += len(tech_result.errors)

        if biz_result.warnings:
            result["warnings"].extend([w.message for w in biz_result.warnings])
            self.stats["validation_warnings"] += len(biz_result.warnings)

        # 검증 통과 시 저장
        if tech_result.can_save and biz_result.can_save:
            self.stats["events_validated"] += 1

            try:
                event_id = await self._upsert_event(competition_id, event_data)
                if event_id:
                    result["saved"] = True
                    result["event_id"] = event_id
                else:
                    result["errors"].append("종목 저장 실패")
            except Exception as e:
                result["errors"].append(f"저장 오류: {e}")

        return result

    # ==================== 데이터베이스 연산 ====================

    async def _upsert_competition(self, comp: Competition) -> Optional[int]:
        """대회 upsert"""
        try:
            data = {
                "comp_idx": comp.event_cd,
                "comp_name": comp.name,
                "start_date": comp.start_date.isoformat() if comp.start_date else None,
                "end_date": comp.end_date.isoformat() if comp.end_date else None,
                "status": comp.status,
                "venue": comp.location,
            }

            result = self.db.table("competitions").upsert(
                data, on_conflict="comp_idx"
            ).execute()

            if result.data:
                return result.data[0].get("id")
            return None

        except Exception as e:
            logger.error(f"대회 upsert 오류: {e}")
            return None

    async def _upsert_event(
        self,
        competition_id: int,
        event_data: Dict[str, Any]
    ) -> Optional[int]:
        """종목 upsert (raw_data 포함)"""
        try:
            # raw_data 구성
            raw_data = {
                "pool_rounds": event_data.get("pool_rounds", []),
                "pool_total_ranking": event_data.get("pool_total_ranking", []),
                "de_bracket": event_data.get("de_bracket", {}),
                "de_matches": event_data.get("de_matches", []),
                "final_rankings": event_data.get("final_rankings", []),
            }

            data = {
                "competition_id": competition_id,
                "event_cd": event_data.get("event_cd", ""),
                "sub_event_cd": event_data.get("sub_event_cd", ""),
                "event_name": event_data.get("name", ""),
                "weapon": event_data.get("weapon", ""),
                "gender": event_data.get("gender", ""),
                "age_group": event_data.get("age_group", ""),
                "category": event_data.get("event_type", "개인"),
                "participants_count": event_data.get("total_participants", 0),
                "raw_data": raw_data,
                "validated_at": datetime.now().isoformat(),
                "validation_version": "1.0",
            }

            result = self.db.table("events").upsert(
                data,
                on_conflict="competition_id,event_cd,sub_event_cd"
            ).execute()

            if result.data:
                return result.data[0].get("id")
            return None

        except Exception as e:
            logger.error(f"종목 upsert 오류: {e}")
            return None

    # ==================== 품질 모니터링 ====================

    async def _collect_quality_metrics(self) -> None:
        """품질 메트릭 수집 및 저장"""
        try:
            # 검증 통과율 계산
            total = self.stats["events_scraped"]
            if total > 0:
                pass_rate = self.stats["events_validated"] / total

                await self.monitor.record_metric(
                    metric_type="validation_pass_rate",
                    value=pass_rate,
                    details={
                        "total": total,
                        "passed": self.stats["events_validated"],
                        "failed": self.stats["validation_errors"],
                    }
                )

            # 저장 성공율 계산
            if self.stats["events_validated"] > 0:
                save_rate = self.stats["events_saved"] / self.stats["events_validated"]

                await self.monitor.record_metric(
                    metric_type="save_success_rate",
                    value=save_rate,
                    details={
                        "validated": self.stats["events_validated"],
                        "saved": self.stats["events_saved"],
                    }
                )

            logger.info("📊 품질 메트릭 수집 완료")

        except Exception as e:
            logger.warning(f"품질 메트릭 수집 실패: {e}")


# ==================== CLI ====================

async def main():
    import argparse

    parser = argparse.ArgumentParser(description="파이프라인 통합 스크래퍼")
    parser.add_argument("--start-year", type=int, default=2024, help="시작 연도")
    parser.add_argument("--end-year", type=int, default=2025, help="종료 연도")
    parser.add_argument("--limit", type=int, default=None, help="대회 수 제한")
    parser.add_argument("--status", type=str, default="종료", help="상태 필터")
    parser.add_argument("--headless", action="store_true", help="헤드리스 모드")

    args = parser.parse_args()

    async with PipelineScraper(headless=args.headless) as scraper:
        result = await scraper.scrape_and_save(
            start_year=args.start_year,
            end_year=args.end_year,
            limit=args.limit,
            status_filter=args.status
        )

        logger.info(f"✅ 처리 완료: {result['total_competitions']}개 대회")


if __name__ == "__main__":
    asyncio.run(main())
