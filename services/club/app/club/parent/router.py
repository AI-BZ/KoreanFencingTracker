"""
Parent API Router - 학부모 전용 API

학부모가 자녀의 출석, 레슨, 대회 정보를 조회하는 엔드포인트.
guardian_member_id 기반으로 자녀 연동.
"""
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..dependencies import (
    ClubMemberContext,
    get_current_club_member,
)
from ...database import get_supabase_client

router = APIRouter(prefix="/parent", tags=["Parent"])


# ─── Response Models ─────────────────────────────────────

class ChildSummary(BaseModel):
    member_id: str
    full_name: str
    player_id: Optional[int] = None
    member_type: str
    attendance_this_month: int = 0
    total_days_this_month: int = 0


class ChildAttendance(BaseModel):
    date: str
    check_in_time: Optional[str] = None
    check_out_time: Optional[str] = None
    attendance_type: Optional[str] = None


class ChildLesson(BaseModel):
    lesson_id: int
    title: str
    coach_name: Optional[str] = None
    scheduled_date: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    status: Optional[str] = None


# ─── Helpers ─────────────────────────────────────────────

def _require_parent(member: ClubMemberContext):
    """학부모 계정인지 확인"""
    if not member.is_parent():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="학부모 계정만 접근 가능합니다",
        )


async def _get_children(parent_member_id: str, org_id: int) -> list:
    """guardian_member_id로 자녀 목록 조회"""
    supabase = get_supabase_client()
    result = supabase.table("members").select(
        "id, full_name, player_id, member_type, club_role"
    ).eq(
        "guardian_member_id", parent_member_id
    ).eq(
        "organization_id", org_id
    ).execute()
    return result.data or []


def _verify_child_access(children: list, child_id: str):
    """자녀 접근 권한 확인"""
    child_ids = [c["id"] for c in children]
    if child_id not in child_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="해당 자녀에 대한 접근 권한이 없습니다",
        )


# ─── Endpoints ───────────────────────────────────────────

@router.get("/children", response_model=List[ChildSummary])
async def get_children(
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """
    학부모의 자녀 목록 + 이번 달 출석 요약

    guardian_member_id가 현재 학부모의 member_id인 회원들을 반환.
    """
    _require_parent(member)

    children = await _get_children(member.member_id, member.organization_id)

    if not children:
        return []

    supabase = get_supabase_client()
    today = date.today()
    month_start = today.replace(day=1).isoformat()
    month_end = today.isoformat()

    result = []
    for child in children:
        # 이번 달 출석 횟수 조회
        att_response = supabase.table("attendance").select(
            "id", count="exact"
        ).eq(
            "member_id", child["id"]
        ).gte(
            "check_in_time", month_start
        ).lte(
            "check_in_time", month_end + "T23:59:59"
        ).execute()

        att_count = att_response.count or 0

        result.append(ChildSummary(
            member_id=child["id"],
            full_name=child["full_name"],
            player_id=child.get("player_id"),
            member_type=child.get("member_type", ""),
            attendance_this_month=att_count,
            total_days_this_month=today.day,
        ))

    return result


@router.get("/children/{child_id}/attendance", response_model=List[ChildAttendance])
async def get_child_attendance(
    child_id: str,
    month: Optional[str] = None,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """
    자녀의 출석 기록 조회

    Args:
        child_id: 자녀 member_id
        month: 조회 월 (YYYY-MM, 기본: 이번 달)
    """
    _require_parent(member)
    children = await _get_children(member.member_id, member.organization_id)
    _verify_child_access(children, child_id)

    if month:
        year, mon = month.split("-")
        start_date = f"{year}-{mon}-01"
        if int(mon) == 12:
            end_date = f"{int(year) + 1}-01-01"
        else:
            end_date = f"{year}-{int(mon) + 1:02d}-01"
    else:
        today = date.today()
        start_date = today.replace(day=1).isoformat()
        if today.month == 12:
            end_date = f"{today.year + 1}-01-01"
        else:
            end_date = f"{today.year}-{today.month + 1:02d}-01"

    supabase = get_supabase_client()
    att_response = supabase.table("attendance").select(
        "check_in_time, check_out_time, attendance_type"
    ).eq(
        "member_id", child_id
    ).gte(
        "check_in_time", start_date
    ).lt(
        "check_in_time", end_date
    ).order(
        "check_in_time", desc=True
    ).execute()

    return [
        ChildAttendance(
            date=row["check_in_time"][:10] if row.get("check_in_time") else "",
            check_in_time=row.get("check_in_time"),
            check_out_time=row.get("check_out_time"),
            attendance_type=row.get("attendance_type"),
        )
        for row in (att_response.data or [])
    ]


@router.get("/children/{child_id}/lessons", response_model=List[ChildLesson])
async def get_child_lessons(
    child_id: str,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """
    자녀의 레슨 현황 조회

    참여 중인 레슨 목록과 스케줄 반환.
    """
    _require_parent(member)
    children = await _get_children(member.member_id, member.organization_id)
    _verify_child_access(children, child_id)

    supabase = get_supabase_client()

    # lesson_participants에서 자녀가 참여한 레슨 조회
    participants = supabase.table("lesson_participants").select(
        "lesson_id, status"
    ).eq(
        "member_id", child_id
    ).execute()

    if not participants.data:
        return []

    lesson_ids = [p["lesson_id"] for p in participants.data]

    # 레슨 상세 정보 조회
    lessons = supabase.table("lessons").select(
        "id, title, coach_id, lesson_date, start_time, end_time, status"
    ).in_(
        "id", lesson_ids
    ).order(
        "lesson_date", desc=True
    ).limit(20).execute()

    # 코치 이름 매핑
    coach_ids = list(set(
        l["coach_id"] for l in (lessons.data or []) if l.get("coach_id")
    ))
    coach_map = {}
    if coach_ids:
        coaches = supabase.table("members").select(
            "id, full_name"
        ).in_("id", coach_ids).execute()
        coach_map = {c["id"]: c["full_name"] for c in (coaches.data or [])}

    return [
        ChildLesson(
            lesson_id=l["id"],
            title=l.get("title", ""),
            coach_name=coach_map.get(l.get("coach_id"), ""),
            scheduled_date=str(l.get("lesson_date", "")),
            start_time=l.get("start_time"),
            end_time=l.get("end_time"),
            status=l.get("status"),
        )
        for l in (lessons.data or [])
    ]


parent_router = router
