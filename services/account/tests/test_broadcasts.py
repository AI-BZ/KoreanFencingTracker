"""Broadcast (배치 이메일) 서비스/엔드포인트 테스트

- Supabase / EmailService(Resend) 는 모두 mock → 실제 네트워크 발송 없음.
- async 로직은 asyncio.run 으로 구동 (pytest-asyncio 설정 비의존).
"""
import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.account.app.broadcasts import service


# ---------------------------------------------------------------------------
# Fake Supabase (query builder mimic)
# ---------------------------------------------------------------------------

class _FakeResult:
    def __init__(self, data=None, count=None):
        self.data = data
        self.count = count


class _FakeQuery:
    def __init__(self, table_name, sb):
        self.table_name = table_name
        self.sb = sb
        self.op = None
        self.payload = None
        self.filters = {}
        self.count_mode = None
        self.email_not_null = False
        self._single = False
        self._limit = None

    def insert(self, payload):
        self.op = "insert"
        self.payload = payload
        return self

    def select(self, *cols, **kw):
        self.op = "select"
        self.count_mode = kw.get("count")
        return self

    def update(self, payload):
        self.op = "update"
        self.payload = payload
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    @property
    def not_(self):
        return self

    def is_(self, col, val):
        if col == "email":
            self.email_not_null = True
        return self

    def single(self):
        self._single = True
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def range(self, *a, **k):
        return self

    def execute(self):
        return self.sb._resolve(self)


class FakeSupabase:
    def __init__(self):
        self.broadcast_id = str(uuid.uuid4())
        self.broadcast = None
        self.all_members = []          # create 스냅샷용 전체 회원
        self.member_by_id = {}         # send 재확인/정보 조회용
        self.recipients = []           # 수신자 상태 (mutable)
        self._rid_seq = 0
        # recorders
        self.recipient_updates = []
        self.members_updates = []
        self.consent_logs = []
        self.broadcast_updates = []
        self.recipient_inserts = []

    def table(self, name):
        return _FakeQuery(name, self)

    def _resolve(self, q):
        name = q.table_name
        if name == "email_broadcasts":
            return self._resolve_broadcasts(q)
        if name == "members":
            return self._resolve_members(q)
        if name == "email_broadcast_recipients":
            return self._resolve_recipients(q)
        if name == "consent_logs":
            self.consent_logs.append(q.payload)
            return _FakeResult(data=[q.payload])
        return _FakeResult(data=[])

    def _resolve_broadcasts(self, q):
        if q.op == "insert":
            self.broadcast = {
                "id": self.broadcast_id,
                "status": "draft",
                "total_recipients": 0,
                "sent_count": 0,
                "failed_count": 0,
                "sent_at": None,
                **q.payload,
            }
            return _FakeResult(data=[self.broadcast])
        if q.op == "select":
            return _FakeResult(data=self.broadcast)
        if q.op == "update":
            self.broadcast_updates.append(q.payload)
            if self.broadcast:
                self.broadcast.update(q.payload)
            return _FakeResult(data=[self.broadcast])
        return _FakeResult(data=[])

    def _resolve_members(self, q):
        if q.op == "select":
            if q._single:
                return _FakeResult(data=self.member_by_id.get(q.filters.get("id")))
            res = list(self.all_members)
            consent = q.filters.get("marketing_consent")
            if consent is not None:
                res = [m for m in res if m.get("marketing_consent") == consent]
            if q.email_not_null:
                res = [m for m in res if m.get("email")]
            return _FakeResult(data=res)
        if q.op == "update":
            self.members_updates.append({"filters": q.filters, "payload": q.payload})
            mid = q.filters.get("id")
            if mid in self.member_by_id:
                self.member_by_id[mid].update(q.payload)
            return _FakeResult(data=[])
        return _FakeResult(data=[])

    def _resolve_recipients(self, q):
        if q.op == "insert":
            rows = q.payload if isinstance(q.payload, list) else [q.payload]
            inserted = []
            for row in rows:
                self._rid_seq += 1
                r = {
                    "id": str(self._rid_seq),
                    "error": None,
                    "sent_at": None,
                    **row,
                }
                self.recipients.append(r)
                inserted.append(r)
            self.recipient_inserts.extend(inserted)
            return _FakeResult(data=inserted)
        if q.op == "select":
            status = q.filters.get("status")
            matched = [r for r in self.recipients if r["status"] == status]
            if q.count_mode == "exact":
                return _FakeResult(data=[], count=len(matched))
            if q._limit is not None:
                matched = matched[: q._limit]
            return _FakeResult(data=matched)
        if q.op == "update":
            rid = q.filters.get("id")
            for r in self.recipients:
                if r["id"] == rid:
                    r.update(q.payload)
            self.recipient_updates.append((rid, q.payload))
            return _FakeResult(data=[])
        return _FakeResult(data=[])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SVC_SB = "services.account.app.broadcasts.service.get_supabase_client"
