"""
Checkin Models

체크인/체크아웃 관련 Pydantic 모델 정의
"""

from datetime import datetime
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field


# =============================================
# Enums
# =============================================

class CheckinMethod(str, Enum):
    """체크인 방식"""
    auto_ip = "auto_ip"           # IP 기반 자동
    manual = "manual"             # 수동 (코치 전용)
    qr = "qr"                     # QR 코드 스캔
    gps = "gps"                   # GPS 위치 인증
    wifi = "wifi"                 # WiFi SSID 매칭
    coach_proxy = "coach_proxy"   # 코치 대리 체크인


class CheckoutMethod(str, Enum):
    """체크아웃 방식"""
    manual = "manual"       # 수동 버튼
    timeout = "timeout"     # 자동 타임아웃
    auto = "auto"           # 자동 (스케줄)


# =============================================
# Request Models
# =============================================

class CheckinRequest(BaseModel):
    """통합 체크인 요청"""
    method: CheckinMethod = CheckinMethod.auto_ip
    qr_code: Optional[str] = None
    wifi_ssid: Optional[str] = None
    wifi_bssid: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    attendance_type: str = "regular"
    notes: Optional[str] = None


class CheckoutRequest(BaseModel):
    """체크아웃 요청"""
    method: Optional[CheckoutMethod] = CheckoutMethod.manual


# =============================================
# Response Models
# =============================================

class CheckinResponse(BaseModel):
    """체크인 응답"""
    success: bool
    member_name: str
    check_in_at: datetime
    method: CheckinMethod
    message: str


class CheckoutResponse(BaseModel):
    """체크아웃 응답"""
    success: bool
    member_name: str
    checked_out_at: datetime
    duration_minutes: int
    message: str


class QRSessionResponse(BaseModel):
    """QR 세션 응답"""
    qr_code: str
    valid_until: datetime
    qr_image_data_url: Optional[str] = None


class AttendanceRecord(BaseModel):
    """출석 기록"""
    id: str
    member_id: str
    member_name: str
    check_in_at: datetime
    checked_out_at: Optional[datetime] = None
    method: Optional[str] = None
    duration_minutes: Optional[int] = None
    wifi_ssid: Optional[str] = None


class AttendanceStats(BaseModel):
    """출석 통계"""
    total_days: int = 0
    this_month: int = 0
    streak: int = 0
    avg_duration_minutes: Optional[float] = None


class WiFiCheckinConfig(BaseModel):
    """WiFi 체크인 설정"""
    ssid: Optional[str] = None
    bssid: Optional[str] = None


class WiFiConfigUpdate(BaseModel):
    """WiFi 설정 업데이트"""
    ssid: str = Field(..., min_length=1, max_length=100)
    bssid: Optional[str] = Field(None, max_length=50)
