#!/usr/bin/env python3
"""
raw_data 정제 스크립트 v2 - 데이터 파이프라인 정합성 보장

기존 Supabase 데이터에서 다음 문제를 수정:
1. pool_total_ranking: 중복 제거 (진출/탈락 두 번 나오는 문제)
2. de_bracket.seeding: 중복 seed 제거, 이상 데이터(다른 이벤트) 제거
3. de_bracket.bracket_size: 실제 참가자 수 기준으로 재계산
4. de_bracket.starting_round: bracket_size 기준으로 재계산
5. de_bracket.bouts: 존재하지 않는 선수 경기 제거
6. de_bracket.bouts_by_round: 부전승(bye) 경기 생성 ★ 핵심
7. 무효한 라운드 제거 (bracket_size에 맞지 않는 라운드)

데이터 파이프라인 원칙:
- 모든 라운드는 정확한 경기 수를 가져야 함 (16강=8경기, 8강=4경기, 준결승=2경기, 결승=1경기)
- 부전승도 경기로 표시되어야 함
- bracket_size에 맞지 않는 라운드는 제거
"""

import os
import json
import asyncio
from typing import Dict, List, Any, Optional, Set, Tuple
from datetime import datetime
from loguru import logger
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()


# ==================== 표준 브라켓 구조 ====================

# 브라켓 크기별 표준 매치업 (seed 쌍)
# 표준 펜싱 대진표: seed 1은 seed N과, seed 2는 seed N-1과 대전
STANDARD_BRACKET_MATCHUPS = {
    128: [(1,128), (64,65), (32,97), (33,96), (16,113), (49,80), (17,112), (48,81),
          (8,121), (57,72), (25,104), (40,89), (9,120), (56,73), (24,105), (41,88),
          (4,125), (61,68), (29,100), (36,93), (13,116), (52,77), (20,109), (45,84),
          (5,124), (60,69), (28,101), (37,92), (12,117), (53,76), (21,108), (44,85),
          (2,127), (63,66), (31,98), (34,95), (15,114), (50,79), (18,111), (47,82),
          (7,122), (58,71), (26,103), (39,90), (10,119), (55,74), (23,106), (42,87),
          (3,126), (62,67), (30,99), (35,94), (14,115), (51,78), (19,110), (46,83),
          (6,123), (59,70), (27,102), (38,91), (11,118), (54,75), (22,107), (43,86)],
    64: [(1,64), (32,33), (16,49), (17,48), (8,57), (25,40), (9,56), (24,41),
         (4,61), (29,36), (13,52), (20,45), (5,60), (28,37), (12,53), (21,44),
         (2,63), (31,34), (15,50), (18,47), (7,58), (26,39), (10,55), (23,42),
         (3,62), (30,35), (14,51), (19,46), (6,59), (27,38), (11,54), (22,43)],
    32: [(1,32), (16,17), (8,25), (9,24), (4,29), (13,20), (5,28), (12,21),
         (2,31), (15,18), (7,26), (10,23), (3,30), (14,19), (6,27), (11,22)],
    16: [(1,16), (8,9), (5,12), (4,13), (3,14), (6,11), (7,10), (2,15)],
    8: [(1,8), (4,5), (3,6), (2,7)],
    4: [(1,4), (2,3)],
}

# 브라켓 크기별 유효한 라운드
VALID_ROUNDS_BY_SIZE = {
    128: {'128강', '64강', '32강', '16강', '8강', '준결승', '결승', '3-4위'},
    64: {'64강', '32강', '16강', '8강', '준결승', '결승', '3-4위'},
    32: {'32강', '16강', '8강', '준결승', '결승', '3-4위'},
    16: {'16강', '8강', '준결승', '결승', '3-4위'},
    8: {'8강', '준결승', '결승', '3-4위'},
    4: {'준결승', '결승', '3-4위'},
}

