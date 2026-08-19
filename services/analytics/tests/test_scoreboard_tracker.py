"""Unit tests for analyzer.scoreboard_tracker.

Everything here is synthetic. Frames are built in-process with numpy/OpenCV —
no file under ``data/`` is opened, no video is decoded, and nothing depends on
wall-clock timing — so the whole suite is deterministic and runs in about a
second.

The three things the synthetic fixtures have to get right, because the module's
thresholds are written against them:

* a lamp is read from **two** pixel populations. ``on`` comes from the blown-out
  core (``V >= core_value_min``) and the colour comes from the surrounding halo
  (``halo_value_min <= V <= halo_value_max``), so a lamp patch that only has one
  of the two reads as either colourless or unlit. :func:`_lamp_fill` builds both.
* a settled score mask is only retained after ``window_frames`` frames have been
  fed *and* on a frame index divisible by ``sample_stride``, so a score test has
  to feed enough consecutive frames to land on those boundaries.
* a tracked position is only believed when the score digits are *glowing* there
  (``ScoreChangeConfig.display_min_fraction``). A frame carrying lamps but no
  display is not a readable scoreboard, it is the hijacked-tracker signature, and
  the module throws it away. Every fixture standing for a successfully tracked
  panel therefore lights the digits too — :func:`_paint_display`, applied by
  default in :func:`_lamp_hsv_frame`.
"""

import cv2
import pytest

np = pytest.importorskip("numpy")

from analyzer.models import EventType
from analyzer.scoreboard_tracker import (
    CHROMATIC_COLOURS,
    COLOUR_GREEN,
    COLOUR_RED,
    COLOUR_WHITE,
    KOR_DOMESTIC_V1,
    LEFT,
    RIGHT,
    SIDES,
    VERDICT_ANNULLED,
    VERDICT_OFF_TARGET,
    VERDICT_TOUCH,
    VERDICT_UNDETERMINED,
    CoverageGap,
    LampConfig,
    LampEvent,
    LampEventScanner,
    LampSample,
    MachineProfile,
    PanelTrack,
    PanelTracker,
    ScoreChangeConfig,
    ScoreChangeDetector,
    ScoreComparison,
    TouchResolution,
    TrackerConfig,
    absolute_roi,
    classify_colour,
    display_lit_fraction,
    event_intervals,
    mask_similarity,
    merge_runs,
    read_lamp,
    resolutions_to_match_events,
    resolve_touches,
)

PROFILE = KOR_DOMESTIC_V1
TRACKER_CONFIG = TrackerConfig()
LAMP_CONFIG = LampConfig()
SCORE_CONFIG = ScoreChangeConfig()

FRAME_W, FRAME_H = 400, 300
#: Panel origin used by every lamp/score fixture. Chosen so that both lamp ROIs
#: and both digit ROIs of ``KOR_DOMESTIC_V1`` sit comfortably inside the frame.
ORIGIN = (100, 80)

HOUSING_BBOX = (100, 80, 60, 40)
PLACARD_BBOX = (110, 130, 24, 30)

RED_HUE = 0
GREEN_HUE = 60
#: OpenCV hue wraps, so red also lives at the top of the range.
RED_WRAP_HUE = 175


# ----------------------------------------------------------------------
# Frame builders — panel tracking
# ----------------------------------------------------------------------


