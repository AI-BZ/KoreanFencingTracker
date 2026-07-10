"""
구독 등급 체크 미들웨어

각 서비스에서 인증된 요청마다 호출하여 현재 구독 등급을 확인.
만료된 구독은 자동으로 FREE로 강등.
"""
from datetime import datetime, timezone
from typing import Dict, List

from loguru import logger

from shared_core.db.client import get_supabase_client
from shared_core.types.service import SubscriptionTier, SubscriptionStatus


async def get_member_tier(member_id: str, service_id: str) -> SubscriptionTier:
    """
    회원의 특정 서비스 구독 등급 조회.

    - member_services에서 active 구독 조회
    - expires_at이 지났으면 FREE로 강등 + DB 업데이트
    - 구독이 없으면 FREE 반환
    """
    supabase = get_supabase_client()

    try:
        result = (
            supabase.table("member_services")
            .select("id, tier, status, expires_at")
            .eq("member_id", member_id)
            .eq("service_id", service_id)
            .eq("status", SubscriptionStatus.ACTIVE.value)
            .execute()
        )

        if not result.data:
            return SubscriptionTier.FREE

        subscription = result.data[0]

        # 만료 체크
        if subscription.get("expires_at"):
            expires_at = datetime.fromisoformat(
                subscription["expires_at"].replace("Z", "+00:00")
            )
            if datetime.now(timezone.utc) > expires_at:
                # 만료 → FREE로 강등
                supabase.table("member_services").update({
                    "tier": SubscriptionTier.FREE.value,
                    "status": SubscriptionStatus.EXPIRED.value,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", subscription["id"]).execute()

                logger.info(
                    f"구독 만료: member={member_id}, service={service_id}, "
                    f"old_tier={subscription['tier']}"
                )
                return SubscriptionTier.FREE

        return SubscriptionTier(subscription["tier"])

    except Exception as e:
        logger.error(f"구독 등급 조회 오류: member={member_id}, service={service_id}, error={e}")
        return SubscriptionTier.FREE


async def get_all_member_tiers(member_id: str) -> Dict[str, SubscriptionTier]:
    """
    회원의 모든 서비스 구독 등급을 한번에 조회.
    dashboard 등에서 사용.
    """
    supabase = get_supabase_client()

    try:
        result = (
            supabase.table("member_services")
            .select("service_id, tier, status, expires_at")
            .eq("member_id", member_id)
            .eq("status", SubscriptionStatus.ACTIVE.value)
            .execute()
        )

        tiers = {}
        now = datetime.now(timezone.utc)

        for sub in result.data:
            service_id = sub["service_id"]
            if sub.get("expires_at"):
                expires_at = datetime.fromisoformat(
                    sub["expires_at"].replace("Z", "+00:00")
                )
                if now > expires_at:
                    tiers[service_id] = SubscriptionTier.FREE
                    continue

            tiers[service_id] = SubscriptionTier(sub["tier"])

        return tiers

    except Exception as e:
        logger.error(f"전체 구독 조회 오류: member={member_id}, error={e}")
        return {}


def get_service_info() -> List[dict]:
    """서비스 정의 테이블에서 활성 서비스 목록 조회"""
    supabase = get_supabase_client()
    try:
        result = (
            supabase.table("services")
            .select("*")
            .order("sort_order")
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"서비스 목록 조회 오류: {e}")
        return []
