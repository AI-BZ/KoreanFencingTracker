#!/usr/bin/env python3
"""
DE (Direct Elimination) 데이터 보완 스크래퍼

기존 JSON 데이터에서 DE 데이터가 누락된 종목만 재수집
"""

import asyncio
import json
import argparse
from datetime import datetime
from pathlib import Path
from loguru import logger

# 기존 스크래퍼 import
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper.full_scraper import KFFFullScraper, throttle_request


async def rescrape_de_only(
    input_file: str = "data/fencing_full_data_v2.json",
    output_file: str = None,
    limit: int = None,
    start_idx: int = 0
):
    """
    DE 데이터만 보완 스크래핑

    Args:
        input_file: 기존 데이터 파일
        output_file: 출력 파일 (None이면 입력 파일 덮어쓰기)
        limit: 처리할 대회 수 제한
        start_idx: 시작할 대회 인덱스 (0-based)
    """
    if output_file is None:
        output_file = input_file

    # 기존 데이터 로드
    logger.info(f"기존 데이터 로드: {input_file}")
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    competitions = data.get("competitions", [])
    total = len(competitions)

    # DE 데이터 누락된 대회 찾기
    need_de = []
    for i, comp in enumerate(competitions):
        events = comp.get("events", [])
        if not events:
            continue  # 종목 데이터 없는 대회는 전체 재스크래핑 필요

        # DE 데이터 확인
        has_de = False
        for event in events:
            de_matches = event.get("de_matches", [])
            match_results = event.get("de_bracket", {}).get("match_results", [])
            if de_matches or match_results:
                has_de = True
                break

        if not has_de:
            need_de.append(i)

    logger.info(f"DE 데이터 누락 대회: {len(need_de)}개 / 전체 {total}개")

    # 시작 인덱스 적용
    need_de = [i for i in need_de if i >= start_idx]

    # 제한 적용
    if limit:
        need_de = need_de[:limit]

    logger.info(f"처리 대상: {len(need_de)}개 대회 (시작: {start_idx})")

    if not need_de:
        logger.info("처리할 대회가 없습니다.")
        return

    async with KFFFullScraper(headless=True) as scraper:
        for idx, comp_idx in enumerate(need_de):
            comp = competitions[comp_idx]
            comp_info = comp.get("competition", {})
            comp_name = comp_info.get("name", "Unknown")
            event_cd = comp_info.get("event_cd", "")

            logger.info(f"[{idx+1}/{len(need_de)}] [{comp_idx+1}] {comp_name}")

            events = comp.get("events", [])
            updated = 0

            # 페이지 번호 계산 (대회 목록은 10개씩 페이지네이션)
            page_num = (comp_idx // 10) + 1

            for event in events:
                sub_event_cd = event.get("sub_event_cd", "")
                event_name = event.get("name", "Unknown")

                try:
                    # DE 데이터만 수집
                    de_data = await scraper.get_de_only(event_cd, sub_event_cd, page_num=page_num)

                    if de_data.get("de_matches") or de_data.get("de_bracket", {}).get("match_results"):
                        event["de_bracket"] = de_data.get("de_bracket", {})
                        event["de_matches"] = de_data.get("de_matches", [])
                        updated += 1
                        logger.debug(f"  ✅ {event_name}: DE {len(de_data.get('de_matches', []))}개")

                except Exception as e:
                    logger.error(f"  ❌ {event_name}: {e}")

                await throttle_request()

            logger.info(f"  업데이트: {updated}/{len(events)} 종목")

            # 중간 저장
            if (idx + 1) % 3 == 0:
                data["meta"]["updated_at"] = datetime.now().isoformat()
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2, default=str)
                logger.info(f"  💾 중간 저장: {output_file}")

    # 최종 저장
    data["meta"]["updated_at"] = datetime.now().isoformat()
    data["meta"]["de_rescrape_completed"] = datetime.now().isoformat()

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    logger.info(f"✅ DE 보완 완료: {output_file}")


async def rescrape_full_missing(
    input_file: str = "data/fencing_full_data_v2.json",
    output_file: str = None,
    limit: int = None
):
    """
    종목 데이터가 없는 대회 전체 재스크래핑
    """
    if output_file is None:
        output_file = input_file

    logger.info(f"기존 데이터 로드: {input_file}")
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    competitions = data.get("competitions", [])

    # 종목 데이터 없는 대회 찾기
    need_full = []
    for i, comp in enumerate(competitions):
        events = comp.get("events", [])
        if not events:
            need_full.append(i)

    logger.info(f"종목 데이터 누락 대회: {len(need_full)}개")

    if limit:
        need_full = need_full[:limit]

    if not need_full:
        logger.info("처리할 대회가 없습니다.")
        return

    async with KFFFullScraper(headless=True) as scraper:
        for idx, comp_idx in enumerate(need_full):
            comp = competitions[comp_idx]
            comp_info = comp.get("competition", {})

            # Competition 객체 재구성
            from scraper.full_scraper import Competition
            comp_obj = Competition(
                event_cd=comp_info.get("event_cd", ""),
                name=comp_info.get("name", ""),
                start_date=comp_info.get("start_date", ""),
                end_date=comp_info.get("end_date", ""),
                location=comp_info.get("location", ""),
                host=comp_info.get("host", ""),
                status=comp_info.get("status", "종료")
            )

            logger.info(f"[{idx+1}/{len(need_full)}] [{comp_idx+1}] {comp_obj.name}")

            try:
                # 전체 데이터 재수집
                page_num = (comp_idx // 10) + 1
                comp_data = await scraper.scrape_competition_full(comp_obj, page_num=page_num)

                # 기존 데이터 업데이트
                competitions[comp_idx] = comp_data

                logger.info(f"  ✅ {len(comp_data.get('events', []))}개 종목 수집")

            except Exception as e:
                logger.error(f"  ❌ 실패: {e}")

            # 중간 저장
            if (idx + 1) % 3 == 0:
                data["meta"]["updated_at"] = datetime.now().isoformat()
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2, default=str)
                logger.info("  💾 중간 저장")

            await throttle_request()

    # 최종 저장
    data["meta"]["updated_at"] = datetime.now().isoformat()

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    logger.info(f"✅ 전체 재스크래핑 완료: {output_file}")


async def main():
    parser = argparse.ArgumentParser(description="DE 데이터 보완 스크래퍼")
    parser.add_argument("--mode", choices=["de", "full", "both"], default="de",
                       help="de: DE만 보완, full: 누락된 대회 전체 재수집, both: 둘 다")
    parser.add_argument("--input", type=str, default="data/fencing_full_data_v2.json",
                       help="입력 파일")
    parser.add_argument("--output", type=str, default=None,
                       help="출력 파일 (기본: 입력 파일 덮어쓰기)")
    parser.add_argument("--limit", type=int, default=None,
                       help="처리할 대회 수 제한")
    parser.add_argument("--start", type=int, default=0,
                       help="시작할 대회 인덱스 (0-based)")

    args = parser.parse_args()

    if args.mode in ["de", "both"]:
        await rescrape_de_only(
            input_file=args.input,
            output_file=args.output,
            limit=args.limit,
            start_idx=args.start
        )

    if args.mode in ["full", "both"]:
        await rescrape_full_missing(
            input_file=args.input,
            output_file=args.output,
            limit=args.limit
        )


if __name__ == "__main__":
    asyncio.run(main())
