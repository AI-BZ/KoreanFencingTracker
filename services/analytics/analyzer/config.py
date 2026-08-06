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


# ==================================================================
# Phase 5a: TV Overlay OCR
# ==================================================================

# --- Overlay bar position (720p reference) ---
OVERLAY_BAR_Y_RATIO = 0.926           # Bottom bar start (667/720)
OVERLAY_BAR_HEIGHT = 53               # Bar height in pixels (720p)
OVERLAY_SCORE_DEBOUNCE = 15           # Frames to confirm score change (~0.5s @30fps)
OVERLAY_OCR_SAMPLE_INTERVAL = 5       # OCR every N frames (not every frame)
OVERLAY_MIN_SCORE_CONFIDENCE = 0.7    # Minimum confidence for score reading
OVERLAY_TEXT_SCALE = 3                # Scale-up factor for OCR preprocessing

# --- HSV color ranges for overlay text ---
OVERLAY_WHITE_LOWER = [0, 0, 200]
OVERLAY_WHITE_UPPER = [180, 30, 255]
OVERLAY_RED_LOWER_1 = [0, 100, 150]
OVERLAY_RED_UPPER_1 = [10, 255, 255]
OVERLAY_RED_LOWER_2 = [170, 100, 150]
OVERLAY_RED_UPPER_2 = [180, 255, 255]
OVERLAY_GREEN_LOWER = [35, 60, 150]
OVERLAY_GREEN_UPPER = [85, 255, 255]
OVERLAY_YELLOW_LOWER = [20, 100, 200]   # Yellow card
OVERLAY_YELLOW_UPPER = [35, 255, 255]
OVERLAY_BLUE_LOWER = [85, 50, 100]       # Time/period digits (blue/cyan)
OVERLAY_BLUE_UPPER = [130, 255, 255]


# ==================================================================
# Phase 5c: Pose-based Analysis (footwork, parry, distance)
# ==================================================================

# --- COCO 17 Keypoint Indices ---
KP_NOSE = 0
KP_LEFT_EYE = 1
KP_RIGHT_EYE = 2
KP_LEFT_EAR = 3
KP_RIGHT_EAR = 4
KP_LEFT_SHOULDER = 5
KP_RIGHT_SHOULDER = 6
KP_LEFT_ELBOW = 7
KP_RIGHT_ELBOW = 8
KP_LEFT_WRIST = 9
KP_RIGHT_WRIST = 10
KP_LEFT_HIP = 11
KP_RIGHT_HIP = 12
KP_LEFT_KNEE = 13
KP_RIGHT_KNEE = 14
KP_LEFT_ANKLE = 15
KP_RIGHT_ANKLE = 16

# --- Distance Zones (BH = Body Height units) ---
DISTANCE_ZONE_THRESHOLDS = {
    "out": 1.8,          # > 1.8 BH = out of distance
    "adv_lunge": 1.5,    # 1.5-1.8 BH = advance-lunge range
    "lunge": 1.2,        # 1.2-1.5 BH = lunge range
    "extension": 0.8,    # 0.8-1.2 BH = arm extension range
    # < 0.8 BH = infighting
}
DISTANCE_SMOOTHING_WINDOW = 5  # frames for moving average

# --- Footwork Detection Thresholds ---
FOOTWORK_LUNGE_HIP_DROP_MIN = 10.0       # px: minimum hip drop for lunge
FOOTWORK_LUNGE_FRONT_FOOT_RATIO = 3.0    # front/rear foot displacement ratio
FOOTWORK_FLECHE_BOTH_ADVANCE_MIN = 20.0  # px: min displacement for both feet
FOOTWORK_MIN_DISPLACEMENT_PX = 15.0      # px: below this = stationary
FOOTWORK_ANALYSIS_WINDOW = 15            # frames before touch to analyze

# --- Parry Detection Thresholds ---
PARRY_WRIST_LATERAL_MIN_PX = 20.0   # px: min lateral displacement for parry
PARRY_WRIST_SPEED_MIN_PX = 8.0      # px/frame: min wrist speed for parry
PARRY_DETECTION_WINDOW = 10         # frames before touch to check

# --- Pose Analysis ---
POSE_ANALYSIS_FPS = 30.0             # assumed video FPS for speed calcs
POSE_ANALYSIS_REMISE_WINDOW_SEC = 2.0  # seconds window for remise detection

# Camera cut / frame jump detection (TV broadcast clips)
CAMERA_CUT_HIP_JUMP_PX = 100.0   # hip center jump > this between consecutive frames = camera cut
CAMERA_CUT_MAX_RATIO = 0.3       # if > 30% of frames are camera cuts, analysis quality is low


