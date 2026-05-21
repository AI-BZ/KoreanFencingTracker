"""
Video quality assessment gate for fencing match analysis.

Evaluates whether a video meets minimum quality thresholds
for meaningful analysis, with profiles per source type.
"""

import cv2
import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple


@dataclass
class VideoQualityAssessment:
    """Quality assessment result for a video."""
    resolution_ok: bool
    fps_ok: bool
    duration_ok: bool
    brightness_ok: bool
    blur_score: float             # 0=blurry, higher=sharper
    fencer_detection_rate: float  # Fraction of sampled frames with 2 fencers
    overall_score: float          # 0-1 composite score
    can_analyze: bool             # Final gate decision
    rejection_reasons: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "resolution_ok": self.resolution_ok,
            "fps_ok": self.fps_ok,
            "duration_ok": self.duration_ok,
            "brightness_ok": self.brightness_ok,
            "blur_score": round(self.blur_score, 2),
            "fencer_detection_rate": round(self.fencer_detection_rate, 3),
            "overall_score": round(self.overall_score, 3),
            "can_analyze": self.can_analyze,
            "rejection_reasons": self.rejection_reasons,
            "recommendations": self.recommendations,
        }


# Source-type-specific quality profiles
_QUALITY_PROFILES: Dict[str, dict] = {
    "coach": {
        "min_resolution": (640, 480),
        "min_fps": 24,
        "min_duration": 10,
        "max_duration": 1800,
        "min_brightness": 40,
        "min_blur_score": 50,
        "min_fencer_rate": 0.5,
    },
    "parent": {
        "min_resolution": (640, 480),
        "min_fps": 24,
        "min_duration": 10,
        "max_duration": 1800,
        "min_brightness": 30,
        "min_blur_score": 30,
        "min_fencer_rate": 0.3,
    },
    "player": {
        "min_resolution": (480, 360),
        "min_fps": 24,
        "min_duration": 5,
        "max_duration": 1800,
        "min_brightness": 30,
        "min_blur_score": 30,
        "min_fencer_rate": 0.0,
    },
    "tv_broadcast": {
        "min_resolution": (640, 480),
        "min_fps": 24,
        "min_duration": 10,
        "max_duration": 7200,
        "min_brightness": 30,
        "min_blur_score": 50,
        "min_fencer_rate": 0.2,
    },
}


class QualityGate:
    """
    Video quality gate with source-type-specific profiles.

    Usage:
        qg = QualityGate()
        result = qg.assess("match.mp4", "coach")
        if not result.can_analyze:
            print(result.rejection_reasons)
    """

    def __init__(self, pose_estimator=None):
        self._pose_estimator = pose_estimator

    def assess(
        self,
        video_path: str,
        source_type: str = "coach",
    ) -> VideoQualityAssessment:
        """
        Assess video quality for analysis suitability.

        Args:
            video_path: Path to the video file.
            source_type: Video source type for profile selection.

        Returns:
            VideoQualityAssessment with pass/fail and recommendations.
        """
        profile = _QUALITY_PROFILES.get(source_type, _QUALITY_PROFILES["coach"])
        reasons: List[str] = []
        recommendations: List[str] = []

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return VideoQualityAssessment(
                resolution_ok=False, fps_ok=False, duration_ok=False,
                brightness_ok=False, blur_score=0.0,
                fencer_detection_rate=0.0, overall_score=0.0,
                can_analyze=False,
                rejection_reasons=["Cannot open video file"],
            )

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0.0

        # Resolution check
        min_w, min_h = profile["min_resolution"]
        resolution_ok = width >= min_w and height >= min_h
        if not resolution_ok:
            reasons.append(f"Resolution {width}x{height} below minimum {min_w}x{min_h}")
            recommendations.append(f"Record at {min_w}x{min_h} or higher")

        # FPS check
        fps_ok = fps >= profile["min_fps"]
        if not fps_ok:
            reasons.append(f"FPS {fps:.1f} below minimum {profile['min_fps']}")
            recommendations.append(f"Record at {profile['min_fps']}fps or higher")

        # Duration check
        duration_ok = profile["min_duration"] <= duration <= profile["max_duration"]
        if not duration_ok:
            if duration < profile["min_duration"]:
                reasons.append(f"Duration {duration:.1f}s too short (min {profile['min_duration']}s)")
            else:
                reasons.append(f"Duration {duration:.1f}s too long (max {profile['max_duration']}s)")
                recommendations.append("Trim video to relevant match segment")

        # Brightness and blur (sample a few frames)
        brightness_ok, blur_score = self._check_visual_quality(
            cap, total_frames, profile,
        )
        if not brightness_ok:
            reasons.append("Video appears too dark")
            recommendations.append("Ensure adequate lighting when recording")

        # Fencer detection rate
        fencer_rate = self._check_fencer_detection(cap, total_frames)
        fencer_ok = fencer_rate >= profile["min_fencer_rate"]
        if not fencer_ok and profile["min_fencer_rate"] > 0:
            reasons.append(
                f"Fencer detection rate {fencer_rate:.0%} below "
                f"minimum {profile['min_fencer_rate']:.0%}"
            )
            recommendations.append("Ensure both fencers are visible in frame")

        cap.release()

        # Composite score
        checks = [resolution_ok, fps_ok, duration_ok, brightness_ok, fencer_ok]
        score = sum(1.0 for c in checks if c) / len(checks)
        can_analyze = all([resolution_ok, fps_ok, duration_ok])

        if not recommendations and can_analyze:
            recommendations.append("Video meets quality requirements")

        return VideoQualityAssessment(
            resolution_ok=resolution_ok,
            fps_ok=fps_ok,
            duration_ok=duration_ok,
            brightness_ok=brightness_ok,
            blur_score=blur_score,
            fencer_detection_rate=fencer_rate,
            overall_score=score,
            can_analyze=can_analyze,
            rejection_reasons=reasons,
            recommendations=recommendations,
        )

    def _check_visual_quality(
        self,
        cap: cv2.VideoCapture,
        total_frames: int,
        profile: dict,
    ) -> Tuple[bool, float]:
        """Check brightness and blur from sampled frames."""
        if total_frames < 1:
            return False, 0.0

        sample_idx = min(30, total_frames - 1)
        cap.set(cv2.CAP_PROP_POS_FRAMES, sample_idx)
        ret, frame = cap.read()
        if not ret:
            return False, 0.0

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Brightness: mean pixel value
        brightness = float(np.mean(gray))
        brightness_ok = brightness >= profile["min_brightness"]

        # Blur: Laplacian variance (higher = sharper)
        blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        return brightness_ok, blur_score

    def _check_fencer_detection(
        self,
        cap: cv2.VideoCapture,
        total_frames: int,
    ) -> float:
        """Check fencer detection rate using pose estimator."""
        if self._pose_estimator is None or total_frames < 1:
            return 1.0  # Assume OK if no pose estimator

        sample_count = min(5, total_frames)
        indices = np.linspace(0, total_frames - 1, sample_count, dtype=int)
        detected = 0

        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if not ret:
                continue
            result = self._pose_estimator.estimate_pose(frame, int(idx))
            if len(result.fencers) >= 2:
                detected += 1

        return detected / sample_count if sample_count > 0 else 0.0
