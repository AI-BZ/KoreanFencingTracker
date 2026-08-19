"""Tests for report view preparation (app.report_renderer view helpers).

Covers the display-only enrichment added for the report page redesign:
broken clock-OCR repair, unclear-outcome reasons, the unified event
timeline, and the clip cache status endpoint.
"""

import re

import pytest
from fastapi.testclient import TestClient

from analyzer.tv_overlay_ocr import _valid_clock_text
from app.report_renderer import (
    OUTCOME_REASON_MUTUAL,
    OUTCOME_REASON_NO_ADVANCE,
    OUTCOME_REASON_NO_EXCHANGE,
    annotate_outcome_reasons,
    build_timeline,
    prepare_report_view,
    repair_match_times,
)


# ------------------------------------------------------------------
# Clock OCR validation (generation-side fix)
# ------------------------------------------------------------------


class TestValidClockText:
    @pytest.mark.parametrize("text", ["2:03", "0:59", "12:00", "45", "0", "180"])
    def test_accepts_valid_readings(self, text):
        assert _valid_clock_text(text) is True

    @pytest.mark.parametrize("text", ["2:3", "2:", ":30", "2:333", "2:61", "1:2:3", "181", "abc"])
    def test_rejects_partial_or_invalid_readings(self, text):
        assert _valid_clock_text(text) is False


# ------------------------------------------------------------------
# Broken match_time repair (render-side fix for saved reports)
# ------------------------------------------------------------------


class TestRepairMatchTimes:
    def test_valid_times_untouched(self):
        touches = [{"match_time": "2:53"}, {"match_time": "0:05"}]
        repair_match_times(touches)
        assert touches[0]["match_time"] == "2:53"
        assert touches[1]["match_time"] == "0:05"
        assert "match_time_estimated" not in touches[0]

    def test_truncated_seconds_repaired_within_neighbor_bounds(self):
        # Real case from the LI/LIN foil report: 2:46 → "2:3" → 2:34.
        # The clock counts down, so the true value lies in [2:34, 2:46];
        # the reconstruction must land in that window and be flagged.
        touches = [
            {"match_time": "2:46"},
            {"match_time": "2:3"},
            {"match_time": "2:34"},
        ]
        repair_match_times(touches)
        repaired = touches[1]["match_time"]
        assert touches[1]["match_time_estimated"] is True
        m, s = repaired.split(":")
        assert len(s) == 2
        total = int(m) * 60 + int(s)
        assert 154 <= total <= 166  # between 2:34 and 2:46

    def test_truncated_without_neighbors_still_formats_validly(self):
        touches = [{"match_time": "2:3"}]
        repair_match_times(touches)
        m, s = touches[0]["match_time"].split(":")
        assert m.isdigit() and s.isdigit() and len(s) == 2
        assert touches[0]["match_time_estimated"] is True

    def test_non_clock_values_left_alone(self):
        touches = [{"match_time": ""}, {"match_time": None}, {}]
        repair_match_times(touches)
        assert touches[0]["match_time"] == ""
        assert touches[1]["match_time"] is None


# ------------------------------------------------------------------
# Unclear outcome reasons
# ------------------------------------------------------------------


class TestOutcomeReasons:
    def _report(self, attacker, matched=1):
        return {
            "touches": [{
                "touch_number": 1, "scorer": "left",
                "attack_outcome": "unclear", "matched_exchange_number": matched,
            }],
            "exchanges": [{"exchange_number": 1, "attacker": attacker}],
        }

    def test_mutual_attack_reason(self):
        r = annotate_outcome_reasons(self._report("both"))
        assert r["touches"][0]["outcome_reason"] == OUTCOME_REASON_MUTUAL

    def test_no_advance_reason(self):
        r = annotate_outcome_reasons(self._report("unknown"))
        assert r["touches"][0]["outcome_reason"] == OUTCOME_REASON_NO_ADVANCE

    def test_no_matched_exchange_reason(self):
        r = annotate_outcome_reasons(self._report("both", matched=None))
        assert r["touches"][0]["outcome_reason"] == OUTCOME_REASON_NO_EXCHANGE

    def test_clear_outcomes_get_no_reason(self):
        report = self._report("left")
        report["touches"][0]["attack_outcome"] = "attack_failed"
        annotate_outcome_reasons(report)
        assert "outcome_reason" not in report["touches"][0]


# ------------------------------------------------------------------
# Unified timeline
# ------------------------------------------------------------------