def _textured_background(seed=0, width=FRAME_W, height=FRAME_H):
    """A smooth gradient plus low-amplitude noise, as BGR.

    Deliberately low-contrast: the panel patch has to be the only strongly
    structured thing in the frame so a full-frame search cannot be fooled.
    """
    rng = np.random.default_rng(seed)
    columns = np.linspace(20, 90, width, dtype=np.float32)
    rows = np.linspace(0, 40, height, dtype=np.float32)
    gray = columns[None, :] + rows[:, None] + rng.normal(0, 3, size=(height, width))
    gray = np.clip(gray, 0, 255).astype(np.uint8)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def _high_contrast_patch(width, height, seed=7):
    """A blocky black/white pattern — a distinctive template to correlate on."""
    rng = np.random.default_rng(seed)
    blocks = rng.integers(0, 2, size=(height // 4 + 1, width // 4 + 1), dtype=np.uint8) * 255
    pattern = np.kron(blocks, np.ones((4, 4), dtype=np.uint8))[:height, :width]
    return cv2.cvtColor(pattern, cv2.COLOR_GRAY2BGR)


def _panel_frame(housing_at=None, placard_at=None, seed=0):
    """Background with the housing and/or placard patch stamped at given corners.

    Passing ``housing_at=None`` erases the housing entirely, which is how the
    placard-carries-the-track and lost-track cases are staged.
    """
    frame = _textured_background(seed=seed)
    if housing_at is not None:
        x, y = housing_at
        frame[y:y + HOUSING_BBOX[3], x:x + HOUSING_BBOX[2]] = _high_contrast_patch(
            HOUSING_BBOX[2], HOUSING_BBOX[3], seed=7
        )
    if placard_at is not None:
        x, y = placard_at
        frame[y:y + PLACARD_BBOX[3], x:x + PLACARD_BBOX[2]] = _high_contrast_patch(
            PLACARD_BBOX[2], PLACARD_BBOX[3], seed=11
        )
    return frame


def _reference_frame():
    """The frame both templates are cut from."""
    return _panel_frame(HOUSING_BBOX[:2], PLACARD_BBOX[:2])


# ----------------------------------------------------------------------
# Frame builders — lamps and digits
# ----------------------------------------------------------------------


def _lamp_fill(hue, saturation=255):
    """A lamp filler: top half blown-out core, bottom half coloured halo.

    Half the ROI saturated clears ``on_fraction`` (0.3) comfortably, and the
    whole halo carrying one hue drives ``red_frac``/``green_frac`` to 1.0.
    """

    def fill(height, width):
        patch = np.zeros((height, width, 3), dtype=np.uint8)
        patch[:height // 2] = (hue, saturation, 255)
        patch[height // 2:] = (hue, saturation, 200)
        return patch

    return fill


#: HSV value of a lit red 7-segment pixel: bright, saturated, in the red band.
#: ``digit_mask`` needs value, saturation *and* hue in range at once, so a bright
#: but desaturated patch is not a display.
DIGIT_RED = (0, 255, 255)

#: ``(width, height)`` of the lit stroke :func:`_paint_display` puts in one score
#: ROI. Sized so the lit fraction lands in the 0.049–0.093 band measured on
#: genuine locks rather than filling the region — the gate has to be cleared by a
#: realistic display, not by a floodlit one.
DISPLAY_BLOCK = (6, 22)

#: What :func:`_paint_display` measures as, per side, under ``digit_mask``.
DISPLAY_LIT_FRACTION = (
    DISPLAY_BLOCK[0] * DISPLAY_BLOCK[1]
    / (PROFILE.digit_rois[LEFT][2] * PROFILE.digit_rois[LEFT][3])
)


def _paint_display(frame, origin=ORIGIN, sides=SIDES):
    """Light the score digits of ``frame`` at ``origin``, and return it.

    A real scoring box always shows a score, even 0–0, so a fixture that stands
    for a tracked and *readable* panel has to glow: ``LampEventScanner.feed``
    refuses to read lamps at a position whose score ROIs are dark. Anything
    painted outside the frame is clipped away by numpy, which is what makes this
    safe to apply to the deliberately off-frame origins.
    """
    width, height = DISPLAY_BLOCK
    for side in sides:
        x, y, w, h = absolute_roi(origin, PROFILE.digit_rois[side])
        top, left = y + (h - height) // 2, x + (w - width) // 2
        frame[top:top + height, left:left + width] = DIGIT_RED
    return frame


def _lamp_hsv_frame(left=None, right=None, origin=ORIGIN, display=True):
    """An HSV frame with the given filler painted into each side's lamp ROI.

    The score digits are lit as well by default — see :func:`_paint_display`.
    ``display=False`` builds the hijacked-tracker frame instead: lamp pixels that
    read as ON at a position where no scoring box exists.
    """
    frame = np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8)
    if display:
        _paint_display(frame, origin)
    for side, fill in ((LEFT, left), (RIGHT, right)):
        if fill is None:
            continue
        x, y, w, h = absolute_roi(origin, PROFILE.lamp_rois[side])
        frame[y:y + h, x:x + w] = fill(h, w)
    return frame


def _track(index, corr=0.9, origin=ORIGIN, source="housing"):
    return PanelTrack(index, origin[0], origin[1], corr, source)


def _digit_hsv_frame(left_shape, right_shape, origin=ORIGIN):
    """An HSV frame with a shape drawn in each side's score-digit ROI.

    ``"block"`` and ``"bar"`` stand in for two different displayed numbers;
    their masks overlap far too little to survive ``similarity_min`` even after
    the ``align_radius`` shift search.
    """
    frame = np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8)
    for side, shape in ((LEFT, left_shape), (RIGHT, right_shape)):
        x, y, w, h = absolute_roi(origin, PROFILE.digit_rois[side])
        if shape == "block":
            frame[y + 5:y + 35, x + 6:x + 30] = DIGIT_RED
        elif shape == "bar":
            frame[y + 5:y + 35, x + 16:x + 20] = DIGIT_RED
    return frame


def _feed_digits(detector, frame_count, left_shape, right_shape, change_at=None):
    """Feed ``frame_count`` locked frames; after ``change_at`` use the new shapes."""
    for index in range(frame_count):
        if change_at is not None and index >= change_at:
            shapes = left_shape[1], right_shape[1]
        elif change_at is not None:
            shapes = left_shape[0], right_shape[0]
        else:
            shapes = left_shape, right_shape
        detector.feed(_digit_hsv_frame(*shapes), _track(index))


# ----------------------------------------------------------------------
# Event builders
# ----------------------------------------------------------------------


def _event(onset=100, end=130, left=None, right=None):
    return LampEvent(onset_frame=onset, end_frame=end, left_colour=left, right_colour=right)


def _comparison(changed=(), determined=True):
    return ScoreComparison(
        changed=frozenset(changed),
        determined=determined,
        similarity={side: None for side in SIDES},
    )


# ----------------------------------------------------------------------
# PanelTracker
# ----------------------------------------------------------------------


class TestPanelTrackerFollowsTheHousing:
    def test_a_small_translation_is_recovered_exactly(self):
        tracker = PanelTracker.from_frame(_reference_frame(), HOUSING_BBOX)

        track = tracker.update(_panel_frame((107, 85)))

        assert track.origin == (107, 85)
        assert track.source == "housing"
        assert track.corr > 0.95
        assert track.locked is True

    def test_the_first_updated_frame_is_numbered_zero(self):
        tracker = PanelTracker.from_frame(_reference_frame(), HOUSING_BBOX)
        assert tracker.update(_panel_frame(HOUSING_BBOX[:2])).frame == 0
        assert tracker.update(_panel_frame(HOUSING_BBOX[:2])).frame == 1

    def test_a_jump_past_the_search_window_is_reacquired_full_frame(self):
        # The local window around (100, 80) spans x in [10, 250) and y in
        # [0, 210), and the template is 60x40, so a housing at (250, 180) cannot
        # be found by the local search at all — only the full-frame fallback can
        # produce this answer.
        tracker = PanelTracker.from_frame(_reference_frame(), HOUSING_BBOX)
        jump = TRACKER_CONFIG.search_pad + 60

        track = tracker.update(_panel_frame((100 + jump, 180)))

        assert jump > TRACKER_CONFIG.search_pad
        assert track.origin == (100 + jump, 180)
        assert track.source == "housing"
        assert track.corr > 0.95

    def test_the_recovered_position_carries_into_the_next_frame(self):
        tracker = PanelTracker.from_frame(_reference_frame(), HOUSING_BBOX)
        tracker.update(_panel_frame((250, 180)))

        track = tracker.update(_panel_frame((255, 184)))

        assert track.origin == (255, 184)
        assert track.source == "housing"


class TestPanelTrackerFallsBackToThePlacard:
    def test_the_placard_carries_the_track_when_the_housing_is_gone(self):
        tracker = PanelTracker.from_frame(_reference_frame(), HOUSING_BBOX, PLACARD_BBOX)
        shift = (15, 15)
        placard_now = (PLACARD_BBOX[0] + shift[0], PLACARD_BBOX[1] + shift[1])

        track = tracker.update(_panel_frame(housing_at=None, placard_at=placard_now))

        # The reported origin is the placard's new position plus the fixed
        # housing-minus-placard offset captured at init.
        offset = (HOUSING_BBOX[0] - PLACARD_BBOX[0], HOUSING_BBOX[1] - PLACARD_BBOX[1])
        assert track.origin == (placard_now[0] + offset[0], placard_now[1] + offset[1])
        assert track.source == "placard"
        assert track.corr >= TRACKER_CONFIG.lock_corr
        assert track.locked is True

    def test_the_housing_wins_while_both_templates_are_visible(self):
        tracker = PanelTracker.from_frame(_reference_frame(), HOUSING_BBOX, PLACARD_BBOX)

        track = tracker.update(_panel_frame((112, 92), (122, 142)))

        assert track.source == "housing"
        assert track.origin == (112, 92)

    def test_a_placard_template_without_its_origin_is_refused(self):
        with pytest.raises(ValueError):
            PanelTracker(
                housing_template=_high_contrast_patch(60, 40),
                housing_origin=(100, 80),
                placard_template=_high_contrast_patch(24, 30),
                placard_origin=None,
            )


class TestPanelTrackerLosesTheTrack:
    def test_a_featureless_frame_with_no_placard_reports_lost(self):
        tracker = PanelTracker.from_frame(_reference_frame(), HOUSING_BBOX)

        track = tracker.update(np.full((FRAME_H, FRAME_W, 3), 120, dtype=np.uint8))

        assert track.source == "lost"
        assert track.locked is False
        assert track.corr < TRACKER_CONFIG.reacquire_corr


class TestPanelTrackerInitialisation:
    def test_a_housing_bbox_hanging_off_the_frame_is_refused(self):
        frame = _reference_frame()
        with pytest.raises(ValueError):
            PanelTracker.from_frame(frame, (FRAME_W - 20, 80, 60, 40))

    def test_a_housing_bbox_with_a_negative_corner_is_refused(self):
        with pytest.raises(ValueError):
            PanelTracker.from_frame(_reference_frame(), (-5, 80, 60, 40))

    def test_a_placard_bbox_hanging_off_the_frame_is_refused(self):
        frame = _reference_frame()
        with pytest.raises(ValueError):
            PanelTracker.from_frame(frame, HOUSING_BBOX, (110, FRAME_H - 10, 24, 30))

    def test_an_empty_housing_template_is_refused(self):
        with pytest.raises(ValueError):
            PanelTracker(housing_template=np.zeros((0, 0), np.uint8), housing_origin=(0, 0))


# ----------------------------------------------------------------------
# Lamp reading and colour classification
# ----------------------------------------------------------------------


class TestReadLamp:
    def test_a_saturated_red_lamp_reads_as_on_and_red(self):
        sample = read_lamp(_lamp_fill(RED_HUE)(20, 56), LAMP_CONFIG)

        assert sample.on is True
        assert sample.sat_frac >= LAMP_CONFIG.on_fraction
        assert sample.red_frac >= LAMP_CONFIG.colour_fraction
        assert sample.green_frac == pytest.approx(0.0)

    def test_red_is_recognised_on_the_far_side_of_the_hue_wrap(self):
        sample = read_lamp(_lamp_fill(RED_WRAP_HUE)(20, 56), LAMP_CONFIG)

        assert sample.on is True
        assert sample.red_frac >= LAMP_CONFIG.colour_fraction

    def test_a_saturated_green_lamp_reads_as_on_and_green(self):
        sample = read_lamp(_lamp_fill(GREEN_HUE)(20, 56), LAMP_CONFIG)

        assert sample.on is True
        assert sample.green_frac >= LAMP_CONFIG.colour_fraction
        assert sample.red_frac == pytest.approx(0.0)

    def test_a_desaturated_white_hot_lamp_reads_as_on_with_no_hue(self):
        sample = read_lamp(_lamp_fill(RED_HUE, saturation=10)(20, 56), LAMP_CONFIG)

        assert sample.on is True
        assert sample.red_frac == pytest.approx(0.0)
        assert sample.green_frac == pytest.approx(0.0)

    def test_a_dark_patch_reads_as_off(self):
        sample = read_lamp(np.zeros((20, 56, 3), dtype=np.uint8), LAMP_CONFIG)

        assert sample.on is False
        assert sample.sat_frac == pytest.approx(0.0)

    def test_a_bright_core_with_no_halo_still_reads_as_on(self):
        # Every pixel blown out: there is no halo band to take a hue from, but
        # the lamp is unmistakably lit.
        patch = np.full((20, 56, 3), 255, dtype=np.uint8)
        patch[:, :, 0] = RED_HUE

        sample = read_lamp(patch, LAMP_CONFIG)

        assert sample.on is True
        assert sample.red_frac == pytest.approx(0.0)


class TestClassifyColour:
    def test_lit_red_samples_classify_as_red(self):
        samples = [read_lamp(_lamp_fill(RED_HUE)(20, 56), LAMP_CONFIG)] * 4
        assert classify_colour(samples, LAMP_CONFIG) == COLOUR_RED

    def test_lit_green_samples_classify_as_green(self):
        samples = [read_lamp(_lamp_fill(GREEN_HUE)(20, 56), LAMP_CONFIG)] * 4
        assert classify_colour(samples, LAMP_CONFIG) == COLOUR_GREEN

    def test_lit_but_hueless_samples_classify_as_white(self):
        samples = [read_lamp(_lamp_fill(RED_HUE, saturation=10)(20, 56), LAMP_CONFIG)] * 4
        assert classify_colour(samples, LAMP_CONFIG) == COLOUR_WHITE

    def test_a_lamp_that_was_never_lit_has_no_colour(self):
        samples = [LampSample(on=False, sat_frac=0.02, red_frac=1.0, green_frac=0.0)] * 4
        assert classify_colour(samples, LAMP_CONFIG) is None

    def test_no_samples_at_all_has_no_colour(self):
        assert classify_colour([], LAMP_CONFIG) is None

    def test_unlit_samples_do_not_dilute_the_lit_ones(self):
        lit = read_lamp(_lamp_fill(GREEN_HUE)(20, 56), LAMP_CONFIG)
        dark = read_lamp(np.zeros((20, 56, 3), dtype=np.uint8), LAMP_CONFIG)

        assert classify_colour([dark] * 9 + [lit], LAMP_CONFIG) == COLOUR_GREEN


# ----------------------------------------------------------------------
# Debounce
# ----------------------------------------------------------------------


class TestMergeRuns:
    def test_no_frames_at_all_produce_no_runs(self):
        assert merge_runs([], min_length=5, max_gap=12) == []

    def test_no_active_frames_produce_no_runs(self):
        assert merge_runs([False] * 50, min_length=5, max_gap=12) == []

    def test_an_all_active_input_is_one_run_spanning_everything(self):
        assert merge_runs([True] * 10, min_length=5, max_gap=12) == [(0, 9)]

    def test_returned_indices_are_inclusive_of_both_ends(self):
        active = [False, True, True, True, False]
        assert merge_runs(active, min_length=3, max_gap=0) == [(1, 3)]

    def test_a_run_shorter_than_the_minimum_is_dropped(self):
        active = [True] * 4 + [False] * 20
        assert merge_runs(active, min_length=5, max_gap=12) == []

    def test_a_run_exactly_at_the_minimum_is_kept(self):
        active = [True] * 5 + [False] * 20
        assert merge_runs(active, min_length=5, max_gap=12) == [(0, 4)]

    def test_runs_separated_by_at_most_the_max_gap_become_one(self):
        active = [True] * 5 + [False] * 12 + [True] * 5
        assert merge_runs(active, min_length=5, max_gap=12) == [(0, 21)]

    def test_runs_separated_by_more_than_the_max_gap_stay_apart(self):
        active = [True] * 5 + [False] * 13 + [True] * 5
        assert merge_runs(active, min_length=5, max_gap=12) == [(0, 4), (18, 22)]

    def test_merging_can_rescue_two_runs_that_are_each_too_short(self):
        # Neither three-frame burst survives min_length on its own; together
        # they are one nine-frame activation with a dropout in the middle.
        active = [True] * 3 + [False] * 3 + [True] * 3
        assert merge_runs(active, min_length=5, max_gap=12) == [(0, 8)]

    def test_an_active_run_at_the_very_end_is_closed(self):
        active = [False] * 10 + [True] * 6
        assert merge_runs(active, min_length=5, max_gap=12) == [(10, 15)]

    def test_a_single_active_frame_survives_a_minimum_of_one(self):
        assert merge_runs([False, True, False], min_length=1, max_gap=0) == [(1, 1)]


# ----------------------------------------------------------------------
# LampEventScanner
# ----------------------------------------------------------------------


class TestLampEventScannerEvents:
    def test_two_separated_activations_become_two_events_with_their_colours(self):
        scanner = LampEventScanner(PROFILE, LAMP_CONFIG, TRACKER_CONFIG)
        for index in range(200):
            left = _lamp_fill(RED_HUE) if 10 <= index < 40 else None
            right = _lamp_fill(GREEN_HUE) if 100 <= index < 130 else None
            scanner.feed(_lamp_hsv_frame(left, right), _track(index))

        events, gaps = scanner.finish()

        assert [(e.onset_frame, e.end_frame) for e in events] == [(10, 39), (100, 129)]
        assert events[0].left_colour == COLOUR_RED
        assert events[0].right_colour is None
        assert events[1].left_colour is None
        assert events[1].right_colour == COLOUR_GREEN
        assert gaps == []

    def test_both_sides_lighting_together_is_one_event_with_two_colours(self):
        scanner = LampEventScanner(PROFILE, LAMP_CONFIG, TRACKER_CONFIG)
        for index in range(60):
            lit = 10 <= index < 40
            scanner.feed(
                _lamp_hsv_frame(
                    _lamp_fill(RED_HUE) if lit else None,
                    _lamp_fill(GREEN_HUE) if lit else None,
                ),
                _track(index),
            )

        events, _ = scanner.finish()

        assert len(events) == 1
        assert events[0].left_colour == COLOUR_RED
        assert events[0].right_colour == COLOUR_GREEN
        assert events[0].both_valid is True

    def test_a_white_activation_is_reported_as_a_white_event(self):
        scanner = LampEventScanner(PROFILE, LAMP_CONFIG, TRACKER_CONFIG)
        for index in range(60):
            left = _lamp_fill(RED_HUE, saturation=10) if 10 <= index < 40 else None
            scanner.feed(_lamp_hsv_frame(left, None), _track(index))

        events, _ = scanner.finish()

        assert len(events) == 1
        assert events[0].left_colour == COLOUR_WHITE
        assert events[0].any_valid is False

    def test_a_flicker_shorter_than_the_minimum_is_not_an_event(self):
        scanner = LampEventScanner(PROFILE, LAMP_CONFIG, TRACKER_CONFIG)
        for index in range(60):
            left = _lamp_fill(RED_HUE) if 10 <= index < 13 else None
            scanner.feed(_lamp_hsv_frame(left, None), _track(index))

        events, gaps = scanner.finish()

        assert events == []
        assert gaps == []

    def test_lamps_that_never_light_produce_no_events(self):
        scanner = LampEventScanner(PROFILE, LAMP_CONFIG, TRACKER_CONFIG)
        for index in range(100):
            scanner.feed(_lamp_hsv_frame(), _track(index))

        assert scanner.finish() == ([], [])
        assert scanner.readable_frames == scanner.total_frames == 100


class TestLampEventScannerCoverageGaps:
    def test_a_stretch_below_the_lock_correlation_is_reported_as_unlocked(self):
        scanner = LampEventScanner(PROFILE, LAMP_CONFIG, TRACKER_CONFIG)
        for index in range(100):
            corr = 0.2 if 20 <= index < 60 else 0.9
            scanner.feed(_lamp_hsv_frame(), _track(index, corr=corr))

        _, gaps = scanner.finish()

        assert gaps == [CoverageGap(start_frame=20, end_frame=59, reason="unlocked")]
        assert gaps[0].frame_count == 40

    def test_a_stretch_whose_lamp_roi_leaves_the_frame_is_reported_as_off_frame(self):
        scanner = LampEventScanner(PROFILE, LAMP_CONFIG, TRACKER_CONFIG)
        off_frame_origin = (FRAME_W - 30, 80)
        for index in range(100):
            origin = off_frame_origin if 20 <= index < 60 else ORIGIN
            scanner.feed(_lamp_hsv_frame(origin=origin), _track(index, origin=origin))

        _, gaps = scanner.finish()

        assert gaps == [CoverageGap(start_frame=20, end_frame=59, reason="off_frame")]

    def test_a_gap_shorter_than_the_reportable_minimum_is_not_reported(self):
        scanner = LampEventScanner(PROFILE, LAMP_CONFIG, TRACKER_CONFIG)
        short = LAMP_CONFIG.coverage_gap_min_frames - 1
        for index in range(100):
            corr = 0.2 if 20 <= index < 20 + short else 0.9
            scanner.feed(_lamp_hsv_frame(), _track(index, corr=corr))

        _, gaps = scanner.finish()

        assert gaps == []

    def test_a_gap_exactly_at_the_reportable_minimum_is_reported(self):
        scanner = LampEventScanner(PROFILE, LAMP_CONFIG, TRACKER_CONFIG)
        exact = LAMP_CONFIG.coverage_gap_min_frames
        for index in range(100):
            corr = 0.2 if 20 <= index < 20 + exact else 0.9
            scanner.feed(_lamp_hsv_frame(), _track(index, corr=corr))

        _, gaps = scanner.finish()

        assert [g.frame_count for g in gaps] == [exact]

    def test_an_unreadable_stretch_running_to_the_end_is_still_closed(self):
        scanner = LampEventScanner(PROFILE, LAMP_CONFIG, TRACKER_CONFIG)
        for index in range(60):
            corr = 0.9 if index < 20 else 0.1
            scanner.feed(_lamp_hsv_frame(), _track(index, corr=corr))

        _, gaps = scanner.finish()

        assert gaps == [CoverageGap(start_frame=20, end_frame=59, reason="unlocked")]

    def test_off_frame_wins_when_one_gap_mixes_both_reasons(self):
        scanner = LampEventScanner(PROFILE, LAMP_CONFIG, TRACKER_CONFIG)
        off_frame_origin = (FRAME_W - 30, 80)
        for index in range(80):
            if 20 <= index < 40:
                scanner.feed(_lamp_hsv_frame(), _track(index, corr=0.1))
            elif 40 <= index < 60:
                scanner.feed(
                    _lamp_hsv_frame(origin=off_frame_origin),
                    _track(index, origin=off_frame_origin),
                )
            else:
                scanner.feed(_lamp_hsv_frame(), _track(index))

        _, gaps = scanner.finish()

        assert gaps == [CoverageGap(start_frame=20, end_frame=59, reason="off_frame")]


class TestLampEventScannerDoesNotConflateUnreadableWithUnlit:
    def test_an_unreadable_stretch_is_reported_as_a_gap_not_as_silence(self):
        # A three-frame burst is dropped as an artefact and the 37 frames that
        # follow cannot be read at all. Treating unreadable frames as "lamp off"
        # would answer "no lamp fired in this clip" — a clean, wrong, silent
        # report. The module must instead answer "nothing seen, and here is the
        # stretch I could not look at", which is what makes a lost touch
        # visible as a lost touch.
        scanner = LampEventScanner(PROFILE, LAMP_CONFIG, TRACKER_CONFIG)
        for index in range(60):
            if index < 3:
                scanner.feed(_lamp_hsv_frame(_lamp_fill(RED_HUE)), _track(index))
            elif index < 40:
                scanner.feed(_lamp_hsv_frame(), _track(index, corr=0.1))
            else:
                scanner.feed(_lamp_hsv_frame(), _track(index))

        events, gaps = scanner.finish()

        assert events == []
        assert gaps == [CoverageGap(start_frame=3, end_frame=39, reason="unlocked")]
        assert scanner.readable_frames == 23
        assert scanner.total_frames == 60

    def test_unreadable_frames_inside_an_activation_do_not_colour_the_event(self):
        # The unreadable frames sit in the middle of a red activation. If they
        # were read as pixels rather than skipped, their hueless content would
        # be averaged into the colour decision; the event must still be red.
        scanner = LampEventScanner(PROFILE, LAMP_CONFIG, TRACKER_CONFIG)
        for index in range(60):
            if 10 <= index < 16:
                scanner.feed(_lamp_hsv_frame(_lamp_fill(RED_HUE)), _track(index))
            elif 16 <= index < 24:
                scanner.feed(_lamp_hsv_frame(), _track(index, corr=0.1))
            elif 24 <= index < 30:
                scanner.feed(_lamp_hsv_frame(_lamp_fill(RED_HUE)), _track(index))
            else:
                scanner.feed(_lamp_hsv_frame(), _track(index))

        events, _ = scanner.finish()

        assert [(e.onset_frame, e.end_frame) for e in events] == [(10, 29)]
        assert events[0].left_colour == COLOUR_RED


class TestLampEventScannerRefusesToReadAPositionWithNoDisplay:
    """The gate that catches a tracker locked onto something that is not a panel.

    Correlation cannot tell a real scoreboard from a convincing impostor: on
    ``260816_venue2_bout`` the piste's painted boundary line matched at 0.63 — above the
    reacquisition floor, so the track never recovered — and the module went on
    "reading lamps" off bare floor for minutes. What separates the two is
    physical: a scoring box emits light, and every hijacked frame measured
    exactly 0.0000 lit fraction in the score ROIs against 0.049–0.093 on genuine
    locks.
    """

    def test_a_tracked_frame_whose_score_rois_are_dark_is_unreadable_as_no_display(self):
        scanner = LampEventScanner(PROFILE, LAMP_CONFIG, TRACKER_CONFIG)
        for index in range(100):
            scanner.feed(_lamp_hsv_frame(display=not (20 <= index < 60)), _track(index))

        _, gaps = scanner.finish()

        assert gaps == [CoverageGap(start_frame=20, end_frame=59, reason="no_display")]
        assert scanner.readable_frames == 60
        assert scanner.total_frames == 100

    def test_a_lamp_lit_where_no_display_exists_is_never_reported_as_an_event(self):
        # THE regression guard for the hijacked-tracker bug. The lamp ROIs carry
        # pixels that unambiguously read as ON — the control below proves it by
        # feeding the identical lamps with the digits lit and getting an event —
        # so the only thing standing between this frame and an invented touch in
        # a customer's report is the display gate. It must hold.
        hijacked = LampEventScanner(PROFILE, LAMP_CONFIG, TRACKER_CONFIG)
        for index in range(120):
            left = _lamp_fill(RED_HUE) if 20 <= index < 90 else None
            hijacked.feed(_lamp_hsv_frame(left, display=False), _track(index))

        events, gaps = hijacked.finish()

        assert events == []
        assert gaps == [CoverageGap(start_frame=0, end_frame=119, reason="no_display")]
        assert hijacked.readable_frames == 0

        # Control: the same lamps over a lit display are a red event.
        genuine = LampEventScanner(PROFILE, LAMP_CONFIG, TRACKER_CONFIG)
        for index in range(120):
            left = _lamp_fill(RED_HUE) if 20 <= index < 90 else None
            genuine.feed(_lamp_hsv_frame(left), _track(index))

        control_events, control_gaps = genuine.finish()

        assert [(e.onset_frame, e.end_frame) for e in control_events] == [(20, 89)]
        assert control_events[0].left_colour == COLOUR_RED
        assert control_gaps == []

    def test_score_rois_off_frame_skip_the_gate_instead_of_blacking_out_the_lamps(self):
        # The panel has drifted low enough that the digits are below the crop
        # while the lamps are still in it. There is no display to measure, so
        # there is nothing to disbelieve — the gate must stand aside rather than
        # turn "score ROI off-frame" into a silent lamp blackout.
        below = (100, FRAME_H - 50)
        assert display_lit_fraction(
            _lamp_hsv_frame(origin=below), _track(0, origin=below), PROFILE, SCORE_CONFIG,
        ) is None

        scanner = LampEventScanner(PROFILE, LAMP_CONFIG, TRACKER_CONFIG)
        for index in range(60):
            left = _lamp_fill(RED_HUE) if 10 <= index < 40 else None
            scanner.feed(
                _lamp_hsv_frame(left, origin=below), _track(index, origin=below),
            )

        events, gaps = scanner.finish()

        assert [(e.onset_frame, e.end_frame) for e in events] == [(10, 39)]
        assert events[0].left_colour == COLOUR_RED
        assert gaps == []


class TestDisplayLitFraction:
    def test_a_glowing_display_measures_above_the_gate_and_like_a_real_one(self):
        measured = display_lit_fraction(
            _lamp_hsv_frame(), _track(0), PROFILE, SCORE_CONFIG,
        )

        assert measured == pytest.approx(DISPLAY_LIT_FRACTION)
        assert measured >= SCORE_CONFIG.display_min_fraction
        # The band measured on genuine locks; the fixture has to sit in it rather
        # than clear the gate by flooding the ROI.
        assert 0.049 <= measured <= 0.093

    def test_a_dark_score_roi_measures_exactly_zero(self):
        # 0.0000 is the number every hijacked frame produced.
        assert display_lit_fraction(
            _lamp_hsv_frame(display=False), _track(0), PROFILE, SCORE_CONFIG,
        ) == 0.0
        assert 0.0 < SCORE_CONFIG.display_min_fraction

    def test_a_bright_but_desaturated_patch_is_not_a_display(self):
        # digit_mask wants value, saturation and hue in range simultaneously, so
        # a blown-out white glare on the panel is not evidence of a score.
        frame = np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8)
        for side in SIDES:
            x, y, w, h = absolute_roi(ORIGIN, PROFILE.digit_rois[side])
            frame[y:y + h, x:x + w] = (RED_HUE, 10, 255)

        assert display_lit_fraction(frame, _track(0), PROFILE, SCORE_CONFIG) == 0.0

    def test_it_is_none_when_every_digit_roi_is_off_frame(self):
        below = (100, FRAME_H - 50)

        assert display_lit_fraction(
            _lamp_hsv_frame(origin=below), _track(0, origin=below), PROFILE, SCORE_CONFIG,
        ) is None

    def test_it_averages_the_two_sides_but_counts_only_the_visible_ones(self):
        # Both sides visible, one lit: the average halves the reading.
        half = _paint_display(
            np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8), sides=(LEFT,),
        )
        assert display_lit_fraction(
            half, _track(0), PROFILE, SCORE_CONFIG,
        ) == pytest.approx(DISPLAY_LIT_FRACTION / 2)

        # At this origin the right digit ROI hangs off the frame, so the visible
        # left side is the whole answer and is not halved by an absent sibling.
        edge = (260, 80)
        one_side = _paint_display(
            np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8), origin=edge, sides=(LEFT,),
        )
        assert display_lit_fraction(
            one_side, _track(0, origin=edge), PROFILE, SCORE_CONFIG,
        ) == pytest.approx(DISPLAY_LIT_FRACTION)


