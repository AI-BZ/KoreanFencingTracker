"""
Notification Models - 알림 Pydantic 모델
"""

from datetime import datetime
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field


class NotificationType(str, Enum):
    """알림 유형"""
    invoice = "invoice"               # 청구서 발송
    reminder = "reminder"             # 미납 리마인더
    payment_confirm = "payment_confirm"  # 납부 확인
    checkin = "checkin"               # 체크인 관련
    lesson = "lesson"                 # 레슨 관련
    competition = "competition"       # 대회 관련
    system = "system"                 # 시스템 공지


class NotificationChannel(str, Enum):
    """알림 채널"""
    fcm = "fcm"           # Firebase Cloud Messaging (무료)
    alimtalk = "alimtalk" # 카카오 알림톡 (유료, 구독 필요)
    sms = "sms"           # SMS (fallback)
    app = "app"           # 앱 내 알림 (DB 기록만)


class NotificationStatus(str, Enum):
    """알림 상태"""
    pending = "pending"
    sent = "sent"
    failed = "failed"
    read = "read"


class DeviceType(str, Enum):
    """디바이스 유형"""
    ios = "ios"
    android = "android"
    web = "web"


# =============================================
# Request Models
# =============================================

class PushTokenRegister(BaseModel):
    """FCM 푸시 토큰 등록"""
    token: str
    device_type: DeviceType
    device_name: Optional[str] = None


class NotificationSend(BaseModel):
    """알림 발송 요청 (코치용)"""
    member_ids: List[str]
    notification_type: NotificationType
    title: str = Field(..., max_length=200)
    message: str
    channels: List[NotificationChannel] = [NotificationChannel.fcm, NotificationChannel.app]
    # alimtalk 포함 시 구독 등급 체크
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None


class NotificationBulkSend(BaseModel):
    """일괄 알림 (청구서 발송 등)"""
    invoice_id: Optional[int] = None  # 청구서 연동 시
    notification_type: NotificationType
    title: str
    message: str
    channels: List[NotificationChannel] = [NotificationChannel.fcm, NotificationChannel.app]


# =============================================
# Response Models
# =============================================

class NotificationResponse(BaseModel):
    """알림 응답"""
    id: int
    notification_type: NotificationType
    channel: NotificationChannel
    title: Optional[str] = None
    message: Optional[str] = None
    status: NotificationStatus
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None
    sent_at: Optional[datetime] = None
    read_at: Optional[datetime] = None
    created_at: datetime


class NotificationListResponse(BaseModel):
    """알림 목록"""
    total: int
    unread_count: int
    notifications: List[NotificationResponse]


class PushTokenResponse(BaseModel):
    """푸시 토큰 응답"""
    id: int
    device_type: DeviceType
    device_name: Optional[str] = None
    is_active: bool
    last_used_at: datetime


class NotificationStatsResponse(BaseModel):
    """알림 통계"""
    total_sent: int
    fcm_sent: int
    alimtalk_sent: int
    alimtalk_limit: int
    alimtalk_remaining: int
    failed_count: int


# =============================================
# Vacancy (공강) Notification Models
# =============================================

class VacancySubscription(BaseModel):
    """공강 알림 구독 요청"""
    coach_id: Optional[str] = None  # NULL = 전체 코치
    day_of_week: Optional[List[int]] = None  # 0=월, 6=일
    time_start: Optional[str] = None  # "14:00"
    time_end: Optional[str] = None    # "18:00"


class VacancySubscriptionResponse(BaseModel):
    """공강 알림 구독 응답"""
    id: str
    coach_id: Optional[str] = None
    coach_name: Optional[str] = None
    day_of_week: Optional[List[int]] = None
    time_start: Optional[str] = None
    time_end: Optional[str] = None
    is_active: bool


class VacancyNotifyRequest(BaseModel):
    """공강 알림 발송 요청 (코치용)"""
    lesson_id: int
    coach_id: str
    day_of_week: Optional[int] = None  # 0=월, 6=일
    time_start: Optional[str] = None   # "14:00"
    time_end: Optional[str] = None     # "15:00"


class VacancyNotifyResponse(BaseModel):
    """공강 알림 발송 결과"""
    total: int
    sent: int
    failed: int
