"""
Competitions Router - 대회 참가 관리 API

코치용: 대회 이벤트 등록/수정/삭제, RSVP 목록, 마감 정산
학생용: 대회 목록 조회, RSVP 참석 응답
웹훅: data 서비스 대회 동기화
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from ..club.dependencies import (
    ClubMemberContext,
    get_current_club_member,
    require_coach,
    require_admin,
)
from .models import (
    CompetitionEventCreate,
    CompetitionEventUpdate,
    CompetitionEventResponse,
    RSVPCreate,
    RSVPResponse,
    CompetitionCostSummary,
    RSVPSummary,
)
from .service import competition_service

router = APIRouter(prefix="/competitions", tags=["Competitions"])


# =============================================
# 대회 이벤트 CRUD
# =============================================

@router.post("/events", response_model=CompetitionEventResponse)
async def create_event(
    data: CompetitionEventCreate,
    member: ClubMemberContext = Depends(require_coach),
):
    """대회 이벤트 생성 (코치 이상)"""
    event = competition_service.create_event(
        org_id=member.organization_id,
        data=data.model_dump(),
        created_by=member.member_id,
    )

    members_map = competition_service._get_members_map(member.organization_id)
    return _to_event_response(event, members_map)


@router.get("/events")
async def list_events(
    status: Optional[str] = Query(None, description="상태 필터 (upcoming/ongoing/completed/cancelled/closed)"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """대회 이벤트 목록 조회"""
    events, total = competition_service.list_events(
        org_id=member.organization_id,
        status=status,
        limit=limit,
        offset=offset,
    )

    members_map = competition_service._get_members_map(member.organization_id)
    return {
        "items": [_to_event_response(e, members_map) for e in events],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/events/{event_id}", response_model=CompetitionEventResponse)
async def get_event(
    event_id: str,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """대회 이벤트 상세 조회"""
    event = competition_service.get_event(
        org_id=member.organization_id,
        event_id=event_id,
    )
    if not event:
        raise HTTPException(404, "대회 이벤트를 찾을 수 없습니다")

    members_map = competition_service._get_members_map(member.organization_id)
    return _to_event_response(event, members_map)


@router.put("/events/{event_id}", response_model=CompetitionEventResponse)
async def update_event(
    event_id: str,
    data: CompetitionEventUpdate,
    member: ClubMemberContext = Depends(require_coach),
):
    """대회 이벤트 수정 (코치 이상)"""
    update_data = data.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(400, "수정할 항목이 없습니다")

    event = competition_service.update_event(
        org_id=member.organization_id,
        event_id=event_id,
        data=update_data,
    )
    if not event:
        raise HTTPException(404, "대회 이벤트를 찾을 수 없습니다")

    members_map = competition_service._get_members_map(member.organization_id)
    return _to_event_response(event, members_map)


@router.delete("/events/{event_id}")
async def delete_event(
    event_id: str,
    member: ClubMemberContext = Depends(require_admin),
):
    """대회 이벤트 삭제 (관리자 이상)"""
    success = competition_service.delete_event(
        org_id=member.organization_id,
        event_id=event_id,
    )
    if not success:
        raise HTTPException(404, "대회 이벤트를 찾을 수 없습니다")

    return {"success": True, "message": "대회 이벤트가 삭제되었습니다"}


# =============================================
# RSVP 관리
# =============================================

@router.post("/events/{event_id}/rsvp", response_model=RSVPResponse)
async def submit_rsvp(
    event_id: str,
    data: RSVPCreate,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """RSVP 참석 응답 제출 (모든 회원)

    동일 이벤트에 대해 재제출 시 기존 응답을 덮어씁니다 (upsert).
    """
    try:
        rsvp = competition_service.submit_rsvp(
            org_id=member.organization_id,
            event_id=event_id,
            member_id=member.member_id,
            responded_by=member.member_id,
            data=data.model_dump(),
        )
    except ValueError as e:
        raise HTTPException(404, str(e))

    members_map = competition_service._get_members_map(member.organization_id)
    return _to_rsvp_response(rsvp, members_map)


@router.get("/events/{event_id}/rsvps")
async def get_rsvps(
    event_id: str,
    member: ClubMemberContext = Depends(require_coach),
):
    """대회 이벤트 RSVP 목록 (코치 이상)"""
    rsvps = competition_service.get_rsvps(
        org_id=member.organization_id,
        event_id=event_id,
    )

    members_map = competition_service._get_members_map(member.organization_id)
    return {
        "items": [_to_rsvp_response(r, members_map) for r in rsvps],
        "total": len(rsvps),
    }


# =============================================
# 대회 마감 & 비용 정산
# =============================================

@router.post("/events/{event_id}/finalize")
async def finalize_event(
    event_id: str,
    member: ClubMemberContext = Depends(require_coach),
):
    """대회 마감 및 비용 정산 (코치 이상)

    - status를 'closed'로 변경
    - 참석 인원 기준 1인당 비용 계산
    """
    result = competition_service.finalize_event(
        org_id=member.organization_id,
        event_id=event_id,
        created_by=member.member_id,
    )
    if not result:
        raise HTTPException(404, "대회 이벤트를 찾을 수 없습니다")

    members_map = competition_service._get_members_map(member.organization_id)
    return {
        "event": _to_event_response(result["event"], members_map),
        "cost_summary": result["cost_summary"],
    }


# =============================================
# data 서비스 웹훅
# =============================================

@router.post("/sync")
async def sync_from_data_service(
    payload: dict,
):
    """data 서비스 대회 동기화 웹훅

    data 서비스에서 새 대회가 등록되면 호출됩니다.
    인증 불필요 (서비스 간 내부 통신).

    payload: {
        organization_id: int,
        competition_id: int,
        name: str,
        start_date: str,
        end_date: str (optional),
        location: str (optional),
        weapon: str (optional),
        age_group: str (optional),
    }
    """
    org_id = payload.get("organization_id")
    if not org_id:
        raise HTTPException(400, "organization_id is required")

    event = competition_service.sync_from_data_service(
        org_id=org_id,
        competition_data=payload,
    )

    return {"success": True, "event_id": event.get("id")}


# =============================================
# Response Helpers
# =============================================

def _to_event_response(event: dict, members_map: dict) -> dict:
    """대회 이벤트 DB row -> response dict"""
    rsvp_summary = event.get("rsvp_summary", {})

    return {
        "id": event["id"],
        "organization_id": event["organization_id"],
        "competition_id": event.get("competition_id"),
        "name": event["name"],
        "start_date": event.get("start_date", ""),
        "end_date": event.get("end_date"),
        "location": event.get("location"),
        "weapon": event.get("weapon"),
        "age_group": event.get("age_group"),
        "entry_fee": event.get("entry_fee", 0),
        "coach_travel_fee": event.get("coach_travel_fee", 0),
        "transportation_fee": event.get("transportation_fee", 0),
        "rsvp_deadline": event.get("rsvp_deadline"),
        "is_auto_synced": event.get("is_auto_synced", False),
        "source": event.get("source", "manual"),
        "status": event.get("status", "upcoming"),
        "created_by": event.get("created_by"),
        "created_at": event.get("created_at"),
        "updated_at": event.get("updated_at", event.get("created_at")),
        "rsvp_summary": {
            "attending_count": rsvp_summary.get("attending_count", 0),
            "not_attending_count": rsvp_summary.get("not_attending_count", 0),
            "maybe_count": rsvp_summary.get("maybe_count", 0),
        },
    }


def _to_rsvp_response(rsvp: dict, members_map: dict) -> dict:
    """RSVP DB row -> response dict"""
    member_info = members_map.get(str(rsvp.get("member_id", "")), {})

    return {
        "id": rsvp.get("id", ""),
        "event_id": rsvp["event_id"],
        "member_id": rsvp["member_id"],
        "member_name": member_info.get("name"),
        "responded_by": rsvp.get("responded_by"),
        "status": rsvp["status"],
        "reason": rsvp.get("reason"),
        "responded_at": rsvp.get("responded_at"),
    }
