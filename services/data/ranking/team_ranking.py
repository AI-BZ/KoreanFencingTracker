"""
팀 랭킹 계산 모듈

모든 소속 선수의 개인전 포인트를 전부 합산 + 단체전 보너스.
포인트 체계 자체가 상위 순위에 극단적으로 집중되어 있어
(1위=700, 10위=133) 캡 없이도 소수 정예팀이 대팀을 이기는 구조.

점수 체계:
- 개인전: 기존 calculate_points() 결과 재활용, 전원 합산
- 단체전: 참가자 수 기반 포인트 × 순위 비율
- 팀 점수 = 개인전 전원 합산 + 단체전 보너스
"""
from dataclasses import dataclass
from typing import List, Dict, Optional
from collections import defaultdict

from .calculator import (
    calculate_points,
    extract_weapon,
    extract_gender,
    extract_age_group,
    classify_competition_tier,
    RankingCalculator,
)


TOP_N_CAP = 0  # 0 = 캡 없음 (전원 합산)


TEAM_CATEGORIES = {
    'middle_school': '중학교',
    'high_school': '고등학교',
    'university': '대학교',
    'club': '클럽',
    'pro': '실업팀',
    'all': '전체',
}


def classify_team_category(team_name: str) -> str:
    """팀 이름으로 카테고리 분류"""
    if '중학교' in team_name or '중학' in team_name:
        return 'middle_school'
    if '고등학교' in team_name or '고교' in team_name:
        return 'high_school'
    if '대학교' in team_name or '대학' in team_name:
        return 'university'
    if any(kw in team_name for kw in ['클럽', '아카데미', '도장', '체육관', 'JJFA']):
        return 'club'
    if any(kw in team_name for kw in ['시청', '도청', '공사', '공단', '국군', '체육회']):
        return 'pro'
    return 'etc'


@dataclass
class TeamMemberResult:
    player_name: str
    rank: int
    total_participants: int
    points: float
    event_name: str
    competition_name: str
    competition_date: str


@dataclass
class TeamEventScore:
    team_name: str
    individual_points: float
    team_event_points: float
    total_points: float
    member_results: List[TeamMemberResult]
    member_count: int
    counted_count: int  # Top-N에 실제 반영된 수
    team_event_rank: Optional[int] = None
    team_event_name: Optional[str] = None


@dataclass
class TeamRanking:
    team_name: str
    total_points: float
    individual_sum: float
    team_event_sum: float
    event_count: int
    top_players: List[Dict]
    rank: int = 0
    member_count: int = 0


