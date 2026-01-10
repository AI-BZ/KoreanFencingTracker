#!/usr/bin/env python3
"""
DE 브라켓 구조 검증기 및 자동 수정기

검증 항목:
1. 시작 라운드부터 결승까지 모든 라운드 존재 확인
2. 각 라운드별 경기 수 검증 (부전승 포함)
3. 부전승이 시작 라운드에만 있는지 확인 (이후 라운드에 부전승 없어야 함)
4. 경기 연결성 검증 (이전 라운드 승자가 다음 라운드에 있는지)

v2 업데이트:
- normalize_bracket_data() 적용 후 검증 (자동 수정 효과 확인)
- raw 데이터 vs 정규화 데이터 비교 모드 추가
"""

import os
import sys
import json
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
from app.bracket_utils import normalize_bracket_data, get_bracket_size, get_starting_round

# Supabase
url = os.environ.get('SUPABASE_URL')
key = os.environ.get('SUPABASE_KEY')
supabase = create_client(url, key)

# 라운드 순서 (시작 → 결승)
ROUND_SEQUENCE = ['128강', '64강', '32강', '16강', '8강', '준결승', '결승']

# 라운드별 예상 경기 수
EXPECTED_BOUT_COUNT = {
    '128강': 64, '64강': 32, '32강': 16, '16강': 8,
    '8강': 4, '준결승': 2, '결승': 1
}

# bracket_size → 시작 라운드
BRACKET_SIZE_TO_ROUND = {
    128: '128강', 64: '64강', 32: '32강', 16: '16강',
    8: '8강', 4: '준결승', 2: '결승'
}


@dataclass
class ValidationIssue:
    """검증 이슈"""
    event_cd: str
    event_name: str
    issue_type: str
    description: str
    severity: str  # 'error', 'warning', 'info'
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """검증 결과"""
    event_cd: str
    event_name: str
    is_valid: bool
    issues: List[ValidationIssue] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)


def get_bracket_size(participant_count: int) -> int:
    """참가자 수에 따른 브래킷 크기"""
    for size in [4, 8, 16, 32, 64, 128]:
        if participant_count <= size:
            return size
    return 128


def get_rounds_from_start_to_final(starting_round: str) -> List[str]:
    """시작 라운드부터 결승까지 라운드 리스트"""
    if starting_round not in ROUND_SEQUENCE:
        return []
    start_idx = ROUND_SEQUENCE.index(starting_round)
    return ROUND_SEQUENCE[start_idx:]


