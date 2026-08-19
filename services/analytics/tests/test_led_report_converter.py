"""Tests for the physical-LED scoreboard report converter and its CLI helpers.

Everything here runs on synthetic ``MatchEvent`` objects and in-memory config
dicts — no video, no model files, no ffmpeg — so the suite stays CI-safe.
"""

import json
from pathlib import Path

import pytest

from analyzer.models import MatchEvent
from analyzer.touch_matching import _LAMP_PATTERNS, _SINGLE_LAMP_SIDE
from app.led_report_converter import (
    DEFAULT_LEFT_NAME,
    DEFAULT_RIGHT_NAME,
    LAMP_DOUBLE,
    LAMP_SINGLE_LEFT,
    LAMP_SINGLE_RIGHT,
    LED_LAMP_CONFIDENCE,
    WARNING_CLOCK_UNREAD,
    WARNING_NO_TOUCHES,
    WARNING_SCORE_NOT_MONOTONIC,
    WARNING_SCORE_UNREADABLE,
    build_touches,
    build_warnings,
    count_by_scorer,
    derive_final_score,
    format_timestamp,
    lamp_pattern,
    led_events_to_match_report,
    parse_score,
    scoring_events,
)
from scripts.analyze_led_scoreboard import (
    ConfigError,
    REQUIRED_ROI_KEYS,
    extract_report_stem,
    extract_rois,
    extract_scoreboard_video,
    format_event_line,
    load_piste_config,
    resolve_work_file,
    summary_lines,
)


# ------------------------------------------------------------------
# Fixtures / factories
# ------------------------------------------------------------------


def make_event(
    frame=100,
    scorer="left",
    lamp_red=True,
    lamp_green=False,
    score_before="0-0",
    score_after="1-0",
    match_time="3:00",
    event_type="left_lamp",
    description="Left lamp (red) -> left scored",
):
    """Build a MatchEvent the way VideoProcessor._record_event would."""
    return MatchEvent(
        frame=frame,
        video_timestamp="0:00:03",
        match_time=match_time,
        event_type=event_type,
        lamp_red=lamp_red,
        lamp_green=lamp_green,
        score_before=score_before,
        score_after=score_after,
        scorer=scorer,
        description=description,
    )


def bout_events():
    """A clean 3-1 sequence: L, L, R, L."""
    return [
        make_event(frame=300, scorer="left", score_before="0-0", score_after="1-0",
                   match_time="2:55"),
        make_event(frame=900, scorer="left", score_before="1-0", score_after="2-0",
                   match_time="2:41"),
        make_event(frame=1500, scorer="right", lamp_red=False, lamp_green=True,
                   score_before="2-0", score_after="2-1", match_time="2:20"),
        make_event(frame=2100, scorer="left", score_before="2-1", score_after="3-1",
                   match_time="1:58"),
    ]


def piste_config():
    return {
        "schema_version": 1,
        "source": "manual",
        "piste_number": 3,
        "scoreboard": {
            "crop": {"x": 1680, "y": 840, "w": 720, "h": 520},
            "rois": {
                "lamp_left": [40, 60, 120, 90],
                "lamp_right": [560, 60, 120, 90],
                "score_left": [80, 200, 140, 160],
                "score_right": [500, 200, 140, 160],
                "clock": [260, 180, 200, 140],
            },
        },
        "work_files": {
            "piste": "data/work/bout_piste3.mp4",
            "scoreboard": "data/work/bout_piste3_scoreboard.mp4",
        },
    }


# ------------------------------------------------------------------
# lamp_pattern mapping — all four cases
# ------------------------------------------------------------------


class TestLampPattern:
    def test_both_lamps_is_double(self):
        assert lamp_pattern(True, True) == LAMP_DOUBLE

    def test_red_only_is_single_left(self):
        assert lamp_pattern(True, False) == LAMP_SINGLE_LEFT

    def test_green_only_is_single_right(self):
        assert lamp_pattern(False, True) == LAMP_SINGLE_RIGHT

    def test_no_lamp_is_none(self):
        """No lamp fired is not a pattern — inventing one fakes a reading."""
        assert lamp_pattern(False, False) is None

    def test_emitted_patterns_are_all_known_to_touch_matching(self):
        """Every pattern we emit must be one summarize_attack_outcomes tallies.

        An unknown string would land in the "unread" bucket, silently erasing
        the lamp evidence for that touch.
        """
        emitted = {lamp_pattern(r, g) for r in (True, False) for g in (True, False)}
        emitted.discard(None)
        assert emitted <= set(_LAMP_PATTERNS)

    def test_single_patterns_carry_the_side_touch_matching_expects(self):
        assert _SINGLE_LAMP_SIDE[LAMP_SINGLE_LEFT] == "left"
        assert _SINGLE_LAMP_SIDE[LAMP_SINGLE_RIGHT] == "right"


