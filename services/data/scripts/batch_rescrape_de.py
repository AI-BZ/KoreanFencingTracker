#!/usr/bin/env python3
"""
DE 데이터 품질 개선 배치 리스크래핑

DE bracket은 있지만 점수가 없는(quality < 3) 종목을 찾아 재수집.
대회별로 그룹화하여 효율적으로 처리.

사용법:
    cd services/data
    PYTHONPATH="." python scripts/batch_rescrape_de.py
    PYTHONPATH="." python scripts/batch_rescrape_de.py --limit 10 --dry-run
    PYTHONPATH="." python scripts/batch_rescrape_de.py --comp COMPM00668
    PYTHONPATH="." python scripts/batch_rescrape_de.py --comp COMPM00633 --force --update-rankings
"""

import asyncio
import argparse
import os
import sys
import time
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from loguru import logger
from supabase import create_client, Client

# 경로 설정
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper.full_scraper import KFFFullScraper, throttle_request, post_process_de_bracket
from app.bracket_utils import compute_full_final_rankings


def get_supabase_client() -> Client:
    url = os.environ.get("SUPABASE_URL", "https://tjfjuasvjzjawyckengv.supabase.co")
    key = os.environ.get("SUPABASE_KEY")
    if not key:
        from dotenv import load_dotenv
        load_dotenv()
        key = os.environ.get("SUPABASE_KEY")
    if not key:
        raise ValueError("SUPABASE_KEY 환경변수가 필요합니다")
    return create_client(url, key)


def _get_bout_player_name(bout: dict, player_key: str) -> str:
    """bout에서 선수 이름 추출 (flat/nested 형식 모두 지원)"""
    # flat: player1_name
    name = bout.get(f"{player_key}_name")
    if name:
        return name
    # nested: player1.name
    player = bout.get(player_key)
    if isinstance(player, dict):
        return player.get("name") or ""
    return ""


def has_valid_bout_content(bouts: list) -> bool:
    """bout에 실제 선수 데이터가 하나라도 있는지 확인
    모든 bout의 선수 이름이 비어있으면 False (빈 placeholder)"""
    if not bouts:
        return False
    for b in bouts:
        if _get_bout_player_name(b, "player1") or _get_bout_player_name(b, "player2"):
            return True
    return False


def has_scored_bouts(de_bracket: dict) -> bool:
    """DE bracket에 점수가 있는 경기가 있는지 확인"""
    if not de_bracket or not isinstance(de_bracket, dict):
        return False

    # dual_de 형식
    if de_bracket.get("format") == "dual_de":
        for sub_key in ["first_de", "second_de"]:
            sub = de_bracket.get(sub_key, {})
            if isinstance(sub, dict):
                bouts = sub.get("full_bouts") or sub.get("bouts") or []
                for b in bouts:
                    if (b.get("player1_score", 0) or 0) > 0 or (b.get("player2_score", 0) or 0) > 0:
                        return True
        return False

    # 일반 형식
    bouts = de_bracket.get("full_bouts") or de_bracket.get("bouts") or []
    for b in bouts:
        if (b.get("player1_score", 0) or 0) > 0 or (b.get("player2_score", 0) or 0) > 0:
            return True
    return False


def de_quality_score(de_bracket: dict) -> int:
    """DE 데이터 품질 (0=없음, 1=seeding만, 2=유효bout, 3=점수있음)"""
    if not de_bracket or not isinstance(de_bracket, dict):
        return 0
    if de_bracket.get("is_in_progress"):
        return 0

    # dual_de 형식은 서브키로 재귀
    if de_bracket.get("format") == "dual_de":
        scores = []
        for sub_key in ["first_de", "second_de"]:
            sub = de_bracket.get(sub_key, {})
            if isinstance(sub, dict):
                scores.append(de_quality_score(sub))
        return max(scores) if scores else 0

    bouts = de_bracket.get("full_bouts") or de_bracket.get("bouts") or []
    if bouts and has_scored_bouts({"bouts": bouts}):
        return 3
    if bouts and has_valid_bout_content(bouts):
        return 2  # 선수 이름이 있는 유효한 bout
    # bouts가 있어도 선수 이름이 모두 비어있으면 quality=0 (빈 placeholder)
    if de_bracket.get("seeding"):
        return 1
    return 0


