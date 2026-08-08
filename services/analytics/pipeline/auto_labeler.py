"""
Automatic clip labeling based on score changes.

Ported from fencing-AI/3-data_labeller.py.
Uses v3's ScoreReader to determine who scored (L/R/T) by comparing
scores between consecutive clips.
"""

import cv2
import shutil
from pathlib import Path
from typing import Optional, Tuple, List
from dataclasses import dataclass

from analyzer.score_reader import ScoreReader
from analyzer.lamp_detector import LampDetector
from analyzer.models import LampState


@dataclass
class LabeledClip:
    """A clip with its determined label."""
    clip_path: Path
    label: str  # "L" (left scored), "R" (right scored), "T" (tie/simultaneous), "X" (unknown)
    score_before: Tuple[Optional[int], Optional[int]]
    score_after: Tuple[Optional[int], Optional[int]]
    lamp_state: str  # "On-On", "On-Off", "Off-On", etc.


class AutoLabeler:
    """
    Labels fencing clips by analyzing score changes between consecutive clips.

    For each clip where both lamps are on (simultaneous touch), determines
    who received priority by checking the score change in the next clip.
    """

    def __init__(self, rois: dict, template_path: Optional[Path] = None):
        self.rois = rois
        self.score_reader = ScoreReader(template_path=template_path)
        self.lamp_detector = LampDetector()

    def check_lights(self, frame) -> str:
        """
        Determine lamp state from the last frame of a clip.

        Returns:
            String like "On-On", "On-Off", "Off-On", "Off-Off",
            or "On-No", "No-On" if only one side is detected.
        """
        lamp = self.lamp_detector.detect_both(frame, self.rois)

        left = "On" if lamp.red else "No"
        right = "On" if lamp.green else "No"

        return f"{left}-{right}"

    def check_score(self, frame) -> Tuple[Optional[int], Optional[int]]:
        """Read score from a frame."""
        return self.score_reader.read_score_from_display(frame, self.rois)

    def determine_label(
        self,
        hit_type: str,
        left: Optional[int],
        right: Optional[int],
        update_left: Optional[int],
        update_right: Optional[int],
    ) -> str:
        """
        Determine who scored based on lamp state and score change.

        Args:
            hit_type: Lamp state string (e.g. "On-On").
            left, right: Scores at end of current clip.
            update_left, update_right: Scores at start of next clip.

        Returns:
            "L" (left), "R" (right), "T" (tie), or "X" (unknown).
        """
        if any(v is None for v in (left, right, update_left, update_right)):
            return "X"

        left_delta = update_left - left
        right_delta = update_right - right

        if hit_type == "On-On":
            # Both lamps: priority decision
            if left_delta == 1 and right_delta == 0:
                return "L"
            elif left_delta == 0 and right_delta == 1:
                return "R"
            elif left_delta == 0 and right_delta == 0:
                return "T"  # No score change = simultaneous annulled
        elif hit_type == "On-No":
            # Only left lamp
            if left_delta == 1 and right_delta == 0:
                return "L"
            elif left_delta == 0:
                return "R"  # Off-target, right gets point
        elif hit_type == "No-On":
            # Only right lamp
            if right_delta == 1 and left_delta == 0:
                return "R"
            elif right_delta == 0:
                return "L"  # Off-target, left gets point

        return "X"

    def label_clips(
        self,
        clip_dir: str,
        output_dir: str = "data/labeled",
    ) -> List[LabeledClip]:
        """
        Label all clips in a directory.

        Clips should be named sequentially (e.g. video_clip0001.mp4).
        The labeler reads the last frame of each clip and the first
        frame of the next clip to determine score changes.

        Args:
            clip_dir: Directory containing clips.
            output_dir: Directory for labeled clips (organized by label).

        Returns:
            List of LabeledClips.
        """
        clip_path = Path(clip_dir)
        out = Path(output_dir)

        # Create label subdirectories
        for label in ("L", "R", "T", "X"):
            (out / label).mkdir(parents=True, exist_ok=True)

        clips = sorted(clip_path.glob("*.mp4"))
        if not clips:
            print(f"  No clips found in {clip_dir}")
            return []

        results: List[LabeledClip] = []

        for i, clip_file in enumerate(clips):
            # Read last frame of current clip
            cap = cv2.VideoCapture(str(clip_file))
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, total - 1))
            ret, last_frame = cap.read()
            cap.release()

            if not ret:
                continue

            hit_type = self.check_lights(last_frame)
            left, right = self.check_score(last_frame)

            # Only label clips with meaningful lamp states
            if hit_type not in ("On-On", "On-No", "No-On"):
                continue

            # Read first frame of next clip for score update
            if i + 1 < len(clips):
                cap_next = cv2.VideoCapture(str(clips[i + 1]))
                ret_next, first_frame = cap_next.read()
                cap_next.release()

                if not ret_next:
                    continue

                update_left, update_right = self.check_score(first_frame)
            else:
                continue  # Can't label last clip without next

            label = self.determine_label(hit_type, left, right, update_left, update_right)

            if label != "X":
                # Copy to labeled directory
                dest = out / label / clip_file.name
                shutil.copy2(clip_file, dest)

                results.append(LabeledClip(
                    clip_path=dest,
                    label=label,
                    score_before=(left, right),
                    score_after=(update_left, update_right),
                    lamp_state=hit_type,
                ))

        print(f"  Labeled {len(results)} clips: "
              f"L={sum(1 for r in results if r.label == 'L')}, "
              f"R={sum(1 for r in results if r.label == 'R')}, "
              f"T={sum(1 for r in results if r.label == 'T')}")
        return results


if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 3:
        print("Usage: python -m pipeline.auto_labeler <clips_dir> <rois.json>")
        sys.exit(1)

    clip_dir = sys.argv[1]
    with open(sys.argv[2]) as f:
        rois_raw = json.load(f)
    rois = {k: tuple(v) for k, v in rois_raw.items()}

    labeler = AutoLabeler(rois=rois)
    labeler.label_clips(clip_dir)
