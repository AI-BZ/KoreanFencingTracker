"""
Auth Router - 인증 라우터

JWT/OAuth 핵심 로직은 shared_core에서 import.
이 파일은 라우트 정의 + 템플릿 렌더링 담당.
"""
import os
import json
import random
import secrets
from datetime import datetime, timedelta, timezone
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
from shared_core.email.service import EmailService
from shared_core.utils.country import phone_to_country
from shared_core.email.templates import SERVICE_DESCRIPTIONS, get_svc_name, get_svc_features
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

# 선수 선택 시퀀스: 무기 / 리그(연령대) 필터
# events.weapon: epee / foil / sabre
WEAPON_VALUES = ("epee", "foil", "sabre")

# events.age_group 값이 불규칙(코드 + 한글 + U표기 혼재)하여 리그 그룹으로 매핑.
# key = 프론트 리그 코드, value = 매칭할 events.age_group 값 집합
LEAGUE_AGE_GROUPS = {
    "elementary": {"E1", "E2", "E3", "초등부", "U9", "U11", "U13"},
    "middle": {"MS", "중등부", "15세이하부", "U15"},
    "high": {"HS", "고등부", "16세이하부", "18세이하부", "U17"},
    "university": {"UNI", "대학", "U20"},
    "senior": {"SR", "일반부", "엘리트부"},
}
# 역매핑: age_group → 리그 코드
_AGE_GROUP_TO_LEAGUE = {
    ag: league for league, groups in LEAGUE_AGE_GROUPS.items() for ag in groups
}


def _is_safe_redirect(url: str) -> bool:
    """오픈 리다이렉트 방지 - 허용된 도메인만 리다이렉트.

    - 내부 상대 경로("/dashboard")는 허용
    - 절대 URL은 hostname이 허용 도메인과 정확히 일치하거나 그 하위 도메인일 때만 허용.
      접미사 우회 차단: "evilfencingmind.ai"는 "fencingmind.ai"로 끝나지만 하위 도메인이
      아니므로 거부.
    - 스킴 상대("//evil.com")·백슬래시 우회("/\\evil.com")는 거부.
    """
    if not url:
        return False
    # 브라우저가 백슬래시를 슬래시로 해석하는 우회를 차단하기 위해 정규화 후 파싱.
    normalized = url.replace("\\", "/")
    parsed = urlparse(normalized)
    if parsed.hostname:
        hostname = parsed.hostname.lower()
        return any(
            hostname == d or hostname.endswith("." + d)
            for d in ALLOWED_REDIRECT_DOMAINS
        )
    # hostname이 없는데 netloc이 있으면 비정상 절대 URL → 거부.
    if parsed.netloc:
        return False
    # 진짜 내부 상대 경로만 허용 ("/..."). "javascript:", "dashboard" 등은 거부.
    return normalized.startswith("/")


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


