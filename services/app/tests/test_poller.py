"""Characterization tests for EventPoller.poll_once.

Pins the watermark loop:
  - only data_events with id > cursor are fetched, in ascending id order
  - cursor advances to the batch's max id and events_processed accumulates
  - empty batch → cursor untouched except last_polled_at (touch)
  - missing cursor row → auto-created
  - a dispatch exception on a poison event does NOT block the batch; cursor still
    advances past it (current behavior — at-most-once, event is skipped forever)
"""
from __future__ import annotations

from services.app.app.pipeline.poller import EventPoller
from services.app.tests._fakes import FakeSupabase


class _RecordingDispatcher:
    """Stub dispatcher: records dispatched event ids, returns a fixed summary."""

    def __init__(self, in_app: int = 1):
        self.seen: list[int] = []
        self._in_app = in_app

    def dispatch(self, event: dict) -> dict:
        self.seen.append(event["id"])
        return {"in_app": self._in_app}


class _RaisingDispatcher:
    def __init__(self):
        self.seen: list[int] = []

    def dispatch(self, event: dict) -> dict:
        self.seen.append(event["id"])
        raise RuntimeError("poison event")


def _cursor(last_event_id=0, events_processed=0) -> list[dict]:
    return [
        {
            "id": 1,
            "last_event_id": last_event_id,
            "events_processed": events_processed,
        }
    ]


def _events(ids) -> list[dict]:
    return [{"id": i, "event_type": "ranking.updated", "data": {}} for i in ids]


def _poller(db, dispatcher):
    return EventPoller(dispatcher=dispatcher, supabase=db)


def test_poll_once_processes_new_events_in_order():
    db = FakeSupabase(
        {"app_event_cursor": _cursor(last_event_id=2), "data_events": _events([1, 2, 3, 4, 5])}
    )
    disp = _RecordingDispatcher()
    result = _poller(db, disp).poll_once()

    # gt(2) → only 3,4,5, ascending
    assert disp.seen == [3, 4, 5]
    assert result["polled"] == 3
    assert result["dispatched"] == 3
    assert result["last_id"] == 5


def test_poll_once_advances_cursor_to_max_id():
    db = FakeSupabase(
        {"app_event_cursor": _cursor(last_event_id=0, events_processed=10), "data_events": _events([1, 2, 3])}
    )
    _poller(db, _RecordingDispatcher()).poll_once()

    row = db.rows("app_event_cursor")[0]
    assert row["last_event_id"] == 3
    assert row["events_processed"] == 13  # 10 + 3
    assert row.get("last_polled_at") is not None


def test_poll_once_empty_batch_touches_only():
    db = FakeSupabase(
        {"app_event_cursor": _cursor(last_event_id=100), "data_events": _events([1, 2, 3])}
    )
    disp = _RecordingDispatcher()
    result = _poller(db, disp).poll_once()

    assert disp.seen == []
    assert result == {"polled": 0, "dispatched": 0, "last_id": 100}
    row = db.rows("app_event_cursor")[0]
    assert row["last_event_id"] == 100  # unchanged
    assert row.get("last_polled_at") is not None  # touched


def test_poll_once_creates_cursor_when_missing():
    db = FakeSupabase({"app_event_cursor": [], "data_events": []})
    result = _poller(db, _RecordingDispatcher()).poll_once()

    assert result["polled"] == 0
    rows = db.rows("app_event_cursor")
    assert len(rows) == 1
    assert rows[0]["id"] == 1
    assert rows[0]["last_event_id"] == 0


def test_poll_once_advances_cursor_even_when_dispatch_raises():
    # Poison event: dispatch throws for every event, but the batch still advances
    # the watermark to max id (events are skipped forever — current behavior).
    db = FakeSupabase(
        {"app_event_cursor": _cursor(last_event_id=0), "data_events": _events([1, 2, 3])}
    )
    disp = _RaisingDispatcher()
    result = _poller(db, disp).poll_once()

    assert disp.seen == [1, 2, 3]      # all attempted
    assert result["polled"] == 3
    assert result["dispatched"] == 0   # none counted (all raised)
    assert result["last_id"] == 3
    assert db.rows("app_event_cursor")[0]["last_event_id"] == 3  # advanced past poison


def test_poll_once_respects_batch_size():
    db = FakeSupabase(
        {"app_event_cursor": _cursor(last_event_id=0), "data_events": _events([1, 2, 3, 4, 5])}
    )
    poller = EventPoller(dispatcher=_RecordingDispatcher(), supabase=db, batch_size=2)
    result = poller.poll_once()

    assert result["polled"] == 2
    assert result["last_id"] == 2
    assert db.rows("app_event_cursor")[0]["last_event_id"] == 2
