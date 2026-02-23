"""
서비스 구독 관리 라우터

member_services 테이블 CRUD - 회원의 서비스 구독 관리
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger

from shared_core.auth.jwt import get_current_member
from shared_core.db.client import get_supabase_client
from shared_core.types.service import ServiceType, SubscriptionTier, SubscriptionStatus
from shared_core.auth.models import MemberServiceCreate, MemberServiceResponse

router = APIRouter(prefix="/services", tags=["subscriptions"])


def _require_member(member: dict | None) -> dict:
    """인증된 회원 필수 - None이면 401"""
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    return member


@router.get("", response_model=list[MemberServiceResponse])
async def list_subscriptions(request: Request):
    """내 서비스 구독 목록 조회"""
    member = _require_member(await get_current_member(request))
    member_id = member["id"]

    try:
        supabase = get_supabase_client()
        result = (
            supabase.table("member_services")
            .select("*")
            .eq("member_id", member_id)
            .execute()
        )
        return result.data
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"구독 목록 조회 오류: {e}")
        raise HTTPException(status_code=500, detail="구독 목록을 불러올 수 없습니다")


@router.post("/{service_id}/subscribe", response_model=MemberServiceResponse, status_code=201)
async def subscribe_service(service_id: ServiceType, body: MemberServiceCreate, request: Request):
    """서비스 구독 신청"""
    member = _require_member(await get_current_member(request))
    member_id = member["id"]

    try:
        supabase = get_supabase_client()

        # 이미 활성 구독이 있는지 확인
        existing = (
            supabase.table("member_services")
            .select("id")
            .eq("member_id", member_id)
            .eq("service_id", service_id.value)
            .eq("status", SubscriptionStatus.ACTIVE.value)
            .execute()
        )
        if existing.data:
            raise HTTPException(
                status_code=409,
                detail=f"이미 {service_id.value} 서비스에 활성 구독이 있습니다",
            )

        now = datetime.now(timezone.utc).isoformat()
        row = {
            "member_id": member_id,
            "service_id": service_id.value,
            "tier": body.tier.value,
            "status": SubscriptionStatus.ACTIVE.value,
            "started_at": now,
            "created_at": now,
            "updated_at": now,
        }
        result = supabase.table("member_services").insert(row).execute()

        if not result.data:
            raise HTTPException(status_code=500, detail="구독 생성에 실패했습니다")

        logger.info(f"회원 {member_id} → {service_id.value} 구독 생성 (tier={body.tier.value})")
        return result.data[0]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"구독 생성 오류: {e}")
        raise HTTPException(status_code=500, detail="구독 처리 중 오류가 발생했습니다")


@router.patch("/{service_id}", response_model=MemberServiceResponse)
async def update_subscription(service_id: ServiceType, body: MemberServiceCreate, request: Request):
    """구독 등급 변경"""
    member = _require_member(await get_current_member(request))
    member_id = member["id"]

    try:
        supabase = get_supabase_client()

        # 활성 구독 조회
        existing = (
            supabase.table("member_services")
            .select("*")
            .eq("member_id", member_id)
            .eq("service_id", service_id.value)
            .eq("status", SubscriptionStatus.ACTIVE.value)
            .execute()
        )
        if not existing.data:
            raise HTTPException(
                status_code=404,
                detail=f"{service_id.value} 서비스에 활성 구독이 없습니다",
            )

        subscription_id = existing.data[0]["id"]
        now = datetime.now(timezone.utc).isoformat()
        result = (
            supabase.table("member_services")
            .update({"tier": body.tier.value, "updated_at": now})
            .eq("id", subscription_id)
            .execute()
        )

        if not result.data:
            raise HTTPException(status_code=500, detail="구독 변경에 실패했습니다")

        logger.info(f"회원 {member_id} → {service_id.value} 등급 변경 → {body.tier.value}")
        return result.data[0]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"구독 변경 오류: {e}")
        raise HTTPException(status_code=500, detail="구독 변경 중 오류가 발생했습니다")


@router.delete("/{service_id}")
async def cancel_subscription(service_id: ServiceType, request: Request):
    """구독 취소"""
    member = _require_member(await get_current_member(request))
    member_id = member["id"]

    try:
        supabase = get_supabase_client()

        # 활성 구독 조회
        existing = (
            supabase.table("member_services")
            .select("id")
            .eq("member_id", member_id)
            .eq("service_id", service_id.value)
            .eq("status", SubscriptionStatus.ACTIVE.value)
            .execute()
        )
        if not existing.data:
            raise HTTPException(
                status_code=404,
                detail=f"{service_id.value} 서비스에 활성 구독이 없습니다",
            )

        subscription_id = existing.data[0]["id"]
        now = datetime.now(timezone.utc).isoformat()
        supabase.table("member_services").update(
            {"status": SubscriptionStatus.CANCELLED.value, "updated_at": now}
        ).eq("id", subscription_id).execute()

        logger.info(f"회원 {member_id} → {service_id.value} 구독 취소")
        return {"detail": f"{service_id.value} 서비스 구독이 취소되었습니다"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"구독 취소 오류: {e}")
        raise HTTPException(status_code=500, detail="구독 취소 중 오류가 발생했습니다")