def _annotate_and_filter_by_weapon_league(
    candidates: list,
    weapon: Optional[str] = None,
    league: Optional[str] = None,
) -> list:
    """
    선수 후보 목록에 무기/리그 정보를 붙이고(무기·리그 selector 표시용),
    weapon/league 필터가 주어지면 매칭되는 선수만 남긴다.

    무기/리그는 players 테이블이 아니라 rankings→events 조인에서 유도.
    후보(cand_ids ≤ 검색 limit)에 한정해 조회하므로 부하가 제한적이다.
    """
    if not candidates:
        return candidates

    cand_ids = [c["id"] for c in candidates if c.get("id") is not None]
    if not cand_ids:
        return candidates

    supabase = get_supabase()

    # 후보 선수들의 rankings → event_id 수집
    try:
        rk = supabase.table("rankings").select(
            "player_id, event_id"
        ).in_("player_id", cand_ids).execute()
        ranking_rows = rk.data or []
    except Exception as e:
        logger.warning(f"weapon/league 필터: rankings 조회 실패 → 필터 생략: {e}")
        return candidates

    event_ids = list({r["event_id"] for r in ranking_rows if r.get("event_id")})
    event_meta = {}
    if event_ids:
        try:
            ev = supabase.table("events").select(
                "id, weapon, age_group"
            ).in_("id", event_ids).execute()
            for e in (ev.data or []):
                event_meta[e["id"]] = (e.get("weapon"), e.get("age_group"))
        except Exception as e:
            logger.warning(f"weapon/league 필터: events 조회 실패 → 필터 생략: {e}")
            return candidates

    # player_id → {weapons}, {leagues}
    player_weapons: dict = {}
    player_leagues: dict = {}
    for r in ranking_rows:
        pid = r.get("player_id")
        meta = event_meta.get(r.get("event_id"))
        if not pid or not meta:
            continue
        w, ag = meta
        if w:
            player_weapons.setdefault(pid, set()).add(w)
        league_code = _AGE_GROUP_TO_LEAGUE.get(ag)
        if league_code:
            player_leagues.setdefault(pid, set()).add(league_code)

    filtered = []
    for c in candidates:
        pid = c.get("id")
        weapons = player_weapons.get(pid, set())
        leagues = player_leagues.get(pid, set())

        if weapon and weapon not in weapons:
            continue
        if league and league not in leagues:
            continue

        c["weapons"] = sorted(weapons)
        c["leagues"] = sorted(leagues)
        filtered.append(c)

    return filtered


# =============================================
# 공개 검색 API (회원가입 폼에서 인증 없이 사용)
# =============================================

@router.get("/public/player-search")
async def public_player_search(
    name: str,
    birth_year: Optional[int] = None,
    team: Optional[str] = None,
    weapon: Optional[str] = None,
    league: Optional[str] = None,
):
    """
    선수 검색 (공개 - 회원가입 폼 용)

    GET /auth/public/player-search?name=홍길동&weapon=foil&league=middle
    대회 공개 데이터이므로 인증 불필요.
    weapon: epee/foil/sabre, league: elementary/middle/high/university/senior
    """
    if not name or len(name.strip()) < 2:
        raise HTTPException(status_code=400, detail="이름은 2자 이상이어야 합니다")

    weapon = weapon if weapon in WEAPON_VALUES else None
    league = league if league in LEAGUE_AGE_GROUPS else None

    supabase = get_supabase()
    query = supabase.table("players").select(
        "id, player_name, team_name, birth_year"
    ).ilike("player_name", f"%{name.strip()}%")

    if birth_year:
        query = query.eq("birth_year", birth_year)
    if team:
        query = query.ilike("team_name", f"%{team.strip()}%")

    # 무기/리그 필터 시 후보 폭을 넓게 잡고 조인 필터로 좁힌다
    query = query.limit(60 if (weapon or league) else 15)

    try:
        result = query.execute()
    except Exception as e:
        logger.error(f"Public player search error: {e}")
        raise HTTPException(status_code=500, detail="검색 중 오류가 발생했습니다")

    results = _annotate_and_filter_by_weapon_league(
        result.data or [], weapon=weapon, league=league
    )[:15]

    return {"results": results, "total": len(results)}


@router.get("/public/child-search")
async def public_child_search(
    name: str,
    birth_year: Optional[int] = None,
    team: Optional[str] = None,
    weapon: Optional[str] = None,
    league: Optional[str] = None,
):
    """
    자녀 선수 검색 (공개 - 부모회원 가입 폼 용)

    GET /auth/public/child-search?name=홍길동&weapon=foil&league=elementary
    """
    if not name or len(name.strip()) < 2:
        raise HTTPException(status_code=400, detail="이름은 2자 이상이어야 합니다")

    weapon = weapon if weapon in WEAPON_VALUES else None
    league = league if league in LEAGUE_AGE_GROUPS else None

    supabase = get_supabase()
    query = supabase.table("players").select(
        "id, player_name, team_name, birth_year"
    ).ilike("player_name", f"%{name.strip()}%")

    if birth_year:
        query = query.eq("birth_year", birth_year)
    if team:
        query = query.ilike("team_name", f"%{team.strip()}%")

    query = query.limit(60 if (weapon or league) else 15)

    try:
        result = query.execute()
    except Exception as e:
        logger.error(f"Public child search error: {e}")
        raise HTTPException(status_code=500, detail="검색 중 오류가 발생했습니다")

    results = _annotate_and_filter_by_weapon_league(
        result.data or [], weapon=weapon, league=league
    )[:15]

    return {"results": results, "total": len(results)}


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
        "id, name, org_type, province, city"
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
# 이메일 인증코드 로그인
# =============================================

