"""Unit tests for foil priority estimation and its cascade integration.

Every threshold used here is passed explicitly to the judge rather than read from
``analyzer.config``. The shipped constants are a calibration result and may be
retuned — or set to disable the feature — without any of these tests silently
changing what they assert.
"""

import copy

import pytest

from analyzer.models import FencerPose, PoseKeypoint, PoseResult
from analyzer.touch_matching import (
    ATTACK_OUTCOME_KO,
    CONFIDENCE_ESTIMATED,
    CONFIDENCE_HIGH,
    METHOD_FOOTWORK,
    NO_PRIORITY_CALL,
    annotate_touch_lamp,
    annotate_touch_outcome,
    determine_attacker,
    resolve_attacker,
)
from analyzer.tv_overlay_ocr import LampReading, LampSideReading
from app.report_renderer import (
    ESTIMATED_BADGE_KO,
    OUTCOME_REASON_PRIORITY_SIMULTANE,
    annotate_estimated_badges,
    annotate_outcome_reasons,
)
from ml.pose_analysis.kinematics import compute_forward_arm_extension
from ml.pose_analyzer import PoseAnalyzer
from ml.weapon_analyzers.foil import (
    METHOD_ARM_EXTENSION,
    REASON_ESTIMATED,
    REASON_LOW_QUALITY,
    REASON_NO_COMMIT,
    REASON_NO_SERIES,
    REASON_SIMULTANEOUS,
    FoilPriorityJudge,
    _median_smooth,
    build_priority_judge,
    compute_session_baselines,
)
from scripts.generate_continuous_report import validate_priority_series_frames

# COCO indices used below: 5/6 shoulders, 7/8 elbows, 9/10 wrists, 11/12 hips,
# 13/14 knees, 15/16 ankles.
_L_SH, _R_SH, _L_EL, _R_EL, _L_WR, _R_WR = 5, 6, 7, 8, 9, 10


def _kp(x, y, conf=0.9):
    return PoseKeypoint(x=x, y=y, confidence=conf)


def _fencer(side, *, cx=100.0, arms=None):
    """A fencer whose two arms can be posed independently.

    ``arms`` maps ``"left"``/``"right"`` (anatomical) to ``(wrist_x, straight)``.
    A straight arm puts shoulder, elbow and wrist on one line (ratio → 1.0); a
    bent one folds the wrist back up beside the shoulder (ratio → small).
    """
    kps = [_kp(cx, 10.0) for _ in range(17)]
    kps[_L_SH], kps[_R_SH] = _kp(cx - 5, 50.0), _kp(cx + 5, 50.0)
    kps[11], kps[12] = _kp(cx - 5, 100.0), _kp(cx + 5, 100.0)
    kps[13], kps[14] = _kp(cx - 5, 140.0), _kp(cx + 5, 140.0)
    kps[15], kps[16] = _kp(cx - 5, 180.0), _kp(cx + 5, 180.0)

    for anat, (sh_i, el_i, wr_i) in (
        ("left", (_L_SH, _L_EL, _L_WR)),
        ("right", (_R_SH, _R_EL, _R_WR)),
    ):
        spec = (arms or {}).get(anat)
        if spec is None:
            continue
        wrist_x, straight = spec
        sh_x = kps[sh_i].x
        mid_x = (sh_x + wrist_x) / 2
        kps[el_i] = _kp(mid_x, 50.0)
        # Straight: wrist continues along the shoulder-elbow line (ratio → 1.0).
        # Bent: wrist folds up perpendicular to the upper arm (ratio → 0.5),
        # which also pulls it back to the elbow's x — the rear arm's posture.
        kps[wr_i] = _kp(wrist_x, 50.0) if straight else _kp(mid_x, -10.0)

    return FencerPose(
        keypoints=kps, bbox=[cx - 20, 0, cx + 20, 190],
        person_confidence=0.9, side=side,
    )


def _series(frames, values):
    return [[f, v] for f, v in zip(frames, values)]


