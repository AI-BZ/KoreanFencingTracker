"""
Auth Router - 인증 라우터

JWT/OAuth 핵심 로직은 shared_core에서 import.
이 파일은 라우트 정의 + 템플릿 렌더링 담당.
"""
import os
import json
import secrets
from datetime import datetime, timedelta
from typing import Optional, List
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
from shared_core.email.templates import SERVICE_DESCRIPTIONS
from app.config import get_account_settings
from app.i18n.middleware import create_language_context
from app.verification.claims import calculate_claim_confidence, _link_player_to_member
from app.verification.notification_service import VerificationNotificationService

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
# 공개 검색 API (회원가입 폼에서 인증 없이 사용)
# =============================================

@router.get("/public/player-search")
async def public_player_search(
    name: str,
    birth_year: Optional[int] = None,
    team: Optional[str] = None,
    weapon: Optional[str] = None,
):
    """
    선수 검색 (공개 - 회원가입 폼 용)

    GET /auth/public/player-search?name=홍길동&birth_year=2005
    대회 공개 데이터이므로 인증 불필요.
    """
    if not name or len(name.strip()) < 2:
        raise HTTPException(status_code=400, detail="이름은 2자 이상이어야 합니다")

    supabase = get_supabase()
    query = supabase.table("players").select(
        "id, name, team_name, birth_year, gender, weapon, "
        "competition_count, last_competition_date"
    ).ilike("name", f"%{name.strip()}%")

    if birth_year:
        query = query.eq("birth_year", birth_year)
    if team:
        query = query.ilike("team_name", f"%{team.strip()}%")
    if weapon:
        query = query.eq("weapon", weapon)

    query = query.limit(15)

    try:
        result = query.execute()
    except Exception as e:
        logger.error(f"Public player search error: {e}")
        raise HTTPException(status_code=500, detail="검색 중 오류가 발생했습니다")

    return {"results": result.data or [], "total": len(result.data or [])}


@router.get("/public/child-search")
async def public_child_search(
    name: str,
    birth_year: Optional[int] = None,
    team: Optional[str] = None,
):
    """
    자녀 선수 검색 (공개 - 부모회원 가입 폼 용)

    GET /auth/public/child-search?name=홍길동&birth_year=2012
    """
    if not name or len(name.strip()) < 2:
        raise HTTPException(status_code=400, detail="이름은 2자 이상이어야 합니다")

    supabase = get_supabase()
    query = supabase.table("players").select(
        "id, name, team_name, birth_year, gender, weapon, "
        "competition_count, last_competition_date"
    ).ilike("name", f"%{name.strip()}%")

    if birth_year:
        query = query.eq("birth_year", birth_year)
    if team:
        query = query.ilike("team_name", f"%{team.strip()}%")

    query = query.limit(15)

    try:
        result = query.execute()
    except Exception as e:
        logger.error(f"Public child search error: {e}")
        raise HTTPException(status_code=500, detail="검색 중 오류가 발생했습니다")

    return {"results": result.data or [], "total": len(result.data or [])}


@router.get("/public/org-search")
async def public_org_search(
    name: str,
):
    """
    조직 검색 (공개 - 코치/감독 가입 폼 용)

    GET /auth/public/org-search?name=최병철
    """
    if not name or len(name.strip()) < 2:
        raise HTTPException(status_code=400, detail="조직명은 2자 이상이어야 합니다")

    supabase = get_supabase()
    query = supabase.table("organizations").select(
        "id, name, org_type, region"
    ).ilike("name", f"%{name.strip()}%").limit(15)

    try:
        result = query.execute()
    except Exception as e:
        logger.error(f"Public org search error: {e}")
        raise HTTPException(status_code=500, detail="검색 중 오류가 발생했습니다")

    return {"results": result.data or [], "total": len(result.data or [])}


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
        **create_language_context(request),
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
        i18n_ctx = create_language_context(request)
        error_msg = i18n_ctx.get("i18n", {}).get("auth", {}).get("error", {}).get(
            "default_message", "인증 처리 중 오류가 발생했습니다. 다시 시도해주세요."
        )
        return _templates.TemplateResponse("auth/error.html", {
            "request": request,
            "error_message": error_msg,
            **i18n_ctx,
        }, status_code=500)


# =============================================
# 회원가입
# =============================================

