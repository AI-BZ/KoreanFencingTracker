"""
FastAPI server for FencingMind Analytics service.

analytics.fencingmind.ai — AI-powered fencing match video analysis.
Port: 76
"""

import json
import os
import sys
import threading
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
from app.report_renderer import prepare_report_view, build_timeline
from app.sharing import (
    find_report_by_token,
    is_accessible_at,
    is_private_path,
    is_unlisted,
    iter_report_files,
    redacted_for_client,
    resolve_keypoints_path,
    resolve_report_path,
)

_logger = logging.getLogger(__name__)
_BASE_DIR = Path(__file__).resolve().parent.parent


def _reports_dir() -> Path:
    """Root of the saved-report tree — public files plus the private subdir."""
    return _BASE_DIR / "data" / "reports"


def _load_report_located(report_id: str) -> Tuple[Optional[dict], bool]:
    """Load a saved report by id and say whether it came from the private tree.

    Every route that reads a report from disk goes through here, so none of them
    can miss the private directory (and serve a 404 for a report that exists) or
    reach it by a path the id could have escaped.

    The location travels with the report because the access rule needs both.
    A report written into data/reports/private is unlisted by virtue of living
    there, before anyone runs the share command — and a route holding only the
    parsed dict cannot see that. Returning the two together means no gate can
    accidentally decide from ``meta`` alone.

    An id that is unsafe, absent or unparseable all come back as
    ``(None, False)``: callers turn all three into the same 404, so a corrupt
    file cannot be told apart from a missing one by probing.
    """
    path = resolve_report_path(_reports_dir(), report_id)
    if path is None:
        return None, False
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None, False
    if not isinstance(data, dict):
        return None, False
    return data, is_private_path(_reports_dir(), path)


def _load_report(report_id: str) -> Optional[dict]:
    """Load a saved report by id, discarding where it was found.

    For callers that only want the content and do no access check of their own.
    A gate must not use this: without the location it cannot tell a freshly
    generated private report from a public one.
    """
    return _load_report_located(report_id)[0]


def _has_keypoints(report_id: str) -> bool:
    """Whether a joint-keypoint sidecar exists for this report id.

    The template uses this to decide whether to offer the skeleton toggle at
    all: a report analysed before sidecars existed has none, and a button that
    404s is worse than no button.
    """
    return resolve_keypoints_path(_reports_dir(), report_id) is not None


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

# Raw source videos.
#
# data/raw holds broadcast footage downloaded from third parties (USA Fencing
# YouTube uploads among them). Re-hosting and serving those publicly copies and
# publicly distributes someone else's work, and some of the bouts are junior and
# cadet events, so the fencers can be minors. The mount is therefore off unless
# SERVE_RAW_VIDEOS is explicitly turned on for local work.
#
# With it off, report pages fall back to linking the original YouTube video, a
# path the template already supports, so the analysis itself still renders.
_raw_video_dir = _BASE_DIR / "data" / "raw"
SERVE_RAW_VIDEOS = os.getenv("SERVE_RAW_VIDEOS", "").strip().lower() in ("1", "true", "yes")

# data/raw/own is by convention the footage we filmed ourselves, so there is no
# third party whose work would be re-hosted by serving it. That is the whole of
# the gate's rationale, so this mount carries no gate. It must be registered
# first: Starlette matches mounts in registration order, and the bare /videos
# mount below would otherwise swallow the /videos/own prefix.
_own_video_dir = _raw_video_dir / "own"
if _own_video_dir.exists():
    app.mount("/videos/own", StaticFiles(directory=str(_own_video_dir)), name="videos_own")

if SERVE_RAW_VIDEOS and _raw_video_dir.exists():
    app.mount("/videos", StaticFiles(directory=str(_raw_video_dir)), name="videos")
    _logger.warning(
        "SERVE_RAW_VIDEOS is on: /videos serves third-party footage publicly. "
        "Keep this off in production."
    )
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
async def get_job_status(job_id: str, token: Optional[str] = None):
    """Check analysis job status."""
    job = _jobs.get(job_id)
    if job is None:
        # Check if report exists on disk (completed before restart). The bare
        # 200/404 difference is itself a signal that an unlisted report exists,
        # so this branch answers to the same token as the page does.
        report_dict, in_private = _load_report_located(job_id)
        if report_dict is not None and is_accessible_at(report_dict, token, in_private=in_private):
            return JobStatus(job_id=job_id, status="completed", progress_pct=100.0)
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    return JobStatus(
        job_id=job_id,
        status=job["status"],
        progress_pct=job["progress_pct"],
        error=job.get("error"),
    )


