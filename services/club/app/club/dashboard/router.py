"""
Dashboard Router

클럽 대시보드 API 및 HTML 페이지 라우팅
- 대시보드 API (오늘 출석, 회원 현황, 비용 현황)
- 역할별 HTML 페이지 라우팅
- 체크인/레슨 페이지
"""

from datetime import date, datetime
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..dependencies import (
    ClubMemberContext,
    ClubRole,
    get_current_club_member,
    try_get_current_club_member,
)
from ..models import (
    ClubDashboard,
    TodayCheckin,
    DashboardAlert,
    AttendanceType,
)
from ...database import get_supabase_client
from ... import config

router = APIRouter(tags=["Dashboard"])

templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))

ROLE_TEMPLATE_MAP = {
    ClubRole.owner: "club/dashboard.html",
    ClubRole.head_coach: "club/dashboard.html",
    ClubRole.coach: "club/dashboard_coach.html",
    ClubRole.assistant: "club/dashboard_coach.html",
    ClubRole.student: "club/dashboard_student.html",
    ClubRole.parent: "club/dashboard_parent.html",
    ClubRole.staff: "club/dashboard_coach.html",
}


# =============================================
# Dashboard API
# =============================================

@router.get("/dashboard", response_model=ClubDashboard)
async def get_dashboard(
    member: ClubMemberContext = Depends(get_current_club_member)
):
    """
    클럽 대시보드

    오늘 출석 현황, 회원 현황, 비용 현황, 예정 대회, 알림을 조회합니다.
    """
    supabase = get_supabase_client()
    org_id = member.organization_id

    # 조직 정보
    org_response = supabase.table("organizations").select(
        "id, name"
    ).eq("id", org_id).single().execute()

    org = org_response.data or {}

    # 오늘 출석 현황
    today = date.today().isoformat()
    attendance_response = supabase.table("attendance").select(
        "id, member_id, check_in_at, attendance_type, members!attendance_member_id_fkey(full_name)"
    ).eq("organization_id", org_id).gte(
        "check_in_at", f"{today}T00:00:00"
    ).lte(
        "check_in_at", f"{today}T23:59:59"
    ).execute()

    today_checkins = []
    for record in (attendance_response.data or []):
        member_info = record.get("members", {}) or {}
        today_checkins.append(TodayCheckin(
            member_id=record["member_id"],
            member_name=member_info.get("full_name", "Unknown"),
            check_in_at=datetime.fromisoformat(record["check_in_at"]),
            attendance_type=AttendanceType(record.get("attendance_type", "regular"))
        ))

    # 회원 현황
    members_response = supabase.table("members").select(
        "id, club_role, member_status"
    ).eq("organization_id", org_id).execute()

    members = members_response.data or []
    active_members = [m for m in members if m.get("member_status") in ["active", None]]
    # 학생만 카운트 (student만, assistant는 보조 코치이므로 코치 그룹)
    students = [m for m in active_members if m.get("club_role") == "student"]
    # 코치 그룹: owner, head_coach, coach, assistant (보조 코치)
    coaches = [m for m in active_members if m.get("club_role") in ["coach", "head_coach", "owner", "assistant"]]

    # 비용 현황
    pending_fees = 0
    overdue_fees = 0
    this_month_collection = 0

    try:
        fees_response = supabase.table("fees").select(
            "amount, status, paid_at"
        ).eq("organization_id", org_id).execute()

        for fee in (fees_response.data or []):
            if fee.get("status") == "pending":
                pending_fees += fee.get("amount", 0)
            elif fee.get("status") == "overdue":
                overdue_fees += fee.get("amount", 0)
            elif fee.get("status") == "paid":
                paid_at = fee.get("paid_at", "")
                if paid_at and paid_at.startswith(today[:7]):  # 이번 달
                    this_month_collection += fee.get("amount", 0)
    except Exception:
        pass  # fees 테이블이 없을 수 있음

    # 알림 생성
    alerts = []

    if overdue_fees > 0:
        alerts.append(DashboardAlert(
            alert_type="overdue_fee",
            message=f"연체된 비용이 {overdue_fees:,}원 있습니다",
            severity="warning"
        ))

    if len(today_checkins) == 0:
        alerts.append(DashboardAlert(
            alert_type="no_attendance",
            message="오늘 아직 출석한 회원이 없습니다",
            severity="info"
        ))

    return ClubDashboard(
        organization_id=org_id,
        organization_name=org.get("name", ""),
        today_attendance=len(today_checkins),
        today_checkins=today_checkins,
        total_members=len(active_members),
        active_students=len(students),
        active_coaches=len(coaches),
        pending_fees=pending_fees,
        overdue_fees=overdue_fees,
        this_month_collection=this_month_collection,
        upcoming_competitions=[],  # TODO: 대회 일정 연동
        alerts=alerts
    )


# =============================================
# HTML Pages
# =============================================

@router.get("/", response_class=HTMLResponse)
async def club_dashboard_page(request: Request):
    """
    클럽 대시보드 페이지 (역할별 라우팅)

    인증된 사용자 → 역할에 맞는 대시보드
    미인증 → 랜딩 페이지로 리다이렉트
    """
    member = await try_get_current_club_member(request)

    if not member:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/", status_code=302)

    template_name = ROLE_TEMPLATE_MAP.get(
        member.club_role, "club/dashboard_student.html"
    )
    return templates.TemplateResponse(
        template_name,
        {
            "request": request,
            "title": "클럽 대시보드",
            "user_role": member.club_role.value if member.club_role else "student",
            "user_name": member.full_name,
            "member_id": member.member_id,
        }
    )


@router.get("/checkin", response_class=HTMLResponse)
async def checkin_page(request: Request):
    """
    체크인 페이지 (학생용 모바일 최적화)
    """
    return templates.TemplateResponse(
        "club/checkin.html",
        {"request": request, "title": "출석 체크인"}
    )


@router.get("/lessons-page", response_class=HTMLResponse)
async def lessons_page(request: Request):
    """
    레슨 관리 페이지 (코치용)
    """
    return templates.TemplateResponse(
        "club/lessons.html",
        {"request": request, "title": "레슨 관리"}
    )


@router.get("/billing", response_class=HTMLResponse)
async def billing_page(request: Request):
    """
    결제 관리 페이지 (학부모/학생용 청구서 조회 및 카드 결제)
    """
    return templates.TemplateResponse(
        "club/billing.html",
        {
            "request": request,
            "title": "결제 관리",
            "portone_store_id": config.PORTONE_STORE_ID,
            "portone_channel_key": getattr(config, "PORTONE_CHANNEL_KEY", ""),
        }
    )
