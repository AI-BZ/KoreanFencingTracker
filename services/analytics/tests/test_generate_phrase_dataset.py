"""Unit tests for pure logic in scripts/generate_phrase_dataset.py.

Covers the side-effect-free transform helpers plus process_report()
(which reads a JSON file but is otherwise deterministic):
- _frame_to_time()
- _merge_short_separations()
- _determine_outcome()
- _build_action_sequence()
- _compute_confidence()
- process_report()
"""

import json

import pytest

from scripts.generate_phrase_dataset import (
    _frame_to_time,
    _merge_short_separations,
    _determine_outcome,
    _build_action_sequence,
    _compute_confidence,
    process_report,
)


class TestFrameToTime:
    def test_zero(self):
        assert _frame_to_time(0) == "0:00"

    def test_one_minute(self):
        assert _frame_to_time(1800) == "1:00"

    def test_zero_pads_seconds(self):
        assert _frame_to_time(90) == "0:03"

    def test_custom_fps(self):
        assert _frame_to_time(48, fps=24.0) == "0:02"


class TestMergeShortSeparations:
    def test_empty(self):
        assert _merge_short_separations([], 10) == []

    def test_single_exchange_returned_as_copy(self):
        ex = {"start_frame": 0, "end_frame": 10, "event_type": "failed_attack"}
        result = _merge_short_separations([ex], 10)
        assert len(result) == 1
        assert result[0]["start_frame"] == 0
        assert result[0]["end_frame"] == 10
        # Returned dict is a copy: mutating input must not affect result
        assert result[0] is not ex

    def test_close_exchanges_merge(self):
        ex1 = {"start_frame": 0, "end_frame": 10, "event_type": "failed_attack",
               "min_distance_bh": 1.5, "end_time": "0:00", "footwork_left": "advance"}
        ex2 = {"start_frame": 15, "end_frame": 25, "event_type": "successful_defense",
               "min_distance_bh": 1.2, "end_time": "0:00", "footwork_right": "retreat"}
        result = _merge_short_separations([ex1, ex2], merge_frames=10)
        # gap = 15 - 10 = 5 <= 10 -> merged into one phrase
        assert len(result) == 1
        merged = result[0]
        assert merged["end_frame"] == 25
        # Keeps the closer (smaller) approach distance
        assert merged["min_distance_bh"] == 1.2
        assert merged["_merged_events"] == ["failed_attack", "successful_defense"]
        # Only the merged-in exchange's non-unknown footwork is collected
        assert merged["_merged_footworks"] == ["retreat"]

    def test_far_exchanges_stay_separate(self):
        ex1 = {"start_frame": 0, "end_frame": 10}
        ex2 = {"start_frame": 30, "end_frame": 40}
        result = _merge_short_separations([ex1, ex2], merge_frames=10)
        # gap = 30 - 10 = 20 > 10 -> not merged
        assert len(result) == 2

    def test_gap_equal_to_threshold_merges(self):
        ex1 = {"start_frame": 0, "end_frame": 10}
        ex2 = {"start_frame": 20, "end_frame": 30}
        # gap = 20 - 10 = 10, and condition is gap <= merge_frames
        result = _merge_short_separations([ex1, ex2], merge_frames=10)
        assert len(result) == 1

    def test_inputs_not_mutated(self):
        ex1 = {"start_frame": 0, "end_frame": 10, "event_type": "failed_attack"}
        ex2 = {"start_frame": 12, "end_frame": 20, "event_type": "successful_defense"}
        _merge_short_separations([ex1, ex2], merge_frames=10)
        # Original dicts must remain untouched
        assert ex1 == {"start_frame": 0, "end_frame": 10, "event_type": "failed_attack"}
        assert ex2 == {"start_frame": 12, "end_frame": 20, "event_type": "successful_defense"}

    def test_unknown_footwork_not_collected(self):
        ex1 = {"start_frame": 0, "end_frame": 10}
        ex2 = {"start_frame": 12, "end_frame": 20, "footwork_left": "unknown"}
        result = _merge_short_separations([ex1, ex2], merge_frames=10)
        assert result[0]["_merged_footworks"] == []


class TestDetermineOutcome:
    def test_no_scoring_frames_is_halt(self):
        phrase = {"start_frame": 100, "end_frame": 200}
        assert _determine_outcome(phrase, set()) == "halt"

    def test_scoring_frame_far_away_is_halt(self):
        phrase = {"start_frame": 100, "end_frame": 200}
        # 1000 is well outside [100-90, 200+90]
        assert _determine_outcome(phrase, {1000}) == "halt"

    def test_scorer_left(self):
        phrase = {"start_frame": 100, "end_frame": 200, "_scorer": "left"}
        assert _determine_outcome(phrase, {150}) == "touch_left"

    def test_scorer_right(self):
        phrase = {"start_frame": 100, "end_frame": 200, "_scorer": "right"}
        assert _determine_outcome(phrase, {150}) == "touch_right"

    def test_scorer_unknown_defaults_to_touch_left(self):
        phrase = {"start_frame": 100, "end_frame": 200}
        assert _determine_outcome(phrase, {150}) == "touch_left"

    def test_within_tolerance_boundary(self):
        phrase = {"start_frame": 100, "end_frame": 200}
        # end + tolerance = 200 + 90 = 290 is inclusive
        assert _determine_outcome(phrase, {290}) == "touch_left"

    def test_just_outside_tolerance(self):
        phrase = {"start_frame": 100, "end_frame": 200}
        assert _determine_outcome(phrase, {291}) == "halt"


