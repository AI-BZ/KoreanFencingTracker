"""Tests for the admin CLI that folds an end-of-bout inference into a saved report.

The edit is applied to reports that must not be regenerated, so the pure
functions are tested against synthetic report dicts and a stand-in analysis —
no video is decoded and nothing under ``data/`` is opened or written.

The load-bearing property throughout is that the edit is *narrow*: the point and
its warning change, and every other field the report carries survives byte for
byte. ``summary.official_final_score`` above all — that is what a human recorded
off the referee's sheet, and an inference must never overwrite an observation.
"""

import pytest

from analyzer.scoreboard_tracker import (
    END_OF_BOUT_TARGET,
    VERDICT_ANNULLED,
    VERDICT_TOUCH,
    VERDICT_UNDETERMINED,
    LampEvent,
    TouchResolution,
    infer_end_of_bout_touch,
)
from app.led_report_converter import (
    TOUCH_SOURCE_END_OF_BOUT,
    WARNING_END_OF_BOUT_INFERRED,
    WARNING_LAMP_ANNULLED,
    WARNING_LAMP_UNDETERMINED,
)
from scripts.apply_end_of_bout_touch import (
    apply_to_report,
    diff_lines,
    next_touch_number,
    swap_warnings,
)

FRAME_COUNT = 4992
TAIL_ONSET = 4903
#: ``_clock(4903, 30.0)`` — the time the superseded warning names.
TAIL_CLOCK = "2:43"


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


def _resolution(onset, verdict, before, after=None, scorer=None,
                left="red", right=None):
    return TouchResolution(
        LampEvent(onset_frame=onset, end_frame=onset + 30,
                  left_colour=left, right_colour=right),
        scorer, verdict, before, after or before, False,
    )


class FakeAnalysis:
    """``ScoreboardAnalysis`` stand-in — the attributes both callers read."""

    def __init__(self, resolutions, frame_count=FRAME_COUNT, fps=30.0,
                 score_reliable=False):
        self.resolutions = list(resolutions)
        self.coverage_gaps = []
        self.frame_count = frame_count
        self.fps = fps
        self.score_reliable = score_reliable

    @property
    def undetermined(self):
        return [r for r in self.resolutions if r.verdict == VERDICT_UNDETERMINED]

    @property
    def annulled(self):
        return [r for r in self.resolutions if r.verdict == VERDICT_ANNULLED]


def bout_analysis(last_verdict=VERDICT_UNDETERMINED, extra=()):
    """A 4-2 pool bout whose last lamp never made it onto the scoreboard."""
    return FakeAnalysis([
        _resolution(900, VERDICT_TOUCH, (3, 2), (4, 2), scorer="left"),
        *extra,
        _resolution(TAIL_ONSET, last_verdict, (4, 2)),
    ])


def inference_for(analysis, bout_type="pool"):
    return infer_end_of_bout_touch(
        analysis.resolutions,
        target_score=END_OF_BOUT_TARGET[bout_type],
        frame_count=analysis.frame_count,
        fps=analysis.fps,
        clock_running_at_cut=True,
    )


def saved_report(warnings=None):
    """A continuous report as it sits on disk before the edit."""
    return {
        "summary": {
            "final_score": "4-2",
            "official_final_score": "5-2",
            "official_final_score_source": "manual",
            "total_touches": 3,
            "weapon": "foil",
        },
        "touches": [
            {"touch_number": 1, "frame": 300, "scorer": "left"},
            {"touch_number": 2, "frame": 620, "scorer": "right"},
            {"touch_number": 3, "frame": 900, "scorer": "left"},
        ],
        "scoring_frames": [300, 620, 900],
        "warnings": list(warnings if warnings is not None else [undetermined_warning()]),
        "exchanges": [{"id": 1}],
        "meta": {"share_token": "abc123", "visibility": "unlisted"},
    }


def undetermined_warning(clock=TAIL_CLOCK):
    return {
        "type": WARNING_LAMP_UNDETERMINED,
        "message": (
            f"{clock} 램프 점등을 확인했으나 점수판 변화를 대조할 수 없어 "
            "득점 여부를 확정하지 못했습니다."
        ),
        "severity": "warning",
    }


def applied(report=None, analysis=None):
    analysis = analysis or bout_analysis()
    report = saved_report() if report is None else report
    return report, apply_to_report(
        report, analysis, inference_for(analysis), analysis.fps, "running",
    )


# ------------------------------------------------------------------
# next_touch_number
# ------------------------------------------------------------------


class TestNextTouchNumber:
    def test_it_continues_the_existing_sequence(self):
        assert next_touch_number([{"touch_number": 1}, {"touch_number": 2}]) == 3

    def test_an_empty_list_starts_at_one(self):
        assert next_touch_number([]) == 1

    def test_a_gapped_sequence_continues_from_the_highest_not_the_count(self):
        """A merged report's touch list is not guaranteed gapless, and reusing a
        number already in use would collide in every consumer that keys on it."""
        assert next_touch_number([{"touch_number": 1}, {"touch_number": 7}]) == 8

    def test_touches_without_a_usable_number_are_ignored(self):
        assert next_touch_number([{"touch_number": None}, {"frame": 10}]) == 1


