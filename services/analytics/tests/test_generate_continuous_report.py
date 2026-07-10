"""Unit tests for pure logic in scripts/generate_continuous_report.py.

Covers the side-effect-free helpers:
- format_timestamp(): frame -> "M:SS"
- _distance_zone(): bell-guard distance -> fencing zone name
"""

import pytest

from scripts.generate_continuous_report import format_timestamp, _distance_zone


class TestFormatTimestamp:
    """format_timestamp(frame, fps) -> 'M:SS'."""

    def test_zero_frame(self):
        assert format_timestamp(0, 30.0) == "0:00"

    def test_one_second(self):
        assert format_timestamp(30, 30.0) == "0:01"

    def test_exactly_one_minute(self):
        assert format_timestamp(1800, 30.0) == "1:00"

    def test_one_minute_one_second(self):
        assert format_timestamp(1830, 30.0) == "1:01"

    def test_seconds_zero_padded(self):
        # 3 seconds -> "0:03" (two-digit seconds)
        assert format_timestamp(90, 30.0) == "0:03"

    def test_fractional_second_truncates(self):
        # 45 frames @ 30fps = 1.5s -> truncated to 1s
        assert format_timestamp(45, 30.0) == "0:01"

    def test_non_integer_fps(self):
        # 60 frames @ 24fps = 2.5s -> "0:02"
        assert format_timestamp(60, 24.0) == "0:02"


class TestDistanceZone:
    """_distance_zone(bh) maps bell-guard-height distance to a zone name."""

    def test_out_of_distance(self):
        assert _distance_zone(3.0) == "out_of_distance"

    def test_just_above_out_of_distance_threshold(self):
        assert _distance_zone(1.9) == "out_of_distance"

    def test_boundary_1_8_is_advance_lunge(self):
        # 1.8 is NOT > 1.8, so falls to the next bucket
        assert _distance_zone(1.8) == "advance_lunge"

    def test_advance_lunge(self):
        assert _distance_zone(1.6) == "advance_lunge"

    def test_boundary_1_5_is_lunge(self):
        assert _distance_zone(1.5) == "lunge"

    def test_lunge(self):
        assert _distance_zone(1.3) == "lunge"

    def test_boundary_1_2_is_extension(self):
        assert _distance_zone(1.2) == "extension"

    def test_extension(self):
        assert _distance_zone(1.0) == "extension"

    def test_boundary_0_8_is_infighting(self):
        assert _distance_zone(0.8) == "infighting"

    def test_infighting(self):
        assert _distance_zone(0.5) == "infighting"

    def test_zero_distance(self):
        assert _distance_zone(0.0) == "infighting"

    @pytest.mark.parametrize("bh,expected", [
        (2.5, "out_of_distance"),
        (1.81, "out_of_distance"),
        (1.51, "advance_lunge"),
        (1.21, "lunge"),
        (0.81, "extension"),
        (0.79, "infighting"),
    ])
    def test_parametrized_boundaries(self, bh, expected):
        assert _distance_zone(bh) == expected
