"""Sanity tests for the in-memory fake Supabase client (services/app/tests/_fakes.py).

These guard the test infrastructure: the whole reason this fake exists is that the
pipeline depends on filters actually filtering. If ``.eq/.in_/.gt/.order/.limit``
regressed to no-ops, every pipeline test below would silently lose its teeth — so
we pin the fake's behavior here first.
"""
from __future__ import annotations

import pytest

from services.app.tests._fakes import FakeSupabase


def _seed() -> FakeSupabase:
    return FakeSupabase(
        {
            "members": [
                {"id": "m1", "player_id": 5},
                {"id": "m2", "player_id": 7},
                {"id": "m3", "player_id": 5},
            ]
        }
    )


def test_eq_filters():
    db = _seed()
    res = db.table("members").select("id").eq("player_id", 5).execute()
    assert {r["id"] for r in res.data} == {"m1", "m3"}


def test_in_filters():
    db = _seed()
    res = db.table("members").select("id").in_("player_id", [7, 999]).execute()
    assert [r["id"] for r in res.data] == ["m2"]


def test_gt_and_order_and_limit():
    db = FakeSupabase({"data_events": [{"id": i} for i in (3, 1, 5, 2, 4)]})
    res = (
        db.table("data_events")
        .select("*")
        .gt("id", 2)
        .order("id")
        .limit(2)
        .execute()
    )
    # gt(2) → {3,4,5}; order asc → 3,4,5; limit 2 → [3,4]
    assert [r["id"] for r in res.data] == [3, 4]


def test_order_desc():
    db = FakeSupabase({"t": [{"id": 1}, {"id": 3}, {"id": 2}]})
    res = db.table("t").select("*").order("id", desc=True).execute()
    assert [r["id"] for r in res.data] == [3, 2, 1]


def test_insert_autoassigns_id_and_persists():
    db = FakeSupabase({"notifications": []})
    res = db.table("notifications").insert({"title": "hi"}).execute()
    assert res.data[0]["id"] == 1
    assert res.data[0]["title"] == "hi"
    assert db.count("notifications") == 1
    # second insert increments
    res2 = db.table("notifications").insert({"title": "yo"}).execute()
    assert res2.data[0]["id"] == 2


def test_insert_preserves_explicit_id():
    db = FakeSupabase({"data_events": []})
    res = db.table("data_events").insert({"id": 42, "event_type": "x"}).execute()
    assert res.data[0]["id"] == 42


def test_update_mutates_matching_only():
    db = FakeSupabase(
        {"app_event_cursor": [{"id": 1, "last_event_id": 0}, {"id": 2, "last_event_id": 0}]}
    )
    db.table("app_event_cursor").update({"last_event_id": 99}).eq("id", 1).execute()
    rows = {r["id"]: r["last_event_id"] for r in db.rows("app_event_cursor")}
    assert rows == {1: 99, 2: 0}


def test_upsert_inserts_then_replaces_on_conflict():
    db = FakeSupabase({"app_event_cursor": []})
    db.table("app_event_cursor").upsert({"id": 1, "last_event_id": 0}).execute()
    assert db.count("app_event_cursor") == 1
    db.table("app_event_cursor").upsert({"id": 1, "last_event_id": 5}).execute()
    assert db.count("app_event_cursor") == 1  # replaced, not duplicated
    assert db.rows("app_event_cursor")[0]["last_event_id"] == 5


def test_upsert_composite_conflict_key():
    db = FakeSupabase({"prefs": [{"member_id": "m1", "category": "x", "in_app": True}]})
    db.table("prefs").upsert(
        {"member_id": "m1", "category": "x", "in_app": False}, on_conflict="member_id,category"
    ).execute()
    assert db.count("prefs") == 1
    assert db.rows("prefs")[0]["in_app"] is False


def test_single_returns_object_or_none():
    db = FakeSupabase({"t": [{"id": 1}]})
    assert db.table("t").select("*").eq("id", 1).single().execute().data == {"id": 1}
    assert db.table("t").select("*").eq("id", 99).single().execute().data is None


def test_raise_on_forces_failure():
    db = FakeSupabase({"members": [{"id": "m1"}]}, raise_on=["members"])
    with pytest.raises(RuntimeError):
        db.table("members").select("id").execute()


def test_select_returns_independent_copies():
    db = FakeSupabase({"t": [{"id": 1, "v": "a"}]})
    got = db.table("t").select("*").execute().data
    got[0]["v"] = "MUTATED"
    assert db.rows("t")[0]["v"] == "a"  # store not affected by caller mutation