class TestBuildTimeline:
    def test_matched_exchange_folded_into_touch(self):
        report = {
            "touches": [{"touch_number": 1, "frame": 900, "matched_exchange_number": 2}],
            "exchanges": [
                {"exchange_number": 1, "start_frame": 100, "end_frame": 200},
                {"exchange_number": 2, "start_frame": 800, "end_frame": 890},
            ],
        }
        timeline = build_timeline(report)
        # Exchange 2 is the touch's engagement — it must not appear twice.
        assert len(timeline) == 2
        kinds = [ev["kind"] for ev in timeline]
        assert kinds == ["exchange", "touch"]
        touch_ev = timeline[1]
        assert touch_ev["exchange"]["exchange_number"] == 2
        # Touch sorts by the exchange start (when the action happened).
        assert touch_ev["sort_frame"] == 800

    def test_unmatched_touch_sorts_by_own_frame(self):
        report = {
            "touches": [{"touch_number": 1, "frame": 500, "matched_exchange_number": None}],
            "exchanges": [{"exchange_number": 1, "start_frame": 600}],
        }
        timeline = build_timeline(report)
        assert [ev["kind"] for ev in timeline] == ["touch", "exchange"]

    def test_report_without_exchanges(self):
        report = {"touches": [{"touch_number": 1, "frame": 10}, {"touch_number": 2, "frame": 5}]}
        timeline = build_timeline(report)
        assert [ev["touch"]["touch_number"] for ev in timeline] == [2, 1]

    def test_empty_report(self):
        assert build_timeline({}) == []


# ------------------------------------------------------------------
# Report page rendering (integration)
# ------------------------------------------------------------------


def _synthetic_report():
    return {
        "summary": {
            "final_score": "1-1", "total_touches": 2, "match_duration": "3:00",
            "weapon": "foil", "bout_type": "de",
            "analysis_time_sec": 1.0, "total_frames_analyzed": 100,
        },
        "touches": [
            {
                "touch_number": 1, "frame": 900, "video_timestamp": "0:30",
                "match_time": "2:46", "scorer": "right", "score_after": "0-1",
                "attack_outcome": "attack_failed", "attacker_side": "left",
                "defender_side": "right", "matched_exchange_number": 1,
            },
            {
                "touch_number": 2, "frame": 1800, "video_timestamp": "1:00",
                "match_time": "2:3", "scorer": "left", "score_after": "1-1",
                "attack_outcome": "unclear", "attacker_side": None,
                "defender_side": None, "matched_exchange_number": 2,
            },
        ],
        "exchanges": [
            {"exchange_number": 1, "start_frame": 800, "end_frame": 880,
             "start_time": "0:26", "end_time": "0:29", "event_type": "failed_attack",
             "event_type_ko": "공격 실패", "attacker": "left", "defender": "right",
             "footwork_left": "fleche", "footwork_right": "retreat"},
            {"exchange_number": 2, "start_frame": 1700, "end_frame": 1780,
             "start_time": "0:56", "end_time": "0:59", "event_type": "unknown_exchange",
             "event_type_ko": "분류 미정", "attacker": "both", "defender": "both"},
            {"exchange_number": 3, "start_frame": 2000, "end_frame": 2100,
             "start_time": "1:06", "end_time": "1:10", "event_type": "mutual_retreat",
             "event_type_ko": "상호 후퇴", "attacker": "unknown", "defender": "unknown"},
        ],
        "left_fencer": {"name": "LIN Youlong", "total_touches_scored": 1,
                        "total_touches_conceded": 1, "action_distribution": []},
        "right_fencer": {"name": "LI Richard", "total_touches_scored": 1,
                         "total_touches_conceded": 1, "action_distribution": []},
        "insights": [],
        "meta": {"phase": "7b", "pose_model": "yolo11n-pose", "action_model": "rule", "fps": 30},
    }


