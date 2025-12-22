"""
Player Identity Resolution System

Handles:
1. 동명이인 (Same name, different person): Different players with identical names
2. 소속변경 (Team change): Same player who changed teams over time

Identification Strategy:
- Group records by name
- Analyze temporal patterns (competition dates)
- Check for overlapping competitions (same event = different people)
- Track team transitions chronologically
- Consider weapon consistency

ID 체계 (2글자 국가코드):
- 선수: KOP00001 (KO=한국, P=Player, 00001=일련번호)
- 특별 ID: KOP00000 = 박소윤(최병철펜싱클럽) - 시스템 기준점
- 조직: KOC0001 (KO=한국, C=클럽), KOM0001 (중학교), KOH0001 (고등학교), KOV0001 (대학교), KOA0001 (실업팀)
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from datetime import datetime, date
from collections import defaultdict
import hashlib
import json
import re


# 소속 유형 판별
def get_team_type(team: str) -> str:
    """
    소속 유형 판별
    Returns: 'elementary', 'middle', 'high', 'university', 'club'
    """
    if not team:
        return 'club'

    # 초등학교
    if re.search(r'초등학교|초교', team):
        return 'elementary'
    # 중학교
    if re.search(r'중학교|중$', team):
        return 'middle'
    # 고등학교
    if re.search(r'고등학교|고$|체고', team):
        return 'high'
    # 대학교
    if re.search(r'대학교|대학$|대$', team):
        return 'university'
    # 클럽/동호회
    return 'club'


# 학교 유형 레벨 (진학 순서)
SCHOOL_LEVEL = {
    'elementary': 1,
    'middle': 2,
    'high': 3,
    'university': 4,
    'club': 0  # 클럽은 별도 트랙
}


@dataclass
class TeamRecord:
    """Record of a player's team affiliation at a specific time"""
    team: str
    team_id: Optional[str] = None  # 조직 ID (예: KC0001)
    team_en: Optional[str] = None  # 영문 팀명
    first_seen: str = ""  # ISO date string
    last_seen: str = ""   # ISO date string
    competition_count: int = 1


@dataclass
class MatchRecord:
    """Individual match record for head-to-head tracking"""
    competition_cd: str
    competition_name: str
    competition_date: str
    event_name: str
    round_type: str  # "pool" or "de"
    round_name: str  # "뿔 1", "32강전", etc.
    opponent_name: str
    opponent_team: str
    my_score: int
    opponent_score: int
    result: str  # "V" or "D"
    weapon: str


@dataclass
class PlayerProfile:
    """Complete player profile with identity resolution"""
    player_id: str  # Unique identifier
    name: str

    # English name (for international data matching)
    name_en: Optional[str] = None  # e.g., "Soyun Park"
    name_en_verified: bool = False  # True if verified against FIE/FencingTracker

    # External IDs for international data
    fie_id: Optional[str] = None  # FIE athlete ID
    fencingtracker_id: Optional[str] = None  # FencingTracker ID

    # Team history (chronologically ordered)
    team_history: List[TeamRecord] = field(default_factory=list)

    # Competition records
    competition_ids: Set[str] = field(default_factory=set)  # Set of competition IDs participated
    records: List[Dict] = field(default_factory=list)  # All competition results

    # Match records for head-to-head
    matches: List[MatchRecord] = field(default_factory=list)

    # Statistics
    weapons: Set[str] = field(default_factory=set)
    age_groups: Set[str] = field(default_factory=set)

    # Podium counts by season
    podium_by_season: Dict[str, Dict[str, int]] = field(default_factory=dict)

    @property
    def current_team(self) -> str:
        """Get most recent team"""
        if self.team_history:
            return self.team_history[-1].team
        return ""

    @property
    def teams(self) -> List[str]:
        """Get all teams (unique)"""
        return list(dict.fromkeys([t.team for t in self.team_history]))

    def add_team(self, team: str, date_str: str) -> None:
        """Add or update team affiliation"""
        if not team:
            return

        # Check if this is a continuation of an existing team
        for record in self.team_history:
            if record.team == team:
                # Update last_seen if this date is later
                if date_str > record.last_seen:
                    record.last_seen = date_str
                elif date_str < record.first_seen:
                    record.first_seen = date_str
                record.competition_count += 1
                return

        # New team - add to history
        self.team_history.append(TeamRecord(
            team=team,
            first_seen=date_str,
            last_seen=date_str
        ))

        # Sort by first_seen date
        self.team_history.sort(key=lambda x: x.first_seen)


