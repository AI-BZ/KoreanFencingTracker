"""
DE Bracket Data Normalization Utility v2

새로운 bout 기반 데이터 구조와 기존 레거시 형식 모두 지원.
- 새 형식: bouts[], bouts_by_round{}
- 레거시 형식: results_by_round{}, match_results[]
"""
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from collections import defaultdict
import re


@dataclass
class BracketBout:
    """단일 DE 경기 (bout) - 새로운 기본 구조"""
    bout_id: str
    round: str                    # "32강", "16강", "8강", "준결승", "결승"
    round_order: int              # 1=128강, 2=64강, ..., 7=결승
    match_number: int             # 해당 라운드 내 경기 번호

    player1_seed: int
    player1_name: str
    player1_team: str
    player1_score: Optional[int]

    player2_seed: Optional[int]   # 부전승 시 None
    player2_name: Optional[str]
    player2_team: Optional[str]
    player2_score: Optional[int]

    winner_seed: Optional[int]
    winner_name: Optional[str]
    is_completed: bool
    is_bye: bool

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class NormalizedBracket:
    """정규화된 브래킷 구조 v2"""
    bracket_size: int             # 8, 16, 32, 64, 128
    participant_count: int        # 실제 참가자 수
    starting_round: str           # 시작 라운드 ("32강", "64강" 등)
    rounds: List[str]             # 라운드 목록 (순서대로)
    seeding: List[Dict]           # 시드 배정
    bouts: List[BracketBout]      # 모든 경기
    bouts_by_round: Dict[str, List[BracketBout]]

    def to_dict(self) -> Dict:
        return {
            'bracket_size': self.bracket_size,
            'participant_count': self.participant_count,
            'starting_round': self.starting_round,
            'rounds': self.rounds,
            'seeding': self.seeding,
            'bouts': [b.to_dict() for b in self.bouts],
            'bouts_by_round': {
                r: [b.to_dict() for b in bouts]
                for r, bouts in self.bouts_by_round.items()
            }
        }


# 라운드 순서 정의
ROUND_ORDER = {
    '128강': 1, '128강전': 1,
    '64강': 2, '64강전': 2,
    '32강': 3, '32강전': 3,
    '16강': 4, '16강전': 4,
    '8강': 5, '8강전': 5,
    '준결승': 6, '4강': 6, '4강전': 6,
    '결승': 7, '결승전': 7,
    '3-4위전': 8, '3위결정전': 8, '3-4위': 8,
}

ROUND_DISPLAY_NAMES = {
    '128강전': '128강', '128강': '128강',
    '64강전': '64강', '64강': '64강',
    '32강전': '32강', '32강': '32강',
    '16강전': '16강', '16강': '16강',
    '8강전': '8강', '8강': '8강',
    '4강전': '준결승', '4강': '준결승', '준결승': '준결승',
    '결승전': '결승', '결승': '결승',
    '3-4위전': '3-4위', '3위결정전': '3-4위', '3-4위': '3-4위',
}


def normalize_round_name(raw_name: str) -> str:
    """라운드 이름 정규화 (표시용)"""
    return ROUND_DISPLAY_NAMES.get(raw_name, raw_name)


def get_round_order(round_name: str) -> int:
    """라운드 순서 번호 반환"""
    return ROUND_ORDER.get(round_name, 99)


def get_bracket_size(participant_count: int) -> int:
    """참가자 수에 따른 브래킷 크기 (2의 거듭제곱)"""
    sizes = [4, 8, 16, 32, 64, 128]
    for size in sizes:
        if participant_count <= size:
            return size
    return 128


def get_starting_round(bracket_size: int) -> str:
    """브래킷 크기에 따른 시작 라운드"""
    mapping = {
        4: '준결승',
        8: '8강',
        16: '16강',
        32: '32강',
        64: '64강',
        128: '128강'
    }
    return mapping.get(bracket_size, '32강')


def extract_score(score_data: Any) -> Tuple[Optional[int], Optional[int]]:
    """점수 추출 (다양한 형식 지원)"""
    if score_data is None:
        return None, None

    if isinstance(score_data, dict):
        return score_data.get('winner_score'), score_data.get('loser_score')

    if isinstance(score_data, (int, float)):
        return int(score_data), None

    if isinstance(score_data, str):
        match = re.match(r'(\d+)\s*[-:]\s*(\d+)', score_data)
        if match:
            return int(match.group(1)), int(match.group(2))

    return None, None


