"""Characterization tests for NotificationDispatcher target resolution.

Covers ``_resolve_targets`` and ``_players_for_result`` — the queries that turn a
data_events row into the set of member ids to notify. The fake actually filters,
so these assert the real ``members.player_id`` / ``rankings.event_id`` scoping.
"""
from __future__ import annotations

from services.app.app.pipeline import event_types as et
from services.app.app.pipeline.dispatcher import NotificationDispatcher
from services.app.tests._fakes import FakeSupabase


def _disp(db: FakeSupabase) -> NotificationDispatcher:
    return NotificationDispatcher(supabase=db)


# ---------------------------------------------------------- ranking_change targets

def test_ranking_targets_from_data_player_id():
    db = FakeSupabase(
        {"members": [{"id": "m1", "player_id": 5}, {"id": "m2", "player_id": 9}]}
    )
    event = {"id": 1, "event_type": "ranking.updated", "data": {"player_id": 5}}
    ids = _disp(db)._resolve_targets(event, et.CATEGORY_RANKING_CHANGE)
    assert ids == ["m1"]


def test_ranking_targets_fall_back_to_entity_id_for_player_entity():
    db = FakeSupabase({"members": [{"id": "m1", "player_id": 5}]})
    event = {
        "id": 1,
        "event_type": "ranking.updated",
        "entity_type": "player",
        "entity_id": 5,
        "data": {},
    }
    ids = _disp(db)._resolve_targets(event, et.CATEGORY_RANKING_CHANGE)
    assert ids == ["m1"]


def test_ranking_targets_empty_when_no_player_id():
    db = FakeSupabase({"members": [{"id": "m1", "player_id": 5}]})
    event = {"id": 1, "event_type": "ranking.updated", "entity_type": "organization", "data": {}}
    ids = _disp(db)._resolve_targets(event, et.CATEGORY_RANKING_CHANGE)
    assert ids == []


def test_ranking_targets_multiple_members_same_player():
    db = FakeSupabase(
        {
            "members": [
                {"id": "m1", "player_id": 5},
                {"id": "m2", "player_id": 5},
                {"id": "m3", "player_id": 6},
            ]
        }
    )
    event = {"id": 1, "event_type": "ranking.updated", "data": {"player_id": 5}}
    ids = _disp(db)._resolve_targets(event, et.CATEGORY_RANKING_CHANGE)
    assert set(ids) == {"m1", "m2"}


# ----------------------------------------------------- competition_result targets

def test_competition_result_event_scope():
    # event.updated → event_ids = [entity_id]; rankings on that event → player_ids → members
    db = FakeSupabase(
        {
            "rankings": [
                {"event_id": 100, "player_id": 5},
                {"event_id": 100, "player_id": 7},
                {"event_id": 200, "player_id": 9},  # different event → excluded
            ],
            "members": [
                {"id": "m5", "player_id": 5},
                {"id": "m7", "player_id": 7},
                {"id": "m9", "player_id": 9},
            ],
        }
    )
    event = {"id": 1, "event_type": "event.updated", "entity_id": 100, "data": {}}
    ids = _disp(db)._resolve_targets(event, et.CATEGORY_COMPETITION_RESULT)
    assert set(ids) == {"m5", "m7"}


def test_competition_result_competition_scope_expands_events():
    # competition.created → events.competition_id lookup → event_ids → rankings → members
    db = FakeSupabase(
        {
            "events": [
                {"id": 100, "competition_id": 50},
                {"id": 101, "competition_id": 50},
                {"id": 300, "competition_id": 99},  # different competition → excluded
            ],
            "rankings": [
                {"event_id": 100, "player_id": 5},
                {"event_id": 101, "player_id": 7},
                {"event_id": 300, "player_id": 9},
            ],
            "members": [
                {"id": "m5", "player_id": 5},
                {"id": "m7", "player_id": 7},
                {"id": "m9", "player_id": 9},
            ],
        }
    )
    event = {"id": 1, "event_type": "competition.created", "entity_id": 50, "data": {}}
    ids = _disp(db)._resolve_targets(event, et.CATEGORY_COMPETITION_RESULT)
    assert set(ids) == {"m5", "m7"}


def test_competition_result_empty_when_no_players():
    db = FakeSupabase({"rankings": [], "members": [{"id": "m1", "player_id": 5}]})
    event = {"id": 1, "event_type": "event.updated", "entity_id": 100, "data": {}}
    ids = _disp(db)._resolve_targets(event, et.CATEGORY_COMPETITION_RESULT)
    assert ids == []


# ------------------------------------------------------- _players_for_result direct

def test_players_for_result_none_entity_id_returns_empty():
    db = FakeSupabase({})
    event = {"id": 1, "event_type": "event.updated", "entity_id": None}
    assert _disp(db)._players_for_result(event) == set()


def test_players_for_result_competition_without_events_returns_empty():
    db = FakeSupabase({"events": [], "rankings": []})
    event = {"id": 1, "event_type": "competition.updated", "entity_id": 50}
    assert _disp(db)._players_for_result(event) == set()


def test_players_for_result_dedupes_player_ids():
    db = FakeSupabase(
        {
            "rankings": [
                {"event_id": 100, "player_id": 5},
                {"event_id": 100, "player_id": 5},  # duplicate
                {"event_id": 100, "player_id": None},  # skipped
            ]
        }
    )
    event = {"id": 1, "event_type": "event.updated", "entity_id": 100}
    assert _disp(db)._players_for_result(event) == {5}


def test_players_for_result_unmapped_prefix_returns_empty():
    # event_type not starting with "event." or "competition." → no event_ids → empty
    db = FakeSupabase({"rankings": [{"event_id": 100, "player_id": 5}]})
    event = {"id": 1, "event_type": "ranking.updated", "entity_id": 100}
    assert _disp(db)._players_for_result(event) == set()
