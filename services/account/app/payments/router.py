"""
결제 라우터

Stripe Checkout, Webhook, Customer Portal, 결제 성공/취소 페이지
PortOne(한국 결제)은 Phase 4에서 추가.
"""
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from loguru import logger

from shared_core.auth.jwt import get_current_member
from shared_core.db.client import get_supabase_client
from shared_core.types.service import SubscriptionTier, SubscriptionStatus

router = APIRouter(prefix="/account", tags=["payments"])

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))


def _require_member(member: Optional[dict]) -> dict:
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    return member


# ============================================================
# Checkout
# ============================================================

@router.post("/checkout/{service_id}/{tier}")
async def create_checkout(service_id: str, tier: str, request: Request, billing_period: str = "monthly"):
    """
    Stripe Checkout 세션 생성 → redirect URL 반환.
    한국 회원은 Phase 4에서 PortOne으로 분기.
    """
    member = _require_member(await get_current_member(request))

    # Free 등급은 결제 불필요
    if tier == "free":
        raise HTTPException(status_code=400, detail="Free 등급은 결제가 필요하지 않습니다")

    try:
        from .stripe_client import create_checkout_session

        result = await create_checkout_session(
            member_id=str(member["id"]),
            email=member["email"],
            service_id=service_id,
            tier=tier,
            billing_period=billing_period,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        logger.error(f"Stripe 설정 오류: {e}")
        raise HTTPException(
            status_code=503,
            detail="결제 시스템이 아직 설정되지 않았습니다. 관리자에게 문의해주세요."
        )
    except Exception as e:
        logger.error(f"Checkout 세션 생성 오류: {e}")
        raise HTTPException(status_code=500, detail="결제 세션 생성에 실패했습니다")


@router.get("/checkout/success", response_class=HTMLResponse)
async def checkout_success(request: Request, session_id: str = ""):
    """결제 성공 페이지"""
    return _templates.TemplateResponse("account/checkout_result.html", {
        "request": request,
        "success": True,
        "session_id": session_id,
    })


@router.get("/checkout/cancel", response_class=HTMLResponse)
async def checkout_cancel(request: Request):
    """결제 취소 페이지"""
    return _templates.TemplateResponse("account/checkout_result.html", {
        "request": request,
        "success": False,
    })


# ============================================================
# Customer Portal
# ============================================================

@router.post("/portal")
async def create_portal(request: Request):
    """Stripe Customer Portal → 구독/결제수단 관리"""
    member = _require_member(await get_current_member(request))

    try:
        from .stripe_client import create_portal_session
        portal_url = await create_portal_session(str(member["id"]))
        return RedirectResponse(url=portal_url, status_code=303)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Portal 세션 생성 오류: {e}")
        raise HTTPException(status_code=500, detail="결제 포털 접속에 실패했습니다")


# ============================================================
# Webhooks
# ============================================================

@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    """
    Stripe 웹훅 수신.
    서명 검증 후 이벤트별 member_services 업데이트.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        from .stripe_client import verify_webhook_signature
        event = verify_webhook_signature(payload, sig_header)
    except Exception as e:
        logger.error(f"Stripe 웹훅 서명 검증 실패: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event.get("type", "")
    data = event.get("data", {}).get("object", {})

    supabase = get_supabase_client()
    now = datetime.now(timezone.utc).isoformat()

    # 결제 이벤트 로그 저장
    try:
        supabase.table("payment_events").insert({
            "member_id": data.get("metadata", {}).get("member_id"),
            "event_source": "stripe",
            "event_id": event.get("id", ""),
            "event_type": event_type,
            "service_id": data.get("metadata", {}).get("service_id"),
            "amount": data.get("amount_total") or data.get("amount_paid"),
            "currency": (data.get("currency") or "usd").upper(),
            "payload": data,
        }).execute()
    except Exception as e:
        logger.warning(f"결제 이벤트 로그 저장 실패 (계속 처리): {e}")

    # 이벤트별 처리
    try:
        if event_type == "checkout.session.completed":
            await _handle_checkout_completed(data, supabase, now)
        elif event_type == "invoice.paid":
            await _handle_invoice_paid(data, supabase, now)
        elif event_type == "invoice.payment_failed":
            await _handle_payment_failed(data, supabase, now)
        elif event_type == "customer.subscription.deleted":
            await _handle_subscription_deleted(data, supabase, now)
        elif event_type == "customer.subscription.updated":
            await _handle_subscription_updated(data, supabase, now)
        else:
            logger.debug(f"미처리 Stripe 이벤트: {event_type}")
    except Exception as e:
        logger.error(f"Stripe 웹훅 처리 오류 ({event_type}): {e}")

    return {"status": "ok"}


@router.post("/webhooks/portone")
async def portone_webhook(request: Request):
    """PortOne 웹훅 (Phase 4에서 구현)"""
    logger.warning("PortOne 웹훅 수신 - 아직 미구현")
    return {"status": "ok"}


# ============================================================
# Webhook Handlers
# ============================================================

async def _handle_checkout_completed(data: dict, supabase, now: str):
    """checkout.session.completed → member_services 활성화"""
    metadata = data.get("metadata", {})
    member_id = metadata.get("member_id")
    service_id = metadata.get("service_id")
    tier = metadata.get("tier")

    if not all([member_id, service_id, tier]):
        logger.warning(f"checkout.session.completed: 메타데이터 부족 {metadata}")
        return

    subscription_id = data.get("subscription")

    # stripe_subscriptions 테이블에 기록
    if subscription_id:
        supabase.table("stripe_subscriptions").upsert({
            "member_id": member_id,
            "service_id": service_id,
            "stripe_subscription_id": subscription_id,
            "tier": tier,
            "status": "active",
            "updated_at": now,
        }, on_conflict="stripe_subscription_id").execute()

    # member_services 업데이트 (upsert)
    existing = (
        supabase.table("member_services")
        .select("id")
        .eq("member_id", member_id)
        .eq("service_id", service_id)
        .execute()
    )

    if existing.data:
        supabase.table("member_services").update({
            "tier": tier,
            "status": SubscriptionStatus.ACTIVE.value,
            "updated_at": now,
        }).eq("id", existing.data[0]["id"]).execute()
    else:
        supabase.table("member_services").insert({
            "member_id": member_id,
            "service_id": service_id,
            "tier": tier,
            "status": SubscriptionStatus.ACTIVE.value,
            "started_at": now,
            "created_at": now,
            "updated_at": now,
        }).execute()

    logger.info(f"구독 활성화: member={member_id}, service={service_id}, tier={tier}")


async def _handle_invoice_paid(data: dict, supabase, now: str):
    """invoice.paid → expires_at 갱신"""
    subscription_id = data.get("subscription")
    if not subscription_id:
        return

    period_end = data.get("lines", {}).get("data", [{}])[0].get("period", {}).get("end")
    if period_end:
        period_end_dt = datetime.fromtimestamp(period_end, tz=timezone.utc).isoformat()

        # stripe_subscriptions 업데이트
        supabase.table("stripe_subscriptions").update({
            "current_period_end": period_end_dt,
            "status": "active",
            "updated_at": now,
        }).eq("stripe_subscription_id", subscription_id).execute()

        # member_services의 expires_at 갱신
        sub_result = (
            supabase.table("stripe_subscriptions")
            .select("member_id, service_id")
            .eq("stripe_subscription_id", subscription_id)
            .execute()
        )
        if sub_result.data:
            sub = sub_result.data[0]
            supabase.table("member_services").update({
                "expires_at": period_end_dt,
                "status": SubscriptionStatus.ACTIVE.value,
                "updated_at": now,
            }).eq("member_id", sub["member_id"]).eq("service_id", sub["service_id"]).execute()


async def _handle_payment_failed(data: dict, supabase, now: str):
    """invoice.payment_failed → status='past_due'"""
    subscription_id = data.get("subscription")
    if not subscription_id:
        return

    supabase.table("stripe_subscriptions").update({
        "status": "past_due",
        "updated_at": now,
    }).eq("stripe_subscription_id", subscription_id).execute()

    sub_result = (
        supabase.table("stripe_subscriptions")
        .select("member_id, service_id")
        .eq("stripe_subscription_id", subscription_id)
        .execute()
    )
    if sub_result.data:
        sub = sub_result.data[0]
        supabase.table("member_services").update({
            "status": SubscriptionStatus.SUSPENDED.value,
            "updated_at": now,
        }).eq("member_id", sub["member_id"]).eq("service_id", sub["service_id"]).execute()
        logger.warning(f"결제 실패: member={sub['member_id']}, service={sub['service_id']}")


async def _handle_subscription_deleted(data: dict, supabase, now: str):
    """customer.subscription.deleted → status='cancelled'"""
    subscription_id = data.get("id")
    if not subscription_id:
        return

    supabase.table("stripe_subscriptions").update({
        "status": "cancelled",
        "canceled_at": now,
        "updated_at": now,
    }).eq("stripe_subscription_id", subscription_id).execute()

    sub_result = (
        supabase.table("stripe_subscriptions")
        .select("member_id, service_id")
        .eq("stripe_subscription_id", subscription_id)
        .execute()
    )
    if sub_result.data:
        sub = sub_result.data[0]
        supabase.table("member_services").update({
            "status": SubscriptionStatus.CANCELLED.value,
            "updated_at": now,
        }).eq("member_id", sub["member_id"]).eq("service_id", sub["service_id"]).execute()
        logger.info(f"구독 취소: member={sub['member_id']}, service={sub['service_id']}")


async def _handle_subscription_updated(data: dict, supabase, now: str):
    """customer.subscription.updated → cancel_at_period_end 등 동기화"""
    subscription_id = data.get("id")
    if not subscription_id:
        return

    update = {
        "status": data.get("status", "active"),
        "cancel_at_period_end": data.get("cancel_at_period_end", False),
        "updated_at": now,
    }
    if data.get("current_period_end"):
        update["current_period_end"] = datetime.fromtimestamp(
            data["current_period_end"], tz=timezone.utc
        ).isoformat()

    supabase.table("stripe_subscriptions").update(update).eq(
        "stripe_subscription_id", subscription_id
    ).execute()