def normalize_bracket_data(de_bracket: Dict) -> NormalizedBracket:
    """
    DE 브래킷 데이터 정규화

    우선순위:
    1. full_bouts (가장 완전한 데이터 - winner/loser/scores 포함)
    2. bouts (새로운 형식)
    3. results_by_round (레거시 - 불완전, 중복 가능)
    """
    if not de_bracket:
        return NormalizedBracket(
            bracket_size=0,
            participant_count=0,
            starting_round='',
            rounds=[],
            seeding=[],
            bouts=[],
            bouts_by_round={}
        )

    # 시딩 정보 추출 및 정리
    raw_seeding = de_bracket.get('seeding', [])
    seen_seeds = set()
    clean_seeding = []

    for player in raw_seeding:
        seed = player.get('seed')
        if seed and seed not in seen_seeds:
            seen_seeds.add(seed)
            clean_seeding.append({
                'seed': seed,
                'name': player.get('name', ''),
                'team': player.get('team', '')
            })

    clean_seeding.sort(key=lambda x: x['seed'])
    participant_count = len(clean_seeding)

    all_bouts: List[BracketBout] = []
    bouts_by_round: Dict[str, List[BracketBout]] = defaultdict(list)

    # 방법 1: full_bouts 사용 (가장 우선 - 완전한 경기 정보)
    full_bouts = de_bracket.get('full_bouts', [])
    if full_bouts:
        all_bouts, bouts_by_round = _process_full_bouts(full_bouts)

    # 방법 2: 새로운 bouts 형식 사용 (de_scraper_v4 호환)
    elif de_bracket.get('bouts', []):
        raw_bouts = de_bracket.get('bouts', [])
        for bout_data in raw_bouts:
            # de_scraper_v4 형식: flat structure (player1_seed, player1_name 등)
            # 기존 형식: nested (player1: {seed, name})
            p1 = bout_data.get('player1', {})
            p2 = bout_data.get('player2', {})

            # de_scraper_v4 flat 형식 지원
            if 'player1_seed' in bout_data:
                p1_seed = bout_data.get('player1_seed', 0)
                p1_name = bout_data.get('player1_name', '')
                p1_team = bout_data.get('player1_team', '')
                p1_score = bout_data.get('player1_score')
                p2_seed = bout_data.get('player2_seed')
                p2_name = bout_data.get('player2_name')
                p2_team = bout_data.get('player2_team')
                p2_score = bout_data.get('player2_score')
            else:
                # 기존 nested 형식
                p1_seed = p1.get('seed', 0) if p1 else 0
                p1_name = p1.get('name', '') if p1 else ''
                p1_team = p1.get('team', '') if p1 else ''
                p1_score = p1.get('score') if p1 else None
                p2_seed = p2.get('seed') if p2 else None
                p2_name = p2.get('name') if p2 else None
                p2_team = p2.get('team') if p2 else None
                p2_score = p2.get('score') if p2 else None

            # round_name 또는 round 필드 지원
            round_field = bout_data.get('round_name', bout_data.get('round', ''))
            # match_number 또는 matchNumber 필드 지원
            match_num = bout_data.get('match_number', bout_data.get('matchNumber', 0))
            # winner_seed 또는 winnerSeed 필드 지원
            winner_seed = bout_data.get('winner_seed', bout_data.get('winnerSeed'))
            winner_name = bout_data.get('winner_name', bout_data.get('winnerName'))
            # is_bye 또는 isBye 필드 지원
            is_bye = bout_data.get('is_bye', bout_data.get('isBye', False))

            bout = BracketBout(
                bout_id=bout_data.get('bout_id', ''),
                round=round_field,
                round_order=bout_data.get('round_order', get_round_order(round_field)),
                match_number=match_num,
                player1_seed=p1_seed,
                player1_name=p1_name,
                player1_team=p1_team,
                player1_score=p1_score,
                player2_seed=p2_seed,
                player2_name=p2_name,
                player2_team=p2_team,
                player2_score=p2_score,
                winner_seed=winner_seed,
                winner_name=winner_name,
                is_completed=winner_name is not None,
                is_bye=is_bye
            )

            all_bouts.append(bout)
            round_name = normalize_round_name(bout.round)
            bouts_by_round[round_name].append(bout)

    # 방법 3: 레거시 results_by_round 형식 변환 (폴백)
    elif de_bracket.get('results_by_round'):
        all_bouts, bouts_by_round = _process_legacy_results_by_round(
            de_bracket.get('results_by_round', {})
        )

    # 라운드 정렬
    sorted_rounds = sorted(
        bouts_by_round.keys(),
        key=lambda r: get_round_order(r)
    )

    # 3-4위전 제외
    main_rounds = [r for r in sorted_rounds if r not in ('3-4위', '3-4위전', '3위결정전')]

    # 브래킷 크기 결정
    bracket_size = de_bracket.get('bracket_size', 0)
    if not bracket_size and participant_count:
        bracket_size = get_bracket_size(participant_count)

    # 시작 라운드
    starting_round = de_bracket.get('starting_round', '')
    if not starting_round and main_rounds:
        starting_round = main_rounds[0]

    return NormalizedBracket(
        bracket_size=bracket_size,
        participant_count=participant_count,
        starting_round=starting_round,
        rounds=main_rounds,
        seeding=clean_seeding,
        bouts=all_bouts,
        bouts_by_round=dict(bouts_by_round)
    )