@router.post("/email/send-code")
async def send_email_code(request: Request, email: str = Form(...)):
    """이메일 인증코드 발송"""
    email = email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="유효한 이메일을 입력해주세요")

    settings = get_account_settings()
    code = str(random.randint(100000, 999999))
    registration_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.EMAIL_CODE_EXPIRE_MINUTES)

    supabase = get_supabase()

    # 기존 이메일 pending 삭제 (중복 방지)
    try:
        supabase.table("pending_registrations").delete().eq(
            "provider", "email"
        ).eq("provider_email", email).execute()
    except Exception:
        pass

    row = {
        "token": registration_token,
        "provider": "email",
        "provider_user_id": email,
        "provider_email": email,
        "provider_name": None,
        "access_token": None,
        "refresh_token": None,
        "promotional": False,
        "verification_code": code,
        "code_attempts": 0,
        "expires_at": expires_at.isoformat(),
    }
    try:
        supabase.table("pending_registrations").insert(row).execute()
    except Exception as e:
        logger.error(f"Email code pending insert failed: {e}")
        raise HTTPException(status_code=500, detail="인증코드 생성 중 오류가 발생했습니다")

    lang = getattr(request.state, "lang", "ko")
    await get_email_service().send_verification_code_email(email, "", code, lang=lang)

    return {"success": True, "token": registration_token}


