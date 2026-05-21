"""Credit and subscription management for FencingMind Analytics."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, List
import time
import uuid


class SubscriptionTier(Enum):
    FREE = "free"           # 2 credits/month
    BASIC = "basic"         # Pay-per-use ($19.99/credit)
    PRO = "pro"             # $99/month, unlimited
    TEAM = "team"           # $499/month, unlimited + multi-user


# Analysis credit costs by job type
ANALYSIS_COSTS = {
    "standard": 1,       # Standard match analysis
    "broadcast": 2,      # TV broadcast analysis (more compute)
    "quick": 0,          # Quick quality check (free)
}

TIER_MONTHLY_CREDITS = {
    SubscriptionTier.FREE: 2,
    SubscriptionTier.BASIC: 0,  # pay-per-use, no monthly
}


@dataclass
class MemberSubscription:
    member_id: str
    tier: SubscriptionTier = SubscriptionTier.FREE
    credits: int = 2       # Starting free credits
    total_earned: int = 2
    total_spent: int = 0
    transactions: List[dict] = field(default_factory=list)


class CreditManager:
    """In-memory credit management (Phase 4.1 will use Supabase)."""

    def __init__(self):
        self._members: Dict[str, MemberSubscription] = {}

    def get_or_create(self, member_id: str) -> MemberSubscription:
        if member_id not in self._members:
            self._members[member_id] = MemberSubscription(member_id=member_id)
        return self._members[member_id]

    def check_balance(self, member_id: str) -> int:
        return self.get_or_create(member_id).credits

    def can_analyze(self, member_id: str, job_type: str = "standard") -> tuple[bool, str]:
        """Check if member can start analysis. Returns (allowed, reason)."""
        sub = self.get_or_create(member_id)

        # Pro/Team = unlimited
        if sub.tier in (SubscriptionTier.PRO, SubscriptionTier.TEAM):
            return True, "unlimited"

        cost = ANALYSIS_COSTS.get(job_type, 1)
        if cost == 0:
            return True, "free_operation"

        if sub.credits >= cost:
            return True, f"credits_available ({sub.credits})"

        return False, f"insufficient_credits (have={sub.credits}, need={cost})"

    def deduct_credit(self, member_id: str, job_type: str = "standard", reference_id: str = "") -> bool:
        """Deduct credits for analysis. Returns True if successful."""
        sub = self.get_or_create(member_id)

        if sub.tier in (SubscriptionTier.PRO, SubscriptionTier.TEAM):
            return True  # No deduction for unlimited tiers

        cost = ANALYSIS_COSTS.get(job_type, 1)
        if cost == 0:
            return True

        if sub.credits < cost:
            return False

        sub.credits -= cost
        sub.total_spent += cost
        sub.transactions.append({
            "id": str(uuid.uuid4())[:8],
            "amount": -cost,
            "balance_after": sub.credits,
            "type": "analysis",
            "reference_id": reference_id,
            "description": f"{job_type} analysis",
            "created_at": time.time(),
        })
        return True

    def add_credits(self, member_id: str, amount: int, source: str = "purchase") -> int:
        """Add credits. Returns new balance."""
        sub = self.get_or_create(member_id)
        sub.credits += amount
        sub.total_earned += amount
        sub.transactions.append({
            "id": str(uuid.uuid4())[:8],
            "amount": amount,
            "balance_after": sub.credits,
            "type": source,
            "reference_id": "",
            "description": f"Added {amount} credits ({source})",
            "created_at": time.time(),
        })
        return sub.credits

    def set_tier(self, member_id: str, tier: SubscriptionTier) -> MemberSubscription:
        """Change subscription tier."""
        sub = self.get_or_create(member_id)
        sub.tier = tier
        return sub

    def get_subscription_info(self, member_id: str) -> dict:
        """Get subscription and credit info for API response."""
        sub = self.get_or_create(member_id)
        return {
            "member_id": member_id,
            "tier": sub.tier.value,
            "credits": sub.credits,
            "total_earned": sub.total_earned,
            "total_spent": sub.total_spent,
            "is_unlimited": sub.tier in (SubscriptionTier.PRO, SubscriptionTier.TEAM),
            "recent_transactions": sub.transactions[-10:],  # last 10
        }
