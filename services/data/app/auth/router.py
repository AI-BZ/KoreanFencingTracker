"""Auth Router - Account 서비스 리다이렉트 shim + 카카오 OAuth 직접 처리"""
import os
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from loguru import logger
from pydantic import BaseModel

from shared_core.auth.config import get_shared_auth_settings
from shared_core.auth.jwt import create_access_token, get_current_member
from shared_core.auth.models import MemberResponse
from shared_core.auth.oauth.handler import OAuthHandler
from shared_core.auth.oauth.user_info import get_oauth_user_info
from shared_core.db.client import get_supabase_client

router = APIRouter(prefix="/auth", tags=["auth"])
ACCOUNT_URL = os.getenv("ACCOUNT_SERVICE_URL", "https://account.fencingmind.ai")

# OAuth handler singleton
_oauth_handler = OAuthHandler()


def _is_kakao_configured() -> bool:
    """카카오 OAuth가 설정되어 있는지 확인"""
    settings = get_shared_auth_settings()
    return bool(settings.KAKAO_CLIENT_ID)


# =============================================
# 기존 라우트 (Account 서비스 리다이렉트 shim)
# =============================================

@router.get("/login")
async def login_redirect(request: Request, redirect: Optional[str] = None):
    url = f"{ACCOUNT_URL}/auth/login"
    if redirect:
        url += f"?redirect={redirect}"
    return RedirectResponse(url=url)


@router.get("/me")
async def get_my_profile(request: Request):
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    return MemberResponse(**member)


@router.post("/logout")
async def logout_redirect():
    return RedirectResponse(url=f"{ACCOUNT_URL}/auth/logout", status_code=303)


@router.get("/logout")
async def logout_redirect_get():
    return RedirectResponse(url=f"{ACCOUNT_URL}/auth/logout")


# =============================================
# 카카오 OAuth 라우트
# =============================================

@router.get("/login/kakao")
async def kakao_login(request: Request, redirect: Optional[str] = None):
    """카카오 로그인 시작 - 카카오 인가 페이지로 리다이렉트"""
    if not _is_kakao_configured():
        raise HTTPException(status_code=503, detail="카카오 로그인이 설정되지 않았습니다")

    try:
        auth_url = _oauth_handler.build_auth_url("kakao", purpose="login")
        return RedirectResponse(url=auth_url)
    except Exception as e:
        logger.error(f"카카오 로그인 URL 생성 실패: {e}")
        raise HTTPException(status_code=500, detail="카카오 로그인을 시작할 수 없습니다")


@router.get("/callback/kakao")
async def kakao_callback(request: Request, code: str = "", state: str = "",
                         error: Optional[str] = None,
                         error_description: Optional[str] = None):
    """카카오 OAuth 콜백 처리"""
    # 사용자가 로그인 취소한 경우
    if error:
        logger.warning(f"카카오 로그인 취소/오류: {error} - {error_description}")
        return RedirectResponse(url="/?login_error=cancelled")

    if not code or not state:
        raise HTTPException(status_code=400, detail="잘못된 콜백 요청입니다")

    # 1. State 검증 (CSRF 방지)
    try:
        state_data = _oauth_handler.validate_state(state, "kakao")
    except HTTPException:
        return RedirectResponse(url="/?login_error=invalid_state")

    # 2. 토큰 교환
    try:
        token_data = await _oauth_handler.exchange_token("kakao", code, state_data)
    except HTTPException:
        logger.error("카카오 토큰 교환 실패")
        return RedirectResponse(url="/?login_error=token_exchange")

    access_token = token_data.get("access_token")
    if not access_token:
        return RedirectResponse(url="/?login_error=no_token")

    # 3. 사용자 정보 가져오기
    try:
        user_info = await get_oauth_user_info("kakao", access_token)
    except Exception as e:
        logger.error(f"카카오 사용자 정보 조회 실패: {e}")
        return RedirectResponse(url="/?login_error=user_info")

    kakao_id = str(user_info["id"])
    kakao_name = user_info.get("name")
    kakao_email = user_info.get("email")

    supabase = get_supabase_client()

    # 4. 기존 OAuth 연결 확인
    try:
        oauth_result = (
            supabase.table("oauth_connections")
            .select("member_id")
            .eq("provider", "kakao")
            .eq("provider_user_id", kakao_id)
            .execute()
        )
    except Exception as e:
        logger.error(f"OAuth 연결 조회 실패: {e}")
        return RedirectResponse(url="/?login_error=db_error")

    if oauth_result.data:
        # 기존 연결 있음 → 로그인
        member_id = oauth_result.data[0]["member_id"]
        return await _login_member(supabase, member_id, kakao_id, kakao_name)

    # 5. 이메일로 기존 회원 매칭 시도
    if kakao_email:
        try:
            email_result = (
                supabase.table("members")
                .select("id")
                .eq("email", kakao_email)
                .execute()
            )
        except Exception as e:
            logger.error(f"이메일 매칭 조회 실패: {e}")
            email_result = type("R", (), {"data": []})()

        if email_result.data:
            member_id = email_result.data[0]["id"]
            # 자동 링크 + 로그인
            await _link_kakao_to_member(supabase, member_id, kakao_id,
                                       kakao_name, kakao_email, access_token,
                                       token_data.get("refresh_token"))
            return await _login_member(supabase, member_id, kakao_id, kakao_name)

    # 6. 매칭 실패 → pending_registration 저장 → 등록 폼으로 리다이렉트
    try:
        reg_token = _oauth_handler.store_pending_registration(
            provider="kakao",
            user_info=user_info,
            token_data=token_data,
        )
        return RedirectResponse(url=f"/auth/register?token={reg_token}")
    except Exception as e:
        logger.error(f"등록 대기 저장 실패: {e}")
        return RedirectResponse(url="/?login_error=registration")


