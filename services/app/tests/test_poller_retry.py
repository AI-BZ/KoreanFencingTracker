"""EventPoller ↔ retry-sweep integration (EVAL P1-1).

poll_once must invoke dispatcher.retry_failed once per cycle — even when the new
event batch is empty — so a previously-failed notification is recovered. A stub
dispatcher without retry_failed must be tolerated (sweep skipped, no crash).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.app.app.pipeline.poller import EventPoller
from services.app.tests._fakes import FakeSupabase

_RECENT = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
# 안전 지연 필터를 통과하는 과거 시각 (poll_once의 .lte(created_at, cutoff)).
_OLD = "2020-01-01T00:00:00+00:00"

_DATA_EVENT = {
    "id": 101,
    "event_type": "ranking.updated",
    "entity_id": 5,
    "data": {"player_name": "박소윤"},
    "created_at": _OLD,
}

_FAILED_IN_APP_LOG = {
    "id": 1,
    "member_id": "m1",
    "channel": "in_app",
    "status": "failed",
    "event_type": "ranking.updated",
    "event_id": 101,
    "attempt_count": 0,
    "created_at": _RECENT,
    "sent_at": None,
    "notification_id": None,
}


def test_poll_once_runs_retry_sweep_on_empty_batch():
    # 커서가 모든 data_events를 지난 상태(빈 배치) — 그래도 이전 실패 로그를 복구해야 함.
    db = FakeSupabase(
        {
            "app_event_cursor": [{"id": 1, "last_event_id": 101, "events_processed": 0}],
            "data_events": [dict(_DATA_EVENT)],
            "app_notification_log": [dict(_FAILED_IN_APP_LOG)],
            "notifications": [],
            "app_push_subscriptions": [],
        }
    )
    result = EventPoller(supabase=db).poll_once()  # 실 디스패처(lazy)

    assert result["polled"] == 0
    assert result["recovered"] == 1
    assert result["retried"] == 1
    assert db.count("notifications") == 1
    assert db.rows("app_notification_log")[0]["status"] == "sent"


def test_poll_once_runs_retry_sweep_alongside_new_events():
    # 새 이벤트를 처리하면서 동시에 이전 실패 로그도 복구.
    new_event = {
        "id": 200,
        "event_type": "ranking.updated",
        "entity_id": 5,
        "data": {"player_id": 5},
        "created_at": _OLD,
    }
    db = FakeSupabase(
        {
            "app_event_cursor": [{"id": 1, "last_event_id": 150, "events_processed": 0}],
            "data_events": [dict(_DATA_EVENT), new_event],
            "members": [{"id": "m1", "player_id": 5}],
            "app_notification_preferences": [
                {"member_id": "m1", "category": "ranking_change", "in_app": True, "web_push": False, "kakao_alimtalk": False}
            ],
            "app_notification_log": [dict(_FAILED_IN_APP_LOG)],
            "notifications": [],
            "app_push_subscriptions": [],
        }
    )
    result = EventPoller(supabase=db).poll_once()

    assert result["polled"] == 1          # id=200 새 이벤트
    assert result["last_id"] == 200
    assert result["recovered"] == 1       # 실패했던 id=101 로그 복구
    # 새 이벤트 1건 + 복구 1건 = 알림 2건
    assert db.count("notifications") == 2


def test_poll_once_tolerates_dispatcher_without_retry():
    # retry_failed 없는 스텁 디스패처 → 스윕 스킵, 크래시 없음, recovered 키 없음.
    class _Stub:
        def dispatch(self, ev):
            return {"in_app": 0}

    db = FakeSupabase(
        {"app_event_cursor": [{"id": 1, "last_event_id": 0}], "data_events": []}
    )
    result = EventPoller(dispatcher=_Stub(), supabase=db).poll_once()

    assert result["polled"] == 0
    assert "recovered" not in result
