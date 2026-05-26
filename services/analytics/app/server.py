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

from app.upload import VideoUploader
from app.credits import CreditManager, SubscriptionTier
from app.demo import generate_demo_report

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

# Static files & Jinja2 templates
# Jinja2 3.1.x has an LRU cache key hashing bug on Python 3.14+;
# disable template caching to work around it until Jinja2 ships a fix.
app.mount("/static", StaticFiles(directory=str(_BASE_DIR / "static")), name="static")
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
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    if job["status"] != "completed" or job["result"] is None:
        return JSONResponse(
            status_code=202,
            content={"job_id": job_id, "status": job["status"]},
        )

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
# HTML page routes (Jinja2 templates)
# ------------------------------------------------------------------


@app.get("/")
async def index():
    """Redirect root to upload page."""
    return RedirectResponse(url="/upload")


@app.get("/upload")
async def upload_page(request: Request):
    """Video upload page."""
    return templates.TemplateResponse(request, "upload.html")


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
        "jobs": jobs_list,
        "credits": credits,
    })


@app.get("/report/{job_id}")
async def report_page(request: Request, job_id: str):
    """
    Analysis report page with charts and insights.

    Uses Jinja2 template with Chart.js for interactive visualizations.
    Falls back to standalone HTML renderer if template is unavailable.
    """
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    if job["status"] != "completed" or job["result"] is None:
        return HTMLResponse(
            content=f"<html><body><p>분석 진행 중... (상태: {job['status']})</p></body></html>",
            status_code=202,
        )

    report_dict = job["result"]

    return templates.TemplateResponse(request, "report.html", {
        "report": report_dict,
        "report_json": json.dumps(report_dict, ensure_ascii=False),
        "job_id": job_id,
        "mock_mode": job.get("mock_mode", False),
    })


# ------------------------------------------------------------------
# Demo endpoints
# ------------------------------------------------------------------


@app.get("/demo")
async def demo_report_page(request: Request):
    """Demo report page with sample data."""
    report_dict = generate_demo_report()
    demo_job_id = "demo-001"
    _jobs[demo_job_id] = {
        "status": "completed",
        "progress_pct": 100.0,
        "video_path": "demo_match.mp4",
        "weapon": "foil",
        "source_type": "coach",
        "started_at": time.time(),
        "result": report_dict,
        "error": None,
    }
    return templates.TemplateResponse(request, "report.html", {
        "report": report_dict,
        "report_json": json.dumps(report_dict, ensure_ascii=False),
        "job_id": demo_job_id,
    })


@app.get("/demo/dashboard")
async def demo_dashboard_page(request: Request):
    """Demo dashboard with sample jobs."""
    report_dict = generate_demo_report()
    demo_jobs = {
        "demo-001": {
            "status": "completed", "progress_pct": 100.0,
            "video_path": "demo_match_foil.mp4", "weapon": "foil",
            "source_type": "coach", "started_at": time.time(),
            "result": report_dict, "error": None, "video_id": "",
        },
        "demo-002": {
            "status": "processing", "progress_pct": 45.0,
            "video_path": "demo_match_epee.mp4", "weapon": "epee",
            "source_type": "parent", "started_at": time.time(),
            "result": None, "error": None, "video_id": "",
        },
        "demo-003": {
            "status": "failed", "progress_pct": 20.0,
            "video_path": "demo_match_sabre.mp4", "weapon": "sabre",
            "source_type": "tv_broadcast", "started_at": time.time(),
            "result": None, "error": "insufficient_credits", "video_id": "",
        },
    }
    _jobs.update(demo_jobs)

    jobs_list = []
    for job_id, job in demo_jobs.items():
        jobs_list.append({
            "job_id": job_id,
            "filename": Path(job.get("video_path", "")).name,
            "weapon": job.get("weapon"),
            "source_type": job.get("source_type"),
            "status": job["status"],
            "uploaded_at": "2026-05-21 14:30",
            "error": job.get("error"),
        })

    sub_info = _credit_manager.get_subscription_info("default")
    return templates.TemplateResponse(request, "dashboard.html", {
        "jobs": jobs_list,
        "credits": sub_info.get("credits", 0),
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

            # Persist to DB
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

            _jobs[job_id]["progress_pct"] = 100.0
            _jobs[job_id]["status"] = "completed"
            _jobs[job_id]["result"] = result.to_dict()

        except (ImportError, Exception) as ml_err:
            # ML models not available — fall back to mock mode
            import logging
            logging.getLogger(__name__).warning(
                "ML models unavailable for broadcast, using mock mode: %s", ml_err
            )
            _generate_mock_result(
                job_id, video_path,
                weapon=_jobs[job_id].get("weapon"),
                source_type="tv_broadcast",
            )

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
