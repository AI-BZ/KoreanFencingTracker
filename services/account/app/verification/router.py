"""
Verification Router - 인증(본인확인) 엔드포인트

/account 접두사는 server.py에서 추가됨.
최종 경로: /account/verification, /account/verification/upload, /account/verification/status
이메일 인증: /account/verification/email/send, /account/verification/email/verify
BRN 인증: /account/verification/brn/verify
"""
from datetime import datetime, timedelta
from uuid import UUID
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request, UploadFile, File, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from loguru import logger
from pydantic import BaseModel, EmailStr

from shared_core.auth.jwt import create_access_token, decode_token, get_current_member
from shared_core.db.client import get_supabase_client
from shared_core.email import EmailService

from ..config import get_account_settings
from .processor import VerificationProcessor
from .brn import validate_brn_checkdigit
from .claims import router as claims_router
from .notification_service import VerificationNotificationService
from app.i18n.middleware import create_language_context

router = APIRouter(prefix="/verification", tags=["verification"])

# Include claims sub-routes (player-search, player-claim, org-claim)
router.include_router(claims_router)

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))


def get_supabase():
    return get_supabase_client()


# =============================================
# Request Models
# =============================================

class EmailSendRequest(BaseModel):
    """이메일 인증 발송 요청"""
    email: EmailStr


class BRNVerifyRequest(BaseModel):
    """사업자등록번호 검증 요청"""
    brn: str  # "XXX-XX-XXXXX" or "XXXXXXXXXX"


# =============================================
# Verification Page & Image Upload (기존)
# =============================================

@router.get("", response_class=HTMLResponse)
async def verification_page(request: Request):
    """인증 페이지 - member_type에 따라 적절한 인증 플로우 표시"""
    member = await get_current_member(request)
    if not member:
        return RedirectResponse(url="/auth/login", status_code=303)

    supabase = get_supabase()

    i18n_ctx = create_language_context(request)
    i18n_data = i18n_ctx.get("i18n", {})
    acct = i18n_data.get("account", {}).get("verification", {}) if isinstance(i18n_data, dict) else {}

    member_type = member.get("member_type", "general")

    # Determine verification flow based on member_type
    flow_map = {
        "player": "player",
        "player_parent": "parent",
        "club_coach": "coach",
        "school_coach": "coach",
        "club_director": "director",
        "school_director": "director",
        "general": "general",
    }
    verification_flow = flow_map.get(member_type, "general")

    # Base context
    context = {
        "request": request,
        "member": member,
        "verification_flow": verification_flow,
        **i18n_ctx,
    }

    # Flow-specific data
    if verification_flow == "player":
        verifications = supabase.table("verifications").select("*").eq(
            "member_id", member["id"]
        ).order("created_at", desc=True).execute()
        context["verifications"] = verifications.data or []
        context["verification_types"] = [
            {"value": "association_card", "label": acct.get("type_association_card", "협회 등록증"), "icon": "card"},
            {"value": "mask_photo", "label": acct.get("type_mask_photo", "마스크 + 이름/날짜 종이"), "icon": "mask"},
            {"value": "uniform_photo", "label": acct.get("type_uniform_photo", "도복 + 이름/날짜 종이"), "icon": "uniform"},
        ]

    elif verification_flow == "parent":
        # Fetch existing parent claims
        parent_claims = supabase.table("parent_claims").select("*").eq(
            "member_id", member["id"]
        ).order("created_at", desc=True).execute()
        context["parent_claims"] = parent_claims.data or []

        # Parse ai_report if string
        for pc in context["parent_claims"]:
            if isinstance(pc.get("ai_report"), str):
                try:
                    import json
                    pc["ai_report"] = json.loads(pc["ai_report"])
                except Exception:
                    pc["ai_report"] = {}

    elif verification_flow == "coach":
        # Fetch existing player claims
        player_claims = supabase.table("player_claims").select("*").eq(
            "member_id", member["id"]
        ).order("created_at", desc=True).execute()
        context["player_claims"] = player_claims.data or []

    elif verification_flow == "director":
        # Fetch existing org claims
        org_claims = supabase.table("organization_claims").select("*").eq(
            "member_id", member["id"]
        ).order("created_at", desc=True).execute()
        context["org_claims"] = org_claims.data or []

    return _templates.TemplateResponse("auth/verification.html", context)


