"""
Account Service - FastAPI 서버

인증/프로필/구독 관리 서비스 (account.fencingmind.ai, port 70)
"""
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

from .auth.router import router as auth_router
from .profile.router import router as profile_router
from .verification.router import router as verification_router
from .subscriptions.router import router as subscriptions_router
from .payments.router import router as payments_router
from .dashboard.router import router as dashboard_router
from .admin.router import router as admin_router
from .admin.notifications import router as notifications_router
from .messenger.router import router as messenger_router
from .legal.router import router as legal_router
from .i18n.middleware import LanguageMiddleware

SERVICE_DIR = Path(__file__).parent.parent
TEMPLATES_DIR = SERVICE_DIR / "templates"
STATIC_DIR = SERVICE_DIR / "static"

app = FastAPI(
    title="FencingMind Account",
    description="인증/프로필/구독 관리 서비스",
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
        "https://community.fencingmind.ai",
        "https://shop.fencingmind.ai",
        "https://blog.fencingmind.ai",
        "https://analytics.fencingmind.ai",
        "https://app.fencingmind.ai",
        "http://localhost:9070",  # account dev
        "http://localhost:9071",  # data dev
        "http://localhost:9072",  # club dev
        "http://localhost:9073",  # community dev
        "http://localhost:9074",  # shop dev
        "http://localhost:9075",  # blog dev
        "http://localhost:9076",  # analytics dev
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
app.include_router(profile_router, prefix="/account")
app.include_router(verification_router, prefix="/account")
app.include_router(subscriptions_router, prefix="/account")
app.include_router(payments_router)     # /account/checkout/*, /account/webhooks/*, /account/portal
app.include_router(dashboard_router)    # /account/dashboard
app.include_router(admin_router)        # /account/admin/*
app.include_router(notifications_router)  # /account/notifications/*
app.include_router(messenger_router)    # /account/messenger/*
app.include_router(legal_router)        # /legal/terms, /legal/privacy, /terms, /privacy


@app.exception_handler(HTTPException)
async def auth_redirect_handler(request: Request, exc: HTTPException):
    """401 에러 시 브라우저 요청이면 로그인 페이지로 리다이렉트"""
    if exc.status_code == 401:
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            redirect_path = quote(str(request.url), safe="")
            return RedirectResponse(url=f"/auth/login?redirect={redirect_path}")
    # 401이 아니거나 API 요청이면 기본 JSON 에러 반환
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "account"}
