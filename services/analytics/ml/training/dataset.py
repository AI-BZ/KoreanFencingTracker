"""
FencingActionDataset for VideoMAE fine-tuning.

Reads labeled fencing clips, samples NUM_FRAMES per clip,
and returns tensors ready for VideoMAEForVideoClassification.

Expected directory structure:
    data/labeled/
    ├── labels.csv          # columns: clip_path, action_label
    └── clips/
        ├── clip_001.mp4
        ├── clip_002.mp4
        └── ...

labels.csv format:
    clip_path,action_label
    clips/clip_001.mp4,attack
    clips/clip_002.mp4,riposte
"""

import csv
import random
from pathlib import Path
from typing import List, Tuple, Optional

import cv2
import numpy as np

from ml.training.config import (
    DATA_DIR,
    FACTS_DATA_DIR,
    LABELS_FILE,
    LABEL_TO_IDX,
    FACTS_CLASS_CODES,
    FLIP_LABEL_MAP,
    NUM_FRAMES,
    TRAIN_RATIO,
    VAL_RATIO,
    HORIZONTAL_FLIP_PROB,
    COLOR_JITTER,
)


class FencingActionDataset:
    """
    Dataset for fencing action clips.

    Compatible with both PyTorch DataLoader and manual iteration.
    Returns (frames_list, label_idx) tuples where frames_list is
    a list of NUM_FRAMES RGB numpy arrays.
    """

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        labels_file: Optional[Path] = None,
        split: str = "train",
        num_frames: int = NUM_FRAMES,
        augment: bool = False,
        seed: int = 42,
    ):
        self.data_dir = Path(data_dir) if data_dir else DATA_DIR
        self.labels_file = Path(labels_file) if labels_file else LABELS_FILE
        self.split = split
        self.num_frames = num_frames
        self.augment = augment and split == "train"
        self.seed = seed

        self.samples: List[Tuple[Path, int]] = []
        self._load_and_split()

    def _load_and_split(self):
        """Load labels.csv and split into train/val/test."""
        all_samples: List[Tuple[Path, int]] = []

        if not self.labels_file.exists():
            return

        with open(self.labels_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                clip_path = self.data_dir / row["clip_path"]
                label_str = row["action_label"].strip().lower()
                if label_str not in LABEL_TO_IDX:
                    continue
                all_samples.append((clip_path, LABEL_TO_IDX[label_str]))

        if not all_samples:
            return

        # Deterministic shuffle + split
        rng = random.Random(self.seed)
        rng.shuffle(all_samples)

        n = len(all_samples)
        train_end = int(n * TRAIN_RATIO)
        val_end = train_end + int(n * VAL_RATIO)

        if self.split == "train":
            self.samples = all_samples[:train_end]
        elif self.split == "val":
            self.samples = all_samples[train_end:val_end]
        elif self.split == "test":
            self.samples = all_samples[val_end:]
        else:
            self.samples = all_samples

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int) -> Tuple[List[np.ndarray], int]:
        clip_path, label_idx = self.samples[idx]
        frames = self._load_clip_frames(clip_path)
        frames = self._sample_frames(frames)

        if self.augment:
            frames, label_idx = self._apply_augmentation(frames, label_idx)

        return frames, label_idx

    def _load_clip_frames(self, clip_path: Path) -> List[np.ndarray]:
        """Load all frames from a video clip as RGB numpy arrays."""
        frames: List[np.ndarray] = []
        cap = cv2.VideoCapture(str(clip_path))

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            # BGR → RGB
            frames.append(frame[:, :, ::-1].copy())

        cap.release()
        return frames

    def _sample_frames(self, frames: List[np.ndarray]) -> List[np.ndarray]:
        """Sample or pad to exactly num_frames."""
        n = len(frames)
        if n == 0:
            # Return black frames as fallback
            return [np.zeros((224, 224, 3), dtype=np.uint8)] * self.num_frames

        if n == self.num_frames:
            return frames

        if n > self.num_frames:
            indices = np.linspace(0, n - 1, self.num_frames, dtype=int)
            return [frames[i] for i in indices]

        # Pad by repeating last frame
        padded = list(frames)
        while len(padded) < self.num_frames:
            padded.append(frames[-1])
        return padded

    def _apply_augmentation(
        self, frames: List[np.ndarray], label_idx: int = -1,
    ) -> Tuple[List[np.ndarray], int]:
        """Apply data augmentation to frame sequence.

        When horizontal flip is applied, the label is swapped using
        FLIP_LABEL_MAP (left↔right) so direction-encoded FACTS labels
        stay consistent with the flipped video.
        """
        # Horizontal flip (consistent across all frames in clip)
        if random.random() < HORIZONTAL_FLIP_PROB:
            frames = [np.fliplr(f).copy() for f in frames]
            # Swap direction-encoded label (left↔right)
            if label_idx in FLIP_LABEL_MAP:
                label_idx = FLIP_LABEL_MAP[label_idx]

        # Color jitter (same random values for all frames)
        if COLOR_JITTER > 0:
            brightness = 1.0 + random.uniform(-COLOR_JITTER, COLOR_JITTER)
            frames = [
                np.clip(f.astype(np.float32) * brightness, 0, 255).astype(np.uint8)
                for f in frames
            ]

        return frames, label_idx

    def get_class_weights(self) -> List[float]:
        """Compute inverse-frequency weights for class balancing."""
        from collections import Counter
        counts = Counter(label for _, label in self.samples)
        total = len(self.samples)
        num_classes = len(LABEL_TO_IDX)
        weights = []
        for i in range(num_classes):
            c = counts.get(i, 1)
            weights.append(total / (num_classes * c))
        return weights


