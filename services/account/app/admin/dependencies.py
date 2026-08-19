"""
관리자 RBAC 의존성 모듈

DB 기반 관리자 권한 검증 (email 하드코딩 대체).
admin_role 컬럼과 admin_service_assignments 테이블 활용.

Cloudflare Access 인증:
  Cloudflare Access를 통과한 요청에는 Cf-Access-Authenticated-User-Email
  헤더와 Cf-Access-Jwt-Assertion(서명 JWT)이 함께 실린다.

  🔴 헤더는 "신원 주장"일 뿐 "권한"이 아니다.
     - 헤더를 근거로 회원을 자동 생성하거나 admin_role을 자동 승격하지 않는다.
     - DB에 이미 admin_role이 부여된 회원만 관리자로 인정한다.
     - 관리자 추가는 DB에서 admin_role을 직접 부여하는 수동 절차다 (의도된 동작).

     이유: Access를 우회해 앱에 직접 닿는 경로(포트 직접 접근, 내부망,
     Access 정책이 적용되지 않은 호스트)가 하나라도 있으면, 헤더 한 줄을
     위조하는 것만으로 사이트 전체를 장악할 수 있기 때문이다.

  추가 방어: CF_ACCESS_TEAM_DOMAIN / CF_ACCESS_AUD 환경변수가 설정돼 있으면
  Cf-Access-Jwt-Assertion의 서명·aud·만료·issuer까지 검증한다. 설정이 없으면
  검증을 건너뛰고 위의 admin_role 규칙만 적용한다 (기동은 깨지지 않음).
"""
import json
import os
import time
from typing import Optional

import httpx
from fastapi import HTTPException, Request
from jose import jwt as jose_jwt, JWTError
from loguru import logger

from shared_core.auth.jwt import get_current_member
from shared_core.db.client import get_supabase_client
from shared_core.types.member import AdminRole

# Cloudflare Access가 설정하는 헤더 (Cloudflare 인프라에서만 설정 가능)
CF_ACCESS_EMAIL_HEADER = "Cf-Access-Authenticated-User-Email"
CF_ACCESS_JWT_HEADER = "Cf-Access-Jwt-Assertion"

# Cloudflare Access 공개키(JWKS) 캐시: {team_domain: (fetched_at_monotonic, keys)}
_JWKS_CACHE: dict = {}
_JWKS_TTL_SECONDS = 3600
_JWKS_TIMEOUT_SECONDS = 5.0


def _normalize_team_domain(raw: str) -> str:
    """'myteam' / 'myteam.cloudflareaccess.com' / 'https://...' 를 호스트명으로 정규화"""
    domain = (raw or "").strip().rstrip("/")
    for prefix in ("https://", "http://"):
        if domain.startswith(prefix):
            domain = domain[len(prefix):]
    if not domain:
        return ""
    if "." not in domain:
        domain = f"{domain}.cloudflareaccess.com"
    return domain


def _cf_access_config() -> tuple:
    """
    (team_domain, aud) 반환. 둘 다 있어야 JWT 검증을 수행한다.

    환경변수가 없으면 ('', '') → 검증 생략 (admin_role 규칙만 적용).
    """
    return (
        _normalize_team_domain(os.getenv("CF_ACCESS_TEAM_DOMAIN", "")),
        os.getenv("CF_ACCESS_AUD", "").strip(),
    )


async def _get_cf_jwks(team_domain: str, force_refresh: bool = False) -> list:
    """
    Cloudflare Access 공개키 조회 (TTL 캐시).

    네트워크 실패 시 만료된 캐시라도 있으면 그것을 사용한다
    (CF 일시 장애로 관리자가 잠기는 것을 방지).
    """
    now = time.monotonic()
    cached = _JWKS_CACHE.get(team_domain)
    if cached and not force_refresh and (now - cached[0]) < _JWKS_TTL_SECONDS:
        return cached[1]

    url = f"https://{team_domain}/cdn-cgi/access/certs"
    try:
        async with httpx.AsyncClient(timeout=_JWKS_TIMEOUT_SECONDS) as client:
            response = await client.get(url)
            response.raise_for_status()
            keys = response.json().get("keys", []) or []
    except Exception as exc:
        if cached:
            logger.warning(
                f"CF Access JWKS 갱신 실패 ({type(exc).__name__}) → 캐시된 키 사용: {team_domain}"
            )
            return cached[1]
        logger.error(f"CF Access JWKS 조회 실패 ({type(exc).__name__}): {team_domain}")
        return []

    if keys:
        _JWKS_CACHE[team_domain] = (now, keys)
    return keys