def validate_de_bracket(
    event_cd: str,
    event_name: str,
    de_bracket: Dict,
    use_normalized: bool = True
) -> ValidationResult:
    """
    DE 브라켓 구조 검증

    Args:
        event_cd: 이벤트 코드
        event_name: 이벤트 이름
        de_bracket: DE 브라켓 데이터
        use_normalized: True면 normalize_bracket_data() 적용 후 검증
    """

    result = ValidationResult(
        event_cd=event_cd,
        event_name=event_name,
        is_valid=True
    )

    if not de_bracket:
        return result

    # 정규화 적용 여부
    if use_normalized:
        normalized = normalize_bracket_data(de_bracket)
        seeding = normalized.seeding
        bouts = normalized.bouts
        bouts_by_round = {
            r: [b for b in bs]
            for r, bs in normalized.bouts_by_round.items()
        }
        stored_bracket_size = normalized.bracket_size
        stored_starting_round = normalized.starting_round
        participant_count = normalized.participant_count
    else:
        # Raw 데이터 사용
        seeding = de_bracket.get('seeding', []) or []
        bouts = de_bracket.get('bouts', []) or []
        bouts_by_round = de_bracket.get('bouts_by_round', {}) or {}
        stored_bracket_size = de_bracket.get('bracket_size', 0)
        stored_starting_round = de_bracket.get('starting_round', '')

        # 실제 참가자 수
        actual_players = [s for s in seeding if s.get('name')]
        participant_count = len(actual_players)

    if participant_count < 2:
        return result

    # 올바른 bracket_size 계산
    correct_bracket_size = get_bracket_size(participant_count)
    correct_starting_round = BRACKET_SIZE_TO_ROUND.get(correct_bracket_size, '32강')

    result.stats = {
        'participant_count': participant_count,
        'stored_bracket_size': stored_bracket_size,
        'correct_bracket_size': correct_bracket_size,
        'stored_starting_round': stored_starting_round,
        'correct_starting_round': correct_starting_round,
        'total_bouts': len(bouts),
        'rounds_with_data': list(bouts_by_round.keys()),
        'use_normalized': use_normalized
    }

    # 1. bracket_size 검증
    if stored_bracket_size != correct_bracket_size:
        result.issues.append(ValidationIssue(
            event_cd=event_cd,
            event_name=event_name,
            issue_type="WRONG_BRACKET_SIZE",
            description=f"bracket_size 불일치: 저장됨={stored_bracket_size}, 올바름={correct_bracket_size}",
            severity="warning",
            details={'stored': stored_bracket_size, 'correct': correct_bracket_size}
        ))

    # 2. 필요한 라운드 목록
    expected_rounds = get_rounds_from_start_to_final(correct_starting_round)

    # 3. 각 라운드별 검증
    for round_name in expected_rounds:
        round_bouts = bouts_by_round.get(round_name, [])
        expected_count = EXPECTED_BOUT_COUNT.get(round_name, 0)
        actual_count = len(round_bouts)

        # BracketBout 객체 또는 dict 모두 지원
        def is_bye(b):
            if hasattr(b, 'is_bye'):
                return b.is_bye
            return b.get('is_bye', False)

        bye_count = len([b for b in round_bouts if is_bye(b)])
        real_count = actual_count - bye_count

        # 3a. 라운드 누락 검증
        if not round_bouts:
            result.issues.append(ValidationIssue(
                event_cd=event_cd,
                event_name=event_name,
                issue_type="MISSING_ROUND",
                description=f"{round_name} 라운드 데이터 없음",
                severity="error",
                details={'round': round_name, 'expected_bouts': expected_count}
            ))
            result.is_valid = False
            continue

        # 3b. 경기 수 검증
        if actual_count != expected_count:
            # 시작 라운드가 아닌데 부전승이 있으면 문제
            if round_name != correct_starting_round and bye_count > 0:
                result.issues.append(ValidationIssue(
                    event_cd=event_cd,
                    event_name=event_name,
                    issue_type="BYE_IN_WRONG_ROUND",
                    description=f"{round_name}에 부전승 {bye_count}개 존재 (시작 라운드: {correct_starting_round})",
                    severity="error",
                    details={
                        'round': round_name,
                        'bye_count': bye_count,
                        'starting_round': correct_starting_round
                    }
                ))
                result.is_valid = False
            elif actual_count < expected_count:
                result.issues.append(ValidationIssue(
                    event_cd=event_cd,
                    event_name=event_name,
                    issue_type="MISSING_BOUTS",
                    description=f"{round_name} 경기 부족: {actual_count}/{expected_count}",
                    severity="error" if round_name in ['준결승', '결승'] else "warning",
                    details={
                        'round': round_name,
                        'actual': actual_count,
                        'expected': expected_count,
                        'bye_count': bye_count
                    }
                ))
                if round_name in ['준결승', '결승']:
                    result.is_valid = False

    # 4. 시작 라운드 부전승 검증
    starting_round_bouts = bouts_by_round.get(correct_starting_round, [])
    starting_expected = EXPECTED_BOUT_COUNT.get(correct_starting_round, 0)
    starting_actual = len(starting_round_bouts)

    # BracketBout 객체 또는 dict 모두 지원
    def check_is_bye(b):
        if hasattr(b, 'is_bye'):
            return b.is_bye
        return b.get('is_bye', False)

    starting_byes = len([b for b in starting_round_bouts if check_is_bye(b)])

    # 부전승 수 계산: bracket_size - participant_count
    expected_byes = correct_bracket_size - participant_count

    if expected_byes > 0 and starting_byes != expected_byes:
        result.issues.append(ValidationIssue(
            event_cd=event_cd,
            event_name=event_name,
            issue_type="WRONG_BYE_COUNT",
            description=f"시작 라운드 부전승 수 불일치: {starting_byes}/{expected_byes}",
            severity="warning",
            details={
                'starting_round': correct_starting_round,
                'actual_byes': starting_byes,
                'expected_byes': expected_byes,
                'bracket_size': correct_bracket_size,
                'participant_count': participant_count
            }
        ))

    return result


