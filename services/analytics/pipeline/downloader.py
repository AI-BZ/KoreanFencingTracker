"""
YouTube video downloader for fencing match footage.

Ported from fencing-AI/1-download_vids.py.
Changes: pytube → yt-dlp (more reliable, actively maintained).
"""

import subprocess
import shutil
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass


@dataclass
class DownloadResult:
    url: str
    output_path: Optional[Path]
    success: bool
    error: Optional[str] = None


class VideoDownloader:
    """Downloads fencing match videos from YouTube using yt-dlp."""

    def __init__(self, output_dir: str = "data/raw", format: str = "mp4", quality: str = "720"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.format = format
        self.quality = quality

        # Check yt-dlp is available
        if not shutil.which("yt-dlp"):
            raise RuntimeError(
                "yt-dlp not found. Install with: pip install yt-dlp"
            )

    def download(self, url: str, filename: Optional[str] = None) -> DownloadResult:
        """
        Download a single video.

        Args:
            url: YouTube URL.
            filename: Optional output filename (without extension).

        Returns:
            DownloadResult with path and status.
        """
        if filename:
            output_template = str(self.output_dir / f"{filename}.%(ext)s")
        else:
            output_template = str(self.output_dir / "%(title)s.%(ext)s")

        cmd = [
            "yt-dlp",
            "--format", f"bestvideo[height<={self.quality}][ext={self.format}]+bestaudio[ext=m4a]/best[height<={self.quality}]",
            "--merge-output-format", self.format,
            "--output", output_template,
            "--no-playlist",
            "--socket-timeout", "30",
            url,
        ]

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
                )
            else:
                return DownloadResult(
                    url=url,
                    output_path=None,
                    success=False,
                    error=result.stderr[:500],
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
