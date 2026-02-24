"""
Billing Models - 청구/결제/수납 Pydantic 모델
"""

from datetime import date, datetime
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field


# =============================================
# Enums
# =============================================

class InvoiceType(str, Enum):
    """청구서 유형"""
    monthly_dues = "monthly_dues"             # 월 회비
    lesson = "lesson"                         # 레슨비
    competition_entry = "competition_entry"   # 대회 출전비
    coach_travel = "coach_travel"             # 코치 출장비
    transportation = "transportation"         # 교통비
    equipment_repair = "equipment_repair"     # 장비 수리비
    equipment_purchase = "equipment_purchase" # 장비 구매비
    other = "other"                           # 기타


class InvoiceStatus(str, Enum):
    """청구서 상태"""
    draft = "draft"           # 작성 중
    sent = "sent"             # 발송됨
    partial = "partial"       # 부분 납부
    paid = "paid"             # 완납
    overdue = "overdue"       # 연체
    cancelled = "cancelled"   # 취소


class InvoiceMemberStatus(str, Enum):
    """멤버별 청구 상태"""
    pending = "pending"
    paid = "paid"
    partial = "partial"
    overdue = "overdue"
    waived = "waived"


class PaymentMethod(str, Enum):
    """결제 수단"""
    card = "card"                 # 카드 (PortOne)
    cash = "cash"                 # 현금
    bank_transfer = "bank_transfer"  # 계좌이체
    billing_key = "billing_key"   # 빌링키 자동결제


class PaymentStatus(str, Enum):
    """결제 상태"""
    success = "success"
    failed = "failed"
    refunded = "refunded"
    pending = "pending"


class SplitType(str, Enum):
    """분할 방식"""
    none = "none"
    equal = "equal"
    custom = "custom"


class RecurringBillType(str, Enum):
    """정기 청구 유형"""
    monthly_dues = "monthly_dues"
    lesson = "lesson"


class SubscriptionTier(str, Enum):
    """구독 등급"""
    free = "free"             # FCM only
    basic = "basic"           # 500 알림톡/월
    premium = "premium"       # 2000 알림톡/월
    enterprise = "enterprise" # 무제한


# 등급별 알림톡 한도
TIER_ALIMTALK_LIMITS = {
    "free": 0,
    "basic": 500,
    "premium": 2000,
    "enterprise": -1,  # unlimited
}


# =============================================
# Request Models
# =============================================

class InvoiceCreate(BaseModel):
    """청구서 생성"""
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    invoice_type: InvoiceType
    total_amount: int = Field(..., gt=0)
    due_date: Optional[date] = None
    member_ids: List[str]  # 청구 대상 멤버
    split_type: SplitType = SplitType.none
    # split_type=equal이면 total_amount를 member_ids 수로 나눔
    # split_type=none이면 각 멤버에게 total_amount 전액 청구
    # split_type=custom이면 amounts 필드 필요
    amounts: Optional[List[int]] = None  # custom split 시 멤버별 금액


class CompetitionSplitCreate(BaseModel):
    """대회 비용 분할 청구"""
    competition_id: Optional[int] = None
    competition_name: Optional[str] = None
    items: List["CompetitionCostItem"]
    member_ids: List[str]
    split_type: SplitType = SplitType.equal
    due_date: Optional[date] = None


class CompetitionCostItem(BaseModel):
    """대회 비용 항목"""
    invoice_type: InvoiceType
    title: str
    total: int = Field(..., gt=0)


class InvoiceUpdate(BaseModel):
    """청구서 수정 (draft 상태만)"""
    title: Optional[str] = None
    description: Optional[str] = None
    total_amount: Optional[int] = None
    due_date: Optional[date] = None


class PaymentCreate(BaseModel):
    """수납 등록 (코치가 현금/이체 확인)"""
    invoice_member_id: int
    amount: int = Field(..., gt=0)
    payment_method: PaymentMethod
    memo: Optional[str] = None


class BillingKeyRegister(BaseModel):
    """빌링키 등록 요청 (학부모가 카드 등록 후)"""
    billing_key: str
    card_name: Optional[str] = None
    card_number_masked: Optional[str] = None


class PortOnePaymentVerify(BaseModel):
    """PortOne 결제 검증 요청"""
    payment_id: str = Field(..., min_length=1)
    invoice_member_id: int


class BillingKeyIssue(BaseModel):
    """PortOne 빌링키 발급 요청 (카드 정보)"""
    customer_id: str = Field(..., min_length=1)
    card_number: str = Field(..., min_length=13, max_length=19)
    expiry: str = Field(..., description="YYYYMM 형식")
    birth_or_business: str = Field(..., min_length=6, max_length=10)
    password_two_digits: str = Field(..., min_length=2, max_length=2)