async def _verify_cf_access_jwt(
    token: str, team_domain: str, expected_aud: str
) -> Optional[dict]:
    """
    Cf-Access-Jwt-Assertion 서명/aud/만료/issuer 검증.

    Returns:
        검증된 claims dict, 실패 시 None
    ⚠️ 토큰 원문은 절대 로그에 남기지 않는다.
    """
    try:
        kid = jose_jwt.get_unverified_header(token).get("kid")
    except Exception as exc:  # JWTError 포함 (변조된 토큰은 형식조차 깨질 수 있음)
        logger.warning(f"CF Access JWT 헤더 파싱 실패: {type(exc).__name__}")
        return None

    if not kid:
        logger.warning("CF Access JWT 거부: kid 없음")
        return None

    keys = await _get_cf_jwks(team_domain)
    key = next((k for k in keys if k.get("kid") == kid), None)
    if key is None:
        # 키 로테이션 가능성 → 강제 갱신 후 1회 재시도
        keys = await _get_cf_jwks(team_domain, force_refresh=True)
        key = next((k for k in keys if k.get("kid") == kid), None)
    if key is None:
        logger.warning(f"CF Access JWT 거부: 일치하는 공개키 없음 (kid={kid})")
        return None

    try:
        return jose_jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=expected_aud,
            issuer=f"https://{team_domain}",
        )
    except JWTError as exc:
        logger.warning(f"CF Access JWT 검증 실패: {type(exc).__name__}: {exc}")
        return None


async def _try_cf_access_auth(request: Request) -> Optional[dict]:
    """
    Cloudflare Access 헤더를 '신원 주장'으로만 사용해 관리자 여부를 확인한다.

    - 헤더 없음 → None (JWT 로그인 경로로 넘어감)
    - CF_ACCESS_* 환경변수가 설정된 경우 서명 JWT 검증 실패 → 403
    - 해당 이메일 회원이 이미 admin_role 보유 → 그 회원 반환
    - 회원 없음 / admin_role 없음 → 403 (자동 생성·자동 승격 없음)

    Returns:
        admin_role을 가진 member dict, 헤더가 없으면 None
    Raises:
        HTTPException(403): 신원은 확인됐지만 관리자가 아니거나 JWT 검증 실패
        HTTPException(503): 회원 조회 실패 (DB 오류 시 권한을 주지 않는다)
    """
    cf_email = request.headers.get(CF_ACCESS_EMAIL_HEADER)
    if not cf_email:
        return None

    cf_email = cf_email.strip()
    team_domain, expected_aud = _cf_access_config()

    # --- (2) 서명 JWT 검증 (설정된 경우에만) ---
    if team_domain and expected_aud:
        assertion = request.headers.get(CF_ACCESS_JWT_HEADER)
        if not assertion:
            logger.warning(
                f"CF Access 거부: {cf_email} - {CF_ACCESS_JWT_HEADER} 헤더 없음 "
                "(Access를 우회한 직접 접근 가능성)"
            )
            raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다")

        claims = await _verify_cf_access_jwt(assertion, team_domain, expected_aud)
        if not claims:
            logger.warning(f"CF Access 거부: {cf_email} - JWT 서명/aud/만료 검증 실패")
            raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다")

        # 검증된 토큰의 email을 신원의 최종 근거로 사용 (헤더 위조 방지)
        claim_email = (claims.get("email") or "").strip()
        if claim_email and claim_email.lower() != cf_email.lower():
            logger.warning(
                f"CF Access 거부: 헤더 이메일({cf_email})과 "
                f"JWT 이메일({claim_email}) 불일치"
            )
            raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다")
        if claim_email:
            cf_email = claim_email
    else:
        logger.debug(
            "CF_ACCESS_TEAM_DOMAIN/CF_ACCESS_AUD 미설정 → JWT 검증 생략 "
            "(admin_role 보유자만 통과)"
        )

    # --- (1) admin_role 보유자만 인정. 자동 생성/승격 없음 ---
    try:
        supabase = get_supabase_client()
        result = (
            supabase.table("members")
            .select("*")
            .eq("email", cf_email)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        # DB 오류로 권한을 열어주지 않는다 (구 버전은 여기서 super_admin을 반환했음)
        logger.error(f"CF Access 회원 조회 실패 ({cf_email}): {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=503, detail="일시적인 오류입니다. 잠시 후 다시 시도해주세요")

    if not result.data:
        logger.warning(
            f"CF Access 거부: {cf_email} - members에 해당 회원 없음 "
            "(자동 생성하지 않음. 관리자 추가는 DB에서 admin_role 부여로만 가능)"
        )
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다")

    member = result.data[0]
    if not member.get("admin_role"):
        logger.warning(
            f"CF Access 거부: {cf_email} - admin_role 없음 (자동 승격하지 않음)"
        )
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다")

    logger.info(f"CF Access 관리자 인증: {cf_email} (role={member['admin_role']})")
    return member


async def require_admin(request: Request) -> dict:
    """
    관리자 권한 확인

    1) Cloudflare Access 헤더 → 신원 확인 후 admin_role 보유자만 통과
       (헤더만으로는 권한을 주지 않음. 미보유 시 403)
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
