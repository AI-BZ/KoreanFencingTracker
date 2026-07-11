#!/usr/bin/env python3
"""
DE (Direct Elimination) 데이터 보완 스크래퍼 - Supabase 연동 버전

기존 Supabase 데이터에서 DE 데이터가 누락된 종목만 재수집하여 업데이트
"""

import asyncio
import argparse
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from loguru import logger
from supabase import create_client, Client

# 기존 스크래퍼 import
from scraper.full_scraper import KFFFullScraper, throttle_request

# Supabase 클라이언트
def get_supabase_client() -> Client:
    """Supabase 클라이언트 생성"""
    url = os.environ.get("SUPABASE_URL", "https://tjfjuasvjzjawyckengv.supabase.co")
    key = os.environ.get("SUPABASE_KEY")
    if not key:
        # .env 파일에서 로드 시도
        from dotenv import load_dotenv
        load_dotenv()
        key = os.environ.get("SUPABASE_KEY")

    if not key:
        raise ValueError("SUPABASE_KEY 환경변수가 필요합니다")

    return create_client(url, key)


async def get_missing_de_events(supabase: Client, limit: Optional[int] = None, individual_only: bool = True) -> List[Dict[str, Any]]:
    """DE 데이터가 없는 종목 목록 조회

    Args:
        supabase: Supabase 클라이언트
        limit: 처리할 종목 수 제한
        individual_only: True면 개인전만 대상 (단체전 제외)
    """

    # 페이지네이션으로 전체 조회
    all_events = []
    page_size = 500
    offset = 0

    while True:
        result = supabase.table("events") \
            .select("id, event_cd, sub_event_cd, event_name, competition_id, raw_data") \
            .range(offset, offset + page_size - 1) \
            .execute()

        if not result.data:
            break

        # DE 데이터 없는 것만 필터
        for event in result.data:
            raw_data = event.get("raw_data") or {}
            event_name = event.get("event_name", "")

            # DE 데이터 있으면 스킵
            if raw_data.get("de_bracket"):
                continue

            # 개인전만 필터 (단체전 제외)
            if individual_only:
                # 단체전 패턴: "(단)", "단체"
                if "(단)" in event_name or "단체" in event_name:
                    continue
                # 개인전 패턴: "(개)"가 있어야 함
                if "(개)" not in event_name:
                    continue

            all_events.append(event)

        if len(result.data) < page_size:
            break
        offset += page_size

    logger.info(f"DE 누락 종목: {len(all_events)}개 (individual_only={individual_only})")

    if limit:
        all_events = all_events[:limit]
        logger.info(f"제한 적용: {len(all_events)}개")

    return all_events


async def get_competition_info(supabase: Client, comp_id: int) -> Dict[str, Any]:
    """대회 정보 조회"""
    result = supabase.table("competitions") \
        .select("*") \
        .eq("id", comp_id) \
        .single() \
        .execute()

    return result.data if result.data else {}


