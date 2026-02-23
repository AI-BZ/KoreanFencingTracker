"""
Auth Router - 인증 라우터

JWT/OAuth 핵심 로직은 shared_core에서 import.
이 파일은 라우트 정의 + 템플릿 렌더링 담당.
"""
import os
from datetime import datetime
from typing import Optional
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from loguru import logger

from shared_core.auth.jwt import (
    create_access_token,
    get_current_member,
)
from shared_core.auth.oauth.providers import (
    get_available_providers,
    get_promotional_providers,
)
from shared_core.auth.oauth.handler import OAuthHandler
from shared_core.auth.oauth.user_info import get_oauth_user_info
from shared_core.db.client import get_supabase_client
from shared_core.privacy.masking import mask_korean_name
from shared_core.privacy.anonymize import is_minor

router = APIRouter(prefix="/auth", tags=["auth"])

# 템플릿
_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))

# OAuth 핸들러 인스턴스 (shared_core)
_oauth_handler = OAuthHandler()


ALLOWED_REDIRECT_DOMAINS = [
    "fencingmind.ai",
    "localhost",
    "127.0.0.1",
]


def _is_safe_redirect(url: str) -> bool:
    """오픈 리다이렉트 방지 - 허용된 도메인만 리다이렉트"""
    if not url:
        return False
    parsed = urlparse(url)
    if not parsed.hostname:
        return True  # 상대 경로는 허용
    return any(parsed.hostname.endswith(d) for d in ALLOWED_REDIRECT_DOMAINS)


def get_supabase():
    """Supabase 클라이언트 가져오기 (shared_core 싱글톤 사용)"""
    return get_supabase_client()


# =============================================
# OAuth 로그인
# =============================================

@router.get("/providers")
async def get_oauth_providers(request: Request):
    """
    사용 가능한 OAuth 제공자 목록 반환
    IP 기반으로 한국/해외 구분
    """
    country_code = "KR"  # 기본값

    providers = get_available_providers(country_code)
    promotional = get_promotional_providers()

    return {
        "providers": providers,
        "promotional_providers": promotional,
        "country_code": country_code,
    }


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, redirect: Optional[str] = None):
    """로그인 페이지 표시"""
    return _templates.TemplateResponse("auth/login.html", {
        "request": request,
        "redirect_url": redirect or "",
    })


@router.get("/login/{provider}")
async def oauth_login(provider: str, request: Request, promotional: bool = False, redirect: Optional[str] = None):
    """OAuth 로그인 시작 (OAuthHandler 사용)"""
    auth_url = _oauth_handler.build_auth_url(provider, promotional)
    if redirect and _is_safe_redirect(redirect):
        state = auth_url.split("state=")[1].split("&")[0] if "state=" in auth_url else None
        if state:
            _oauth_handler._pending_redirects[state] = redirect
    return RedirectResponse(url=auth_url)


@router.get("/callback/{provider}")
async def oauth_callback(provider: str, code: str, state: str, request: Request):
    """OAuth 콜백 처리 (OAuthHandler 사용)"""
    state_data = _oauth_handler.validate_state(state, provider)

    try:
        # 토큰 교환
        token_data = await _oauth_handler.exchange_token(provider, code, state_data)

        # 사용자 정보 가져오기
        user_info = await get_oauth_user_info(provider, token_data["access_token"])

        # 기존 회원 확인
        supabase = get_supabase()
        existing_oauth = supabase.table("oauth_connections").select("*").eq(
            "provider", provider
        ).eq("provider_user_id", user_info["id"]).execute()

        if existing_oauth.data:
            # 기존 회원 - 로그인
            member_id = existing_oauth.data[0]["member_id"]
            member = supabase.table("members").select("*").eq("id", member_id).single().execute()

            if member.data:
                access_token = create_access_token({
                    "member_id": str(member.data["id"]),
                    "email": member.data["email"],
                    "member_type": member.data["member_type"],
                })

                redirect_url = _oauth_handler._pending_redirects.pop(state, None)
                if redirect_url and not _is_safe_redirect(redirect_url):
                    redirect_url = None
                response = RedirectResponse(url=redirect_url or "/", status_code=303)
                response.set_cookie(
                    key="access_token",
                    value=access_token,
                    httponly=True,
                    max_age=60 * 60 * 24,  # 24시간
                    samesite="lax",
                    domain=os.getenv("COOKIE_DOMAIN", ".fencingmind.ai"),
                )
                return response

        # 신규 회원 - 회원가입 페이지로
        registration_token = _oauth_handler.store_pending_registration(
            provider, user_info, token_data,
            promotional=state_data.get("promotional", False),
        )

        return RedirectResponse(
            url=f"/auth/register?token={registration_token}",
            status_code=303
        )

    except Exception as e:
        logger.exception(f"OAuth 콜백 처리 오류: {e}")
        return _templates.TemplateResponse("auth/error.html", {
            "request": request,
            "error_message": "인증 처리 중 오류가 발생했습니다. 다시 시도해주세요.",
        }, status_code=500)