# 라운드별 예상 경기 수
EXPECTED_BOUTS_PER_ROUND = {
    '128강': 64, '64강': 32, '32강': 16, '16강': 8,
    '8강': 4, '준결승': 2, '결승': 1, '3-4위': 1,
}


def get_supabase_client() -> Client:
    """Supabase 클라이언트 생성"""
    url = os.environ.get("SUPABASE_URL", "https://tjfjuasvjzjawyckengv.supabase.co")
    key = os.environ.get("SUPABASE_KEY")
    if not key:
        raise ValueError("SUPABASE_KEY 환경변수가 필요합니다")
    return create_client(url, key)


def get_correct_bracket_size(participant_count: int) -> int:
    """실제 참가자 수에 맞는 브라켓 크기 결정"""
    for size in [4, 8, 16, 32, 64, 128]:
        if participant_count <= size:
            return size
    return 128


def get_starting_round(bracket_size: int) -> str:
    """브라켓 크기에 따른 시작 라운드"""
    mapping = {
        4: '준결승',
        8: '8강',
        16: '16강',
        32: '32강',
        64: '64강',
        128: '128강'
    }
    return mapping.get(bracket_size, '32강')


def fix_pool_total_ranking(pool_total_ranking: List[Dict]) -> List[Dict]:
    """
    pool_total_ranking 중복 제거

    문제: 같은 선수가 "진출"과 "탈락" 두 번 나옴
    해결: 같은 이름+순위 조합은 첫 번째만 유지
    """
    if not pool_total_ranking:
        return []

    seen = set()
    fixed = []

    for player in pool_total_ranking:
        name = player.get('name', '')
        rank = player.get('rank')

        if not name:
            continue

        key = (name, rank)
        if key not in seen:
            seen.add(key)
            # status 정리: "진출" 우선
            player_copy = player.copy()
            if 'status' not in player_copy or player_copy.get('status') == '탈락':
                player_copy['status'] = '진출'
            fixed.append(player_copy)

    return fixed


def fix_seeding(seeding: List[Dict], valid_players: Set[str]) -> List[Dict]:
    """
    seeding 중복 및 이상 데이터 제거

    문제:
    1. 같은 seed가 여러 번 나옴 (중복)
    2. pool_total_ranking에 없는 선수가 나옴 (다른 이벤트 데이터 혼입)

    해결:
    1. seed 기준 첫 번째만 유지
    2. valid_players에 없는 선수는 제거 (bye는 유지)
    """
    if not seeding:
        return []

    seen_seeds = set()
    fixed = []

    for player in seeding:
        seed = player.get('seed')
        name = player.get('name')
        is_bye = player.get('is_bye', False)

        if not seed:
            continue

        # 중복 seed 제거
        if seed in seen_seeds:
            continue
        seen_seeds.add(seed)

        # bye는 그대로 유지
        if is_bye or not name:
            fixed.append({
                'seed': seed,
                'name': None,
                'team': None,
                'is_bye': True
            })
            continue

        # 다른 이벤트 데이터 제거 (valid_players에 없으면)
        if valid_players and name not in valid_players:
            logger.debug(f"이상 데이터 제거: seed={seed}, name={name}")
            fixed.append({
                'seed': seed,
                'name': None,
                'team': None,
                'is_bye': True
            })
            continue

        fixed.append(player)

    # seed 순으로 정렬
    fixed.sort(key=lambda x: x.get('seed', 999))

    return fixed


def fill_missing_seeds(seeding: List[Dict], bracket_size: int) -> List[Dict]:
    """
    bracket_size까지 빈 seed를 bye로 채움

    예: seeding이 14명이고 bracket_size가 16이면 seed 15, 16을 bye로 추가
    """
    if not bracket_size or bracket_size < 4:
        return seeding

    existing_seeds = {p.get('seed') for p in seeding if p.get('seed')}
    result = list(seeding)

    for seed in range(1, bracket_size + 1):
        if seed not in existing_seeds:
            result.append({
                'seed': seed,
                'name': None,
                'team': None,
                'is_bye': True
            })

    # seed 순으로 정렬
    result.sort(key=lambda x: x.get('seed', 999))

    return result


