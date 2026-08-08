"""Characterization tests for services/app/app/pipeline/event_types.py.

Pins the current event_type→category mapping and message building. These are
"golden" assertions of what the code does *today*, including its narrowness:
only 4 event types map, and several plausible siblings (ranking.created,
competition.deleted, ...) deliberately do NOT.
"""
from __future__ import annotations

import pytest

from services.app.app.pipeline import event_types as et


# ------------------------------------------------------------ category_for_event

@pytest.mark.parametrize(
    "event_type, expected",
    [
        ("ranking.updated", et.CATEGORY_RANKING_CHANGE),
        ("competition.created", et.CATEGORY_COMPETITION_RESULT),
        ("competition.updated", et.CATEGORY_COMPETITION_RESULT),
        ("event.updated", et.CATEGORY_COMPETITION_RESULT),
    ],
)
def test_mapped_event_types(event_type, expected):
    assert et.category_for_event(event_type) == expected


@pytest.mark.parametrize(
    "event_type",
    [
        "",
        "player.deleted",
        "competition.deleted",
        "event.created",          # note: only event.updated is mapped, not event.created
        "ranking.created",        # note: only ranking.updated is mapped
        "ranking.changed",
        "pipeline.started",
        "validation.failed",
        "unknown",
    ],
)
def test_unmapped_event_types_return_none(event_type):
    assert et.category_for_event(event_type) is None


def test_category_for_event_handles_none():
    # category_for_event(None) → "" lookup → None, no exception.
    assert et.category_for_event(None) is None


# ------------------------------------------------------------------ build_message

def test_build_message_ranking_change_uses_player_name():
    title, body, link = et.build_message(
        {"event_type": "ranking.updated", "data": {"player_name": "박소윤"}}
    )
    assert title == "랭킹이 변동되었습니다"
    assert "박소윤" in body
    assert link == f"{et.DATA_BASE_URL}/rankings"


def test_build_message_ranking_change_falls_back_to_name_then_default():
    _, body_name, _ = et.build_message(
        {"event_type": "ranking.updated", "data": {"name": "홍길동"}}
    )
    assert "홍길동" in body_name

    _, body_default, _ = et.build_message({"event_type": "ranking.updated", "data": {}})
    assert "선수" in body_default  # default label when no name present


def test_build_message_competition_result_uses_name_and_entity_link():
    title, body, link = et.build_message(
        {
            "event_type": "competition.updated",
            "entity_id": 321,
            "data": {"competition_name": "회장배"},
        }
    )
    assert title == "대회 결과가 업데이트되었습니다"
    assert "회장배" in body
    assert link == f"{et.DATA_BASE_URL}/competition/321"


def test_build_message_competition_result_link_without_entity_id():
    _, _, link = et.build_message({"event_type": "event.updated", "data": {}})
    # No entity_id → link falls back to bare base url (not /competition/None)
    assert link == et.DATA_BASE_URL


def test_build_message_unmapped_returns_generic_default():
    title, body, link = et.build_message({"event_type": "something.unmapped", "data": {}})
    assert title == "FencingMind 알림"
    assert body == "새로운 소식이 있습니다."
    assert link == et.DATA_BASE_URL


def test_build_message_tolerates_missing_data_key():
    # data absent entirely → (event.get("data") or {}) → no KeyError.
    title, body, link = et.build_message({"event_type": "ranking.updated"})
    assert title and body and link
