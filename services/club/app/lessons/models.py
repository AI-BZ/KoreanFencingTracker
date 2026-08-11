"""
Lessons Models - 레슨 패키지 & 예약 Pydantic 모델
"""

from datetime import date, datetime, time
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field


# =============================================
# Enums
# =============================================

class PackageType(str, Enum):
    """패키지 유형"""
    ten_pack = "10_pack"
    twenty_pack = "20_pack"
    single = "single"
    custom = "custom"


class PackageStatus(str, Enum):
    """패키지 상태"""
    active = "active"
    exhausted = "exhausted"
    expired = "expired"
    cancelled = "cancelled"


class LessonRequestStatus(str, Enum):
    """레슨 신청 상태"""
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    rescheduled = "rescheduled"
    cancelled = "cancelled"


# =============================================
# 패키지 Request Models
# =============================================

class LessonPackageCreate(BaseModel):
    """레슨 패키지 생성 (코치가 등록)"""
    member_id: str = Field(..., description="구매한 선수 ID")
    coach_id: str = Field(..., description="담당 코치 ID")
    package_type: PackageType
    total_sessions: int = Field(..., gt=0, description="총 회수")
    price_per_session: Optional[int] = Field(None, ge=0, description="회당 금액")
    total_price: int = Field(..., ge=0, description="총 결제 금액")
    expires_at: Optional[datetime] = Field(None, description="만료일")
    notes: Optional[str] = None


class LessonPackageUpdate(BaseModel):
    """레슨 패키지 수정"""
    total_sessions: Optional[int] = Field(None, gt=0)
    expires_at: Optional[datetime] = None
    status: Optional[PackageStatus] = None
    notes: Optional[str] = None


# =============================================
# 패키지 Response Models
# =============================================

class LessonPackageResponse(BaseModel):
    """레슨 패키지 응답"""
    id: str
    organization_id: int
    member_id: str
    member_name: Optional[str] = None
    coach_id: str
    coach_name: Optional[str] = None
    package_type: str
    total_sessions: int
    used_sessions: int
    remaining_sessions: int
    price_per_session: Optional[int] = None
    total_price: int
    purchased_at: datetime
    expires_at: Optional[datetime] = None
    status: str
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class LessonDeductionResponse(BaseModel):
    """차감 기록 응답"""
    id: str
    package_id: str
    lesson_id: Optional[str] = None
    deducted_at: datetime
    deducted_by: str
    deductor_name: Optional[str] = None
    notes: Optional[str] = None


class LessonPackageDetailResponse(LessonPackageResponse):
    """패키지 상세 (차감 이력 포함)"""
    deductions: List[LessonDeductionResponse] = []


class MyPackageSummary(BaseModel):
    """내 패키지 현황 요약"""
    total_active_packages: int = 0
    total_remaining: int = 0
    packages: List[LessonPackageResponse] = []


# =============================================
# 레슨 신청 Request Models
# =============================================

class LessonRequestCreate(BaseModel):
    """레슨 신청 (학생/학부모)"""
    coach_id: str = Field(..., description="코치 ID")
    student_id: Optional[str] = Field(None, description="학생 ID (학부모 대리 신청 시)")
    requested_date: date = Field(..., description="신청 날짜")
    requested_start_time: time = Field(..., description="신청 시작 시간")
    duration_minutes: int = Field(60, gt=0, le=180, description="레슨 시간(분)")


class LessonRequestRespond(BaseModel):
    """레슨 신청 응답 (코치)"""
    coach_note: Optional[str] = None


class LessonRequestReschedule(BaseModel):
    """레슨 시간 변경 제안 (코치)"""
    rescheduled_date: date
    rescheduled_time: time
    coach_note: Optional[str] = None


# =============================================
# 레슨 신청 Response Models
# =============================================

class LessonRequestResponse(BaseModel):
    """레슨 신청 응답"""
    id: str
    organization_id: int
    student_id: str
    student_name: Optional[str] = None
    coach_id: str
    coach_name: Optional[str] = None
    requested_by: str
    requester_name: Optional[str] = None
    requested_date: str
    requested_start_time: str
    duration_minutes: int
    status: str
    coach_note: Optional[str] = None
    rescheduled_date: Optional[str] = None
    rescheduled_time: Optional[str] = None
    created_at: datetime
    responded_at: Optional[datetime] = None


# =============================================
# 빈 시간 조회
# =============================================

class AvailableSlot(BaseModel):
    """코치 빈 시간 슬롯"""
    date: str
    start_time: str
    end_time: str
    is_available: bool = True


class CoachAvailability(BaseModel):
    """코치 빈 시간 응답"""
    coach_id: str
    coach_name: Optional[str] = None
    date: str
    slots: List[AvailableSlot] = []


# =============================================
# 공강 알림 구독
# =============================================

class VacancySubscribeCreate(BaseModel):
    """공강 알림 수신 등록"""
    coach_id: Optional[str] = Field(None, description="특정 코치만 (NULL=전체)")
    weekdays: Optional[List[int]] = Field(None, description="수신 요일 [1=월,...,7=일]")
    time_range_start: Optional[time] = None
    time_range_end: Optional[time] = None


class VacancySubscriptionResponse(BaseModel):
    """공강 알림 구독 응답"""
    id: str
    member_id: str
    coach_id: Optional[str] = None
    coach_name: Optional[str] = None
    weekdays: Optional[List[int]] = None
    time_range_start: Optional[str] = None
    time_range_end: Optional[str] = None
    is_active: bool = True
