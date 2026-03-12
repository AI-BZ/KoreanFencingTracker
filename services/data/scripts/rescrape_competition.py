"""
특정 대회 재스크래핑 스크립트

사용법:
    cd services/data
    python scripts/rescrape_competition.py COMPM00679
"""
import asyncio
import sys
import json
from datetime import datetime

# 경로 설정 (중요: 순서대로!)
PROJECT_ROOT = '/Users/gyejinpark/Documents/GitHub/FencingMind-data'
sys.path.insert(0, f'{PROJECT_ROOT}/services/data')
sys.path.insert(0, PROJECT_ROOT)

from loguru import logger
from scraper.full_scraper import KFFFullScraper, Competition
from database.supabase_client import get_supabase_client

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>")


async def rescrape_competition(comp_idx: str):
    """특정 대회 재스크래핑 및 DB 업데이트"""

    logger.info(f"🔄 대회 재스크래핑 시작: {comp_idx}")

    # headful 모드로 실행 (더 안정적)
    async with KFFFullScraper(headless=False) as scraper:
        # 1. 대회 목록에서 해당 대회 찾기
        logger.info("대회 목록 조회 중...")
        competitions = await scraper.get_all_competitions(start_year=2024, end_year=2026)

        target_comp = None
        for comp in competitions:
            # full_scraper의 Competition은 event_cd 속성 사용
            if comp.event_cd == comp_idx:
                target_comp = comp
                break

        if not target_comp:
            logger.error(f"대회를 찾을 수 없음: {comp_idx}")
            return None

        logger.info(f"📋 대회 발견: {target_comp.name}")

        # 2. 대회 전체 스크래핑
        logger.info("종목 및 결과 스크래핑 중...")
        result = await scraper.scrape_competition_full(target_comp)

        if not result:
            logger.error("스크래핑 실패")
            return None

        # 3. 결과 요약 출력
        events = result.get("events", [])
        logger.info(f"✅ 스크래핑 완료: {len(events)}개 종목")

        for event in events:
            event_name = event.get("event_name", "")
            de_bracket = event.get("de_bracket", {})
            full_bouts = de_bracket.get("full_bouts", [])

            # 기권 경기 확인
            forfeit_count = sum(1 for fb in full_bouts if fb.get("is_forfeit"))

            logger.info(f"  - {event_name}: DE {len(full_bouts)}경기 (기권: {forfeit_count})")

        # 4. DB 업데이트
        logger.info("DB 업데이트 중...")
        supabase = get_supabase_client()

        # 기존 대회 데이터 삭제 후 재삽입
        # competitions 테이블
        comp_data = {
            "comp_idx": result.get("comp_idx"),
            "comp_name": result.get("comp_name"),
            "start_date": result.get("start_date"),
            "end_date": result.get("end_date"),
            "venue": result.get("venue"),
            "status": result.get("status"),
            "raw_data": result,
            "updated_at": datetime.now().isoformat()
        }

        # upsert
        try:
            supabase.table("competitions").upsert(
                comp_data,
                on_conflict="comp_idx"
            ).execute()
            logger.info(f"✅ competitions 테이블 업데이트 완료")
        except Exception as e:
            logger.error(f"competitions 업데이트 실패: {e}")

        # events 테이블
        for event in events:
            try:
                # competition_id 조회
                comp_result = supabase.table("competitions").select("id").eq("comp_idx", comp_idx).execute()
                if comp_result.data:
                    comp_id = comp_result.data[0]["id"]

                    event_data = {
                        "competition_id": comp_id,
                        "sub_event_cd": event.get("sub_event_cd"),
                        "event_name": event.get("event_name"),
                        "raw_data": event,
                        "updated_at": datetime.now().isoformat()
                    }

                    supabase.table("events").upsert(
                        event_data,
                        on_conflict="sub_event_cd"
                    ).execute()
            except Exception as e:
                logger.error(f"events 업데이트 실패 ({event.get('event_name')}): {e}")

        logger.info(f"✅ events 테이블 업데이트 완료")

        return result


async def main():
    if len(sys.argv) < 2:
        print("사용법: python scripts/rescrape_competition.py COMPM00679")
        return

    comp_idx = sys.argv[1]
    result = await rescrape_competition(comp_idx)

    if result:
        # 결과 파일 저장 (디버깅용)
        output_file = f"data/rescrape_{comp_idx}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"📁 결과 저장: {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
