"""
FencingMind Club Management SaaS
포트: 75 | 파일럿: 최병철펜싱클럽
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from . import config
from .database import get_supabase_client
from .club import club_router

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if config.STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")

# Club 라우터 마운트 (핵심!)
app.include_router(club_router, prefix="/api")


# ─────────────────────────────────────────────────────────────
# Health Check
# ─────────────────────────────────────────────────────────────

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
# Pages (club_router의 HTML 페이지가 /api/club/ 하위에 있으므로
# 루트 페이지만 여기서 제공)
# ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    if templates:
        try:
            return templates.TemplateResponse("base.html", {"request": request})
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
        <p class="subtitle">app.fencingmind.ai | Port 75 | Pilot: 최병철펜싱클럽</p>

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
                    <li><span class="status planned">PLAN</span> Push Notifications</li>
                    <li><span class="status planned">PLAN</span> Public Club Page</li>
                    <li><span class="status planned">PLAN</span> Lesson Booking</li>
                    <li><span class="status planned">PLAN</span> Payment (Toss)</li>
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
