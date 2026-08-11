"""Tests for video upload handling (Phase 4)."""

import asyncio
import pytest
from pathlib import Path

from app.upload import VideoUploader, ALLOWED_EXTENSIONS, MAX_FILE_SIZE


class FakeUploadFile:
    """Mock file object with async read for testing save_upload."""

    def __init__(self, content: bytes):
        self._content = content
        self._pos = 0

    async def read(self, size=-1):
        if self._pos >= len(self._content):
            return b""
        end = self._pos + size if size > 0 else len(self._content)
        chunk = self._content[self._pos:end]
        self._pos = end
        return chunk


# ------------------------------------------------------------------
# validate_file tests
# ------------------------------------------------------------------


def test_validate_valid_file():
    """Accepted extensions (.mp4, .avi, .mov) should pass validation."""
    uploader = VideoUploader()
    assert uploader.validate_file("match.mp4", 1024) is None
    assert uploader.validate_file("match.avi", 1024) is None
    assert uploader.validate_file("match.mov", 1024) is None


def test_validate_invalid_extension():
    """Non-video extensions (.txt, .exe) should be rejected."""
    uploader = VideoUploader()
    err = uploader.validate_file("readme.txt", 1024)
    assert err is not None
    assert "Unsupported" in err

    err = uploader.validate_file("virus.exe", 1024)
    assert err is not None
    assert "Unsupported" in err


def test_validate_file_too_large():
    """Files exceeding 500MB should be rejected."""
    uploader = VideoUploader()
    err = uploader.validate_file("match.mp4", MAX_FILE_SIZE + 1)
    assert err is not None
    assert "too large" in err.lower()


def test_validate_empty_filename():
    """Empty filename (no extension) should be rejected."""
    uploader = VideoUploader()
    err = uploader.validate_file("", 1024)
    assert err is not None


# ------------------------------------------------------------------
# save / delete tests
# ------------------------------------------------------------------


def test_save_and_delete(tmp_path):
    """Save file, verify it exists, delete it, verify it's gone."""
    uploader = VideoUploader(upload_dir=tmp_path)
    content = b"fake video content for testing"
    fake_file = FakeUploadFile(content)

    video_id, storage_path = asyncio.run(
        uploader.save_upload(fake_file, "test_bout.mp4")
    )

    # File should exist with correct content
    assert storage_path.exists()
    assert storage_path.read_bytes() == content
    assert storage_path.name == "test_bout.mp4"

    # Delete should succeed
    result = uploader.delete_upload(video_id)
    assert result is True
    assert not storage_path.exists()

    # Delete again should return False (already gone)
    result = uploader.delete_upload(video_id)
    assert result is False


def test_upload_creates_directory(tmp_path):
    """Upload directory should be auto-created if it doesn't exist."""
    upload_dir = tmp_path / "new_uploads"
    assert not upload_dir.exists()

    VideoUploader(upload_dir=upload_dir)
    assert upload_dir.exists()
    assert upload_dir.is_dir()


# ------------------------------------------------------------------
# Constants tests
# ------------------------------------------------------------------


def test_allowed_extensions_complete():
    """All ALLOWED_EXTENSIONS should be video file types."""
    expected = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
    assert ALLOWED_EXTENSIONS == expected
