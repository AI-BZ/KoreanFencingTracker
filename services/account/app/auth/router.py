"""
Auth Router - 인증 라우터

JWT/OAuth 핵심 로직은 shared_core에서 import.
이 파일은 라우트 정의 + 템플릿 렌더링 담당.
"""
import os
import json
import secrets
from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path
from urllib.parse import urlparse, quote

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
from shared_core.email.service import EmailService
from shared_core.utils.country import phone_to_country
from app.config import get_account_settings

router = APIRouter(prefix="/auth", tags=["auth"])

# 템플릿
_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))

# OAuth 핸들러 인스턴스 (shared_core)
_oauth_handler = OAuthHandler()

# 이메일 서비스 (lazy init - .env 로드 후 생성)
_email_service = None

def get_email_service() -> EmailService:
    global _email_service
    if _email_service is None:
        settings = get_account_settings()
        _email_service = EmailService(api_key=settings.RESEND_API_KEY)
    return _email_service


import re

NICKNAME_PATTERN = re.compile(r'^[a-zA-Z0-9_]{3,20}$')

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


def _set_auth_cookies(response, access_token: str, email: str):
    """access_token (httpOnly) + user_display (JS 읽기용) 쿠키 설정"""
    cookie_domain = os.getenv("COOKIE_DOMAIN", ".fencingmind.ai")
    # JWT - httpOnly (보안)
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=True,
        max_age=60 * 60 * 24,  # 24시간
        samesite="lax",
        domain=cookie_domain,
    )
    # UI 표시용 - JS에서 읽을 수 있음
    display_info = quote(json.dumps({"email": email}, ensure_ascii=False))
    response.set_cookie(
        key="user_display",
        value=display_info,
        httponly=False,
        secure=True,
        max_age=60 * 60 * 24,
        samesite="lax",
        domain=cookie_domain,
    )


# =============================================
# 닉네임 중복 확인
# =============================================

@router.get("/check-nickname")
async def check_nickname(nickname: str):
    """닉네임 사용 가능 여부 확인 (대소문자 구분 없음)"""
    if not nickname or not NICKNAME_PATTERN.match(nickname):
        return {"available": False, "reason": "영문, 숫자, 밑줄(_)만 사용 가능 (3~20자)"}

    supabase = get_supabase()
    result = supabase.table("members").select("id").ilike("nickname", nickname).execute()
    if result.data:
        return {"available": False, "reason": "이미 사용 중인 닉네임입니다"}
    return {"available": True}


# =============================================
# OAuth 로그인
# =============================================

@router.get("/providers")
async def get_oauth_providers(request: Request):
    """
    사용 가능한 OAuth 제공자 목록 반환
    IP 기반으로 한국/해외 구분
    """
    # TODO: IP 기반 국가 감지 구현 시 교체
    country_code = phone_to_country("+82") or "KR"

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
    # redirect URL을 DB의 oauth_states에 저장
    if redirect and _is_safe_redirect(redirect):
        state = auth_url.split("state=")[1].split("&")[0] if "state=" in auth_url else None
        if state:
            supabase = get_supabase()
            try:
                supabase.table("oauth_states").update(
                    {"redirect_url": redirect}
                ).eq("state", state).execute()
            except Exception:
                pass  # redirect 저장 실패는 치명적이지 않음
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
            # 기존 회원 - 로그인: OAuth 토큰 갱신
            supabase.table("oauth_connections").update({
                "access_token_encrypted": token_data["access_token"],
                "refresh_token_encrypted": token_data.get("refresh_token"),
            }).eq("provider", provider).eq("provider_user_id", user_info["id"]).execute()

            member_id = existing_oauth.data[0]["member_id"]
            member = supabase.table("members").select("*").eq("id", member_id).single().execute()

            if member.data:
                access_token = create_access_token({
                    "member_id": str(member.data["id"]),
                    "email": member.data["email"],
                    "member_type": member.data["member_type"],
                })

                redirect_url = state_data.get("redirect_url")
                if redirect_url and not _is_safe_redirect(redirect_url):
                    redirect_url = None
                # redirect_url이 없으면 Referer 또는 기본 data 서비스로
                if not redirect_url:
                    referer = request.headers.get("referer", "")
                    for domain in ["club", "shop", "community", "blog", "analytics"]:
                        if f"{domain}.fencingmind.ai" in referer:
                            redirect_url = f"https://{domain}.fencingmind.ai"
                            break
                response = RedirectResponse(url=redirect_url or "https://data.fencingmind.ai", status_code=303)
                _set_auth_cookies(response, access_token, member.data["email"])
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
                {"value": "general", "label": "일반 회원"},
                {"value": "player", "label": "선수회원"},
                {"value": "player_parent", "label": "선수 부모회원"},
                {"value": "club_coach", "label": "클럽 코치"},
                {"value": "club_director", "label": "클럽 감독/대표"},
                {"value": "school_coach", "label": "학교 코치"},
                {"value": "school_director", "label": "학교 감독"},
            ],
        }
    )