def calculate_team_scores_for_event(
    individual_rankings: List[Dict],
    team_event_rankings: Optional[List[Dict]] = None,
    competition_name: str = "",
    event_name: str = "",
    top_n: int = TOP_N_CAP,
) -> List[TeamEventScore]:
    """
    단일 이벤트(종목)의 팀별 점수 계산

    Args:
        individual_rankings: [{name, rank, team, ...}] 개인전 최종순위
        team_event_rankings: [{name(=팀명), rank, ...}] 단체전 최종순위 (있으면)
        competition_name: 대회명
        event_name: 종목명
        top_n: 0이면 전원 합산, 양수면 팀당 상위 N명만
    """
    total_participants = len(individual_rankings)
    if total_participants == 0:
        return []

    team_members = defaultdict(list)
    for r in individual_rankings:
        name = r.get('name', '')
        team = r.get('team', '')
        rank = r.get('rank', 999)
        if not team or not name:
            continue

        age = extract_age_group(event_name)
        tier = classify_competition_tier(competition_name)
        pts = calculate_points(
            tier=tier,
            final_rank=rank,
            total_participants=total_participants,
            age_group=age,
            competition_name=competition_name,
        )

        team_members[team].append(TeamMemberResult(
            player_name=name,
            rank=rank,
            total_participants=total_participants,
            points=pts,
            event_name=event_name,
            competition_name=competition_name,
            competition_date="",
        ))

    for members in team_members.values():
        members.sort(key=lambda x: x.points, reverse=True)

    effective_n = top_n if top_n > 0 else None  # None = 전원

    team_event_map = {}
    if team_event_rankings:
        total_teams = len(team_event_rankings)
        age = extract_age_group(event_name)
        tier = classify_competition_tier(competition_name)
        for tr in team_event_rankings:
            t_name = tr.get('name', '')
            t_rank = tr.get('rank', 999)
            if t_name:
                t_pts = calculate_points(
                    tier=tier,
                    final_rank=t_rank,
                    total_participants=total_teams,
                    age_group=age,
                    competition_name=competition_name,
                )
                team_event_map[t_name] = (t_rank, t_pts)

    results = []
    for team_name, members in team_members.items():
        counted = members[:effective_n] if effective_n else members
        ind_pts = sum(m.points for m in counted)

        te_rank, te_pts = team_event_map.get(team_name, (None, 0.0))

        total = ind_pts + te_pts
        results.append(TeamEventScore(
            team_name=team_name,
            individual_points=round(ind_pts, 1),
            team_event_points=round(te_pts, 1),
            total_points=round(total, 1),
            member_results=counted,
            member_count=len(members),
            counted_count=len(counted),
            team_event_rank=te_rank,
            team_event_name=event_name.replace('(개)', '(단)') if te_rank else None,
        ))

    results.sort(key=lambda x: x.total_points, reverse=True)
    return results


def calculate_competition_team_rankings(
    competition_data: Dict,
    weapon: Optional[str] = None,
    gender: Optional[str] = None,
    age_group: Optional[str] = None,
    top_n: int = TOP_N_CAP,
) -> List[TeamRanking]:
    """
    대회 전체의 팀 랭킹 (모든 종목 합산)

    Args:
        competition_data: 대회 데이터 (events 포함)
        weapon/gender/age_group: 필터 (None이면 전체)
        top_n: 종목당 팀 반영 선수 수
    """
    events = competition_data.get('events', [])
    comp_name = competition_data.get('name', '')
    team_scores = defaultdict(lambda: {
        'individual_sum': 0.0,
        'team_event_sum': 0.0,
        'event_count': 0,
        'top_players': [],
        'all_members': set(),
    })

    def _ev_name(e):
        return e.get('event_name') or e.get('name', '')

    individual_events = [e for e in events if '(개)' in _ev_name(e) or '개인' in _ev_name(e)]
    team_events = [e for e in events if '(단)' in _ev_name(e) or '단체' in _ev_name(e)]

    team_event_map = {}
    for te in team_events:
        fr = te.get('final_rankings') or (te.get('raw_data') or {}).get('final_rankings', [])
        if fr:
            base_name = _ev_name(te).replace('(단)', '').replace('단체', '').strip()
            team_event_map[base_name] = fr

    for ie in individual_events:
        ev_name = _ev_name(ie)
        ind_fr = ie.get('final_rankings') or (ie.get('raw_data') or {}).get('final_rankings', [])
        if not ind_fr:
            continue

        ev_weapon = extract_weapon(ev_name)
        ev_gender = extract_gender(ev_name)
        ev_age = extract_age_group(ev_name)

        if weapon and ev_weapon != weapon:
            continue
        if gender and ev_gender != gender:
            continue
        if age_group and ev_age != age_group:
            continue

        base_name = ev_name.replace('(개)', '').replace('개인', '').strip()
        te_fr = team_event_map.get(base_name)

        event_scores = calculate_team_scores_for_event(
            individual_rankings=ind_fr,
            team_event_rankings=te_fr,
            competition_name=comp_name,
            event_name=ev_name,
            top_n=top_n,
        )

        for es in event_scores:
            ts = team_scores[es.team_name]
            ts['individual_sum'] += es.individual_points
            ts['team_event_sum'] += es.team_event_points
            ts['event_count'] += 1
            for mr in es.member_results:
                ts['top_players'].append({
                    'player': mr.player_name,
                    'event': ev_name,
                    'rank': mr.rank,
                    'points': mr.points,
                })
                ts['all_members'].add(mr.player_name)

    rankings = []
    for team_name, ts in team_scores.items():
        total = ts['individual_sum'] + ts['team_event_sum']
        ts['top_players'].sort(key=lambda x: x['points'], reverse=True)
        rankings.append(TeamRanking(
            team_name=team_name,
            total_points=round(total, 1),
            individual_sum=round(ts['individual_sum'], 1),
            team_event_sum=round(ts['team_event_sum'], 1),
            event_count=ts['event_count'],
            top_players=ts['top_players'][:10],
            member_count=len(ts['all_members']),
        ))

    rankings.sort(key=lambda x: x.total_points, reverse=True)
    for i, r in enumerate(rankings, 1):
        r.rank = i

    return rankings


