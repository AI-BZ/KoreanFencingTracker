"""
Subscriptions Router tests
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4

import pytest

# Define sample member data locally (avoid broken cross-package import)
_NOW = datetime.now(timezone.utc).isoformat()

SAMPLE_MEMBER = {
    "id": str(uuid.uuid4()),
    "full_name": "박소윤",
    "display_name": "B.S.",
    "email": "test@fencingmind.ai",
    "phone": "010-1234-5678",
    "birth_date": "2005-03-15",
    "member_type": "player",
    "player_id": None,
    "organization_id": None,
    "verification_status": "pending",
    "verified_at": None,
    "privacy_public": True,
    "marketing_consent": False,
    "promotional_consent": False,
    "created_at": _NOW,
    "updated_at": _NOW,
}

# Patch targets in subscriptions router module
_GCM = "services.account.app.subscriptions.router.get_current_member"
_GET_SB = "services.account.app.subscriptions.router.get_supabase_client"

_MEMBER_ID = str(uuid4())


def _make_subscription(service_id="data", tier="free", status="active"):
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": str(uuid4()),
        "member_id": _MEMBER_ID,
        "service_id": service_id,
        "tier": tier,
        "status": status,
        "settings": None,
        "started_at": now,
        "expires_at": None,
        "created_at": now,
        "updated_at": now,
    }


def _make_sb_with_calls(*call_results):
    """
    Create a supabase mock that returns different data on sequential .execute() calls.
    Each call_results entry is the data for one .execute() call.
    """
    sb = MagicMock()
    chain = MagicMock()
    sb.table.return_value = chain
    chain.select.return_value = chain
    chain.insert.return_value = chain
    chain.update.return_value = chain
    chain.eq.return_value = chain

    results = list(call_results)
    call_idx = {"i": 0}

    def execute_side_effect():
        idx = call_idx["i"]
        call_idx["i"] += 1
        if idx < len(results):
            return MagicMock(data=results[idx])
        return MagicMock(data=[])

    chain.execute = MagicMock(side_effect=execute_side_effect)
    return sb


class TestListSubscriptions:
    def test_returns_subscription_list(self, app_client):
        member = SAMPLE_MEMBER.copy()
        subs = [_make_subscription("data"), _make_subscription("club")]
        sb = _make_sb_with_calls(subs)

        with (
            patch(_GCM, new_callable=AsyncMock, return_value=member),
            patch(_GET_SB, return_value=sb),
        ):
            resp = app_client.get("/account/services")

        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_returns_401_when_not_authenticated(self, app_client):
        with patch(_GCM, new_callable=AsyncMock, return_value=None):
            resp = app_client.get("/account/services")
        assert resp.status_code == 401


class TestSubscribe:
    def test_creates_subscription(self, app_client):
        member = SAMPLE_MEMBER.copy()
        new_sub = _make_subscription("data")

        # 1st execute: check existing → empty, 2nd execute: insert → new_sub
        sb = _make_sb_with_calls([], [new_sub])

        with (
            patch(_GCM, new_callable=AsyncMock, return_value=member),
            patch(_GET_SB, return_value=sb),
        ):
            resp = app_client.post(
                "/account/services/data/subscribe",
                json={"service_id": "data", "tier": "free"},
            )

        assert resp.status_code == 201

    def test_duplicate_returns_409(self, app_client):
        member = SAMPLE_MEMBER.copy()
        existing = _make_subscription("data")

        # 1st execute: check existing → found
        sb = _make_sb_with_calls([existing])

        with (
            patch(_GCM, new_callable=AsyncMock, return_value=member),
            patch(_GET_SB, return_value=sb),
        ):
            resp = app_client.post(
                "/account/services/data/subscribe",
                json={"service_id": "data", "tier": "free"},
            )

        assert resp.status_code == 409

    def test_returns_401_when_not_authenticated(self, app_client):
        with patch(_GCM, new_callable=AsyncMock, return_value=None):
            resp = app_client.post(
                "/account/services/data/subscribe",
                json={"service_id": "data", "tier": "free"},
            )
        assert resp.status_code == 401


class TestUpdateSubscription:
    def test_updates_tier(self, app_client):
        member = SAMPLE_MEMBER.copy()
        existing = _make_subscription("data", tier="free")
        updated = _make_subscription("data", tier="premium")

        # 1st execute: find existing, 2nd execute: update result
        sb = _make_sb_with_calls([existing], [updated])

        with (
            patch(_GCM, new_callable=AsyncMock, return_value=member),
            patch(_GET_SB, return_value=sb),
        ):
            resp = app_client.patch(
                "/account/services/data",
                json={"service_id": "data", "tier": "premium"},
            )

        assert resp.status_code == 200

    def test_returns_404_when_no_active_subscription(self, app_client):
        member = SAMPLE_MEMBER.copy()

        # 1st execute: no existing subscription
        sb = _make_sb_with_calls([])

        with (
            patch(_GCM, new_callable=AsyncMock, return_value=member),
            patch(_GET_SB, return_value=sb),
        ):
            resp = app_client.patch(
                "/account/services/data",
                json={"service_id": "data", "tier": "premium"},
            )

        assert resp.status_code == 404


class TestCancelSubscription:
    def test_sets_status_to_cancelled(self, app_client):
        member = SAMPLE_MEMBER.copy()
        existing = _make_subscription("data")

        # 1st execute: find existing, 2nd execute: update (don't care about result)
        sb = _make_sb_with_calls([existing], [])

        with (
            patch(_GCM, new_callable=AsyncMock, return_value=member),
            patch(_GET_SB, return_value=sb),
        ):
            resp = app_client.delete("/account/services/data")

        assert resp.status_code == 200
        assert "취소" in resp.json()["detail"]

    def test_returns_404_when_no_active_subscription(self, app_client):
        member = SAMPLE_MEMBER.copy()

        # 1st execute: no existing subscription
        sb = _make_sb_with_calls([])

        with (
            patch(_GCM, new_callable=AsyncMock, return_value=member),
            patch(_GET_SB, return_value=sb),
        ):
            resp = app_client.delete("/account/services/data")

        assert resp.status_code == 404