# ------------------------------------------------------------------
# apply_to_report — what it changes
# ------------------------------------------------------------------


class TestAppliedEdit:
    def test_the_inferred_touch_is_appended_with_the_next_number(self):
        _, updated = applied()

        touch = updated["touches"][-1]
        assert len(updated["touches"]) == 4
        assert touch["touch_number"] == 4
        assert touch["frame"] == TAIL_ONSET
        assert touch["scorer"] == "left"
        assert touch["score_before"] == "4-2"
        assert touch["score_after"] == "5-2"

    def test_the_inferred_touch_is_marked_as_inferred(self):
        _, updated = applied()

        touch = updated["touches"][-1]
        assert touch["touch_source"] == TOUCH_SOURCE_END_OF_BOUT
        assert touch["inference_basis"] == {
            "onset_frame": TAIL_ONSET,
            "frames_remaining": FRAME_COUNT - TAIL_ONSET,
            "clock_at_cut": "running",
            "score_at_match_point": "4-2",
            "lamps_lit": ["left"],
        }

    def test_the_existing_touches_are_untouched(self):
        report, updated = applied()

        assert updated["touches"][:3] == report["touches"]

    def test_the_final_score_becomes_the_inferred_one(self):
        _, updated = applied()

        assert updated["summary"]["final_score"] == "5-2"

    def test_total_touches_matches_the_new_list_length(self):
        _, updated = applied()

        assert updated["summary"]["total_touches"] == len(updated["touches"])

    def test_the_official_score_a_human_recorded_is_left_alone(self):
        _, updated = applied()

        assert updated["summary"]["official_final_score"] == "5-2"
        assert updated["summary"]["official_final_score_source"] == "manual"

    def test_the_lamp_onset_joins_scoring_frames_in_order(self):
        _, updated = applied()

        assert updated["scoring_frames"] == [300, 620, 900, TAIL_ONSET]

    def test_applying_twice_does_not_duplicate_the_scoring_frame(self):
        report, once = applied()
        _, twice = applied(report=once)

        assert twice["scoring_frames"] == once["scoring_frames"]

    def test_every_other_top_level_field_survives_unchanged(self):
        report, updated = applied()

        for key in ("exchanges", "meta"):
            assert updated[key] == report[key]
        assert set(updated) == set(report)

    def test_the_input_report_is_not_mutated(self):
        """The CLI prints a diff of before against after, which is meaningless if
        the edit happened in place."""
        report, updated = applied()

        assert len(report["touches"]) == 3
        assert report["summary"]["final_score"] == "4-2"
        assert report["scoring_frames"] == [300, 620, 900]

    def test_a_de_bout_is_promoted_to_fifteen(self):
        analysis = FakeAnalysis([_resolution(TAIL_ONSET, VERDICT_UNDETERMINED, (14, 11))])
        report = saved_report()

        updated = apply_to_report(
            report, analysis, inference_for(analysis, "de"), analysis.fps, "running",
        )

        assert updated["summary"]["final_score"] == "15-11"


# ------------------------------------------------------------------
# The warning swap
# ------------------------------------------------------------------


