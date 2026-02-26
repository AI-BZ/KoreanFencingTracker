"""
Announcements Service - 공지사항 비즈니스 로직

- 공지사항 CRUD (작성자/관리자 권한)
- 대상 역할별 필터링
- 읽음 추적 (read_by UUID 배열)
- 고정 공지 + 만료일 관리
"""

from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from loguru import logger

from ..database import get_supabase_client


class AnnouncementService:
    """공지사항 서비스"""

    def __init__(self):
        self._supabase = None

    @property
    def supabase(self):
        if self._supabase is None:
            self._supabase = get_supabase_client()
        return self._supabase

    # =============================================
    # 공지사항 CRUD
    # =============================================

    async def create_announcement(
        self, org_id: int, author_id: str, data: dict
    ) -> dict:
        """공지사항 작성"""
        now = datetime.now(timezone.utc).isoformat()

        insert_data = {
            "organization_id": org_id,
            "author_id": author_id,
            "title": data["title"],
            "content": data["content"],
            "category": data.get("category", "general"),
            "is_pinned": data.get("is_pinned", False),
            "target_roles": data.get("target_roles"),
            "published_at": now,
            "expires_at": data.get("expires_at"),
            "read_by": [],
        }

        result = self.supabase.table("app_announcements").insert(insert_data).execute()

        if not result.data:
            raise Exception("공지사항 작성 실패")

        announcement = result.data[0]

        # 작성자 이름 조회
        author_name = self._get_member_name(author_id)
        announcement["author_name"] = author_name
        announcement["read_count"] = 0
        announcement["is_read"] = False

        logger.info("공지사항 작성: id={}, org_id={}, author={}", announcement["id"], org_id, author_id)
        return announcement

    async def list_announcements(
        self,
        org_id: int,
        member_id: Optional[str] = None,
        category: Optional[str] = None,
        include_expired: bool = False,
        limit: int = 20,
        offset: int = 0,
    ) -> List[dict]:
        """공지사항 목록 조회"""
        query = self.supabase.table("app_announcements").select(
            "*, members!app_announcements_author_id_fkey(full_name)"
        ).eq("organization_id", org_id)

        if category:
            query = query.eq("category", category)

        if not include_expired:
            now = datetime.now(timezone.utc).isoformat()
            # expires_at이 null이거나 미래인 것만
            query = query.or_(f"expires_at.is.null,expires_at.gte.{now}")

        # 고정 공지 먼저, 그 다음 최신순
        query = query.order("is_pinned", desc=True).order("created_at", desc=True)
        query = query.range(offset, offset + limit - 1)

        result = query.execute()
        announcements = result.data or []

        for ann in announcements:
            member_info = ann.pop("members", None) or {}
            ann["author_name"] = member_info.get("full_name")

            read_by = ann.get("read_by") or []
            ann["read_count"] = len(read_by)
            ann["is_read"] = member_id in read_by if member_id else False

        return announcements

    async def get_announcement(
        self, announcement_id: str, member_id: Optional[str] = None
    ) -> Optional[dict]:
        """공지사항 상세 조회 + 읽음 처리"""
        result = self.supabase.table("app_announcements").select(
            "*, members!app_announcements_author_id_fkey(full_name)"
        ).eq("id", announcement_id).execute()

        if not result.data:
            return None

        announcement = result.data[0]
        member_info = announcement.pop("members", None) or {}
        announcement["author_name"] = member_info.get("full_name")

        read_by = announcement.get("read_by") or []
        announcement["read_count"] = len(read_by)
        announcement["is_read"] = member_id in read_by if member_id else False

        # 읽음 처리
        if member_id and member_id not in read_by:
            await self.mark_as_read(announcement_id, member_id)
            announcement["is_read"] = True
            announcement["read_count"] += 1

        return announcement

    async def update_announcement(
        self, announcement_id: str, author_id: str, data: dict, is_admin: bool = False
    ) -> Optional[dict]:
        """공지사항 수정 (작성자 또는 관리자)"""
        # 기존 공지 조회
        existing = self.supabase.table("app_announcements").select(
            "id, author_id"
        ).eq("id", announcement_id).execute()

        if not existing.data:
            return None

        ann = existing.data[0]

        # 권한 검증
        if ann["author_id"] != author_id and not is_admin:
            raise PermissionError("공지사항 수정 권한이 없습니다")

        # None이 아닌 필드만 업데이트
        update_data = {k: v for k, v in data.items() if v is not None}
        if not update_data:
            return await self.get_announcement(announcement_id)

        result = self.supabase.table("app_announcements").update(
            update_data
        ).eq("id", announcement_id).execute()

        if not result.data:
            return None

        return await self.get_announcement(announcement_id)

    async def delete_announcement(
        self, announcement_id: str, author_id: str, is_admin: bool = False
    ) -> bool:
        """공지사항 삭제 (작성자 또는 관리자)"""
        existing = self.supabase.table("app_announcements").select(
            "id, author_id"
        ).eq("id", announcement_id).execute()

        if not existing.data:
            return False

        ann = existing.data[0]

        if ann["author_id"] != author_id and not is_admin:
            raise PermissionError("공지사항 삭제 권한이 없습니다")

        self.supabase.table("app_announcements").delete().eq("id", announcement_id).execute()
        logger.info("공지사항 삭제: id={}, by={}", announcement_id, author_id)
        return True

    # =============================================
    # 읽음 추적
    # =============================================

    async def mark_as_read(self, announcement_id: str, member_id: str) -> bool:
        """읽음 처리 (read_by 배열에 member_id 추가)"""
        try:
            # 현재 read_by 조회
            result = self.supabase.table("app_announcements").select(
                "read_by"
            ).eq("id", announcement_id).execute()

            if not result.data:
                return False

            read_by = result.data[0].get("read_by") or []

            if member_id not in read_by:
                read_by.append(member_id)
                self.supabase.table("app_announcements").update(
                    {"read_by": read_by}
                ).eq("id", announcement_id).execute()

            return True
        except Exception as e:
            logger.error("읽음 처리 실패: id={}, member={}, error={}", announcement_id, member_id, e)
            return False

    async def get_unread_count(self, org_id: int, member_id: str) -> int:
        """읽지 않은 공지 수"""
        try:
            now = datetime.now(timezone.utc).isoformat()

            # 만료되지 않은 전체 공지 조회
            result = self.supabase.table("app_announcements").select(
                "id, read_by"
            ).eq(
                "organization_id", org_id
            ).or_(
                f"expires_at.is.null,expires_at.gte.{now}"
            ).execute()

            announcements = result.data or []
            unread = 0
            for ann in announcements:
                read_by = ann.get("read_by") or []
                if member_id not in read_by:
                    unread += 1

            return unread
        except Exception as e:
            logger.error("읽지 않은 공지 수 조회 실패: org_id={}, member={}, error={}", org_id, member_id, e)
            return 0

    # =============================================
    # 헬퍼
    # =============================================

    def _get_member_name(self, member_id: str) -> Optional[str]:
        """회원 이름 조회"""
        try:
            result = self.supabase.table("members").select(
                "full_name"
            ).eq("id", member_id).execute()

            if result.data:
                return result.data[0].get("full_name")
            return None
        except Exception:
            return None


# 싱글톤 인스턴스
announcement_service = AnnouncementService()
