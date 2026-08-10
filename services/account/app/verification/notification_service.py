"""
Verification Notification Service - 인증 이벤트 알림 자동화

모든 인증 요청(이미지 인증, 선수 Claim, 학부모 Claim, 조직 Claim) 제출 시
관리자에게 알림을 보내고, 승인/거부 시 사용자에게 알림을 보냄.
"""
import json
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from shared_core.db.client import get_supabase_client
from shared_core.email import EmailService
from ..config import get_account_settings


class VerificationNotificationService:
    """인증 관련 알림 서비스"""

    def __init__(self):
        self.settings = get_account_settings()

    async def notify_admin_new_request(
        self,
        request_type: str,
        item_id: str,
        summary: str,
        member_name: Optional[str] = None,
    ) -> None:
        """
        새 인증 요청 시 모든 관리자에게 알림

        Args:
            request_type: verification / player_claim / parent_claim / org_claim
            item_id: 해당 레코드 ID
            summary: 알림 요약 (예: "김철수 - 학부모 인증 요청")
            member_name: 요청한 회원 이름
        """
        supabase = get_supabase_client()

        # Find all admins
        try:
            admin_result = supabase.table("members").select("id, email, full_name").not_(
                "admin_role", "is", "null"
            ).execute()
            admins = admin_result.data or []
        except Exception as e:
            logger.error(f"Admin lookup failed: {e}")
            return

        if not admins:
            logger.warning("No admins found for notification")
            return

        type_labels = {
            "verification": "본인인증",
            "player_claim": "선수 Claim",
            "parent_claim": "학부모 인증",
            "org_claim": "조직 Claim",
        }
        type_label = type_labels.get(request_type, request_type)

        title = f"[새 {type_label} 요청] {member_name or '회원'}"
        body = summary
        link_url = f"/account/admin/approvals?type={request_type}"
        now = datetime.now(timezone.utc).isoformat()

        # Create notifications for each admin
        notifications = []
        for admin in admins:
            notifications.append({
                "recipient_id": admin["id"],
                "title": title,
                "body": body,
                "notification_type": f"new_{request_type}",
                "link_url": link_url,
                "metadata": json.dumps({
                    "request_type": request_type,
                    "item_id": item_id,
                }, ensure_ascii=False),
                "is_read": False,
            })

        if notifications:
            try:
                supabase.table("notifications").insert(notifications).execute()
                logger.info(f"Admin notifications sent: {len(notifications)} for {request_type}/{item_id}")
            except Exception as e:
                logger.error(f"Failed to create admin notifications: {e}")

        # Send email to admins (best-effort)
        if self.settings.RESEND_API_KEY:
            for admin in admins:
                admin_email = admin.get("email")
                if admin_email:
                    await self._send_admin_email(
                        to=admin_email,
                        admin_name=admin.get("full_name", "관리자"),
                        type_label=type_label,
                        member_name=member_name or "회원",
                        summary=summary,
                    )

    async def notify_member_status_change(
        self,
        member_id: str,
        request_type: str,
        status: str,
        details: Optional[str] = None,
    ) -> None:
        """
        인증 상태 변경 시 해당 사용자에게 알림

        Args:
            member_id: 알림 받을 회원 ID
            request_type: verification / player_claim / parent_claim / org_claim
            status: approved / rejected
            details: 추가 메시지 (거부 사유 등)
        """
        supabase = get_supabase_client()

        type_labels = {
            "verification": "본인인증",
            "player_claim": "선수 Claim",
            "parent_claim": "학부모 인증",
            "org_claim": "조직 Claim",
        }
        type_label = type_labels.get(request_type, request_type)

        status_labels = {
            "approved": "승인",
            "rejected": "거부",
        }
        status_label = status_labels.get(status, status)

        title = f"[{type_label}] {status_label}되었습니다"

        if status == "approved":
            body = f"{type_label}이 승인되었습니다. 축하합니다!"
        elif status == "rejected":
            body = f"{type_label}이 거부되었습니다."
            if details:
                body += f" 사유: {details}"
        else:
            body = f"{type_label} 상태가 '{status}'(으)로 변경되었습니다."

        try:
            supabase.table("notifications").insert({
                "recipient_id": member_id,
                "title": title,
                "body": body,
                "notification_type": f"{request_type}_{status}",
                "metadata": json.dumps({
                    "request_type": request_type,
                    "status": status,
                }, ensure_ascii=False),
                "is_read": False,
            }).execute()
            logger.info(f"Member notification sent: {member_id} for {request_type}/{status}")
        except Exception as e:
            logger.error(f"Failed to create member notification: {e}")

    async def _send_admin_email(
        self,
        to: str,
        admin_name: str,
        type_label: str,
        member_name: str,
        summary: str,
    ) -> None:
        """관리자에게 이메일 알림 (best-effort)"""
        try:
            email_service = EmailService(api_key=self.settings.RESEND_API_KEY)
            body_text = (
                f"{admin_name}님, 새 인증 요청이 접수되었습니다.\n\n"
                f"유형: {type_label}\n"
                f"요청자: {member_name}\n"
                f"요약: {summary}\n\n"
                f"승인 큐: https://account.fencingmind.ai/account/admin/approvals"
            )
            await email_service.send_admin_email(
                to=to,
                recipient_name=admin_name,
                subject=f"[FencingMind] 새 {type_label} 요청: {member_name}",
                body=body_text,
            )
        except Exception as e:
            logger.debug(f"Admin email send failed (non-critical): {e}")
