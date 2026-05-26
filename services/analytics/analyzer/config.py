"""
Configuration constants for the fencing video analyzer.

Phase 1: HSV ranges, thresholds, 7-segment patterns
Phase 2: Device, YOLO11-Pose, VideoMAE, integration settings
"""

import numpy as np
from pathlib import Path


# --- LED Lamp Detection (HSV ranges) ---

# Red LED in HSV colorspace (two ranges due to hue wrap-around)
RED_LOWER_1 = np.array([0, 100, 100])
RED_UPPER_1 = np.array([10, 255, 255])
RED_LOWER_2 = np.array([160, 100, 100])
RED_UPPER_2 = np.array([180, 255, 255])

# Green LED in HSV colorspace
GREEN_LOWER = np.array([35, 100, 100])
GREEN_UPPER = np.array([85, 255, 255])

# Lamp detection: minimum bright pixels to consider lamp ON
LAMP_PIXEL_THRESHOLD = 300

# Lamp detection: expanded HSV for detect_lamp method
LAMP_RED_SAT_LOW = np.array([0, 50, 150])
LAMP_RED_SAT_HIGH_1 = np.array([15, 255, 255])
LAMP_RED_SAT_LOW_2 = np.array([160, 50, 150])
LAMP_RED_SAT_HIGH_2 = np.array([180, 255, 255])
LAMP_BRIGHT_LOW = np.array([0, 0, 200])
LAMP_BRIGHT_HIGH = np.array([180, 80, 255])

LAMP_GREEN_LOW = np.array([35, 50, 150])
LAMP_GREEN_HIGH = np.array([85, 255, 255])


# --- Score ROI LED Mask Extraction (HSV) ---

SCORE_RED_LOWER_1 = np.array([0, 80, 80])
SCORE_RED_UPPER_1 = np.array([15, 255, 255])
SCORE_RED_LOWER_2 = np.array([165, 80, 80])
SCORE_RED_UPPER_2 = np.array([180, 255, 255])


# --- Score Change Detection ---

SCORE_CHANGE_THRESHOLD = 20  # pixel count difference to detect change


# --- Event Debouncing ---

DEBOUNCE_FRAMES = 30  # min frames between events
SCORE_WAIT_SECONDS = 15  # wait for referee decision after lamp
SCORE_WAIT_FRAMES = 450  # at 30fps


# --- 7-Segment OCR ---

# Feature extraction: normalized digit size
DIGIT_NORM_WIDTH = 20
DIGIT_NORM_HEIGHT = 30

# Template matching minimum similarity
TEMPLATE_MATCH_THRESHOLD = 0.5

# Minimum pixel ratio to consider segment active
SEGMENT_MIN_PIXEL_RATIO = 0.05

# Aspect ratio threshold for digit "1" (narrow)
DIGIT_ONE_ASPECT_THRESHOLD = 0.65

# Dynamic threshold: fraction of max segment ratio
DYNAMIC_THRESHOLD_FRACTION = 0.35
DYNAMIC_THRESHOLD_MIN = 0.12

# Brightness threshold for LED detection
BRIGHTNESS_THRESHOLD = 200


# --- 7-Segment Pattern Map ---
# (a, b, c, d, e, f, g) -> digit
SEVEN_SEGMENT_PATTERNS = {
    (True, True, True, True, True, True, False): 0,
    (False, True, True, False, False, False, False): 1,
    (True, True, False, True, True, False, True): 2,
    (True, True, True, True, False, False, True): 3,
    (False, True, True, False, False, True, True): 4,
    (True, False, True, True, False, True, True): 5,
    (True, False, True, True, True, True, True): 6,
    (True, True, True, False, False, False, False): 7,
    (True, True, True, True, True, True, True): 8,
    (True, True, True, True, False, True, True): 9,
}


# --- Clock ROI ---

CLOCK_RED_LOWER_1 = np.array([0, 50, 100])
CLOCK_RED_UPPER_1 = np.array([15, 255, 255])
CLOCK_RED_LOWER_2 = np.array([160, 50, 100])
CLOCK_RED_UPPER_2 = np.array([180, 255, 255])
CLOCK_BRIGHTNESS_THRESHOLD = 180

# Colon detection: aspect ratio below this is a colon
COLON_ASPECT_THRESHOLD = 0.3


# ==================================================================
# Phase 2: Pose Estimation + Action Recognition
# ==================================================================

# --- Device ---
DEVICE_PREFERENCE = "mps"  # Apple Silicon GPU; fallback: cuda > cpu

# --- YOLO11-Pose ---
_ML_DIR = Path(__file__).resolve().parent.parent / "ml"
POSE_MODEL_PATH = _ML_DIR / "models" / "yolo11n-pose.pt"
POSE_CONFIDENCE_THRESHOLD = 0.5
POSE_KEYPOINT_CONFIDENCE = 0.3
POSE_MAX_PERSONS = 2
POSE_IMGSZ = 640

# --- VideoMAE (Action Classification) ---
ACTION_MODEL_NAME = "MCG-NJU/videomae-base-finetuned-kinetics"
ACTION_FINETUNED_PATH = None  # Set to Path when FACTS fine-tuned model is ready
ACTION_WINDOW_SIZE = 16  # frames per clip
ACTION_STRIDE = 8  # sliding window stride
ACTION_CONFIDENCE_THRESHOLD = 0.4
ACTION_LABEL_MAP = {
    0: "attack_left",
    1: "attack_right",
    2: "riposte_left",
    3: "riposte_right",
    4: "counter_attack_left",
    5: "counter_attack_right",
    6: "remise_left",
    7: "remise_right",
}
ACTION_LABEL_MAP_KR = {
    "attack": "공격",
    "riposte": "리포스트",
    "parry": "파리",
    "lunge": "런지",
    "fleche": "플레쉬",
    "retreat": "후퇴",
    "advance": "전진",
    "counter_attack": "콘트르아탁",
    "remise": "르미즈",
}

# FACTS direction-encoded label → (FencingAction value, direction)
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

# --- Integrated Analysis (2-pass enrichment) ---
ENRICHED_POSE_WINDOW_BEFORE = 30  # frames before scoring event
ENRICHED_POSE_WINDOW_AFTER = 15  # frames after scoring event


# ==================================================================
# Phase 4b: Scoreboard Auto-Detection
# ==================================================================

# --- Scoreboard detection thresholds ---
SCOREBOARD_MIN_WIDTH_RATIO = 0.15    # Min scoreboard width as fraction of frame width
SCOREBOARD_MAX_WIDTH_RATIO = 0.80    # Max scoreboard width as fraction of frame width
SCOREBOARD_MIN_ASPECT = 2.0          # Min aspect ratio (width/height) for scoreboard
SCOREBOARD_DETECTION_CONFIDENCE_MIN = 0.5  # Min confidence to accept detection
SCOREBOARD_LAMP_PAD_RATIO = 0.20     # Lamp region padding ratio
