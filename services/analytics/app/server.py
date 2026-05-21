"""
FastAPI server for FencingMind Analytics service.

analytics.fencingmind.ai — AI-powered fencing match video analysis.
Port: 76
"""

import uuid
import time
from pathlib import Path
from typing import Optional, Dict, Tuple

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel


app = FastAPI(
    title="FencingMind Analytics",
    description="AI-powered fencing match video analysis",
    version="0.2.0",
)


# ------------------------------------------------------------------
# In-memory job store (Phase 3: migrate to analytics_analysis_jobs DB)
# ------------------------------------------------------------------

_jobs: Dict[str, dict] = {}


# ------------------------------------------------------------------
# Request / Response models
# ------------------------------------------------------------------


class AnalyzeRequest(BaseModel):
    """Request body for video analysis."""
    video_path: str
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

    Creates a job and runs analysis in the background.
    Poll GET /api/analytics/jobs/{job_id} for status.
    """
    video = Path(req.video_path)
    if not video.exists():
        raise HTTPException(status_code=404, detail=f"Video not found: {req.video_path}")

    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {
        "status": "queued",
        "progress_pct": 0.0,
        "video_path": req.video_path,
        "weapon": req.weapon,
        "started_at": time.time(),
        "result": None,
        "error": None,
    }

    background_tasks.add_task(
        _run_analysis,
        job_id,
        req.video_path,
        req.weapon,
        req.enable_pose,
        req.enable_action,
        req.rois,
        req.source_type,
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
        format: "json" (default) or "html" (Phase 3)
    """
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    if job["status"] != "completed" or job["result"] is None:
        return JSONResponse(
            status_code=202,
            content={"job_id": job_id, "status": job["status"]},
        )

    if format == "html":
        # Phase 3: Jinja2 template rendering
        raise HTTPException(status_code=501, detail="HTML report not yet implemented")

    return job["result"]


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
    video = Path(req.video_path)
    if not video.exists():
        raise HTTPException(status_code=404, detail=f"Video not found: {req.video_path}")

    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {
        "status": "queued",
        "progress_pct": 0.0,
        "video_path": req.video_path,
        "weapon": req.weapon,
        "started_at": time.time(),
        "result": None,
        "error": None,
        "job_type": "broadcast",
    }

    background_tasks.add_task(
        _run_broadcast_analysis,
        job_id,
        req.video_path,
        req.enable_pose,
        req.enable_action,
    )

    return {"job_id": job_id, "status": "queued", "job_type": "broadcast"}


# ------------------------------------------------------------------
# Background analysis runner
# ------------------------------------------------------------------


def _run_analysis(
    job_id: str,
    video_path: str,
    weapon: Optional[str],
    enable_pose: bool,
    enable_action: bool,
    rois: Optional[Dict[str, list]],
    source_type: Optional[str] = None,
):
    """Run the full analysis pipeline in background."""
    try:
        _jobs[job_id]["status"] = "processing"
        _jobs[job_id]["progress_pct"] = 10.0

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

        _jobs[job_id]["progress_pct"] = 20.0

        # Pass 1 + Pass 2
        enriched_events = ia.analyze_video(
            video_path=video_path,
            rois=roi_tuples,
        )

        _jobs[job_id]["progress_pct"] = 80.0

        # Generate report
        gen = ReportGenerator()
        report = gen.generate(
            events=enriched_events,
            video_path=video_path,
            weapon=weapon,
            source_type=source_type,
        )

        _jobs[job_id]["progress_pct"] = 100.0
        _jobs[job_id]["status"] = "completed"
        _jobs[job_id]["result"] = report.to_dict()

    except Exception as exc:
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = str(exc)


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

    except Exception as exc:
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = str(exc)