# ==================================================================
# Phase 6: Exchange Detection + Continuous Analysis + Threshold Tuning
# ==================================================================

# --- Exchange detection (continuous analysis) ---
# Footwork types that count as a committed attacking approach. A non-scoring
# exchange without one of these on either fencer has no clear aggressor, so it
# is labelled NEUTRAL instead of FAILED_ATTACK to keep low-confidence noise
# exchanges out of the attack/defense statistics.
EXCHANGE_ATTACK_FOOTWORK_TYPES = frozenset({"lunge", "fleche", "advance"})
EXCHANGE_MIN_APPROACH_FRAMES = 3          # min frames of decreasing distance to start exchange
# Hysteresis band (BH) on the approach→separation turn in detect_exchanges: a
# rise smaller than this above the closest point is treated as pose noise and
# does not end the exchange, preventing jitter-driven over-segmentation.
EXCHANGE_DISTANCE_DECREASE_THRESHOLD = 0.05
# Minimum total closing (BH) for an approach to count as a real exchange.
# Raised 0.2 → 0.3: 0.2 BH is within pose-jitter range and produced phantom
# exchanges; a committed engagement closes ≥0.3 BH (see DISTANCE_ZONE_THRESHOLDS).
# Empirically this drops non-scoring phantom exchanges while retaining every
# real scoring exchange (validated on div1_epee div1 final: 334→143 exchanges,
# scoring-exchange count unchanged).
EXCHANGE_MIN_DISTANCE_CHANGE_BH = 0.3
# Absolute proximity gate (BH): an exchange is only emitted if the fencers
# actually closed to within this distance at their nearest point. The relative
# closing test above (EXCHANGE_MIN_DISTANCE_CHANGE_BH) accepts an approach even
# when the fencers never come within striking range — e.g. drifting from 4.5 to
# 4.0 BH — producing "phantom" out-of-distance exchanges that inflate the count.
#
# This is a deliberately conservative *global* value. It must not drop any real
# touch, so it is set above the coverage floor of both validation weapons — the
# largest nearest-distance among exchanges that still cover a real scored touch:
# epee floor 2.28 BH, foil floor 1.38 BH. Epee scores at longer range and sets
# the floor. Pose estimation is non-deterministic on these clips (the epee floor
# ranged 1.74–2.28 BH across runs), so 2.5 keeps a margin above the worst
# observed floor and holds 22/22 touch coverage on both bouts. A nearest
# approach beyond 2.5 BH is out of striking range in any weapon → phantom.
#
# Note this does NOT fully resolve epee over-segmentation: most epee exchanges
# are genuine long-range engagements, not phantoms, so a coverage-safe gate
# cannot cut them. It removes the clearly out-of-distance tail only.
EXCHANGE_MAX_MIN_DISTANCE_BH = 2.5
EXCHANGE_MERGE_SEPARATION_FRAMES = 10    # if re-approach within N frames of separation → merge into same exchange
CONTINUOUS_SAMPLE_EVERY_N = 5            # analyze every N frames
CONTINUOUS_MAX_FRAMES = 10800            # max frames to analyze (6min @30fps)

# --- Clock state tracking (Allez/Halt proxy) ---
CLOCK_RUNNING_CONFIRM_FRAMES = 3   # N consecutive frames with time decrease = clock running (Allez)
CLOCK_STOPPED_CONFIRM_FRAMES = 5   # N consecutive frames with time unchanged = clock stopped (Halt)

# --- Joint kinematics tracking ---
KINEMATICS_TRACKED_JOINTS = [
    "left_wrist", "right_wrist",
    "left_ankle", "right_ankle",
    "left_hip", "right_hip",
    "left_shoulder", "right_shoulder",
]
KINEMATICS_JOINT_TO_KP = {
    "left_wrist": KP_LEFT_WRIST,
    "right_wrist": KP_RIGHT_WRIST,
    "left_ankle": KP_LEFT_ANKLE,
    "right_ankle": KP_RIGHT_ANKLE,
    "left_hip": KP_LEFT_HIP,
    "right_hip": KP_RIGHT_HIP,
    "left_shoulder": KP_LEFT_SHOULDER,
    "right_shoulder": KP_RIGHT_SHOULDER,
}

# --- Threshold tuning (ratio-based footwork) ---
FOOTWORK_LUNGE_HIP_DROP_RATIO_MIN = 0.005  # BH ratio: min hip drop for lunge (0.5% — TV clips have subtle drops)
FOOTWORK_FLECHE_BOTH_ADVANCE_MIN_TUNED = 50.0  # px: raised from 40 to reduce fleche false positives
FOOTWORK_FLECHE_MAX_RATIO = 2.5            # max front/rear ratio for fleche (above this → lunge-like, not fleche)
FOOTWORK_USE_RATIO_BASED_HIP_DROP = True   # use ratio-based hip drop (True) vs absolute px (False)

