#!/usr/bin/env python3
"""
DE 데이터 품질 개선 배치 리스크래핑

DE bracket은 있지만 점수가 없는(quality < 3) 종목을 찾아 재수집.
대회별로 그룹화하여 효율적으로 처리.

저장 조건은 **내용 기반**이다 (`de_replacement_verdict`). 개수나 품질 점수로 재면
부분 유실을 못 잡고(2026-08-18: 159→127경기 덮어쓰기), 반대로 팬텀 항목이 섞인
레코드는 올바른 재수집을 영구히 거부한다(2026-08-19: 단체전 2종목 SKIP).

사용법:
    cd services/data
    PYTHONPATH="." python scripts/batch_rescrape_de.py
    PYTHONPATH="." python scripts/batch_rescrape_de.py --limit 10 --dry-run
    PYTHONPATH="." python scripts/batch_rescrape_de.py --comp COMPM00668
    PYTHONPATH="." python scripts/batch_rescrape_de.py --comp COMPM00633 --force --update-rankings

    # 팬텀 부전승 정리 (구 파서가 참가자 컬럼을 부전승으로 오파싱한 레코드)
    PYTHONPATH="." python scripts/batch_rescrape_de.py --phantom --dry-run
    PYTHONPATH="." python scripts/batch_rescrape_de.py --phantom --backup /path/backup.json
    PYTHONPATH="." python scripts/batch_rescrape_de.py --phantom --only-ids 321,2912 --backup ...
"""

import asyncio
import argparse
import json
import os
import sys
import time
from datetime import datetime
from typing import List, Dict, Any, Optional
from loguru import logger
from supabase import create_client, Client

# 경로 설정
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper.full_scraper import KFFFullScraper, throttle_request
from app.bracket_utils import compute_full_final_rankings, is_bye_bout


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


def iter_all_bouts(de_bracket: dict):
    """de_bracket 안의 모든 bout 을 (bout, 위상) 으로 훑는다. dual/single 양쪽 지원."""
    if not de_bracket or not isinstance(de_bracket, dict):
        return
    if de_bracket.get("format") == "dual_de":
        seen_sub = False
        for sub_key, phase in (("first_de", "qualifying"), ("second_de", "main")):
            sub = de_bracket.get(sub_key) or {}
            if isinstance(sub, dict):
                for b in (sub.get("full_bouts") or sub.get("bouts") or []):
                    seen_sub = True
                    yield b, (b.get("de_phase") or phase)
        if seen_sub:
            return
        # 하위 브래킷이 비어 있고 top-level 에만 있는 저장 형태
    for b in (de_bracket.get("full_bouts") or de_bracket.get("bouts") or []):
        yield b, (b.get("de_phase") or "main")


def real_bout_identities(de_bracket: dict) -> set:
    """**실제 대결**의 신원 집합 = {(위상, {선수1, 선수2})}.

    저장 조건을 개수가 아니라 이 집합으로 재는 이유 (2026-08-19):

    구 파서가 브래킷의 참가자 표시 컬럼을 부전승 경기로 오파싱해, 참가 팀 수만큼
    **팬텀 항목**을 남긴 레코드가 77종목 635건 있다(bout_id 가 `..._bye_NN`, 한쪽
    이름만 있고 점수·결과 없음). 개수로 비교하면 재수집한 올바른 데이터가
    "새 15 < 기존 30" 으로 판정돼 영구히 거부된다 — 실제로 2건이 그렇게 SKIP 됐다.

    부전승은 경기가 아니므로(슬롯 수 ≠ 경기 수, `is_bye_bout()`) 신원에서 뺀다.
    라운드명도 신원에서 뺀다 — 같은 구 파서가 8팀/16팀 브래킷의 첫 라운드를 '32강'
    으로 잘못 적어 뒀고, 재수집은 이것을 '8강'/'16강' 으로 교정하기 때문이다.
    위상은 남긴다: Dual DE 의 예선 64강과 본선 64강은 서로 다른 경기다.
    """
    identities = set()
    for b, phase in iter_all_bouts(de_bracket):
        if is_bye_bout(b):
            continue
        p1 = (b.get("player1_name") or "").strip()
        p2 = (b.get("player2_name") or "").strip()
        if not (p1 and p2):
            continue
        identities.add((phase, frozenset({p1, p2})))
    return identities