class FACTSDatasetAdapter:
    """
    Adapter for the FACTS dataset directory structure.

    FACTS organises clips into sub-directories named by class code:
        data/facts/
        ├── AL/          # Attack Left
        │   ├── clip_001.mp4
        │   └── ...
        ├── AR/          # Attack Right
        ├── RL/          # Riposte Left
        ├── RR/          # Riposte Right
        ├── CAL/         # Counter-Attack Left
        ├── CAR/         # Counter-Attack Right
        ├── ReL/         # Remise Left
        └── ReR/         # Remise Right

    This adapter converts the directory structure into a labels.csv
    file compatible with :class:`FencingActionDataset`, or can be
    used directly to iterate over (clip_path, label_idx) pairs.
    """

    VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}

    def __init__(
        self,
        facts_dir: Optional[Path] = None,
    ):
        self.facts_dir = Path(facts_dir) if facts_dir else FACTS_DATA_DIR
        self.samples: List[Tuple[Path, int]] = []
        self._scan()

    def _scan(self):
        """Scan FACTS directory for clips organised by class code."""
        if not self.facts_dir.exists():
            return

        for code, label_str in FACTS_CLASS_CODES.items():
            class_dir = self.facts_dir / code
            if not class_dir.is_dir():
                continue

            label_idx = LABEL_TO_IDX.get(label_str)
            if label_idx is None:
                continue

            for clip_file in sorted(class_dir.iterdir()):
                if clip_file.suffix.lower() in self.VIDEO_EXTENSIONS:
                    self.samples.append((clip_file, label_idx))

    def __len__(self) -> int:
        return len(self.samples)

    def to_csv(self, output_path: Path) -> int:
        """
        Write a labels.csv compatible with FencingActionDataset.

        Args:
            output_path: Path to write the CSV file.

        Returns:
            Number of samples written.
        """
        from ml.training.config import IDX_TO_LABEL

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8", newline="") as f:
            f.write("clip_path,action_label\n")
            for clip_path, label_idx in self.samples:
                label_str = IDX_TO_LABEL.get(label_idx, "unknown")
                f.write(f"{clip_path},{label_str}\n")
        return len(self.samples)

    def get_class_distribution(self) -> dict:
        """Return {label_name: count} for all discovered clips."""
        from collections import Counter
        from ml.training.config import IDX_TO_LABEL

        counts = Counter(idx for _, idx in self.samples)
        return {
            IDX_TO_LABEL.get(idx, f"idx_{idx}"): count
            for idx, count in sorted(counts.items())
        }
