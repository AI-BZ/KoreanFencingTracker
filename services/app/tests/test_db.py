"""Tests for app-local DB client (services.app.app.db.get_app_db).

Pins the RLS-lockdown Part A behavior:
  - SUPABASE_SERVICE_KEY set  → service_role client via create_client(url, service_key)
  - SUPABASE_SERVICE_KEY unset → anon fallback (shared_core get_supabase_client)
  - fallback logs a warning at most once (module-level guard, no repeat spam)
  - service_role client is cached (singleton); create_client called once
"""
from __future__ import annotations

import logging

import pytest

from services.app.app import db as dbmod


@pytest.fixture(autouse=True)
def _reset():
    """각 테스트마다 싱글턴/경고 상태 초기화 (모듈 전역 상태 격리)."""
    dbmod.reset_app_db()
    yield
    dbmod.reset_app_db()


class _Sentinel:
    def __init__(self, tag: str):
        self.tag = tag


def test_service_role_path_uses_service_key(monkeypatch):
    """service key가 설정되면 create_client(url, service_key)로 service_role 경로."""
    calls: list[tuple[str, str]] = []

    def fake_create_client(url, key):
        calls.append((url, key))
        return _Sentinel("service_role")

    monkeypatch.setattr(dbmod, "create_client", fake_create_client)
    # anon 폴백이 호출되면 실패로 간주 (service_role 경로여야 함).
    monkeypatch.setattr(
        dbmod, "get_supabase_client",
        lambda: pytest.fail("anon fallback이 호출되면 안 됨"),
    )
    monkeypatch.setattr(dbmod.settings, "SUPABASE_URL", "https://svc.example")
    monkeypatch.setattr(dbmod.settings, "SUPABASE_SERVICE_KEY", "svc-secret-key")

    client = dbmod.get_app_db()

    assert isinstance(client, _Sentinel) and client.tag == "service_role"
    assert calls == [("https://svc.example", "svc-secret-key")]


def test_service_role_client_is_singleton(monkeypatch):
    """service_role 클라이언트는 싱글턴 — create_client는 1회만 호출."""
    count = {"n": 0}

    def fake_create_client(url, key):
        count["n"] += 1
        return _Sentinel("service_role")

    monkeypatch.setattr(dbmod, "create_client", fake_create_client)
    monkeypatch.setattr(dbmod.settings, "SUPABASE_URL", "https://svc.example")
    monkeypatch.setattr(dbmod.settings, "SUPABASE_SERVICE_KEY", "svc-secret-key")

    first = dbmod.get_app_db()
    second = dbmod.get_app_db()

    assert first is second
    assert count["n"] == 1


def test_anon_fallback_when_service_key_missing(monkeypatch, caplog):
    """service key 미설정 → anon 폴백 + warning 1회."""
    anon = _Sentinel("anon")
    monkeypatch.setattr(dbmod, "get_supabase_client", lambda: anon)
    # create_client가 호출되면 실패로 간주 (service 경로를 타면 안 됨).
    monkeypatch.setattr(
        dbmod, "create_client",
        lambda *a, **k: pytest.fail("service key 없는데 create_client 호출됨"),
    )
    monkeypatch.setattr(dbmod.settings, "SUPABASE_SERVICE_KEY", "")

    with caplog.at_level(logging.WARNING, logger="app.db"):
        client = dbmod.get_app_db()

    assert client is anon
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "폴백" in warnings[0].getMessage()


def test_anon_fallback_warns_only_once(monkeypatch, caplog):
    """폴백을 여러 번 타도 warning은 1회만 (반복 로그 방지)."""
    anon = _Sentinel("anon")
    monkeypatch.setattr(dbmod, "get_supabase_client", lambda: anon)
    monkeypatch.setattr(dbmod.settings, "SUPABASE_SERVICE_KEY", "")

    with caplog.at_level(logging.WARNING, logger="app.db"):
        for _ in range(5):
            assert dbmod.get_app_db() is anon

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_service_role_creation_failure_falls_back_to_anon(monkeypatch, caplog):
    """service_role 클라이언트 생성이 실패하면 안전측으로 anon 폴백."""
    anon = _Sentinel("anon")
    monkeypatch.setattr(dbmod, "get_supabase_client", lambda: anon)

    def boom(url, key):
        raise RuntimeError("bad service key")

    monkeypatch.setattr(dbmod, "create_client", boom)
    monkeypatch.setattr(dbmod.settings, "SUPABASE_URL", "https://svc.example")
    monkeypatch.setattr(dbmod.settings, "SUPABASE_SERVICE_KEY", "broken-key")

    with caplog.at_level(logging.WARNING, logger="app.db"):
        client = dbmod.get_app_db()

    assert client is anon
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "생성 실패" in warnings[0].getMessage()


def test_injected_client_bypasses_get_app_db(monkeypatch):
    """poller/dispatcher에 supabase가 주입되면 get_app_db()를 타지 않는다(테스트 격리)."""
    from services.app.app.pipeline.dispatcher import NotificationDispatcher
    from services.app.app.pipeline.poller import EventPoller
    from services.app.tests._fakes import FakeSupabase

    fake = FakeSupabase()
    # get_app_db가 불리면 실패 — 주입된 클라이언트만 써야 한다.
    # poller/dispatcher는 `from ..db import get_app_db`로 모듈 로컬 이름을 참조하므로
    # 각 모듈의 이름을 패치해야 실제 호출을 가로챌 수 있다.
    import services.app.app.pipeline.dispatcher as _disp_mod
    import services.app.app.pipeline.poller as _poll_mod
    for _m in (_disp_mod, _poll_mod):
        monkeypatch.setattr(
            _m, "get_app_db", lambda: pytest.fail("주입 상태에서 get_app_db 호출됨")
        )

    disp = NotificationDispatcher(supabase=fake)
    poller = EventPoller(supabase=fake)
    assert disp.db is fake
    assert poller.db is fake
