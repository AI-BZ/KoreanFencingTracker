"""Phase 6 카카오 알림톡 디스패처 단위 테스트 (페이크 Supabase 클라이언트).

검증:
  1. 카카오 설정이 비어 있어도 _send_kakao가 예외 없이 'pending' 로그를 남긴다.
  2. 회원에게 전화번호가 없으면 'pending'(전화번호 없음) 로그를 남긴다.
  3. 멱등성: 이미 보낸 이벤트면 재발송/재로그하지 않는다.

실행:
  PYTHONPATH=".:./packages:./services/app" python3 services/app/tests/test_dispatcher_kakao.py
"""
from __future__ import annotations

import sys
from typing import Any


# ----------------------------------------------------------------- fake supabase

class _FakeQuery:
    def __init__(self, table_name: str, store: dict):
        self._t = table_name
        self._store = store
        self._inserted: list[dict] = []

    # select/eq/in_/limit/order 등은 self를 반환해 체이닝 흉내
    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def in_(self, *_a, **_k):
        return self

    def gt(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def single(self):
        return self

    def insert(self, row):
        self._pending_insert = row
        return self

    def update(self, *_a, **_k):
        return self

    def execute(self):
        # 테이블별로 동작 분기
        if getattr(self, "_pending_insert", None) is not None:
            self._store.setdefault(self._t, []).append(self._pending_insert)
            return _Resp([{"id": "fake-id", **self._pending_insert}])
        # select 결과
        if self._t == "members":
            return _Resp(self._store.get("members_select", []))
        if self._t == "app_notification_log":
            return _Resp(self._store.get("log_select", []))
        return _Resp([])


class _Resp:
    def __init__(self, data: Any):
        self.data = data


class _FakeDB:
    def __init__(self, store: dict):
        self._store = store

    def table(self, name: str):
        return _FakeQuery(name, self._store)


# ---------------------------------------------------------------------- helpers

def _logs(store: dict) -> list[dict]:
    return store.get("app_notification_log", [])


def _make_event() -> dict:
    return {
        "id": 101,
        "event_type": "ranking.updated",
        "entity_type": "player",
        "entity_id": 5,
        "data": {"player_name": "박소윤"},
    }


# ------------------------------------------------------------------------- tests

def test_no_credentials_writes_pending():
    from services.app.app.pipeline.dispatcher import NotificationDispatcher

    store: dict = {
        "members_select": [{"phone": "010-1234-5678", "phone_country_code": "", "contact_phone": None}],
        "log_select": [],  # 아직 보낸 적 없음
    }
    disp = NotificationDispatcher(supabase=_FakeDB(store))

    # 자격증명 비어있는 기본 상태 → not_configured → pending 로그
    disp._send_kakao("member-1", _make_event())

    logs = _logs(store)
    assert len(logs) == 1, f"기대 1개 로그, 실제 {len(logs)}"
    assert logs[0]["channel"] == "kakao_alimtalk"
    assert logs[0]["status"] == "pending", logs[0]
    print("OK test_no_credentials_writes_pending:", logs[0]["status"], "|", logs[0]["error_message"])


def test_no_phone_writes_pending():
    from services.app.app.pipeline.dispatcher import NotificationDispatcher

    store: dict = {
        "members_select": [{"phone": "", "phone_country_code": "", "contact_phone": None}],
        "log_select": [],
    }
    disp = NotificationDispatcher(supabase=_FakeDB(store))

    disp._send_kakao("member-2", _make_event())

    logs = _logs(store)
    assert len(logs) == 1, f"기대 1개 로그, 실제 {len(logs)}"
    assert logs[0]["status"] == "pending", logs[0]
    assert "전화번호" in (logs[0]["error_message"] or ""), logs[0]
    print("OK test_no_phone_writes_pending:", logs[0]["error_message"])


def test_idempotent_skips():
    from services.app.app.pipeline.dispatcher import NotificationDispatcher

    store: dict = {
        "members_select": [{"phone": "010-1234-5678", "phone_country_code": "", "contact_phone": None}],
        "log_select": [{"id": "already"}],  # 이미 보낸 기록 존재
    }
    disp = NotificationDispatcher(supabase=_FakeDB(store))

    disp._send_kakao("member-3", _make_event())

    logs = _logs(store)
    assert len(logs) == 0, f"멱등성 위반: 재로그 발생 {logs}"
    print("OK test_idempotent_skips: 재발송/재로그 없음")


def test_sender_never_raises_without_httpx():
    # KakaoAlimtalkSender.send 는 설정이 없으면 not_configured, 예외 없음.
    from services.app.app.pipeline.kakao import KakaoAlimtalkSender

    sender = KakaoAlimtalkSender()
    result = sender.send(to_phone="010-1234-5678", event=_make_event())
    assert isinstance(result, dict) and "status" in result, result
    assert result["status"] in ("not_configured", "pending", "failed"), result
    print("OK test_sender_never_raises_without_httpx:", result["status"])


def test_phone_normalization():
    from services.app.app.pipeline.kakao import _normalize_phone, build_recipient_phone

    assert _normalize_phone("010-1234-5678") == "01012345678"
    assert _normalize_phone("+82 10-1234-5678") == "01012345678"
    assert _normalize_phone("8210-1234-5678") == "01012345678"
    assert _normalize_phone("123") is None
    assert build_recipient_phone({"phone": "010-1111-2222"}) == "010-1111-2222"
    assert build_recipient_phone({"phone": "", "contact_phone": "010-3333-4444"}) == "010-3333-4444"
    assert build_recipient_phone({}) is None
    print("OK test_phone_normalization")


if __name__ == "__main__":
    failures = 0
    for fn in [
        test_no_credentials_writes_pending,
        test_no_phone_writes_pending,
        test_idempotent_skips,
        test_sender_never_raises_without_httpx,
        test_phone_normalization,
    ]:
        try:
            fn()
        except AssertionError as e:
            failures += 1
            print("FAIL", fn.__name__, ":", e)
        except Exception as e:  # noqa: BLE001
            failures += 1
            print("ERROR", fn.__name__, ":", e)
    if failures:
        print(f"\n{failures} test(s) failed")
        sys.exit(1)
    print("\nAll dispatcher kakao tests passed")
