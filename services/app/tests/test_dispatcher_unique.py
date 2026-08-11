"""Tests for the UNIQUE-constraint defense on app_notification_log (P1-3).

Migration 022 adds UNIQUE(member_id, channel, event_type, event_id) so that two
pollers racing the same event batch cannot both INSERT a send log. This pins the
dispatcher's cooperation with that constraint:

    (a) _already_sent lookup raising → warning + False (send still attempted, but
        observable), never propagates.
    (b) _log INSERT hitting a unique violation (another worker won the race) →
        swallowed as debug ("중복 로그 스킵"), not a warning, never propagates.
    (c) normal path: app-level idempotency still short-circuits the second send
        for the same (member, channel, event_type, event_id).
"""
from __future__ import annotations

import logging

from services.app.app.pipeline.dispatcher import (
    NotificationDispatcher,
    _is_unique_violation,
)
from services.app.tests._fakes import FakeSupabase, _Table

_EVENT = {"id": 202, "event_type": "ranking.updated", "entity_id": 7, "data": {}}


def _send_in_app(db) -> bool:
    disp = NotificationDispatcher(supabase=db)
    return disp._send_in_app(
        member_id="m1",
        category="ranking_change",
        title="랭킹이 변동되었습니다",
        body="박소윤님의 랭킹 정보가 업데이트되었습니다.",
        link="https://data.fencingmind.ai/rankings",
        event=_EVENT,
    )


# --------------------------------------------------------------------------- (a)
def test_already_sent_lookup_error_warns_and_returns_false(caplog):
    # raise_on app_notification_log → the idempotency SELECT raises.
    db = FakeSupabase({"app_notification_log": []}, raise_on=["app_notification_log"])
    disp = NotificationDispatcher(supabase=db)

    with caplog.at_level(logging.WARNING, logger="app.pipeline.dispatcher"):
        result = disp._already_sent("m1", "in_app", _EVENT)

    assert result is False  # UNIQUE 제약이 최종 방어선 → 발송은 계속하되 관측 가능하게
    assert any("중복 확인 실패" in r.message for r in caplog.records)


def test_dispatch_does_not_raise_when_log_table_errors():
    # app_notification_log raises on both the SELECT and the log INSERT; the
    # in-app send must still complete (notification inserted) without propagating.
    db = FakeSupabase(
        {"notifications": [], "app_notification_log": []},
        raise_on=["app_notification_log"],
    )
    assert _send_in_app(db) is True
    assert db.count("notifications") == 1


# --------------------------------------------------------------------------- (b)
class _UniqueViolationTable(_Table):
    """_Table whose INSERT into app_notification_log raises a unique violation.

    Every other op (select/insert into other tables) delegates to the real fake,
    so the send path runs normally up to the log write that "loses" the race.
    """

    def execute(self):
        if self._op == "insert" and self._name == "app_notification_log":
            raise Exception(
                'duplicate key value violates unique constraint '
                '"uq_app_notif_log_member_channel_event" (SQLSTATE 23505)'
            )
        return super().execute()


class _UniqueViolationFake(FakeSupabase):
    def table(self, name: str) -> _Table:
        return _UniqueViolationTable(self, name)


def test_helper_classifies_unique_violation():
    assert _is_unique_violation(Exception("... (SQLSTATE 23505)"))
    assert _is_unique_violation(Exception("duplicate key value"))
    assert _is_unique_violation(Exception("violates UNIQUE constraint"))
    assert not _is_unique_violation(Exception("connection reset"))


def test_log_unique_violation_is_swallowed_as_debug(caplog):
    db = _UniqueViolationFake({"notifications": [], "app_notification_log": []})

    with caplog.at_level(logging.DEBUG, logger="app.pipeline.dispatcher"):
        # notifications insert succeeds; the 'sent' log INSERT hits the UNIQUE
        # violation → must be swallowed, and _send_in_app returns True (the
        # notification itself was created).
        assert _send_in_app(db) is True

    # notification row was created despite the log write losing the race.
    assert db.count("notifications") == 1
    # classified as a benign duplicate: debug message, no WARNING about log 실패.
    assert any("중복 로그 스킵" in r.message for r in caplog.records)
    assert not any(
        r.levelno >= logging.WARNING and "로그 기록 실패" in r.message
        for r in caplog.records
    )


# --------------------------------------------------------------------------- (c)
def test_normal_path_second_send_is_idempotent():
    # The fake does not enforce UNIQUE, but the app-level _already_sent guard
    # must still short-circuit a duplicate send for the same event key.
    db = FakeSupabase({"notifications": [], "app_notification_log": []})
    assert _send_in_app(db) is True
    assert _send_in_app(db) is False  # blocked by its own 'sent' log
    assert db.count("notifications") == 1
    # exactly one send log written for this (member, channel, event_type, event_id)
    logs = [
        row
        for row in db.rows("app_notification_log")
        if row.get("channel") == "in_app" and row.get("event_id") == _EVENT["id"]
    ]
    assert len(logs) == 1