def _process_full_bouts(full_bouts: List[Dict]) -> Tuple[List[BracketBout], Dict[str, List[BracketBout]]]:
    """
    full_bouts 데이터 처리 (가장 완전한 형식)

    full_bouts는 winner/loser/scores를 모두 포함하므로
    가장 정확한 대진표 구성 가능
    """
    all_bouts: List[BracketBout] = []
    bouts_by_round: Dict[str, List[BracketBout]] = defaultdict(list)

    # 중복 제거를 위한 키 세트 (라운드 + 선수 조합)
    seen_matches: set = set()

    # 라운드별로 그룹화하여 경기 수 기반으로 라운드명 검증
    raw_bouts_by_round: Dict[str, List[Dict]] = defaultdict(list)
    for bout_data in full_bouts:
        round_name = normalize_round_name(bout_data.get('round', ''))
        raw_bouts_by_round[round_name].append(bout_data)

    # 라운드별 예상 경기 수 기반으로 라운드명 수정
    corrected_rounds = _correct_round_names(raw_bouts_by_round)

    bout_counter = 1
    for original_round, bouts_data in corrected_rounds.items():
        match_num = 1

        for bout_data in bouts_data:
            winner = bout_data.get('winner', {})
            loser = bout_data.get('loser', {})
            score = bout_data.get('score', {})

            winner_name = winner.get('name', '')
            loser_name = loser.get('name', '')

            # 중복 체크 (같은 라운드에서 같은 두 선수 경기)
            match_key = _create_match_key(original_round, winner_name, loser_name)
            if match_key in seen_matches:
                continue
            seen_matches.add(match_key)

            # 점수 추출
            winner_score = score.get('winner_score')
            loser_score = score.get('loser_score')

            # BracketBout 생성 (winner가 player1, loser가 player2)
            bout = BracketBout(
                bout_id=f"{original_round}_{bout_counter:02d}",
                round=original_round,
                round_order=get_round_order(original_round),
                match_number=match_num,
                player1_seed=winner.get('seed', 0),
                player1_name=winner_name,
                player1_team=winner.get('team', ''),
                player1_score=winner_score,
                player2_seed=loser.get('seed'),
                player2_name=loser_name,
                player2_team=loser.get('team', ''),
                player2_score=loser_score,
                winner_seed=winner.get('seed'),
                winner_name=winner_name,
                is_completed=True,
                is_bye=False
            )

            all_bouts.append(bout)
            bouts_by_round[original_round].append(bout)
            bout_counter += 1
            match_num += 1

    return all_bouts, bouts_by_round


def _create_match_key(round_name: str, player1: str, player2: str) -> str:
    """경기 중복 체크를 위한 키 생성 (순서 무관)"""
    players = sorted([player1.strip(), player2.strip()])
    return f"{round_name}:{players[0]}:{players[1]}"


