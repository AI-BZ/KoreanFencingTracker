"""
Settings Service - 클럽 설정 및 회원 승인 비즈니스 로직
"""

from datetime import datetime
from typing import Optional, List
from loguru import logger

from ..database import get_supabase_client
from .models import ApprovalStatus


class SettingsService:
    """클럽 설정 및 회원 승인 서비스"""

    def __init__(self):
        pass

    @property
    def supabase(self):
        return get_supabase_client()

    # ─────────────────────────────────────────
    # 클럽 프로필
    # ─────────────────────────────────────────

    def get_club_profile(self, org_id: int) -> Optional[dict]:
        """클럽 프로필 조회 (organizations + club_settings 조인)"""

        # 1. organizations 테이블 조회
        try:
            org_result = self.supabase.table("organizations").select(
                "*"
            ).eq("id", org_id).maybe_single().execute()
            org = org_result.data if org_result and org_result.data else None
        except Exception:
            # maybe_single() 204 에러 대응
            org_result = self.supabase.table("organizations").select(
                "*"
            ).eq("id", org_id).execute()
            org = org_result.data[0] if org_result and org_result.data else None

        if not org:
            return None

        # 2. club_settings 테이블 조회
        try:
            settings_result = self.supabase.table("club_settings").select(
                "*"
            ).eq("organization_id", org_id).maybe_single().execute()
            settings = settings_result.data if settings_result and settings_result.data else {}
        except Exception:
            settings_result = self.supabase.table("club_settings").select(
                "*"
            ).eq("organization_id", org_id).execute()
            settings = settings_result.data[0] if settings_result and settings_result.data else {}

        # 3. 병합
        return {**org, **settings}

    def update_club_profile(self, org_id: int, data: dict) -> Optional[dict]:
        """클럽 프로필 업데이트 (organizations 테이블)"""
        if not data:
            return self.get_club_profile(org_id)

        result = self.supabase.table("organizations").update(
            data
        ).eq("id", org_id).execute()

        if not result.data:
            return None

        logger.info("클럽 프로필 업데이트: org_id={}, fields={}", org_id, list(data.keys()))
        return self.get_club_profile(org_id)

    # ─────────────────────────────────────────
    # 클럽 설정
    # ─────────────────────────────────────────

    def get_club_settings(self, org_id: int) -> Optional[dict]:
        """클럽 설정 조회"""
        try:
            result = self.supabase.table("club_settings").select("*").eq(
                "organization_id", org_id
            ).maybe_single().execute()
            if not result or not result.data:
                return {"organization_id": org_id}
            return result.data
        except Exception:
            result = self.supabase.table("club_settings").select("*").eq(
                "organization_id", org_id
            ).execute()
            if result and result.data:
                return result.data[0]
            return {"organization_id": org_id}

    def update_club_settings(self, org_id: int, data: dict) -> dict:
        """클럽 설정 업데이트 (upsert)"""
        if not data:
            return self.get_club_settings(org_id)

        # upsert: 없으면 생성, 있으면 업데이트
        upsert_data = {
            "organization_id": org_id,
            **data,
        }

        result = self.supabase.table("club_settings").upsert(
            upsert_data,
            on_conflict="organization_id",
        ).execute()

        if not result.data:
            logger.warning("클럽 설정 upsert 실패: org_id={}", org_id)
            return {"organization_id": org_id}

        logger.info("클럽 설정 업데이트: org_id={}, fields={}", org_id, list(data.keys()))
        return result.data[0]

    # ─────────────────────────────────────────
    # 회원 승인
    # ─────────────────────────────────────────

    def get_pending_members(self, org_id: int) -> List[dict]:
        """승인 대기 회원 목록"""
        result = self.supabase.table("members").select(
            "id, full_name, email, phone, created_at, approval_status"
        ).eq("organization_id", org_id).eq(
            "approval_status", ApprovalStatus.pending.value
        ).order("created_at", desc=True).execute()

        members = []
        for m in (result.data or []):
            members.append({
                "id": m["id"],
                "full_name": m.get("full_name", ""),
                "email": m.get("email"),
                "phone": m.get("phone"),
                "requested_at": m.get("created_at"),
                "approval_status": m.get("approval_status", "pending"),
            })

        return members

    def approve_member(
        self,
        org_id: int,
        approver_id: str,
        member_id: str,
        role: Optional[str] = None,
    ) -> Optional[dict]:
        """회원 승인"""
        update_data = {
            "approval_status": ApprovalStatus.approved.value,
            "approved_by": approver_id,
            "approved_at": datetime.now().isoformat(),
            "member_status": "active",
        }

        if role:
            update_data["club_role"] = role

        result = self.supabase.table("members").update(
            update_data
        ).eq("id", member_id).eq("organization_id", org_id).eq(
            "approval_status", ApprovalStatus.pending.value
        ).execute()

        if not result.data:
            return None

        logger.info(
            "회원 승인: member_id={}, approver={}, role={}",
            member_id, approver_id, role,
        )
        return result.data[0]

    def reject_member(
        self,
        org_id: int,
        approver_id: str,
        member_id: str,
        reason: Optional[str] = None,
    ) -> Optional[dict]:
        """회원 거절"""
        update_data = {
            "approval_status": ApprovalStatus.rejected.value,
            "approved_by": approver_id,
            "approved_at": datetime.now().isoformat(),
            "rejection_reason": reason,
        }

        result = self.supabase.table("members").update(
            update_data
        ).eq("id", member_id).eq("organization_id", org_id).eq(
            "approval_status", ApprovalStatus.pending.value
        ).execute()

        if not result.data:
            return None

        logger.info(
            "회원 거절: member_id={}, approver={}, reason={}",
            member_id, approver_id, reason,
        )
        return result.data[0]

    def request_membership(self, org_id: int, member_data: dict) -> Optional[dict]:
        """회원 가입 신청 (approval_status='pending')"""
        insert_data = {
            "organization_id": org_id,
            "full_name": member_data["full_name"],
            "email": member_data["email"],
            "phone": member_data.get("phone"),
            "approval_status": ApprovalStatus.pending.value,
            "member_status": "inactive",
            "club_role": "student",
        }

        result = self.supabase.table("members").insert(insert_data).execute()

        if not result.data:
            return None

        logger.info(
            "회원 가입 신청: org_id={}, name={}, email={}",
            org_id, member_data["full_name"], member_data["email"],
        )
        return result.data[0]

    # ─────────────────────────────────────────
    # 회원 통계
    # ─────────────────────────────────────────

    def get_member_stats(self, org_id: int) -> dict:
        """회원 통계 (역할별, 상태별, 월별)"""
        result = self.supabase.table("members").select(
            "id, club_role, member_status, approval_status, created_at, full_name"
        ).eq("organization_id", org_id).execute()

        members = result.data or []

        # 전체 카운트
        total = len(members)
        active = len([m for m in members if m.get("member_status") in ("active", None)])
        inactive = len([m for m in members if m.get("member_status") == "inactive"])
        pending = len([m for m in members if m.get("approval_status") == "pending"])

        # 역할별 카운트
        by_role = {}
        for m in members:
            role = m.get("club_role", "student")
            by_role[role] = by_role.get(role, 0) + 1

        # 상태별 카운트
        by_status = {}
        for m in members:
            status = m.get("member_status", "active")
            by_status[status] = by_status.get(status, 0) + 1

        # 최근 가입 (최근 10명)
        sorted_members = sorted(
            members,
            key=lambda x: x.get("created_at", ""),
            reverse=True,
        )
        recent_joins = [
            {
                "id": m["id"],
                "full_name": m.get("full_name", ""),
                "club_role": m.get("club_role", "student"),
                "created_at": m.get("created_at"),
            }
            for m in sorted_members[:10]
        ]

        return {
            "total_members": total,
            "active_members": active,
            "inactive_members": inactive,
            "pending_members": pending,
            "by_role": by_role,
            "by_status": by_status,
            "recent_joins": recent_joins,
        }


# 싱글톤
settings_service = SettingsService()