class TestLampEventProperties:
    def test_a_chromatic_lamp_on_a_side_means_that_side_scored_validly(self):
        assert _event(left=COLOUR_RED).left_valid is True
        assert _event(right=COLOUR_GREEN).right_valid is True
        assert set(CHROMATIC_COLOURS) == {COLOUR_RED, COLOUR_GREEN}

    def test_a_white_lamp_is_a_lamp_but_not_a_valid_hit(self):
        event = _event(left=COLOUR_WHITE)
        assert event.left_valid is False
        assert event.any_valid is False

    def test_both_chromatic_lamps_flag_a_priority_situation(self):
        event = _event(left=COLOUR_RED, right=COLOUR_GREEN)
        assert event.both_valid is True
        assert event.any_valid is True


# ----------------------------------------------------------------------
# mask_similarity
# ----------------------------------------------------------------------


def _block_mask(top, left, size=10, shape=(24, 24)):
    mask = np.zeros(shape, dtype=bool)
    mask[top:top + size, left:left + size] = True
    return mask


class TestMaskSimilarity:
    def test_identical_masks_are_a_perfect_match(self):
        mask = _block_mask(5, 5)
        assert mask_similarity(mask, mask, SCORE_CONFIG.align_radius) == pytest.approx(1.0)

    def test_a_shift_inside_the_align_radius_is_still_a_perfect_match(self):
        radius = SCORE_CONFIG.align_radius
        assert mask_similarity(
            _block_mask(5, 5), _block_mask(5 + radius, 5 + radius), radius
        ) == pytest.approx(1.0)

    def test_a_shift_beyond_the_align_radius_scores_lower(self):
        radius = SCORE_CONFIG.align_radius
        far = mask_similarity(_block_mask(5, 5), _block_mask(5 + radius + 4, 5), radius)

        assert far < 1.0
        assert far < SCORE_CONFIG.similarity_min

    def test_two_empty_masks_count_as_unchanged(self):
        empty = np.zeros((24, 24), dtype=bool)
        assert mask_similarity(empty, empty, SCORE_CONFIG.align_radius) == pytest.approx(1.0)

    def test_an_empty_mask_against_a_filled_one_shares_nothing(self):
        empty = np.zeros((24, 24), dtype=bool)
        assert mask_similarity(_block_mask(5, 5), empty, SCORE_CONFIG.align_radius) == 0.0
        assert mask_similarity(empty, _block_mask(5, 5), SCORE_CONFIG.align_radius) == 0.0

    def test_masks_of_different_shapes_share_nothing(self):
        assert mask_similarity(
            _block_mask(5, 5), _block_mask(5, 5, shape=(20, 20)), SCORE_CONFIG.align_radius
        ) == 0.0

    def test_a_thin_stroke_inside_a_solid_block_scores_far_below_threshold(self):
        block = np.zeros((30, 30), dtype=bool)
        block[5:25, 5:25] = True
        stroke = np.zeros((30, 30), dtype=bool)
        stroke[5:25, 14:16] = True

        assert mask_similarity(block, stroke, SCORE_CONFIG.align_radius) < SCORE_CONFIG.similarity_min


