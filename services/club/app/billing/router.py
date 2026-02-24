"""
Billing Router - 청구/결제/수납 API

코치용: 청구서 생성, 수납 확인, 정기 청구, 대회비용 분할
학부모용: 내 청구 조회, 카드 결제, 빌링키 관리
"""

from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from ..club.dependencies import (
    ClubMemberContext,
    get_current_club_member,
    require_coach,
    require_staff,
)
from .models import (
    InvoiceCreate,
    InvoiceUpdate,
    InvoiceResponse,
    InvoiceDetailResponse,
    InvoiceMemberResponse,
    InvoiceStatus,
    InvoiceMemberStatus,
    PaymentCreate,
    PaymentResponse,
    PaymentSummaryResponse,
    BillingKeyRegister,
    BillingKeyResponse,
    RecurringBillCreate,
    RecurringBillUpdate,
    RecurringBillResponse,
    FeeTemplateCreate,
    FeeTemplateUpdate,
    FeeTemplateResponse,
    CompetitionSplitCreate,
    OutstandingMemberResponse,
    SplitType,
    PortOnePaymentVerify,
    BillingKeyIssue,
)
from .portone import PortOneError
from .service import billing_service

router = APIRouter(prefix="/billing", tags=["Billing & Payments"])


# =============================================
# 청구서 관리 (코치용)
# =============================================

@router.post("/invoices", response_model=InvoiceResponse)
async def create_invoice(
    data: InvoiceCreate,
    member: ClubMemberContext = Depends(require_coach),
):
    """청구서 생성 (코치 이상)"""
    custom_amounts = None
    if data.split_type == SplitType.custom:
        if not data.amounts or len(data.amounts) != len(data.member_ids):
            raise HTTPException(400, "custom split 시 amounts 필수 (member_ids와 같은 수)")
        custom_amounts = data.amounts

    invoice = billing_service.create_invoice(
        org_id=member.organization_id,
        created_by=member.member_id,
        title=data.title,
        invoice_type=data.invoice_type.value,
        total_amount=data.total_amount,
        member_ids=data.member_ids,
        split_type=data.split_type.value,
        description=data.description,
        due_date=data.due_date,
        custom_amounts=custom_amounts,
    )

    return _to_invoice_response(invoice, member_count=len(data.member_ids))


@router.get("/invoices")
async def list_invoices(
    status: Optional[str] = Query(None),
    invoice_type: Optional[str] = Query(None),
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    member: ClubMemberContext = Depends(require_staff),
):
    """청구서 목록 (스태프 이상)"""
    invoices, total = billing_service.list_invoices(
        org_id=member.organization_id,
        status=status,
        invoice_type=invoice_type,
        limit=limit,
        offset=offset,
    )

    return {
        "total": total,
        "invoices": [_to_invoice_response(inv) for inv in invoices],
    }


