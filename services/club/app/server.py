"""
FencingMind Club Management SaaS
포트: 72 | 파일럿: 최병철펜싱클럽
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from . import config
from .database import get_supabase_client
from .club import club_router
from .billing import billing_router
from .notifications import notifications_router
from .schedule import schedule_router
from .lessons import lessons_router

templates: Jinja2Templates = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global templates
    logger.info(f"Club Service starting on port {config.PORT}")

    # Supabase 연결 확인
    try:
        client = get_supabase_client()
        logger.info("Supabase connected")
    except Exception as e:
        logger.warning(f"Supabase connection failed: {e}")

    if config.TEMPLATES_DIR.exists():
        templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))

    yield
    logger.info("Club Service stopped")


app = FastAPI(
    title="FencingMind Club",
    description="펜싱 클럽 관리 SaaS",
    version="0.1.0",
    lifespan=lifespan,
)

ALLOWED_ORIGINS = [
    "https://app.fencingmind.ai",
    "https://fencingmind.ai",
    "http://localhost:72",
    "http://127.0.0.1:72",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)

if config.STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")

# 라우터 마운트
app.include_router(club_router, prefix="/api")
app.include_router(billing_router, prefix="/api")
app.include_router(notifications_router, prefix="/api")
app.include_router(schedule_router, prefix="/api")
app.include_router(lessons_router, prefix="/api")


# ─────────────────────────────────────────────────────────────
# Health Check
# ─────────────────────────────────────────────────────────────

@app.get("/api/kakao-key")
async def kakao_key():
    """Kakao JavaScript App Key (public, safe to expose)"""
    return {"kakao_app_key": config.KAKAO_CLIENT_ID or ""}


@app.get("/api/health")
async def health():
    supabase_status = "disconnected"
    try:
        get_supabase_client()
        supabase_status = "connected"
    except Exception:
        pass

    return {
        "status": "ok",
        "service": "club",
        "port": config.PORT,
        "supabase": supabase_status,
        "org_id": config.DEFAULT_ORG_ID,
        "data_service_url": config.DATA_SERVICE_URL,
    }


# ─────────────────────────────────────────────────────────────
# PWA Support
# ─────────────────────────────────────────────────────────────

@app.get("/sw.js")
async def service_worker():
    sw_path = config.STATIC_DIR / "sw.js"
    return FileResponse(
        sw_path,
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Service-Worker-Allowed": "/",
        },
    )


@app.get("/offline.html")
async def offline_page():
    return FileResponse(config.STATIC_DIR / "offline.html", media_type="text/html")


# ─────────────────────────────────────────────────────────────
# Pages — 루트: 인증 여부에 따라 랜딩 or 대시보드 리다이렉트
# ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    from .club.dependencies import try_get_current_club_member
    from fastapi.responses import RedirectResponse

    member = await try_get_current_club_member(request)
    if member:
        # 인증된 사용자 → 역할별 대시보드로 리다이렉트
        return RedirectResponse(url="/api/club/", status_code=302)

    # 미인증 → 랜딩 페이지
    if templates:
        try:
            return templates.TemplateResponse(
                "club/landing.html",
                {"request": request, "title": "FencingMind Club"}
            )
        except Exception:
            pass
    return HTMLResponse(HOME_HTML)


HOME_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FencingMind Club</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, sans-serif; background: #f8fafc; }
        .nav { background: #2563eb; padding: 15px 20px; }
        .nav a { color: white; text-decoration: none; margin-right: 20px; }
        .container { max-width: 1000px; margin: 40px auto; padding: 0 20px; }
        h1 { color: #1e40af; margin-bottom: 10px; }
        .subtitle { color: #64748b; margin-bottom: 30px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; }
        .card { background: white; border-radius: 12px; padding: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        .card h3 { color: #1e40af; margin-bottom: 15px; font-size: 1.1rem; }
        .card ul { list-style: none; }
        .card li { padding: 10px 0; border-bottom: 1px solid #f1f5f9; display: flex; align-items: center; gap: 10px; }
        .card li:last-child { border: none; }
        .status { font-size: 0.8rem; padding: 2px 8px; border-radius: 10px; }
        .done { background: #dcfce7; color: #166534; }
        .progress { background: #fef3c7; color: #92400e; }
        .planned { background: #f1f5f9; color: #64748b; }
        .btn { display: inline-block; background: #2563eb; color: white; padding: 12px 24px; border-radius: 8px; text-decoration: none; margin-top: 20px; }
        .btn:hover { background: #1d4ed8; }
    </style>
</head>
<body>
    <nav class="nav">
        <a href="/">Home</a>
        <a href="/api/club/">Dashboard</a>
        <a href="/api/club/checkin">Check-in</a>
        <a href="/api/club/lessons-page">Lessons</a>
        <a href="/docs">API Docs</a>
    </nav>
    <div class="container">
        <h1>FencingMind Club Management</h1>
        <p class="subtitle">app.fencingmind.ai | Port 72 | Pilot: 최병철펜싱클럽</p>

        <div class="grid">
            <div class="card">
                <h3>Core Features</h3>
                <ul>
                    <li><span class="status done">DONE</span> Member Management</li>
                    <li><span class="status done">DONE</span> Attendance Check-in</li>
                    <li><span class="status done">DONE</span> Lesson Scheduling</li>
                    <li><span class="status done">DONE</span> Fee Management</li>
                    <li><span class="status done">DONE</span> Player Analytics</li>
                </ul>
            </div>
            <div class="card">
                <h3>Phase 2 - Advanced</h3>
                <ul>
                    <li><span class="status planned">PLAN</span> Kakao Login</li>
                    <li><span class="status done">DONE</span> Push Notifications (FCM)</li>
                    <li><span class="status done">DONE</span> Billing & Invoices</li>
                    <li><span class="status planned">PLAN</span> Kakao Alimtalk</li>
                    <li><span class="status planned">PLAN</span> PortOne Payment</li>
                </ul>
            </div>
        </div>

        <a href="/api/club/" class="btn">Go to Dashboard</a>
    </div>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host=config.HOST, port=config.PORT, reload=config.DEBUG)
