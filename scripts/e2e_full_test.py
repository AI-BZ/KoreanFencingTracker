#!/usr/bin/env python3
"""
E2E 전체 테스트 스크립트 - 모든 대회/이벤트 검증

검증 항목:
1. 모든 대회 페이지 접근 가능
2. 모든 이벤트의 DE 브라켓 데이터 검증
   - bracket_size 정확성
   - 라운드별 경기 수 (16강=8, 8강=4, 준결승=2, 결승=1)
   - 부전승 포함 여부
3. 문제점 리스트 생성
"""

import asyncio
import aiohttp
import json
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass
from datetime import datetime

BASE_URL = "http://localhost:71"

# 라운드별 예상 경기 수
EXPECTED_BOUTS = {
    '128강': 64, '64강': 32, '32강': 16, '16강': 8,
    '8강': 4, '준결승': 2, '결승': 1, '3-4위': 1,
}

# 브라켓 크기별 시작 라운드
STARTING_ROUNDS = {
    4: '준결승', 8: '8강', 16: '16강', 32: '32강', 64: '64강', 128: '128강'
}

# 라운드 리매핑 규칙 (스크래퍼가 잘못 저장한 라운드를 올바른 라운드로 변환)
ROUND_REMAP = {
    4: {'8강': '준결승', '16강': '준결승', '32강': '준결승'},
    8: {'16강': '8강', '32강': '8강', '64강': '8강'},
    16: {'32강': '16강', '64강': '16강', '128강': '16강'},
    32: {'64강': '32강', '128강': '32강'},
    64: {'128강': '64강'},
}


@dataclass
class Issue:
    """발견된 문제"""
    competition_cd: str
    competition_name: str
    event_cd: str
    event_name: str
    issue_type: str
    description: str
    details: Dict[str, Any]


async def get_all_competitions(session: aiohttp.ClientSession) -> List[Dict]:
    """모든 대회 목록 조회 (페이지네이션 처리)"""
    all_competitions = []
    page = 1
    per_page = 50

    while True:
        async with session.get(f"{BASE_URL}/api/competitions?page={page}&per_page={per_page}") as resp:
            if resp.status == 200:
                data = await resp.json()
                competitions = data.get("competitions", [])
                all_competitions.extend(competitions)

                total = data.get("total", 0)
                if len(all_competitions) >= total:
                    break
                page += 1
            else:
                break

    return all_competitions


async def get_competition_detail(session: aiohttp.ClientSession, event_cd: str) -> Dict:
    """대회 상세 정보 조회 (이벤트 + DE 브라켓 포함)"""
    async with session.get(f"{BASE_URL}/api/competition/{event_cd}") as resp:
        if resp.status == 200:
            return await resp.json()
        return {}


def get_correct_bracket_size(participant_count: int) -> int:
    """참가자 수에 맞는 브라켓 크기"""
    for size in [4, 8, 16, 32, 64, 128]:
        if participant_count <= size:
            return size
    return 128


