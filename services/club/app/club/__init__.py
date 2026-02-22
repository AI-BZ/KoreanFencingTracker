"""
Club Management Module

펜싱 클럽/학교 회원 관리 SaaS 시스템
- 선수 데이터 연동 (대회 히스토리, 랭킹, 상대전적) - 핵심 기능!
- 회원 관리, 출결, 레슨, 비용, 대회 참가 관리
"""

from .router import router as club_router
from .models import (
    ClubRole,
    MemberStatus,
    AttendanceType,
    CheckinMethod,
    FeeType,
    FeeStatus
)
from .dependencies import ClubMemberContext

__all__ = [
    "club_router",
    "ClubRole",
    "MemberStatus",
    "AttendanceType",
    "CheckinMethod",
    "FeeType",
    "FeeStatus",
    "ClubMemberContext"
]
