"""Unit tests for scripts/build_referee_exam_set.py.

No video is decoded. Frames are synthesised at the real 1280x720 so the tests
exercise the same downscale the script performs, and every threshold under test
is a fraction rather than a pixel count — a card is a card at any resolution.

The cases that matter are the two frames that look alike to a brightness rule:
a question slate and the closing "answers are in the description below" card.
Both are dark; only the ink span separates them, and mistaking the second for
the first would silently produce a sixteenth question and shift every answer.
"""

import cv2
import numpy as np
import pytest

from scripts.build_referee_exam_set import (
    CARD_MAX_INK_SPAN,
    SLATE_MAX_MEAN,
    SlateMetrics,
    build_manifest,
    clip_spans,
    find_runs,
    is_number_card,
    is_slate,
    slate_metrics,
)

FRAME_W, FRAME_H = 1280, 720

#: The exam's slate colour, measured off the source: #212121.
SLATE_GREY = 33


# ------------------------------------------------------------------
# Frame builders
# ------------------------------------------------------------------


def blank_slate(grey: int = SLATE_GREY, size=(FRAME_H, FRAME_W)) -> np.ndarray:
    """A uniformly dark frame with no ink on it (a fade frame)."""
    return np.full((size[0], size[1], 3), grey, dtype=np.uint8)


def write(frame, text, org, scale, thickness) -> np.ndarray:
    """Draw white text, strokes and all.

    Text is drawn rather than block-filled because the thresholds under test are
    *ink fractions*, and a solid rectangle of the same bounding box carries an
    order of magnitude more white than the glyphs that actually appear on the
    slate. Rendered this way the synthetic frames land within 10% of every
    number measured off the source video.
    """
    cv2.putText(
        frame, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale,
        (255, 255, 255), thickness, cv2.LINE_AA,
    )
    return frame


def number_card(text: str = "1") -> np.ndarray:
    """A dark slate with a small centred white numeral, as questions 1-15 are."""
    org_x = 615 if len(text) == 1 else 585
    return write(blank_slate(), text, (org_x, 370), 3.0, 6)


def outro_card() -> np.ndarray:
    """The closing card: as dark as a question slate, but text-wide."""
    frame = blank_slate()
    write(frame, "Answers are in the", (255, 250), 2.4, 5)
    write(frame, "description below", (280, 360), 2.4, 5)
    return write(frame, "Thanks for watching", (420, 450), 1.4, 3)


def broadcast_frame(grey: int = 100) -> np.ndarray:
    """A mid-grey frame standing in for the piste footage between slates."""
    return np.full((FRAME_H, FRAME_W, 3), grey, dtype=np.uint8)


# ------------------------------------------------------------------
# slate_metrics
# ------------------------------------------------------------------


