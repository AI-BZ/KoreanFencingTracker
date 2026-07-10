"""
Training hyperparameters for VideoMAE fine-tuning.

These values are defaults for Colab/Lambda GPU training.
Override via command-line args in train_videomae.py.
"""

from pathlib import Path

# ------------------------------------------------------------------
# Paths
# ------------------------------------------------------------------
DATA_DIR = Path("data/labeled")           # Labeled clips root
CLIPS_DIR = DATA_DIR / "clips"            # Individual clip videos
LABELS_FILE = DATA_DIR / "labels.csv"     # clip_path, action_label
OUTPUT_DIR = Path("ml/models/videomae-fencing-v1")

# ------------------------------------------------------------------
# Model
# ------------------------------------------------------------------
BASE_MODEL = "MCG-NJU/videomae-base-finetuned-kinetics"
NUM_CLASSES = 8  # 8 fencing actions (excluding UNKNOWN)
NUM_FRAMES = 16  # Frames per clip input

# ------------------------------------------------------------------
# Label mapping (index → FACTS 8-class with direction encoding)
# ------------------------------------------------------------------
LABEL_TO_IDX = {
    "attack_left": 0,
    "attack_right": 1,
    "riposte_left": 2,
    "riposte_right": 3,
    "counter_attack_left": 4,
    "counter_attack_right": 5,
    "remise_left": 6,
    "remise_right": 7,
}
IDX_TO_LABEL = {v: k for k, v in LABEL_TO_IDX.items()}

# FACTS original class names (for dataset adapter)
FACTS_LABEL_NAMES = [
    "attack_left", "attack_right",
    "riposte_left", "riposte_right",
    "counter_attack_left", "counter_attack_right",
    "remise_left", "remise_right",
]

# FACTS class code → our label mapping
FACTS_CLASS_CODES = {
    "AL": "attack_left",
    "AR": "attack_right",
    "RL": "riposte_left",
    "RR": "riposte_right",
    "CAL": "counter_attack_left",
    "CAR": "counter_attack_right",
    "ReL": "remise_left",
    "ReR": "remise_right",
}

# Direction-stripped action mapping (for inference)
FACTS_TO_ACTION = {
    "attack_left": ("attack", "left"),
    "attack_right": ("attack", "right"),
    "riposte_left": ("riposte", "left"),
    "riposte_right": ("riposte", "right"),
    "counter_attack_left": ("counter_attack", "left"),
    "counter_attack_right": ("counter_attack", "right"),
    "remise_left": ("remise", "left"),
    "remise_right": ("remise", "right"),
}

# Horizontal flip: swap left↔right labels during augmentation
FLIP_LABEL_MAP = {
    0: 1,  # attack_left → attack_right
    1: 0,  # attack_right → attack_left
    2: 3,  # riposte_left → riposte_right
    3: 2,  # riposte_right → riposte_left
    4: 5,  # counter_attack_left → counter_attack_right
    5: 4,  # counter_attack_right → counter_attack_left
    6: 7,  # remise_left → remise_right
    7: 6,  # remise_right → remise_left
}

# ------------------------------------------------------------------
# Paths (FACTS dataset)
# ------------------------------------------------------------------
FACTS_DATA_DIR = Path("data/facts")  # FACTS dataset root directory
FACTS_ZIP_PATH = FACTS_DATA_DIR / "facts_dataset.zip"  # 30.3GB nested ZIP
FACTS_CLIP_INDEX_PATH = FACTS_DATA_DIR / "clip_index.json"  # clip → inner ZIP mapping
FACTS_CSV_PATH = FACTS_DATA_DIR / "filtered_data_800_fencing.csv"  # 6,400 annotations

# FACTS CSV label normalization (CSV title case → config snake_case)
FACTS_CSV_LABEL_MAP = {
    "Attack left": "attack_left",
    "Attack right": "attack_right",
    "Riposte left": "riposte_left",
    "Riposte right": "riposte_right",
    "Counter Attack left": "counter_attack_left",
    "Counter Attack right": "counter_attack_right",
    "Remise left": "remise_left",
    "Remise right": "remise_right",
}

# ------------------------------------------------------------------
# Training (FACTS paper-aligned hyperparameters)
# ------------------------------------------------------------------
BATCH_SIZE = 4  # Smaller batch for FACTS (gradient accumulation compensates)
GRADIENT_ACCUMULATION_STEPS = 2  # Effective batch size = 4 * 2 = 8
LEARNING_RATE = 5e-5
WEIGHT_DECAY = 0.05
EPOCHS = 10  # FACTS paper: 10 epochs with early stopping
WARMUP_EPOCHS = 3
LABEL_SMOOTHING = 0.1

# ------------------------------------------------------------------
# Data split
# ------------------------------------------------------------------
TRAIN_RATIO = 0.70
VAL_RATIO = 0.15
TEST_RATIO = 0.15

# ------------------------------------------------------------------
# Augmentation
# ------------------------------------------------------------------
HORIZONTAL_FLIP_PROB = 0.5
COLOR_JITTER = 0.2  # Brightness/contrast/saturation jitter