# =============================================
# 회원가입
# =============================================

@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, token: Optional[str] = None):
    """회원가입 페이지"""
    pending = None
    if token:
        pending = _oauth_handler.get_pending_registration(token)
        if not pending:
            raise HTTPException(status_code=400, detail="유효하지 않은 등록 토큰입니다")

    return _templates.TemplateResponse(
        "auth/register.html",
        {
            "request": request,
            "token": token,
            "pending": pending,
            "member_types": [
                {"value": "player", "label": "선수회원"},
                {"value": "player_parent", "label": "선수 부모회원"},
                {"value": "club_coach", "label": "클럽 코치"},
                {"value": "school_coach", "label": "학교 코치"},
                {"value": "general", "label": "일반 회원"},
            ],
        }
    )


@router.post("/register")
async def register_member(
    token: str = Form(...),
    full_name: str = Form(...),
    email: str = Form(...),
    phone: Optional[str] = Form(None),
    birth_date: Optional[str] = Form(None),
    member_type: str = Form(...),
    marketing_consent: bool = Form(False),
    promotional_consent: bool = Form(False),
):
    """회원가입 처리"""
    pending = _oauth_handler.pop_pending_registration(token)
    if not pending:
        raise HTTPException(status_code=400, detail="유효하지 않은 등록 토큰입니다")

    # 생년월일 파싱
    parsed_birth_date = None
    if birth_date:
        try:
            parsed_birth_date = datetime.strptime(birth_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="잘못된 생년월일 형식입니다")

    # 14세 미만 확인
    if is_minor(parsed_birth_date) and member_type == "player":
        raise HTTPException(
            status_code=400,
            detail="14세 미만 선수는 보호자(부모회원)를 통해 등록해야 합니다"
        )

    supabase = get_supabase()

    # 이메일 중복 확인
    existing = supabase.table("members").select("id").eq("email", email).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="이미 가입된 이메일입니다")

    # 회원 생성
    member_data = {
        "full_name": full_name,
        "display_name": mask_korean_name(full_name),
        "email": email,
        "phone": phone,
        "birth_date": birth_date,
        "member_type": member_type,
        "marketing_consent": marketing_consent,
        "promotional_consent": promotional_consent,
        "verification_status": "pending",
    }

    result = supabase.table("members").insert(member_data).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="회원가입 처리 중 오류가 발생했습니다")

    member = result.data[0]

    # OAuth 연결 저장
    oauth_data = {
        "member_id": member["id"],
        "provider": pending["provider"],
        "provider_user_id": pending["provider_user_id"],
        "provider_email": pending.get("email"),
        "provider_name": pending.get("name"),
        "is_primary": True,
        "for_promotional": pending.get("promotional", False),
    }

    supabase.table("oauth_connections").insert(oauth_data).execute()

    # 토큰 생성
    access_token = create_access_token({
        "member_id": str(member["id"]),
        "email": member["email"],
        "member_type": member["member_type"],
    })

    # 쿠키에 토큰 저장하고 인증 페이지로 리다이렉트
    response = RedirectResponse(url="/account/verification", status_code=303)
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=60 * 60 * 24,
        samesite="lax",
        domain=os.getenv("COOKIE_DOMAIN", ".fencingmind.ai"),
    )

    return response


# =============================================
# 로그아웃
# =============================================

@router.post("/logout")
async def logout():
    """로그아웃"""
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("access_token", domain=os.getenv("COOKIE_DOMAIN", ".fencingmind.ai"))
    return response


@router.get("/logout")
async def logout_get():
    """로그아웃 (GET)"""
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("access_token", domain=os.getenv("COOKIE_DOMAIN", ".fencingmind.ai"))
    return response
