"""Tests for subscription/credit API endpoints via FastAPI TestClient (Phase 4)."""

import uuid
import pytest
from fastapi.testclient import TestClient

from app.server import app


client = TestClient(app)


def _unique_id() -> str:
    """Generate a unique member_id to isolate test state."""
    return f"test_{uuid.uuid4().hex[:8]}"


# ------------------------------------------------------------------
# Credit balance
# ------------------------------------------------------------------


def test_get_credits_default():
    """GET /api/analytics/credits should return initial balance for new member."""
    mid = _unique_id()
    resp = client.get("/api/analytics/credits", params={"member_id": mid})
    assert resp.status_code == 200
    data = resp.json()
    assert data["member_id"] == mid
    assert data["credits"] == 2  # Initial free credits
    assert data["tier"] == "free"
    assert data["is_unlimited"] is False


def test_purchase_credits():
    """POST /api/analytics/credits/purchase should increase balance."""
    mid = _unique_id()

    # Check initial balance
    resp = client.get("/api/analytics/credits", params={"member_id": mid})
    initial = resp.json()["credits"]

    # Purchase 5 credits
    resp = client.post(
        "/api/analytics/credits/purchase",
        params={"member_id": mid, "amount": 5},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["credits_added"] == 5
    assert data["new_balance"] == initial + 5

    # Verify balance updated
    resp = client.get("/api/analytics/credits", params={"member_id": mid})
    assert resp.json()["credits"] == initial + 5


def test_purchase_invalid_amount():
    """amount=0 or amount=101 should be rejected with 400."""
    mid = _unique_id()

    # amount=0
    resp = client.post(
        "/api/analytics/credits/purchase",
        params={"member_id": mid, "amount": 0},
    )
    assert resp.status_code == 400

    # amount=101
    resp = client.post(
        "/api/analytics/credits/purchase",
        params={"member_id": mid, "amount": 101},
    )
    assert resp.status_code == 400


# ------------------------------------------------------------------
# Subscription
# ------------------------------------------------------------------


def test_get_subscription():
    """GET /api/analytics/subscription should return tier info."""
    mid = _unique_id()
    resp = client.get("/api/analytics/subscription", params={"member_id": mid})
    assert resp.status_code == 200
    data = resp.json()
    assert data["member_id"] == mid
    assert data["tier"] == "free"
    assert "credits" in data
    assert "is_unlimited" in data


def test_update_subscription():
    """POST /api/analytics/subscription should change tier."""
    mid = _unique_id()

    # Upgrade to pro
    resp = client.post(
        "/api/analytics/subscription",
        params={"member_id": mid, "tier": "pro"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["tier"] == "pro"
    assert data["is_unlimited"] is True

    # Verify persisted
    resp = client.get("/api/analytics/subscription", params={"member_id": mid})
    assert resp.json()["tier"] == "pro"


def test_update_invalid_tier():
    """Invalid tier name should be rejected with 400."""
    mid = _unique_id()
    resp = client.post(
        "/api/analytics/subscription",
        params={"member_id": mid, "tier": "platinum_vip"},
    )
    assert resp.status_code == 400
    assert "Invalid tier" in resp.json()["detail"]
