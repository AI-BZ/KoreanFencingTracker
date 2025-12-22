"""
Club Management Router

펜싱 클럽/학교 회원 관리 SaaS 메인 라우터
- 대시보드
- 선수 데이터 연동 (핵심!)
- 회원 관리
- 출결 관리
- 비용 관리
"""

from datetime import date, datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .dependencies import (
    ClubMemberContext,
    get_current_club_member,
    require_coach,
    require_staff,
    get_client_ip
)
from .models import (
    ClubDashboard,
    TodayCheckin,
    UpcomingCompetition,
    DashboardAlert,
    CheckInRequest,
    CheckInResponse,
    AttendanceType,
    CheckinMethod,
    LessonType,
    LessonStatus,
    ParticipantStatus,
    LessonCreate,
    LessonUpdate,
    LessonResponse,
    LessonDetail,
    LessonParticipant,
    ParticipantAdd,
    ParticipantAttendance
)
from .players import players_router, player_service
from database.supabase_client import get_supabase_client

router = APIRouter(prefix="/club", tags=["Club Management"])

# 선수 데이터 라우터 포함 (핵심 기능!)
router.include_router(players_router)

# 템플릿 설정
templates = Jinja2Templates(directory="templates")


# =============================================
# Dashboard
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
# 출석 체크인 (학생용)
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


# =============================================
# 회원 관리
# =============================================

@router.get("/members")
async def list_members(
    status: Optional[str] = Query(None, description="상태 필터"),
    role: Optional[str] = Query(None, description="역할 필터"),
    member: ClubMemberContext = Depends(require_staff)
):
    """
    회원 목록 조회

    - staff 이상 권한 필요
    """
    supabase = get_supabase_client()

    query = supabase.table("members").select(
        "id, full_name, email, phone, club_role, member_status, player_id, "
        "enrollment_date, created_at"
    ).eq("organization_id", member.organization_id)

    if status:
        query = query.eq("member_status", status)
    if role:
        query = query.eq("club_role", role)

    response = query.order("created_at", desc=True).execute()

    # 연결된 선수 정보 추가
    members = []
    for m in (response.data or []):
        player_info = {}
        if m.get("player_id"):
            player_response = supabase.table("players").select(
                "name, team, weapon"
            ).eq("id", m["player_id"]).single().execute()

            if player_response.data:
                player_info = {
                    "player_name": player_response.data.get("name"),
                    "player_team": player_response.data.get("team"),
                    "player_weapon": player_response.data.get("weapon")
                }

        members.append({**m, **player_info})

    return {"total": len(members), "members": members}


@router.get("/members/{member_id}")
async def get_member_detail(
    member_id: str,
    member: ClubMemberContext = Depends(get_current_club_member)
):
    """
    회원 상세 조회

    본인 또는 staff 이상만 조회 가능
    """
    supabase = get_supabase_client()

    # 권한 체크: 본인이거나 staff 이상
    if member.member_id != member_id and not member.is_staff():
        raise HTTPException(status_code=403, detail="권한이 없습니다")

    response = supabase.table("members").select(
        "*"
    ).eq("id", member_id).eq(
        "organization_id", member.organization_id
    ).single().execute()

    if not response.data:
        raise HTTPException(status_code=404, detail="회원을 찾을 수 없습니다")

    member_data = response.data

    # 연결된 선수 정보
    player_profile = None
    if member_data.get("player_id"):
        player_profile = await player_service.get_player_profile(
            member_data["player_id"]
        )

    return {
        **member_data,
        "player_profile": player_profile
    }


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


# =============================================
# 레슨 관리 (코치용)
# =============================================

