"""
Account Service - FastAPI 서버

인증/프로필/구독 관리 서비스 (account.fencingmind.ai, port 70)
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
from .messenger.router import router as messenger_router
from .legal.router import router as legal_router

SERVICE_DIR = Path(__file__).parent.parent
TEMPLATES_DIR = SERVICE_DIR / "templates"
STATIC_DIR = SERVICE_DIR / "static"

app = FastAPI(
    title="FencingMind Account",
    description="인증/프로필/구독 관리 서비스",
    version="0.1.0",
)

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
        "http://localhost:70",  # account dev
        "http://localhost:71",  # data dev
        "http://localhost:72",  # club dev
        "http://localhost:73",  # community dev
        "http://localhost:74",  # shop dev
        "http://localhost:75",  # blog dev
        "http://localhost:76",  # analytics dev
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
app.include_router(messenger_router)    # /account/messenger/*
app.include_router(legal_router)        # /legal/terms, /legal/privacy, /terms, /privacy


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "account"}