# ------------------------------------------------------------------
# Event filtering
# ------------------------------------------------------------------


class TestScoringEventFilter:
    def test_non_scoring_events_are_dropped(self):
        events = [
            make_event(frame=100, scorer="left"),
            make_event(frame=200, scorer=None, score_after="1-0"),   # invalid touch
            make_event(frame=300, scorer="none"),                    # no score change
            make_event(frame=400, scorer="right", lamp_red=False, lamp_green=True),
        ]
        kept = scoring_events(events)
        assert [e.frame for e in kept] == [100, 400]

    def test_both_is_kept_as_a_scoring_event(self):
        events = [make_event(scorer="both", lamp_red=True, lamp_green=True)]
        assert len(scoring_events(events)) == 1

    def test_report_drops_non_scoring_events(self):
        events = [
            make_event(frame=100, scorer="left"),
            make_event(frame=200, scorer=None),
        ]
        report = led_events_to_match_report(
            events, video_path="sb.mp4", weapon="foil",
        )
        assert report["summary"]["total_touches"] == 1
        assert [t["frame"] for t in report["touches"]] == [100]


# ------------------------------------------------------------------
# Touch construction
# ------------------------------------------------------------------


class TestTouches:
    def test_touch_number_is_sequential_after_drops(self):
        events = [
            make_event(frame=100, scorer="left"),
            make_event(frame=150, scorer=None),
            make_event(frame=200, scorer="right", lamp_red=False, lamp_green=True),
            make_event(frame=250, scorer="none"),
            make_event(frame=300, scorer="left"),
        ]
        touches = build_touches(scoring_events(events))
        assert [t["touch_number"] for t in touches] == [1, 2, 3]

    def test_frame_passes_through_with_no_fps_conversion(self):
        """The scoreboard and piste work files share a 30 fps frame index.

        Any scaling here (e.g. 120 fps source → 30 fps work file) would offset
        every touch by 4x and break touch→exchange matching.
        """
        event = make_event(frame=4321)
        for fps in (30.0, 25.0, 120.0, 59.94):
            touches = build_touches([event], fps=fps)
            assert touches[0]["frame"] == 4321

    def test_video_timestamp_is_recomputed_in_m_ss(self):
        """MatchEvent carries "0:00:03" (str(timedelta)); reports use "M:SS"."""
        touches = build_touches([make_event(frame=5010)], fps=30.0)
        assert touches[0]["video_timestamp"] == "2:47"

    def test_lamp_fields_are_written_for_a_single_lamp_touch(self):
        touches = build_touches([make_event(lamp_red=True, lamp_green=False)])
        t = touches[0]
        assert t["lamp_red"] is True
        assert t["lamp_green"] is False
        assert t["lamp_pattern"] == LAMP_SINGLE_LEFT
        assert t["lamp_confidence"] == LED_LAMP_CONFIDENCE
        assert t["lamp_scorer_conflict"] is False

    def test_lamp_confidence_is_zero_when_no_lamp_fired(self):
        touches = build_touches([make_event(lamp_red=False, lamp_green=False)])
        assert touches[0]["lamp_pattern"] is None
        assert touches[0]["lamp_confidence"] == 0.0

    def test_lamp_scorer_conflict_is_flagged(self):
        """Green lamp + left scorer is physically impossible — one read is wrong."""
        touches = build_touches([
            make_event(scorer="left", lamp_red=False, lamp_green=True),
        ])
        assert touches[0]["lamp_pattern"] == LAMP_SINGLE_RIGHT
        assert touches[0]["lamp_scorer_conflict"] is True

    def test_missing_match_time_becomes_empty_string(self):
        touches = build_touches([make_event(match_time="")])
        assert touches[0]["match_time"] == ""

    def test_match_time_passes_through_when_the_clock_was_read(self):
        touches = build_touches([make_event(match_time="2:47")])
        assert touches[0]["match_time"] == "2:47"


# ------------------------------------------------------------------
# Score derivation
# ------------------------------------------------------------------