@router.post("/upload")
async def upload_verification(
    request: Request,
    file: UploadFile = File(...),
    verification_type: str = Form(...),
):
    """인증 이미지 업로드 및 Gemini 자동 처리"""
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="이미지 파일만 업로드 가능합니다")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="파일 크기는 10MB 이하여야 합니다")

    supabase = get_supabase()

    # Supabase Storage에 업로드
    import uuid
    file_ext = file.filename.split(".")[-1] if file.filename else "jpg"
    storage_path = f"verifications/{member['id']}/{uuid.uuid4()}.{file_ext}"

    try:
        supabase.storage.from_("verification-images").upload(
            storage_path,
            content,
            {"content-type": file.content_type}
        )
        public_url = supabase.storage.from_("verification-images").get_public_url(storage_path)
    except Exception as e:
        logger.error(f"Storage 업로드 오류: {e}")
        public_url = f"/static/uploads/{storage_path}"

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
    processor = VerificationProcessor(supabase)

    try:
        process_result = await processor.process_verification(
            UUID(verification["id"]),
            UUID(member["id"]),
        )

        # Notify admins if status requires review
        status = process_result.get("status", "pending")
        if status in ("pending", "submitted"):
            try:
                notifier = VerificationNotificationService()
                await notifier.notify_admin_new_request(
                    request_type="verification",
                    item_id=verification["id"],
                    summary=f"{member.get('full_name', '회원')} - {verification_type}, AI 신뢰도: {process_result.get('confidence', 0):.0%}",
                    member_name=member.get("full_name"),
                )
            except Exception as ne:
                logger.warning(f"Admin notification failed: {ne}")

        return {
            "success": True,
            "verification_id": verification["id"],
            "status": status,
            "confidence": process_result.get("confidence"),
            "extracted_name": process_result.get("extracted_name"),
            "message": _get_status_message(status),
        }

    except Exception as e:
        logger.exception(f"인증 처리 오류: {e}")

        # Still notify admin even on processing error
        try:
            notifier = VerificationNotificationService()
            await notifier.notify_admin_new_request(
                request_type="verification",
                item_id=verification["id"],
                summary=f"{member.get('full_name', '회원')} - {verification_type} (처리 오류, 수동 검토 필요)",
                member_name=member.get("full_name"),
            )
        except Exception:
            pass

        return {
            "success": True,
            "verification_id": verification["id"],
            "status": "pending",
            "message": "인증 처리 중입니다. 잠시 후 결과를 확인해주세요.",
        }


# =============================================
# Email Verification
# =============================================

@router.post("/email/send")
async def send_verification_email(request: Request, body: EmailSendRequest):
    """
    이메일 인증 메일 발송

    POST /account/verification/email/send
    Body: { "email": "user@example.com" }

    JWT 토큰(purpose=email_verify)을 생성하여 인증 메일 발송.
    토큰 유효기간: EMAIL_VERIFICATION_EXPIRE_HOURS (기본 24시간)
    """
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    # 이미 인증된 이메일인지 확인
    if member.get("email_verified"):
        return {"success": True, "message": "이미 이메일 인증이 완료되었습니다."}

    settings = get_account_settings()

    # 인증 토큰 생성 (JWT with purpose)
    token = create_access_token(
        data={
            "member_id": member["id"],
            "email": body.email,
            "purpose": "email_verify",
        },
        expires_delta=timedelta(hours=settings.EMAIL_VERIFICATION_EXPIRE_HOURS),
    )

    # 이메일 발송
    email_service = EmailService(api_key=settings.RESEND_API_KEY)
    name = member.get("full_name", "회원")

    sent = await email_service.send_verification_email(
        to=body.email,
        name=name,
        token=token,
    )

    if not sent:
        logger.warning(f"Email verification send failed for member {member['id']}")
        return {
            "success": False,
            "message": "이메일 발송에 실패했습니다. 잠시 후 다시 시도해주세요.",
        }

    # members 테이블에 pending 이메일 기록 (아직 미인증)
    supabase = get_supabase()
    try:
        supabase.table("members").update({
            "email": body.email,
        }).eq("id", member["id"]).execute()
    except Exception as e:
        logger.error(f"Member email update error: {e}")

    return {
        "success": True,
        "message": "인증 메일이 발송되었습니다. 이메일을 확인해주세요.",
    }


