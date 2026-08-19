"""Tests for the priority label collector's own logic.

Video decoding, OCR and ffmpeg are all out of scope here — those are exercised
by running the script. What is pinned here is everything that decides *what*
gets written: ROI parsing, clip anchoring, preview selection, the yield funnel
and the CSV contract.
"""

import csv

import numpy as np
import pytest

from pipeline.priority_label_rules import (
    DOUBLE,
    REJECT_SCORE_BOTH_INCREASED,
    REJECT_SINGLE_LAMP,
    SINGLE_LEFT,
    decide_priority_label,
)
from scripts.collect_priority_labels import (
    CSV_HEADER,
    RectLampReader,
    TouchRecord,
    build_stats,
    clip_start_frame,
    format_stats,
    parse_lamp_roi,
    select_preview_indices,
    write_labels_csv,
)


def make_record(index, *, lamp=DOUBLE, before="2-1", after="3-1", scorer="left",
                lamp_frame=None, conf=0.9, touch_frame=1000):
    rec = TouchRecord(
        index=index,
        touch_frame=touch_frame,
        touch_time=touch_frame / 30.0,
        scorer=scorer,
        score_before=before,
        score_after=after,
        lamp_pattern=lamp,
        lamp_confidence=conf,
        lamp_frame=lamp_frame,
    )
    rec.decision = decide_priority_label(
        lamp, before, after, scorer=scorer, lamp_confidence=conf
    )
    return rec


class TestParseLampRoi:
    def test_both_sides(self):
        assert parse_lamp_roi("left=1,2,3,4;right=5,6,7,8") == {
            "left": (1, 2, 3, 4),
            "right": (5, 6, 7, 8),
        }

    def test_whitespace_and_trailing_semicolon(self):
        assert parse_lamp_roi(" left = 1, 2, 3, 4 ; right=5,6,7,8 ; ")["left"] == (1, 2, 3, 4)

    @pytest.mark.parametrize(
        "spec",
        [
            "left=1,2,3,4",                    # right missing
            "right=1,2,3,4",                   # left missing
            "left=1,2,3;right=5,6,7,8",        # too few coords
            "left=1,2,3,4,5;right=5,6,7,8",    # too many coords
            "left=a,2,3,4;right=5,6,7,8",      # non-integer
            "middle=1,2,3,4;right=5,6,7,8",    # unknown side
            "left:1,2,3,4",                    # no '='
            "left=3,2,1,4;right=5,6,7,8",      # x1 <= x0
            "left=1,4,3,2;right=5,6,7,8",      # y1 <= y0
        ],
    )
    def test_rejected(self, spec):
        with pytest.raises(ValueError):
            parse_lamp_roi(spec)


class TestRectLampReader:
    def test_reads_from_absolute_rectangles(self):
        frame = np.zeros((200, 200, 3), dtype=np.uint8)
        frame[10:40, 10:40] = (0, 0, 255)      # red block, left ROI
        frame[10:40, 100:130] = (0, 255, 0)    # green block, right ROI
        reader = RectLampReader(
            {"left": (10, 10, 40, 40), "right": (100, 10, 130, 40)}
        )
        assert reader.read_side_states(frame) == ("color", "color")

    def test_off_when_rectangles_are_dark(self):
        frame = np.zeros((200, 200, 3), dtype=np.uint8)
        reader = RectLampReader(
            {"left": (10, 10, 40, 40), "right": (100, 10, 130, 40)}
        )
        assert reader.read_side_states(frame) == ("off", "off")

    def test_missing_side_rejected(self):
        with pytest.raises(ValueError):
            RectLampReader({"left": (0, 0, 10, 10)})

    def test_inherits_pattern_semantics(self):
        # The point of subclassing is that a manual ROI cannot invent its own
        # notion of "double".
        frame = np.zeros((200, 200, 3), dtype=np.uint8)
        frame[10:40, 10:40] = (0, 0, 255)
        reader = RectLampReader(
            {"left": (10, 10, 40, 40), "right": (100, 10, 130, 40)}
        )
        assert reader.read_side_states(frame) == ("color", "off")


class TestClipAnchoring:
    def test_anchors_on_lamp_frame_when_available(self):
        rec = make_record(1, lamp_frame=900, touch_frame=1000)
        assert clip_start_frame(rec, 30.0) == 900

    def test_falls_back_behind_score_frame(self):
        # Without a lamp the score frame is all there is, and it trails the
        # touch, so the anchor must step back by the measured OCR lag.
        rec = make_record(1, lamp_frame=None, touch_frame=1000)
        anchor = clip_start_frame(rec, 30.0)
        assert anchor < 1000
        assert anchor == 1000 - int(2.8 * 30)

    def test_never_negative(self):
        rec = make_record(1, lamp_frame=None, touch_frame=5)
        assert clip_start_frame(rec, 30.0) == 0

    def test_lamp_anchor_precedes_score_frame_in_practice(self):
        rec = make_record(1, lamp_frame=940, touch_frame=1000)
        assert clip_start_frame(rec, 30.0) < rec.touch_frame


