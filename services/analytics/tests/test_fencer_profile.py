"""
Tests for ml/fencer_profile.py — FencerProfileBuilder.

6 tests covering:
- builder_basic, distance_stats_aggregation, weakness_detection,
  serialization, parry_tracking, joint_angle_aggregation
"""

import pytest

from analyzer.models import (
    PoseAnalysisResult,
    FootworkResult, FootworkType,
    ParryResult,
    DistanceResult, DistanceZone,
    JointAngles,
    ContinuousAnalysisResult, MyFencerSummary, ExchangeEvent,
    NonScoringEventType,
)
from ml.fencer_profile import FencerProfileBuilder, FencerProfile


def _make_result(
    distance_bh: float = 1.3,
    zone: DistanceZone = DistanceZone.LUNGE,
    fw_type: FootworkType = FootworkType.LUNGE,
    parry: bool = False,
    label: str = "attack_left",
    closing_speed: float = 0.5,
    hip_angle: float = 120.0,
    front_knee: float = 110.0,
    arm_ext: float = 0.85,
) -> PoseAnalysisResult:
    """Create a PoseAnalysisResult for testing."""
    return PoseAnalysisResult(
        footwork_left=FootworkResult(
            footwork_type=fw_type, confidence=0.8,
            hip_drop_px=5.0, front_foot_displacement_px=40.0,
            rear_foot_displacement_px=5.0,
        ),
        footwork_right=FootworkResult(
            footwork_type=FootworkType.STATIONARY, confidence=0.9,
        ),
        parry_left=ParryResult(
            parry_detected=parry, confidence=0.7 if parry else 0.1,
            wrist_lateral_displacement_px=30.0 if parry else 5.0,
        ),
        parry_right=ParryResult(parry_detected=False, confidence=0.1),
        distance_at_touch=DistanceResult(
            distance_bh=distance_bh,
            distance_zone=zone,
            closing_speed_bh=closing_speed,
        ),
        suggested_label=label,
        suggestion_confidence=0.7,
        joint_angles_left=JointAngles(
            hip_angle=hip_angle,
            front_knee_angle=front_knee,
            rear_knee_angle=150.0,
            trunk_lean_deg=10.0,
            arm_extension_ratio=arm_ext,
        ),
        joint_angles_right=None,
    )


class TestFencerProfileBuilder:

    def test_builder_basic(self):
        """Builder produces a valid FencerProfile."""
        builder = FencerProfileBuilder("left")
        builder.add_bout(_make_result(), scored=True)
        builder.add_bout(_make_result(), scored=False)
        profile = builder.build()

        assert isinstance(profile, FencerProfile)
        assert profile.fencer_side == "left"
        assert profile.total_bouts == 2
        assert profile.total_touches == 1

    def test_distance_stats_aggregation(self):
        """Distance stats are correctly aggregated across bouts."""
        builder = FencerProfileBuilder("left")
        # 3 bouts in lunge zone: 2 scored, 1 not
        builder.add_bout(
            _make_result(distance_bh=1.3, zone=DistanceZone.LUNGE),
            scored=True,
        )
        builder.add_bout(
            _make_result(distance_bh=1.4, zone=DistanceZone.LUNGE),
            scored=True,
        )
        builder.add_bout(
            _make_result(distance_bh=1.35, zone=DistanceZone.LUNGE),
            scored=False,
        )
        # 1 bout in extension zone
        builder.add_bout(
            _make_result(distance_bh=1.0, zone=DistanceZone.EXTENSION),
            scored=False,
        )

        profile = builder.build()
        assert profile.distance_stats is not None
        assert profile.distance_stats.zone_distribution["lunge"] == 3
        assert profile.distance_stats.zone_distribution["extension"] == 1
        assert profile.distance_stats.zone_success_rate["lunge"] == pytest.approx(2 / 3, abs=0.01)
        assert profile.distance_stats.zone_success_rate["extension"] == 0.0

    def test_weakness_detection(self):
        """Builder generates weaknesses for dominant footwork pattern."""
        builder = FencerProfileBuilder("left")
        # 5 bouts all using lunge → > 50% should trigger weakness
        for _ in range(5):
            builder.add_bout(
                _make_result(fw_type=FootworkType.LUNGE),
                scored=True,
            )
        profile = builder.build()
        # Should have weakness about lunge dominance
        has_fw_weakness = any("비율" in w for w in profile.weaknesses)
        assert has_fw_weakness, f"Expected footwork weakness, got: {profile.weaknesses}"

    def test_serialization(self):
        """FencerProfile.to_dict() produces valid dict."""
        builder = FencerProfileBuilder("left")
        builder.add_bout(_make_result(), scored=True)
        profile = builder.build()
        d = profile.to_dict()

        assert isinstance(d, dict)
        assert d["fencer_side"] == "left"
        assert d["total_bouts"] == 1
        assert "distance_stats" in d
        assert "footwork_stats" in d
        assert isinstance(d["weaknesses"], list)

    def test_parry_tracking(self):
        """Parry events and riposte conversion are tracked."""
        builder = FencerProfileBuilder("left")
        # Bout with parry + riposte label
        builder.add_bout(
            _make_result(parry=True, label="riposte_left"),
            scored=True,
        )
        # Bout with parry but no riposte
        builder.add_bout(
            _make_result(parry=True, label="attack_left"),
            scored=False,
        )
        # Bout without parry
        builder.add_bout(
            _make_result(parry=False, label="attack_left"),
            scored=True,
        )

        profile = builder.build()
        assert profile.parry_rate == pytest.approx(2 / 3, abs=0.01)
        assert profile.parry_success_to_riposte == pytest.approx(0.5, abs=0.01)

    def test_joint_angle_aggregation(self):
        """Joint angles are averaged across bouts."""
        builder = FencerProfileBuilder("left")
        builder.add_bout(
            _make_result(hip_angle=120.0, front_knee=100.0, arm_ext=0.8),
            scored=True,
        )
        builder.add_bout(
            _make_result(hip_angle=140.0, front_knee=120.0, arm_ext=0.9),
            scored=True,
        )

        profile = builder.build()
        assert profile.joint_angle_stats is not None
        assert profile.joint_angle_stats.avg_hip_angle == pytest.approx(130.0, abs=0.1)
        assert profile.joint_angle_stats.avg_front_knee == pytest.approx(110.0, abs=0.1)
        assert profile.joint_angle_stats.avg_arm_extension == pytest.approx(0.85, abs=0.01)
