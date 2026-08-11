"""
메신저 연결 라우터

메시징용 OAuth 연결/해제 엔드포인트
"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from loguru import logger

from shared_core.auth.jwt import get_current_member
from shared_core.auth.oauth.handler import OAuthHandler
from shared_core.auth.oauth.user_info import get_oauth_user_info
from shared_core.db.client import get_supabase_client

from .service import get_messenger_for_member

router = APIRouter(prefix="/account/messenger", tags=["messenger"])

_oauth_handler = OAuthHandler()


@router.post("/connect")
async def messenger_connect(request: Request):
    """메시징 scope로 OAuth 시작"""
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    provider_info = get_messenger_for_member(member)
    if not provider_info:
        raise HTTPException(status_code=400, detail="해당 국가에 사용 가능한 메신저가 없습니다")

    provider = provider_info["provider"]
    required_scopes = provider_info.get("required_scopes") or []

    auth_url = _oauth_handler.build_auth_url(
        provider,
        extra_scopes=required_scopes,
        purpose="messaging",
    )

    # state에 redirect_url 저장
    state = auth_url.split("state=")[1].split("&")[0] if "state=" in auth_url else None
    if state:
        supabase = get_supabase_client()
        try:
            supabase.table("oauth_states").update(
                {"redirect_url": "/account/dashboard"}
            ).eq("state", state).execute()
        except Exception:
            pass

    return RedirectResponse(url=auth_url, status_code=303)


@router.get("/callback/{provider}")
async def messenger_callback(provider: str, code: str, state: str, request: Request):
    """메시징용 OAuth 콜백 처리"""
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    state_data = _oauth_handler.validate_state(state, provider)

    # purpose 확인
    if state_data.get("purpose") != "messaging":
        raise HTTPException(status_code=400, detail="잘못된 인증 목적입니다")

    try:
        token_data = await _oauth_handler.exchange_token(provider, code, state_data)
        user_info = await get_oauth_user_info(provider, token_data["access_token"])

        member_id = str(member["id"])
        supabase = get_supabase_client()

        # 기존 oauth_connections 확인
        existing = (
            supabase.table("oauth_connections")
            .select("id")
            .eq("member_id", member_id)
            .eq("provider", provider)
            .execute()
        )

        granted_scopes = token_data.get("scope", "").split()

        if existing.data:
            # UPDATE: messaging 관련 필드만 갱신
            supabase.table("oauth_connections").update({
                "access_token_encrypted": token_data["access_token"],
                "refresh_token_encrypted": token_data.get("refresh_token"),
                "messaging_enabled": True,
                "messaging_role": "sender",
                "scopes": granted_scopes,
            }).eq("member_id", member_id).eq("provider", provider).execute()
        else:
            # INSERT: 새 연결
            supabase.table("oauth_connections").insert({
                "member_id": member_id,
                "provider": provider,
                "provider_user_id": str(user_info["id"]),
                "provider_email": user_info.get("email"),
                "provider_name": user_info.get("name"),
                "is_primary": False,
                "access_token_encrypted": token_data["access_token"],
                "refresh_token_encrypted": token_data.get("refresh_token"),
                "messaging_enabled": True,
                "messaging_role": "sender",
                "scopes": granted_scopes,
            }).execute()

        return RedirectResponse(url="/account/dashboard", status_code=303)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"메신저 콜백 처리 오류: {e}")
        raise HTTPException(status_code=500, detail="메신저 연결 중 오류가 발생했습니다")


@router.post("/disconnect")
async def messenger_disconnect(request: Request):
    """메시징 비활성화 (OAuth 연결은 유지)"""
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    provider_info = get_messenger_for_member(member)
    if not provider_info:
        raise HTTPException(status_code=400, detail="해당 국가에 사용 가능한 메신저가 없습니다")

    member_id = str(member["id"])
    provider = provider_info["provider"]

    supabase = get_supabase_client()
    try:
        supabase.table("oauth_connections").update({
            "messaging_enabled": False,
        }).eq("member_id", member_id).eq("provider", provider).execute()
    except Exception as e:
        logger.error(f"메신저 연결 해제 실패: {e}")
        raise HTTPException(status_code=500, detail="연결 해제 중 오류가 발생했습니다")

    return RedirectResponse(url="/account/dashboard", status_code=303)
