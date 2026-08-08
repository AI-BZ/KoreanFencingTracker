"""
Data augmentation for fencing video clips.

Ported from fencing-AI/5-data_multiplier.py.
Doubles training data by horizontally flipping clips and
swapping L/R labels accordingly.
"""

import cv2
from pathlib import Path
from typing import List
from dataclasses import dataclass


@dataclass
class AugmentedClip:
    """Result of augmenting a clip."""
    source_path: Path
    output_path: Path
    original_label: str
    flipped_label: str


class DataAugmentor:
    """
    Augments labeled fencing clips by horizontal flipping.

    When a clip is flipped horizontally:
    - "L" (left scored) becomes "R" (right scored) and vice versa
    - "T" (tie/simultaneous) stays "T"
    - Video is mirrored left-right
    """

    LABEL_FLIP_MAP = {
        "L": "R",
        "R": "L",
        "T": "T",
    }

    def __init__(self, output_dir: str = "data/labeled"):
        self.output_dir = Path(output_dir)

    def flip_clip(self, clip_path: Path, label: str) -> AugmentedClip:
        """
        Flip a single clip horizontally and save with swapped label.

        Args:
            clip_path: Path to the source clip.
            label: Original label ("L", "R", or "T").

        Returns:
            AugmentedClip with output path and new label.
        """
        flipped_label = self.LABEL_FLIP_MAP.get(label, label)
        output_subdir = self.output_dir / flipped_label
        output_subdir.mkdir(parents=True, exist_ok=True)

        output_path = output_subdir / f"{clip_path.stem}_flipped.mp4"

        cap = cv2.VideoCapture(str(clip_path))
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open clip: {clip_path}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            flipped = cv2.flip(frame, 1)  # horizontal flip
            writer.write(flipped)

        cap.release()
        writer.release()

        return AugmentedClip(
            source_path=clip_path,
            output_path=output_path,
            original_label=label,
            flipped_label=flipped_label,
        )

    def augment_directory(self, labeled_dir: str) -> List[AugmentedClip]:
        """
        Augment all labeled clips in a directory.

        Expects subdirectories named "L", "R", "T" containing clips.

        Args:
            labeled_dir: Root directory with label subdirectories.

        Returns:
            List of AugmentedClips created.
        """
        source = Path(labeled_dir)
        results: List[AugmentedClip] = []

        for label in ("L", "R", "T"):
            label_dir = source / label
            if not label_dir.exists():
                continue

            clips = list(label_dir.glob("*.mp4"))
            # Exclude already-flipped clips
            clips = [c for c in clips if "_flipped" not in c.stem]

            for clip in clips:
                try:
                    result = self.flip_clip(clip, label)
                    results.append(result)
                except Exception as e:
                    print(f"  Failed to flip {clip.name}: {e}")

        print(f"  Augmented {len(results)} clips (L↔R swap + horizontal flip)")
        return results


if __name__ == "__main__":
    import sys

    labeled_dir = sys.argv[1] if len(sys.argv) > 1 else "data/labeled"
    augmentor = DataAugmentor()
    augmentor.augment_directory(labeled_dir)
