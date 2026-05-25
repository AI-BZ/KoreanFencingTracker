"""
DE 대진표에서 순위 추정 스크립트

진행 중인 대회의 DE 결과를 기반으로 final_rankings를 추정한다.
- 완료된 경기: 점수로 승패 판정 → 패자에게 해당 라운드 순위 부여
- 미완료 경기(0:0): 해당 라운드 진출자들에게 시드 순으로 순위 배정
- Pool 전용 참가자: DE 참가자 뒤에 pool 순위로 배치

사용법:
    PYTHONPATH="." python scripts/estimate_de_rankings.py --comp COMPM00691
    PYTHONPATH="." python scripts/estimate_de_rankings.py --comp COMPM00691 --dry-run
    PYTHONPATH="." python scripts/estimate_de_rankings.py --comp COMPM00691 --event-id 5824
"""
import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from loguru import logger
from supabase import create_client

load_dotenv()

logger.remove()
logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | {message}")

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# 라운드 → 순위 매핑 (해당 라운드에서 탈락 시 부여되는 순위)
# 펜싱 표준: 같은 라운드 탈락자는 동일 순위
ROUND_TO_RANK = {
    "결승": 2,       # 결승 패자 = 2위
    "준결승": 3,     # 4강 패자 = T3
    "8강": 5,        # 8강 패자 = T5
    "16강": 9,       # 16강 패자 = T9
    "32강": 17,      # 32강 패자 = T17
    "64강": 33,      # 64강 패자 = T33
    "128강": 65,     # 128강 패자 = T65
    "256강": 129,    # 256강 패자 = T129
}

# 라운드 순서 (결승이 마지막)
ROUND_ORDER = ["256강", "128강", "64강", "32강", "16강", "8강", "준결승", "결승"]


def determine_bout_winner(bout: Dict) -> Optional[str]:
    """경기 승자 판정. 반환값: 'player1', 'player2', None(미결정)"""
    # 이미 승자가 설정된 경우
    winner_name = (bout.get("winner_name") or "").strip()
    p1_name = (bout.get("player1_name") or "").strip()
    p2_name = (bout.get("player2_name") or "").strip()

    if winner_name:
        if winner_name == p1_name:
            return "player1"
        elif winner_name == p2_name:
            return "player2"

    # 바이인 경우
    if bout.get("is_bye"):
        if p1_name and not p2_name:
            return "player1"
        elif p2_name and not p1_name:
            return "player2"
        return None

    # 점수로 판정
    try:
        s1 = int(bout.get("player1_score", 0) or 0)
        s2 = int(bout.get("player2_score", 0) or 0)
    except (ValueError, TypeError):
        return None

    if s1 == 0 and s2 == 0:
        return None  # 미진행

    if s1 > s2:
        return "player1"
    elif s2 > s1:
        return "player2"

    return None  # 동점 (이론상 DE에서 불가하지만 안전장치)