class KakaoRegisterRequest(BaseModel):
    """카카오 신규 회원 등록 요청"""
    registration_token: str
    full_name: str
    email: str
    phone: Optional[str] = None
    member_type: str = "player"
    organization_id: Optional[int] = None


@router.post("/register-kakao")
async def register_kakao(request: Request, body: KakaoRegisterRequest):
    """카카오 계정으로 신규 회원 등록 완료"""
    # pending_registration에서 정보 가져오기
    pending = _oauth_handler.pop_pending_registration(body.registration_token)
    if not pending:
        raise HTTPException(status_code=400, detail="등록 토큰이 만료되었거나 유효하지 않습니다")

    supabase = get_supabase_client()

    # 이메일 중복 확인
    try:
        existing = (
            supabase.table("members")
            .select("id")
            .eq("email", body.email)
            .execute()
        )
        if existing.data:
            raise HTTPException(status_code=409, detail="이미 등록된 이메일입니다")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"이메일 중복 확인 실패: {e}")
        raise HTTPException(status_code=500, detail="회원 등록 처리 중 오류가 발생했습니다")

    # 회원 생성
    member_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    kakao_id = pending["provider_user_id"]

    try:
        member_data = {
            "id": member_id,
            "full_name": body.full_name,
            "email": body.email,
            "phone": body.phone,
            "member_type": body.member_type,
            "organization_id": body.organization_id,
            "verification_status": "pending",
            "privacy_public": False,
            "marketing_consent": False,
            "promotional_consent": False,
            "kakao_id": kakao_id,
            "kakao_nickname": pending.get("name"),
            "created_at": now,
            "updated_at": now,
        }
        supabase.table("members").insert(member_data).execute()
    except Exception as e:
        logger.error(f"회원 생성 실패: {e}")
        raise HTTPException(status_code=500, detail="회원 등록에 실패했습니다")

    # OAuth 연결 생성
    try:
        oauth_data = {
            "id": str(uuid4()),
            "member_id": member_id,
            "provider": "kakao",
            "provider_user_id": kakao_id,
            "provider_email": pending.get("email"),
            "provider_name": pending.get("name"),
            "is_primary": True,
            "for_promotional": False,
            "access_token_encrypted": pending.get("access_token"),
            "refresh_token_encrypted": pending.get("refresh_token"),
            "created_at": now,
            "updated_at": now,
        }
        supabase.table("oauth_connections").insert(oauth_data).execute()
    except Exception as e:
        logger.error(f"OAuth 연결 생성 실패: {e}")
        # 회원은 생성됨, OAuth 연결만 실패 → 에러 로깅하되 계속 진행

    # JWT 토큰 발급
    jwt_token = create_access_token(data={
        "member_id": member_id,
        "email": body.email,
        "member_type": body.member_type,
    })

    response = JSONResponse(content={
        "message": "회원 등록이 완료되었습니다",
        "member_id": member_id,
        "access_token": jwt_token,
        "token_type": "bearer",
    })
    response.set_cookie(
        key="access_token",
        value=jwt_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 24,  # 24시간
    )
    return response