_SVC_EMAIL = "services.account.app.broadcasts.service.get_email_service"
_JWT_SETTINGS = "shared_core.auth.jwt.get_shared_auth_settings"


def _member(mid, email="u@fencingmind.ai", consent=True, name="회원"):
    return {
        "id": mid,
        "email": email,
        "full_name": name,
        "marketing_consent": consent,
        "preferred_language": None,
        "lang": None,
    }


def _fake_email_service():
    svc = MagicMock()
    svc.send_broadcast_email = AsyncMock(return_value=True)
    return svc


# ---------------------------------------------------------------------------
# 1. 스냅샷: marketing_consent=FALSE 회원 제외
# ---------------------------------------------------------------------------

class TestCreateBroadcastSnapshot:
    def test_snapshot_excludes_non_consenting_members(self):
        m1 = str(uuid.uuid4())  # consent True
        m2 = str(uuid.uuid4())  # consent False → 제외
        m3 = str(uuid.uuid4())  # consent True but email None → 제외
        fake = FakeSupabase()
        fake.all_members = [
            _member(m1, email="a@fencingmind.ai", consent=True),
            _member(m2, email="b@fencingmind.ai", consent=False),
            {"id": m3, "email": None, "marketing_consent": True},
        ]

        with patch(_SVC_SB, return_value=fake):
            result = service.create_broadcast(
                subject="공지", body_html="<p>hi</p>", created_by=str(uuid.uuid4())
            )

        assert result["recipient_count"] == 1
        inserted_member_ids = {r["member_id"] for r in fake.recipient_inserts}
        assert inserted_member_ids == {m1}
        assert m2 not in inserted_member_ids
        # total_recipients 갱신됨
        assert fake.broadcast["total_recipients"] == 1
        # 모든 수신자는 pending 으로 시작
        assert all(r["status"] == "pending" for r in fake.recipient_inserts)


# ---------------------------------------------------------------------------
# 2. unsubscribe 토큰 처리 → marketing_consent FALSE + consent_logs
# ---------------------------------------------------------------------------

class TestUnsubscribe:
    def test_unsubscribe_flips_consent_and_logs(self):
        mid = str(uuid.uuid4())
        fake = FakeSupabase()
        fake.member_by_id[mid] = _member(mid, consent=True)

        settings = MagicMock(
            JWT_SECRET_KEY="test-secret", JWT_ALGORITHM="HS256",
            JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60,
        )
        with patch(_JWT_SETTINGS, return_value=settings):
            token = service.create_unsubscribe_token(mid)
            with patch(_SVC_SB, return_value=fake):
                returned = service.process_unsubscribe(token)

        assert returned == mid
        # marketing_consent False update
        assert any(
            u["filters"].get("id") == mid and u["payload"].get("marketing_consent") is False
            for u in fake.members_updates
        )
        # consent_logs 이력 (marketing / agreed False)
        assert len(fake.consent_logs) == 1
        log = fake.consent_logs[0]
        assert log["consent_type"] == "marketing"
        assert log["agreed"] is False
        assert log["member_id"] == mid

    def test_invalid_token_returns_none(self):
        fake = FakeSupabase()
        settings = MagicMock(
            JWT_SECRET_KEY="test-secret", JWT_ALGORITHM="HS256",
            JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60,
        )
        with patch(_JWT_SETTINGS, return_value=settings):
            with patch(_SVC_SB, return_value=fake):
                assert service.process_unsubscribe("not-a-token") is None
        # 아무 변경도 없어야 함
        assert fake.members_updates == []
        assert fake.consent_logs == []

    def test_wrong_purpose_token_rejected(self):
        mid = str(uuid.uuid4())
        fake = FakeSupabase()
        settings = MagicMock(
            JWT_SECRET_KEY="test-secret", JWT_ALGORITHM="HS256",
            JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60,
        )
        from shared_core.auth.jwt import create_access_token
        with patch(_JWT_SETTINGS, return_value=settings):
            # purpose 가 다른 토큰
            wrong = create_access_token({"purpose": "login", "member_id": mid})
            with patch(_SVC_SB, return_value=fake):
                assert service.process_unsubscribe(wrong) is None
        assert fake.members_updates == []