# ----------------------------------------------------------------------
# event_intervals
# ----------------------------------------------------------------------


class TestEventIntervals:
    def test_a_bout_with_no_lamp_event_is_one_interval(self):
        assert event_intervals([], 500, SCORE_CONFIG) == [(0, 500)]

    def test_one_onset_splits_the_bout_at_the_onset_and_after_the_settle(self):
        settle = SCORE_CONFIG.settle_frames
        assert event_intervals([200], 500, SCORE_CONFIG) == [(0, 200), (200 + settle, 500)]

    def test_there_is_always_one_more_interval_than_onsets(self):
        onsets = [100, 300, 600, 900]
        assert len(event_intervals(onsets, 1200, SCORE_CONFIG)) == len(onsets) + 1

    def test_each_interval_runs_from_after_its_settle_to_the_next_onset(self):
        settle = SCORE_CONFIG.settle_frames
        assert event_intervals([100, 300], 500, SCORE_CONFIG) == [
            (0, 100),
            (100 + settle, 300),
            (300 + settle, 500),
        ]


# ----------------------------------------------------------------------
# ScoreChangeDetector
# ----------------------------------------------------------------------


class TestScoreChangeDetectorSampleRetention:
    def test_no_settled_sample_exists_before_the_window_fills(self):
        detector = ScoreChangeDetector(PROFILE, SCORE_CONFIG, TRACKER_CONFIG)
        _feed_digits(detector, SCORE_CONFIG.window_frames - 1, "block", "block")

        assert detector.interval_state(LEFT, 0, 40) == []

    def test_the_first_sample_lands_on_the_first_stride_boundary_after_the_window(self):
        # Frames 0..29: the window fills at frame 20, but no frame in 20..29 is
        # divisible by the stride of 15, so nothing is retained yet.
        short = ScoreChangeDetector(PROFILE, SCORE_CONFIG, TRACKER_CONFIG)
        _feed_digits(short, 30, "block", "block")
        assert short.interval_state(LEFT, 0, 40) == []

        # One more frame reaches frame 30, the first qualifying boundary.
        long = ScoreChangeDetector(PROFILE, SCORE_CONFIG, TRACKER_CONFIG)
        _feed_digits(long, 31, "block", "block")
        assert [f for f, _ in long._samples[LEFT]] == [30]

    def test_unlocked_frames_contribute_nothing_to_the_window(self):
        detector = ScoreChangeDetector(PROFILE, SCORE_CONFIG, TRACKER_CONFIG)
        for index in range(120):
            detector.feed(_digit_hsv_frame("block", "block"), _track(index, corr=0.1))

        assert detector.interval_state(LEFT, 0, 120) == []

    def test_only_the_tail_of_a_long_interval_is_sampled(self):
        detector = ScoreChangeDetector(PROFILE, SCORE_CONFIG, TRACKER_CONFIG)
        _feed_digits(detector, 500, "block", "block")

        frames = [f for f, _ in detector._samples[LEFT]]
        tail = detector.interval_state(LEFT, 0, 500)

        assert min(frames) < 500 - SCORE_CONFIG.tail_frames
        assert len(tail) < len(frames)
        assert len(tail) == sum(1 for f in frames if f >= 500 - SCORE_CONFIG.tail_frames)