def _exchange(
    frames,
    arm_left,
    arm_right,
    hip_left,
    hip_right,
    *,
    number=1,
    start=None,
    footwork=("unknown", "unknown"),
):
    return {
        "exchange_number": number,
        "start_frame": frames[0] if start is None else start,
        "end_frame": frames[-1],
        "min_distance_frame": frames[-1],
        "footwork_left": footwork[0],
        "footwork_right": footwork[1],
        "arm_series_left": _series(frames, arm_left),
        "arm_series_right": _series(frames, arm_right),
        "hip_x_series_left": _series(frames, hip_left),
        "hip_x_series_right": _series(frames, hip_right),
    }


def _judge(**kw):
    """Judge with permissive, explicit thresholds unless a test overrides them."""
    params = dict(
        baselines={"left": 0.5, "right": 0.5},
        fps=30.0,
        normalise=False,
        decision_window_sec=1.5,
        # The synthetic series below end exactly at the anchor, so nothing is
        # trimmed here. The shipped offset is exercised by its own test.
        decision_end_offset_sec=0.0,
        smooth_window=3,
        clear_margin=0.15,
        min_commit=0.10,
        min_quality=0.6,
        stationary_weight=0.0,
        fwd_min_vx_bh=0.01,
    )
    params.update(kw)
    return FoilPriorityJudge(**params)


# A left fencer driving forward with an extending arm against a retreating,
# passive right fencer. 46 samples at stride 3 spans ~1.5s at 30fps.
_FRAMES = list(range(0, 46 * 3, 3))
_ATTACK_LEFT = dict(
    frames=_FRAMES,
    arm_left=[0.5 + 0.45 * i / 45 for i in range(46)],
    arm_right=[0.5] * 46,
    hip_left=[1.0 + 0.05 * i for i in range(46)],
    hip_right=[4.0 + 0.05 * i for i in range(46)],
)


# Nobody moving: arms at guard, both fencers planted.
_FLAT = dict(
    frames=_FRAMES,
    arm_left=[0.5] * 46, arm_right=[0.5] * 46,
    hip_left=[1.0] * 46, hip_right=[4.0] * 46,
)


def _mirror(exchange):
    """Swap the two fencers and flip the x axis.

    A correct judge must be blind to which side of the piste a fencer stands on,
    so mirroring the whole exchange has to mirror the verdict. Hip positions are
    reflected because "forward" is +x for the left fencer and −x for the right;
    without the reflection the mirrored fencer would read as retreating.
    """
    out = dict(exchange)
    for kind in ("arm_series", "hip_x_series"):
        left = exchange[f"{kind}_left"]
        right = exchange[f"{kind}_right"]
        if kind == "hip_x_series":
            left = [[f, None if v is None else 10.0 - v] for f, v in left]
            right = [[f, None if v is None else 10.0 - v] for f, v in right]
        out[f"{kind}_left"], out[f"{kind}_right"] = right, left
    out["footwork_left"] = exchange["footwork_right"]
    out["footwork_right"] = exchange["footwork_left"]
    return out