class TestScore:
    @pytest.mark.parametrize("raw,expected", [
        ("5-3", (5, 3)),
        ("0-0", (0, 0)),
        ("15-11", (15, 11)),
        ("", None),
        ("5", None),
        ("?-3", None),
        ("5-3-1", None),
        (None, None),
    ])
    def test_parse_score(self, raw, expected):
        assert parse_score(raw) == expected

    def test_final_score_is_the_last_readable_score_after(self):
        assert derive_final_score(build_touches(bout_events())) == "3-1"

    def test_final_score_falls_back_to_zero_zero_when_empty(self):
        assert derive_final_score([]) == "0-0"

    def test_final_score_skips_unreadable_trailing_touches(self):
        events = bout_events() + [
            make_event(frame=2500, scorer="left", score_after=""),
        ]
        assert derive_final_score(build_touches(events)) == "3-1"

    def test_count_by_scorer_counts_both_for_each_side(self):
        touches = build_touches([
            make_event(frame=1, scorer="left"),
            make_event(frame=2, scorer="right", lamp_red=False, lamp_green=True),
            make_event(frame=3, scorer="both", lamp_red=True, lamp_green=True),
        ])
        assert count_by_scorer(touches, "left") == 2
        assert count_by_scorer(touches, "right") == 2


class TestFormatTimestamp:
    @pytest.mark.parametrize("frame,fps,expected", [
        (0, 30.0, "0:00"),
        (30, 30.0, "0:01"),
        (1230, 30.0, "0:41"),
        (5010, 30.0, "2:47"),
        (0, 0.0, "0:00"),
    ])
    def test_format(self, frame, fps, expected):
        assert format_timestamp(frame, fps) == expected


# ------------------------------------------------------------------
# Warnings
# ------------------------------------------------------------------


def warning_types(warnings):
    return {w["type"] for w in warnings}


class TestWarnings:
    def test_clean_bout_has_no_warnings(self):
        assert build_warnings(build_touches(bout_events())) == []

    def test_no_touches_is_an_error(self):
        warnings = build_warnings([])
        assert warning_types(warnings) == {WARNING_NO_TOUCHES}
        assert warnings[0]["severity"] == "error"

    def test_identical_match_time_across_all_touches_warns(self):
        """One clock value for a whole bout means the clock ROI failed."""
        events = [
            make_event(frame=300, scorer="left", score_after="1-0", match_time="3:00"),
            make_event(frame=900, scorer="left", score_before="1-0",
                       score_after="2-0", match_time="3:00"),
            make_event(frame=1500, scorer="left", score_before="2-0",
                       score_after="3-0", match_time="3:00"),
        ]
        warnings = build_warnings(build_touches(events))
        assert WARNING_CLOCK_UNREAD in warning_types(warnings)

    def test_all_empty_match_times_warns_too(self):
        events = [
            make_event(frame=300, scorer="left", score_after="1-0", match_time=""),
            make_event(frame=900, scorer="left", score_before="1-0",
                       score_after="2-0", match_time=""),
        ]
        warnings = build_warnings(build_touches(events))
        assert WARNING_CLOCK_UNREAD in warning_types(warnings)

    def test_varying_match_times_do_not_warn(self):
        warnings = build_warnings(build_touches(bout_events()))
        assert WARNING_CLOCK_UNREAD not in warning_types(warnings)

    def test_single_touch_does_not_trigger_the_clock_warning(self):
        """One touch trivially has one clock value; that proves nothing."""
        warnings = build_warnings(build_touches([make_event()]))
        assert WARNING_CLOCK_UNREAD not in warning_types(warnings)

    def test_non_monotonic_score_warns(self):
        events = [
            make_event(frame=300, scorer="left", score_after="1-0", match_time="2:55"),
            make_event(frame=900, scorer="left", score_before="1-0",
                       score_after="2-0", match_time="2:41"),
            # Left drops back to 1 — a misread digit.
            make_event(frame=1500, scorer="right", lamp_red=False, lamp_green=True,
                       score_before="2-0", score_after="1-1", match_time="2:20"),
        ]
        warnings = build_warnings(build_touches(events))
        assert WARNING_SCORE_NOT_MONOTONIC in warning_types(warnings)
        assert "3" in [w for w in warnings
                       if w["type"] == WARNING_SCORE_NOT_MONOTONIC][0]["message"]

    def test_monotonic_score_does_not_warn(self):
        warnings = build_warnings(build_touches(bout_events()))
        assert WARNING_SCORE_NOT_MONOTONIC not in warning_types(warnings)

    def test_unreadable_score_after_warns(self):
        events = [
            make_event(frame=300, scorer="left", score_after="1-0", match_time="2:55"),
            make_event(frame=900, scorer="left", score_after="", match_time="2:41"),
        ]
        warnings = build_warnings(build_touches(events))
        assert WARNING_SCORE_UNREADABLE in warning_types(warnings)

    def test_warning_dicts_have_the_shape_the_template_renders(self):
        for warning in build_warnings([]):
            assert set(warning) == {"type", "message", "severity"}
            assert warning["severity"] in ("info", "warning", "error")


