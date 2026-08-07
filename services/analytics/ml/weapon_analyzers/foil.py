"""Foil priority estimation from arm extension and forward motion.

FIE t.56 defines the attack as extending the arm *while* advancing on the
opponent, and priority follows the attack. Two of those three elements are
visible in pose data — the arm and the feet — while the third, the blade
threatening valid target, is not. So this module does not reproduce a referee's
call. It answers a narrower question: **in the run-up to contact, which fencer
was committing forward with an extending arm?** That is a coaching signal, and
it is labelled ``estimated`` everywhere it surfaces so it is never mistaken for
the footwork-determined verdict.

Two measured findings shape the algorithm, both from the reference foil final:

*Comparing onset times does not work.* Detecting who extended first matched
footwork-determined attackers on only 5 of 9 exchanges, called one exactly
backwards, and found no onset at all on 3. The reason is structural rather than a
tuning problem: an attacker's arm is often already extended when the window
opens, so there is no rise to detect. This module compares *how much* each fencer
committed over the approach instead of *when* they started.

*Absolute thresholds are meaningless.* En-garde extension ranged 0.6-0.9 between
the two fencers of a single bout — one fencer's resting arm sits above the
other's attacking one. Every extension value is therefore normalised against
that fencer's own baseline for that bout before the two are compared.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from analyzer.config import (
    PRIORITY_BASELINE_DEFAULT,
    PRIORITY_BASELINE_MIN_SAMPLES,
    PRIORITY_BASELINE_NORMALISE,
    PRIORITY_CLEAR_MARGIN,
    PRIORITY_DECISION_END_OFFSET_SEC,
    PRIORITY_DECISION_WINDOW_SEC,
    PRIORITY_FWD_MIN_VX_BH,
    PRIORITY_FWD_STATIONARY_WEIGHT,
    PRIORITY_MIN_COMMIT,
    PRIORITY_ESTIMATION_ENABLED,
    PRIORITY_MIN_QUALITY,
    PRIORITY_SMOOTH_WINDOW,
)

SIDES = ("left", "right")

#: Grade written onto a touch whose attacker came from this module. Kept distinct
#: from the footwork verdict's "high" so the two can never be totalled together
#: by accident.
GRADE_ESTIMATED = "estimated"

#: Method tag, parallel to the footwork path's "footwork".
METHOD_ARM_EXTENSION = "arm_extension"

# Why no call was made. These are outcomes, not errors: foil's simultaneous
# attack is a real situation in which the referee awards nothing, so declining to
# choose is the correct answer rather than a failure to produce one.
REASON_ESTIMATED = "estimated"
REASON_NO_SERIES = "no_series"
REASON_LOW_QUALITY = "low_quality"
REASON_NO_COMMIT = "no_commit"
REASON_SIMULTANEOUS = "simultaneous"

#: Baseline ceiling. A fencer whose baseline extension reads ~1.0 would make the
#: normalising denominator (1 − baseline) vanish and turn keypoint noise into
#: enormous normalised values.
_BASELINE_MAX = 0.95

#: Extension and forward weight a side must reach for its "onset" timestamp. Only
#: feeds the informational ``lead_sec``; no decision depends on it.
_ONSET_EXT = 0.5


@dataclass(frozen=True)
class PriorityCall:
    """The judge's answer for one exchange.

    ``attacker`` is ``None`` whenever ``reason`` is anything but
    :data:`REASON_ESTIMATED`; ``detail`` carries the measured scores whenever
    they could be computed at all, including for declined calls, because the
    calibration script needs to see near-misses.
    """

    attacker: Optional[str] = None
    grade: Optional[str] = None
    reason: str = REASON_NO_SERIES
    detail: Optional[dict] = None


# ------------------------------------------------------------------
# Series helpers
# ------------------------------------------------------------------


def _median(values: Sequence[float]) -> Optional[float]:
    """Median of ``values``; ``None`` when empty."""
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return None
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _median_smooth(
    values: Sequence[Optional[float]],
    window: int,
) -> List[Optional[float]]:
    """Centred median filter that treats ``None`` as missing, not as zero.

    Dropouts stay ``None`` only where the whole window is missing, so an
    isolated gap is bridged by its neighbours while a real blackout is still
    reported as a gap. A mean would let one 0.9→0.1 occlusion spike drag the
    whole neighbourhood; the median discards it.
    """
    half = max(window, 1) // 2
    out: List[Optional[float]] = []
    for i in range(len(values)):
        lo = max(0, i - half)
        hi = min(len(values), i + half + 1)
        present = [v for v in values[lo:hi] if v is not None]
        out.append(_median(present))
    return out


def _as_map(series: Optional[Sequence]) -> Dict[int, Optional[float]]:
    """``[[frame, value], ...]`` → ``{frame: value}``."""
    if not series:
        return {}
    return {int(entry[0]): entry[1] for entry in series}


def _forward_sign(side: str) -> float:
    """+1 if this fencer advances toward larger x, −1 otherwise.

    The left-of-frame fencer faces right, so closing the distance increases the
    hip x coordinate; the right-of-frame fencer's decreases.
    """
    return 1.0 if side == "left" else -1.0


# ------------------------------------------------------------------
# Session baselines
# ------------------------------------------------------------------


def compute_session_baselines(
    exchanges: Sequence[dict],
    min_samples: int = PRIORITY_BASELINE_MIN_SAMPLES,
    default: float = PRIORITY_BASELINE_DEFAULT,
) -> Dict[str, float]:
    """Per-fencer resting arm extension for one bout.

    Preference order per side:

    1. The pooled *lead-in* samples — everything captured before an exchange's
       own start frame, i.e. preparation rather than the attack itself. This is
       the closest thing to "at rest" the stored windows contain.
    2. All stored samples, when the lead-ins are too sparse to be stable.
    3. :data:`PRIORITY_BASELINE_DEFAULT`, when the side has no usable pose at
       all.

    Computed once per bout, not per exchange: the quantity being estimated is a
    fencer's habitual guard, and a single exchange has neither enough samples nor
    enough rest in it.
    """
    baselines: Dict[str, float] = {}
    for side in SIDES:
        lead: List[float] = []
        every: List[float] = []
        for ex in exchanges:
            start = ex.get("start_frame")
            for entry in ex.get(f"arm_series_{side}") or ():
                frame, value = int(entry[0]), entry[1]
                if value is None:
                    continue
                every.append(value)
                if start is not None and frame < start:
                    lead.append(value)

        if len(lead) >= min_samples:
            base = _median(lead)
        elif every:
            base = _median(every)
        else:
            base = None

        baselines[side] = min(default if base is None else base, _BASELINE_MAX)
    return baselines


# ------------------------------------------------------------------
# The judge
# ------------------------------------------------------------------


class FoilPriorityJudge:
    """Estimates the attacking side of a foil exchange from its stored series.

    Constructed once per bout because the baselines it normalises against are a
    per-bout property. :meth:`judge` is pure with respect to the exchange dict —
    it reads the serialized report, so the same judge runs inside report
    generation and inside a threshold sweep over an already-written report.

    All thresholds are constructor arguments rather than module constants read at
    call time, so the calibration script can sweep them without mutating global
    state that the production path also reads.
    """

    weapon = "foil"
    #: Written to ``attacker_method`` by the touch-annotation cascade, which
    #: reads this attribute rather than importing the class.
    method = METHOD_ARM_EXTENSION

    def __init__(
        self,
        baselines: Optional[Dict[str, float]] = None,
        fps: float = 30.0,
        normalise: bool = PRIORITY_BASELINE_NORMALISE,
        decision_window_sec: float = PRIORITY_DECISION_WINDOW_SEC,
        decision_end_offset_sec: float = PRIORITY_DECISION_END_OFFSET_SEC,
        smooth_window: int = PRIORITY_SMOOTH_WINDOW,
        clear_margin: float = PRIORITY_CLEAR_MARGIN,
        min_commit: float = PRIORITY_MIN_COMMIT,
        min_quality: float = PRIORITY_MIN_QUALITY,
        stationary_weight: float = PRIORITY_FWD_STATIONARY_WEIGHT,
        fwd_min_vx_bh: float = PRIORITY_FWD_MIN_VX_BH,
    ) -> None:
        self.baselines = dict(baselines or {})
        for side in SIDES:
            self.baselines.setdefault(side, PRIORITY_BASELINE_DEFAULT)
            self.baselines[side] = min(self.baselines[side], _BASELINE_MAX)
        self.fps = fps
        self.normalise = normalise
        self.decision_window_sec = decision_window_sec
        self.decision_end_offset_sec = decision_end_offset_sec
        self.smooth_window = smooth_window
        self.clear_margin = clear_margin
        self.min_commit = min_commit
        self.min_quality = min_quality
        self.stationary_weight = stationary_weight
        self.fwd_min_vx_bh = fwd_min_vx_bh

    # -- signal construction ---------------------------------------

    def _side_signals(
        self,
        frames: Sequence[int],
        arm: Dict[int, Optional[float]],
        hip: Dict[int, Optional[float]],
        side: str,
    ) -> Tuple[List[Optional[float]], List[Optional[float]]]:
        """Normalised extension and forward weight, one entry per frame.

        Extension is rescaled so that 0 is this fencer's own guard and 1 is a
        fully straight arm; below-guard values clip to 0 rather than going
        negative, since withdrawing further than usual is not negative attack.

        The forward weight applies FIE's conjunction: extending while advancing
        counts fully, extending while stationary is discounted, and extending
        while retreating counts for nothing at all. That last case is the
        counter-attack — a real, common, and deliberately unrewarded action.
        """
        base = self.baselines[side] if self.normalise else 0.0
        denominator = 1.0 - base

        arm_sm = _median_smooth([arm.get(f) for f in frames], self.smooth_window)
        hip_sm = _median_smooth([hip.get(f) for f in frames], self.smooth_window)

        ext: List[Optional[float]] = []
        for value in arm_sm:
            if value is None or denominator <= 0:
                ext.append(None)
            else:
                ext.append(max(0.0, min(1.0, (value - base) / denominator)))

        sign = _forward_sign(side)
        fwd: List[Optional[float]] = [None]
        for i in range(1, len(hip_sm)):
            prev, curr = hip_sm[i - 1], hip_sm[i]
            if prev is None or curr is None:
                fwd.append(None)
                continue
            toward = sign * (curr - prev)
            if toward > self.fwd_min_vx_bh:
                fwd.append(1.0)
            elif toward < -self.fwd_min_vx_bh:
                fwd.append(0.0)
            else:
                fwd.append(self.stationary_weight)
        return ext, fwd

    def _onset_index(
        self,
        ext: Sequence[Optional[float]],
        fwd: Sequence[Optional[float]],
        indices: Sequence[int],
    ) -> Optional[int]:
        """First index in ``indices`` where this side is extending and advancing."""
        for i in indices:
            if ext[i] is not None and fwd[i] is not None:
                if ext[i] >= _ONSET_EXT and fwd[i] >= 1.0:
                    return i
        return None

    # -- public API ------------------------------------------------

    def judge(self, exchange: dict) -> PriorityCall:
        """Estimate who was attacking, or decline with a reason."""
        arm = {side: _as_map(exchange.get(f"arm_series_{side}")) for side in SIDES}
        hip = {side: _as_map(exchange.get(f"hip_x_series_{side}")) for side in SIDES}
        if not all(arm[s] and hip[s] for s in SIDES):
            return PriorityCall(reason=REASON_NO_SERIES)

        frames = sorted(set(arm["left"]) | set(arm["right"]))
        # The decision window is the run-up to the nearest approach — the best
        # available estimate of blade contact, and deliberately not the OCR score
        # frame, which lags it by a measured ~2.8s median. The series already
        # ends at nearest approach, so the last stored frame is the anchor.
        #
        # The final stretch before that anchor is then cut off. At closest
        # approach the fencers overlap, the pose estimator starts assigning one
        # body's keypoints to the other, and whatever the arms read there
        # describes the collision rather than who caused it.
        end = frames[-1] - self.decision_end_offset_sec * self.fps
        start = end - self.decision_window_sec * self.fps
        decision = [i for i, f in enumerate(frames) if start <= f <= end]
        if len(decision) < 2:
            return PriorityCall(reason=REASON_LOW_QUALITY)

        ext: Dict[str, List[Optional[float]]] = {}
        fwd: Dict[str, List[Optional[float]]] = {}
        for side in SIDES:
            ext[side], fwd[side] = self._side_signals(
                frames, arm[side], hip[side], side,
            )

        usable = [
            i for i in decision
            if all(ext[s][i] is not None and fwd[s][i] is not None for s in SIDES)
        ]
        quality = len(usable) / len(decision)

        commit: Dict[str, Optional[float]] = {}
        for side in SIDES:
            scores = [
                ext[side][i] * fwd[side][i]
                for i in decision
                if ext[side][i] is not None and fwd[side][i] is not None
            ]
            commit[side] = sum(scores) / len(scores) if scores else None

        detail = {
            "commit_left": _round(commit["left"]),
            "commit_right": _round(commit["right"]),
            "margin": (
                None if commit["left"] is None or commit["right"] is None
                else round(abs(commit["left"] - commit["right"]), 3)
            ),
            "window_quality": round(quality, 3),
            "window_frames": [frames[decision[0]], frames[decision[-1]]],
            "lead_sec": self._lead_sec(ext, fwd, decision, frames),
        }

        if quality < self.min_quality:
            return PriorityCall(reason=REASON_LOW_QUALITY, detail=detail)
        if commit["left"] is None or commit["right"] is None:
            return PriorityCall(reason=REASON_LOW_QUALITY, detail=detail)
        if max(commit["left"], commit["right"]) < self.min_commit:
            return PriorityCall(reason=REASON_NO_COMMIT, detail=detail)
        if abs(commit["left"] - commit["right"]) < self.clear_margin:
            # Both committed together and neither clearly first. In foil that is
            # a simultaneous attack, which the referee also declines to score —
            # so this is the right answer, not a missing one.
            return PriorityCall(reason=REASON_SIMULTANEOUS, detail=detail)

        attacker = "left" if commit["left"] > commit["right"] else "right"
        return PriorityCall(
            attacker=attacker,
            grade=GRADE_ESTIMATED,
            reason=REASON_ESTIMATED,
            detail=detail,
        )

    def _lead_sec(
        self,
        ext: Dict[str, List[Optional[float]]],
        fwd: Dict[str, List[Optional[float]]],
        decision: Sequence[int],
        frames: Sequence[int],
    ) -> Optional[float]:
        """Seconds by which the left fencer's commitment preceded the right's.

        Informational only — the measured failure of onset comparison (see the
        module docstring) is why no decision reads this.
        """
        onsets = {
            side: self._onset_index(ext[side], fwd[side], decision)
            for side in SIDES
        }
        if onsets["left"] is None or onsets["right"] is None:
            return None
        delta = frames[onsets["right"]] - frames[onsets["left"]]
        return round(delta / self.fps, 2)


def _round(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 3)


def build_priority_judge(
    weapon: Optional[str],
    exchanges: Sequence[dict],
    fps: float = 30.0,
    enabled: bool = PRIORITY_ESTIMATION_ENABLED,
    **overrides,
) -> Optional[FoilPriorityJudge]:
    """Judge for ``weapon``, or ``None`` when priority cannot be estimated.

    Returns ``None`` for every weapon but foil, for a foil bout whose exchanges
    carry no priority series (reports generated before the series existed must
    keep producing exactly the verdicts they produced before), and whenever
    :data:`PRIORITY_ESTIMATION_ENABLED` is off.

    The calibration script passes ``enabled=True`` explicitly so that it can
    measure the judge whether or not the measurement has yet justified shipping
    it — which is the only way the flag can ever be flipped back on.
    """
    if not enabled:
        return None
    if weapon != "foil":
        return None
    if not any(ex.get("arm_series_left") for ex in exchanges):
        return None
    return FoilPriorityJudge(
        baselines=compute_session_baselines(exchanges), fps=fps, **overrides,
    )
