"""
team_history 검증 스크립트

선수의 실제 대회 기록에서 팀 순서를 재구성하여 team_history와 비교합니다.
특히 A->B->A (원래 팀으로 복귀) 패턴을 감지합니다.

사용법:
    # 전체 분석 실행
    python scripts/validate_team_history.py

    # 특정 선수만 분석
    python scripts/validate_team_history.py --player "박소윤"

    # 상세 출력
    python scripts/validate_team_history.py --verbose

    # JSON 형식으로 결과 저장
    python scripts/validate_team_history.py --output results.json
"""

import os
import sys
import json
import argparse
from datetime import datetime
from collections import defaultdict
from typing import Optional, Dict, List, Tuple, Any

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()


class TeamHistoryValidator:
    """선수의 team_history와 실제 대회 기록을 비교 검증"""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.supabase: Client = create_client(
            os.getenv("SUPABASE_URL"),
            os.getenv("SUPABASE_KEY")
        )

        # 캐시
        self._events_cache: Optional[Dict[str, List[Dict]]] = None
        self._comp_dates_cache: Optional[Dict[int, str]] = None

        # 통계
        self.stats = {
            "total_players_with_history": 0,
            "players_with_multiple_teams": 0,
            "players_with_return_pattern": 0,
            "players_with_mismatch": 0,
            "mismatch_details": []
        }

    def _log(self, message: str):
        """verbose 모드일 때만 출력"""
        if self.verbose:
            print(message)

    def _load_events_cache(self):
        """events 데이터를 한 번만 로드 (선수명으로 인덱싱)"""
        if self._events_cache is not None:
            return

        print("이벤트 데이터 로딩 중...")

        # competitions 조회
        competitions = self.supabase.table('competitions').select('id, start_date').execute()
        self._comp_dates_cache = {c['id']: c['start_date'] for c in competitions.data}

        # events 조회 (페이지네이션)
        all_events = []
        offset = 0
        page_size = 200

        while True:
            result = self.supabase.table('events').select(
                'id, event_name, raw_data, competition_id'
            ).range(offset, offset + page_size - 1).execute()

            if not result.data:
                break
            all_events.extend(result.data)
            print(f"  로딩: {len(all_events)} 이벤트...")
            if len(result.data) < page_size:
                break
            offset += page_size

        print(f"  총 {len(all_events)} 이벤트 로드 완료")

        # 선수명으로 인덱싱 (date, team 정보 추출)
        self._events_cache = defaultdict(list)

        for event in all_events:
            if not event.get('raw_data'):
                continue

            raw_data = event['raw_data']
            comp_date = self._comp_dates_cache.get(event['competition_id'])
            if not comp_date:
                continue

            # 선수 정보 추출 함수
            def add_player(name: str, team: str):
                if name and team:
                    self._events_cache[name].append({
                        'date': comp_date,
                        'team': team,
                        'event_id': event['id']
                    })

            # 1. final_rankings에서 추출
            for ranking in raw_data.get('final_rankings', []):
                if isinstance(ranking, dict):
                    add_player(ranking.get('name'), ranking.get('team'))

            # 2. pool_total_ranking에서 추출
            for ranking in raw_data.get('pool_total_ranking', []):
                if isinstance(ranking, dict):
                    add_player(ranking.get('name'), ranking.get('team'))

            # 3. pool_rounds에서 추출
            for pool_round in raw_data.get('pool_rounds', []):
                if isinstance(pool_round, dict):
                    for pool in pool_round.get('pools', []):
                        if isinstance(pool, dict):
                            for fencer in pool.get('fencers', []):
                                if isinstance(fencer, dict):
                                    add_player(fencer.get('name'), fencer.get('team'))

        print(f"  {len(self._events_cache)} 명의 선수 인덱싱 완료")

    def _reconstruct_team_sequence(self, player_name: str) -> List[Dict]:
        """
        실제 대회 기록에서 선수의 팀 순서를 시간순으로 재구성

        Returns:
            [{'team': '팀명', 'first_seen': 'YYYY-MM-DD', 'last_seen': 'YYYY-MM-DD'}, ...]
        """
        self._load_events_cache()

        events = self._events_cache.get(player_name, [])
        if not events:
            return []

        # 날짜순 정렬
        sorted_events = sorted(events, key=lambda x: x['date'])

        # 연속된 팀 구간 생성
        sequence = []
        current_team = None
        current_start = None
        current_end = None

        for event in sorted_events:
            team = event['team']
            date = event['date']

            if team != current_team:
                # 이전 팀 구간 저장
                if current_team is not None:
                    sequence.append({
                        'team': current_team,
                        'first_seen': current_start,
                        'last_seen': current_end
                    })
                # 새 팀 구간 시작
                current_team = team
                current_start = date
                current_end = date
            else:
                # 같은 팀 - 종료일 갱신
                current_end = date

        # 마지막 팀 구간 저장
        if current_team is not None:
            sequence.append({
                'team': current_team,
                'first_seen': current_start,
                'last_seen': current_end
            })

        return sequence

    def _detect_return_pattern(self, sequence: List[Dict]) -> List[Dict]:
        """
        A->B->A 패턴 (원래 팀으로 복귀) 감지

        Returns:
            [{'original_team': 'A', 'intermediate_team': 'B', 'return_index': 2}, ...]
        """
        patterns = []
        team_first_occurrence = {}

        for i, entry in enumerate(sequence):
            team = entry['team']

            if team in team_first_occurrence:
                # 이전에 같은 팀이 있었음 -> A->...->A 패턴
                first_idx = team_first_occurrence[team]

                # 그 사이에 다른 팀이 있었는지 확인
                intermediate_teams = []
                for j in range(first_idx + 1, i):
                    if sequence[j]['team'] != team:
                        intermediate_teams.append(sequence[j]['team'])

                if intermediate_teams:
                    patterns.append({
                        'original_team': team,
                        'intermediate_teams': intermediate_teams,
                        'first_occurrence_index': first_idx,
                        'return_index': i,
                        'first_period': f"{sequence[first_idx]['first_seen']} ~ {sequence[first_idx]['last_seen']}",
                        'return_period': f"{entry['first_seen']} ~ {entry['last_seen']}"
                    })
            else:
                team_first_occurrence[team] = i

        return patterns

    def _normalize_team_name(self, team: str) -> str:
        """팀명 정규화 (비교용)"""
        if not team:
            return ""
        # 공백 제거, 소문자 변환
        return team.replace(" ", "").lower()

    def _compare_sequences(
        self,
        actual_sequence: List[Dict],
        stored_history: List[Dict]
    ) -> Dict:
        """
        실제 시퀀스와 저장된 team_history 비교

        Returns:
            {
                'match': bool,
                'differences': [...],
                'actual_teams': [...],
                'stored_teams': [...]
            }
        """
        actual_teams = [self._normalize_team_name(s['team']) for s in actual_sequence]
        stored_teams = [self._normalize_team_name(s.get('team', '')) for s in stored_history]

        differences = []

        # 길이 차이
        if len(actual_teams) != len(stored_teams):
            differences.append({
                'type': 'length_mismatch',
                'actual_count': len(actual_teams),
                'stored_count': len(stored_teams)
            })

        # 팀 순서 비교
        max_len = max(len(actual_teams), len(stored_teams))
        for i in range(max_len):
            actual = actual_teams[i] if i < len(actual_teams) else None
            stored = stored_teams[i] if i < len(stored_teams) else None

            if actual != stored:
                differences.append({
                    'type': 'team_mismatch',
                    'position': i,
                    'actual': actual_sequence[i]['team'] if i < len(actual_sequence) else None,
                    'stored': stored_history[i].get('team') if i < len(stored_history) else None
                })

        return {
            'match': len(differences) == 0,
            'differences': differences,
            'actual_teams': [s['team'] for s in actual_sequence],
            'stored_teams': [s.get('team') for s in stored_history]
        }

    def validate_player(self, player_id: int, player_name: str, team_history: List[Dict]) -> Dict:
        """단일 선수의 team_history 검증"""

        # 실제 대회 기록에서 팀 순서 재구성
        actual_sequence = self._reconstruct_team_sequence(player_name)

        if not actual_sequence:
            return {
                'player_id': player_id,
                'player_name': player_name,
                'status': 'no_events',
                'has_return_pattern': False,
                'return_patterns': [],
                'comparison': {'match': True, 'differences': []},
                'message': '대회 기록 없음'
            }

        # A->B->A 패턴 감지
        return_patterns = self._detect_return_pattern(actual_sequence)

        # 저장된 history와 비교
        comparison = self._compare_sequences(actual_sequence, team_history)

        result = {
            'player_id': player_id,
            'player_name': player_name,
            'actual_sequence': actual_sequence,
            'stored_history': team_history,
            'has_return_pattern': len(return_patterns) > 0,
            'return_patterns': return_patterns,
            'comparison': comparison,
            'status': 'ok' if comparison['match'] else 'mismatch'
        }

        return result

    def validate_all_players(self, player_filter: Optional[str] = None) -> Dict:
        """모든 선수의 team_history 검증"""

        print("선수 데이터 조회 중...")

        # team_history가 있는 선수 조회
        query = self.supabase.table('players').select(
            'id, player_name, team_name, team_history'
        ).not_.is_('team_history', 'null')

        if player_filter:
            query = query.ilike('player_name', f'%{player_filter}%')

        # 페이지네이션
        all_players = []
        offset = 0
        page_size = 1000

        while True:
            result = query.range(offset, offset + page_size - 1).execute()
            if not result.data:
                break
            all_players.extend(result.data)
            if len(result.data) < page_size:
                break
            offset += page_size

        print(f"총 {len(all_players)} 명의 선수 조회 완료")

        self.stats["total_players_with_history"] = len(all_players)

        # 이벤트 캐시 로드
        self._load_events_cache()

        # 각 선수 검증
        results = []
        return_pattern_players = []
        mismatch_players = []

        for i, player in enumerate(all_players):
            if (i + 1) % 500 == 0:
                print(f"  진행: {i + 1}/{len(all_players)} 선수 검증 중...")

            team_history = player.get('team_history', [])

            # team_history가 비어있거나 1개만 있으면 건너뜀
            if not team_history or len(team_history) <= 1:
                continue

            self.stats["players_with_multiple_teams"] += 1

            result = self.validate_player(
                player['id'],
                player['player_name'],
                team_history
            )

            if result['has_return_pattern']:
                self.stats["players_with_return_pattern"] += 1
                return_pattern_players.append(result)
                self._log(f"\n[복귀 패턴] {player['player_name']}:")
                for pattern in result['return_patterns']:
                    self._log(f"  {pattern['original_team']} -> {pattern['intermediate_teams']} -> {pattern['original_team']}")
                    self._log(f"    첫 소속: {pattern['first_period']}")
                    self._log(f"    복귀 후: {pattern['return_period']}")

            if result['status'] == 'mismatch':
                self.stats["players_with_mismatch"] += 1
                mismatch_players.append(result)
                self._log(f"\n[불일치] {player['player_name']}:")
                self._log(f"  실제: {result['comparison']['actual_teams']}")
                self._log(f"  저장: {result['comparison']['stored_teams']}")
                for diff in result['comparison']['differences']:
                    self._log(f"  차이: {diff}")

            results.append(result)

        return {
            'stats': self.stats,
            'return_pattern_players': return_pattern_players,
            'mismatch_players': mismatch_players,
            'all_results': results if self.verbose else None
        }

    def print_summary(self, results: Dict):
        """검증 결과 요약 출력"""
        stats = results['stats']

        print("\n" + "=" * 60)
        print("Team History 검증 결과 요약")
        print("=" * 60)
        print(f"총 team_history 보유 선수: {stats['total_players_with_history']:,}명")
        print(f"2개 이상 팀 이력 선수: {stats['players_with_multiple_teams']:,}명")
        print(f"복귀 패턴 (A->B->A) 선수: {stats['players_with_return_pattern']:,}명")
        print(f"불일치 선수: {stats['players_with_mismatch']:,}명")
        print("=" * 60)

        # 복귀 패턴 상세
        if results['return_pattern_players']:
            print("\n[복귀 패턴 선수 상위 20명]")
            for player in results['return_pattern_players'][:20]:
                patterns = player['return_patterns']
                print(f"\n  {player['player_name']} (ID: {player['player_id']}):")
                for pattern in patterns:
                    print(f"    {pattern['original_team']} -> {pattern['intermediate_teams']} -> {pattern['original_team']}")

        # 불일치 상세
        if results['mismatch_players']:
            print("\n[불일치 선수 상위 20명]")
            for player in results['mismatch_players'][:20]:
                print(f"\n  {player['player_name']} (ID: {player['player_id']}):")
                print(f"    실제: {player['comparison']['actual_teams']}")
                print(f"    저장: {player['comparison']['stored_teams']}")


