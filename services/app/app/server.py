"""
App Service - FastAPI 서버

PWA/알림 허브 서비스 (app.fencingmind.ai, port 77)
- FCM 웹 푸시 + 카카오 알림톡 통합 발송
- data 서비스 이벤트 폴링 → 알림 디스패치
- PWA manifest + service worker 호스팅
"""
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

from shared_core.i18n import LanguageMiddleware, create_language_context

from .auth.router import router as auth_router

SERVICE_DIR = Path(__file__).parent.parent
TEMPLATES_DIR = SERVICE_DIR / "templates"
STATIC_DIR = SERVICE_DIR / "static"

app = FastAPI(
    title="FencingMind App",
    description="PWA/알림 허브 서비스",
    version="0.1.0",
)

# Language detection middleware (must be before CORS)
app.add_middleware(LanguageMiddleware)

# CORS 미들웨어 (서브도메인 간 API 호출 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://account.fencingmind.ai",
        "https://data.fencingmind.ai",
        "https://club.fencingmind.ai",
        "https://app.fencingmind.ai",
        "http://localhost:9070",  # account dev
        "http://localhost:9071",  # data dev
        "http://localhost:9077",  # app dev
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files (only if directory exists)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Routers
app.include_router(auth_router)


@app.exception_handler(HTTPException)
async def auth_redirect_handler(request: Request, exc: HTTPException):
    """401 에러 시 브라우저 요청이면 로그인 페이지로 리다이렉트"""
    if exc.status_code == 401:
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            redirect_path = quote(str(request.url), safe="")
            return RedirectResponse(url=f"/auth/login?redirect={redirect_path}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.get("/")
async def home(request: Request):
    """PWA 알림 허브 메인 페이지"""
    return templates.TemplateResponse("home.html", {
        "request": request,
        **create_language_context(request),
    })


@app.get("/service-worker.js")
async def service_worker():
    """Serve SW from root path so its scope covers the entire origin."""
    sw_path = STATIC_DIR / "service-worker.js"
    return FileResponse(
        str(sw_path),
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


@app.get("/offline.html")
async def offline_page():
    """Offline fallback page (served by SW when network is unavailable)."""
    return FileResponse(str(STATIC_DIR / "offline.html"), media_type="text/html")


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "app"}