def fix_bouts(bouts: List[Dict], valid_players: Set[str]) -> List[Dict]:
    """
    bouts에서 존재하지 않는 선수 경기 제거

    문제: 다른 이벤트 선수가 경기에 등장
    해결: 양쪽 선수가 모두 valid_players에 있어야 유지
    """
    if not bouts:
        return []

    fixed = []

    for bout in bouts:
        p1_name = bout.get('player1_name')
        p2_name = bout.get('player2_name')
        is_bye = bout.get('is_bye', False)

        # bye 경기는 p1만 확인
        if is_bye:
            if not p1_name or (valid_players and p1_name not in valid_players):
                continue
            fixed.append(bout)
            continue

        # 일반 경기: 양쪽 선수 확인
        if valid_players:
            if p1_name and p1_name not in valid_players:
                continue
            if p2_name and p2_name not in valid_players:
                continue

        fixed.append(bout)

    return fixed


def fix_bouts_by_round(bouts_by_round: Dict[str, List[Dict]], valid_players: Set[str]) -> Dict[str, List[Dict]]:
    """bouts_by_round 정제"""
    if not bouts_by_round:
        return {}

    fixed = {}
    for round_name, bouts in bouts_by_round.items():
        fixed_bouts = fix_bouts(bouts, valid_players)
        if fixed_bouts:
            fixed[round_name] = fixed_bouts

    return fixed


# ==================== 부전승(Bye) 생성 로직 ====================

def get_seeding_map(seeding: List[Dict]) -> Dict[int, Dict]:
    """seed 번호 → 선수 정보 맵 생성"""
    return {p.get('seed'): p for p in seeding if p.get('seed')}


def generate_bye_bouts_for_starting_round(
    seeding: List[Dict],
    bracket_size: int,
    starting_round: str,
    existing_bouts: List[Dict]
) -> List[Dict]:
    """
    시작 라운드의 부전승 경기 생성

    Args:
        seeding: 시드 배정 리스트
        bracket_size: 브라켓 크기 (8, 16, 32, ...)
        starting_round: 시작 라운드명 ("16강", "32강", ...)
        existing_bouts: 기존 실제 경기 리스트

    Returns:
        기존 경기 + 새로 생성된 부전승 경기
    """
    if bracket_size not in STANDARD_BRACKET_MATCHUPS:
        return existing_bouts

    seeding_map = get_seeding_map(seeding)
    matchups = STANDARD_BRACKET_MATCHUPS[bracket_size]

    # 기존 경기에서 이미 있는 매치업 추적 (seed 기준)
    existing_matchups = set()
    for bout in existing_bouts:
        s1 = bout.get('player1_seed')
        s2 = bout.get('player2_seed')
        if s1 and s2:
            existing_matchups.add((min(s1, s2), max(s1, s2)))
        elif s1:
            # 부전승 경기 - s1만 있음
            existing_matchups.add((s1, None))

    result_bouts = list(existing_bouts)  # 기존 경기 복사

    for match_num, (seed1, seed2) in enumerate(matchups, 1):
        p1 = seeding_map.get(seed1, {})
        p2 = seeding_map.get(seed2, {})

        p1_is_bye = p1.get('is_bye', False) or not p1.get('name')
        p2_is_bye = p2.get('is_bye', False) or not p2.get('name')

        # 둘 다 bye면 스킵 (실제로 없는 경기)
        if p1_is_bye and p2_is_bye:
            continue

        # 이미 경기가 있는지 확인
        match_key = (min(seed1, seed2), max(seed1, seed2))
        if match_key in existing_matchups:
            continue

        # 부전승이면 경기 추가
        if p2_is_bye and not p1_is_bye:
            # seed1이 부전승으로 진출
            bye_bout = {
                'bout_id': f"{starting_round}_bye_{match_num:02d}",
                'round_name': starting_round,
                'match_number': match_num,
                'player1_seed': seed1,
                'player1_name': p1.get('name'),
                'player1_team': p1.get('team'),
                'player1_score': None,
                'player2_seed': seed2,
                'player2_name': None,  # bye
                'player2_team': None,
                'player2_score': None,
                'winner_seed': seed1,
                'winner_name': p1.get('name'),
                'is_bye': True,
                'is_completed': True,
            }
            result_bouts.append(bye_bout)
            existing_matchups.add((seed1, None))

        elif p1_is_bye and not p2_is_bye:
            # seed2가 부전승으로 진출 (드문 케이스)
            bye_bout = {
                'bout_id': f"{starting_round}_bye_{match_num:02d}",
                'round_name': starting_round,
                'match_number': match_num,
                'player1_seed': seed2,
                'player1_name': p2.get('name'),
                'player1_team': p2.get('team'),
                'player1_score': None,
                'player2_seed': seed1,
                'player2_name': None,  # bye
                'player2_team': None,
                'player2_score': None,
                'winner_seed': seed2,
                'winner_name': p2.get('name'),
                'is_bye': True,
                'is_completed': True,
            }
            result_bouts.append(bye_bout)
            existing_matchups.add((seed2, None))

    # match_number 순으로 정렬
    result_bouts.sort(key=lambda x: x.get('match_number', 999))

    return result_bouts


