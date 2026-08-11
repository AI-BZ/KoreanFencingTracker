"""
Lessons Router - 레슨 패키지 & 예약 API

코치용: 패키지 생성/관리, 차감, 신청 승인/거절/시간변경
학생용: 패키지 조회, 레슨 신청, 코치 빈 시간 조회
공강 알림: 구독/해지
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
    LessonPackageCreate,
    LessonPackageUpdate,
    LessonPackageResponse,
    LessonPackageDetailResponse,
    LessonDeductionResponse,
    MyPackageSummary,
    LessonRequestCreate,
    LessonRequestRespond,
    LessonRequestReschedule,
    LessonRequestResponse,
    CoachAvailability,
    AvailableSlot,
    VacancySubscribeCreate,
    VacancySubscriptionResponse,
)
from .service import lesson_service

router = APIRouter(prefix="/lessons", tags=["Lessons & Packages"])


# =============================================
# 레슨 패키지 관리 (코치 이상)
# =============================================

@router.post("/packages", response_model=LessonPackageResponse)
async def create_package(
    data: LessonPackageCreate,
    member: ClubMemberContext = Depends(require_coach),
):
    """레슨 패키지 생성 (코치 이상)"""
    package = lesson_service.create_package(
        org_id=member.organization_id,
        member_id=data.member_id,
        coach_id=data.coach_id,
        package_type=data.package_type.value,
        total_sessions=data.total_sessions,
        total_price=data.total_price,
        price_per_session=data.price_per_session,
        expires_at=data.expires_at,
        notes=data.notes,
    )

    members_map = lesson_service._get_members_map(member.organization_id)
    return _to_package_response(package, members_map)


@router.get("/packages")
async def list_packages(
    member_id: Optional[str] = Query(None, description="회원 필터"),
    coach_id: Optional[str] = Query(None, description="코치 필터"),
    status: Optional[str] = Query(None, description="상태 필터"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    member: ClubMemberContext = Depends(require_staff),
):
    """패키지 목록 (스태프 이상)"""
    packages, total = lesson_service.list_packages(
        org_id=member.organization_id,
        member_id=member_id,
        coach_id=coach_id,
        status=status,
        limit=limit,
        offset=offset,
    )

    members_map = lesson_service._get_members_map(member.organization_id)
    return {
        "items": [_to_package_response(p, members_map) for p in packages],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/packages/my", response_model=MyPackageSummary)
async def get_my_packages(
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """내 활성 패키지 현황 (학생/학부모)"""
    summary = lesson_service.get_my_packages(
        org_id=member.organization_id,
        member_id=member.member_id,
    )

    members_map = lesson_service._get_members_map(member.organization_id)
    summary["packages"] = [
        _to_package_response(p, members_map) for p in summary["packages"]
    ]
    return summary


@router.get("/packages/{package_id}", response_model=LessonPackageDetailResponse)
async def get_package_detail(
    package_id: str,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """패키지 상세 (차감 이력 포함)"""
    package = lesson_service.get_package_with_deductions(
        package_id, member.organization_id
    )
    if not package:
        raise HTTPException(404, "패키지를 찾을 수 없습니다")

    # 본인 패키지 또는 코치/스태프만 조회 가능
    if not member.is_staff() and package["member_id"] != member.member_id:
        raise HTTPException(403, "본인 패키지만 조회할 수 있습니다")

    members_map = lesson_service._get_members_map(member.organization_id)
    result = _to_package_response(package, members_map)
    result["deductions"] = [
        _to_deduction_response(d, members_map) for d in package.get("deductions", [])
    ]
    return result


@router.put("/packages/{package_id}", response_model=LessonPackageResponse)
async def update_package(
    package_id: str,
    data: LessonPackageUpdate,
    member: ClubMemberContext = Depends(require_coach),
):
    """패키지 수정 (코치 이상)"""
    update_data = data.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(400, "수정할 항목이 없습니다")

    package = lesson_service.update_package(
        package_id, member.organization_id, **update_data
    )
    if not package:
        raise HTTPException(404, "패키지를 찾을 수 없습니다")

    members_map = lesson_service._get_members_map(member.organization_id)
    return _to_package_response(package, members_map)


# =============================================
# 레슨 차감 (코치)
# =============================================

@router.post("/packages/{package_id}/deduct", response_model=LessonDeductionResponse)
async def deduct_lesson(
    package_id: str,
    student_id: str = Query(..., description="학생 ID"),
    lesson_id: Optional[str] = Query(None, description="연결할 레슨 일정 ID"),
    notes: Optional[str] = Query(None, description="메모"),
    member: ClubMemberContext = Depends(require_coach),
):
    """레슨 완료 차감 (코치 이상)

    가장 오래된 활성 패키지에서 1회 차감.
    잔여 2회 이하 시 알림 트리거.
    """
    # 패키지 확인
    package = lesson_service.get_package(package_id, member.organization_id)
    if not package:
        raise HTTPException(404, "패키지를 찾을 수 없습니다")

    deduction = lesson_service.deduct_lesson(
        org_id=member.organization_id,
        lesson_id=lesson_id,
        student_id=student_id,
        coach_id=package["coach_id"],
        deducted_by=member.member_id,
        notes=notes,
    )
    if not deduction:
        raise HTTPException(400, "차감 가능한 패키지가 없거나 잔여 회수가 0입니다")

    members_map = lesson_service._get_members_map(member.organization_id)
    return _to_deduction_response(deduction, members_map)


# =============================================
# 레슨 신청 (학생/학부모)
# =============================================

@router.post("/requests", response_model=LessonRequestResponse)
async def create_lesson_request(
    data: LessonRequestCreate,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """레슨 신청 (학생/학부모)

    학부모는 student_id를 지정하여 대리 신청 가능.
    """
    student_id = data.student_id or member.member_id

    request = lesson_service.create_request(
        org_id=member.organization_id,
        student_id=student_id,
        coach_id=data.coach_id,
        requested_by=member.member_id,
        requested_date=data.requested_date,
        requested_start_time=data.requested_start_time,
        duration_minutes=data.duration_minutes,
    )

    members_map = lesson_service._get_members_map(member.organization_id)
    return _to_request_response(request, members_map)


@router.get("/requests")
async def list_lesson_requests(
    status: Optional[str] = Query(None, description="상태 필터"),
    student_id: Optional[str] = Query(None, description="학생 필터"),
    limit: int = Query(50, ge=1, le=200),
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """레슨 신청 목록

    코치: 자신에게 온 신청 목록
    학생/학부모: 자신의 신청 목록
    """
    coach_id = None

    if member.is_staff():
        # 코치 이상: 본인에게 온 신청 조회 (전체 조회도 가능)
        if not student_id:
            coach_id = member.member_id
    else:
        # 학생/학부모: 본인 신청만
        student_id = member.member_id

    requests = lesson_service.list_requests(
        org_id=member.organization_id,
        coach_id=coach_id,
        student_id=student_id,
        status=status,
        limit=limit,
    )

    members_map = lesson_service._get_members_map(member.organization_id)
    return {
        "items": [_to_request_response(r, members_map) for r in requests],
        "total": len(requests),
    }


@router.get("/requests/{request_id}", response_model=LessonRequestResponse)
async def get_lesson_request(
    request_id: str,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """레슨 신청 상세"""
    req = lesson_service.get_request(request_id, member.organization_id)
    if not req:
        raise HTTPException(404, "신청을 찾을 수 없습니다")

    # 관련자만 조회 가능
    if not member.is_staff():
        if req["student_id"] != member.member_id and req["requested_by"] != member.member_id:
            raise HTTPException(403, "본인 신청만 조회할 수 있습니다")

    members_map = lesson_service._get_members_map(member.organization_id)
    return _to_request_response(req, members_map)


# =============================================
# 레슨 신청 응답 (코치)
# =============================================

@router.patch("/requests/{request_id}/approve", response_model=LessonRequestResponse)
async def approve_request(
    request_id: str,
    data: LessonRequestRespond,
    member: ClubMemberContext = Depends(require_coach),
):
    """레슨 신청 승인 (코치)

    승인 시 스케줄에 자동 등록됩니다.
    """
    req = lesson_service.approve_request(
        request_id, member.organization_id, data.coach_note
    )
    if not req:
        raise HTTPException(400, "승인할 수 없는 신청입니다 (이미 처리됨)")

    members_map = lesson_service._get_members_map(member.organization_id)
    return _to_request_response(req, members_map)


@router.patch("/requests/{request_id}/reject", response_model=LessonRequestResponse)
async def reject_request(
    request_id: str,
    data: LessonRequestRespond,
    member: ClubMemberContext = Depends(require_coach),
):
    """레슨 신청 거절 (코치)"""
    req = lesson_service.reject_request(
        request_id, member.organization_id, data.coach_note
    )
    if not req:
        raise HTTPException(400, "거절할 수 없는 신청입니다 (이미 처리됨)")

    members_map = lesson_service._get_members_map(member.organization_id)
    return _to_request_response(req, members_map)


@router.patch("/requests/{request_id}/reschedule", response_model=LessonRequestResponse)
async def reschedule_request(
    request_id: str,
    data: LessonRequestReschedule,
    member: ClubMemberContext = Depends(require_coach),
):
    """레슨 시간 변경 제안 (코치)"""
    req = lesson_service.reschedule_request(
        request_id,
        member.organization_id,
        new_date=data.rescheduled_date,
        new_time=data.rescheduled_time,
        coach_note=data.coach_note,
    )
    if not req:
        raise HTTPException(400, "시간 변경할 수 없는 신청입니다 (이미 처리됨)")

    members_map = lesson_service._get_members_map(member.organization_id)
    return _to_request_response(req, members_map)


@router.delete("/requests/{request_id}")
async def cancel_request(
    request_id: str,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """레슨 신청 취소 (학생/학부모 본인만)"""
    req = lesson_service.cancel_request(
        request_id, member.organization_id, member.member_id
    )
    if not req:
        raise HTTPException(400, "취소할 수 없는 신청입니다 (권한 없거나 이미 처리됨)")

    return {"success": True, "message": "레슨 신청이 취소되었습니다"}


# =============================================
# 코치 빈 시간 조회
# =============================================

@router.get("/coaches/{coach_id}/available-slots", response_model=CoachAvailability)
async def get_coach_available_slots(
    coach_id: str,
    target_date: date = Query(..., description="조회 날짜"),
    duration: int = Query(60, ge=30, le=180, description="레슨 시간(분)"),
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """코치 빈 시간 조회

    다른 학생의 레슨은 '예약됨'으로만 표시 (개인정보 보호).
    """
    slots = lesson_service.get_coach_available_slots(
        org_id=member.organization_id,
        coach_id=coach_id,
        target_date=target_date,
        slot_duration=duration,
    )

    # 코치 이름 조회
    members_map = lesson_service._get_members_map(member.organization_id)
    coach_info = members_map.get(coach_id, {})

    return CoachAvailability(
        coach_id=coach_id,
        coach_name=coach_info.get("name"),
        date=target_date.isoformat(),
        slots=[AvailableSlot(**s) for s in slots],
    )


# =============================================
# 공강 알림 구독
# =============================================

@router.post("/vacancy-subscribe", response_model=VacancySubscriptionResponse)
async def subscribe_vacancy(
    data: VacancySubscribeCreate,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """공강 알림 구독 등록"""
    sub = lesson_service.subscribe_vacancy(
        org_id=member.organization_id,
        member_id=member.member_id,
        coach_id=data.coach_id,
        weekdays=data.weekdays,
        time_range_start=data.time_range_start,
        time_range_end=data.time_range_end,
    )

    members_map = lesson_service._get_members_map(member.organization_id)
    return _to_subscription_response(sub, members_map)


@router.get("/vacancy-subscribe")
async def get_my_subscriptions(
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """내 공강 알림 구독 목록"""
    subs = lesson_service.get_my_subscriptions(
        member.organization_id, member.member_id
    )

    members_map = lesson_service._get_members_map(member.organization_id)
    return {
        "items": [_to_subscription_response(s, members_map) for s in subs],
        "total": len(subs),
    }


@router.delete("/vacancy-subscribe/{sub_id}")
async def unsubscribe_vacancy(
    sub_id: str,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """공강 알림 구독 해제"""
    success = lesson_service.unsubscribe_vacancy(
        sub_id, member.organization_id, member.member_id
    )
    if not success:
        raise HTTPException(404, "구독을 찾을 수 없습니다")

    return {"success": True, "message": "구독이 해제되었습니다"}


# =============================================
# Response Helpers
# =============================================

def _to_package_response(package: dict, members_map: dict) -> dict:
    """패키지 DB row → response dict"""
    member_info = members_map.get(package.get("member_id", ""), {})
    coach_info = members_map.get(package.get("coach_id", ""), {})

    return {
        "id": package["id"],
        "organization_id": package["organization_id"],
        "member_id": package["member_id"],
        "member_name": member_info.get("name"),
        "coach_id": package["coach_id"],
        "coach_name": coach_info.get("name"),
        "package_type": package["package_type"],
        "total_sessions": package["total_sessions"],
        "used_sessions": package.get("used_sessions", 0),
        "remaining_sessions": package.get("remaining_sessions", 0),
        "price_per_session": package.get("price_per_session"),
        "total_price": package["total_price"],
        "purchased_at": package.get("purchased_at", package.get("created_at")),
        "expires_at": package.get("expires_at"),
        "status": package["status"],
        "notes": package.get("notes"),
        "created_at": package["created_at"],
        "updated_at": package.get("updated_at", package["created_at"]),
    }


def _to_deduction_response(deduction: dict, members_map: dict) -> dict:
    """차감 기록 DB row → response dict"""
    deductor_info = members_map.get(deduction.get("deducted_by", ""), {})

    return {
        "id": deduction["id"],
        "package_id": deduction["package_id"],
        "lesson_id": deduction.get("lesson_id"),
        "deducted_at": deduction.get("deducted_at", deduction.get("created_at")),
        "deducted_by": deduction["deducted_by"],
        "deductor_name": deductor_info.get("name"),
        "notes": deduction.get("notes"),
    }


def _to_request_response(req: dict, members_map: dict) -> dict:
    """레슨 신청 DB row → response dict"""
    student_info = members_map.get(req.get("student_id", ""), {})
    coach_info = members_map.get(req.get("coach_id", ""), {})
    requester_info = members_map.get(req.get("requested_by", ""), {})

    return {
        "id": req["id"],
        "organization_id": req["organization_id"],
        "student_id": req["student_id"],
        "student_name": student_info.get("name"),
        "coach_id": req["coach_id"],
        "coach_name": coach_info.get("name"),
        "requested_by": req["requested_by"],
        "requester_name": requester_info.get("name"),
        "requested_date": req["requested_date"],
        "requested_start_time": req["requested_start_time"],
        "duration_minutes": req.get("duration_minutes", 60),
        "status": req["status"],
        "coach_note": req.get("coach_note"),
        "rescheduled_date": req.get("rescheduled_date"),
        "rescheduled_time": req.get("rescheduled_time"),
        "created_at": req["created_at"],
        "responded_at": req.get("responded_at"),
    }


def _to_subscription_response(sub: dict, members_map: dict) -> dict:
    """구독 DB row → response dict"""
    coach_info = members_map.get(sub.get("coach_id", ""), {})

    return {
        "id": sub["id"],
        "member_id": sub["member_id"],
        "coach_id": sub.get("coach_id"),
        "coach_name": coach_info.get("name") if sub.get("coach_id") else None,
        "weekdays": sub.get("weekdays"),
        "time_range_start": sub.get("time_range_start"),
        "time_range_end": sub.get("time_range_end"),
        "is_active": sub.get("is_active", True),
    }
