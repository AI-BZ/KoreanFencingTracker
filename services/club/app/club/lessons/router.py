"""
Lessons Router

레슨 관리 API (코치용)
- 레슨 CRUD (생성, 목록, 상세, 수정, 취소, 완료)
- 참가자 관리 (추가, 제거, 출석 변경, 전체 출석)
"""

from datetime import date, datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from ..dependencies import (
    ClubMemberContext,
    get_current_club_member,
    require_coach,
    require_staff,
)
from ..models import (
    LessonType,
    LessonStatus,
    ParticipantStatus,
    LessonCreate,
    LessonUpdate,
    LessonResponse,
    LessonDetail,
    LessonParticipant,
    ParticipantAdd,
    ParticipantAttendance,
)
from ...database import get_supabase_client

router = APIRouter(tags=["Lessons"])


# =============================================
# 레슨 CRUD
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