def _get_available_services() -> list[dict]:
    """서비스 목록 조회 (services 테이블 → fallback: SERVICE_DESCRIPTIONS)"""
    try:
        supabase = get_supabase()
        result = supabase.table("services").select(
            "id, name_ko, description, is_active, sort_order"
        ).order("sort_order").execute()
        if result.data:
            return [
                {
                    "service_key": s["id"],
                    "icon": SERVICE_DESCRIPTIONS.get(s["id"], {}).get("icon", ""),
                    "display_name": s.get("name_ko") or s["id"],
                    "description": s.get("description") or "",
                    "is_active": s.get("is_active", False),
                }
                for s in result.data
            ]
    except Exception as e:
        logger.debug(f"services 테이블 조회 실패, fallback 사용: {e}")

    # Fallback: SERVICE_DESCRIPTIONS에서 생성
    return [
        {
            "service_key": key,
            "icon": svc["icon"],
            "display_name": svc["name"],
            "description": ", ".join(svc["features"][:2]),
            "is_active": not svc.get("coming_soon", False),
        }
        for key, svc in SERVICE_DESCRIPTIONS.items()
    ]


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, token: Optional[str] = None):
    """회원가입 페이지"""
    pending = None
    if token:
        pending = _oauth_handler.get_pending_registration(token)
        if not pending:
            raise HTTPException(status_code=400, detail="유효하지 않은 등록 토큰입니다")

    available_services = _get_available_services()
    i18n_ctx = create_language_context(request)
    i18n_data = i18n_ctx.get("i18n", {})
    mt = i18n_data.get("common", {}).get("member_types", {})

    return _templates.TemplateResponse(
        "auth/register.html",
        {
            "request": request,
            "token": token,
            "pending": pending,
            "available_services": available_services,
            "member_types": [
                {"value": "general", "label": mt.get("general", "일반 회원")},
                {"value": "player", "label": mt.get("player", "선수회원")},
                {"value": "player_parent", "label": mt.get("player_parent", "선수 부모회원")},
                {"value": "club_coach", "label": mt.get("club_coach", "클럽 코치")},
                {"value": "club_director", "label": mt.get("club_director", "클럽 감독/대표")},
                {"value": "school_coach", "label": mt.get("school_coach", "학교 코치")},
                {"value": "school_director", "label": mt.get("school_director", "학교 감독")},
            ],
            **i18n_ctx,
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
    interested_services: List[str] = Form([]),
    # 동의 항목 (서버사이드 검증)
    terms_consent: bool = Form(False),
    privacy_consent: bool = Form(False),
    overseas_consent: bool = Form(False),
    optional_privacy_consent: bool = Form(False),
    marketing_consent: bool = Form(False),
    promotional_consent: bool = Form(False),
    # 가입 시 선수/조직 선택 (선택사항 — Claim 자동 생성용)
    # str로 받아서 수동 파싱 (hidden field의 빈 문자열 → None 변환)
    selected_player_id: Optional[str] = Form(None),
    selected_org_id: Optional[str] = Form(None),
    selected_child_player_id: Optional[str] = Form(None),
    selected_child_name: Optional[str] = Form(None),
    selected_child_birth_year: Optional[str] = Form(None),
    selected_child_team: Optional[str] = Form(None),
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

    # Claim 파라미터 파싱 (빈 문자열 → None, 숫자 문자열 → int)
    def _parse_int(v):
        if not v or not str(v).strip():
            return None
        try:
            return int(v)
        except (ValueError, TypeError):
            return None

    parsed_player_id = _parse_int(selected_player_id)
    parsed_org_id = _parse_int(selected_org_id)
    parsed_child_player_id = _parse_int(selected_child_player_id)
    parsed_child_name = selected_child_name.strip() if selected_child_name and selected_child_name.strip() else None
    parsed_child_birth_year = _parse_int(selected_child_birth_year)
    parsed_child_team = selected_child_team.strip() if selected_child_team and selected_child_team.strip() else None

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

    # interested_services 검증: 유효한 서비스 키만 허용
    valid_service_keys = set(SERVICE_DESCRIPTIONS.keys())
    try:
        svc_result = supabase.table("services").select("id").execute()
        if svc_result.data:
            valid_service_keys.update(s["id"] for s in svc_result.data)
    except Exception:
        pass
    interested_services = [s for s in interested_services if s in valid_service_keys]
    # data는 항상 포함
    if "data" not in interested_services:
        interested_services.insert(0, "data")

    member_data = {
        "full_name": full_name,
        "nickname": nickname,
        "display_name": mask_korean_name(full_name),
        "email": email,
        "phone": phone if phone else None,
        "phone_country_code": phone_country_code,
        "birth_date": birth_date if birth_date else None,
        "member_type": member_type,
        "interested_services": json.dumps(interested_services),
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

    # 선택한 서비스별 free tier 구독 생성 (data는 DB trigger가 처리)
    for svc_key in interested_services:
        if svc_key == "data":
            continue  # DB trigger가 자동 생성
        try:
            supabase.table("member_services").insert({
                "member_id": member["id"],
                "service_id": svc_key,
                "tier": "free",
            }).execute()
        except Exception as e:
            logger.debug(f"member_services 생성 실패 ({svc_key}): {e}")

    # =============================================
    # 가입 시 선택한 선수/조직 → 자동 Claim 생성
    # =============================================
    await _create_registration_claims(
        supabase=supabase,
        member=member,
        member_type=member_type,
        selected_player_id=parsed_player_id,
        selected_org_id=parsed_org_id,
        selected_child_player_id=parsed_child_player_id,
        selected_child_name=parsed_child_name,
        selected_child_birth_year=parsed_child_birth_year,
        selected_child_team=parsed_child_team,
    )

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
# 가입 시 자동 Claim 생성 (내부 헬퍼)
# =============================================

async def _create_registration_claims(
    supabase,
    member: dict,
    member_type: str,
    selected_player_id: Optional[int],
    selected_org_id: Optional[int],
    selected_child_player_id: Optional[int],
    selected_child_name: Optional[str],
    selected_child_birth_year: Optional[int],
    selected_child_team: Optional[str],
):
    """
    회원가입 시 선택한 선수/조직 정보로 Claim 자동 생성.
    실패해도 가입은 정상 진행 (나중에 인증 페이지에서 재시도 가능).
    """
    settings = get_account_settings()

    # 1) 선수회원 → player_claims
    if member_type == "player" and selected_player_id:
        try:
            player_result = supabase.table("players").select("*").eq(
                "id", selected_player_id
            ).single().execute()

            if player_result.data:
                player = player_result.data
                confidence = calculate_claim_confidence(member, player)

                auto_approve = confidence >= settings.CLAIM_AUTO_APPROVE_THRESHOLD
                auto_reject = confidence < settings.CLAIM_MANUAL_REVIEW_THRESHOLD
                if auto_approve:
                    status = "approved"
                elif auto_reject:
                    status = "rejected"
                else:
                    status = "pending"

                evidence = {
                    "source": "registration_form",
                    "member_name": member.get("full_name"),
                    "player_name": player.get("name"),
                }

                claim_data = {
                    "member_id": member["id"],
                    "player_id": selected_player_id,
                    "confidence_score": confidence,
                    "evidence": json.dumps(evidence),
                    "status": status,
                }
                if status == "approved":
                    claim_data["reviewed_at"] = datetime.utcnow().isoformat()

                claim_result = supabase.table("player_claims").insert(claim_data).execute()

                if status == "approved" and claim_result.data:
                    await _link_player_to_member(supabase, member["id"], selected_player_id)

                if status == "pending" and claim_result.data:
                    try:
                        notifier = VerificationNotificationService()
                        await notifier.notify_admin_new_request(
                            request_type="player_claim",
                            item_id=claim_result.data[0]["id"],
                            summary=(
                                f"[가입시] {member.get('full_name', '회원')} → "
                                f"선수 #{selected_player_id} ({player.get('name', '')}), "
                                f"매칭: {confidence:.0%}"
                            ),
                            member_name=member.get("full_name"),
                        )
                    except Exception as ne:
                        logger.warning(f"Registration player claim notification failed: {ne}")

                logger.info(
                    f"Registration player claim created: member={member['id']}, "
                    f"player={selected_player_id}, confidence={confidence}, status={status}"
                )
        except Exception as e:
            logger.warning(f"Registration player claim failed (non-fatal): {e}")

    # 2) 부모회원 → parent_claims
    elif member_type == "player_parent" and (selected_child_player_id or selected_child_name):
        try:
            claim_data = {
                "member_id": member["id"],
                "child_name": (selected_child_name or "").strip(),
                "child_birth_year": selected_child_birth_year,
                "child_team_name": selected_child_team,
                "matched_player_id": selected_child_player_id,
                "relationship_type": "parent",
                "status": "pending",
            }

            claim_result = supabase.table("parent_claims").insert(claim_data).execute()

            if claim_result.data:
                try:
                    notifier = VerificationNotificationService()
                    await notifier.notify_admin_new_request(
                        request_type="parent_claim",
                        item_id=claim_result.data[0]["id"],
                        summary=(
                            f"[가입시] {member.get('full_name', '회원')} → "
                            f"자녀: {selected_child_name or '미지정'}"
                        ),
                        member_name=member.get("full_name"),
                    )
                except Exception as ne:
                    logger.warning(f"Registration parent claim notification failed: {ne}")

            logger.info(
                f"Registration parent claim created: member={member['id']}, "
                f"child={selected_child_name}, player_id={selected_child_player_id}"
            )
        except Exception as e:
            logger.warning(f"Registration parent claim failed (non-fatal): {e}")

    # 3) 코치/감독 → organization_claims
    elif member_type in ("club_coach", "club_director", "school_coach", "school_director") and selected_org_id:
        try:
            # claim_type 결정
            if member_type in ("club_director", "school_director"):
                claim_type = "director"
            else:
                claim_type = "head_coach"

            claim_data = {
                "member_id": member["id"],
                "organization_id": selected_org_id,
                "claim_type": claim_type,
                "status": "pending",
            }

            claim_result = supabase.table("organization_claims").insert(claim_data).execute()

            if claim_result.data:
                try:
                    org_result = supabase.table("organizations").select("name").eq(
                        "id", selected_org_id
                    ).single().execute()
                    org_name = org_result.data.get("name", "") if org_result.data else ""

                    notifier = VerificationNotificationService()
                    await notifier.notify_admin_new_request(
                        request_type="org_claim",
                        item_id=claim_result.data[0]["id"],
                        summary=(
                            f"[가입시] {member.get('full_name', '회원')} → "
                            f"조직: {org_name} (#{selected_org_id}), 역할: {claim_type}"
                        ),
                        member_name=member.get("full_name"),
                    )
                except Exception as ne:
                    logger.warning(f"Registration org claim notification failed: {ne}")

            logger.info(
                f"Registration org claim created: member={member['id']}, "
                f"org={selected_org_id}, type={claim_type}"
            )
        except Exception as e:
            logger.warning(f"Registration org claim failed (non-fatal): {e}")


# =============================================
# 이메일 인증
# =============================================

@router.get("/verify-email-sent", response_class=HTMLResponse)
async def verify_email_sent_page(request: Request, email: str = ""):
    """이메일 인증 안내 페이지"""
    return _templates.TemplateResponse("auth/verify_email_sent.html", {
        "request": request,
        "email": email,
        **create_language_context(request),
    })


_NOTIFICATION_ICONS = {
    "data": "\U0001f4ca",      # 📊
    "club": "\U0001f3eb",      # 🏫
    "community": "\U0001f4ac", # 💬
    "shop": "\U0001f6d2",      # 🛒
    "analytics": "\U0001f3af", # 🎯
}


def _send_welcome_notification(supabase, member_id: str, services: list[str]):
    """환영 사이트 알림 생성"""
    svc_names = []
    for svc_key in services:
        svc = SERVICE_DESCRIPTIONS.get(svc_key)
        if svc and not svc.get("coming_soon"):
            icon = _NOTIFICATION_ICONS.get(svc_key, "")
            svc_names.append(f'{icon} {svc["name"]}')

    if svc_names:
        body = f"관심 서비스: {', '.join(svc_names)}\n\n시작하기: https://data.fencingmind.ai"
    else:
        body = "시작하기: https://data.fencingmind.ai"

    try:
        supabase.table("notifications").insert({
            "recipient_id": member_id,
            "title": "FencingMind에 오신 것을 환영합니다!",
            "body": body,
            "notification_type": "welcome",
        }).execute()
    except Exception as e:
        logger.warning(f"환영 알림 생성 실패: {e}")


@router.get("/verify-email")
async def verify_email(token: str):
    """이메일 인증 처리"""
    supabase = get_supabase()

    # Find member by verification token
    result = supabase.table("members").select(
        "id, email, full_name, email_verification_expires_at, interested_services"
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

    # Send personalized welcome email
    interested = member.get("interested_services") or ["data"]
    if isinstance(interested, str):
        try:
            interested = json.loads(interested)
        except (json.JSONDecodeError, TypeError):
            interested = ["data"]
    await get_email_service().send_welcome_email(
        member["email"], member["full_name"], services=interested,
    )

    # Create welcome notification
    _send_welcome_notification(supabase, str(member["id"]), interested)

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