@router.post("/lessons", response_model=LessonResponse)
async def create_lesson(
    lesson_data: LessonCreate,
    member: ClubMemberContext = Depends(require_coach)
):
    """
    레슨 생성 (코치 이상)

    - 개인/그룹/팀/특별 레슨 생성
    - 참가자 함께 등록 가능
    """
    supabase = get_supabase_client()

    # 코치 ID 설정 (지정 안 됐으면 현재 사용자)
    coach_id = lesson_data.coach_id or member.member_id

    # 지정된 코치가 같은 조직 소속인지 확인
    if coach_id != member.member_id:
        coach_check = supabase.table("members").select("id").eq(
            "id", coach_id
        ).eq("organization_id", member.organization_id).execute()
        if not coach_check.data:
            raise HTTPException(status_code=400, detail="지정된 코치를 찾을 수 없습니다")

    # 레슨 생성
    lesson_insert = {
        "organization_id": member.organization_id,
        "lesson_type": lesson_data.lesson_type.value,
        "title": lesson_data.title,
        "description": lesson_data.description,
        "scheduled_at": lesson_data.scheduled_at.isoformat(),
        "duration_minutes": lesson_data.duration_minutes,
        "coach_id": coach_id,
        "max_students": lesson_data.max_students,
        "fee_per_session": lesson_data.fee_per_session,
        "status": LessonStatus.scheduled.value
    }

    response = supabase.table("lessons").insert(lesson_insert).execute()

    if not response.data:
        raise HTTPException(status_code=500, detail="레슨 생성 실패")

    lesson = response.data[0]

    # 참가자 등록
    participant_count = 0
    if lesson_data.participant_ids:
        for pid in lesson_data.participant_ids[:lesson_data.max_students]:
            try:
                supabase.table("lesson_participants").insert({
                    "lesson_id": lesson["id"],
                    "member_id": pid,
                    "attendance_status": ParticipantStatus.registered.value
                }).execute()
                participant_count += 1
            except Exception:
                pass  # 중복이거나 없는 회원은 무시

    # 코치 이름 조회
    coach_response = supabase.table("members").select(
        "full_name"
    ).eq("id", coach_id).single().execute()
    coach_name = coach_response.data.get("full_name") if coach_response.data else None

    return LessonResponse(
        id=lesson["id"],
        organization_id=lesson["organization_id"],
        lesson_type=LessonType(lesson["lesson_type"]),
        title=lesson["title"],
        description=lesson.get("description"),
        scheduled_at=datetime.fromisoformat(lesson["scheduled_at"]),
        duration_minutes=lesson["duration_minutes"],
        coach_id=lesson["coach_id"],
        coach_name=coach_name,
        max_students=lesson["max_students"],
        fee_per_session=lesson.get("fee_per_session", 0),
        status=LessonStatus(lesson["status"]),
        participant_count=participant_count,
        created_at=datetime.fromisoformat(lesson["created_at"]),
        updated_at=datetime.fromisoformat(lesson["updated_at"])
    )


@router.get("/lessons", response_model=dict)
async def list_lessons(
    status: Optional[str] = Query(None, description="상태 필터"),
    lesson_type: Optional[str] = Query(None, description="유형 필터"),
    coach_id: Optional[str] = Query(None, description="코치 필터"),
    from_date: Optional[date] = Query(None, description="시작일"),
    to_date: Optional[date] = Query(None, description="종료일"),
    limit: int = Query(50, le=100),
    member: ClubMemberContext = Depends(require_staff)
):
    """
    레슨 목록 조회 (스태프 이상)

    - 다양한 필터 옵션 지원
    """
    supabase = get_supabase_client()

    query = supabase.table("lessons").select(
        "*, members!lessons_coach_id_fkey(full_name)"
    ).eq("organization_id", member.organization_id)

    if status:
        query = query.eq("status", status)
    if lesson_type:
        query = query.eq("lesson_type", lesson_type)
    if coach_id:
        query = query.eq("coach_id", coach_id)
    if from_date:
        query = query.gte("scheduled_at", f"{from_date}T00:00:00")
    if to_date:
        query = query.lte("scheduled_at", f"{to_date}T23:59:59")

    response = query.order("scheduled_at", desc=True).limit(limit).execute()

    lessons = []
    for lesson in (response.data or []):
        coach_info = lesson.get("members", {}) or {}

        # 참가자 수 조회
        participants_response = supabase.table("lesson_participants").select(
            "id", count="exact"
        ).eq("lesson_id", lesson["id"]).execute()
        participant_count = participants_response.count or 0

        lessons.append(LessonResponse(
            id=lesson["id"],
            organization_id=lesson["organization_id"],
            lesson_type=LessonType(lesson["lesson_type"]),
            title=lesson["title"],
            description=lesson.get("description"),
            scheduled_at=datetime.fromisoformat(lesson["scheduled_at"]),
            duration_minutes=lesson["duration_minutes"],
            coach_id=lesson["coach_id"],
            coach_name=coach_info.get("full_name"),
            max_students=lesson["max_students"],
            fee_per_session=lesson.get("fee_per_session", 0),
            status=LessonStatus(lesson["status"]),
            participant_count=participant_count,
            created_at=datetime.fromisoformat(lesson["created_at"]),
            updated_at=datetime.fromisoformat(lesson["updated_at"])
        ))

    return {"total": len(lessons), "lessons": lessons}


