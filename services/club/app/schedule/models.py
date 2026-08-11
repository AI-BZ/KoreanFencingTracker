"""
Schedule Models - 일정 관리 Pydantic 모델
"""

from datetime import date, datetime
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field


# =============================================
# Enums
# =============================================

class EventType(str, Enum):
    """일정 유형"""
    training = "training"           # 정규 훈련
    lesson = "lesson"               # 개인/그룹 레슨
    competition = "competition"     # 대회
    club_event = "club_event"       # 클럽 행사
    holiday = "holiday"             # 휴일/휴무
    personal = "personal"           # 개인 일정
    meeting = "meeting"             # 미팅/회의


class EventVisibility(str, Enum):
    """일정 공개 범위"""
    club = "club"           # 클럽 전체 공개
    coaches = "coaches"     # 코치 이상만
    personal = "personal"   # 본인만


class EventStatus(str, Enum):
    """일정 상태"""
    scheduled = "scheduled"     # 예정
    in_progress = "in_progress" # 진행중
    completed = "completed"     # 완료
    cancelled = "cancelled"     # 취소


class RecurrenceFreq(str, Enum):
    """반복 주기"""
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"


# =============================================
# Default colors per event type
# =============================================

EVENT_COLORS = {
    "training": "#667eea",      # 파란색 - 정규 훈련
    "lesson": "#48bb78",        # 초록색 - 레슨
    "competition": "#ed8936",   # 주황색 - 대회
    "club_event": "#9f7aea",    # 보라색 - 클럽 행사
    "holiday": "#fc8181",       # 빨간색 - 휴일
    "personal": "#4fd1c5",      # 청록색 - 개인
    "meeting": "#f6ad55",       # 황금색 - 미팅
}


# =============================================
# Request Models
# =============================================

class RecurrenceRule(BaseModel):
    """반복 규칙"""
    freq: RecurrenceFreq
    days: Optional[List[int]] = None  # 0=Mon, 6=Sun (weekly용)
    until: Optional[date] = None      # 반복 종료일


class ScheduleCreate(BaseModel):
    """일정 생성"""
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    event_type: EventType
    color: Optional[str] = None  # None이면 event_type 기본 색상

    start_at: datetime
    end_at: datetime
    all_day: bool = False

    is_recurring: bool = False
    recurrence_rule: Optional[RecurrenceRule] = None

    visibility: EventVisibility = EventVisibility.club
    assigned_coach_id: Optional[str] = None
    participant_ids: Optional[List[str]] = None
    max_participants: Optional[int] = None

    lesson_id: Optional[str] = None
    competition_id: Optional[int] = None
    location: Optional[str] = None


class ScheduleUpdate(BaseModel):
    """일정 수정"""
    title: Optional[str] = None
    description: Optional[str] = None
    event_type: Optional[EventType] = None
    color: Optional[str] = None

    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    all_day: Optional[bool] = None

    visibility: Optional[EventVisibility] = None
    assigned_coach_id: Optional[str] = None
    participant_ids: Optional[List[str]] = None
    max_participants: Optional[int] = None

    location: Optional[str] = None
    status: Optional[EventStatus] = None


# =============================================
# Response Models
# =============================================

class ScheduleResponse(BaseModel):
    """일정 응답 (FullCalendar 호환)"""
    id: str
    title: str
    description: Optional[str] = None
    event_type: EventType
    color: str

    start: str   # ISO 8601 (FullCalendar 필드명)
    end: str     # ISO 8601
    allDay: bool = False  # FullCalendar camelCase

    is_recurring: bool = False
    recurrence_rule: Optional[dict] = None
    recurrence_parent_id: Optional[str] = None

    created_by: str
    creator_name: Optional[str] = None
    visibility: EventVisibility

    assigned_coach_id: Optional[str] = None
    coach_name: Optional[str] = None
    participant_ids: Optional[List[str]] = None
    max_participants: Optional[int] = None

    lesson_id: Optional[str] = None
    competition_id: Optional[int] = None
    location: Optional[str] = None
    status: EventStatus = EventStatus.scheduled

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ScheduleListResponse(BaseModel):
    """일정 목록 (캘린더 뷰용)"""
    total: int
    events: List[ScheduleResponse]


class CoachOption(BaseModel):
    """코치 목록 (드롭다운용)"""
    id: str
    name: str
    role: str


class MemberOption(BaseModel):
    """회원 목록 (참가자 선택용)"""
    id: str
    name: str
    role: str