async def get_low_quality_de_events(
    supabase: Client,
    target_comp: Optional[str] = None,
    limit: Optional[int] = None,
    force: bool = False
) -> List[Dict[str, Any]]:
    """DE bracket이 있는 종목 조회 (force=True면 품질 무관 전부)"""
    all_events = []
    page_size = 500
    offset = 0

    while True:
        query = supabase.table("events") \
            .select("id, event_cd, sub_event_cd, event_name, competition_id, raw_data, de_format")

        if target_comp:
            # 특정 대회만 조회 - comp_idx로 competition_id 조회 후 필터
            comp_result = supabase.table("competitions") \
                .select("id") \
                .eq("comp_idx", target_comp) \
                .execute()
            if comp_result.data:
                comp_id = comp_result.data[0]["id"]
                query = query.eq("competition_id", comp_id)
            else:
                logger.error(f"대회를 찾을 수 없음: {target_comp}")
                return []

        result = query.range(offset, offset + page_size - 1).execute()

        if not result.data:
            break

        for event in result.data:
            raw_data = event.get("raw_data") or {}
            de_bracket = raw_data.get("de_bracket", {})

            # DE bracket이 있는 경우만 대상
            if not de_bracket:
                continue

            quality = de_quality_score(de_bracket)
            if not force and quality >= 3:
                continue  # 이미 점수가 있음 (force 모드가 아닐 때만 스킵)

            # is_in_progress만 있는 빈 bracket도 대상
            all_events.append({
                **event,
                "current_quality": quality
            })

        if len(result.data) < page_size:
            break
        offset += page_size

    label = "전체 DE 종목 (force)" if force else "품질 미달 DE 종목"
    logger.info(f"{label}: {len(all_events)}개")

    if limit:
        all_events = all_events[:limit]
        logger.info(f"제한 적용: {len(all_events)}개")

    return all_events