@router.get("/lessons/{lesson_id}", response_model=LessonDetail)
async def get_lesson_detail(
    lesson_id: str,
    member: ClubMemberContext = Depends(get_current_club_member)
):
    """
    레슨 상세 조회 (모든 역할)

    - 참가자 목록 포함
    """
    supabase = get_supabase_client()

    # 레슨 조회
    lesson_response = supabase.table("lessons").select(
        "*, members!lessons_coach_id_fkey(full_name)"
    ).eq("id", lesson_id).eq(
        "organization_id", member.organization_id
    ).single().execute()

    if not lesson_response.data:
        raise HTTPException(status_code=404, detail="레슨을 찾을 수 없습니다")

    lesson = lesson_response.data
    coach_info = lesson.get("members", {}) or {}

    # 참가자 목록 조회
    participants_response = supabase.table("lesson_participants").select(
        "*, members!lesson_participants_member_id_fkey(full_name)"
    ).eq("lesson_id", lesson_id).execute()

    participants = []
    for p in (participants_response.data or []):
        member_info = p.get("members", {}) or {}
        participants.append(LessonParticipant(
            id=p["id"],
            member_id=p["member_id"],
            member_name=member_info.get("full_name", "Unknown"),
            attendance_status=ParticipantStatus(p["attendance_status"]),
            attended_at=datetime.fromisoformat(p["attended_at"]) if p.get("attended_at") else None
        ))

    return LessonDetail(
        id=lesson["id"],
        organization_id=lesson["organization_id"],
        lesson_type=LessonType(lesson["lesson_type"]),
        title=lesson["title"],
        description=lesson.get("description"),
        scheduled_at=datetime.fromisoformat(lesson["scheduled_at"]),
        duration_minutes=lesson["duration_minutes"],
        coach_id=lesson["coach_id"],
        coach_name=coach_info.get("full_name"),
        max_students=lesson["max_students"],
        fee_per_session=lesson.get("fee_per_session", 0),
        status=LessonStatus(lesson["status"]),
        participants=participants,
        created_at=datetime.fromisoformat(lesson["created_at"]),
        updated_at=datetime.fromisoformat(lesson["updated_at"])
    )


