"""
YouTube video downloader for fencing match footage.

Ported from fencing-AI/1-download_vids.py.
Changes: pytube → yt-dlp (more reliable, actively maintained).
Phase 5a: anti-bot evasion options + bout clip extraction.
"""

import subprocess
import shutil
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass

# Chrome-like User-Agent for anti-bot evasion
_CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


@dataclass
class DownloadResult:
    url: str
    output_path: Optional[Path]
    success: bool
    error: Optional[str] = None
    title: Optional[str] = None


class VideoDownloader:
    """Downloads fencing match videos from YouTube using yt-dlp."""

    def __init__(
        self,
        output_dir: str = "data/raw",
        format: str = "mp4",
        quality: str = "720",
        anti_bot: bool = False,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.format = format
        self.quality = quality
        self.anti_bot = anti_bot

        # Check yt-dlp is available
        if not shutil.which("yt-dlp"):
            raise RuntimeError(
                "yt-dlp not found. Install with: pip install yt-dlp"
            )

    def download(
        self,
        url: str,
        filename: Optional[str] = None,
        anti_bot: Optional[bool] = None,
    ) -> DownloadResult:
        """
        Download a single video.

        Args:
            url: YouTube URL.
            filename: Optional output filename (without extension).
            anti_bot: Override instance-level anti_bot setting.

        Returns:
            DownloadResult with path and status.
        """
        use_anti_bot = anti_bot if anti_bot is not None else self.anti_bot

        if filename:
            output_template = str(self.output_dir / f"{filename}.%(ext)s")
        else:
            output_template = str(self.output_dir / "%(title)s.%(ext)s")

        cmd = [
            "yt-dlp",
            "--format", f"bestvideo[height<={self.quality}]+bestaudio/best[height<={self.quality}]/best",
            "--merge-output-format", self.format,
            "--output", output_template,
            "--no-playlist",
            "--socket-timeout", "30",
        ]

        if use_anti_bot:
            cmd.extend([
                "--user-agent", _CHROME_UA,
                "--sleep-interval", "2",
                "--max-sleep-interval", "5",
                "--throttled-rate", "500K",
                "--retries", "3",
                "--extractor-args", "youtube:player_client=web",
            ])

        cmd.append(url)

        # Extract title separately (lightweight, no download)
        video_title = None
        try:
            title_cmd = ["yt-dlp", "--print", "title", "--no-download", url]
            title_result = subprocess.run(
                title_cmd, capture_output=True, text=True, timeout=30,
            )
            if title_result.returncode == 0 and title_result.stdout.strip():
                video_title = title_result.stdout.strip()
        except Exception:
            pass  # Title extraction is best-effort

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
            )

            if result.returncode == 0:
                # Find the downloaded file
                output_path = self._find_downloaded_file(filename or url)
                return DownloadResult(
                    url=url,
                    output_path=output_path,
                    success=True,
                    title=video_title,
                )
            else:
                return DownloadResult(
                    url=url,
                    output_path=None,
                    success=False,
                    error=result.stderr[:500],
                    title=video_title,
                )

        except subprocess.TimeoutExpired:
            return DownloadResult(
                url=url,
                output_path=None,
                success=False,
                error="Download timed out (600s)",
            )
        except Exception as e:
            return DownloadResult(
                url=url,
                output_path=None,
                success=False,
                error=str(e),
            )

    def download_bout_clips(
        self,
        video_path: str,
        touch_events: list,
        output_dir: Optional[str] = None,
        before_sec: float = 3.0,
        after_sec: float = 3.0,
    ) -> List[Path]:
        """
        Extract bout clips around touch events using ffmpeg.

        Args:
            video_path: Path to the source video.
            touch_events: List of TVTouchEvent (or any object with .timestamp).
            output_dir: Output directory for clips (default: data/clips).
            before_sec: Seconds to include before touch.
            after_sec: Seconds to include after touch.

        Returns:
            List of extracted clip paths.
        """
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg not found in PATH")

        out = Path(output_dir or "data/clips")
        out.mkdir(parents=True, exist_ok=True)

        video_stem = Path(video_path).stem
        clips: List[Path] = []

        for i, event in enumerate(touch_events):
            ts = event.timestamp if hasattr(event, "timestamp") else event.get("timestamp", 0)
            start = max(0, ts - before_sec)
            duration = before_sec + after_sec

            clip_path = out / f"{video_stem}_touch{i:04d}.mp4"

            cmd = [
                "ffmpeg", "-y",
                "-ss", f"{start:.3f}",
                "-i", video_path,
                "-t", f"{duration:.3f}",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-an",
                str(clip_path),
            ]

            try:
                subprocess.run(cmd, capture_output=True, timeout=60, check=True)
                clips.append(clip_path)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                print(f"  Failed to extract clip {i}: {e}")

        return clips

    def download_batch(
        self,
        urls: List[str],
        start_index: int = 0,
    ) -> List[DownloadResult]:
        """
        Download multiple videos sequentially.

        Args:
            urls: List of YouTube URLs.
            start_index: Filename numbering start.

        Returns:
            List of DownloadResults.
        """
        results = []
        for i, url in enumerate(urls, start=start_index):
            url = url.strip()
            if not url:
                continue
            print(f"  [{i}/{len(urls) + start_index}] Downloading: {url[:60]}...")
            result = self.download(url, filename=str(i))
            results.append(result)
            if result.success:
                print(f"    OK: {result.output_path}")
            else:
                print(f"    FAILED: {result.error}")
        return results

    def download_from_file(self, url_file: str) -> List[DownloadResult]:
        """
        Download all videos listed in a text file (one URL per line).

        Args:
            url_file: Path to text file with YouTube URLs.

        Returns:
            List of DownloadResults.
        """
        path = Path(url_file)
        if not path.exists():
            raise FileNotFoundError(f"URL file not found: {url_file}")

        urls = [
            line.strip()
            for line in path.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

        print(f"Found {len(urls)} URLs in {url_file}")
        return self.download_batch(urls)

    def _find_downloaded_file(self, hint: str) -> Optional[Path]:
        """Find the most recently downloaded file in output_dir."""
        files = sorted(
            self.output_dir.glob(f"*.{self.format}"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        return files[0] if files else None


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m pipeline.downloader <url_or_file>")
        sys.exit(1)

    arg = sys.argv[1]
    dl = VideoDownloader()

    if Path(arg).exists():
        dl.download_from_file(arg)
    else:
        result = dl.download(arg)
        if result.success:
            print(f"Downloaded: {result.output_path}")
        else:
            print(f"Failed: {result.error}")
