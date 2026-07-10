"""
COMPM00691 pool_total_ranking 중복 수정 스크립트

문제: pool_total_ranking에 동일 선수가 2번씩 등장 (진출+탈락 동일 테이블 재스크래핑)
해결: pool_rounds에서 자체 계산한 결과로 교체
"""
import os
import sys

# 프로젝트 루트를 PYTHONPATH에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
from app.pool_calculator import calculate_pool_total_ranking, enrich_with_advancement_status
from loguru import logger


def fix_pool_ranking_duplicates(comp_id: str = "COMPM00691", dry_run: bool = True):
    """pool_total_ranking 중복을 자체 계산 결과로 교체"""
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    db = create_client(url, key)

    # 해당 대회의 competition id 조회
    comp_result = db.table("competitions").select("id").eq("comp_idx", comp_id).execute()
    if not comp_result.data:
        logger.error(f"대회 {comp_id} 찾을 수 없음")
        return

    db_comp_id = comp_result.data[0]["id"]
    logger.info(f"대회: {comp_id} (DB id: {db_comp_id})")

    # 해당 대회의 모든 이벤트 조회
    events_result = db.table("events").select(
        "id, event_name, sub_event_cd, raw_data"
    ).eq("competition_id", db_comp_id).execute()

    if not events_result.data:
        logger.warning("이벤트 없음")
        return

    fixed = 0
    for event in events_result.data:
        raw = event.get("raw_data") or {}
        pool_ranking = raw.get("pool_total_ranking", [])
        pool_rounds = raw.get("pool_rounds", [])
        event_name = event["event_name"]

        if not pool_ranking:
            continue

        # 중복 확인: 이름 기준 unique vs total
        names = [r.get("name", "") for r in pool_ranking]
        unique_names = set(names)

        if len(names) == len(unique_names):
            logger.info(f"  ✅ {event_name}: {len(names)}명 (중복 없음)")
            continue

        logger.warning(
            f"  ⚠️ {event_name}: {len(names)}명 중 unique {len(unique_names)}명 "
            f"(중복 {len(names) - len(unique_names)}명)"
        )

        if not pool_rounds:
            logger.warning("    pool_rounds 없음 → 이름 기반 중복 제거")
            # pool_rounds 없으면 이름 기반으로 중복 제거 (첫 번째 것 유지)
            seen = set()
            deduped = []
            for r in pool_ranking:
                name = r.get("name", "")
                if name not in seen:
                    seen.add(name)
                    deduped.append(r)
            new_ranking = deduped
        else:
            # pool_rounds에서 자체 계산
            calculated = calculate_pool_total_ranking(pool_rounds)
            if calculated:
                # 기존 진출 상태 정보 병합
                calculated = enrich_with_advancement_status(calculated, pool_ranking)
                new_ranking = calculated
                logger.info(f"    자체 계산: {len(calculated)}명")
            else:
                logger.warning("    자체 계산 실패 → 이름 기반 중복 제거")
                seen = set()
                deduped = []
                for r in pool_ranking:
                    name = r.get("name", "")
                    if name not in seen:
                        seen.add(name)
                        deduped.append(r)
                new_ranking = deduped

        if dry_run:
            logger.info(f"    [DRY RUN] {len(pool_ranking)}명 → {len(new_ranking)}명으로 교체 예정")
        else:
            raw["pool_total_ranking"] = new_ranking
            db.table("events").update({"raw_data": raw}).eq("id", event["id"]).execute()
            logger.info(f"    ✅ 수정 완료: {len(pool_ranking)}명 → {len(new_ranking)}명")
            fixed += 1

    if dry_run:
        logger.info(f"\n[DRY RUN] 수정 대상: {fixed}건 이상. --apply 플래그로 실행하세요.")
    else:
        logger.info(f"\n총 {fixed}건 수정 완료")


if __name__ == "__main__":
    dry_run = "--apply" not in sys.argv
    comp_id = "COMPM00691"

    # --comp 인자로 대회 지정 가능
    for i, arg in enumerate(sys.argv):
        if arg == "--comp" and i + 1 < len(sys.argv):
            comp_id = sys.argv[i + 1]

    if dry_run:
        logger.info("🔍 DRY RUN 모드 (실제 수정 안 함). --apply로 실행하세요.")
    else:
        logger.info("🔧 APPLY 모드 (실제 DB 수정)")

    fix_pool_ranking_duplicates(comp_id=comp_id, dry_run=dry_run)
