"""
Accounting Router

회계관리 API (Owner/사장 전용)
- 회계 요약 (미납, 연체, 수금)
- 미납/연체 비용 목록
- 납부 확인 처리
"""

from datetime import date, datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from ..dependencies import (
    ClubMemberContext,
    get_current_club_member,
)
from ...database import get_supabase_client

router = APIRouter(tags=["Accounting"])


# =============================================
# 회계관리 (Owner/사장 전용)
# =============================================

@router.get("/accounting/summary")
async def get_accounting_summary(
    member: ClubMemberContext = Depends(get_current_club_member)
):
    """
    회계 요약 조회 (owner 전용)

    미납 총액, 연체 총액, 이번 달 수금 등 요약 정보를 반환합니다.
    """
    # owner만 접근 가능
    if member.club_role.value != "owner":
        raise HTTPException(
            status_code=403,
            detail="회계 정보는 클럽 대표만 조회할 수 있습니다"
        )

    supabase = get_supabase_client()
    org_id = member.organization_id
    today = date.today()

    # 비용 데이터 조회
    fees_response = supabase.table("fees").select(
        "id, amount, status, fee_type, paid_at"
    ).eq("organization_id", org_id).execute()

    pending_total = 0
    overdue_total = 0
    this_month_total = 0

    for fee in (fees_response.data or []):
        if fee.get("status") == "pending":
            pending_total += fee.get("amount", 0)
        elif fee.get("status") == "overdue":
            overdue_total += fee.get("amount", 0)
        elif fee.get("status") == "paid":
            paid_at = fee.get("paid_at", "")
            if paid_at and paid_at.startswith(today.strftime("%Y-%m")):
                this_month_total += fee.get("amount", 0)

    return {
        "pending_total": pending_total,
        "overdue_total": overdue_total,
        "this_month_collection": this_month_total,
        "total_outstanding": pending_total + overdue_total
    }


@router.get("/accounting/fees")
async def get_pending_fees(
    status: Optional[str] = Query(None, description="상태 필터 (pending/overdue)"),
    member: ClubMemberContext = Depends(get_current_club_member)
):
    """
    미납/연체 비용 목록 조회 (owner 전용)
    """
    if member.club_role.value != "owner":
        raise HTTPException(
            status_code=403,
            detail="회계 정보는 클럽 대표만 조회할 수 있습니다"
        )

    supabase = get_supabase_client()
    org_id = member.organization_id

    query = supabase.table("fees").select(
        "id, member_id, fee_type, amount, description, status, due_date, "
        "members!fees_member_id_fkey(full_name)"
    ).eq("organization_id", org_id)

    if status:
        query = query.eq("status", status)
    else:
        # 기본: 미납 + 연체만
        query = query.in_("status", ["pending", "overdue"])

    response = query.order("due_date", desc=False).execute()

    fees = []
    for fee in (response.data or []):
        member_info = fee.get("members", {}) or {}
        fees.append({
            "id": fee["id"],
            "member_id": fee["member_id"],
            "member_name": member_info.get("full_name", "Unknown"),
            "fee_type": fee["fee_type"],
            "amount": fee["amount"],
            "description": fee.get("description"),
            "status": fee["status"],
            "due_date": fee.get("due_date")
        })

    return {"total": len(fees), "fees": fees}


@router.post("/accounting/fees/{fee_id}/paid")
async def mark_fee_as_paid(
    fee_id: str,
    member: ClubMemberContext = Depends(get_current_club_member)
):
    """
    비용 납부 확인 (owner 전용)
    """
    if member.club_role.value != "owner":
        raise HTTPException(
            status_code=403,
            detail="회계 정보는 클럽 대표만 수정할 수 있습니다"
        )

    supabase = get_supabase_client()

    # 비용이 해당 조직 소속인지 확인
    check_response = supabase.table("fees").select("id").eq(
        "id", fee_id
    ).eq("organization_id", member.organization_id).single().execute()

    if not check_response.data:
        raise HTTPException(status_code=404, detail="비용 정보를 찾을 수 없습니다")

    # 납부 완료로 업데이트
    update_response = supabase.table("fees").update({
        "status": "paid",
        "paid_at": datetime.now().isoformat(),
        "confirmed_by": member.member_id
    }).eq("id", fee_id).execute()

    if not update_response.data:
        raise HTTPException(status_code=500, detail="업데이트 실패")

    return {"success": True, "message": "납부 확인되었습니다"}
