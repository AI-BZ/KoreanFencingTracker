"""
Tests for report data models and report generator.
"""

import pytest


# ------------------------------------------------------------------
# Import tests
# ------------------------------------------------------------------

def test_import_report_models():
    from analyzer.report_models import (
        MatchReport, MatchSummary, TouchDetail,
        FencerStats, ActionDistribution, CoachingInsight, ReportMeta,
    )
    assert MatchReport is not None
    assert MatchSummary is not None


def test_import_report_generator():
    from ml.report_generator import ReportGenerator
    assert ReportGenerator is not None


# ------------------------------------------------------------------
# MatchSummary tests
# ------------------------------------------------------------------

def test_match_summary_creation():
    from analyzer.report_models import MatchSummary
    s = MatchSummary(
        video_path="test.mp4",
        weapon="epee",
        final_score_left=5,
        final_score_right=3,
        total_touches=8,
        match_duration="3:00",
    )
    assert s.final_score_left == 5
    assert s.weapon == "epee"


def test_match_summary_to_dict():
    from analyzer.report_models import MatchSummary
    s = MatchSummary(video_path="test.mp4", weapon="foil")
    d = s.to_dict()
    assert "final_score" in d
    assert d["weapon"] == "foil"
    assert d["final_score"] == "0-0"


def test_match_summary_to_dict_no_weapon():
    from analyzer.report_models import MatchSummary
    s = MatchSummary(video_path="test.mp4")
    d = s.to_dict()
    assert "weapon" not in d


# ------------------------------------------------------------------
# FencerStats tests
# ------------------------------------------------------------------

def test_fencer_stats_empty():
    from analyzer.report_models import FencerStats
    s = FencerStats(side="left")
    assert s.total_touches_scored == 0
    assert s.action_distribution == []
    assert s.most_common_action is None


def test_fencer_stats_with_distribution():
    from analyzer.report_models import FencerStats, ActionDistribution
    s = FencerStats(
        side="left",
        total_touches_scored=5,
        action_distribution=[
            ActionDistribution(action="lunge", count=3, percentage=60.0),
            ActionDistribution(action="attack", count=2, percentage=40.0),
        ],
        most_common_action="lunge",
        most_common_action_pct=60.0,
    )
    d = s.to_dict()
    assert len(d["action_distribution"]) == 2
    assert d["action_distribution"][0]["action"] == "lunge"
    assert d["most_common_action_pct"] == 60.0


# ------------------------------------------------------------------
# CoachingInsight tests
# ------------------------------------------------------------------

def test_coaching_insight_to_dict():
    from analyzer.report_models import CoachingInsight
    insight = CoachingInsight(
        category="action_pattern",
        target="left",
        message="Left fencer relies on lunge",
        severity="warning",
        evidence="3/5 touches = lunge",
    )
    d = insight.to_dict()
    assert d["category"] == "action_pattern"
    assert d["severity"] == "warning"


# ------------------------------------------------------------------
# TouchDetail tests
# ------------------------------------------------------------------

def test_touch_detail_creation():
    from analyzer.report_models import TouchDetail
    t = TouchDetail(
        touch_number=1,
        frame=300,
        video_timestamp="0:10.00",
        match_time="2:50",
        scorer="left",
        score_after="1-0",
        action_scorer="lunge",
        action_confidence=0.87,
    )
    assert t.touch_number == 1
    assert t.action_scorer == "lunge"


# ------------------------------------------------------------------
# MatchReport tests
# ------------------------------------------------------------------

def test_match_report_empty():
    from analyzer.report_models import MatchReport, MatchSummary
    report = MatchReport(
        summary=MatchSummary(video_path="test.mp4"),
    )
    d = report.to_dict()
    assert "summary" in d
    assert "touches" in d
    assert d["touches"] == []
    assert "insights" not in d  # Empty insights omitted


def test_match_report_to_dict_full():
    from analyzer.report_models import (
        MatchReport, MatchSummary, TouchDetail, FencerStats,
        CoachingInsight, ReportMeta,
    )
    report = MatchReport(
        summary=MatchSummary(video_path="test.mp4", weapon="sabre"),
        touches=[
            TouchDetail(
                touch_number=1, frame=100, video_timestamp="0:03.33",
                match_time="3:00", scorer="left", score_after="1-0",
                action_scorer="attack", action_confidence=0.9,
            ),
        ],
        left_fencer=FencerStats(side="left", total_touches_scored=1),
        right_fencer=FencerStats(side="right", total_touches_conceded=1),
        insights=[
            CoachingInsight(
                category="tempo", target="left",
                message="Dominant scorer", severity="info",
                evidence="1-0",
            ),
        ],
        meta=ReportMeta(action_model="videomae-fencing-finetuned"),
    )
    d = report.to_dict()
    assert d["summary"]["weapon"] == "sabre"
    assert len(d["touches"]) == 1
    assert d["left_fencer"]["total_touches_scored"] == 1
    assert len(d["insights"]) == 1
    assert d["meta"]["action_model"] == "videomae-fencing-finetuned"