def filter_invalid_rounds(
    bouts_by_round: Dict[str, List[Dict]],
    bracket_size: int
) -> Dict[str, List[Dict]]:
    """
    bracket_size에 맞지 않는 라운드 제거

    예: bracket_size=16인데 "32강" 데이터가 있으면 제거
    """
    if bracket_size not in VALID_ROUNDS_BY_SIZE:
        return bouts_by_round

    valid_rounds = VALID_ROUNDS_BY_SIZE[bracket_size]
    filtered = {}

    for round_name, bouts in bouts_by_round.items():
        # 라운드명 정규화
        normalized = round_name.replace('전', '')  # "16강전" → "16강"
        if normalized in valid_rounds:
            filtered[round_name] = bouts
        else:
            logger.debug(f"무효한 라운드 제거: {round_name} (bracket_size={bracket_size})")

    return filtered


def validate_bracket_structure(
    bouts_by_round: Dict[str, List[Dict]],
    bracket_size: int,
    starting_round: str
) -> Dict[str, Any]:
    """
    브라켓 구조 검증 - 파이프라인 정합성 확인

    Returns:
        {
            'valid': bool,
            'issues': List[str],
            'round_counts': Dict[str, int]
        }
    """
    issues = []
    round_counts = {}

    # 시작 라운드부터 결승까지 확인
    round_order = ['128강', '64강', '32강', '16강', '8강', '준결승', '결승']

    try:
        start_idx = round_order.index(starting_round)
    except ValueError:
        return {'valid': False, 'issues': [f'알 수 없는 시작 라운드: {starting_round}'], 'round_counts': {}}

    for round_name in round_order[start_idx:]:
        expected = EXPECTED_BOUTS_PER_ROUND.get(round_name, 0)
        actual = len(bouts_by_round.get(round_name, []))
        round_counts[round_name] = actual

        if actual == 0:
            issues.append(f"{round_name}: 경기 없음 (예상: {expected})")
        elif actual != expected:
            issues.append(f"{round_name}: {actual}경기 (예상: {expected})")

    return {
        'valid': len(issues) == 0,
        'issues': issues,
        'round_counts': round_counts
    }


