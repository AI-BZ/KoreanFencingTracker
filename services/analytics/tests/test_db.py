"""Tests for AnalyticsDB — Supabase data access layer."""

import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock


class MockSupabaseResponse:
    """Mock Supabase response object."""
    def __init__(self, data=None):
        self.data = data or []


class MockTable:
    """Mock Supabase table query builder."""
    def __init__(self, data=None):
        self._data = data or []
        self._response = MockSupabaseResponse(self._data)

    def insert(self, data):
        self._response = MockSupabaseResponse([{**data, "id": "test-uuid-123"}])
        return self

    def select(self, *args):
        return self

    def update(self, data):
        if self._data:
            self._response = MockSupabaseResponse([{**self._data[0], **data}])
        else:
            self._response = MockSupabaseResponse([data])
        return self

    def eq(self, key, value):
        return self

    def neq(self, key, value):
        return self

    def order(self, key, desc=False):
        return self

    def limit(self, n):
        return self

    def execute(self):
        return self._response


class MockSupabaseClient:
    """Mock Supabase client."""
    def __init__(self, table_data=None):
        self._table_data = table_data or {}

    def table(self, name):
        data = self._table_data.get(name, [])
        return MockTable(data)


@pytest.fixture
def mock_env(monkeypatch):
    """Set required environment variables."""
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-service-key")


@pytest.fixture
def mock_db(mock_env):
    """Create an AnalyticsDB with mocked Supabase client."""
    with patch("app.db.AnalyticsDB.__init__", lambda self: None):
        from app.db import AnalyticsDB
        db = AnalyticsDB()
        db.client = MockSupabaseClient()
        return db


class TestAnalyticsDBInit:
    """Test AnalyticsDB initialization."""

    def test_missing_url_raises(self, monkeypatch):
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
        from app.db import AnalyticsDB
        with pytest.raises(RuntimeError, match="SUPABASE_URL"):
            AnalyticsDB()

    def test_missing_key_raises(self, monkeypatch):
        monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
        monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
        from app.db import AnalyticsDB
        with pytest.raises(RuntimeError, match="SUPABASE_URL"):
            AnalyticsDB()

    def test_missing_supabase_package_raises(self, mock_env):
        with patch.dict("sys.modules", {"supabase": None}):
            from app.db import AnalyticsDB
            with pytest.raises((RuntimeError, ImportError)):
                AnalyticsDB()


class TestVideoCRUD:
    """Test video CRUD operations."""

    def test_insert_video(self, mock_db):
        result = mock_db.insert_video({
            "filename": "match.mp4",
            "original_filename": "match.mp4",
            "file_size": 1024000,
            "source_type": "coach",
            "weapon": "foil",
            "storage_path": "/data/uploads/match.mp4",
        })
        assert result is not None
        assert "id" in result

    def test_insert_video_minimal(self, mock_db):
        result = mock_db.insert_video({
            "filename": "test.mp4",
            "storage_path": "/data/test.mp4",
        })
        assert result is not None

    def test_get_video(self, mock_db):
        mock_db.client = MockSupabaseClient({
            "analytics_videos": [{"id": "vid-1", "filename": "test.mp4"}]
        })
        result = mock_db.get_video("vid-1")
        assert result is not None
        assert result["filename"] == "test.mp4"

    def test_get_video_not_found(self, mock_db):
        result = mock_db.get_video("nonexistent")
        assert result is None

    def test_list_videos(self, mock_db):
        mock_db.client = MockSupabaseClient({
            "analytics_videos": [
                {"id": "v1", "filename": "a.mp4"},
                {"id": "v2", "filename": "b.mp4"},
            ]
        })
        result = mock_db.list_videos()
        assert len(result) == 2


class TestJobsCRUD:
    """Test job CRUD operations."""

    def test_create_job(self, mock_db):
        result = mock_db.create_job(
            video_id="vid-1",
            job_type="standard",
            config={"weapon": "foil"},
        )
        assert result is not None
        assert "id" in result

    def test_get_job(self, mock_db):
        mock_db.client = MockSupabaseClient({
            "analytics_analysis_jobs": [{"id": "job-1", "status": "queued"}]
        })
        result = mock_db.get_job("job-1")
        assert result is not None
        assert result["status"] == "queued"

    def test_get_job_not_found(self, mock_db):
        result = mock_db.get_job("nonexistent")
        assert result is None

    def test_update_job_status(self, mock_db):
        mock_db.client = MockSupabaseClient({
            "analytics_analysis_jobs": [{"id": "job-1", "status": "queued"}]
        })
        result = mock_db.update_job("job-1", status="processing", progress_pct=50.0)
        assert result is not None

    def test_update_job_no_fields(self, mock_db):
        result = mock_db.update_job("job-1")
        assert result is None

    def test_list_jobs(self, mock_db):
        mock_db.client = MockSupabaseClient({
            "analytics_analysis_jobs": [
                {"id": "j1", "status": "completed"},
                {"id": "j2", "status": "processing"},
            ]
        })
        result = mock_db.list_jobs()
        assert len(result) == 2


class TestResultsCRUD:
    """Test analysis results operations."""

    def test_save_result(self, mock_db):
        result = mock_db.save_result(
            job_id="job-1",
            result_json={"events": []},
            report_json={"summary": {"final_score": "5-3"}},
        )
        assert result is not None
        assert "id" in result

    def test_get_result(self, mock_db):
        mock_db.client = MockSupabaseClient({
            "analytics_analysis_results": [{
                "id": "r1",
                "job_id": "job-1",
                "result_json": json.dumps({"events": []}),
                "report_json": json.dumps({"summary": {}}),
            }]
        })
        result = mock_db.get_result("job-1")
        assert result is not None
        assert "result_json" in result

    def test_get_result_not_found(self, mock_db):
        result = mock_db.get_result("nonexistent")
        assert result is None


class TestCreditsCRUD:
    """Test credits operations."""

    def test_get_credits(self, mock_db):
        mock_db.client = MockSupabaseClient({
            "analytics_credits": [{"member_id": "m1", "balance": 10}]
        })
        result = mock_db.get_credits("m1")
        assert result is not None
        assert result["balance"] == 10

    def test_get_credits_not_found(self, mock_db):
        result = mock_db.get_credits("nonexistent")
        assert result is None
