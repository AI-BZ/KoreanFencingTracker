"""Tests for credit and subscription management (Phase 4)."""

import pytest

from app.credits import CreditManager, SubscriptionTier, ANALYSIS_COSTS


# ------------------------------------------------------------------
# Initial state / balance
# ------------------------------------------------------------------


def test_initial_free_credits():
    """New member should start with 2 free credits on FREE tier."""
    cm = CreditManager()
    sub = cm.get_or_create("new_member")
    assert sub.credits == 2
    assert sub.tier == SubscriptionTier.FREE
    assert sub.total_earned == 2
    assert sub.total_spent == 0


def test_check_balance():
    """check_balance should return correct credit count."""
    cm = CreditManager()
    balance = cm.check_balance("member_a")
    assert balance == 2


# ------------------------------------------------------------------
# can_analyze
# ------------------------------------------------------------------


def test_can_analyze_with_credits():
    """Standard analysis should be allowed when member has credits."""
    cm = CreditManager()
    allowed, reason = cm.can_analyze("member_b", "standard")
    assert allowed is True
    assert "credits_available" in reason


def test_can_analyze_insufficient():
    """Analysis should be rejected when credits are exhausted."""
    cm = CreditManager()
    # Exhaust all 2 credits
    cm.deduct_credit("member_c", "standard")
    cm.deduct_credit("member_c", "standard")
    assert cm.check_balance("member_c") == 0

    allowed, reason = cm.can_analyze("member_c", "standard")
    assert allowed is False
    assert "insufficient" in reason


def test_can_analyze_pro_unlimited():
    """PRO tier should always be allowed (unlimited)."""
    cm = CreditManager()
    cm.set_tier("member_pro", SubscriptionTier.PRO)
    allowed, reason = cm.can_analyze("member_pro", "standard")
    assert allowed is True
    assert reason == "unlimited"


def test_can_analyze_team_unlimited():
    """TEAM tier should always be allowed (unlimited), even for broadcast."""
    cm = CreditManager()
    cm.set_tier("member_team", SubscriptionTier.TEAM)
    allowed, reason = cm.can_analyze("member_team", "broadcast")
    assert allowed is True
    assert reason == "unlimited"


# ------------------------------------------------------------------
# deduct_credit
# ------------------------------------------------------------------


def test_deduct_credit_standard():
    """Standard analysis should deduct 1 credit."""
    cm = CreditManager()
    before = cm.check_balance("member_d")
    result = cm.deduct_credit("member_d", "standard")
    after = cm.check_balance("member_d")
    assert result is True
    assert after == before - ANALYSIS_COSTS["standard"]


def test_deduct_credit_broadcast():
    """Broadcast analysis should deduct 2 credits."""
    cm = CreditManager()
    # Add extra credits so we have enough for broadcast (cost=2)
    cm.add_credits("member_e", 3)
    before = cm.check_balance("member_e")
    result = cm.deduct_credit("member_e", "broadcast")
    after = cm.check_balance("member_e")
    assert result is True
    assert after == before - ANALYSIS_COSTS["broadcast"]


def test_deduct_credit_quick_free():
    """Quick analysis costs 0 credits — no deduction."""
    cm = CreditManager()
    before = cm.check_balance("member_f")
    result = cm.deduct_credit("member_f", "quick")
    after = cm.check_balance("member_f")
    assert result is True
    assert after == before  # No change


def test_deduct_insufficient_fails():
    """Deduction should fail and leave balance unchanged when insufficient."""
    cm = CreditManager()
    # Exhaust credits
    cm.deduct_credit("member_g", "standard")
    cm.deduct_credit("member_g", "standard")
    balance_before = cm.check_balance("member_g")
    assert balance_before == 0

    result = cm.deduct_credit("member_g", "standard")
    assert result is False
    assert cm.check_balance("member_g") == balance_before


# ------------------------------------------------------------------
# add_credits / transactions
# ------------------------------------------------------------------


def test_add_credits():
    """Adding credits should increase balance correctly."""
    cm = CreditManager()
    initial = cm.check_balance("member_h")
    new_balance = cm.add_credits("member_h", 5)
    assert new_balance == initial + 5
    assert cm.check_balance("member_h") == initial + 5


def test_transaction_history():
    """Transactions should be recorded for purchases and deductions."""
    cm = CreditManager()
    cm.add_credits("member_i", 3, "purchase")
    cm.deduct_credit("member_i", "standard", reference_id="job_123")

    sub = cm.get_or_create("member_i")
    assert len(sub.transactions) == 2

    # First transaction: purchase
    assert sub.transactions[0]["type"] == "purchase"
    assert sub.transactions[0]["amount"] == 3

    # Second transaction: analysis deduction
    assert sub.transactions[1]["type"] == "analysis"
    assert sub.transactions[1]["amount"] == -1
    assert sub.transactions[1]["reference_id"] == "job_123"
    assert "balance_after" in sub.transactions[1]


# ------------------------------------------------------------------
# Tier management
# ------------------------------------------------------------------


def test_set_tier():
    """set_tier should change the subscription tier."""
    cm = CreditManager()
    sub = cm.set_tier("member_j", SubscriptionTier.PRO)
    assert sub.tier == SubscriptionTier.PRO

    # Change again
    sub = cm.set_tier("member_j", SubscriptionTier.BASIC)
    assert sub.tier == SubscriptionTier.BASIC


def test_subscription_info():
    """get_subscription_info should return correct structure."""
    cm = CreditManager()
    cm.set_tier("member_k", SubscriptionTier.PRO)
    info = cm.get_subscription_info("member_k")

    assert info["member_id"] == "member_k"
    assert info["tier"] == "pro"
    assert info["is_unlimited"] is True
    assert "credits" in info
    assert "total_earned" in info
    assert "total_spent" in info
    assert "recent_transactions" in info
    assert isinstance(info["recent_transactions"], list)