async def get_competition_page_map(supabase: Client) -> Dict[str, int]:
    """대회별 페이지 번호 맵"""
    result = supabase.table("competitions") \
        .select("comp_idx") \
        .order("start_date", desc=True) \
        .execute()

    page_map = {}
    if result.data:
        for idx, comp in enumerate(result.data):
            comp_idx = comp.get("comp_idx")
            if comp_idx:
                page_map[comp_idx] = (idx // 10) + 1

    return page_map


async def get_competition_info_map(supabase: Client) -> Dict[int, Dict]:
    """competition_id → 정보 맵"""
    result = supabase.table("competitions") \
        .select("id, comp_idx, comp_name") \
        .execute()

    return {c["id"]: c for c in (result.data or [])}


async def update_event_de_data(supabase: Client, event_id: int, de_data: Dict, de_format: Optional[str] = None) -> bool:
    """종목 DE 데이터 업데이트 (기존 데이터 보존하면서 DE만 교체)
    Returns: True if updated, False if skipped"""
    de_bracket = de_data.get("de_bracket", {})

    # 저장 전 검증: bout이 있는데 선수 이름이 모두 비어있으면 스킵
    bouts = de_bracket.get("full_bouts") or de_bracket.get("bouts") or []
    if bouts and not has_valid_bout_content(bouts):
        logger.warning(f"  ⛔ event {event_id}: 빈 placeholder bout {len(bouts)}개 → DB 업데이트 스킵")
        return False

    result = supabase.table("events") \
        .select("raw_data") \
        .eq("id", event_id) \
        .single() \
        .execute()

    raw_data = result.data.get("raw_data") or {} if result.data else {}

    # DE 데이터만 교체
    raw_data["de_bracket"] = de_bracket
    if de_data.get("de_matches"):
        raw_data["de_matches"] = de_data["de_matches"]
    raw_data["de_updated_at"] = datetime.now().isoformat()
    raw_data["de_scraper_version"] = "v4-batch-rescrape"

    update_data = {
        "raw_data": raw_data,
        "updated_at": datetime.now().isoformat()
    }

    if de_format:
        update_data["de_format"] = de_format

    supabase.table("events") \
        .update(update_data) \
        .eq("id", event_id) \
        .execute()

    return True


async def update_final_rankings(supabase: Client, event_id: int, de_bracket: dict, raw_data: dict) -> bool:
    """DE bracket + pool_total_ranking으로 final_rankings 재계산 후 업데이트.
    새 결과가 기존보다 많을 때만 교체. Returns True if updated."""
    pool_total_ranking = raw_data.get("pool_total_ranking") or []
    existing_rankings = raw_data.get("final_rankings") or []

    # dual_de: second_de(본선)로 순위 계산, first_de 탈락자는 pool에서 추가됨
    bracket_for_ranking = de_bracket
    if de_bracket.get("format") == "dual_de" and "second_de" in de_bracket:
        bracket_for_ranking = de_bracket["second_de"]

    computed = compute_full_final_rankings(bracket_for_ranking, pool_total_ranking)
    if not computed:
        return False

    if len(computed) <= len(existing_rankings):
        logger.debug(f"  final_rankings 유지 (기존 {len(existing_rankings)}명 >= 새 {len(computed)}명)")
        return False

    raw_data["final_rankings"] = computed
    supabase.table("events") \
        .update({"raw_data": raw_data}) \
        .eq("id", event_id) \
        .execute()
    logger.info(f"  📊 final_rankings 갱신: {len(existing_rankings)}→{len(computed)}명")
    return True


async def batch_rescrape(
    limit: Optional[int] = None,
    target_comp: Optional[str] = None,
    headless: bool = True,
    dry_run: bool = False,
    force: bool = False,
    update_rankings: bool = False
):
    """배치 DE 리스크래핑 실행"""
    start_time = time.time()
    supabase = get_supabase_client()

    # 1. 대상 종목 조회
    events = await get_low_quality_de_events(supabase, target_comp, limit, force=force)
    if not events:
        logger.info("처리할 종목이 없습니다.")
        return

    # 2. 대회 정보 및 페이지 맵
    comp_info_map = await get_competition_info_map(supabase)
    page_map = await get_competition_page_map(supabase)

    # 3. 대회별 그룹화
    events_by_comp: Dict[int, List[Dict]] = {}
    for event in events:
        comp_id = event["competition_id"]
        events_by_comp.setdefault(comp_id, []).append(event)

    # 통계
    total_events = len(events)
    total_comps = len(events_by_comp)
    success_count = 0
    improved_count = 0  # 품질이 실제로 향상된 수
    rankings_count = 0  # final_rankings 갱신 수
    fail_count = 0
    skip_count = 0

    mode_label = "[FORCE] " if force else ""
    logger.info(f"{mode_label}{'[DRY RUN] ' if dry_run else ''}배치 리스크래핑 시작")
    logger.info(f"대회 {total_comps}개, 종목 {total_events}개")
    if update_rankings:
        logger.info("final_rankings 재계산 활성화")
    logger.info("=" * 60)

    if dry_run:
        # 대상 목록만 출력
        for comp_id, comp_events in events_by_comp.items():
            comp = comp_info_map.get(comp_id, {})
            comp_name = comp.get("comp_name", "Unknown")
            comp_idx = comp.get("comp_idx", "")
            page = page_map.get(comp_idx, 1)
            logger.info(f"\n[{comp_name}] (page {page}, {len(comp_events)}개)")
            for ev in comp_events:
                logger.info(f"  - {ev['event_name']} (quality={ev['current_quality']})")
        return

    # 4. 스크래핑 실행
    async with KFFFullScraper(headless=headless) as scraper:
        comp_idx_counter = 0

        for comp_id, comp_events in events_by_comp.items():
            comp_idx_counter += 1
            comp = comp_info_map.get(comp_id, {})
            comp_name = comp.get("comp_name", "Unknown")
            comp_idx = comp.get("comp_idx", "")
            page_num = page_map.get(comp_idx, 1)

            logger.info(f"\n[{comp_idx_counter}/{total_comps}] {comp_name} "
                        f"(page {page_num}, {len(comp_events)}개)")

            for event in comp_events:
                event_cd = event["event_cd"]
                sub_event_cd = event["sub_event_cd"]
                event_name = event["event_name"]
                event_id = event["id"]
                old_quality = event["current_quality"]

                try:
                    # DE 전용 스크래핑 시도
                    de_data = await scraper.get_de_only(event_cd, sub_event_cd, page_num=page_num)

                    de_bracket = de_data.get("de_bracket", {})
                    new_quality = de_quality_score(de_bracket)
                    is_structured_dual = de_bracket.get("format") == "dual_de"
                    de_format = "dual_de" if is_structured_dual else None

                    should_update = False
                    update_reason = ""

                    if force and is_structured_dual:
                        # force 모드: flat→structured 변환이 목적이므로 무조건 업데이트
                        should_update = True
                        update_reason = "force+dual_de"
                    elif new_quality > old_quality:
                        should_update = True
                        update_reason = "품질향상"
                    elif new_quality == old_quality and new_quality > 0:
                        should_update = True
                        update_reason = "갱신"
                    elif new_quality == 0:
                        logger.warning(f"  ⚠️ {event_name}: DE 데이터 없음 (q{old_quality}→q0, 보존)")
                        skip_count += 1
                    else:
                        logger.warning(f"  ⚠️ {event_name}: 품질 하락 (q{old_quality}→q{new_quality}, 보존)")
                        skip_count += 1

                    if should_update:
                        updated = await update_event_de_data(supabase, event_id, de_data, de_format)
                        if updated:
                            full_bouts = de_bracket.get("full_bouts") or de_bracket.get("bouts") or []
                            if is_structured_dual:
                                # dual_de의 경우 서브키에서 bout 수 합산
                                bout_count = 0
                                for sk in ["first_de", "second_de"]:
                                    sub = de_bracket.get(sk, {})
                                    if isinstance(sub, dict):
                                        bout_count += len(sub.get("full_bouts") or sub.get("bouts") or [])
                            else:
                                bout_count = len(full_bouts)
                            logger.info(f"  ✅ {event_name}: q{old_quality}→q{new_quality} "
                                        f"({bout_count} bouts, {update_reason})"
                                        f"{' [dual_de]' if is_structured_dual else ''}")
                            if new_quality > old_quality:
                                improved_count += 1
                            success_count += 1

                            # final_rankings 재계산
                            if update_rankings:
                                # 최신 raw_data 다시 조회 (update_event_de_data가 수정했으므로)
                                fresh = supabase.table("events") \
                                    .select("raw_data") \
                                    .eq("id", event_id) \
                                    .single() \
                                    .execute()
                                fresh_raw = fresh.data.get("raw_data", {}) if fresh.data else {}
                                if await update_final_rankings(supabase, event_id, de_bracket, fresh_raw):
                                    rankings_count += 1
                        else:
                            skip_count += 1

                except Exception as e:
                    logger.error(f"  ❌ {event_name}: {e}")
                    fail_count += 1

                await throttle_request()

            # 대회별 진행 상황
            processed = success_count + fail_count + skip_count
            logger.info(f"  진행: {processed}/{total_events} "
                        f"(성공:{success_count} 향상:{improved_count} "
                        f"실패:{fail_count} 보존:{skip_count})")

    # 5. 최종 결과
    elapsed = int(time.time() - start_time)
    logger.info("\n" + "=" * 60)
    logger.info(f"배치 리스크래핑 완료 ({elapsed}초)")
    logger.info(f"  성공: {success_count}/{total_events}")
    logger.info(f"  향상: {improved_count}")
    if update_rankings:
        logger.info(f"  순위갱신: {rankings_count}")
    logger.info(f"  실패: {fail_count}")
    logger.info(f"  보존: {skip_count}")


async def main():
    parser = argparse.ArgumentParser(description="DE 데이터 품질 개선 배치 리스크래핑")
    parser.add_argument("--limit", type=int, default=None, help="처리할 종목 수 제한")
    parser.add_argument("--comp", type=str, default=None, help="특정 대회만 (예: COMPM00668)")
    parser.add_argument("--no-headless", action="store_true", help="브라우저 표시")
    parser.add_argument("--dry-run", action="store_true", help="실행 없이 대상 목록만 출력")
    parser.add_argument("--force", action="store_true",
                        help="품질 무관 전체 리스크래핑 (flat→structured 변환용)")
    parser.add_argument("--update-rankings", action="store_true",
                        help="리스크래핑 후 final_rankings 재계산")

    args = parser.parse_args()

    # 로그 설정
    logger.remove()
    logger.add(sys.stderr, level="INFO",
               format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>")
    logger.add(f"logs/batch_rescrape_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
               level="DEBUG", rotation="50 MB")

    await batch_rescrape(
        limit=args.limit,
        target_comp=args.comp,
        headless=not args.no_headless,
        dry_run=args.dry_run,
        force=args.force,
        update_rankings=args.update_rankings
    )


if __name__ == "__main__":
    asyncio.run(main())