class TestPreviewSelection:
    def test_only_accepted_records(self):
        records = [
            make_record(1),
            make_record(2, lamp=SINGLE_LEFT),
            make_record(3),
        ]
        assert select_preview_indices(records, 5) == [0, 2]

    def test_spread_across_the_bout(self):
        records = [make_record(i) for i in range(1, 21)]
        picked = select_preview_indices(records, 4)
        assert len(picked) == 4
        assert picked[0] == 0
        assert picked[-1] == 19
        assert picked == sorted(picked)

    def test_no_duplicates(self):
        records = [make_record(i) for i in range(1, 31)]
        picked = select_preview_indices(records, 8)
        assert len(set(picked)) == len(picked) == 8

    def test_zero_count(self):
        assert select_preview_indices([make_record(1)], 0) == []

    def test_no_accepted_records(self):
        records = [make_record(1, lamp=SINGLE_LEFT)]
        assert select_preview_indices(records, 4) == []


class TestStats:
    def test_funnel_counts(self):
        records = [
            make_record(1),                                    # accepted
            make_record(2),                                    # accepted
            make_record(3, lamp=SINGLE_LEFT),                  # single
            make_record(4, lamp=None),                         # unread
            make_record(5, after="3-2"),                       # double, bad score
        ]
        stats = build_stats(records)
        assert stats.touches_detected == 5
        assert stats.labels_confirmed == 2
        assert stats.lamp_read == 4          # everything but the unread one
        assert stats.two_light == 3          # includes the discarded double
        assert stats.rejected[REJECT_SINGLE_LAMP] == 1
        assert stats.rejected[REJECT_SCORE_BOTH_INCREASED] == 1

    def test_two_light_counts_discarded_doubles(self):
        # A double thrown out for an inconsistent score is still evidence about
        # how often two-lights occur, and must not vanish from the funnel.
        records = [make_record(1, after="3-2")]
        stats = build_stats(records)
        assert stats.two_light == 1
        assert stats.labels_confirmed == 0

    def test_rejected_totals_reconcile(self):
        records = [make_record(i, lamp=SINGLE_LEFT) for i in range(1, 6)]
        records += [make_record(9), make_record(10)]
        stats = build_stats(records)
        assert stats.labels_confirmed + sum(stats.rejected.values()) == stats.touches_detected

    def test_empty(self):
        stats = build_stats([])
        assert stats.touches_detected == 0
        assert stats.rejected == {}
        assert "touches detected" in format_stats(stats)

    def test_format_lists_every_reason(self):
        records = [make_record(1, lamp=SINGLE_LEFT), make_record(2, after="3-2")]
        text = format_stats(build_stats(records))
        assert REJECT_SINGLE_LAMP in text
        assert REJECT_SCORE_BOTH_INCREASED in text


class TestLabelsCsv:
    def test_header_is_the_contract(self, tmp_path):
        path = tmp_path / "labels.csv"
        write_labels_csv(path, [make_record(1)], "vid")
        with open(path, encoding="utf-8") as fh:
            assert next(csv.reader(fh)) == CSV_HEADER

    def test_only_accepted_rows_written(self, tmp_path):
        path = tmp_path / "labels.csv"
        records = [
            make_record(1),
            make_record(2, lamp=SINGLE_LEFT),
            make_record(3, after="3-2"),
            make_record(4, before="2-1", after="2-2", scorer="right"),
        ]
        rows = write_labels_csv(path, records, "vid")
        assert rows == 2
        with open(path, encoding="utf-8") as fh:
            data = list(csv.DictReader(fh))
        assert [r["label"] for r in data] == ["left", "right"]

    def test_both_lamps_always_true_in_output(self, tmp_path):
        # Only two-light touches are ever written, so the column is a stated
        # invariant of the file rather than a per-row variable.
        path = tmp_path / "labels.csv"
        write_labels_csv(path, [make_record(1), make_record(2)], "vid")
        with open(path, encoding="utf-8") as fh:
            assert all(r["both_lamps"] == "true" for r in csv.DictReader(fh))

    def test_scores_and_id_round_trip(self, tmp_path):
        path = tmp_path / "labels.csv"
        rec = make_record(7, before="4-3", after="5-3", lamp_frame=880, touch_frame=910)
        rec.clip_path = "clip_007.mp4"
        write_labels_csv(path, [rec], "my_video")
        with open(path, encoding="utf-8") as fh:
            row = next(csv.DictReader(fh))
        assert row["video_id"] == "my_video"
        assert row["clip"] == "clip_007.mp4"
        assert row["score_before"] == "4-3"
        assert row["score_after"] == "5-3"
        assert row["touch_frame"] == "910"
        assert row["lamp_frame"] == "880"
        assert float(row["touch_time"]) == pytest.approx(910 / 30.0, abs=0.01)

    def test_missing_lamp_frame_is_blank_not_none(self, tmp_path):
        path = tmp_path / "labels.csv"
        write_labels_csv(path, [make_record(1, lamp_frame=None)], "vid")
        with open(path, encoding="utf-8") as fh:
            assert next(csv.DictReader(fh))["lamp_frame"] == ""

    def test_empty_input_writes_header_only(self, tmp_path):
        path = tmp_path / "labels.csv"
        assert write_labels_csv(path, [], "vid") == 0
        assert path.read_text(encoding="utf-8").strip() == ",".join(CSV_HEADER)
