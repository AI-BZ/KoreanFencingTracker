"""
Videos Router - 영상 코멘트 API

POST   /club/videos/             - 영상 등록 (모든 회원)
GET    /club/videos/             - 영상 목록
GET    /club/videos/stats        - 영상 통계
GET    /club/videos/{video_id}   - 영상 상세 (댓글 포함)
DELETE /club/videos/{video_id}   - 영상 삭제
POST   /club/videos/{video_id}/comments            - 댓글 추가
DELETE /club/videos/{video_id}/comments/{comment_id} - 댓글 삭제
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger

from ..club.dependencies import (
    ClubMemberContext,
    ClubRole,
    get_current_club_member,
    require_coach,
)
from .models import (
    VideoCreate,
    VideoResponse,
    VideoDetailResponse,
    VideoCommentCreate,
    VideoCommentResponse,
    VideoStatsResponse,
)
from .service import video_service

router = APIRouter(prefix="/club/videos", tags=["Videos"])

COACH_ROLES = {ClubRole.owner, ClubRole.head_coach, ClubRole.coach, ClubRole.assistant}


# =============================================
# 영상 CRUD
# =============================================

@router.post("/", response_model=VideoResponse)
async def create_video(
    data: VideoCreate,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """
    영상 등록

    YouTube URL을 입력하면 oEmbed API로 제목/썸네일을 자동 추출합니다.
    모든 회원이 등록할 수 있습니다.
    """
    try:
        video = await video_service.create_video(
            org_id=member.organization_id,
            member_id=member.member_id,
            data=data.model_dump(),
        )
        return video
    except Exception as e:
        logger.error("영상 등록 실패: {}", e)
        raise HTTPException(500, f"영상 등록 실패: {str(e)}")


@router.get("/", response_model=List[VideoResponse])
async def list_videos(
    category: str = Query(None, description="카테고리 필터 (training, competition, drill)"),
    member_id: str = Query(None, description="특정 회원의 영상만"),
    limit: int = Query(20, ge=1, le=100, description="조회 개수"),
    offset: int = Query(0, ge=0, description="오프셋"),
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """
    영상 목록 조회

    클럽의 전체 영상을 조회합니다. 카테고리 또는 회원으로 필터링할 수 있습니다.
    """
    videos = await video_service.list_videos(
        org_id=member.organization_id,
        member_id=member_id,
        category=category,
        limit=limit,
        offset=offset,
    )
    return videos


@router.get("/stats", response_model=VideoStatsResponse)
async def get_video_stats(
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """
    영상 통계

    전체 영상 수, 댓글 수, 카테고리별 집계를 반환합니다.
    """
    stats = await video_service.get_video_stats(member.organization_id)
    return stats


@router.get("/{video_id}", response_model=VideoDetailResponse)
async def get_video(
    video_id: str,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """
    영상 상세 조회

    영상 정보와 모든 댓글(답글 포함)을 반환합니다.
    """
    video = await video_service.get_video(video_id)

    if not video:
        raise HTTPException(404, "영상을 찾을 수 없습니다")

    return video


@router.delete("/{video_id}")
async def delete_video(
    video_id: str,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """
    영상 삭제

    본인이 등록한 영상 또는 코치 이상만 삭제할 수 있습니다.
    """
    is_coach = member.club_role in COACH_ROLES

    try:
        deleted = await video_service.delete_video(
            video_id=video_id,
            member_id=member.member_id,
            is_coach=is_coach,
        )
        if not deleted:
            raise HTTPException(404, "영상을 찾을 수 없습니다")
        return {"success": True, "message": "영상이 삭제되었습니다"}
    except PermissionError as e:
        raise HTTPException(403, str(e))


# =============================================
# 댓글 CRUD
# =============================================

@router.post("/{video_id}/comments", response_model=VideoCommentResponse)
async def add_comment(
    video_id: str,
    data: VideoCommentCreate,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """
    댓글 추가

    타임스탬프 댓글(timestamp_seconds)은 코치 이상만 작성할 수 있습니다.
    답글은 parent_comment_id를 지정하여 작성합니다.
    """
    # 타임스탬프 댓글은 코치+만
    if data.timestamp_seconds is not None and member.club_role not in COACH_ROLES:
        raise HTTPException(403, "타임스탬프 코멘트는 코치만 작성할 수 있습니다")

    # 영상 존재 확인
    video = await video_service.get_video(video_id)
    if not video:
        raise HTTPException(404, "영상을 찾을 수 없습니다")

    try:
        comment = await video_service.add_comment(
            video_id=video_id,
            author_id=member.member_id,
            data=data.model_dump(),
        )
        return comment
    except Exception as e:
        logger.error("댓글 추가 실패: {}", e)
        raise HTTPException(500, f"댓글 추가 실패: {str(e)}")


@router.delete("/{video_id}/comments/{comment_id}")
async def delete_comment(
    video_id: str,
    comment_id: str,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """
    댓글 삭제

    본인이 작성한 댓글 또는 코치 이상만 삭제할 수 있습니다.
    """
    is_coach = member.club_role in COACH_ROLES

    try:
        deleted = await video_service.delete_comment(
            comment_id=comment_id,
            author_id=member.member_id,
            is_coach=is_coach,
        )
        if not deleted:
            raise HTTPException(404, "댓글을 찾을 수 없습니다")
        return {"success": True, "message": "댓글이 삭제되었습니다"}
    except PermissionError as e:
        raise HTTPException(403, str(e))