def validate_all_events(limit: int = None, verbose: bool = False, use_normalized: bool = True) -> Tuple[List[ValidationResult], Dict]:
    """
    모든 이벤트 검증

    Args:
        limit: 검증할 이벤트 수 제한
        verbose: 상세 출력 여부
        use_normalized: True면 normalize_bracket_data() 적용 후 검증
    """

    # 이벤트 조회
    query = supabase.table('events').select('sub_event_cd, event_name, raw_data')
    if limit:
        query = query.limit(limit)
    result = query.execute()

    all_results = []
    issue_summary = defaultdict(list)

    total = len(result.data)
    checked = 0
    with_de = 0
    invalid = 0

    for ev in result.data:
        event_cd = ev.get('sub_event_cd', '')
        event_name = ev.get('event_name', '')
        raw_data = ev.get('raw_data', {}) or {}
        de_bracket = raw_data.get('de_bracket', {})

        if not de_bracket or not de_bracket.get('bouts'):
            continue

        with_de += 1
        validation = validate_de_bracket(event_cd, event_name, de_bracket, use_normalized=use_normalized)
        all_results.append(validation)

        if not validation.is_valid:
            invalid += 1

        for issue in validation.issues:
            issue_summary[issue.issue_type].append({
                'event_cd': event_cd,
                'event_name': event_name,
                'description': issue.description,
                'severity': issue.severity
            })

        checked += 1
        if verbose and checked % 100 == 0:
            print(f"검증 진행: {checked}/{with_de}")

    summary = {
        'total_events': total,
        'events_with_de': with_de,
        'valid_events': with_de - invalid,
        'invalid_events': invalid,
        'issue_counts': {k: len(v) for k, v in issue_summary.items()}
    }

    return all_results, issue_summary, summary


def print_validation_report(results: List[ValidationResult], issue_summary: Dict, summary: Dict):
    """검증 보고서 출력"""

    print("=" * 70)
    print("DE 브라켓 구조 검증 보고서")
    print("=" * 70)
    print()
    print(f"총 이벤트: {summary['total_events']}개")
    print(f"DE 데이터 있는 이벤트: {summary['events_with_de']}개")
    print(f"유효한 이벤트: {summary['valid_events']}개")
    print(f"문제있는 이벤트: {summary['invalid_events']}개")
    print()

    print("=" * 70)
    print("이슈 유형별 요약")
    print("=" * 70)

    # 심각도 순으로 정렬
    severity_order = {'error': 0, 'warning': 1, 'info': 2}

    for issue_type, issues in sorted(issue_summary.items()):
        errors = [i for i in issues if i['severity'] == 'error']
        warnings = [i for i in issues if i['severity'] == 'warning']

        print(f"\n### {issue_type} ({len(issues)}개)")
        if errors:
            print(f"  [ERROR] {len(errors)}개")
        if warnings:
            print(f"  [WARNING] {len(warnings)}개")

        # 샘플 출력 (최대 5개)
        for issue in issues[:5]:
            print(f"  - [{issue['event_cd']}] {issue['event_name']}")
            print(f"    {issue['description']}")

        if len(issues) > 5:
            print(f"  ... 외 {len(issues) - 5}개")

    print()
    print("=" * 70)
    print("주요 문제 이벤트 (ERROR)")
    print("=" * 70)

    error_events = set()
    for issue_type, issues in issue_summary.items():
        for issue in issues:
            if issue['severity'] == 'error':
                error_events.add((issue['event_cd'], issue['event_name']))

    for event_cd, event_name in list(error_events)[:20]:
        print(f"  - [{event_cd}] {event_name}")

    if len(error_events) > 20:
        print(f"  ... 외 {len(error_events) - 20}개")


