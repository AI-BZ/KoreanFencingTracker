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
from collections import defaultdict
import hashlib
import re
import logging

logger = logging.getLogger(__name__)


def is_team_event(event_name: str) -> bool:
    """단체전 이벤트인지 판별.

    단체전 final_rankings의 name 필드에는 팀명(학교/클럽명)이 들어있어
    개인 선수 프로필로 처리하면 안 됨 (~202개 가짜 선수 프로필 발생 원인).

    Args:
        event_name: 이벤트 이름 (예: "남자 사브르(단)", "여자 에페 단체")

    Returns:
        True if team event, False otherwise
    """
    return "(단)" in event_name or "단체" in event_name


# ============================================================
# 자동 동명이인 감지 (Automatic Homonym Detection)
# ============================================================
# 규칙 우선순위:
#   Level 1: 같은 대회 + 다른 팀 → 100% 다른 사람 (물리적 불가)
#   Level 2: 다른 성별 → 100% 다른 사람
#   Level 3: 나이그룹 역행 → 100% 다른 사람
#   Level 4: 다른 무기 (cross-time) → 99%+ 다른 사람
# KNOWN_HOMONYMS는 위 규칙으로 감지 불가한 예외 케이스에만 사용
# ============================================================

def detect_homonyms_from_competitions(competitions_data: list) -> Dict[str, Set[str]]:
    """대회 데이터에서 동명이인을 자동 감지.

    "같은 대회(comp_id) + 다른 팀" 규칙으로 동명이인 이름과 해당 팀 집합을 반환.
    한 사람이 같은 대회에서 2개 팀으로 출전할 수 없으므로 100% 신뢰할 수 있는 규칙.

    Args:
        competitions_data: [{competition: {...}, events: [{...}]}] 형태의 대회 데이터

    Returns:
        {이름: {팀1, 팀2, ...}} — 동명이인으로 확인된 이름별 팀 집합
        (한 이름에 2개 이상 팀이 있으면 동명이인)
    """
    # {name: {comp_id: set(teams)}}
    name_comp_teams: Dict[str, Dict[str, Set[str]]] = defaultdict(lambda: defaultdict(set))

    for comp_data in competitions_data:
        comp = comp_data.get("competition", {})
        comp_id = str(comp.get("id", comp.get("event_cd", "")))

        for event in comp_data.get("events", []):
            # 단체전 이벤트는 제외 (팀명이 name 필드에 있어 가짜 선수 생성됨)
            if is_team_event(event.get("name", "")):
                continue
            for r in event.get("final_rankings", []):
                name = (r.get("name") or "").strip()
                team = (r.get("team") or "").strip()
                if name and team:
                    name_comp_teams[name][comp_id].add(team)

    # 같은 대회에서 2개 이상 팀으로 나온 이름 = 동명이인
    homonyms: Dict[str, Set[str]] = {}
    for name, comp_teams in name_comp_teams.items():
        all_teams_for_name: Set[str] = set()
        is_homonym = False
        for comp_id, teams in comp_teams.items():
            if len(teams) > 1:
                is_homonym = True
            all_teams_for_name.update(teams)
        if is_homonym:
            homonyms[name] = all_teams_for_name

    return homonyms


def is_same_date_homonym(name: str, competitions_data: list) -> bool:
    """특정 이름이 같은 대회에서 다른 팀으로 출전한 적이 있는지 확인."""
    for comp_data in competitions_data:
        teams_in_comp: Set[str] = set()
        for event in comp_data.get("events", []):
            if is_team_event(event.get("name", "")):
                continue
            for r in event.get("final_rankings", []):
                if (r.get("name") or "").strip() == name:
                    team = (r.get("team") or "").strip()
                    if team:
                        teams_in_comp.add(team)
        if len(teams_in_comp) > 1:
            return True
    return False


# 소속 유형 판별 — 패턴 우선순위 (긴 패턴 먼저, 단일글자는 $ anchor)
# organization_identity.py의 detect_org_type()과 동일한 우선순위
_TEAM_TYPE_PATTERNS: list = [
    # 0단계: OB(졸업생/동문) — 대학교 패턴보다 먼저 매칭
    (r'OB$|OB\b', 'club'),  # "고려대학교OB" → club (졸업생 팀)

    # 1단계: 부속학교 (대학교+고등학교 조합)
    (r'부속고등학교|부속고|부설고', 'high'),
    (r'부속중학교|부속중|부설중', 'middle'),
    (r'부속초등학교', 'elementary'),

    # 2단계: 전체 단어 학교
    (r'초등학교|초교', 'elementary'),
    (r'중학교|중학', 'middle'),
    (r'고등학교|고등|체육고|예술고|과학고|외고|국제고|자사고|특목고|국제학교', 'high'),
    (r'대학교|대학', 'university'),

    # 3단계: 행정기관/실업팀 (체육회+클럽은 클럽 우선)
    (r'체육회.*클럽|체육회.*아카데미|체육회.*도장', 'club'),  # "안산시체육회 상록펜싱클럽" → club
    (r'시청|군청|구청|도청|체육회|체육부대', 'professional'),
    (r'공사|공단|은행|보험|증권|카드|전력|가스|통신|철도|항공', 'professional'),
    (r'삼성|현대|LG|SK|롯데|포스코|KT|CJ', 'professional'),

    # 4단계: 협회클럽 복합 패턴 (협회보다 클럽 우선)
    (r'협회클럽', 'club'),  # "수원시펜싱협회클럽" → club
    (r'국가대표|대표팀|협회|연맹', 'national'),

    # 5단계: 클럽 키워드 (한글 + 영문)
    (r'클럽|스포츠클럽|스포츠단|스포츠스쿨|아카데미|도장|체육관|센터|랩|LAB|FC|SC|가르드', 'club'),
    (r'(?i)CLUB|FENCING\s*CLUB', 'club'),  # 영문 클럽명
    (r'(?i)INTERNATIONAL\s*SCHOOL|SCHOOL', 'high'),  # 국제학교

    # 6단계 (최후 fallback): 단일글자 + $ anchor
    (r'여중$|남중$', 'middle'),
    (r'여고$|남고$', 'high'),
    (r'중$', 'middle'),
    (r'고$', 'high'),
    (r'대$', 'university'),
]