class TestForwardArmExtension:
    """The weapon arm is picked by reach, not by an assumption about handedness."""

    def test_picks_the_arm_reaching_toward_the_opponent(self):
        # Left fencer faces right: the arm with the larger wrist x is forward.
        fencer = _fencer("left", cx=100.0, arms={
            "left": (200.0, True),    # forward, straight
            "right": (40.0, False),   # trailing, bent
        })
        assert compute_forward_arm_extension(fencer, "left") == pytest.approx(1.0, abs=0.01)

    def test_forward_is_the_other_direction_for_the_right_fencer(self):
        # Same anatomy, but a right-of-frame fencer faces left, so the forward
        # arm is the one with the *smaller* wrist x — here the bent one.
        fencer = _fencer("right", cx=100.0, arms={
            "left": (200.0, True),
            "right": (40.0, False),
        })
        assert compute_forward_arm_extension(fencer, "right") < 0.7

    def test_handedness_does_not_matter(self):
        """A left-hander reads the same as a right-hander with the same reach.

        This is the whole point of selecting by reach: on the reference bout
        handedness detection returned None at confidence 0.03, so anything that
        depended on it would have had nothing to depend on.
        """
        righty = _fencer("left", arms={"left": (40.0, False), "right": (200.0, True)})
        lefty = _fencer("left", arms={"left": (200.0, True), "right": (40.0, False)})
        assert compute_forward_arm_extension(righty, "left") == pytest.approx(
            compute_forward_arm_extension(lefty, "left"), abs=0.01,
        )

    def test_falls_back_to_the_only_confident_arm(self):
        fencer = _fencer("left", arms={"left": (200.0, True)})
        for idx in (_R_SH, _R_EL, _R_WR):
            fencer.keypoints[idx] = _kp(0.0, 0.0, conf=0.01)
        assert compute_forward_arm_extension(fencer, "left") == pytest.approx(1.0, abs=0.01)

    def test_none_when_neither_arm_is_confident(self):
        fencer = _fencer("left")
        for idx in (_L_SH, _L_EL, _L_WR, _R_SH, _R_EL, _R_WR):
            fencer.keypoints[idx] = _kp(0.0, 0.0, conf=0.01)
        assert compute_forward_arm_extension(fencer, "left") is None


class TestMedianSmooth:
    def test_bridges_an_isolated_gap(self):
        assert _median_smooth([0.4, None, 0.4], 3) == [0.4, 0.4, 0.4]

    def test_keeps_a_total_blackout_as_a_gap(self):
        assert _median_smooth([None, None, None], 3) == [None, None, None]

    def test_rejects_a_single_sample_spike(self):
        """Occlusion produces 0.9→0.1→0.9; a mean would keep the dip."""
        out = _median_smooth([0.9, 0.1, 0.9], 3)
        assert out[1] == pytest.approx(0.9)


class TestSessionBaselines:
    def test_prefers_lead_in_samples_over_the_attack_itself(self):
        # Lead-in (frames < start) sits at 0.4; the approach climbs to 0.9. The
        # baseline is the guard, so it must read 0.4.
        frames = list(range(0, 60 * 3, 3))
        arm = [0.4] * 30 + [0.9] * 30
        ex = _exchange(frames, arm, arm, [1.0] * 60, [2.0] * 60, start=frames[30])
        base = compute_session_baselines([ex], min_samples=10)
        assert base["left"] == pytest.approx(0.4)

    def test_falls_back_to_all_samples_when_lead_in_is_too_thin(self):
        frames = list(range(0, 30 * 3, 3))
        arm = [0.8] * 30
        ex = _exchange(frames, arm, arm, [1.0] * 30, [2.0] * 30, start=frames[0])
        assert compute_session_baselines([ex], min_samples=10)["left"] == pytest.approx(0.8)

    def test_defaults_when_a_side_has_no_pose_at_all(self):
        ex = _exchange([0, 3], [None, None], [None, None], [None, None], [None, None])
        assert compute_session_baselines([ex], default=0.66)["left"] == pytest.approx(0.66)

    def test_clamps_so_normalisation_cannot_explode(self):
        """A baseline of ~1.0 would make (1 − baseline) vanish."""
        frames = list(range(0, 30 * 3, 3))
        ex = _exchange(frames, [1.0] * 30, [1.0] * 30, [1.0] * 30, [2.0] * 30)
        assert compute_session_baselines([ex], min_samples=1)["left"] <= 0.95