@router.put("/lessons/{lesson_id}", response_model=LessonResponse)
async def update_lesson(
    lesson_id: str,
    update_data: LessonUpdate,
    member: ClubMemberContext = Depends(require_coach)
):
    """
    레슨 수정 (코치 이상)
    """
    supabase = get_supabase_client()

    # 레슨 확인
    lesson_check = supabase.table("lessons").select("id, status").eq(
        "id", lesson_id
    ).eq("organization_id", member.organization_id).single().execute()

    if not lesson_check.data:
        raise HTTPException(status_code=404, detail="레슨을 찾을 수 없습니다")

    # 완료/취소된 레슨은 수정 불가
    if lesson_check.data["status"] in ["completed", "cancelled"]:
        raise HTTPException(status_code=400, detail="완료/취소된 레슨은 수정할 수 없습니다")

    # 업데이트할 필드만 추출
    update_fields = {}
    if update_data.title is not None:
        update_fields["title"] = update_data.title
    if update_data.description is not None:
        update_fields["description"] = update_data.description
    if update_data.scheduled_at is not None:
        update_fields["scheduled_at"] = update_data.scheduled_at.isoformat()
    if update_data.duration_minutes is not None:
        update_fields["duration_minutes"] = update_data.duration_minutes
    if update_data.coach_id is not None:
        update_fields["coach_id"] = update_data.coach_id
    if update_data.max_students is not None:
        update_fields["max_students"] = update_data.max_students
    if update_data.fee_per_session is not None:
        update_fields["fee_per_session"] = update_data.fee_per_session
    if update_data.status is not None:
        update_fields["status"] = update_data.status.value

    if not update_fields:
        raise HTTPException(status_code=400, detail="수정할 내용이 없습니다")

    response = supabase.table("lessons").update(update_fields).eq(
        "id", lesson_id
    ).execute()

    if not response.data:
        raise HTTPException(status_code=500, detail="레슨 수정 실패")

    # 수정된 레슨 다시 조회
    lesson = response.data[0]

    # 코치 이름 조회
    coach_response = supabase.table("members").select(
        "full_name"
    ).eq("id", lesson["coach_id"]).single().execute()
    coach_name = coach_response.data.get("full_name") if coach_response.data else None

    # 참가자 수 조회
    participants_response = supabase.table("lesson_participants").select(
        "id", count="exact"
    ).eq("lesson_id", lesson_id).execute()
    participant_count = participants_response.count or 0

    return LessonResponse(
        id=lesson["id"],
        organization_id=lesson["organization_id"],
        lesson_type=LessonType(lesson["lesson_type"]),
        title=lesson["title"],
        description=lesson.get("description"),
        scheduled_at=datetime.fromisoformat(lesson["scheduled_at"]),
        duration_minutes=lesson["duration_minutes"],
        coach_id=lesson["coach_id"],
        coach_name=coach_name,
        max_students=lesson["max_students"],
        fee_per_session=lesson.get("fee_per_session", 0),
        status=LessonStatus(lesson["status"]),
        participant_count=participant_count,
        created_at=datetime.fromisoformat(lesson["created_at"]),
        updated_at=datetime.fromisoformat(lesson["updated_at"])
    )


@router.delete("/lessons/{lesson_id}")
async def cancel_lesson(
    lesson_id: str,
    member: ClubMemberContext = Depends(require_coach)
):
    """
    레슨 취소 (코치 이상)

    - 실제 삭제가 아닌 상태 변경
    """
    supabase = get_supabase_client()

    # 레슨 확인
    lesson_check = supabase.table("lessons").select("id, status").eq(
        "id", lesson_id
    ).eq("organization_id", member.organization_id).single().execute()

    if not lesson_check.data:
        raise HTTPException(status_code=404, detail="레슨을 찾을 수 없습니다")

    if lesson_check.data["status"] == "completed":
        raise HTTPException(status_code=400, detail="완료된 레슨은 취소할 수 없습니다")

    # 취소로 상태 변경
    response = supabase.table("lessons").update({
        "status": LessonStatus.cancelled.value
    }).eq("id", lesson_id).execute()

    if not response.data:
        raise HTTPException(status_code=500, detail="레슨 취소 실패")

    # 참가자들 상태도 취소로 변경
    supabase.table("lesson_participants").update({
        "attendance_status": ParticipantStatus.cancelled.value
    }).eq("lesson_id", lesson_id).execute()

    return {"success": True, "message": "레슨이 취소되었습니다"}


@router.post("/lessons/{lesson_id}/complete")
async def complete_lesson(
    lesson_id: str,
    member: ClubMemberContext = Depends(require_coach)
):
    """
    레슨 완료 처리 (코치 이상)

    - 등록됨 상태의 참가자는 결석으로 처리
    """
    supabase = get_supabase_client()

    # 레슨 확인
    lesson_check = supabase.table("lessons").select("id, status").eq(
        "id", lesson_id
    ).eq("organization_id", member.organization_id).single().execute()

    if not lesson_check.data:
        raise HTTPException(status_code=404, detail="레슨을 찾을 수 없습니다")

    if lesson_check.data["status"] in ["completed", "cancelled"]:
        raise HTTPException(status_code=400, detail="이미 완료/취소된 레슨입니다")

    # 완료로 상태 변경
    supabase.table("lessons").update({
        "status": LessonStatus.completed.value
    }).eq("id", lesson_id).execute()

    # 등록만 된 참가자는 결석 처리
    supabase.table("lesson_participants").update({
        "attendance_status": ParticipantStatus.absent.value
    }).eq("lesson_id", lesson_id).eq(
        "attendance_status", ParticipantStatus.registered.value
    ).execute()

    return {"success": True, "message": "레슨이 완료 처리되었습니다"}