def validate_de_bracket(
    event_cd: str,
    event_name: str,
    comp_cd: str,
    comp_name: str,
    de_bracket: Dict
) -> List[Issue]:
    """DE 브라켓 데이터 검증"""
    issues = []

    if not de_bracket:
        return issues  # DE 데이터 없으면 스킵 (단체전 등)

    seeding = de_bracket.get('seeding', [])
    bouts = de_bracket.get('bouts', [])
    bouts_by_round = de_bracket.get('bouts_by_round', {})
    bracket_size = de_bracket.get('bracket_size', 0)
    starting_round = de_bracket.get('starting_round', '')

    # 실제 참가자 수 계산
    actual_players = [p for p in seeding if p.get('name') and not p.get('is_bye')]
    participant_count = len(actual_players)

    if participant_count < 2:
        return issues  # 참가자 없으면 스킵

    # bouts가 비어있으면 별도 처리 (스크래핑 실패)
    if not bouts and not bouts_by_round:
        issues.append(Issue(
            competition_cd=comp_cd,
            competition_name=comp_name,
            event_cd=event_cd,
            event_name=event_name,
            issue_type="NO_BOUT_DATA",
            description=f"DE 경기 데이터 없음 (bouts=0, seeding={participant_count}명)",
            details={
                "seeding_count": participant_count,
                "bracket_size": bracket_size
            }
        ))
        return issues  # 더 이상 검증할 수 없음

    # 1. bracket_size 검증
    expected_bracket_size = get_correct_bracket_size(participant_count)
    if bracket_size != expected_bracket_size:
        issues.append(Issue(
            competition_cd=comp_cd,
            competition_name=comp_name,
            event_cd=event_cd,
            event_name=event_name,
            issue_type="WRONG_BRACKET_SIZE",
            description=f"bracket_size 불일치: 현재 {bracket_size}, 예상 {expected_bracket_size}",
            details={
                "current": bracket_size,
                "expected": expected_bracket_size,
                "participant_count": participant_count
            }
        ))

    # 2. seeding 수 검증 (bracket_size와 일치해야 함)
    if bracket_size and len(seeding) != bracket_size:
        issues.append(Issue(
            competition_cd=comp_cd,
            competition_name=comp_name,
            event_cd=event_cd,
            event_name=event_name,
            issue_type="WRONG_SEEDING_COUNT",
            description=f"seeding 수 불일치: 현재 {len(seeding)}, 예상 {bracket_size}",
            details={
                "current": len(seeding),
                "expected": bracket_size,
                "bracket_size": bracket_size
            }
        ))

    # 3. 시작 라운드 경기 수 검증
    # bouts_by_round 키를 정규화 (리매핑 적용)
    remap_rules = ROUND_REMAP.get(expected_bracket_size, {})
    normalized_bouts_by_round = {}
    for round_name, round_bouts in bouts_by_round.items():
        # 리매핑된 라운드 이름 사용
        normalized_name = remap_rules.get(round_name, round_name)
        if normalized_name not in normalized_bouts_by_round:
            normalized_bouts_by_round[normalized_name] = []
        normalized_bouts_by_round[normalized_name].extend(round_bouts)

    expected_starting = STARTING_ROUNDS.get(expected_bracket_size or bracket_size, '')
    if expected_starting and expected_starting in normalized_bouts_by_round:
        round_bouts = normalized_bouts_by_round[expected_starting]
        expected_count = EXPECTED_BOUTS.get(expected_starting, 0)
        actual_count = len(round_bouts)
        bye_count = len([b for b in round_bouts if b.get('is_bye')])

        if actual_count != expected_count:
            issues.append(Issue(
                competition_cd=comp_cd,
                competition_name=comp_name,
                event_cd=event_cd,
                event_name=event_name,
                issue_type="WRONG_BOUT_COUNT",
                description=f"{expected_starting} 경기 수 불일치: 현재 {actual_count}, 예상 {expected_count} (부전승: {bye_count})",
                details={
                    "round": expected_starting,
                    "current": actual_count,
                    "expected": expected_count,
                    "bye_count": bye_count,
                    "participant_count": participant_count
                }
            ))
    elif expected_starting and expected_starting not in normalized_bouts_by_round:
        # 시작 라운드가 정규화된 bouts_by_round에도 없음
        available_rounds = list(normalized_bouts_by_round.keys())
        issues.append(Issue(
            competition_cd=comp_cd,
            competition_name=comp_name,
            event_cd=event_cd,
            event_name=event_name,
            issue_type="MISSING_STARTING_ROUND",
            description=f"시작 라운드 {expected_starting} 없음. 가능한 라운드: {available_rounds}",
            details={
                "expected_starting": expected_starting,
                "available_rounds": available_rounds,
                "bracket_size": bracket_size
            }
        ))

    # 4. 각 라운드별 경기 수 검증
    for round_name, round_bouts in bouts_by_round.items():
        normalized = round_name.replace('전', '')
        expected_count = EXPECTED_BOUTS.get(normalized, 0)
        if expected_count and len(round_bouts) != expected_count:
            # 이미 시작 라운드에서 체크했으면 스킵
            if normalized == expected_starting:
                continue
            issues.append(Issue(
                competition_cd=comp_cd,
                competition_name=comp_name,
                event_cd=event_cd,
                event_name=event_name,
                issue_type="WRONG_ROUND_BOUT_COUNT",
                description=f"{round_name} 경기 수 불일치: 현재 {len(round_bouts)}, 예상 {expected_count}",
                details={
                    "round": round_name,
                    "current": len(round_bouts),
                    "expected": expected_count
                }
            ))

    return issues