def get_team_type(team: str) -> str:
    """
    소속 유형 판별
    Returns: 'elementary', 'middle', 'high', 'university', 'professional', 'club'

    우선순위: 부속학교 → 전체단어 학교 → 행정기관 → 클럽 → 단일글자 fallback
    """
    if not team:
        return 'club'

    for pattern, team_type in _TEAM_TYPE_PATTERNS:
        if re.search(pattern, team):
            return team_type

    return 'club'


# 학교 유형 레벨 (진학 순서)
SCHOOL_LEVEL = {
    'elementary': 1,
    'middle': 2,
    'high': 3,
    'university': 4,
    'club': 0,  # 클럽은 별도 트랙
    'professional': 5,  # 실업팀/시청/기업
    'national': 5,  # 국가대표/협회
}

# 나이그룹 레벨 (성장 순서 - 시간이 지나면 레벨이 올라가야 함)
AGE_GROUP_LEVEL = {
    # 유년부
    'U9': 1, 'Y9': 1,
    'U11': 2, 'Y11': 2,
    'U13': 3, 'Y13': 3,
    # 초등
    '초등저': 4, '초등고': 5, '초등부': 5,
    # 중등
    'U14': 6, 'Y14': 6, '여중': 6, '남중': 6, '중등부': 6,
    # 고등
    'U17': 7, 'Y17': 7, '여고': 7, '남고': 7, '고등부': 7,
    # 대학/청년
    'U20': 8, 'Y20': 8, '대학': 8, '청년부': 8,
    # 일반/성인
    '일반부': 9, '일반': 9, '시니어': 10,
}


def get_age_group_level(age_group: str) -> int:
    """나이그룹의 레벨을 반환 (높을수록 나이가 많음)"""
    if not age_group:
        return 0

    # 정확한 매칭
    for key, level in AGE_GROUP_LEVEL.items():
        if key in age_group:
            return level
    return 0


def is_valid_age_progression(old_age_group: str, old_date: str, new_age_group: str, new_date: str) -> bool:
    """
    나이그룹 진행이 유효한지 확인
    시간이 지나면 나이그룹이 올라가거나 유지되어야 함 (내려가면 안 됨)

    Returns:
        True if valid progression, False if suspicious (might be different person)
    """
    if not old_age_group or not new_age_group:
        return True  # 정보 없으면 유효로 처리

    old_level = get_age_group_level(old_age_group)
    new_level = get_age_group_level(new_age_group)

    if old_level == 0 or new_level == 0:
        return True  # 레벨 파악 불가면 유효로 처리

    # 날짜 비교
    if old_date and new_date:
        if new_date > old_date:
            # 시간이 지났는데 나이그룹이 내려가면 이상함
            if new_level < old_level:
                return False

    return True


def extract_gender(event_name: str) -> str:
    """
    이벤트 이름에서 성별 추출

    Returns:
        'M' for 남자, 'F' for 여자, '' for unknown
    """
    if not event_name:
        return ''

    # 여자 패턴 (먼저 체크 - "여자", "여중", "여고", "여대" 등)
    if re.search(r'여자|여중|여고|여대|여초', event_name):
        return 'F'

    # 남자 패턴
    if re.search(r'남자|남중|남고|남대|남초', event_name):
        return 'M'

    return ''