def _correct_round_names(raw_bouts_by_round: Dict[str, List[Dict]]) -> Dict[str, List[Dict]]:
    """
    라운드별 중복 제거 및 필요시 라운드명 수정

    순서:
    1. 먼저 각 라운드별로 중복 제거
    2. 중복 제거 후에도 경기 수가 맞지 않으면 라운드명 수정 고려
       (단, 결승/준결승은 이동하지 않음 - 원본 데이터 존중)
    """
    # 1단계: 각 라운드별 중복 제거 먼저 수행
    deduped_by_round = {}
    for round_name, bouts in raw_bouts_by_round.items():
        seen = set()
        unique_bouts = []
        for bout in bouts:
            winner = bout.get('winner', {})
            loser = bout.get('loser', {})
            key = _create_match_key(round_name, winner.get('name', ''), loser.get('name', ''))
            if key not in seen:
                seen.add(key)
                unique_bouts.append(bout)
        deduped_by_round[round_name] = unique_bouts

    # 2단계: 중복 제거 후 경기 수 검증 (대부분 이 단계에서 정상)
    expected_counts = {
        '결승': 1,
        '준결승': 2,
        '8강': 4,
        '16강': 8,
        '32강': 16,
        '64강': 32,
    }

    # 라운드명 변경하지 않을 라운드들 (원본 존중)
    # 결승/준결승은 절대 다른 라운드로 이동시키지 않음
    protected_rounds = {'결승', '준결승'}

    result = {}
    for round_name, bouts in deduped_by_round.items():
        actual_count = len(bouts)
        expected = expected_counts.get(round_name, actual_count)

        # 보호된 라운드는 경기 수와 관계없이 원래 라운드명 유지
        if round_name in protected_rounds:
            if round_name not in result:
                result[round_name] = []
            result[round_name].extend(bouts)
            continue

        # 경기 수가 예상보다 현저히 많은 경우에만 라운드명 수정
        # (2배 이상 차이나는 경우만 - 중복 제거 후에도 이렇게 차이나면 진짜 잘못된 것)
        if actual_count >= expected * 2:
            corrected_round = _find_round_by_count(actual_count)
            # 보호된 라운드로 이동하려는 경우 무시
            if corrected_round and corrected_round != round_name and corrected_round not in protected_rounds:
                if corrected_round not in result:
                    result[corrected_round] = []
                result[corrected_round].extend(bouts)
                continue

        # 원래 라운드명 유지
        if round_name not in result:
            result[round_name] = []
        result[round_name].extend(bouts)

    return result


def _find_round_by_count(count: int) -> Optional[str]:
    """경기 수에 맞는 라운드명 반환"""
    # 약간의 오차 허용
    if count == 1:
        return '결승'
    elif count == 2:
        return '준결승'
    elif 3 <= count <= 4:
        return '8강'
    elif 5 <= count <= 8:
        return '16강'
    elif 9 <= count <= 16:
        return '32강'
    elif 17 <= count <= 32:
        return '64강'
    return None