# --- Scoring frame tolerance (OCR delay compensation) ---
SCORING_FRAME_TOLERANCE_SEC = 2.0  # seconds: OCR score change delay tolerance

# --- Touch clip anchoring (real touch vs delayed OCR score change) ---
# Measured on the foil bout (22/22 touches): the OCR score change lags the end of
# the pose engagement that produced the touch by a MEDIAN of +2.8s (range
# 0.6-4.6s), never negative. Anchoring a clip on the OCR score-change frame
# therefore lands the window on the post-touch reset/recovery, not the touch.
# So each OCR touch is matched back to the *preceding* pose exchange, and the clip
# is anchored on that exchange's real-touch frame (min_distance_frame).
#
# EXCHANGE_MATCH_DELAY_SEC: how far after an exchange end an OCR touch may arrive
# and still be attributed to that exchange. Set to 4.0 = median 2.8s + margin.
# (Covers most touches; the few with >4s lag fall back to the low-confidence path.)
# Replaces the old ±2s TOLERANCE_FRAMES window that only matched 5/22 touches.
EXCHANGE_MATCH_DELAY_SEC = 4.0

# PHRASE_MAX_LEAD_SEC: lead-in cap on the clip. Continuous analysis can produce
# degenerate exchanges up to ~36s long; without a cap the clip start would run far
# ahead of the touch. Clamp the start to at most this many seconds before the end.
PHRASE_MAX_LEAD_SEC = 8.0

# OCR_TOUCH_DELAY_MEDIAN_SEC: measured median OCR-vs-touch lag. Used as the lead-in
# for the fallback window when no preceding exchange can be matched (low confidence,
# real-touch position unknown so we anchor the clip END on the OCR frame itself).
OCR_TOUCH_DELAY_MEDIAN_SEC = 2.8


# ==================================================================
# Foil lamp-colour reading (scoring-box lamps in the TV overlay bar)
# ==================================================================
#
# The USA Fencing bottom overlay encodes the scoring-box lamps as the BACKGROUND
# FILL of each fencer's name region, not as a separate lamp graphic:
#   idle    → coloured text on black      → small fill fraction
#   lamp on → white text on a solid fill  → large fill fraction
#
# All values below were measured on a 1280x720 foil bout.

# HSV fill masks (OpenCV HSV, H in 0..179). The bounds encode the measured
# strict inequalities inclusively for cv2.inRange:
#   red   = S>100 and V>120 and (H<=12 or H>=168)
#   green = 35<=H<=85 and S>60 and V>100
#   white = S<40 and V>180
LAMP_FILL_RED_LOWER_1 = [0, 101, 121]
LAMP_FILL_RED_UPPER_1 = [12, 255, 255]
LAMP_FILL_RED_LOWER_2 = [168, 101, 121]
LAMP_FILL_RED_UPPER_2 = [180, 255, 255]
LAMP_FILL_GREEN_LOWER = [35, 61, 101]
LAMP_FILL_GREEN_UPPER = [85, 255, 255]
LAMP_FILL_WHITE_LOWER = [0, 0, 181]
LAMP_FILL_WHITE_UPPER = [180, 39, 255]

# Fill fraction above which a lamp counts as ON. Measured fills:
#   left idle (red text on black)  0.227 | left red lamp ON   0.75-0.76
#   right idle (green text)        0.174 | right green ON     0.82
#   white lamp ON                  0.79
# Both populations sit far from 0.5, so the threshold has a wide margin.
LAMP_ON_FILL_THRESHOLD = 0.5

# Frame step when sampling the bar for lamp state. Step 3 still caught the
# shortest real lamp display observed (7 frames).
LAMP_SAMPLE_STEP = 3

# The broadcast sometimes renders the two lamps of a double *sequentially* with a
# short gap (measured gaps up to 9 frames), so runs closer than this merge into a
# single event. Genuinely separate actions are seconds apart.
LAMP_EVENT_MERGE_GAP = 15

# Search window around the OCR score-change frame. The lamp onset leads the OCR
# score frame by a measured 81-222 frames.
LAMP_SEARCH_LOOKBACK = 330
LAMP_SEARCH_FORWARD = 30

# Confidence shaping: fill at which fill-based confidence saturates, lamp-on
# duration (frames) at which duration confidence saturates, and the floor applied
# to the duration term so a briefly-rendered lamp is penalised but not zeroed.
LAMP_CONF_FULL_FILL = 0.75
LAMP_CONF_FULL_FRAMES = 30
LAMP_CONF_MIN_DURATION_FACTOR = 0.4