@app.get("/api/analytics/results/{job_id}")
async def get_results(job_id: str, token: Optional[str] = None):
    """
    Get full analysis results as MatchReport JSON.

    Returns 202 if analysis is still in progress.
    """
    job = _jobs.get(job_id)
    if job is None:
        # Job not in memory — check persisted reports on disk. This hands back
        # the whole report, so it is the most valuable door of the lot: it has
        # to be as gated as the page, and the payload has to lose the share
        # token before it goes out or one guessed id yields the key to the rest.
        report_dict, in_private = _load_report_located(job_id)
        if report_dict is not None and is_accessible_at(report_dict, token, in_private=in_private):
            return redacted_for_client(report_dict)
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
async def get_report(job_id: str, format: str = "json", token: Optional[str] = None):
    """
    Get formatted analysis report.

    Query params:
        format: "json" (default), "html", or "pdf"
    """
    job = _jobs.get(job_id)
    if job is None:
        # Job not in memory — check persisted reports on disk. Same rule as the
        # page: an unlisted report is unreachable by id, and a wrong token is
        # indistinguishable from a report that was never there.
        report_dict, in_private = _load_report_located(job_id)
        if report_dict is None or not is_accessible_at(report_dict, token, in_private=in_private):
            raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    elif job["status"] != "completed" or job["result"] is None:
        return JSONResponse(
            status_code=202,
            content={"job_id": job_id, "status": job["status"]},
        )
    else:
        report_dict = job["result"]

    # Every format below leaves the process, so the token comes off here rather
    # than in each branch — an HTML or PDF export is just as readable as JSON.
    payload = redacted_for_client(report_dict)

    if format == "html":
        from app.report_renderer import ReportRenderer
        renderer = ReportRenderer()
        html = renderer.render_html(payload, standalone=True)
        return HTMLResponse(content=html)

    if format == "pdf":
        from app.pdf_exporter import PDFExporter
        try:
            exporter = PDFExporter()
            pdf_bytes = exporter.export(payload)
        except RuntimeError as exc:
            raise HTTPException(status_code=501, detail=str(exc))
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="report-{job_id}.pdf"'},
        )

    return payload


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


def _video_version(video_filename: Optional[str]) -> int:
    """Cache-busting version for a served video: the file's mtime.

    The CDN caches /videos/* aggressively, and a re-encode replaces the file
    under the same name — a 10-bit copy cached before one such swap kept
    breaking phone playback. Keying the URL on mtime makes every replacement
    a fresh cache entry without anyone remembering to bump a constant.
    """
    if not video_filename:
        return 0
    try:
        return int((_raw_video_dir / video_filename).stat().st_mtime)
    except OSError:
        return 0


def _own_video_filename(video_path: str) -> Optional[str]:
    """Return ``own/<name>`` when ``video_path`` points into data/raw/own.

    Both report routes need this and neither may gate it on SERVE_RAW_VIDEOS —
    /videos/own is mounted unconditionally, so our own footage plays whether or
    not the third-party gate is open.

    The comparison is on resolved paths rather than the raw string, so a
    ``../`` segment cannot escape the directory while still looking like it
    starts inside it. ``resolve()`` stays non-strict because a report may name a
    file that is not on this machine, and that should read as "not ours",
    not raise.

    The file has to actually be there, for the same reason the gated branch
    below checks: data/raw is gitignored, so a report can outlive its video, and
    naming one anyway renders a dead player instead of falling through.
    """
    if not video_path:
        return None
    try:
        resolved = Path(video_path).resolve()
        own_dir = _own_video_dir.resolve()
    except OSError:
        return None
    if resolved.parent != own_dir or not resolved.is_file():
        return None
    return f"own/{resolved.name}"