def _process_legacy_results_by_round(
    results_by_round: Dict[str, List[Dict]]
) -> Tuple[List[BracketBout], Dict[str, List[BracketBout]]]:
    """
    레거시 results_by_round 형식 처리 (폴백)

    주의: 이 형식은 승자 정보만 있고 table_index가 부정확할 수 있음
    """
    all_bouts: List[BracketBout] = []
    bouts_by_round: Dict[str, List[BracketBout]] = defaultdict(list)
    bout_counter = 1

    for raw_round, players in results_by_round.items():
        round_name = normalize_round_name(raw_round)
        round_order = get_round_order(raw_round)

        # 경기 결과만 필터링
        match_players = [p for p in players if p.get('is_match_result', False)]

        # table_index로 그룹화하여 경기 매칭
        by_table = defaultdict(list)
        for p in match_players:
            by_table[p.get('table_index', 0)].append(p)

        match_num = 1
        for table_idx in sorted(by_table.keys()):
            table_players = sorted(by_table[table_idx], key=lambda x: x.get('seed', 999))

            for i in range(0, len(table_players), 2):
                p1 = table_players[i]
                p2 = table_players[i + 1] if i + 1 < len(table_players) else None

                if not p1:
                    continue

                # 같은 선수끼리 매칭되면 스킵 (bye 처리 오류)
                if p2 and p1.get('name') == p2.get('name'):
                    # 단일 선수 - bye 처리
                    p2 = None

                # 점수로 승자/패자 결정
                p1_score = extract_score(p1.get('score'))
                p2_score = extract_score(p2.get('score')) if p2 else (None, None)

                # 승자 점수가 있는 쪽이 승자
                winner_seed = None
                winner_name = None

                if p1_score[0] is not None:
                    winner_seed = p1.get('seed')
                    winner_name = p1.get('name')
                elif p2 and p2_score[0] is not None:
                    winner_seed = p2.get('seed')
                    winner_name = p2.get('name')

                bout = BracketBout(
                    bout_id=f"{round_name}_{bout_counter:02d}",
                    round=round_name,
                    round_order=round_order,
                    match_number=match_num,
                    player1_seed=p1.get('seed', 0),
                    player1_name=p1.get('name', ''),
                    player1_team=p1.get('team', ''),
                    player1_score=p1_score[0] if winner_seed == p1.get('seed') else p1_score[1],
                    player2_seed=p2.get('seed') if p2 else None,
                    player2_name=p2.get('name') if p2 else None,
                    player2_team=p2.get('team') if p2 else None,
                    player2_score=p2_score[0] if p2 and winner_seed == p2.get('seed') else (p2_score[1] if p2 else None),
                    winner_seed=winner_seed,
                    winner_name=winner_name,
                    is_completed=winner_seed is not None,
                    is_bye=p2 is None
                )

                all_bouts.append(bout)
                bouts_by_round[round_name].append(bout)
                bout_counter += 1
                match_num += 1

    return all_bouts, bouts_by_round


def calculate_expected_matches(bracket_size: int) -> Dict[str, int]:
    """브래킷 크기에 따른 라운드별 예상 경기 수"""
    expected = {}

    if bracket_size >= 128:
        expected['128강'] = 64
    if bracket_size >= 64:
        expected['64강'] = 32
    if bracket_size >= 32:
        expected['32강'] = 16
    if bracket_size >= 16:
        expected['16강'] = 8
    if bracket_size >= 8:
        expected['8강'] = 4
    if bracket_size >= 4:
        expected['준결승'] = 2
    expected['결승'] = 1

    return expected


def validate_bracket(bracket: NormalizedBracket) -> Dict[str, Any]:
    """브래킷 데이터 검증"""
    issues = []

    expected = calculate_expected_matches(bracket.bracket_size)

    # 각 라운드별 경기 수 확인
    for round_name, expected_count in expected.items():
        if round_name not in bracket.bouts_by_round:
            issues.append(f"누락된 라운드: {round_name}")
        else:
            actual_count = len(bracket.bouts_by_round[round_name])
            if actual_count < expected_count * 0.5:  # 50% 미만이면 경고
                issues.append(f"{round_name}: 예상 {expected_count}개, 실제 {actual_count}개")

    # 필수 라운드 확인
    required_rounds = ['준결승', '결승']
    for r in required_rounds:
        if r not in bracket.bouts_by_round:
            issues.append(f"필수 라운드 누락: {r}")

    # 경기 완료 여부 확인
    incomplete_count = sum(1 for b in bracket.bouts if not b.is_completed)

    return {
        'valid': len(issues) == 0,
        'issues': issues,
        'total_bouts': len(bracket.bouts),
        'incomplete_bouts': incomplete_count,
        'rounds_found': bracket.rounds,
        'expected_rounds': list(expected.keys())
    }