class TestReportPageView:
    @pytest.fixture()
    def client(self):
        from app.server import app
        return TestClient(app)

    @pytest.fixture()
    def report_url(self):
        from app.server import _jobs
        report = _synthetic_report()
        _jobs["view-test-001"] = {
            "status": "completed", "progress_pct": 100.0,
            "result": report, "mock_mode": False,
        }
        yield "/report/view-test-001"
        _jobs.pop("view-test-001", None)

    def test_page_renders(self, client, report_url):
        resp = client.get(report_url)
        assert resp.status_code == 200

    def test_timeline_section_above_stats(self, client, report_url):
        html = client.get(report_url).text
        assert html.index("경기 타임라인") < html.index("스코어 타임라인")
        assert html.index("경기 타임라인") < html.index("터치별 상세")

    def test_attack_failed_sentence_has_subject(self, client, report_url):
        html = client.get(report_url).text
        # The attacker (LIN) and the scoring defender (LI) must both be named.
        assert "공격 실패 →" in html
        assert "LIN Youlong" in html and "LI Richard" in html
        assert "방어 성공 후" in html or "방어 후 득점" in html

    def test_unclear_touch_has_reason(self, client, report_url):
        html = client.get(report_url).text
        assert OUTCOME_REASON_MUTUAL in html

    def test_broken_match_time_not_rendered(self, client, report_url):
        html = client.get(report_url).text
        assert ">2:3<" not in html
        assert "~2:" in html  # repaired + flagged as estimate

    def test_matched_exchanges_not_duplicated(self, client, report_url):
        html = client.get(report_url).text
        # Exchange 3 (unmatched) appears; exchanges 1 & 2 are folded into touches.
        assert html.count("상호 후퇴") >= 1
        assert 'data-kind="exchange"' in html
        assert html.count('data-kind="touch"') == 2
        assert html.count('data-kind="exchange"') == 1

    def test_clips_status_endpoint(self, client):
        resp = client.get("/api/analytics/clips/no-such-report/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cached"] == {"touch": [], "exchange": []}


class TestPrepareReportView:
    def test_prepare_is_idempotent(self):
        report = _synthetic_report()
        prepare_report_view(report)
        first = [t["match_time"] for t in report["touches"]]
        prepare_report_view(report)
        assert [t["match_time"] for t in report["touches"]] == first


# ------------------------------------------------------------------
# Timeline row numbering — the handle a coach names ("the call on #12")
# ------------------------------------------------------------------


class TestTimelineDisplayIndex:
    """The number on the chip: the row's position, unique by construction."""

    def test_ordinals_are_contiguous_from_one_in_display_order(self):
        timeline = build_timeline(_numbered_report())
        assert [ev["display_index"] for ev in timeline] == [1, 2, 3, 4]

    def test_ordinal_follows_the_sort_not_the_input_order(self):
        # Exchange 9 is listed first but happens last, so it is the third row.
        report = {
            "touches": [{"touch_number": 1, "frame": 900, "matched_exchange_number": 4}],
            "exchanges": [
                {"exchange_number": 9, "start_frame": 5000},
                {"exchange_number": 4, "start_frame": 800, "end_frame": 890},
            ],
        }
        timeline = build_timeline(report)
        assert [ev["sort_frame"] for ev in timeline] == [800, 5000]
        assert [ev["display_index"] for ev in timeline] == [1, 2]

    def test_ordinal_stays_unique_where_the_record_numbers_collide(self):
        # Touch numbers and exchange numbers are independent sequences, so two
        # different rows legitimately carry the same record number. That is what
        # made the record number unusable as the thing a coach points at.
        report = {
            "touches": [{"touch_number": 3, "frame": 900, "matched_exchange_number": None}],
            "exchanges": [{"exchange_number": 3, "start_frame": 100}],
        }
        timeline = build_timeline(report)
        assert [ev["display_number"] for ev in timeline] == [3, 3]
        assert [ev["display_index"] for ev in timeline] == [1, 2]

    def test_row_without_a_record_number_still_gets_an_ordinal(self):
        # The ordinal never goes missing — a row a coach cannot name defeats
        # the whole point of numbering the timeline.
        report = {"touches": [{"frame": 120}], "exchanges": [{"start_frame": 900}]}
        timeline = build_timeline(report)
        assert [ev["display_number"] for ev in timeline] == [None, None]
        assert [ev["display_index"] for ev in timeline] == [1, 2]


