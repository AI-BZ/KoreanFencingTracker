"""Exchange detection state machine, classification, and my-fencer summary."""

from typing import List, Optional, Set, Tuple

from analyzer.models import (
    PoseResult, FootworkType, NonScoringEventType,
    ExchangeEvent, MyFencerSummary,
)
from analyzer.config import (
    EXCHANGE_MIN_APPROACH_FRAMES,
    EXCHANGE_MIN_DISTANCE_CHANGE_BH,
    EXCHANGE_MERGE_SEPARATION_FRAMES,
    EXCHANGE_ATTACK_FOOTWORK_TYPES,
    SCORING_FRAME_TOLERANCE_SEC,
)
from ml.pose_analysis.footwork import detect_footwork
from ml.pose_analysis.parry import detect_parry


def detect_exchanges(
    sampled: List[Tuple[int, Optional[float]]],
) -> List[Tuple[int, int, int, float]]:
    """
    State machine to detect exchanges from sampled distance series.

    Returns list of (start_frame, end_frame, min_distance_frame, min_distance_bh).
    """
    exchanges: List[Tuple[int, int, int, float]] = []
    state = "IDLE"
    approach_start = 0
    approach_count = 0
    min_dist = float("inf")
    min_dist_frame = 0
    start_dist = 0.0

    for i in range(len(sampled)):
        frame_idx, dist = sampled[i]
        if dist is None:
            continue

        if state == "IDLE":
            # Check if distance is decreasing
            if i > 0:
                _, prev_dist = sampled[i - 1]
                if prev_dist is not None and dist < prev_dist:
                    state = "APPROACH"
                    approach_start = frame_idx
                    approach_count = 1
                    start_dist = prev_dist
                    min_dist = dist
                    min_dist_frame = frame_idx

        elif state == "APPROACH":
            if dist <= min_dist:
                min_dist = dist
                min_dist_frame = frame_idx
                approach_count += 1
            else:
                # Distance started increasing → engagement → separation
                if (approach_count >= EXCHANGE_MIN_APPROACH_FRAMES
                        and (start_dist - min_dist) >= EXCHANGE_MIN_DISTANCE_CHANGE_BH):
                    # Valid exchange
                    state = "SEPARATION"
                else:
                    # Too short — reset
                    state = "IDLE"

        elif state == "SEPARATION":
            sep_frames = frame_idx - min_dist_frame
            if i > 0:
                _, prev_dist = sampled[i - 1]
                if prev_dist is not None and dist < prev_dist:
                    if sep_frames <= EXCHANGE_MERGE_SEPARATION_FRAMES:
                        # Short separation → merge into same exchange (back to APPROACH)
                        state = "APPROACH"
                        approach_count += 1
                        if dist <= min_dist:
                            min_dist = dist
                            min_dist_frame = frame_idx
                    else:
                        # Long separation → end current exchange, start new one
                        exchanges.append((approach_start, frame_idx, min_dist_frame, min_dist))
                        state = "APPROACH"
                        approach_start = frame_idx
                        approach_count = 1
                        start_dist = prev_dist if prev_dist is not None else dist
                        min_dist = dist
                        min_dist_frame = frame_idx
                # else still separating
                elif (dist - min_dist) > EXCHANGE_MIN_DISTANCE_CHANGE_BH:
                    # Sufficiently separated — exchange complete
                    exchanges.append((approach_start, frame_idx, min_dist_frame, min_dist))
                    state = "IDLE"

    # Handle unfinished exchange
    if state in ("APPROACH", "SEPARATION") and approach_count >= EXCHANGE_MIN_APPROACH_FRAMES:
        last_frame = sampled[-1][0] if sampled else 0
        if (start_dist - min_dist) >= EXCHANGE_MIN_DISTANCE_CHANGE_BH:
            exchanges.append((approach_start, last_frame, min_dist_frame, min_dist))

    return exchanges


