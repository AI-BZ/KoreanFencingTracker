"""
Announcements Router - 공지사항 API

POST   /club/announcements/                - 공지사항 작성 (관리자)
GET    /club/announcements/                - 공지사항 목록
GET    /club/announcements/unread-count    - 읽지 않은 공지 수
GET    /club/announcements/{id}            - 공지사항 상세 + 읽음 처리
PUT    /club/announcements/{id}            - 공지사항 수정
DELETE /club/announcements/{id}            - 공지사항 삭제
POST   /club/announcements/{id}/read       - 읽음 처리
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger

from ..club.dependencies import (
    ClubMemberContext,
    ClubRole,
    get_current_club_member,
    require_admin,
)
from .models import (
    AnnouncementCreate,
    AnnouncementUpdate,
    AnnouncementResponse,
    UnreadCountResponse,
)
from .service import announcement_service

router = APIRouter(prefix="/club/announcements", tags=["Announcements"])

ADMIN_ROLES = {ClubRole.owner, ClubRole.head_coach}


# =============================================
# 공지사항 CRUD
# =============================================

@router.post("/", response_model=AnnouncementResponse)
async def create_announcement(
    data: AnnouncementCreate,
    member: ClubMemberContext = Depends(require_admin),
):
    """
    공지사항 작성

    클럽 대표(owner) 또는 수석코치(head_coach)만 작성할 수 있습니다.
    target_roles를 지정하면 해당 역할의 회원에게만 표시됩니다.
    """
    try:
        announcement = await announcement_service.create_announcement(
            org_id=member.organization_id,
            author_id=member.member_id,
            data=data.model_dump(mode="json"),
        )
        return announcement
    except Exception as e:
        logger.error("공지사항 작성 실패: {}", e)
        raise HTTPException(500, f"공지사항 작성 실패: {str(e)}")


@router.get("/", response_model=list[AnnouncementResponse])
async def list_announcements(
    category: str = Query(None, description="카테고리 필터 (general, competition, schedule, urgent)"),
    include_expired: bool = Query(False, description="만료된 공지 포함"),
    limit: int = Query(20, ge=1, le=100, description="조회 개수"),
    offset: int = Query(0, ge=0, description="오프셋"),
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """
    공지사항 목록 조회

    고정 공지가 상단에, 최신 공지가 그 다음에 표시됩니다.
    기본적으로 만료되지 않은 공지만 표시됩니다.
    """
    announcements = await announcement_service.list_announcements(
        org_id=member.organization_id,
        member_id=member.member_id,
        category=category,
        include_expired=include_expired,
        limit=limit,
        offset=offset,
    )
    return announcements


@router.get("/unread-count", response_model=UnreadCountResponse)
async def get_unread_count(
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """
    읽지 않은 공지 수

    현재 유효한 공지 중 아직 읽지 않은 공지의 수를 반환합니다.
    """
    count = await announcement_service.get_unread_count(
        org_id=member.organization_id,
        member_id=member.member_id,
    )
    return {"unread_count": count}


@router.get("/{announcement_id}", response_model=AnnouncementResponse)
async def get_announcement(
    announcement_id: str,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """
    공지사항 상세 조회

    조회 시 자동으로 읽음 처리됩니다.
    """
    announcement = await announcement_service.get_announcement(
        announcement_id=announcement_id,
        member_id=member.member_id,
    )

    if not announcement:
        raise HTTPException(404, "공지사항을 찾을 수 없습니다")

    return announcement


@router.put("/{announcement_id}", response_model=AnnouncementResponse)
async def update_announcement(
    announcement_id: str,
    data: AnnouncementUpdate,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """
    공지사항 수정

    작성자 본인 또는 관리자(owner/head_coach)만 수정할 수 있습니다.
    """
    is_admin = member.club_role in ADMIN_ROLES

    try:
        announcement = await announcement_service.update_announcement(
            announcement_id=announcement_id,
            author_id=member.member_id,
            data=data.model_dump(exclude_none=True, mode="json"),
            is_admin=is_admin,
        )
        if not announcement:
            raise HTTPException(404, "공지사항을 찾을 수 없습니다")
        return announcement
    except PermissionError as e:
        raise HTTPException(403, str(e))


@router.delete("/{announcement_id}")
async def delete_announcement(
    announcement_id: str,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """
    공지사항 삭제

    작성자 본인 또는 관리자(owner/head_coach)만 삭제할 수 있습니다.
    """
    is_admin = member.club_role in ADMIN_ROLES

    try:
        deleted = await announcement_service.delete_announcement(
            announcement_id=announcement_id,
            author_id=member.member_id,
            is_admin=is_admin,
        )
        if not deleted:
            raise HTTPException(404, "공지사항을 찾을 수 없습니다")
        return {"success": True, "message": "공지사항이 삭제되었습니다"}
    except PermissionError as e:
        raise HTTPException(403, str(e))


@router.post("/{announcement_id}/read")
async def mark_as_read(
    announcement_id: str,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """
    읽음 처리

    공지사항을 읽음으로 표시합니다.
    """
    success = await announcement_service.mark_as_read(
        announcement_id=announcement_id,
        member_id=member.member_id,
    )

    if not success:
        raise HTTPException(404, "공지사항을 찾을 수 없습니다")

    return {"success": True, "message": "읽음 처리 완료"}
