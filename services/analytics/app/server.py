"""
FastAPI server for FencingMind Analytics service.

analytics.fencingmind.ai — AI-powered fencing match video analysis.
Port: 76
"""

import json
import sys
import uuid
import time
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Tuple

import jinja2
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse, HTMLResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from fastapi.middleware.cors import CORSMiddleware

from app.upload import VideoUploader
from app.credits import CreditManager, SubscriptionTier
from app.demo import generate_demo_report, generate_demo_de_report
from app.i18n.manager import i18n
from app.gallery import get_demo_reports, extract_youtube_id

_logger = logging.getLogger(__name__)
_BASE_DIR = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Application lifespan: connect DB on startup."""
    global _db
    try:
        from app.db import AnalyticsDB
        _db = AnalyticsDB()
        _logger.info("Supabase DB connected")
    except Exception as e:
        _logger.warning("Supabase DB unavailable, using in-memory fallback: %s", e)
        _db = None
    yield


app = FastAPI(
    title="FencingMind Analytics",
    description="AI-powered fencing match video analysis",
    version="0.3.0",
    lifespan=_lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://analytics.fencingmind.ai",
        "https://data.fencingmind.ai",
        "http://localhost:76",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files & Jinja2 templates
# Jinja2 3.1.x has an LRU cache key hashing bug on Python 3.14+;
# disable template caching to work around it until Jinja2 ships a fix.
app.mount("/static", StaticFiles(directory=str(_BASE_DIR / "static")), name="static")

# Serve raw video files for in-report playback (only if directory exists)
_raw_video_dir = _BASE_DIR / "data" / "raw"
if _raw_video_dir.exists():
    app.mount("/videos", StaticFiles(directory=str(_raw_video_dir)), name="videos")
_cache_size = 0 if sys.version_info >= (3, 14) else 400
_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_BASE_DIR / "templates")),
    autoescape=jinja2.select_autoescape(),
    cache_size=_cache_size,
)
templates = Jinja2Templates(env=_jinja_env)


# ------------------------------------------------------------------
# In-memory job store + optional Supabase DB
# ------------------------------------------------------------------

_jobs: Dict[str, dict] = {}
_videos: Dict[str, dict] = {}
_credit_manager = CreditManager()

# Supabase DB (optional — falls back to in-memory if unavailable)
_db = None


# ------------------------------------------------------------------
# Request / Response models
# ------------------------------------------------------------------


class AnalyzeRequest(BaseModel):
    """Request body for video analysis."""
    video_path: Optional[str] = None
    video_id: Optional[str] = None     # Reference to uploaded video
    weapon: Optional[str] = None       # "foil", "epee", "sabre"
    source_type: Optional[str] = None  # "coach", "parent", "player", "tv_broadcast"
    enable_pose: bool = True
    enable_action: bool = True
    rois: Optional[Dict[str, list]] = None  # Pre-defined ROIs


class JobStatus(BaseModel):
    """Analysis job status response."""
    job_id: str
    status: str            # "queued", "processing", "completed", "failed"
    progress_pct: float = 0.0
    error: Optional[str] = None


# ------------------------------------------------------------------
# Health / Status
# ------------------------------------------------------------------


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "analytics", "version": "0.2.0"}


@app.get("/api/analytics/status")
async def service_status():
    """Service status with available capabilities."""
    return {
        "service": "analytics",
        "capabilities": {
            "led_detection": True,
            "score_ocr": True,
            "clip_extraction": True,
            "auto_labeling": True,
            "pose_estimation": True,
            "action_recognition": True,
            "report_generation": True,
        },
        "phase": 2,
    }


# ------------------------------------------------------------------
# Analysis endpoints
# ------------------------------------------------------------------


@app.post("/api/analytics/analyze")
async def start_analysis(
    req: AnalyzeRequest,
    background_tasks: BackgroundTasks,
):
    """
    Start async video analysis.

    Accepts either video_path (local file) or video_id (uploaded video).
    Creates a job and runs analysis in the background.
    Poll GET /api/analytics/jobs/{job_id} for status.
    """
    # Resolve video path from video_id or video_path
    resolved_path = req.video_path
    if req.video_id:
        vid = _videos.get(req.video_id)
        if vid is None:
            raise HTTPException(status_code=404, detail=f"Uploaded video not found: {req.video_id}")
        resolved_path = vid["storage_path"]
    if not resolved_path:
        raise HTTPException(status_code=400, detail="Either video_path or video_id is required")

    video = Path(resolved_path)
    if not video.exists():
        raise HTTPException(status_code=404, detail=f"Video not found: {resolved_path}")

    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {
        "status": "queued",
        "progress_pct": 0.0,
        "video_path": resolved_path,
        "video_id": req.video_id,
        "weapon": req.weapon,
        "source_type": req.source_type,
        "started_at": time.time(),
        "result": None,
        "error": None,
    }

    background_tasks.add_task(
        _run_analysis,
        job_id,
        resolved_path,
        req.weapon,
        req.enable_pose,
        req.enable_action,
        req.rois,
        req.source_type,
        "default",  # member_id placeholder until auth is integrated
    )

    return {"job_id": job_id, "status": "queued"}


@app.get("/api/analytics/jobs/{job_id}")
async def get_job_status(job_id: str):
    """Check analysis job status."""
    job = _jobs.get(job_id)
    if job is None:
        # Check if report exists on disk (completed before restart)
        report_path = _BASE_DIR / "data" / "reports" / f"{job_id}.json"
        if report_path.exists():
            return JobStatus(job_id=job_id, status="completed", progress_pct=100.0)
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    return JobStatus(
        job_id=job_id,
        status=job["status"],
        progress_pct=job["progress_pct"],
        error=job.get("error"),
    )


@app.get("/api/analytics/results/{job_id}")
async def get_results(job_id: str):
    """
    Get full analysis results as MatchReport JSON.

    Returns 202 if analysis is still in progress.
    """
    job = _jobs.get(job_id)
    if job is None:
        # Job not in memory — check persisted reports on disk
        report_path = _BASE_DIR / "data" / "reports" / f"{job_id}.json"
        if report_path.exists():
            with open(report_path, "r", encoding="utf-8") as f:
                return json.load(f)
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    if job["status"] == "processing":
        return JSONResponse(
            status_code=202,
            content={"job_id": job_id, "status": "processing", "progress_pct": job["progress_pct"]},
        )

    if job["status"] == "failed":
        raise HTTPException(status_code=500, detail=job.get("error", "Analysis failed"))

    if job["status"] != "completed" or job["result"] is None:
        return JSONResponse(
            status_code=202,
            content={"job_id": job_id, "status": job["status"]},
        )

    return job["result"]


@app.get("/api/analytics/report/{job_id}")
async def get_report(job_id: str, format: str = "json"):
    """
    Get formatted analysis report.

    Query params:
        format: "json" (default), "html", or "pdf"
    """
    job = _jobs.get(job_id)
    if job is None:
        # Job not in memory — check persisted reports on disk
        report_path = _BASE_DIR / "data" / "reports" / f"{job_id}.json"
        if not report_path.exists():
            raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
        with open(report_path, "r", encoding="utf-8") as f:
            report_dict = json.load(f)
    elif job["status"] != "completed" or job["result"] is None:
        return JSONResponse(
            status_code=202,
            content={"job_id": job_id, "status": job["status"]},
        )
    else:
        report_dict = job["result"]

    if format == "html":
        from app.report_renderer import ReportRenderer
        renderer = ReportRenderer()
        html = renderer.render_html(report_dict, standalone=True)
        return HTMLResponse(content=html)

    if format == "pdf":
        from app.pdf_exporter import PDFExporter
        try:
            exporter = PDFExporter()
            pdf_bytes = exporter.export(report_dict)
        except RuntimeError as exc:
            raise HTTPException(status_code=501, detail=str(exc))
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="report-{job_id}.pdf"'},
        )

    return report_dict


# ------------------------------------------------------------------
# i18n helpers
# ------------------------------------------------------------------


def _get_lang(request: Request) -> str:
    """Detect language from cookie, Accept-Language header, or default."""
    lang = request.cookies.get("lang")
    if lang in ("ko", "en"):
        return lang
    accept = request.headers.get("accept-language", "")
    if "en" in accept.split(",")[0].lower():
        return "en"
    return "ko"


def _i18n_context(request: Request) -> dict:
    """Build Jinja2 template context with i18n support."""
    lang = _get_lang(request)
    return {
        "lang": lang,
        "t": lambda key: i18n.get(key, lang),
    }


@app.get("/lang/{code}")
async def switch_language(request: Request, code: str):
    """Switch language and redirect back."""
    if code not in ("ko", "en"):
        code = "ko"
    referer = request.headers.get("referer", "/")
    response = RedirectResponse(url=referer, status_code=303)
    response.set_cookie("lang", code, max_age=365 * 24 * 3600, path="/")
    return response


# ------------------------------------------------------------------
# HTML page routes (Jinja2 templates)
# ------------------------------------------------------------------


@app.get("/")
async def index(request: Request):
    """Landing page."""
    ctx = _i18n_context(request)
    gallery_reports = get_demo_reports(ctx["lang"])
    return templates.TemplateResponse(request, "landing.html", {
        **ctx,
        "gallery_reports": gallery_reports,
    })


@app.get("/upload")
async def upload_page(request: Request):
    """Video upload page."""
    return templates.TemplateResponse(request, "upload.html", _i18n_context(request))


@app.get("/dashboard")
async def dashboard_page(request: Request):
    """Dashboard page showing all analysis jobs."""
    jobs_list = []
    for job_id, job in _jobs.items():
        vid_info = _videos.get(job.get("video_id", ""), {})
        jobs_list.append({
            "job_id": job_id,
            "filename": vid_info.get("filename", Path(job.get("video_path", "")).name),
            "weapon": vid_info.get("weapon", job.get("weapon")),
            "source_type": vid_info.get("source_type", job.get("source_type")),
            "status": job["status"],
            "uploaded_at": vid_info.get("uploaded_at_display", ""),
            "error": job.get("error"),
        })

    # Most recent first (by started_at timestamp)
    jobs_list.sort(key=lambda j: j["uploaded_at"] or "", reverse=True)

    sub_info = _credit_manager.get_subscription_info("default")
    credits = sub_info.get("credits", 0)

    return templates.TemplateResponse(request, "dashboard.html", {
        **_i18n_context(request),
        "jobs": jobs_list,
        "credits": credits,
    })


@app.get("/report/{job_id}")
async def report_page(request: Request, job_id: str):
    """
    Analysis report page with charts and insights.

    Uses Jinja2 template with Chart.js for interactive visualizations.
    Falls back to loading from data/reports/ if job is not in memory
    (e.g. after server restart).
    """
    job = _jobs.get(job_id)

    if job is not None:
        if job["status"] != "completed" or job["result"] is None:
            return HTMLResponse(
                content=f"<html><body><p>분석 진행 중... (상태: {job['status']})</p></body></html>",
                status_code=202,
            )
        report_dict = job["result"]
        mock_mode = job.get("mock_mode", False)
    else:
        # Job not in memory — check persisted reports on disk
        report_path = _BASE_DIR / "data" / "reports" / f"{job_id}.json"
        if not report_path.exists():
            raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
        with open(report_path, "r", encoding="utf-8") as f:
            report_dict = json.load(f)
        mock_mode = False

    # Enrich with aggregated stats if needed
    _enrich_report_stats(report_dict)

    # Resolve video for playback
    video_filename = None
    video_path = report_dict.get("meta", {}).get("video_path") or ""
    if video_path:
        vf = Path(video_path).name
        if (_raw_video_dir / vf).exists():
            video_filename = vf

    youtube_url = None
    if not video_filename:
        yt_id = extract_youtube_id(job_id)
        if yt_id:
            youtube_url = f"https://www.youtube.com/watch?v={yt_id}"

    return templates.TemplateResponse(request, "report.html", {
        **_i18n_context(request),
        "report": report_dict,
        "report_json": json.dumps(report_dict, ensure_ascii=False),
        "job_id": job_id,
        "report_id": job_id,
        "mock_mode": mock_mode,
        "video_filename": video_filename,
        "youtube_url": youtube_url,
    })


# ------------------------------------------------------------------
# Demo gallery
# ------------------------------------------------------------------


@app.get("/gallery")
async def gallery_page(request: Request):
    """Demo gallery page with curated real analysis reports."""
    ctx = _i18n_context(request)
    reports = get_demo_reports(ctx["lang"])
    return templates.TemplateResponse(request, "gallery.html", {
        **ctx,
        "reports": reports,
    })


@app.get("/demo")
async def demo_report_page(request: Request):
    """Redirect legacy /demo to /gallery."""
    return RedirectResponse(url="/gallery", status_code=303)


@app.get("/demo/de")
async def demo_de_report_page(request: Request):
    """Redirect legacy /demo/de to /gallery."""
    return RedirectResponse(url="/gallery", status_code=303)


@app.get("/demo/dashboard")
async def demo_dashboard_page(request: Request):
    """Demo dashboard with sample jobs."""
    report_dict = generate_demo_report()
    de_report = generate_demo_de_report()
    demo_jobs = {
        "demo-001": {
            "status": "completed", "progress_pct": 100.0,
            "video_path": "2026-전국체전-남자플뢰레-김민수vs박지현.mp4", "weapon": "foil",
            "source_type": "coach", "started_at": time.time(),
            "result": report_dict, "error": None, "video_id": "",
        },
        "demo-002": {
            "status": "processing", "progress_pct": 45.0,
            "video_path": "2026-전국체전-남자에페-이준호vs최서연.mp4", "weapon": "epee",
            "source_type": "coach", "started_at": time.time(),
            "result": None, "error": None, "video_id": "",
        },
        "demo-003": {
            "status": "completed", "progress_pct": 100.0,
            "video_path": "2026-회장배-여자사브르-예선3조.mp4", "weapon": "sabre",
            "source_type": "parent", "started_at": time.time(),
            "result": de_report, "error": None, "video_id": "",
        },
    }
    _jobs.update(demo_jobs)

    jobs_list = [
        {
            "job_id": "demo-001",
            "filename": "2026-전국체전-남자플뢰레-김민수vs박지현.mp4",
            "weapon": "foil",
            "source_type": "coach",
            "status": "completed",
            "uploaded_at": "2026-05-24 09:15",
            "error": None,
        },
        {
            "job_id": "demo-002",
            "filename": "2026-전국체전-남자에페-이준호vs최서연.mp4",
            "weapon": "epee",
            "source_type": "coach",
            "status": "processing",
            "uploaded_at": "2026-05-25 14:30",
            "error": None,
        },
        {
            "job_id": "demo-003",
            "filename": "2026-회장배-여자사브르-예선3조.mp4",
            "weapon": "sabre",
            "source_type": "parent",
            "status": "completed",
            "uploaded_at": "2026-05-25 16:45",
            "error": None,
        },
    ]

    return templates.TemplateResponse(request, "dashboard.html", {
        **_i18n_context(request),
        "jobs": jobs_list,
        "credits": 100,
    })


# ------------------------------------------------------------------
# Saved report endpoints (load from data/reports/)
# ------------------------------------------------------------------


def _enrich_report_stats(report_dict: dict) -> dict:
    """Compute distance_stats and footwork_stats from per-touch pose_analysis data.

    Saved reports may have per-touch pose_analysis data but missing aggregated
    fencer_profile.distance_stats / footwork_stats. This function computes them
    on-the-fly from the available touch and exchange data.
    """
    touches = report_dict.get("touches") or []
    exchanges = report_dict.get("exchanges") or []
    fencer_profile = report_dict.get("fencer_profile") or {}

    for side in ("left", "right"):
        fp = fencer_profile.get(side)
        if not fp:
            continue

        # Skip if already populated
        has_distance = fp.get("distance_stats") and fp["distance_stats"].get("zone_distribution")
        has_footwork = fp.get("footwork_stats") and fp["footwork_stats"].get("type_distribution")
        if has_distance and has_footwork:
            continue

        # Aggregate from touches
        zone_counts: Dict[str, int] = {}
        zone_scored: Dict[str, int] = {}
        footwork_counts: Dict[str, int] = {}
        footwork_scored: Dict[str, int] = {}
        total_distance_bh = 0.0
        distance_count = 0

        for touch in touches:
            pa = touch.get("pose_analysis")
            if not pa:
                continue

            scorer = touch.get("scorer", "")

            # Distance stats
            zone = pa.get("distance_zone")
            dist_bh = pa.get("distance_bh")
            if zone:
                zone_counts[zone] = zone_counts.get(zone, 0) + 1
                if scorer == side:
                    zone_scored[zone] = zone_scored.get(zone, 0) + 1
            if dist_bh is not None:
                total_distance_bh += dist_bh
                distance_count += 1

            # Footwork — use scorer's footwork
            fw_key = f"footwork_{'scorer' if scorer == side else 'opponent'}"
            fw = pa.get(fw_key, pa.get("footwork_scorer"))
            if fw and fw != "unknown":
                footwork_counts[fw] = footwork_counts.get(fw, 0) + 1
                if scorer == side:
                    footwork_scored[fw] = footwork_scored.get(fw, 0) + 1

        # Also aggregate from exchanges for footwork
        for ex in exchanges:
            # exchanges use footwork_left / footwork_right
            fw = ex.get(f"footwork_{side}")
            if fw and fw != "unknown":
                footwork_counts[fw] = footwork_counts.get(fw, 0) + 1

        # Build distance_stats if we have data
        if not has_distance and zone_counts:
            zone_success_rate = {}
            for z, cnt in zone_counts.items():
                scored = zone_scored.get(z, 0)
                zone_success_rate[z] = scored / cnt if cnt > 0 else 0.0

            # Preferred zone = zone with most touches
            preferred = max(zone_counts, key=zone_counts.get) if zone_counts else None

            fp["distance_stats"] = {
                "zone_distribution": zone_counts,
                "zone_success_rate": zone_success_rate,
                "preferred_zone": preferred,
                "avg_distance_bh": total_distance_bh / distance_count if distance_count > 0 else None,
            }

        # Build footwork_stats if we have data
        if not has_footwork and footwork_counts:
            fw_success_rate = {}
            for fw_type, cnt in footwork_counts.items():
                scored = footwork_scored.get(fw_type, 0)
                fw_success_rate[fw_type] = scored / cnt if cnt > 0 else 0.0

            preferred_fw = max(footwork_counts, key=footwork_counts.get) if footwork_counts else None

            fp["footwork_stats"] = {
                "type_distribution": footwork_counts,
                "type_success_rate": fw_success_rate,
                "preferred_footwork": preferred_fw,
            }

    return report_dict


@app.get("/report/saved/{video_id}")
async def saved_report_page(request: Request, video_id: str):
    """Load a saved report JSON from data/reports/ and render it."""
    reports_dir = _BASE_DIR / "data" / "reports"
    report_path = reports_dir / f"{video_id}.json"

    if not report_path.exists():
        raise HTTPException(status_code=404, detail=f"Report not found: {video_id}")

    with open(report_path, "r", encoding="utf-8") as f:
        report_dict = json.load(f)

    # Enrich fencer_profile with aggregated distance/footwork stats
    _enrich_report_stats(report_dict)

    # Resolve video filename for in-report playback
    video_filename = None
    video_path = report_dict.get("meta", {}).get("video_path") or ""
    if video_path:
        vf = Path(video_path).name
        if (_raw_video_dir / vf).exists():
            video_filename = vf
    if not video_filename:
        # Convention: {stem}_continuous_report → {stem}.mp4
        stem = video_id.replace("_continuous_report", "").replace("_report", "")
        for ext in (".mp4", ".mkv", ".webm"):
            if (_raw_video_dir / f"{stem}{ext}").exists():
                video_filename = f"{stem}{ext}"
                break

    # Extract YouTube URL for TV broadcast reports with no local video
    youtube_url = None
    if not video_filename:
        yt_id = extract_youtube_id(video_id)
        if yt_id:
            youtube_url = f"https://www.youtube.com/watch?v={yt_id}"

    return templates.TemplateResponse(request, "report.html", {
        **_i18n_context(request),
        "report": report_dict,
        "report_json": json.dumps(report_dict, ensure_ascii=False),
        "job_id": f"saved-{video_id}",
        "report_id": video_id,
        "video_filename": video_filename,
        "youtube_url": youtube_url,
    })


@app.get("/reports")
async def list_saved_reports(request: Request):
    """List all saved report JSON files."""
    reports_dir = _BASE_DIR / "data" / "reports"
    if not reports_dir.exists():
        return JSONResponse({"reports": []})

    reports = []
    for f in sorted(reports_dir.glob("*.json")):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            summary = data.get("summary", {})
            reports.append({
                "video_id": f.stem,
                "url": f"/report/saved/{f.stem}",
                "final_score": summary.get("final_score", ""),
                "match_duration": summary.get("match_duration", ""),
                "analysis_mode": data.get("meta", {}).get("analysis_mode", "unknown"),
                "total_exchanges": data.get("continuous_summary", {}).get("total_exchanges", 0),
            })
        except (json.JSONDecodeError, KeyError):
            continue

    return JSONResponse({"reports": reports, "total": len(reports)})


# ------------------------------------------------------------------
# Clip overlay endpoints
# ------------------------------------------------------------------


@app.get("/api/analytics/clips/{report_id}/{event_type}/{event_number}")
async def get_event_clip(report_id: str, event_type: str, event_number: int):
    """
    On-demand clip generation with caching.

    Generates a pose-overlay mp4 clip for a specific touch or exchange event.
    Clips are cached in data/clips/overlay/{report_id}/.
    """
    from fastapi.responses import StreamingResponse

    # Validate event_type
    if event_type not in ("touch", "exchange"):
        raise HTTPException(status_code=400, detail=f"Invalid event_type: {event_type}")

    # Load report
    reports_dir = _BASE_DIR / "data" / "reports"
    report_path = reports_dir / f"{report_id}.json"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail=f"Report not found: {report_id}")

    with open(report_path, "r", encoding="utf-8") as f:
        report_dict = json.load(f)

    # Check cache
    clips_dir = _BASE_DIR / "data" / "clips" / "overlay" / report_id
    clip_filename = f"{event_type}_{event_number:03d}.mp4"
    clip_path = clips_dir / clip_filename

    if clip_path.exists() and clip_path.stat().st_size > 1000:
        return StreamingResponse(
            open(str(clip_path), "rb"),
            media_type="video/mp4",
            headers={"Content-Disposition": f"inline; filename={clip_filename}"},
        )

    # Find the event
    if event_type == "touch":
        events = report_dict.get("touches", [])
        event = next((t for t in events if t.get("touch_number") == event_number), None)
        if event is None:
            raise HTTPException(status_code=404, detail=f"Touch #{event_number} not found")
        frame = event.get("frame")
        if frame is None:
            raise HTTPException(status_code=400, detail=f"Touch #{event_number} has no frame data")
        start_frame = frame
        end_frame = frame
    else:
        events = report_dict.get("exchanges", [])
        event = next((e for e in events if e.get("exchange_number") == event_number), None)
        if event is None:
            raise HTTPException(status_code=404, detail=f"Exchange #{event_number} not found")
        start_frame = event.get("start_frame")
        end_frame = event.get("end_frame")
        if start_frame is None or end_frame is None:
            raise HTTPException(status_code=400, detail=f"Exchange #{event_number} has no frame data")

    # Find video path from report metadata
    video_path = report_dict.get("meta", {}).get("video_path")
    if not video_path:
        # Try to infer from report_id (convention: {video_stem}_continuous_report)
        stem = report_id.replace("_continuous_report", "")
        raw_dir = _BASE_DIR / "data" / "raw"
        candidates = list(raw_dir.glob(f"{stem}.*"))
        if candidates:
            video_path = str(candidates[0])

    if not video_path or not Path(video_path).exists():
        raise HTTPException(
            status_code=404,
            detail="Source video not found. Cannot generate clip.",
        )

    # Generate clip
    try:
        from ml.clip_overlay import ClipOverlayGenerator
        gen = ClipOverlayGenerator()

        event_info = {}
        if event_type == "touch":
            event_info = gen._extract_touch_info(event)
        else:
            event_info = gen._extract_exchange_info(event)

        gen.generate_clip(
            video_path, start_frame, end_frame, str(clip_path), event_info,
        )
    except Exception as e:
        _logger.error("Clip generation failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Clip generation failed: {e}")

    return StreamingResponse(
        open(str(clip_path), "rb"),
        media_type="video/mp4",
        headers={"Content-Disposition": f"inline; filename={clip_filename}"},
    )


@app.post("/api/analytics/clips/{report_id}/generate")
async def generate_all_clips(
    report_id: str,
    background_tasks: BackgroundTasks,
    touches_only: bool = True,
):
    """Generate all overlay clips for a report (background task)."""
    reports_dir = _BASE_DIR / "data" / "reports"
    report_path = reports_dir / f"{report_id}.json"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail=f"Report not found: {report_id}")

    with open(report_path, "r", encoding="utf-8") as f:
        report_dict = json.load(f)

    video_path = report_dict.get("meta", {}).get("video_path")
    if not video_path:
        stem = report_id.replace("_continuous_report", "")
        raw_dir = _BASE_DIR / "data" / "raw"
        candidates = list(raw_dir.glob(f"{stem}.*"))
        if candidates:
            video_path = str(candidates[0])

    if not video_path or not Path(video_path).exists():
        raise HTTPException(status_code=404, detail="Source video not found")

    clips_dir = _BASE_DIR / "data" / "clips" / "overlay" / report_id

    def _generate_clips():
        try:
            from ml.clip_overlay import ClipOverlayGenerator
            gen = ClipOverlayGenerator()
            gen.generate_clips_for_report(
                video_path, report_dict, str(clips_dir), touches_only=touches_only,
            )
            _logger.info("Batch clip generation completed for %s", report_id)
        except Exception as e:
            _logger.error("Batch clip generation failed for %s: %s", report_id, e)

    background_tasks.add_task(_generate_clips)

    return JSONResponse({
        "status": "generating",
        "report_id": report_id,
        "clips_dir": str(clips_dir),
        "touches_only": touches_only,
    })


# ------------------------------------------------------------------
# Video upload endpoints
# ------------------------------------------------------------------


@app.post("/api/analytics/upload")
async def upload_video(
    file: UploadFile = File(...),
    source_type: Optional[str] = Form(None),
    weapon: Optional[str] = Form(None),
):
    """Upload a video file for analysis."""
    uploader = VideoUploader()

    # Get file size by seeking
    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)

    error = uploader.validate_file(file.filename, file_size)
    if error:
        raise HTTPException(status_code=400, detail=error)

    video_id, storage_path = await uploader.save_upload(file, file.filename)

    _videos[video_id] = {
        "video_id": video_id,
        "filename": file.filename,
        "file_size": file_size,
        "storage_path": str(storage_path),
        "source_type": source_type,
        "weapon": weapon,
        "status": "uploaded",
        "uploaded_at": time.time(),
        "uploaded_at_display": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    # Persist to DB if available
    if _db:
        try:
            db_record = _db.insert_video({
                "filename": file.filename,
                "original_filename": file.filename,
                "file_size": file_size,
                "storage_path": str(storage_path),
                "source_type": source_type,
                "weapon": weapon,
            })
            if db_record and db_record.get("id"):
                # Use DB-generated UUID as video_id
                _videos[video_id]["db_id"] = db_record["id"]
        except Exception:
            pass  # DB failure is non-fatal

    return {
        "video_id": video_id,
        "video_path": str(storage_path),
        "filename": file.filename,
        "status": "uploaded",
    }


@app.get("/api/analytics/videos")
async def list_videos():
    """List all uploaded videos."""
    videos = sorted(_videos.values(), key=lambda v: v["uploaded_at"], reverse=True)
    return {"videos": videos}


@app.delete("/api/analytics/videos/{video_id}")
async def delete_video(video_id: str):
    """Delete an uploaded video and its files."""
    if video_id not in _videos:
        raise HTTPException(status_code=404, detail=f"Video not found: {video_id}")

    uploader = VideoUploader()
    uploader.delete_upload(video_id)

    _videos[video_id]["status"] = "deleted"

    return {"video_id": video_id, "status": "deleted"}


# ------------------------------------------------------------------
# Video source detection endpoint
# ------------------------------------------------------------------


@app.get("/api/analytics/quality-check")
async def quality_check(video_path: str, source_type: str = "coach"):
    """
    Check video quality for analysis suitability.

    Query params:
        video_path: Path to the video file.
        source_type: Video source type for profile selection.
    """
    path = Path(video_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Video not found: {video_path}")

    from ml.quality_gate import QualityGate
    qg = QualityGate()
    result = qg.assess(video_path, source_type)

    if not result.can_analyze:
        return JSONResponse(
            status_code=422,
            content={
                "can_analyze": False,
                "quality": result.to_dict(),
                "recommendations": result.recommendations,
            },
        )

    return result.to_dict()


@app.get("/api/analytics/filming-guide")
async def filming_guide(
    source_type: str = "coach",
    weapon: Optional[str] = None,
    language: str = "ko",
):
    """
    Get filming recommendations for recording fencing matches.

    Query params:
        source_type: "coach", "parent", or "player"
        weapon: Optional weapon type (foil/epee/sabre)
        language: "ko" or "en"
    """
    from app.filming_guide import get_filming_guide
    guide = get_filming_guide(source_type, weapon, language)
    return guide.to_dict()


@app.get("/api/analytics/detect-source")
async def detect_source(video_path: str):
    """
    Detect video source type without running full analysis.

    Query params:
        video_path: Path to the video file.
    """
    path = Path(video_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Video not found: {video_path}")

    from ml.video_source_detector import VideoSourceDetector
    detector = VideoSourceDetector()
    assessment = detector.detect(video_path)
    return assessment.to_dict()


# ------------------------------------------------------------------
# TV Broadcast analysis endpoints
# ------------------------------------------------------------------


@app.post("/api/analytics/analyze-broadcast")
async def start_broadcast_analysis(
    req: AnalyzeRequest,
    background_tasks: BackgroundTasks,
):
    """
    Start async TV broadcast analysis for technique extraction.

    Creates a job and runs broadcast analysis in the background.
    Poll GET /api/analytics/jobs/{job_id} for status.
    """
    # Resolve video path from video_id or video_path
    resolved_path = req.video_path
    if req.video_id:
        vid = _videos.get(req.video_id)
        if vid is None:
            raise HTTPException(status_code=404, detail=f"Uploaded video not found: {req.video_id}")
        resolved_path = vid["storage_path"]
    if not resolved_path:
        raise HTTPException(status_code=400, detail="Either video_path or video_id is required")

    video = Path(resolved_path)
    if not video.exists():
        raise HTTPException(status_code=404, detail=f"Video not found: {resolved_path}")

    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {
        "status": "queued",
        "progress_pct": 0.0,
        "video_path": resolved_path,
        "video_id": req.video_id,
        "weapon": req.weapon,
        "started_at": time.time(),
        "result": None,
        "error": None,
        "job_type": "broadcast",
    }

    background_tasks.add_task(
        _run_broadcast_analysis,
        job_id,
        resolved_path,
        req.enable_pose,
        req.enable_action,
    )

    return {"job_id": job_id, "status": "queued", "job_type": "broadcast"}


# ------------------------------------------------------------------
# Background analysis runner
# ------------------------------------------------------------------


def _persist_report(job_id: str, report_dict: dict) -> None:
    """Save a completed report to data/reports/ for persistence across restarts."""
    reports_dir = _BASE_DIR / "data" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"{job_id}.json"
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report_dict, f, ensure_ascii=False, indent=2)
        _logger.info("Report persisted to %s", report_path)
    except Exception as e:
        _logger.warning("Failed to persist report %s: %s", job_id, e)


def _generate_mock_result(
    job_id: str,
    video_path: str,
    weapon: Optional[str],
    source_type: Optional[str],
):
    """Generate mock analysis result when ML models are unavailable."""
    import time as _time

    # Simulate processing with progress updates
    for pct in [20.0, 40.0, 60.0, 80.0]:
        _jobs[job_id]["progress_pct"] = pct
        _time.sleep(0.5)  # Brief delay to simulate work

    report_dict = generate_demo_report()
    # Override with actual video info
    report_dict["summary"]["video_path"] = video_path
    if weapon:
        report_dict["summary"]["weapon"] = weapon
    if source_type:
        report_dict["meta"]["source_type"] = source_type

    _jobs[job_id]["progress_pct"] = 100.0
    _jobs[job_id]["status"] = "completed"
    _jobs[job_id]["result"] = report_dict
    _jobs[job_id]["mock_mode"] = True


def _run_analysis(
    job_id: str,
    video_path: str,
    weapon: Optional[str],
    enable_pose: bool,
    enable_action: bool,
    rois: Optional[Dict[str, list]],
    source_type: Optional[str] = None,
    member_id: str = "default",
):
    """Run the full analysis pipeline in background."""
    try:
        # Credit check before processing
        job_type = _jobs[job_id].get("job_type", "standard")
        allowed, reason = _credit_manager.can_analyze(member_id, job_type)
        if not allowed:
            _jobs[job_id]["status"] = "failed"
            _jobs[job_id]["error"] = "insufficient_credits"
            if _db:
                _db.update_job(job_id, status="failed", error="insufficient_credits")
            return

        _jobs[job_id]["status"] = "processing"
        _jobs[job_id]["progress_pct"] = 10.0
        if _db:
            _db.update_job(job_id, status="processing", progress_pct=10.0)

        try:
            from ml.integrated_analyzer import IntegratedAnalyzer
            from ml.report_generator import ReportGenerator

            ia = IntegratedAnalyzer(
                enable_pose=enable_pose,
                enable_action=enable_action,
            )

            # Convert ROI dict values from lists to tuples
            roi_tuples: Dict[str, Tuple[int, int, int, int]] = {}
            if rois:
                for key, val in rois.items():
                    if isinstance(val, (list, tuple)) and len(val) == 4:
                        roi_tuples[key] = tuple(val)  # type: ignore[arg-type]

            # Auto-detect ROIs if none provided
            if not roi_tuples:
                _jobs[job_id]["progress_pct"] = 15.0
                try:
                    from analyzer.scoreboard_detector import ScoreboardDetector
                    detector = ScoreboardDetector()
                    detected = detector.detect_from_video(video_path)
                    if detected:
                        roi_tuples = detected
                        import logging
                        logging.getLogger(__name__).info(
                            "Auto-detected ROIs for job %s: %s",
                            job_id, list(roi_tuples.keys())
                        )
                except Exception as roi_err:
                    import logging
                    logging.getLogger(__name__).warning(
                        "ROI auto-detection failed for job %s: %s", job_id, roi_err
                    )

            _jobs[job_id]["progress_pct"] = 20.0
            if _db:
                _db.update_job(job_id, progress_pct=20.0)

            # Pass 1 + Pass 2 (auto-ROI integrated in IntegratedAnalyzer)
            enriched_events = ia.analyze_video(
                video_path=video_path,
                rois=roi_tuples,
            )

            _jobs[job_id]["progress_pct"] = 80.0
            if _db:
                _db.update_job(job_id, progress_pct=80.0)

            # Generate report
            gen = ReportGenerator()
            report = gen.generate(
                events=enriched_events,
                video_path=video_path,
                weapon=weapon,
                source_type=source_type,
            )

            report_dict = report.to_dict()
            _jobs[job_id]["progress_pct"] = 100.0
            _jobs[job_id]["status"] = "completed"
            _jobs[job_id]["result"] = report_dict

            # Persist to disk + DB
            _persist_report(job_id, report_dict)
            if _db:
                _db.update_job(job_id, status="completed", progress_pct=100.0)
                _db.save_result(
                    job_id=job_id,
                    result_json={"events": [e.to_dict() for e in enriched_events]},
                    report_json=report_dict,
                )

        except (ImportError, Exception) as ml_err:
            # ML models not available — fall back to mock mode
            import logging
            logging.getLogger(__name__).warning(
                "ML models unavailable, using mock mode: %s", ml_err
            )
            _generate_mock_result(job_id, video_path, weapon, source_type)

        # Deduct credit on successful completion
        if _jobs[job_id]["status"] == "completed":
            _credit_manager.deduct_credit(member_id, job_type, reference_id=job_id)
            # Persist mock/fallback results too
            if _jobs[job_id]["result"]:
                _persist_report(job_id, _jobs[job_id]["result"])

    except Exception as exc:
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = str(exc)
        if _db:
            _db.update_job(job_id, status="failed", error=str(exc))


def _run_broadcast_analysis(
    job_id: str,
    video_path: str,
    enable_pose: bool,
    enable_action: bool,
):
    """Run TV broadcast analysis pipeline in background."""
    try:
        _jobs[job_id]["status"] = "processing"
        _jobs[job_id]["progress_pct"] = 10.0

        try:
            from ml.tv_analyzer import TVBroadcastAnalyzer

            analyzer = TVBroadcastAnalyzer(
                enable_pose=enable_pose,
                enable_action=enable_action,
            )

            _jobs[job_id]["progress_pct"] = 20.0

            result = analyzer.analyze_broadcast(video_path)

            report_dict_ml = result.to_dict()
            _jobs[job_id]["progress_pct"] = 100.0
            _jobs[job_id]["status"] = "completed"
            _jobs[job_id]["result"] = report_dict_ml
            _persist_report(job_id, report_dict_ml)

        except (ImportError, Exception) as ml_err:
            # ML models not available — try TVOverlayOCR fallback
            import logging
            logging.getLogger(__name__).warning(
                "ML models unavailable for broadcast, trying OCR fallback: %s", ml_err
            )
            try:
                import os
                import cv2
                from analyzer.tv_overlay_ocr import TVOverlayOCR, TVScoreTracker
                from app.tv_report_converter import tv_ocr_to_match_report
                from app.metadata_parser import parse_fencing_metadata

                # Parse metadata from filename
                filename = os.path.basename(video_path)
                metadata = parse_fencing_metadata(filename)
                weapon = _jobs[job_id].get("weapon") or metadata.get("weapon", "unknown")
                expected_final = metadata.get("expected_final_score")

                ocr = TVOverlayOCR()
                tracker = TVScoreTracker()
                cap = cv2.VideoCapture(video_path)
                fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
                total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                sample_interval = 5  # OCR every 5 frames

                left_name = right_name = None
                frame_num = 0
                t_start = time.time()

                while cap.isOpened():
                    ret, frame = cap.read()
                    if not ret:
                        break
                    if frame_num % sample_interval == 0:
                        data = ocr.read_overlay(frame)
                        if data:
                            tracker.update(frame_num, data, fps)
                            if data.left_name and not left_name:
                                left_name = data.left_name
                            if data.right_name and not right_name:
                                right_name = data.right_name
                    frame_num += 1
                    if total > 0:
                        _jobs[job_id]["progress_pct"] = 20 + 60 * (frame_num / total)
                cap.release()

                events = tracker.get_all_events()
                clock_events = tracker.get_clock_events()
                summary = tracker.get_match_summary()
                analysis_time = time.time() - t_start

                report_dict = tv_ocr_to_match_report(
                    events=events,
                    summary=summary,
                    left_name=left_name,
                    right_name=right_name,
                    video_path=video_path,
                    analysis_time_sec=analysis_time,
                    total_frames=frame_num,
                    fps=fps,
                    expected_final_score=expected_final,
                )

                # Inject metadata into report
                report_dict["summary"]["weapon"] = weapon
                report_dict["summary"]["gender"] = metadata.get("gender", "unknown")
                report_dict["summary"]["age_group"] = metadata.get("age_group", "unknown")
                if metadata.get("bout_type", "unknown") != "unknown":
                    report_dict["summary"]["bout_type"] = metadata["bout_type"]

                # Store clock events (Allez/Halt proxy)
                if clock_events:
                    report_dict["clock_events"] = clock_events

                _jobs[job_id]["progress_pct"] = 100.0
                _jobs[job_id]["status"] = "completed"
                _jobs[job_id]["result"] = report_dict
                _persist_report(job_id, report_dict)
                logging.getLogger(__name__).info(
                    "OCR fallback completed for job %s: %d touches detected",
                    job_id, summary.get("total_touches", 0),
                )

            except Exception as ocr_err:
                # OCR also failed — fall back to mock mode
                logging.getLogger(__name__).warning(
                    "OCR fallback also failed, using mock mode: %s", ocr_err
                )
                _generate_mock_result(
                    job_id, video_path,
                    weapon=_jobs[job_id].get("weapon"),
                    source_type="tv_broadcast",
                )
                if _jobs[job_id]["status"] == "completed" and _jobs[job_id]["result"]:
                    _persist_report(job_id, _jobs[job_id]["result"])

    except Exception as exc:
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = str(exc)


# ------------------------------------------------------------------
# Credit / Subscription endpoints
# ------------------------------------------------------------------


@app.get("/api/analytics/credits")
async def get_credits(member_id: str = "default"):
    """Check credit balance."""
    return _credit_manager.get_subscription_info(member_id)


@app.post("/api/analytics/credits/purchase")
async def purchase_credits(member_id: str = "default", amount: int = 1):
    """Purchase credits (placeholder - no real payment)."""
    if amount < 1 or amount > 100:
        raise HTTPException(400, "Amount must be 1-100")
    new_balance = _credit_manager.add_credits(member_id, amount, "purchase")
    return {"member_id": member_id, "credits_added": amount, "new_balance": new_balance}


@app.get("/api/analytics/subscription")
async def get_subscription(member_id: str = "default"):
    """Get subscription status."""
    return _credit_manager.get_subscription_info(member_id)


@app.post("/api/analytics/subscription")
async def update_subscription(member_id: str = "default", tier: str = "free"):
    """Change subscription tier (placeholder)."""
    try:
        tier_enum = SubscriptionTier(tier)
    except ValueError:
        raise HTTPException(400, f"Invalid tier: {tier}. Options: free, basic, pro, team")
    _credit_manager.set_tier(member_id, tier_enum)
    return _credit_manager.get_subscription_info(member_id)