def classify_exchange(
    sub_seq: List[PoseResult],
    is_scoring: bool,
    start_frame: int,
    end_frame: int,
    lamp_white_frames: Set[int],
    footwork_window: int,
    parry_window: int,
    use_ratio_based_hip_drop: bool,
) -> NonScoringEventType:
    """Classify an exchange as scoring or non-scoring event type."""
    if is_scoring:
        # A touch landed in this exchange, but the scorer attribution is not
        # resolved here (the scoring label lives in the touch analysis).
        # UNKNOWN_EXCHANGE means "scored, attribution unknown here" — it is not
        # a low-confidence marker.
        return NonScoringEventType.UNKNOWN_EXCHANGE

    # Check for white lamp (off-target)
    if any(start_frame <= wf <= end_frame for wf in lamp_white_frames):
        return NonScoringEventType.OFF_TARGET

    # Check for parry in sub-sequence
    has_parry = False
    if len(sub_seq) >= 3:
        for s in ("left", "right"):
            pr = detect_parry(sub_seq, s, parry_window)
            if pr.parry_detected:
                has_parry = True
                break

    # Footwork for both fencers, reused for the mutual-retreat and
    # attack-signal checks. None when the window is too short to analyse.
    fw_l = None
    fw_r = None
    if len(sub_seq) >= 3:
        fw_l = detect_footwork(sub_seq, "left", footwork_window, use_ratio_based_hip_drop)
        fw_r = detect_footwork(sub_seq, "right", footwork_window, use_ratio_based_hip_drop)

    both_retreat = (
        fw_l is not None and fw_r is not None
        and fw_l.footwork_type == FootworkType.RETREAT
        and fw_r.footwork_type == FootworkType.RETREAT
    )

    if both_retreat:
        return NonScoringEventType.MUTUAL_RETREAT
    if has_parry:
        return NonScoringEventType.SUCCESSFUL_DEFENSE

    # Only label a failed attack when at least one fencer committed to an
    # attacking approach (advance/lunge/fleche). Without that signal — both
    # fencers stationary/unknown, or the window too short — the exchange is
    # low-confidence noise, so return NEUTRAL to keep it out of the stats
    # instead of asserting a confident "failed attack".
    has_attack_signal = (
        (fw_l is not None and fw_l.footwork_type.value in EXCHANGE_ATTACK_FOOTWORK_TYPES)
        or (fw_r is not None and fw_r.footwork_type.value in EXCHANGE_ATTACK_FOOTWORK_TYPES)
    )
    if has_attack_signal:
        return NonScoringEventType.FAILED_ATTACK
    return NonScoringEventType.NEUTRAL


def build_my_fencer_summary(
    exchanges: List[ExchangeEvent],
    my_fencer: str,
    scoring_frames: Set[int],
    fps: float,
) -> MyFencerSummary:
    """Build stats summary from my_fencer's perspective."""
    summary = MyFencerSummary(side=my_fencer)
    narratives: List[str] = []

    # Same tolerance as analyze_continuous for OCR delay
    scoring_tolerance = int(SCORING_FRAME_TOLERANCE_SEC * fps)

    for ex in exchanges:
        # NEUTRAL exchanges are low-confidence noise with no clear aggressor —
        # exclude them from both the attack and defense denominators so they
        # do not distort success rates.
        if ex.event_type == NonScoringEventType.NEUTRAL:
            continue

        is_scoring = any(
            ex.start_frame - scoring_tolerance <= sf <= ex.end_frame + scoring_tolerance
            for sf in scoring_frames
        )

        # Determine if my fencer was attacking (approaching toward opponent)
        my_fw = ex.footwork_left if my_fencer == "left" else ex.footwork_right
        opp_fw = ex.footwork_right if my_fencer == "left" else ex.footwork_left

        my_attacking = (
            my_fw is not None
            and my_fw.footwork_type in (
                FootworkType.LUNGE, FootworkType.FLECHE,
                FootworkType.ADVANCE,
            )
        )
        opp_attacking = (
            opp_fw is not None
            and opp_fw.footwork_type in (
                FootworkType.LUNGE, FootworkType.FLECHE,
                FootworkType.ADVANCE,
            )
        )

        if my_attacking:
            summary.attacks_attempted += 1
            if is_scoring:
                summary.attacks_succeeded += 1
            else:
                summary.attacks_failed += 1
                if ex.event_type == NonScoringEventType.FAILED_ATTACK:
                    narratives.append(
                        f"프레임 {ex.start_frame}-{ex.end_frame}: "
                        f"공격 실패 (거리 {ex.min_distance_bh:.2f} BH)"
                    )

        if opp_attacking and not my_attacking:
            summary.defenses_attempted += 1
            if ex.event_type == NonScoringEventType.SUCCESSFUL_DEFENSE:
                summary.defenses_succeeded += 1
                narratives.append(
                    f"프레임 {ex.start_frame}-{ex.end_frame}: "
                    f"방어 성공"
                )

    # Compute rates
    if summary.attacks_attempted > 0:
        summary.attack_success_rate = summary.attacks_succeeded / summary.attacks_attempted
    if summary.defenses_attempted > 0:
        summary.defense_success_rate = summary.defenses_succeeded / summary.defenses_attempted

    summary.narratives = narratives
    return summary
