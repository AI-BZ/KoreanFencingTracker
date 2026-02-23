"""
Verification Router - 인증(본인확인) 엔드포인트

/account 접두사는 server.py에서 추가됨.
최종 경로: /account/verification, /account/verification/upload, /account/verification/status
"""
from uuid import UUID
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from loguru import logger

from shared_core.auth.jwt import get_current_member
from shared_core.db.client import get_supabase_client

from .processor import VerificationProcessor

router = APIRouter(prefix="/verification", tags=["verification"])

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))


def get_supabase():
    return get_supabase_client()


@router.get("", response_class=HTMLResponse)
async def verification_page(request: Request):
    """인증 페이지"""
    member = await get_current_member(request)
    if not member:
        return RedirectResponse(url="/auth/login", status_code=303)

    supabase = get_supabase()
    verifications = supabase.table("verifications").select("*").eq(
        "member_id", member["id"]
    ).order("created_at", desc=True).execute()

    return _templates.TemplateResponse(
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
            "success": True,
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


@router.get("/status")
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
