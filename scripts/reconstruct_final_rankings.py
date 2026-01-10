#!/usr/bin/env python3
"""
DE bracket에서 전체 final_rankings를 재구성하는 스크립트
- 모든 대회의 불완전한 final_rankings 수정
- DE bracket의 탈락 라운드 기반으로 순위 계산
- Pool seeding 기반 순차 순위 부여 (공동 순위 없음)
"""

import json
import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def get_base_rank_from_round(round_name: str) -> int:
    """탈락 라운드에 따른 기본 순위 반환 (해당 라운드의 시작 순위)

    펜싱 DE 토너먼트 순위 체계:
    - 결승 승자: 1위
    - 결승 패자: 2위
    - 준결승 패자: 3위~4위 (seed로 구분)
    - 8강 패자: 5위~8위 (seed로 구분)
    - 16강 패자: 9위~16위 (seed로 구분)
    - 32강 패자: 17위~32위 (seed로 구분)
    - 64강 패자: 33위~64위 (seed로 구분)
    """
    round_to_base_rank = {
        "결승": 2,  # 결승 패자
        "준결승": 3,  # 3~4위
        "8강": 5,     # 5~8위
        "16강": 9,    # 9~16위
        "32강": 17,   # 17~32위
        "64강": 33,   # 33~64위
        "128강": 65,  # 65~128위
    }
    return round_to_base_rank.get(round_name, 99)


def reconstruct_rankings_from_de(de_bracket: dict, pool_ranking: list) -> list:
    """DE bracket과 pool ranking에서 전체 순위 재구성"""
    if not de_bracket:
        return []

    bouts = de_bracket.get("full_bouts") or de_bracket.get("bouts", [])
    seeding = de_bracket.get("seeding", [])
    champion = de_bracket.get("champion", {})

    if not bouts:
        return []

    # 선수 정보 맵 (name -> player info) - 이름 기반 lookup
    player_map_by_name = {}
    for s in seeding:
        if s.get("name") and not s.get("is_bye"):
            player_map_by_name[s["name"]] = {
                "name": s["name"],
                "team": s.get("team", ""),
                "seed": s["seed"]
            }

    # pool ranking에서 추가 정보 보완
    pool_map = {}
    for p in pool_ranking:
        name = p.get("name") or p.get("player_name")
        if name:
            pool_map[name] = p

    # 각 선수의 탈락 라운드 추적
    player_elimination_round = {}  # name -> round_name

    # 모든 bout을 분석하여 패자의 탈락 라운드 기록
    for bout in bouts:
        if bout.get("is_bye"):
            continue

        winner = bout.get("winner_name")
        p1_name = bout.get("player1_name")
        p2_name = bout.get("player2_name")
        round_name = bout.get("round_name")

        if not winner or not round_name:
            continue

        # 패자 결정
        if p1_name and p1_name != winner:
            loser = p1_name
            loser_team = bout.get("player1_team", "")
            loser_seed = bout.get("player1_seed")
        elif p2_name and p2_name != winner:
            loser = p2_name
            loser_team = bout.get("player2_team", "")
            loser_seed = bout.get("player2_seed")
        else:
            continue

        if loser and loser not in player_elimination_round:
            player_elimination_round[loser] = {
                "round": round_name,
                "team": loser_team,
                "seed": loser_seed
            }

    # 순위 목록 생성
    rankings = []

    # 1위: 챔피언
    if champion and champion.get("name"):
        champ_name = champion["name"]
        champ_info = player_map_by_name.get(champ_name, {})
        pool_info = pool_map.get(champ_name, {})
        rankings.append({
            "rank": 1,
            "name": champ_name,
            "team": champ_info.get("team") or pool_info.get("team_name", ""),
            "seed": champ_info.get("seed", 0)
        })

    # 라운드별로 그룹화
    round_groups = {}  # round_name -> [player_info, ...]
    for name, elim_info in player_elimination_round.items():
        round_name = elim_info["round"]
        if round_name not in round_groups:
            round_groups[round_name] = []

        seeding_info = player_map_by_name.get(name, {})
        pool_info = pool_map.get(name, {})
        # 팀 정보 우선순위: bout에서 > seeding에서 > pool에서
        team = elim_info.get("team") or seeding_info.get("team") or pool_info.get("team_name", "")
        # seed 우선순위: 원래 seeding에서 > bout에서 (bout seed는 라운드마다 재번호됨)
        seed = seeding_info.get("seed") or elim_info.get("seed", 0)

        round_groups[round_name].append({
            "name": name,
            "team": team,
            "seed": seed
        })

    # 각 라운드 그룹 내에서 seed로 정렬 후 순차적 순위 부여
    for round_name, players in round_groups.items():
        base_rank = get_base_rank_from_round(round_name)
        # seed가 낮을수록 (pool 순위가 높을수록) 좋은 순위
        players.sort(key=lambda x: x.get("seed", 999))

        for i, player in enumerate(players):
            rankings.append({
                "rank": base_rank + i,  # seed 순서대로 순차 순위
                "name": player["name"],
                "team": player["team"],
                "seed": player["seed"]
            })

    # 최종 순위로 정렬
    rankings.sort(key=lambda x: (x["rank"], x.get("seed", 999)))

    return rankings


