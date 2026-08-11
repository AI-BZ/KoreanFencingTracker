"""
Schedule Router - 일정 관리 API

코치용: 일정 CRUD, 반복 일정, 참가자 관리
학생용: 내 일정 조회
FullCalendar.js 연동 API
"""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from ..club.dependencies import (
    ClubMemberContext,
    get_current_club_member,
    require_coach,
    require_staff,
)
from .models import (
    EventType,
    EventVisibility,
    EventStatus,
    EVENT_COLORS,
    ScheduleCreate,
    ScheduleUpdate,
)
from .service import schedule_service

router = APIRouter(prefix="/schedule", tags=["Schedule & Calendar"])


# =============================================
# 캘린더 페이지 (HTML)
# =============================================

@router.get("/page", response_class=HTMLResponse)
async def schedule_page(request: Request):
    """캘린더 페이지"""
    from ..server import templates
    if templates:
        return templates.TemplateResponse("club/schedule.html", {"request": request})
    return HTMLResponse("<h1>Schedule Page</h1><p>Template not found</p>")


# =============================================
# 일정 조회 API (FullCalendar 연동)
# =============================================

@router.get("/events")
async def get_events(
    start: str = Query(..., description="시작일 (ISO 8601)"),
    end: str = Query(..., description="종료일 (ISO 8601)"),
    event_type: Optional[str] = Query(None, description="이벤트 유형 필터"),
    visibility: Optional[str] = Query(None, description="공개 범위 필터"),
    coach_id: Optional[str] = Query(None, description="코치 필터"),
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """
    일정 목록 (FullCalendar eventSources 호환)

    FullCalendar에서 start/end를 자동으로 전달합니다.
    """
    events = schedule_service.get_events(
        org_id=member.organization_id,
        start_date=start,
        end_date=end,
        member_id=member.member_id,
        member_role=member.club_role.value if member.club_role else None,
        event_type=event_type,
        visibility=visibility,
        coach_id=coach_id,
    )

    # 회원 이름 매핑
    members_map = _get_members_map(member.organization_id)

    return [
        schedule_service.to_fullcalendar_event(ev, members_map)
        for ev in events
    ]


@router.get("/events/{event_id}")
async def get_event_detail(
    event_id: str,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """일정 상세 조회"""
    event = schedule_service.get_event(event_id, member.organization_id)
    if not event:
        raise HTTPException(404, "일정을 찾을 수 없습니다")

    members_map = _get_members_map(member.organization_id)

    result = schedule_service.to_fullcalendar_event(event, members_map)

    # 참가자 이름 추가
    participant_names = []
    for pid in (event.get("participant_ids") or []):
        m = members_map.get(pid)
        if m:
            participant_names.append({"id": pid, "name": m["name"], "role": m.get("role")})
    result["participants"] = participant_names

    return result


# =============================================
# 일정 생성/수정/삭제 (코치 이상)
# =============================================

@router.post("/events")
async def create_event(
    data: ScheduleCreate,
    member: ClubMemberContext = Depends(require_coach),
):
    """일정 생성 (코치 이상)"""
    recurrence_rule = None
    if data.is_recurring and data.recurrence_rule:
        recurrence_rule = {
            "freq": data.recurrence_rule.freq.value,
            "days": data.recurrence_rule.days,
            "until": data.recurrence_rule.until.isoformat() if data.recurrence_rule.until else None,
        }

    event = schedule_service.create_event(
        org_id=member.organization_id,
        created_by=member.member_id,
        title=data.title,
        event_type=data.event_type.value,
        start_at=data.start_at,
        end_at=data.end_at,
        all_day=data.all_day,
        description=data.description,
        color=data.color,
        is_recurring=data.is_recurring,
        recurrence_rule=recurrence_rule,
        visibility=data.visibility.value,
        assigned_coach_id=data.assigned_coach_id,
        participant_ids=data.participant_ids,
        max_participants=data.max_participants,
        lesson_id=data.lesson_id,
        competition_id=data.competition_id,
        location=data.location,
    )

    members_map = _get_members_map(member.organization_id)
    return schedule_service.to_fullcalendar_event(event, members_map)


@router.put("/events/{event_id}")
async def update_event(
    event_id: str,
    data: ScheduleUpdate,
    member: ClubMemberContext = Depends(require_coach),
):
    """일정 수정 (코치 이상, 코치는 본인 담당만)"""
    existing = schedule_service.get_event(event_id, member.organization_id)
    if not existing:
        raise HTTPException(404, "일정을 찾을 수 없습니다")

    # 코치 권한 분리: owner/head_coach는 전체 편집, 코치는 본인만
    if not member.is_admin():
        is_creator = existing.get("created_by") == member.member_id
        is_assigned = existing.get("assigned_coach_id") == member.member_id
        if not (is_creator or is_assigned):
            raise HTTPException(403, "본인이 생성하거나 담당하는 일정만 수정할 수 있습니다")

    update_kwargs = data.model_dump(exclude_none=True)
    event = schedule_service.update_event(
        event_id=event_id,
        org_id=member.organization_id,
        **update_kwargs,
    )

    if not event:
        raise HTTPException(400, "수정에 실패했습니다")

    members_map = _get_members_map(member.organization_id)
    return schedule_service.to_fullcalendar_event(event, members_map)


@router.delete("/events/{event_id}")
async def delete_event(
    event_id: str,
    delete_children: bool = Query(False, description="반복 일정 전체 삭제"),
    member: ClubMemberContext = Depends(require_coach),
):
    """일정 삭제 (코치 이상, 코치는 본인 담당만)"""
    # 코치 권한 분리
    if not member.is_admin():
        existing = schedule_service.get_event(event_id, member.organization_id)
        if existing:
            is_creator = existing.get("created_by") == member.member_id
            is_assigned = existing.get("assigned_coach_id") == member.member_id
            if not (is_creator or is_assigned):
                raise HTTPException(403, "본인이 생성하거나 담당하는 일정만 삭제할 수 있습니다")

    success = schedule_service.delete_event(
        event_id, member.organization_id, delete_children
    )
    if not success:
        raise HTTPException(404, "일정을 찾을 수 없습니다")
    return {"success": True, "message": "일정이 삭제되었습니다"}


# =============================================
# 드래그&드롭 (시간 변경)
# =============================================

@router.patch("/events/{event_id}/move")
async def move_event(
    event_id: str,
    start: datetime = Query(...),
    end: datetime = Query(...),
    all_day: Optional[bool] = Query(None),
    member: ClubMemberContext = Depends(require_coach),
):
    """일정 이동 (드래그&드롭) - 코치 이상, 코치는 본인 담당만"""
    if not member.is_admin():
        existing = schedule_service.get_event(event_id, member.organization_id)
        if existing:
            is_creator = existing.get("created_by") == member.member_id
            is_assigned = existing.get("assigned_coach_id") == member.member_id
            if not (is_creator or is_assigned):
                raise HTTPException(403, "본인이 생성하거나 담당하는 일정만 이동할 수 있습니다")

    event = schedule_service.move_event(
        event_id, member.organization_id, start, end, all_day
    )
    if not event:
        raise HTTPException(404, "일정을 찾을 수 없습니다")

    members_map = _get_members_map(member.organization_id)
    return schedule_service.to_fullcalendar_event(event, members_map)


# =============================================
# 코치/회원 목록 (일정 생성 드롭다운용)
# =============================================

@router.get("/coaches")
async def get_coaches(
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """코치 목록"""
    coaches = schedule_service.get_coaches(member.organization_id)
    return {"coaches": coaches}


@router.get("/members")
async def get_members(
    member: ClubMemberContext = Depends(require_staff),
):
    """회원 목록 (스태프 이상)"""
    members = schedule_service.get_members(member.organization_id)
    return {"members": members}


# =============================================
# 이벤트 유형/색상 메타데이터
# =============================================

@router.get("/meta")
async def get_schedule_meta():
    """일정 메타데이터 (이벤트 유형, 색상 등)"""
    return {
        "event_types": [
            {"value": t.value, "label": _event_type_label(t.value)}
            for t in EventType
        ],
        "event_colors": EVENT_COLORS,
        "visibility_options": [
            {"value": "club", "label": "클럽 전체"},
            {"value": "coaches", "label": "코치만"},
            {"value": "personal", "label": "나만"},
        ],
        "status_options": [
            {"value": s.value, "label": _status_label(s.value)}
            for s in EventStatus
        ],
    }


# =============================================
# Helpers
# =============================================

def _get_members_map(org_id: int) -> dict:
    """회원 ID → {name, role} 매핑"""
    supabase = get_supabase_client()
    result = (
        supabase.table("members")
        .select("id, full_name, club_role")
        .eq("organization_id", org_id)
        .execute()
    )
    return {
        str(m["id"]): {"name": m["full_name"], "role": m.get("club_role")}
        for m in (result.data or [])
    }


def _event_type_label(et: str) -> str:
    labels = {
        "training": "정규 훈련",
        "lesson": "레슨",
        "competition": "대회",
        "club_event": "클럽 행사",
        "holiday": "휴일/휴무",
        "personal": "개인 일정",
        "meeting": "미팅/회의",
    }
    return labels.get(et, et)


def _status_label(st: str) -> str:
    labels = {
        "scheduled": "예정",
        "in_progress": "진행중",
        "completed": "완료",
        "cancelled": "취소",
    }
    return labels.get(st, st)


def get_supabase_client():
    from ..database import get_supabase_client as _get
    return _get()
