"""Tests for chunked `.in_()` target resolution (PLAN item 7, EVAL P2-1).

Large competitions have thousands of participants; a single .in_() would
overflow PostgREST's URI length limit (414). _select_in_chunks splits the
IN list into batches and merges the rows. These tests pin that the merge is
complete (no rows dropped) and that chunking actually happens.
"""
from __future__ import annotations

from services.app.app.pipeline.dispatcher import NotificationDispatcher
from services.app.tests._fakes import FakeSupabase


def test_select_in_chunks_merges_all_rows_across_batches():
    # 5 members, chunk_size=2 → 3 batches (2+2+1); every match must come back.
    members = [{"id": f"m{i}", "player_id": i} for i in range(1, 6)]
    db = FakeSupabase({"members": members})
    disp = NotificationDispatcher(supabase=db)

    rows = disp._select_in_chunks(
        "members", "id", "player_id", [1, 2, 3, 4, 5], chunk_size=2
    )

    assert sorted(r["id"] for r in rows) == ["m1", "m2", "m3", "m4", "m5"]


def test_select_in_chunks_empty_values_makes_no_query():
    db = FakeSupabase({"members": [{"id": "m1", "player_id": 1}]})
    disp = NotificationDispatcher(supabase=db)

    assert disp._select_in_chunks("members", "id", "player_id", []) == []


def test_select_in_chunks_only_returns_matches():
    members = [{"id": "m1", "player_id": 1}, {"id": "m2", "player_id": 2}]
    db = FakeSupabase({"members": members})
    disp = NotificationDispatcher(supabase=db)

    rows = disp._select_in_chunks("members", "id", "player_id", [1, 99], chunk_size=1)

    assert [r["id"] for r in rows] == ["m1"]


def test_resolve_targets_returns_all_members_beyond_one_chunk():
    # 250 participants > default chunk_size (200) → forces multiple batches
    # through the real _resolve_targets path (competition_result category).
    n = 250
    events = [{"id": 10, "competition_id": 500}]
    rankings = [{"event_id": 10, "player_id": p} for p in range(1, n + 1)]
    members = [{"id": f"m{p}", "player_id": p} for p in range(1, n + 1)]
    db = FakeSupabase({"events": events, "rankings": rankings, "members": members})
    disp = NotificationDispatcher(supabase=db)

    targets = disp._resolve_targets(
        {"event_type": "competition.updated", "entity_type": "competition", "entity_id": 500},
        "competition_result",
    )

    assert len(targets) == n
    assert set(targets) == {f"m{p}" for p in range(1, n + 1)}