def team_contamination(de_bracket: dict) -> int:
    """소속 칸에 '기권' 문구가 새어 들어간 bout 수.

    KFA 는 첫 라운드 이후 소속 칸에 '직전 경기 결과'를 넣는다. 구 파서가 그 문구를
    소속으로 인정해 `박지희의기권` 같은 값이 저장됐다(2026-08-18, 343건/27대회).
    """
    n = 0
    for b, _phase in iter_all_bouts(de_bracket):
        for i in (1, 2):
            if "기권" in (b.get(f"player{i}_team") or ""):
                n += 1
    return n


def phase_coverage(de_bracket: dict) -> tuple:
    """(위상이 붙은 bout 수, 전체 bout 수). dual DE 는 전부 붙어 있어야 한다."""
    total = tagged = 0
    for b, _phase in iter_all_bouts(de_bracket):
        total += 1
        if b.get("de_phase"):
            tagged += 1
    return tagged, total


def de_replacement_verdict(new_de: dict, existing_de: dict) -> tuple:
    """새 DE 로 교체해도 되는가? → (ok: bool, 사유: str)

    세 조건을 모두 만족해야 저장한다:
      1) 기존의 **실제 대결**이 하나도 사라지지 않을 것 (팬텀·부전승·라운드명 무관)
      2) 소속에 '기권' 오염이 없을 것
      3) dual DE 면 모든 bout 에 de_phase 가 있을 것
    """
    old_ids = real_bout_identities(existing_de)
    new_ids = real_bout_identities(new_de)
    lost = old_ids - new_ids
    if lost:
        sample = ", ".join(" vs ".join(sorted(pair)) for _phase, pair in list(lost)[:3])
        return False, (f"실제 대결 유실 {len(lost)}건 "
                       f"(기존 {len(old_ids)} → 새 {len(new_ids)}): {sample}")

    cont = team_contamination(new_de)
    if cont:
        return False, f"소속 '기권' 오염 {cont}건"

    if new_de.get("format") == "dual_de":
        tagged, total = phase_coverage(new_de)
        if tagged != total:
            return False, f"de_phase 누락 {total - tagged}/{total}"

    gained = len(new_ids) - len(old_ids)
    return True, (f"실제 대결 {len(old_ids)}→{len(new_ids)}"
                  + (f" (+{gained})" if gained > 0 else ""))


