"""
Notification Service - FCM Push + Kakao Alimtalk

구독 등급별 알림톡 한도 관리:
- free: FCM only (알림톡 비활성)
- basic: 500 알림톡/월
- premium: 2000 알림톡/월
- enterprise: 무제한
"""

from datetime import datetime, date
from typing import Optional, List, Tuple
from loguru import logger

from ..database import get_supabase_client
from ..billing.models import TIER_ALIMTALK_LIMITS
from .models import (
    NotificationType,
    NotificationChannel,
    NotificationStatus,
)


class NotificationService:
    """알림 서비스"""

    def __init__(self):
        self._fcm_initialized = False

    @property
    def supabase(self):
        return get_supabase_client()

    # ─────────────────────────────────────────
    # 알림 발송 (통합)
    # ─────────────────────────────────────────

    async def send_notification(
        self,
        org_id: int,
        member_id: str,
        notification_type: str,
        title: str,
        message: str,
        channels: List[str],
        reference_type: Optional[str] = None,
        reference_id: Optional[int] = None,
    ) -> List[dict]:
        """단일 멤버에게 알림 발송"""
        results = []

        for channel in channels:
            record = {
                "org_id": org_id,
                "member_id": member_id,
                "notification_type": notification_type,
                "channel": channel,
                "title": title,
                "message": message,
                "reference_type": reference_type,
                "reference_id": reference_id,
                "status": NotificationStatus.pending.value,
            }

            # DB 기록 생성
            db_result = self.supabase.table("app_notifications").insert(
                record
            ).execute()
            notification = db_result.data[0]
            notification_id = notification["id"]

            # 채널별 발송
            success = False
            error_message = None

            if channel == NotificationChannel.fcm.value:
                success, error_message = await self._send_fcm(member_id, title, message)
            elif channel == NotificationChannel.alimtalk.value:
                success, error_message = await self._send_alimtalk(
                    org_id, member_id, title, message
                )
            elif channel == NotificationChannel.app.value:
                # 앱 내 알림은 DB 기록만으로 충분
                success = True

            # 상태 업데이트
            new_status = NotificationStatus.sent.value if success \
                else NotificationStatus.failed.value

            self.supabase.table("app_notifications").update({
                "status": new_status,
                "sent_at": datetime.now().isoformat() if success else None,
                "error_message": error_message,
            }).eq("id", notification_id).execute()

            notification["status"] = new_status
            results.append(notification)

        return results

    async def send_bulk_notification(
        self,
        org_id: int,
        member_ids: List[str],
        notification_type: str,
        title: str,
        message: str,
        channels: List[str],
        reference_type: Optional[str] = None,
        reference_id: Optional[int] = None,
    ) -> dict:
        """다수 멤버에게 일괄 알림"""
        total = len(member_ids)
        sent = 0
        failed = 0

        for member_id in member_ids:
            try:
                results = await self.send_notification(
                    org_id=org_id,
                    member_id=member_id,
                    notification_type=notification_type,
                    title=title,
                    message=message,
                    channels=channels,
                    reference_type=reference_type,
                    reference_id=reference_id,
                )
                if any(r["status"] == "sent" for r in results):
                    sent += 1
                else:
                    failed += 1
            except Exception as e:
                logger.error(f"알림 발송 실패 (member {member_id}): {e}")
                failed += 1

        return {"total": total, "sent": sent, "failed": failed}

    # ─────────────────────────────────────────
    # FCM Push (무료)
    # ─────────────────────────────────────────

    def _init_firebase(self) -> bool:
        """Firebase Admin SDK 지연 초기화 (최초 발송 시 1회)"""
        if self._fcm_initialized:
            return True

        from ..config import FCM_CREDENTIALS_PATH

        if not FCM_CREDENTIALS_PATH:
            logger.info("FCM_CREDENTIALS_PATH 미설정 - FCM 시뮬레이션 모드")
            return False

        import os
        if not os.path.exists(FCM_CREDENTIALS_PATH):
            logger.warning(f"FCM credentials 파일 없음: {FCM_CREDENTIALS_PATH}")
            return False

        try:
            import firebase_admin
            from firebase_admin import credentials

            if not firebase_admin._apps:
                cred = credentials.Certificate(FCM_CREDENTIALS_PATH)
                firebase_admin.initialize_app(cred)

            self._fcm_initialized = True
            logger.info("Firebase Admin SDK 초기화 완료")
            return True
        except Exception as e:
            logger.error(f"Firebase 초기화 실패: {e}")
            return False

    async def _send_fcm(
        self, member_id: str, title: str, message: str
    ) -> Tuple[bool, Optional[str]]:
        """FCM 푸시 발송"""
        # 멤버의 활성 푸시 토큰 조회
        tokens = self.supabase.table("app_push_tokens").select(
            "token, device_type"
        ).eq("member_id", member_id).eq("is_active", True).execute()

        if not tokens.data:
            return False, "등록된 푸시 토큰 없음"

        firebase_ready = self._init_firebase()

        if not firebase_ready:
            # 개발 모드: credentials 없으면 성공으로 시뮬레이션
            logger.info(f"FCM 시뮬레이션: member {member_id}, {len(tokens.data)} tokens")
            for t in tokens.data:
                self.supabase.table("app_push_tokens").update({
                    "last_used_at": datetime.now().isoformat()
                }).eq("member_id", member_id).eq("token", t["token"]).execute()
            return True, None

        from firebase_admin import messaging
        from firebase_admin.exceptions import NotFoundError

        sent_count = 0
        errors = []

        for token_record in tokens.data:
            try:
                fcm_message = messaging.Message(
                    notification=messaging.Notification(
                        title=title,
                        body=message,
                    ),
                    token=token_record["token"],
                )
                messaging.send(fcm_message)
                sent_count += 1

                # 토큰 사용 시간 업데이트
                self.supabase.table("app_push_tokens").update({
                    "last_used_at": datetime.now().isoformat()
                }).eq("member_id", member_id).eq(
                    "token", token_record["token"]
                ).execute()

            except (messaging.UnregisteredError, NotFoundError):
                # 만료/해제된 토큰 → 자동 비활성화
                logger.warning(
                    f"FCM 토큰 만료, 비활성화: member {member_id}"
                )
                self.supabase.table("app_push_tokens").update({
                    "is_active": False,
                }).eq("member_id", member_id).eq(
                    "token", token_record["token"]
                ).execute()

            except Exception as e:
                logger.error(f"FCM 발송 실패: {e}")
                errors.append(str(e))

        logger.info(
            f"FCM push to member {member_id}: "
            f"{sent_count}/{len(tokens.data)} sent"
        )

        if sent_count > 0:
            return True, None
        return False, "; ".join(errors) if errors else "모든 토큰 만료됨"

    # ─────────────────────────────────────────
    # Kakao Alimtalk (유료, 구독 필요)
    # ─────────────────────────────────────────

    async def _send_alimtalk(
        self, org_id: int, member_id: str, title: str, message: str
    ) -> Tuple[bool, Optional[str]]:
        """카카오 알림톡 발송"""
        # 1. 구독 등급 확인 + 한도 체크
        can_send, error = self._check_alimtalk_quota(org_id)
        if not can_send:
            return False, error

        # 2. 멤버 전화번호 조회
        member_result = self.supabase.table("members").select(
            "phone"
        ).eq("id", member_id).single().execute()

        if not member_result.data or not member_result.data.get("phone"):
            return False, "전화번호 없음"

        phone = member_result.data["phone"]

        # TODO: 비즈메시지 API 연동 (Solapi, NHN Cloud 등)
        # 현재는 한도 차감만 (실제 발송은 API 설정 후)
        #
        # import httpx
        # async with httpx.AsyncClient() as client:
        #     response = await client.post(
        #         "https://api.solapi.com/messages/v4/send",
        #         json={
        #             "message": {
        #                 "to": phone,
        #                 "from": SENDER_PHONE,
        #                 "kakaoOptions": {
        #                     "pfId": KAKAO_CHANNEL_ID,
        #                     "templateId": TEMPLATE_ID,
        #                     "variables": {"title": title, "message": message},
        #                 }
        #             }
        #         },
        #         headers={"Authorization": f"Bearer {API_KEY}"}
        #     )

        logger.info(f"Alimtalk to member {member_id} (phone: {phone[:3]}***)")

        # 3. 사용량 증가
        self._increment_alimtalk_usage(org_id)

        return True, None

    def _check_alimtalk_quota(self, org_id: int) -> Tuple[bool, Optional[str]]:
        """알림톡 한도 확인"""
        sub = self.supabase.table("app_subscriptions").select(
            "tier, alimtalk_limit, alimtalk_used, alimtalk_reset_at, is_active"
        ).eq("org_id", org_id).single().execute()

        if not sub.data or not sub.data.get("is_active"):
            return False, "활성 구독 없음 (알림톡은 유료 구독 필요)"

        tier = sub.data["tier"]
        limit = sub.data["alimtalk_limit"]
        used = sub.data.get("alimtalk_used", 0)

        # 리셋 날짜 확인
        reset_at = sub.data.get("alimtalk_reset_at")
        if reset_at and reset_at <= date.today().isoformat():
            # 월 리셋
            self.supabase.table("app_subscriptions").update({
                "alimtalk_used": 0,
                "alimtalk_reset_at": self._next_reset_date().isoformat(),
            }).eq("org_id", org_id).execute()
            used = 0

        if tier == "free":
            return False, "무료 구독에서는 알림톡 사용 불가"

        if limit != -1 and used >= limit:
            return False, f"알림톡 월 한도 초과 ({used}/{limit})"

        return True, None

    def _increment_alimtalk_usage(self, org_id: int):
        """알림톡 사용량 증가"""
        sub = self.supabase.table("app_subscriptions").select(
            "alimtalk_used"
        ).eq("org_id", org_id).single().execute()

        if sub.data:
            new_count = (sub.data.get("alimtalk_used") or 0) + 1
            self.supabase.table("app_subscriptions").update({
                "alimtalk_used": new_count,
            }).eq("org_id", org_id).execute()

    def _next_reset_date(self) -> date:
        """다음 월 리셋 날짜"""
        today = date.today()
        if today.month == 12:
            return date(today.year + 1, 1, 1)
        return date(today.year, today.month + 1, 1)

    # ─────────────────────────────────────────
    # 푸시 토큰 관리
    # ─────────────────────────────────────────

    def register_push_token(
        self, member_id: str, token: str,
        device_type: str, device_name: Optional[str] = None,
    ) -> dict:
        """FCM 푸시 토큰 등록"""
        # upsert (중복이면 업데이트)
        existing = self.supabase.table("app_push_tokens").select("id").eq(
            "member_id", member_id
        ).eq("token", token).execute()

        if existing.data:
            result = self.supabase.table("app_push_tokens").update({
                "is_active": True,
                "device_type": device_type,
                "device_name": device_name,
                "last_used_at": datetime.now().isoformat(),
            }).eq("id", existing.data[0]["id"]).execute()
        else:
            result = self.supabase.table("app_push_tokens").insert({
                "member_id": member_id,
                "token": token,
                "device_type": device_type,
                "device_name": device_name,
            }).execute()

        return result.data[0]

    def deactivate_push_token(self, member_id: str, token: str) -> bool:
        """푸시 토큰 비활성화"""
        result = self.supabase.table("app_push_tokens").update({
            "is_active": False,
        }).eq("member_id", member_id).eq("token", token).execute()
        return bool(result.data)

    def list_push_tokens(self, member_id: str) -> List[dict]:
        """내 푸시 토큰 목록"""
        result = self.supabase.table("app_push_tokens").select("*").eq(
            "member_id", member_id
        ).eq("is_active", True).execute()
        return result.data or []

    # ─────────────────────────────────────────
    # 알림 조회
    # ─────────────────────────────────────────

    def get_notifications(
        self, member_id: str, limit: int = 20, offset: int = 0,
    ) -> Tuple[List[dict], int, int]:
        """알림 목록 (unread_count 포함)"""
        result = self.supabase.table("app_notifications").select(
            "*", count="exact"
        ).eq("member_id", member_id).order(
            "created_at", desc=True
        ).range(offset, offset + limit - 1).execute()

        # 안 읽은 수
        unread = self.supabase.table("app_notifications").select(
            "id", count="exact"
        ).eq("member_id", member_id).in_(
            "status", ["pending", "sent"]
        ).execute()

        return result.data or [], result.count or 0, unread.count or 0

    def mark_as_read(self, notification_id: int, member_id: str) -> bool:
        """알림 읽음 처리"""
        result = self.supabase.table("app_notifications").update({
            "status": NotificationStatus.read.value,
            "read_at": datetime.now().isoformat(),
        }).eq("id", notification_id).eq("member_id", member_id).execute()
        return bool(result.data)

    def mark_all_as_read(self, member_id: str) -> int:
        """모든 알림 읽음 처리"""
        result = self.supabase.table("app_notifications").update({
            "status": NotificationStatus.read.value,
            "read_at": datetime.now().isoformat(),
        }).eq("member_id", member_id).in_(
            "status", ["pending", "sent"]
        ).execute()
        return len(result.data) if result.data else 0

    # ─────────────────────────────────────────
    # 구독 관리
    # ─────────────────────────────────────────

    def get_subscription(self, org_id: int) -> Optional[dict]:
        """구독 정보 조회"""
        result = self.supabase.table("app_subscriptions").select(
            "*"
        ).eq("org_id", org_id).single().execute()

        if not result.data:
            return None

        sub = result.data
        limit = sub["alimtalk_limit"]
        used = sub.get("alimtalk_used", 0)
        remaining = (limit - used) if limit != -1 else -1

        return {
            **sub,
            "alimtalk_remaining": remaining,
            "fcm_enabled": True,
            "alimtalk_enabled": sub["tier"] != "free" and sub.get("is_active", False),
        }

    def get_notification_stats(self, org_id: int) -> dict:
        """알림 통계"""
        this_month = date.today().strftime("%Y-%m")

        total = self.supabase.table("app_notifications").select(
            "id", count="exact"
        ).eq("org_id", org_id).gte(
            "created_at", f"{this_month}-01T00:00:00"
        ).execute()

        fcm = self.supabase.table("app_notifications").select(
            "id", count="exact"
        ).eq("org_id", org_id).eq("channel", "fcm").eq("status", "sent").gte(
            "created_at", f"{this_month}-01T00:00:00"
        ).execute()

        alimtalk = self.supabase.table("app_notifications").select(
            "id", count="exact"
        ).eq("org_id", org_id).eq("channel", "alimtalk").eq("status", "sent").gte(
            "created_at", f"{this_month}-01T00:00:00"
        ).execute()

        failed = self.supabase.table("app_notifications").select(
            "id", count="exact"
        ).eq("org_id", org_id).eq("status", "failed").gte(
            "created_at", f"{this_month}-01T00:00:00"
        ).execute()

        sub = self.get_subscription(org_id)

        return {
            "total_sent": total.count or 0,
            "fcm_sent": fcm.count or 0,
            "alimtalk_sent": alimtalk.count or 0,
            "alimtalk_limit": sub["alimtalk_limit"] if sub else 0,
            "alimtalk_remaining": sub["alimtalk_remaining"] if sub else 0,
            "failed_count": failed.count or 0,
        }


# 싱글톤
notification_service = NotificationService()