@router.get("/register")
async def register_form(request: Request, token: Optional[str] = None):
    """카카오 회원 등록 폼 페이지 (pending_registration 정보 표시)"""
    if not token:
        return RedirectResponse(url="/auth/login/kakao")

    pending = _oauth_handler.get_pending_registration(token)
    if not pending:
        return RedirectResponse(url="/?login_error=expired_token")

    # 템플릿 렌더링 대신 간단한 JSON 응답 (프론트엔드에서 폼 처리)
    return JSONResponse(content={
        "registration_token": token,
        "provider": pending["provider"],
        "suggested_name": pending.get("name", ""),
        "suggested_email": pending.get("email", ""),
    })


@router.get("/kakao/status")
async def kakao_status():
    """카카오 로그인 사용 가능 여부 확인 API"""
    return {"kakao_enabled": _is_kakao_configured()}


# =============================================
# 내부 헬퍼 함수
# =============================================

async def _login_member(supabase, member_id: str, kakao_id: str,
                        kakao_name: Optional[str]) -> RedirectResponse:
    """회원 로그인 처리: JWT 발급 + 쿠키 설정 + 카카오 정보 업데이트"""
    try:
        member_result = (
            supabase.table("members")
            .select("id, email, member_type, full_name")
            .eq("id", member_id)
            .single()
            .execute()
        )
        member = member_result.data
    except Exception as e:
        logger.error(f"회원 조회 실패 (login): {e}")
        return RedirectResponse(url="/?login_error=member_not_found")

    if not member:
        return RedirectResponse(url="/?login_error=member_not_found")

    # 카카오 정보 업데이트 (최신 닉네임 반영)
    update_data = {"kakao_id": kakao_id, "updated_at": datetime.now(timezone.utc).isoformat()}
    if kakao_name:
        update_data["kakao_nickname"] = kakao_name
    try:
        supabase.table("members").update(update_data).eq("id", member_id).execute()
    except Exception as e:
        logger.warning(f"카카오 정보 업데이트 실패 (비치명적): {e}")

    # JWT 토큰 발급
    jwt_token = create_access_token(data={
        "member_id": member["id"],
        "email": member.get("email", ""),
        "member_type": member.get("member_type", "general"),
    })

    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        key="access_token",
        value=jwt_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 24,  # 24시간
    )
    return response


async def _link_kakao_to_member(supabase, member_id: str, kakao_id: str,
                                kakao_name: Optional[str], kakao_email: Optional[str],
                                access_token: str, refresh_token: Optional[str]):
    """기존 회원에 카카오 계정 연결"""
    now = datetime.now(timezone.utc).isoformat()

    # members 테이블에 kakao_id 저장
    update_data = {"kakao_id": kakao_id, "updated_at": now}
    if kakao_name:
        update_data["kakao_nickname"] = kakao_name
    try:
        supabase.table("members").update(update_data).eq("id", member_id).execute()
    except Exception as e:
        logger.error(f"회원 카카오 정보 업데이트 실패: {e}")

    # oauth_connections에 연결 추가
    try:
        oauth_data = {
            "id": str(uuid4()),
            "member_id": member_id,
            "provider": "kakao",
            "provider_user_id": kakao_id,
            "provider_email": kakao_email,
            "provider_name": kakao_name,
            "is_primary": True,
            "for_promotional": False,
            "access_token_encrypted": access_token,
            "refresh_token_encrypted": refresh_token,
            "created_at": now,
            "updated_at": now,
        }
        supabase.table("oauth_connections").insert(oauth_data).execute()
    except Exception as e:
        logger.error(f"OAuth 연결 생성 실패: {e}")