class TestBuildActionSequence:
    def test_empty_phrase_is_unknown(self):
        assert _build_action_sequence({}) == ["unknown"]

    def test_footwork_only(self):
        assert _build_action_sequence({"footwork_left": "lunge"}) == ["lunge"]

    def test_failed_attack_maps_to_attack(self):
        assert _build_action_sequence({"event_type": "failed_attack"}) == ["attack"]

    def test_successful_defense_maps_to_defense(self):
        assert _build_action_sequence({"event_type": "successful_defense"}) == ["defense"]

    def test_parry_appends_parade(self):
        seq = _build_action_sequence({"parry_left": True})
        assert seq == ["parade"]

    def test_combined_sequence_order(self):
        phrase = {
            "footwork_left": "advance",
            "event_type": "failed_attack",
            "parry_right": True,
        }
        assert _build_action_sequence(phrase) == ["advance", "attack", "parade"]

    def test_unknown_footwork_excluded(self):
        assert _build_action_sequence({"footwork_left": "unknown"}) == ["unknown"]

    def test_merged_footworks_lead(self):
        phrase = {"_merged_footworks": ["advance", "lunge"], "footwork_left": "retreat"}
        assert _build_action_sequence(phrase) == ["advance", "lunge", "retreat"]


class TestComputeConfidence:
    def test_baseline_only(self):
        phrase = {"start_frame": 0, "end_frame": 100}
        assert _compute_confidence(phrase, has_ocr=False, has_clock=False) == pytest.approx(0.3)

    def test_ocr_adds(self):
        phrase = {"start_frame": 0, "end_frame": 100}
        assert _compute_confidence(phrase, has_ocr=True, has_clock=False) == pytest.approx(0.6)

    def test_ocr_and_clock(self):
        phrase = {"start_frame": 0, "end_frame": 100}
        assert _compute_confidence(phrase, has_ocr=True, has_clock=True) == pytest.approx(0.8)

    def test_footwork_adds(self):
        phrase = {"start_frame": 0, "end_frame": 100, "footwork_left": "advance"}
        assert _compute_confidence(phrase, has_ocr=True, has_clock=True) == pytest.approx(0.9)

    def test_short_phrase_penalty(self):
        phrase = {"start_frame": 0, "end_frame": 5}
        # duration 5 < 10 -> -0.1 from baseline 0.3
        assert _compute_confidence(phrase, has_ocr=False, has_clock=False) == pytest.approx(0.2)


class TestProcessReport:
    def _write_report(self, tmp_path, name, report):
        p = tmp_path / name
        p.write_text(json.dumps(report), encoding="utf-8")
        return p

    def test_no_exchanges_returns_empty(self, tmp_path):
        p = self._write_report(tmp_path, "vid_continuous_report.json", {"exchanges": []})
        assert process_report(p) == []

    def test_video_id_stripped_from_filename(self, tmp_path):
        report = {
            "exchanges": [{"start_frame": 0, "end_frame": 10, "event_type": "failed_attack"}],
        }
        p = self._write_report(tmp_path, "myvideo_continuous_report.json", report)
        annotations = process_report(p)
        assert len(annotations) == 1
        assert annotations[0].video_id == "myvideo"

    def test_scoring_and_halt_outcomes(self, tmp_path):
        report = {
            "exchanges": [
                {"start_frame": 0, "end_frame": 10, "event_type": "failed_attack",
                 "min_distance_bh": 1.5, "start_time": "0:00", "end_time": "0:00",
                 "footwork_left": "advance"},
                {"start_frame": 200, "end_frame": 250, "event_type": "successful_defense",
                 "min_distance_bh": 1.2, "start_time": "0:06", "end_time": "0:08",
                 "footwork_right": "retreat"},
            ],
            "touches": [{"frame": 5, "scorer": "left"}],
            "meta": {"ocr_source": "foo.json"},
        }
        p = self._write_report(tmp_path, "vid_continuous_report.json", report)
        annotations = process_report(p)
        # gap (190) exceeds merge threshold (30) -> two phrases
        assert len(annotations) == 2

        first, second = annotations
        # First phrase is near the touch frame -> scoring outcome
        assert first.outcome == "touch_left"
        assert first.trigger == "scoring"
        assert first.action_sequence == ["advance", "attack"]
        # OCR + clock + footwork -> 0.9 confidence
        assert first.confidence == pytest.approx(0.9)
        assert first.phrase_id == 1

        # Second phrase is far from any touch -> halt, distance-triggered
        assert second.outcome == "halt"
        assert second.trigger == "distance"
        assert second.action_sequence == ["retreat", "defense"]
        assert second.phrase_id == 2
