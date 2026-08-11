"""
관리자 RBAC 의존성 모듈

DB 기반 관리자 권한 검증 (email 하드코딩 대체).
admin_role 컬럼과 admin_service_assignments 테이블 활용.

Cloudflare Access 인증:
  Cloudflare Access OTP를 통과하면 Cf-Access-Authenticated-User-Email 헤더가
  자동으로 설정됨. 이 헤더로 admin 인증을 처리하여 별도 OAuth 로그인 없이
  관리자 대시보드에 접근 가능.
"""
import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, Request
from loguru import logger

from shared_core.auth.jwt import get_current_member
from shared_core.db.client import get_supabase_client
from shared_core.types.member import AdminRole

# Cloudflare Access가 설정하는 헤더 (Cloudflare 인프라에서만 설정 가능)
CF_ACCESS_EMAIL_HEADER = "Cf-Access-Authenticated-User-Email"


async def _try_cf_access_auth(request: Request) -> Optional[dict]:
    """
    Cloudflare Access OTP 인증 헤더 확인.

    Cloudflare Access를 통과한 요청에는 Cf-Access-Authenticated-User-Email
    헤더가 자동으로 포함됨. 이 이메일로 members 테이블에서 회원 조회.
    회원이 없으면 자동 생성 (super_admin).

    Returns:
        member dict if CF Access authenticated, None otherwise
    """
    cf_email = request.headers.get(CF_ACCESS_EMAIL_HEADER)
    if not cf_email:
        return None

    logger.info(f"Cloudflare Access 인증: {cf_email}")

    try:
        supabase = get_supabase_client()

        # DB에서 회원 조회
        result = (
            supabase.table("members")
            .select("*")
            .eq("email", cf_email)
            .limit(1)
            .execute()
        )

        if result.data:
            member = result.data[0]
            # CF Access를 통과했으면 admin_role 보장 (DB에도 반영)
            if not member.get("admin_role"):
                supabase.table("members").update({
                    "admin_role": "super_admin",
                }).eq("id", member["id"]).execute()
                member["admin_role"] = "super_admin"
            return member

        # members 테이블에 없는 경우 → 자동 생성
        # RLS 정책: anon INSERT는 verification_status='pending'만 허용
        # 따라서 2단계로 처리: INSERT(pending) → UPDATE(admin 권한 설정)
        logger.info(f"CF Access admin 자동 생성: {cf_email}")
        new_member = supabase.table("members").insert({
            "email": cf_email,
            "full_name": cf_email.split("@")[0],
            "member_type": "general",
            "member_status": "active",
            "verification_status": "pending",
        }).execute()

        if new_member.data:
            member_id = new_member.data[0]["id"]
            # admin 권한 및 인증 상태 업데이트 (anon UPDATE 정책: true)
            supabase.table("members").update({
                "admin_role": "super_admin",
                "email_verified": True,
                "verification_status": "verified",
            }).eq("id", member_id).execute()

            member = new_member.data[0]
            member["admin_role"] = "super_admin"
            member["email_verified"] = True
            member["verification_status"] = "verified"
            return member

    except Exception as e:
        logger.error(f"CF Access auth 실패: {e}")

    # DB 오류 시 가상 컨텍스트 (읽기 전용 fallback)
    return {
        "id": None,
        "email": cf_email,
        "full_name": cf_email.split("@")[0],
        "admin_role": "super_admin",
        "member_type": "admin",
        "_cf_access_only": True,
    }


async def require_admin(request: Request) -> dict:
    """
    관리자 권한 확인

    1) Cloudflare Access 헤더 → 통과 (별도 로그인 불필요)
    2) JWT 기반 admin_role IS NOT NULL → 통과

    Returns:
        member dict (admin_role 포함)
    """
    # Cloudflare Access 인증 우선
    cf_admin = await _try_cf_access_auth(request)
    if cf_admin:
        return cf_admin

    # JWT 기반 인증
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    admin_role = member.get("admin_role")
    if not admin_role:
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다")

    return member


async def require_super_admin(request: Request) -> dict:
    """
    최고 관리자 권한 확인 (admin_role == 'super_admin')
    """
    member = await require_admin(request)
    if member.get("admin_role") != AdminRole.SUPER_ADMIN.value:
        raise HTTPException(status_code=403, detail="최고 관리자 권한이 필요합니다")
    return member


async def require_service_admin(request: Request, service_id: str) -> dict:
    """
    서비스 관리자 권한 확인

    super_admin이거나, service_admin이면서 해당 서비스에 배정된 경우.
    """
    member = await require_admin(request)
    admin_role = member.get("admin_role")

    # super_admin은 모든 서비스 접근 가능
    if admin_role == AdminRole.SUPER_ADMIN.value:
        return member

    # service_admin은 배정된 서비스만 접근 가능
    if admin_role == AdminRole.SERVICE_ADMIN.value:
        supabase = get_supabase_client()
        assignment = (
            supabase.table("admin_service_assignments")
            .select("id")
            .eq("member_id", member["id"])
            .eq("service_id", service_id)
            .execute()
        )
        if assignment.data:
            return member

    raise HTTPException(
        status_code=403,
        detail=f"'{service_id}' 서비스 관리 권한이 필요합니다"
    )


async def log_admin_action(
    admin_id: Optional[str],
    action: str,
    target_type: str,
    target_id: Optional[str] = None,
    details: Optional[dict] = None,
    ip_address: Optional[str] = None,
) -> None:
    """
    관리자 행동을 admin_audit_logs에 기록

    Args:
        admin_id: 관리자 member_id (None이면 CF Access only 관리자)
        action: 행동 유형 (approve, reject, suspend, update 등)
        target_type: 대상 유형 (member, verification, player_claim, org_claim)
        target_id: 대상 ID
        details: 추가 상세 정보 (JSONB)
        ip_address: 관리자 IP
    """
    if not admin_id:
        logger.info(f"Admin action (CF Access, no member record): {action} {target_type}/{target_id}")
        return

    try:
        supabase = get_supabase_client()
        supabase.table("admin_audit_logs").insert({
            "admin_id": admin_id,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "details": json.dumps(details or {}, ensure_ascii=False),
            "ip_address": ip_address,
        }).execute()
    except Exception as e:
        logger.error(f"감사 로그 기록 실패: {e}")


def get_client_ip(request: Request) -> str:
    """클라이언트 IP 추출"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    if request.client:
        return request.client.host
    return "unknown"
