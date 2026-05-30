"""
Legal Router - 법적 문서 라우터

이용약관, 개인정보처리방침 등 법적 문서 페이지 제공.
기존 /terms, /privacy URL은 /legal/* 로 redirect.
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.i18n.middleware import create_language_context

router = APIRouter(tags=["legal"])

LEGAL_DIR = Path(__file__).parent.parent.parent / "templates" / "legal"
_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))


@router.get("/legal/terms", response_class=HTMLResponse)
async def terms_page(request: Request, v: str = None):
    """이용약관 페이지"""
    version = v or "1.0"
    md_file = LEGAL_DIR / f"terms_v{version}.md"
    if not md_file.exists():
        md_file = LEGAL_DIR / "terms_v1.0.md"
    content = md_file.read_text(encoding="utf-8")
    i18n_ctx = create_language_context(request)
    lang = i18n_ctx.get("lang", "ko")
    title = "Terms of Service" if lang == "en" else "이용약관"
    return _templates.TemplateResponse("legal/document.html", {
        "request": request,
        "title": title,
        "doc_type": "terms",
        "version": version,
        "effective_date": "2026-03-01",
        "content": content,
        **i18n_ctx,
    })


@router.get("/legal/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request, v: str = None):
    """개인정보처리방침 페이지"""
    version = v or "1.0"
    md_file = LEGAL_DIR / f"privacy_v{version}.md"
    if not md_file.exists():
        md_file = LEGAL_DIR / "privacy_v1.0.md"
    content = md_file.read_text(encoding="utf-8")
    i18n_ctx = create_language_context(request)
    lang = i18n_ctx.get("lang", "ko")
    title = "Privacy Policy" if lang == "en" else "개인정보처리방침"
    return _templates.TemplateResponse("legal/document.html", {
        "request": request,
        "title": title,
        "doc_type": "privacy",
        "version": version,
        "effective_date": "2026-03-01",
        "content": content,
        **i18n_ctx,
    })


# Redirects for old URLs
@router.get("/terms")
async def terms_redirect():
    """기존 /terms → /legal/terms redirect"""
    return RedirectResponse(url="/legal/terms", status_code=301)


@router.get("/privacy")
async def privacy_redirect():
    """기존 /privacy → /legal/privacy redirect"""
    return RedirectResponse(url="/legal/privacy", status_code=301)