class TestTimelineDisplayNumber:
    """The tracing handle behind the chip: which record the row came from."""

    def test_matched_touch_row_names_the_exchange_it_folded_in(self):
        report = {
            "touches": [{"touch_number": 1, "frame": 900, "matched_exchange_number": 4}],
            "exchanges": [{"exchange_number": 4, "start_frame": 800, "end_frame": 890}],
        }
        (event,) = build_timeline(report)
        assert event["display_number"] == 4
        assert event["display_number_kind"] == "exchange"

    def test_unmatched_touch_row_falls_back_to_its_touch_number(self):
        report = {
            "touches": [{"touch_number": 7, "frame": 500, "matched_exchange_number": None}],
        }
        (event,) = build_timeline(report)
        assert event["display_number"] == 7
        assert event["display_number_kind"] == "touch"

    def test_plain_exchange_row_uses_its_exchange_number(self):
        report = {"exchanges": [{"exchange_number": 12, "start_frame": 300}]}
        (event,) = build_timeline(report)
        assert event["display_number"] == 12
        assert event["display_number_kind"] == "exchange"

    def test_row_without_any_record_number_reports_none(self):
        report = {"touches": [{"frame": 120}], "exchanges": [{"start_frame": 900}]}
        touch_ev, exchange_ev = build_timeline(report)
        assert touch_ev["display_number"] is None
        assert touch_ev["display_number_kind"] == "touch"
        assert exchange_ev["display_number"] is None
        assert exchange_ev["display_number_kind"] == "exchange"

    def test_every_event_carries_all_three_keys(self):
        timeline = build_timeline(_numbered_report())
        assert timeline
        for event in timeline:
            assert "display_number" in event
            assert event["display_number_kind"] in ("touch", "exchange")
            assert event["display_index"] >= 1


# ------------------------------------------------------------------
# The number chip on the page
# ------------------------------------------------------------------

#: Neutral bout stems stand in for fencer names — no real fencer here.
_HOME_STEM = "260815_pool_home_vs_away"
_AWAY_STEM = "260815_bout_b"

_TAG = re.compile(r"<[^>]+>")
_HANGUL = re.compile(r"[가-힣]")
#: Any element carrying .fm-num — the face is Barlow Condensed, digits only.
_FM_NUM = re.compile(r'<(\w+)[^>]*\bclass="[^"]*\bfm-num\b[^"]*"[^>]*>(.*?)</\1>', re.S)
#: The chip itself: "#" sits outside the span, the digits inside it.
_NUM_CHIP = re.compile(r'#<span class="fm-num">(\d+)</span>')
_CLIP_LABEL = re.compile(r'data-clip-label="([^"]*)"')


def _numbered_report() -> dict:
    """Four timeline rows, one per numbering case, in chronological order.

    Row 1 folded exchange 3 in, row 2 matched nothing and carries touch number
    3, row 3 has no record number at all, row 4 is a plain exchange numbered 1.

    Rows 1 and 2 deliberately collide: both are touch rows whose underlying
    record reads "3", one from the exchange sequence and one from the touch
    sequence. Nothing on screen separates two touch rows, so if the chip ever
    goes back to showing the record number this fixture catches it.
    """
    return {
        "summary": {
            "final_score": "2-1", "total_touches": 3, "match_duration": "3:00",
            "weapon": "foil", "bout_type": "de",
            "analysis_time_sec": 1.0, "total_frames_analyzed": 100,
        },
        "touches": [
            {"touch_number": 1, "frame": 900, "video_timestamp": "0:30",
             "match_time": "2:46", "scorer": "right", "score_after": "0-1",
             "attack_outcome": "unclear", "matched_exchange_number": 3},
            {"touch_number": 3, "frame": 1800, "video_timestamp": "1:00",
             "match_time": "2:20", "scorer": "left", "score_after": "1-1",
             "attack_outcome": "unclear", "matched_exchange_number": None},
            # No touch_number and no matched exchange — no record to trace to.
            {"frame": 2400, "video_timestamp": "1:20",
             "match_time": "2:00", "scorer": "left", "score_after": "2-1",
             "attack_outcome": "unclear", "matched_exchange_number": None},
        ],
        "exchanges": [
            {"exchange_number": 3, "start_frame": 800, "end_frame": 890,
             "start_time": "0:26", "end_time": "0:29", "event_type": "failed_attack",
             "event_type_ko": "공격 실패", "attacker": "left", "defender": "right"},
            {"exchange_number": 1, "start_frame": 2600, "end_frame": 2700,
             "start_time": "1:26", "end_time": "1:30", "event_type": "mutual_retreat",
             "event_type_ko": "상호 후퇴", "attacker": "unknown", "defender": "unknown"},
        ],
        "left_fencer": {"name": _HOME_STEM, "total_touches_scored": 2,
                        "total_touches_conceded": 1, "action_distribution": []},
        "right_fencer": {"name": _AWAY_STEM, "total_touches_scored": 1,
                         "total_touches_conceded": 2, "action_distribution": []},
        "insights": [],
        "meta": {"phase": "7b", "pose_model": "yolo11n-pose", "action_model": "rule", "fps": 30},
    }


