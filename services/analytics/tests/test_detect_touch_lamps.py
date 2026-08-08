"""Unit tests for scripts/detect_touch_lamps.py.

No video is decoded and no network is touched: the scan is faked either by
injecting prebuilt ``LampEvent`` / ``LampReading`` objects or by monkeypatching
``LampBarReader.scan_video_events``.
"""

import json
import time

import pytest

from analyzer.config import LAMP_SEARCH_FORWARD, LAMP_SEARCH_LOOKBACK
from analyzer.tv_overlay_ocr import (
    LampBarReader,
    LampEvent,
    LampReading,
    LampSideReading,
)
from scripts.detect_touch_lamps import (
    LABEL_CSV_HEADER,
    NOTE_AUTO_PREFIX,
    NOTE_REVIEW_PREFIX,
    JsonStyle,
    build_label_row,
    build_label_rows,
    detect_json_style,
    dumps_json,
    format_touch_table,
    lamp_scorer_consistency,
    main,
    merge_windows,
    pattern_counts,
    read_touch_readings,
    row_needs_review,
    scan_windows,
    touch_window,
    write_label_csv,
)


# ------------------------------------------------------------------
# Builders
# ------------------------------------------------------------------


def make_event(start, end, left="off", right="off", fill=0.9, on_frames=30):
    """A LampEvent with the given per-side states."""

    def side(state):
        if state == "off":
            return LampSideReading(state="off", peak_fill=0.0, on_frames=0)
        return LampSideReading(state=state, peak_fill=fill, on_frames=on_frames)

    return LampEvent(
        start_frame=start,
        end_frame=end,
        left=side(left),
        right=side(right),
        frames_sampled=max(1, (end - start) // 3),
    )


def make_touch(number, frame, scorer, exchange=None, outcome="unclear"):
    return {
        "touch_number": number,
        "frame": frame,
        "scorer": scorer,
        "attack_outcome": outcome,
        "attacker_side": None,
        "matched_exchange_number": exchange,
    }


class RecordingReader:
    """Stands in for LampBarReader, recording how it was called."""

    def __init__(self, readings=None, events=None):
        self._readings = list(readings or [])
        self._events = list(events or [])
        self.touch_calls = []
        self.scan_calls = []

    def read_touch_lamp(self, events, touch_frame, previous_end=None):
        self.touch_calls.append((touch_frame, previous_end))
        if self._readings:
            return self._readings.pop(0)
        return LampBarReader.read_touch_lamp(
            LampBarReader(), events, touch_frame, previous_end=previous_end,
        )

    def scan_video_events(self, video_path, start_frame, end_frame, step):
        self.scan_calls.append((str(video_path), start_frame, end_frame, step))
        return [
            e for e in self._events if start_frame <= e.start_frame <= end_frame
        ]


# ------------------------------------------------------------------
# Window construction and merging
# ------------------------------------------------------------------


class TestTouchWindow:
    def test_window_matches_the_matcher_search_bounds(self):
        assert touch_window(1000) == (
            1000 - LAMP_SEARCH_LOOKBACK,
            1000 + LAMP_SEARCH_FORWARD,
        )

    def test_window_is_clamped_at_frame_zero(self):
        start, end = touch_window(10)
        assert start == 0
        assert end == 10 + LAMP_SEARCH_FORWARD

    def test_explicit_bounds_override_defaults(self):
        assert touch_window(500, lookback=100, forward=20) == (400, 520)


class TestMergeWindows:
    def test_disjoint_windows_are_kept_separate(self):
        assert merge_windows([(0, 100), (200, 300)]) == [(0, 100), (200, 300)]

    def test_overlapping_windows_merge(self):
        assert merge_windows([(0, 100), (50, 300)]) == [(0, 300)]

    def test_touching_windows_merge(self):
        assert merge_windows([(0, 100), (100, 200)]) == [(0, 200)]

    def test_adjacent_but_not_overlapping_stays_split(self):
        assert merge_windows([(0, 100), (101, 200)]) == [(0, 100), (101, 200)]

    def test_contained_window_is_absorbed(self):
        assert merge_windows([(0, 500), (100, 200)]) == [(0, 500)]

    def test_unordered_input_is_sorted_before_merging(self):
        assert merge_windows([(200, 300), (0, 100), (250, 400)]) == [
            (0, 100),
            (200, 400),
        ]

    def test_three_consecutive_touches_collapse_to_one_window(self):
        # Touches 60 frames apart are far closer than the 330-frame lookback,
        # so all three windows must collapse into a single sequential pass.
        windows = [touch_window(f) for f in (1000, 1060, 1120)]
        assert merge_windows(windows) == [
            (1000 - LAMP_SEARCH_LOOKBACK, 1120 + LAMP_SEARCH_FORWARD),
        ]

    def test_far_apart_touches_keep_their_own_windows(self):
        windows = [touch_window(f) for f in (1000, 9000)]
        assert merge_windows(windows) == [
            (1000 - LAMP_SEARCH_LOOKBACK, 1000 + LAMP_SEARCH_FORWARD),
            (9000 - LAMP_SEARCH_LOOKBACK, 9000 + LAMP_SEARCH_FORWARD),
        ]

    def test_empty_input(self):
        assert merge_windows([]) == []


class TestScanWindows:
    def test_one_scan_call_per_merged_window(self):
        reader = RecordingReader(events=[make_event(120, 150, left="color")])
        scan_windows(reader, "clip.mp4", [(0, 200), (500, 700)], step=3)
        assert reader.scan_calls == [
            ("clip.mp4", 0, 200, 3),
            ("clip.mp4", 500, 700, 3),
        ]

    def test_events_from_all_windows_are_returned_in_frame_order(self):
        reader = RecordingReader(
            events=[
                make_event(600, 630, right="color"),
                make_event(120, 150, left="color"),
            ],
        )
        events = scan_windows(reader, "clip.mp4", [(0, 200), (500, 700)], step=3)
        assert [e.start_frame for e in events] == [120, 600]


# ------------------------------------------------------------------
# previous_end chaining
# ------------------------------------------------------------------


class TestReadTouchReadings:
    def test_previous_end_is_chained_in_touch_order(self):
        events = [
            make_event(100, 130, left="color"),
            make_event(400, 430, right="color"),
            make_event(700, 730, left="color", right="color"),
        ]
        reader = LampBarReader()
        readings = read_touch_readings(reader, events, [200, 500, 800])

        assert [r.start_frame for r in readings] == [100, 400, 700]
        assert [r.pattern for r in readings] == [
            "single_left",
            "single_right",
            "double",
        ]

    def test_chain_starts_with_no_previous_end(self):
        reader = RecordingReader(readings=[LampBarReader().read_touch_lamp([], 100)])
        read_touch_readings(reader, [], [100])
        assert reader.touch_calls == [(100, None)]

    def test_each_call_receives_the_previous_matched_end(self):
        first = make_event(100, 130, left="color")
        second = make_event(400, 430, right="color")
        reader = RecordingReader(
            readings=[
                LampBarReader().read_touch_lamp([first], 200),
                LampBarReader().read_touch_lamp([second], 500),
            ],
        )
        read_touch_readings(reader, [first, second], [200, 500])
        assert reader.touch_calls == [(200, None), (500, 130)]

    def test_unread_touch_does_not_reset_the_chain(self):
        # The middle touch reads nothing; the boundary must stay at the last
        # event that actually matched, not fall back to None.
        matched = make_event(100, 130, left="color")
        reader = RecordingReader(
            readings=[
                LampBarReader().read_touch_lamp([matched], 200),
                LampBarReader().read_touch_lamp([], 5000),
                LampBarReader().read_touch_lamp([], 9000),
            ],
        )
        read_touch_readings(reader, [matched], [200, 5000, 9000])
        assert reader.touch_calls == [(200, None), (5000, 130), (9000, 130)]

    def test_a_touch_cannot_reuse_the_previous_touch_lamp(self):
        # Only one lamp event exists but two touches sit within its window; the
        # second must come back unread rather than borrowing the first's event.
        events = [make_event(100, 130, left="color")]
        readings = read_touch_readings(LampBarReader(), events, [200, 260])
        assert readings[0].pattern == "single_left"
        assert readings[1].pattern is None

    def test_readings_are_parallel_to_touch_frames(self):
        readings = read_touch_readings(LampBarReader(), [], [1, 2, 3, 4])
        assert len(readings) == 4


# ------------------------------------------------------------------
# JSON style round-trip
# ------------------------------------------------------------------


class TestDetectJsonStyle:
    def test_indent_two_is_detected(self):
        text = json.dumps({"a": {"b": 1}}, indent=2, ensure_ascii=False)
        assert detect_json_style(text).indent == 2

    def test_indent_four_is_detected(self):
        text = json.dumps({"a": {"b": 1}}, indent=4, ensure_ascii=False)
        assert detect_json_style(text).indent == 4

    def test_compact_json_has_no_indent(self):
        assert detect_json_style('{"a": 1}').indent is None

    def test_literal_non_ascii_means_ensure_ascii_false(self):
        text = json.dumps({"ko": "공격"}, indent=2, ensure_ascii=False)
        assert detect_json_style(text).ensure_ascii is False

    def test_escaped_non_ascii_means_ensure_ascii_true(self):
        text = json.dumps({"ko": "공격"}, indent=2, ensure_ascii=True)
        assert detect_json_style(text).ensure_ascii is True

    def test_trailing_newline_is_detected(self):
        assert detect_json_style('{"a": 1}\n').trailing_newline is True
        assert detect_json_style('{"a": 1}').trailing_newline is False


class TestJsonRoundTrip:
    def test_untouched_document_round_trips_byte_identical(self):
        original = json.dumps(
            {"summary": {"weapon": "foil"}, "touches": [{"ko": "공격 실패"}]},
            indent=2,
            ensure_ascii=False,
        )
        data = json.loads(original)
        assert dumps_json(data, detect_json_style(original)) == original

    def test_key_order_is_preserved_and_nothing_is_dropped(self):
        original = json.dumps(
            {"z": 1, "a": 2, "m": {"y": 3, "b": 4}}, indent=2, ensure_ascii=False,
        )
        data = json.loads(original)
        rewritten = dumps_json(data, detect_json_style(original))
        assert rewritten == original
        assert list(json.loads(rewritten).keys()) == ["z", "a", "m"]
        assert list(json.loads(rewritten)["m"].keys()) == ["y", "b"]

    def test_added_keys_append_without_reordering_existing_ones(self):
        original = json.dumps({"z": 1, "a": 2}, indent=2, ensure_ascii=False)
        data = json.loads(original)
        data["lamp_pattern"] = "double"
        rewritten = dumps_json(data, detect_json_style(original))
        assert list(json.loads(rewritten).keys()) == ["z", "a", "lamp_pattern"]

    def test_real_report_round_trips_byte_identical(self, tmp_path):
        # The style detector must handle the actual on-disk report shape.
        source = (
            "{\n"
            '  "summary": {\n'
            '    "weapon": "foil"\n'
            "  },\n"
            '  "touches": [\n'
            '    {\n'
            '      "attack_outcome_ko": "공격 실패 (방어 성공)"\n'
            "    }\n"
            "  ]\n"
            "}"
        )
        path = tmp_path / "r.json"
        path.write_text(source, encoding="utf-8")
        raw = path.read_text(encoding="utf-8")
        assert dumps_json(json.loads(raw), detect_json_style(raw)) == source


# ------------------------------------------------------------------
# Consistency and counting
# ------------------------------------------------------------------


class TestLampScorerConsistency:
    def test_double_is_consistent_with_either_scorer(self):
        assert lamp_scorer_consistency("double", "left") is True
        assert lamp_scorer_consistency("double", "right") is True

    def test_single_matching_the_scorer_is_consistent(self):
        assert lamp_scorer_consistency("single_left", "left") is True
        assert lamp_scorer_consistency("single_right", "right") is True

    def test_single_contradicting_the_scorer_is_inconsistent(self):
        assert lamp_scorer_consistency("single_left", "right") is False
        assert lamp_scorer_consistency("single_right", "left") is False

    def test_white_and_unread_have_nothing_to_check(self):
        assert lamp_scorer_consistency("white", "left") is None
        assert lamp_scorer_consistency(None, "left") is None

    def test_missing_scorer_has_nothing_to_check(self):
        assert lamp_scorer_consistency("single_left", None) is None


class TestPatternCounts:
    def test_all_buckets_present_even_when_zero(self):
        counts = pattern_counts([])
        assert counts == {
            "double": 0,
            "single_left": 0,
            "single_right": 0,
            "white": 0,
            "unread": 0,
        }

    def test_none_reading_counts_as_unread(self):
        reader = LampBarReader()
        readings = [
            reader.read_touch_lamp([make_event(100, 130, left="color")], 200),
            None,
            reader.read_touch_lamp([], 500),
        ]
        counts = pattern_counts(readings)
        assert counts["single_left"] == 1
        assert counts["unread"] == 2


class TestFormatTouchTable:
    def test_row_carries_every_requested_column(self):
        touches = [make_touch(1, 250, "left")]
        readings = read_touch_readings(
            LampBarReader(), [make_event(100, 130, left="color")], [250],
        )
        row = format_touch_table(touches, readings).splitlines()[-1].split()
        # touch number, scorer, pattern, confidence, lamp start, lead, consistent
        assert row[0] == "1"
        assert row[1] == "left"
        assert row[2] == "single_left"
        assert float(row[3]) > 0.0
        assert row[4] == "100"
        assert row[5] == "150"  # 250 - 100
        assert row[6] == "yes"

    def test_header_names_every_column(self):
        header = format_touch_table([], []).splitlines()[0]
        for name in ("scorer", "lamp", "conf", "lamp_start", "lead", "consistent"):
            assert name in header

    def test_unread_touch_renders_dashes_for_lamp_columns(self):
        row = format_touch_table([make_touch(1, 200, "left")], [None])
        row = row.splitlines()[-1].split()
        assert row[0] == "1"
        assert row[2] == "-"  # pattern
        assert row[4] == "-"  # lamp start
        assert row[5] == "-"  # lead
        assert row[6] == "-"  # consistency undecidable

    def test_conflicting_row_is_marked_NO(self):
        touches = [make_touch(1, 250, "right")]
        readings = read_touch_readings(
            LampBarReader(), [make_event(100, 130, left="color")], [250],
        )
        assert format_touch_table(touches, readings).splitlines()[-1].split()[6] == "NO"


# ------------------------------------------------------------------
# Label CSV
# ------------------------------------------------------------------


def row_confidence_places(row):
    """True when the row's confidence is formatted to exactly 3 decimals."""
    value = row["confidence"]
    return "." in value and len(value.split(".")[1]) == 3


class TestBuildLabelRow:
    def _reading(self, events, frame):
        return LampBarReader().read_touch_lamp(events, frame)

    def test_double_autofills_priority_attacker_with_the_scorer(self):
        reading = self._reading(
            [make_event(100, 130, left="color", right="color")], 200,
        )
        row = build_label_row(make_touch(3, 200, "right", exchange=12), reading)
        assert row["lamp"] == "double"
        assert row["priority_attacker"] == "right"
        assert row["note"].startswith(NOTE_AUTO_PREFIX)
        assert row_needs_review(row) is False

    def test_double_autofill_follows_a_left_scorer_too(self):
        reading = self._reading(
            [make_event(100, 130, left="color", right="color")], 200,
        )
        row = build_label_row(make_touch(4, 200, "left"), reading)
        assert row["priority_attacker"] == "left"

    def test_single_left_leaves_priority_attacker_blank(self):
        reading = self._reading([make_event(100, 130, left="color")], 200)
        row = build_label_row(make_touch(1, 200, "left"), reading)
        assert row["lamp"] == "single_left"
        assert row["priority_attacker"] == ""
        assert row["note"].startswith(NOTE_REVIEW_PREFIX)
        assert row_needs_review(row) is True

    def test_single_right_leaves_priority_attacker_blank(self):
        reading = self._reading([make_event(100, 130, right="color")], 200)
        row = build_label_row(make_touch(2, 200, "right"), reading)
        assert row["lamp"] == "single_right"
        assert row["priority_attacker"] == ""
        assert row_needs_review(row) is True

    def test_single_note_states_no_priority_ruling_was_made(self):
        reading = self._reading([make_event(100, 130, left="color")], 200)
        row = build_label_row(make_touch(1, 200, "left"), reading)
        assert "우선권 판정" in row["note"]

    def test_white_leaves_priority_blank_and_needs_review(self):
        # read_touch_lamp never attributes a white-only event to a touch, so a
        # white pattern can only reach the row builder as a constructed reading.
        row = build_label_row(
            make_touch(5, 200, "left"),
            LampReading(pattern="white", confidence=0.5),
        )
        assert row["lamp"] == "white"
        assert row["priority_attacker"] == ""
        assert row_needs_review(row) is True

    def test_unread_leaves_lamp_and_priority_blank(self):
        row = build_label_row(make_touch(6, 200, "left"), None)
        assert row["lamp"] == ""
        assert row["priority_attacker"] == ""
        assert row["confidence"] == "0.000"
        assert row_needs_review(row) is True

    def test_confidence_is_three_decimal_places(self):
        reading = self._reading([make_event(100, 130, left="color")], 200)
        assert row_confidence_places(build_label_row(make_touch(1, 200, "left"), reading))

    def test_exchange_number_is_blank_when_none(self):
        row = build_label_row(make_touch(7, 200, "left", exchange=None), None)
        assert row["exchange_number"] == ""

    def test_exchange_number_is_copied_when_present(self):
        row = build_label_row(make_touch(7, 200, "left", exchange=41), None)
        assert row["exchange_number"] == 41

    def test_conflicting_single_lamp_is_flagged_for_review(self):
        reading = self._reading([make_event(100, 130, left="color")], 200)
        row = build_label_row(make_touch(8, 200, "right"), reading)
        assert row["priority_attacker"] == ""
        assert row_needs_review(row) is True
        assert "모순" in row["note"]



class TestWriteLabelCsv:
    def test_header_is_exactly_the_six_specified_columns_in_order(self, tmp_path):
        path = tmp_path / "labels.csv"
        write_label_csv(path, [])
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
        assert first_line == (
            "touch_number,exchange_number,priority_attacker,lamp,confidence,note"
        )
        assert LABEL_CSV_HEADER == first_line.split(",")

    def test_rows_are_written_in_touch_order(self, tmp_path):
        reader = LampBarReader()
        events = [
            make_event(100, 130, left="color", right="color"),
            make_event(400, 430, right="color"),
        ]
        touches = [make_touch(1, 200, "left"), make_touch(2, 500, "right")]
        readings = read_touch_readings(reader, events, [200, 500])
        rows = build_label_rows(touches, readings)

        path = tmp_path / "labels.csv"
        write_label_csv(path, rows)
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3
        assert lines[1].startswith("1,,left,double,")
        assert lines[2].startswith("2,,,single_right,")


# ------------------------------------------------------------------
# CLI behaviour
# ------------------------------------------------------------------


FOIL_REPORT = {
    "summary": {"weapon": "foil", "final_score": "2-0"},
    "touches": [
        {
            "touch_number": 1,
            "frame": 200,
            "scorer": "left",
            "attack_outcome": "unclear",
            "attacker_side": None,
            "matched_exchange_number": 5,
        },
        {
            "touch_number": 2,
            "frame": 500,
            "scorer": "right",
            "attack_outcome": "unclear",
            "attacker_side": None,
            "matched_exchange_number": 6,
        },
    ],
    "meta": {"version": "test"},
}


@pytest.fixture
def report_file(tmp_path):
    path = tmp_path / "bout_continuous_report.json"
    path.write_text(
        json.dumps(FOIL_REPORT, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    return path


@pytest.fixture
def video_file(tmp_path):
    path = tmp_path / "bout.mp4"
    path.write_bytes(b"not a real video")
    return path


@pytest.fixture
def fake_scan(monkeypatch):
    """Replace video decoding with prebuilt events inside the scanned range."""
    events = [
        make_event(100, 130, left="color", right="color"),
        make_event(400, 430, right="color"),
    ]

    def scan(self, video_path, start_frame, end_frame, step=3):
        return [e for e in events if start_frame <= e.start_frame <= end_frame]

    monkeypatch.setattr(LampBarReader, "scan_video_events", scan)
    return events


class TestWeaponGate:
    def test_non_foil_report_is_refused_with_nonzero_exit(
        self, tmp_path, video_file, fake_scan, capsys,
    ):
        report = dict(FOIL_REPORT)
        report["summary"] = {"weapon": "sabre"}
        path = tmp_path / "sabre_report.json"
        source = json.dumps(report, indent=2, ensure_ascii=False)
        path.write_text(source, encoding="utf-8")

        code = main(["--report", str(path), "--video", str(video_file)])

        assert code != 0
        assert "foil" in capsys.readouterr().err
        assert path.read_text(encoding="utf-8") == source

    def test_force_overrides_the_weapon_gate(
        self, tmp_path, video_file, fake_scan,
    ):
        report = json.loads(json.dumps(FOIL_REPORT))
        report["summary"]["weapon"] = "epee"
        path = tmp_path / "epee_report.json"
        path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8",
        )

        code = main(
            ["--report", str(path), "--video", str(video_file), "--force"],
        )

        assert code == 0
        assert json.loads(path.read_text(encoding="utf-8"))["touches"][0][
            "lamp_pattern"
        ] == "double"

    def test_missing_weapon_is_refused(self, tmp_path, video_file, fake_scan):
        report = json.loads(json.dumps(FOIL_REPORT))
        del report["summary"]["weapon"]
        path = tmp_path / "unknown_report.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        assert main(["--report", str(path), "--video", str(video_file)]) != 0


class TestDryRun:
    def test_dry_run_writes_nothing(
        self, report_file, video_file, fake_scan, tmp_path,
    ):
        before_text = report_file.read_text(encoding="utf-8")
        before_mtime = report_file.stat().st_mtime_ns
        labels = tmp_path / "labels.csv"
        time.sleep(0.01)

        code = main([
            "--report", str(report_file),
            "--video", str(video_file),
            "--labels-csv", str(labels),
            "--dry-run",
        ])

        assert code == 0
        assert report_file.read_text(encoding="utf-8") == before_text
        assert report_file.stat().st_mtime_ns == before_mtime
        assert not labels.exists()

    def test_dry_run_still_prints_the_table(
        self, report_file, video_file, fake_scan, capsys,
    ):
        main([
            "--report", str(report_file),
            "--video", str(video_file),
            "--dry-run",
        ])
        out = capsys.readouterr().out
        assert "double" in out
        assert "Read rate:" in out


class TestWriteBack:
    def test_report_keeps_every_original_key_in_order(
        self, report_file, video_file, fake_scan,
    ):
        main(["--report", str(report_file), "--video", str(video_file)])
        data = json.loads(report_file.read_text(encoding="utf-8"))

        assert list(data.keys()) == ["summary", "touches", "meta"]
        assert data["summary"] == {"weapon": "foil", "final_score": "2-0"}
        assert data["meta"] == {"version": "test"}

        touch = data["touches"][0]
        for key in (
            "touch_number", "frame", "scorer", "attack_outcome",
            "attacker_side", "matched_exchange_number",
        ):
            assert key in touch
        assert list(touch.keys())[:6] == [
            "touch_number", "frame", "scorer", "attack_outcome",
            "attacker_side", "matched_exchange_number",
        ]

    def test_report_formatting_style_is_preserved(
        self, report_file, video_file, fake_scan,
    ):
        main(["--report", str(report_file), "--video", str(video_file)])
        text = report_file.read_text(encoding="utf-8")
        assert text.startswith('{\n  "summary": {\n')
        assert not text.endswith("\n")

    def test_lamp_fields_are_applied_via_annotate_touch_lamps(
        self, report_file, video_file, fake_scan,
    ):
        main(["--report", str(report_file), "--video", str(video_file)])
        touches = json.loads(report_file.read_text(encoding="utf-8"))["touches"]
        assert touches[0]["lamp_pattern"] == "double"
        assert touches[1]["lamp_pattern"] == "single_right"
        assert touches[0]["lamp_detail"]["lead_frames"] == 100

    def test_labels_csv_is_written_when_requested(
        self, report_file, video_file, fake_scan, tmp_path,
    ):
        labels = tmp_path / "labels.csv"
        main([
            "--report", str(report_file),
            "--video", str(video_file),
            "--labels-csv", str(labels),
        ])
        lines = labels.read_text(encoding="utf-8").splitlines()
        assert lines[0] == ",".join(LABEL_CSV_HEADER)
        assert lines[1].startswith("1,5,left,double,")
        assert lines[2].startswith("2,6,,single_right,")

    def test_autofilled_and_review_counts_are_printed(
        self, report_file, video_file, fake_scan, capsys,
    ):
        main(["--report", str(report_file), "--video", str(video_file)])
        assert "1 auto-filled, 1 need human review" in capsys.readouterr().out

    def test_windows_are_merged_before_scanning(
        self, report_file, video_file, monkeypatch,
    ):
        calls = []

        def scan(self, video_path, start_frame, end_frame, step=3):
            calls.append((start_frame, end_frame))
            return []

        monkeypatch.setattr(LampBarReader, "scan_video_events", scan)
        main(["--report", str(report_file), "--video", str(video_file)])

        # Touches at 200 and 500 are 300 frames apart, inside the 330-frame
        # lookback, so exactly one merged window must be scanned.
        assert calls == [(0, 500 + LAMP_SEARCH_FORWARD)]


class TestInputValidation:
    def test_missing_report_exits_nonzero(self, tmp_path, video_file):
        code = main([
            "--report", str(tmp_path / "nope.json"),
            "--video", str(video_file),
        ])
        assert code != 0

    def test_missing_video_exits_nonzero(self, report_file, tmp_path):
        code = main([
            "--report", str(report_file),
            "--video", str(tmp_path / "nope.mp4"),
        ])
        assert code != 0

    def test_report_without_touches_exits_nonzero(self, tmp_path, video_file):
        path = tmp_path / "empty_report.json"
        path.write_text(
            json.dumps({"summary": {"weapon": "foil"}, "touches": []}, indent=2),
            encoding="utf-8",
        )
        assert main(["--report", str(path), "--video", str(video_file)]) != 0


class TestJsonStyleDataclass:
    def test_defaults_match_this_project_convention(self):
        style = JsonStyle()
        assert style.indent == 2
        assert style.ensure_ascii is False
        assert style.trailing_newline is False
