"""
FencerProfile builder — aggregates bout/continuous analysis results
into a comprehensive fencer profile for consulting services.

Collects data across multiple bouts to compute:
- Distance zone success rates
- Footwork pattern distribution
- Parry effectiveness
- Joint angle averages
- Strengths, weaknesses, and recommendations
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from analyzer.models import (
    PoseAnalysisResult,
    ContinuousAnalysisResult,
    DistanceZone,
    FootworkType,
    JointAngles,
    NonScoringEventType,
)


@dataclass
class DistanceStats:
    """Distance zone statistics across bouts."""
    zone_distribution: Dict[str, int] = field(default_factory=dict)
    zone_success_rate: Dict[str, float] = field(default_factory=dict)
    preferred_zone: str = ""
    avg_closing_speed: float = 0.0

    def to_dict(self) -> dict:
        return {
            "zone_distribution": self.zone_distribution,
            "zone_success_rate": {
                k: round(v, 3) for k, v in self.zone_success_rate.items()
            },
            "preferred_zone": self.preferred_zone,
            "avg_closing_speed": round(self.avg_closing_speed, 3),
        }


@dataclass
class FootworkStats:
    """Footwork pattern statistics across bouts."""
    type_distribution: Dict[str, int] = field(default_factory=dict)
    type_success_rate: Dict[str, float] = field(default_factory=dict)
    preferred_footwork: str = ""

    def to_dict(self) -> dict:
        return {
            "type_distribution": self.type_distribution,
            "type_success_rate": {
                k: round(v, 3) for k, v in self.type_success_rate.items()
            },
            "preferred_footwork": self.preferred_footwork,
        }


@dataclass
class JointAngleStats:
    """Average joint angles across bouts."""
    avg_hip_angle: Optional[float] = None
    avg_front_knee: Optional[float] = None
    avg_rear_knee: Optional[float] = None
    avg_trunk_lean: Optional[float] = None
    avg_arm_extension: Optional[float] = None

    def to_dict(self) -> dict:
        d: dict = {}
        if self.avg_hip_angle is not None:
            d["avg_hip_angle"] = round(self.avg_hip_angle, 1)
        if self.avg_front_knee is not None:
            d["avg_front_knee"] = round(self.avg_front_knee, 1)
        if self.avg_rear_knee is not None:
            d["avg_rear_knee"] = round(self.avg_rear_knee, 1)
        if self.avg_trunk_lean is not None:
            d["avg_trunk_lean"] = round(self.avg_trunk_lean, 1)
        if self.avg_arm_extension is not None:
            d["avg_arm_extension"] = round(self.avg_arm_extension, 3)
        return d


@dataclass
class FencerProfile:
    """Comprehensive fencer profile aggregated from multiple bouts."""
    fencer_side: str
    total_bouts: int = 0
    total_touches: int = 0
    handedness: Optional[str] = None
    handedness_confidence: float = 0.0
    distance_stats: Optional[DistanceStats] = None
    footwork_stats: Optional[FootworkStats] = None
    parry_rate: float = 0.0
    parry_success_to_riposte: float = 0.0
    joint_angle_stats: Optional[JointAngleStats] = None
    weaknesses: List[str] = field(default_factory=list)
    strengths: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d: dict = {
            "fencer_side": self.fencer_side,
            "total_bouts": self.total_bouts,
            "total_touches": self.total_touches,
            "handedness": self.handedness,
            "handedness_confidence": round(self.handedness_confidence, 2),
            "parry_rate": round(self.parry_rate, 3),
            "parry_success_to_riposte": round(self.parry_success_to_riposte, 3),
            "weaknesses": self.weaknesses,
            "strengths": self.strengths,
            "recommendations": self.recommendations,
        }
        if self.distance_stats is not None:
            d["distance_stats"] = self.distance_stats.to_dict()
        if self.footwork_stats is not None:
            d["footwork_stats"] = self.footwork_stats.to_dict()
        if self.joint_angle_stats is not None:
            d["joint_angle_stats"] = self.joint_angle_stats.to_dict()
        return d


class FencerProfileBuilder:
    """
    Incrementally builds a FencerProfile from bout results.

    Usage:
        builder = FencerProfileBuilder("left")
        builder.add_bout(result1, scored=True)
        builder.add_bout(result2, scored=False)
        builder.add_continuous(continuous_result)
        profile = builder.build()
    """

    def __init__(self, fencer_side: str):
        self.fencer_side = fencer_side
        self._bout_count = 0
        self._touch_count = 0

        # Distance tracking
        self._zone_attempts: Dict[str, int] = {}
        self._zone_scores: Dict[str, int] = {}
        self._closing_speeds: List[float] = []

        # Footwork tracking
        self._fw_attempts: Dict[str, int] = {}
        self._fw_scores: Dict[str, int] = {}

        # Parry tracking
        self._parry_events: int = 0
        self._parry_to_riposte: int = 0

        # Joint angles
        self._hip_angles: List[float] = []
        self._front_knees: List[float] = []
        self._rear_knees: List[float] = []
        self._trunk_leans: List[float] = []
        self._arm_extensions: List[float] = []

        # Continuous analysis aggregation
        self._total_attacks_attempted: int = 0
        self._total_attacks_succeeded: int = 0
        self._total_defenses_attempted: int = 0
        self._total_defenses_succeeded: int = 0

    def add_bout(self, result: PoseAnalysisResult, scored: bool) -> None:
        """Add a single touch analysis result."""
        self._bout_count += 1
        if scored:
            self._touch_count += 1

        # Distance zone
        if result.distance_at_touch is not None:
            zone = result.distance_at_touch.distance_zone.value
            self._zone_attempts[zone] = self._zone_attempts.get(zone, 0) + 1
            if scored:
                self._zone_scores[zone] = self._zone_scores.get(zone, 0) + 1
            self._closing_speeds.append(result.distance_at_touch.closing_speed_bh)

        # Footwork
        fw = result.footwork_left if self.fencer_side == "left" else result.footwork_right
        if fw is not None:
            fw_type = fw.footwork_type.value
            self._fw_attempts[fw_type] = self._fw_attempts.get(fw_type, 0) + 1
            if scored:
                self._fw_scores[fw_type] = self._fw_scores.get(fw_type, 0) + 1

        # Parry (opponent's parry against us = our attack was parried)
        # Our parry (when we defend)
        my_parry = result.parry_left if self.fencer_side == "left" else result.parry_right
        if my_parry is not None and my_parry.parry_detected:
            self._parry_events += 1
            # If we scored after parrying = riposte success
            if scored and result.suggested_label and "riposte" in result.suggested_label:
                self._parry_to_riposte += 1

        # Joint angles
        ja = result.joint_angles_left if self.fencer_side == "left" else result.joint_angles_right
        if ja is not None:
            self._collect_joint_angles(ja)

    def add_continuous(self, result: ContinuousAnalysisResult) -> None:
        """Add continuous analysis result."""
        if result.my_fencer_summary is not None:
            s = result.my_fencer_summary
            self._total_attacks_attempted += s.attacks_attempted
            self._total_attacks_succeeded += s.attacks_succeeded
            self._total_defenses_attempted += s.defenses_attempted
            self._total_defenses_succeeded += s.defenses_succeeded

        # Collect joint angles from exchanges
        for ex in result.exchanges:
            ja = (
                ex.joint_angles_left
                if self.fencer_side == "left"
                else ex.joint_angles_right
            )
            if ja is not None:
                self._collect_joint_angles(ja)

    def _collect_joint_angles(self, ja: JointAngles) -> None:
        """Accumulate joint angle values for averaging."""
        if ja.hip_angle is not None:
            self._hip_angles.append(ja.hip_angle)
        if ja.front_knee_angle is not None:
            self._front_knees.append(ja.front_knee_angle)
        if ja.rear_knee_angle is not None:
            self._rear_knees.append(ja.rear_knee_angle)
        if ja.trunk_lean_deg is not None:
            self._trunk_leans.append(ja.trunk_lean_deg)
        if ja.arm_extension_ratio is not None:
            self._arm_extensions.append(ja.arm_extension_ratio)

    def build(self) -> FencerProfile:
        """Build the final FencerProfile with computed stats."""
        profile = FencerProfile(
            fencer_side=self.fencer_side,
            total_bouts=self._bout_count,
            total_touches=self._touch_count,
        )

        # Distance stats
        if self._zone_attempts:
            zone_success: Dict[str, float] = {}
            for zone, attempts in self._zone_attempts.items():
                scores = self._zone_scores.get(zone, 0)
                zone_success[zone] = scores / attempts if attempts > 0 else 0.0

            preferred = max(zone_success, key=zone_success.get) if zone_success else ""  # type: ignore[arg-type]
            avg_speed = (
                sum(self._closing_speeds) / len(self._closing_speeds)
                if self._closing_speeds else 0.0
            )

            profile.distance_stats = DistanceStats(
                zone_distribution=dict(self._zone_attempts),
                zone_success_rate=zone_success,
                preferred_zone=preferred,
                avg_closing_speed=avg_speed,
            )

        # Footwork stats
        if self._fw_attempts:
            fw_success: Dict[str, float] = {}
            for fw_type, attempts in self._fw_attempts.items():
                scores = self._fw_scores.get(fw_type, 0)
                fw_success[fw_type] = scores / attempts if attempts > 0 else 0.0

            preferred_fw = max(fw_success, key=fw_success.get) if fw_success else ""  # type: ignore[arg-type]

            profile.footwork_stats = FootworkStats(
                type_distribution=dict(self._fw_attempts),
                type_success_rate=fw_success,
                preferred_footwork=preferred_fw,
            )

        # Parry stats
        if self._parry_events > 0:
            profile.parry_rate = self._parry_events / max(self._bout_count, 1)
            profile.parry_success_to_riposte = (
                self._parry_to_riposte / self._parry_events
            )

        # Joint angle stats
        if any([self._hip_angles, self._front_knees, self._trunk_leans]):
            profile.joint_angle_stats = JointAngleStats(
                avg_hip_angle=_avg(self._hip_angles),
                avg_front_knee=_avg(self._front_knees),
                avg_rear_knee=_avg(self._rear_knees),
                avg_trunk_lean=_avg(self._trunk_leans),
                avg_arm_extension=_avg(self._arm_extensions),
            )

        # Auto-generate strengths, weaknesses, recommendations
        self._generate_insights(profile)

        return profile

    def _generate_insights(self, profile: FencerProfile) -> None:
        """Auto-generate strengths, weaknesses, and recommendations."""
        weaknesses: List[str] = []
        strengths: List[str] = []
        recommendations: List[str] = []

        # Distance analysis
        if profile.distance_stats:
            ds = profile.distance_stats
            for zone, rate in ds.zone_success_rate.items():
                if rate >= 0.6:
                    strengths.append(f"{zone} 거리에서 득점률 {rate:.0%}로 우수")
                elif rate <= 0.2 and ds.zone_distribution.get(zone, 0) >= 3:
                    weaknesses.append(f"{zone} 거리에서 득점률 {rate:.0%}로 낮음")

        # Footwork analysis
        if profile.footwork_stats:
            fs = profile.footwork_stats
            total_fw = sum(fs.type_distribution.values())
            for fw_type, count in fs.type_distribution.items():
                ratio = count / total_fw if total_fw > 0 else 0
                if ratio > 0.5:
                    weaknesses.append(
                        f"{fw_type} 비율 {ratio:.0%} — 패턴이 예측 가능할 수 있음"
                    )
                    recommendations.append(
                        f"다양한 풋워크 혼합 권장 ({fw_type} 의존도 낮추기)"
                    )

        # Parry
        if profile.parry_rate > 0.3:
            if profile.parry_success_to_riposte >= 0.5:
                strengths.append(
                    f"빠라드-리포스트 전환률 {profile.parry_success_to_riposte:.0%}로 우수"
                )
            elif profile.parry_success_to_riposte < 0.25:
                weaknesses.append(
                    f"빠라드 후 리포스트 전환률 {profile.parry_success_to_riposte:.0%}로 낮음"
                )
                recommendations.append("빠라드 후 즉각적인 리포스트 연습 필요")

        # Joint angles
        if profile.joint_angle_stats:
            jas = profile.joint_angle_stats
            if jas.avg_front_knee is not None and jas.avg_front_knee > 160:
                weaknesses.append("앞무릎 각도 평균이 높음 — 런지 깊이 부족 가능성")
                recommendations.append("런지 시 앞무릎 90-120도 유지 연습")
            if jas.avg_arm_extension is not None and jas.avg_arm_extension < 0.6:
                weaknesses.append("팔 신전 비율 낮음 — 공격 시 팔을 충분히 뻗지 않음")
                recommendations.append("공격 시 팔 완전 신전 후 런지 시작 연습")

        # Continuous analysis insights
        if self._total_attacks_attempted > 0:
            attack_rate = self._total_attacks_succeeded / self._total_attacks_attempted
            if attack_rate < 0.3:
                weaknesses.append(f"공격 성공률 {attack_rate:.0%}로 낮음")
                recommendations.append("거리 관리 개선 — 적절한 거리에서 공격 시작")
            elif attack_rate >= 0.5:
                strengths.append(f"공격 성공률 {attack_rate:.0%}로 높음")

        if self._total_defenses_attempted > 0:
            defense_rate = self._total_defenses_succeeded / self._total_defenses_attempted
            if defense_rate >= 0.5:
                strengths.append(f"방어 성공률 {defense_rate:.0%}로 우수")
            elif defense_rate < 0.2:
                weaknesses.append(f"방어 성공률 {defense_rate:.0%}로 낮음")
                recommendations.append("빠라드 타이밍 연습 필요")

        profile.weaknesses = weaknesses
        profile.strengths = strengths
        profile.recommendations = recommendations


def _avg(values: List[float]) -> Optional[float]:
    """Compute average or return None if empty."""
    if not values:
        return None
    return sum(values) / len(values)
