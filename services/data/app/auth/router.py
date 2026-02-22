"""
Auth Router - FastAPI 인증 라우터

JWT/OAuth 핵심 로직은 shared_core에서 import.
이 파일은 라우트 정의 + 템플릿 렌더링 담당.
"""
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID
import httpx

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from loguru import logger

# === shared_core에서 import ===
from shared_core.auth.jwt import (
    create_access_token,
    get_current_member,
    require_auth,
)
from shared_core.auth.oauth.providers import (
    OAUTH_PROVIDERS,
    get_available_providers,
    get_promotional_providers,
)
from shared_core.auth.oauth.handler import OAuthHandler
from shared_core.auth.oauth.user_info import get_oauth_user_info
from shared_core.db.client import get_supabase_client
from shared_core.privacy.masking import mask_korean_name
from shared_core.privacy.anonymize import is_minor

# === data 서비스 전용 import ===
from .config import get_auth_settings
from .models import (
    MemberType,
    VerificationType,
    VerificationStatus,
    MemberVerificationStatus,
    MemberCreate,
    MemberResponse,
    MemberPublicResponse,
    VerificationResponse,
    PrivacySettings,
    GuardianLink,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# OAuth 핸들러 인스턴스 (shared_core)
_oauth_handler = OAuthHandler()


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
    # 클라이언트 IP에서 국가 추측 (간단한 방식)
    # 실제로는 IP Geolocation API 사용 권장
    client_ip = request.client.host if request.client else None

    # 개발 환경이거나 한국 IP 대역이면 KR로 간주
    country_code = "KR"  # 기본값

    providers = get_available_providers(country_code)
    promotional = get_promotional_providers()

    return {
        "providers": providers,
        "promotional_providers": promotional,
        "country_code": country_code,
    }


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """
    로그인 페이지 표시
    """
    from fastapi.templating import Jinja2Templates
    templates = Jinja2Templates(directory="templates")
    return templates.TemplateResponse("auth/login.html", {"request": request})


@router.get("/login/{provider}")
async def oauth_login(provider: str, request: Request, promotional: bool = False):
    """
    OAuth 로그인 시작 (OAuthHandler 사용)
    """
    auth_url = _oauth_handler.build_auth_url(provider, promotional)
    return RedirectResponse(url=auth_url)


@router.get("/callback/{provider}")
async def oauth_callback(provider: str, code: str, state: str, request: Request):
    """
    OAuth 콜백 처리 (OAuthHandler 사용)
    """
    # 상태 검증
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
                # 토큰 생성
                access_token = create_access_token({
                    "member_id": str(member.data["id"]),
                    "email": member.data["email"],
                    "member_type": member.data["member_type"],
                })

                # 쿠키에 토큰 저장하고 메인 페이지로 리다이렉트
                response = RedirectResponse(url="/", status_code=303)
                response.set_cookie(
                    key="access_token",
                    value=access_token,
                    httponly=True,
                    max_age=60 * 60 * 24,  # 24시간
                    samesite="lax",
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
        raise HTTPException(status_code=500, detail=f"인증 처리 중 오류 발생: {str(e)}")


# =============================================
# 회원가입
# =============================================

@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, token: Optional[str] = None):
    """회원가입 페이지"""
    from fastapi.templating import Jinja2Templates
    templates = Jinja2Templates(directory="templates")

    pending = None
    if token:
        pending = _oauth_handler.get_pending_registration(token)
        if not pending:
            raise HTTPException(status_code=400, detail="유효하지 않은 등록 토큰입니다")

    return templates.TemplateResponse(
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
    # 등록 토큰 확인
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
    response = RedirectResponse(url="/auth/verification", status_code=303)
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=60 * 60 * 24,
        samesite="lax",
    )

    return response


# =============================================
# 인증 (Verification)
# =============================================

@router.get("/verification", response_class=HTMLResponse)
async def verification_page(request: Request):
    """인증 페이지"""
    from fastapi.templating import Jinja2Templates
    templates = Jinja2Templates(directory="templates")

    member = await get_current_member(request)
    if not member:
        return RedirectResponse(url="/auth/login/google", status_code=303)

    # 기존 인증 내역 조회
    supabase = get_supabase()
    verifications = supabase.table("verifications").select("*").eq(
        "member_id", member["id"]
    ).order("created_at", desc=True).execute()

    return templates.TemplateResponse(
        "auth/verification.html",
        {
            "request": request,
            "member": member,
            "verifications": verifications.data or [],
            "verification_types": [
                {"value": "association_card", "label": "협회 등록증", "icon": "card"},
                {"value": "mask_photo", "label": "마스크 + 이름/날짜 종이", "icon": "mask"},
                {"value": "uniform_photo", "label": "도복 + 이름/날짜 종이", "icon": "uniform"},
            ],
        }
    )


@router.post("/verification/upload")
async def upload_verification(
    request: Request,
    file: UploadFile = File(...),
    verification_type: str = Form(...),
):
    """인증 이미지 업로드 및 Gemini 자동 처리"""
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    # 파일 검증
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="이미지 파일만 업로드 가능합니다")

    # 파일 크기 제한 (10MB)
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="파일 크기는 10MB 이하여야 합니다")

    supabase = get_supabase()

    # Supabase Storage에 업로드
    import uuid
    file_ext = file.filename.split(".")[-1] if file.filename else "jpg"
    storage_path = f"verifications/{member['id']}/{uuid.uuid4()}.{file_ext}"

    try:
        # Storage 업로드
        supabase.storage.from_("verification-images").upload(
            storage_path,
            content,
            {"content-type": file.content_type}
        )

        # 공개 URL 가져오기
        public_url = supabase.storage.from_("verification-images").get_public_url(storage_path)

    except Exception as e:
        logger.error(f"Storage 업로드 오류: {e}")
        # Storage 실패 시 직접 URL 생성 (개발 환경)
        public_url = f"/static/uploads/{storage_path}"
        storage_path = storage_path

    # 인증 레코드 생성
    verification_data = {
        "member_id": member["id"],
        "verification_type": verification_type,
        "image_url": public_url,
        "image_storage_path": storage_path,
        "status": "pending",
    }

    result = supabase.table("verifications").insert(verification_data).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="인증 등록 중 오류가 발생했습니다")

    verification = result.data[0]

    # Gemini API로 자동 처리
    from .verification import VerificationProcessor
    processor = VerificationProcessor(supabase)

    try:
        process_result = await processor.process_verification(
            UUID(verification["id"]),
            UUID(member["id"]),
        )

        return {
            "success": True,
            "verification_id": verification["id"],
            "status": process_result.get("status", "pending"),
            "confidence": process_result.get("confidence"),
            "extracted_name": process_result.get("extracted_name"),
            "message": _get_status_message(process_result.get("status")),
        }

    except Exception as e:
        logger.exception(f"인증 처리 오류: {e}")
        return {
            "success": True,  # 업로드는 성공
            "verification_id": verification["id"],
            "status": "pending",
            "message": "인증 처리 중입니다. 잠시 후 결과를 확인해주세요.",
        }