@router.get("/invoices/{invoice_id}", response_model=InvoiceDetailResponse)
async def get_invoice_detail(
    invoice_id: int,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """청구서 상세 조회"""
    invoice = billing_service.get_invoice(invoice_id, member.organization_id)
    if not invoice:
        raise HTTPException(404, "청구서를 찾을 수 없습니다")

    # 학부모/학생은 본인 관련 청구만 확인
    if not member.is_staff():
        my_invoices = [
            m for m in invoice.get("invoice_members", [])
            if m["member_id"] == member.member_id
        ]
        if not my_invoices:
            raise HTTPException(403, "권한이 없습니다")

    return _to_invoice_detail_response(invoice)


@router.post("/invoices/{invoice_id}/send")
async def send_invoice(
    invoice_id: int,
    member: ClubMemberContext = Depends(require_coach),
):
    """청구서 발송 (알림 발송 + status→sent)"""
    result = billing_service.send_invoice(invoice_id, member.organization_id)
    if not result:
        raise HTTPException(400, "발송할 수 없는 상태입니다 (draft만 발송 가능)")

    return {"success": True, "message": "청구서가 발송되었습니다"}


@router.post("/invoices/{invoice_id}/remind")
async def remind_invoice(
    invoice_id: int,
    member: ClubMemberContext = Depends(require_coach),
):
    """미납자 재알림"""
    invoice = billing_service.get_invoice(invoice_id, member.organization_id)
    if not invoice:
        raise HTTPException(404, "청구서를 찾을 수 없습니다")

    unpaid = [
        m for m in invoice.get("invoice_members", [])
        if m["status"] in ("pending", "overdue")
    ]

    if not unpaid:
        return {"success": True, "message": "미납자가 없습니다", "reminded": 0}

    # 알림 발송은 notification service에서 처리
    # 여기서는 reminder_count만 증가
    from ..database import get_supabase_client
    supabase = get_supabase_client()
    for m in unpaid:
        from datetime import datetime
        supabase.table("app_invoice_members").update({
            "reminder_count": (m.get("reminder_count") or 0) + 1,
            "notified_at": datetime.now().isoformat(),
        }).eq("id", m["id"]).execute()

    return {
        "success": True,
        "message": f"{len(unpaid)}명에게 재알림을 발송했습니다",
        "reminded": len(unpaid),
    }


@router.delete("/invoices/{invoice_id}")
async def cancel_invoice(
    invoice_id: int,
    member: ClubMemberContext = Depends(require_coach),
):
    """청구서 취소"""
    success = billing_service.cancel_invoice(invoice_id, member.organization_id)
    if not success:
        raise HTTPException(400, "취소할 수 없습니다")
    return {"success": True, "message": "청구서가 취소되었습니다"}


# =============================================
# 대회 비용 분할 청구
# =============================================

@router.post("/invoices/competition-split")
async def create_competition_split(
    data: CompetitionSplitCreate,
    member: ClubMemberContext = Depends(require_coach),
):
    """대회 비용 자동 분할 청구"""
    created = []
    for item in data.items:
        invoice = billing_service.create_invoice(
            org_id=member.organization_id,
            created_by=member.member_id,
            title=item.title,
            invoice_type=item.invoice_type.value,
            total_amount=item.total,
            member_ids=data.member_ids,
            split_type=data.split_type.value,
            due_date=data.due_date,
            competition_id=data.competition_id,
        )
        created.append(_to_invoice_response(invoice, member_count=len(data.member_ids)))

    total_amount = sum(item.total for item in data.items)
    per_member = total_amount // len(data.member_ids) if data.split_type == SplitType.equal else total_amount

    return {
        "success": True,
        "invoices_created": len(created),
        "total_amount": total_amount,
        "per_member_amount": per_member,
        "member_count": len(data.member_ids),
        "invoices": created,
    }


# =============================================
# 수납 관리 (코치용)
# =============================================

@router.post("/payments", response_model=PaymentResponse)
async def record_payment(
    data: PaymentCreate,
    member: ClubMemberContext = Depends(require_coach),
):
    """수납 등록 (현금/이체 확인)"""
    try:
        payment = billing_service.record_payment(
            invoice_member_id=data.invoice_member_id,
            org_id=member.organization_id,
            amount=data.amount,
            payment_method=data.payment_method.value,
            confirmed_by=member.member_id,
            memo=data.memo,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    return PaymentResponse(
        id=payment["id"],
        invoice_member_id=payment["invoice_member_id"],
        amount=payment["amount"],
        payment_method=data.payment_method,
        payment_status=payment["payment_status"],
        memo=payment.get("memo"),
        paid_at=payment["paid_at"],
        created_at=payment["created_at"],
    )


@router.get("/payments/summary", response_model=PaymentSummaryResponse)
async def get_payment_summary(
    member: ClubMemberContext = Depends(require_staff),
):
    """수납 현황 요약"""
    summary = billing_service.get_payment_summary(member.organization_id)
    return PaymentSummaryResponse(**summary)


@router.get("/payments/outstanding")
async def get_outstanding_members(
    member: ClubMemberContext = Depends(require_staff),
):
    """미납 회원 목록"""
    members = billing_service.get_outstanding_members(member.organization_id)
    return {"total": len(members), "members": members}


# =============================================
# 비용 템플릿
# =============================================

@router.get("/fee-templates")
async def list_fee_templates(
    member: ClubMemberContext = Depends(require_staff),
):
    """비용 템플릿 목록"""
    templates = billing_service.list_fee_templates(member.organization_id)
    return {"templates": templates}


@router.post("/fee-templates", response_model=FeeTemplateResponse)
async def create_fee_template(
    data: FeeTemplateCreate,
    member: ClubMemberContext = Depends(require_coach),
):
    """비용 템플릿 생성"""
    template = billing_service.create_fee_template(
        org_id=member.organization_id,
        name=data.name,
        fee_type=data.fee_type.value,
        default_amount=data.default_amount,
        description=data.description,
    )
    return FeeTemplateResponse(**template)


@router.put("/fee-templates/{template_id}", response_model=FeeTemplateResponse)
async def update_fee_template(
    template_id: int,
    data: FeeTemplateUpdate,
    member: ClubMemberContext = Depends(require_coach),
):
    """비용 템플릿 수정"""
    update_data = data.model_dump(exclude_none=True)
    if "fee_type" in update_data:
        update_data["fee_type"] = update_data["fee_type"].value

    result = billing_service.update_fee_template(
        template_id, member.organization_id, **update_data
    )
    if not result:
        raise HTTPException(404, "템플릿을 찾을 수 없습니다")
    return FeeTemplateResponse(**result)


# =============================================
# 정기 청구
# =============================================

@router.get("/recurring")
async def list_recurring_bills(
    member: ClubMemberContext = Depends(require_staff),
):
    """정기 청구 목록"""
    bills = billing_service.list_recurring_bills(member.organization_id)
    return {"recurring_bills": bills}


@router.post("/recurring", response_model=RecurringBillResponse)
async def create_recurring_bill(
    data: RecurringBillCreate,
    member: ClubMemberContext = Depends(require_coach),
):
    """정기 청구 설정"""
    bill = billing_service.create_recurring_bill(
        org_id=member.organization_id,
        member_id=data.member_id,
        bill_type=data.bill_type.value,
        amount=data.amount,
        billing_day=data.billing_day,
        auto_pay=data.auto_pay,
    )
    return RecurringBillResponse(
        **bill, member_name=None, has_billing_key=False,
    )


@router.post("/recurring/generate")
async def generate_monthly_invoices(
    member: ClubMemberContext = Depends(require_coach),
):
    """이번 달 정기 청구서 일괄 생성"""
    invoices = billing_service.generate_monthly_invoices(
        org_id=member.organization_id,
        created_by=member.member_id,
    )
    return {
        "success": True,
        "invoices_created": len(invoices),
        "message": f"{len(invoices)}건의 정기 청구서가 생성되었습니다",
    }


# =============================================
# 학부모용 API
# =============================================

@router.get("/my/invoices")
async def get_my_invoices(
    status: Optional[str] = Query(None),
    limit: int = Query(20, le=50),
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """내 청구 내역"""
    from ..database import get_supabase_client
    supabase = get_supabase_client()

    query = supabase.table("app_invoice_members").select(
        "*, app_invoices!inner(title, invoice_type, due_date, status, created_at)"
    ).eq("member_id", member.member_id)

    if status:
        query = query.eq("status", status)

    result = query.order("created_at", desc=True).limit(limit).execute()

    invoices = []
    for im in (result.data or []):
        inv = im.get("app_invoices", {}) or {}
        invoices.append({
            "id": im["id"],
            "invoice_title": inv.get("title"),
            "invoice_type": inv.get("invoice_type"),
            "amount": im["amount"],
            "paid_amount": im.get("paid_amount", 0),
            "status": im["status"],
            "due_date": inv.get("due_date"),
            "created_at": im["created_at"],
        })

    return {"total": len(invoices), "invoices": invoices}


@router.get("/my/outstanding")
async def get_my_outstanding(
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """내 미납 내역"""
    from ..database import get_supabase_client
    supabase = get_supabase_client()

    result = supabase.table("app_invoice_members").select(
        "*, app_invoices!inner(title, invoice_type, due_date)"
    ).eq("member_id", member.member_id).in_(
        "status", ["pending", "overdue"]
    ).execute()

    total_outstanding = 0
    items = []
    for im in (result.data or []):
        inv = im.get("app_invoices", {}) or {}
        outstanding = im["amount"] - (im.get("paid_amount") or 0)
        total_outstanding += outstanding
        items.append({
            "invoice_member_id": im["id"],
            "title": inv.get("title"),
            "type": inv.get("invoice_type"),
            "amount": im["amount"],
            "paid": im.get("paid_amount", 0),
            "outstanding": outstanding,
            "due_date": inv.get("due_date"),
            "status": im["status"],
        })

    return {
        "total_outstanding": total_outstanding,
        "items": items,
    }


# =============================================
# PortOne 결제 연동
# =============================================

@router.post("/payments/verify-portone")
async def verify_portone_payment(
    data: PortOnePaymentVerify,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """PortOne 결제 검증 (프론트에서 결제 완료 후 호출)"""
    try:
        payment = await billing_service.verify_portone_payment(
            payment_id=data.payment_id,
            invoice_member_id=data.invoice_member_id,
            org_id=member.organization_id,
        )
    except PortOneError as e:
        raise HTTPException(502, f"결제 검증 실패: {e.message}")
    except ValueError as e:
        raise HTTPException(400, str(e))

    return {
        "success": True,
        "payment_id": payment["id"],
        "amount": payment["amount"],
        "message": "결제가 확인되었습니다",
    }


@router.post("/my/billing-key/issue", response_model=BillingKeyResponse)
async def issue_billing_key_portone(
    data: BillingKeyIssue,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """PortOne 빌링키 발급 (카드 등록)"""
    try:
        key = await billing_service.issue_billing_key_portone(
            member_id=member.member_id,
            org_id=member.organization_id,
            customer_id=data.customer_id,
            card_number=data.card_number,
            expiry=data.expiry,
            birth_or_business=data.birth_or_business,
            password_two_digits=data.password_two_digits,
        )
    except PortOneError as e:
        raise HTTPException(502, f"빌링키 발급 실패: {e.message}")
    except ValueError as e:
        raise HTTPException(400, str(e))

    return BillingKeyResponse(
        id=key["id"],
        card_name=key.get("card_name"),
        card_number_masked=key.get("card_number_masked"),
        is_active=key["is_active"],
        registered_at=key["registered_at"],
    )


# =============================================
# 빌링키 (학부모용)
# =============================================

@router.post("/my/billing-key", response_model=BillingKeyResponse)
async def register_billing_key(
    data: BillingKeyRegister,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """카드 등록 (빌링키 발급)"""
    key = billing_service.register_billing_key(
        member_id=member.member_id,
        org_id=member.organization_id,
        billing_key=data.billing_key,
        card_name=data.card_name,
        card_number_masked=data.card_number_masked,
    )
    return BillingKeyResponse(
        id=key["id"],
        card_name=key.get("card_name"),
        card_number_masked=key.get("card_number_masked"),
        is_active=key["is_active"],
        registered_at=key["registered_at"],
    )


@router.get("/my/billing-key")
async def get_my_billing_key(
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """내 등록 카드 조회"""
    key = billing_service.get_billing_key(member.member_id, member.organization_id)
    if not key:
        return {"billing_key": None}
    return {
        "billing_key": BillingKeyResponse(
            id=key["id"],
            card_name=key.get("card_name"),
            card_number_masked=key.get("card_number_masked"),
            is_active=key["is_active"],
            registered_at=key["registered_at"],
        )
    }


@router.delete("/my/billing-key")
async def deactivate_billing_key(
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """카드 해지"""
    success = billing_service.deactivate_billing_key(
        member.member_id, member.organization_id
    )
    if not success:
        raise HTTPException(404, "등록된 카드가 없습니다")
    return {"success": True, "message": "카드가 해지되었습니다"}


# =============================================
# Helper functions
# =============================================

def _to_invoice_response(inv: dict, member_count: int = 0) -> InvoiceResponse:
    return InvoiceResponse(
        id=inv["id"],
        org_id=inv["org_id"],
        created_by=inv["created_by"],
        creator_name=inv.get("creator_name"),
        title=inv["title"],
        description=inv.get("description"),
        invoice_type=inv["invoice_type"],
        total_amount=inv["total_amount"],
        due_date=inv.get("due_date"),
        status=inv.get("status", "draft"),
        split_type=inv.get("split_type", "none"),
        target_count=inv.get("target_count"),
        competition_id=inv.get("competition_id"),
        member_count=inv.get("member_count", member_count),
        paid_count=inv.get("paid_count", 0),
        created_at=inv["created_at"],
        updated_at=inv["updated_at"],
    )


def _to_invoice_detail_response(inv: dict) -> InvoiceDetailResponse:
    members = []
    for m in inv.get("invoice_members", []):
        members.append(InvoiceMemberResponse(
            id=m["id"],
            member_id=m["member_id"],
            member_name=m.get("member_name"),
            amount=m["amount"],
            status=m.get("status", "pending"),
            paid_amount=m.get("paid_amount", 0),
            notified_at=m.get("notified_at"),
            reminder_count=m.get("reminder_count", 0),
            paid_at=m.get("paid_at"),
            memo=m.get("memo"),
        ))

    resp = _to_invoice_response(inv, member_count=len(members))
    return InvoiceDetailResponse(
        **resp.model_dump(),
        members=members,
    )