# =============================================
# 레슨 참가자 관리
# =============================================

@router.post("/lessons/{lesson_id}/participants")
async def add_participants(
    lesson_id: str,
    participant_data: ParticipantAdd,
    member: ClubMemberContext = Depends(require_coach)
):
    """
    레슨에 참가자 추가 (코치 이상)
    """
    supabase = get_supabase_client()

    # 레슨 확인
    lesson_check = supabase.table("lessons").select(
        "id, status, max_students"
    ).eq("id", lesson_id).eq(
        "organization_id", member.organization_id
    ).single().execute()

    if not lesson_check.data:
        raise HTTPException(status_code=404, detail="레슨을 찾을 수 없습니다")

    if lesson_check.data["status"] in ["completed", "cancelled"]:
        raise HTTPException(status_code=400, detail="완료/취소된 레슨에는 참가자를 추가할 수 없습니다")

    # 현재 참가자 수 확인
    current_count_response = supabase.table("lesson_participants").select(
        "id", count="exact"
    ).eq("lesson_id", lesson_id).execute()
    current_count = current_count_response.count or 0

    max_students = lesson_check.data["max_students"]
    available_slots = max_students - current_count

    if available_slots <= 0:
        raise HTTPException(status_code=400, detail="레슨 정원이 가득 찼습니다")

    # 참가자 추가
    added = []
    errors = []

    for pid in participant_data.member_ids[:available_slots]:
        try:
            # 해당 조직 소속 회원인지 확인
            member_check = supabase.table("members").select("id, full_name").eq(
                "id", pid
            ).eq("organization_id", member.organization_id).single().execute()

            if not member_check.data:
                errors.append({"member_id": pid, "error": "회원을 찾을 수 없습니다"})
                continue

            # 참가자 등록
            supabase.table("lesson_participants").insert({
                "lesson_id": lesson_id,
                "member_id": pid,
                "attendance_status": ParticipantStatus.registered.value
            }).execute()

            added.append({
                "member_id": pid,
                "member_name": member_check.data["full_name"]
            })

        except Exception as e:
            if "duplicate" in str(e).lower():
                errors.append({"member_id": pid, "error": "이미 등록된 참가자입니다"})
            else:
                errors.append({"member_id": pid, "error": str(e)})

    return {
        "success": True,
        "added": added,
        "errors": errors
    }


@router.delete("/lessons/{lesson_id}/participants/{participant_member_id}")
async def remove_participant(
    lesson_id: str,
    participant_member_id: str,
    member: ClubMemberContext = Depends(require_coach)
):
    """
    레슨에서 참가자 제거 (코치 이상)
    """
    supabase = get_supabase_client()

    # 레슨 확인
    lesson_check = supabase.table("lessons").select("id, status").eq(
        "id", lesson_id
    ).eq("organization_id", member.organization_id).single().execute()

    if not lesson_check.data:
        raise HTTPException(status_code=404, detail="레슨을 찾을 수 없습니다")

    if lesson_check.data["status"] == "completed":
        raise HTTPException(status_code=400, detail="완료된 레슨의 참가자는 제거할 수 없습니다")

    # 참가자 삭제
    response = supabase.table("lesson_participants").delete().eq(
        "lesson_id", lesson_id
    ).eq("member_id", participant_member_id).execute()

    if not response.data:
        raise HTTPException(status_code=404, detail="참가자를 찾을 수 없습니다")

    return {"success": True, "message": "참가자가 제거되었습니다"}