class TestSlateMetrics:
    def test_blank_slate_reports_no_ink(self):
        m = slate_metrics(blank_slate())
        assert m.mean == pytest.approx(SLATE_GREY, abs=1.0)
        assert m.ink_fraction == 0.0
        assert m.ink_span_x == 0.0
        assert m.ink_span_y == 0.0

    def test_number_card_ink_is_small_and_centred(self):
        m = slate_metrics(number_card())
        assert m.mean < SLATE_MAX_MEAN
        assert 0 < m.ink_fraction < 0.01
        assert m.ink_span_x < CARD_MAX_INK_SPAN
        assert m.ink_span_y < CARD_MAX_INK_SPAN
        assert m.centre_offset_x < 0.05
        assert m.centre_offset_y < 0.10

    def test_outro_ink_spans_most_of_the_frame(self):
        m = slate_metrics(outro_card())
        # Just as dark as a question card…
        assert m.mean < SLATE_MAX_MEAN
        # …but its ink is nothing like a numeral's.
        assert m.ink_span_x > CARD_MAX_INK_SPAN

    def test_accepts_single_channel_frames(self):
        colour = slate_metrics(number_card())
        grey = slate_metrics(number_card()[:, :, 0])
        assert grey == colour

    def test_metrics_are_resolution_independent(self):
        """Half-size frame, same proportions — still a card."""
        small = blank_slate(size=(FRAME_H // 2, FRAME_W // 2))
        write(small, "15", (292, 185), 1.5, 3)
        half = slate_metrics(small)
        assert is_number_card(half)
        assert half.ink_span_x == pytest.approx(
            slate_metrics(number_card("15")).ink_span_x, abs=0.03,
        )


# ------------------------------------------------------------------
# Classification
# ------------------------------------------------------------------


class TestIsSlate:
    def test_dark_frames_are_slates_whatever_is_written_on_them(self):
        assert is_slate(slate_metrics(number_card()))
        assert is_slate(slate_metrics(outro_card()))
        assert is_slate(slate_metrics(blank_slate()))

    def test_broadcast_frame_is_not_a_slate(self):
        assert not is_slate(slate_metrics(broadcast_frame()))

    def test_darkest_measured_broadcast_frame_stays_out(self):
        """46.9 was the darkest broadcast frame in the source exam."""
        assert not is_slate(slate_metrics(broadcast_frame(47)))


class TestIsNumberCard:
    def test_number_card_is_a_card(self):
        assert is_number_card(slate_metrics(number_card()))

    def test_outro_card_is_rejected_on_ink_span(self):
        assert not is_number_card(slate_metrics(outro_card()))

    def test_blank_slate_is_rejected_for_carrying_no_number(self):
        assert not is_number_card(slate_metrics(blank_slate()))

    def test_broadcast_frame_is_rejected_for_being_bright(self):
        assert not is_number_card(slate_metrics(broadcast_frame()))

    def test_offset_graphic_on_a_dark_frame_is_rejected(self):
        """A dark frame with a bright corner logo is not a question card."""
        frame = write(blank_slate(), "LOGO", (40, 120), 1.5, 3)
        assert not is_number_card(slate_metrics(frame))

    def test_two_digit_number_is_still_a_card(self):
        """Questions 10-15 are twice as wide as 1-9 and must survive."""
        assert is_number_card(slate_metrics(number_card("15")))

    def test_measured_thresholds_bracket_the_real_values(self):
        """The numbers taken off the source exam, asserted directly.

        Question slates measured mean 31.2-31.5 with ink fraction
        0.0005-0.0019; the outro measured 38.5 with 0.026.
        """
        assert is_number_card(
            SlateMetrics(31.2, 0.0005, 0.04, 0.09, 0.01, 0.02)
        )
        assert is_number_card(
            SlateMetrics(31.5, 0.0019, 0.08, 0.09, 0.01, 0.02)
        )
        assert not is_number_card(
            SlateMetrics(38.5, 0.026, 0.60, 0.40, 0.01, 0.02)
        )


# ------------------------------------------------------------------
# Runs
# ------------------------------------------------------------------


class TestFindRuns:
    def test_empty(self):
        assert find_runs([]) == []

    def test_single_run_is_inclusive(self):
        assert find_runs([False, True, True, True, False]) == [(1, 3)]

    def test_multiple_runs(self):
        flags = [True, True, False, False, True, False, True, True]
        assert find_runs(flags) == [(0, 1), (4, 4), (6, 7)]

    def test_run_reaching_the_end_is_closed(self):
        assert find_runs([False, True, True]) == [(1, 2)]

    def test_short_runs_are_dropped(self):
        flags = [True, False, True, True, True, False]
        assert find_runs(flags, min_length=3) == [(2, 4)]

    def test_short_trailing_run_is_dropped_too(self):
        assert find_runs([True, True, True, False, True], min_length=3) == [(0, 2)]

    def test_all_true(self):
        assert find_runs([True] * 5, min_length=5) == [(0, 4)]


# ------------------------------------------------------------------
# Clip spans
# ------------------------------------------------------------------


class TestClipSpans:
    def test_clip_runs_from_card_end_to_next_slate_start(self):
        cards = [(0, 9), (50, 59)]
        slates = [(0, 9), (50, 59)]
        assert clip_spans(cards, slates, total_frames=100) == [(10, 49), (60, 99)]

    def test_last_clip_stops_at_a_non_card_slate(self):
        """The outro terminates question 15 without becoming question 16."""
        cards = [(0, 9)]
        slates = [(0, 9), (80, 99)]
        assert clip_spans(cards, slates, total_frames=100) == [(10, 79)]

    def test_last_clip_runs_to_end_of_video_when_nothing_follows(self):
        assert clip_spans([(0, 9)], [(0, 9)], total_frames=100) == [(10, 99)]

    def test_no_cards_gives_no_clips(self):
        assert clip_spans([], [(0, 9)], total_frames=100) == []

    def test_slate_runs_need_not_be_sorted(self):
        cards = [(0, 9)]
        slates = [(80, 99), (0, 9), (40, 49)]
        assert clip_spans(cards, slates, total_frames=100) == [(10, 39)]


# ------------------------------------------------------------------
# Manifest
# ------------------------------------------------------------------


class TestBuildManifest:
    @staticmethod
    def _manifest(**kwargs):
        from pathlib import Path
        defaults = dict(
            video_path=Path("/tmp/ref_exam_p2.mp4"),
            prefix="p2",
            fps=30.0,
            total_frames=300,
            card_runs=[(0, 9), (100, 109)],
            spans=[(10, 99), (110, 199)],
            answers={"answers": {"1": "right", "2": "left"}, "weapon": "foil"},
        )
        defaults.update(kwargs)
        return build_manifest(**defaults)

    def test_questions_are_numbered_from_one_in_order(self):
        m = self._manifest()
        assert [q["question"] for q in m["questions"]] == [1, 2]
        assert [q["clip"] for q in m["questions"]] == ["p2_q01.mp4", "p2_q02.mp4"]

    def test_answers_are_merged_by_question_number(self):
        m = self._manifest()
        assert m["questions"][0]["answer"] == "right"
        assert m["questions"][1]["answer"] == "left"

    def test_missing_answer_is_none_rather_than_an_error(self):
        m = self._manifest(answers={"answers": {"1": "right"}})
        assert m["questions"][1]["answer"] is None

    def test_end_sec_stops_half_a_frame_past_the_last_frame(self):
        """Otherwise ffmpeg hands back the next slate's first frame."""
        m = self._manifest()
        q = m["questions"][0]
        assert q["end_sec"] == pytest.approx((99 + 0.5) / 30.0, abs=1e-4)
        assert q["start_sec"] == pytest.approx(10 / 30.0, abs=1e-4)
        assert q["duration_sec"] == pytest.approx(90 / 30.0, abs=1e-3)

    def test_card_frames_are_recorded_alongside_the_clip(self):
        q = self._manifest()["questions"][1]
        assert (q["card_start_frame"], q["card_end_frame"]) == (100, 109)
        assert (q["start_frame"], q["end_frame"]) == (110, 199)

    def test_source_metadata_is_carried_through(self):
        m = self._manifest(
            answers={"answers": {}, "source": "exam part 2", "provided_by": "user"},
        )
        assert m["source"] == "exam part 2"
        assert m["provided_by"] == "user"
        assert m["source_video"] == "ref_exam_p2.mp4"
        assert m["question_count"] == 2
