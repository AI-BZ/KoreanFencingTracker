"""배치 이메일 발송 라우터

- /admin/broadcasts (admin 전용): 배치 생성/발송/조회
- /auth/unsubscribe (공개): 수신거부 처리
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from loguru import logger
from pydantic import BaseModel, Field

from app.admin.dependencies import require_admin
from . import service

router = APIRouter(prefix="/admin/broadcasts", tags=["admin-broadcasts"])
public_router = APIRouter(tags=["broadcasts-public"])


class BroadcastCreate(BaseModel):
    subject: str = Field(..., min_length=1, max_length=300)
    body_html: str = Field(..., min_length=1)


@router.post("")
async def create_broadcast(
    payload: BroadcastCreate,
    admin: dict = Depends(require_admin),
):
    """배치 생성 + 수신자 스냅샷 (발송 전 미리보기용 수신자 수 반환)"""
    try:
        result = service.create_broadcast(
            subject=payload.subject,
            body_html=payload.body_html,
            created_by=admin.get("id"),
        )
    except Exception as e:
        logger.error(f"배치 생성 실패: {e}")
        raise HTTPException(status_code=500, detail="배치 생성에 실패했습니다")
    return result


@router.post("/{broadcast_id}/send")
async def send_broadcast(
    broadcast_id: str,
    limit: Optional[int] = None,
    admin: dict = Depends(require_admin),
):
    """pending 수신자 발송 (재실행 시 자동 재개). limit 으로 회당 발송량 제한."""
    try:
        result = await service.send_broadcast(broadcast_id, limit=limit)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"배치 발송 실패 ({broadcast_id}): {e}")
        raise HTTPException(status_code=500, detail="배치 발송에 실패했습니다")
    return result


@router.get("/{broadcast_id}")
async def get_broadcast(
    broadcast_id: str,
    admin: dict = Depends(require_admin),
):
    """배치 상태/카운트 조회"""
    result = service.get_broadcast(broadcast_id)
    if not result:
        raise HTTPException(status_code=404, detail="배치를 찾을 수 없습니다")
    return result


_UNSUB_OK_HTML = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>수신거부 완료 - FencingMind</title></head>
<body style="margin:0;padding:0;background:#f5f7fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;margin:60px auto;">
<tr><td style="background:#fff;border-radius:12px;padding:40px;text-align:center;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
    <h1 style="color:#3182ce;font-size:22px;margin:0 0 16px 0;">FencingMind</h1>
    <h2 style="font-size:18px;color:#333;margin:0 0 12px 0;">수신거부 처리되었습니다</h2>
    <p style="color:#555;font-size:15px;line-height:1.6;margin:0;">
        마케팅 정보 이메일 수신이 중단되었습니다.<br>
        언제든지 계정 설정에서 다시 수신 동의하실 수 있습니다.
    </p>
</td></tr>
</table>
</body></html>"""

_UNSUB_INVALID_HTML = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>수신거부 - FencingMind</title></head>
<body style="margin:0;padding:0;background:#f5f7fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;margin:60px auto;">
<tr><td style="background:#fff;border-radius:12px;padding:40px;text-align:center;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
    <h1 style="color:#3182ce;font-size:22px;margin:0 0 16px 0;">FencingMind</h1>
    <h2 style="font-size:18px;color:#333;margin:0 0 12px 0;">링크가 유효하지 않습니다</h2>
    <p style="color:#555;font-size:15px;line-height:1.6;margin:0;">
        수신거부 링크가 만료되었거나 올바르지 않습니다.<br>
        수신거부를 원하시면 계정 설정에서 마케팅 수신 동의를 해제해주세요.
    </p>
</td></tr>
</table>
</body></html>"""


@public_router.get("/auth/unsubscribe", response_class=HTMLResponse)
async def unsubscribe(token: str = ""):
    """수신거부 (공개, 인증 없음). 토큰 무효/만료 시에도 200 안내 페이지."""
    member_id = service.process_unsubscribe(token) if token else None
    if member_id:
        return HTMLResponse(content=_UNSUB_OK_HTML, status_code=200)
    return HTMLResponse(content=_UNSUB_INVALID_HTML, status_code=200)