class TestJudgeGates:
    def test_calls_the_committed_side(self):
        call = _judge().judge(_exchange(**_ATTACK_LEFT))
        assert call.attacker == "left"
        assert call.reason == REASON_ESTIMATED
        assert call.detail["commit_left"] > call.detail["commit_right"]

    def test_declines_without_series(self):
        assert _judge().judge({"exchange_number": 1}).reason == REASON_NO_SERIES

    def test_declines_when_the_window_is_mostly_dropout(self):
        spec = copy.deepcopy(_ATTACK_LEFT)
        spec["arm_left"] = [None] * 40 + spec["arm_left"][40:]
        call = _judge().judge(_exchange(**spec))
        assert call.reason == REASON_LOW_QUALITY
        assert call.attacker is None

    def test_declines_when_neither_side_commits(self):
        """Both standing still at their guard: nothing to award priority to."""
        assert _judge().judge(_exchange(**_FLAT)).reason == REASON_NO_COMMIT

    def test_the_end_offset_trims_the_collision(self):
        """The last stretch before closest approach is excluded from the score.

        The right fencer here does nothing until the final half second, then
        lunges into the collision — the stretch where the two bodies overlap and
        the pose estimator starts attributing one fencer's keypoints to the
        other. Whatever is measured there describes the contact, not who
        initiated it, so it must not count toward commitment.
        """
        late_surge = dict(
            frames=_FRAMES,
            arm_left=[0.45] * 46,
            arm_right=[0.2] * 31 + [1.0] * 15,
            hip_left=[1.0 + 0.05 * i for i in range(46)],
            hip_right=[4.0] * 31 + [4.0 - 0.05 * i for i in range(15)],
        )
        exchange = _exchange(**late_surge)
        untrimmed = _judge(decision_end_offset_sec=0.0).judge(exchange).detail
        trimmed = _judge(decision_end_offset_sec=0.6).judge(exchange).detail
        assert trimmed["commit_right"] < untrimmed["commit_right"]
        assert trimmed["window_frames"][1] < untrimmed["window_frames"][1]

    def test_normalisation_is_off_by_default_and_can_be_switched_on(self):
        """The flag is a measurement result, so both branches stay exercised."""
        exchange = _exchange(**_ATTACK_LEFT)
        plain = _judge(normalise=False).judge(exchange)
        normalised = _judge(
            normalise=True, baselines={"left": 0.9, "right": 0.1},
        ).judge(exchange)
        # A high baseline suppresses that fencer's extension — the mechanism
        # measured to make the judge answer one side every time.
        assert plain.detail["commit_left"] > normalised.detail["commit_left"]

    def test_declines_when_both_commit_equally(self):
        """A simultaneous attack. The referee awards nothing here either."""
        both = dict(
            frames=_FRAMES,
            arm_left=[0.5 + 0.45 * i / 45 for i in range(46)],
            arm_right=[0.5 + 0.45 * i / 45 for i in range(46)],
            hip_left=[1.0 + 0.05 * i for i in range(46)],
            hip_right=[4.0 - 0.05 * i for i in range(46)],
        )
        call = _judge().judge(_exchange(**both))
        assert call.reason == REASON_SIMULTANEOUS
        assert call.attacker is None

    def test_retreating_extension_earns_nothing(self):
        """Counter-attack: the arm goes out while the feet give ground.

        FIE priority requires extending *and* advancing, so this must not
        outscore a passive opponent — it is the失 case the design named as the
        direct cause of a measured misread.
        """
        counter = dict(
            frames=_FRAMES,
            arm_left=[0.5] * 46,
            arm_right=[0.5 + 0.45 * i / 45 for i in range(46)],
            hip_left=[1.0] * 46,
            hip_right=[4.0 + 0.05 * i for i in range(46)],  # +x = retreating
        )
        call = _judge().judge(_exchange(**counter))
        assert call.detail["commit_right"] == pytest.approx(0.0)
        assert call.attacker != "right"

    def test_margin_boundary_is_the_only_thing_separating_call_from_decline(self):
        exchange = _exchange(**_ATTACK_LEFT)
        margin = _judge().judge(exchange).detail["margin"]
        assert _judge(clear_margin=margin - 0.01).judge(exchange).attacker == "left"
        assert _judge(clear_margin=margin + 0.01).judge(exchange).attacker is None