# ---------------------------------------------------------------------------
# 3 & 4. send: 스냅샷 후 수신거부한 회원 skipped, EmailService 호출(실제 발송 없음)
# ---------------------------------------------------------------------------

class TestSendBroadcast:
    def _setup(self, consent_r1=True, consent_r2=False):
        m1, m2 = str(uuid.uuid4()), str(uuid.uuid4())
        fake = FakeSupabase()
        fake.broadcast = {
            "id": fake.broadcast_id,
            "subject": "공지",
            "body_html": "<p>hi</p>",
            "status": "draft",
            "sent_at": None,
        }
        fake.member_by_id[m1] = _member(m1, email="a@fencingmind.ai", consent=consent_r1)
        fake.member_by_id[m2] = _member(m2, email="b@fencingmind.ai", consent=consent_r2)
        fake.recipients = [
            {"id": "1", "broadcast_id": fake.broadcast_id, "member_id": m1,
             "email": "a@fencingmind.ai", "status": "pending", "error": None, "sent_at": None},
            {"id": "2", "broadcast_id": fake.broadcast_id, "member_id": m2,
             "email": "b@fencingmind.ai", "status": "pending", "error": None, "sent_at": None},
        ]
        return fake, m1, m2

    def test_skips_member_who_unsubscribed_after_snapshot(self):
        fake, m1, m2 = self._setup(consent_r1=True, consent_r2=False)
        email_svc = _fake_email_service()

        with (
            patch(_SVC_SB, return_value=fake),
            patch(_SVC_EMAIL, return_value=email_svc),
            patch.object(service, "SEND_INTERVAL_SECONDS", 0),
        ):
            result = asyncio.run(service.send_broadcast(fake.broadcast_id))

        assert result["sent"] == 1
        assert result["skipped"] == 1
        assert result["failed"] == 0
        assert result["remaining"] == 0
        assert result["status"] == "sent"

        # EmailService 는 opt-in 회원(m1)에게만 호출됨
        assert email_svc.send_broadcast_email.await_count == 1
        call_kwargs = email_svc.send_broadcast_email.await_args.kwargs
        assert call_kwargs["to"] == "a@fencingmind.ai"
        assert "unsubscribe_url" in call_kwargs

        # 수신자 상태: m1 sent, m2 skipped
        statuses = {r["member_id"]: r["status"] for r in fake.recipients}
        assert statuses[m1] == "sent"
        assert statuses[m2] == "skipped"

    def test_send_uses_email_service_no_real_network(self):
        fake, m1, m2 = self._setup(consent_r1=True, consent_r2=True)
        email_svc = _fake_email_service()

        with (
            patch(_SVC_SB, return_value=fake),
            patch(_SVC_EMAIL, return_value=email_svc),
            patch.object(service, "SEND_INTERVAL_SECONDS", 0),
        ):
            result = asyncio.run(service.send_broadcast(fake.broadcast_id))

        assert result["sent"] == 2
        assert result["failed"] == 0
        # 실제 발송이 아니라 mock 호출만 (Resend HTTP 미호출)
        assert email_svc.send_broadcast_email.await_count == 2
        for r in fake.recipients:
            assert r["status"] == "sent"

    def test_resume_only_processes_pending(self):
        """이미 sent 인 수신자는 재실행 시 건너뛴다 (중복발송 방지)."""
        fake, m1, m2 = self._setup(consent_r1=True, consent_r2=True)
        fake.recipients[0]["status"] = "sent"  # m1 이미 발송됨
        email_svc = _fake_email_service()

        with (
            patch(_SVC_SB, return_value=fake),
            patch(_SVC_EMAIL, return_value=email_svc),
            patch.object(service, "SEND_INTERVAL_SECONDS", 0),
        ):
            result = asyncio.run(service.send_broadcast(fake.broadcast_id))

        # pending 인 m2 만 발송
        assert email_svc.send_broadcast_email.await_count == 1
        assert email_svc.send_broadcast_email.await_args.kwargs["to"] == "b@fencingmind.ai"
        assert result["sent"] == 1

    def test_limit_leaves_remaining_pending(self):
        fake, m1, m2 = self._setup(consent_r1=True, consent_r2=True)
        email_svc = _fake_email_service()

        with (
            patch(_SVC_SB, return_value=fake),
            patch(_SVC_EMAIL, return_value=email_svc),
            patch.object(service, "SEND_INTERVAL_SECONDS", 0),
        ):
            result = asyncio.run(service.send_broadcast(fake.broadcast_id, limit=1))

        assert result["sent"] == 1
        assert result["remaining"] == 1
        assert result["status"] == "sending"  # 남은 pending 재개 가능

    def test_send_failure_aborts_and_keeps_remaining(self):
        fake, m1, m2 = self._setup(consent_r1=True, consent_r2=True)
        email_svc = MagicMock()
        email_svc.send_broadcast_email = AsyncMock(return_value=False)  # Resend 실패

        with (
            patch(_SVC_SB, return_value=fake),
            patch(_SVC_EMAIL, return_value=email_svc),
            patch.object(service, "SEND_INTERVAL_SECONDS", 0),
        ):
            result = asyncio.run(service.send_broadcast(fake.broadcast_id))

        # 첫 건 실패 → 기록 후 중단, 나머지 pending
        assert result["failed"] == 1
        assert result["sent"] == 0
        assert result["remaining"] == 1
        assert email_svc.send_broadcast_email.await_count == 1


