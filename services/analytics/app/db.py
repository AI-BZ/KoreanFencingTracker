"""
Supabase data access layer for the Analytics service.

Provides CRUD operations for analytics_videos, analytics_analysis_jobs,
analytics_analysis_results tables. Falls back gracefully if Supabase
is not configured.
"""

import os
import json
import logging
from datetime import datetime
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)


class AnalyticsDB:
    """
    Data access layer for Analytics service using Supabase.

    Uses service_role_key to bypass RLS during demo period.
    All methods return dicts for easy JSON serialization.
    """

    def __init__(self):
        """
        Initialize Supabase client.

        Requires SUPABASE_URL and SUPABASE_SERVICE_KEY environment variables.
        Raises RuntimeError if not configured.
        """
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_KEY")

        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set for DB access"
            )

        try:
            from supabase import create_client
            self.client = create_client(url, key)
        except ImportError:
            raise RuntimeError("supabase-py package not installed")

    # ------------------------------------------------------------------
    # Videos CRUD
    # ------------------------------------------------------------------

    def insert_video(self, data: dict) -> dict:
        """
        Insert a new video record.

        Args:
            data: Dict with keys: filename, original_filename, file_size,
                  source_type, weapon, storage_path, member_id (optional)

        Returns:
            Inserted record dict.
        """
        insert_data = {
            "filename": data["filename"],
            "original_filename": data.get("original_filename", data["filename"]),
            "file_size": data.get("file_size"),
            "source_type": data.get("source_type"),
            "weapon": data.get("weapon"),
            "storage_path": data["storage_path"],
            "status": "uploaded",
        }
        if data.get("member_id"):
            insert_data["member_id"] = data["member_id"]

        result = (
            self.client.table("analytics_videos")
            .insert(insert_data)
            .execute()
        )
        return result.data[0] if result.data else {}

    def get_video(self, video_id: str) -> Optional[dict]:
        """Get a video record by ID."""
        result = (
            self.client.table("analytics_videos")
            .select("*")
            .eq("id", video_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def list_videos(self, limit: int = 50) -> List[dict]:
        """List videos ordered by upload time (most recent first)."""
        result = (
            self.client.table("analytics_videos")
            .select("*")
            .neq("status", "deleted")
            .order("uploaded_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []

    def update_video_status(self, video_id: str, status: str) -> Optional[dict]:
        """Update video status."""
        result = (
            self.client.table("analytics_videos")
            .update({"status": status})
            .eq("id", video_id)
            .execute()
        )
        return result.data[0] if result.data else None

    # ------------------------------------------------------------------
    # Jobs CRUD
    # ------------------------------------------------------------------

    def create_job(
        self,
        video_id: str,
        job_type: str = "standard",
        config: Optional[dict] = None,
    ) -> dict:
        """
        Create a new analysis job.

        Args:
            video_id: UUID of the video to analyze.
            job_type: "standard", "broadcast", or "quick".
            config: Optional job configuration (weapon, source_type, etc.)

        Returns:
            Created job record dict.
        """
        insert_data = {
            "video_id": video_id,
            "job_type": job_type,
            "status": "queued",
            "progress_pct": 0.0,
            "config": json.dumps(config or {}),
        }
        result = (
            self.client.table("analytics_analysis_jobs")
            .insert(insert_data)
            .execute()
        )
        return result.data[0] if result.data else {}

    def get_job(self, job_id: str) -> Optional[dict]:
        """Get a job record by ID."""
        result = (
            self.client.table("analytics_analysis_jobs")
            .select("*")
            .eq("id", job_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def update_job(self, job_id: str, **kwargs) -> Optional[dict]:
        """
        Update a job record.

        Keyword args can include: status, progress_pct, error, started_at, completed_at
        """
        update_data = {}
        for key in ("status", "progress_pct", "error", "started_at", "completed_at"):
            if key in kwargs:
                update_data[key] = kwargs[key]

        if not update_data:
            return None

        result = (
            self.client.table("analytics_analysis_jobs")
            .update(update_data)
            .eq("id", job_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def list_jobs(self, limit: int = 50) -> List[dict]:
        """List jobs ordered by creation time (most recent first)."""
        result = (
            self.client.table("analytics_analysis_jobs")
            .select("*, analytics_videos(filename, weapon, source_type)")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []

    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------

    def save_result(
        self,
        job_id: str,
        result_json: dict,
        report_json: Optional[dict] = None,
    ) -> dict:
        """
        Save analysis result.

        Args:
            job_id: UUID of the completed job.
            result_json: Raw analysis result (EnrichedMatchEvent[]).
            report_json: Formatted MatchReport JSON.

        Returns:
            Created result record dict.
        """
        insert_data = {
            "job_id": job_id,
            "result_json": json.dumps(result_json, ensure_ascii=False),
            "report_json": json.dumps(report_json, ensure_ascii=False) if report_json else None,
        }
        result = (
            self.client.table("analytics_analysis_results")
            .insert(insert_data)
            .execute()
        )
        return result.data[0] if result.data else {}

    def get_result(self, job_id: str) -> Optional[dict]:
        """Get analysis result by job ID."""
        result = (
            self.client.table("analytics_analysis_results")
            .select("*")
            .eq("job_id", job_id)
            .execute()
        )
        if not result.data:
            return None
        record = result.data[0]
        # Parse JSON strings back to dicts
        if isinstance(record.get("result_json"), str):
            record["result_json"] = json.loads(record["result_json"])
        if isinstance(record.get("report_json"), str):
            record["report_json"] = json.loads(record["report_json"])
        return record

    # ------------------------------------------------------------------
    # Credits (informational only - actual logic stays in CreditManager)
    # ------------------------------------------------------------------

    def get_credits(self, member_id: str) -> Optional[dict]:
        """Get credit balance for a member."""
        result = (
            self.client.table("analytics_credits")
            .select("*")
            .eq("member_id", member_id)
            .execute()
        )
        return result.data[0] if result.data else None