async def test_all_events(session: aiohttp.ClientSession) -> Tuple[List[Issue], Dict[str, int]]:
    """모든 이벤트 테스트"""
    all_issues = []
    stats = {
        "total_competitions": 0,
        "total_events": 0,
        "events_with_de": 0,
        "events_with_issues": 0,
        "total_issues": 0
    }

    print("=" * 60)
    print("E2E 전체 테스트 시작")
    print("=" * 60)

    competitions = await get_all_competitions(session)
    stats["total_competitions"] = len(competitions)
    print(f"\n총 대회 수: {len(competitions)}")

    for comp_idx, comp in enumerate(competitions):
        comp_cd = comp.get('event_cd')
        comp_name = comp.get('name', 'Unknown')

        # 대회 상세 정보 조회 (이벤트 포함)
        comp_detail = await get_competition_detail(session, comp_cd)
        events = comp_detail.get('events', [])

        for event in events:
            stats["total_events"] += 1
            sub_event_cd = event.get('sub_event_cd')
            event_name = event.get('name', 'Unknown')

            # DE 브라켓 데이터 확인
            de_bracket = event.get('de_bracket', {})

            if de_bracket and de_bracket.get('seeding'):
                stats["events_with_de"] += 1

                # 검증
                issues = validate_de_bracket(
                    sub_event_cd, event_name, comp_cd, comp_name, de_bracket
                )

                if issues:
                    stats["events_with_issues"] += 1
                    stats["total_issues"] += len(issues)
                    all_issues.extend(issues)

        # 진행 상황 출력
        if (comp_idx + 1) % 10 == 0:
            print(f"  진행: {comp_idx + 1}/{len(competitions)} 대회 완료, 문제 {len(all_issues)}개 발견")

    return all_issues, stats


async def main():
    """메인 실행"""
    start_time = datetime.now()

    async with aiohttp.ClientSession() as session:
        # 서버 연결 테스트
        try:
            async with session.get(f"{BASE_URL}/") as resp:
                if resp.status != 200:
                    print(f"❌ 서버 연결 실패: {resp.status}")
                    return
        except Exception as e:
            print(f"❌ 서버 연결 실패: {e}")
            return

        print("✅ 서버 연결 성공")

        # 전체 테스트 실행
        issues, stats = await test_all_events(session)

    elapsed = (datetime.now() - start_time).total_seconds()

    # 결과 출력
    print("\n" + "=" * 60)
    print("테스트 결과")
    print("=" * 60)
    print(f"소요 시간: {elapsed:.1f}초")
    print(f"총 대회: {stats['total_competitions']}개")
    print(f"총 이벤트: {stats['total_events']}개")
    print(f"DE 데이터 있는 이벤트: {stats['events_with_de']}개")
    print(f"문제 있는 이벤트: {stats['events_with_issues']}개")
    print(f"총 문제 수: {stats['total_issues']}개")

    if issues:
        print("\n" + "=" * 60)
        print("발견된 문제 목록")
        print("=" * 60)

        # 문제 유형별 그룹화
        by_type = {}
        for issue in issues:
            if issue.issue_type not in by_type:
                by_type[issue.issue_type] = []
            by_type[issue.issue_type].append(issue)

        for issue_type, type_issues in by_type.items():
            print(f"\n### {issue_type} ({len(type_issues)}개)")
            for issue in type_issues[:10]:  # 각 유형당 최대 10개만 출력
                print(f"  - [{issue.event_cd}] {issue.event_name}")
                print(f"    대회: {issue.competition_name}")
                print(f"    문제: {issue.description}")
            if len(type_issues) > 10:
                print(f"  ... 외 {len(type_issues) - 10}개")

        # 결과 JSON 저장
        result = {
            "timestamp": datetime.now().isoformat(),
            "stats": stats,
            "issues": [
                {
                    "competition_cd": i.competition_cd,
                    "competition_name": i.competition_name,
                    "event_cd": i.event_cd,
                    "event_name": i.event_name,
                    "issue_type": i.issue_type,
                    "description": i.description,
                    "details": i.details
                }
                for i in issues
            ]
        }

        with open("/tmp/e2e_test_result.json", "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        print(f"\n결과 저장: /tmp/e2e_test_result.json")
    else:
        print("\n✅ 모든 테스트 통과!")

    return issues, stats


if __name__ == "__main__":
    asyncio.run(main())
