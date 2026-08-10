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
import io
import json
import os
import random
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import cv2
import numpy as np

from ml.training.config import (
    DATA_DIR,
    FACTS_DATA_DIR,
    FACTS_CSV_PATH,
    FACTS_ZIP_PATH,
    FACTS_CLIP_INDEX_PATH,
    FACTS_CSV_LABEL_MAP,
    LABELS_FILE,
    LABEL_TO_IDX,
    IDX_TO_LABEL,
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


class FACTSCsvZipDataset(FencingActionDataset):
    """
    Streaming adapter for the FACTS dataset stored as nested ZIPs.

    Reads ``filtered_data_800_fencing.csv`` for annotations and streams
    video clips directly from the 30.3 GB nested ZIP archive without
    extracting to disk.

    Outer ZIP (``facts_dataset.zip``) contains 16 inner ZIPs, each
    holding bout clips.  ``clip_index.json`` maps each clip path to its
    containing inner ZIP.

    Data leakage prevention:
        Unique clips are split into train/val/test *first*, then all CSV
        rows for each split's clips are included.  This preserves the
        FACTS oversampling strategy while preventing the same clip from
        appearing in multiple splits.
    """

    def __init__(
        self,
        facts_dir: Optional[Path] = None,
        csv_path: Optional[Path] = None,
        clip_index_path: Optional[Path] = None,
        zip_path: Optional[Path] = None,
        split: str = "train",
        num_frames: int = NUM_FRAMES,
        augment: bool = False,
        seed: int = 42,
        max_cached_zips: int = 2,
    ):
        # Bypass FencingActionDataset.__init__ — we set everything manually.
        self.facts_dir = Path(facts_dir) if facts_dir else FACTS_DATA_DIR
        self.csv_path = Path(csv_path) if csv_path else FACTS_CSV_PATH
        self.clip_index_path = (
            Path(clip_index_path) if clip_index_path else FACTS_CLIP_INDEX_PATH
        )
        self.zip_path = Path(zip_path) if zip_path else FACTS_ZIP_PATH
        self.split = split
        self.num_frames = num_frames
        self.augment = augment and split == "train"
        self.seed = seed

        # Inner ZIP LRU cache
        self._max_cached_zips = max_cached_zips
        self._outer_zip: Optional[zipfile.ZipFile] = None
        self._inner_cache: Dict[str, zipfile.ZipFile] = {}  # name → ZipFile
        self._inner_order: List[str] = []  # LRU order (most recent last)

        # clip_path (str) → inner ZIP name (str)
        self._clip_index: Dict[str, str] = {}

        # (clip_path_str, label_idx) pairs
        self.samples: List[Tuple[str, int]] = []
        self._load_and_split()

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_and_split(self):
        """Read CSV + clip_index.json, split by unique clips, then expand."""
        # Load clip index
        if not self.clip_index_path.exists():
            return
        with open(self.clip_index_path, "r", encoding="utf-8") as f:
            self._clip_index = json.load(f)

        if not self.csv_path.exists():
            return

        # Read CSV — group rows by normalised clip path
        # clip_path → list of label_idx
        clip_rows: Dict[str, List[int]] = {}
        with open(self.csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                raw_path = row.get("video_url", "").strip()
                label_str = row.get("label", "").strip()

                # Normalise label (CSV title-case → config snake_case)
                norm_label = FACTS_CSV_LABEL_MAP.get(label_str)
                if norm_label is None:
                    continue
                label_idx = LABEL_TO_IDX.get(norm_label)
                if label_idx is None:
                    continue

                # Strip ``storage/`` prefix to match ZIP internal paths
                clip_key = raw_path
                if clip_key.startswith("storage/"):
                    clip_key = clip_key[len("storage/"):]

                # Only keep clips present in the ZIP
                if clip_key not in self._clip_index:
                    continue

                clip_rows.setdefault(clip_key, []).append(label_idx)

        if not clip_rows:
            return

        # Skip clips with conflicting labels (only 1 known)
        clean_clips: Dict[str, List[int]] = {}
        for clip_key, labels in clip_rows.items():
            unique_labels = set(labels)
            if len(unique_labels) > 1:
                continue  # conflicting — skip
            clean_clips[clip_key] = labels

        # Split unique clips into train/val/test (data leakage prevention)
        unique_keys = sorted(clean_clips.keys())
        rng = random.Random(self.seed)
        rng.shuffle(unique_keys)

        n = len(unique_keys)
        train_end = int(n * TRAIN_RATIO)
        val_end = train_end + int(n * VAL_RATIO)

        if self.split == "train":
            split_keys = set(unique_keys[:train_end])
        elif self.split == "val":
            split_keys = set(unique_keys[train_end:val_end])
        elif self.split == "test":
            split_keys = set(unique_keys[val_end:])
        else:
            split_keys = set(unique_keys)

        # Expand: include ALL CSV rows for each split's clips
        for clip_key in sorted(split_keys):
            for label_idx in clean_clips[clip_key]:
                self.samples.append((clip_key, label_idx))

    # ------------------------------------------------------------------
    # Clip loading (streaming from nested ZIPs)
    # ------------------------------------------------------------------

    def __getitem__(self, idx: int) -> Tuple[List[np.ndarray], int]:
        clip_key, label_idx = self.samples[idx]
        frames = self._load_clip_frames(clip_key)
        frames = self._sample_frames(frames)

        if self.augment:
            frames, label_idx = self._apply_augmentation(frames, label_idx)

        return frames, label_idx

    def _load_clip_frames(self, clip_key: str) -> List[np.ndarray]:
        """Extract a clip from the nested ZIP into a temp file, read frames."""
        inner_name = self._clip_index.get(clip_key)
        if inner_name is None:
            return []

        inner_zip = self._get_inner_zip(inner_name)
        if inner_zip is None:
            return []

        try:
            clip_data = inner_zip.read(clip_key)
        except (KeyError, zipfile.BadZipFile):
            return []

        # Write to a temp file (cv2.VideoCapture needs a file path)
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".mp4")
        try:
            os.write(tmp_fd, clip_data)
            os.close(tmp_fd)

            frames: List[np.ndarray] = []
            cap = cv2.VideoCapture(tmp_path)
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                frames.append(frame[:, :, ::-1].copy())  # BGR → RGB
            cap.release()
            return frames
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def _get_inner_zip(self, inner_name: str) -> Optional[zipfile.ZipFile]:
        """Return a ZipFile for *inner_name*, using an LRU cache."""
        # Cache hit — move to end (most recently used)
        if inner_name in self._inner_cache:
            self._inner_order.remove(inner_name)
            self._inner_order.append(inner_name)
            return self._inner_cache[inner_name]

        # Ensure outer ZIP is open
        if self._outer_zip is None:
            if not self.zip_path.exists():
                return None
            self._outer_zip = zipfile.ZipFile(str(self.zip_path), "r")

        # Evict oldest if at capacity
        while len(self._inner_cache) >= self._max_cached_zips:
            oldest = self._inner_order.pop(0)
            self._inner_cache[oldest].close()
            del self._inner_cache[oldest]

        # Load inner ZIP into memory (BytesIO)
        try:
            raw = self._outer_zip.read(inner_name)
        except (KeyError, zipfile.BadZipFile):
            return None

        buf = io.BytesIO(raw)
        try:
            zf = zipfile.ZipFile(buf, "r")
        except zipfile.BadZipFile:
            return None

        self._inner_cache[inner_name] = zf
        self._inner_order.append(inner_name)
        return zf

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def get_class_distribution(self) -> Dict[str, int]:
        """Return {label_name: count} for all samples in this split."""
        from collections import Counter
        counts = Counter(label for _, label in self.samples)
        return {
            IDX_TO_LABEL.get(idx, f"idx_{idx}"): count
            for idx, count in sorted(counts.items())
        }

    def close(self):
        """Release all open ZIP handles."""
        for zf in self._inner_cache.values():
            zf.close()
        self._inner_cache.clear()
        self._inner_order.clear()
        if self._outer_zip is not None:
            self._outer_zip.close()
            self._outer_zip = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
