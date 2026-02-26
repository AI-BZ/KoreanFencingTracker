"""
Videos Models - 영상 코멘트 Pydantic 모델
"""

from datetime import datetime
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field, field_validator
import re


# =============================================
# Enums
# =============================================

class VideoCategory(str, Enum):
    """영상 카테고리"""
    training = "training"
    competition = "competition"
    drill = "drill"


# =============================================
# Request Models
# =============================================

class VideoCreate(BaseModel):
    """영상 등록 요청"""
    youtube_url: str = Field(..., description="YouTube URL")
    title: Optional[str] = Field(None, max_length=200, description="제목 (미입력 시 YouTube에서 자동 추출)")
    description: Optional[str] = Field(None, description="설명")
    category: Optional[VideoCategory] = Field(None, description="카테고리")
    is_public: Optional[bool] = Field(True, description="공개 여부")

    @field_validator("youtube_url")
    @classmethod
    def validate_youtube_url(cls, v: str) -> str:
        """YouTube URL 형식 검증"""
        patterns = [
            r"(?:https?://)?(?:www\.)?youtube\.com/watch\?v=[\w-]+",
            r"(?:https?://)?(?:www\.)?youtube\.com/shorts/[\w-]+",
            r"(?:https?://)?youtu\.be/[\w-]+",
            r"(?:https?://)?(?:www\.)?youtube\.com/embed/[\w-]+",
        ]
        if not any(re.match(p, v) for p in patterns):
            raise ValueError("올바른 YouTube URL을 입력하세요")
        return v


class VideoCommentCreate(BaseModel):
    """영상 댓글 작성 요청"""
    content: str = Field(..., min_length=1, max_length=1000, description="댓글 내용")
    timestamp_seconds: Optional[int] = Field(None, ge=0, description="타임스탬프 (초)")
    parent_comment_id: Optional[str] = Field(None, description="부모 댓글 ID (답글)")


# =============================================
# Response Models
# =============================================

class VideoCommentResponse(BaseModel):
    """영상 댓글 응답"""
    id: str
    video_id: str
    author_id: str
    author_name: Optional[str] = None
    content: str
    timestamp_seconds: Optional[int] = None
    parent_comment_id: Optional[str] = None
    created_at: datetime
    replies: Optional[List["VideoCommentResponse"]] = None


class VideoResponse(BaseModel):
    """영상 응답"""
    id: str
    member_id: str
    member_name: Optional[str] = None
    youtube_url: str
    youtube_id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    thumbnail_url: Optional[str] = None
    duration_seconds: Optional[int] = None
    is_public: bool = True
    created_at: datetime
    comments_count: Optional[int] = 0


class VideoDetailResponse(BaseModel):
    """영상 상세 응답 (댓글 포함)"""
    id: str
    member_id: str
    member_name: Optional[str] = None
    youtube_url: str
    youtube_id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    thumbnail_url: Optional[str] = None
    duration_seconds: Optional[int] = None
    is_public: bool = True
    created_at: datetime
    comments: List[VideoCommentResponse] = []


class VideoStatsResponse(BaseModel):
    """영상 통계 응답"""
    total_videos: int = 0
    total_comments: int = 0
    by_category: dict = Field(default_factory=dict)
