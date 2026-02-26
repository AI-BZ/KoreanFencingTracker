"""
Videos Service - 영상 코멘트 비즈니스 로직

- YouTube 영상 등록 (oEmbed 메타데이터 자동 추출)
- 영상 목록 조회 (댓글 수 포함)
- 영상 상세 조회 (댓글 + 답글 포함)
- 댓글/답글 CRUD
- 영상 통계
"""

import re
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

import httpx
from loguru import logger

from ..database import get_supabase_client


class VideoService:
    """영상 코멘트 서비스"""

    def __init__(self):
        self._supabase = None

    @property
    def supabase(self):
        if self._supabase is None:
            self._supabase = get_supabase_client()
        return self._supabase

    # =============================================
    # YouTube 유틸리티
    # =============================================

    @staticmethod
    def extract_youtube_id(url: str) -> Optional[str]:
        """YouTube URL에서 video ID 추출"""
        patterns = [
            r"(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([\w-]+)",
            r"(?:https?://)?(?:www\.)?youtube\.com/shorts/([\w-]+)",
            r"(?:https?://)?youtu\.be/([\w-]+)",
            r"(?:https?://)?(?:www\.)?youtube\.com/embed/([\w-]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    async def fetch_youtube_metadata(self, url: str) -> Dict[str, Any]:
        """YouTube oEmbed API로 메타데이터 조회"""
        metadata = {}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://www.youtube.com/oembed",
                    params={"url": url, "format": "json"},
                )
                if response.status_code == 200:
                    data = response.json()
                    metadata["title"] = data.get("title")
                    metadata["thumbnail_url"] = data.get("thumbnail_url")
                    # oEmbed는 duration을 제공하지 않지만 thumbnail은 제공
                    # thumbnail_url에서 고화질 버전으로 변경
                    youtube_id = self.extract_youtube_id(url)
                    if youtube_id:
                        metadata["thumbnail_url"] = f"https://img.youtube.com/vi/{youtube_id}/hqdefault.jpg"
        except Exception as e:
            logger.warning("YouTube 메타데이터 조회 실패: url={}, error={}", url, e)

        return metadata

    # =============================================
    # 영상 CRUD
    # =============================================

    async def create_video(
        self, org_id: int, member_id: str, data: dict
    ) -> dict:
        """영상 등록"""
        youtube_url = data["youtube_url"]
        youtube_id = self.extract_youtube_id(youtube_url)

        # oEmbed로 메타데이터 자동 추출
        metadata = await self.fetch_youtube_metadata(youtube_url)

        insert_data = {
            "organization_id": org_id,
            "member_id": member_id,
            "youtube_url": youtube_url,
            "youtube_id": youtube_id,
            "title": data.get("title") or metadata.get("title") or "제목 없음",
            "description": data.get("description"),
            "category": data.get("category"),
            "thumbnail_url": metadata.get("thumbnail_url"),
            "duration_seconds": data.get("duration_seconds"),
            "is_public": data.get("is_public", True),
        }

        result = self.supabase.table("app_videos").insert(insert_data).execute()

        if not result.data:
            raise Exception("영상 등록 실패")

        video = result.data[0]
        logger.info("영상 등록: id={}, org_id={}, member_id={}", video["id"], org_id, member_id)
        return video

    async def list_videos(
        self,
        org_id: int,
        member_id: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[dict]:
        """영상 목록 조회 (댓글 수 포함)"""
        query = self.supabase.table("app_videos").select(
            "*, members!app_videos_member_id_fkey(full_name)"
        ).eq("organization_id", org_id)

        if member_id:
            query = query.eq("member_id", member_id)

        if category:
            query = query.eq("category", category)

        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        result = query.execute()

        videos = result.data or []

        # 댓글 수 조회
        video_ids = [v["id"] for v in videos]
        if video_ids:
            comments_result = self.supabase.table("app_video_comments").select(
                "video_id"
            ).in_("video_id", video_ids).execute()

            comment_counts: Dict[str, int] = {}
            for c in (comments_result.data or []):
                vid = c["video_id"]
                comment_counts[vid] = comment_counts.get(vid, 0) + 1

            for video in videos:
                member_info = video.pop("members", None) or {}
                video["member_name"] = member_info.get("full_name")
                video["comments_count"] = comment_counts.get(video["id"], 0)
        else:
            for video in videos:
                member_info = video.pop("members", None) or {}
                video["member_name"] = member_info.get("full_name")
                video["comments_count"] = 0

        return videos

    async def get_video(self, video_id: str) -> Optional[dict]:
        """영상 상세 조회 (댓글 포함)"""
        # 영상 조회
        result = self.supabase.table("app_videos").select(
            "*, members!app_videos_member_id_fkey(full_name)"
        ).eq("id", video_id).execute()

        if not result.data:
            return None

        video = result.data[0]
        member_info = video.pop("members", None) or {}
        video["member_name"] = member_info.get("full_name")

        # 댓글 조회 (작성자 이름 포함)
        comments_result = self.supabase.table("app_video_comments").select(
            "*, members!app_video_comments_author_id_fkey(full_name)"
        ).eq("video_id", video_id).order("created_at").execute()

        raw_comments = comments_result.data or []

        # 댓글 트리 구성
        comments_map: Dict[str, dict] = {}
        root_comments: List[dict] = []

        for c in raw_comments:
            member_info = c.pop("members", None) or {}
            c["author_name"] = member_info.get("full_name")
            c["replies"] = []
            comments_map[c["id"]] = c

        for c in raw_comments:
            parent_id = c.get("parent_comment_id")
            if parent_id and parent_id in comments_map:
                comments_map[parent_id]["replies"].append(c)
            else:
                root_comments.append(c)

        video["comments"] = root_comments
        return video

    async def delete_video(
        self, video_id: str, member_id: str, is_coach: bool = False
    ) -> bool:
        """영상 삭제 (본인 또는 코치+)"""
        # 영상 조회
        result = self.supabase.table("app_videos").select(
            "id, member_id"
        ).eq("id", video_id).execute()

        if not result.data:
            return False

        video = result.data[0]

        # 권한 검증: 본인 또는 코치+
        if video["member_id"] != member_id and not is_coach:
            raise PermissionError("영상 삭제 권한이 없습니다")

        # 삭제 (CASCADE로 댓글도 함께 삭제됨)
        self.supabase.table("app_videos").delete().eq("id", video_id).execute()
        logger.info("영상 삭제: id={}, by={}", video_id, member_id)
        return True

    # =============================================
    # 댓글 CRUD
    # =============================================

    async def add_comment(
        self, video_id: str, author_id: str, data: dict
    ) -> dict:
        """댓글 추가"""
        insert_data = {
            "video_id": video_id,
            "author_id": author_id,
            "content": data["content"],
            "timestamp_seconds": data.get("timestamp_seconds"),
            "parent_comment_id": data.get("parent_comment_id"),
        }

        result = self.supabase.table("app_video_comments").insert(insert_data).execute()

        if not result.data:
            raise Exception("댓글 등록 실패")

        comment = result.data[0]

        # 작성자 이름 조회
        member_result = self.supabase.table("members").select(
            "full_name"
        ).eq("id", author_id).execute()

        if member_result.data:
            comment["author_name"] = member_result.data[0].get("full_name")
        else:
            comment["author_name"] = None

        logger.info("댓글 추가: video_id={}, author_id={}", video_id, author_id)
        return comment

    async def delete_comment(
        self, comment_id: str, author_id: str, is_coach: bool = False
    ) -> bool:
        """댓글 삭제 (본인 또는 코치+)"""
        result = self.supabase.table("app_video_comments").select(
            "id, author_id"
        ).eq("id", comment_id).execute()

        if not result.data:
            return False

        comment = result.data[0]

        if comment["author_id"] != author_id and not is_coach:
            raise PermissionError("댓글 삭제 권한이 없습니다")

        self.supabase.table("app_video_comments").delete().eq("id", comment_id).execute()
        logger.info("댓글 삭제: id={}, by={}", comment_id, author_id)
        return True

    # =============================================
    # 통계
    # =============================================

    async def get_video_stats(self, org_id: int) -> dict:
        """영상 통계"""
        # 전체 영상 수
        videos_result = self.supabase.table("app_videos").select(
            "id, category"
        ).eq("organization_id", org_id).execute()

        videos = videos_result.data or []
        total_videos = len(videos)

        # 카테고리별 집계
        by_category: Dict[str, int] = {}
        video_ids = []
        for v in videos:
            cat = v.get("category") or "uncategorized"
            by_category[cat] = by_category.get(cat, 0) + 1
            video_ids.append(v["id"])

        # 전체 댓글 수
        total_comments = 0
        if video_ids:
            comments_result = self.supabase.table("app_video_comments").select(
                "id"
            ).in_("video_id", video_ids).execute()
            total_comments = len(comments_result.data or [])

        return {
            "total_videos": total_videos,
            "total_comments": total_comments,
            "by_category": by_category,
        }


# 싱글톤 인스턴스
video_service = VideoService()
