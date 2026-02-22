"""
Club Management Models

Pydantic 모델 정의
"""

from datetime import date, datetime
from typing import Optional, List, Union
from enum import Enum
from pydantic import BaseModel, Field


# =============================================
# Enums
# =============================================

class ClubRole(str, Enum):
    """클럽 내 역할"""
    owner = "owner"           # 클럽 소유자/대표
    head_coach = "head_coach" # 수석 코치
    coach = "coach"           # 코치
    assistant = "assistant"   # 보조 코치
    student = "student"       # 수강생
    parent = "parent"         # 학부모
    staff = "staff"           # 행정 스태프


class MemberStatus(str, Enum):
    """회원 상태"""
    active = "active"         # 활성
    inactive = "inactive"     # 휴회
    suspended = "suspended"   # 정지
    graduated = "graduated"   # 졸업/퇴회


class AttendanceType(str, Enum):
    """출석 유형"""
    regular = "regular"       # 정규 훈련
    lesson = "lesson"         # 개인/그룹 레슨
    competition = "competition"  # 대회 참가
    makeup = "makeup"         # 보강
    trial = "trial"           # 체험


class CheckinMethod(str, Enum):
    """체크인 방식"""
    manual = "manual"         # 수동 버튼
    auto_ip = "auto_ip"       # IP 기반 자동
    auto_wifi = "auto_wifi"   # WiFi 기반 자동
    auto_geo = "auto_geo"     # GPS 기반 자동
    coach = "coach"           # 코치가 대신 체크인


class FeeType(str, Enum):
    """비용 유형"""
    membership = "membership"   # 월회비
    lesson = "lesson"           # 레슨비
    competition = "competition" # 대회비
    equipment = "equipment"     # 장비비
    uniform = "uniform"         # 유니폼비
    registration = "registration"  # 등록비
    other = "other"             # 기타


class FeeStatus(str, Enum):
    """납부 상태"""
    pending = "pending"       # 대기
    paid = "paid"             # 납부완료
    overdue = "overdue"       # 연체
    waived = "waived"         # 면제
    refunded = "refunded"     # 환불


class LessonType(str, Enum):
    """레슨 유형"""
    individual = "individual"   # 개인 레슨
    group = "group"             # 그룹 레슨 (2-4명)
    team = "team"               # 팀 훈련
    special = "special"         # 특별 레슨 (집중/캠프)


class LessonStatus(str, Enum):
    """레슨 상태"""
    scheduled = "scheduled"     # 예정
    in_progress = "in_progress" # 진행중
    completed = "completed"     # 완료
    cancelled = "cancelled"     # 취소


class ParticipantStatus(str, Enum):
    """참가자 출석 상태"""
    registered = "registered"   # 등록됨
    attended = "attended"       # 출석
    absent = "absent"           # 결석
    cancelled = "cancelled"     # 취소


# =============================================
# Player Data Models (핵심 기능)
# =============================================

class PlayerSearchResult(BaseModel):
    """선수 검색 결과"""
    player_id: Union[int, str]  # int (기존) 또는 str (KOP00000 형식)
    name: str
    team: Optional[str] = None
    weapon: Optional[str] = None
    birth_year: Optional[int] = None
    competition_count: int = 0
    is_linked: bool = False  # 이미 클럽 회원과 연결됨


class PlayerProfile(BaseModel):
    """선수 프로필"""
    player_id: Union[int, str]  # int (기존) 또는 str (KOP00000 형식)
    name: str
    team: Optional[str] = None
    weapon: Optional[str] = None
    birth_year: Optional[int] = None
    nationality: Optional[str] = None

    # 통계
    total_competitions: int = 0
    total_events: int = 0
    gold_medals: int = 0
    silver_medals: int = 0
    bronze_medals: int = 0

    # 최근 랭킹
    current_rankings: List["RankingInfo"] = []


class RankingInfo(BaseModel):
    """랭킹 정보"""
    weapon: str
    gender: str
    age_group: str
    rank: int
    points: float
    year: int


class CompetitionHistory(BaseModel):
    """대회 출전 히스토리"""
    competition_id: int
    competition_name: str
    competition_date: date
    event_name: str
    final_rank: Optional[int] = None
    pool_rank: Optional[int] = None
    pool_wins: int = 0
    pool_losses: int = 0
    de_rounds_won: int = 0


class HeadToHeadRecord(BaseModel):
    """상대 전적"""
    opponent_id: int
    opponent_name: str
    opponent_team: Optional[str] = None
    total_bouts: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    recent_bouts: List["BoutRecord"] = []


class BoutRecord(BaseModel):
    """경기 기록"""
    competition_name: str
    competition_date: date
    round_type: str  # pool, de
    round_name: str
    score: str  # "15-10"
    is_winner: bool