class TestMirrorSymmetry:
    """Which side of the piste a fencer stands on must not bias the verdict."""

    @pytest.mark.parametrize("spec,expected", [
        (_ATTACK_LEFT, "left"),
    ])
    def test_mirroring_the_exchange_mirrors_the_call(self, spec, expected):
        exchange = _exchange(**spec)
        judge = _judge()
        assert judge.judge(exchange).attacker == expected
        mirrored = _judge(baselines={"left": 0.5, "right": 0.5}).judge(_mirror(exchange))
        assert mirrored.attacker == ("right" if expected == "left" else "left")

    def test_mirroring_preserves_the_margin(self):
        exchange = _exchange(**_ATTACK_LEFT)
        judge = _judge()
        assert judge.judge(_mirror(exchange)).detail["margin"] == pytest.approx(
            judge.judge(exchange).detail["margin"],
        )


class TestBuildPriorityJudge:
    def test_no_judge_for_weapons_without_priority(self):
        exchanges = [_exchange(**_ATTACK_LEFT)]
        assert build_priority_judge("epee", exchanges) is None

    def test_no_judge_for_sabre_yet(self):
        """Sabre needs its own judge, not foil's thresholds."""
        assert build_priority_judge("sabre", [_exchange(**_ATTACK_LEFT)]) is None

    def test_no_judge_for_a_report_without_series(self):
        """Reports predating the arm series must keep their exact verdicts."""
        assert build_priority_judge("foil", [{"exchange_number": 1}]) is None

    def test_foil_with_series_gets_a_judge_when_enabled(self):
        judge = build_priority_judge(
            "foil", [_exchange(**_ATTACK_LEFT)], enabled=True,
        )
        assert judge is not None
        assert judge.method == METHOD_ARM_EXTENSION

    def test_the_master_switch_suppresses_the_judge_entirely(self):
        """Disabled means never consulted, so verdicts revert to footwork-only."""
        assert build_priority_judge(
            "foil", [_exchange(**_ATTACK_LEFT)], enabled=False,
        ) is None


class TestCascade:
    """Footwork outranks estimation, always."""

    def test_footwork_wins_and_the_judge_is_never_consulted(self):
        exchange = _exchange(**_ATTACK_LEFT, footwork=("retreat", "fleche"))

        class Exploding:
            method = METHOD_ARM_EXTENSION

            def judge(self, _exchange):
                raise AssertionError("judge ran on a footwork-determined exchange")

        resolution = resolve_attacker(exchange, judge=Exploding())
        assert resolution.side == "right"
        assert resolution.confidence == CONFIDENCE_HIGH
        assert resolution.method == METHOD_FOOTWORK

    def test_judge_fills_only_what_footwork_left_unclear(self):
        exchange = _exchange(**_ATTACK_LEFT, footwork=("advance", "advance"))
        assert determine_attacker(exchange) == "unclear"
        resolution = resolve_attacker(exchange, judge=_judge())
        assert resolution.side == "left"
        assert resolution.confidence == CONFIDENCE_ESTIMATED
        assert resolution.method == METHOD_ARM_EXTENSION

    def test_without_a_judge_the_result_is_the_old_one(self):
        exchange = _exchange(**_ATTACK_LEFT, footwork=("advance", "advance"))
        resolution = resolve_attacker(exchange)
        assert resolution.side == "unclear"
        assert resolution.confidence is None
        assert resolution.detail is None

    def test_declined_calls_carry_the_reason_but_no_attacker(self):
        exchange = _exchange(**_FLAT, footwork=("advance", "advance"))
        resolution = resolve_attacker(exchange, judge=_judge())
        assert resolution.side == "unclear"
        assert resolution.reason == REASON_NO_COMMIT