@router.patch("/lessons/{lesson_id}/participants/{participant_member_id}/attendance")
async def update_participant_attendance(
    lesson_id: str,
    participant_member_id: str,
    attendance_data: ParticipantAttendance,
    member: ClubMemberContext = Depends(require_coach)
):
    """
    참가자 출석 상태 변경 (코치 이상)
    """
    supabase = get_supabase_client()

    # 레슨 확인
    lesson_check = supabase.table("lessons").select("id, status").eq(
        "id", lesson_id
    ).eq("organization_id", member.organization_id).single().execute()

    if not lesson_check.data:
        raise HTTPException(status_code=404, detail="레슨을 찾을 수 없습니다")

    # 참가자 출석 상태 업데이트
    update_fields = {
        "attendance_status": attendance_data.attendance_status.value
    }

    if attendance_data.attendance_status == ParticipantStatus.attended:
        update_fields["attended_at"] = datetime.now().isoformat()

    response = supabase.table("lesson_participants").update(update_fields).eq(
        "lesson_id", lesson_id
    ).eq("member_id", participant_member_id).execute()

    if not response.data:
        raise HTTPException(status_code=404, detail="참가자를 찾을 수 없습니다")

    return {"success": True, "message": "출석 상태가 변경되었습니다"}


@router.post("/lessons/{lesson_id}/participants/attendance-all")
async def mark_all_attended(
    lesson_id: str,
    member: ClubMemberContext = Depends(require_coach)
):
    """
    모든 참가자 출석 처리 (코치 이상)
    """
    supabase = get_supabase_client()

    # 레슨 확인
    lesson_check = supabase.table("lessons").select("id").eq(
        "id", lesson_id
    ).eq("organization_id", member.organization_id).single().execute()

    if not lesson_check.data:
        raise HTTPException(status_code=404, detail="레슨을 찾을 수 없습니다")

    # 모든 등록된 참가자 출석 처리
    response = supabase.table("lesson_participants").update({
        "attendance_status": ParticipantStatus.attended.value,
        "attended_at": datetime.now().isoformat()
    }).eq("lesson_id", lesson_id).eq(
        "attendance_status", ParticipantStatus.registered.value
    ).execute()

    count = len(response.data) if response.data else 0

    return {"success": True, "message": f"{count}명이 출석 처리되었습니다"}


# =============================================
# 학생/부모용 API (내 정보)
# =============================================

@router.get("/me")
async def get_my_info(
    member: ClubMemberContext = Depends(get_current_club_member)
):
    """
    내 정보 조회 (모든 역할)
    """
    supabase = get_supabase_client()

    # 조직 정보
    org_response = supabase.table("organizations").select(
        "id, name"
    ).eq("id", member.organization_id).single().execute()

    org = org_response.data or {}

    return {
        "member_id": member.member_id,
        "full_name": member.full_name,
        "club_role": member.club_role.value,
        "organization_id": member.organization_id,
        "organization_name": org.get("name", ""),
        "player_id": member.player_id
    }


@router.get("/my/attendance")
async def get_my_attendance(
    member: ClubMemberContext = Depends(get_current_club_member),
    limit: int = Query(10, le=50)
):
    """
    내 출석 기록 조회 (모든 역할)
    """
    supabase = get_supabase_client()

    # 내 출석 기록 (최근순)
    attendance_response = supabase.table("attendance").select(
        "id, check_in_at, check_out_at, attendance_type, notes"
    ).eq("member_id", member.member_id).order(
        "check_in_at", desc=True
    ).limit(limit).execute()

    attendance = attendance_response.data or []

    # 이번 달 출석 횟수
    this_month = date.today().strftime("%Y-%m")
    monthly_response = supabase.table("attendance").select(
        "id", count="exact"
    ).eq("member_id", member.member_id).gte(
        "check_in_at", f"{this_month}-01T00:00:00"
    ).execute()

    monthly_count = monthly_response.count or 0

    return {
        "attendance": [
            {
                "id": a["id"],
                "date": a["check_in_at"][:10] if a.get("check_in_at") else None,
                "check_in_at": a.get("check_in_at"),
                "check_out_at": a.get("check_out_at"),
                "type": a.get("attendance_type", "regular"),
                "notes": a.get("notes")
            }
            for a in attendance
        ],
        "monthly_count": monthly_count
    }