class TestScoreChangeDetectorCompare:
    def test_too_few_retained_samples_declines_the_comparison(self):
        detector = ScoreChangeDetector(PROFILE, SCORE_CONFIG, TRACKER_CONFIG)
        # 60 frames retains samples at 30 and 45 only — one short of min_samples.
        _feed_digits(detector, 60, "block", "block")

        comparison = detector.compare((0, 60), (0, 60))

        assert len(detector.interval_state(LEFT, 0, 60)) < SCORE_CONFIG.min_samples
        assert comparison.determined is False
        assert comparison.changed == frozenset()
        assert comparison.similarity[LEFT] is None

    def test_an_empty_second_interval_declines_the_comparison(self):
        detector = ScoreChangeDetector(PROFILE, SCORE_CONFIG, TRACKER_CONFIG)
        _feed_digits(detector, 200, "block", "block")

        comparison = detector.compare((0, 200), (200, 400))

        assert comparison.determined is False

    def test_enough_samples_on_both_sides_determines_the_comparison(self):
        detector = ScoreChangeDetector(PROFILE, SCORE_CONFIG, TRACKER_CONFIG)
        _feed_digits(detector, 500, "block", "block")

        comparison = detector.compare((0, 200), (275, 500))

        assert comparison.determined is True
        assert comparison.changed == frozenset()
        assert comparison.similarity[LEFT] == pytest.approx(1.0)
        assert comparison.similarity[RIGHT] == pytest.approx(1.0)

    def test_a_digit_that_changes_across_the_boundary_is_reported_changed(self):
        detector = ScoreChangeDetector(PROFILE, SCORE_CONFIG, TRACKER_CONFIG)
        _feed_digits(
            detector, 500, ("block", "bar"), ("block", "block"), change_at=200,
        )

        comparison = detector.compare((0, 200), (275, 500))

        assert comparison.determined is True
        assert comparison.changed == frozenset({LEFT})
        assert comparison.similarity[LEFT] < SCORE_CONFIG.similarity_min
        assert comparison.similarity[RIGHT] == pytest.approx(1.0)

    def test_both_digits_changing_reports_both_sides(self):
        detector = ScoreChangeDetector(PROFILE, SCORE_CONFIG, TRACKER_CONFIG)
        _feed_digits(detector, 500, ("block", "bar"), ("block", "bar"), change_at=200)

        comparison = detector.compare((0, 200), (275, 500))

        assert comparison.changed == frozenset({LEFT, RIGHT})