class TestWarningSwap:
    def test_the_superseded_undetermined_warning_is_replaced_in_place(self):
        _, updated = applied()

        types = [w["type"] for w in updated["warnings"]]
        assert WARNING_LAMP_UNDETERMINED not in types
        assert types.count(WARNING_END_OF_BOUT_INFERRED) == 1

    def test_the_report_never_counts_the_touch_and_doubts_it_at_once(self):
        _, updated = applied()

        text = " ".join(w["message"] for w in updated["warnings"])
        assert TAIL_CLOCK not in text or "경기 종료 규칙" in text
        assert "득점 여부를 확정하지 못했습니다" not in text

    def test_a_superseded_annulment_line_is_replaced(self):
        analysis = bout_analysis(last_verdict=VERDICT_ANNULLED)
        report = saved_report(warnings=[{
            "type": WARNING_LAMP_ANNULLED,
            "message": f"유효 램프가 점등됐으나 점수가 변하지 않은 이벤트 1건 ({TAIL_CLOCK}). "
                       "심판 무효 처리로 보고 터치에서 제외했습니다.",
            "severity": "info",
        }])

        _, updated = applied(report=report, analysis=analysis)

        types = [w["type"] for w in updated["warnings"]]
        assert WARNING_LAMP_ANNULLED not in types
        assert WARNING_END_OF_BOUT_INFERRED in types

    def test_another_events_annulment_survives_the_swap(self):
        other = _resolution(1800, VERDICT_ANNULLED, (4, 2))
        analysis = bout_analysis(last_verdict=VERDICT_ANNULLED, extra=[other])
        report = saved_report(warnings=[{
            "type": WARNING_LAMP_ANNULLED,
            "message": f"유효 램프가 점등됐으나 점수가 변하지 않은 이벤트 2건 (1:00, {TAIL_CLOCK}). "
                       "심판 무효 처리로 보고 터치에서 제외했습니다.",
            "severity": "info",
        }])

        _, updated = applied(report=report, analysis=analysis)

        [annulled] = [w for w in updated["warnings"] if w["type"] == WARNING_LAMP_ANNULLED]
        assert "1:00" in annulled["message"]
        assert TAIL_CLOCK not in annulled["message"]

    def test_unrelated_warnings_are_preserved_in_order(self):
        first = {"type": "lamp_coverage_gap", "message": "gap", "severity": "warning"}
        last = {"type": "score_is_lower_bound", "message": "lower", "severity": "warning"}
        report = saved_report(warnings=[first, undetermined_warning(), last])

        _, updated = applied(report=report)

        assert updated["warnings"][0] == first
        assert updated["warnings"][-1] == last
        assert updated["warnings"][1]["type"] == WARNING_END_OF_BOUT_INFERRED

    def test_a_drifted_warning_text_is_still_recognised_and_removed(self):
        """Reports written by an older version do not match today's wording byte
        for byte. Leaving the stale line behind would contradict the new touch,
        so type plus the promoted event's clock time is enough to retire it."""
        stale = {
            "type": WARNING_LAMP_UNDETERMINED,
            "message": f"{TAIL_CLOCK} 램프 점등 — 예전 문구",
            "severity": "warning",
        }
        report = saved_report(warnings=[stale])

        _, updated = applied(report=report)

        assert stale not in updated["warnings"]
        assert [w["type"] for w in updated["warnings"]] == [WARNING_END_OF_BOUT_INFERRED]

    def test_a_report_with_no_lamp_warning_at_all_just_gains_the_new_one(self):
        report = saved_report(warnings=[])

        _, updated = applied(report=report)

        assert [w["type"] for w in updated["warnings"]] == [WARNING_END_OF_BOUT_INFERRED]

    def test_an_undetermined_warning_for_a_different_event_is_kept(self):
        other = _resolution(1800, VERDICT_UNDETERMINED, (4, 2))
        analysis = bout_analysis(extra=[other])
        report = saved_report(warnings=[undetermined_warning("1:00"), undetermined_warning()])

        _, updated = applied(report=report, analysis=analysis)

        kept = [w for w in updated["warnings"] if w["type"] == WARNING_LAMP_UNDETERMINED]
        assert len(kept) == 1
        assert "1:00" in kept[0]["message"]


class TestSwapWarningsDirectly:
    def test_nothing_removed_means_the_replacements_are_appended(self):
        new = {"type": WARNING_END_OF_BOUT_INFERRED, "message": "m", "severity": "info"}

        result = swap_warnings([{"type": "other", "message": "x"}], [], [new], TAIL_CLOCK)

        assert result == [{"type": "other", "message": "x"}, new]

    def test_a_warning_with_no_message_key_does_not_raise(self):
        result = swap_warnings([{"type": WARNING_LAMP_UNDETERMINED}], [], [], TAIL_CLOCK)

        assert result == [{"type": WARNING_LAMP_UNDETERMINED}]


# ------------------------------------------------------------------
# diff_lines
# ------------------------------------------------------------------


class TestDiffLines:
    def test_it_names_the_score_change_the_new_touch_and_the_swapped_warning(self):
        report, updated = applied()

        text = "\n".join(diff_lines(report, updated))
        assert "'4-2' -> '5-2'" in text
        assert TOUCH_SOURCE_END_OF_BOUT in text
        assert str(TAIL_ONSET) in text
        assert WARNING_END_OF_BOUT_INFERRED in text
        assert WARNING_LAMP_UNDETERMINED in text

    def test_it_marks_removals_and_additions_distinctly(self):
        report, updated = applied()

        lines = diff_lines(report, updated)
        assert any(line.startswith("  - ") for line in lines)
        assert any(line.startswith("  + ") for line in lines)


# ------------------------------------------------------------------
# Refusal
# ------------------------------------------------------------------


class TestTheRuleStillRefuses:
    @pytest.mark.parametrize("before,reason", [
        ((3, 2), "not_match_point"),
        ((4, 4), "not_match_point"),
    ])
    def test_a_score_that_is_not_a_single_match_point_is_refused(self, before, reason):
        analysis = FakeAnalysis([_resolution(TAIL_ONSET, VERDICT_UNDETERMINED, before)])

        assert inference_for(analysis).reason == reason

    def test_a_lamp_far_from_the_end_is_refused(self):
        analysis = FakeAnalysis([_resolution(900, VERDICT_UNDETERMINED, (4, 2))])

        assert inference_for(analysis).reason == "not_in_tail_window"
