"""NotificationDispatcher — 단일 data_events 행을 알림으로 변환/발송.

흐름:
    1. event_type → 카테고리 매핑 (없으면 skip)
    2. 대상 회원 결정 (_resolve_targets)
    3. 회원별 알림 설정 확인 (notifications.service.get_member_preference)
    4. 채널별 발송:
       - in_app  : notifications 테이블 insert + app_notification_log 기록 (Phase 3 활성)
       - web_push: FCM/표준 웹 푸시 발송 (Phase 4 활성 — pywebpush + VAPID)
       - kakao   : 카카오 알림톡 — 현재 계획 보류(hidden). 코드 보존, ENABLE_KAKAO_ALIMTALK로 게이트
                   자격증명/템플릿 미설정 시 graceful no-op('pending' 로그).

멱등성: app_notification_log(event_type, event_id, member_id, channel) 존재 시 재발송 안 함
(폴러 재시작 시 중복 알림 방지).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from shared_core.db.client import get_supabase_client

from ..config import settings
from ..notifications import service as prefs
from . import event_types as et

logger = logging.getLogger("app.pipeline.dispatcher")

# VAPID 클레임 subject (RFC 8292) — 연락 가능한 mailto/https.
_VAPID_SUBJECT = "mailto:privacy@fencingmind.ai"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_unique_violation(exc: Exception) -> bool:
    """예외가 UNIQUE 제약 위반(중복 INSERT)인지 판별.

    supabase-py/PostgREST는 구체 예외 타입이 환경마다 달라 문자열로 판별한다.
    PostgreSQL unique_violation SQLSTATE는 23505.
    """
    text = str(exc).lower()
    return "23505" in text or "unique" in text or "duplicate" in text


class NotificationDispatcher:
    def __init__(self, supabase: Any = None):
        self._db = supabase

    @property
    def db(self) -> Any:
        if self._db is None:
            self._db = get_supabase_client()
        return self._db

    # ----------------------------------------------------------------- public

    def dispatch(self, event: dict) -> dict:
        """data_events 한 행을 처리. 요약 dict 반환."""
        event_id = event.get("id")
        event_type = event.get("event_type", "")
        category = et.category_for_event(event_type)

        summary = {"event_id": event_id, "category": category, "targets": 0, "in_app": 0, "web_push": 0}
        if not category:
            return summary

        try:
            member_ids = self._resolve_targets(event, category)
        except Exception as exc:  # noqa: BLE001 - 폴러를 죽이지 않도록 방어
            logger.warning("대상 해석 실패 event=%s type=%s: %s", event_id, event_type, exc)
            summary["error"] = "resolve_failed"
            return summary

        if not member_ids:
            return summary

        title, body, link = et.build_message(event)
        summary["targets"] = len(member_ids)

        for member_id in member_ids:
            try:
                pref = prefs.get_member_preference(member_id, category, self.db)
            except Exception as exc:  # noqa: BLE001
                logger.warning("설정 조회 실패 member=%s: %s", member_id, exc)
                continue

            if pref.get("in_app"):
                if self._send_in_app(member_id, category, title, body, link, event):
                    summary["in_app"] += 1
            if pref.get("web_push"):
                if self._send_web_push(member_id, event):
                    summary["web_push"] += 1
            # 카카오 알림톡은 현재 계획에서 보류 — ENABLE_KAKAO_ALIMTALK(기본 False)로 게이트.
            # 코드(_send_kakao, kakao.py)는 재활성화 대비 보존. 플래그를 켜면 다시 동작.
            if settings.ENABLE_KAKAO_ALIMTALK and pref.get("kakao_alimtalk"):
                self._send_kakao(member_id, event)

        return summary

    # ----------------------------------------------------- target resolution

    def _resolve_targets(self, event: dict, category: str) -> list[str]:
        """카테고리별 대상 회원 id 목록."""
        data = event.get("data") or {}

        if category == et.CATEGORY_RANKING_CHANGE:
            player_id = data.get("player_id")
            if player_id is None and event.get("entity_type") == "player":
                player_id = event.get("entity_id")
            if player_id is None:
                return []
            res = self.db.table("members").select("id").eq("player_id", player_id).execute()
            return [r["id"] for r in (res.data or [])]

        if category == et.CATEGORY_COMPETITION_RESULT:
            player_ids = self._players_for_result(event)
            if not player_ids:
                return []
            res = (
                self.db.table("members")
                .select("id")
                .in_("player_id", list(player_ids))
                .execute()
            )
            return [r["id"] for r in (res.data or [])]

        return []

    def _players_for_result(self, event: dict) -> set[int]:
        """대회/종목 결과 이벤트 → 참가 선수 player_id 집합 (rankings 기준)."""
        event_type = event.get("event_type", "")
        entity_id = event.get("entity_id")
        if entity_id is None:
            return set()

        event_ids: list[int] = []
        if event_type.startswith("event."):
            event_ids = [entity_id]
        elif event_type.startswith("competition."):
            evs = self.db.table("events").select("id").eq("competition_id", entity_id).execute()
            event_ids = [e["id"] for e in (evs.data or []) if e.get("id") is not None]

        if not event_ids:
            return set()

        rk = self.db.table("rankings").select("player_id").in_("event_id", event_ids).execute()
        return {r["player_id"] for r in (rk.data or []) if r.get("player_id") is not None}

    # ------------------------------------------------------------- channels

    def _send_in_app(
        self,
        member_id: str,
        category: str,
        title: str,
        body: str,
        link: Optional[str],
        event: dict,
    ) -> bool:
        """notifications 테이블에 인앱 알림 생성. 중복이면 False."""
        if self._already_sent(member_id, "in_app", event):
            return False
        try:
            ins = (
                self.db.table("notifications")
                .insert(
                    {
                        "recipient_id": member_id,
                        "title": title,
                        "body": body,
                        "notification_type": category,
                        "link_url": link,
                        "metadata": {
                            "source": "app_pipeline",
                            "event_type": event.get("event_type"),
                            "event_id": event.get("id"),
                        },
                    }
                )
                .execute()
            )
            notif_id = ins.data[0]["id"] if ins.data else None
            self._log(member_id, "in_app", "sent", event, notification_id=notif_id)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("인앱 알림 발송 실패 member=%s: %s", member_id, exc)
            self._log(member_id, "in_app", "failed", event, error=str(exc))
            return False

    def _send_web_push(self, member_id: str, event: dict) -> bool:
        """웹 푸시 발송 (FCM은 표준 Web Push 위에서 동작 → pywebpush 사용).

        graceful degradation:
          - VAPID 비밀키 미설정 / pywebpush 미설치 → 크래시 없이 'pending' 로그 후 종료.
          - 만료 구독(404/410) → 해당 구독 is_active=false.
          - 발송 성공 → app_notification_log status='sent'.
        멱등성: app_notification_log(channel='web_push') 존재 시 재발송 안 함.

        Returns:
            이번 호출에서 1건 이상 실제 발송했으면 True, 그 외(중복/미설정/구독 없음/실패)는 False.
            메트릭(dispatched) 집계용 신호이며 발송 로직 자체에는 영향을 주지 않는다.
        """
        if self._already_sent(member_id, "web_push", event):
            return False

        # 1) VAPID 비밀키 확인 (없으면 발송 불가 → pending 로그)
        private_key = settings.FCM_VAPID_PRIVATE_KEY
        if not private_key:
            logger.info("web_push skip member=%s: VAPID key 미설정", member_id)
            self._log(member_id, "web_push", "pending", event, error="VAPID key 미설정")
            return False

        # 2) pywebpush 지연 import (미설치여도 모듈 import는 깨지지 않음)
        try:
            from pywebpush import WebPushException, webpush  # type: ignore
        except Exception as exc:  # noqa: BLE001 - ImportError 등
            logger.warning("web_push skip member=%s: pywebpush 미설치 (%s)", member_id, exc)
            self._log(member_id, "web_push", "pending", event, error="pywebpush 미설치")
            return False

        # 3) 활성 구독 조회
        try:
            res = (
                self.db.table("app_push_subscriptions")
                .select("id, fcm_endpoint, fcm_p256dh, fcm_auth")
                .eq("member_id", member_id)
                .eq("is_active", True)
                .execute()
            )
            subscriptions = res.data or []
        except Exception as exc:  # noqa: BLE001
            logger.error("구독 조회 실패 member=%s: %s", member_id, exc)
            self._log(member_id, "web_push", "failed", event, error=str(exc))
            return False

        if not subscriptions:
            logger.debug("web_push: 활성 구독 없음 member=%s", member_id)
            return False

        title, body, link = et.build_message(event)
        payload = json.dumps(
            {
                "title": title,
                "body": body,
                "url": link or "/",
                "tag": f"{event.get('event_type', 'fencingmind')}:{event.get('id', '')}",
            }
        )

        sent_any = False
        last_error: Optional[str] = None
        for sub in subscriptions:
            endpoint = sub.get("fcm_endpoint")
            p256dh = sub.get("fcm_p256dh")
            auth = sub.get("fcm_auth")
            if not (endpoint and p256dh and auth):
                continue

            subscription_info = {
                "endpoint": endpoint,
                "keys": {"p256dh": p256dh, "auth": auth},
            }
            try:
                webpush(
                    subscription_info=subscription_info,
                    data=payload,
                    vapid_private_key=private_key,
                    vapid_claims={"sub": _VAPID_SUBJECT},
                )
                sent_any = True
            except WebPushException as exc:  # noqa: PERF203
                status = getattr(getattr(exc, "response", None), "status_code", None)
                last_error = f"webpush {status}: {exc}"
                if status in (404, 410):
                    # 만료/폐기된 구독 → 비활성화
                    self._deactivate_subscription(sub.get("id"))
                    logger.info("만료 구독 비활성화 member=%s sub=%s", member_id, sub.get("id"))
                else:
                    logger.warning("web_push 발송 실패 member=%s: %s", member_id, exc)
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                logger.error("web_push 예외 member=%s: %s", member_id, exc)

        if sent_any:
            self._log(member_id, "web_push", "sent", event)
        else:
            self._log(member_id, "web_push", "failed", event, error=last_error or "발송 대상 없음")
        return sent_any

    def _deactivate_subscription(self, sub_id: Optional[str]) -> None:
        if not sub_id:
            return
        try:
            self.db.table("app_push_subscriptions").update({"is_active": False}).eq(
                "id", sub_id
            ).execute()
        except Exception as exc:  # noqa: BLE001
            logger.warning("구독 비활성화 실패 sub=%s: %s", sub_id, exc)

    def _send_kakao(self, member_id: str, event: dict) -> None:
        """카카오 알림톡 발송 (Phase 6).

        graceful degradation:
          - 자격증명/템플릿 미설정 → KakaoAlimtalkSender가 not_configured 반환
            → 'pending' 로그 후 종료 (폴러 안 죽음).
          - 수신 전화번호 없음 → 'pending' 로그(error '전화번호 없음') 후 종료.
          - httpx 미설치 → sender가 'pending' 반환.
        멱등성: app_notification_log(channel='kakao_alimtalk') 존재 시 재발송 안 함.
        """
        if self._already_sent(member_id, "kakao_alimtalk", event):
            return

        # 1) 수신 전화번호 해석 (members.phone / phone_country_code / contact_phone)
        try:
            res = (
                self.db.table("members")
                .select("phone, phone_country_code, contact_phone")
                .eq("id", member_id)
                .limit(1)
                .execute()
            )
            member_row = (res.data or [None])[0]
        except Exception as exc:  # noqa: BLE001
            logger.error("kakao 수신번호 조회 실패 member=%s: %s", member_id, exc)
            self._log(member_id, "kakao_alimtalk", "failed", event, error=str(exc))
            return

        from .kakao import KakaoAlimtalkSender, build_recipient_phone

        phone = build_recipient_phone(member_row or {})
        if not phone:
            logger.info("kakao skip member=%s: 전화번호 없음", member_id)
            self._log(member_id, "kakao_alimtalk", "pending", event, error="전화번호 없음")
            return

        # 2) 발송 (sender는 절대 예외를 던지지 않음)
        sender = KakaoAlimtalkSender()
        result = sender.send(to_phone=phone, event=event)
        status = result.get("status")
        error = result.get("error")

        # 3) 결과 → 로그 상태 매핑
        #    not_configured(자격증명/템플릿 없음)은 pending으로 기록 (향후 재시도 가능 상태).
        if status == "sent":
            self._log(member_id, "kakao_alimtalk", "sent", event)
        elif status in ("pending", "not_configured"):
            self._log(member_id, "kakao_alimtalk", "pending", event, error=error)
        else:  # 'failed' 또는 알 수 없는 값
            self._log(member_id, "kakao_alimtalk", "failed", event, error=error or "알 수 없는 오류")

    # ------------------------------------------------------------- logging

    def _already_sent(self, member_id: str, channel: str, event: dict) -> bool:
        event_id = event.get("id")
        if event_id is None:
            return False
        try:
            res = (
                self.db.table("app_notification_log")
                .select("id")
                .eq("member_id", member_id)
                .eq("channel", channel)
                .eq("event_type", event.get("event_type", ""))
                .eq("event_id", event_id)
                .limit(1)
                .execute()
            )
            return bool(res.data)
        except Exception as exc:  # noqa: BLE001
            logger.warning("중복 확인 실패 member=%s: %s", member_id, exc)
            return False

    def _log(
        self,
        member_id: str,
        channel: str,
        status: str,
        event: dict,
        notification_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        try:
            self.db.table("app_notification_log").insert(
                {
                    "notification_id": notification_id,
                    "member_id": member_id,
                    "channel": channel,
                    "status": status,
                    "error_message": error,
                    "event_type": event.get("event_type", ""),
                    "event_id": event.get("id"),
                    "sent_at": _now_iso() if status == "sent" else None,
                }
            ).execute()
        except Exception as exc:  # noqa: BLE001
            # UNIQUE 제약(uq_app_notif_log_member_channel_event) 위반은 다른 워커가
            # 먼저 같은 (member, channel, event_type, event_id) 로그를 INSERT했다는 뜻 →
            # 중복 발송이 DB에서 차단된 정상 동작이므로 debug로만 남긴다.
            if _is_unique_violation(exc):
                logger.debug(
                    "중복 로그 스킵 (UNIQUE 위반) member=%s channel=%s", member_id, channel
                )
            else:
                logger.warning(
                    "로그 기록 실패 member=%s channel=%s: %s", member_id, channel, exc
                )