def main():
    parser = argparse.ArgumentParser(description='team_history 검증 스크립트')
    parser.add_argument('--player', type=str, help='특정 선수명으로 필터')
    parser.add_argument('--verbose', '-v', action='store_true', help='상세 출력')
    parser.add_argument('--output', '-o', type=str, help='JSON 결과 파일 경로')

    args = parser.parse_args()

    validator = TeamHistoryValidator(verbose=args.verbose)
    results = validator.validate_all_players(player_filter=args.player)

    validator.print_summary(results)

    if args.output:
        # JSON 저장시 all_results는 제외 (너무 큼)
        output_data = {
            'stats': results['stats'],
            'return_pattern_players': [
                {
                    'player_id': p['player_id'],
                    'player_name': p['player_name'],
                    'return_patterns': p['return_patterns'],
                    'actual_sequence': p['actual_sequence'],
                    'stored_history': p['stored_history']
                }
                for p in results['return_pattern_players']
            ],
            'mismatch_players': [
                {
                    'player_id': p['player_id'],
                    'player_name': p['player_name'],
                    'comparison': p['comparison'],
                    'actual_sequence': p['actual_sequence'],
                    'stored_history': p['stored_history']
                }
                for p in results['mismatch_players']
            ]
        }

        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2, default=str)

        print(f"\n결과가 {args.output}에 저장되었습니다.")


if __name__ == '__main__':
    main()