def estimate_rankings_from_bracket(de_bracket: Dict, pool_total_ranking: Optional[List] = None) -> List[Dict]:
    """DE 대진표에서 순위 추정

    Returns:
        [{name, rank, team, estimated: True}, ...]
    """
    full_bouts = de_bracket.get("full_bouts", [])
    seeding = de_bracket.get("seeding", [])
    bracket_size = int(de_bracket.get("bracket_size", 0))
    rounds = de_bracket.get("rounds", [])

    if not full_bouts or not seeding:
        return []

    # 시드 맵: name → {seed, team}
    seed_map = {}
    for s in seeding:
        name = (s.get("name") or "").strip()
        if name and not s.get("is_bye"):
            seed_map[name] = {
                "seed": s.get("seed", 999),
                "team": s.get("team") or "",
            }

    # 라운드별 경기 분류
    bouts_by_round = defaultdict(list)
    for bout in full_bouts:
        rn = bout.get("round_name", "")
        bouts_by_round[rn].append(bout)

    # 탈락자 추적: {name: {round_name, seed, team}}
    eliminated = {}
    # 아직 탈락하지 않은 선수 (최종 라운드 진출자)
    active_players = set(seed_map.keys())

    # 라운드 순서대로 처리 (1라운드부터)
    ordered_rounds = [r for r in ROUND_ORDER if r in bouts_by_round]

    for round_name in ordered_rounds:
        for bout in bouts_by_round[round_name]:
            p1_name = (bout.get("player1_name") or "").strip()
            p2_name = (bout.get("player2_name") or "").strip()
            is_bye = bout.get("is_bye") or False

            # 바이: 빈 선수는 진짜 참가자가 아님
            if is_bye:
                # 바이 상대가 있으면 그 선수는 계속 진출
                continue

            winner = determine_bout_winner(bout)

            if winner == "player1" and p2_name and p2_name in active_players:
                eliminated[p2_name] = {
                    "round_name": round_name,
                    "seed": seed_map.get(p2_name, {}).get("seed", 999),
                    "team": seed_map.get(p2_name, {}).get("team", ""),
                }
                active_players.discard(p2_name)
            elif winner == "player2" and p1_name and p1_name in active_players:
                eliminated[p1_name] = {
                    "round_name": round_name,
                    "seed": seed_map.get(p1_name, {}).get("seed", 999),
                    "team": seed_map.get(p1_name, {}).get("team", ""),
                }
                active_players.discard(p1_name)
            elif winner is None and p1_name and p2_name:
                # 미결정 경기: 두 선수 모두 아직 active 상태 유지
                pass

    # 순위 빌드
    rankings = []

    # 1. Active 선수 (아직 탈락하지 않은 선수) → 시드 순으로 1위부터
    active_list = sorted(
        [(name, seed_map.get(name, {}).get("seed", 999), seed_map.get(name, {}).get("team", ""))
         for name in active_players if name],
        key=lambda x: x[1]
    )

    if len(active_list) == 1:
        # 우승자 확정
        rankings.append({
            "name": active_list[0][0],
            "rank": 1,
            "team": active_list[0][2],
            "estimated": False,
        })
    else:
        # 복수의 active 선수 → 시드 순 배정
        for i, (name, seed, team) in enumerate(active_list):
            rankings.append({
                "name": name,
                "rank": i + 1,
                "team": team,
                "estimated": True,
            })

    # 2. 탈락자: 라운드별 그룹, 그룹 내 시드 순
    # 결승부터 역순으로
    for round_name in reversed(ROUND_ORDER):
        losers = [
            (name, info) for name, info in eliminated.items()
            if info["round_name"] == round_name
        ]
        if not losers:
            continue

        # 시드 순 정렬
        losers.sort(key=lambda x: x[1]["seed"])
        base_rank = ROUND_TO_RANK.get(round_name, 999)

        # active 선수 수 고려: 실제 순위는 active 수 + 이전 탈락자 수 + 1부터
        # 하지만 표준 펜싱은 ROUND_TO_RANK 고정 순위 사용
        # active 선수 수가 1 이상이면 표준 순위 사용
        # active 선수가 여러명이면 그들이 1~N위이므로 결승 패자 순위 조정
        actual_rank = max(base_rank, len(active_list) + 1) if round_name == "결승" else base_rank

        # active가 여럿이면 (아직 진행 중), 순위를 active 수 이후로 밀어야 함
        if len(active_list) > 1 and round_name in ROUND_ORDER:
            round_idx = ROUND_ORDER.index(round_name)
            # 이 라운드보다 후속 라운드에서 탈락한 선수 수
            later_rounds = ROUND_ORDER[round_idx + 1:]
            later_eliminated = sum(
                1 for _, info in eliminated.items()
                if info["round_name"] in later_rounds
            )
            actual_rank = len(active_list) + later_eliminated + 1

        for name, info in losers:
            rankings.append({
                "name": name,
                "rank": actual_rank,
                "team": info["team"],
                "estimated": True,
            })

    # 3. Pool 전용 참가자 (DE에 진출하지 못한 선수)
    if pool_total_ranking:
        de_names = set(seed_map.keys())
        max_de_rank = max((r["rank"] for r in rankings), default=0)

        pool_only = []
        for pr in pool_total_ranking:
            name = pr.get("name", "").strip()
            if name and name not in de_names:
                pool_only.append({
                    "name": name,
                    "team": pr.get("team", ""),
                    "pool_rank": pr.get("rank", 999),
                })

        # Pool 순위 순으로 정렬
        pool_only.sort(key=lambda x: x["pool_rank"])
        pool_base_rank = max_de_rank + 1 if rankings else 1

        # 같은 순위 그룹으로 (모두 pool 탈락이므로)
        for p in pool_only:
            rankings.append({
                "name": p["name"],
                "rank": pool_base_rank,
                "team": p["team"],
                "estimated": True,
            })

    # 정렬: rank 오름차순, 같은 rank 내 시드 순
    rankings.sort(key=lambda x: (x["rank"], seed_map.get(x["name"], {}).get("seed", 999)))

    return rankings


