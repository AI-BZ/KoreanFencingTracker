"""Tests for the re-correction spam suppression (cooldown) on the dispatcher (EVAL P1-4).

The per-event idempotency guard (_already_sent) keys on data_events.id. Re-scraping
or correcting a competition result publishes a NEW data_events row (new id), so that
guard passes and every participant is notified again — one correction = one spam wave.

``dispatcher._dedup_key`` groups notifications by *logical entity*
("{category}:{entity_type}:{entity_id}") and ``_dedup_suppressed`` skips a send when
that member+channel already has a 'sent' log for the same key within
``NOTIFY_DEDUP_COOLDOWN_HOURS``.

Pinned behavior:
  - 2nd dispatch of the same logical entity (different event_id) within the window →
    in_app send skipped (no new notifications row).
  - once the cooldown window has passed → re-sent.
  - event missing entity_type/entity_id → dedup_key None → no suppression (normal send).
  - suppression is per-member: member A suppressed does not stop member B.
  - a failing dedup lookup does not block the send (raise absorbed, send proceeds).
  - retry_failed bypasses the dedup gate entirely (recovery path, not first dispatch).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.app.app.config import settings
from services.app.app.pipeline.dispatcher import NotificationDispatcher
from services.app.tests._fakes import FakeSupabase


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# 같은 논리 엔티티(player 5)에 대한 두 정정 이벤트 — id만 다르다.
def _event(event_id: int) -> dict:
    return {
        "id": event_id,
        "event_type": "ranking.updated",
        "entity_type": "player",
        "entity_id": 5,
        "data": {"player_name": "박소윤"},
    }


_DEDUP_KEY = "ranking_change:player:5"  # _dedup_key(category, event)와 일치


def _pref(member_id: str) -> dict:
    return {
        "member_id": member_id,
        "category": "ranking_change",
        "in_app": True,
        "web_push": False,
        "kakao_alimtalk": False,
    }


def _tables(*, prefs, members, log=None) -> dict:
    return {
        "members": members,
        "app_notification_preferences": prefs,
        "notifications": [],
        "app_notification_log": log or [],
    }


def _sent_log(member_id: str, created_at: str, *, event_id: int = 100) -> dict:
    """이미 발송(sent)된 in_app 로그 (dedup_key 채워짐)."""
    return {
        "id": event_id,
        "member_id": member_id,
        "channel": "in_app",
        "status": "sent",
        "event_type": "ranking.updated",
        "event_id": event_id,
        "dedup_key": _DEDUP_KEY,
        "created_at": created_at,
        "attempt_count": 0,
        "sent_at": created_at,
        "notification_id": None,
    }


# ------------------------------------------------- 2nd dispatch suppressed (window)

def test_second_dispatch_within_cooldown_is_suppressed():
    db = FakeSupabase(
        _tables(prefs=[_pref("m1")], members=[{"id": "m1", "player_id": 5}])
    )
    disp = NotificationDispatcher(supabase=db)

    first = disp.dispatch(_event(101))
    second = disp.dispatch(_event(102))  # 정정 → 새 event_id, 같은 논리 엔티티

    assert first["in_app"] == 1
    assert second["in_app"] == 0            # 쿨다운 억제
    assert db.count("notifications") == 1   # 두 번째는 알림 미생성


# --------------------------------------------------------- cooldown expired → resend

def test_dispatch_after_cooldown_resends():
    # 7시간 전(기본 쿨다운 6h 초과) sent 로그가 있으면 억제되지 않고 재발송된다.
    old = _iso(_now() - timedelta(hours=settings.NOTIFY_DEDUP_COOLDOWN_HOURS + 1))
    db = FakeSupabase(
        _tables(
            prefs=[_pref("m1")],
            members=[{"id": "m1", "player_id": 5}],
            log=[_sent_log("m1", old)],
        )
    )
    summary = NotificationDispatcher(supabase=db).dispatch(_event(102))

    assert summary["in_app"] == 1
    assert db.count("notifications") == 1


# ----------------------------------------------- incomplete key → no suppression

def test_event_without_entity_is_not_suppressed():
    # entity_type/entity_id 없음 → dedup_key None → 억제하지 않고 정상 발송.
    # (이미 최근 sent 로그가 있어도, 키가 불완전하면 억제 근거로 쓰지 않는다.)
    recent = _iso(_now() - timedelta(minutes=5))
    event_no_entity = {
        "id": 202,
        "event_type": "ranking.updated",
        "data": {"player_id": 5},  # entity_type/entity_id 없음
    }
    db = FakeSupabase(
        _tables(
            prefs=[_pref("m1")],
            members=[{"id": "m1", "player_id": 5}],
            log=[_sent_log("m1", recent)],
        )
    )
    summary = NotificationDispatcher(supabase=db).dispatch(event_no_entity)

    assert summary["in_app"] == 1
    assert db.count("notifications") == 1


# ------------------------------------------------------------- per-member isolation

def test_suppression_is_per_member():
    # m1은 최근 sent 로그 보유 → 억제. m2는 없음 → 발송.
    recent = _iso(_now() - timedelta(minutes=5))
    db = FakeSupabase(
        _tables(
            prefs=[_pref("m1"), _pref("m2")],
            members=[{"id": "m1", "player_id": 5}, {"id": "m2", "player_id": 5}],
            log=[_sent_log("m1", recent)],
        )
    )
    summary = NotificationDispatcher(supabase=db).dispatch(_event(102))

    assert summary["targets"] == 2
    assert summary["in_app"] == 1  # m2만 발송 (m1은 억제)
    notes = db.rows("notifications")
    assert len(notes) == 1
    assert notes[0]["recipient_id"] == "m2"


# ------------------------------------------------- dedup lookup error → send proceeds

def test_dedup_lookup_error_does_not_block_send():
    # app_notification_log의 모든 execute()가 raise → _already_sent/_dedup_suppressed/
    # _log 모두 흡수. 억제 실패 < 알림 유실 → 발송은 계속되어야 한다.
    db = FakeSupabase(
        _tables(prefs=[_pref("m1")], members=[{"id": "m1", "player_id": 5}]),
        raise_on=["app_notification_log"],
    )
    summary = NotificationDispatcher(supabase=db).dispatch(_event(101))

    assert summary["in_app"] == 1
    assert db.count("notifications") == 1  # 조회 예외에도 알림은 생성됨


# ------------------------------------------------------- retry bypasses dedup gate

def test_retry_failed_ignores_dedup_gate():
    # 같은 dedup_key로 최근 'sent' 로그가 있어도, 재시도 스윕은 dedup 게이트를 타지
    # 않는다(_in_app_core 직접 호출). failed 행이 정상 복구되어야 한다.
    recent = _iso(_now() - timedelta(minutes=5))
    failed = {
        "id": 2,
        "member_id": "m1",
        "channel": "in_app",
        "status": "failed",
        "event_type": "ranking.updated",
        "event_id": 102,
        "dedup_key": _DEDUP_KEY,
        "created_at": recent,
        "attempt_count": 0,
        "error_message": "boom",
        "sent_at": None,
        "notification_id": None,
    }
    db = FakeSupabase(
        {
            "app_notification_log": [_sent_log("m1", recent, event_id=101), failed],
            "data_events": [_event(102)],
            "notifications": [],
            "app_push_subscriptions": [],
        }
    )
    summary = NotificationDispatcher(supabase=db).retry_failed(
        max_attempts=3, window_hours=24
    )

    assert summary == {"retried": 1, "recovered": 1}
    assert db.count("notifications") == 1  # dedup에 막히지 않고 복구됨
    recovered = next(r for r in db.rows("app_notification_log") if r["id"] == 2)
    assert recovered["status"] == "sent"
