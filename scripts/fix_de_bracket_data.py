"""
DE Bracket Data Correction Script

문제: 스크래퍼가 DE 브래킷을 잘못 파싱함
- 선수 아래 표시된 점수 = 이전 라운드 승리 점수 (현재 경기 결과 아님)
- 배열 순서로 상대 매칭 → 실제 브래킷 위치와 불일치

해결: seeding + final_rankings를 사용해 올바른 경기 결과 재구성
"""

import os
import sys
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import math

# 프로젝트 루트 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.supabase_client import get_supabase_client


@dataclass
class PlayerResult:
    """선수 결과 정보"""
    name: str
    team: str
    seed: int
    final_rank: int
    eliminated_in: str  # 탈락 라운드 (결승=우승자/준우승자)


def get_bracket_size(participant_count: int) -> int:
    """참가자 수에 맞는 브래킷 크기 계산 (2의 거듭제곱)"""
    return 2 ** math.ceil(math.log2(participant_count))


def get_round_name(round_size: int) -> str:
    """라운드 크기로 라운드 이름 반환"""
    round_names = {
        128: "128강",
        64: "64강",
        32: "32강",
        16: "16강",
        8: "8강",
        4: "준결승",
        2: "결승"
    }
    return round_names.get(round_size, f"{round_size}강")


def rank_to_eliminated_round(rank: int, bracket_size: int) -> str:
    """최종 순위로 탈락 라운드 추론"""
    if rank == 1:
        return "결승_승자"
    elif rank == 2:
        return "결승"
    elif rank <= 4:  # 3-4위
        return "준결승"
    elif rank <= 8:  # 5-8위
        return "8강"
    elif rank <= 16:  # 9-16위
        return "16강"
    elif rank <= 32:  # 17-32위
        return "32강"
    elif rank <= 64:
        return "64강"
    else:
        return "128강"


def get_standard_seeding_positions(bracket_size: int) -> Dict[int, int]:
    """
    표준 DE 브래킷 시드 배치 반환
    시드 번호 -> 브래킷 위치 (1-indexed)

    예: 32강 브래킷
    위치 1: 시드 1 vs 위치 2: 시드 32
    위치 3: 시드 16 vs 위치 4: 시드 17
    ...
    """
    # 표준 시드 배치 (1 vs 32, 16 vs 17 등이 16강에서 만나도록)
    if bracket_size == 32:
        # 32강에서 만나는 매치업 (시드 번호 기준)
        # 1-32, 16-17, 9-24, 8-25, 5-28, 12-21, 13-20, 4-29
        # 3-30, 14-19, 11-22, 6-27, 7-26, 10-23, 15-18, 2-31
        return {
            1: 1, 32: 2, 16: 3, 17: 4, 9: 5, 24: 6, 8: 7, 25: 8,
            5: 9, 28: 10, 12: 11, 21: 12, 13: 13, 20: 14, 4: 15, 29: 16,
            3: 17, 30: 18, 14: 19, 19: 20, 11: 21, 22: 22, 6: 23, 27: 24,
            7: 25, 26: 26, 10: 27, 23: 28, 15: 29, 18: 30, 2: 31, 31: 32
        }
    elif bracket_size == 16:
        return {
            1: 1, 16: 2, 8: 3, 9: 4, 5: 5, 12: 6, 4: 7, 13: 8,
            3: 9, 14: 10, 6: 11, 11: 12, 7: 13, 10: 14, 2: 15, 15: 16
        }
    else:
        # 기본 배치 (순차)
        return {i: i for i in range(1, bracket_size + 1)}


