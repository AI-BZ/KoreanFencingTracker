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
from .processor import (
    VerificationProcessor,
    VerificationStorageError,
    VerificationUploadRejected,
    build_verification_object_path,
    upload_verification_image,
    validate_verification_image,
)
from .brn import validate_brn_checkdigit
from .claims import router as claims_router
from .notification_service import VerificationNotificationService
from app.i18n.middleware import create_language_context

router = APIRouter(prefix="/verification", tags=["verification"])

# Include claims sub-routes (player-search, player-claim, org-claim)
router.include_router(claims_router)

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))

# verifications.verification_type CHECK 제약(migration 003)과 일치해야 한다.
# 화이트리스트 밖의 값은 DB가 거부하기 전에 400으로 막는다.
ALLOWED_VERIFICATION_TYPES = frozenset({
    "association_card",
    "mask_photo",
    "uniform_photo",
})


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
# Verification Axes (인증 축 상태 계산)
# =============================================
#
# 인증은 서로 독립적인 4개의 축으로 구성된다. 한 축이 완료되었다고 해서
# 다른 축이 완료된 것이 아니므로, 화면 게이트를 members.verification_status
# 하나로 묶으면 안 된다.
#
#   document     : members.verification_status  (서류/사진 심사)
#   player       : members.player_id + player_claims  (선수 기록 연결)
#   parent       : parent_claims                (자녀 관계)
#   organization : organization_claims          (조직 소유권)
#
# 각 축의 상태는 verified | in_review | rejected | none 4가지로 정규화한다.

AXIS_STATE_VERIFIED = "verified"
AXIS_STATE_IN_REVIEW = "in_review"
AXIS_STATE_REJECTED = "rejected"
AXIS_STATE_NONE = "none"

# 플로우별로 "먼저 보여줄" 축 순서. 여기에 없더라도 상태가 none이 아닌 축은
# 뒤에 자동으로 덧붙여 표시한다. 예: general 회원인데 서류 심사만 통과(verified)된
# 대표 계정의 경우 document 축이 자동으로 붙어 "무엇이 인증된 것인지" 드러난다.
# 사진 제출 UI는 player 플로우에서만 제공하므로 document를 기본 노출하는 것도 player뿐.
FLOW_AXES = {
    "player": ["player", "document"],
    "parent": ["parent"],
    "coach": ["player"],
    "director": ["organization"],
    "general": ["player"],
}

AXIS_ORDER = ["player", "parent", "organization", "document"]


def _safe_rows(supabase, table: str, member_id) -> list:
    """member_id로 조회. 테이블이 없거나 조회 실패해도 페이지는 떠야 하므로 fail-open."""
    try:
        result = supabase.table(table).select("*").eq(
            "member_id", member_id
        ).order("created_at", desc=True).execute()
        return result.data or []
    except Exception as e:
        logger.warning(f"{table} 조회 실패 (member={member_id}): {e}")
        return []


def _latest(rows: list):
    return rows[0] if rows else None


def _document_state(member: dict, verifications: list) -> str:
    """서류/사진 심사 축 상태."""
    status = (member.get("verification_status") or "").lower()
    if status == "verified":
        return AXIS_STATE_VERIFIED
    if status in ("submitted", "processing"):
        return AXIS_STATE_IN_REVIEW
    if status == "rejected":
        return AXIS_STATE_REJECTED

    latest = _latest(verifications)
    if latest:
        row_status = (latest.get("status") or "").lower()
        if row_status == "approved":
            return AXIS_STATE_VERIFIED
        if row_status in ("pending", "processing", "submitted"):
            return AXIS_STATE_IN_REVIEW
        if row_status == "rejected":
            return AXIS_STATE_REJECTED
    return AXIS_STATE_NONE


def _claim_state(claim: dict | None, approved: tuple, in_review: tuple) -> str:
    """claim 레코드 하나를 축 상태로 정규화."""
    if not claim:
        return AXIS_STATE_NONE
    status = (claim.get("status") or "").lower()
    if status in approved:
        return AXIS_STATE_VERIFIED
    if status in in_review:
        return AXIS_STATE_IN_REVIEW
    if status == "rejected":
        return AXIS_STATE_REJECTED
    return AXIS_STATE_NONE


def _build_axes(member: dict, verifications: list, player_claims: list,
                parent_claims: list, org_claims: list) -> dict:
    """4개 축의 상태를 계산한다. 문구는 템플릿(i18n)에서 결정한다."""
    latest_player = _latest(player_claims)
    latest_parent = _latest(parent_claims)
    latest_org = _latest(org_claims)

    # 선수 축: members.player_id가 이미 연결됐으면 그 자체로 완료.
    if member.get("player_id"):
        player_state = AXIS_STATE_VERIFIED
    else:
        player_state = _claim_state(latest_player, ("approved",), ("pending", "processing", "ai_reviewed"))

    return {
        "document": {
            "state": _document_state(member, verifications),
            "latest": _latest(verifications),
            "count": len(verifications),
            "raw_status": member.get("verification_status") or "pending",
        },
        "player": {
            "state": player_state,
            "player_id": member.get("player_id"),
            "latest": latest_player,
            "count": len(player_claims),
        },
        "parent": {
            "state": _claim_state(latest_parent, ("approved",), ("pending", "processing", "ai_reviewed")),
            "latest": latest_parent,
            "count": len(parent_claims),
        },
        "organization": {
            "state": _claim_state(latest_org, ("approved", "auto_verified"), ("pending", "processing")),
            "latest": latest_org,
            "count": len(org_claims),
        },
    }


