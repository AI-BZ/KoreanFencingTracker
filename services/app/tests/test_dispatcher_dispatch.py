"""Characterization tests for NotificationDispatcher.dispatch (end-to-end of one event).

Pins the orchestration contract:
  - unmapped event_type → no-op summary (category None)
  - channel gate: in_app pref off → nothing sent
  - idempotency: second dispatch of the same event does not re-send
  - exception absorption: dispatch NEVER raises (target resolution failure and
    per-member preference failure are both swallowed)

To isolate the in_app channel, preferences are seeded with web_push=False so the
Phase-4 web-push path (which depends on env VAPID keys) does not run.
"""
from __future__ import annotations

from services.app.app.pipeline.dispatcher import NotificationDispatcher
from services.app.tests._fakes import FakeSupabase


def _pref(member_id: str, category: str, *, in_app=True, web_push=False, kakao=False) -> dict:
    return {
        "member_id": member_id,
        "category": category,
        "in_app": in_app,
        "web_push": web_push,
        "kakao_alimtalk": kakao,
    }


def _base_tables(prefs: list[dict], members: list[dict]) -> dict:
    return {
        "members": members,
        "app_notification_preferences": prefs,
        "notifications": [],
        "app_notification_log": [],
    }


_RANKING_EVENT = {"id": 101, "event_type": "ranking.updated", "data": {"player_id": 5}}


# ------------------------------------------------------------------ mapping gate

def test_dispatch_unmapped_event_is_noop():
    db = FakeSupabase(_base_tables([], []))
    summary = NotificationDispatcher(supabase=db).dispatch(
        {"id": 1, "event_type": "player.deleted", "data": {}}
    )
    assert summary == {"event_id": 1, "category": None, "targets": 0, "in_app": 0, "web_push": 0}
    assert db.count("notifications") == 0


def test_dispatch_mapped_but_no_targets():
    db = FakeSupabase(_base_tables([], []))  # no members
    summary = NotificationDispatcher(supabase=db).dispatch(_RANKING_EVENT)
    assert summary["category"] == "ranking_change"
    assert summary["targets"] == 0
    assert summary["in_app"] == 0


# -------------------------------------------------------------- happy path + gate

def test_dispatch_sends_in_app_when_enabled():
    db = FakeSupabase(
        _base_tables(
            prefs=[_pref("m1", "ranking_change", in_app=True, web_push=False)],
            members=[{"id": "m1", "player_id": 5}],
        )
    )
    summary = NotificationDispatcher(supabase=db).dispatch(_RANKING_EVENT)
    assert summary["targets"] == 1
    assert summary["in_app"] == 1
    assert db.count("notifications") == 1


def test_dispatch_channel_gate_in_app_off():
    db = FakeSupabase(
        _base_tables(
            prefs=[_pref("m1", "ranking_change", in_app=False, web_push=False)],
            members=[{"id": "m1", "player_id": 5}],
        )
    )
    summary = NotificationDispatcher(supabase=db).dispatch(_RANKING_EVENT)
    assert summary["targets"] == 1  # target was resolved...
    assert summary["in_app"] == 0   # ...but pref off → nothing sent
    assert db.count("notifications") == 0


def test_dispatch_idempotent_second_run():
    db = FakeSupabase(
        _base_tables(
            prefs=[_pref("m1", "ranking_change", in_app=True, web_push=False)],
            members=[{"id": "m1", "player_id": 5}],
        )
    )
    disp = NotificationDispatcher(supabase=db)
    first = disp.dispatch(_RANKING_EVENT)
    second = disp.dispatch(_RANKING_EVENT)
    assert first["in_app"] == 1
    assert second["in_app"] == 0  # blocked by _already_sent
    assert db.count("notifications") == 1  # not duplicated


# ---------------------------------------------------------- exception absorption

def test_dispatch_absorbs_target_resolution_failure():
    # members table raises → _resolve_targets fails → summary error, no exception.
    db = FakeSupabase(
        _base_tables(prefs=[], members=[{"id": "m1", "player_id": 5}]),
        raise_on=["members"],
    )
    summary = NotificationDispatcher(supabase=db).dispatch(_RANKING_EVENT)
    assert summary["error"] == "resolve_failed"
    assert summary["in_app"] == 0


def test_dispatch_absorbs_preference_lookup_failure():
    # target resolves, but preference lookup raises → member skipped, no exception.
    db = FakeSupabase(
        _base_tables(prefs=[], members=[{"id": "m1", "player_id": 5}]),
        raise_on=["app_notification_preferences"],
    )
    summary = NotificationDispatcher(supabase=db).dispatch(_RANKING_EVENT)
    assert summary["targets"] == 1
    assert summary["in_app"] == 0
    assert db.count("notifications") == 0