def main():
    parser = argparse.ArgumentParser(description="DE 대진표에서 순위 추정")
    parser.add_argument("--comp", required=True, help="Competition comp_idx (e.g., COMPM00691)")
    parser.add_argument("--event-id", type=int, help="특정 이벤트 ID만 처리")
    parser.add_argument("--dry-run", action="store_true", help="DB 저장 안 하고 결과만 출력")
    parser.add_argument("--force", action="store_true", help="이미 final_rankings가 있어도 추정 재실행")
    args = parser.parse_args()

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    # 대회 ID 조회
    comp_result = supabase.table("competitions").select("id, comp_name").eq("comp_idx", args.comp).execute()
    if not comp_result.data:
        logger.error(f"대회를 찾을 수 없습니다: {args.comp}")
        sys.exit(1)

    comp = comp_result.data[0]
    comp_id = comp["id"]
    logger.info(f"대회: {comp['comp_name']} (id={comp_id})")

    # 이벤트 조회
    query = supabase.table("events").select(
        "id, event_name, sub_event_cd, weapon, category, raw_data"
    ).eq("competition_id", comp_id)

    if args.event_id:
        query = query.eq("id", args.event_id)

    events_result = query.execute()
    events = events_result.data or []
    logger.info(f"이벤트 수: {len(events)}")

    estimated_count = 0
    skipped_count = 0
    error_count = 0

    for event in events:
        event_id = event["id"]
        event_name = event["event_name"]
        raw_data = event.get("raw_data") or {}

        # 단체전 건너뛰기
        if "단" in event_name:
            logger.debug(f"  [{event_name}] 단체전 건너뜀")
            continue

        de_bracket = raw_data.get("de_bracket")
        if not de_bracket:
            logger.debug(f"  [{event_name}] DE 대진표 없음")
            continue

        # 이미 final_rankings가 있으면 건너뛰기
        existing_rankings = raw_data.get("final_rankings", [])
        if existing_rankings and not args.force:
            logger.info(f"  [{event_name}] 이미 final_rankings 있음 ({len(existing_rankings)}명) → 건너뜀")
            skipped_count += 1
            continue

        pool_total_ranking = raw_data.get("pool_total_ranking", [])

        try:
            estimated = estimate_rankings_from_bracket(de_bracket, pool_total_ranking)
        except Exception as e:
            logger.error(f"  [{event_name}] 추정 실패: {e}")
            error_count += 1
            continue

        if not estimated:
            logger.warning(f"  [{event_name}] 추정 결과 없음")
            continue

        # 참가자 수 비교
        participant_count = int(de_bracket.get("participant_count", 0))
        pool_count = len(pool_total_ranking) if pool_total_ranking else 0

        # 요약 출력
        is_est = any(r.get("estimated") for r in estimated)
        status = "추정" if is_est else "확정"
        top3 = ", ".join(f"{r['rank']}위 {r['name']}({r['team'][:6]})" for r in estimated[:3])
        logger.success(
            f"  [{event_name}] {status}: {len(estimated)}명 "
            f"(DE:{participant_count}, Pool:{pool_count}) | {top3}..."
        )

        if args.dry_run:
            # 상세 출력 (dry-run 시)
            for r in estimated[:20]:
                est_mark = " *" if r.get("estimated") else ""
                logger.info(f"    {r['rank']:>3}위  {r['name']:<12} {r['team']}{est_mark}")
            if len(estimated) > 20:
                logger.info(f"    ... +{len(estimated) - 20}명")
        else:
            # DB 저장 - final_rankings에 estimated 플래그 포함
            # raw_data 전체를 업데이트 (기존 데이터 보존)
            raw_data["final_rankings"] = estimated
            raw_data["final_rankings_source"] = "estimated"

            try:
                supabase.table("events").update({
                    "raw_data": raw_data
                }).eq("id", event_id).execute()
                estimated_count += 1
            except Exception as e:
                logger.error(f"  [{event_name}] DB 저장 실패: {e}")
                error_count += 1

    logger.info("=" * 60)
    logger.info(f"완료: 추정 {estimated_count}, 건너뜀 {skipped_count}, 오류 {error_count}")
    if args.dry_run:
        logger.info("(dry-run 모드: DB 저장 안 함)")


if __name__ == "__main__":
    main()