@app.get("/report/{job_id}")
async def report_page(request: Request, job_id: str, token: Optional[str] = None):
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
        report_dict, in_private = _load_report_located(job_id)
        # An unlisted report has to be as unreachable by id here as it is on
        # /report/saved — same detail string, so a bad token is indistinguishable
        # from a report that was never there.
        if report_dict is None or not is_accessible_at(report_dict, token, in_private=in_private):
            raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
        mock_mode = False

    # Enrich with aggregated stats if needed
    _enrich_report_stats(report_dict)
    prepare_report_view(report_dict)

    # Resolve video for playback. The file being on disk is not enough: unless
    # SERVE_RAW_VIDEOS is on there is no /videos mount to play it from, and
    # pointing at it anyway renders a dead player instead of the YouTube link.
    video_path = report_dict.get("meta", {}).get("video_path") or ""
    video_filename = _own_video_filename(video_path)
    if not video_filename and SERVE_RAW_VIDEOS and video_path:
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
        # Embedded verbatim in the page source, so it is a serialisation like any
        # other — the page gets its token from share_token, never from here.
        "report_json": json.dumps(redacted_for_client(report_dict), ensure_ascii=False),
        "timeline": build_timeline(report_dict),
        "job_id": job_id,
        "report_id": job_id,
        "mock_mode": mock_mode,
        "video_filename": video_filename,
        "video_version": _video_version(video_filename),
        "youtube_url": youtube_url,
        "share_token": None,
        "has_keypoints": _has_keypoints(job_id),
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
    from ml.fencer_profile import compute_success_rates

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
            zone_success_rate = compute_success_rates(zone_counts, zone_scored)

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
            fw_success_rate = compute_success_rates(footwork_counts, footwork_scored)

            preferred_fw = max(footwork_counts, key=footwork_counts.get) if footwork_counts else None

            fp["footwork_stats"] = {
                "type_distribution": footwork_counts,
                "type_success_rate": fw_success_rate,
                "preferred_footwork": preferred_fw,
            }

    return report_dict


def _render_saved_report(
    request: Request,
    report_id: str,
    report_dict: dict,
    share_token: Optional[str] = None,
):
    """Render a report loaded from data/reports/ — by id or by share token.

    /report/saved/{id} and /r/{token} differ only in how they find the report,
    so everything downstream of the lookup lives here and the two cannot drift.
    """
    # Enrich fencer_profile with aggregated distance/footwork stats
    _enrich_report_stats(report_dict)
    prepare_report_view(report_dict)

    # Resolve video filename for in-report playback. Gated on SERVE_RAW_VIDEOS
    # for the same reason as the report view above — except for our own footage,
    # which /videos/own serves regardless.
    video_path = report_dict.get("meta", {}).get("video_path") or ""
    video_filename = _own_video_filename(video_path)
    if not video_filename and SERVE_RAW_VIDEOS:
        if video_path:
            vf = Path(video_path).name
            if (_raw_video_dir / vf).exists():
                video_filename = vf
        if not video_filename:
            # Convention: {stem}_continuous_report → {stem}.mp4
            stem = report_id.replace("_continuous_report", "").replace("_report", "")
            for ext in (".mp4", ".mkv", ".webm"):
                if (_raw_video_dir / f"{stem}{ext}").exists():
                    video_filename = f"{stem}{ext}"
                    break

    # Extract YouTube URL for TV broadcast reports with no local video
    youtube_url = None
    if not video_filename:
        yt_id = extract_youtube_id(report_id)
        if yt_id:
            youtube_url = f"https://www.youtube.com/watch?v={yt_id}"

    return templates.TemplateResponse(request, "report.html", {
        **_i18n_context(request),
        "report": report_dict,
        # Redacted at serialisation time, not before: _enrich_report_stats and
        # prepare_report_view mutate report_dict in place, and the page still
        # needs the token — it gets it from share_token below, not from here.
        "report_json": json.dumps(redacted_for_client(report_dict), ensure_ascii=False),
        "timeline": build_timeline(report_dict),
        "job_id": f"saved-{report_id}",
        "report_id": report_id,
        "video_filename": video_filename,
        "video_version": _video_version(video_filename),
        "youtube_url": youtube_url,
        "share_token": share_token,
        "has_keypoints": _has_keypoints(report_id),
    })