async def get_phantom_bye_events(
    supabase: Client,
    target_comp: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """팬텀 부전승(`bout_id` 에 `_bye_`)이 섞인 종목 조회.

    구 파서가 참가자 표시 컬럼을 부전승 경기로 오파싱한 레코드다. 이 종목들은
    `starting_round`/`bracket_size`/첫 라운드 라벨까지 함께 틀려 있어서 팬텀만
    지워서는 고쳐지지 않는다 — 재수집이 셋을 한 번에 교정한다.
    """
    events, offset, page_size = [], 0, 500
    comp_id = None
    if target_comp:
        comp_result = supabase.table("competitions").select("id").eq("comp_idx", target_comp).execute()
        if not comp_result.data:
            logger.error(f"대회를 찾을 수 없음: {target_comp}")
            return []
        comp_id = comp_result.data[0]["id"]

    while True:
        query = supabase.table("events") \
            .select("id, event_cd, sub_event_cd, event_name, competition_id, raw_data, de_format")
        if comp_id is not None:
            query = query.eq("competition_id", comp_id)
        result = query.range(offset, offset + page_size - 1).execute()
        if not result.data:
            break

        for event in result.data:
            de_bracket = (event.get("raw_data") or {}).get("de_bracket") or {}
            bouts = de_bracket.get("full_bouts") or de_bracket.get("bouts") or []
            phantom = sum(1 for b in bouts if "_bye_" in (b.get("bout_id") or ""))
            if not phantom:
                continue
            events.append({
                **event,
                "current_quality": de_quality_score(de_bracket),
                "phantom_bouts": phantom,
                "real_bouts": len(real_bout_identities(de_bracket)),
            })

        if len(result.data) < page_size:
            break
        offset += page_size

    logger.info(f"팬텀 부전승 보유 종목: {len(events)}개 "
                f"(팬텀 {sum(e['phantom_bouts'] for e in events)}건)")
    if limit:
        events = events[:limit]
        logger.info(f"제한 적용: {len(events)}개")
    return events


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
    update_rankings: bool = False,
    phantom: bool = False,
    backup_path: Optional[str] = None,
    only_ids: Optional[List[int]] = None
):
    """배치 DE 리스크래핑 실행"""
    start_time = time.time()
    supabase = get_supabase_client()

    # 1. 대상 종목 조회
    if phantom:
        events = await get_phantom_bye_events(supabase, target_comp, limit)
    else:
        events = await get_low_quality_de_events(supabase, target_comp, limit, force=force)
    if only_ids:
        wanted = set(only_ids)
        events = [e for e in events if e["id"] in wanted]
        logger.info(f"--only-ids 필터: {len(events)}개")
    if not events:
        logger.info("처리할 종목이 없습니다.")
        return

    # 1b. 교체 전 백업 — 되돌릴 수 없는 저장을 하기 전에 원본을 남긴다
    if backup_path and not dry_run:
        snapshot = {}
        for ev in events:
            snapshot[str(ev["id"])] = {
                "id": ev["id"],
                "sub_event_cd": ev.get("sub_event_cd"),
                "event_name": ev.get("event_name"),
                "de_bracket": (ev.get("raw_data") or {}).get("de_bracket"),
            }
        with open(backup_path, "w") as f:
            json.dump(snapshot, f, ensure_ascii=False)
        logger.info(f"백업 {len(snapshot)}종목 → {backup_path}")

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

                    # 내용 기반 저장 조건이 최우선이다. 품질 점수(0~3)는 '점수 있는 경기가
                    # 하나라도 있으면 3'에서 천장을 쳐서 부분 유실을 못 잡는다 —
                    # 2026-08-18 에 159경기가 127경기로 덮어써진 직접 원인이다.
                    existing_de = (event.get("raw_data") or {}).get("de_bracket") or {}
                    if new_quality == 0:
                        logger.warning(f"  ⚠️ {event_name}: DE 데이터 없음 (q{old_quality}→q0, 보존)")
                        skip_count += 1
                    else:
                        ok, verdict = de_replacement_verdict(de_bracket, existing_de)
                        if ok:
                            should_update = True
                            update_reason = verdict
                        else:
                            logger.warning(f"  ⛔ {event_name}: 교체 거부 — {verdict}")
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
    parser.add_argument("--phantom", action="store_true",
                        help="팬텀 부전승(bout_id 에 _bye_)이 섞인 종목만 대상")
    parser.add_argument("--backup", type=str, default=None,
                        help="교체 전 대상 종목의 de_bracket 을 이 경로에 JSON 백업")
    parser.add_argument("--only-ids", type=str, default=None,
                        help="쉼표로 구분한 event id 만 처리 (예: 321,2912)")
    parser.add_argument("--log-dir", type=str, default="logs",
                        help="로그 디렉토리")

    args = parser.parse_args()

    # 로그 설정
    logger.remove()
    logger.add(sys.stderr, level="INFO",
               format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>")
    os.makedirs(args.log_dir, exist_ok=True)
    logger.add(os.path.join(args.log_dir,
                            f"batch_rescrape_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
               level="DEBUG", rotation="50 MB")

    only_ids = None
    if args.only_ids:
        only_ids = [int(x) for x in args.only_ids.split(",") if x.strip()]

    await batch_rescrape(
        limit=args.limit,
        target_comp=args.comp,
        headless=not args.no_headless,
        dry_run=args.dry_run,
        force=args.force,
        update_rankings=args.update_rankings,
        phantom=args.phantom,
        backup_path=args.backup,
        only_ids=only_ids
    )


if __name__ == "__main__":
    asyncio.run(main())
