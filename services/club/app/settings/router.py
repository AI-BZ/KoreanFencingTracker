"""
Settings Router - 클럽 설정 및 회원 승인 API

관리자용: 프로필 수정, 설정 관리, 회원 승인/거절
코치용: 승인 대기 목록 조회, 회원 통계
공개: 회원 가입 신청
"""

from fastapi import APIRouter, Depends, HTTPException

from ..club.dependencies import (
    ClubMemberContext,
    get_current_club_member,
    require_coach,
    require_admin,
)
from .models import (
    ClubProfile,
    ClubProfileResponse,
    ClubSettingsUpdate,
    ClubSettingsResponse,
    MemberApprovalRequest,
    PendingMemberResponse,
    MembershipRequest,
    MemberStatsResponse,
    ApprovalAction,
)
from .service import settings_service
from .. import config

router = APIRouter(prefix="/club/settings", tags=["Settings"])


# =============================================
# 클럽 프로필
# =============================================

@router.get("/profile", response_model=ClubProfileResponse)
async def get_club_profile(
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """클럽 프로필 조회 (모든 회원)"""
    profile = settings_service.get_club_profile(member.organization_id)
    if not profile:
        raise HTTPException(404, "클럽 정보를 찾을 수 없습니다")
    return ClubProfileResponse(**profile)


@router.put("/profile", response_model=ClubProfileResponse)
async def update_club_profile(
    data: ClubProfile,
    member: ClubMemberContext = Depends(require_admin),
):
    """클럽 프로필 수정 (관리자 전용)"""
    update_data = data.model_dump(exclude_none=True)

    if not update_data:
        raise HTTPException(400, "수정할 항목이 없습니다")

    profile = settings_service.update_club_profile(
        member.organization_id, update_data
    )
    if not profile:
        raise HTTPException(404, "클럽 정보를 찾을 수 없습니다")

    return ClubProfileResponse(**profile)


# =============================================
# 클럽 설정
# =============================================

@router.get("/settings", response_model=ClubSettingsResponse)
async def get_club_settings(
    member: ClubMemberContext = Depends(require_admin),
):
    """클럽 설정 조회 (관리자 전용)"""
    settings = settings_service.get_club_settings(member.organization_id)
    return ClubSettingsResponse(**settings)


@router.put("/settings", response_model=ClubSettingsResponse)
async def update_club_settings(
    data: ClubSettingsUpdate,
    member: ClubMemberContext = Depends(require_admin),
):
    """클럽 설정 수정 (관리자 전용)"""
    update_data = data.model_dump(exclude_none=True)

    if not update_data:
        raise HTTPException(400, "수정할 항목이 없습니다")

    settings = settings_service.update_club_settings(
        member.organization_id, update_data
    )
    return ClubSettingsResponse(**settings)


# =============================================
# 회원 승인
# =============================================

@router.get("/members/pending")
async def get_pending_members(
    member: ClubMemberContext = Depends(require_coach),
):
    """승인 대기 회원 목록 (코치 이상)"""
    pending = settings_service.get_pending_members(member.organization_id)
    return {
        "total": len(pending),
        "members": [PendingMemberResponse(**m) for m in pending],
    }


@router.post("/members/approve")
async def approve_member(
    data: MemberApprovalRequest,
    member: ClubMemberContext = Depends(require_admin),
):
    """회원 승인 (관리자 전용)"""
    if data.action != ApprovalAction.approve:
        raise HTTPException(400, "이 엔드포인트는 승인만 처리합니다. 거절은 /members/reject를 사용하세요.")

    result = settings_service.approve_member(
        org_id=member.organization_id,
        approver_id=member.member_id,
        member_id=data.member_id,
        role=data.role.value if data.role else None,
    )

    if not result:
        raise HTTPException(404, "승인 대기 회원을 찾을 수 없습니다")

    return {
        "success": True,
        "message": f"{result.get('full_name', '')} 회원이 승인되었습니다",
        "member": result,
    }


@router.post("/members/reject")
async def reject_member(
    data: MemberApprovalRequest,
    member: ClubMemberContext = Depends(require_admin),
):
    """회원 거절 (관리자 전용)"""
    if data.action != ApprovalAction.reject:
        raise HTTPException(400, "이 엔드포인트는 거절만 처리합니다. 승인은 /members/approve를 사용하세요.")

    result = settings_service.reject_member(
        org_id=member.organization_id,
        approver_id=member.member_id,
        member_id=data.member_id,
        reason=data.rejection_reason,
    )

    if not result:
        raise HTTPException(404, "승인 대기 회원을 찾을 수 없습니다")

    return {
        "success": True,
        "message": f"{result.get('full_name', '')} 회원이 거절되었습니다",
        "member": result,
    }


@router.post("/members/request")
async def request_membership(
    data: MembershipRequest,
):
    """회원 가입 신청 (비인증 공개 API)"""
    org_id = config.DEFAULT_ORG_ID

    result = settings_service.request_membership(
        org_id=org_id,
        member_data=data.model_dump(),
    )

    if not result:
        raise HTTPException(500, "가입 신청 처리 중 오류가 발생했습니다")

    return {
        "success": True,
        "message": "가입 신청이 완료되었습니다. 관리자 승인 후 이용 가능합니다.",
        "member_id": result["id"],
    }


# =============================================
# 회원 통계
# =============================================

@router.get("/members/stats", response_model=MemberStatsResponse)
async def get_member_stats(
    member: ClubMemberContext = Depends(require_coach),
):
    """회원 통계 (코치 이상)"""
    stats = settings_service.get_member_stats(member.organization_id)
    return MemberStatsResponse(**stats)