@app.get("/report/saved/{video_id}")
async def saved_report_page(request: Request, video_id: str, token: Optional[str] = None):
    """Load a saved report JSON from data/reports/ and render it."""
    report_dict, in_private = _load_report_located(video_id)

    # An unlisted report is reachable only through its token. The detail string
    # is the same one a missing report gets, so probing ids leaks nothing.
    if report_dict is None or not is_accessible_at(report_dict, token, in_private=in_private):
        raise HTTPException(status_code=404, detail=f"Report not found: {video_id}")

    return _render_saved_report(request, video_id, report_dict, share_token=token)


@app.get("/r/{token}")
async def shared_report_page(request: Request, token: str):
    """Open an unlisted report by its share token."""
    found = find_report_by_token(_reports_dir(), token)
    if found is None:
        # Deliberately says nothing about whether the token was wrong or the
        # report is gone — either way the caller learns nothing it can probe.
        raise HTTPException(status_code=404, detail="Report not found")

    report_id, report_dict = found
    return _render_saved_report(request, report_id, report_dict, share_token=token)


@app.get("/reports")
async def list_saved_reports(request: Request):
    """List all saved report JSON files."""
    reports_dir = _reports_dir()
    if not reports_dir.exists():
        return JSONResponse({"reports": []})

    reports = []
    # include_private=False keeps the private directory out of the walk entirely:
    # its whole purpose is to hide ids, and enumerating them here would undo that
    # even though each one is filtered again below.
    for f in iter_report_files(reports_dir, include_private=False):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            # Listing an unlisted report would hand out the very id its token
            # exists to hide, so it is omitted entirely rather than redacted.
            if is_unlisted(data):
                continue
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


def _compute_touch_clip_bounds(
    touch_frame: int,
    exchanges: list,
    clock_events: list,
    fps: float = 30.0,
) -> tuple:
    """Compute clip start/end anchored on the REAL touch, not the OCR score change.

    Thin wrapper over :func:`analyzer.touch_matching.compute_touch_clip_bounds` so
    the clip window and the report's attack success/failure verdict are derived
    from the same touch→exchange match.
    """
    from analyzer.touch_matching import compute_touch_clip_bounds

    return compute_touch_clip_bounds(
        touch_frame=touch_frame,
        exchanges=exchanges,
        clock_events=clock_events,
        fps=fps,
    )


