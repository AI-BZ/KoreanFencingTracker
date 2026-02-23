"""
Account service test fixtures
"""
import sys
from pathlib import Path

# Ensure project root and packages are on sys.path
_project_root = Path(__file__).resolve().parent.parent.parent.parent
for p in [str(_project_root), str(_project_root / "packages"), str(_project_root / "services" / "account")]:
    if p not in sys.path:
        sys.path.insert(0, p)

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from shared_core.auth.jwt import create_access_token


# ---------------------
# Sample data
# ---------------------

SAMPLE_MEMBER_ID = str(uuid.uuid4())

SAMPLE_MEMBER = {
    "id": SAMPLE_MEMBER_ID,
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
    "created_at": datetime.now(timezone.utc).isoformat(),
    "updated_at": datetime.now(timezone.utc).isoformat(),
}

SAMPLE_PARENT_MEMBER = {
    **SAMPLE_MEMBER,
    "id": str(uuid.uuid4()),
    "member_type": "player_parent",
    "full_name": "김부모",
    "email": "parent@fencingmind.ai",
}


@pytest.fixture
def sample_member():
    return SAMPLE_MEMBER.copy()


@pytest.fixture
def sample_parent_member():
    return SAMPLE_PARENT_MEMBER.copy()


@pytest.fixture
def app_client():
    """TestClient with mocked JWT settings."""
    with patch("shared_core.auth.jwt.get_shared_auth_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            JWT_SECRET_KEY="test-secret-key-for-unit-tests",
            JWT_ALGORITHM="HS256",
            JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60,
        )

        from services.account.app.server import app
        client = TestClient(app)
        yield client
