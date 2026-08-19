"""Unit tests for the pure helpers of scripts/eval_priority_exam.py.

No video is decoded and no model is loaded — ``PoseEstimator`` and
``PoseAnalyzer`` are imported inside ``main()`` precisely so these can run.

The one piece here that could invalidate a whole evaluation run without ever
raising is ``keep_two_largest``: if it assigned sides the wrong way round, every
call the judge made would be inverted and the result table would still look
perfectly plausible. Most of these tests exist for that.
"""

import pytest

from analyzer.models import FencerPose, PoseKeypoint, PoseResult
from scripts.eval_priority_exam import (
    format_table,
    keep_two_largest,
    pose_quality,
    select_exchange,
    summarise,
)


def fencer(x1, y1, x2, y2, conf=0.9, side=None) -> FencerPose:
    return FencerPose(
        keypoints=[PoseKeypoint(x=0.0, y=0.0, confidence=0.9) for _ in range(17)],
        bbox=[float(x1), float(y1), float(x2), float(y2)],
        person_confidence=conf,
        side=side,
    )


def result(*fencers) -> PoseResult:
    return PoseResult(frame_idx=0, fencers=list(fencers))


# ------------------------------------------------------------------
# keep_two_largest
# ------------------------------------------------------------------


class TestKeepTwoLargest:
    def test_keeps_the_two_largest_bodies(self):
        big_left = fencer(100, 300, 200, 600)     # 100x300
        big_right = fencer(700, 300, 800, 600)    # 100x300
        referee = fencer(400, 350, 440, 480)      # 40x130, smaller
        out = keep_two_largest(result(referee, big_left, big_right))
        assert len(out.fencers) == 2
        assert referee not in out.fencers

    def test_size_beats_confidence(self):
        """A confident referee must not displace a less confident fencer.

        This is the whole reason ``--select largest`` exists: the referee stands
        still and unoccluded, so YOLO is often *more* sure about him.
        """
        confident_referee = fencer(400, 350, 440, 480, conf=0.95)
        unsure_fencer = fencer(100, 300, 200, 600, conf=0.40)
        other_fencer = fencer(700, 300, 800, 600, conf=0.85)
        out = keep_two_largest(
            result(confident_referee, unsure_fencer, other_fencer)
        )
        assert confident_referee not in out.fencers
        assert {f.side for f in out.fencers} == {"left", "right"}

    def test_sides_follow_bbox_x_centre(self):
        a = fencer(700, 300, 800, 600)
        b = fencer(100, 300, 200, 600)
        out = keep_two_largest(result(a, b))
        by_side = {f.side: f for f in out.fencers}
        assert by_side["left"].bbox[0] == 100
        assert by_side["right"].bbox[0] == 700

    def test_sides_are_reassigned_not_inherited(self):
        """Stale sides from the estimator must not survive the reselection."""
        a = fencer(700, 300, 800, 600, side="left")
        b = fencer(100, 300, 200, 600, side="right")
        out = keep_two_largest(result(a, b))
        by_side = {f.side: f for f in out.fencers}
        assert by_side["left"].bbox[0] == 100
        assert by_side["right"].bbox[0] == 700

    def test_single_detection_is_passed_through(self):
        out = keep_two_largest(result(fencer(100, 300, 200, 600)))
        assert len(out.fencers) == 1

    def test_no_detections_is_not_an_error(self):
        out = keep_two_largest(result())
        assert out.fencers == []

    def test_frame_index_is_preserved(self):
        pr = PoseResult(frame_idx=42, fencers=[fencer(1, 1, 2, 2)])
        assert keep_two_largest(pr).frame_idx == 42


# ------------------------------------------------------------------
# pose_quality
# ------------------------------------------------------------------


class TestPoseQuality:
    def test_counts_only_frames_holding_both_sides(self):
        both = keep_two_largest(
            result(fencer(100, 300, 200, 600), fencer(700, 300, 800, 600))
        )
        one = keep_two_largest(result(fencer(100, 300, 200, 600)))
        q = pose_quality([both, one], frame_height=720.0)
        assert q["sampled_frames"] == 2
        assert q["two_fencer_frames"] == 1
        assert q["two_fencer_rate"] == 0.5

    def test_body_height_ratio_is_a_fraction_of_the_frame(self):
        pr = keep_two_largest(
            result(fencer(100, 300, 200, 660), fencer(700, 300, 800, 660))
        )
        q = pose_quality([pr], frame_height=720.0)
        assert q["mean_body_height_ratio"] == pytest.approx(0.5, abs=0.01)

    def test_empty_sequence_reports_zeroes_rather_than_dividing_by_zero(self):
        q = pose_quality([], frame_height=720.0)
        assert q["two_fencer_rate"] == 0.0
        assert q["mean_body_height_ratio"] == 0.0