# ------------------------------------------------------------------
# Full report
# ------------------------------------------------------------------


class TestLedEventsToMatchReport:
    def test_report_shape(self):
        report = led_events_to_match_report(
            bout_events(), video_path="data/work/bout_piste3_scoreboard.mp4",
            weapon="foil", bout_type="pool", fps=30.0, total_frames=4980,
            analysis_time_sec=12.34,
        )
        assert set(report) >= {
            "summary", "touches", "left_fencer", "right_fencer", "warnings",
        }
        summary = report["summary"]
        assert summary["final_score"] == "3-1"
        assert summary["weapon"] == "foil"
        assert summary["bout_type"] == "pool"
        assert summary["total_touches"] == 4
        assert summary["video_path"] == "data/work/bout_piste3_scoreboard.mp4"
        assert summary["total_frames_analyzed"] == 4980
        assert summary["analysis_time_sec"] == 12.3
        assert summary["match_duration"] == "2:46"

    def test_fencer_touch_counts(self):
        report = led_events_to_match_report(
            bout_events(), video_path="sb.mp4", weapon="foil",
        )
        assert report["left_fencer"]["total_touches_scored"] == 3
        assert report["left_fencer"]["total_touches_conceded"] == 1
        assert report["right_fencer"]["total_touches_scored"] == 1
        assert report["right_fencer"]["total_touches_conceded"] == 3

    def test_names_come_from_arguments(self):
        report = led_events_to_match_report(
            bout_events(), video_path="sb.mp4", weapon="foil",
            left_name="박소윤", right_name="정다희",
        )
        assert report["left_fencer"]["name"] == "박소윤"
        assert report["right_fencer"]["name"] == "정다희"

    def test_default_names_are_the_merge_sentinels(self):
        """generate_continuous_report only merges a name not in ("Left","Right").

        A physical scoreboard has no names, so the defaults must be exactly the
        sentinels — anything else would overwrite the continuous report's own
        fencer names with a placeholder.
        """
        report = led_events_to_match_report(
            bout_events(), video_path="sb.mp4", weapon="foil",
        )
        assert report["left_fencer"]["name"] == DEFAULT_LEFT_NAME == "Left"
        assert report["right_fencer"]["name"] == DEFAULT_RIGHT_NAME == "Right"

    def test_empty_event_list_produces_a_valid_empty_report(self):
        report = led_events_to_match_report(
            [], video_path="sb.mp4", weapon="epee",
        )
        assert report["touches"] == []
        assert report["summary"]["total_touches"] == 0
        assert report["summary"]["final_score"] == "0-0"
        assert report["summary"]["match_duration"] == "0:00"
        assert warning_types(report["warnings"]) == {WARNING_NO_TOUCHES}

    def test_report_is_json_serialisable(self):
        report = led_events_to_match_report(
            bout_events(), video_path="sb.mp4", weapon="sabre",
        )
        assert json.loads(json.dumps(report, ensure_ascii=False)) == report

    def test_clock_events_key_is_absent(self):
        """v1 does not produce allez/halt from a physical box; an empty list
        would make the merge print "Clock events: 0" as if it had tried."""
        report = led_events_to_match_report(
            bout_events(), video_path="sb.mp4", weapon="foil",
        )
        assert "clock_events" not in report

    def test_touches_carry_every_field_the_merge_reads(self):
        report = led_events_to_match_report(
            bout_events(), video_path="sb.mp4", weapon="foil",
        )
        for touch in report["touches"]:
            # generate_continuous_report.py: t["frame"], t["scorer"],
            # t["match_time"], t["video_timestamp"];
            # touch_matching.summarize_attack_outcomes: lamp_pattern,
            # lamp_scorer_conflict.
            assert set(touch) >= {
                "frame", "scorer", "match_time", "video_timestamp",
                "lamp_pattern", "lamp_scorer_conflict", "score_after",
                "touch_number",
            }


# ------------------------------------------------------------------
# CLI config helpers
# ------------------------------------------------------------------


