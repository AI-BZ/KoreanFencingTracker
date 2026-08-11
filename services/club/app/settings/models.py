"""
Settings Models - 클럽 설정 및 회원 승인 Pydantic 모델
"""

from datetime import datetime
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field

from shared_core.types.member import ClubRole


# =============================================
# Enums
# =============================================

class ApprovalStatus(str, Enum):
    """회원 승인 상태"""
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class ApprovalAction(str, Enum):
    """승인/거절 액션"""
    approve = "approve"
    reject = "reject"


# =============================================
# Club Profile Models
# =============================================

class ClubProfile(BaseModel):
    """클럽 프로필 수정 요청"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    address: Optional[str] = Field(None, max_length=200)
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = Field(None, max_length=100)
    website: Optional[str] = Field(None, max_length=200)
    logo_url: Optional[str] = Field(None, max_length=500)
    established_year: Optional[int] = Field(None, ge=1900, le=2100)


class ClubProfileResponse(BaseModel):
    """클럽 프로필 응답 (organizations + club_settings 병합)"""
    # Organizations 필드
    id: int
    name: str
    description: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    logo_url: Optional[str] = None
    established_year: Optional[int] = None

    # Club Settings 필드
    auto_checkin_ip: Optional[str] = None
    auto_checkin_enabled: bool = False
    default_lesson_fee: Optional[int] = None
    default_monthly_fee: Optional[int] = None
    wifi_ssid: Optional[str] = None
    wifi_bssid: Optional[str] = None
    qr_refresh_minutes: Optional[int] = None
    geofence_lat: Optional[float] = None
    geofence_lng: Optional[float] = None
    geofence_radius_m: Optional[int] = None


# =============================================
# Club Settings Models
# =============================================

class ClubSettingsUpdate(BaseModel):
    """클럽 설정 수정 요청"""
    auto_checkin_ip: Optional[str] = Field(None, max_length=100)
    auto_checkin_enabled: Optional[bool] = None
    default_lesson_fee: Optional[int] = Field(None, ge=0)
    default_monthly_fee: Optional[int] = Field(None, ge=0)
    wifi_ssid: Optional[str] = Field(None, max_length=100)
    wifi_bssid: Optional[str] = Field(None, max_length=100)
    qr_refresh_minutes: Optional[int] = Field(None, ge=1, le=60)
    geofence_lat: Optional[float] = Field(None, ge=-90, le=90)
    geofence_lng: Optional[float] = Field(None, ge=-180, le=180)
    geofence_radius_m: Optional[int] = Field(None, ge=10, le=5000)


class ClubSettingsResponse(BaseModel):
    """클럽 설정 응답"""
    organization_id: int
    auto_checkin_ip: Optional[str] = None
    auto_checkin_enabled: bool = False
    default_lesson_fee: Optional[int] = None
    default_monthly_fee: Optional[int] = None
    wifi_ssid: Optional[str] = None
    wifi_bssid: Optional[str] = None
    qr_refresh_minutes: Optional[int] = None
    geofence_lat: Optional[float] = None
    geofence_lng: Optional[float] = None
    geofence_radius_m: Optional[int] = None


# =============================================
# Member Approval Models
# =============================================

class MemberApprovalRequest(BaseModel):
    """회원 승인/거절 요청"""
    member_id: str
    action: ApprovalAction
    role: Optional[ClubRole] = None  # 승인 시 역할 지정
    rejection_reason: Optional[str] = Field(None, max_length=500)


class PendingMemberResponse(BaseModel):
    """승인 대기 회원 응답"""
    id: str
    full_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    requested_at: Optional[datetime] = None
    approval_status: ApprovalStatus = ApprovalStatus.pending


class MembershipRequest(BaseModel):
    """회원 가입 신청 요청 (비인증 공개 API)"""
    full_name: str = Field(..., min_length=1, max_length=50)
    email: str = Field(..., min_length=3, max_length=100)
    phone: Optional[str] = Field(None, max_length=20)
    message: Optional[str] = Field(None, max_length=500)


# =============================================
# Member Statistics Models
# =============================================

class MemberStatsResponse(BaseModel):
    """회원 통계 응답"""
    total_members: int = 0
    active_members: int = 0
    inactive_members: int = 0
    pending_members: int = 0
    by_role: dict = {}  # {"student": 10, "coach": 2, ...}
    by_status: dict = {}  # {"active": 10, "inactive": 2, ...}
    recent_joins: List[dict] = []  # 최근 가입 회원 목록
