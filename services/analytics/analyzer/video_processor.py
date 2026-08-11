"""
Main video processing loop for fencing match analysis.

Extracted from fencing_analyzer_v3.py — orchestrates lamp detection,
score reading, event tracking, and result export. Supports both
interactive (GUI) and headless processing modes.
"""

import cv2
import json
import csv
import numpy as np
from datetime import timedelta
from pathlib import Path
from dataclasses import asdict
from typing import Optional, List, Dict, Tuple

from analyzer.models import (
    ScoreState,
    StableScore,
    LampState,
    MatchEvent,
)
from analyzer.config import DEBOUNCE_FRAMES, LAMP_PIXEL_THRESHOLD
from analyzer.lamp_detector import LampDetector
from analyzer.score_reader import ScoreReader


class VideoProcessor:
    """
    Processes a fencing match video to detect scoring events.

    Orchestrates LampDetector and ScoreReader to:
    1. Detect lamp activations (touches)
    2. Read score changes from the LED display
    3. Correlate lamp events with score changes
    4. Export results as JSON/CSV
    """

    def __init__(self, template_path: Optional[Path] = None):
        self.lamp_detector = LampDetector()
        self.score_reader = ScoreReader(template_path=template_path)

        # State
        self.rois: Dict[str, Tuple[int, int, int, int]] = {}
        self.events: List[MatchEvent] = []
        self.current_score = ScoreState()
        self.stable_score = StableScore()
        self.last_event_frame = 0
        self.debounce_frames = DEBOUNCE_FRAMES

        # Score change detection
        self.score_baseline: Dict[str, Optional[int]] = {"left": None, "right": None}
        self.auto_score_mode = True

        # Pending lamp event (waiting for score change)
        self.pending_lamp_event: Optional[dict] = None
        self.pending_lamp_frame = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_video(
        self,
        video_path: str,
        debug: bool = True,
        output_dir: Optional[str] = None,
    ):
        """
        Analyze a fencing match video.

        Args:
            video_path: Path to the video file.
            debug: If True, show real-time preview with ROI overlays.
            output_dir: Directory for result files (default: same as video).
        """
        video_path = Path(video_path)
        cap = cv2.VideoCapture(str(video_path))

        if not cap.isOpened():
            print(f"Failed to open video: {video_path}")
            return

        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        print(f"\nFencing Analyzer")
        print(f"  {video_path.name}: {width}x{height} @ {fps:.1f}fps, {total_frames} frames")

        # ROI selection
        start_frame, setup_frame = self._select_setup_frame(cap, fps, total_frames)
        if setup_frame is None:
            print("Frame selection cancelled")
            return

        self.rois = self._select_rois(setup_frame)
        if not self.rois:
            print("No ROIs selected")
            return

        # Capture baseline score image (0-0 state)
        self._capture_score_baseline(setup_frame)

        # Start analysis
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        self.events = []
        self.current_score = ScoreState()
        self.stable_score = StableScore()
        prev_lamp = LampState()

        print(f"  Starting analysis from frame {start_frame}...")

        frame_num = start_frame
        paused = False
        show_debug = debug

        while True:
            if not paused:
                ret, frame = cap.read()
                if not ret:
                    break
                frame_num += 1

            # Detect lamps
            lamp = self.lamp_detector.detect_both(frame, self.rois)

            # Read scores
            read_left, read_right = self.score_reader.read_score_from_display(frame, self.rois)

            # Stabilize LED readings (require 3 consecutive identical frames)
            self._stabilize_readings(read_left, read_right)

            # Read match time
            match_time_str = self.score_reader.read_match_time(frame, self.rois)

            # Detect new lamp events
            new_red = lamp.red and not prev_lamp.red
            new_green = lamp.green and not prev_lamp.green

            # Process pending events and new lamp events
            self._process_pending_event(
                frame, frame_num, fps, read_left, read_right, match_time_str,
            )
            self._process_new_lamp_event(
                frame, frame_num, fps, lamp, new_red, new_green,
                read_left, read_right, match_time_str,
            )

            prev_lamp = lamp

            # Debug display
            if show_debug:
                self._draw_debug(
                    frame, frame_num, total_frames, fps,
                    lamp, read_left, read_right, match_time_str, paused,
                )

            # Key handling
            key = cv2.waitKey(1 if not paused else 0) & 0xFF
            action = self._handle_key(
                key, frame, frame_num, fps, total_frames, cap, paused, show_debug,
            )
            if action == "quit":
                break
            elif action == "toggle_pause":
                paused = not paused
            elif action == "toggle_debug":
                show_debug = not show_debug
                if not show_debug:
                    cv2.destroyAllWindows()
            elif isinstance(action, dict):
                if "frame_num" in action:
                    frame_num = action["frame_num"]
                if "paused" in action:
                    paused = action["paused"]
                if "show_debug" in action:
                    show_debug = action["show_debug"]

            # Progress
            remaining = total_frames - start_frame
            if not show_debug and remaining > 0 and (frame_num - start_frame) % max(1, remaining // 10) == 0:
                progress = ((frame_num - start_frame) / remaining) * 100
                print(f"  ... {progress:.0f}%")

        cap.release()
        cv2.destroyAllWindows()
        self._save_results(video_path, output_dir)

    def process_video_headless(
        self,
        video_path: str,
        rois: Dict[str, Tuple[int, int, int, int]],
        start_frame: int = 0,
        output_dir: Optional[str] = None,
    ) -> List[MatchEvent]:
        """
        Process a video without GUI (for automated pipelines).

        Args:
            video_path: Path to the video file.
            rois: Pre-defined ROIs.
            start_frame: Frame to start analysis from.
            output_dir: Directory for result files.

        Returns:
            List of detected MatchEvents.
        """
        video_path = Path(video_path)
        cap = cv2.VideoCapture(str(video_path))

        if not cap.isOpened():
            return []

        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        self.rois = rois
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        self.events = []
        self.current_score = ScoreState()
        self.stable_score = StableScore()
        prev_lamp = LampState()

        # Capture baseline
        ret, baseline_frame = cap.read()
        if ret:
            self._capture_score_baseline(baseline_frame)
            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        frame_num = start_frame

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frame_num += 1

            lamp = self.lamp_detector.detect_both(frame, self.rois)
            read_left, read_right = self.score_reader.read_score_from_display(frame, self.rois)
            self._stabilize_readings(read_left, read_right)
            match_time_str = self.score_reader.read_match_time(frame, self.rois)

            new_red = lamp.red and not prev_lamp.red
            new_green = lamp.green and not prev_lamp.green

            self._process_pending_event(
                frame, frame_num, fps, read_left, read_right, match_time_str,
            )
            self._process_new_lamp_event(
                frame, frame_num, fps, lamp, new_red, new_green,
                read_left, read_right, match_time_str,
            )

            prev_lamp = lamp

        cap.release()

        if output_dir:
            self._save_results(video_path, output_dir)

        return self.events

    # ------------------------------------------------------------------
    # Internal: score stabilization
    # ------------------------------------------------------------------

    def _stabilize_readings(self, read_left: Optional[int], read_right: Optional[int]):
        """Track consecutive identical readings for score stabilization."""
        if read_left == self.stable_score.last_read_left:
            self.stable_score.read_count_left += 1
        else:
            self.stable_score.last_read_left = read_left
            self.stable_score.read_count_left = 1

        if read_right == self.stable_score.last_read_right:
            self.stable_score.read_count_right += 1
        else:
            self.stable_score.last_read_right = read_right
            self.stable_score.read_count_right = 1

    # ------------------------------------------------------------------
    # Internal: event processing
    # ------------------------------------------------------------------

    def _process_pending_event(
        self,
        frame: np.ndarray,
        frame_num: int,
        fps: float,
        read_left: Optional[int],
        read_right: Optional[int],
        match_time_str: Optional[str],
    ):
        """Check pending lamp event for score change confirmation."""
        if not self.pending_lamp_event or not self.auto_score_mode:
            return

        frames_since_lamp = frame_num - self.pending_lamp_frame
        confirmed_left = self.stable_score.left
        confirmed_right = self.stable_score.right
        lamp_side = self.pending_lamp_event["lamp_side"]

        # Template matching for current digits
        left_mask = self.score_reader.get_score_roi_mask(frame, self.rois.get("score_left"))
        right_mask = self.score_reader.get_score_roi_mask(frame, self.rois.get("score_right"))

        curr_left = self.score_reader.match_digit_template(left_mask, "left")
        curr_right = self.score_reader.match_digit_template(right_mask, "right")

        if curr_left is None:
            curr_left = read_left
        if curr_right is None:
            curr_right = read_right

        prev_left = self.pending_lamp_event.get("left_digit")
        prev_right = self.pending_lamp_event.get("right_digit")

        check_left = lamp_side in ("left", "both")
        check_right = lamp_side in ("right", "both")

        # Detect digit change (+1)
        left_changed = (
            check_left
            and curr_left is not None
            and prev_left is not None
            and curr_left == prev_left + 1
        )
        right_changed = (
            check_right
            and curr_right is not None
            and prev_right is not None
            and curr_right == prev_right + 1
        )

        left_plus1 = check_left and curr_left == confirmed_left + 1
        right_plus1 = check_right and curr_right == confirmed_right + 1

        if (left_changed or left_plus1) and not self.pending_lamp_event.get("left_change_detected"):
            self.pending_lamp_event["left_change_detected"] = True
        if (right_changed or right_plus1) and not self.pending_lamp_event.get("right_change_detected"):
            self.pending_lamp_event["right_change_detected"] = True

        left_scored = self.pending_lamp_event.get("left_change_detected", False)
        right_scored = self.pending_lamp_event.get("right_change_detected", False)

        scorer = ""

        # Confirm after 0.5s
        if left_scored or right_scored:
            if frames_since_lamp > fps * 0.5:
                if left_scored:
                    self.stable_score.left = confirmed_left + 1
                    scorer = "left"
                if right_scored:
                    self.stable_score.right = confirmed_right + 1
                    scorer = "right" if not scorer else "both"

        # Invalid after 2s with no change
        if not scorer and frames_since_lamp > fps * 2.0:
            scorer = "none"

        if scorer and scorer not in ("none", "timeout"):
            self._record_event(scorer, confirmed_left, confirmed_right)
        elif scorer == "none":
            self._record_invalid_event(confirmed_left, confirmed_right)

    def _process_new_lamp_event(
        self,
        frame: np.ndarray,
        frame_num: int,
        fps: float,
        lamp: LampState,
        new_red: bool,
        new_green: bool,
        read_left: Optional[int],
        read_right: Optional[int],
        match_time_str: Optional[str],
    ):
        """Detect and register new lamp events."""
        if frame_num - self.last_event_frame <= self.debounce_frames:
            return
        if not (new_red or new_green):
            return

        # Flush previous pending event
        if self.pending_lamp_event:
            event = MatchEvent(
                frame=self.pending_lamp_event["frame"],
                video_timestamp=self.pending_lamp_event["timestamp"],
                match_time=self.pending_lamp_event.get("match_time", ""),
                event_type=self.pending_lamp_event["event_type"],
                lamp_red=self.pending_lamp_event["lamp_red"],
                lamp_green=self.pending_lamp_event["lamp_green"],
                score_before=self.pending_lamp_event["score_before"],
                score_after=self.pending_lamp_event["score_before"],
                scorer=None,
                description=self.pending_lamp_event["desc"] + " → no score (new lamp)",
            )
            self.events.append(event)
            self.pending_lamp_event = None

        timestamp = self._format_time(frame_num, fps)

        if new_red and new_green:
            desc = "Simultaneous touch"
            event_type = "simultaneous"
            lamp_side = "both"
        elif new_red:
            desc = "Left lamp (red)"
            event_type = "left_lamp"
            lamp_side = "left"
        else:
            desc = "Right lamp (green)"
            event_type = "right_lamp"
            lamp_side = "right"

        if self.auto_score_mode:
            left_mask = self.score_reader.get_score_roi_mask(frame, self.rois.get("score_left"))
            right_mask = self.score_reader.get_score_roi_mask(frame, self.rois.get("score_right"))

            left_digit = self.score_reader.match_digit_template(left_mask, "left")
            right_digit = self.score_reader.match_digit_template(right_mask, "right")
            if left_digit is None:
                left_digit = read_left
            if right_digit is None:
                right_digit = read_right

            self.pending_lamp_event = {
                "frame": frame_num,
                "timestamp": timestamp,
                "event_type": event_type,
                "lamp_red": lamp.red,
                "lamp_green": lamp.green,
                "lamp_side": lamp_side,
                "desc": desc,
                "score_before": f"{self.stable_score.left}-{self.stable_score.right}",
                "match_time": match_time_str or "",
                "left_digit": left_digit,
                "right_digit": right_digit,
            }
            self.pending_lamp_frame = frame_num
        else:
            event = MatchEvent(
                frame=frame_num,
                video_timestamp=timestamp,
                match_time=match_time_str or "",
                event_type=event_type,
                lamp_red=lamp.red,
                lamp_green=lamp.green,
                score_before=f"{self.current_score.left}-{self.current_score.right}",
                score_after="",
                scorer=lamp_side,
                description=desc,
            )
            self.events.append(event)

        self.last_event_frame = frame_num

    def _record_event(self, scorer: str, prev_left: int, prev_right: int):
        """Record a confirmed scoring event."""
        event = MatchEvent(
            frame=self.pending_lamp_event["frame"],
            video_timestamp=self.pending_lamp_event["timestamp"],
            match_time=self.pending_lamp_event.get("match_time", ""),
            event_type=self.pending_lamp_event["event_type"],
            lamp_red=self.pending_lamp_event["lamp_red"],
            lamp_green=self.pending_lamp_event["lamp_green"],
            score_before=f"{prev_left}-{prev_right}",
            score_after=f"{self.stable_score.left}-{self.stable_score.right}",
            scorer=scorer,
            description=self.pending_lamp_event["desc"] + f" → {scorer} scored",
        )
        self.events.append(event)
        self.pending_lamp_event = None

    def _record_invalid_event(self, prev_left: int, prev_right: int):
        """Record an invalid touch (no score change detected)."""
        event = MatchEvent(
            frame=self.pending_lamp_event["frame"],
            video_timestamp=self.pending_lamp_event["timestamp"],
            match_time=self.pending_lamp_event.get("match_time", ""),
            event_type=self.pending_lamp_event["event_type"],
            lamp_red=self.pending_lamp_event["lamp_red"],
            lamp_green=self.pending_lamp_event["lamp_green"],
            score_before=f"{prev_left}-{prev_right}",
            score_after=f"{prev_left}-{prev_right}",
            scorer=None,
            description=self.pending_lamp_event["desc"] + " → invalid",
        )
        self.events.append(event)
        self.pending_lamp_event = None

    # ------------------------------------------------------------------
    # Internal: score baseline
    # ------------------------------------------------------------------

    def _capture_score_baseline(self, frame: np.ndarray):
        """Capture baseline score pixel counts (0-0 state)."""
        for side in ["left", "right"]:
            roi_key = f"score_{side}"
            if roi_key in self.rois:
                pixels = self.score_reader.get_score_pixel_count(frame, self.rois[roi_key])
                self.score_baseline[side] = pixels

    # ------------------------------------------------------------------
    # Internal: ROI selection (GUI)
    # ------------------------------------------------------------------

    def _select_setup_frame(self, cap, fps, total_frames):
        """Interactive frame selection for ROI setup."""
        current_frame = min(int(30 * fps), total_frames - 1)
        cap.set(cv2.CAP_PROP_POS_FRAMES, current_frame)

        while True:
            cap.set(cv2.CAP_PROP_POS_FRAMES, current_frame)
            ret, frame = cap.read()
            if not ret:
                current_frame = max(0, current_frame - int(fps))
                continue

            display = frame.copy()
            time_str = str(timedelta(seconds=current_frame / fps))[:8]

            overlay = display.copy()
            cv2.rectangle(overlay, (5, 5), (450, 120), (0, 0, 0), -1)
            cv2.addWeighted(overlay, 0.7, display, 0.3, 0, display)

            cv2.putText(display, "SELECT FRAME FOR ROI", (15, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            cv2.putText(display, f"Frame: {current_frame}/{total_frames}  Time: {time_str}", (15, 55),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(display, "[<-/->] 1s  [A/D] 10s  [Enter] Select  [Q] Quit", (15, 80),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)

            scale = 0.7
            display_resized = cv2.resize(display, None, fx=scale, fy=scale)
            cv2.imshow("Select Frame for ROI Setup", display_resized)

            key = cv2.waitKey(0) & 0xFF
            if key == 13:  # Enter
                cv2.destroyAllWindows()
                return current_frame, frame
            elif key == ord("q"):
                cv2.destroyAllWindows()
                return None, None
            elif key in (81, 2, ord(",")):
                current_frame = max(0, current_frame - int(fps))
            elif key in (83, 3, ord(".")):
                current_frame = min(total_frames - 1, current_frame + int(fps))
            elif key == ord("a"):
                current_frame = max(0, current_frame - int(fps * 10))
            elif key == ord("d"):
                current_frame = min(total_frames - 1, current_frame + int(fps * 10))

    def _select_rois(self, frame: np.ndarray) -> Dict[str, Tuple[int, int, int, int]]:
        """Interactive ROI selection for 5 regions."""
        rois = {}
        selections = [
            ("lamp_left", "1/5: LEFT LAMP (Red)"),
            ("lamp_right", "2/5: RIGHT LAMP (Green)"),
            ("score_left", "3/5: LEFT SCORE"),
            ("score_right", "4/5: RIGHT SCORE"),
            ("clock", "5/5: CLOCK (M:SS)"),
        ]

        for idx, (key, name) in enumerate(selections):
            display = frame.copy()
            for k, r in rois.items():
                cv2.rectangle(display, (r[0], r[1]), (r[0] + r[2], r[1] + r[3]), (0, 255, 0), 2)

            overlay = display.copy()
            cv2.rectangle(overlay, (5, 5), (450, 60), (0, 0, 0), -1)
            cv2.addWeighted(overlay, 0.7, display, 0.3, 0, display)
            cv2.putText(display, f"Select: {name}", (15, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            cv2.putText(display, "Drag -> Enter/Space | C: Skip", (15, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)

            roi = cv2.selectROI(name, display, fromCenter=False)
            cv2.destroyAllWindows()

            if roi[2] > 0 and roi[3] > 0:
                rois[key] = roi

        return rois

    # ------------------------------------------------------------------
    # Internal: debug display
    # ------------------------------------------------------------------

    def _draw_debug(
        self,
        frame: np.ndarray,
        frame_num: int,
        total_frames: int,
        fps: float,
        lamp: LampState,
        read_left: Optional[int],
        read_right: Optional[int],
        match_time_str: Optional[str],
        paused: bool,
    ):
        """Draw debug overlay on frame."""
        display = frame.copy()
        h, w = display.shape[:2]

        # ROI boxes
        colors = {
            "lamp_left": (0, 0, 255),
            "lamp_right": (0, 255, 0),
            "score_left": (255, 255, 0),
            "score_right": (255, 255, 0),
            "clock": (255, 0, 255),
        }
        for name, roi in self.rois.items():
            x, y, rw, rh = roi
            color = colors.get(name, (255, 255, 255))
            cv2.rectangle(display, (x, y), (x + rw, y + rh), color, 2)

        # Info overlay
        overlay = display.copy()
        cv2.rectangle(overlay, (5, 5), (400, 100), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.7, display, 0.3, 0, display)

        time_str = self._format_time(frame_num, fps)
        disp_left = self.stable_score.left if self.auto_score_mode else self.current_score.left
        disp_right = self.stable_score.right if self.auto_score_mode else self.current_score.right

        cv2.putText(display, f"Frame: {frame_num}/{total_frames} | {time_str}", (15, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
        cv2.putText(display, f"Score: {disp_left} - {disp_right}", (15, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        cv2.putText(display, f"Read: L={read_left or '?'} R={read_right or '?'}  Events: {len(self.events)}", (15, 75),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
        cv2.putText(display, f"[Q] Quit [Space] Pause [D] Debug", (15, 92),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (180, 180, 180), 1)

        # Lamp indicators
        if lamp.red:
            cv2.circle(display, (w - 80, 40), 20, (0, 0, 255), -1)
        if lamp.green:
            cv2.circle(display, (w - 30, 40), 20, (0, 255, 0), -1)

        if paused:
            cv2.putText(display, "PAUSED", (w // 2 - 60, h // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 3)

        scale = 0.6
        display_resized = cv2.resize(display, None, fx=scale, fy=scale)
        cv2.imshow("Fencing Analyzer", display_resized)

    # ------------------------------------------------------------------
    # Internal: key handling
    # ------------------------------------------------------------------

    def _handle_key(self, key, frame, frame_num, fps, total_frames, cap, paused, show_debug):
        """Handle keyboard input. Returns action string or dict."""
        if key in (ord("q"), ord("Q"), 27):
            return "quit"
        elif key == ord(" "):
            return "toggle_pause"
        elif key in (ord("d"), ord("D")):
            return "toggle_debug"
        elif key in (ord("+"), ord("=")):
            self.lamp_detector.pixel_threshold += 50
        elif key in (ord("-"), ord("_")):
            self.lamp_detector.pixel_threshold = max(50, self.lamp_detector.pixel_threshold - 50)
        elif key in (ord("a"), ord("A")):
            self.auto_score_mode = not self.auto_score_mode
        elif key == ord("1"):
            self.stable_score.left += 1
        elif key == ord("2"):
            self.stable_score.right += 1
        elif key == ord("0"):
            self.stable_score = StableScore()
        return None

    # ------------------------------------------------------------------
    # Internal: utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _format_time(frame_num: int, fps: float) -> str:
        secs = frame_num / fps
        return str(timedelta(seconds=secs))[:8]

    def _save_results(self, video_path: Path, output_dir: Optional[str]):
        """Save analysis results as JSON and CSV."""
        if output_dir is None:
            out = video_path.parent
        else:
            out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        base_name = video_path.stem

        # JSON
        json_path = out / f"{base_name}_events.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "final_score": f"{self.stable_score.left}-{self.stable_score.right}",
                    "events": [asdict(e) for e in self.events],
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

        # CSV
        csv_path = out / f"{base_name}_events.csv"
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            if self.events:
                writer = csv.DictWriter(f, fieldnames=asdict(self.events[0]).keys())
                writer.writeheader()
                for e in self.events:
                    writer.writerow(asdict(e))

        print(f"\n  Results saved:")
        print(f"    Score: {self.stable_score.left} - {self.stable_score.right}")
        print(f"    Events: {len(self.events)}")
        print(f"    Files: {json_path.name}, {csv_path.name}")


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        video = sys.argv[1]
        debug = "--no-debug" not in sys.argv
        processor = VideoProcessor()
        processor.process_video(video, debug=debug)
    else:
        print("Usage: python -m analyzer.video_processor <video.mp4> [--no-debug]")