def _visible_axes(flow: str, axes: dict) -> list:
    """플로우 기본 축 + 상태가 있는 나머지 축."""
    order = list(FLOW_AXES.get(flow, FLOW_AXES["general"]))
    for key in AXIS_ORDER:
        if key not in order and axes[key]["state"] != AXIS_STATE_NONE:
            order.append(key)
    return order


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
    settings = get_account_settings()

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

    # 축별 상태를 계산하려면 플로우와 무관하게 4개 축을 모두 조회해야 한다.
    # (예: general 회원이 과거에 서류 심사만 통과한 경우도 정확히 보여줘야 함)
    member_id = member["id"]
    verifications = _safe_rows(supabase, "verifications", member_id)
    player_claims = _safe_rows(supabase, "player_claims", member_id)
    parent_claims = _safe_rows(supabase, "parent_claims", member_id)
    org_claims = _safe_rows(supabase, "organization_claims", member_id)

    # parent_claims.ai_report가 문자열로 오는 경우 파싱 (템플릿에서 dict로 접근)
    for pc in parent_claims:
        if isinstance(pc.get("ai_report"), str):
            try:
                import json
                pc["ai_report"] = json.loads(pc["ai_report"])
            except Exception:
                pc["ai_report"] = {}

    axes = _build_axes(member, verifications, player_claims, parent_claims, org_claims)

    context = {
        "request": request,
        "member": member,
        "verification_flow": verification_flow,
        "axes": axes,
        "visible_axes": _visible_axes(verification_flow, axes),
        # Gemini 키가 없으면 사진 인증은 제출 즉시 자동 거부된다.
        # 동작하지 않는 기능을 열어두지 않기 위해 서버에서 판단해 넘긴다.
        "photo_verification_enabled": bool(settings.GEMINI_API_KEY),
        "verifications": verifications,
        "player_claims": player_claims,
        "parent_claims": parent_claims,
        "org_claims": org_claims,
        "verification_types": [
            {"value": "association_card", "label": acct.get("type_association_card", "협회 등록증"), "icon": "card"},
            {"value": "mask_photo", "label": acct.get("type_mask_photo", "마스크 + 이름/날짜 종이"), "icon": "mask"},
            {"value": "uniform_photo", "label": acct.get("type_uniform_photo", "도복 + 이름/날짜 종이"), "icon": "uniform"},
        ],
        **i18n_ctx,
    }

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

    if verification_type not in ALLOWED_VERIFICATION_TYPES:
        raise HTTPException(status_code=400, detail="지원하지 않는 인증 유형입니다")

    content = await file.read()

    # 크기/형식 검증. 선언된 Content-Type이 아니라 실제 바이트를 스니핑해서
    # 판단하고, 저장 확장자도 스니핑 결과에서만 파생시킨다(사용자 파일명 미사용).
    try:
        actual_mime, file_ext = validate_verification_image(content, file.content_type)
    except VerificationUploadRejected as e:
        raise HTTPException(status_code=400, detail=str(e))

    supabase = get_supabase()

    # 비공개 버킷에 업로드. 실패하면 여기서 끝낸다 —
    # 공개 URL이나 가짜 로컬 경로로 폴백하고 DB 행만 남기던 예전 동작은 제거했다.
    storage_path = build_verification_object_path(member["id"], file_ext)
    try:
        upload_verification_image(storage_path, content, actual_mime)
    except VerificationStorageError as e:
        logger.error(f"인증 이미지 업로드 거부 (member={member['id']}): {e}")
        raise HTTPException(
            status_code=503,
            detail=(
                "인증 이미지 저장소가 설정되지 않아 업로드를 처리할 수 없습니다. "
                "관리자에게 문의해주세요."
            ),
        )

    # 인증 레코드 생성.
    # image_url은 003 마이그레이션에서 NOT NULL로 잡혀 있어 값을 채워야 하지만,
    # 더 이상 공개 URL을 넣지 않는다. 역참조 불가능한 storage:// URI를 넣어
    # (a) NOT NULL을 만족시키고 (b) 혹시 이 값을 href/img src로 쓰는 코드가 있으면
    # 조용히 유출되는 대신 눈에 띄게 깨지도록 한다.
    # 정식 값은 image_storage_path이며, 읽을 때는 매번 서명 URL을 발급한다.
    settings = get_account_settings()
    verification_data = {
        "member_id": member["id"],
        "verification_type": verification_type,
        "image_url": f"storage://{settings.VERIFICATION_STORAGE_BUCKET}/{storage_path}",
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