# ----------------------------------------------------------------------
# resolve_touches
# ----------------------------------------------------------------------


class TestResolveTouches:
    def test_a_chromatic_lamp_with_one_side_changing_is_a_touch_by_that_side(self):
        events = [_event(left=COLOUR_RED)]

        resolutions = resolve_touches(events, [_comparison(changed={LEFT})])

        assert len(resolutions) == 1
        assert resolutions[0].verdict == VERDICT_TOUCH
        assert resolutions[0].scorer == LEFT
        assert resolutions[0].score_before == (0, 0)
        assert resolutions[0].score_after == (1, 0)
        assert resolutions[0].priority_call is False

    def test_a_right_side_touch_increments_only_the_right_tally(self):
        resolutions = resolve_touches(
            [_event(right=COLOUR_GREEN)], [_comparison(changed={RIGHT})],
        )

        assert resolutions[0].scorer == RIGHT
        assert resolutions[0].score_after == (0, 1)

    def test_both_lamps_chromatic_with_one_side_changing_is_a_priority_call(self):
        resolutions = resolve_touches(
            [_event(left=COLOUR_RED, right=COLOUR_GREEN)], [_comparison(changed={RIGHT})],
        )

        assert resolutions[0].verdict == VERDICT_TOUCH
        assert resolutions[0].priority_call is True
        assert resolutions[0].scorer == RIGHT
        assert resolutions[0].score_after == (0, 1)

    def test_both_sides_changing_awards_a_point_to_each(self):
        resolutions = resolve_touches(
            [_event(left=COLOUR_RED, right=COLOUR_GREEN)],
            [_comparison(changed={LEFT, RIGHT})],
        )

        assert resolutions[0].scorer == "both"
        assert resolutions[0].score_after == (1, 1)

    def test_a_chromatic_lamp_with_no_score_change_is_annulled(self):
        resolutions = resolve_touches([_event(left=COLOUR_RED)], [_comparison(changed=set())])

        assert resolutions[0].verdict == VERDICT_ANNULLED
        assert resolutions[0].scorer is None
        assert resolutions[0].score_before == resolutions[0].score_after == (0, 0)

    def test_white_lamps_alone_are_off_target_regardless_of_the_score(self):
        # The comparison says the left digits changed, and it is never consulted:
        # a white-only event short-circuits before the score is looked at.
        resolutions = resolve_touches(
            [_event(left=COLOUR_WHITE, right=COLOUR_WHITE)],
            [_comparison(changed={LEFT})],
        )

        assert resolutions[0].verdict == VERDICT_OFF_TARGET
        assert resolutions[0].scorer is None
        assert resolutions[0].score_after == (0, 0)
        assert resolutions[0].priority_call is False

    def test_a_chromatic_lamp_with_an_undetermined_score_is_undetermined(self):
        resolutions = resolve_touches(
            [_event(left=COLOUR_RED)], [_comparison(determined=False)],
        )

        assert resolutions[0].verdict == VERDICT_UNDETERMINED
        assert resolutions[0].scorer is None
        assert resolutions[0].score_before == resolutions[0].score_after == (0, 0)

    def test_a_missing_comparison_is_undetermined_rather_than_annulled(self):
        resolutions = resolve_touches([_event(left=COLOUR_RED)], [])

        assert resolutions[0].verdict == VERDICT_UNDETERMINED

    def test_a_start_score_is_honoured_as_the_first_score_before(self):
        resolutions = resolve_touches(
            [_event(left=COLOUR_RED)], [_comparison(changed={LEFT})], start_score=(3, 2),
        )

        assert resolutions[0].score_before == (3, 2)
        assert resolutions[0].score_after == (4, 2)

    def test_the_tally_carries_across_a_mixed_sequence_of_verdicts(self):
        events = [
            _event(onset=100, left=COLOUR_RED),                      # touch, left
            _event(onset=300, left=COLOUR_WHITE),                    # off-target
            _event(onset=500, right=COLOUR_GREEN),                   # annulled
            _event(onset=700, right=COLOUR_GREEN),                   # touch, right
            _event(onset=900, left=COLOUR_RED),                      # undetermined
            _event(onset=1100, left=COLOUR_RED, right=COLOUR_GREEN),  # priority, left
        ]
        comparisons = [
            _comparison(changed={LEFT}),
            _comparison(changed={LEFT}),
            _comparison(changed=set()),
            _comparison(changed={RIGHT}),
            _comparison(determined=False),
            _comparison(changed={LEFT}),
        ]

        resolutions = resolve_touches(events, comparisons, start_score=(1, 0))

        assert [r.verdict for r in resolutions] == [
            VERDICT_TOUCH,
            VERDICT_OFF_TARGET,
            VERDICT_ANNULLED,
            VERDICT_TOUCH,
            VERDICT_UNDETERMINED,
            VERDICT_TOUCH,
        ]
        assert [r.scorer for r in resolutions] == [LEFT, None, None, RIGHT, None, LEFT]
        assert [r.score_before for r in resolutions] == [
            (1, 0), (2, 0), (2, 0), (2, 0), (2, 1), (2, 1),
        ]
        assert [r.score_after for r in resolutions] == [
            (2, 0), (2, 0), (2, 0), (2, 1), (2, 1), (3, 1),
        ]
        assert [r.priority_call for r in resolutions] == [
            False, False, False, False, False, True,
        ]

    def test_events_are_resolved_in_onset_order_whatever_order_they_arrive_in(self):
        events = [_event(onset=500, right=COLOUR_GREEN), _event(onset=100, left=COLOUR_RED)]
        comparisons = [_comparison(changed={LEFT}), _comparison(changed={RIGHT})]

        resolutions = resolve_touches(events, comparisons)

        assert [r.event.onset_frame for r in resolutions] == [100, 500]
        assert [r.scorer for r in resolutions] == [LEFT, RIGHT]

    def test_no_events_resolve_to_no_resolutions(self):
        assert resolve_touches([], []) == []


