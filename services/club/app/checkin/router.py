"""
Checkin Router

멀티 체크인/체크아웃 API 엔드포인트
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Query

from ..club.dependencies import (
    ClubMemberContext,
    ClubRole,
    get_current_club_member,
    require_coach,
    require_admin,
    get_client_ip,
)
from ..database import get_supabase_client
from .models import (
    CheckinRequest,
    CheckinResponse,
    CheckoutRequest,
    CheckoutResponse,
    QRSessionResponse,
    AttendanceRecord,
    AttendanceStats,
    WiFiCheckinConfig,
    WiFiConfigUpdate,
    CheckinMethod,
)
from .service import checkin_service

router = APIRouter(prefix="/club/checkin", tags=["Check-in"])


# =============================================
# Check-in / Check-out
# =============================================

@router.post("/", response_model=CheckinResponse)
async def unified_checkin(
    request: Request,
    body: CheckinRequest,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """
    통합 체크인

    지원 방식: auto_ip, wifi, qr, gps, manual, coach_proxy
    """
    # manual은 코치+ 전용
    if body.method == CheckinMethod.manual:
        coach_roles = {ClubRole.owner, ClubRole.head_coach, ClubRole.coach, ClubRole.assistant, ClubRole.staff}
        if member.club_role not in coach_roles:
            raise HTTPException(status_code=403, detail="수동 체크인은 코치만 가능합니다.")

    client_ip = await get_client_ip(request)

    result = await checkin_service.check_in(
        org_id=member.organization_id,
        member_id=member.member_id,
        member_name=member.full_name,
        request=body,
        client_ip=client_ip,
    )

    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)

    return result


@router.post("/checkout", response_model=CheckoutResponse)
async def checkout(
    body: CheckoutRequest,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """체크아웃"""
    result = await checkin_service.check_out(
        org_id=member.organization_id,
        member_id=member.member_id,
        member_name=member.full_name,
        method=body.method,
    )

    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)

    return result


# =============================================
# Status & History
# =============================================

@router.get("/status")
async def get_checkin_status(
    request: Request,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """오늘 체크인 상태"""
    client_ip = await get_client_ip(request)
    return await checkin_service.get_checkin_status(
        org_id=member.organization_id,
        member_id=member.member_id,
        client_ip=client_ip,
    )


@router.get("/today", response_model=List[AttendanceRecord])
async def get_today_attendance(
    member: ClubMemberContext = Depends(require_coach),
):
    """오늘 전체 출석 현황 (코치+)"""
    return await checkin_service.get_today_attendance(
        org_id=member.organization_id,
    )


@router.get("/history", response_model=List[AttendanceRecord])
async def get_attendance_history(
    member_id: Optional[str] = Query(None, description="특정 회원 필터"),
    date_from: Optional[str] = Query(None, description="시작일 (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="종료일 (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=200),
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """출석 히스토리"""
    # 학생은 자기 기록만
    query_member_id = member_id
    coach_roles = {ClubRole.owner, ClubRole.head_coach, ClubRole.coach, ClubRole.assistant, ClubRole.staff}
    if member.club_role not in coach_roles:
        query_member_id = member.member_id

    return await checkin_service.get_attendance_history(
        org_id=member.organization_id,
        member_id=query_member_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )


@router.get("/stats", response_model=AttendanceStats)
async def get_attendance_stats(
    target_member_id: Optional[str] = Query(None, description="조회 대상 회원 ID"),
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """출석 통계"""
    query_member_id = target_member_id or member.member_id
    # 학생은 자기 통계만
    coach_roles = {ClubRole.owner, ClubRole.head_coach, ClubRole.coach, ClubRole.assistant, ClubRole.staff}
    if member.club_role not in coach_roles:
        query_member_id = member.member_id

    return await checkin_service.get_attendance_stats(
        org_id=member.organization_id,
        member_id=query_member_id,
    )


# =============================================
# QR Code
# =============================================

@router.post("/qr/generate", response_model=QRSessionResponse)
async def generate_qr(
    member: ClubMemberContext = Depends(require_coach),
):
    """QR 세션 생성 (코치+)"""
    return await checkin_service.generate_qr_session(
        org_id=member.organization_id,
    )


@router.get("/qr/current")
async def get_current_qr(
    member: ClubMemberContext = Depends(require_coach),
):
    """현재 유효한 QR 세션 (코치+)"""
    qr = await checkin_service.get_active_qr(org_id=member.organization_id)
    if not qr:
        return {"active": False, "message": "활성 QR 세션이 없습니다."}
    return {"active": True, "qr_code": qr.qr_code, "valid_until": qr.valid_until.isoformat(), "qr_image_data_url": qr.qr_image_data_url}


# =============================================
# Coach Proxy Check-in
# =============================================

@router.post("/proxy/{student_member_id}", response_model=CheckinResponse)
async def coach_proxy_checkin(
    student_member_id: str,
    member: ClubMemberContext = Depends(require_coach),
):
    """코치 대리 체크인 (코치+)"""
    # 학생 정보 조회
    supabase = get_supabase_client()
    student = (
        supabase.table("members")
        .select("id, full_name")
        .eq("id", student_member_id)
        .eq("organization_id", member.organization_id)
        .single()
        .execute()
    )

    if not student.data:
        raise HTTPException(status_code=404, detail="해당 회원을 찾을 수 없습니다.")

    result = await checkin_service.coach_proxy_checkin(
        org_id=member.organization_id,
        coach_id=member.member_id,
        student_member_id=student_member_id,
        student_name=student.data["full_name"],
    )

    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)

    return result


# =============================================
# Auto Checkout
# =============================================

@router.post("/auto-checkout")
async def trigger_auto_checkout(
    timeout_hours: int = Query(4, ge=1, le=12),
    member: ClubMemberContext = Depends(require_coach),
):
    """자동 체크아웃 배치 실행 (코치+)"""
    count = await checkin_service.auto_checkout(
        org_id=member.organization_id,
        timeout_hours=timeout_hours,
    )
    return {
        "success": True,
        "auto_checked_out": count,
        "message": f"{count}명 자동 체크아웃 완료",
    }


# =============================================
# WiFi Config
# =============================================

@router.get("/wifi-config", response_model=WiFiCheckinConfig)
async def get_wifi_config(
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """WiFi 설정 조회 (체크인 화면용)"""
    return await checkin_service.get_wifi_config(org_id=member.organization_id)


@router.put("/wifi-config", response_model=WiFiCheckinConfig)
async def update_wifi_config(
    body: WiFiConfigUpdate,
    member: ClubMemberContext = Depends(require_admin),
):
    """WiFi 설정 업데이트 (관리자 전용)"""
    return await checkin_service.configure_wifi(
        org_id=member.organization_id,
        ssid=body.ssid,
        bssid=body.bssid,
    )
