"""Tests for the failed/pending retry sweep on app_notification_log (EVAL P1-1).

The poller cursor advances past every batch, so a notification that failed
transiently would never be re-sent without a sweep. ``dispatcher.retry_failed``
finds unfinished log rows, re-fetches the original data_events row to rebuild the
message, re-sends through the channel core (bypassing the per-event idempotency
guard that would otherwise skip it), and UPDATEs the existing log row.

Pinned behavior:
  - failed in_app row → re-sent to 'sent' (attempt bumped, last_attempt_at set),
    message rebuilt from data_events.
  - attempt_count at max → excluded (no infinite retry).
  - created_at outside window → excluded.
  - pending web_push with VAPID still unset → stays pending, attempt bumped.
  - missing original event → attempt bumped, status unchanged (no infinite retry).
  - kakao gated off → skipped, row untouched (preserved for re-enable).
  - never raises: log-query error and source-fetch error are both absorbed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.app.app.config import settings
from services.app.app.pipeline.dispatcher import NotificationDispatcher
from services.app.tests._fakes import FakeSupabase


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _recent() -> str:
    return (_now() - timedelta(minutes=5)).isoformat()


def _old() -> str:
    return (_now() - timedelta(days=2)).isoformat()


def _log_row(**overrides) -> dict:
    row = {
        "id": 1,
        "member_id": "m1",
        "channel": "in_app",
        "status": "failed",
        "event_type": "ranking.updated",
        "event_id": 101,
        "attempt_count": 0,
        "created_at": _recent(),
        "error_message": "boom",
        "sent_at": None,
        "notification_id": None,
    }
    row.update(overrides)
    return row


# data_events 원본 (retry가 재조회해 메시지를 재구성하는 대상).
_DATA_EVENT = {
    "id": 101,
    "event_type": "ranking.updated",
    "entity_id": 5,
    "data": {"player_name": "박소윤"},
}


def _db(log_rows, *, with_source=True, raise_on=None, extra=None) -> FakeSupabase:
    tables = {
        "app_notification_log": log_rows,
        "data_events": [dict(_DATA_EVENT)] if with_source else [],
        "notifications": [],
        "app_push_subscriptions": [],
    }
    if extra:
        tables.update(extra)
    return FakeSupabase(tables, raise_on=raise_on)


# ------------------------------------------------------------ happy path (in_app)

def test_retry_recovers_failed_in_app():
    db = _db([_log_row()])
    summary = NotificationDispatcher(supabase=db).retry_failed(max_attempts=3, window_hours=24)

    assert summary == {"retried": 1, "recovered": 1}

    # 메시지가 data_events 재조회로 재구성됨.
    notes = db.rows("notifications")
    assert len(notes) == 1
    assert notes[0]["title"] == "랭킹이 변동되었습니다"
    assert notes[0]["notification_type"] == "ranking_change"

    # 로그 행이 sent로 전이 (attempt/last_attempt_at/sent_at/notification_id 갱신).
    log = db.rows("app_notification_log")[0]
    assert log["status"] == "sent"
    assert log["attempt_count"] == 1
    assert log["last_attempt_at"] is not None
    assert log["sent_at"] is not None
    assert log["notification_id"] == notes[0]["id"]


# ------------------------------------------------------------------- guardrails

def test_retry_skips_when_attempts_exhausted():
    db = _db([_log_row(attempt_count=3)])
    summary = NotificationDispatcher(supabase=db).retry_failed(max_attempts=3, window_hours=24)

    assert summary == {"retried": 0, "recovered": 0}
    assert db.count("notifications") == 0
    assert db.rows("app_notification_log")[0]["attempt_count"] == 3  # 변화 없음


def test_retry_excludes_rows_outside_window():
    db = _db([_log_row(created_at=_old())])
    summary = NotificationDispatcher(supabase=db).retry_failed(max_attempts=3, window_hours=24)

    assert summary == {"retried": 0, "recovered": 0}
    assert db.count("notifications") == 0
    # attempt 미증가 (아예 조회 대상 아님).
    assert db.rows("app_notification_log")[0]["attempt_count"] == 0


def test_retry_ignores_sent_rows():
    # 이미 sent인 행은 재시도 대상이 아니다 (status IN ('failed','pending')만).
    db = _db([_log_row(status="sent", sent_at=_recent())])
    summary = NotificationDispatcher(supabase=db).retry_failed(max_attempts=3, window_hours=24)

    assert summary == {"retried": 0, "recovered": 0}
    assert db.count("notifications") == 0


# ------------------------------------------------------------ pending web_push

def test_retry_pending_web_push_stays_pending(monkeypatch):
    # VAPID 키가 여전히 미설정이면 재시도해도 pending 유지 + attempt만 증가.
    monkeypatch.setattr(settings, "FCM_VAPID_PRIVATE_KEY", "")
    db = _db(
        [_log_row(channel="web_push", status="pending", error_message="VAPID key 미설정")]
    )
    summary = NotificationDispatcher(supabase=db).retry_failed(max_attempts=3, window_hours=24)

    assert summary == {"retried": 1, "recovered": 0}
    log = db.rows("app_notification_log")[0]
    assert log["status"] == "pending"
    assert log["attempt_count"] == 1
    assert log["last_attempt_at"] is not None


def test_retry_pending_web_push_recovers_when_vapid_set(monkeypatch):
    # VAPID + 활성 구독이 갖춰지면 pending → sent 복구 (pywebpush 발송 성공 스텁).
    monkeypatch.setattr(settings, "FCM_VAPID_PRIVATE_KEY", "test-private-key")

    sent = []

    class _FakeWebPushException(Exception):
        pass

    def _fake_webpush(**kwargs):
        sent.append(kwargs)

    import sys
    import types

    fake_mod = types.ModuleType("pywebpush")
    fake_mod.webpush = _fake_webpush
    fake_mod.WebPushException = _FakeWebPushException
    monkeypatch.setitem(sys.modules, "pywebpush", fake_mod)

    db = _db(
        [_log_row(channel="web_push", status="pending")],
        extra={
            "app_push_subscriptions": [
                {
                    "id": "s1",
                    "member_id": "m1",
                    "is_active": True,
                    "fcm_endpoint": "https://push.example/e",
                    "fcm_p256dh": "p",
                    "fcm_auth": "a",
                }
            ]
        },
    )
    summary = NotificationDispatcher(supabase=db).retry_failed(max_attempts=3, window_hours=24)

    assert summary == {"retried": 1, "recovered": 1}
    assert len(sent) == 1  # 실제 발송 코어가 호출됨
    log = db.rows("app_notification_log")[0]
    assert log["status"] == "sent"
    assert log["attempt_count"] == 1
    assert log["sent_at"] is not None


# ------------------------------------------------------------ missing source

def test_retry_missing_source_event_bumps_attempt():
    # 원본 data_events가 사라졌으면 재구성 불가 → attempt만 올려 무한 재시도 방지.
    db = _db([_log_row(event_id=999)])  # data_events엔 101만 존재
    summary = NotificationDispatcher(supabase=db).retry_failed(max_attempts=3, window_hours=24)

    assert summary == {"retried": 1, "recovered": 0}
    log = db.rows("app_notification_log")[0]
    assert log["attempt_count"] == 1
    assert log["status"] == "failed"  # 상태 유지
    assert "원본 이벤트 없음" in (log["error_message"] or "")
    assert db.count("notifications") == 0


# ------------------------------------------------------------ kakao gated off

def test_retry_skips_kakao_when_gated_off(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_KAKAO_ALIMTALK", False)
    db = _db([_log_row(channel="kakao_alimtalk", status="pending")])
    summary = NotificationDispatcher(supabase=db).retry_failed(max_attempts=3, window_hours=24)

    # 게이트 off → 아예 시도하지 않음 (retried 미집계), 행 그대로 보존.
    assert summary == {"retried": 0, "recovered": 0}
    log = db.rows("app_notification_log")[0]
    assert log["attempt_count"] == 0
    assert log["status"] == "pending"


# ----------------------------------------------------------- never raises

def test_retry_never_raises_on_log_query_error():
    # app_notification_log SELECT가 raise → 흡수하고 빈 요약 반환.
    db = FakeSupabase({"app_notification_log": []}, raise_on=["app_notification_log"])
    summary = NotificationDispatcher(supabase=db).retry_failed(max_attempts=3, window_hours=24)
    assert summary == {"retried": 0, "recovered": 0}


def test_retry_never_raises_when_source_fetch_errors():
    # data_events 재조회가 raise → _fetch_source_event가 None 반환 → attempt만 증가.
    db = _db([_log_row()], raise_on=["data_events"])
    summary = NotificationDispatcher(supabase=db).retry_failed(max_attempts=3, window_hours=24)

    assert summary == {"retried": 1, "recovered": 0}
    log = db.rows("app_notification_log")[0]
    assert log["attempt_count"] == 1
    assert log["status"] == "failed"
    assert db.count("notifications") == 0


def test_retry_batch_multiple_rows_mixed():
    # 여러 행을 한 스윕에서 처리: in_app 2건 복구.
    db = _db(
        [
            _log_row(id=1, member_id="m1"),
            _log_row(id=2, member_id="m2"),
        ]
    )
    summary = NotificationDispatcher(supabase=db).retry_failed(max_attempts=3, window_hours=24)

    assert summary == {"retried": 2, "recovered": 2}
    assert db.count("notifications") == 2
    assert all(r["status"] == "sent" for r in db.rows("app_notification_log"))