class TestConfigParsing:
    def test_extract_rois_returns_int_tuples(self):
        rois = extract_rois(piste_config())
        assert set(rois) == set(REQUIRED_ROI_KEYS)
        assert rois["lamp_left"] == (40, 60, 120, 90)
        for value in rois.values():
            assert isinstance(value, tuple) and len(value) == 4
            assert all(isinstance(v, int) for v in value)

    def test_missing_roi_key_is_an_error(self):
        config = piste_config()
        del config["scoreboard"]["rois"]["clock"]
        with pytest.raises(ConfigError, match="clock"):
            extract_rois(config)

    def test_malformed_roi_is_an_error(self):
        config = piste_config()
        config["scoreboard"]["rois"]["clock"] = [1, 2, 3]
        with pytest.raises(ConfigError, match=r"\[x, y, w, h\]"):
            extract_rois(config)

    def test_zero_size_roi_is_an_error(self):
        config = piste_config()
        config["scoreboard"]["rois"]["clock"] = [10, 10, 0, 40]
        with pytest.raises(ConfigError, match="non-positive"):
            extract_rois(config)

    def test_missing_scoreboard_section_is_an_error(self):
        with pytest.raises(ConfigError, match="scoreboard"):
            extract_rois({"work_files": {}})

    def test_report_stem_is_the_piste_work_file_stem(self):
        """find_ocr_report's exact tier matches on the ANALYSED video's stem,
        which is the piste work file — not the scoreboard one."""
        assert extract_report_stem(piste_config()) == "bout_piste3"

    def test_missing_piste_entry_is_an_error(self):
        config = piste_config()
        del config["work_files"]["piste"]
        with pytest.raises(ConfigError, match="work_files.piste"):
            extract_report_stem(config)

    def test_missing_scoreboard_work_file_entry_is_an_error(self):
        config = piste_config()
        del config["work_files"]["scoreboard"]
        with pytest.raises(ConfigError, match="work_files.scoreboard"):
            extract_scoreboard_video(config)

    def test_scoreboard_path_resolves_against_the_service_root(self, tmp_path):
        video = extract_scoreboard_video(piste_config(), service_root=tmp_path)
        assert video == (tmp_path / "data/work/bout_piste3_scoreboard.mp4").resolve()

    def test_absolute_work_file_path_is_used_as_is(self, tmp_path):
        config = piste_config()
        config["work_files"]["scoreboard"] = "/abs/sb.mp4"
        assert extract_scoreboard_video(config, service_root=tmp_path) == \
            Path("/abs/sb.mp4")

    def test_resolve_work_file_prefers_an_existing_relative_path(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "here.mp4").write_text("x")
        assert resolve_work_file("here.mp4", service_root=tmp_path / "nope") == \
            (tmp_path / "here.mp4").resolve()

    def test_load_piste_config_reads_json(self, tmp_path):
        path = tmp_path / "cfg.json"
        path.write_text(json.dumps(piste_config()), encoding="utf-8")
        assert load_piste_config(path)["piste_number"] == 3

    def test_load_piste_config_missing_file(self, tmp_path):
        with pytest.raises(ConfigError, match="not found"):
            load_piste_config(tmp_path / "absent.json")

    def test_load_piste_config_invalid_json(self, tmp_path):
        path = tmp_path / "cfg.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ConfigError, match="not valid JSON"):
            load_piste_config(path)