@router.post("/register")
async def register_member(
    request: Request,
    token: str = Form(...),
    full_name: str = Form(...),
    nickname: str = Form(...),
    email: str = Form(...),
    phone: Optional[str] = Form(None),
    phone_country_code: str = Form("+82"),
    birth_date: Optional[str] = Form(None),
    member_type: str = Form(...),
    # 동의 항목 (서버사이드 검증)
    terms_consent: bool = Form(False),
    privacy_consent: bool = Form(False),
    overseas_consent: bool = Form(False),
    optional_privacy_consent: bool = Form(False),
    marketing_consent: bool = Form(False),
    promotional_consent: bool = Form(False),
):
    """회원가입 처리"""
    # 필수 동의 검증
    if not all([terms_consent, privacy_consent, overseas_consent]):
        raise HTTPException(status_code=400, detail="필수 동의 항목을 모두 체크해주세요")

    pending = _oauth_handler.pop_pending_registration(token)
    if not pending:
        raise HTTPException(status_code=400, detail="유효하지 않은 등록 토큰입니다")

    # 닉네임 검증
    if not NICKNAME_PATTERN.match(nickname):
        raise HTTPException(status_code=400, detail="닉네임: 영문, 숫자, 밑줄(_)만 사용 가능 (3~20자)")

    # Fix email "None" from OAuth
    if not email or email.lower() == "none":
        raise HTTPException(status_code=400, detail="이메일을 입력해주세요")

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

    # 닉네임 중복 확인 (대소문자 무시)
    existing_nick = supabase.table("members").select("id").ilike("nickname", nickname).execute()
    if existing_nick.data:
        raise HTTPException(status_code=400, detail="이미 사용 중인 닉네임입니다")

    # Generate email verification token
    verification_token = secrets.token_urlsafe(64)
    settings = get_account_settings()
    expires_at = datetime.utcnow() + timedelta(hours=settings.EMAIL_VERIFICATION_EXPIRE_HOURS)
    now = datetime.utcnow()

    # 선택 개인정보 미동의 시 전화번호/생년월일 무시
    if not optional_privacy_consent:
        phone = None
        birth_date = None

    member_data = {
        "full_name": full_name,
        "nickname": nickname,
        "display_name": mask_korean_name(full_name),
        "email": email,
        "phone": phone if phone else None,
        "phone_country_code": phone_country_code,
        "birth_date": birth_date if birth_date else None,
        "member_type": member_type,
        "marketing_consent": marketing_consent,
        "promotional_consent": promotional_consent,
        "overseas_transfer_consent": True,
        "optional_privacy_consent": optional_privacy_consent,
        "verification_status": "pending",
        "email_verified": False,
        "email_verification_token": verification_token,
        "email_verification_expires_at": expires_at.isoformat(),
        "terms_agreed_at": now.isoformat(),
        "privacy_agreed_at": now.isoformat(),
        "consent_version": "1.0",
    }

    result = supabase.table("members").insert(member_data).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="회원가입 처리 중 오류가 발생했습니다")

    member = result.data[0]

    # consent_logs에 동의 이력 기록
    consent_entries = [
        {"consent_type": "terms_of_service", "agreed": True},
        {"consent_type": "required_privacy", "agreed": True},
        {"consent_type": "overseas_transfer", "agreed": True},
        {"consent_type": "optional_privacy", "agreed": optional_privacy_consent},
        {"consent_type": "marketing", "agreed": marketing_consent},
        {"consent_type": "promotional", "agreed": promotional_consent},
    ]
    for entry in consent_entries:
        try:
            supabase.table("consent_logs").insert({
                "member_id": member["id"],
                "consent_type": entry["consent_type"],
                "agreed": entry["agreed"],
                "consent_version": "1.0",
                "ip_address": str(request.client.host) if request.client else None,
                "user_agent": request.headers.get("user-agent", "")[:500],
            }).execute()
        except Exception as e:
            logger.warning(f"consent_logs 기록 실패: {e}")

    # OAuth 연결 저장
    oauth_data = {
        "member_id": member["id"],
        "provider": pending["provider"],
        "provider_user_id": pending["provider_user_id"],
        "provider_email": pending.get("email"),
        "provider_name": pending.get("name"),
        "is_primary": True,
        "for_promotional": pending.get("promotional", False),
        "access_token_encrypted": pending.get("access_token"),
        "refresh_token_encrypted": pending.get("refresh_token"),
    }

    supabase.table("oauth_connections").insert(oauth_data).execute()

    # 토큰 생성
    access_token = create_access_token({
        "member_id": str(member["id"]),
        "email": member["email"],
        "member_type": member["member_type"],
    })

    # Send verification email
    verify_url = f"https://account.fencingmind.ai/auth/verify-email?token={verification_token}"
    await get_email_service().send_verification_email(
        email, full_name, verification_token, verify_url=verify_url,
    )

    # Redirect to email verification page instead of /account/verification
    response = RedirectResponse(url=f"/auth/verify-email-sent?email={email}", status_code=303)
    _set_auth_cookies(response, access_token, email)

    return response


