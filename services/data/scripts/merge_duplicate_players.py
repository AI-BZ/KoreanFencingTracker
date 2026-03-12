"""
중복 선수 레코드 병합 스크립트

동일 선수가 소속 변경으로 인해 여러 레코드로 분리된 경우를 병합합니다.

사용법:
    # Dry-run (실제 변경 없이 확인만)
    python scripts/merge_duplicate_players.py --dry-run

    # 실제 병합 실행
    python scripts/merge_duplicate_players.py --execute

    # 특정 선수만 병합
    python scripts/merge_duplicate_players.py --player "김애린" --execute
"""

import os
import sys
import json
import argparse
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client, Client

load_dotenv()


class PlayerMerger:
    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.supabase: Client = create_client(
            os.getenv("SUPABASE_URL"),
            os.getenv("SUPABASE_KEY")
        )
        self.merge_count = 0
        self.skip_count = 0
        self.error_count = 0

        # 캐시: events와 competitions를 한 번만 조회
        self._events_cache = None
        self._comp_dates_cache = None

    def _load_events_cache(self):
        """events 데이터를 한 번만 로드 (선수명으로 인덱싱)"""
        if self._events_cache is not None:
            return

        print("  이벤트 데이터 로딩 중...")

        # competitions 조회
        competitions = self.supabase.table('competitions').select('id, start_date').execute()
        self._comp_dates_cache = {c['id']: c['start_date'] for c in competitions.data}

        # events 조회 (페이지네이션 - 작은 배치)
        all_events = []
        offset = 0
        page_size = 200  # raw_data가 크기 때문에 작은 배치로

        while True:
            result = self.supabase.table('events').select(
                'id, event_name, gender, age_group, weapon, raw_data, competition_id'
            ).range(offset, offset + page_size - 1).execute()

            if not result.data:
                break
            all_events.extend(result.data)
            if len(result.data) < page_size:
                break
            offset += page_size

        # 선수명으로 인덱싱
        from collections import defaultdict
        self._events_cache = defaultdict(list)  # player_name -> [event_details]

        for event in all_events:
            if not event.get('raw_data'):
                continue

            raw_data = event['raw_data']
            comp_date = self._comp_dates_cache.get(event['competition_id'])
            if not comp_date:
                continue

            def add_player(name, team):
                if name and team:
                    self._events_cache[name].append({
                        'date': comp_date,
                        'team': team,
                        'gender': event.get('gender'),
                        'age_group': event.get('age_group'),
                        'weapon': event.get('weapon'),
                        'event_name': event.get('event_name')
                    })

            # 1. final_rankings
            for r in raw_data.get('final_rankings', []):
                add_player(r.get('name', ''), r.get('team', ''))

            # 2. pool_rounds
            for pool in raw_data.get('pool_rounds', []):
                for r in pool.get('results', []):
                    add_player(r.get('name', ''), r.get('team', ''))

            # 3. de_bracket.seeding
            de_bracket = raw_data.get('de_bracket', {})
            for r in de_bracket.get('seeding', []):
                add_player(r.get('name', ''), r.get('team', ''))

        print(f"    {len(all_events)}개 이벤트에서 {len(self._events_cache)}명 선수 인덱싱 완료")

    def find_duplicate_players(self, player_name: Optional[str] = None) -> list:
        """동일 이름으로 여러 레코드가 있는 선수 찾기"""
        from collections import defaultdict

        print("  중복 선수 검색 중...")

        # Supabase에서 활성 선수 조회
        query = self.supabase.table('players').select('id, player_name, team_name, is_active, merged_into')

        if player_name:
            query = query.eq('player_name', player_name)

        # merged_into가 null인 것만 (아직 병합 안된 것)
        query = query.is_('merged_into', 'null')

        # 페이지네이션으로 전체 조회
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

        print(f"    총 {len(all_players)}명 조회됨")

        # Python에서 그룹화
        grouped = defaultdict(list)
        for p in all_players:
            # is_active가 False가 아닌 것만
            if p.get('is_active') != False:
                grouped[p['player_name']].append(p)

        # 중복 찾기 (다른 소속으로 2개 이상 레코드)
        duplicates = []
        for name, records in grouped.items():
            teams = set(r['team_name'] for r in records if r.get('team_name'))
            if len(records) > 1 and len(teams) > 1:
                duplicates.append({
                    'player_name': name,
                    'record_count': len(records),
                    'player_ids': [r['id'] for r in records],
                    'teams': list(teams)
                })

        print(f"    중복 선수 {len(duplicates)}명 발견")
        return sorted(duplicates, key=lambda x: -x['record_count'])

    def get_player_team_history(self, player_name: str) -> tuple:
        """
        캐시된 events 데이터에서 선수의 소속별 출전 기간 추출

        핵심 로직: 이전 소속으로 복귀하는 경우를 별도 기간으로 처리
        - 날짜순 정렬 후 순차 처리
        - 소속 변경 시 현재 기간 종료, 새 기간 시작
        - 같은 소속으로 복귀해도 새로운 기간으로 기록

        Returns:
            (team_history, event_details): 소속 이력과 상세 출전 정보

        Example:
            Input events: [
                (2022-03, 최병철펜싱클럽), (2024-04, 최병철펜싱클럽),
                (2025-08, 올즈윈스포츠), (2025-10, 최병철펜싱클럽)
            ]
            Output history: [
                {team: 최병철펜싱클럽, first_seen: 2022-03, last_seen: 2024-04},  # 1차
                {team: 올즈윈스포츠, first_seen: 2025-08, last_seen: 2025-08},    # 이적
                {team: 최병철펜싱클럽, first_seen: 2025-10, last_seen: 2025-10}   # 복귀
            ]
        """
        # 캐시 로드 (최초 1회만)
        self._load_events_cache()

        # 캐시에서 선수 데이터 조회
        raw_events = self._events_cache.get(player_name, [])

        # 중복 제거 (date+team+weapon 조합)
        seen = set()
        event_details = []
        for e in raw_events:
            key = (e['date'], e['team'], e['weapon'])
            if key not in seen:
                seen.add(key)
                event_details.append(e)

        if not event_details:
            return [], event_details

        # 날짜순 정렬 (핵심: 시간 순서대로 처리해야 복귀 감지 가능)
        sorted_events = sorted(event_details, key=lambda x: x['date'])

        # 연속된 기간별로 그룹화 (소속 변경 시 새 기간 시작)
        history = []
        current_period = None

        for e in sorted_events:
            team = e['team']
            date = e['date']

            if current_period is None:
                # 첫 번째 이벤트: 새 기간 시작
                current_period = {
                    'team': team,
                    'first_seen': date,
                    'last_seen': date,
                    'count': 1
                }
            elif current_period['team'] == team:
                # 같은 소속: 현재 기간 연장
                current_period['last_seen'] = date
                current_period['count'] += 1
            else:
                # 소속 변경: 현재 기간 종료, 새 기간 시작
                history.append(current_period)
                current_period = {
                    'team': team,
                    'first_seen': date,
                    'last_seen': date,
                    'count': 1
                }

        # 마지막 기간 추가
        if current_period is not None:
            history.append(current_period)

        return history, event_details

    def is_likely_same_person(self, event_details: list) -> tuple:
        """
        동명이인 여부 판별

        Returns:
            (is_same_person, reason): 동일인 여부와 판별 이유
        """
        if not event_details:
            return False, "출전 기록 없음"

        # 1. 성별 일관성 검사
        genders = set(e['gender'] for e in event_details if e.get('gender'))
        if len(genders) > 1:
            return False, f"성별 불일치: {genders}"

        # 2. 무기 + 소속 조합 검사
        # 다른 무기 + 다른 소속 = 동명이인
        weapons = set(e['weapon'] for e in event_details if e.get('weapon'))

        if len(weapons) > 2:
            return False, f"무기 3종 이상: {weapons}"

        if len(weapons) >= 2:
            # 무기별 소속 그룹화
            weapon_teams = {}
            for e in event_details:
                weapon = e.get('weapon')
                team = e.get('team')
                if weapon and team:
                    if weapon not in weapon_teams:
                        weapon_teams[weapon] = set()
                    weapon_teams[weapon].add(team)

            # 무기별 소속 교집합 확인
            if len(weapon_teams) >= 2:
                team_sets = list(weapon_teams.values())
                common_teams = team_sets[0]
                for ts in team_sets[1:]:
                    common_teams = common_teams & ts

                # 교집합 없음 = 각 무기마다 완전히 다른 소속 = 동명이인
                if not common_teams:
                    return False, f"무기별 소속 불일치: {weapon_teams}"

        # 3. 나이그룹 연속성 검사
        # 초등(1) < 중등(2) < 고등(3) < 대학(4) < 일반(5)
        age_order = {
            '초등': 1, '초등부': 1, 'ES': 1, 'E1': 1, 'E2': 1, 'E3': 1,
            '중등': 2, '중등부': 2, '여중': 2, '남중': 2, 'MS': 2, 'M1': 2, 'M2': 2, 'M3': 2,
            '고등': 3, '고등부': 3, '여고': 3, '남고': 3, 'HS': 3, 'H1': 3, 'H2': 3, 'H3': 3,
            '대학': 4, '대학부': 4, 'UNI': 4, '여대': 4, '남대': 4,
            '일반': 5, '일반부': 5, '시니어': 5, 'GEN': 5,
            'U13': 1, 'U15': 2, 'U17': 2, 'U20': 3, 'U23': 4
        }

        sorted_events = sorted(event_details, key=lambda x: x['date'])
        max_order_reached = 0  # 도달한 최고 나이그룹

        for e in sorted_events:
            age_group = e.get('age_group', '')
            current_order = 0
            for key, order in age_order.items():
                if key in str(age_group):
                    current_order = order
                    break

            if current_order > 0:
                # 대학/일반(4+)에서 고등 이하(3-)로 역행하면 즉시 동명이인
                # 성인이 학생 대회에 나갈 수 없음
                if max_order_reached >= 4 and current_order <= 3:
                    return False, f"나이그룹 심각한 역행: 대학/일반 → {age_group}"

                # 2단계 이상 역행도 동명이인 (예: 고등→초등)
                if max_order_reached > 0 and current_order < max_order_reached - 1:
                    return False, f"나이그룹 2단계 이상 역행: {max_order_reached} → {current_order}"

                max_order_reached = max(max_order_reached, current_order)

        # 4. 소속 수 검사 (너무 많으면 동명이인)
        teams = set(e['team'] for e in event_details)
        if len(teams) > 5:
            # 5개 초과 소속은 동명이인 가능성 매우 높음
            return False, f"소속 {len(teams)}개 (동명이인 가능성 높음)"

        # 5. 기간 대비 소속 수 검사
        if sorted_events:
            first_date = sorted_events[0]['date']
            last_date = sorted_events[-1]['date']
            try:
                from datetime import datetime
                d1 = datetime.strptime(first_date, '%Y-%m-%d')
                d2 = datetime.strptime(last_date, '%Y-%m-%d')
                years = (d2 - d1).days / 365

                # 1년에 2개 이상 소속 변경은 비정상
                if years > 0 and len(teams) / years > 2:
                    return False, f"{years:.1f}년간 {len(teams)}개 소속 (연평균 {len(teams)/years:.1f}개)"
            except:
                pass

        return True, f"동일인 판정 (성별:{genders}, 무기:{weapons}, 소속:{len(teams)}개)"

    def determine_main_record(self, player_ids: list, team_history: list) -> tuple:
        """
        메인 레코드 결정: 가장 최근 대회의 소속을 가진 레코드

        Returns:
            (main_id, merge_ids): 메인 레코드 ID와 병합할 레코드 ID 리스트
        """
        if not team_history:
            return None, []

        # 가장 최근 소속
        latest_team = team_history[-1]['team']

        # 해당 소속의 레코드 찾기
        players = self.supabase.table('players').select('id, team_name').in_('id', player_ids).execute()

        main_id = None
        merge_ids = []

        for p in players.data:
            if p['team_name'] == latest_team:
                main_id = p['id']
            else:
                merge_ids.append(p['id'])

        # 메인을 못찾았으면 가장 낮은 ID를 메인으로
        if main_id is None and player_ids:
            main_id = min(player_ids)
            merge_ids = [pid for pid in player_ids if pid != main_id]

        return main_id, merge_ids

    def merge_player(self, player_name: str, player_ids: list) -> bool:
        """단일 선수의 중복 레코드 병합"""

        print(f"\n{'='*60}")
        print(f"선수: {player_name}")
        print(f"레코드 IDs: {player_ids}")

        # 1. 소속 이력 추출
        team_history, event_details = self.get_player_team_history(player_name)

        if not team_history:
            print(f"  ⚠️ 대회 출전 기록 없음 - 스킵")
            self.skip_count += 1
            return False

        # 2. 동명이인 검사
        is_same, reason = self.is_likely_same_person(event_details)
        if not is_same:
            print(f"  ⚠️ 동명이인으로 판정 - 스킵")
            print(f"     사유: {reason}")
            self.skip_count += 1
            return False

        print(f"  ✅ {reason}")
        print(f"  소속 이력:")
        for th in team_history:
            print(f"    - {th['team']}: {th['first_seen']} ~ {th['last_seen']} ({th['count']}회)")

        # 2. 메인 레코드 결정
        main_id, merge_ids = self.determine_main_record(player_ids, team_history)

        if not main_id:
            print(f"  ⚠️ 메인 레코드를 결정할 수 없음 - 스킵")
            self.skip_count += 1
            return False

        latest_team = team_history[-1]['team']
        print(f"  → 메인 레코드: {main_id} ({latest_team})")
        print(f"  → 병합 대상: {merge_ids}")

        if self.dry_run:
            print(f"  [DRY-RUN] 실제 변경 없음")
            self.merge_count += 1
            return True

        # 3. 실제 병합 실행
        try:
            # 3-1. 메인 레코드 업데이트
            history_json = [
                {
                    'team': th['team'],
                    'first_seen': th['first_seen'],
                    'last_seen': th['last_seen']
                }
                for th in team_history
            ]

            self.supabase.table('players').update({
                'team_name': latest_team,
                'team_history': history_json,
                'updated_at': datetime.now().isoformat()
            }).eq('id', main_id).execute()

            print(f"  ✅ 메인 레코드 업데이트 완료")

            # 3-2. 중복 레코드 비활성화
            for merge_id in merge_ids:
                self.supabase.table('players').update({
                    'is_active': False,
                    'merged_into': main_id,
                    'updated_at': datetime.now().isoformat()
                }).eq('id', merge_id).execute()

            print(f"  ✅ {len(merge_ids)}개 레코드 병합 완료")
            self.merge_count += 1
            return True

        except Exception as e:
            print(f"  ❌ 오류 발생: {e}")
            self.error_count += 1
            return False

    def run(self, player_name: Optional[str] = None, limit: int = 100):
        """병합 실행"""

        print(f"\n{'#'*60}")
        print(f"# 중복 선수 레코드 병합")
        print(f"# 모드: {'DRY-RUN (실제 변경 없음)' if self.dry_run else '실제 실행'}")
        print(f"{'#'*60}")

        # 중복 선수 찾기
        duplicates = self.find_duplicate_players(player_name)

        print(f"\n발견된 중복 선수: {len(duplicates)}명")

        if limit:
            duplicates = duplicates[:limit]
            print(f"처리 대상: {len(duplicates)}명 (limit={limit})")

        # 각 선수 병합
        for dup in duplicates:
            self.merge_player(dup['player_name'], dup['player_ids'])

        # 결과 요약
        print(f"\n{'='*60}")
        print(f"# 결과 요약")
        print(f"{'='*60}")
        print(f"  병합 완료: {self.merge_count}명")
        print(f"  스킵: {self.skip_count}명")
        print(f"  오류: {self.error_count}명")

        if self.dry_run:
            print(f"\n⚠️ DRY-RUN 모드였습니다. 실제 실행하려면 --execute 옵션을 사용하세요.")


def main():
    parser = argparse.ArgumentParser(description='중복 선수 레코드 병합')
    parser.add_argument('--dry-run', action='store_true', default=True,
                        help='실제 변경 없이 확인만 (기본값)')
    parser.add_argument('--execute', action='store_true',
                        help='실제 병합 실행')
    parser.add_argument('--player', type=str,
                        help='특정 선수만 처리')
    parser.add_argument('--limit', type=int, default=100,
                        help='처리할 최대 선수 수 (기본값: 100)')

    args = parser.parse_args()

    # --execute가 있으면 dry_run=False
    dry_run = not args.execute

    merger = PlayerMerger(dry_run=dry_run)
    merger.run(player_name=args.player, limit=args.limit)


if __name__ == '__main__':
    main()