@app.get("/api/analytics/keypoints/{report_id}")
async def get_report_keypoints(report_id: str, token: Optional[str] = None):
    """Serve the joint-keypoint sidecar so the page can overlay a skeleton.

    Gated exactly like the clip endpoints, and for the same reason: the sidecar
    is the analysis in another form — every joint of two named fencers, frame by
    frame — so leaving it open would reopen an unlisted bout through a side
    door. The 404 detail is byte-identical to the one a missing report gets, so
    a wrong token cannot be told apart from an id that was never there.

    "Report exists but has no sidecar" is a different 404 on purpose: it is only
    reached once access has already been granted, so it leaks nothing, and the
    page needs to tell "not allowed" from "nothing to draw".
    """
    report_dict, in_private = _load_report_located(report_id)
    if report_dict is None or not is_accessible_at(report_dict, token, in_private=in_private):
        raise HTTPException(status_code=404, detail=f"Report not found: {report_id}")

    path = resolve_keypoints_path(_reports_dir(), report_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Keypoints not found")

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        # A corrupt sidecar reads as an absent one — same answer the page
        # already knows how to handle, rather than a 500 on a cosmetic feature.
        raise HTTPException(status_code=404, detail="Keypoints not found")

    return JSONResponse(data)


@app.get("/api/analytics/clips/{report_id}/status")
async def get_clips_status(report_id: str, token: Optional[str] = None):
    """List which overlay clips are already cached for a report.

    Lets the report page distinguish instant playback (cached) from first-time
    generation (~1 min of YOLO pose overlay) before the user clicks play.
    """
    import re as _re

    # This route never needed the report itself, but a cached-clip listing still
    # confirms an unlisted report exists, so visibility has to be checked here
    # too. A report file that is simply absent keeps its old answer — an empty
    # listing — because 404-ing on it would break every caller that polls before
    # the report is written.
    report_dict, in_private = _load_report_located(report_id)
    if report_dict is not None and not is_accessible_at(report_dict, token, in_private=in_private):
        raise HTTPException(status_code=404, detail=f"Report not found: {report_id}")

    clips_dir = _BASE_DIR / "data" / "clips" / "overlay" / report_id
    cached: Dict[str, list] = {"touch": [], "exchange": []}
    if clips_dir.exists():
        for p in clips_dir.glob("*.mp4"):
            m = _re.match(r"^(touch|exchange)_(\d+)\.mp4$", p.name)
            if m and p.stat().st_size > 1000:
                cached[m.group(1)].append(int(m.group(2)))
    cached["touch"].sort()
    cached["exchange"].sort()
    return JSONResponse({"report_id": report_id, "cached": cached})


# ------------------------------------------------------------------
# On-demand clip generation: job store
# ------------------------------------------------------------------
#
# Generating one pose-overlay clip is a full YOLO pass over its frames. Since
# the piste gate raised the pose input from 640 to 1280 that takes 2-4 minutes,
# and Cloudflare's tunnel stops waiting at ~100s — so any request that generates
# inline is a guaranteed 504 no matter what our own timeouts say. Generation
# therefore happens in a background job and every request only ever *reports*
# on one. No route below may call gen.generate_clip() itself.

_CLIP_JOBS: Dict[str, dict] = {}
_CLIP_JOBS_LOCK = threading.Lock()
_CLIP_JOB_SEQ = 0

# Concurrency cap. Clip generation is GPU/CPU bound and saturates the machine
# on its own; ten rows clicked in a row must not become ten simultaneous YOLO
# passes, which would thrash memory and make *every* clip slower than running
# them one after another. Two at a time, the rest wait their turn and are
# reported to the caller as "queued" with a position.
_CLIP_MAX_CONCURRENT = 2
_CLIP_SLOTS = threading.Semaphore(_CLIP_MAX_CONCURRENT)


def _clip_cache_path(report_id: str, event_type: str, event_number: int) -> Path:
    """The one cache location every producer and consumer of a clip agrees on."""
    clips_dir = _BASE_DIR / "data" / "clips" / "overlay" / report_id
    return clips_dir / f"{event_type}_{event_number:03d}.mp4"


def _clip_is_cached(clip_path: Path) -> bool:
    """A usable clip on disk. The size floor rejects truncated writes."""
    try:
        return clip_path.exists() and clip_path.stat().st_size > 1000
    except OSError:
        return False


def _clip_job_key(report_id: str, event_type: str, event_number: int) -> str:
    return f"{report_id}/{event_type}/{event_number}"


def _resolve_event_clip(
    report_dict: dict,
    report_id: str,
    event_type: str,
    event_number: int,
) -> Tuple[dict, str, int, int]:
    """Resolve a clip request to (event, video_path, start_frame, end_frame).

    Shared by the GET route and the /start route so the two cannot drift: they
    must resolve to the same bounds or they would write different bytes into the
    same cache path.

    The validation order is load-bearing and unchanged — event lookup, then
    frame data, then the source video — because a report with no touches has to
    keep answering "Touch #N not found" rather than "Source video not found".
    """
    if event_type == "touch":
        events = report_dict.get("touches", [])
        event = next((t for t in events if t.get("touch_number") == event_number), None)
        if event is None:
            raise HTTPException(status_code=404, detail=f"Touch #{event_number} not found")
        frame = event.get("frame")
        if frame is None:
            raise HTTPException(status_code=400, detail=f"Touch #{event_number} has no frame data")
        meta_fps = report_dict.get("meta", {}).get("fps", 30)
        start_frame, end_frame = _compute_touch_clip_bounds(
            touch_frame=frame,
            exchanges=report_dict.get("exchanges", []),
            clock_events=report_dict.get("clock_events", []),
            fps=meta_fps,
        )
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

    return event, video_path, start_frame, end_frame


def _generate_event_clip(
    report_dict: dict,
    event_type: str,
    event: dict,
    video_path: str,
    start_frame: int,
    end_frame: int,
    clip_path: Path,
) -> None:
    """Render one overlay clip. Blocking, minutes long — never call from a route.

    Byte-for-byte the generation the endpoint used to do inline, so clips made
    on demand stay interchangeable with the ones the batch endpoint writes.
    """
    from ml.clip_overlay import ClipOverlayGenerator

    # for_report reproduces the pose settings the report was analysed with:
    # a piste-gated report re-rendered with the stock estimator draws the
    # foreground referee instead of the fencers (the user caught this on a
    # real clip). Plain TV reports get the default estimator unchanged.
    if event_type == "touch":
        # Touch: smart bounds already computed, use small padding for margin
        gen = ClipOverlayGenerator.for_report(
            report_dict, pad_before=0.5, pad_after=0.0,
        )
        event_info = gen._extract_touch_info(event)
    else:
        # Exchange: start/end are already exchange boundaries, small padding
        gen = ClipOverlayGenerator.for_report(
            report_dict, pad_before=0.5, pad_after=0.3,
        )
        event_info = gen._extract_exchange_info(event)

    gen.generate_clip(
        video_path, start_frame, end_frame, str(clip_path), event_info,
    )


def _claim_clip_job(key: str) -> Tuple[str, str, bool]:
    """Join the live job for `key`, or create one. Returns (job_id, status, created).

    Lookup and insert happen under one lock because generation runs in a
    threadpool worker while requests are served from the event loop: two clicks
    on the same row really can check-then-insert concurrently, and the loser
    would start a second four-minute YOLO pass writing the same file.

    A job that already finished (ready with its file since deleted, or failed)
    is not joined — the caller is asking again precisely because it wants a
    retry.
    """
    global _CLIP_JOB_SEQ
    with _CLIP_JOBS_LOCK:
        job = _CLIP_JOBS.get(key)
        if job is not None and job["status"] in ("queued", "running"):
            return job["job_id"], job["status"], False

        _CLIP_JOB_SEQ += 1
        job = {
            "job_id": uuid.uuid4().hex,
            "seq": _CLIP_JOB_SEQ,
            "status": "queued",
            "error": None,
            "created_at": time.monotonic(),
            "started_at": None,
            "finished_at": None,
        }
        _CLIP_JOBS[key] = job
        return job["job_id"], job["status"], True


def _clip_job_snapshot(key: str) -> Optional[dict]:
    """A consistent copy of one job plus its queue position, taken under lock."""
    with _CLIP_JOBS_LOCK:
        job = _CLIP_JOBS.get(key)
        if job is None:
            return None
        snap = dict(job)
        if job["status"] == "queued":
            # Position among everything still waiting for a slot, oldest first.
            ahead = sum(
                1 for other in _CLIP_JOBS.values()
                if other["status"] == "queued" and other["seq"] < job["seq"]
            )
            snap["queue_position"] = ahead + 1
        else:
            snap["queue_position"] = None
        return snap


def _run_clip_job(
    key: str,
    job_id: str,
    report_dict: dict,
    event_type: str,
    event: dict,
    video_path: str,
    start_frame: int,
    end_frame: int,
    clip_path: Path,
) -> None:
    """Background worker: wait for a slot, generate, record the outcome."""
    # Blocks here while the machine is busy; the job stays "queued" meanwhile,
    # which is exactly what the poller should be told.
    with _CLIP_SLOTS:
        with _CLIP_JOBS_LOCK:
            job = _CLIP_JOBS.get(key)
            if job is None or job["job_id"] != job_id:
                return  # superseded by a newer job for the same clip
            job["status"] = "running"
            job["started_at"] = time.monotonic()

        try:
            _generate_event_clip(
                report_dict, event_type, event,
                video_path, start_frame, end_frame, clip_path,
            )
            if not _clip_is_cached(clip_path):
                raise RuntimeError("Clip generation produced no usable output")
        except Exception as e:
            # A half-written mp4 would pass the size check forever and be served
            # as a good clip, so a failed run must leave nothing behind.
            try:
                clip_path.unlink(missing_ok=True)
            except OSError:
                pass
            _logger.error("Clip generation failed for %s: %s", key, e)
            _finish_clip_job(key, job_id, "failed", str(e))
            return

        _finish_clip_job(key, job_id, "ready", None)


def _finish_clip_job(key: str, job_id: str, status: str, error: Optional[str]) -> None:
    with _CLIP_JOBS_LOCK:
        job = _CLIP_JOBS.get(key)
        if job is None or job["job_id"] != job_id:
            return
        job["status"] = status
        job["error"] = error
        job["finished_at"] = time.monotonic()


def _clip_job_elapsed(snap: Optional[dict]) -> float:
    if snap is None:
        return 0.0
    end = snap["finished_at"] if snap["finished_at"] is not None else time.monotonic()
    return round(max(0.0, end - snap["created_at"]), 3)


@app.post("/api/analytics/clips/{report_id}/{event_type}/{event_number}/start")
async def start_event_clip(
    report_id: str,
    event_type: str,
    event_number: int,
    background_tasks: BackgroundTasks,
    token: Optional[str] = None,
):
    """Ask for a clip to exist. Returns immediately — never generates inline.

    Gated exactly like the clip read routes, with the same 404 detail, because
    starting a job on an unlisted report both confirms it exists and spends our
    GPU on it.
    """
    if event_type not in ("touch", "exchange"):
        raise HTTPException(status_code=400, detail=f"Invalid event_type: {event_type}")

    report_dict, in_private = _load_report_located(report_id)
    if report_dict is None or not is_accessible_at(report_dict, token, in_private=in_private):
        raise HTTPException(status_code=404, detail=f"Report not found: {report_id}")

    clip_path = _clip_cache_path(report_id, event_type, event_number)
    if _clip_is_cached(clip_path):
        # Already on disk: nothing to schedule, and no job to leave lying around.
        return JSONResponse({"status": "ready", "cached": True, "job_id": None})

    # Resolve before claiming, so a bad request 404s now rather than becoming a
    # job that fails four minutes later.
    event, video_path, start_frame, end_frame = _resolve_event_clip(
        report_dict, report_id, event_type, event_number,
    )

    key = _clip_job_key(report_id, event_type, event_number)
    job_id, status, created = _claim_clip_job(key)
    if created:
        clip_path.parent.mkdir(parents=True, exist_ok=True)
        background_tasks.add_task(
            _run_clip_job,
            key, job_id, report_dict, event_type, event,
            video_path, start_frame, end_frame, clip_path,
        )

    return JSONResponse({"status": status, "cached": False, "job_id": job_id})


@app.get("/api/analytics/clips/{report_id}/{event_type}/{event_number}/status")
async def get_event_clip_status(
    report_id: str,
    event_type: str,
    event_number: int,
    token: Optional[str] = None,
):
    """Poll one clip. The file on disk outranks whatever the job store says."""
    if event_type not in ("touch", "exchange"):
        raise HTTPException(status_code=400, detail=f"Invalid event_type: {event_type}")

    report_dict, in_private = _load_report_located(report_id)
    if report_dict is None or not is_accessible_at(report_dict, token, in_private=in_private):
        raise HTTPException(status_code=404, detail=f"Report not found: {report_id}")

    clip_path = _clip_cache_path(report_id, event_type, event_number)
    key = _clip_job_key(report_id, event_type, event_number)
    snap = _clip_job_snapshot(key)

    if _clip_is_cached(clip_path):
        # Playable regardless of job state — a clip written by the batch
        # endpoint has no job at all.
        return JSONResponse({
            "status": "ready",
            "error": None,
            "elapsed_sec": _clip_job_elapsed(snap),
            "queue_position": None,
        })

    if snap is None or snap["status"] == "ready":
        # "ready" with no file means the clip was removed after the fact; from
        # the caller's side that is indistinguishable from never having asked,
        # and the right next move is the same — POST /start.
        return JSONResponse({
            "status": "idle",
            "error": None,
            "elapsed_sec": 0.0,
            "queue_position": None,
        })

    return JSONResponse({
        "status": snap["status"],
        "error": snap["error"],
        "elapsed_sec": _clip_job_elapsed(snap),
        "queue_position": snap["queue_position"],
    })


@app.get("/api/analytics/clips/{report_id}/{event_type}/{event_number}")
async def get_event_clip(
    report_id: str,
    event_type: str,
    event_number: int,
    token: Optional[str] = None,
):
    """Serve a cached pose-overlay clip, or say how to get one made.

    This route used to generate inline and reliably 504'd behind Cloudflare on
    the ~2-4 minute render. It now never generates: a cached clip streams as
    before, anything else is a 202 pointing at the job endpoints.
    """
    from fastapi.responses import StreamingResponse

    # Validate event_type
    if event_type not in ("touch", "exchange"):
        raise HTTPException(status_code=400, detail=f"Invalid event_type: {event_type}")

    # Load report
    report_dict, in_private = _load_report_located(report_id)

    # Clips are the analysis in video form, so they answer to the same rule as
    # the page — and to the same detail string.
    if report_dict is None or not is_accessible_at(report_dict, token, in_private=in_private):
        raise HTTPException(status_code=404, detail=f"Report not found: {report_id}")

    # Check cache
    clip_path = _clip_cache_path(report_id, event_type, event_number)
    clip_filename = clip_path.name

    if _clip_is_cached(clip_path):
        return StreamingResponse(
            open(str(clip_path), "rb"),
            media_type="video/mp4",
            headers={"Content-Disposition": f"inline; filename={clip_filename}"},
        )

    # Not cached. Validate the request the same way and in the same order as
    # before — a nonexistent touch is still a 404, not a job invitation.
    _resolve_event_clip(report_dict, report_id, event_type, event_number)

    base = f"/api/analytics/clips/{report_id}/{event_type}/{event_number}"
    snap = _clip_job_snapshot(_clip_job_key(report_id, event_type, event_number))
    return JSONResponse(
        status_code=202,
        content={
            "status": snap["status"] if snap else "idle",
            "detail": (
                "Clip is not generated yet. POST to the start URL, then poll the "
                "status URL until it reports \"ready\", then request this URL again."
            ),
            "start_url": f"{base}/start",
            "status_url": f"{base}/status",
        },
    )


@app.post("/api/analytics/clips/{report_id}/generate")
async def generate_all_clips(
    report_id: str,
    background_tasks: BackgroundTasks,
    touches_only: bool = True,
    token: Optional[str] = None,
):
    """Generate all overlay clips for a report (background task)."""
    report_dict, in_private = _load_report_located(report_id)

    # Same gate as the read endpoints: this one reads the report and writes the
    # clips the read endpoints then serve, so leaving it open reopens both.
    if report_dict is None or not is_accessible_at(report_dict, token, in_private=in_private):
        raise HTTPException(status_code=404, detail=f"Report not found: {report_id}")

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

            # Anchor each touch on its real-touch frame so batch clips match the
            # on-demand endpoint (same padding, same bounds → identical cache).
            meta_fps = report_dict.get("meta", {}).get("fps", 30)
            exchanges = report_dict.get("exchanges", [])
            clock_events = report_dict.get("clock_events", [])
            touch_bounds = {}
            for t in report_dict.get("touches", []):
                tn = t.get("touch_number")
                frame = t.get("frame")
                if tn is None or frame is None:
                    continue
                touch_bounds[tn] = _compute_touch_clip_bounds(
                    touch_frame=frame,
                    exchanges=exchanges,
                    clock_events=clock_events,
                    fps=meta_fps,
                )

            gen = ClipOverlayGenerator.for_report(
                report_dict, pad_before=0.5, pad_after=0.0,
            )
            gen.generate_clips_for_report(
                video_path, report_dict, str(clips_dir),
                touches_only=touches_only, touch_bounds=touch_bounds,
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
    reports_dir = _reports_dir()
    # Re-analysing a bout that has already been shared must overwrite the file
    # where it actually lives. Always writing to the public directory would
    # resurrect a private report into the committed tree and leave the private
    # copy behind as a stale second answer for the same id.
    report_path = resolve_report_path(reports_dir, job_id)
    if report_path is None:
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

                # Low-confidence gate: if OCR read no touches, the scoreboard
                # was unreadable. Keep the job "completed" so the user still
                # gets a report, but tv_ocr_to_match_report has embedded an
                # error-level "no_touches_detected" warning flagging it as
                # untrustworthy. Surface it in the logs too.
                touches_detected = summary.get("total_touches", 0)
                if touches_detected == 0:
                    logging.getLogger(__name__).warning(
                        "OCR fallback for job %s detected 0 touches — "
                        "result flagged untrustworthy (no_touches_detected)",
                        job_id,
                    )

                _jobs[job_id]["progress_pct"] = 100.0
                _jobs[job_id]["status"] = "completed"
                _jobs[job_id]["result"] = report_dict
                _persist_report(job_id, report_dict)
                logging.getLogger(__name__).info(
                    "OCR fallback completed for job %s: %d touches detected",
                    job_id, touches_detected,
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