# =============================================
# 이메일 인증
# =============================================

@router.get("/verify-email-sent", response_class=HTMLResponse)
async def verify_email_sent_page(request: Request, email: str = ""):
    """이메일 인증 안내 페이지"""
    return _templates.TemplateResponse("auth/verify_email_sent.html", {
        "request": request,
        "email": email,
    })


@router.get("/verify-email")
async def verify_email(token: str):
    """이메일 인증 처리"""
    supabase = get_supabase()

    # Find member by verification token
    result = supabase.table("members").select(
        "id, email, full_name, email_verification_expires_at"
    ).eq("email_verification_token", token).execute()

    if not result.data:
        raise HTTPException(status_code=400, detail="유효하지 않은 인증 링크입니다")

    member = result.data[0]

    # Check expiration
    if member.get("email_verification_expires_at"):
        expires_at = datetime.fromisoformat(member["email_verification_expires_at"].replace("Z", "+00:00"))
        if datetime.now(expires_at.tzinfo) > expires_at:
            raise HTTPException(status_code=400, detail="인증 링크가 만료되었습니다. 재발송해주세요.")

    # Mark email as verified
    supabase.table("members").update({
        "email_verified": True,
        "email_verified_at": datetime.utcnow().isoformat(),
        "email_verification_token": None,
        "email_verification_expires_at": None,
    }).eq("id", member["id"]).execute()

    # Send welcome email
    await get_email_service().send_welcome_email(member["email"], member["full_name"])

    # Redirect to data service after email verification
    return RedirectResponse(url="https://data.fencingmind.ai", status_code=303)


@router.post("/resend-verification")
async def resend_verification_email(request: Request):
    """인증 메일 재발송"""
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    if member.get("email_verified"):
        return RedirectResponse(url="/account/verification", status_code=303)

    # Generate new token
    new_token = secrets.token_urlsafe(64)
    settings = get_account_settings()
    expires_at = datetime.utcnow() + timedelta(hours=settings.EMAIL_VERIFICATION_EXPIRE_HOURS)

    supabase = get_supabase()
    supabase.table("members").update({
        "email_verification_token": new_token,
        "email_verification_expires_at": expires_at.isoformat(),
    }).eq("id", member["id"]).execute()

    verify_url = f"https://account.fencingmind.ai/auth/verify-email?token={new_token}"
    await get_email_service().send_verification_email(
        member["email"], member["full_name"], new_token, verify_url=verify_url,
    )

    return RedirectResponse(url=f"/auth/verify-email-sent?email={member['email']}", status_code=303)


# =============================================
# 로그아웃
# =============================================

@router.post("/logout")
async def logout():
    """로그아웃"""
    cookie_domain = os.getenv("COOKIE_DOMAIN", ".fencingmind.ai")
    response = RedirectResponse(url="https://data.fencingmind.ai", status_code=303)
    response.delete_cookie("access_token", domain=cookie_domain, secure=True)
    response.delete_cookie("user_display", domain=cookie_domain, secure=True)
    return response


@router.get("/logout")
async def logout_get():
    """로그아웃 (GET)"""
    cookie_domain = os.getenv("COOKIE_DOMAIN", ".fencingmind.ai")
    response = RedirectResponse(url="https://data.fencingmind.ai", status_code=303)
    response.delete_cookie("access_token", domain=cookie_domain, secure=True)
    response.delete_cookie("user_display", domain=cookie_domain, secure=True)
    return response
