"""
Automatic clip extraction around touch/scoring moments.

Ported from fencing-AI/2-fast_clip_cutter.py.
Key change: Uses v3's LampDetector + ScoreReader instead of the
original logistic classifier for more accurate touch detection.
"""

import cv2
import subprocess
import shutil
from pathlib import Path
from typing import List, Optional, Tuple
from dataclasses import dataclass

from analyzer.lamp_detector import LampDetector
from analyzer.score_reader import ScoreReader
from analyzer.models import LampState


@dataclass
class TouchEvent:
    """A detected touch moment in a video."""
    frame: int
    timestamp_sec: float
    lamp_state: LampState
    score_left: Optional[int]
    score_right: Optional[int]


@dataclass
class ClipInfo:
    """Information about an extracted clip."""
    source_video: str
    clip_path: Path
    touch_frame: int
    start_sec: float
    end_sec: float
    lamp_state: LampState


class ClipCutter:
    """
    Extracts short clips around scoring moments from fencing match videos.

    Uses v3's LED lamp detection to find touch moments, then extracts
    clips with configurable padding before/after the touch.
    """

    def __init__(
        self,
        rois: dict,
        template_path: Optional[Path] = None,
        before_sec: float = 5.0,
        after_sec: float = 2.0,
    ):
        """
        Args:
            rois: ROI dict with lamp_left, lamp_right, score_left, score_right keys.
            template_path: Path to digit template pickle.
            before_sec: Seconds to include before the touch.
            after_sec: Seconds to include after the touch.
        """
        self.rois = rois
        self.lamp_detector = LampDetector()
        self.score_reader = ScoreReader(template_path=template_path)
        self.before_sec = before_sec
        self.after_sec = after_sec

        # Minimum frames between detected touches (debounce)
        self.min_touch_gap_frames = 60  # ~2 seconds at 30fps

    def find_touch_moments(self, video_path: str) -> List[TouchEvent]:
        """
        Scan a video for all touch/scoring moments.

        Args:
            video_path: Path to the video file.

        Returns:
            List of TouchEvents with frame numbers and timestamps.
        """
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return []

        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        touches: List[TouchEvent] = []
        prev_lamp = LampState()
        last_touch_frame = -self.min_touch_gap_frames

        frame_num = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frame_num += 1

            lamp = self.lamp_detector.detect_both(frame, self.rois)

            # Detect new lamp activation
            new_red = lamp.red and not prev_lamp.red
            new_green = lamp.green and not prev_lamp.green

            if (new_red or new_green) and (frame_num - last_touch_frame > self.min_touch_gap_frames):
                # Read current score
                left, right = self.score_reader.read_score_from_display(frame, self.rois)

                # Skip if score is 15 (match over) or 0-0 at very start
                if (left == 15 or right == 15):
                    prev_lamp = lamp
                    continue
                if frame_num < fps * 5 and left == 0 and right == 0:
                    prev_lamp = lamp
                    continue

                touch = TouchEvent(
                    frame=frame_num,
                    timestamp_sec=frame_num / fps,
                    lamp_state=lamp,
                    score_left=left,
                    score_right=right,
                )
                touches.append(touch)
                last_touch_frame = frame_num

                if frame_num % 1000 == 0 or len(touches) % 10 == 0:
                    print(f"  Frame {frame_num}/{total_frames}: {len(touches)} touches found")

            prev_lamp = lamp

        cap.release()
        print(f"  Total: {len(touches)} touch moments in {frame_num} frames")
        return touches

    def extract_clips(
        self,
        video_path: str,
        output_dir: str = "data/clips",
        touches: Optional[List[TouchEvent]] = None,
    ) -> List[ClipInfo]:
        """
        Extract clips around touch moments using ffmpeg.

        Args:
            video_path: Source video path.
            output_dir: Directory for output clips.
            touches: Pre-computed touch events (will scan if not provided).

        Returns:
            List of ClipInfo for extracted clips.
        """
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg not found in PATH")

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        if touches is None:
            touches = self.find_touch_moments(video_path)

        if not touches:
            print("  No touch moments found")
            return []

        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
        cap.release()

        video_stem = Path(video_path).stem
        clips: List[ClipInfo] = []

        for i, touch in enumerate(touches):
            start_sec = max(0, touch.timestamp_sec - self.before_sec)
            end_sec = min(duration, touch.timestamp_sec + self.after_sec)
            clip_duration = end_sec - start_sec

            clip_path = out / f"{video_stem}_clip{i:04d}.mp4"

            cmd = [
                "ffmpeg",
                "-y",
                "-ss", f"{start_sec:.3f}",
                "-i", video_path,
                "-t", f"{clip_duration:.3f}",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-an",  # no audio
                str(clip_path),
            ]

            try:
                subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=60,
                    check=True,
                )
                clips.append(ClipInfo(
                    source_video=video_path,
                    clip_path=clip_path,
                    touch_frame=touch.frame,
                    start_sec=start_sec,
                    end_sec=end_sec,
                    lamp_state=touch.lamp_state,
                ))
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                print(f"  Failed to extract clip {i}: {e}")

        print(f"  Extracted {len(clips)} clips to {output_dir}")
        return clips


if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 2:
        print("Usage: python -m pipeline.clip_cutter <video.mp4> [rois.json]")
        print("  rois.json: {\"lamp_left\": [x,y,w,h], ...}")
        sys.exit(1)

    video = sys.argv[1]

    if len(sys.argv) > 2:
        with open(sys.argv[2]) as f:
            rois_raw = json.load(f)
        rois = {k: tuple(v) for k, v in rois_raw.items()}
    else:
        print("ROIs must be provided as JSON. Run interactive ROI selection first.")
        sys.exit(1)

    cutter = ClipCutter(rois=rois)
    cutter.extract_clips(video)