def fix_de_bracket(de_bracket: Dict, valid_players: Set[str]) -> Dict:
    """
    DE bracket 전체 정제 - 데이터 파이프라인 정합성 보장

    수정 사항:
    1. seeding 정제 (중복/오염 제거)
    2. bracket_size, starting_round 재계산
    3. 무효한 라운드 제거 (bracket_size에 맞지 않는 라운드)
    4. 부전승 경기 생성 ★
    5. 브라켓 구조 검증
    """
    if not de_bracket:
        return {}

    fixed = de_bracket.copy()

    # 1. seeding 정제
    if 'seeding' in fixed:
        fixed['seeding'] = fix_seeding(fixed['seeding'], valid_players)

    # 2. 실제 참가자 수 계산 (non-bye)
    actual_participants = sum(
        1 for p in fixed.get('seeding', [])
        if p.get('name') and not p.get('is_bye')
    )
    fixed['participant_count'] = actual_participants

    # 3. bracket_size 재계산
    bracket_size = 0
    starting_round = ''
    if actual_participants > 0:
        bracket_size = get_correct_bracket_size(actual_participants)
        starting_round = get_starting_round(bracket_size)
        fixed['bracket_size'] = bracket_size
        fixed['starting_round'] = starting_round

    # 3.5. ★ seeding에서 빠진 seed를 bye로 채움 (핵심!)
    if bracket_size and fixed.get('seeding'):
        fixed['seeding'] = fill_missing_seeds(fixed['seeding'], bracket_size)

    # 4. bouts 정제
    if 'bouts' in fixed:
        fixed['bouts'] = fix_bouts(fixed['bouts'], valid_players)

    # 5. bouts_by_round 정제
    if 'bouts_by_round' in fixed:
        fixed['bouts_by_round'] = fix_bouts_by_round(fixed['bouts_by_round'], valid_players)

    # 6. ★ 무효한 라운드 제거 (bracket_size에 맞지 않는 라운드)
    if bracket_size and fixed.get('bouts_by_round'):
        fixed['bouts_by_round'] = filter_invalid_rounds(fixed['bouts_by_round'], bracket_size)

    # 7. ★★ 부전승 경기 생성 (핵심!)
    if bracket_size and starting_round and fixed.get('seeding'):
        existing_starting_bouts = fixed.get('bouts_by_round', {}).get(starting_round, [])

        # 시작 라운드에 부전승 추가
        updated_starting_bouts = generate_bye_bouts_for_starting_round(
            seeding=fixed['seeding'],
            bracket_size=bracket_size,
            starting_round=starting_round,
            existing_bouts=existing_starting_bouts
        )

        if 'bouts_by_round' not in fixed:
            fixed['bouts_by_round'] = {}
        fixed['bouts_by_round'][starting_round] = updated_starting_bouts

    # 8. rounds 재계산 (남은 bouts 기준)
    if fixed.get('bouts_by_round'):
        # 라운드 순서대로 정렬
        round_order = ['128강', '64강', '32강', '16강', '8강', '준결승', '결승', '3-4위']
        fixed['rounds'] = sorted(
            fixed['bouts_by_round'].keys(),
            key=lambda r: round_order.index(r) if r in round_order else 99
        )

    # 9. 전체 bouts 리스트 업데이트
    all_bouts = []
    for round_name in fixed.get('rounds', []):
        all_bouts.extend(fixed.get('bouts_by_round', {}).get(round_name, []))
    fixed['bouts'] = all_bouts

    # 10. ★★★ full_bouts도 동일하게 업데이트 (normalize_bracket_data가 full_bouts 우선 사용!)
    fixed['full_bouts'] = all_bouts

    # 11. 브라켓 구조 검증 (로깅용)
    if bracket_size and starting_round:
        validation = validate_bracket_structure(
            fixed.get('bouts_by_round', {}),
            bracket_size,
            starting_round
        )
        fixed['_validation'] = validation
        if not validation['valid']:
            logger.debug(f"브라켓 검증 실패: {validation['issues']}")

    return fixed


