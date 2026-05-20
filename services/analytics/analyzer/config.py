"""
Configuration constants for the fencing video analyzer.

Extracted from fencing_analyzer_v3.py — all threshold values,
HSV ranges, and tuning parameters.
"""

import numpy as np


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