class PlayerStats(BaseModel):
    """선수 성과 지표"""
    player_id: Union[int, str]  # int (기존) 또는 str (KOP00000 형식)
    player_name: str

    # Pool 통계
    pool_total_bouts: int = 0
    pool_wins: int = 0
    pool_losses: int = 0
    pool_win_rate: float = 0.0
    pool_touches_scored: int = 0
    pool_touches_received: int = 0
    pool_indicator: int = 0  # TS - TR

    # DE 통계
    de_total_events: int = 0
    de_advancement_rate: float = 0.0  # DE 진출률
    de_avg_rounds_won: float = 0.0

    # 전체 통계
    medal_count: int = 0
    avg_final_rank: Optional[float] = None


class TeamRoster(BaseModel):
    """클럽 소속 선수 명단"""
    organization_id: int
    organization_name: str
    total_members: int
    players: List["TeamMember"]


class TeamMember(BaseModel):
    """팀 멤버"""
    member_id: str
    player_id: Optional[Union[int, str]] = None  # int (기존) 또는 str (KOP00000 형식)
    name: str
    club_role: ClubRole
    status: MemberStatus
    weapon: Optional[str] = None

    # 연동된 선수 데이터
    competition_count: int = 0
    current_rank: Optional[int] = None
    recent_result: Optional[str] = None


# =============================================
# Member Management Models
# =============================================

class ClubMemberCreate(BaseModel):
    """클럽 회원 생성"""
    full_name: str
    email: str
    phone: Optional[str] = None
    birth_date: Optional[date] = None
    club_role: ClubRole = ClubRole.student
    enrollment_date: Optional[date] = None
    notes: Optional[str] = None

    # 선수 연결 (선택)
    player_id: Optional[Union[int, str]] = None  # int (기존) 또는 str (KOP00000 형식)


class ClubMemberUpdate(BaseModel):
    """클럽 회원 수정"""
    full_name: Optional[str] = None
    phone: Optional[str] = None
    club_role: Optional[ClubRole] = None
    member_status: Optional[MemberStatus] = None
    notes: Optional[str] = None
    player_id: Optional[Union[int, str]] = None  # int (기존) 또는 str (KOP00000 형식)


class ClubMemberResponse(BaseModel):
    """클럽 회원 응답"""
    id: str
    full_name: str
    email: str
    phone: Optional[str] = None
    birth_date: Optional[date] = None
    club_role: ClubRole
    member_status: MemberStatus
    enrollment_date: Optional[date] = None
    notes: Optional[str] = None

    # 연동된 선수 정보
    player_id: Optional[Union[int, str]] = None  # int (기존) 또는 str (KOP00000 형식)
    player_name: Optional[str] = None
    player_team: Optional[str] = None

    created_at: datetime


# =============================================
# Attendance Models
# =============================================

class CheckInRequest(BaseModel):
    """체크인 요청"""
    attendance_type: AttendanceType = AttendanceType.regular
    notes: Optional[str] = None


class CheckInResponse(BaseModel):
    """체크인 응답"""
    id: str
    member_id: str
    member_name: str
    check_in_at: datetime
    attendance_type: AttendanceType
    checkin_method: CheckinMethod
    auto_checkin_available: bool = False


class AttendanceRecord(BaseModel):
    """출석 기록"""
    id: str
    member_id: str
    member_name: str
    check_in_at: datetime
    check_out_at: Optional[datetime] = None
    attendance_type: AttendanceType
    checkin_method: CheckinMethod
    duration_minutes: Optional[int] = None


class DailyAttendance(BaseModel):
    """일별 출석 현황"""
    date: date
    total_checkins: int
    members: List[AttendanceRecord]


class AttendanceStats(BaseModel):
    """출석 통계"""
    period: str  # "2025-01" 또는 "2025-W01"
    total_days: int
    unique_members: int
    avg_daily_attendance: float
    by_member: List["MemberAttendanceStats"]


class MemberAttendanceStats(BaseModel):
    """회원별 출석 통계"""
    member_id: str
    member_name: str
    total_days: int
    regular_count: int
    lesson_count: int
    attendance_rate: float


# =============================================
# Fee Models
# =============================================

class FeeCreate(BaseModel):
    """비용 생성"""
    member_id: str
    fee_type: FeeType
    amount: int
    description: Optional[str] = None
    due_date: Optional[date] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None


class FeeBulkCreate(BaseModel):
    """월회비 일괄 생성"""
    fee_type: FeeType = FeeType.membership
    amount: int
    period_year: int
    period_month: int
    due_date: date
    member_ids: Optional[List[str]] = None  # None이면 전체 활성 회원


