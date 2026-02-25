"""
Competitions Models - 대회 참가 관리 Pydantic 모델
"""

from datetime import date, datetime
from typing import Optional, Dict
from enum import Enum
from pydantic import BaseModel, Field


# =============================================
# Enums
# =============================================

class EventStatus(str, Enum):
    """대회 이벤트 상태"""
    upcoming = "upcoming"
    ongoing = "ongoing"
    completed = "completed"
    cancelled = "cancelled"
    closed = "closed"


class RSVPStatus(str, Enum):
    """RSVP 응답 상태"""
    attending = "attending"
    not_attending = "not_attending"
    maybe = "maybe"


class EventSource(str, Enum):
    """이벤트 소스"""
    manual = "manual"
    data_sync = "data_sync"


# =============================================
# Competition Event Request Models
# =============================================

class CompetitionEventCreate(BaseModel):
    """대회 이벤트 생성"""
    name: str = Field(..., max_length=200, description="대회명")
    start_date: date = Field(..., description="시작일")
    end_date: Optional[date] = Field(None, description="종료일")
    location: Optional[str] = Field(None, max_length=200, description="개최 장소")
    weapon: Optional[str] = Field(None, max_length=20, description="무기 (foil/epee/sabre)")
    age_group: Optional[str] = Field(None, max_length=50, description="나이 그룹")
    entry_fee: int = Field(0, ge=0, description="참가비 (원)")
    coach_travel_fee: int = Field(0, ge=0, description="코치 교통비 (원)")
    transportation_fee: int = Field(0, ge=0, description="교통비 (원)")
    rsvp_deadline: Optional[date] = Field(None, description="RSVP 마감일")
    competition_id: Optional[int] = Field(None, description="data 서비스 competition ID (연동용)")


class CompetitionEventUpdate(BaseModel):
    """대회 이벤트 수정 (모든 필드 optional)"""
    name: Optional[str] = Field(None, max_length=200)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    location: Optional[str] = Field(None, max_length=200)
    weapon: Optional[str] = Field(None, max_length=20)
    age_group: Optional[str] = Field(None, max_length=50)
    entry_fee: Optional[int] = Field(None, ge=0)
    coach_travel_fee: Optional[int] = Field(None, ge=0)
    transportation_fee: Optional[int] = Field(None, ge=0)
    rsvp_deadline: Optional[date] = None
    status: Optional[EventStatus] = None
    competition_id: Optional[int] = None


# =============================================
# Competition Event Response Models
# =============================================

class RSVPSummary(BaseModel):
    """RSVP 요약"""
    attending_count: int = 0
    not_attending_count: int = 0
    maybe_count: int = 0


class CompetitionEventResponse(BaseModel):
    """대회 이벤트 응답"""
    id: str
    organization_id: int
    competition_id: Optional[int] = None
    name: str
    start_date: str
    end_date: Optional[str] = None
    location: Optional[str] = None
    weapon: Optional[str] = None
    age_group: Optional[str] = None
    entry_fee: int = 0
    coach_travel_fee: int = 0
    transportation_fee: int = 0
    rsvp_deadline: Optional[str] = None
    is_auto_synced: bool = False
    source: str = "manual"
    status: str = "upcoming"
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    rsvp_summary: RSVPSummary = RSVPSummary()


# =============================================
# RSVP Models
# =============================================

class RSVPCreate(BaseModel):
    """RSVP 응답 생성"""
    status: RSVPStatus = Field(..., description="참석 여부")
    reason: Optional[str] = Field(None, description="사유")


class RSVPResponse(BaseModel):
    """RSVP 응답"""
    id: str
    event_id: str
    member_id: str
    member_name: Optional[str] = None
    responded_by: Optional[str] = None
    status: str
    reason: Optional[str] = None
    responded_at: Optional[datetime] = None


# =============================================
# Cost Summary
# =============================================

class CompetitionCostSummary(BaseModel):
    """대회 비용 정산 요약"""
    entry_fee_per_person: int = 0
    coach_travel_per_person: int = 0
    transport_per_person: int = 0
    total_per_person: int = 0
    attending_count: int = 0
