"""
Report generator: converts EnrichedMatchEvent list into a structured MatchReport.

Computes per-fencer statistics, detects patterns, and generates
coaching insights from raw analysis output.
"""

import math
from collections import Counter
from typing import List, Optional

from analyzer.models import EnrichedMatchEvent, FencingAction
from analyzer.report_models import (
    MatchReport,
    MatchSummary,
    TouchDetail,
    FencerStats,
    ActionDistribution,
    CoachingInsight,
    ReportMeta,
)
from analyzer.config import ACTION_CONFIDENCE_THRESHOLD, ACTION_LABEL_MAP_KR


# Thresholds for coaching insight generation
_DOMINANT_ACTION_PCT = 40.0   # Warn if one action > 40%
_LOW_SUCCESS_PCT = 30.0       # Flag success rate below 30%
_MIN_TOUCHES_FOR_INSIGHT = 3  # Need at least 3 touches for pattern analysis


class ReportGenerator:
    """
    Generates a MatchReport from a list of EnrichedMatchEvent.

    Usage:
        gen = ReportGenerator()
        report = gen.generate(events, video_path="match.mp4", weapon="epee")
    """

    def generate(
        self,
        events: List[EnrichedMatchEvent],
        video_path: str = "",
        weapon: Optional[str] = None,
        source_type: Optional[str] = None,
    ) -> MatchReport:
        """
        Generate a complete match report from enriched events.

        Args:
            events: List of EnrichedMatchEvent from IntegratedAnalyzer.
            video_path: Source video path.
            weapon: Weapon type (foil/epee/sabre) or None.
            source_type: Video source type for insight customization.

        Returns:
            MatchReport with summary, touches, stats, and insights.
        """
        if not events:
            return MatchReport(
                summary=MatchSummary(video_path=video_path, weapon=weapon),
            )

        # Infer weapon from events if not provided
        if weapon is None:
            for e in events:
                if e.weapon is not None:
                    weapon = e.weapon.value
                    break

        touches = self._build_touches(events)
        summary = self._build_summary(events, touches, video_path, weapon)
        left_stats = self._compute_fencer_stats(events, touches, "left")
        right_stats = self._compute_fencer_stats(events, touches, "right")
        insights = self._generate_insights(
            left_stats, right_stats, touches, weapon,
        )

        meta = ReportMeta(
            action_model=(
                "videomae-fencing-finetuned"
                if any(
                    e.action_left and e.action_left.action != FencingAction.UNKNOWN
                    for e in events
                )
                else "videomae-kinetics400"
            ),
            source_type=source_type,
        )

        return MatchReport(
            summary=summary,
            touches=touches,
            left_fencer=left_stats,
            right_fencer=right_stats,
            insights=insights,
            meta=meta,
        )

    def _build_touches(
        self, events: List[EnrichedMatchEvent],
    ) -> List[TouchDetail]:
        """Convert events to ordered TouchDetail list."""
        touches: List[TouchDetail] = []
        for i, e in enumerate(events):
            scorer_action = None
            scorer_conf = 0.0
            opponent_action = None
            opponent_conf = 0.0

            if e.scorer == "left" and e.action_left:
                scorer_action = e.action_left.action.value
                scorer_conf = e.action_left.confidence
                if e.action_right:
                    opponent_action = e.action_right.action.value
                    opponent_conf = e.action_right.confidence
            elif e.scorer == "right" and e.action_right:
                scorer_action = e.action_right.action.value
                scorer_conf = e.action_right.confidence
                if e.action_left:
                    opponent_action = e.action_left.action.value
                    opponent_conf = e.action_left.confidence

            touches.append(TouchDetail(
                touch_number=i + 1,
                frame=e.frame,
                video_timestamp=e.video_timestamp,
                match_time=e.match_time,
                scorer=e.scorer,
                score_after=e.score_after,
                action_scorer=scorer_action,
                action_confidence=scorer_conf,
                action_opponent=opponent_action,
                opponent_confidence=opponent_conf,
                description=e.description,
            ))
        return touches

    @staticmethod
    def _build_summary(
        events: List[EnrichedMatchEvent],
        touches: List[TouchDetail],
        video_path: str,
        weapon: Optional[str],
    ) -> MatchSummary:
        """Build match summary from events."""
        final_score = events[-1].score_after if events else "0-0"
        parts = final_score.split("-")
        left_score = int(parts[0]) if len(parts) == 2 and parts[0].isdigit() else 0
        right_score = int(parts[1]) if len(parts) == 2 and parts[1].isdigit() else 0

        match_duration = events[-1].match_time if events else ""

        return MatchSummary(
            video_path=video_path,
            weapon=weapon,
            final_score_left=left_score,
            final_score_right=right_score,
            total_touches=len(touches),
            match_duration=match_duration,
        )

    def _compute_fencer_stats(
        self,
        events: List[EnrichedMatchEvent],
        touches: List[TouchDetail],
        side: str,
    ) -> FencerStats:
        """Compute statistics for one fencer."""
        scored = [t for t in touches if t.scorer == side]
        conceded = [t for t in touches if t.scorer and t.scorer != side]

        stats = FencerStats(
            side=side,
            total_touches_scored=len(scored),
            total_touches_conceded=len(conceded),
        )

        # Action distribution (from scoring touches)
        action_counter: Counter = Counter()
        for t in scored:
            action = t.action_scorer or "unknown"
            action_counter[action] += 1

        total_actions = sum(action_counter.values())
        if total_actions > 0:
            stats.action_distribution = [
                ActionDistribution(
                    action=action,
                    count=count,
                    percentage=round(count / total_actions * 100, 1),
                )
                for action, count in action_counter.most_common()
            ]
            most_common = action_counter.most_common(1)[0]
            stats.most_common_action = most_common[0]
            stats.most_common_action_pct = round(
                most_common[1] / total_actions * 100, 1,
            )

        # Distance at touch (from pose data)
        distances = self._compute_distances_at_touch(events, side)
        if distances:
            stats.avg_distance_at_touch = round(
                sum(distances) / len(distances), 1,
            )

        return stats

    @staticmethod
    def _compute_distances_at_touch(
        events: List[EnrichedMatchEvent],
        side: str,
    ) -> List[float]:
        """Compute fencer distance (pixels) at each touch where both poses exist."""
        distances: List[float] = []
        for e in events:
            if e.scorer != side:
                continue
            if e.pose_left is None or e.pose_right is None:
                continue
            # Distance = euclidean between bbox centers
            lx = (e.pose_left.bbox[0] + e.pose_left.bbox[2]) / 2
            ly = (e.pose_left.bbox[1] + e.pose_left.bbox[3]) / 2
            rx = (e.pose_right.bbox[0] + e.pose_right.bbox[2]) / 2
            ry = (e.pose_right.bbox[1] + e.pose_right.bbox[3]) / 2
            dist = math.sqrt((lx - rx) ** 2 + (ly - ry) ** 2)
            distances.append(dist)
        return distances

    def _generate_insights(
        self,
        left: FencerStats,
        right: FencerStats,
        touches: List[TouchDetail],
        weapon: Optional[str],
    ) -> List[CoachingInsight]:
        """Auto-generate coaching insights from detected patterns."""
        insights: List[CoachingInsight] = []

        for stats in [left, right]:
            if stats.total_touches_scored < _MIN_TOUCHES_FOR_INSIGHT:
                continue

            # Dominant action pattern
            if (
                stats.most_common_action
                and stats.most_common_action != "unknown"
                and stats.most_common_action_pct >= _DOMINANT_ACTION_PCT
            ):
                action_kr = ACTION_LABEL_MAP_KR.get(
                    stats.most_common_action, stats.most_common_action,
                )
                insights.append(CoachingInsight(
                    category="action_pattern",
                    target=stats.side,
                    message=(
                        f"{stats.side.capitalize()} 선수: "
                        f"{action_kr}({stats.most_common_action}) 비율 "
                        f"{stats.most_common_action_pct}% — "
                        f"상대에게 예측 가능한 패턴, 동작 혼합 권장"
                    ),
                    severity="warning",
                    evidence=(
                        f"{stats.total_touches_scored}회 득점 중 "
                        f"{stats.most_common_action} "
                        f"{stats.most_common_action_pct}%"
                    ),
                ))

            # Low action variety (only 1-2 types used)
            non_unknown = [
                a for a in stats.action_distribution if a.action != "unknown"
            ]
            if (
                len(non_unknown) <= 2
                and stats.total_touches_scored >= _MIN_TOUCHES_FOR_INSIGHT
                and non_unknown
            ):
                actions_str = ", ".join(a.action for a in non_unknown)
                insights.append(CoachingInsight(
                    category="action_pattern",
                    target=stats.side,
                    message=(
                        f"{stats.side.capitalize()} 선수: "
                        f"사용 동작이 {actions_str}로 제한적 — "
                        f"다양한 동작 연습 필요"
                    ),
                    severity="suggestion",
                    evidence=f"감지된 동작 유형: {len(non_unknown)}개",
                ))

        # Scoring imbalance
        total = left.total_touches_scored + right.total_touches_scored
        if total >= _MIN_TOUCHES_FOR_INSIGHT:
            if left.total_touches_scored > 0 and right.total_touches_scored > 0:
                ratio = max(
                    left.total_touches_scored, right.total_touches_scored,
                ) / min(
                    left.total_touches_scored, right.total_touches_scored,
                )
                if ratio >= 2.0:
                    dominant = (
                        "left" if left.total_touches_scored > right.total_touches_scored
                        else "right"
                    )
                    insights.append(CoachingInsight(
                        category="tempo",
                        target=dominant,
                        message=(
                            f"{dominant.capitalize()} 선수가 "
                            f"득점을 {ratio:.1f}배 더 많이 기록 — "
                            f"상대 선수의 수비 전략 점검 필요"
                        ),
                        severity="info",
                        evidence=(
                            f"Left {left.total_touches_scored} vs "
                            f"Right {right.total_touches_scored}"
                        ),
                    ))

        return insights