@router.get("/email/verify")
async def verify_email_token(
    token: str = Query(..., description="이메일 인증 토큰"),
):
    """
    이메일 인증 토큰 검증

    GET /account/verification/email/verify?token=xxx

    토큰을 디코딩하여 purpose=email_verify 확인 후,
    해당 회원의 email_verified를 true로 업데이트.
    성공 시 로그인 페이지로 리다이렉트.
    """
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=400, detail="유효하지 않거나 만료된 인증 토큰입니다.")

    if payload.get("purpose") != "email_verify":
        raise HTTPException(status_code=400, detail="유효하지 않은 토큰입니다.")

    member_id = payload.get("member_id")
    email = payload.get("email")

    if not member_id or not email:
        raise HTTPException(status_code=400, detail="토큰 정보가 올바르지 않습니다.")

    supabase = get_supabase()

    # 회원 존재 확인
    try:
        member_result = supabase.table("members").select("id, email, email_verified").eq(
            "id", member_id
        ).single().execute()
    except Exception:
        raise HTTPException(status_code=404, detail="회원 정보를 찾을 수 없습니다.")

    if not member_result.data:
        raise HTTPException(status_code=404, detail="회원 정보를 찾을 수 없습니다.")

    member = member_result.data

    # 이미 인증된 경우
    if member.get("email_verified"):
        return RedirectResponse(
            url="/auth/login?message=already_verified",
            status_code=303,
        )

    # 이메일 인증 처리
    try:
        supabase.table("members").update({
            "email_verified": True,
            "email": email,
            "updated_at": datetime.utcnow().isoformat(),
        }).eq("id", member_id).execute()
        logger.info(f"Email verified for member {member_id}: {email}")
    except Exception as e:
        logger.error(f"Email verification update error: {e}")
        raise HTTPException(status_code=500, detail="이메일 인증 처리 중 오류가 발생했습니다.")

    # 환영 이메일 발송
    settings = get_account_settings()
    try:
        email_service = EmailService(api_key=settings.RESEND_API_KEY)
        await email_service.send_welcome_email(to=email, name=member.get("full_name", "회원"))
    except Exception as e:
        logger.warning(f"Welcome email send failed: {e}")

    return RedirectResponse(
        url="/auth/login?message=email_verified",
        status_code=303,
    )


# =============================================
# BRN (사업자등록번호) Verification
# =============================================

@router.post("/brn/verify")
async def verify_brn(request: Request, body: BRNVerifyRequest):
    """
    사업자등록번호 형식 검증 (체크디짓)

    POST /account/verification/brn/verify
    Body: { "brn": "123-45-67890" }

    오프라인 체크디짓 검증만 수행. 국세청 API 진위확인은 org-claim에서 처리.
    """
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    brn = body.brn.replace("-", "").replace(" ", "")

    if len(brn) != 10 or not brn.isdigit():
        return {
            "valid": False,
            "formatted": None,
            "message": "사업자등록번호는 10자리 숫자여야 합니다.",
        }

    is_valid = validate_brn_checkdigit(body.brn)
    formatted = f"{brn[:3]}-{brn[3:5]}-{brn[5:]}"

    return {
        "valid": is_valid,
        "formatted": formatted,
        "message": "유효한 사업자등록번호입니다." if is_valid else "체크디짓 검증에 실패했습니다. 번호를 확인해주세요.",
    }


# =============================================
# Verification Status
# =============================================

@router.get("/status")
async def get_verification_status(request: Request):
    """
    현재 회원의 전체 인증 상태 확인

    GET /account/verification/status

    이메일 인증, 이미지 인증, 선수 Claim 등 통합 상태 반환.
    """
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    supabase = get_supabase()
    verifications = supabase.table("verifications").select("*").eq(
        "member_id", member["id"]
    ).order("created_at", desc=True).execute()

    return {
        "email_verified": member.get("email_verified", False),
        "member_verification_status": member.get("verification_status", "pending"),
        "verification_tier": member.get("verification_tier", 0),
        "verifications": verifications.data or [],
    }


# =============================================
# Helpers
# =============================================

def _get_status_message(status: str) -> str:
    """상태별 메시지"""
    messages = {
        "approved": "인증이 완료되었습니다!",
        "rejected": "인증이 거부되었습니다. 다시 시도해주세요.",
        "pending": "인증 검토 중입니다.",
        "processing": "인증 처리 중입니다.",
    }
    return messages.get(status, "처리 중입니다.")
