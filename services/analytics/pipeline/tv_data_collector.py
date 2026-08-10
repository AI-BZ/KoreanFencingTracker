"""
End-to-end pipeline for collecting training data from TV broadcasts.

Pipeline flow:
    YouTube URL → download → TVOverlayOCR (score/name extraction)
    → TVScoreTracker (touch event detection) → clip extraction
    → heuristic labeling → labels.csv for VideoMAE fine-tuning
"""

import csv
import cv2
from pathlib import Path
from typing import Optional, List

from analyzer.config import OVERLAY_OCR_SAMPLE_INTERVAL
from analyzer.tv_overlay_ocr import TVOverlayOCR, TVScoreTracker, TVTouchEvent
from pipeline.downloader import VideoDownloader
from pipeline.action_heuristic_labeler import (
    ActionHeuristicLabeler,
    TouchEvent as HeuristicTouchEvent,
)
from app.metadata_parser import parse_fencing_metadata


class TVDataCollector:
    """YouTube TV broadcast → touch detection → clips → label CSV.

    Orchestrates the full data-collection pipeline:
    1. Download video from YouTube (with anti-bot evasion)
    2. OCR overlay bar every N frames to track scores
    3. Detect touch events from score changes
    4. Extract short clips around each touch
    5. Apply heuristic action labels
    6. Write labels.csv for VideoMAE training
    """

    def __init__(
        self,
        output_dir: str = "data",
        layout: str = "usa_fencing",
        sample_interval: int = OVERLAY_OCR_SAMPLE_INTERVAL,
        clip_before: float = 3.0,
        clip_after: float = 3.0,
    ):
        self.output_dir = Path(output_dir)
        self.raw_dir = self.output_dir / "raw"
        self.clips_dir = self.output_dir / "clips"
        self.labels_path = self.output_dir / "labels.csv"

        self.sample_interval = sample_interval
        self.clip_before = clip_before
        self.clip_after = clip_after

        self.downloader = VideoDownloader(
            output_dir=str(self.raw_dir),
            anti_bot=True,
        )
        self.ocr = TVOverlayOCR(layout=layout)
        self.labeler = ActionHeuristicLabeler()

    def process_video(self, video_path: str) -> dict:
        """Process a local video file through the full pipeline.

        Args:
            video_path: Path to the video file.

        Returns:
            Dict with keys: events, clips, labels, summary.
        """
        import os
        # Extract weapon metadata from filename
        filename = os.path.basename(video_path)
        metadata = parse_fencing_metadata(filename)
        weapon = metadata.get("weapon", "unknown")

        # Step 1: Scan video with OCR → touch events + clock events
        events, clock_events = self._scan_video(video_path)

        if not events:
            return {
                "video_path": video_path,
                "events": [],
                "clips": [],
                "labels": [],
                "clock_events": clock_events,
                "summary": {"total_touches": 0},
            }

        # Step 2: Extract clips around touch events
        clips = self.downloader.download_bout_clips(
            video_path=video_path,
            touch_events=events,
            output_dir=str(self.clips_dir),
            before_sec=self.clip_before,
            after_sec=self.clip_after,
        )

        # Step 3: Apply heuristic labels
        labels = self._label_events(events, clips)

        # Step 4: Write labels.csv
        self._write_labels_csv(labels, weapon=weapon)

        tracker = TVScoreTracker()
        # Replay events to get summary
        summary = {
            "total_touches": len(events),
            "total_clips": len(clips),
            "total_labels": len(labels),
            "video_path": video_path,
        }
        if events:
            last = events[-1]
            summary["final_score"] = last.score_after

        return {
            "video_path": video_path,
            "events": [e.to_dict() for e in events],
            "clips": [str(c) for c in clips],
            "labels": labels,
            "clock_events": clock_events,
            "summary": summary,
        }

    def process_youtube_url(self, url: str, filename: Optional[str] = None) -> dict:
        """Download a YouTube video and process it.

        Args:
            url: YouTube video URL.
            filename: Optional output filename (without extension).

        Returns:
            Pipeline result dict.
        """
        result = self.downloader.download(url, filename=filename)

        if not result.success:
            return {
                "video_path": None,
                "error": result.error,
                "events": [],
                "clips": [],
                "labels": [],
                "summary": {"total_touches": 0},
            }

        pipe_result = self.process_video(str(result.output_path))

        # Extract weapon metadata from title
        title_text = result.title or ""
        if title_text:
            metadata = parse_fencing_metadata(title_text)
            pipe_result["metadata"] = metadata

        return pipe_result

    def process_playlist(
        self,
        playlist_url: str,
        max_videos: int = 10,
    ) -> dict:
        """Process multiple videos from a YouTube playlist.

        Args:
            playlist_url: YouTube playlist URL.
            max_videos: Maximum number of videos to process.

        Returns:
            Aggregated results dict.
        """
        # Use yt-dlp to get playlist URLs
        import subprocess

        cmd = [
            "yt-dlp",
            "--flat-playlist",
            "--print", "url",
            "--playlist-items", f"1:{max_videos}",
            playlist_url,
        ]

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            urls = [u.strip() for u in proc.stdout.splitlines() if u.strip()]
        except (subprocess.TimeoutExpired, Exception) as e:
            return {"error": str(e), "videos": []}

        all_results = []
        total_events = 0
        total_clips = 0
        total_labels = 0

        for i, url in enumerate(urls):
            print(f"  [{i + 1}/{len(urls)}] Processing: {url[:60]}...")
            result = self.process_youtube_url(url, filename=f"playlist_{i:04d}")
            all_results.append(result)

            summary = result.get("summary", {})
            total_events += summary.get("total_touches", 0)
            total_clips += summary.get("total_clips", 0)
            total_labels += summary.get("total_labels", 0)

        return {
            "videos_processed": len(all_results),
            "total_events": total_events,
            "total_clips": total_clips,
            "total_labels": total_labels,
            "videos": all_results,
        }

    # ── Internal methods ──

    def _scan_video(self, video_path: str) -> tuple:
        """Scan a video for touch events using overlay OCR.

        Returns:
            Tuple of (touch_events, clock_events) where touch_events is a list
            of TVTouchEvent and clock_events is a list of allez/halt dicts.
        """
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            print(f"  Cannot open video: {video_path}")
            return [], []

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        tracker = TVScoreTracker()

        frame_num = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frame_num += 1

            # Sample every N frames for OCR (performance)
            if frame_num % self.sample_interval != 0:
                continue

            data = self.ocr.read_overlay(frame)
            if data is None:
                continue

            tracker.update(frame_num, data, fps=fps)

            if frame_num % 3000 == 0:
                events_so_far = tracker.get_all_events()
                print(f"  Frame {frame_num}/{total_frames}: {len(events_so_far)} touches")

        cap.release()

        events = tracker.get_all_events()
        clock_events = tracker.get_clock_events()
        print(f"  Scan complete: {len(events)} touch events, {len(clock_events)} clock events in {frame_num} frames")
        return events, clock_events

    def _label_events(
        self,
        events: List[TVTouchEvent],
        clips: List[Path],
    ) -> list:
        """Apply heuristic action labels to touch events.

        Converts TVTouchEvents to the format expected by
        ActionHeuristicLabeler, then labels them.
        """
        # Convert TVTouchEvent → HeuristicTouchEvent
        heuristic_events = []
        for event in events:
            # Map "left"/"right" scorer to "L"/"R"
            scorer = "L" if event.scorer == "left" else "R"

            heuristic_events.append(HeuristicTouchEvent(
                timestamp_sec=event.timestamp,
                scorer=scorer,
                lamp_state="On-No" if scorer == "L" else "No-On",
            ))

        labeled = self.labeler.label_sequence(heuristic_events)

        # Build result with clip paths
        results = []
        for i, la in enumerate(labeled):
            clip_path = str(clips[i]) if i < len(clips) else None
            results.append({
                "clip_path": clip_path,
                "action": la.action,
                "confidence": la.confidence,
                "reason": la.reason,
                "timestamp": la.touch.timestamp_sec,
                "scorer": la.touch.scorer,
            })

        return results

    def _write_labels_csv(self, labels: list, weapon: str = "unknown"):
        """Append labeled data to labels.csv."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        file_exists = self.labels_path.exists()
        fieldnames = ["clip_path", "action", "confidence", "reason", "timestamp", "scorer", "weapon"]

        with open(self.labels_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            for row in labels:
                row_with_weapon = dict(row)
                if "weapon" not in row_with_weapon:
                    row_with_weapon["weapon"] = weapon
                writer.writerow(row_with_weapon)

        print(f"  Wrote {len(labels)} labels to {self.labels_path}")
