"""
Generate overlay video clips for fencing events (touches/exchanges).

Uses YOLO11-Pose for skeleton overlay and cv2.putText for
distance/footwork/parry HUD text.
"""

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np

from ml.pose_estimator import PoseEstimator
from ml.pose_analyzer import PoseAnalyzer

_logger = logging.getLogger(__name__)


class ClipOverlayGenerator:
    """Generate overlay clips for touch/exchange events."""

    def __init__(
        self,
        model_path: Optional[str] = None,
        pad_seconds: float = 2.0,
        pad_before: Optional[float] = None,
        pad_after: Optional[float] = None,
    ):
        self.estimator = PoseEstimator(model_path=model_path)
        self.analyzer = PoseAnalyzer()
        self.pad_seconds = pad_seconds
        self.pad_before = pad_before  # None → falls back to pad_seconds
        self.pad_after = pad_after    # None → falls back to pad_seconds

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_clip(
        self,
        video_path: str,
        start_frame: int,
        end_frame: int,
        output_path: str,
        event_info: Optional[dict] = None,
    ) -> str:
        """
        Extract frames [start-pad .. end+pad], run YOLO, overlay skeleton + text.

        Args:
            video_path: Source video file.
            start_frame: First frame of the event.
            end_frame: Last frame of the event.
            output_path: Destination mp4 file path.
            event_info: Optional dict with keys like footwork_scorer,
                        footwork_defender, distance_bh, distance_zone,
                        parry_side, touch_number, score_after, etc.

        Returns:
            output_path on success.
        """
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise FileNotFoundError(f"Cannot open video: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        pb = self.pad_before if self.pad_before is not None else self.pad_seconds
        pa = self.pad_after if self.pad_after is not None else self.pad_seconds
        pad_frames_before = int(pb * fps)
        pad_frames_after = int(pa * fps)
        actual_start = max(0, start_frame - pad_frames_before)
        actual_end = min(total_frames - 1, end_frame + pad_frames_after)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # Write to temp file first (mp4v), then transcode to H.264
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".mp4")
        import os
        os.close(tmp_fd)

        try:
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(tmp_path, fourcc, fps, (width, height))

            if not writer.isOpened():
                cap.release()
                raise RuntimeError(f"Cannot create video writer: {tmp_path}")

            cap.set(cv2.CAP_PROP_POS_FRAMES, actual_start)

            for frame_idx in range(actual_start, actual_end + 1):
                ret, frame = cap.read()
                if not ret:
                    break

                # Run YOLO
                self.estimator._load_model()
                yolo_results = self.estimator._model(
                    frame,
                    device=self.estimator.device,
                    imgsz=self.estimator.imgsz,
                    conf=self.estimator.confidence,
                    max_det=2,
                    verbose=False,
                )

                # Parse for PoseAnalyzer
                pose_result = self.estimator._parse_results(yolo_results)

                # Build pose analysis for this frame
                from analyzer.models import PoseResult as PR
                pr = PR(frame_idx=frame_idx, fencers=pose_result, inference_time_ms=0)
                analysis = self.analyzer.analyze([pr])

                # Compute per-frame joint angles directly
                ja_left = self.analyzer._compute_joint_angles_for_side(pr, "left")
                ja_right = self.analyzer._compute_joint_angles_for_side(pr, "right")

                # Draw skeleton overlay
                annotated = self._annotate_frame(
                    frame, yolo_results, analysis, event_info,
                    joint_angles_left=ja_left, joint_angles_right=ja_right,
                )
                writer.write(annotated)

            writer.release()
            cap.release()

            # Transcode mp4v → H.264 for browser compatibility
            self._transcode_to_h264(tmp_path, str(output_path))

        finally:
            # Clean up temp file
            if Path(tmp_path).exists():
                Path(tmp_path).unlink()

        _logger.info(
            "Clip generated: %s (frames %d-%d, %d frames)",
            output_path, actual_start, actual_end, actual_end - actual_start + 1,
        )
        return output_path

    def generate_clips_for_report(
        self,
        video_path: str,
        report_dict: dict,
        output_dir: str,
        touches_only: bool = True,
        touch_bounds: Optional[dict] = None,
    ) -> List[dict]:
        """
        Generate overlay clips for all events in a report JSON.

        Args:
            video_path: Source video file.
            report_dict: Parsed report JSON dict.
            output_dir: Directory for output clips.
            touches_only: If True, only generate clips for touches (scoring).
            touch_bounds: Optional {touch_number: (start_frame, end_frame)} of
                anchored clip bounds (real-touch anchoring, see
                app.server._compute_touch_clip_bounds). When provided, a touch's
                clip uses these bounds instead of the point-in-time OCR frame,
                keeping batch clips consistent with the on-demand endpoint.

        Returns:
            List of dicts: [{event_type, event_number, clip_path, duration_sec}, ...]
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        cap.release()

        results: List[dict] = []

        # Process touches
        for touch in report_dict.get("touches", []):
            touch_num = touch.get("touch_number", len(results) + 1)
            frame = touch.get("frame")
            if frame is None:
                continue

            clip_path = str(out / f"touch_{touch_num:03d}.mp4")
            event_info = self._extract_touch_info(touch)

            # Anchor on the real touch when bounds are supplied; otherwise fall
            # back to the point-in-time OCR frame.
            if touch_bounds and touch_num in touch_bounds:
                sf, ef = touch_bounds[touch_num]
            else:
                sf, ef = frame, frame

            try:
                self.generate_clip(
                    video_path, sf, ef, clip_path, event_info
                )
                pb = self.pad_before if self.pad_before is not None else self.pad_seconds
                pa = self.pad_after if self.pad_after is not None else self.pad_seconds
                duration = (int(pb * fps) + int(pa * fps) + 1) / fps
                results.append({
                    "event_type": "touch",
                    "event_number": touch_num,
                    "clip_path": clip_path,
                    "duration_sec": round(duration, 2),
                })
            except Exception as e:
                _logger.warning("Failed to generate clip for touch %d: %s", touch_num, e)

        # Process exchanges (if not touches_only)
        if not touches_only:
            for ex in report_dict.get("exchanges", []):
                ex_num = ex.get("exchange_number", len(results) + 1)
                start_frame = ex.get("start_frame")
                end_frame = ex.get("end_frame")
                if start_frame is None or end_frame is None:
                    continue

                clip_path = str(out / f"exchange_{ex_num:03d}.mp4")
                event_info = self._extract_exchange_info(ex)

                try:
                    self.generate_clip(
                        video_path, start_frame, end_frame, clip_path, event_info
                    )
                    pb = self.pad_before if self.pad_before is not None else self.pad_seconds
                    pa = self.pad_after if self.pad_after is not None else self.pad_seconds
                    duration = (end_frame - start_frame + int(pb * fps) + int(pa * fps)) / fps
                    results.append({
                        "event_type": "exchange",
                        "event_number": ex_num,
                        "clip_path": clip_path,
                        "duration_sec": round(duration, 2),
                    })
                except Exception as e:
                    _logger.warning("Failed to generate clip for exchange %d: %s", ex_num, e)

        return results

    # ------------------------------------------------------------------
    # Transcoding
    # ------------------------------------------------------------------

    @staticmethod
    def _transcode_to_h264(input_path: str, output_path: str) -> None:
        """Transcode mp4v → H.264 (avc1) for browser playback compatibility."""
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-an",  # no audio in overlay clips
            output_path,
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            _logger.error("ffmpeg transcode failed: %s", result.stderr[-500:])
            raise RuntimeError(f"ffmpeg transcode failed: {result.stderr[-200:]}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _annotate_frame(
        self,
        frame: np.ndarray,
        yolo_results,
        pose_analysis,
        event_info: Optional[dict],
        joint_angles_left=None,
        joint_angles_right=None,
    ) -> np.ndarray:
        """
        1. YOLO result.plot() -> skeleton overlay frame
        2. cv2.putText -> HUD text (distance, footwork, parry, joint angles)
        3. Return annotated frame
        """
        # Draw skeleton via YOLO's built-in plotter
        if yolo_results and len(yolo_results) > 0:
            annotated = yolo_results[0].plot(
                kpt_radius=5,
                line_width=2,
                font_size=0.5,
            )
        else:
            annotated = frame.copy()

        # Build HUD lines
        hud_lines = self._build_hud_lines(
            pose_analysis, event_info,
            joint_angles_left=joint_angles_left,
            joint_angles_right=joint_angles_right,
        )

        if hud_lines:
            self._draw_hud(annotated, hud_lines)

        return annotated

    def _build_hud_lines(
        self,
        pose_analysis,
        event_info: Optional[dict],
        joint_angles_left=None,
        joint_angles_right=None,
    ) -> List[str]:
        """Build text lines for the HUD overlay."""
        lines: List[str] = []

        # Static event info (from report) — show first
        if event_info:
            if event_info.get("touch_label"):
                lines.append(event_info["touch_label"])

        # Distance from live pose analysis
        if pose_analysis and hasattr(pose_analysis, "distance_at_touch"):
            dist = pose_analysis.distance_at_touch
            if dist and dist.distance_bh is not None:
                zone = dist.distance_zone.value if dist.distance_zone else "?"
                lines.append(f"Dist: {dist.distance_bh:.2f} BH ({zone})")

        # Footwork from live analysis
        if pose_analysis and hasattr(pose_analysis, "footwork_left"):
            fl = pose_analysis.footwork_left
            fr = pose_analysis.footwork_right
            if fl or fr:
                fl_str = fl.footwork_type.value if fl else "?"
                fr_str = fr.footwork_type.value if fr else "?"
                lines.append(f"FW  L:{fl_str}  R:{fr_str}")

        # Parry from live analysis
        if pose_analysis and hasattr(pose_analysis, "parry_left"):
            parry_sides = []
            if pose_analysis.parry_left and pose_analysis.parry_left.parry_detected:
                parry_sides.append("L")
            if pose_analysis.parry_right and pose_analysis.parry_right.parry_detected:
                parry_sides.append("R")
            if parry_sides:
                lines.append(f"Parry: {', '.join(parry_sides)}")

        # Joint angles (per-frame, computed separately)
        ja_l_line = self._format_joint_angles(joint_angles_left, "L")
        ja_r_line = self._format_joint_angles(joint_angles_right, "R")
        if ja_l_line:
            lines.append(ja_l_line)
        if ja_r_line:
            lines.append(ja_r_line)

        return lines

    @staticmethod
    def _format_joint_angles(ja, side_label: str) -> Optional[str]:
        """Format a JointAngles object into a compact HUD string."""
        if ja is None:
            return None
        parts: List[str] = []
        if ja.front_knee_angle is not None:
            parts.append(f"Knee:{ja.front_knee_angle:.0f}")
        if ja.hip_angle is not None:
            parts.append(f"Hip:{ja.hip_angle:.0f}")
        if ja.trunk_lean_deg is not None:
            parts.append(f"Trunk:{ja.trunk_lean_deg:.0f}")
        if ja.arm_extension_ratio is not None:
            pct = ja.arm_extension_ratio * 100
            parts.append(f"Arm:{pct:.0f}%")
        if not parts:
            return None
        return f"{side_label}: {' '.join(parts)}"

    def _draw_hud(self, frame: np.ndarray, lines: List[str]) -> None:
        """Draw semi-transparent HUD box with text lines on top-left."""
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.6
        thickness = 1
        padding = 10
        line_height = 26

        # Calculate box size
        max_width = 0
        for line in lines:
            (w, _), _ = cv2.getTextSize(line, font, font_scale, thickness)
            max_width = max(max_width, w)

        box_w = max_width + 2 * padding
        box_h = len(lines) * line_height + 2 * padding

        # Draw semi-transparent background
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (box_w, box_h), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)

        # Draw text
        for i, line in enumerate(lines):
            y = padding + (i + 1) * line_height - 6
            cv2.putText(
                frame, line,
                (padding, y),
                font, font_scale, (255, 255, 255), thickness, cv2.LINE_AA,
            )

    def _extract_touch_info(self, touch: dict) -> dict:
        """Extract event_info dict from a touch entry in report JSON."""
        info: dict = {}
        tn = touch.get("touch_number", "?")
        score = touch.get("score_after", "")
        if tn or score:
            info["touch_label"] = f"Touch #{tn}: {score}"

        pa = touch.get("pose_analysis")
        if pa:
            info["distance_bh"] = pa.get("distance_bh")
            info["distance_zone"] = pa.get("distance_zone")
            info["footwork_scorer"] = pa.get("footwork_scorer")
            info["parry_detected"] = pa.get("parry_detected")
        return info

    def _extract_exchange_info(self, exchange: dict) -> dict:
        """Extract event_info dict from an exchange entry in report JSON."""
        info: dict = {}
        en = exchange.get("exchange_number", "?")
        etype = exchange.get("event_type_ko", exchange.get("event_type", ""))
        info["touch_label"] = f"Exchange #{en}: {etype}"

        fl = exchange.get("footwork_left")
        fr = exchange.get("footwork_right")
        if fl or fr:
            info["footwork_left"] = fl
            info["footwork_right"] = fr

        return info
