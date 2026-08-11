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

from datetime import datetime, timedelta, timezone

from services.app.app.pipeline.poller import EventPoller
from services.app.tests._fakes import FakeSupabase

# 안전 지연(EVENT_SAFETY_LAG_SECONDS)을 여유롭게 통과하는 과거 시각.
_OLD_CREATED_AT = "2020-01-01T00:00:00+00:00"


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
    # created_at을 충분히 과거로 두어 poll_once의 안전 지연 필터(.lte(created_at, cutoff))를
    # 통과시킨다. 지연 필터 자체는 아래 전용 테스트에서 검증한다.
    return [
        {"id": i, "event_type": "ranking.updated", "data": {}, "created_at": _OLD_CREATED_AT}
        for i in ids
    ]


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


def test_poll_once_skips_events_within_safety_lag():
    # 안전 지연 필터(P1-2 방지): created_at이 (now - safety_lag)보다 최근인 이벤트는
    # 이번 배치에서 제외되고, 커서가 그 지연 이벤트를 지나쳐 전진하지 않아야 한다.
    # (지연 이벤트는 나이가 들면 다음 폴에서 처리된다 — 낮은 id 누락 방지의 핵심.)
    now = datetime.now(timezone.utc)
    db = FakeSupabase(
        {
            "app_event_cursor": _cursor(last_event_id=0),
            "data_events": [
                {
                    "id": 1,
                    "event_type": "ranking.updated",
                    "data": {},
                    "created_at": (now - timedelta(minutes=5)).isoformat(),
                },
                {
                    "id": 2,
                    "event_type": "ranking.updated",
                    "data": {},
                    "created_at": now.isoformat(),
                },
            ],
        }
    )
    disp = _RecordingDispatcher()
    result = _poller(db, disp).poll_once()

    # 오래된 id=1만 디스패치, 지연된 id=2는 제외
    assert disp.seen == [1]
    assert result["polled"] == 1
    assert result["last_id"] == 1
    # 커서는 지연된 id=2를 지나가지 않는다 (다음 폴에서 처리되도록)
    assert db.rows("app_event_cursor")[0]["last_event_id"] == 1


def test_poll_once_processes_events_older_than_lag():
    # 모든 이벤트가 안전 지연을 통과할 만큼 과거이면 전부 정상 처리되고
    # 커서가 최대 id로 전진한다.
    db = FakeSupabase(
        {"app_event_cursor": _cursor(last_event_id=0), "data_events": _events([1, 2, 3])}
    )
    disp = _RecordingDispatcher()
    result = _poller(db, disp).poll_once()

    assert disp.seen == [1, 2, 3]
    assert result["polled"] == 3
    assert result["last_id"] == 3
    assert db.rows("app_event_cursor")[0]["last_event_id"] == 3