@router.post("/email/verify-code")
async def verify_email_code(token: str = Form(...), code: str = Form(...)):
    """이메일 인증코드 검증"""
    supabase = get_supabase()
    settings = get_account_settings()

    result = supabase.table("pending_registrations").select("*").eq(
        "token", token
    ).execute()

    if not result.data:
        raise HTTPException(status_code=400, detail="유효하지 않은 토큰입니다")

    pending = result.data[0]

    # 만료 확인
    expires_at = datetime.fromisoformat(pending["expires_at"].replace("Z", "+00:00"))
    if datetime.now(timezone.utc) > expires_at:
        raise HTTPException(status_code=400, detail="인증코드가 만료되었습니다. 다시 발송해주세요.")

    # 시도 횟수 확인
    if (pending.get("code_attempts") or 0) >= settings.EMAIL_CODE_MAX_ATTEMPTS:
        raise HTTPException(status_code=400, detail="인증 시도 횟수를 초과했습니다. 코드를 재발송해주세요.")

    # 코드 확인
    if pending.get("verification_code") != code.strip():
        # 시도 횟수 증가
        supabase.table("pending_registrations").update({
            "code_attempts": (pending.get("code_attempts") or 0) + 1,
        }).eq("token", token).execute()
        raise HTTPException(status_code=400, detail="인증코드가 일치하지 않습니다")

    email = pending["provider_email"]

    # 기존 회원 확인 (이메일로 members 또는 oauth_connections 검색)
    existing_member = supabase.table("members").select(
        "id, email, member_type, full_name"
    ).eq("email", email).execute()

    if existing_member.data:
        # 기존 회원 → JWT 발급 + 로그인
        member = existing_member.data[0]
        access_token = create_access_token({
            "member_id": str(member["id"]),
            "email": member["email"],
            "member_type": member["member_type"],
        })
        # pending 삭제
        supabase.table("pending_registrations").delete().eq("token", token).execute()
        return {
            "verified": True,
            "is_new": False,
            "access_token": access_token,
            "email": email,
        }

    # 신규 → 회원가입 진행
    return {"verified": True, "is_new": True, "token": token}


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
    """로그인 페이지 표시 (서비스 소개 + 인증 선택)"""
    available_services = _get_available_services()
    return _templates.TemplateResponse("auth/login.html", {
        "request": request,
        "redirect_url": redirect or "",
        "available_services": available_services,
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
async def oauth_callback(
    provider: str,
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
):
    """OAuth 콜백 처리 (OAuthHandler 사용)"""
    # OAuth 에러 또는 사용자 취소 처리
    if error or not code or not state:
        logger.warning(f"OAuth 콜백 에러/취소: provider={provider}, error={error}, desc={error_description}")
        return RedirectResponse(url="/auth/login", status_code=303)

    try:
        state_data = _oauth_handler.validate_state(state, provider)
    except HTTPException:
        logger.warning(f"OAuth state 검증 실패: provider={provider}, state 만료 또는 재사용")
        return RedirectResponse(url="/auth/login", status_code=303)

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
            "display_name": get_svc_name(svc, "ko"),
            "description": ", ".join(get_svc_features(svc, "ko")[:2]),
            "is_active": not svc.get("coming_soon", False),
        }
        for key, svc in SERVICE_DESCRIPTIONS.items()
    ]


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, token: Optional[str] = None):
    """회원가입 페이지 (멀티스텝 위자드)"""
    pending = None
    if token:
        # OAuth 또는 이메일 인증코드 모두 pending_registrations에 저장됨
        pending = _oauth_handler.get_pending_registration(token)
        if not pending:
            raise HTTPException(status_code=400, detail="유효하지 않은 등록 토큰입니다")

    i18n_ctx = create_language_context(request)

    return _templates.TemplateResponse(
        "auth/register.html",
        {
            "request": request,
            "token": token,
            "pending": pending,
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
    member_type: str = Form(...),
    # 프로필 (선택)
    phone: Optional[str] = Form(None),
    phone_country_code: Optional[str] = Form(None),
    birth_date: Optional[str] = Form(None),
    # 동의 항목 (서버사이드 검증)
    terms_consent: bool = Form(False),
    privacy_consent: bool = Form(False),
    overseas_consent: bool = Form(False),  # 하위 호환 - 더 이상 필수 아님
    marketing_consent: bool = Form(False),
    # 가입 시 선수/조직 선택 (선택사항 — Claim 자동 생성용)
    selected_player_id: Optional[str] = Form(None),
    selected_org_id: Optional[str] = Form(None),
    selected_child_player_id: Optional[str] = Form(None),
    selected_child_name: Optional[str] = Form(None),
    selected_child_birth_year: Optional[str] = Form(None),
    selected_child_team: Optional[str] = Form(None),
):
    """회원가입 처리 (위자드 폼)"""
    # 필수 동의 검증 (overseas_consent 제거 — 2023 PIPA 개정)
    if not all([terms_consent, privacy_consent]):
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

    # 회원 유형 검증 (migration 008 CHECK 제약과 동일)
    ALLOWED_MEMBER_TYPES = {
        "general", "player", "player_parent",
        "club_coach", "club_director", "school_coach", "school_director",
    }
    if member_type not in ALLOWED_MEMBER_TYPES:
        raise HTTPException(status_code=400, detail="유효하지 않은 회원 유형입니다")

    # 프로필 선택 필드 정리
    phone_clean = "".join(ch for ch in (phone or "") if ch.isdigit()) or None
    phone_cc = (phone_country_code or "+82").strip() if phone_clean else None
    birth_date_clean = None
    if birth_date and birth_date.strip():
        try:
            birth_date_clean = datetime.strptime(birth_date.strip(), "%Y-%m-%d").date().isoformat()
        except ValueError:
            birth_date_clean = None

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

    now = datetime.utcnow()
    is_email_provider = pending["provider"] == "email"

    # 이메일 가입: 이미 인증코드로 검증 완료 → email_verified = True
    # OAuth 가입: 이메일 인증 필요 → email_verified = False
    if is_email_provider:
        email_verified = True
        verification_token = None
        verification_expires = None
    else:
        email_verified = False
        verification_token = secrets.token_urlsafe(64)
        settings = get_account_settings()
        verification_expires = (now + timedelta(hours=settings.EMAIL_VERIFICATION_EXPIRE_HOURS)).isoformat()

    # data 서비스는 항상 기본 구독
    interested_services = ["data"]

    member_data = {
        "full_name": full_name,
        "nickname": nickname,
        "display_name": mask_korean_name(full_name),
        "email": email,
        "member_type": member_type,
        "phone": phone_clean,
        "phone_country_code": phone_cc,
        "birth_date": birth_date_clean,
        "interested_services": json.dumps(interested_services),
        "marketing_consent": marketing_consent,
        "overseas_transfer_consent": True,  # 개인정보처리방침 동의로 갈음
        "verification_status": "pending",
        "email_verified": email_verified,
        "email_verification_token": verification_token,
        "email_verification_expires_at": verification_expires,
        "terms_agreed_at": now.isoformat(),
        "privacy_agreed_at": now.isoformat(),
        "consent_version": "2.0",
    }

    result = supabase.table("members").insert(member_data).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="회원가입 처리 중 오류가 발생했습니다")

    member = result.data[0]

    # consent_logs에 동의 이력 기록
    consent_entries = [
        {"consent_type": "terms_of_service", "agreed": True},
        {"consent_type": "required_privacy", "agreed": True},
        {"consent_type": "overseas_transfer", "agreed": True},  # 개인정보처리방침에 포함
        {"consent_type": "marketing", "agreed": marketing_consent},
    ]
    for entry in consent_entries:
        try:
            supabase.table("consent_logs").insert({
                "member_id": member["id"],
                "consent_type": entry["consent_type"],
                "agreed": entry["agreed"],
                "consent_version": "2.0",
                "ip_address": str(request.client.host) if request.client else None,
                "user_agent": request.headers.get("user-agent", "")[:500],
            }).execute()
        except Exception as e:
            logger.warning(f"consent_logs 기록 실패: {e}")

    # OAuth 연결 저장 (이메일 가입 시에는 건너뜀)
    if not is_email_provider:
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

    # OAuth 가입 → 이메일 인증 메일 발송
    if not is_email_provider and verification_token:
        lang = getattr(request.state, "lang", "ko")
        verify_url = f"https://account.fencingmind.ai/auth/verify-email?token={verification_token}"
        await get_email_service().send_verification_email(
            email, full_name, verification_token, verify_url=verify_url, lang=lang,
        )

    # Welcome 페이지로 리다이렉트
    response = RedirectResponse(url="/auth/welcome", status_code=303)
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

                p_name = player.get("player_name") or player.get("name") or ""
                evidence = {
                    "source": "registration_form",
                    "member_name": member.get("full_name"),
                    "player_name": p_name,
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
                                f"선수 #{selected_player_id} ({p_name}), "
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
# 환영 페이지
# =============================================

@router.get("/welcome", response_class=HTMLResponse)
async def welcome_page(request: Request):
    """가입 완료 환영 페이지"""
    member = await get_current_member(request)
    if not member:
        return RedirectResponse(url="/auth/login", status_code=303)

    return _templates.TemplateResponse("auth/welcome.html", {
        "request": request,
        "member": member,
        **create_language_context(request),
    })


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
            svc_names.append(f'{icon} {get_svc_name(svc, "ko")}')

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
async def verify_email(request: Request, token: str):
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
    lang = getattr(request.state, "lang", "ko")
    await get_email_service().send_welcome_email(
        member["email"], member["full_name"], services=interested, lang=lang,
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

    lang = getattr(request.state, "lang", "ko")
    verify_url = f"https://account.fencingmind.ai/auth/verify-email?token={new_token}"
    await get_email_service().send_verification_email(
        member["email"], member["full_name"], new_token, verify_url=verify_url, lang=lang,
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