def validate_bracket_vs_final_rankings(
    bracket: NormalizedBracket,
    final_rankings: List[Dict]
) -> Dict[str, Any]:
    """
    DE 대진표 결과와 최종 순위 일치 여부 검증

    검증 항목:
    1. 결승 우승자 = 최종 1위
    2. 결승 패자 = 최종 2위
    3. 준결승 패자들 = 최종 3위 (공동 3위 2명)

    참고:
    - 원본 데이터에 여러 개의 결승 경기가 있을 수 있음 (스크래퍼 오류)
    - 이 경우 최종 순위와 일치하는 경기를 찾아서 검증
    """
    issues = []
    warnings = []

    if not bracket.bouts or not final_rankings:
        return {
            'valid': False,
            'issues': ['대진표 또는 최종 순위 데이터 없음'],
            'warnings': []
        }

    # 최종 순위 파싱
    rank_map = {}
    for r in final_rankings:
        rank = r.get('rank')
        name = r.get('name', '').strip()
        if rank and name:
            if rank not in rank_map:
                rank_map[rank] = []
            rank_map[rank].append(name)

    first_place = rank_map.get(1, [])
    second_place = rank_map.get(2, [])

    # 결승 찾기
    final_bouts = bracket.bouts_by_round.get('결승', [])

    if not final_bouts:
        issues.append('결승 경기 없음')
    else:
        # 여러 결승 경기가 있으면 최종 순위와 일치하는 경기 찾기
        matched_final_bout = None

        for bout in final_bouts:
            if bout.winner_name in first_place:
                matched_final_bout = bout
                break

        if matched_final_bout is None:
            # 일치하는 경기 없으면 첫 번째 사용
            matched_final_bout = final_bouts[0]
            issues.append(
                f'결승 우승자({matched_final_bout.winner_name})가 '
                f'최종 1위({first_place})와 불일치'
            )

        if len(final_bouts) > 1:
            # 여러 결승 경기는 경고로 처리 (데이터 품질 문제)
            warnings.append(
                f'결승이 {len(final_bouts)}경기 (데이터 품질 문제, '
                f'{matched_final_bout.winner_name} vs {matched_final_bout.player2_name if matched_final_bout.winner_name == matched_final_bout.player1_name else matched_final_bout.player1_name} 사용)'
            )

        final_winner = matched_final_bout.winner_name

        # 2위 검증 (결승 패자)
        final_loser = matched_final_bout.player2_name if matched_final_bout.winner_name == matched_final_bout.player1_name else matched_final_bout.player1_name
        if final_loser and final_loser not in second_place:
            warnings.append(
                f'결승 패자({final_loser})가 최종 2위({second_place})와 불일치'
            )

    # 준결승 검증 (3위 공동)
    semifinal_bouts = bracket.bouts_by_round.get('준결승', [])
    if semifinal_bouts:
        semifinal_losers = []
        for bout in semifinal_bouts:
            loser = bout.player2_name if bout.winner_name == bout.player1_name else bout.player1_name
            if loser:
                semifinal_losers.append(loser)

        third_place = rank_map.get(3, [])
        for loser in semifinal_losers:
            if loser not in third_place:
                warnings.append(
                    f'준결승 패자({loser})가 최종 3위({third_place})에 없음'
                )

    return {
        'valid': len(issues) == 0,
        'issues': issues,
        'warnings': warnings,
        'final_winner': matched_final_bout.winner_name if final_bouts else None,
        'expected_first': first_place
    }