@router.get("/my/lessons")
async def get_my_lessons(
    member: ClubMemberContext = Depends(get_current_club_member),
    limit: int = Query(20, le=50)
):
    """
    내 레슨 일정 조회 (모든 역할)

    - 학생: 참가 중인 레슨 목록
    - 코치: 담당 레슨 목록
    """
    supabase = get_supabase_client()
    today = date.today()

    lessons = []

    # 학생인 경우: 참가 중인 레슨
    if member.club_role.value in ["student", "parent"]:
        participants_response = supabase.table("lesson_participants").select(
            "lesson_id, attendance_status, "
            "lessons!lesson_participants_lesson_id_fkey("
            "id, title, lesson_type, scheduled_at, duration_minutes, status, "
            "coach_id, members!lessons_coach_id_fkey(full_name))"
        ).eq("member_id", member.member_id).execute()

        for p in (participants_response.data or []):
            lesson = p.get("lessons", {})
            if not lesson:
                continue
            coach_info = lesson.get("members", {}) or {}

            lessons.append({
                "id": lesson.get("id"),
                "title": lesson.get("title"),
                "lesson_type": lesson.get("lesson_type"),
                "scheduled_at": lesson.get("scheduled_at"),
                "duration_minutes": lesson.get("duration_minutes"),
                "status": lesson.get("status"),
                "coach_name": coach_info.get("full_name"),
                "attendance_status": p.get("attendance_status")
            })
    else:
        # 코치/스태프인 경우: 담당 레슨
        lessons_response = supabase.table("lessons").select(
            "id, title, lesson_type, scheduled_at, duration_minutes, status"
        ).eq("organization_id", member.organization_id).eq(
            "coach_id", member.member_id
        ).gte("scheduled_at", f"{today}T00:00:00").order(
            "scheduled_at", desc=False
        ).limit(limit).execute()

        for lesson in (lessons_response.data or []):
            # 참가자 수 조회
            count_response = supabase.table("lesson_participants").select(
                "id", count="exact"
            ).eq("lesson_id", lesson["id"]).execute()

            lessons.append({
                "id": lesson.get("id"),
                "title": lesson.get("title"),
                "lesson_type": lesson.get("lesson_type"),
                "scheduled_at": lesson.get("scheduled_at"),
                "duration_minutes": lesson.get("duration_minutes"),
                "status": lesson.get("status"),
                "participant_count": count_response.count or 0
            })

    # 예정된 레슨만 카운트 (upcoming)
    upcoming_count = sum(
        1 for l in lessons
        if l.get("status") in ["scheduled", "in_progress"]
        and l.get("scheduled_at", "") >= today.isoformat()
    )

    return {
        "lessons": lessons,
        "upcoming_count": upcoming_count
    }


@router.get("/announcements")
async def get_announcements(
    member: ClubMemberContext = Depends(get_current_club_member),
    limit: int = Query(10, le=50)
):
    """
    클럽 공지사항 조회 (모든 역할)
    공지사항 테이블 구현 후 실제 데이터 반환
    """
    # TODO: 공지사항 테이블 구현 후 실제 데이터 조회
    # 현재는 테스트 데이터 반환

    return {
        "announcements": [
            {
                "id": "1",
                "title": "12월 대회 참가 안내",
                "date": "2024-12-15",
                "preview": "이번 12월 회장배 대회 참가 신청을 받습니다. 참가 희망 선수는 12월 20일까지 신청해주세요.",
                "author": "최병철 감독"
            },
            {
                "id": "2",
                "title": "연말 휴관 안내",
                "date": "2024-12-10",
                "preview": "12월 30일 ~ 1월 2일까지 휴관합니다. 새해 복 많이 받으세요!",
                "author": "최병철 감독"
            },
        ]
    }


# =============================================
# HTML 페이지 (템플릿)
# =============================================

@router.get("/", response_class=HTMLResponse)
async def club_dashboard_page(request: Request):
    """
    클럽 대시보드 페이지 (HTML)
    """
    return templates.TemplateResponse(
        "club/dashboard.html",
        {"request": request, "title": "클럽 대시보드"}
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