def calculate_season_team_rankings(
    ranking_calculator: 'RankingCalculator',
    year: int,
    weapon: Optional[str] = None,
    gender: Optional[str] = None,
    age_group: Optional[str] = None,
    top_n: int = TOP_N_CAP,
) -> List[TeamRanking]:
    """
    시즌(연도) 누적 팀 랭킹

    각 대회의 각 종목에서 팀별 Top-N 선수 점수를 누적 합산.
    """
    team_scores = defaultdict(lambda: {
        'individual_sum': 0.0,
        'team_event_sum': 0.0,
        'event_count': 0,
        'top_players': [],
        'all_members': set(),
        'competitions': set(),
    })

    for result in ranking_calculator.results:
        if result.competition_date.year != year:
            continue
        if weapon and result.weapon != weapon:
            continue
        if gender and result.gender != gender:
            continue
        if age_group and result.age_group != age_group:
            continue
        if result.age_group == 'NT':
            continue

        team = result.team
        if not team:
            continue

        comp_event_key = f"{result.competition_name}|{result.event_name}"
        if comp_event_key not in team_scores[team].get('_event_members', {}):
            if '_event_members' not in team_scores[team]:
                team_scores[team]['_event_members'] = defaultdict(list)
            team_scores[team]['_event_members'][comp_event_key] = []

        team_scores[team]['_event_members'][comp_event_key].append(result)

    final_scores = defaultdict(lambda: {
        'individual_sum': 0.0,
        'team_event_sum': 0.0,
        'event_count': 0,
        'top_players': [],
        'all_members': set(),
        'competitions': set(),
    })

    effective_n = top_n if top_n > 0 else None

    for team, ts in team_scores.items():
        event_members = ts.get('_event_members', {})
        for comp_event_key, results in event_members.items():
            results.sort(key=lambda r: r.points, reverse=True)
            counted = results[:effective_n] if effective_n else results

            for r in counted:
                final_scores[team]['individual_sum'] += r.points
                final_scores[team]['top_players'].append({
                    'player': r.player_name,
                    'event': r.event_name,
                    'competition': r.competition_name,
                    'rank': r.final_rank,
                    'points': r.points,
                })
                final_scores[team]['all_members'].add(r.player_name)
                final_scores[team]['competitions'].add(r.competition_name)

            final_scores[team]['event_count'] += 1

    rankings = []
    for team_name, ts in final_scores.items():
        total = ts['individual_sum'] + ts['team_event_sum']
        ts['top_players'].sort(key=lambda x: x['points'], reverse=True)
        rankings.append(TeamRanking(
            team_name=team_name,
            total_points=round(total, 1),
            individual_sum=round(ts['individual_sum'], 1),
            team_event_sum=round(ts['team_event_sum'], 1),
            event_count=ts['event_count'],
            top_players=ts['top_players'][:15],
            member_count=len(ts['all_members']),
        ))

    rankings.sort(key=lambda x: x.total_points, reverse=True)
    for i, r in enumerate(rankings, 1):
        r.rank = i

    return rankings
