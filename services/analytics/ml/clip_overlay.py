"""
Generate overlay video clips for fencing events (touches/exchanges).

Uses YOLO11-Pose for skeleton overlay and cv2.putText for
distance/footwork/parry HUD text.
"""

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

from ml.pose_estimator import PisteGate, PoseEstimator
from ml.pose_analyzer import PoseAnalyzer

_logger = logging.getLogger(__name__)

# services/analytics — piste configs record `work_files`/CLI paths relative to it.
_SERVICE_ROOT = Path(__file__).resolve().parent.parent

# Fallbacks for the optional `piste.pose_*` tunables. These mirror
# PISTE_DEFAULT_* in scripts/generate_continuous_report.py, which is what the
# report was actually analysed with when a config omits them. Using the plain
# PoseEstimator defaults here instead would silently re-create the referee bug.
_PISTE_DEFAULT_POSE_CONF = 0.35
_PISTE_DEFAULT_POSE_IMGSZ = 1280
_PISTE_DEFAULT_POSE_MAX_DET = 8


class ClipOverlayGenerator:
    """Generate overlay clips for touch/exchange events."""

    def __init__(
        self,
        model_path: Optional[str] = None,
        pad_seconds: float = 2.0,
        pad_before: Optional[float] = None,
        pad_after: Optional[float] = None,
        piste_gate: Optional[PisteGate] = None,
        imgsz: Optional[int] = None,
        max_det: Optional[int] = None,
        confidence: Optional[float] = None,
    ):
        """
        Args:
            model_path: YOLO11-Pose weights; estimator default when omitted.
            pad_seconds: Symmetric clip padding, in seconds.
            pad_before/pad_after: Asymmetric overrides for `pad_seconds`.
            piste_gate: Target-piste foot-band gate, in WORK-FILE pixels. Must
                match the gate the report was analysed with.
            imgsz/max_det/confidence: PoseEstimator overrides. Every one of
                these is `None` by default and only supplied arguments are
                forwarded, so the no-argument call builds exactly the estimator
                it always did — TV-broadcast clips are unaffected.
        """
        estimator_kwargs: Dict[str, Any] = {}
        if confidence is not None:
            estimator_kwargs["confidence"] = confidence
        if imgsz is not None:
            estimator_kwargs["imgsz"] = imgsz
        if max_det is not None:
            estimator_kwargs["max_det"] = max_det
        if piste_gate is not None:
            estimator_kwargs["piste_gate"] = piste_gate

        self.estimator = PoseEstimator(model_path=model_path, **estimator_kwargs)
        self.analyzer = PoseAnalyzer()
        self.pad_seconds = pad_seconds
        self.pad_before = pad_before  # None → falls back to pad_seconds
        self.pad_after = pad_after    # None → falls back to pad_seconds

    # ------------------------------------------------------------------
    # Construction from a report
    # ------------------------------------------------------------------

    @classmethod
    def for_report(
        cls,
        report_dict: dict,
        *,
        base_dir=None,
        **kwargs,
    ) -> "ClipOverlayGenerator":
        """
        Build a generator whose pose settings match how the report was analysed.

        A report analysed with `--piste-config` was gated to one piste with a
        wide detection pool; re-running the clip overlay with the stock
        estimator would draw the foreground referee instead of the fencers
        (measured referee confidence 0.84-0.90 vs fencers 0.55-0.85). This reads
        `meta.piste_config` back out of the report and reproduces those settings.

        Reports outlive their config files and this runs inside a web request,
        so every failure mode — no `meta.piste_config`, a path that no longer
        resolves, unreadable or malformed JSON, a `piste` block without a usable
        `foot_band_work` — degrades to the plain default generator with a
        warning. It never raises: a clip drawn with default pose settings is a
        degraded clip, an exception is a 500.

        Args:
            report_dict: Parsed report JSON.
            base_dir: Directory to resolve a relative `meta.piste_config`
                against first (typically the report's own directory). The
                current directory and the service root are tried after it.
            **kwargs: Passed through to `__init__` (pad_before, pad_after, ...).
                Explicit values win over anything derived from the config.
        """
        try:
            settings = cls._piste_estimator_settings(report_dict, base_dir=base_dir)
        except Exception:  # never let clip generation die on a config problem
            _logger.warning(
                "Unexpected error reading piste config from report meta; "
                "falling back to default pose settings",
                exc_info=True,
            )
            settings = {}

        settings.update(kwargs)
        return cls(**settings)

    @classmethod
    def _piste_estimator_settings(
        cls,
        report_dict: dict,
        base_dir=None,
    ) -> Dict[str, Any]:
        """
        Derive `__init__` pose kwargs from `report_dict["meta"]["piste_config"]`.

        Returns an empty dict — i.e. "construct the default generator" — for
        every report that has no usable piste config, including plain TV reports.
        """
        meta = report_dict.get("meta") if isinstance(report_dict, dict) else None
        raw = meta.get("piste_config") if isinstance(meta, dict) else None
        if not raw:
            # TV-shaped report: the default estimator is correct, not degraded.
            return {}

        path = cls._resolve_piste_config_path(raw, base_dir=base_dir)
        if path is None:
            _logger.warning(
                "Piste config %r referenced by the report was not found; "
                "clip overlay falls back to default pose settings",
                str(raw),
            )
            return {}

        try:
            with open(path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            _logger.warning(
                "Piste config %s could not be read (%s); clip overlay falls "
                "back to default pose settings", path, exc,
            )
            return {}

        piste = config.get("piste") if isinstance(config, dict) else None
        if not isinstance(piste, dict):
            _logger.warning(
                "Piste config %s has no 'piste' object; clip overlay falls back "
                "to default pose settings", path,
            )
            return {}

        gate = cls._build_piste_gate(piste.get("foot_band_work"))
        if gate is None:
            # Without the foot band there is no gate, and a raised max_det on
            # its own is strictly worse than the default — it widens the pool
            # with nothing to filter it.
            _logger.warning(
                "Piste config %s has no usable 'piste.foot_band_work' (%r); "
                "clip overlay falls back to default pose settings",
                path, piste.get("foot_band_work"),
            )
            return {}

        return {
            "piste_gate": gate,
            "confidence": cls._positive_number(
                piste, "pose_conf", _PISTE_DEFAULT_POSE_CONF, float, path,
            ),
            "imgsz": cls._positive_number(
                piste, "pose_imgsz", _PISTE_DEFAULT_POSE_IMGSZ, int, path,
            ),
            "max_det": cls._positive_number(
                piste, "pose_max_det", _PISTE_DEFAULT_POSE_MAX_DET, int, path,
            ),
        }

    @staticmethod
    def _resolve_piste_config_path(raw, base_dir=None) -> Optional[Path]:
        """
        Resolve `meta.piste_config`, which is stored exactly as typed on the CLI.

        Absolute paths are used as-is. Relative ones are tried against
        `base_dir` (when given), then the current directory, then the service
        root. Returns None when no candidate exists.
        """
        candidate = Path(str(raw)).expanduser()
        if candidate.is_absolute():
            return candidate if candidate.exists() else None

        roots = []
        if base_dir is not None:
            roots.append(Path(base_dir))
        roots.append(Path.cwd())
        roots.append(_SERVICE_ROOT)

        for root in roots:
            resolved = root / candidate
            if resolved.exists():
                return resolved
        return None

    @staticmethod
    def _build_piste_gate(band) -> Optional[PisteGate]:
        """Build a PisteGate from `piste.foot_band_work`, or None if unusable."""
        if isinstance(band, (str, bytes)) or not isinstance(band, (list, tuple)):
            return None
        if len(band) != 2:
            return None
        if any(isinstance(v, bool) for v in band):
            return None
        try:
            y_min, y_max = float(band[0]), float(band[1])
        except (TypeError, ValueError):
            return None
        if not y_min < y_max:  # also rejects NaN
            return None
        return PisteGate(y_min, y_max)

    @staticmethod
    def _positive_number(piste: dict, key: str, default, kind, path):
        """Read an optional positive `piste.<key>`, falling back to `default`."""
        value = piste.get(key)
        if value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _logger.warning(
                "Piste config %s has non-numeric 'piste.%s' (%r); using %r",
                path, key, value, default,
            )
            return default
        if not value > 0:
            _logger.warning(
                "Piste config %s has non-positive 'piste.%s' (%r); using %r",
                path, key, value, default,
            )
            return default
        return kind(value)

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

                # Run YOLO.
                # max_det MUST come from the estimator, never a literal: it is a
                # YOLO *call* argument, so anyone it cuts is never returned and
                # cannot be recovered downstream. Hardcoding 2 hands back the two
                # highest-confidence people, which on a multi-piste recording is
                # the foreground referee and scorer (conf 0.84-0.90), not the
                # fencers (0.55-0.85) — and would starve the piste gate entirely.
                self.estimator._load_model()
                yolo_results = self.estimator._model(
                    frame,
                    device=self.estimator.device,
                    imgsz=self.estimator.imgsz,
                    conf=self.estimator.confidence,
                    max_det=self.estimator.max_det,
                    verbose=False,
                )

                # Parse for PoseAnalyzer (applies the piste gate when set)
                pose_result = self.estimator._parse_results(yolo_results)

                # Build pose analysis for this frame
                from analyzer.models import PoseResult as PR
                pr = PR(frame_idx=frame_idx, fencers=pose_result, inference_time_ms=0)
                analysis = self.analyzer.analyze([pr])

                # Compute per-frame joint angles directly
                ja_left = self.analyzer._compute_joint_angles_for_side(pr, "left")
                ja_right = self.analyzer._compute_joint_angles_for_side(pr, "right")

                # Draw skeleton overlay — only for the people the gate kept
                annotated = self._annotate_frame(
                    frame,
                    self._gated_yolo_results(yolo_results, pose_result),
                    analysis, event_info,
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
                duration = (ef - sf + int(pb * fps) + int(pa * fps) + 1) / fps
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

    def _gated_yolo_results(self, yolo_results, fencers):
        """
        Narrow the YOLO result to the people the piste gate kept, for drawing.

        `Results.plot()` draws *every* detection in the result. Raising
        `max_det` for the gate therefore has a side effect on the overlay: the
        eight-person candidate pool would all be drawn, referee included. The
        gate's verdict lives in the parsed `fencers`, so the plotted result is
        re-indexed to match it.

        Without a gate this is a no-op — the non-gate path is left byte-for-byte
        as it was. Any problem re-indexing falls back to the unfiltered result,
        because a clip with extra skeletons beats no clip at all.
        """
        if self.estimator.piste_gate is None:
            return yolo_results
        if not yolo_results or len(yolo_results) == 0:
            return yolo_results

        try:
            result = yolo_results[0]
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                return yolo_results
            boxes_data = boxes.data.cpu().numpy()

            # FencerPose.bbox is float() of these exact values, so identity of
            # the 4-tuple is an exact match, not a tolerance comparison.
            wanted = {tuple(f.bbox) for f in fencers}
            keep = [
                i for i, box in enumerate(boxes_data)
                if (float(box[0]), float(box[1]),
                    float(box[2]), float(box[3])) in wanted
            ]
            if len(keep) == len(boxes_data):
                return yolo_results
            if not keep:
                # Nobody on the target piste this frame (halt, occlusion) —
                # draw the raw frame rather than someone else's skeleton.
                return []
            return [result[keep]]
        except Exception:
            _logger.debug(
                "Could not restrict overlay to gated fencers; drawing all "
                "detections", exc_info=True,
            )
            return yolo_results

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

        # Footwork: prefer the report's values over the live single-frame analysis.
        #
        # `analysis` here is computed from ONE frame, and footwork is inherently
        # temporal — you cannot tell advance from retreat without a window — so
        # the live values are ~always None and the HUD rendered
        # "FW L:unknown R:unknown" even for an exchange the report had labelled
        # fleche/advance. The report's per-exchange footwork is derived over the
        # whole exchange and is the number the viewer is being shown elsewhere,
        # so it is what belongs on the clip. Live values remain the fallback for
        # callers that pass no event_info.
        fl_str = fr_str = None
        if event_info:
            fl_str = event_info.get("footwork_left")
            fr_str = event_info.get("footwork_right")
        if fl_str is None and fr_str is None and pose_analysis and hasattr(
            pose_analysis, "footwork_left"
        ):
            fl = pose_analysis.footwork_left
            fr = pose_analysis.footwork_right
            if fl or fr:
                fl_str = fl.footwork_type.value if fl else None
                fr_str = fr.footwork_type.value if fr else None
        if fl_str is not None or fr_str is not None:
            lines.append(f"FW  L:{fl_str or '?'}  R:{fr_str or '?'}")

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
