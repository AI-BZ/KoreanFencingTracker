"""NotificationDispatcher — 단일 data_events 행을 알림으로 변환/발송.

흐름:
    1. event_type → 카테고리 매핑 (없으면 skip)
    2. 대상 회원 결정 (_resolve_targets)
    3. 회원별 알림 설정 확인 (notifications.service.get_member_preference)
    4. 채널별 발송:
       - in_app  : notifications 테이블 insert + app_notification_log 기록 (Phase 3 활성)
       - web_push: Phase 4 (현재 no-op)
       - kakao   : Phase 6 (현재 no-op)

멱등성: app_notification_log(event_type, event_id, member_id, channel) 존재 시 재발송 안 함
(폴러 재시작 시 중복 알림 방지).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from shared_core.db.client import get_supabase_client

from ..notifications import service as prefs
from . import event_types as et

logger = logging.getLogger("app.pipeline.dispatcher")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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

        summary = {"event_id": event_id, "category": category, "targets": 0, "in_app": 0}
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
                self._send_web_push(member_id, event)
            if pref.get("kakao_alimtalk"):
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

    def _send_web_push(self, member_id: str, event: dict) -> None:
        """웹 푸시 발송 — Phase 4(FCM)에서 구현. 현재 no-op."""
        logger.debug("web_push deferred to Phase 4 (member=%s event=%s)", member_id, event.get("id"))

    def _send_kakao(self, member_id: str, event: dict) -> None:
        """카카오 알림톡 발송 — Phase 6에서 구현. 현재 no-op."""
        logger.debug("kakao deferred to Phase 6 (member=%s event=%s)", member_id, event.get("id"))

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
            logger.warning("로그 기록 실패 member=%s channel=%s: %s", member_id, channel, exc)
