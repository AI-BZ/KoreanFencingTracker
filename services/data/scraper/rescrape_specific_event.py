#!/usr/bin/env python3
"""
특정 종목 DE 데이터 재스크래핑 스크립트

사용법:
    python scraper/rescrape_specific_event.py --event-id 131

또는 종목 코드 직접 지정:
    python scraper/rescrape_specific_event.py --event-cd COMPM00659 --sub-event-cd COMPS000000000003661
"""

import asyncio
import argparse
import os
from datetime import datetime
from typing import Dict, Any
from loguru import logger
from supabase import create_client, Client

# 기존 스크래퍼 import
from scraper.full_scraper import KFFFullScraper


def get_supabase_client() -> Client:
    """Supabase 클라이언트 생성"""
    url = os.environ.get("SUPABASE_URL", "https://tjfjuasvjzjawyckengv.supabase.co")
    key = os.environ.get("SUPABASE_KEY")
    if not key:
        from dotenv import load_dotenv
        load_dotenv()
        key = os.environ.get("SUPABASE_KEY")

    if not key:
        raise ValueError("SUPABASE_KEY 환경변수가 필요합니다")

    return create_client(url, key)


async def get_event_info(supabase: Client, event_id: int) -> Dict[str, Any]:
    """종목 정보 조회"""
    result = supabase.table("events") \
        .select("id, event_cd, sub_event_cd, event_name, competition_id, raw_data") \
        .eq("id", event_id) \
        .single() \
        .execute()

    return result.data if result.data else {}


async def get_competition_page_num(supabase: Client, comp_idx: str) -> int:
    """대회의 페이지 번호 계산"""
    result = supabase.table("competitions") \
        .select("comp_idx") \
        .order("start_date", desc=True) \
        .execute()

    if result.data:
        for idx, comp in enumerate(result.data):
            if comp.get("comp_idx") == comp_idx:
                return (idx // 10) + 1

    return 1


async def update_event_de_data(supabase: Client, event_id: int, de_data: Dict[str, Any]):
    """종목의 DE 데이터 업데이트"""
    result = supabase.table("events") \
        .select("raw_data") \
        .eq("id", event_id) \
        .single() \
        .execute()

    raw_data = result.data.get("raw_data") or {} if result.data else {}

    # DE 데이터 업데이트
    raw_data["de_bracket"] = de_data.get("de_bracket", {})
    raw_data["de_matches"] = de_data.get("de_matches", [])
    raw_data["de_updated_at"] = datetime.now().isoformat()
    raw_data["de_scraper_version"] = "v4-rescrape"

    supabase.table("events") \
        .update({"raw_data": raw_data, "updated_at": datetime.now().isoformat()}) \
        .eq("id", event_id) \
        .execute()


async def rescrape_event(
    event_id: int = None,
    event_cd: str = None,
    sub_event_cd: str = None,
    headless: bool = True
):
    """특정 종목 DE 재스크래핑"""
    supabase = get_supabase_client()

    # event_id로 정보 조회
    if event_id:
        event_info = await get_event_info(supabase, event_id)
        if not event_info:
            logger.error(f"종목 ID {event_id}를 찾을 수 없습니다")
            return

        event_cd = event_info["event_cd"]
        sub_event_cd = event_info["sub_event_cd"]
        event_name = event_info["event_name"]
        comp_id = event_info["competition_id"]

        # 대회 정보로 페이지 번호 계산
        comp_result = supabase.table("competitions") \
            .select("comp_idx, comp_name") \
            .eq("id", comp_id) \
            .single() \
            .execute()

        comp_idx = comp_result.data.get("comp_idx") if comp_result.data else ""
        comp_name = comp_result.data.get("comp_name") if comp_result.data else ""

        page_num = await get_competition_page_num(supabase, comp_idx)

        logger.info(f"대상 종목: {event_name}")
        logger.info(f"대회: {comp_name} (page {page_num})")
        logger.info(f"event_cd: {event_cd}, sub_event_cd: {sub_event_cd}")

    elif event_cd and sub_event_cd:
        # 종목 코드로 직접 지정
        page_num = 1  # 기본값
        event_name = f"{event_cd}/{sub_event_cd}"
        event_id = None
    else:
        logger.error("event_id 또는 (event_cd, sub_event_cd) 조합이 필요합니다")
        return

    # 기존 DE 데이터 확인
    if event_id:
        raw_data = event_info.get("raw_data", {})
        de_bracket = raw_data.get("de_bracket", {})
        existing_rounds = list(de_bracket.get("bouts_by_round", {}).keys())
        logger.info(f"기존 DE 라운드: {existing_rounds}")

    # 스크래핑 실행
    logger.info("스크래핑 시작...")

    async with KFFFullScraper(headless=headless) as scraper:
        try:
            de_data = await scraper.get_de_only(event_cd, sub_event_cd, page_num=page_num)

            if de_data.get("de_bracket") or de_data.get("de_matches"):
                de_bracket = de_data.get("de_bracket", {})
                new_rounds = list(de_bracket.get("bouts_by_round", {}).keys())
                match_count = len(de_data.get("de_matches", []))

                logger.info(f"수집된 DE 라운드: {new_rounds}")
                logger.info(f"수집된 경기 수: {match_count}")

                # full_bouts 확인
                full_bouts = de_bracket.get("full_bouts", [])
                logger.info(f"full_bouts 수: {len(full_bouts)}")

                if event_id:
                    # Supabase 업데이트
                    await update_event_de_data(supabase, event_id, de_data)
                    logger.info(f"✅ {event_name}: Supabase 업데이트 완료")
                else:
                    # 결과만 출력
                    logger.info(f"결과 (저장 안함): {de_data}")
            else:
                logger.warning(f"⚠️ {event_name}: DE 데이터 없음")

        except Exception as e:
            logger.error(f"❌ 스크래핑 오류: {e}")
            import traceback
            traceback.print_exc()


async def main():
    parser = argparse.ArgumentParser(description="특정 종목 DE 데이터 재스크래핑")
    parser.add_argument("--event-id", type=int, help="종목 ID (Supabase events.id)")
    parser.add_argument("--event-cd", type=str, help="대회 코드 (event_cd)")
    parser.add_argument("--sub-event-cd", type=str, help="종목 코드 (sub_event_cd)")
    parser.add_argument("--no-headless", action="store_true", help="브라우저 표시 (디버깅용)")

    args = parser.parse_args()

    await rescrape_event(
        event_id=args.event_id,
        event_cd=args.event_cd,
        sub_event_cd=args.sub_event_cd,
        headless=not args.no_headless
    )


if __name__ == "__main__":
    asyncio.run(main())