async def get_competition_page_map(supabase: Client) -> Dict[str, int]:
    """대회별 페이지 번호 맵 생성 (대회 목록은 최신순, 10개씩)"""
    # 모든 대회를 최신순으로 조회
    result = supabase.table("competitions") \
        .select("comp_idx") \
        .order("start_date", desc=True) \
        .execute()

    page_map = {}
    if result.data:
        for idx, comp in enumerate(result.data):
            comp_idx = comp.get("comp_idx")
            if comp_idx:
                # 10개씩 페이지네이션 (1-indexed)
                page_num = (idx // 10) + 1
                page_map[comp_idx] = page_num

    logger.info(f"대회 페이지 맵 생성: {len(page_map)}개 대회")
    return page_map


async def update_event_de_data(supabase: Client, event_id: int, de_data: Dict[str, Any]):
    """종목의 DE 데이터 업데이트"""
    # 기존 raw_data 조회
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
    raw_data["de_scraper_version"] = "v4"

    # 업데이트 실행
    supabase.table("events") \
        .update({"raw_data": raw_data, "updated_at": datetime.now().isoformat()}) \
        .eq("id", event_id) \
        .execute()


async def rescrape_de_supabase(
    limit: Optional[int] = None,
    batch_size: int = 10,
    headless: bool = True
):
    """
    Supabase에서 DE 누락 종목을 찾아 재스크래핑

    Args:
        limit: 처리할 종목 수 제한
        batch_size: 저장 배치 크기
        headless: 브라우저 헤드리스 모드
    """
    supabase = get_supabase_client()

    # 대회 페이지 맵 생성 (네비게이션용)
    page_map = await get_competition_page_map(supabase)

    # DE 누락 종목 조회 (개인전만)
    missing_events = await get_missing_de_events(supabase, limit, individual_only=True)

    if not missing_events:
        logger.info("처리할 종목이 없습니다.")
        return

    # 대회별로 그룹화 (효율적인 네비게이션을 위해)
    events_by_comp: Dict[int, List[Dict]] = {}
    for event in missing_events:
        comp_id = event["competition_id"]
        if comp_id not in events_by_comp:
            events_by_comp[comp_id] = []
        events_by_comp[comp_id].append(event)

    logger.info(f"대회 {len(events_by_comp)}개, 종목 {len(missing_events)}개 처리 예정")

    # 스크래핑 시작
    success_count = 0
    fail_count = 0

    async with KFFFullScraper(headless=headless) as scraper:
        comp_idx = 0
        total_comps = len(events_by_comp)

        for comp_id, events in events_by_comp.items():
            comp_idx += 1

            # 대회 정보 조회
            comp_info = await get_competition_info(supabase, comp_id)
            comp_name = comp_info.get("comp_name", "Unknown")
            comp_event_cd = comp_info.get("comp_idx", "")  # event_cd = comp_idx

            # 페이지 번호 계산
            page_num = page_map.get(comp_event_cd, 1)

            logger.info(f"[{comp_idx}/{total_comps}] {comp_name} (page {page_num}, {len(events)}개 종목)")

            for event in events:
                event_cd = event["event_cd"]
                sub_event_cd = event["sub_event_cd"]
                event_name = event["event_name"]
                event_id = event["id"]

                try:
                    # DE 데이터 스크래핑 (페이지 번호 전달)
                    de_data = await scraper.get_de_only(event_cd, sub_event_cd, page_num=page_num)

                    if de_data.get("de_bracket") or de_data.get("de_matches"):
                        # Supabase 업데이트
                        await update_event_de_data(supabase, event_id, de_data)

                        match_count = len(de_data.get("de_matches", []))
                        logger.info(f"  ✅ {event_name}: DE {match_count}경기")
                        success_count += 1
                    else:
                        logger.warning(f"  ⚠️ {event_name}: DE 데이터 없음")
                        fail_count += 1

                except Exception as e:
                    logger.error(f"  ❌ {event_name}: {e}")
                    fail_count += 1

                await throttle_request()

            # 진행 상황 로그
            logger.info(f"  진행: 성공 {success_count}, 실패 {fail_count}")

    logger.info(f"✅ DE 스크래핑 완료: 성공 {success_count}, 실패 {fail_count}")


async def main():
    parser = argparse.ArgumentParser(description="DE 데이터 보완 스크래퍼 (Supabase)")
    parser.add_argument("--limit", type=int, default=None,
                       help="처리할 종목 수 제한")
    parser.add_argument("--batch-size", type=int, default=10,
                       help="저장 배치 크기")
    parser.add_argument("--no-headless", action="store_true",
                       help="브라우저 표시 (디버깅용)")

    args = parser.parse_args()

    await rescrape_de_supabase(
        limit=args.limit,
        batch_size=args.batch_size,
        headless=not args.no_headless
    )


if __name__ == "__main__":
    asyncio.run(main())