# ---------------------------------------------------------------------------
# 5. Admin gate: 인증 없이 접근 시 401/403
# ---------------------------------------------------------------------------

class TestAdminGate:
    def test_create_broadcast_requires_admin(self, app_client):
        resp = app_client.post(
            "/admin/broadcasts",
            json={"subject": "x", "body_html": "<p>y</p>"},
        )
        assert resp.status_code in (401, 403)

    def test_send_broadcast_requires_admin(self, app_client):
        resp = app_client.post(f"/admin/broadcasts/{uuid.uuid4()}/send")
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# 6. Unsubscribe endpoint (public, 200 always)
# ---------------------------------------------------------------------------

class TestUnsubscribeEndpoint:
    def test_valid_token_returns_confirmation(self, app_client):
        mid = str(uuid.uuid4())
        fake = FakeSupabase()
        fake.member_by_id[mid] = _member(mid, consent=True)

        # app_client 픽스처가 JWT settings 를 test-secret 로 patch 함
        token = service.create_unsubscribe_token(mid)
        with patch(_SVC_SB, return_value=fake):
            resp = app_client.get(f"/auth/unsubscribe?token={token}")

        assert resp.status_code == 200
        assert "수신거부" in resp.text
        assert fake.consent_logs and fake.consent_logs[0]["agreed"] is False

    def test_invalid_token_still_200(self, app_client):
        fake = FakeSupabase()
        with patch(_SVC_SB, return_value=fake):
            resp = app_client.get("/auth/unsubscribe?token=garbage")
        assert resp.status_code == 200
        assert "유효하지 않" in resp.text
