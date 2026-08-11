"""
Announcements Models - 공지사항 Pydantic 모델
"""

from datetime import datetime
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field


# =============================================
# Enums
# =============================================

class AnnouncementCategory(str, Enum):
    """공지사항 카테고리"""
    general = "general"
    competition = "competition"
    schedule = "schedule"
    urgent = "urgent"


# =============================================
# Request Models
# =============================================

class AnnouncementCreate(BaseModel):
    """공지사항 작성 요청"""
    title: str = Field(..., min_length=1, max_length=200, description="제목")
    content: str = Field(..., min_length=1, description="내용")
    category: Optional[AnnouncementCategory] = Field(
        AnnouncementCategory.general, description="카테고리"
    )
    is_pinned: Optional[bool] = Field(False, description="고정 여부")
    target_roles: Optional[List[str]] = Field(
        None, description="대상 역할 (미지정 시 전체)"
    )
    expires_at: Optional[datetime] = Field(None, description="만료일")


class AnnouncementUpdate(BaseModel):
    """공지사항 수정 요청"""
    title: Optional[str] = Field(None, max_length=200, description="제목")
    content: Optional[str] = Field(None, description="내용")
    category: Optional[AnnouncementCategory] = Field(None, description="카테고리")
    is_pinned: Optional[bool] = Field(None, description="고정 여부")
    target_roles: Optional[List[str]] = Field(None, description="대상 역할")
    expires_at: Optional[datetime] = Field(None, description="만료일")


# =============================================
# Response Models
# =============================================

class AnnouncementResponse(BaseModel):
    """공지사항 응답"""
    id: str
    author_id: str
    author_name: Optional[str] = None
    title: str
    content: str
    category: Optional[str] = "general"
    is_pinned: bool = False
    target_roles: Optional[List[str]] = None
    published_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    read_count: int = 0
    is_read: bool = False
    created_at: datetime


class UnreadCountResponse(BaseModel):
    """읽지 않은 공지 수 응답"""
    unread_count: int = 0
