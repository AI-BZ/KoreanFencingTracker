"""
Members Router

회원 관리 API
- 회원 CRUD (목록, 상세)
- 내 정보 / 내 출석 / 내 레슨
- 공지사항
"""

from datetime import date, datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from ..dependencies import (
    ClubMemberContext,
    get_current_club_member,
    require_staff,
)
from ..players import player_service
from ...database import get_supabase_client

router = APIRouter(tags=["Members"])


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