def update_event_rankings(event_id: int, new_rankings: list):
    """이벤트의 final_rankings 업데이트"""
    # 현재 raw_data 가져오기
    result = supabase.table("events").select("raw_data").eq("id", event_id).execute()
    if not result.data:
        print(f"  Event {event_id} not found")
        return False

    raw_data = result.data[0]["raw_data"]
    raw_data["final_rankings"] = new_rankings

    # 업데이트
    supabase.table("events").update({"raw_data": raw_data}).eq("id", event_id).execute()
    return True


def main():
    """모든 대회의 모든 이벤트 final_rankings 재구성"""
    import argparse
    parser = argparse.ArgumentParser(description="Reconstruct final rankings from DE bracket")
    parser.add_argument("--competition-id", type=int, help="특정 대회만 처리")
    parser.add_argument("--dry-run", action="store_true", help="실제 업데이트 없이 확인만")
    parser.add_argument("--verbose", action="store_true", help="상세 출력")
    args = parser.parse_args()

    # 모든 대회 가져오기
    if args.competition_id:
        comp_result = supabase.table("competitions")\
            .select("id, comp_name")\
            .eq("id", args.competition_id)\
            .execute()
    else:
        comp_result = supabase.table("competitions")\
            .select("id, comp_name")\
            .order("id")\
            .execute()

    total_updated = 0
    total_skipped = 0
    total_no_de = 0

    for comp in comp_result.data:
        comp_id = comp["id"]
        comp_name = comp["comp_name"]

        # 이벤트 가져오기
        result = supabase.table("events")\
            .select("id, event_name, raw_data")\
            .eq("competition_id", comp_id)\
            .execute()

        if not result.data:
            continue

        comp_updated = 0
        for event in result.data:
            event_id = event["id"]
            event_name = event["event_name"]
            raw_data = event["raw_data"] or {}

            de_bracket = raw_data.get("de_bracket") or {}
            pool_ranking = raw_data.get("pool_total_ranking", [])
            current_rankings = raw_data.get("final_rankings") or []

            # DE bracket 없으면 스킵
            if not de_bracket or not de_bracket.get("bouts") and not de_bracket.get("full_bouts"):
                total_no_de += 1
                continue

            participant_count = de_bracket.get("participant_count", 0)
            current_count = len(current_rankings) if current_rankings else 0

            # 공동 순위가 있는 경우도 재구성 필요 (3위가 2명 이상인 경우)
            rank_3_count = sum(1 for r in current_rankings if r.get("rank") == 3) if current_rankings else 0
            has_tied_ranks = rank_3_count > 1
            has_missing_teams = any(not r.get("team") and not r.get("team_name") for r in current_rankings[:4]) if current_rankings else False

            # 필드명 체크 (player_name -> name, team_name -> team으로 변환 필요 여부)
            has_wrong_fields = False
            if current_rankings and len(current_rankings) > 0:
                first_ranking = current_rankings[0]
                if first_ranking.get("player_name") and not first_ranking.get("name"):
                    has_wrong_fields = True

            # 이미 완전하면 스킵 (필드명이 올바른 경우만)
            if current_count >= participant_count and not has_missing_teams and not has_tied_ranks and not has_wrong_fields:
                total_skipped += 1
                continue

            # 순위 재구성
            new_rankings = reconstruct_rankings_from_de(de_bracket, pool_ranking)

            if not new_rankings:
                continue

            needs_update = (
                len(new_rankings) > current_count or
                has_missing_teams or
                has_tied_ranks or
                has_wrong_fields or
                current_count == 0
            )

            if needs_update:
                if has_wrong_fields:
                    reason = "필드명수정"
                elif has_tied_ranks:
                    reason = "공동순위→순차순위"
                elif has_missing_teams:
                    reason = "팀정보보완"
                elif current_count == 0:
                    reason = f"신규 {len(new_rankings)}명"
                else:
                    reason = f"{current_count}→{len(new_rankings)}명"

                if args.verbose or comp_updated == 0:
                    print(f"\n[{comp_id}] {comp_name}")

                print(f"  [{event_id}] {event_name}: {reason}")

                if args.verbose:
                    for r in new_rankings[:5]:
                        print(f"      {r['rank']}위: {r['name']} ({r['team']})")

                # 업데이트
                if not args.dry_run:
                    if update_event_rankings(event_id, new_rankings):
                        comp_updated += 1
                        total_updated += 1
                    else:
                        print(f"      ❌ 업데이트 실패")
                else:
                    comp_updated += 1
                    total_updated += 1

    print(f"\n{'='*50}")
    print(f"처리 완료:")
    print(f"  - 업데이트: {total_updated}개 이벤트")
    print(f"  - 스킵 (이미 완전): {total_skipped}개 이벤트")
    print(f"  - DE 없음: {total_no_de}개 이벤트")


if __name__ == "__main__":
    main()
