"""Unit tests for pure logic in scripts/generate_continuous_report.py.

Covers the side-effect-free helpers:
- format_timestamp(): frame -> "M:SS"
- _distance_zone(): bell-guard distance -> fencing zone name
- find_ocr_report(): video stem -> matching OCR report path
"""

import pytest

from scripts.generate_continuous_report import (
    format_timestamp,
    _distance_zone,
    find_ocr_report,
)


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


class TestFindOcrReport:
    """find_ocr_report(video_stem, output_dir) -> Path | None.

    Regression: a video named '<description>_<youtubeID>.mp4' used to find
    nothing, because the old matcher only stripped known prefixes and then
    required the whole stem to be a substring of the candidate. The OCR merge
    was then skipped silently and the report came out with touches=0.
    """

    def _dir(self, tmp_path, *names):
        for n in names:
            (tmp_path / n).write_text("{}", encoding="utf-8")
        return tmp_path

    def test_arbitrary_prefix_before_youtube_id(self, tmp_path):
        d = self._dir(tmp_path, "hKUXgUsDOKE_report.json")
        found = find_ocr_report("jr_foil_final_li_lin_hKUXgUsDOKE", d)
        assert found is not None and found.name == "hKUXgUsDOKE_report.json"

    def test_exact_stem_match(self, tmp_path):
        d = self._dir(tmp_path, "0HeqT9us5wA_report.json")
        found = find_ocr_report("0HeqT9us5wA", d)
        assert found.name == "0HeqT9us5wA_report.json"

    def test_known_prefix_stripped(self, tmp_path):
        d = self._dir(tmp_path, "7Amgqc5HJR0_report.json")
        assert find_ocr_report("usaf_7Amgqc5HJR0", d).name == "7Amgqc5HJR0_report.json"
        assert find_ocr_report("usa_fencing_sample_7Amgqc5HJR0", d).name == "7Amgqc5HJR0_report.json"

    def test_continuous_reports_never_matched(self, tmp_path):
        d = self._dir(tmp_path, "hKUXgUsDOKE_continuous_report.json")
        assert find_ocr_report("jr_foil_final_li_lin_hKUXgUsDOKE", d) is None

    def test_no_candidates_returns_none(self, tmp_path):
        assert find_ocr_report("anything_hKUXgUsDOKE", tmp_path) is None

    def test_unrelated_report_not_matched(self, tmp_path):
        d = self._dir(tmp_path, "3XTpDrDSvUs_report.json")
        assert find_ocr_report("jr_foil_final_li_lin_hKUXgUsDOKE", d) is None

    def test_exact_match_wins_over_substring(self, tmp_path):
        """Directory order must not decide: the exact base wins even though the
        looser candidate sorts first."""
        d = self._dir(
            tmp_path,
            "0000_hKUXgUsDOKE_extra_report.json",   # sorts first, substring-ish
            "hKUXgUsDOKE_report.json",              # exact YouTube ID
        )
        assert find_ocr_report("hKUXgUsDOKE", d).name == "hKUXgUsDOKE_report.json"

    def test_descriptive_report_name_matching_full_stem(self, tmp_path):
        d = self._dir(tmp_path, "jr_foil_final_li_lin_hKUXgUsDOKE_report.json")
        found = find_ocr_report("jr_foil_final_li_lin_hKUXgUsDOKE", d)
        assert found.name == "jr_foil_final_li_lin_hKUXgUsDOKE_report.json"

    def test_short_base_not_substring_matched(self, tmp_path):
        """A too-short base must not match by substring alone."""
        d = self._dir(tmp_path, "li_report.json")
        assert find_ocr_report("jr_foil_final_li_lin_hKUXgUsDOKE", d) is None

    def test_partial_token_not_matched(self, tmp_path):
        """A base that only partially overlaps the trailing token is no match:
        it is neither an 11-char YouTube ID nor aligned on an underscore."""
        d = self._dir(tmp_path, "short_report.json")
        assert find_ocr_report("some_video_shortx", d) is None

    def test_boundary_aligned_trailing_base_matches(self, tmp_path):
        """A base that does align on the trailing underscore matches, even when
        it is not an 11-char YouTube ID."""
        d = self._dir(tmp_path, "short_report.json")
        assert find_ocr_report("some_video_short", d).name == "short_report.json"
