"""
Attendance Router

출석 체크인/체크아웃 API
- 수동/자동 체크인
- 체크인 상태 확인
- IP 기반 자동 체크인 검증
"""

from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException, Request

from ..dependencies import (
    ClubMemberContext,
    get_current_club_member,
    get_client_ip,
)
from ..models import (
    CheckInRequest,
    CheckInResponse,
    AttendanceType,
    CheckinMethod,
)
from ...database import get_supabase_client

router = APIRouter(tags=["Attendance"])


# =============================================
# 출석 체크인
# =============================================

@router.post("/check-in", response_model=CheckInResponse)
async def check_in(
    request: Request,
    check_in_data: CheckInRequest,
    member: ClubMemberContext = Depends(get_current_club_member)
):
    """
    출석 체크인 (수동)

    학생이 직접 버튼을 눌러 체크인합니다.
    클럽 IP 범위 내에서만 체크인 가능 (설정된 경우).
    """
    supabase = get_supabase_client()
    client_ip = await get_client_ip(request)

    # 자동 체크인 가능 여부 확인
    auto_checkin = await _check_auto_checkin_eligibility(
        member.organization_id, client_ip
    )

    # 오늘 이미 체크인했는지 확인
    today = date.today().isoformat()
    existing = supabase.table("attendance").select("id").eq(
        "member_id", member.member_id
    ).gte(
        "check_in_at", f"{today}T00:00:00"
    ).execute()

    if existing.data:
        raise HTTPException(
            status_code=400,
            detail="오늘 이미 체크인했습니다"
        )

    # 체크인 기록 생성
    checkin_method = CheckinMethod.auto_ip if auto_checkin else CheckinMethod.manual

    attendance_data = {
        "member_id": member.member_id,
        "organization_id": member.organization_id,
        "check_in_at": datetime.now().isoformat(),
        "attendance_type": check_in_data.attendance_type.value,
        "checkin_method": checkin_method.value,
        "client_ip": client_ip,
        "notes": check_in_data.notes
    }

    response = supabase.table("attendance").insert(attendance_data).execute()

    if not response.data:
        raise HTTPException(status_code=500, detail="체크인 실패")

    record = response.data[0]

    return CheckInResponse(
        id=record["id"],
        member_id=member.member_id,
        member_name=member.full_name,
        check_in_at=datetime.fromisoformat(record["check_in_at"]),
        attendance_type=check_in_data.attendance_type,
        checkin_method=checkin_method,
        auto_checkin_available=auto_checkin
    )


@router.get("/check-in/status")
async def get_checkin_status(
    request: Request,
    member: ClubMemberContext = Depends(get_current_club_member)
):
    """
    체크인 상태 확인

    오늘 체크인 여부와 자동 체크인 가능 여부를 반환합니다.
    """
    supabase = get_supabase_client()
    client_ip = await get_client_ip(request)

    # 오늘 체크인 여부
    today = date.today().isoformat()
    existing = supabase.table("attendance").select(
        "id, check_in_at, attendance_type"
    ).eq(
        "member_id", member.member_id
    ).gte(
        "check_in_at", f"{today}T00:00:00"
    ).execute()

    already_checked_in = len(existing.data or []) > 0
    checkin_record = existing.data[0] if already_checked_in else None

    # 자동 체크인 가능 여부
    auto_checkin = await _check_auto_checkin_eligibility(
        member.organization_id, client_ip
    )

    return {
        "already_checked_in": already_checked_in,
        "checkin_record": checkin_record,
        "auto_checkin_available": auto_checkin,
        "client_ip": client_ip,
        "current_time": datetime.now().isoformat()
    }


# =============================================
# Helper Functions
# =============================================

async def _check_auto_checkin_eligibility(
    organization_id: int,
    client_ip: str
) -> bool:
    """자동 체크인 가능 여부 확인 (IP 기반)"""
    supabase = get_supabase_client()

    try:
        settings_response = supabase.table("club_settings").select(
            "auto_checkin_enabled, allowed_ips"
        ).eq("organization_id", organization_id).single().execute()

        if not settings_response.data:
            return False

        settings = settings_response.data

        if not settings.get("auto_checkin_enabled"):
            return False

        allowed_ips = settings.get("allowed_ips", []) or []

        # IP 매칭 (정확 매칭 또는 서브넷)
        for allowed_ip in allowed_ips:
            if client_ip == allowed_ip:
                return True
            # 간단한 서브넷 체크 (예: 192.168.0.*)
            if allowed_ip.endswith(".*"):
                prefix = allowed_ip[:-1]
                if client_ip.startswith(prefix):
                    return True

        return False

    except Exception:
        return False