# ------------------------------------------------------------------
# select_exchange
# ------------------------------------------------------------------


class TestSelectExchange:
    EXCHANGES = [
        {"start_frame": 0, "min_distance_bh": 0.4},
        {"start_frame": 30, "min_distance_bh": 1.9},
    ]

    def test_last_takes_the_final_exchange(self):
        assert select_exchange(self.EXCHANGES, "last")["start_frame"] == 30

    def test_closest_takes_the_nearest_approach(self):
        assert select_exchange(self.EXCHANGES, "closest")["start_frame"] == 0

    def test_missing_distance_never_wins_closest(self):
        exchanges = [{"start_frame": 0, "min_distance_bh": None},
                     {"start_frame": 30, "min_distance_bh": 1.9}]
        assert select_exchange(exchanges, "closest")["start_frame"] == 30

    def test_no_exchanges_returns_none(self):
        assert select_exchange([], "last") is None
        assert select_exchange([], "closest") is None


# ------------------------------------------------------------------
# summarise
# ------------------------------------------------------------------


def row(question, answer, verdict, reason="estimated"):
    return {
        "question": question,
        "answer": answer,
        "verdict": verdict,
        "reason": reason if verdict else reason,
        "correct": bool(verdict) and verdict == answer,
        "exchanges_detected": 1,
        "target_exchange": None,
        "detail": None,
    }


class TestSummarise:
    def test_accuracy_is_reported_both_ways(self):
        rows = [
            row(1, "left", "left"),
            row(2, "right", "left"),
            row(3, "left", None, "simultaneous"),
            row(4, "right", "right"),
        ]
        s = summarise(rows)
        assert s["calls_made"] == 3
        assert s["correct"] == 2
        assert s["unknown"] == 1
        assert s["accuracy_over_calls"] == pytest.approx(2 / 3, abs=1e-3)
        assert s["accuracy_over_all"] == 0.5

    def test_declines_are_broken_down_by_reason(self):
        rows = [
            row(1, "left", None, "simultaneous"),
            row(2, "left", None, "simultaneous"),
            row(3, "left", None, "no_exchange_detected"),
        ]
        assert summarise(rows)["decline_reasons"] == {
            "simultaneous": 2, "no_exchange_detected": 1,
        }

    def test_majority_baseline_is_the_bar_the_judge_has_to_clear(self):
        """Nine left and six right answers make 'always say left' worth 60%."""
        rows = [row(i, "left", None) for i in range(9)]
        rows += [row(9 + i, "right", None) for i in range(6)]
        s = summarise(rows)
        assert s["majority_class_baseline"] == 0.6
        assert s["answer_distribution"] == {"left": 9, "right": 6}

    def test_no_calls_leaves_call_accuracy_undefined_rather_than_zero(self):
        s = summarise([row(1, "left", None, "simultaneous")])
        assert s["accuracy_over_calls"] is None

    def test_empty_input(self):
        s = summarise([])
        assert s["questions"] == 0
        assert s["accuracy_over_all"] == 0.0


# ------------------------------------------------------------------
# format_table
# ------------------------------------------------------------------


class TestFormatTable:
    def test_renders_one_line_per_question_plus_a_header(self):
        rows = [row(1, "left", "left"), row(2, "right", None, "simultaneous")]
        lines = format_table(rows).splitlines()
        assert len(lines) == 4  # header, rule, two rows

    def test_marks_hit_miss_and_decline_distinctly(self):
        table = format_table([
            row(1, "left", "left"),
            row(2, "left", "right"),
            row(3, "left", None, "simultaneous"),
        ])
        hit, miss, decline = table.splitlines()[2:5]
        assert "✔" in hit
        assert "✘" in miss
        assert "·" in decline

    def test_footwork_dicts_are_reduced_to_their_type(self):
        r = row(1, "left", "left")
        r["target_exchange"] = {
            "footwork": {
                "left": {"footwork_type": "fleche", "confidence": 0.75},
                "right": {"footwork_type": "retreat", "confidence": 0.8},
            }
        }
        table = format_table([r])
        assert "fleche,retreat" in table
        assert "confidence" not in table
