"""Characterization tests for NotificationDispatcher._send_in_app.

Pins the in-app channel: notifications row shape, the app_notification_log entry,
per-channel idempotency (_already_sent), and the failure path (insert raises →
'failed' log, returns False, never propagates).
"""
from __future__ import annotations

from services.app.app.pipeline.dispatcher import NotificationDispatcher
from services.app.tests._fakes import FakeSupabase

_EVENT = {"id": 101, "event_type": "ranking.updated", "entity_id": 5, "data": {}}


def _send(db: FakeSupabase):
    disp = NotificationDispatcher(supabase=db)
    return disp._send_in_app(
        member_id="m1",
        category="ranking_change",
        title="랭킹이 변동되었습니다",
        body="박소윤님의 랭킹 정보가 업데이트되었습니다.",
        link="https://data.fencingmind.ai/rankings",
        event=_EVENT,
    )


def test_send_in_app_inserts_notification_row():
    db = FakeSupabase({"notifications": [], "app_notification_log": []})
    assert _send(db) is True

    notes = db.rows("notifications")
    assert len(notes) == 1
    note = notes[0]
    assert note["recipient_id"] == "m1"
    assert note["title"] == "랭킹이 변동되었습니다"
    assert note["notification_type"] == "ranking_change"
    assert note["link_url"] == "https://data.fencingmind.ai/rankings"
    assert note["metadata"]["source"] == "app_pipeline"
    assert note["metadata"]["event_type"] == "ranking.updated"
    assert note["metadata"]["event_id"] == 101


def test_send_in_app_writes_sent_log_with_notification_id():
    db = FakeSupabase({"notifications": [], "app_notification_log": []})
    _send(db)

    logs = db.rows("app_notification_log")
    assert len(logs) == 1
    log = logs[0]
    assert log["channel"] == "in_app"
    assert log["status"] == "sent"
    assert log["member_id"] == "m1"
    assert log["event_type"] == "ranking.updated"
    assert log["event_id"] == 101
    assert log["sent_at"] is not None
    # notification_id links back to the inserted notifications row id
    assert log["notification_id"] == db.rows("notifications")[0]["id"]


def test_send_in_app_idempotent_skip_when_already_logged():
    db = FakeSupabase(
        {
            "notifications": [],
            "app_notification_log": [
                {
                    "member_id": "m1",
                    "channel": "in_app",
                    "event_type": "ranking.updated",
                    "event_id": 101,
                    "status": "sent",
                }
            ],
        }
    )
    assert _send(db) is False
    # no new notification created
    assert db.count("notifications") == 0


def test_send_in_app_second_call_is_skipped():
    db = FakeSupabase({"notifications": [], "app_notification_log": []})
    assert _send(db) is True
    assert _send(db) is False  # now blocked by its own 'sent' log
    assert db.count("notifications") == 1


def test_send_in_app_idempotency_is_per_event():
    # A different event_id is NOT blocked by an existing log for another event.
    db = FakeSupabase(
        {
            "notifications": [],
            "app_notification_log": [
                {
                    "member_id": "m1",
                    "channel": "in_app",
                    "event_type": "ranking.updated",
                    "event_id": 999,  # different event
                    "status": "sent",
                }
            ],
        }
    )
    assert _send(db) is True
    assert db.count("notifications") == 1


def test_send_in_app_insert_failure_logs_failed_and_returns_false():
    # notifications insert raises → caught → 'failed' log, no exception propagates.
    db = FakeSupabase(
        {"notifications": [], "app_notification_log": []}, raise_on=["notifications"]
    )
    assert _send(db) is False
    logs = db.rows("app_notification_log")
    assert len(logs) == 1
    assert logs[0]["channel"] == "in_app"
    assert logs[0]["status"] == "failed"
    assert logs[0]["error_message"]  # non-empty error string
    assert logs[0]["sent_at"] is None