class TestTouchAnnotation:
    def _touch_and_exchanges(self, footwork):
        exchange = _exchange(**_ATTACK_LEFT, number=7, footwork=footwork)
        exchange["end_frame"] = 135
        exchange["min_distance_frame"] = 135
        return {"frame": 160, "scorer": "left"}, [exchange]

    def test_estimated_attacker_produces_an_outcome(self):
        touch, exchanges = self._touch_and_exchanges(("advance", "advance"))
        annotate_touch_outcome(touch, exchanges, fps=30.0, judge=_judge())
        assert touch["attacker_side"] == "left"
        assert touch["attack_outcome"] == "attack_success"
        assert touch["attacker_confidence"] == CONFIDENCE_ESTIMATED
        assert touch["priority_detail"]["margin"] > 0

    def test_new_keys_are_always_present_even_without_a_judge(self):
        """A touch dict's shape must not depend on the weapon it came from."""
        touch, exchanges = self._touch_and_exchanges(("retreat", "fleche"))
        annotate_touch_outcome(touch, exchanges, fps=30.0)
        for key in ("attacker_confidence", "attacker_method", "priority_detail"):
            assert key in touch
        assert touch["attacker_confidence"] == CONFIDENCE_HIGH
        assert touch["priority_detail"] is None


def _lamp(pattern):
    states = {
        "double": ("color", "color"),
        "single_left": ("color", "off"),
        "single_right": ("off", "color"),
    }[pattern]
    return LampReading(
        pattern=pattern,
        confidence=1.0,
        left=LampSideReading(state=states[0], peak_fill=0.8, on_frames=60),
        right=LampSideReading(state=states[1], peak_fill=0.8, on_frames=60),
        start_frame=100,
        end_frame=120,
        frames_sampled=40,
    )


class TestSingleLampWithdrawsEstimates:
    """A single valid lamp proves the priority question was never asked."""

    def _estimated_touch(self, scorer="left"):
        return {
            "frame": 160,
            "scorer": scorer,
            "attack_outcome": "attack_success" if scorer == "left" else "attack_failed",
            "attack_outcome_ko": ATTACK_OUTCOME_KO[
                "attack_success" if scorer == "left" else "attack_failed"
            ],
            "attacker_side": "left",
            "defender_side": "right",
            "matched_exchange_number": 7,
            "attacker_confidence": CONFIDENCE_ESTIMATED,
            "attacker_method": METHOD_ARM_EXTENSION,
            "priority_detail": {"margin": 0.3},
            "priority_reason": REASON_ESTIMATED,
        }

    def test_estimate_is_withdrawn(self):
        touch = self._estimated_touch()
        annotate_touch_lamp(touch, _lamp("single_left"))
        assert touch["attack_outcome"] == NO_PRIORITY_CALL
        assert touch["attacker_side"] == "unclear"
        assert touch["attacker_confidence"] is None
        assert touch["priority_reason"] == "withdrawn_single_lamp"

    def test_a_double_lamp_leaves_the_estimate_standing(self):
        """Both hits valid means the referee *did* rule — the estimate applies."""
        touch = self._estimated_touch()
        annotate_touch_lamp(touch, _lamp("double"))
        assert touch["attack_outcome"] == "attack_success"
        assert touch["attacker_confidence"] == CONFIDENCE_ESTIMATED

    def test_a_footwork_verdict_is_never_withdrawn(self):
        touch = self._estimated_touch()
        touch["attacker_confidence"] = CONFIDENCE_HIGH
        touch["attacker_method"] = METHOD_FOOTWORK
        touch["priority_detail"] = None
        annotate_touch_lamp(touch, _lamp("single_left"))
        assert touch["attack_outcome"] == "attack_success"
        assert touch["attacker_side"] == "left"

    def test_withdrawal_is_idempotent(self):
        touch = self._estimated_touch()
        annotate_touch_lamp(touch, _lamp("single_left"))
        once = copy.deepcopy(touch)
        annotate_touch_lamp(touch, _lamp("single_left"))
        assert touch == once