def _get_status_message(status: str) -> str:
    """상태별 메시지"""
    messages = {
        "approved": "인증이 완료되었습니다!",
        "rejected": "인증이 거부되었습니다. 다시 시도해주세요.",
        "pending": "인증 검토 중입니다.",
        "processing": "인증 처리 중입니다.",
    }
    return messages.get(status, "처리 중입니다.")


@router.get("/verification/status")
async def get_verification_status(request: Request):
    """인증 상태 확인"""
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    supabase = get_supabase()
    verifications = supabase.table("verifications").select("*").eq(
        "member_id", member["id"]
    ).order("created_at", desc=True).execute()

    return {
        "member_verification_status": member.get("verification_status", "pending"),
        "verifications": verifications.data or [],
    }


# =============================================
# 프로필
# =============================================

@router.get("/me")
async def get_my_profile(request: Request):
    """내 정보 조회"""
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    return MemberResponse(**member)


@router.patch("/me/privacy")
async def update_privacy_settings(
    request: Request,
    settings: PrivacySettings,
):
    """개인정보 설정 변경"""
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    supabase = get_supabase()

    update_data = {"privacy_public": settings.privacy_public}
    if settings.marketing_consent is not None:
        update_data["marketing_consent"] = settings.marketing_consent
    if settings.promotional_consent is not None:
        update_data["promotional_consent"] = settings.promotional_consent

    result = supabase.table("members").update(update_data).eq(
        "id", member["id"]
    ).execute()

    return {"success": True, "message": "설정이 저장되었습니다"}


# =============================================
# 보호자 연결
# =============================================

@router.post("/guardian/link")
async def link_guardian(
    request: Request,
    data: GuardianLink,
):
    """보호자-미성년자 연결"""
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    # 보호자는 player_parent여야 함
    if member["member_type"] != "player_parent":
        raise HTTPException(status_code=400, detail="보호자 회원만 미성년자를 연결할 수 있습니다")

    supabase = get_supabase()

    # 미성년자 확인
    minor = supabase.table("members").select("*").eq(
        "id", str(data.minor_member_id)
    ).single().execute()

    if not minor.data:
        raise HTTPException(status_code=404, detail="회원을 찾을 수 없습니다")

    # 이미 보호자가 있는지 확인
    if minor.data.get("guardian_member_id"):
        raise HTTPException(status_code=400, detail="이미 보호자가 등록되어 있습니다")

    # 연결
    supabase.table("members").update({
        "guardian_member_id": member["id"]
    }).eq("id", str(data.minor_member_id)).execute()

    return {"success": True, "message": "보호자 연결이 완료되었습니다"}


# =============================================
# 로그아웃
# =============================================

@router.post("/logout")
async def logout():
    """로그아웃"""
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("access_token")
    return response


@router.get("/logout")
async def logout_get():
    """로그아웃 (GET)"""
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("access_token")
    return response