def get_match_pairs_for_round(round_size: int, bracket_size: int) -> List[Tuple[int, int]]:
    """
    해당 라운드의 매치 쌍 반환 (시드 위치 기준)

    32강에서 22명이면:
    - 시드 1-10은 부전승 (상대 없음)
    - 시드 11-22가 32강 경기: (11,22), (12,21), (13,20), (14,19), (15,18), (16,17)
    """
    pairs = []
    for i in range(round_size // 2):
        pos1 = i * 2 + 1
        pos2 = i * 2 + 2
        pairs.append((pos1, pos2))
    return pairs


def reconstruct_bracket_from_rankings(
    seeding: List[Dict],
    final_rankings: List[Dict],
    bracket_size: int
) -> Dict[str, List[Dict]]:
    """
    시드와 최종 순위를 기반으로 브래킷 경기 재구성

    핵심 로직:
    1. 최종 순위가 높은 선수가 더 오래 살아남음
    2. 같은 라운드에서 탈락한 선수들 중 시드 배치로 누가 누구와 만났는지 추론
    3. 순위가 더 높은 선수가 해당 경기 승자
    """
    # 선수 정보 매핑
    player_info = {}
    for s in seeding:
        name = s.get('name', '')
        if name and name not in player_info:
            player_info[name] = {
                'name': name,
                'team': s.get('team', ''),
                'seed': s.get('seed', 99),
            }

    for r in final_rankings:
        name = r.get('name', '')
        if name in player_info:
            player_info[name]['final_rank'] = r.get('rank', 99)
            player_info[name]['eliminated_in'] = rank_to_eliminated_round(
                r.get('rank', 99), bracket_size
            )
        elif name:
            player_info[name] = {
                'name': name,
                'team': r.get('team', ''),
                'seed': 99,
                'final_rank': r.get('rank', 99),
                'eliminated_in': rank_to_eliminated_round(r.get('rank', 99), bracket_size)
            }

    # 시드로 정렬된 선수 목록
    sorted_players = sorted(
        [p for p in player_info.values() if p.get('seed', 99) < 99],
        key=lambda x: x['seed']
    )

    participant_count = len(sorted_players)

    # 각 라운드별 경기 결과 재구성
    reconstructed_bouts = {
        '32강': [],
        '16강': [],
        '8강': [],
        '준결승': [],
        '결승': [],
    }

    # 현재 라운드 진출자 (시드 순)
    current_round_players = sorted_players.copy()

    # 라운드별로 처리
    rounds = ['32강', '16강', '8강', '준결승', '결승']
    round_sizes = [32, 16, 8, 4, 2]

    for round_name, round_size in zip(rounds, round_sizes):
        if len(current_round_players) > round_size:
            # 이 라운드에서 경기 필요
            num_matches = len(current_round_players) - round_size

            # 하위 시드끼리 먼저 경기 (시드 배치 규칙)
            # 예: 22명이면 11-22 시드가 32강 경기
            bye_count = round_size * 2 - len(current_round_players)
            match_players = current_round_players[bye_count:]  # 부전승 제외

            next_round_players = current_round_players[:bye_count]  # 부전승 선수들

            # 매치 쌍 생성 (상위 시드 vs 하위 시드)
            half = len(match_players) // 2
            for i in range(half):
                p1 = match_players[i]  # 상위 시드
                p2 = match_players[-(i+1)]  # 하위 시드 (역순)

                # 누가 이겼나? → 최종 순위가 더 높은 선수
                p1_rank = p1.get('final_rank', 99)
                p2_rank = p2.get('final_rank', 99)

                if p1_rank < p2_rank:
                    winner, loser = p1, p2
                else:
                    winner, loser = p2, p1

                bout = {
                    'round_name': round_name,
                    'winner': {
                        'name': winner['name'],
                        'team': winner.get('team', ''),
                        'seed': winner.get('seed'),
                        'score': None  # 점수는 알 수 없음
                    },
                    'loser': {
                        'name': loser['name'],
                        'team': loser.get('team', ''),
                        'seed': loser.get('seed'),
                        'score': None
                    },
                    'is_reconstructed': True
                }
                reconstructed_bouts[round_name].append(bout)
                next_round_players.append(winner)

            # 시드 순으로 재정렬
            current_round_players = sorted(next_round_players, key=lambda x: x.get('seed', 99))

        elif len(current_round_players) == round_size:
            # 정확히 이 라운드 시작
            half = round_size // 2
            next_round_players = []

            for i in range(half):
                p1 = current_round_players[i]  # 상위 시드
                p2 = current_round_players[-(i+1)] if i < half else None  # 하위 시드

                if p2 is None:
                    next_round_players.append(p1)
                    continue

                p1_rank = p1.get('final_rank', 99)
                p2_rank = p2.get('final_rank', 99)

                if p1_rank < p2_rank:
                    winner, loser = p1, p2
                else:
                    winner, loser = p2, p1

                bout = {
                    'round_name': round_name,
                    'winner': {
                        'name': winner['name'],
                        'team': winner.get('team', ''),
                        'seed': winner.get('seed'),
                        'score': None
                    },
                    'loser': {
                        'name': loser['name'],
                        'team': loser.get('team', ''),
                        'seed': loser.get('seed'),
                        'score': None
                    },
                    'is_reconstructed': True
                }
                reconstructed_bouts[round_name].append(bout)
                next_round_players.append(winner)

            current_round_players = sorted(next_round_players, key=lambda x: x.get('seed', 99))

        if len(current_round_players) <= 1:
            break

    return reconstructed_bouts


def compare_bouts(
    original_bouts: List[Dict],
    reconstructed_bouts: Dict[str, List[Dict]]
) -> List[Dict]:
    """원본 bouts와 재구성된 bouts 비교"""
    discrepancies = []

    # 원본에서 선수쌍 → 경기 정보 매핑
    original_matchups = {}
    for bout in original_bouts:
        winner = bout.get('winner', {})
        loser = bout.get('loser', {})
        w_name = winner.get('name', '')
        l_name = loser.get('name', '')
        if w_name and l_name:
            key = tuple(sorted([w_name, l_name]))
            if key not in original_matchups:
                original_matchups[key] = []
            original_matchups[key].append({
                'round': bout.get('round_name'),
                'winner': w_name,
                'loser': l_name,
                'score': f"{winner.get('score', '?')}-{loser.get('score', '?')}"
            })

    # 재구성된 데이터와 비교
    for round_name, bouts in reconstructed_bouts.items():
        for bout in bouts:
            winner = bout['winner']['name']
            loser = bout['loser']['name']
            key = tuple(sorted([winner, loser]))

            if key in original_matchups:
                orig = original_matchups[key]
                for o in orig:
                    if o['winner'] != winner:
                        discrepancies.append({
                            'type': 'WINNER_MISMATCH',
                            'players': key,
                            'round': round_name,
                            'original_winner': o['winner'],
                            'correct_winner': winner,
                            'original_round': o['round'],
                            'original_score': o['score']
                        })

    return discrepancies


def analyze_event(event_id: int) -> Dict:
    """특정 종목의 DE 데이터 분석 및 수정 제안"""
    supabase = get_supabase_client()

    # 종목 데이터 가져오기
    result = supabase.table('events').select('*').eq('id', event_id).execute()
    if not result.data:
        return {'error': f'Event {event_id} not found'}

    event = result.data[0]
    raw_data = event.get('raw_data', {})
    de_bracket = raw_data.get('de_bracket', {})

    seeding = de_bracket.get('seeding', [])
    final_rankings = raw_data.get('final_rankings', [])
    full_bouts = de_bracket.get('full_bouts', [])

    if not seeding or not final_rankings:
        return {'error': 'Missing seeding or final_rankings data'}

    # 참가자 수와 브래킷 크기
    unique_seeds = len(set(s.get('seed') for s in seeding if s.get('seed')))
    participant_count = unique_seeds
    bracket_size = get_bracket_size(participant_count)

    # 브래킷 재구성
    reconstructed = reconstruct_bracket_from_rankings(seeding, final_rankings, bracket_size)

    # 비교 분석
    discrepancies = compare_bouts(full_bouts, reconstructed)

    return {
        'event_id': event_id,
        'event_name': event.get('event_name'),
        'participant_count': participant_count,
        'bracket_size': bracket_size,
        'original_bout_count': len(full_bouts),
        'reconstructed': reconstructed,
        'discrepancies': discrepancies,
        'discrepancy_count': len(discrepancies)
    }


def fix_head_to_head_query(player_name: str, event_id: int) -> str:
    """특정 선수의 head-to-head 데이터 수정을 위한 분석"""
    result = analyze_event(event_id)

    if 'error' in result:
        return result['error']

    # 해당 선수 관련 불일치 찾기
    player_issues = [
        d for d in result['discrepancies']
        if player_name in d['players']
    ]

    return {
        'player': player_name,
        'event': result['event_name'],
        'issues': player_issues,
        'correct_results': [
            bout for round_bouts in result['reconstructed'].values()
            for bout in round_bouts
            if bout['winner']['name'] == player_name or bout['loser']['name'] == player_name
        ]
    }


if __name__ == '__main__':
    # 테스트: 익산 U13 여자 플뢰레 (event_id: 2487)
    print("=== DE Bracket Data Analysis ===\n")

    result = analyze_event(2487)

    if 'error' in result:
        print(f"Error: {result['error']}")
    else:
        print(f"종목: {result['event_name']}")
        print(f"참가자: {result['participant_count']}명 (브래킷 크기: {result['bracket_size']})")
        print(f"원본 bout 수: {result['original_bout_count']}")
        print(f"불일치 건수: {result['discrepancy_count']}")

        print("\n=== 재구성된 경기 결과 ===")
        for round_name, bouts in result['reconstructed'].items():
            if bouts:
                print(f"\n{round_name}:")
                for bout in bouts:
                    w = bout['winner']
                    l = bout['loser']
                    print(f"  {w['name']}(시드{w['seed']}) def. {l['name']}(시드{l['seed']})")

        if result['discrepancies']:
            print("\n=== 발견된 불일치 ===")
            for d in result['discrepancies']:
                print(f"  [{d['type']}] {d['players']}")
                print(f"    원본: {d['original_winner']} 승 ({d['original_round']}, {d['original_score']})")
                print(f"    수정: {d['correct_winner']} 승 ({d['round']})")

        # 박소윤 관련 분석
        print("\n=== 박소윤 관련 분석 ===")
        sooyoon_result = fix_head_to_head_query('박소윤', 2487)
        if isinstance(sooyoon_result, dict):
            print(f"이슈 건수: {len(sooyoon_result['issues'])}")
            for issue in sooyoon_result['issues']:
                print(f"  {issue}")
            print("\n올바른 경기 결과:")
            for bout in sooyoon_result['correct_results']:
                w = bout['winner']
                l = bout['loser']
                print(f"  {bout['round_name']}: {w['name']} def. {l['name']}")