# ----------------------------------------------------------------------
# resolutions_to_match_events
# ----------------------------------------------------------------------


def _resolution(event, scorer=None, verdict=VERDICT_TOUCH, before=(0, 0), after=(0, 0),
                priority=False):
    return TouchResolution(event, scorer, verdict, before, after, priority)


class TestResolutionsToMatchEvents:
    def test_the_frame_is_the_lamp_onset_frame_with_no_fps_conversion(self):
        # Frame indices in this pipeline are work-file frames and are never
        # rescaled. Multiplying or dividing by fps here is the recurring bug
        # this assertion exists to catch, so the onset must survive verbatim at
        # any fps.
        resolution = _resolution(_event(onset=1234, left=COLOUR_RED), scorer=LEFT,
                                 after=(1, 0))

        for fps in (25.0, 30.0, 59.94, 120.0):
            [match_event] = resolutions_to_match_events([resolution], fps=fps)
            assert match_event.frame == 1234

    def test_the_video_timestamp_is_the_only_thing_fps_affects(self):
        resolution = _resolution(_event(onset=1800, left=COLOUR_RED), scorer=LEFT,
                                 after=(1, 0))

        [at_thirty] = resolutions_to_match_events([resolution], fps=30.0)
        [at_sixty] = resolutions_to_match_events([resolution], fps=60.0)

        assert at_thirty.frame == at_sixty.frame == 1800
        assert at_thirty.video_timestamp == "1:00"
        assert at_sixty.video_timestamp == "0:30"

    def test_lamp_red_follows_the_left_side_not_the_observed_hue(self):
        # The right fencer's lamp is red in this staging; the flags describe
        # which *side* fired a valid lamp, so lamp_green must be the true one.
        resolution = _resolution(_event(right=COLOUR_RED), scorer=RIGHT, after=(0, 1))

        [match_event] = resolutions_to_match_events([resolution])

        assert match_event.lamp_red is False
        assert match_event.lamp_green is True

    def test_lamp_green_follows_the_right_side_not_the_observed_hue(self):
        resolution = _resolution(_event(left=COLOUR_GREEN), scorer=LEFT, after=(1, 0))

        [match_event] = resolutions_to_match_events([resolution])

        assert match_event.lamp_red is True
        assert match_event.lamp_green is False

    def test_both_lamps_are_flagged_for_a_double(self):
        resolution = _resolution(
            _event(left=COLOUR_RED, right=COLOUR_GREEN), scorer="both", after=(1, 1),
        )

        [match_event] = resolutions_to_match_events([resolution])

        assert match_event.lamp_red is True
        assert match_event.lamp_green is True
        assert match_event.event_type == EventType.SIMULTANEOUS.value

    def test_a_white_only_event_flags_neither_lamp(self):
        resolution = _resolution(
            _event(left=COLOUR_WHITE, right=COLOUR_WHITE), verdict=VERDICT_OFF_TARGET,
        )

        [match_event] = resolutions_to_match_events([resolution])

        assert match_event.lamp_red is False
        assert match_event.lamp_green is False

    def test_every_resolution_becomes_an_event_including_the_non_scoring_ones(self):
        resolutions = [
            _resolution(_event(onset=100, left=COLOUR_RED), scorer=LEFT, after=(1, 0)),
            _resolution(_event(onset=300, left=COLOUR_WHITE), verdict=VERDICT_OFF_TARGET,
                        before=(1, 0), after=(1, 0)),
            _resolution(_event(onset=500, right=COLOUR_GREEN), verdict=VERDICT_ANNULLED,
                        before=(1, 0), after=(1, 0)),
            _resolution(_event(onset=700, left=COLOUR_RED), verdict=VERDICT_UNDETERMINED,
                        before=(1, 0), after=(1, 0)),
        ]

        match_events = resolutions_to_match_events(resolutions)

        assert [e.frame for e in match_events] == [100, 300, 500, 700]
        assert [e.scorer for e in match_events] == [LEFT, None, None, None]
        assert [e.event_type for e in match_events] == [
            EventType.SINGLE_TOUCH.value,
            EventType.INVALID_TOUCH.value,
            EventType.INVALID_TOUCH.value,
            EventType.INVALID_TOUCH.value,
        ]

    def test_the_running_score_is_rendered_either_side_of_the_event(self):
        resolution = _resolution(_event(left=COLOUR_RED), scorer=LEFT,
                                 before=(2, 3), after=(3, 3))

        [match_event] = resolutions_to_match_events([resolution])

        assert match_event.score_before == "2-3"
        assert match_event.score_after == "3-3"

    def test_the_observed_hue_survives_in_the_description(self):
        resolution = _resolution(_event(left=COLOUR_RED), verdict=VERDICT_ANNULLED)

        [match_event] = resolutions_to_match_events([resolution])

        assert "left red" in match_event.description

    def test_no_resolutions_produce_no_events(self):
        assert resolutions_to_match_events([]) == []


# ----------------------------------------------------------------------
# MachineProfile
# ----------------------------------------------------------------------


class TestMachineProfile:
    def test_a_profile_missing_a_side_of_lamps_is_refused(self):
        with pytest.raises(ValueError, match="lamp_rois"):
            MachineProfile(
                name="half",
                housing_size=(160, 100),
                lamp_rois={LEFT: (0, 0, 10, 10)},
                digit_rois={LEFT: (0, 0, 10, 10), RIGHT: (20, 0, 10, 10)},
            )

    def test_a_profile_missing_a_side_of_digits_is_refused(self):
        with pytest.raises(ValueError, match="digit_rois"):
            MachineProfile(
                name="half",
                housing_size=(160, 100),
                lamp_rois={LEFT: (0, 0, 10, 10), RIGHT: (20, 0, 10, 10)},
                digit_rois={RIGHT: (20, 0, 10, 10)},
            )