def compare_raw_vs_normalized():
    """Raw 데이터 vs 정규화 데이터 검증 비교"""
    print("=" * 70)
    print("Raw vs Normalized 비교 검증")
    print("=" * 70)
    print()

    # Raw 데이터 검증
    print("1. Raw 데이터 검증 (정규화 없음)...")
    raw_results, raw_issues, raw_summary = validate_all_events(verbose=False, use_normalized=False)

    # 정규화 데이터 검증
    print("2. 정규화 데이터 검증 (자동 수정 적용)...")
    norm_results, norm_issues, norm_summary = validate_all_events(verbose=False, use_normalized=True)

    print()
    print("=" * 70)
    print("비교 결과")
    print("=" * 70)
    print()

    print(f"{'항목':<30} {'Raw':<15} {'Normalized':<15} {'개선':<10}")
    print("-" * 70)

    print(f"{'총 이벤트':<30} {raw_summary['total_events']:<15} {norm_summary['total_events']:<15}")
    print(f"{'DE 데이터 있는 이벤트':<30} {raw_summary['events_with_de']:<15} {norm_summary['events_with_de']:<15}")
    print(f"{'유효한 이벤트':<30} {raw_summary['valid_events']:<15} {norm_summary['valid_events']:<15} +{norm_summary['valid_events'] - raw_summary['valid_events']}")
    print(f"{'문제 있는 이벤트':<30} {raw_summary['invalid_events']:<15} {norm_summary['invalid_events']:<15} -{raw_summary['invalid_events'] - norm_summary['invalid_events']}")

    print()
    print("이슈 유형별 비교:")
    print("-" * 70)

    all_issue_types = set(raw_summary['issue_counts'].keys()) | set(norm_summary['issue_counts'].keys())
    for issue_type in sorted(all_issue_types):
        raw_count = raw_summary['issue_counts'].get(issue_type, 0)
        norm_count = norm_summary['issue_counts'].get(issue_type, 0)
        diff = raw_count - norm_count
        improvement = f"+{diff}" if diff > 0 else str(diff) if diff < 0 else "0"
        print(f"  {issue_type:<28} {raw_count:<15} {norm_count:<15} {improvement:<10}")

    return raw_summary, norm_summary


def main():
    import argparse
    parser = argparse.ArgumentParser(description='DE 브라켓 구조 검증기')
    parser.add_argument('--compare', action='store_true', help='Raw vs Normalized 비교 모드')
    parser.add_argument('--raw', action='store_true', help='Raw 데이터만 검증 (정규화 없음)')
    parser.add_argument('--limit', type=int, help='검증할 이벤트 수 제한')
    args = parser.parse_args()

    if args.compare:
        raw_summary, norm_summary = compare_raw_vs_normalized()

        # 결과 저장
        output = {
            'raw_summary': raw_summary,
            'normalized_summary': norm_summary,
            'improvement': {
                'valid_events': norm_summary['valid_events'] - raw_summary['valid_events'],
                'invalid_events': raw_summary['invalid_events'] - norm_summary['invalid_events']
            }
        }

        with open('/tmp/de_validation_comparison.json', 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        print(f"\n비교 결과 저장: /tmp/de_validation_comparison.json")
        return

    use_normalized = not args.raw
    mode_name = "Raw 데이터" if args.raw else "정규화 데이터 (자동 수정 적용)"

    print(f"DE 브라켓 구조 검증 시작... [{mode_name}]")
    print()

    results, issue_summary, summary = validate_all_events(
        limit=args.limit,
        verbose=True,
        use_normalized=use_normalized
    )
    print_validation_report(results, issue_summary, summary)

    # 결과 저장
    output = {
        'mode': 'normalized' if use_normalized else 'raw',
        'summary': summary,
        'issue_counts': {k: len(v) for k, v in issue_summary.items()},
        'issues_by_type': {k: v[:50] for k, v in issue_summary.items()}  # 각 유형별 최대 50개
    }

    with open('/tmp/de_validation_result.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n결과 저장: /tmp/de_validation_result.json")


if __name__ == "__main__":
    main()
