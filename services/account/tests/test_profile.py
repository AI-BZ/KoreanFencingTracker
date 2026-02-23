"""
Profile Router tests
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

# Define sample data locally (avoid broken cross-package import)
_MEMBER_ID = str(uuid.uuid4())
_NOW = datetime.now(timezone.utc).isoformat()

SAMPLE_MEMBER = {
    "id": _MEMBER_ID,
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

SAMPLE_PARENT_MEMBER = {
    **SAMPLE_MEMBER,
    "id": str(uuid.uuid4()),
    "member_type": "player_parent",
    "full_name": "김부모",
    "email": "parent@fencingmind.ai",
}

# Patch targets in profile router module
_GCM = "services.account.app.profile.router.get_current_member"
_GET_SB = "services.account.app.profile.router.get_supabase_client"


def _make_sb(execute_data):
    """Create a fresh supabase mock returning execute_data"""
    sb = MagicMock()
    chain = MagicMock()
    sb.table.return_value = chain
    chain.select.return_value = chain
    chain.update.return_value = chain
    chain.eq.return_value = chain
    chain.single.return_value = chain
    chain.execute.return_value = MagicMock(data=execute_data)
    return sb


class TestGetMe:
    def test_returns_member_when_authenticated(self, app_client):
        member = SAMPLE_MEMBER.copy()
        with patch(_GCM, new_callable=AsyncMock, return_value=member):
            resp = app_client.get("/account/me")

        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == member["email"]
        assert data["full_name"] == member["full_name"]

    def test_returns_401_when_not_authenticated(self, app_client):
        with patch(_GCM, new_callable=AsyncMock, return_value=None):
            resp = app_client.get("/account/me")
        assert resp.status_code == 401


class TestPatchMe:
    def test_updates_profile_fields(self, app_client):
        member = SAMPLE_MEMBER.copy()
        updated = member.copy()
        updated["full_name"] = "김펜싱"
        updated["display_name"] = "김*싱"

        sb = _make_sb([updated])

        with (
            patch(_GCM, new_callable=AsyncMock, return_value=member),
            patch(_GET_SB, return_value=sb),
        ):
            resp = app_client.patch("/account/me", json={"full_name": "김펜싱"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["full_name"] == "김펜싱"

    def test_returns_400_when_no_fields(self, app_client):
        member = SAMPLE_MEMBER.copy()
        with patch(_GCM, new_callable=AsyncMock, return_value=member):
            resp = app_client.patch("/account/me", json={})
        assert resp.status_code == 400

    def test_returns_401_when_not_authenticated(self, app_client):
        with patch(_GCM, new_callable=AsyncMock, return_value=None):
            resp = app_client.patch("/account/me", json={"full_name": "테스트"})
        assert resp.status_code == 401


class TestPatchPrivacy:
    def test_updates_privacy_settings(self, app_client):
        member = SAMPLE_MEMBER.copy()
        sb = _make_sb([{}])

        with (
            patch(_GCM, new_callable=AsyncMock, return_value=member),
            patch(_GET_SB, return_value=sb),
        ):
            resp = app_client.patch(
                "/account/me/privacy",
                json={"privacy_public": False, "marketing_consent": True},
            )

        assert resp.status_code == 200
        assert resp.json()["success"] is True


class TestGuardianLink:
    def test_rejects_non_parent(self, app_client):
        member = SAMPLE_MEMBER.copy()
        with patch(_GCM, new_callable=AsyncMock, return_value=member):
            resp = app_client.post(
                "/account/guardian/link",
                json={"minor_member_id": "00000000-0000-0000-0000-000000000001", "relationship": "부"},
            )
        assert resp.status_code == 400
        assert "보호자" in resp.json()["detail"]

    def test_allows_parent_member(self, app_client):
        parent = SAMPLE_PARENT_MEMBER.copy()
        minor_id = "00000000-0000-0000-0000-000000000001"
        minor_data = {"id": minor_id, "guardian_member_id": None, "member_type": "player"}

        sb = MagicMock()
        chain = MagicMock()
        sb.table.return_value = chain
        chain.select.return_value = chain
        chain.update.return_value = chain
        chain.eq.return_value = chain
        chain.single.return_value = chain
        # select → single → execute returns minor
        # update → eq → execute returns success
        chain.execute.return_value = MagicMock(data=minor_data)

        with (
            patch(_GCM, new_callable=AsyncMock, return_value=parent),
            patch(_GET_SB, return_value=sb),
        ):
            resp = app_client.post(
                "/account/guardian/link",
                json={"minor_member_id": minor_id, "relationship": "모"},
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