def is_gender_consistent(records: List[Dict]) -> Tuple[bool, str]:
    """
    레코드들의 성별이 일관성 있는지 확인

    Returns:
        (is_consistent, warning_message)
        - True, '' if consistent or unknown
        - False, warning_message if inconsistent (definitely different people)
    """
    genders = set()
    gender_records = []

    for record in records:
        event_name = record.get('event_name', '')
        gender = extract_gender(event_name)
        if gender:
            genders.add(gender)
            gender_records.append({
                'date': record.get('comp_date', ''),
                'gender': '남자' if gender == 'M' else '여자',
                'event': event_name
            })

    if len(genders) > 1:
        # 남자와 여자가 섞여있음 - 확실히 다른 사람
        male_record = next((r for r in gender_records if r['gender'] == '남자'), None)
        female_record = next((r for r in gender_records if r['gender'] == '여자'), None)

        warning = "성별 불일치 감지 (동명이인): "
        if male_record and female_record:
            warning += f"남자({male_record['date']}) vs 여자({female_record['date']})"

        return False, warning

    return True, ''


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

    # Disambiguation warnings
    _age_group_warning: Optional[str] = field(default=None, repr=False)

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
        """팀 기록 추가 (단순화됨 - rebuild_team_history()로 그룹화)

        모든 기록을 개별적으로 추가합니다.
        프로필 구축 완료 후 rebuild_team_history()를 호출하여
        연속된 같은 팀을 그룹화하고 원복 케이스를 처리합니다.
        """
        if not team:
            return

        # 무조건 새 기록 추가 (나중에 rebuild_team_history()로 그룹화)
        self.team_history.append(TeamRecord(
            team=team,
            first_seen=date_str,
            last_seen=date_str
        ))

    def rebuild_team_history(self) -> None:
        """프로필 구축 완료 후 team_history 재구축

        - 날짜순 정렬
        - 연속된 같은 팀을 하나의 기간으로 그룹화
        - 원복 케이스(A→B→A)는 별도 기간으로 유지

        예: 최병철(2022-03~2025-07) → 올즈윈(2025-08) → 최병철(2025-10~2026-01)
        """
        if not self.team_history:
            return

        # 날짜순 정렬
        sorted_records = sorted(self.team_history, key=lambda x: x.first_seen)

        # 연속된 같은 팀 그룹화 (원복 케이스 분리 유지)
        new_history = []
        current_period = None

        for record in sorted_records:
            if current_period is None:
                # 첫 번째 기록
                current_period = TeamRecord(
                    team=record.team,
                    team_id=record.team_id,
                    team_en=record.team_en,
                    first_seen=record.first_seen,
                    last_seen=record.last_seen,
                    competition_count=record.competition_count
                )
            elif current_period.team == record.team:
                # 연속된 같은 팀 - 기간 연장
                current_period.last_seen = record.last_seen
                current_period.competition_count += record.competition_count
            else:
                # 다른 팀 - 현재 기간 저장, 새 기간 시작
                new_history.append(current_period)
                current_period = TeamRecord(
                    team=record.team,
                    team_id=record.team_id,
                    team_en=record.team_en,
                    first_seen=record.first_seen,
                    last_seen=record.last_seen,
                    competition_count=record.competition_count
                )

        if current_period:
            new_history.append(current_period)

        self.team_history = new_history

    def check_data_integrity(self) -> Optional[str]:
        """
        데이터 무결성 검사 - 동명이인 오류 감지

        검사 순서 (우선순위):
        1. 성별 불일치 (절대적 - 남/여 바뀔 수 없음)
        2. 나이그룹 역행 (시간이 지나면 나이가 어려질 수 없음)

        Returns:
            None if valid, warning message if suspicious
        """
        if not self.records:
            return None

        # 1. 성별 일관성 체크 (가장 중요 - 절대 불변)
        is_consistent, gender_warning = is_gender_consistent(self.records)
        if not is_consistent:
            return gender_warning

        # 2. 나이그룹 진행 체크
        sorted_records = sorted(
            [r for r in self.records if r.get('age_group')],
            key=lambda x: x.get('comp_date', '')
        )

        if len(sorted_records) >= 2:
            prev_record = None
            for record in sorted_records:
                if prev_record:
                    prev_date = prev_record.get('comp_date', '')
                    curr_date = record.get('comp_date', '')
                    prev_age = prev_record.get('age_group', '')
                    curr_age = record.get('age_group', '')

                    if not is_valid_age_progression(prev_age, prev_date, curr_age, curr_date):
                        return f"나이그룹 역행 감지: {prev_age}({prev_date[:10]}) → {curr_age}({curr_date[:10]})"

                prev_record = record

        return None

    def check_age_group_validity(self) -> Optional[str]:
        """Deprecated: use check_data_integrity instead"""
        return self.check_data_integrity()

    @property
    def has_disambiguation_warning(self) -> bool:
        """동명이인 오류 가능성이 있는지 확인"""
        if self._age_group_warning is None:
            self._age_group_warning = self.check_data_integrity() or ""
        return bool(self._age_group_warning)

    @property
    def disambiguation_warning(self) -> str:
        """동명이인 오류 경고 메시지"""
        if self._age_group_warning is None:
            self._age_group_warning = self.check_data_integrity() or ""
        return self._age_group_warning


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

    # [보조용] 수동 등록 동명이인: 자동 감지(같은 대회 다른 팀)로 잡히지 않는 케이스만.
    # 대부분의 동명이인은 _find_overlapping_teams()가 자동으로 감지.
    # 여기는 두 사람이 절대 같은 대회에 나가지 않는 희귀 케이스에만 사용.
    # Format: name -> [(team_set_a, team_set_b), ...] — 서로 다른 사람의 팀 그룹
    KNOWN_HOMONYMS = {
        # Case 1: 이지민 (foil, 여) — 2024 5/6학년 남현희인터내셔널 vs 2025 일반 이글펜싱클럽
        "이지민": [
            ({"남현희 인터내셔널펜싱아카데미"},
             {"이글펜싱클럽", "이글펜싱클럽 전문트레이닝센터 올림픽점"}),
        ],
        # Case 2: 김가윤 (foil, 여) — 2024 1/2학년 엔티언펜싱 김포 vs 2025 중등 송정여자중학교
        "김가윤": [
            ({"엔티언 펜싱클럽 김포"}, {"송정여자중학교"}),
        ],
        # Case 3: 김시우 (foil, 남) — 2023 3/4학년 압구정펜싱클럽 vs 2024 고등 울산산업고등학교
        "김시우": [
            ({"압구정펜싱클럽"}, {"울산산업고등학교"}),
        ],
        # Case 4: 이준서 (foil, 남) — 2024 3/4학년 평창동펜싱클럽 vs 2025 고등 곤지암고등학교
        "이준서": [
            ({"평창동펜싱클럽"}, {"곤지암고등학교"}),
        ],
        # Case 5: 김주원 (foil, 남) — 2025 5/6학년 송도펜싱클럽 vs 2026 고등 가림고등학교
        "김주원": [
            ({"송도펜싱클럽"}, {"가림고등학교"}),
        ],
        # Case 6: 이가연 (foil, 여) — 2025 1/2학년 알레펜싱클럽 vs 2026 5/6학년 비앤케이펜싱클럽
        "이가연": [
            ({"알레펜싱클럽"}, {"비앤케이펜싱클럽"}),
        ],
        # Case 7: 정하윤 (foil, 여) — 2025 3/4학년 노블레스펜싱클럽 vs 2026 중등 개양중학교
        "정하윤": [
            ({"노블레스펜싱클럽"}, {"개양중학교"}),
        ],
        # Case 8: 구준영 (sabre, 남) — 2022 1/2학년 아이에프씨제주 vs 2025 고등 더블유펜싱클럽
        "구준영": [
            ({"아이에프씨제주"}, {"더블유펜싱클럽"}),
        ],
        # Case 9: 박소윤 (여중) — 플뢰레 최병철펜싱클럽/송도펜싱클럽 vs 에페 덕원중학교
        # 같은 대회 같은 날 다른 종목/팀으로 출전 확인 (2026-03, 2026-04)
        "박소윤": [
            ({"최병철펜싱클럽", "송도펜싱클럽"}, {"덕원중학교"}),
        ],

        # ============================================================
        # Tier 1: 성별 기반 동명이인 (R10+R13 — 같은 날 남/여 종목 동시 출전)
        # 2026-05-14 Data Guardian 검증 결과 일괄 등록 (47명)
        # 증거: DB에서 같은 이름이 같은 대회에서 남자/여자 종목에 각각 출전
        # ============================================================

        # Case 10: 강민서 — 남(오성고/오성중/서울펜싱클럽, 사브르) vs 여(신수중/마스터펜싱클럽/윈펜싱클럽, 플뢰레/에페)
        "강민서": [
            ({"오성고", "오성중", "서울펜싱클럽"},
             {"신수중", "마스터펜싱클럽", "윈펜싱클럽"}),
        ],
        # Case 11: 김도연 — 남(광주체육중/발안바이오과학고/한국체육대, 에페/사브르) vs 여(시지고/이지펜싱클럽/전주호성중, 사브르/플뢰레)
        "김도연": [
            ({"광주체육중", "발안바이오과학고", "한국체육대"},
             {"시지고", "이지펜싱클럽", "전주호성중"}),
        ],
        # Case 12: 김민강 — 남(대전매봉중, 사브르) vs 여(하이브펜싱클럽, 플뢰레)
        "김민강": [
            ({"대전매봉중"}, {"하이브펜싱클럽"}),
        ],
        # Case 13: 김민서 — 남(국군체육부대, 플뢰레) vs 여(K1펜싱클럽/구본길펜싱클럽/부천트윈펜싱클럽/이리북중, 에페)
        "김민서": [
            ({"국군체육부대"},
             {"K1펜싱클럽", "구본길펜싱클럽", "부천트윈펜싱클럽", "이리북중"}),
        ],
        # Case 14: 김민솔 — 남(JK펜싱클럽, 초등남에페) vs 여(수원펜싱클럽/예코치펜싱클럽/펜싱레이블, 초등여에페/여일에페)
        "김민솔": [
            ({"JK펜싱클럽"},
             {"수원펜싱클럽", "예코치펜싱클럽", "펜싱레이블"}),
        ],
        # Case 15: 김서율 — 남(투셰펜싱클럽, 초등남플뢰레) vs 여(어썸코리아펜싱클럽, 초등여플뢰레)
        "김서율": [
            ({"투셰펜싱클럽"}, {"어썸코리아펜싱클럽"}),
        ],
        # Case 16: 김서진 — 남(원주중/한국체육대, 에페) vs 여(비앤케이펜싱클럽/서울체육고/은성중, 사브르)
        "김서진": [
            ({"원주중", "한국체육대"},
             {"비앤케이펜싱클럽", "서울체육고", "은성중"}),
        ],
        # Case 17: 김성은 — 남(드림펜싱클럽, 플뢰레) vs 여(서울대펜싱부/신동중/중경고, 플뢰레)
        "김성은": [
            ({"드림펜싱클럽"},
             {"서울대펜싱부", "신동중", "중경고"}),
        ],
        # Case 18: 김시원 — 남(부산영선중, 플뢰레) vs 여(엔티언펜싱클럽배곧/엔티언펜싱클럽송도, 초등여플뢰레)
        "김시원": [
            ({"부산영선중"},
             {"엔티언펜싱클럽배곧", "엔티언펜싱클럽송도"}),
        ],
        # Case 19: 김시윤 — 남(에이치펜싱클럽, 플뢰레) vs 여(위즈펜싱클럽/윤지수펜싱클럽, 사브르)
        "김시윤": [
            ({"에이치펜싱클럽"},
             {"위즈펜싱클럽", "윤지수펜싱클럽"}),
        ],
        # Case 20: 김연수 — 남(전북체육고, 플뢰레) vs 여(동의대, 사브르)
        "김연수": [
            ({"전북체육고"}, {"동의대"}),
        ],
        # Case 21: 김연우 — 남(곤지암중/광주시G-스포츠/센텀펜싱클럽, 플뢰레/에페) vs 여(대전송촌고/우송대/호남대, 사브르/에페)
        "김연우": [
            ({"곤지암중", "광주시G-스포츠", "센텀펜싱클럽"},
             {"대전송촌고", "우송대", "호남대"}),
        ],
        # Case 22: 김영현 — 남(대전생활과학고, 플뢰레) vs 여(청라펜싱클럽, 사브르)
        "김영현": [
            ({"대전생활과학고"}, {"청라펜싱클럽"}),
        ],
        # Case 23: 김윤서 — 남(상록고/동의대, 사브르) vs 여(신수펜싱아카데미/익산시청, 사브르/플뢰레)
        # 동의대는 남녀 모두 출전 → 성별이 겹치지 않는 팀만 등록 (동의대 제외)
        "김윤서": [
            ({"상록고"}, {"신수펜싱아카데미", "익산시청"}),
        ],
        # Case 24: 김윤성 — 남(호남대, 사브르) vs 여(봄내중, 에페)
        "김윤성": [
            ({"호남대"}, {"봄내중"}),
        ],
        # Case 25: 김지우 — 남(경덕중/오성중, 플뢰레/사브르) vs 여(부산체육고/재송여자중, 플뢰레)
        "김지우": [
            ({"경덕중", "오성중"},
             {"부산체육고", "재송여자중"}),
        ],
        # Case 26: 김하람 — 남(엔에프에이펜싱아카데미, 초등남플뢰레) vs 여(청라펜싱클럽, 여중사브르)
        "김하람": [
            ({"엔에프에이펜싱아카데미"}, {"청라펜싱클럽"}),
        ],
        # Case 27: 김현진 — 남(펜싱_아레나, 엘리트플뢰레) vs 여(인천광역시중구청/전남체육고, 플뢰레)
        "김현진": [
            ({"펜싱_아레나"},
             {"인천광역시중구청", "전남체육고"}),
        ],
        # Case 28: 남선우 — 남(압구정펜싱클럽, 초등남플뢰레) vs 여(고려대펜싱부, 여일에페)
        "남선우": [
            ({"압구정펜싱클럽"}, {"고려대펜싱부"}),
        ],
        # Case 29: 박서윤 — 남(부산체육고, 플뢰레) vs 여(계룡중/충남체육고, 에페)
        "박서윤": [
            ({"부산체육고"},
             {"계룡중", "충남체육고"}),
        ],
        # Case 30: 박수빈 — 남(가림고, 플뢰레) vs 여(경기도화성시청/스타펜싱아카데미/우송대, 에페/사브르/플뢰레)
        "박수빈": [
            ({"가림고"},
             {"경기도화성시청", "스타펜싱아카데미", "우송대"}),
        ],
        # Case 31: 박제이 — 남(광주시G-스포츠클럽, 초등남플뢰레) vs 여(신아람펜싱클럽, 초등여에페)
        "박제이": [
            ({"광주시G-스포츠클럽"}, {"신아람펜싱클럽"}),
        ],
        # Case 32: 박하온 — 남(센트럴펜싱클럽, 초등남에페) vs 여(사비오펜싱클럽, 초등여사브르)
        "박하온": [
            ({"센트럴펜싱클럽"}, {"사비오펜싱클럽"}),
        ],
        # Case 33: 유시연 — 남(레이스펜싱클럽, 에페) vs 여((사)부산펜싱클럽/경성전자정보고, 에페)
        "유시연": [
            ({"레이스펜싱클럽"},
             {"(사)부산펜싱클럽", "경성전자정보고"}),
        ],
        # Case 34: 윤현서 — 남(어썸코리아펜싱클럽, 초등남플뢰레) vs 여(윤지수펜싱클럽, 초등여사브르)
        "윤현서": [
            ({"어썸코리아펜싱클럽"}, {"윤지수펜싱클럽"}),
        ],
        # Case 35: 이로은 — 남(은호펜싱클럽, 초등남에페) vs 여(어썸코리아펜싱클럽, 초등여플뢰레)
        "이로은": [
            ({"은호펜싱클럽"}, {"어썸코리아펜싱클럽"}),
        ],
        # Case 36: 이서윤 — 남(압구정펜싱클럽, 초등남플뢰레) vs 여(광교펜싱클럽/동백중/성남여고/성남여중, 사브르/플뢰레/에페)
        "이서윤": [
            ({"압구정펜싱클럽"},
             {"광교펜싱클럽", "동백중", "성남여고", "성남여중"}),
        ],
        # Case 37: 이선우 — 남(전북체육고/전주호성중/풍암고, 플뢰레) vs 여(창문여고/창문여중, 에페)
        "이선우": [
            ({"전북체육고", "전주호성중", "풍암고"},
             {"창문여고", "창문여중"}),
        ],
        # Case 38: 이솔 — 남(이글펜싱클럽, 초등남플뢰레) vs 여(춘천스포츠클럽, 초등여사브르)
        "이솔": [
            ({"이글펜싱클럽"}, {"춘천스포츠클럽"}),
        ],
        # Case 39: 이신희 — 남(구본길펜싱클럽, 초등남사브르) vs 여(강원특별자치도청, 여일에페)
        "이신희": [
            ({"구본길펜싱클럽"}, {"강원특별자치도청"}),
        ],
        # Case 40: 이윤서 — 남(압구정펜싱클럽, 남중플뢰레) vs 여(광주시G-스포츠/성남여고/한국체육대, 초등여플뢰레/여고플뢰레/여대사브르)
        "이윤서": [
            ({"압구정펜싱클럽"},
             {"광주시G-스포츠", "성남여고", "한국체육대"}),
        ],
        # Case 41: 이정원 — 남(K1펜싱클럽/숭실대펜싱부/태화중, 에페) vs 여(춘천여고, 에페)
        "이정원": [
            ({"K1펜싱클럽", "숭실대펜싱부", "태화중"},
             {"춘천여고"}),
        ],
        # Case 42: 이주영 — 남(대전생활과학고/한국체육대, 플뢰레) vs 여(대전펜싱클럽, 플뢰레)
        "이주영": [
            ({"대전생활과학고", "한국체육대"},
             {"대전펜싱클럽"}),
        ],
        # Case 43: 이준희 — 남(동의대/수원펜싱클럽/충북체육고, 사브르/에페) vs 여(이리여고/호원대, 사브르)
        "이준희": [
            ({"동의대", "수원펜싱클럽", "충북체육고"},
             {"이리여고", "호원대"}),
        ],
        # Case 44: 이지우 — 남(태화중, 에페) vs 여(대전문정중/덕원중, 에페)
        "이지우": [
            ({"태화중"},
             {"대전문정중", "덕원중"}),
        ],
        # Case 45: 정가온 — 남(인천체육고, 에페) vs 여(경북체육중/케이펜싱클럽, 사브르)
        "정가온": [
            ({"인천체육고"},
             {"경북체육중", "케이펜싱클럽"}),
        ],
        # Case 46: 정승원 — 남(앱솔루트펜싱클럽, 플뢰레) vs 여(FENCINGLAB(펜싱랩), 사브르)
        "정승원": [
            ({"앱솔루트펜싱클럽"}, {"FENCINGLAB(펜싱랩)"}),
        ],
        # Case 47: 정주원 — 남(스킬펜싱클럽/오성고, 초등남플뢰레/남고사브르) vs 여(부천트윈펜싱클럽, 여엘리트에페)
        "정주원": [
            ({"스킬펜싱클럽", "오성고"},
             {"부천트윈펜싱클럽"}),
        ],
        # Case 48: 최민서 — 남(대전도시공사/울산고/전북체육고/태화중/펜싱아카데미더원, 플뢰레/에페) vs 여(경남대/시지고/안산시청, 사브르/플뢰레)
        "최민서": [
            ({"대전도시공사", "울산고", "전북체육고", "태화중", "펜싱아카데미더원", "하태규의기권"},
             {"경남대", "시지고", "안산시청"}),
        ],
        # Case 49: 최시원 — 남(가좌중/부산체육고/진주제일중, 플뢰레/에페) vs 여(엔에스펜싱클럽, 초등여플뢰레)
        "최시원": [
            ({"가좌중", "부산체육고", "진주제일중"},
             {"엔에스펜싱클럽"}),
        ],
        # Case 50: 최유진 — 남(알레펜싱클럽, 초등남플뢰레) vs 여(성남시청, 여일플뢰레)
        "최유진": [
            ({"알레펜싱클럽"}, {"성남시청"}),
        ],
        # Case 51: 최은서 — 남(남산중, 에페) vs 여(만수여중, 플뢰레)
        "최은서": [
            ({"남산중"}, {"만수여중"}),
        ],
        # Case 52: 최은수 — 남(월드펜싱클럽/태화중, 초등남에페/남중에페) vs 여(부산광역시거점스포츠클럽, 초등여플뢰레)
        "최은수": [
            ({"월드펜싱클럽", "태화중"},
             {"부산광역시거점스포츠클럽"}),
        ],
        # Case 53: 최지안 — 남(알레펜싱클럽, 남고플뢰레) vs 여(동백중/비앤케이펜싱클럽/스킬펜싱클럽/엔에프에이펜싱아카데미, 여중사브르/초등여사브르/초등여플뢰레)
        "최지안": [
            ({"알레펜싱클럽"},
             {"동백중", "비앤케이펜싱클럽", "스킬펜싱클럽", "엔에프에이펜싱아카데미"}),
        ],
        # Case 54: 최지우 — 남(한국체육대, 플뢰레) vs 여(서울체육고/서울체육중, 사브르)
        "최지우": [
            ({"한국체육대"},
             {"서울체육고", "서울체육중"}),
        ],
        # Case 55: 한지호 — 남(강원체육중/스킬펜싱클럽, 사브르/플뢰레) vs 여(이리북중, 에페)
        "한지호": [
            ({"강원체육중", "스킬펜싱클럽"},
             {"이리북중"}),
        ],
        # Case 56: 홍하람 — 남(홍익대사범대부속고, 사브르) vs 여(울산서여중/울산스포츠과학고, 에페)
        "홍하람": [
            ({"홍익대사범대부속고"},
             {"울산서여중", "울산스포츠과학고"}),
        ],

        # ============================================================
        # Tier 1 추가: R10 ERROR 잔여 15명 (성별 기반 동명이인)
        # 2026-05-14 추가 등록
        # ============================================================

        # Case 57: 김유현 — 남(마운틴체리아카데미) vs 여(청주경덕중학교)
        "김유현": [
            ({"마운틴체리아카데미"}, {"청주경덕중학교"}),
        ],
        # Case 58: 김지민 — 남(경남대학교) vs 여(재송여자중학교)
        "김지민": [
            ({"경남대학교"}, {"재송여자중학교"}),
        ],
        # Case 59: 김지현 — 남(비에이블펜싱클럽) vs 여(전남도청/엠디비펜싱클럽)
        "김지현": [
            ({"비에이블펜싱클럽"}, {"전남도청", "엠디비펜싱클럽"}),
        ],
        # Case 60: 김태린 — 남(신수중학교) vs 여(에이치펜싱클럽)
        "김태린": [
            ({"신수중학교"}, {"에이치펜싱클럽"}),
        ],
        # Case 61: 김하민 — 남(세인트존스베리아카데미제주/청주대학교) vs 여(페이스튼 센트럴 캠퍼스)
        "김하민": [
            ({"세인트존스베리아카데미제주", "청주대학교"},
             {"페이스튼 센트럴 캠퍼스"}),
        ],
        # Case 62: 박서진 — 남(고덕국제펜싱클럽) vs 여(예코치펜싱클럽)
        "박서진": [
            ({"고덕국제펜싱클럽"}, {"예코치펜싱클럽"}),
        ],
        # Case 63: 박주원 — 남(이리중학교/위즈펜싱클럽) vs 여(두암중학교)
        "박주원": [
            ({"이리중학교", "위즈펜싱클럽"}, {"두암중학교"}),
        ],
        # Case 64: 박지수 — 남(대전매봉중학교) vs 여(경남대학교)
        "박지수": [
            ({"대전매봉중학교"}, {"경남대학교"}),
        ],
        # Case 65: 박지호 — 남(엔에스펜싱클럽/에이치펜싱클럽(H FENCING CLUB)/포인트펜싱클럽) vs 여(전남체육고등학교/경해여자중학교)
        "박지호": [
            ({"엔에스펜싱클럽", "에이치펜싱클럽(H FENCING CLUB)", "포인트펜싱클럽"},
             {"전남체육고등학교", "경해여자중학교"}),
        ],
        # Case 66: 윤태연 — 남(광주국대펜싱) vs 여(천안두정중학교)
        "윤태연": [
            ({"광주국대펜싱"}, {"천안두정중학교"}),
        ],
        # Case 67: 이한솔 — 남(부산광역시거점스포츠클럽) vs 여(청심국제고등학교)
        "이한솔": [
            ({"부산광역시거점스포츠클럽"}, {"청심국제고등학교"}),
        ],
        # Case 68: 임지우 — 남(FENCINGLAB(펜싱랩)) vs 여(윤남진펜싱클럽(천안))
        "임지우": [
            ({"FENCINGLAB(펜싱랩)"}, {"윤남진펜싱클럽(천안)"}),
        ],
        # Case 69: 정선우 — 남(윤지수펜싱클럽) vs 여(송정여자중학교)
        "정선우": [
            ({"윤지수펜싱클럽"}, {"송정여자중학교"}),
        ],
        # Case 70: 정재희 — 남(향남중학교) vs 여(국대스포츠클럽)
        "정재희": [
            ({"향남중학교"}, {"국대스포츠클럽"}),
        ],
        # Case 71: 황승민 — 남(서울시펜싱협회/국민체육진흥공단) vs 여(민족사관고등학교 펜싱부)
        "황승민": [
            ({"서울시펜싱협회", "국민체육진흥공단"},
             {"민족사관고등학교 펜싱부"}),
        ],
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

        # 조직→지역 캐시 (지역 인식 동명이인 분리용)
        # {org_name: {"province": "서울", "city": "강남", "org_type": "club"}}
        self._org_region_cache: Dict[str, Dict[str, str]] = {}

    def set_org_region_cache(self, cache: Dict[str, Dict[str, str]]):
        """Set organization region cache for region-aware identity resolution.

        Args:
            cache: {org_name: {"province": str, "city": str, "org_type": str}}
        """
        self._org_region_cache = cache

    def add_competition_data(self, competition_data: Dict) -> None:
        """Add competition data for player extraction"""
        comp = competition_data.get("competition", {})
        comp_cd = comp.get("event_cd", "")
        comp_name = comp.get("name", "")
        comp_date = comp.get("start_date", "")

        events = competition_data.get("events", [])

        for event in events:
            event_name = event.get("name", "")

            # 단체전 이벤트는 선수 프로필 생성에서 제외
            # (팀명이 name 필드에 저장되어 가짜 선수 프로필이 생성됨)
            if is_team_event(event_name):
                continue

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

        # 전국남녀종별 형식: "여중", "남중", "여고", "남고", "여대", "남대", "일반"
        # 클럽/동호인 형식: "초등부", "중등부", "고등부", "대학부", "일반부"
        # 국제 형식: "U9", "U11", "U13", "U14", "U17", "U20"
        patterns = [
            # 전국남녀종별 형식 (가장 먼저 체크 - 짧은 패턴)
            r"(여중|남중|여고|남고|여대|남대)",
            # 세이하부 형식
            r"(\d+세이하부)",
            # 부별 형식
            r"(초등부|중등부|고등부|대학부|일반부|초등저|초등고)",
            # 국제 형식
            r"([UY]\d+)",
            # 기타
            r"(시니어|주니어|마스터|일반)",
        ]

        for pattern in patterns:
            match = re.search(pattern, event_name)
            if match:
                return match.group(1)

        return ""

    def resolve_identities(self) -> int:
        """
        Main identity resolution algorithm.

        Strategy (우선순위):
        0. ABSOLUTE FIRST: Group by GENDER - 남/여 절대 불변 (다른 사람 확정)
        1. SECOND: Group by weapons - completely different weapons = different people
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

            # DEBUG: Check age regression on ALL records BEFORE gender split
            # This catches impossible progressions like 일반부→여중
            all_records_age_split = self._find_age_regression_split(sorted_records)
            if all_records_age_split:
                print(f"[DEBUG] Pre-gender age split for {name}: split at {all_records_age_split}")
                self._create_separate_profiles_by_age_split(name, sorted_records, all_records_age_split)
                continue  # Skip gender grouping - already split by age

            # Step 0: ABSOLUTE FIRST - Group by GENDER
            # Gender CANNOT change - Male vs Female = DEFINITELY different people
            gender_groups = self._group_by_gender(sorted_records)

            for gender_key, gender_records in gender_groups.items():
                # Step 1: Group by weapons within each gender group
                weapon_groups = self._group_by_weapons(gender_records)

                if len(weapon_groups) > 1:
                    # Multiple weapon groups = definitely different people
                    for weapon_key, weapon_records in weapon_groups.items():
                        overlapping_teams = self._find_overlapping_teams(weapon_records)
                        if overlapping_teams:
                            self._create_separate_profiles(name, weapon_records, overlapping_teams)
                        else:
                            if self._should_separate_by_team_pattern(weapon_records):
                                pseudo_overlapping = self._create_pseudo_overlapping(weapon_records)
                                self._create_separate_profiles(name, weapon_records, pseudo_overlapping)
                            else:
                                self._create_single_profile(name, weapon_records)
                else:
                    # Single weapon group - proceed with traditional algorithm
                    overlapping_teams = self._find_overlapping_teams(gender_records)

                    if overlapping_teams:
                        self._create_separate_profiles(name, gender_records, overlapping_teams)
                    else:
                        # Step 2: Check for AGE GROUP REGRESSION (impossible - different people)
                        age_split_point = self._find_age_regression_split(gender_records)
                        if age_split_point:
                            # DEBUG: print when age split is found
                            print(f"[DEBUG] Age split found for {name}: split at {age_split_point}")
                            self._create_separate_profiles_by_age_split(name, gender_records, age_split_point)
                        elif self._should_separate_by_team_pattern(gender_records):
                            pseudo_overlapping = self._create_pseudo_overlapping(gender_records)
                            self._create_separate_profiles(name, gender_records, pseudo_overlapping)
                        else:
                            self._create_single_profile(name, gender_records)

        # Post-resolution: Rebuild team_history for all profiles
        # This groups consecutive same-team records and preserves 원복 케이스
        for profile in self.profiles.values():
            profile.rebuild_team_history()

        # Assign special IDs for reference players
        return self._assign_special_ids()

    def _find_age_regression_split(self, records: List[Dict]) -> Optional[str]:
        """
        Find the date where age group regression occurs (impossible = different people).

        나이그룹 역행이 감지되면 분리 시점을 반환.
        예: 일반부(2024) → 여중(2025) = 불가능, 분리 필요

        Returns:
            The comp_date where regression starts, or None if no regression
        """
        sorted_records = sorted(
            [r for r in records if r.get('age_group')],
            key=lambda x: x.get('comp_date', '')
        )

        if len(sorted_records) < 2:
            return None

        prev_record = None
        for record in sorted_records:
            if prev_record:
                prev_date = prev_record.get('comp_date', '')
                curr_date = record.get('comp_date', '')
                prev_age = prev_record.get('age_group', '')
                curr_age = record.get('age_group', '')

                if prev_date and curr_date and curr_date > prev_date:
                    prev_level = get_age_group_level(prev_age)
                    curr_level = get_age_group_level(curr_age)

                    # Significant regression (2+ levels down) = definitely different person
                    # 일반부(9) → 여중(6) = 3 levels down = IMPOSSIBLE
                    if prev_level > 0 and curr_level > 0 and prev_level - curr_level >= 2:
                        return curr_date

            prev_record = record

        return None

    def _create_separate_profiles_by_age_split(
        self,
        name: str,
        records: List[Dict],
        split_date: str
    ) -> None:
        """
        Split records into two profiles based on age regression split point.

        Records before split_date = Person A (older/adult)
        Records from split_date = Person B (younger)

        IMPORTANT: Each split group still needs gender/overlap processing!
        """
        before_records = []
        after_records = []

        for record in records:
            comp_date = record.get('comp_date', '')
            if comp_date < split_date:
                before_records.append(record)
            else:
                after_records.append(record)

        # Process each group through gender/overlap detection
        for record_group in [before_records, after_records]:
            if not record_group:
                continue

            # Apply gender grouping to this subset
            self._process_records_with_gender_grouping(name, record_group)

    def _process_records_with_gender_grouping(self, name: str, records: List[Dict]) -> None:
        """
        Process records through gender and overlap detection.
        This is called for subsets after age-based splitting.
        """
        gender_groups = self._group_by_gender(records)

        for gender_key, gender_records in gender_groups.items():
            # Check for age regression within this gender group
            age_split_point = self._find_age_regression_split(gender_records)
            if age_split_point:
                print(f"[DEBUG] Post-gender age split for {name} ({gender_key}): split at {age_split_point}")
                # Recursively process the split groups
                self._create_separate_profiles_by_age_split(name, gender_records, age_split_point)
                continue

            weapon_groups = self._group_by_weapons(gender_records)

            if len(weapon_groups) > 1:
                for weapon_key, weapon_records in weapon_groups.items():
                    overlapping_teams = self._find_overlapping_teams(weapon_records)
                    if overlapping_teams:
                        self._create_separate_profiles(name, weapon_records, overlapping_teams)
                    else:
                        if self._should_separate_by_team_pattern(weapon_records):
                            pseudo_overlapping = self._create_pseudo_overlapping(weapon_records)
                            self._create_separate_profiles(name, weapon_records, pseudo_overlapping)
                        else:
                            self._create_single_profile(name, weapon_records)
            else:
                overlapping_teams = self._find_overlapping_teams(gender_records)

                if overlapping_teams:
                    self._create_separate_profiles(name, gender_records, overlapping_teams)
                else:
                    if self._should_separate_by_team_pattern(gender_records):
                        pseudo_overlapping = self._create_pseudo_overlapping(gender_records)
                        self._create_separate_profiles(name, gender_records, pseudo_overlapping)
                    else:
                        self._create_single_profile(name, gender_records)

    def _group_by_gender(self, records: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Group records by gender (ABSOLUTE - cannot change).

        Key insight: Gender is IMMUTABLE.
        - Same gender = could be same person
        - Different gender = DEFINITELY different people (absolute rule)

        Unknown gender records ('U') are assigned to known gender groups
        if they share the same team (team continuity assumption).
        If both M and F exist, unknown stays separate.

        Returns:
            Dict with keys: 'M' (male), 'F' (female), 'U' (unknown)
        """
        groups = {'M': [], 'F': [], 'U': []}

        # First pass: separate by known gender
        for record in records:
            event_name = record.get('event_name', '')
            gender = extract_gender(event_name)

            if gender == 'M':
                groups['M'].append(record)
            elif gender == 'F':
                groups['F'].append(record)
            else:
                groups['U'].append(record)

        # Second pass: try to assign unknown gender records to known groups
        # based on team continuity (same team = likely same person)
        if groups['U']:
            unknown_records = groups['U']
            groups['U'] = []

            # Get teams from known gender groups
            male_teams = set(r.get('team', '') for r in groups['M'] if r.get('team'))
            female_teams = set(r.get('team', '') for r in groups['F'] if r.get('team'))

            for record in unknown_records:
                team = record.get('team', '')

                if team:
                    # If team exists in only ONE gender group, assign to that group
                    in_male = team in male_teams
                    in_female = team in female_teams

                    if in_male and not in_female:
                        groups['M'].append(record)
                    elif in_female and not in_male:
                        groups['F'].append(record)
                    elif not in_male and not in_female:
                        # Team not in either group - check if only one gender exists
                        if groups['M'] and not groups['F']:
                            groups['M'].append(record)
                        elif groups['F'] and not groups['M']:
                            groups['F'].append(record)
                        else:
                            # Both exist or neither - keep unknown
                            groups['U'].append(record)
                    else:
                        # Team exists in both groups - ambiguous, keep unknown
                        groups['U'].append(record)
                else:
                    # No team info - keep unknown
                    groups['U'].append(record)

        # Remove empty groups
        return {k: v for k, v in groups.items() if v}

    def _try_assign_unknown_gender(self, records: List[Dict], known_genders: Dict[str, List[Dict]]) -> Dict[str, List[Dict]]:
        """
        Try to assign unknown gender records to known gender groups based on team/time proximity.
        """
        # For now, keep unknowns separate - they'll be merged later if teams match
        return known_genders

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
        2. Same school level (중/고) in different provinces (region-aware, via _org_region_cache)
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

                    # Region check: same school level but different provinces
                    if self._org_region_cache:
                        p1 = self._org_region_cache.get(t1, {}).get("province", "")
                        p2 = self._org_region_cache.get(t2, {}).get("province", "")
                        if p1 and p2 and p1 != p2:
                            # Same school level in different provinces = different people
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
        Also includes KNOWN_HOMONYMS forced splits.
        Also detects same-event same-team duplicates (같은 팀 동명이인).
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

        # Detect same-event same-team duplicates (같은 이벤트에 같은 이름+같은 팀 2회+)
        # This catches same-team homonyms that can't be auto-separated
        if records:
            name = records[0].get("name", "")
            event_team_count: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
            for r in records:
                key = f"{r.get('comp_cd', '')}_{r.get('event_name', '')}"
                team = r.get("team", "")
                if team:
                    event_team_count[key][team] += 1
            for event_key, team_counts in event_team_count.items():
                for team, count in team_counts.items():
                    if count > 1:
                        logger.warning(
                            f"[동명이인-같은팀] '{name}' 같은 이벤트({event_key})에 "
                            f"같은 팀({team})으로 {count}회 등장 → 자동 분리 불가"
                        )

        # Inject known homonym forced splits
        if records:
            name = records[0].get("name", "")
            if name in self.KNOWN_HOMONYMS:
                record_teams = {r.get("team", "") for r in records if r.get("team")}
                for team_group_a, team_group_b in self.KNOWN_HOMONYMS[name]:
                    present_a = team_group_a & record_teams
                    present_b = team_group_b & record_teams
                    if present_a and present_b:
                        for ta in present_a:
                            for tb in present_b:
                                overlapping.add(tuple(sorted([ta, tb])))

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
                    except (ValueError, TypeError, IndexError):
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

    def search_players(self, query: str, include_history: bool = False) -> List[PlayerProfile]:
        """Search for players by name or team

        Args:
            query: Search query (name or team name)
            include_history: If True, also search team_history (for finding alumni/transferred players)

        When searching by team:
        - Default: Only returns players whose most recent competition was with that team
        - With include_history=True: Returns all players who ever played for that team
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

        # 3. Search by team history (alumni/transferred players)
        if include_history:
            for player_id, profile in self.profiles.items():
                if player_id in results_set:
                    continue
                # Check if query matches any team in history
                for team_record in profile.team_history:
                    if team_record.team and query_lower in team_record.team.lower():
                        results.append(profile)
                        results_set.add(player_id)
                        break

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
