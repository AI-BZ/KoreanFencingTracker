#!/usr/bin/env python3
"""
불완전한 DE bracket 데이터를 final_rankings에서 재구성하는 스크립트

문제:
- 49개 이벤트에서 8강, 준결승, 결승 데이터가 누락됨
- final_rankings에는 순위 정보가 있음

해결:
- final_rankings의 1-8위를 사용해서 누락된 라운드 재구성
- 1위 = 결승 승자
- 2위 = 결승 패자
- 3-4위 = 준결승 패자
- 5-8위 = 8강 패자
"""

import os
import sys
import json
from typing import Dict, List, Optional
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def get_seed_for_player(name: str, seeding: List[Dict]) -> int:
    """선수 이름으로 시드 번호 찾기"""
    for s in seeding:
        if s.get('name') == name:
            return s.get('seed', 0)
    return 0


def reconstruct_later_rounds(de_bracket: Dict, final_rankings: List[Dict]) -> Dict:
    """
    final_rankings에서 8강, 준결승, 결승 라운드 재구성

    DE 토너먼트 순위 체계:
    - 1위: 결승 승자
    - 2위: 결승 패자
    - 3-4위: 준결승 패자
    - 5-8위: 8강 패자
    """
    if not final_rankings or len(final_rankings) < 4:
        return de_bracket

    seeding = de_bracket.get('seeding', [])
    existing_full_bouts = de_bracket.get('full_bouts', [])
    existing_rounds = set()

    for bout in existing_full_bouts:
        r = bout.get('round_name') or bout.get('round')
        if r:
            existing_rounds.add(r)

    # 이미 8강 이상이 있으면 스킵
    if '8강' in existing_rounds or '준결승' in existing_rounds or '결승' in existing_rounds:
        return de_bracket

    new_bouts = []

    # 순위별 선수 분류
    rank_1 = [r for r in final_rankings if r.get('rank') == 1]
    rank_2 = [r for r in final_rankings if r.get('rank') == 2]
    rank_3 = [r for r in final_rankings if r.get('rank') == 3]
    rank_5_8 = [r for r in final_rankings if r.get('rank') in [5, 6, 7, 8]]

    # 결승 재구성 (1위 vs 2위)
    if rank_1 and rank_2:
        winner = rank_1[0]
        loser = rank_2[0]

        new_bouts.append({
            'bout_id': '결승_01',
            'round_name': '결승',
            'round': '결승',
            'round_order': 7,
            'match_number': 1,
            'player1_name': winner.get('name'),
            'player1_team': winner.get('team', ''),
            'player1_seed': get_seed_for_player(winner.get('name'), seeding),
            'player2_name': loser.get('name'),
            'player2_team': loser.get('team', ''),
            'player2_seed': get_seed_for_player(loser.get('name'), seeding),
            'winner_name': winner.get('name'),
            'winner_seed': get_seed_for_player(winner.get('name'), seeding),
            'is_completed': True,
            'is_bye': False,
            '_reconstructed': True
        })

    # 준결승 재구성 (1-2위 vs 3-4위)
    if rank_1 and rank_3 and len(rank_3) >= 1:
        # 준결승 1: 1위(결승승자) vs 3위(준결승패자1)
        winner1 = rank_1[0]
        loser1 = rank_3[0]
        new_bouts.append({
            'bout_id': '준결승_01',
            'round_name': '준결승',
            'round': '준결승',
            'round_order': 6,
            'match_number': 1,
            'player1_name': winner1.get('name'),
            'player1_team': winner1.get('team', ''),
            'player1_seed': get_seed_for_player(winner1.get('name'), seeding),
            'player2_name': loser1.get('name'),
            'player2_team': loser1.get('team', ''),
            'player2_seed': get_seed_for_player(loser1.get('name'), seeding),
            'winner_name': winner1.get('name'),
            'winner_seed': get_seed_for_player(winner1.get('name'), seeding),
            'is_completed': True,
            'is_bye': False,
            '_reconstructed': True
        })

    if rank_2 and len(rank_3) >= 2:
        # 준결승 2: 2위(결승패자) vs 4위(준결승패자2)
        winner2 = rank_2[0]
        loser2 = rank_3[1] if len(rank_3) > 1 else rank_3[0]
        new_bouts.append({
            'bout_id': '준결승_02',
            'round_name': '준결승',
            'round': '준결승',
            'round_order': 6,
            'match_number': 2,
            'player1_name': winner2.get('name'),
            'player1_team': winner2.get('team', ''),
            'player1_seed': get_seed_for_player(winner2.get('name'), seeding),
            'player2_name': loser2.get('name'),
            'player2_team': loser2.get('team', ''),
            'player2_seed': get_seed_for_player(loser2.get('name'), seeding),
            'winner_name': winner2.get('name'),
            'winner_seed': get_seed_for_player(winner2.get('name'), seeding),
            'is_completed': True,
            'is_bye': False,
            '_reconstructed': True
        })

    # 8강 재구성 (1-4위 vs 5-8위)
    # 이건 더 복잡 - 누가 누구와 붙었는지 알 수 없음
    # 일단 스킵하고 준결승/결승만 추가

    if not new_bouts:
        return de_bracket

    # 새 bout들을 기존 데이터에 추가
    result = dict(de_bracket)
    result['full_bouts'] = existing_full_bouts + new_bouts
    result['bouts'] = result.get('bouts', []) + new_bouts

    # rounds 업데이트
    all_rounds = set(result.get('rounds', []))
    for bout in new_bouts:
        all_rounds.add(bout.get('round_name'))

    # 라운드 순서 정렬
    round_order = ['128강', '64강', '32강', '16강', '8강', '준결승', '결승']
    result['rounds'] = [r for r in round_order if r in all_rounds]

    return result