class RecurringBillCreate(BaseModel):
    """정기 청구 설정"""
    member_id: str
    bill_type: RecurringBillType
    amount: int = Field(..., gt=0)
    billing_day: int = Field(default=1, ge=1, le=28)
    auto_pay: bool = False


class RecurringBillUpdate(BaseModel):
    """정기 청구 수정"""
    amount: Optional[int] = None
    billing_day: Optional[int] = Field(default=None, ge=1, le=28)
    auto_pay: Optional[bool] = None
    is_active: Optional[bool] = None


class FeeTemplateCreate(BaseModel):
    """비용 템플릿 생성"""
    name: str = Field(..., min_length=1, max_length=100)
    fee_type: InvoiceType
    default_amount: int = Field(..., gt=0)
    description: Optional[str] = None


class FeeTemplateUpdate(BaseModel):
    """비용 템플릿 수정"""
    name: Optional[str] = None
    default_amount: Optional[int] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


# =============================================
# Response Models
# =============================================

class InvoiceMemberResponse(BaseModel):
    """멤버별 청구 상세"""
    id: int
    member_id: str
    member_name: Optional[str] = None
    amount: int
    status: InvoiceMemberStatus
    paid_amount: int = 0
    notified_at: Optional[datetime] = None
    reminder_count: int = 0
    paid_at: Optional[datetime] = None
    memo: Optional[str] = None


class InvoiceResponse(BaseModel):
    """청구서 응답"""
    id: int
    org_id: int
    created_by: str
    creator_name: Optional[str] = None
    title: str
    description: Optional[str] = None
    invoice_type: InvoiceType
    total_amount: int
    due_date: Optional[date] = None
    status: InvoiceStatus
    split_type: SplitType
    target_count: Optional[int] = None
    competition_id: Optional[int] = None
    member_count: int = 0
    paid_count: int = 0
    created_at: datetime
    updated_at: datetime


class InvoiceDetailResponse(InvoiceResponse):
    """청구서 상세 (멤버 포함)"""
    members: List[InvoiceMemberResponse] = []


class PaymentResponse(BaseModel):
    """수납 응답"""
    id: int
    invoice_member_id: int
    member_name: Optional[str] = None
    invoice_title: Optional[str] = None
    amount: int
    payment_method: PaymentMethod
    payment_status: PaymentStatus
    confirmed_by_name: Optional[str] = None
    memo: Optional[str] = None
    paid_at: datetime
    created_at: datetime


class PaymentSummaryResponse(BaseModel):
    """수납 현황 요약"""
    total_invoiced: int       # 총 청구 금액
    total_paid: int           # 총 수납 금액
    total_pending: int        # 미납 금액
    total_overdue: int        # 연체 금액
    collection_rate: float    # 수금률 (%)
    this_month_invoiced: int  # 이번 달 청구
    this_month_collected: int # 이번 달 수납
    outstanding_members: int  # 미납 회원 수


class BillingKeyResponse(BaseModel):
    """빌링키 응답"""
    id: int
    card_name: Optional[str] = None
    card_number_masked: Optional[str] = None
    is_active: bool
    registered_at: datetime


class RecurringBillResponse(BaseModel):
    """정기 청구 응답"""
    id: int
    member_id: str
    member_name: Optional[str] = None
    bill_type: RecurringBillType
    amount: int
    billing_day: int
    auto_pay: bool
    has_billing_key: bool = False
    is_active: bool
    next_bill_date: Optional[date] = None
    last_billed_at: Optional[datetime] = None


class FeeTemplateResponse(BaseModel):
    """비용 템플릿 응답"""
    id: int
    name: str
    fee_type: InvoiceType
    default_amount: int
    description: Optional[str] = None
    is_active: bool


class SubscriptionResponse(BaseModel):
    """구독 정보 응답"""
    tier: SubscriptionTier
    alimtalk_limit: int
    alimtalk_used: int
    alimtalk_remaining: int
    fcm_enabled: bool = True  # 항상 true
    alimtalk_enabled: bool
    is_active: bool


class OutstandingMemberResponse(BaseModel):
    """미납 회원"""
    member_id: str
    member_name: str
    total_outstanding: int
    invoice_count: int
    oldest_due_date: Optional[date] = None


# Forward references
CompetitionSplitCreate.model_rebuild()
InvoiceDetailResponse.model_rebuild()