class FeeConfirm(BaseModel):
    """납부 확인"""
    payment_method: str
    payment_reference: Optional[str] = None


class FeeResponse(BaseModel):
    """비용 응답"""
    id: str
    member_id: str
    member_name: str
    fee_type: FeeType
    amount: int
    description: Optional[str] = None
    status: FeeStatus
    due_date: Optional[date] = None
    paid_at: Optional[datetime] = None
    payment_method: Optional[str] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None


class FeeSummary(BaseModel):
    """비용 요약"""
    period: str
    total_expected: int
    total_paid: int
    total_pending: int
    total_overdue: int
    collection_rate: float


# =============================================
# Club Dashboard Models
# =============================================

class ClubDashboard(BaseModel):
    """클럽 대시보드"""
    organization_id: int
    organization_name: str

    # 오늘 현황
    today_attendance: int
    today_checkins: List["TodayCheckin"]

    # 회원 현황
    total_members: int
    active_students: int
    active_coaches: int

    # 비용 현황
    pending_fees: int
    overdue_fees: int
    this_month_collection: int

    # 예정 대회
    upcoming_competitions: List["UpcomingCompetition"]

    # 알림
    alerts: List["DashboardAlert"]


class TodayCheckin(BaseModel):
    """오늘 체크인"""
    member_id: str
    member_name: str
    check_in_at: datetime
    attendance_type: AttendanceType


class UpcomingCompetition(BaseModel):
    """예정 대회"""
    competition_id: Optional[int] = None
    competition_name: str
    competition_date: date
    participant_count: int


class DashboardAlert(BaseModel):
    """대시보드 알림"""
    alert_type: str  # overdue_fee, absent_member, upcoming_competition
    message: str
    severity: str  # info, warning, error
    related_id: Optional[str] = None


# =============================================
# Lesson Models
# =============================================

class LessonCreate(BaseModel):
    """레슨 생성"""
    lesson_type: LessonType
    title: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    scheduled_at: datetime
    duration_minutes: int = Field(default=60, ge=15, le=480)
    coach_id: Optional[str] = None  # None이면 현재 코치
    max_students: int = Field(default=1, ge=1, le=20)
    fee_per_session: int = Field(default=0, ge=0)
    participant_ids: Optional[List[str]] = None  # 참가자 member_id 목록


class LessonUpdate(BaseModel):
    """레슨 수정"""
    title: Optional[str] = None
    description: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    coach_id: Optional[str] = None
    max_students: Optional[int] = None
    fee_per_session: Optional[int] = None
    status: Optional[LessonStatus] = None


class LessonParticipant(BaseModel):
    """레슨 참가자"""
    id: str
    member_id: str
    member_name: str
    attendance_status: ParticipantStatus
    attended_at: Optional[datetime] = None


class LessonResponse(BaseModel):
    """레슨 응답"""
    id: str
    organization_id: int
    lesson_type: LessonType
    title: str
    description: Optional[str] = None
    scheduled_at: datetime
    duration_minutes: int
    coach_id: str
    coach_name: Optional[str] = None
    max_students: int
    fee_per_session: int
    status: LessonStatus
    participant_count: int = 0
    created_at: datetime
    updated_at: datetime


class LessonDetail(BaseModel):
    """레슨 상세 (참가자 포함)"""
    id: str
    organization_id: int
    lesson_type: LessonType
    title: str
    description: Optional[str] = None
    scheduled_at: datetime
    duration_minutes: int
    coach_id: str
    coach_name: Optional[str] = None
    max_students: int
    fee_per_session: int
    status: LessonStatus
    participants: List[LessonParticipant]
    created_at: datetime
    updated_at: datetime


class LessonCalendar(BaseModel):
    """레슨 캘린더 뷰"""
    date: date
    lessons: List[LessonResponse]


class LessonStats(BaseModel):
    """레슨 통계"""
    period: str  # "2025-01" 또는 "2025-W01"
    total_lessons: int
    completed_lessons: int
    cancelled_lessons: int
    total_participants: int
    total_revenue: int  # fee_per_session * participants
    by_type: dict  # {individual: 5, group: 3, ...}
    by_coach: List[dict]  # [{coach_name: "김코치", count: 8}, ...]


class ParticipantAdd(BaseModel):
    """참가자 추가"""
    member_ids: List[str]


class ParticipantAttendance(BaseModel):
    """참가자 출석 확인"""
    attendance_status: ParticipantStatus


# Forward references 해결
PlayerProfile.model_rebuild()
HeadToHeadRecord.model_rebuild()
TeamRoster.model_rebuild()
AttendanceStats.model_rebuild()
