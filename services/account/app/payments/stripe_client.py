"""
Stripe SDK 래퍼

Stripe Checkout Session, Customer Portal, Webhook 서명 검증 등
"""
from typing import Optional

from loguru import logger

try:
    import stripe
except ImportError:
    stripe = None
    logger.warning("stripe 패키지 미설치 - 결제 기능 비활성")

from app.config import get_account_settings


def _get_stripe():
    """Stripe API 키 설정 후 모듈 반환"""
    if stripe is None:
        raise RuntimeError("stripe 패키지가 설치되지 않았습니다: pip install stripe")
    settings = get_account_settings()
    if not settings.STRIPE_SECRET_KEY:
        raise RuntimeError("STRIPE_SECRET_KEY가 설정되지 않았습니다")
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


# ============================================================
# Price ID 매핑 (Stripe Dashboard에서 생성한 Price 객체)
# 실제 운영 시 services 테이블 또는 환경변수에서 로드
# ============================================================
STRIPE_PRICE_MAP = {
    # service_id -> tier -> stripe_price_id
    "data": {
        "basic_monthly": "",    # Stripe에서 Price 생성 후 입력
        "basic_yearly": "",
        "premium_monthly": "",
        "premium_yearly": "",
        "enterprise_monthly": "",
    },
    "club": {
        "basic_monthly": "",
        "premium_monthly": "",
        "enterprise_monthly": "",
    },
    "community": {
        "premium_monthly": "",
    },
    "analytics": {
        "pro_monthly": "",
        "team_monthly": "",
    },
}


def get_price_id(service_id: str, tier: str, billing_period: str = "monthly") -> Optional[str]:
    """서비스+등급에 해당하는 Stripe Price ID 조회"""
    key = f"{tier}_{billing_period}"
    return STRIPE_PRICE_MAP.get(service_id, {}).get(key)


async def get_or_create_customer(member_id: str, email: str) -> str:
    """
    회원의 Stripe Customer 조회 또는 생성.
    stripe_customers 테이블에 매핑 저장.
    """
    from shared_core.db.client import get_supabase_client

    s = _get_stripe()
    supabase = get_supabase_client()

    # DB에서 기존 매핑 조회
    result = (
        supabase.table("stripe_customers")
        .select("stripe_customer_id")
        .eq("member_id", member_id)
        .execute()
    )
    if result.data:
        return result.data[0]["stripe_customer_id"]

    # Stripe Customer 생성
    customer = s.Customer.create(
        email=email,
        metadata={"member_id": member_id},
    )

    # DB에 매핑 저장
    supabase.table("stripe_customers").insert({
        "member_id": member_id,
        "stripe_customer_id": customer.id,
    }).execute()

    logger.info(f"Stripe Customer 생성: member={member_id}, customer={customer.id}")
    return customer.id


async def create_checkout_session(
    member_id: str,
    email: str,
    service_id: str,
    tier: str,
    billing_period: str = "monthly",
    success_url: str = "",
    cancel_url: str = "",
) -> dict:
    """
    Stripe Checkout Session 생성.
    반환: {"checkout_url": "...", "session_id": "..."}
    """
    s = _get_stripe()
    price_id = get_price_id(service_id, tier, billing_period)
    if not price_id:
        raise ValueError(f"Price ID 미설정: {service_id}/{tier}/{billing_period}")

    customer_id = await get_or_create_customer(member_id, email)

    session = s.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url or "https://account.fencingmind.ai/account/checkout/success?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=cancel_url or "https://account.fencingmind.ai/account/checkout/cancel",
        metadata={
            "member_id": member_id,
            "service_id": service_id,
            "tier": tier,
        },
    )

    return {"checkout_url": session.url, "session_id": session.id}


async def create_portal_session(member_id: str) -> str:
    """Stripe Customer Portal 세션 생성 → URL 반환"""
    s = _get_stripe()
    from shared_core.db.client import get_supabase_client
    supabase = get_supabase_client()

    result = (
        supabase.table("stripe_customers")
        .select("stripe_customer_id")
        .eq("member_id", member_id)
        .execute()
    )
    if not result.data:
        raise ValueError("Stripe 고객 정보가 없습니다. 구독을 먼저 시작해주세요.")

    session = s.billing_portal.Session.create(
        customer=result.data[0]["stripe_customer_id"],
        return_url="https://account.fencingmind.ai/account/dashboard",
    )
    return session.url


def verify_webhook_signature(payload: bytes, sig_header: str) -> dict:
    """Stripe 웹훅 서명 검증"""
    s = _get_stripe()
    settings = get_account_settings()
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET 미설정")

    event = s.Webhook.construct_event(
        payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
    )
    return event
