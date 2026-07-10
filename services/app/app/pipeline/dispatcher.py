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

재정정 스팸 억제(EVAL P1-4): 멱등키는 data_events.id(행 id) 기준이라, 결과를 재스크래핑/
정정하면 새 event_id가 생겨 멱등성 검사를 통과 → 전원 재발송(스팸)된다. dedup_key
("{category}:{entity_type}:{entity_id}")로 "같은 논리 엔티티"를 묶어, 최초 발송에 한해
쿨다운(NOTIFY_DEDUP_COOLDOWN_HOURS) 이내 재알림을 회원별·채널별로 억제한다. 재시도 스윕
(retry_failed)은 이 게이트를 타지 않는다(채널 코어를 직접 호출 → 복구 경로).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
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

        # 재정정 스팸 억제 키 (EVAL P1-4): event_id가 아니라 논리 엔티티 기준.
        # entity_type/entity_id가 불완전하면 None → 억제하지 않고 정상 발송.
        dedup_key = self._dedup_key(category, event)

        for member_id in member_ids:
            try:
                pref = prefs.get_member_preference(member_id, category, self.db)
            except Exception as exc:  # noqa: BLE001
                logger.warning("설정 조회 실패 member=%s: %s", member_id, exc)
                continue

            if pref.get("in_app"):
                if self._send_in_app(member_id, category, title, body, link, event, dedup_key):
                    summary["in_app"] += 1
            if pref.get("web_push"):
                if self._send_web_push(member_id, event, dedup_key):
                    summary["web_push"] += 1
            # 카카오 알림톡은 현재 계획에서 보류 — ENABLE_KAKAO_ALIMTALK(기본 False)로 게이트.
            # 코드(_send_kakao, kakao.py)는 재활성화 대비 보존. 플래그를 켜면 다시 동작.
            if settings.ENABLE_KAKAO_ALIMTALK and pref.get("kakao_alimtalk"):
                self._send_kakao(member_id, event)

        return summary

    # ----------------------------------------------------- dedup (P1-4)

    @staticmethod
    def _dedup_key(category: str, event: dict) -> Optional[str]:
        """재정정 스팸 억제용 논리 엔티티 키. entity 정보가 불완전하면 None.

        포맷: "{category}:{entity_type}:{entity_id}"
              예: "competition_result:competition:132".
        entity_type/entity_id 중 하나라도 None이면 억제 대상이 아니라고 판단해 None을
        반환한다(키가 불완전하면 억제하지 않고 정상 발송 — 억제 실패 < 알림 유실).
        """
        entity_type = event.get("entity_type")
        entity_id = event.get("entity_id")
        if entity_type is None or entity_id is None:
            return None
        return f"{category}:{entity_type}:{entity_id}"

    def _dedup_suppressed(
        self, member_id: str, channel: str, dedup_key: Optional[str]
    ) -> bool:
        """이 (member, channel, dedup_key)에 대해 쿨다운 창 안에 이미 'sent' 로그가
        있으면 True(발송 억제). 억제할 이유가 없으면 False.

        회원별·채널별로 판정한다: 같은 논리 엔티티라도 회원 A는 이미 받았고 B는 아직일
        수 있고, 채널마다 도달 여부가 다르기 때문이다('sent' 로그가 남는 in_app/web_push
        각각을 자기 채널 이력으로 억제). dedup_key가 None이거나 쿨다운이 0 이하이면
        억제하지 않는다. 조회 실패는 안전측으로 False(억제 실패 < 알림 유실).
        """
        if not dedup_key or settings.NOTIFY_DEDUP_COOLDOWN_HOURS <= 0:
            return False
        try:
            window_start = (
                datetime.now(timezone.utc)
                - timedelta(hours=settings.NOTIFY_DEDUP_COOLDOWN_HOURS)
            ).isoformat()
            res = (
                self.db.table("app_notification_log")
                .select("id")
                .eq("member_id", member_id)
                .eq("channel", channel)
                .eq("dedup_key", dedup_key)
                .eq("status", "sent")
                .gte("created_at", window_start)
                .limit(1)
                .execute()
            )
            return bool(res.data)
        except Exception as exc:  # noqa: BLE001 - 폴러 생존, 억제 실패 < 알림 유실
            logger.warning(
                "쿨다운 조회 실패 member=%s key=%s: %s", member_id, dedup_key, exc
            )
            return False

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
        dedup_key: Optional[str] = None,
    ) -> bool:
        """notifications 테이블에 인앱 알림 생성. 중복/쿨다운이면 False.

        최초 발송 경로에서만 호출된다(재시도는 _in_app_core 직접 호출 → 게이트 우회).
        """
        if self._already_sent(member_id, "in_app", event):
            return False
        # 재정정 스팸 억제 (P1-4): 같은 논리 엔티티를 쿨다운 안에 이미 받았으면 skip.
        if self._dedup_suppressed(member_id, "in_app", dedup_key):
            logger.debug("쿨다운 억제 member=%s channel=in_app key=%s", member_id, dedup_key)
            return False
        ok, notif_id, error = self._in_app_core(member_id, category, title, body, link, event)
        if ok:
            self._log(
                member_id, "in_app", "sent", event,
                notification_id=notif_id, dedup_key=dedup_key,
            )
            return True
        self._log(member_id, "in_app", "failed", event, error=error, dedup_key=dedup_key)
        return False

    def _in_app_core(
        self,
        member_id: str,
        category: str,
        title: str,
        body: str,
        link: Optional[str],
        event: dict,
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """인앱 알림 발송 코어 (멱등성 검사·로그 기록 없음).

        최초 발송(_send_in_app)과 재시도(retry_failed)가 공유한다.
        Returns:
            (ok, notification_id, error) — 성공 시 (True, 생성된 notifications.id, None),
            실패 시 (False, None, 오류 문자열).
        """
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
            return True, notif_id, None
        except Exception as exc:  # noqa: BLE001
            logger.error("인앱 알림 발송 실패 member=%s: %s", member_id, exc)
            return False, None, str(exc)

    def _send_web_push(
        self, member_id: str, event: dict, dedup_key: Optional[str] = None
    ) -> bool:
        """웹 푸시 발송 (FCM은 표준 Web Push 위에서 동작 → pywebpush 사용).

        graceful degradation:
          - VAPID 비밀키 미설정 / pywebpush 미설치 → 크래시 없이 'pending' 로그 후 종료.
          - 만료 구독(404/410) → 해당 구독 is_active=false.
          - 발송 성공 → app_notification_log status='sent'.
        멱등성: app_notification_log(channel='web_push') 존재 시 재발송 안 함.
        재정정 스팸 억제(P1-4): 같은 논리 엔티티를 쿨다운 안에 이미 발송했으면 skip.

        최초 발송 경로에서만 호출된다(재시도는 _web_push_core 직접 호출 → 게이트 우회).

        Returns:
            이번 호출에서 1건 이상 실제 발송했으면 True, 그 외(중복/쿨다운/미설정/구독 없음/실패)는 False.
            메트릭(dispatched) 집계용 신호이며 발송 로직 자체에는 영향을 주지 않는다.
        """
        if self._already_sent(member_id, "web_push", event):
            return False
        if self._dedup_suppressed(member_id, "web_push", dedup_key):
            logger.debug("쿨다운 억제 member=%s channel=web_push key=%s", member_id, dedup_key)
            return False

        status, error = self._web_push_core(member_id, event)
        if status == "sent":
            self._log(member_id, "web_push", "sent", event, dedup_key=dedup_key)
            return True
        if status == "no_subscription":
            # 원본 동작 보존: 활성 구독이 없으면 로그를 남기지 않는다 (debug만).
            return False
        # pending(VAPID/pywebpush 미설정) 또는 failed(구독 조회 실패/발송 실패)
        self._log(member_id, "web_push", status, event, error=error, dedup_key=dedup_key)
        return False

    def _web_push_core(self, member_id: str, event: dict) -> tuple[str, Optional[str]]:
        """웹 푸시 발송 코어 (멱등성 검사·로그 기록 없음).

        최초 발송(_send_web_push)과 재시도(retry_failed)가 공유한다.
        Returns:
            (status, error) — status ∈ {'sent','pending','failed','no_subscription'}.
              - sent            : 1건 이상 실제 발송 성공.
              - pending         : VAPID 키 미설정 / pywebpush 미설치 (향후 재시도 가능).
              - failed          : 구독 조회 실패 또는 모든 발송 실패.
              - no_subscription : 활성 구독 없음 (발송 대상 자체가 없음).
        """
        # 1) VAPID 비밀키 확인 (없으면 발송 불가 → pending)
        private_key = settings.FCM_VAPID_PRIVATE_KEY
        if not private_key:
            logger.info("web_push skip member=%s: VAPID key 미설정", member_id)
            return "pending", "VAPID key 미설정"

        # 2) pywebpush 지연 import (미설치여도 모듈 import는 깨지지 않음)
        try:
            from pywebpush import WebPushException, webpush  # type: ignore
        except Exception as exc:  # noqa: BLE001 - ImportError 등
            logger.warning("web_push skip member=%s: pywebpush 미설치 (%s)", member_id, exc)
            return "pending", "pywebpush 미설치"

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
            return "failed", str(exc)

        if not subscriptions:
            logger.debug("web_push: 활성 구독 없음 member=%s", member_id)
            return "no_subscription", None

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
            return "sent", None
        return "failed", last_error or "발송 대상 없음"

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

        status, error = self._kakao_core(member_id, event)
        if status == "sent":
            self._log(member_id, "kakao_alimtalk", "sent", event)
        elif status == "pending":
            self._log(member_id, "kakao_alimtalk", "pending", event, error=error)
        else:  # 'failed'
            self._log(member_id, "kakao_alimtalk", "failed", event, error=error or "알 수 없는 오류")

    def _kakao_core(self, member_id: str, event: dict) -> tuple[str, Optional[str]]:
        """카카오 알림톡 발송 코어 (멱등성 검사·로그 기록 없음).

        최초 발송(_send_kakao)과 재시도(retry_failed)가 공유한다.
        not_configured(자격증명/템플릿 없음)는 pending으로 정규화한다(향후 재시도 가능 상태).
        Returns:
            (status, error) — status ∈ {'sent','pending','failed'}.
        """
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
            return "failed", str(exc)

        from .kakao import KakaoAlimtalkSender, build_recipient_phone

        phone = build_recipient_phone(member_row or {})
        if not phone:
            logger.info("kakao skip member=%s: 전화번호 없음", member_id)
            return "pending", "전화번호 없음"

        # 2) 발송 (sender는 절대 예외를 던지지 않음)
        sender = KakaoAlimtalkSender()
        result = sender.send(to_phone=phone, event=event)
        status = result.get("status")
        error = result.get("error")

        # 3) 결과 정규화 (not_configured → pending)
        if status == "sent":
            return "sent", None
        if status in ("pending", "not_configured"):
            return "pending", error
        return "failed", error or "알 수 없는 오류"

    # -------------------------------------------------------------- retry sweep

    def retry_failed(self, max_attempts: int, window_hours: int) -> dict:
        """실패/보류(failed/pending) 알림 로그를 재발송하는 스윕 (EVAL P1-1).

        폴러 커서는 배치 max(id)로 무조건 전진하므로, 일시적 오류로 실패한 알림은
        재시도 경로가 없으면 영원히 재발송되지 않는다. 이 스윕이 app_notification_log에서
        아직 성공하지 못한 행을 찾아 원본 이벤트를 재조회하고 채널별로 재발송한다.

        멱등성 우회: 재발송은 _send_* 가 아니라 채널 코어(_in_app_core/_web_push_core/
        _kakao_core)를 직접 호출한다. _send_* 는 맨 앞에서 _already_sent()로 스킵하는데,
        재시도 대상은 이미 로그 행이 있어 그 검사에 걸리기 때문이다. 결과는 기존 로그 행을
        UPDATE(migration 022의 UNIQUE 제약과 정합 — 신규 INSERT 아님)한다.

        절대 raise 하지 않는다(폴러 생존 보장).

        Returns:
            {"retried": 시도한 행 수, "recovered": sent로 전이한 행 수}.
        """
        summary = {"retried": 0, "recovered": 0}
        try:
            window_start = (
                datetime.now(timezone.utc) - timedelta(hours=window_hours)
            ).isoformat()
            res = (
                self.db.table("app_notification_log")
                .select("*")
                .in_("status", ["failed", "pending"])
                .lt("attempt_count", max_attempts)
                .gte("created_at", window_start)
                .order("created_at")
                .limit(200)
                .execute()
            )
            rows = res.data or []
        except Exception as exc:  # noqa: BLE001 - 스윕 조회 실패는 폴러를 죽이지 않음
            logger.error("재시도 스윕 조회 실패: %s", exc)
            return summary

        for row in rows:
            try:
                self._retry_one(row, summary)
            except Exception as exc:  # noqa: BLE001 - 한 행 실패가 스윕을 막지 않음
                logger.error("재시도 처리 오류 log=%s: %s", row.get("id"), exc)

        return summary

    def _retry_one(self, row: dict, summary: dict) -> None:
        """단일 로그 행 재시도. 로그 행 상태를 UPDATE한다."""
        channel = row.get("channel")
        log_id = row.get("id")
        member_id = row.get("member_id")
        event_id = row.get("event_id")
        event_type = row.get("event_type") or ""

        # 카카오는 게이트 off면 건너뜀 (재활성화 대비 상태 보존, attempt 증가 안 함).
        if channel == "kakao_alimtalk" and not settings.ENABLE_KAKAO_ALIMTALK:
            return

        summary["retried"] += 1

        # 원본 이벤트 재조회 (title/body는 로그에 없으므로 data_events에서 재구성).
        event = self._fetch_source_event(event_id)
        if event is None:
            # 원본이 사라졌으면 재구성 불가 → attempt만 올려 무한 재시도 방지.
            self._update_log_row(
                log_id, row, status=None, error="원본 이벤트 없음"
            )
            return

        status, error, notif_id = self._resend_channel(channel, member_id, event_type, event)
        if status == "sent":
            self._update_log_row(log_id, row, status="sent", error=None, notification_id=notif_id)
            summary["recovered"] += 1
        elif status == "pending":
            self._update_log_row(log_id, row, status="pending", error=error)
        else:  # 'failed' 또는 알 수 없는 채널
            self._update_log_row(log_id, row, status="failed", error=error)

    def _fetch_source_event(self, event_id: Any) -> Optional[dict]:
        """event_id로 data_events 원본 행을 재조회. 없거나 실패하면 None."""
        if event_id is None:
            return None
        try:
            res = (
                self.db.table("data_events")
                .select("*")
                .eq("id", event_id)
                .limit(1)
                .execute()
            )
            return (res.data or [None])[0]
        except Exception as exc:  # noqa: BLE001
            logger.warning("원본 이벤트 조회 실패 event_id=%s: %s", event_id, exc)
            return None

    def _resend_channel(
        self, channel: Optional[str], member_id: str, event_type: str, event: dict
    ) -> tuple[str, Optional[str], Optional[str]]:
        """채널별 재발송 (멱등성 우회, 로그 INSERT 없음).

        Returns:
            (status, error, notification_id) — status ∈ {'sent','pending','failed'}.
            notification_id는 in_app 재발송 성공 시에만 채워진다.
        """
        if channel == "in_app":
            category = et.category_for_event(event.get("event_type", "")) or event_type
            title, body, link = et.build_message(event)
            ok, notif_id, error = self._in_app_core(
                member_id, category, title, body, link, event
            )
            return ("sent" if ok else "failed"), error, notif_id

        if channel == "web_push":
            status, error = self._web_push_core(member_id, event)
            # 재시도 시 '구독 없음'은 재발송 불가한 실패로 취급(원본과 달리 로그를 남겨야 함).
            if status == "no_subscription":
                return "failed", "활성 구독 없음", None
            return status, error, None

        if channel == "kakao_alimtalk":
            # 게이트는 _retry_one에서 이미 확인됨 (여기 도달 = ENABLE_KAKAO_ALIMTALK True).
            status, error = self._kakao_core(member_id, event)
            return status, error, None

        return "failed", f"알 수 없는 채널: {channel}", None

    def _update_log_row(
        self,
        log_id: Any,
        row: dict,
        status: Optional[str],
        error: Optional[str],
        notification_id: Optional[str] = None,
    ) -> None:
        """재시도 결과를 로그 행에 UPDATE (id로 특정). attempt_count는 항상 +1.

        status가 None이면 기존 상태를 유지하고 attempt_count/last_attempt_at/error만 갱신
        (원본 이벤트 소실 등 재발송을 아예 시도하지 못한 경우).
        """
        if log_id is None:
            return
        patch: dict[str, Any] = {
            "attempt_count": int(row.get("attempt_count") or 0) + 1,
            "last_attempt_at": _now_iso(),
            "error_message": error,
        }
        if status is not None:
            patch["status"] = status
        if status == "sent":
            patch["sent_at"] = _now_iso()
            if notification_id is not None:
                patch["notification_id"] = notification_id
        try:
            self.db.table("app_notification_log").update(patch).eq("id", log_id).execute()
        except Exception as exc:  # noqa: BLE001
            logger.warning("재시도 로그 업데이트 실패 log=%s: %s", log_id, exc)

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
        dedup_key: Optional[str] = None,
    ) -> None:
        now = _now_iso()
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
                    # dedup_key: 재정정 스팸 억제 조회 대상(P1-4). None이면 억제 대상 아님.
                    "dedup_key": dedup_key,
                    # created_at을 명시적으로 기록 → 쿨다운 창(created_at >= window) 조회 근거.
                    # (DB DEFAULT now()와 동일 의미. 명시 기록으로 조회 시점 정합성 보장.)
                    "created_at": now,
                    "sent_at": now if status == "sent" else None,
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