class TestMergeCompatibility:
    """Feed the converter's output through the real downstream code.

    These are the tests that would catch a schema drift: they call the same
    functions ``scripts/generate_continuous_report.py`` calls, rather than
    re-asserting a hand-copied field list.
    """

    def test_find_ocr_report_matches_on_the_exact_tier(self, tmp_path):
        """The piste-stem filename must hit find_ocr_report's strictest tier.

        Tier 1 (exact) is the only one that cannot be stolen by an unrelated
        report sitting in the same data/reports directory.
        """
        from scripts.generate_continuous_report import find_ocr_report

        stem = extract_report_stem(piste_config())          # "bout_piste3"
        (tmp_path / f"{stem}_report.json").write_text("{}", encoding="utf-8")
        # A decoy that the looser substring tier could otherwise pick up.
        (tmp_path / "bout_piste3_scoreboard_report.json").write_text(
            "{}", encoding="utf-8",
        )
        # The continuous report the generator itself writes, which must be
        # excluded from the candidate set.
        (tmp_path / f"{stem}_continuous_report.json").write_text(
            "{}", encoding="utf-8",
        )

        found = find_ocr_report(stem, tmp_path)
        assert found is not None
        assert found.name == f"{stem}_report.json"

    def test_annotate_touch_outcomes_accepts_our_touches(self):
        """annotate_touch_outcomes reads t["frame"] and t["scorer"]."""
        from analyzer.touch_matching import annotate_touch_outcomes

        report = led_events_to_match_report(
            bout_events(), video_path="sb.mp4", weapon="foil",
        )
        exchanges = [{
            "exchange_number": 1,
            "start_frame": 240, "end_frame": 295, "min_distance_frame": 290,
            "footwork_left": "lunge", "footwork_right": "retreat",
        }]
        annotate_touch_outcomes(report["touches"], exchanges, fps=30.0)

        first = report["touches"][0]           # frame 300, matched to exchange 1
        assert first["matched_exchange_number"] == 1
        assert first["attacker_side"] == "left"
        assert first["attack_outcome"] == "attack_success"

    def test_summarize_attack_outcomes_tallies_our_lamp_patterns(self):
        """Our lamp_pattern strings must land in real buckets, not "unread"."""
        from analyzer.touch_matching import (
            annotate_touch_outcomes,
            summarize_attack_outcomes,
        )

        events = bout_events() + [
            make_event(frame=2700, scorer="left", lamp_red=True, lamp_green=True,
                       score_before="3-1", score_after="4-1", match_time="1:30"),
        ]
        report = led_events_to_match_report(
            events, video_path="sb.mp4", weapon="foil",
        )
        annotate_touch_outcomes(report["touches"], [], fps=30.0)
        stats = summarize_attack_outcomes(report["touches"])

        assert stats["lamp"]["single_left"] == 3
        assert stats["lamp"]["single_right"] == 1
        assert stats["lamp"]["double"] == 1
        assert stats["lamp"]["unread"] == 0
        assert stats["lamp"]["conflict"] == 0
        # The lamp buckets must partition the touches exactly.
        assert sum(
            stats["lamp"][k] for k in
            ("double", "single_left", "single_right", "white", "unread")
        ) == stats["total_touches"] == 5

    def test_lamp_scorer_conflict_reaches_the_summary(self):
        from analyzer.touch_matching import (
            annotate_touch_outcomes,
            summarize_attack_outcomes,
        )

        report = led_events_to_match_report(
            [make_event(scorer="left", lamp_red=False, lamp_green=True)],
            video_path="sb.mp4", weapon="foil",
        )
        annotate_touch_outcomes(report["touches"], [], fps=30.0)
        stats = summarize_attack_outcomes(report["touches"])
        assert stats["lamp"]["conflict"] == 1

    def test_merge_clock_fallback_triggers_on_our_warning_condition(self):
        """The same condition our warning fires on is what the merge fixes up.

        generate_continuous_report.py replaces match_time with video_timestamp
        when ``len(set(match_times)) <= 1``. Our warning must fire on exactly
        that set, so the user is told why the column changed meaning.
        """
        events = [
            make_event(frame=300, scorer="left", score_after="1-0", match_time="3:00"),
            make_event(frame=900, scorer="left", score_before="1-0",
                       score_after="2-0", match_time="3:00"),
        ]
        report = led_events_to_match_report(
            events, video_path="sb.mp4", weapon="foil",
        )
        match_times = [t.get("match_time") for t in report["touches"]]
        assert len(set(match_times)) <= 1
        assert WARNING_CLOCK_UNREAD in warning_types(report["warnings"])


class TestCliPresentation:
    def test_format_event_line_shows_the_key_fields(self):
        line = format_event_line(make_event(frame=1234, scorer="left"))
        assert "1234" in line
        assert "RED" in line
        assert "0-0" in line and "1-0" in line
        assert "scorer=left" in line

    def test_format_event_line_handles_a_non_scoring_event(self):
        line = format_event_line(
            make_event(scorer=None, lamp_red=False, lamp_green=False, match_time=""),
        )
        assert "scorer=None" in line
        assert "lamp -" in line

    def test_summary_lines_report_counts_and_warnings(self):
        report = led_events_to_match_report(
            bout_events(), video_path="sb.mp4", weapon="foil",
        )
        text = "\n".join(summary_lines(report))
        assert "Total touches: 4" in text
        assert "3-1" in text
        assert "left 3, right 1" in text
        assert "none" in text

    def test_summary_lines_list_each_warning(self):
        report = led_events_to_match_report([], video_path="sb.mp4", weapon="foil")
        text = "\n".join(summary_lines(report))
        assert WARNING_NO_TOUCHES in text
        assert "[error]" in text