def _render_numbered() -> str:
    from app.server import _jobs, app

    job_id = "numbering-render-001"
    _jobs[job_id] = {
        "status": "completed", "progress_pct": 100.0,
        "result": _numbered_report(), "mock_mode": False,
    }
    try:
        resp = TestClient(app, raise_server_exceptions=False).get(f"/report/{job_id}")
        assert resp.status_code == 200, resp.text[:2000]
        return resp.text
    finally:
        _jobs.pop(job_id, None)


def _timeline_block(html: str) -> str:
    start = html.index('id="timeline-list"')
    return html[start:html.index("</div>", html.index("득점으로 이어진 교전", start))]


@pytest.fixture()
def numbered_html():
    return _render_numbered()


class TestNumberChipRendering:
    def test_chips_are_the_row_ordinals_in_display_order(self, numbered_html):
        assert _NUM_CHIP.findall(_timeline_block(numbered_html)) == ["1", "2", "3", "4"]

    def test_every_chip_on_the_page_is_unique(self, numbered_html):
        # The whole feature rests on this: "#3 판정이 틀렸다" has to name one row.
        chips = _NUM_CHIP.findall(_timeline_block(numbered_html))
        assert len(set(chips)) == len(chips)

    def test_every_row_gets_a_chip_including_the_record_less_one(self, numbered_html):
        block = _timeline_block(numbered_html)
        rows = block.count('data-kind="touch"') + block.count('data-kind="exchange"')
        assert rows == 4
        assert len(_NUM_CHIP.findall(block)) == rows
        assert "#None" not in block

    def test_hash_sits_outside_the_barlow_span(self, numbered_html):
        # .fm-num is a digits face; the "#" glyph belongs to the surrounding text.
        for _tag, inner in _FM_NUM.findall(_timeline_block(numbered_html)):
            assert "#" not in inner

    def test_tooltip_traces_the_row_back_to_its_record(self, numbered_html):
        block = _timeline_block(numbered_html)
        # Row 1 folded exchange 3 in; row 2 is touch 3; row 4 is exchange 1.
        assert 'title="타임라인 1번째 — 교전 #3"' in block
        assert 'title="타임라인 2번째 — 득점 #3"' in block
        assert 'title="타임라인 4번째 — 교전 #1"' in block

    def test_tooltip_omits_the_record_when_there_is_none(self, numbered_html):
        assert 'title="타임라인 3번째"' in _timeline_block(numbered_html)

    def test_no_korean_inside_any_fm_num_element(self, numbered_html):
        offenders = [
            m.group(0) for m in _FM_NUM.finditer(numbered_html)
            if _HANGUL.search(" ".join(_TAG.sub("", m.group(2)).split()))
        ]
        assert offenders == []


class TestClipLabels:
    def test_touch_rows_lead_with_their_kind_and_ordinal(self, numbered_html):
        labels = _CLIP_LABEL.findall(_timeline_block(numbered_html))
        # Row 1 folded an exchange in, but it is still a score, so the word
        # stays 득점 — "교전" means non-scoring in this timeline.
        assert labels[0] == f"득점 #1 — {_AWAY_STEM} 0-1"
        assert labels[1] == f"득점 #2 — {_HOME_STEM} 1-1"

    def test_record_less_row_still_gets_a_numbered_label(self, numbered_html):
        labels = _CLIP_LABEL.findall(_timeline_block(numbered_html))
        assert labels[2] == f"득점 #3 — {_HOME_STEM} 2-1"

    def test_exchange_row_keeps_its_kind_and_ordinal(self, numbered_html):
        labels = _CLIP_LABEL.findall(_timeline_block(numbered_html))
        assert labels[3] == "교전 #4 — 상호 후퇴"

    def test_label_number_matches_the_chip_on_the_same_row(self, numbered_html):
        block = _timeline_block(numbered_html)
        # Both come from ``display_index``. If they ever diverge, the loop chip
        # and the AI-clip title name a different row than the one the coach is
        # looking at, which is worse than having no number at all.
        labelled = re.findall(r'data-clip-label="[^"#]*#(\d+)', block)
        assert labelled == _NUM_CHIP.findall(block)