def compute_full_final_rankings(
    de_bracket: Dict,
    pool_total_ranking: List[Dict]
) -> List[Dict]:
    """
    DE 대진표 + Pool 결과에서 전체 최종 순위 계산

    순위 결정 원칙 (펜싱 표준):
    - 1위: 결승 승자
    - 2위: 결승 패자
    - 3위 (공동): 준결승 패자 2명
    - 5-8위 (공동): 8강 패자 4명
    - 9-16위 (공동): 16강 패자 8명
    - 17-32위 (공동): 32강 패자 16명
    - 나머지: Pool 순위대로 (DE 진출 못한 선수들)

    Returns:
        List[Dict]: [{"rank": 1, "name": "...", "team": "..."}, ...]
    """
    # 1. DE 데이터 정규화
    normalized = normalize_bracket_data(de_bracket)
    if not normalized or not normalized.bouts:
        # DE 데이터가 없으면 pool 순위 반환
        return [
            {"rank": r.get("rank", i+1), "name": r.get("name", ""), "team": r.get("team", "")}
            for i, r in enumerate(pool_total_ranking or [])
        ]

    final_rankings = []
    assigned_players = set()

    # 라운드별 패자 수집
    def get_losers_from_round(round_name: str) -> List[Dict]:
        """특정 라운드에서 진 선수들을 반환"""
        losers = []
        bouts = normalized.bouts_by_round.get(round_name, [])
        for bout in bouts:
            if bout.is_bye:
                continue
            # 패자 결정: 승자가 아닌 쪽
            if bout.winner_name:
                loser_name = bout.player2_name if bout.winner_name == bout.player1_name else bout.player1_name
                loser_team = bout.player2_team if bout.winner_name == bout.player1_name else bout.player1_team
                if loser_name and loser_name not in assigned_players:
                    losers.append({"name": loser_name, "team": loser_team or ""})
        return losers

    # 2. 결승에서 1, 2위 결정
    final_bouts = normalized.bouts_by_round.get('결승', [])
    if final_bouts:
        final_bout = final_bouts[0]  # 첫 번째 결승 사용
        if final_bout.winner_name:
            # 1위: 결승 승자
            winner_team = final_bout.player1_team if final_bout.winner_name == final_bout.player1_name else final_bout.player2_team
            final_rankings.append({
                "rank": 1,
                "name": final_bout.winner_name,
                "team": winner_team or ""
            })
            assigned_players.add(final_bout.winner_name)

            # 2위: 결승 패자
            loser_name = final_bout.player2_name if final_bout.winner_name == final_bout.player1_name else final_bout.player1_name
            loser_team = final_bout.player2_team if final_bout.winner_name == final_bout.player1_name else final_bout.player1_team
            if loser_name:
                final_rankings.append({
                    "rank": 2,
                    "name": loser_name,
                    "team": loser_team or ""
                })
                assigned_players.add(loser_name)

    # 3. 준결승 패자 = 공동 3위
    sf_losers = get_losers_from_round('준결승')
    for loser in sf_losers:
        if loser["name"] not in assigned_players:
            final_rankings.append({
                "rank": 3,
                "name": loser["name"],
                "team": loser["team"]
            })
            assigned_players.add(loser["name"])

    # 4. 8강 패자 = 공동 5위
    qf_losers = get_losers_from_round('8강')
    for loser in qf_losers:
        if loser["name"] not in assigned_players:
            final_rankings.append({
                "rank": 5,
                "name": loser["name"],
                "team": loser["team"]
            })
            assigned_players.add(loser["name"])

    # 5. 16강 패자 = 공동 9위
    r16_losers = get_losers_from_round('16강')
    for loser in r16_losers:
        if loser["name"] not in assigned_players:
            final_rankings.append({
                "rank": 9,
                "name": loser["name"],
                "team": loser["team"]
            })
            assigned_players.add(loser["name"])

    # 6. 32강 패자 = 공동 17위
    r32_losers = get_losers_from_round('32강')
    for loser in r32_losers:
        if loser["name"] not in assigned_players:
            final_rankings.append({
                "rank": 17,
                "name": loser["name"],
                "team": loser["team"]
            })
            assigned_players.add(loser["name"])

    # 7. 64강 패자 = 공동 33위
    r64_losers = get_losers_from_round('64강')
    for loser in r64_losers:
        if loser["name"] not in assigned_players:
            final_rankings.append({
                "rank": 33,
                "name": loser["name"],
                "team": loser["team"]
            })
            assigned_players.add(loser["name"])

    # 8. 128강 패자 = 공동 65위
    r128_losers = get_losers_from_round('128강')
    for loser in r128_losers:
        if loser["name"] not in assigned_players:
            final_rankings.append({
                "rank": 65,
                "name": loser["name"],
                "team": loser["team"]
            })
            assigned_players.add(loser["name"])

    # 9. DE 진출 선수들 (부전승 포함) - pool에서 가져옴
    # seeding에 있는 선수들도 추가
    de_participants = set()
    for s in normalized.seeding:
        if s.get('name'):
            de_participants.add(s['name'])

    # bouts에서 참가자 추가
    for bout in normalized.bouts:
        if bout.player1_name:
            de_participants.add(bout.player1_name)
        if bout.player2_name:
            de_participants.add(bout.player2_name)

    # 10. Pool에서 DE 진출 못한 선수들 추가
    if pool_total_ranking:
        current_rank = max((r["rank"] for r in final_rankings), default=0)

        for pool_player in pool_total_ranking:
            player_name = pool_player.get("name", "")
            if player_name and player_name not in assigned_players:
                current_rank += 1
                final_rankings.append({
                    "rank": current_rank,
                    "name": player_name,
                    "team": pool_player.get("team", "")
                })
                assigned_players.add(player_name)

    # 순위순으로 정렬
    final_rankings.sort(key=lambda x: (x["rank"], x["name"]))

    return final_rankings


# 레거시 호환성을 위한 별칭
BracketMatch = BracketBout