def find_incomplete_events():
    """불완전한 DE 데이터가 있는 이벤트 찾기"""
    incomplete = []

    # Get all events in batches
    all_events = []
    offset = 0
    batch_size = 1000

    while True:
        result = supabase.table("events").select(
            "id, event_name, competition_id, raw_data"
        ).order("id").range(offset, offset + batch_size - 1).execute()

        if not result.data:
            break
        all_events.extend(result.data)
        if len(result.data) < batch_size:
            break
        offset += batch_size

    for event in all_events:
        raw = event.get("raw_data") or {}
        de_bracket = raw.get("de_bracket") or {}
        full_bouts = de_bracket.get('full_bouts', [])
        final_rankings = raw.get('final_rankings', [])

        if not full_bouts:
            continue

        # Check for later rounds
        rounds = set()
        for bout in full_bouts:
            r = bout.get('round_name') or bout.get('round')
            if r:
                rounds.add(r)

        participant_count = de_bracket.get('participant_count', 0)
        has_later = '8강' in rounds or '준결승' in rounds or '결승' in rounds

        # 8명 이상 참가자인데 8강 이상 없으면 불완전
        if participant_count >= 8 and not has_later and len(final_rankings) >= 4:
            incomplete.append({
                'id': event['id'],
                'name': event['event_name'],
                'comp_id': event['competition_id'],
                'participants': participant_count,
                'rounds': sorted(rounds),
                'rankings_count': len(final_rankings)
            })

    return incomplete


def fix_event(event_id: int, dry_run: bool = True) -> bool:
    """단일 이벤트 수정"""
    result = supabase.table("events").select("id, event_name, raw_data").eq("id", event_id).execute()

    if not result.data:
        print(f"  Event {event_id} not found")
        return False

    event = result.data[0]
    raw = event.get("raw_data") or {}
    de_bracket = raw.get("de_bracket") or {}
    final_rankings = raw.get("final_rankings", [])

    # 재구성
    fixed_bracket = reconstruct_later_rounds(de_bracket, final_rankings)

    # 변경 확인
    old_rounds = set(de_bracket.get('rounds', []))
    new_rounds = set(fixed_bracket.get('rounds', []))
    added_rounds = new_rounds - old_rounds

    if not added_rounds:
        print(f"  [{event_id}] {event['event_name']}: 변경 없음")
        return False

    print(f"  [{event_id}] {event['event_name']}: 추가된 라운드 {added_rounds}")

    if dry_run:
        return True

    # 실제 업데이트
    raw['de_bracket'] = fixed_bracket
    supabase.table("events").update({"raw_data": raw}).eq("id", event_id).execute()
    return True


def main():
    import argparse
    parser = argparse.ArgumentParser(description="불완전한 DE bracket 데이터 수정")
    parser.add_argument("--dry-run", action="store_true", help="실제 업데이트 없이 확인만")
    parser.add_argument("--event-id", type=int, help="특정 이벤트만 처리")
    parser.add_argument("--competition-id", type=int, help="특정 대회만 처리")
    args = parser.parse_args()

    if args.event_id:
        print(f"=== 단일 이벤트 수정: {args.event_id} ===")
        fix_event(args.event_id, dry_run=args.dry_run)
        return

    print("=== 불완전한 DE 데이터 검색 중... ===")
    incomplete = find_incomplete_events()

    if args.competition_id:
        incomplete = [e for e in incomplete if e['comp_id'] == args.competition_id]

    print(f"발견된 불완전한 이벤트: {len(incomplete)}개")

    if not incomplete:
        print("수정할 이벤트가 없습니다.")
        return

    # Group by competition
    by_comp = defaultdict(list)
    for e in incomplete:
        by_comp[e['comp_id']].append(e)

    print(f"\n{len(by_comp)}개 대회에서 발견:")
    for comp_id, events in sorted(by_comp.items()):
        print(f"\n  Competition {comp_id}: {len(events)}개 이벤트")
        for e in events[:3]:
            print(f"    [{e['id']}] {e['name']}")

    if args.dry_run:
        print(f"\n=== Dry Run 모드 - 수정 미리보기 ===")
    else:
        print(f"\n=== 수정 시작 ===")

    fixed_count = 0
    for event in incomplete:
        if fix_event(event['id'], dry_run=args.dry_run):
            fixed_count += 1

    print(f"\n{'수정 예정' if args.dry_run else '수정 완료'}: {fixed_count}/{len(incomplete)}개 이벤트")


if __name__ == "__main__":
    main()