# ------------------------------------------------------------------
# ReportGenerator tests
# ------------------------------------------------------------------

def test_report_generator_empty_events():
    from ml.report_generator import ReportGenerator
    gen = ReportGenerator()
    report = gen.generate([], video_path="test.mp4")
    assert report.summary.total_touches == 0
    assert report.touches == []


def test_report_generator_single_event():
    from ml.report_generator import ReportGenerator
    from analyzer.models import (
        EnrichedMatchEvent, FencingAction, ActionPrediction,
    )
    event = EnrichedMatchEvent(
        frame=100,
        video_timestamp="0:03.33",
        match_time="3:00",
        event_type="left_lamp",
        lamp_red=True,
        lamp_green=False,
        score_before="0-0",
        score_after="1-0",
        scorer="left",
        description="Left scored",
        action_left=ActionPrediction(action=FencingAction.LUNGE, confidence=0.85),
    )
    gen = ReportGenerator()
    report = gen.generate([event], video_path="test.mp4", weapon="epee")

    assert report.summary.final_score_left == 1
    assert report.summary.final_score_right == 0
    assert report.summary.weapon == "epee"
    assert len(report.touches) == 1
    assert report.touches[0].action_scorer == "lunge"
    assert report.left_fencer.total_touches_scored == 1
    assert report.right_fencer.total_touches_conceded == 1


def test_report_generator_multiple_events():
    from ml.report_generator import ReportGenerator
    from analyzer.models import (
        EnrichedMatchEvent, FencingAction, ActionPrediction,
    )
    events = [
        EnrichedMatchEvent(
            frame=100, video_timestamp="0:03.33", match_time="3:00",
            event_type="left_lamp", lamp_red=True, lamp_green=False,
            score_before="0-0", score_after="1-0", scorer="left",
            description="Touch 1",
            action_left=ActionPrediction(action=FencingAction.LUNGE, confidence=0.8),
        ),
        EnrichedMatchEvent(
            frame=300, video_timestamp="0:10.00", match_time="2:30",
            event_type="right_lamp", lamp_red=False, lamp_green=True,
            score_before="1-0", score_after="1-1", scorer="right",
            description="Touch 2",
            action_right=ActionPrediction(action=FencingAction.RIPOSTE, confidence=0.75),
        ),
        EnrichedMatchEvent(
            frame=500, video_timestamp="0:16.67", match_time="2:00",
            event_type="left_lamp", lamp_red=True, lamp_green=False,
            score_before="1-1", score_after="2-1", scorer="left",
            description="Touch 3",
            action_left=ActionPrediction(action=FencingAction.LUNGE, confidence=0.9),
        ),
    ]
    gen = ReportGenerator()
    report = gen.generate(events)

    assert report.summary.final_score_left == 2
    assert report.summary.final_score_right == 1
    assert report.summary.total_touches == 3
    assert report.left_fencer.total_touches_scored == 2
    assert report.right_fencer.total_touches_scored == 1


def test_report_generator_insights_dominant_action():
    """Insights should flag dominant action patterns."""
    from ml.report_generator import ReportGenerator
    from analyzer.models import (
        EnrichedMatchEvent, FencingAction, ActionPrediction,
    )
    # 4 touches all by left, all lunge → should trigger dominant action insight
    events = []
    for i in range(4):
        events.append(EnrichedMatchEvent(
            frame=100 * (i + 1),
            video_timestamp=f"0:{3*(i+1):02d}.00",
            match_time=f"2:{60-15*i:02d}",
            event_type="left_lamp",
            lamp_red=True, lamp_green=False,
            score_before=f"{i}-0", score_after=f"{i+1}-0",
            scorer="left", description=f"Touch {i+1}",
            action_left=ActionPrediction(
                action=FencingAction.LUNGE, confidence=0.85,
            ),
        ))

    gen = ReportGenerator()
    report = gen.generate(events)

    assert len(report.insights) > 0
    action_insights = [
        i for i in report.insights if i.category == "action_pattern"
    ]
    assert len(action_insights) > 0
    assert "lunge" in action_insights[0].evidence.lower() or \
           "런지" in action_insights[0].message


def test_report_generator_weapon_inference():
    """Weapon should be inferred from events if not provided."""
    from ml.report_generator import ReportGenerator
    from analyzer.models import EnrichedMatchEvent, Weapon

    event = EnrichedMatchEvent(
        frame=100, video_timestamp="0:03.33", match_time="3:00",
        event_type="left_lamp", lamp_red=True, lamp_green=False,
        score_before="0-0", score_after="1-0", scorer="left",
        description="Touch", weapon=Weapon.SABRE,
    )
    gen = ReportGenerator()
    report = gen.generate([event])
    assert report.summary.weapon == "sabre"


# ------------------------------------------------------------------
# ReportMeta tests
# ------------------------------------------------------------------

def test_report_meta_defaults():
    from analyzer.report_models import ReportMeta
    m = ReportMeta()
    d = m.to_dict()
    assert d["phase"] == 2
    assert d["pose_model"] == "yolo11n-pose"
    assert d["action_model"] == "videomae-kinetics400"
