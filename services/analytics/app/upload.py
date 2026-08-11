"""Video upload handling for FencingMind Analytics."""
import uuid
import shutil
from pathlib import Path
from typing import Optional

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB
ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
ALLOWED_MIME_TYPES = {"video/mp4", "video/x-msvideo", "video/quicktime", "video/x-matroska", "video/webm"}


class VideoUploader:
    """Handles video file upload, validation, and storage."""

    def __init__(self, upload_dir: Path = UPLOAD_DIR):
        self.upload_dir = upload_dir
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def validate_file(self, filename: str, file_size: int) -> Optional[str]:
        """Validate file extension and size. Returns error message or None."""
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            return f"Unsupported file type: {ext}. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        if file_size > MAX_FILE_SIZE:
            return f"File too large: {file_size / 1024 / 1024:.1f}MB. Max: 500MB"
        return None

    async def save_upload(self, file, filename: str) -> tuple[str, Path]:
        """
        Save uploaded file to disk.
        Returns (video_id, storage_path).
        """
        video_id = str(uuid.uuid4())[:8]
        dest_dir = self.upload_dir / video_id
        dest_dir.mkdir(parents=True, exist_ok=True)

        safe_name = Path(filename).name  # strip any path components
        dest_path = dest_dir / safe_name

        # Stream file to disk
        with open(dest_path, "wb") as f:
            while chunk := await file.read(1024 * 1024):  # 1MB chunks
                f.write(chunk)

        return video_id, dest_path

    def delete_upload(self, video_id: str) -> bool:
        """Delete uploaded video directory."""
        video_dir = self.upload_dir / video_id
        if video_dir.exists():
            shutil.rmtree(video_dir)
            return True
        return False