class TestReportPresentation:
    """The UI must never present an estimate as though it were a determination."""

    def test_estimated_touches_get_a_badge(self):
        report = {"touches": [{
            "attack_outcome": "attack_success",
            "attacker_side": "left",
            "attacker_confidence": CONFIDENCE_ESTIMATED,
        }]}
        annotate_estimated_badges(report)
        assert report["touches"][0]["estimated_badge"] == ESTIMATED_BADGE_KO

    def test_footwork_verdicts_get_no_badge(self):
        report = {"touches": [{
            "attack_outcome": "attack_success",
            "attacker_side": "left",
            "attacker_confidence": CONFIDENCE_HIGH,
        }]}
        annotate_estimated_badges(report)
        assert "estimated_badge" not in report["touches"][0]

    def test_reports_predating_priority_estimation_are_untouched(self):
        report = {"touches": [{"attack_outcome": "unclear"}]}
        annotate_estimated_badges(report)
        assert report == {"touches": [{"attack_outcome": "unclear"}]}

    def test_a_declined_call_explains_itself_rather_than_the_question(self):
        """"Both advanced" is why the judge was asked, not what it answered."""
        report = {
            "touches": [{
                "attack_outcome": "unclear",
                "matched_exchange_number": 1,
                "priority_reason": REASON_SIMULTANEOUS,
            }],
            "exchanges": [{"exchange_number": 1, "attacker": "both"}],
        }
        annotate_outcome_reasons(report)
        assert report["touches"][0]["outcome_reason"] == (
            OUTCOME_REASON_PRIORITY_SIMULTANE
        )

    def test_footwork_reason_still_used_when_the_judge_never_ran(self):
        report = {
            "touches": [{
                "attack_outcome": "unclear",
                "matched_exchange_number": 1,
                "priority_reason": None,
            }],
            "exchanges": [{"exchange_number": 1, "attacker": "both"}],
        }
        annotate_outcome_reasons(report)
        assert "동시에 전진" in report["touches"][0]["outcome_reason"]


class TestSeriesFrameConversion:
    """The sample-index → video-frame multiplication is asserted, not trusted."""

    def test_accepts_a_correctly_converted_series(self):
        exchange = {
            "exchange_number": 1,
            "start_frame": 300,
            "min_distance_frame": 400,
            "end_frame": 400,
            "arm_series_left": [[255, 0.5], [300, 0.6], [400, 0.7]],
        }
        validate_priority_series_frames([exchange], lead_frames=45)

    def test_rejects_an_unmultiplied_sample_index(self):
        """The exact bug this guards: frames left in sample units."""
        exchange = {
            "exchange_number": 1,
            "start_frame": 300,
            "min_distance_frame": 400,
            "end_frame": 400,
            "arm_series_left": [[85, 0.5], [100, 0.6]],
        }
        with pytest.raises(ValueError, match="conversion is wrong"):
            validate_priority_series_frames([exchange], lead_frames=45)


class TestSeriesExtraction:
    def test_gaps_are_kept_rather_than_dropped(self):
        """"Arm was down" and "we could not see the arm" are different facts."""
        analyzer = PoseAnalyzer()
        seq = [
            PoseResult(frame_idx=i, fencers=[
                _fencer("left", cx=100.0 + i, arms={"left": (200.0 + i, True)}),
            ])
            for i in range(5)
        ]
        seq[2] = PoseResult(frame_idx=2, fencers=[])
        arm, hip = analyzer._extract_priority_series(seq, 0, 4, "left")
        assert [f for f, _ in arm] == [0, 1, 2, 3, 4]
        assert arm[2][1] is None
        assert hip[2][1] is None
        assert arm[0][1] is not None

    def test_hip_is_normalised_by_body_height(self):
        """Thresholds in body heights must mean the same on a zoomed shot."""
        analyzer = PoseAnalyzer()
        seq = [PoseResult(frame_idx=0, fencers=[_fencer("left", cx=130.0)])]
        _arm, hip = analyzer._extract_priority_series(seq, 0, 0, "left")
        # Hip centre x is 130 and shoulder-to-ankle height is 130px.
        assert hip[0][1] == pytest.approx(1.0, abs=0.01)