@dataclass
class NameGroup:
    """Group of player records with the same name"""
    name: str
    records: List[Dict] = field(default_factory=list)  # Raw records from competitions
    profiles: List[PlayerProfile] = field(default_factory=list)  # Resolved profiles


class PlayerIdentityResolver:
    """
    Main class for resolving player identities across competitions.

    Resolution Algorithm:
    1. Group all player records by name
    2. For each name group:
       a. Sort records chronologically
       b. Check for overlapping competitions (different people indicator)
       c. Track team transitions
       d. Create separate profiles for clearly different people
       e. Merge profiles for same person with team changes
    """

    # 특별 ID 매핑: 시스템 기준점이 되는 선수
    # (이름, 팀들 중 하나): ID
    SPECIAL_PLAYER_IDS = {
        "박소윤": {
            "teams": ["최병철펜싱클럽"],  # 이 팀들 중 하나라도 속하면 매칭
            "id": "KOP00000",  # 모든 데이터의 근원/샘플링 기준점
        },
    }

    def __init__(self, country: str = "KO"):
        self.country = country  # 국가 코드 (KO=한국, JP=일본, CN=중국 등)
        self.name_groups: Dict[str, NameGroup] = {}
        self.profiles: Dict[str, PlayerProfile] = {}  # player_id -> profile
        self.name_to_profiles: Dict[str, List[str]] = {}  # name -> [player_id, ...]
        self._player_id_counter: int = 0  # 선수 ID 카운터
        self._legacy_id_map: Dict[str, str] = {}  # 기존 ID -> 새 ID 매핑
        self._special_ids_assigned: Set[str] = set()  # 이미 할당된 특별 ID

        # 조직 식별자 (지연 로딩)
        self._org_resolver = None

    def add_competition_data(self, competition_data: Dict) -> None:
        """Add competition data for player extraction"""
        comp = competition_data.get("competition", {})
        comp_cd = comp.get("event_cd", "")
        comp_name = comp.get("name", "")
        comp_date = comp.get("start_date", "")

        events = competition_data.get("events", [])

        for event in events:
            event_name = event.get("name", "")
            weapon = event.get("weapon", "")

            # Extract age group from event name
            age_group = self._extract_age_group(event_name)

            # Process pool results
            for pool in event.get("pool_rounds", []):
                for result in pool.get("results", []):
                    name = result.get("name", "")
                    team = result.get("team", "")

                    if name and name not in ["", "-"]:
                        self._add_player_record(
                            name=name,
                            team=team,
                            comp_cd=comp_cd,
                            comp_name=comp_name,
                            comp_date=comp_date,
                            event_name=event_name,
                            weapon=weapon,
                            age_group=age_group,
                            record_type="pool",
                            record=result
                        )

            # Process final rankings
            for ranking in event.get("final_rankings", []):
                name = ranking.get("name", "")
                team = ranking.get("team", "")

                if name and name not in ["", "-"]:
                    self._add_player_record(
                        name=name,
                        team=team,
                        comp_cd=comp_cd,
                        comp_name=comp_name,
                        comp_date=comp_date,
                        event_name=event_name,
                        weapon=weapon,
                        age_group=age_group,
                        record_type="ranking",
                        record=ranking
                    )

            # Process DE bracket
            de_bracket = event.get("de_bracket", {})
            for seeding in de_bracket.get("seeding", []):
                name = seeding.get("name", "")
                team = seeding.get("team", "")

                if name and name not in ["", "-"]:
                    self._add_player_record(
                        name=name,
                        team=team,
                        comp_cd=comp_cd,
                        comp_name=comp_name,
                        comp_date=comp_date,
                        event_name=event_name,
                        weapon=weapon,
                        age_group=age_group,
                        record_type="de_seeding",
                        record=seeding
                    )

    def _add_player_record(
        self,
        name: str,
        team: str,
        comp_cd: str,
        comp_name: str,
        comp_date: str,
        event_name: str,
        weapon: str,
        age_group: str,
        record_type: str,
        record: Dict
    ) -> None:
        """Add a player record to the name group"""
        if name not in self.name_groups:
            self.name_groups[name] = NameGroup(name=name)

        self.name_groups[name].records.append({
            "name": name,
            "team": team,
            "comp_cd": comp_cd,
            "comp_name": comp_name,
            "comp_date": comp_date,
            "event_name": event_name,
            "weapon": weapon,
            "age_group": age_group,
            "record_type": record_type,
            "record": record
        })

    def _extract_age_group(self, event_name: str) -> str:
        """Extract age group from event name"""
        import re
        patterns = [
            r"(\d+세이하부)",
            r"(초등부|중등부|고등부|대학부|일반부)",
            r"(U\d+)",
            r"(시니어|주니어|마스터)",
        ]

        for pattern in patterns:
            match = re.search(pattern, event_name)
            if match:
                return match.group(1)

        return ""

    def resolve_identities(self) -> int:
        """
        Main identity resolution algorithm.

        Strategy:
        1. FIRST: Group by weapons - completely different weapons = different people
        2. For each weapon group, identify clear splits (overlapping competitions)
        3. Group remaining records by team continuity
        4. Handle team transitions (same person, different teams)
        5. Assign special IDs for reference players

        Returns: Number of special IDs assigned
        """
        for name, group in self.name_groups.items():
            if not group.records:
                continue

            # Sort records by date
            sorted_records = sorted(group.records, key=lambda x: x["comp_date"])

            # Step 0: CRITICAL - Group by weapons first
            # Completely different weapons (e.g., 플러레 vs 사브르) = DEFINITELY different people
            weapon_groups = self._group_by_weapons(sorted_records)

            if len(weapon_groups) > 1:
                # Multiple weapon groups = definitely different people
                # Process each weapon group separately
                for weapon_key, weapon_records in weapon_groups.items():
                    overlapping_teams = self._find_overlapping_teams(weapon_records)
                    if overlapping_teams:
                        self._create_separate_profiles(name, weapon_records, overlapping_teams)
                    else:
                        # Check if we should still separate (e.g., different team types)
                        if self._should_separate_by_team_pattern(weapon_records):
                            pseudo_overlapping = self._create_pseudo_overlapping(weapon_records)
                            self._create_separate_profiles(name, weapon_records, pseudo_overlapping)
                        else:
                            self._create_single_profile(name, weapon_records)
            else:
                # Single weapon group - proceed with traditional algorithm
                # Step 1: Find overlapping competitions (definite different people)
                overlapping_teams = self._find_overlapping_teams(sorted_records)

                if overlapping_teams:
                    # Multiple people with same name
                    self._create_separate_profiles(name, sorted_records, overlapping_teams)
                else:
                    # Check for team pattern based separation
                    if self._should_separate_by_team_pattern(sorted_records):
                        pseudo_overlapping = self._create_pseudo_overlapping(sorted_records)
                        self._create_separate_profiles(name, sorted_records, pseudo_overlapping)
                    else:
                        # Likely same person with possible team changes
                        self._create_single_profile(name, sorted_records)

        # Post-resolution: Assign special IDs for reference players
        return self._assign_special_ids()

    def _group_by_weapons(self, records: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Group records by weapon sets.

        Key insight: A fencer typically specializes in ONE weapon.
        - Same weapon = could be same person
        - Completely different weapons = DEFINITELY different people

        Returns: Dict[weapon_key, records]
        - weapon_key is frozenset of weapons for that group
        """
        # First, get weapons per team
        team_weapons = defaultdict(set)
        team_records = defaultdict(list)

        for record in records:
            team = record.get("team", "")
            weapon = record.get("weapon", "")
            if team and weapon:
                team_weapons[team].add(weapon)
                team_records[team].append(record)

        if not team_weapons:
            return {"all": records}

        # Use Union-Find to group teams with overlapping weapons
        teams_list = list(team_weapons.keys())
        parent = {t: t for t in teams_list}

        def find(x):
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]

        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[py] = px

        # Union teams that share ANY weapon (could be same person)
        for i, t1 in enumerate(teams_list):
            for t2 in teams_list[i+1:]:
                # If weapons overlap, they COULD be the same person
                if team_weapons[t1].intersection(team_weapons[t2]):
                    union(t1, t2)

        # Group teams by root
        team_groups = defaultdict(list)
        for team in teams_list:
            root = find(team)
            team_groups[root].append(team)

        # If all teams are in one group, return single group
        if len(team_groups) == 1:
            return {"all": records}

        # Create weapon groups with their records
        result = {}
        for root, teams in team_groups.items():
            # Collect all weapons for this group
            group_weapons = set()
            group_records = []
            for team in teams:
                group_weapons.update(team_weapons[team])
                group_records.extend(team_records[team])

            # Add records without team
            for record in records:
                if not record.get("team"):
                    # Assign to matching weapon group or first group
                    if record.get("weapon") in group_weapons:
                        group_records.append(record)

            weapon_key = "_".join(sorted(group_weapons)) if group_weapons else "unknown"
            result[weapon_key] = group_records

        return result

    def _should_separate_by_team_pattern(self, records: List[Dict]) -> bool:
        """
        Check if records should be separated based on team patterns even without overlap.

        Separation indicators:
        1. School-type teams from different schools at same level active simultaneously
        2. Very long gap (>3 years) between teams with no progression logic
        """
        team_info = defaultdict(lambda: {"first": None, "last": None, "type": None})

        for record in records:
            team = record.get("team", "")
            date = record.get("comp_date", "")
            if not team or not date:
                continue

            if team_info[team]["first"] is None or date < team_info[team]["first"]:
                team_info[team]["first"] = date
            if team_info[team]["last"] is None or date > team_info[team]["last"]:
                team_info[team]["last"] = date
            team_info[team]["type"] = get_team_type(team)

        if len(team_info) < 2:
            return False

        teams_list = list(team_info.keys())

        # Check for simultaneous same-level schools (different schools)
        for i, t1 in enumerate(teams_list):
            info1 = team_info[t1]
            type1 = info1["type"]

            for t2 in teams_list[i+1:]:
                info2 = team_info[t2]
                type2 = info2["type"]

                # Same school level (both middle schools, both high schools)
                if type1 == type2 and type1 in ('middle', 'high', 'university'):
                    # Check for time overlap
                    if info1["first"] and info1["last"] and info2["first"] and info2["last"]:
                        # If time ranges overlap significantly, probably different people
                        overlap_start = max(info1["first"], info2["first"])
                        overlap_end = min(info1["last"], info2["last"])
                        if overlap_start <= overlap_end:
                            # Time overlap at same school level = different people
                            return True

        return False

    def _create_pseudo_overlapping(self, records: List[Dict]) -> Set[Tuple[str, str]]:
        """
        Create pseudo-overlapping set for teams that should be separated
        based on team pattern analysis (not actual competition overlap).
        """
        teams = set()
        for record in records:
            team = record.get("team", "")
            if team:
                teams.add(team)

        # Return all pairs as "overlapping" to force separation
        result = set()
        teams_list = list(teams)
        for i, t1 in enumerate(teams_list):
            for t2 in teams_list[i+1:]:
                result.add(tuple(sorted([t1, t2])))

        return result

    def _find_overlapping_teams(self, records: List[Dict]) -> Set[Tuple[str, str]]:
        """
        Find teams that appear in the same competition - indicating different people.
        Returns set of (team1, team2) pairs that are different people.
        """
        overlapping = set()

        # Group by competition
        comp_teams = defaultdict(set)
        for record in records:
            comp_cd = record["comp_cd"]
            team = record["team"]
            if team:
                comp_teams[comp_cd].add(team)

        # Find competitions with multiple teams for same name
        for comp_cd, teams in comp_teams.items():
            if len(teams) > 1:
                teams_list = list(teams)
                for i, t1 in enumerate(teams_list):
                    for t2 in teams_list[i+1:]:
                        overlapping.add(tuple(sorted([t1, t2])))

        return overlapping

    def _create_separate_profiles(
        self,
        name: str,
        records: List[Dict],
        overlapping_teams: Set[Tuple[str, str]]
    ) -> None:
        """Create separate profiles for clearly different people using Union-Find.

        Algorithm:
        1. Get all unique teams
        2. Use Union-Find to group teams that could be the same person
        3. Teams that overlap (same competition) = DIFFERENT people (don't union)
        4. Teams that don't overlap = COULD be same person (union them)
        5. CRITICAL: Before union, check that NO team in component A overlaps with ANY team in component B
        6. Create one profile per connected component
        """
        # Get all unique teams
        all_teams = set()
        team_records = defaultdict(list)
        for record in records:
            team = record["team"]
            if team:
                all_teams.add(team)
                team_records[team].append(record)

        if not all_teams:
            return

        teams_list = list(all_teams)

        # Union-Find data structure with component tracking
        parent = {team: team for team in teams_list}
        rank = {team: 0 for team in teams_list}
        # Track which teams are in each component (keyed by root)
        component_members = {team: {team} for team in teams_list}

        def find(x):
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]

        def union(x, y):
            px, py = find(x), find(y)
            if px == py:
                return True  # Already in same component
            if rank[px] < rank[py]:
                px, py = py, px
            parent[py] = px
            if rank[px] == rank[py]:
                rank[px] += 1
            # Merge component members
            component_members[px] = component_members[px] | component_members[py]
            del component_members[py]
            return True

        def can_union(x, y, overlapping_set):
            """Check if two teams can be unioned without violating overlap constraints."""
            px, py = find(x), find(y)
            if px == py:
                return True  # Already same component
            # Check if ANY team in component X overlaps with ANY team in component Y
            for tx in component_members[px]:
                for ty in component_members[py]:
                    if (tx, ty) in overlapping_set or (ty, tx) in overlapping_set:
                        return False  # Can't union - would violate overlap constraint
            return True

        # Build set of overlapping team pairs (definitely different people)
        overlapping_set = set()
        for t1, t2 in overlapping_teams:
            overlapping_set.add((t1, t2))
            overlapping_set.add((t2, t1))

        # Sort teams by first appearance date for sequential processing
        def get_first_date(team):
            dates = [r["comp_date"] for r in team_records[team] if r["comp_date"]]
            return min(dates) if dates else "9999"

        def get_weapons(team):
            """팀 레코드에서 무기 목록 추출"""
            return set(r["weapon"] for r in team_records[team] if r["weapon"])

        teams_sorted = sorted(teams_list, key=get_first_date)

        # Union teams that DON'T overlap (could be same person with team change)
        # Process in chronological order to prefer sequential team changes
        for i, team1 in enumerate(teams_sorted):
            for team2 in teams_sorted[i+1:]:
                # Skip if already in same component
                if find(team1) == find(team2):
                    continue

                # Skip if they definitely overlap (different people)
                if (team1, team2) in overlapping_set:
                    continue

                # CRITICAL: Check if union would violate any overlap constraint
                if not can_union(team1, team2, overlapping_set):
                    continue

                # ====== 강화된 동명이인 분리 로직 ======

                # 1. 소속 유형 확인
                type1 = get_team_type(team1)
                type2 = get_team_type(team2)
                level1 = SCHOOL_LEVEL[type1]
                level2 = SCHOOL_LEVEL[type2]

                # 2. 무기 일치 확인 (클럽 선수는 한 무기만 하는 경우가 많음)
                weapons1 = get_weapons(team1)
                weapons2 = get_weapons(team2)

                # 무기가 완전히 다르면 다른 사람 (예: 플러레 vs 사브르)
                if weapons1 and weapons2 and not weapons1.intersection(weapons2):
                    continue  # 무기가 다르면 합치지 않음

                # 3. Check if teams could be same person based on time progression
                dates1 = sorted([r["comp_date"] for r in team_records[team1] if r["comp_date"]])
                dates2 = sorted([r["comp_date"] for r in team_records[team2] if r["comp_date"]])

                if not dates1 or not dates2:
                    continue

                range1_end = dates1[-1]
                range2_start = dates2[0]
                range1_start = dates1[0]
                range2_end = dates2[-1]

                def parse_year(d):
                    try:
                        return int(d[:4])
                    except:
                        return 0

                year1_end = parse_year(range1_end)
                year2_start = parse_year(range2_start)
                year1_start = parse_year(range1_start)
                year2_end = parse_year(range2_end)

                should_union = False

                # 4. 소속 유형별 Union 조건
                is_school1 = type1 in ('elementary', 'middle', 'high', 'university')
                is_school2 = type2 in ('elementary', 'middle', 'high', 'university')

                if is_school1 and is_school2:
                    # 학교→학교: 레벨이 순차적이어야 함 (중→고→대)
                    # 중요: 한 단계씩만 진학 가능 (중→대 불가, 반드시 중→고→대)
                    level_diff = abs(level2 - level1)

                    if level_diff > 1:
                        # 레벨 차이가 2 이상이면 같은 사람일 수 없음 (중→대 불가)
                        pass  # 합치지 않음
                    elif level2 > level1:
                        # 정방향 진학: team1이 먼저, team2가 나중
                        if range1_end <= range2_start:
                            gap_years = year2_start - year1_end
                            # 진학 간격 체크: 중→고 1년, 고→대 1년 정도
                            if gap_years <= 1:
                                should_union = True
                    elif level1 > level2:
                        # 역방향: team2가 먼저, team1이 나중 (예: 중학교 2020, 고등학교 2023)
                        if range2_end <= range1_start:
                            gap_years = year1_start - year2_end
                            if gap_years <= 1:
                                should_union = True
                    # 같은 레벨 학교→학교는 전학 가능
                    elif level1 == level2:
                        # 같은 레벨 학교 전학: 시간적으로 겹치지 않아야 함
                        if range1_end <= range2_start or range2_end <= range1_start:
                            gap_years = abs(year2_start - year1_end)
                            if gap_years <= 1:
                                should_union = True

                elif is_school1 != is_school2:
                    # 학교↔클럽: 기본적으로 합치지 않음 (다른 트랙)
                    # 단, 초등학교 선수가 클럽에서도 활동하는 경우는 허용 (시간이 겹치지 않을 때)
                    pass  # 합치지 않음

                else:
                    # 클럽→클럽: 소속 이적은 흔한 일
                    # 조건 완화: 무기가 겹치면 동일인일 수 있음 (정확히 같을 필요 없음)

                    # 무기 겹침 여부 확인 (이미 위에서 완전 불일치는 걸러짐)
                    weapons_compatible = (
                        not weapons1 or not weapons2 or  # 무기 정보 없으면 호환
                        bool(weapons1.intersection(weapons2))  # 겹치면 호환
                    )

                    if not weapons_compatible:
                        pass  # 무기가 완전히 다르면 합치지 않음
                    elif range1_end <= range2_start:
                        gap_years = year2_start - year1_end
                        # 클럽 간 전환은 2년 이내 허용 (휴식기 고려)
                        if gap_years <= 2:
                            should_union = True
                    elif range2_end <= range1_start:
                        gap_years = year1_start - year2_end
                        if gap_years <= 2:
                            should_union = True
                    else:
                        # 시간이 겹치는 경우: 동시에 두 클럽 활동은 드물지만 가능
                        # 무기가 완전히 같고 시간 겹침이 적으면 허용
                        if weapons1 == weapons2:
                            # 겹치는 기간 계산
                            overlap_start = max(range1_start, range2_start)
                            overlap_end = min(range1_end, range2_end)
                            if overlap_start <= overlap_end:
                                # 약간의 겹침은 이적 과도기로 허용
                                overlap_years = parse_year(overlap_end) - parse_year(overlap_start)
                                if overlap_years <= 1:
                                    should_union = True

                if should_union:
                    union(team1, team2)

        # Group teams by connected component
        components = defaultdict(list)
        for team in teams_list:
            root = find(team)
            components[root].append(team)

        # Create profile for each connected component
        for root_team, group_teams in components.items():
            # Use first team chronologically as base for ID
            first_date = None
            first_team = group_teams[0]
            for team in group_teams:
                team_dates = [r["comp_date"] for r in team_records[team] if r["comp_date"]]
                if team_dates:
                    min_date = min(team_dates)
                    if first_date is None or min_date < first_date:
                        first_date = min_date
                        first_team = team

            player_id = self._generate_player_id(name, first_team)
            profile = PlayerProfile(
                player_id=player_id,
                name=name
            )

            # Add all records from all teams in this component
            for team in group_teams:
                for rec in team_records[team]:
                    self._populate_profile(profile, rec)

            self.profiles[player_id] = profile

            if name not in self.name_to_profiles:
                self.name_to_profiles[name] = []
            self.name_to_profiles[name].append(player_id)

            self.name_groups[name].profiles.append(profile)

    def _create_single_profile(self, name: str, records: List[Dict]) -> None:
        """Create a single profile for a person (possibly with team changes)"""
        # Use first team as base for ID generation
        first_team = ""
        for rec in records:
            if rec["team"]:
                first_team = rec["team"]
                break

        player_id = self._generate_player_id(name, first_team)
        profile = PlayerProfile(
            player_id=player_id,
            name=name
        )

        for rec in records:
            self._populate_profile(profile, rec)

        self.profiles[player_id] = profile

        if name not in self.name_to_profiles:
            self.name_to_profiles[name] = []
        self.name_to_profiles[name].append(player_id)

        self.name_groups[name].profiles.append(profile)

    def _populate_profile(self, profile: PlayerProfile, record: Dict) -> None:
        """Populate profile with record data"""
        profile.add_team(record["team"], record["comp_date"])
        profile.competition_ids.add(record["comp_cd"])
        profile.records.append(record)

        if record["weapon"]:
            profile.weapons.add(record["weapon"])
        if record["age_group"]:
            profile.age_groups.add(record["age_group"])

        # Update podium stats
        if record["record_type"] == "ranking":
            rank = record["record"].get("rank")
            if rank:
                year = record["comp_date"][:4] if record["comp_date"] else "Unknown"

                if year not in profile.podium_by_season:
                    profile.podium_by_season[year] = {
                        "gold": 0, "silver": 0, "bronze": 0, "top8": 0, "total": 0
                    }

                if rank == 1:
                    profile.podium_by_season[year]["gold"] += 1
                elif rank == 2:
                    profile.podium_by_season[year]["silver"] += 1
                elif rank == 3:
                    profile.podium_by_season[year]["bronze"] += 1
                elif rank <= 8:
                    profile.podium_by_season[year]["top8"] += 1

                profile.podium_by_season[year]["total"] += 1

    def _generate_player_id(self, name: str, team: str) -> str:
        """Generate unique player ID with country code prefix

        ID Format: {Country}{P}{Number}
        - Country: KO(한국), JP(일본), CN(중국), TW(대만), etc.
        - P: Player를 의미
        - Number: 5자리 일련번호

        Example: KOP00001, KOP00002, JPP00001
        Special: KOP00000 = 박소윤(최병철펜싱클럽) - 시스템 기준점

        기존 호환성을 위해 legacy ID도 매핑 유지
        """
        # 기존 ID 생성 (호환성용)
        legacy_base = f"{name}_{team}"
        legacy_id = hashlib.md5(legacy_base.encode()).hexdigest()[:12]

        # 이미 매핑된 경우 기존 새 ID 반환
        if legacy_id in self._legacy_id_map:
            return self._legacy_id_map[legacy_id]

        # 새 ID 생성
        self._player_id_counter += 1
        new_id = f"{self.country}P{self._player_id_counter:05d}"

        # 매핑 저장
        self._legacy_id_map[legacy_id] = new_id

        return new_id

    def _assign_special_ids(self) -> int:
        """특별 ID 할당 (resolve_identities 후 호출)

        소속 변경이 있는 선수도 처리하기 위해 모든 프로필을 검사
        Returns: 할당된 특별 ID 수
        """
        assigned = 0

        for name, special_config in self.SPECIAL_PLAYER_IDS.items():
            target_teams = special_config["teams"]
            special_id = special_config["id"]

            # 이미 할당된 경우 스킵
            if special_id in self._special_ids_assigned:
                continue

            # 해당 이름의 프로필들 검색
            if name not in self.name_to_profiles:
                continue

            for old_id in list(self.name_to_profiles[name]):
                profile = self.profiles.get(old_id)
                if not profile:
                    continue

                # 프로필의 모든 팀 중 target_teams와 매칭되는지 확인
                profile_teams = [t.team for t in profile.team_history]
                if any(team in profile_teams for team in target_teams):
                    # 특별 ID로 교체
                    self.profiles[special_id] = profile
                    profile.player_id = special_id
                    del self.profiles[old_id]

                    # name_to_profiles 업데이트
                    idx = self.name_to_profiles[name].index(old_id)
                    self.name_to_profiles[name][idx] = special_id

                    self._special_ids_assigned.add(special_id)
                    assigned += 1
                    break  # 이 이름에 대해서는 하나만 할당

        return assigned

    def search_players(self, query: str) -> List[PlayerProfile]:
        """Search for players by name or current team

        When searching by team:
        - Only returns players whose most recent competition was with that team
        """
        results = []
        results_set = set()  # To avoid duplicates
        query_lower = query.lower()

        # 1. Search by player name
        for name, player_ids in self.name_to_profiles.items():
            if query_lower in name.lower():
                for player_id in player_ids:
                    if player_id in self.profiles and player_id not in results_set:
                        results.append(self.profiles[player_id])
                        results_set.add(player_id)

        # 2. Search by current team (most recent team)
        for player_id, profile in self.profiles.items():
            if player_id in results_set:
                continue
            # Check if query matches current_team (most recent team)
            if profile.current_team and query_lower in profile.current_team.lower():
                results.append(profile)
                results_set.add(player_id)

        return results

    def get_player_by_id(self, player_id: str) -> Optional[PlayerProfile]:
        """Get player profile by ID"""
        return self.profiles.get(player_id)

    def get_players_by_name(self, name: str) -> List[PlayerProfile]:
        """Get all players with exact name match"""
        player_ids = self.name_to_profiles.get(name, [])
        return [self.profiles[pid] for pid in player_ids if pid in self.profiles]

    def has_disambiguation(self, name: str) -> bool:
        """Check if name has multiple possible identities"""
        return len(self.name_to_profiles.get(name, [])) > 1

    def to_dict(self) -> Dict:
        """Export resolver state to dictionary"""
        return {
            "profiles": {
                pid: {
                    "player_id": p.player_id,
                    "name": p.name,
                    "name_en": p.name_en,
                    "name_en_verified": p.name_en_verified,
                    "fie_id": p.fie_id,
                    "fencingtracker_id": p.fencingtracker_id,
                    "current_team": p.current_team,
                    "teams": p.teams,
                    "team_history": [
                        {
                            "team": t.team,
                            "team_id": t.team_id,
                            "team_en": t.team_en,
                            "first_seen": t.first_seen,
                            "last_seen": t.last_seen,
                            "competition_count": t.competition_count
                        }
                        for t in p.team_history
                    ],
                    "weapons": list(p.weapons),
                    "age_groups": list(p.age_groups),
                    "competition_count": len(p.competition_ids),
                    "podium_by_season": p.podium_by_season
                }
                for pid, p in self.profiles.items()
            },
            "name_index": self.name_to_profiles,
            "ambiguous_names": [
                name for name, pids in self.name_to_profiles.items()
                if len(pids) > 1
            ]
        }

    def populate_english_names(self) -> int:
        """
        Populate English names for all profiles using international_data module.
        Returns the number of profiles updated.
        """
        try:
            from app.international_data import InternationalDataManager
        except ImportError:
            print("Warning: international_data module not available")
            return 0

        manager = InternationalDataManager()
        updated = 0

        for player_id, profile in self.profiles.items():
            if profile.name_en:
                continue  # Already has English name

            en_name = manager.get_english_name(profile.name)
            if en_name:
                profile.name_en = en_name.full_name
                profile.name_en_verified = en_name.source == 'verified'

                # Set external IDs if available
                if en_name.external_id:
                    if en_name.source == 'verified':
                        # Check which ID it is
                        from app.international_data import VERIFIED_NAME_MAPPINGS
                        if profile.name in VERIFIED_NAME_MAPPINGS:
                            verified = VERIFIED_NAME_MAPPINGS[profile.name]
                            profile.fie_id = verified.get('fie_id')
                            profile.fencingtracker_id = verified.get('fencingtracker_id')

                updated += 1

        manager.close()
        return updated

    def get_org_resolver(self):
        """조직 식별자 가져오기 (지연 로딩)"""
        if self._org_resolver is None:
            try:
                from app.organization_identity import OrganizationIdentityResolver
                self._org_resolver = OrganizationIdentityResolver(country=self.country)
            except ImportError:
                print("Warning: organization_identity module not available")
                return None
        return self._org_resolver

    def populate_team_info(self) -> int:
        """
        Populate team IDs and English names for all profiles.
        Returns the number of team records updated.
        """
        org_resolver = self.get_org_resolver()
        if not org_resolver:
            return 0

        updated = 0

        for player_id, profile in self.profiles.items():
            for team_record in profile.team_history:
                if team_record.team_id:
                    continue  # Already has team ID

                org = org_resolver.get_or_create_organization(team_record.team)
                team_record.team_id = org.org_id
                team_record.team_en = org.name_en

                # 조직 통계 업데이트
                org_resolver.update_organization_stats(
                    team_record.team,
                    team_record.first_seen or "",
                    player_id
                )

                updated += 1

        return updated

    def get_organization_stats(self) -> dict:
        """조직 통계 가져오기"""
        org_resolver = self.get_org_resolver()
        if org_resolver:
            return org_resolver.get_stats()
        return {}

    def search_organizations(self, query: str, limit: int = 20) -> list:
        """조직 검색"""
        org_resolver = self.get_org_resolver()
        if org_resolver:
            return [org.to_dict() for org in org_resolver.search_organizations(query, limit)]
        return []


def build_player_database(data_path: str) -> PlayerIdentityResolver:
    """Build player database from JSON data file"""
    with open(data_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    resolver = PlayerIdentityResolver()

    for competition_data in data.get("competitions", []):
        resolver.add_competition_data(competition_data)

    resolver.resolve_identities()

    return resolver


if __name__ == "__main__":
    # Test the resolver
    # 🚨 NOTE: JSON 파일 테스트 비활성화 (2025-12-22)
    # 실제 서비스는 Supabase 캐시 데이터 사용
    import sys

    print("⚠️ JSON 테스트 비활성화됨. 서버 환경에서 테스트하세요.")
    print("서버는 Supabase에서 데이터를 로드합니다.")
    sys.exit(0)

    # (레거시 코드 - 참조용으로만 유지)
    data_path = "data/fencing_full_data_v2.json"

    print("Building player database...")
    resolver = build_player_database(data_path)

    print(f"\nTotal profiles: {len(resolver.profiles)}")
    print(f"Total unique names: {len(resolver.name_to_profiles)}")

    # Find ambiguous names
    ambiguous = [
        (name, len(pids))
        for name, pids in resolver.name_to_profiles.items()
        if len(pids) > 1
    ]

    print(f"\nAmbiguous names (동명이인): {len(ambiguous)}")
    for name, count in sorted(ambiguous, key=lambda x: -x[1])[:10]:
        print(f"  - {name}: {count} profiles")
        for pid in resolver.name_to_profiles[name]:
            p = resolver.profiles[pid]
            print(f"    └ {p.current_team} ({len(p.competition_ids)} competitions)")

    # Export summary
    summary = resolver.to_dict()
    print(f"\nExportable data structure ready with {len(summary['profiles'])} profiles")