def fix_raw_data(raw_data: Dict) -> Dict:
    """
    raw_data 전체 정제
    """
    if not raw_data:
        return {}

    fixed = raw_data.copy()

    # 1. pool_total_ranking 정제
    if 'pool_total_ranking' in fixed:
        fixed['pool_total_ranking'] = fix_pool_total_ranking(fixed['pool_total_ranking'])

    # 2. valid_players 추출 (pool_total_ranking + pool_rounds 기준)
    valid_players = set()

    # pool_total_ranking에서 추출
    for player in fixed.get('pool_total_ranking', []):
        name = player.get('name')
        if name:
            valid_players.add(name)

    # pool_rounds에서도 추출
    for pool in fixed.get('pool_rounds', []):
        for result in pool.get('results', []):
            name = result.get('name')
            if name:
                valid_players.add(name)

    # 3. de_bracket 정제
    if 'de_bracket' in fixed:
        fixed['de_bracket'] = fix_de_bracket(fixed['de_bracket'], valid_players)

    # 4. 정제 메타데이터 추가
    fixed['data_fixed_at'] = datetime.now().isoformat()
    fixed['data_fix_version'] = 'v2'  # 부전승 생성 로직 추가

    return fixed


async def fix_all_events(
    limit: Optional[int] = None,
    dry_run: bool = True
):
    """
    모든 이벤트의 raw_data 정제

    Args:
        limit: 처리할 이벤트 수 제한 (테스트용)
        dry_run: True면 실제 업데이트 안함
    """
    supabase = get_supabase_client()

    # 이벤트 목록 조회
    query = supabase.table("events").select("id, event_name, raw_data")

    if limit:
        query = query.limit(limit)

    result = query.execute()
    events = result.data or []

    logger.info(f"처리할 이벤트: {len(events)}개")

    fixed_count = 0
    error_count = 0

    for event in events:
        event_id = event['id']
        event_name = event['event_name']
        raw_data = event.get('raw_data') or {}

        if not raw_data:
            continue

        try:
            # 정제 전 상태
            before_pool_count = len(raw_data.get('pool_total_ranking', []))
            before_seeding_count = len(raw_data.get('de_bracket', {}).get('seeding', []))
            before_bracket_size = raw_data.get('de_bracket', {}).get('bracket_size')

            # 정제
            fixed_data = fix_raw_data(raw_data)

            # 정제 후 상태
            after_pool_count = len(fixed_data.get('pool_total_ranking', []))
            after_seeding_count = len(fixed_data.get('de_bracket', {}).get('seeding', []))
            after_bracket_size = fixed_data.get('de_bracket', {}).get('bracket_size')

            # 변경 여부 확인
            changed = (
                before_pool_count != after_pool_count or
                before_seeding_count != after_seeding_count or
                before_bracket_size != after_bracket_size
            )

            if changed:
                logger.info(
                    f"[{event_id}] {event_name}: "
                    f"pool {before_pool_count}→{after_pool_count}, "
                    f"seeding {before_seeding_count}→{after_seeding_count}, "
                    f"bracket {before_bracket_size}→{after_bracket_size}"
                )

                if not dry_run:
                    supabase.table("events").update({
                        "raw_data": fixed_data,
                        "updated_at": datetime.now().isoformat()
                    }).eq("id", event_id).execute()

                fixed_count += 1

        except Exception as e:
            logger.error(f"[{event_id}] {event_name}: 오류 - {e}")
            error_count += 1

    logger.info(f"완료: 수정 {fixed_count}개, 오류 {error_count}개")
    if dry_run:
        logger.info("DRY RUN 모드: 실제 업데이트 안함")


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="raw_data 정제 스크립트")
    parser.add_argument("--limit", type=int, default=None,
                       help="처리할 이벤트 수 제한")
    parser.add_argument("--apply", action="store_true",
                       help="실제 업데이트 적용 (기본은 dry-run)")

    args = parser.parse_args()

    await fix_all_events(
        limit=args.limit,
        dry_run=not args.apply
    )


if __name__ == "__main__":
    asyncio.run(main())
