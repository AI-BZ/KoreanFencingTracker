"""
FastAPI server for FencingMind Analytics service.

analytics.fencingmind.ai — AI-powered fencing match analysis.
Port: 76
"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse


app = FastAPI(
    title="FencingMind Analytics",
    description="AI-powered fencing match video analysis",
    version="0.1.0",
)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "analytics", "version": "0.1.0"}


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
            "pose_estimation": False,  # Phase 2
            "action_recognition": False,  # Phase 2
        },
        "phase": 1,
    }


# Phase 2: video upload and analysis endpoints
# @app.post("/api/analytics/upload")
# @app.get("/api/analytics/results/{analysis_id}")
# @app.get("/api/analytics/report/{analysis_id}")
