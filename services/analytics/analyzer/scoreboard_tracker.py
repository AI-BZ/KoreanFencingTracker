"""Track a physical LED scoreboard through a shaky crop and read its lamps.

The fixed-ROI reader (:mod:`analyzer.lamp_detector` + :mod:`analyzer.score_reader`
driven by :class:`analyzer.video_processor.VideoProcessor`) assumes the scoreboard
sits at the same pixels all bout. On handheld/tripod-with-drift coach footage it
does not: on ``260815_bout_a_…_scoreboard.mp4`` the panel wanders 367 px
horizontally and 306 px vertically over 166 s, so a fixed lamp ROI spends most of
the bout pointed at the wall. That path reported 40 lamp events for a 6-touch
pool bout and misread the final score.

This module replaces the *detection* layer only. It locates the panel in every
frame, expresses the lamp and score-digit regions relative to the located panel,
and emits lamp events plus a scorer decision. Everything downstream — the
``MatchEvent`` shape, :mod:`app.led_report_converter`, the
``<piste stem>_report.json`` merge — is unchanged.

Three cooperating pieces
------------------------
:class:`PanelTracker`
    Two independent normalized-correlation template trackers (the machine
    housing, and the piste placard bolted below it) with a local search window
    and a full-frame reacquisition fallback. Their positions are fused so that
    either one alone can carry the track. Measured on the two reference videos:
    100 % / 99.65 % fused lock, position agreement between the two independent
    trackers of 1 px median and 2 px p95.

:class:`LampEventScanner`
    Reads the lamp pairs in panel-relative coordinates. A lamp core is blown out
    to white by the exposure, so "is it lit" comes from the *saturated* pixel
    fraction (``V >= 245``) and "what colour" comes from the surrounding halo
    (``150 <= V <= 244``), where the hue survives.

:class:`ScoreChangeDetector`
    Watches the two 7-segment score digits — for a *change*, not a value. No OCR:
    a shift-tolerant comparison of the red-LED pixel mask against the previous
    settled mask. This is what turns "a lamp lit" into "a point was awarded".

Why the score check is not optional
-----------------------------------
A lit lamp is not a touch. On ``260815_bout_b`` the referee annulled three
chromatic lamp events (two green, one red) — hit after halt and similar — and the
score never moved. A lamp-only pipeline scores those as touches. So a touch is
confirmed only when a lamp event is followed by a change in one side's score
digits before the next lamp event; a chromatic lamp with no score change is
reported as ``annulled`` rather than silently kept or silently dropped.

The one thing that check gets wrong on its own is *which* lamp closes the window.
An off-target white lamp closes it like any other, so an operator entering the
point a beat late lands after the boundary and the touch vanishes — measured on
``20260828_김창환배``, where the hit that ended the bout 5–1 was reported as no
hit at all. A white lamp is not something a referee weighs, so
:func:`resolve_touches` looks past a run of them for the score change, under
conditions strict enough that a genuine annulment still cannot get through. See
its docstring; the annulment gate above is unchanged.

The other thing the digit comparison gets wrong is claiming *both* sides changed
when only one did. The similarity distributions of a real change and a false one
overlap — measured across the four ``20260828_김창환배`` bouts, real changes span
0.149–0.604 and false "changes" 0.585–0.770 — so no threshold separates them and
the fix cannot come from the pixels. It comes from the weapon: under priority
(foil, sabre) one action awards one point or none, so both sides rising is not a
result the bout can have produced, and one of the two readings is wrong. Which
one is settled by the lamps, which are electrical signals rather than pixel
statistics. See :func:`resolve_touches` and :data:`PRIORITY_WEAPONS`.

Score values are *derived*, not read
------------------------------------
:func:`resolve_touches` numbers the score by counting confirmed touches from a
baseline. Everything after the baseline is a lamp-confirmed count; the baseline
itself is the score the panel already showed when the clip opened, and getting
it wrong shifts every number in the report by the same amount with nothing else
to show for it. That is not a corner case: a DE period 2 or 3 opens on the
previous period's score, and a camera started late opens on whatever had been
scored already. Measured on ``260716_de64_s1_piste3``, the panel is at 0–1
before the first lamp and the report came out 6–5 against a true 7–6.

:class:`StartScoreReader` reads that baseline off the digits, and
:func:`track_scoreboard_video` uses it whenever the caller does not name one.
**On all nine calibrated venues it currently declines**, and the read is built to
decline rather than guess — see :class:`DigitReadConfig`. What defeats it is
resolution, not logic: a glyph spans 10–20 px, blooming closes the hole in a
``0``, and per-glyph identification measures 29 % top-1 with the match score of
a right answer and a wrong one drawn from the same distribution. So in practice
``--start-score`` is still how a mid-bout clip gets its baseline; what changed is
that a clip which needs one and did not get one now says so
(:attr:`ScoreboardAnalysis.start_score_assumed`) instead of quietly reporting a
score that is uniformly too low.

Coordinates
-----------
Every ROI in a :class:`MachineProfile` is relative to the **housing template's
top-left corner**, which is what :class:`PanelTracker` reports. That is why the
same profile works on both reference videos and would survive re-cropping the
source: only the frame-0 anchor changes, never the profile. Frame indices are
work-file frames (30 fps) and are never converted — see
:mod:`app.led_report_converter`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import cv2
import numpy as np

#: ``(x, y, w, h)``, always in pixels.
Rect = Tuple[int, int, int, int]

LEFT = "left"
RIGHT = "right"
SIDES = (LEFT, RIGHT)

#: Lamp colours :class:`LampEventScanner` can report. ``"white"`` is a real
#: reading — a foil off-target hit — not a failure to classify.
COLOUR_RED = "red"
COLOUR_GREEN = "green"
COLOUR_WHITE = "white"

#: Colours that mean a valid hit landed. A white lamp is a lamp, but not a hit.
CHROMATIC_COLOURS = (COLOUR_RED, COLOUR_GREEN)

#: :class:`TouchResolution.verdict` values.
VERDICT_TOUCH = "touch"
VERDICT_ANNULLED = "annulled"
VERDICT_OFF_TARGET = "off_target"
VERDICT_UNDETERMINED = "undetermined"
VERDICT_INCONSISTENT = "inconsistent"


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class TrackerConfig:
    """Thresholds for :class:`PanelTracker`.

    The defaults are the values validated on the two reference videos; the
    correlation floors are the load-bearing ones and are quoted against measured
    distributions rather than picked round.
    """

    #: Half-width of the local search window around the previous position. The
    #: largest measured frame-to-frame jump is 5 px, so 90 is ~18x headroom and
    #: still cheap.
    search_pad: int = 90

    #: At or above this correlation the position is trusted and lamps are read.
    #: The worst locked frame measured was 0.704, and the drop was caused by a
    #: fencer's mask occluding the panel's lower edge while the position stayed
    #: correct — so 0.55 keeps a healthy margin without inviting drift.
    lock_corr: float = 0.55

    #: Below this, the local window is presumed to have lost the panel and a
    #: full-frame search is run. Between this and ``lock_corr`` the position is
    #: carried forward but marked low-confidence and its frame is not read.
    reacquire_corr: float = 0.45

    #: Frames inspected when choosing which frame to cut live templates from.
    init_scan_frames: int = 90

    #: How far the two trackers may disagree, in pixels, before neither is
    #: believed. They track one rigid object, so on the reference videos they
    #: agree to 1 px median / 2 px p95; 12 is far outside that and still far
    #: inside the hundreds of pixels a false match lands away.
    max_disagreement_px: int = 12


@dataclass(frozen=True)
class LampConfig:
    """Thresholds for :class:`LampEventScanner`.

    Lit/unlit and colour are answered from two different pixel populations
    because the lamp core saturates: the core says *whether*, the halo says
    *which*.
    """

    #: A pixel this bright is self-luminous, not reflected light.
    core_value_min: int = 245

    #: Fraction of ROI pixels that must be saturated for the lamp to read as on.
    #: Unlit lamps sit at 0.01–0.06 of the ROI and lit ones near 1.0, so the gap
    #: this threshold has to land in is wide.
    on_fraction: float = 0.3

    #: The halo band, bright enough to be lamp light but not blown out.
    halo_value_min: int = 150
    halo_value_max: int = 244

    #: Halo pixels below this saturation are white light and carry no hue.
    halo_saturation_min: int = 40

    #: OpenCV hue is 0–179, so red straddles the wrap.
    red_hue_max: int = 15
    red_hue_min: int = 165
    green_hue_min: int = 35
    green_hue_max: int = 90

    #: Fraction of halo pixels of one hue needed to call the colour.
    #:
    #: The two populations are nowhere near each other, so this only has to land
    #: between them: white lamps measure 0.00–0.09 across all three venues, and
    #: chromatic ones 0.91–1.00 at the two close-up venues.
    #:
    #: It was 0.5, which is the midpoint of that gap but not the safe part of
    #: it. On the far-away ``kor_domestic_v3`` venue a lamp ROI spans a pair of
    #: lamps and most of its halo comes from the *unlit* neighbour, which
    #: dilutes the hue fraction: single green lamps there read 0.58–0.94, but
    #: the two **double-lamp** events — both fencers valid, i.e. exactly the
    #: foil priority calls this whole path exists to find — read 0.46 and 0.47
    #: and were therefore called white and dropped as non-touches. That is two
    #: real touches lost out of thirteen, and it cost the bout's score.
    #:
    #: 0.3 is still 3x the highest white ever measured and now clears the
    #: lowest chromatic by the same margin. Raising the floor on the white side
    #: is not possible — those are 0.00 — so the threshold belongs down here.
    colour_fraction: float = 0.3

    #: A lamp activation shorter than this is a pixel artefact, not a lamp.
    #: Real activations run ~2.3 s (70 frames).
    min_on_frames: int = 5

    #: Activations separated by less than this are one event with a dropout in
    #: the middle, not two events.
    merge_gap_frames: int = 12

    #: Frames of unreadable coverage that constitute a reportable gap. Half a
    #: second, i.e. well under one lamp activation, so any gap that could hide a
    #: whole event is always reported.
    coverage_gap_min_frames: int = 15


@dataclass(frozen=True)
class ScoreChangeConfig:
    """Thresholds for :class:`ScoreChangeDetector`.

    The window size is the load-bearing one. The score digits are multiplexed
    LEDs, so at 30 fps a single frame's mask is close to worthless: on the
    reference video the lit-pixel count of one unchanging digit swings between 0
    and 327, and consecutive single-frame masks agree only 0.75. Averaging over
    ``window_frames`` collapses that — consecutive averaged masks agree 0.98,
    and the averaged mask is a clean, legible digit.
    """

    #: A score digit segment is a red LED: chromatic in the red band, and bright
    #: relative to the rest of its own ROI. ``digit_value_min`` is a *floor* on
    #: the per-ROI Otsu cut, not the operating threshold — see :func:`digit_mask`.
    #: It exists so an ROI showing nothing cannot have a digit invented out of
    #: the faint glow of unlit segments; it is low enough that on both calibrated
    #: venues Otsu, not the floor, decides.
    digit_value_min: int = 120
    digit_saturation_min: int = 80
    digit_hue_max: int = 15
    digit_hue_min: int = 160

    #: Too few red pixels to be a lit display, so the ROI reads as blank rather
    #: than having Otsu split noise into a shape.
    digit_min_red_pixels: int = 40

    #: Frames averaged into one settled mask (0.7 s at 30 fps). Long enough to
    #: cover several multiplex cycles and to dilute a blade crossing the digits,
    #: short enough that two touches can never share a window.
    window_frames: int = 21

    #: How often a settled mask is retained for later comparison.
    sample_stride: int = 15

    #: Grace given to the operator to press the button after the lamp fires.
    #: Samples inside this are ignored, because a score read too early still
    #: shows the old number and would read as "no point awarded".
    settle_frames: int = 75

    #: How far back from the end of an interval samples are taken. The number is
    #: certainly settled by then, and several samples make the comparison immune
    #: to a fencer standing in front of the box for one of them.
    tail_frames: int = 180

    #: Fewer retained samples than this on either side of a boundary and the
    #: comparison is declined rather than guessed.
    min_samples: int = 3

    #: Shift search radius when comparing two settled masks. Absorbs the 1–2 px
    #: tracking jitter, which matters most for a thin ``1``.
    align_radius: int = 4

    #: Least fraction of the score ROIs that must be lit red for the tracked
    #: position to be believed at all. A scoring box emits light; a patch of
    #: piste floor does not. On 260816_venue2_bout the tracker was hijacked by the
    #: piste's boundary line — a false match scoring 0.63, above the
    #: reacquisition floor, so it never recovered — and every frame it read
    #: lamps from measured exactly 0.0000 here while genuine locks measured
    #: 0.049–0.093. Correlation cannot catch that; the absence of any display
    #: can.
    display_min_fraction: float = 0.01

    #: Below this best-aligned overlap the digits are showing a different number.
    #: Measured across all nine lamp events of the reference bout: intervals
    #: where the number changed scored 0.21–0.71 and intervals where it did not
    #: scored 0.88–0.96, so the threshold sits in an empty band.
    similarity_min: float = 0.78


@dataclass(frozen=True)
class DigitReadConfig:
    """Thresholds for reading a score field's *value* (:class:`StartScoreReader`).

    Separate from :class:`ScoreChangeConfig` because the two want opposite
    pixels. Change detection wants the glyph's whole red envelope — a fat, stable
    blob that survives jitter. Reading the value wants only the blown-out core of
    the lit segments, because a ``0`` and an ``8`` differ *only* by the hole in
    the middle, and the red glow fills that hole in. Measured on the 07-16 venue,
    where a glyph is ~20x33 px: the lit strokes sit at value 234-253 and the
    glow inside a ``0`` at 156-233, so the two populations do separate — but only
    well above the cut :func:`digit_mask` uses.
    """

    #: Where to put the brightness cut inside the red pixels' own range, as a
    #: fraction from the Otsu split (0.0) to the brightest red pixel (1.0).
    #: Relative rather than absolute because "how bright is a lit segment" varies
    #: by venue, exposure and distance — the same reason :func:`digit_mask` uses
    #: Otsu at all. See :func:`digit_core_mask`.
    #:
    #: Several of them, and a field only counts as read when they *all* decode
    #: to the same number. No single cut works everywhere: too low and a ``0``
    #: fills in and reads as an ``8``, too high and the same ``0`` breaks into
    #: its two side strokes and reads as ``11``. Both failures are confident and
    #: stable over time, so agreeing with itself frame after frame does not
    #: catch them — but they land on different values at different cuts, and
    #: requiring the cuts to agree does. Measured on the 07-15 venue, whose
    #: glyphs are 10 px wide featureless pills, this is the difference between
    #: reporting 1-1 for a 0-0 panel at 0.92 agreement and declining to read.
    core_fractions: Tuple[float, ...] = (0.35, 0.45, 0.55)

    #: Least spread, in value levels, between the dimmest and brightest red
    #: pixel before a field counts as showing anything. Without it a *flat*
    #: patch — every pixel red and equally bright, which is what a fully
    #: occluded or out-of-frame ROI looks like — has Otsu split it into halves
    #: of nothing and the whole rectangle comes back as one lit glyph. Measured
    #: on calibrated venues the real spread is 90-110 levels, so 25 rejects the
    #: degenerate case without coming near a genuine reading.
    min_contrast: int = 25

    #: Too few core pixels to be a lit glyph at all: the field reads as blank.
    #: A blank field is a legitimate reading (an unlit tens digit) but it is not
    #: a digit, so it must not be handed to the segment decoder.
    min_core_pixels: int = 10

    #: A digit's bounding box must span at least this fraction of the ROI's
    #: height. Discards specks, the period-counter dots and the top edge of the
    #: housing, all of which are short.
    min_digit_height_fraction: float = 0.40

    #: Columns this far apart or closer belong to the same digit. A 7-segment
    #: glyph can break into unconnected strokes, so components are grouped by
    #: horizontal span rather than by connectivity.
    digit_gap_px: int = 2

    #: A field wider than this many digits is not a score — the ROI has drifted
    #: onto the period counter or the neighbouring side, and any number read out
    #: of it would be fiction.
    max_digits: int = 2

    #: Below this width-to-height ratio the glyph is a ``1``. Checked before any
    #: template match because a ``1`` is a bare vertical stroke, and cropping it
    #: to its own ink makes it a solid rectangle that resembles nothing.
    one_aspect_max: float = 0.42

    #: Least correlation with a font glyph that counts as recognising it. Both
    #: sides of the product are unit-normalised, so this is a cosine: 1.0 is a
    #: perfect shape match and 0.0 is no relationship at all.
    match_min: float = 0.55

    #: How far the best match must beat the runner-up. Two glyphs scoring alike
    #: means the mask is too damaged to tell them apart, which is the exact
    #: situation a confident answer would be wrong in.
    match_margin: float = 0.08

    #: Settled reads needed on each side before a value is offered at all.
    min_samples: int = 4

    #: Largest italic slant, in pixels of drift per row, that will be corrected.
    #: A field whose apparent slant exceeds this is not an italic display, it is
    #: a mask full of something else, and shearing by it would only spread the
    #: mess further.
    max_slant: float = 0.5

    #: Least fraction of a side's reads that must agree on the modal value.
    #: See :meth:`StartScoreReader.read`.
    min_agreement: float = 0.70


@dataclass(frozen=True)
class MachineProfile:
    """Panel-relative geometry for one model of scoring machine at one zoom.

    ``lamp_rois`` needs ``left`` and ``right``; each covers that fencer's pair of
    small round lamps (valid + off-target) as a single region, because what
    matters is the colour of whichever one of the pair is lit.

    ``pillar_rois`` are the large repeater columns. They are optional and are
    skipped automatically on any frame where they fall outside the crop, which
    is the normal case on a tight crop — their y offsets are negative, i.e.
    *above* the housing.

    ``lamp_config`` overrides the caller's :class:`LampConfig` for this machine.
    It exists because "how bright is an unlit lens" and "how much hue survives in
    a lit one" are properties of the machine and its exposure, exactly like the
    ROIs — not of the caller. On the 2026-07-15 venue the unlit lenses are white
    plastic under bright hall light and sit at 0.31 saturated fraction, so the
    default ``on_fraction`` of 0.3 reads every frame as lit; and its green lamp
    is washed out badly enough that only 0.4-0.6 of the halo keeps a green hue
    against the default 0.5 requirement. Leaving this ``None`` keeps the caller's
    config, which is what every previously calibrated venue does.
    """

    name: str
    housing_size: Tuple[int, int]
    lamp_rois: Mapping[str, Rect]
    digit_rois: Mapping[str, Rect]
    pillar_rois: Mapping[str, Rect] = field(default_factory=dict)
    lamp_config: Optional["LampConfig"] = None
    #: Same idea as ``lamp_config`` for the score-digit comparison. How far apart
    #: two settled masks of the *same* number land depends on how many pixels the
    #: glyph spans and how often a fencer crosses in front of it, both of which
    #: are properties of this camera on this box. ``None`` keeps the caller's.
    score_config: Optional["ScoreChangeConfig"] = None
    #: Same idea again for reading the digits' *values*. ``None`` keeps the
    #: caller's :class:`DigitReadConfig`.
    read_config: Optional["DigitReadConfig"] = None

    def __post_init__(self) -> None:
        for label, rois in (("lamp_rois", self.lamp_rois), ("digit_rois", self.digit_rois)):
            missing = [s for s in SIDES if s not in rois]
            if missing:
                raise ValueError(
                    f"{self.name}: {label} is missing {', '.join(missing)}"
                )


#: Measured on the 2026-08-15 domestic-venue footage (both reference videos, same
#: machine and same camera zoom). A different venue, machine model or zoom needs
#: its own entry — one calibration per venue, not per bout.
KOR_DOMESTIC_V1 = MachineProfile(
    name="kor_domestic_v1",
    housing_size=(160, 100),
    lamp_rois={LEFT: (25, 18, 56, 20), RIGHT: (86, 18, 56, 20)},
    digit_rois={LEFT: (28, 52, 36, 40), RIGHT: (118, 52, 36, 40)},
    pillar_rois={LEFT: (5, -105, 24, 50), RIGHT: (140, -105, 24, 50)},
)

#: Measured on the 2026-08-16 venue (``260816_venue2_bout``, piste 12). A
#: different machine, not just a different camera: a free-standing post with two
#: white repeater cylinders on top, four round lamps in a row, and a **two-digit**
#: score field per side. The housing template deliberately spans the black
#: U-frame as well as the lamps, because the frame is rigid and the digits are
#: not.
#:
#: The two-digit score field is why ``digit_rois`` here are wider than
#: :data:`KOR_DOMESTIC_V1`'s: the ROI covers a side's whole field rather than one
#: glyph, so a bout that passes 9 does not walk out of the region being watched.
#:
#: ``housing_size`` spans the whole panel — lamps, clock and digits included —
#: and that is deliberate even though those all change. A smaller template of
#: just the rigid black cross-bar looks far better by lock rate (96 % vs 44 %)
#: and is much worse: a plain horizontal bar also matches the piste's painted
#: boundary line, so the tracker latches onto bare floor and reads lamps there.
#: Scored by the only metric that matters — of the frames it claims, how many
#: are actually on a lit display — the bar manages 29 % and the full panel
#: 99.7 %. Lock rate rewards a template for matching anything; precision does
#: not.
KOR_DOMESTIC_V2 = MachineProfile(
    name="kor_domestic_v2",
    housing_size=(200, 140),
    lamp_rois={LEFT: (24, 48, 72, 32), RIGHT: (99, 48, 74, 32)},
    digit_rois={LEFT: (24, 104, 52, 34), RIGHT: (114, 104, 52, 34)},
    pillar_rois={LEFT: (0, -100, 28, 75), RIGHT: (170, -97, 32, 75)},
)

#: Measured on the 2026-07-16 venue (``260716`` DE footage, piste 3). Same style
#: of panel as :data:`KOR_DOMESTIC_V1` — four round lamps in a row over a clock
#: row over a two-digit-per-side score row — but shot from much further away, so
#: every feature is roughly a third of the size it is there: a score glyph spans
#: ~20x33 px instead of ~36x40, and the whole housing is 142x90.
#:
#: Two things about this venue that the geometry has to respect:
#:
#: * There is a small always-lit white indicator between the two lamp pairs, at
#:   the bottom of the lamp row. The lamp ROIs are therefore shorter than the
#:   lamps themselves (22 px of a ~24 px oval, top-aligned) so that the
#:   indicator's saturated pixels cannot be counted as a lamp activation.
#: * The score field is two digits per side with a *period* digit between them.
#:   The digit ROIs stop well short of it on both sides — a wider ROI would read
#:   the period counter as part of somebody's score.
#:
#: Measured lamp separation on set 1 (76 sampled frames): unlit ROIs sit at
#: 0.08-0.14 saturated fraction and lit ones at 0.33-0.58, so the default
#: ``LampConfig.on_fraction`` of 0.3 lands in the gap. Chromatic halo fractions
#: are 0.90-0.93 for red and 0.65-0.91 for green against 0.00-0.04 for white.
KOR_DOMESTIC_V3 = MachineProfile(
    name="kor_domestic_v3",
    housing_size=(142, 90),
    lamp_rois={LEFT: (7, 6, 62, 22), RIGHT: (74, 6, 62, 22)},
    digit_rois={LEFT: (8, 50, 36, 38), RIGHT: (93, 50, 41, 38)},
)

#: The 2026-07-15 pool venue, piste 2, first framing (``260715`` bout A). Same
#: machine family as :data:`KOR_DOMESTIC_V1` — four lenses in a row over a clock
#: row over a one-digit-per-side score row with a period digit between them.
#:
#: What is different here is photometric, not geometric, and it is why this
#: profile carries its own :class:`LampConfig`. Measured over the whole bout at
#: the ROIs below:
#:
#: * Unlit lenses are white plastic under bright hall light: saturated fraction
#:   0.31 median (left) / 0.27 (right), against 0.50-0.58 for a lit red lamp and
#:   0.77-0.86 for a lit green one. ``on_fraction`` therefore moves to 0.45,
#:   which sits between the unlit p90 (0.38) and the dimmest lit event (0.50).
#: * The green lamp is close to blown out, so its halo keeps little saturation:
#:   at the default ``halo_saturation_min`` of 40 its green fraction is only
#:   0.16-0.30 and every right-side valid hit would be filed as off-target. At 30
#:   it reads 0.40-0.58, against 0.81-0.96 for red and 0.00 for a white lamp — so
#:   ``colour_fraction`` drops to 0.35, still far above anything a white lamp
#:   produces.
#:
#: Both lenses of a side glow together when either fires, which is why the ROIs
#: stay per-side pairs. They stop above the always-lit white indicator that sits
#: between the pairs, at the bottom of the lamp row.
KOR_DOMESTIC_260715_P2A = MachineProfile(
    name="kor_domestic_260715_p2a",
    housing_size=(158, 100),
    lamp_rois={LEFT: (22, 26, 57, 16), RIGHT: (79, 26, 58, 16)},
    digit_rois={LEFT: (18, 62, 42, 34), RIGHT: (98, 62, 44, 34)},
    lamp_config=LampConfig(
        on_fraction=0.45, halo_saturation_min=30, colour_fraction=0.35
    ),
)

#: The same venue and machine as :data:`KOR_DOMESTIC_260715_P2A`, filmed closer
#: (bout B): the housing spans 160x108 instead of 158x100 and every feature moves
#: with it, so it needs its own entry even though nothing about the machine
#: changed.
#:
#: Two thresholds differ from bout A's, both measured on this bout:
#:
#: * ``on_fraction`` 0.40, because a lit red lamp here averages 0.41-0.51 rather
#:   than 0.50-0.58 while the unlit lenses sit lower too (0.26 median, p90 0.36).
#: * ``merge_gap_frames`` 20, because at that margin single frames of a real
#:   activation dip under the threshold; the default 12 split one 2.3 s red event
#:   into three fragments 16 frames apart. Nothing here is near 20 frames of
#:   genuine separation — every activation on both bouts runs 69 frames.
#: It also needs its own ``similarity_min``. Measured across all fourteen lamp
#: events of this bout, a side whose number changed scores 0.194-0.275 and a side
#: whose number did not scores 0.571-0.872 — so the default 0.78 sits *inside*
#: the unchanged population and reports a change on almost every event, which
#: then contradicts the lamp and is discarded as inconsistent. 0.50 sits in the
#: empty band. The reason the unchanged scores run so low here is this camera:
#: it is close enough that a fencer crosses the panel often, and the digits are
#: 1s and 0s whose thin masks lose more overlap to that than a fat glyph would.
KOR_DOMESTIC_260715_P2B = MachineProfile(
    name="kor_domestic_260715_p2b",
    housing_size=(160, 108),
    lamp_rois={LEFT: (15, 27, 66, 18), RIGHT: (81, 27, 66, 18)},
    digit_rois={LEFT: (18, 70, 36, 36), RIGHT: (108, 69, 36, 36)},
    lamp_config=LampConfig(
        on_fraction=0.40, halo_saturation_min=30, colour_fraction=0.35,
        merge_gap_frames=20,
    ),
    score_config=ScoreChangeConfig(similarity_min=0.50),
)

#: The 2026-07-16 venue seen from piste 9 (``260716`` DE set 1). Same hall as
#: :data:`KOR_DOMESTIC_V3`, which was calibrated from piste 3, but a different
#: machine at a different distance — the housing is 148x88 against that one's
#: 142x90 and the features sit a few pixels differently inside it, so the two are
#: not interchangeable.
#:
#: Unlit lenses read 0.33 (left) / 0.29 (right) saturated fraction against
#: 0.54-0.59 for red and 0.67-0.81 for green, so ``on_fraction`` is 0.45 here as
#: well. The colour thresholds are relaxed for the same reason as the 07-15
#: venue: at ``halo_saturation_min`` 30 green reads 0.55-0.87 and red 0.57-0.95,
#: while white lamps read exactly 0.00 on both counts.
KOR_DOMESTIC_260716_P9 = MachineProfile(
    name="kor_domestic_260716_p9",
    housing_size=(148, 88),
    lamp_rois={LEFT: (14, 11, 60, 16), RIGHT: (74, 11, 60, 16)},
    digit_rois={LEFT: (12, 48, 40, 32), RIGHT: (100, 48, 38, 32)},
    lamp_config=LampConfig(
        on_fraction=0.45, halo_saturation_min=30, colour_fraction=0.35
    ),
)

#: The 2026-08-28 venue (김창환배), piste 6. A free-standing post like
#: :data:`KOR_DOMESTIC_V2`, but a different machine and a much wider shot: the
#: whole panel spans 166x106 px and one score glyph ~27x32.
#:
#: ``housing_size`` spans the black panel plus a slice of the green U-frame arms
#: on either side. The arms are the rigid part; the lamps and digits inside them
#: change constantly, and including them is the same trade :data:`KOR_DOMESTIC_V2`
#: documents — a template of only the rigid frame is a plain dark bar, and a plain
#: dark bar also matches the piste's painted boundary lines, which run right
#: across this crop.
#:
#: The lamp ROIs stop short of the always-lit white indicator that sits between
#: the two pairs (crop x 373-382, y >= 349): they end at y-offset 48, i.e. above
#: it, the same guard :data:`KOR_DOMESTIC_V3` uses.
#:
#: Measured over the whole bout (2,998 sampled frames) at these ROIs:
#:
#: * Saturated fraction: unlit 0.12-0.16 (p5-p75 both sides), lit 0.49-0.70. The
#:   default ``on_fraction`` of 0.3 sits in the middle of that gap, so it stands.
#: * ``colour_fraction`` is the one threshold that had to move, and it moves
#:   **up**. Each side's ROI covers that fencer's valid lamp *and* its off-target
#:   lamp, and this box blooms enough that a lit off-target lamp floods the whole
#:   ROI. Its halo then picks up a variable amount of red from the score digits
#:   glowing right below: the five off-target activations measure 0.00, 0.22,
#:   0.27, 0.30 and 0.54 red. Genuine chromatic activations measure 0.96-1.00 red
#:   (six left events) and 1.00 green (two right events), so 0.75 sits in an empty
#:   band twice as wide as it needs to be, while the default 0.3 would file three
#:   off-target lamps as red hits. The default is low for the opposite venue —
#:   ``kor_domestic_v3``, where the panel is far away and an unlit neighbour lamp
#:   dilutes the hue — and that dilution does not happen at this distance.
#: * ``merge_gap_frames`` drops to 6, because this box does not hold a lamp on:
#:   it drives every activation for exactly 69-70 frames and re-fires while the
#:   referee has not reset, so a held lamp arrives as a chain of 69-frame
#:   activations **1 frame** apart. Every gap measured over the bout is either
#:   that 1 frame or >= 11, with nothing in between, so 6 splits genuinely
#:   separate lamps while still stitching the chains. The default 12 does not:
#:   the bout's last red activation (frames 5769-5837) is followed 11 frames
#:   later by an off-target white one (5849-5917), and merging them averages a
#:   1.00 red halo with a 0.00 one into a single "white" event — which silently
#:   deletes the winning touch. Their saturated fractions differ too (0.555 vs
#:   0.659), i.e. they are two different lenses, not one lamp with a dropout.
#:
#: Known limit: ``digit_rois`` frame the **one-digit** score fields this pool bout
#: uses. The period digit sits between them (crop x 368-395) and a two-digit score
#: would grow toward it, so a DE at this venue needs the ROIs re-measured on
#: footage that actually shows a two-digit score rather than widened by guess.
KOR_DOMESTIC_260828_P6 = MachineProfile(
    name="kor_domestic_260828_p6",
    housing_size=(166, 106),
    lamp_rois={LEFT: (18, 28, 52, 20), RIGHT: (81, 28, 50, 20)},
    digit_rois={LEFT: (11, 66, 34, 35), RIGHT: (105, 66, 33, 35)},
    lamp_config=LampConfig(colour_fraction=0.75, merge_gap_frames=6),
)

MACHINE_PROFILES: Dict[str, MachineProfile] = {
    KOR_DOMESTIC_V1.name: KOR_DOMESTIC_V1,
    KOR_DOMESTIC_V2.name: KOR_DOMESTIC_V2,
    KOR_DOMESTIC_V3.name: KOR_DOMESTIC_V3,
    KOR_DOMESTIC_260715_P2A.name: KOR_DOMESTIC_260715_P2A,
    KOR_DOMESTIC_260715_P2B.name: KOR_DOMESTIC_260715_P2B,
    KOR_DOMESTIC_260716_P9.name: KOR_DOMESTIC_260716_P9,
    KOR_DOMESTIC_260828_P6.name: KOR_DOMESTIC_260828_P6,
}

#: Housing/placard template rectangles on frame 0 of each reference video, in
#: that video's own scoreboard-crop coordinates. Callers normally get these from
#: the piste config's ``tracker`` block; this is the fallback for the two videos
#: the thresholds above were measured on.
DEFAULT_PLACARD_SIZE = (56, 60)


def get_machine_profile(name: str) -> MachineProfile:
    """Look up a machine profile by name, listing the alternatives on a miss."""
    try:
        return MACHINE_PROFILES[name]
    except KeyError:
        raise KeyError(
            f"unknown machine profile {name!r}; known: "
            f"{', '.join(sorted(MACHINE_PROFILES))}"
        ) from None


# ----------------------------------------------------------------------
# Pure geometry / pixel helpers
# ----------------------------------------------------------------------


def to_gray(frame: np.ndarray) -> np.ndarray:
    """Grayscale view of a BGR or already-gray frame."""
    if frame.ndim == 2:
        return frame
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def match_template(
    gray: np.ndarray,
    template: np.ndarray,
    origin: Optional[Tuple[int, int]] = None,
    pad: Optional[int] = None,
) -> Optional[Tuple[float, Tuple[int, int]]]:
    """Best ``TM_CCOEFF_NORMED`` match of ``template``, in whole-frame coords.

    With ``origin``/``pad`` the search is confined to a window of that padding
    around the given top-left corner; without them the whole frame is searched.
    Returns ``None`` when the search area cannot contain the template at all,
    which is the caller's cue that the panel has left the frame rather than that
    the match was merely poor.
    """
    frame_h, frame_w = gray.shape[:2]
    tmpl_h, tmpl_w = template.shape[:2]

    if origin is None or pad is None:
        x0, y0, x1, y1 = 0, 0, frame_w, frame_h
    else:
        cx, cy = origin
        x0, y0 = max(0, cx - pad), max(0, cy - pad)
        x1, y1 = min(frame_w, cx + tmpl_w + pad), min(frame_h, cy + tmpl_h + pad)

    window = gray[y0:y1, x0:x1]
    if window.shape[0] < tmpl_h or window.shape[1] < tmpl_w:
        return None

    result = cv2.matchTemplate(window, template, cv2.TM_CCOEFF_NORMED)
    _, best, _, location = cv2.minMaxLoc(result)
    return float(best), (x0 + int(location[0]), y0 + int(location[1]))


def absolute_roi(origin: Tuple[int, int], roi: Rect) -> Rect:
    """Panel-relative ROI → frame-absolute ROI."""
    x, y = origin
    rx, ry, rw, rh = roi
    return (x + rx, y + ry, rw, rh)


def roi_fully_visible(roi: Rect, frame_shape: Sequence[int]) -> bool:
    """True when every pixel of ``roi`` lies inside a frame of ``frame_shape``.

    Partial visibility is treated as invisible on purpose: a lamp ROI clipped by
    the frame edge still produces a plausible-looking saturation fraction from
    whatever survives, and that number is not a lamp reading.
    """
    x, y, w, h = roi
    frame_h, frame_w = int(frame_shape[0]), int(frame_shape[1])
    return x >= 0 and y >= 0 and x + w <= frame_w and y + h <= frame_h


def crop_roi(image: np.ndarray, roi: Rect) -> Optional[np.ndarray]:
    """``image[roi]`` when the ROI is fully inside the image, else ``None``."""
    if not roi_fully_visible(roi, image.shape):
        return None
    x, y, w, h = roi
    return image[y:y + h, x:x + w]


# ----------------------------------------------------------------------
# Panel tracking
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class PanelTrack:
    """Where the panel was on one frame, and how much to believe it."""

    frame: int
    x: int
    y: int
    corr: float
    #: ``"housing"`` / ``"placard"`` — which tracker produced the position — or
    #: ``"lost"`` when neither reached :attr:`TrackerConfig.reacquire_corr` and
    #: the position is the last known one carried forward.
    source: str

    @property
    def origin(self) -> Tuple[int, int]:
        return (self.x, self.y)

    @property
    def locked(self) -> bool:
        """Whether the position may be read from.

        ``"disputed"`` counts as unlocked: the trackers contradict each other, so
        the position is reported for diagnosis but nothing may be measured at it.
        """
        return self.source not in ("lost", "disputed")


class PanelTracker:
    """Follow the scoreboard panel frame by frame.

    Two templates are tracked independently and fused. The housing is the
    primary — it contains the lamps and digits, so its correlation is the direct
    measure of whether the regions we care about are being addressed correctly.
    The placard below it is the backup, and it earns its keep exactly when the
    housing does not: when the panel drifts far enough up that the housing is
    clipped by the top of the crop, the placard is still fully visible, and it
    carried 99.65 % fused lock on the video where the housing alone managed
    85.8 %.

    Feed frames in order with :meth:`update`; seeking backwards invalidates the
    search-window assumption.
    """

    def __init__(
        self,
        housing_template: np.ndarray,
        housing_origin: Tuple[int, int],
        placard_template: Optional[np.ndarray] = None,
        placard_origin: Optional[Tuple[int, int]] = None,
        config: TrackerConfig = TrackerConfig(),
    ) -> None:
        if housing_template is None or housing_template.size == 0:
            raise ValueError("housing template is empty")
        self.config = config
        self._housing = to_gray(housing_template)
        self._placard = to_gray(placard_template) if placard_template is not None else None

        self._housing_pos = (int(housing_origin[0]), int(housing_origin[1]))
        if self._placard is not None:
            if placard_origin is None:
                raise ValueError("placard_origin is required when a placard template is given")
            self._placard_pos = (int(placard_origin[0]), int(placard_origin[1]))
            #: housing_origin - placard_origin, held fixed. Both templates are cut
            #: from one rigid object, so this offset is a constant of the scene;
            #: measured drift between the two trackers is 1 px median / 2 px p95.
            self._placard_to_housing = (
                self._housing_pos[0] - self._placard_pos[0],
                self._housing_pos[1] - self._placard_pos[1],
            )
        else:
            self._placard_pos = None
            self._placard_to_housing = None

        self._frame_index = -1

    @classmethod
    def from_frame(
        cls,
        frame: np.ndarray,
        housing_bbox: Rect,
        placard_bbox: Optional[Rect] = None,
        config: TrackerConfig = TrackerConfig(),
    ) -> "PanelTracker":
        """Cut both templates out of ``frame`` at the given rectangles.

        The frame should be one where every lamp is off: the lamp ROIs sit
        *inside* the housing rectangle, so a template cut while a lamp is lit
        carries that lamp's glare and correlates worse for the rest of the bout.
        :func:`select_template_frame` picks such a frame.
        """
        gray = to_gray(frame)
        housing = crop_roi(gray, housing_bbox)
        if housing is None:
            raise ValueError(
                f"housing bbox {housing_bbox} is not fully inside a "
                f"{gray.shape[1]}x{gray.shape[0]} frame"
            )
        placard = None
        placard_origin = None
        if placard_bbox is not None:
            placard = crop_roi(gray, placard_bbox)
            if placard is None:
                raise ValueError(
                    f"placard bbox {placard_bbox} is not fully inside a "
                    f"{gray.shape[1]}x{gray.shape[0]} frame"
                )
            placard_origin = (placard_bbox[0], placard_bbox[1])
        return cls(
            housing_template=housing.copy(),
            housing_origin=(housing_bbox[0], housing_bbox[1]),
            placard_template=None if placard is None else placard.copy(),
            placard_origin=placard_origin,
            config=config,
        )

    def _track_one(
        self,
        gray: np.ndarray,
        template: np.ndarray,
        previous: Tuple[int, int],
    ) -> Tuple[float, Tuple[int, int]]:
        """Local search, escalating to a full-frame search when it looks lost."""
        cfg = self.config
        local = match_template(gray, template, previous, cfg.search_pad)
        if local is not None and local[0] >= cfg.reacquire_corr:
            return local
        full = match_template(gray, template, None, None)
        if full is None:
            return (local[0], local[1]) if local is not None else (0.0, previous)
        if local is None or full[0] > local[0]:
            return full
        return local

    def update(self, frame: np.ndarray) -> PanelTrack:
        """Locate the panel in the next frame and return the fused position."""
        cfg = self.config
        gray = to_gray(frame)
        self._frame_index += 1

        housing_corr, housing_pos = self._track_one(gray, self._housing, self._housing_pos)
        if housing_corr >= cfg.reacquire_corr:
            self._housing_pos = housing_pos

        placard_corr = 0.0
        placard_implied: Optional[Tuple[int, int]] = None
        if self._placard is not None:
            placard_corr, placard_pos = self._track_one(gray, self._placard, self._placard_pos)
            if placard_corr >= cfg.reacquire_corr:
                self._placard_pos = placard_pos
            placard_implied = (
                placard_pos[0] + self._placard_to_housing[0],
                placard_pos[1] + self._placard_to_housing[1],
            )

        # Two rigidly-connected templates must agree about where the panel is.
        # Correlation alone cannot tell a real lock from a convincing impostor:
        # on 260816_venue2_bout a template of the machine's black cross-bar scored 0.87
        # against the piste's boundary line with the panel nowhere in the frame,
        # and every lamp "read" from that position was invented. Agreement is the
        # check correlation cannot do for itself — the two templates are cut from
        # one rigid object, so on the reference videos they agree to 1 px median
        # and 2 px p95, and any real disagreement means at least one is wrong.
        if placard_implied is not None and housing_corr >= cfg.lock_corr and placard_corr >= cfg.lock_corr:
            disagreement = max(
                abs(housing_pos[0] - placard_implied[0]),
                abs(housing_pos[1] - placard_implied[1]),
            )
            if disagreement > cfg.max_disagreement_px:
                return PanelTrack(self._frame_index, housing_pos[0], housing_pos[1],
                                  min(housing_corr, placard_corr), "disputed")

        # Housing wins whenever it is locked: it is the template whose own
        # correlation vouches for the pixels the lamps are read from.
        if housing_corr >= cfg.lock_corr:
            return PanelTrack(self._frame_index, housing_pos[0], housing_pos[1],
                              housing_corr, "housing")
        if placard_implied is not None and placard_corr >= cfg.lock_corr:
            # The placard vouches for the panel's position even when the housing
            # itself is clipped or occluded, so the implied origin is usable and
            # may legitimately fall outside the frame.
            self._housing_pos = placard_implied
            return PanelTrack(self._frame_index, placard_implied[0], placard_implied[1],
                              placard_corr, "placard")

        best_corr, best_pos, best_source = housing_corr, housing_pos, "housing"
        if placard_implied is not None and placard_corr > best_corr:
            best_corr, best_pos, best_source = placard_corr, placard_implied, "placard"
        if best_corr < cfg.reacquire_corr:
            best_source = "lost"
        return PanelTrack(self._frame_index, best_pos[0], best_pos[1], best_corr, best_source)


def lamp_activity(hsv: np.ndarray, roi: Rect, config: LampConfig) -> Optional[float]:
    """Saturated-pixel fraction of a lamp ROI, or ``None`` when it is off-frame."""
    patch = crop_roi(hsv, roi)
    if patch is None or patch.size == 0:
        return None
    return float((patch[:, :, 2] >= config.core_value_min).mean())


def select_template_frame(
    activities: Sequence[Optional[float]],
) -> int:
    """Index of the frame with the least lamp glare, for cutting templates from.

    ``activities`` is one saturated-fraction reading per candidate frame (see
    :func:`lamp_activity`), summed over the lamp ROIs; ``None`` marks a frame
    where the lamps could not be measured. Frame 0 is the answer for a clip that
    starts between touches, which is the normal case — this exists for the clip
    that starts mid-activation, where frame 0 would bake a lit lamp into the
    template.
    """
    best_index = 0
    best_value: Optional[float] = None
    for index, value in enumerate(activities):
        if value is None:
            continue
        if best_value is None or value < best_value:
            best_index, best_value = index, value
    return best_index


# ----------------------------------------------------------------------
# Lamp reading
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class LampSample:
    """One side's lamp pair on one frame."""

    on: bool
    sat_frac: float
    red_frac: float
    green_frac: float


def read_lamp(hsv_patch: np.ndarray, config: LampConfig) -> LampSample:
    """Measure one lamp ROI: lit from the core, colour from the halo."""
    hue = hsv_patch[:, :, 0]
    sat = hsv_patch[:, :, 1]
    val = hsv_patch[:, :, 2]

    sat_frac = float((val >= config.core_value_min).mean())

    halo = (val >= config.halo_value_min) & (val <= config.halo_value_max)
    chromatic = halo & (sat >= config.halo_saturation_min)
    halo_count = int(halo.sum())
    if halo_count == 0:
        return LampSample(sat_frac >= config.on_fraction, sat_frac, 0.0, 0.0)

    is_red = ((hue <= config.red_hue_max) | (hue >= config.red_hue_min)) & chromatic
    is_green = (hue >= config.green_hue_min) & (hue <= config.green_hue_max) & chromatic
    return LampSample(
        on=sat_frac >= config.on_fraction,
        sat_frac=sat_frac,
        red_frac=float(int(is_red.sum()) / halo_count),
        green_frac=float(int(is_green.sum()) / halo_count),
    )


def classify_colour(
    samples: Sequence[LampSample],
    config: LampConfig,
) -> Optional[str]:
    """Colour of a lamp across the frames it was lit for.

    ``None`` when the lamp was never lit. Otherwise ``"red"``/``"green"`` when
    the mean halo hue fraction clears :attr:`LampConfig.colour_fraction`, and
    ``"white"`` when neither does — a positive reading of an off-target lamp, not
    a shrug.
    """
    lit = [s for s in samples if s.on]
    if not lit:
        return None
    red = sum(s.red_frac for s in lit) / len(lit)
    green = sum(s.green_frac for s in lit) / len(lit)
    if red >= config.colour_fraction and red >= green:
        return COLOUR_RED
    if green >= config.colour_fraction:
        return COLOUR_GREEN
    return COLOUR_WHITE


def merge_runs(
    active: Sequence[bool],
    min_length: int,
    max_gap: int,
) -> List[Tuple[int, int]]:
    """Group ``active`` flags into inclusive ``(start, end)`` runs.

    Runs separated by ``max_gap`` inactive frames or fewer are merged — a lamp
    that flickers off for three frames mid-activation is one event — and runs
    shorter than ``min_length`` after merging are dropped as artefacts. Indices
    are positions in ``active``; the caller maps them back to frame numbers.
    """
    runs: List[List[int]] = []
    for index, flag in enumerate(active):
        if not flag:
            continue
        if runs and index - runs[-1][1] - 1 <= max_gap:
            runs[-1][1] = index
        else:
            runs.append([index, index])
    return [(s, e) for s, e in runs if e - s + 1 >= min_length]


@dataclass(frozen=True)
class CoverageGap:
    """A stretch where the lamps could not be read, and why.

    Emitted so a missing touch is visible as a missing touch. The reasons are
    physical, not diagnostic hedging: ``"off_frame"`` means the panel drifted
    past the edge of the crop and the lamp pixels are simply not in the file
    (re-crop wider), ``"unlocked"`` means the tracker could not vouch for the
    position.
    """

    start_frame: int
    end_frame: int
    reason: str

    @property
    def frame_count(self) -> int:
        return self.end_frame - self.start_frame + 1


@dataclass(frozen=True)
class LampEvent:
    """One lamp activation, with each side's colour."""

    onset_frame: int
    end_frame: int
    left_colour: Optional[str]
    right_colour: Optional[str]

    @property
    def left_valid(self) -> bool:
        """The left fencer's chromatic lamp fired — a valid hit by the left."""
        return self.left_colour in CHROMATIC_COLOURS

    @property
    def right_valid(self) -> bool:
        return self.right_colour in CHROMATIC_COLOURS

    @property
    def both_valid(self) -> bool:
        """Both chromatic — the referee had to apply priority."""
        return self.left_valid and self.right_valid

    @property
    def any_valid(self) -> bool:
        return self.left_valid or self.right_valid


class LampEventScanner:
    """Accumulate per-frame lamp readings, then group them into events.

    Feed every frame with :meth:`feed` in order, then call :meth:`finish`.
    Frames whose track is not locked, or whose lamp ROIs are not fully inside the
    frame, are recorded as unreadable rather than read as "no lamp" — the
    difference between those two is the difference between a reported gap and a
    silently lost touch.
    """

    def __init__(
        self,
        profile: MachineProfile,
        config: LampConfig = LampConfig(),
        tracker_config: TrackerConfig = TrackerConfig(),
        score_config: ScoreChangeConfig = ScoreChangeConfig(),
    ) -> None:
        self.profile = profile
        self.config = config
        self.tracker_config = tracker_config
        self.score_config = score_config
        self._samples: Dict[str, List[Optional[LampSample]]] = {s: [] for s in SIDES}
        self._readable: List[bool] = []
        self._reasons: List[Optional[str]] = []
        self._frames: List[int] = []

    def feed(self, hsv: np.ndarray, track: PanelTrack) -> None:
        """Read both lamp ROIs on one frame."""
        self._frames.append(track.frame)

        if track.corr < self.tracker_config.lock_corr or not track.locked:
            self._append_unreadable("disputed" if track.source == "disputed" else "unlocked")
            return

        lit = display_lit_fraction(hsv, track, self.profile, self.score_config)
        if lit is not None and lit < self.score_config.display_min_fraction:
            self._append_unreadable("no_display")
            return

        patches = {}
        for side in SIDES:
            roi = absolute_roi(track.origin, self.profile.lamp_rois[side])
            patch = crop_roi(hsv, roi)
            if patch is None or patch.size == 0:
                self._append_unreadable("off_frame")
                return
            patches[side] = patch

        for side in SIDES:
            self._samples[side].append(read_lamp(patches[side], self.config))
        self._readable.append(True)
        self._reasons.append(None)

    def _append_unreadable(self, reason: str) -> None:
        for side in SIDES:
            self._samples[side].append(None)
        self._readable.append(False)
        self._reasons.append(reason)

    def finish(self) -> Tuple[List[LampEvent], List[CoverageGap]]:
        """Group the accumulated readings into events and coverage gaps."""
        active = [
            bool(readable and any(
                (self._samples[side][i] is not None and self._samples[side][i].on)
                for side in SIDES
            ))
            for i, readable in enumerate(self._readable)
        ]
        runs = merge_runs(active, self.config.min_on_frames, self.config.merge_gap_frames)

        events: List[LampEvent] = []
        for start, end in runs:
            colours = {}
            for side in SIDES:
                window = [s for s in self._samples[side][start:end + 1] if s is not None]
                colours[side] = classify_colour(window, self.config)
            events.append(LampEvent(
                onset_frame=self._frames[start],
                end_frame=self._frames[end],
                left_colour=colours[LEFT],
                right_colour=colours[RIGHT],
            ))
        return events, self._coverage_gaps()

    def _coverage_gaps(self) -> List[CoverageGap]:
        gaps: List[CoverageGap] = []
        start: Optional[int] = None
        reason: Optional[str] = None
        for index, readable in enumerate(self._readable):
            if not readable:
                if start is None:
                    start, reason = index, self._reasons[index]
                elif self._reasons[index] == "off_frame":
                    # Off-frame is the actionable reason (re-crop wider), so it
                    # wins when a gap is a mix of both.
                    reason = "off_frame"
                continue
            if start is not None:
                gaps.append(self._close_gap(start, index - 1, reason))
                start, reason = None, None
        if start is not None:
            gaps.append(self._close_gap(start, len(self._readable) - 1, reason))
        return [g for g in gaps if g.frame_count >= self.config.coverage_gap_min_frames]

    def _close_gap(self, start: int, end: int, reason: Optional[str]) -> CoverageGap:
        return CoverageGap(self._frames[start], self._frames[end], reason or "unlocked")

    @property
    def readable_frames(self) -> int:
        return sum(1 for r in self._readable if r)

    @property
    def total_frames(self) -> int:
        return len(self._readable)


# ----------------------------------------------------------------------
# Score-digit change detection
# ----------------------------------------------------------------------


def display_lit_fraction(
    hsv: np.ndarray,
    track: "PanelTrack",
    profile: MachineProfile,
    config: ScoreChangeConfig,
) -> Optional[float]:
    """Fraction of the tracked score ROIs that is lit LED, or ``None`` if unseen.

    This is the sanity check on the *track*, not on the score: wherever the
    tracker claims the panel is, a scoring box has to be glowing there.
    """
    total = 0.0
    count = 0
    for side in SIDES:
        patch = crop_roi(hsv, absolute_roi(track.origin, profile.digit_rois[side]))
        if patch is None or patch.size == 0:
            continue
        total += float(digit_mask(patch, config).mean())
        count += 1
    return total / count if count else None


def digit_mask(hsv_patch: np.ndarray, config: ScoreChangeConfig) -> np.ndarray:
    """Boolean mask of lit red 7-segment pixels in a score-digit ROI.

    The brightness cut is chosen per ROI by Otsu's method rather than fixed,
    because "how bright is a lit segment" is not a property of scoreboards — it
    is a property of this box, this exposure and this camera distance. A fixed
    cut calibrated on one venue produced clean legible digits there and torn
    stroke fragments on the next, whose LEDs read dimmer (95th percentile of
    red-pixel value 222, i.e. most lit pixels below the old 200 threshold). The
    split between lit and unlit is bimodal and obvious *within* any one ROI, so
    letting the ROI choose it transfers where a constant does not.

    Two guards remain fixed. The hue/saturation test still runs first, so Otsu
    only ever splits pixels that are already red — it can never promote a white
    highlight to a digit. And the cut is floored, because Otsu on an ROI holding
    no lit segment at all would happily split the unlit ghost glow (segments
    that are off still emit faintly) into "bright" and "dark" halves and invent
    a digit out of nothing.
    """
    hue = hsv_patch[:, :, 0]
    sat = hsv_patch[:, :, 1]
    val = hsv_patch[:, :, 2]
    red = ((hue <= config.digit_hue_max) | (hue >= config.digit_hue_min)) & (
        sat >= config.digit_saturation_min
    )
    if int(red.sum()) < config.digit_min_red_pixels:
        return np.zeros(val.shape, dtype=bool)

    threshold = max(_otsu_threshold(val[red]), config.digit_value_min)
    return red & (val >= threshold)


def _otsu_threshold(values: np.ndarray) -> int:
    """Otsu's between-class-variance split of a 1-D uint8 sample."""
    sample = np.ascontiguousarray(values, dtype=np.uint8).reshape(-1, 1)
    threshold, _ = cv2.threshold(sample, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return int(threshold)


def mask_similarity(a: np.ndarray, b: np.ndarray, align_radius: int) -> float:
    """Best Jaccard overlap of two digit masks over small integer shifts.

    The shift search is what makes this usable on a tracked ROI: the position is
    accurate to 1–2 px, and for a stroke as thin as a ``1`` that jitter alone
    drags the overlap below any useful threshold.

    Overlap rather than correlation because correlation on a mostly-empty ROI is
    dominated by the shared background, which is exactly the regime here: it
    scored a genuine ``1`` → ``2`` change at 0.93, indistinguishable from no
    change at all.

    Returns 1.0 for two empty masks (a dark ROI is unchanged, not changed), and
    0.0 when only one is empty.
    """
    if a.shape != b.shape:
        return 0.0
    mask_a = np.ascontiguousarray(a, dtype=np.float32)
    mask_b = np.ascontiguousarray(b, dtype=np.float32)
    count_a = float(mask_a.sum())
    count_b = float(mask_b.sum())
    if count_a == 0.0 and count_b == 0.0:
        return 1.0
    if count_a == 0.0 or count_b == 0.0:
        return 0.0

    # Both masks are 0/1, so cross-correlation *is* the intersection count at
    # each shift, and the union follows from the two fixed totals. Maximising
    # overlap is therefore maximising the correlation — one call, not 81.
    padded = cv2.copyMakeBorder(
        mask_b, align_radius, align_radius, align_radius, align_radius,
        cv2.BORDER_CONSTANT, value=0.0,
    )
    intersection = float(cv2.matchTemplate(padded, mask_a, cv2.TM_CCORR).max())
    union = count_a + count_b - intersection
    return intersection / union if union > 0 else 1.0


@dataclass(frozen=True)
class ScoreComparison:
    """Whether each side's displayed number differs across one lamp event.

    ``determined`` is false when either side had too few readable samples on one
    side of the boundary — a coverage gap, or a lamp event too close to the end
    of the clip for the box to have been updated on camera. An undetermined
    comparison is not a "no change": conflating the two is how a real touch
    disappears from a report without trace.
    """

    changed: frozenset
    determined: bool
    similarity: Mapping[str, Optional[float]]


class ScoreChangeDetector:
    """Detect *that* a score digit changed, without reading what it says.

    Each side keeps a rolling window of per-frame masks whose average — the
    settled mask — is a clean rendering of the current number, immune to the
    display's multiplexing. Settled masks are retained every
    :attr:`ScoreChangeConfig.sample_stride` frames.

    Comparison happens per lamp event, not per frame, via :meth:`compare`. A
    streaming per-frame comparison was tried first and does not work: the digits
    cross over gradually, so each frame resembles the last closely enough that a
    re-baselining reference ratchets across the transition and reports nothing.
    Comparing two well-separated *settled* intervals has no such failure mode,
    and taking the best match over several samples per interval makes it immune
    to a fencer occluding the box during any one of them.
    """

    def __init__(
        self,
        profile: MachineProfile,
        config: ScoreChangeConfig = ScoreChangeConfig(),
        tracker_config: TrackerConfig = TrackerConfig(),
    ) -> None:
        self.profile = profile
        self.config = config
        self.tracker_config = tracker_config
        self._window: Dict[str, List[np.ndarray]] = {s: [] for s in SIDES}
        self._samples: Dict[str, List[Tuple[int, np.ndarray]]] = {s: [] for s in SIDES}

    def feed(self, hsv: np.ndarray, track: PanelTrack) -> None:
        """Add one frame's score digits to each side's window."""
        if track.corr < self.tracker_config.lock_corr or not track.locked:
            return
        lit = display_lit_fraction(hsv, track, self.profile, self.config)
        if lit is not None and lit < self.config.display_min_fraction:
            return
        for side in SIDES:
            roi = absolute_roi(track.origin, self.profile.digit_rois[side])
            patch = crop_roi(hsv, roi)
            if patch is None or patch.size == 0:
                continue
            self._feed_side(side, track.frame, digit_mask(patch, self.config))

    def _feed_side(self, side: str, frame: int, mask: np.ndarray) -> None:
        window = self._window[side]
        if window and window[-1].shape != mask.shape:
            # The ROI changed size, which only happens when it was clipped by
            # the frame edge. Averaging across that boundary is meaningless.
            window.clear()
        window.append(mask.astype(np.float32))
        if len(window) > self.config.window_frames:
            window.pop(0)
        if len(window) < self.config.window_frames:
            return
        if frame % self.config.sample_stride:
            return
        settled = np.mean(window, axis=0, dtype=np.float32) >= 0.5
        self._samples[side].append((frame, settled.astype(np.float32)))

    def interval_state(self, side: str, start: int, end: int) -> List[np.ndarray]:
        """Settled masks from the tail of ``[start, end)``, latest last.

        Only the tail is used: earlier in the interval the box may not have been
        updated yet, and a sample from then shows the *previous* number, which
        would match the previous interval and hide a real point.
        """
        tail_start = max(start, end - self.config.tail_frames)
        return [m for frame, m in self._samples[side] if tail_start <= frame < end]

    def compare(self, previous: Tuple[int, int], current: Tuple[int, int]) -> ScoreComparison:
        """Compare two intervals, each given as ``(start, end)`` frames."""
        changed = set()
        similarity: Dict[str, Optional[float]] = {}
        determined = True
        for side in SIDES:
            before = self.interval_state(side, *previous)
            after = self.interval_state(side, *current)
            if len(before) < self.config.min_samples or len(after) < self.config.min_samples:
                similarity[side] = None
                determined = False
                continue
            best = max(
                mask_similarity(a, b, self.config.align_radius)
                for a in before for b in after
            )
            similarity[side] = best
            if best < self.config.similarity_min:
                changed.add(side)
        return ScoreComparison(frozenset(changed), determined, similarity)


def event_intervals(
    onsets: Sequence[int],
    total_frames: int,
    config: ScoreChangeConfig = ScoreChangeConfig(),
) -> List[Tuple[int, int]]:
    """Split a bout into the settled stretches between lamp events.

    ``len(onsets) + 1`` intervals: everything before the first lamp, then one
    per event running from ``settle_frames`` after its onset to the next onset.
    Comparing consecutive intervals answers "did the score move because of event
    *n*" without any per-frame bookkeeping.
    """
    intervals: List[Tuple[int, int]] = []
    start = 0
    for onset in onsets:
        intervals.append((start, onset))
        start = onset + config.settle_frames
    intervals.append((start, total_frames))
    return intervals


# ----------------------------------------------------------------------
# Reading the score's absolute value
# ----------------------------------------------------------------------


#: The digit shapes these panels draw, as a 5x7 dot-matrix font.
#:
#: Not 7-segment, which is what :mod:`analyzer.score_reader` assumes and what
#: this module's first attempt assumed too. Look at a ``7`` on any of the
#: reference footage: it is a top bar and a stroke slanting down to the *left*,
#: ending as a vertical under the middle of the bar. A 7-segment ``7`` is a top
#: bar and a vertical down the right-hand edge. The panels are dot-matrix
#: modules running the usual 5x7 character generator, so segment-region tests
#: score a ``7`` as a ``1`` or as nothing, whatever the threshold.
#:
#: ``0`` is a plain ring here rather than the ring-with-diagonal the classic
#: character generator draws: measured on 07-16 piste 3, the inside of a ``0``
#: is uniformly dark at every threshold, with no diagonal.
DOT_MATRIX_DIGITS: Mapping[int, Tuple[str, ...]] = {
    0: ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    1: ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    2: ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    3: ("11111", "00010", "00100", "00010", "00001", "10001", "01110"),
    4: ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    5: ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    6: ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    7: ("11111", "10001", "00001", "00010", "00100", "00100", "00100"),
    8: ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    9: ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
}

#: Grid a glyph and a template are both resampled onto before they are compared.
#: Coarse on purpose: the observed strokes are broken and a pixel or two wide,
#: so a fine grid measures stroke damage rather than shape.
DIGIT_GRID = (7, 5)


def _digit_grid_templates() -> Dict[int, np.ndarray]:
    """Each font glyph, cropped to its own ink and resampled onto the grid."""
    templates: Dict[int, np.ndarray] = {}
    for digit, rows in DOT_MATRIX_DIGITS.items():
        bitmap = np.array([[c == "1" for c in row] for row in rows], dtype=np.float32)
        columns = np.flatnonzero(bitmap.any(axis=0))
        lines = np.flatnonzero(bitmap.any(axis=1))
        cropped = bitmap[lines[0]:lines[-1] + 1, columns[0]:columns[-1] + 1]
        templates[digit] = _resample_glyph(cropped)
    return templates


def _resample_glyph(glyph: np.ndarray) -> np.ndarray:
    """Area-average a bbox-cropped glyph onto :data:`DIGIT_GRID`, mean-centred."""
    grid = cv2.resize(
        np.ascontiguousarray(glyph, dtype=np.float32),
        (DIGIT_GRID[1], DIGIT_GRID[0]),
        interpolation=cv2.INTER_AREA,
    )
    centred = grid - float(grid.mean())
    norm = float(np.linalg.norm(centred))
    return centred / norm if norm > 0 else centred


def digit_core_mask(
    hsv_patch: np.ndarray,
    config: ScoreChangeConfig,
    read_config: DigitReadConfig = DigitReadConfig(),
    core_fraction: Optional[float] = None,
) -> np.ndarray:
    """Boolean mask of the *lit cores* of a score field's segments.

    :func:`digit_mask` answers "which pixels belong to this display", which is
    what comparing two numbers needs. This answers the harder question "which
    pixels are a lit stroke", which is what reading a number needs, and it needs
    a much higher cut: inside a ``0`` the plastic glows red brightly enough to
    pass :func:`digit_mask` and fill the hole, at which point the glyph is
    indistinguishable from an ``8``.

    The cut is placed a fixed fraction of the way from :func:`digit_mask`'s Otsu
    split to the brightest red pixel in the same ROI, so it rides the exposure
    instead of being calibrated per venue. Measured on the 07-16 venue's left
    field showing ``0``: Otsu lands at 160, the brightest red pixel at 253, the
    lit strokes occupy 234-253 and the glow inside the hole 156-233. Any
    fraction from roughly 0.4 to 0.75 puts the cut inside that empty band; 0.5
    (207) is the middle of the usable range on the venues measured.
    """
    return settled_core_mask(
        red_pixels(hsv_patch, config),
        hsv_patch[:, :, 2].astype(np.float32),
        config,
        read_config,
        core_fraction,
    )


def red_pixels(hsv_patch: np.ndarray, config: ScoreChangeConfig) -> np.ndarray:
    """Mask of pixels whose hue and saturation say "lit red LED"."""
    hue = hsv_patch[:, :, 0]
    sat = hsv_patch[:, :, 1]
    return ((hue <= config.digit_hue_max) | (hue >= config.digit_hue_min)) & (
        sat >= config.digit_saturation_min
    )


def settled_core_mask(
    red: np.ndarray,
    val: np.ndarray,
    config: ScoreChangeConfig,
    read_config: DigitReadConfig = DigitReadConfig(),
    core_fraction: Optional[float] = None,
) -> np.ndarray:
    """:func:`digit_core_mask` on an already time-averaged patch.

    Split out because *when* the threshold is chosen decides whether the glyph
    survives. Thresholding each frame and averaging the results keeps only the
    pixels that clear the cut in most frames, and the digits are multiplexed, so
    on the 07-16 venue that leaves a ``7`` as a few disconnected edge fragments
    that match no template at all (best correlation 0.15). Averaging the pixels
    first and thresholding once leaves the same ``7`` whole.
    """
    if int(red.sum()) < config.digit_min_red_pixels:
        return np.zeros(val.shape, dtype=bool)
    values = val[red]
    high = float(values.max())
    if high - float(values.min()) < read_config.min_contrast:
        return np.zeros(val.shape, dtype=bool)
    low = max(_otsu_threshold(values.astype(np.uint8)), config.digit_value_min)
    if high <= low:
        return np.zeros(val.shape, dtype=bool)
    fraction = (
        core_fraction if core_fraction is not None
        else read_config.core_fractions[len(read_config.core_fractions) // 2]
    )
    core = red & (val >= low + fraction * (high - low))
    if int(core.sum()) < read_config.min_core_pixels:
        return np.zeros(val.shape, dtype=bool)
    return core


def field_slant(mask: np.ndarray, read_config: DigitReadConfig = DigitReadConfig()) -> float:
    """Pixels of horizontal drift per row of the glyphs in a score field.

    These panels draw italic digits — measured on the 07-15 venue, a ``0``'s
    centre of mass moves 4 px left over its 24 rows. Matched against upright
    templates that costs more correlation than the difference between one digit
    and another, so the field is straightened before anything is read from it.

    Estimated over the whole field rather than per glyph: it is one property of
    one display, and every extra lit pixel steadies the fit.
    """
    rows = np.flatnonzero(mask.any(axis=1))
    if rows.size < 4:
        return 0.0
    weights = mask[rows].sum(axis=1).astype(np.float64)
    centroids = (mask[rows] * np.arange(mask.shape[1])).sum(axis=1) / weights
    ys = rows.astype(np.float64)
    ys = ys - ys.mean()
    spread = float((ys * ys).sum())
    if spread <= 0:
        return 0.0
    slope = float((ys * (centroids - centroids.mean())).sum() / spread)
    return float(np.clip(slope, -read_config.max_slant, read_config.max_slant))


def deskew_mask(mask: np.ndarray, slope: float) -> np.ndarray:
    """Shear a field mask upright, widening the canvas so nothing is cut off."""
    if abs(slope) < 1e-3 or mask.size == 0:
        return mask
    height, width = mask.shape
    pad = int(np.ceil(abs(slope) * height)) + 1
    matrix = np.array([[1.0, -slope, slope * (height / 2.0) + pad], [0.0, 1.0, 0.0]])
    warped = cv2.warpAffine(
        mask.astype(np.uint8), matrix, (width + 2 * pad, height),
        flags=cv2.INTER_NEAREST, borderValue=0,
    )
    return warped.astype(bool)


def split_digit_boxes(
    mask: np.ndarray, read_config: DigitReadConfig = DigitReadConfig()
) -> List[Rect]:
    """Bounding boxes of the digits in a score-field mask, left to right.

    Grouping is by horizontal span, not by connectivity: a 7-segment glyph is
    physically several separated bars, and at this scale some of them merge and
    some do not, so "one connected blob" is not "one digit". Two strokes that
    overlap in x are the same digit; a gap wider than
    :attr:`DigitReadConfig.digit_gap_px` starts a new one.
    """
    if mask.size == 0 or not mask.any():
        return []
    height = mask.shape[0]
    min_height = max(2, int(round(height * read_config.min_digit_height_fraction)))

    columns = mask.any(axis=0)
    boxes: List[Rect] = []
    start: Optional[int] = None
    gap = 0
    for x in range(len(columns) + 1):
        lit = x < len(columns) and bool(columns[x])
        if lit:
            if start is None:
                start = x
            gap = 0
            continue
        if start is None:
            continue
        gap += 1
        if gap <= read_config.digit_gap_px and x < len(columns):
            continue
        end = x - gap + 1
        block = mask[:, start:end]
        rows = np.flatnonzero(block.any(axis=1))
        if rows.size and int(rows[-1] - rows[0] + 1) >= min_height:
            boxes.append((start, int(rows[0]), end - start, int(rows[-1] - rows[0] + 1)))
        start = None
        gap = 0
    return boxes


DIGIT_TEMPLATES: Dict[int, np.ndarray] = _digit_grid_templates()


def decode_digit(
    glyph: np.ndarray, read_config: DigitReadConfig = DigitReadConfig()
) -> Optional[int]:
    """Read one digit from a mask cropped to its own bounding box.

    A narrow box is a ``1`` and is decided on shape alone, before any matching.
    A ``1`` is a bare vertical stroke on these panels, so cropping it to its own
    ink and stretching that onto the comparison grid turns it into a solid
    rectangle that matches nothing in particular.

    Everything else is matched against :data:`DIGIT_TEMPLATES` by correlation on
    a coarse grid. ``None`` when the best match is weak, or when it barely beats
    the runner-up: two digits that score alike is exactly the situation where a
    confident answer is a wrong one.
    """
    if glyph.ndim != 2 or glyph.size == 0 or not glyph.any():
        return None
    height, width = glyph.shape
    if height < 4 or width < 1:
        return None

    if width / height < read_config.one_aspect_max:
        return 1

    sample = _resample_glyph(glyph.astype(np.float32))
    scores = {
        digit: float((sample * template).sum())
        for digit, template in DIGIT_TEMPLATES.items()
    }
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best, best_score = ranked[0]
    runner_up = ranked[1][1]
    if best_score < read_config.match_min:
        return None
    if best_score - runner_up < read_config.match_margin:
        return None
    return best


def read_digit_field(
    mask: np.ndarray, read_config: DigitReadConfig = DigitReadConfig()
) -> Optional[int]:
    """Read a whole side's score — one or two digits — from one settled mask.

    Returns ``None`` rather than a guess whenever the field does not look like a
    score: nothing lit, more digits than a score can have, or a glyph the
    segment decoder will not name. An unlit tens digit simply produces one box,
    which is why a blank field is not special-cased.
    """
    upright = deskew_mask(mask, field_slant(mask, read_config))
    boxes = split_digit_boxes(upright, read_config)
    if not boxes or len(boxes) > read_config.max_digits:
        return None
    value = 0
    for x, y, w, h in boxes:
        digit = decode_digit(upright[y:y + h, x:x + w], read_config)
        if digit is None:
            return None
        value = value * 10 + digit
    return value


@dataclass(frozen=True)
class StartScoreReading:
    """What :class:`StartScoreReader` made of the opening of a clip."""

    #: The score read, or ``None`` when the read was declined.
    score: Optional[Tuple[int, int]]
    #: Fraction of each side's reads that agreed with the value returned, taken
    #: over the side that agreed least. 0.0 when nothing was read.
    agreement: float
    #: Settled reads per side that produced any value at all.
    samples: Mapping[str, int]
    #: Frames offered to the reader, i.e. before gating.
    frames_examined: int
    #: ``"read"`` on success; otherwise why not — ``"no_samples"``,
    #: ``"too_few_samples"`` or ``"low_agreement"``.
    reason: str

    @property
    def confident(self) -> bool:
        return self.score is not None


class StartScoreReader:
    """Read the absolute score the panel shows before the first touch.

    :func:`resolve_touches` counts touches from a baseline it is told; this
    finds that baseline by reading the digits, so a clip that opens mid-bout —
    a DE second or third period, or a camera started late — reports the score
    the panel actually shows instead of one that restarts at 0-0.

    Reading is per settled mask, not per frame. The digits are multiplexed, so a
    single frame's mask is a torn fragment; averaging
    :attr:`ScoreChangeConfig.window_frames` of them gives the clean glyph that
    :class:`ScoreChangeDetector` already relies on. Several settled masks then
    vote, which is what makes the answer survive a fencer walking across the box
    or a lamp's glare washing one window out.
    """

    def __init__(
        self,
        profile: MachineProfile,
        score_config: ScoreChangeConfig = ScoreChangeConfig(),
        read_config: DigitReadConfig = DigitReadConfig(),
        tracker_config: TrackerConfig = TrackerConfig(),
    ) -> None:
        self.profile = profile
        self.score_config = score_config
        self.read_config = read_config
        self.tracker_config = tracker_config
        self._red: Dict[str, List[np.ndarray]] = {s: [] for s in SIDES}
        self._val: Dict[str, List[np.ndarray]] = {s: [] for s in SIDES}
        self._reads: Dict[str, List[Tuple[int, int]]] = {s: [] for s in SIDES}
        self._frames = 0

    def feed(self, hsv: np.ndarray, track: PanelTrack) -> None:
        """Offer one frame. Gated exactly like :meth:`ScoreChangeDetector.feed`."""
        self._frames += 1
        if track.corr < self.tracker_config.lock_corr or not track.locked:
            return
        lit = display_lit_fraction(hsv, track, self.profile, self.score_config)
        if lit is not None and lit < self.score_config.display_min_fraction:
            return
        for side in SIDES:
            patch = crop_roi(
                hsv, absolute_roi(track.origin, self.profile.digit_rois[side])
            )
            if patch is None or patch.size == 0:
                continue
            self._feed_side(side, track.frame, patch)

    def _feed_side(self, side: str, frame: int, patch: np.ndarray) -> None:
        reds, vals = self._red[side], self._val[side]
        red = red_pixels(patch, self.score_config).astype(np.float32)
        if reds and reds[-1].shape != red.shape:
            reds.clear()
            vals.clear()
        reds.append(red)
        vals.append(patch[:, :, 2].astype(np.float32))
        window = self.score_config.window_frames
        if len(reds) > window:
            reds.pop(0)
            vals.pop(0)
        if len(reds) < window or frame % self.score_config.sample_stride:
            return

        settled_red = np.mean(reds, axis=0, dtype=np.float32) >= 0.5
        settled_val = np.mean(vals, axis=0, dtype=np.float32)
        values = {
            read_digit_field(
                settled_core_mask(
                    settled_red, settled_val, self.score_config,
                    self.read_config, fraction,
                ),
                self.read_config,
            )
            for fraction in self.read_config.core_fractions
        }
        if len(values) == 1:
            value = values.pop()
            if value is not None:
                self._reads[side].append((frame, value))

    def read(self, before_frame: Optional[int] = None) -> StartScoreReading:
        """Modal value per side over the reads taken before ``before_frame``.

        ``before_frame`` is normally the first lamp event's onset, because that
        is the moment the tally starts counting: a read taken after it would
        already include the touch the tally is about to add, and the score would
        come out one too high. Passing ``None`` uses everything fed.

        The answer is declined — ``score is None`` — when either side produced
        fewer than :attr:`DigitReadConfig.min_samples` reads or when the modal
        value carries less than :attr:`DigitReadConfig.min_agreement` of them.
        A wrong baseline is worse than no baseline: it shifts every score in the
        report and, unlike a missing one, nothing downstream can tell.
        """
        modes: Dict[str, Optional[int]] = {}
        counts: Dict[str, int] = {}
        agreements: List[float] = []
        for side in SIDES:
            reads = [
                value for frame, value in self._reads[side]
                if before_frame is None or frame < before_frame
            ]
            counts[side] = len(reads)
            if not reads:
                modes[side] = None
                continue
            values, tallies = np.unique(np.asarray(reads), return_counts=True)
            best = int(np.argmax(tallies))
            modes[side] = int(values[best])
            agreements.append(float(tallies[best]) / len(reads))

        agreement = min(agreements) if len(agreements) == len(SIDES) else 0.0
        if any(counts[s] == 0 for s in SIDES):
            reason = "no_samples"
        elif any(counts[s] < self.read_config.min_samples for s in SIDES):
            reason = "too_few_samples"
        elif agreement < self.read_config.min_agreement:
            reason = "low_agreement"
        else:
            reason = "read"

        score = (
            (int(modes[LEFT]), int(modes[RIGHT])) if reason == "read" else None
        )
        return StartScoreReading(
            score=score,
            agreement=agreement,
            samples=dict(counts),
            frames_examined=self._frames,
            reason=reason,
        )


# ----------------------------------------------------------------------
# Cross-validation: lamp event + score change → touch
# ----------------------------------------------------------------------


#: How long after a valid lamp a score entry can still be credited to it when
#: only off-target lamps came in between — see :func:`resolve_touches`.
#:
#: Note what it bounds. Not the score change directly — the digits carry no
#: timestamp — but the samples the change is read from, because
#: :func:`late_entry_comparisons` cuts its after-interval off here. So the
#: operative delay is shorter than the number: 2.5 s of it is
#: :attr:`ScoreChangeConfig.settle_frames` before any sample is taken at all, and
#: :attr:`ScoreChangeConfig.min_samples` settled masks need roughly 1.5 s more to
#: accumulate at :attr:`ScoreChangeConfig.sample_stride`. Whatever is left is the
#: real tolerance for a late button press.
#:
#: The value was swept over all eleven calibrated bouts at 0, 4, 5, 6, 7, 8, 9,
#: 10, 12, 15, 20 and 30 s, and the answer is flat in between:
#:
#: * Below 7 s nothing is promoted anywhere, this bout included. The measured
#:   late entry on ``20260828_김창환배_…_piste6`` — red lamp at frame 5769, white
#:   lamp 2.7 s later, digits 4 → 5 at about 196 s — first appears at 7 s.
#: * From 7 s to 11 s that one promotion is the only one in the set. Every other
#:   bout resolves identically to the pre-promotion tracker.
#: * At 12 s three more arrive, all from ``annulled`` — 260716_de32_s1 frame
#:   10214, 260716_de64_s2 frame 7457, 260716_scout_s3 frame 4420 — and at 15 s a
#:   fourth. These are lamps the referee waved off, 7.2–9.0 s ahead of the next
#:   white lamp, and turning them into touches is precisely the failure the score
#:   cross-check exists to prevent. Nothing in the footage says otherwise; there
#:   is no ground truth for those bouts to appeal to.
#:
#: 8 s sits in the empty band, a second clear of what the real case needs and
#: four short of where invented touches start. It is deliberately nearer the
#: bottom: a promotion this rule declines costs one point in a report that
#: already flags its score as a lower bound, and one it makes wrongly puts a
#: touch in the timeline that never happened.
LATE_ENTRY_WINDOW_SEC = 8.0


@dataclass(frozen=True)
class LatePromotion:
    """Why a lamp that its own comparison could not confirm was counted anyway.

    Recorded on the promoted :class:`TouchResolution` so a report can say how the
    point was arrived at instead of the number simply going up. See
    :func:`resolve_touches` for the conditions that have to hold.
    """

    #: The verdict this event carried before the promotion: ``"undetermined"``
    #: or ``"annulled"``.
    from_verdict: str
    #: Onset frames of the off-target events the score change was found past, in
    #: order. Never empty — with nothing skipped there is nothing to promote.
    skipped_off_target: Tuple[int, ...]
    #: Seconds from this event's lamp to the last skipped off-target lamp. The
    #: quantity :data:`LATE_ENTRY_WINDOW_SEC` bounds.
    delay_sec: float

    def describe(self) -> str:
        before = {
            VERDICT_UNDETERMINED: "직후에는 점수판을 대조할 수 없었으나",
            VERDICT_ANNULLED: "직후에는 점수가 그대로였으나",
        }.get(self.from_verdict, f"({self.from_verdict})")
        skipped = ", ".join(str(f) for f in self.skipped_off_target)
        return (
            f"{before}, 무효 램프(프레임 {skipped}) 뒤 {self.delay_sec:.1f}초 안에 "
            "점수가 올라 승격"
        )


#: Weapons whose rules award at most one point per action, because the referee
#: resolves a double hit on priority: either one fencer takes it or nobody does.
#: Both sides' digits rising together is therefore not a result these weapons can
#: produce, and :func:`resolve_touches` refuses to report it as one.
#:
#: Épée is deliberately absent and must stay absent. There a simultaneous double
#: touch is a real, common result and both scores rising together is exactly what
#: it looks like, so the same reading is evidence rather than error.
PRIORITY_WEAPONS = frozenset({"foil", "sabre"})

#: :attr:`PriorityRuleApplication.rule` values.
RULE_NO_SIMULTANEOUS = "no_simultaneous_touch"
RULE_LAMP_OVER_SCORE = "lamp_over_score"

_SIDE_KO = {LEFT: "좌", RIGHT: "우"}


def _similarity_ko(similarity: Mapping[str, Optional[float]]) -> str:
    parts = [
        f"{_SIDE_KO[side]} {similarity[side]:.3f}"
        for side in SIDES
        if similarity.get(side) is not None
    ]
    return f" (유사도 {' / '.join(parts)})" if parts else ""


@dataclass(frozen=True)
class PriorityRuleApplication:
    """Why a comparison reading *both* sides up was not taken at face value.

    Recorded on the :class:`TouchResolution` the rule produced, so a report can
    say the reading was overruled and on what grounds rather than presenting the
    outcome as an ordinary read. See :func:`resolve_touches`.
    """

    #: :data:`RULE_NO_SIMULTANEOUS` or :data:`RULE_LAMP_OVER_SCORE`.
    rule: str
    #: The weapon whose rules made the reading impossible.
    weapon: str
    #: Sides the digit comparison claimed had changed. Always both — with one
    #: side there is nothing to overrule.
    changed: Tuple[str, ...]
    #: Sides whose valid lamp fired.
    lit: Tuple[str, ...]
    #: The comparison's per-side similarity, kept because it is the number that
    #: was wrong and the one to look at when re-tuning anything.
    similarity: Mapping[str, Optional[float]]

    def describe(self) -> str:
        detail = _similarity_ko(self.similarity)
        if self.rule == RULE_LAMP_OVER_SCORE:
            side = _SIDE_KO.get(self.lit[0], self.lit[0]) if self.lit else "?"
            return (
                f"양쪽 점수가 함께 변한 것으로 읽혔으나 {side}측 유효 램프만 점등 — "
                f"램프가 지목한 {side} 득점 채택{detail}"
            )
        return (
            f"양쪽 점수가 함께 오른 것으로 읽혔으나 {self.weapon}에는 양측 동시 "
            f"득점이 없어 미확정 처리{detail}"
        )


@dataclass(frozen=True)
class TouchResolution:
    """A lamp event with its scorer decided, or explicitly not decided."""

    event: LampEvent
    #: ``"left"`` / ``"right"`` / ``"both"`` / ``None``.
    scorer: Optional[str]
    verdict: str
    score_before: Tuple[int, int]
    score_after: Tuple[int, int]
    #: True when both sides' chromatic lamps fired and the referee had to award
    #: the point on priority. Directly usable as a ``no_priority_call`` signal.
    priority_call: bool
    #: False once an earlier event went undetermined. The *scorer* of this touch
    #: is still sound — it rests on this event's own comparison — but the running
    #: totals are not, because an unknown number of points went unrecorded
    #: before it. Callers must not present these numbers as the score.
    tally_reliable: bool = True
    #: Set only on a touch this event's own comparison did not support, reached
    #: instead by :func:`resolve_touches`'s late-entry rule. ``None`` on every
    #: other resolution, so ``promotion is not None`` is the test for "this
    #: number came from somewhere other than the usual cross-check".
    promotion: Optional[LatePromotion] = None
    #: Set only when one of the priority-weapon rules overruled a comparison that
    #: read both sides as changing — see :func:`resolve_touches`. ``None``
    #: everywhere else.
    priority_rule: Optional[PriorityRuleApplication] = None


def late_entry_comparisons(
    events: Sequence[LampEvent],
    intervals: Sequence[Tuple[int, int]],
    detector: ScoreChangeDetector,
    *,
    fps: float,
    window_sec: float = LATE_ENTRY_WINDOW_SEC,
) -> List[Optional[ScoreComparison]]:
    """Re-compare each lamp event's score across the off-target lamps after it.

    ``[i]`` is ``events[i]``'s ordinary comparison with its *after* side moved
    past the run of off-target events that follows — same settled "before", the
    settled score once the white lamps are done rather than as soon as the first
    one interrupts. ``None`` where there is no such run, which is most events.

    The after side is also cut off ``window_sec`` from the lamp, so the digits
    being compared are ones that settled while the point could still plausibly
    have been being entered. That is what makes :func:`resolve_touches`'s window
    a statement about the score change and not merely about the white lamp:
    outside it, there are no samples left to promote on.
    """
    out: List[Optional[ScoreComparison]] = [None] * len(events)
    window_frames = window_sec * fps if fps > 0 and window_sec > 0 else 0.0
    for index, event in enumerate(events):
        if not event.any_valid:
            continue
        end = index
        while end + 1 < len(events) and not events[end + 1].any_valid:
            end += 1
        if end == index or end + 1 >= len(intervals):
            continue
        after_start, after_end = intervals[end + 1]
        after_end = min(after_end, int(event.onset_frame + window_frames))
        if after_end <= after_start:
            continue
        out[index] = detector.compare(intervals[index], (after_start, after_end))
    return out


def _late_entry_promotion(
    index: int,
    events: Sequence[LampEvent],
    late_comparisons: Optional[Sequence[Optional[ScoreComparison]]],
    from_verdict: str,
    fps: float,
    window_sec: float,
) -> Optional[Tuple[str, LatePromotion]]:
    """Decide whether ``events[index]`` earns a touch on a late score entry.

    Returns ``(scorer, promotion)`` or ``None``. Every condition is required, for
    the reason given at :func:`resolve_touches`: on the pixels alone a referee's
    annulment and an operator's late button press look the same, and only the
    surrounding circumstance separates them.
    """
    if late_comparisons is None or index >= len(late_comparisons):
        return None
    comparison = late_comparisons[index]
    if comparison is None or not comparison.determined:
        return None

    event = events[index]

    # 1. Only an unconfirmed chromatic lamp is a candidate. A touch is already
    #    counted, an off-target lamp was never a point, and an inconsistent read
    #    is a contradiction that a second look at the same digits cannot settle.
    if from_verdict not in (VERDICT_UNDETERMINED, VERDICT_ANNULLED) or not event.any_valid:
        return None

    # 2. Nothing but off-target lamps in between. A chromatic lamp inside the
    #    stretch is a nearer and better owner of the point, so the moment one
    #    appears this event stops being the answer.
    end = index
    while end + 1 < len(events) and not events[end + 1].any_valid:
        end += 1
    if end == index:
        return None
    skipped = tuple(events[k].onset_frame for k in range(index + 1, end + 1))

    # 3. One side went up, and it is the side whose lamp lit. Both sides moving
    #    is a double touch, which arrives on a lamp event of its own; a side
    #    moving without its own lamp is the contradiction :func:`resolve_touches`
    #    calls ``inconsistent``, and is no more resolvable seen from here.
    lit = {s for s in SIDES if (s == LEFT and event.left_valid) or (s == RIGHT and event.right_valid)}
    changed = set(comparison.changed)
    if len(changed) != 1 or not changed <= lit:
        return None

    # 4. Soon enough after the lamp to still be this lamp's point.
    delay_frames = events[end].onset_frame - event.onset_frame
    window_frames = window_sec * fps if fps > 0 and window_sec > 0 else 0.0
    if delay_frames > window_frames:
        return None

    scorer = next(iter(changed))
    return scorer, LatePromotion(
        from_verdict=from_verdict,
        skipped_off_target=skipped,
        delay_sec=delay_frames / fps if fps > 0 else 0.0,
    )


def resolve_touches(
    events: Sequence[LampEvent],
    comparisons: Sequence[ScoreComparison],
    *,
    start_score: Tuple[int, int] = (0, 0),
    late_comparisons: Optional[Sequence[Optional[ScoreComparison]]] = None,
    fps: float = 30.0,
    late_entry_window_sec: float = LATE_ENTRY_WINDOW_SEC,
    weapon: Optional[str] = None,
) -> List[TouchResolution]:
    """Decide, for each lamp event, whether a point was actually awarded.

    ``comparisons[i]`` compares the settled score across ``events[i]`` — see
    :meth:`ScoreChangeDetector.compare` and :func:`event_intervals`.

    The outcomes:

    * chromatic lamp, one side's digits change → a touch by that side;
    * both chromatic, one side's digits change → a touch by that side, decided on
      priority (``priority_call``);
    * chromatic lamp, no digit change → ``annulled`` — the referee waved it off,
      and reporting it as a touch is the failure mode this whole cross-check
      exists to prevent;
    * white only → ``off_target``, which was never a touch to begin with;
    * chromatic lamp, score not comparable → ``undetermined``. It is reported,
      never counted, and never silently dropped;
    * a side's score moves with no coloured lamp of its own → ``inconsistent``.
      The lamp and the digits cannot both be right, so neither is trusted.

    Late entry: a score that moves past the white lamps
    ---------------------------------------------------
    Each ``comparisons[i]`` window closes at the next lamp event, whatever colour
    that lamp is, and an operator who presses the button a moment late can fall
    on the wrong side of that boundary. Measured on
    ``20260828_김창환배_…_piste6``: the bout-winning red lamp fires at frame 5769,
    an off-target white lamp follows 2.7 s later, and the digits go 4 → 5 inside
    the white lamp's window. The red lamp's own comparison closed before the
    point landed, so the bout finished 5–1 and the report said 4–1 — the touch
    that ended it simply gone.

    A white lamp between a valid lamp and the point is not evidence about the
    point. It is an error or a hit off target; it is not something a referee
    weighs, and it does not stop the previous valid hit from being awarded. So
    when ``late_comparisons[i]`` is supplied — the same "before" state as
    ``comparisons[i]`` compared against the settled score *past* the off-target
    run, see :func:`late_entry_comparisons` — an unconfirmed chromatic lamp is
    promoted to a touch, and says so in :attr:`TouchResolution.promotion`.

    None of that loosens the annulment gate. On the digits alone a referee waving
    a hit off and an operator who has not pressed the button yet are the same
    picture, so all four conditions in :func:`_late_entry_promotion` are required
    rather than weighed: an unconfirmed lamp of that fencer's own colour, nothing
    but off-target lamps in between, exactly that one side's digits moving, and
    the whole thing inside :data:`LATE_ENTRY_WINDOW_SEC`. Miss one and the event
    keeps the verdict it had. What the promotion cannot check is *how much* the
    digits moved: :class:`ScoreChangeDetector` reports change, not value, so a
    one-point rise and a two-point correction are the same reading — the same
    limit the ordinary touch path lives with, and the reason a change on both
    sides is refused here rather than split into two points.

    Both sides at once: what the weapon's rules allow
    -------------------------------------------------
    ``weapon`` names the weapon being fenced, and when it is one of
    :data:`PRIORITY_WEAPONS` it settles a reading the digits cannot settle for
    themselves. Under priority, one action produces one point or none: the
    referee either awards it to a fencer or, on a true simultaneous, to nobody.
    So a comparison reporting that *both* sides' digits went up is not a result
    the bout can have produced; one of the two readings is wrong. Two shapes of
    that, distinguished by how many valid lamps fired:

    * **Both lamps lit** (:data:`RULE_NO_SIMULTANEOUS`) — the lamps say a double
      hit and nothing says which fencer the referee gave it to. The reading is
      demoted to ``undetermined``. Picking a side here would be a guess, and the
      guess would be invisible in the output; ``undetermined`` is what is
      actually known. Measured on ``20260828_김창환배_소율vs박소윤`` at frame
      ~730: red and green lamps, similarity 0.747 left and 0.770 right, both read
      as changed, and the panel in fact sat at 0–0 for another fifty seconds. The
      spurious point took the report to 6–3 against a true 5–2.
    * **Exactly one lamp lit** (:data:`RULE_LAMP_OVER_SCORE`) — the lamp names
      the scorer, so the other side's "change" is the spurious one and the touch
      is awarded to the side whose lamp fired. A lamp is an electrical signal off
      the scoring machine; a digit comparison is a similarity score on a handful
      of blown-out pixels, and where they disagree the lamp is the better witness.
      Measured on ``20260828_김창환배_이예은vs박소윤`` at frame ~3970: green lamp
      only, right similarity 0.200 (a real change) and left 0.585 (not), which
      the ``inconsistent`` gate below threw the whole event away for.

    Both rules need a weapon to fire and neither fires without one, so a caller
    that names no weapon gets the unchanged behaviour. Neither touches the
    annulment gate: the first only ever removes a touch, and the second acts on
    an event where a side's digits *did* change, so a lamp the referee waved off
    — digits unmoved — reaches neither.

    What can still fool the second rule is the operator zeroing the box for the
    next bout while the camera runs: both fields change at once and neither
    change is a point. Measured on ``260715_pool_a_piste2``, where that is
    exactly what happens after the last lamp — and the rule still answers
    correctly there, because the left fencer really did score 4 → 5 before the
    reset. It would answer wrongly on the same picture with the last lamp
    annulled and the bout ending on time, which is the ambiguity
    :func:`infer_end_of_bout_touch` documents at length and refuses to resolve
    without a clock reading. The exposure is one event per bout, at the end, and
    the rule is worth it: across the eleven calibrated bouts it recovers four
    touches, every one of them confirmed by reading the panel by eye.

    Scores are a running tally from ``start_score``, not an OCR reading, so they
    are only meaningful for a clip that starts at the beginning of the bout.
    Once any event is undetermined the tally keeps counting — it remains the best
    available estimate — but every later resolution is flagged
    ``tally_reliable=False``, because an unknown number of points may have gone
    unrecorded at that event. Per-touch scorers stay trustworthy either way;
    only the totals are in doubt.
    """
    resolutions: List[TouchResolution] = []
    score = (int(start_score[0]), int(start_score[1]))
    ordered = sorted(events, key=lambda e: e.onset_frame)
    reliable = True
    priority_weapon = weapon is not None and weapon.strip().lower() in PRIORITY_WEAPONS

    for index, event in enumerate(ordered):
        comparison = comparisons[index] if index < len(comparisons) else None
        before = score

        if not event.any_valid:
            resolutions.append(TouchResolution(
                event, None, VERDICT_OFF_TARGET, before, before, False, reliable))
            continue

        def promote(from_verdict: str) -> Optional[TouchResolution]:
            """This event as a late-entry touch, or ``None`` to keep the verdict."""
            promotion = _late_entry_promotion(
                index, ordered, late_comparisons, from_verdict, fps,
                late_entry_window_sec,
            )
            if promotion is None:
                return None
            side, detail = promotion
            after = (before[0] + 1, before[1]) if side == LEFT else (before[0], before[1] + 1)
            return TouchResolution(
                event, side, VERDICT_TOUCH, before, after, event.both_valid,
                reliable, detail)

        if comparison is None or not comparison.determined:
            promoted = promote(VERDICT_UNDETERMINED)
            if promoted is not None:
                # The point was found after all, so nothing went unrecorded here
                # and the tally stays as trustworthy as it already was.
                resolutions.append(promoted)
                score = promoted.score_after
                continue
            resolutions.append(TouchResolution(
                event, None, VERDICT_UNDETERMINED, before, before, event.both_valid,
                reliable))
            reliable = False
            continue

        sides = set(comparison.changed)
        if not sides:
            promoted = promote(VERDICT_ANNULLED)
            if promoted is not None:
                resolutions.append(promoted)
                score = promoted.score_after
                continue
            resolutions.append(TouchResolution(
                event, None, VERDICT_ANNULLED, before, before, event.both_valid,
                reliable))
            continue

        lit = {s for s in SIDES if (s == LEFT and event.left_valid) or (s == RIGHT and event.right_valid)}

        # Both sides' digits rising is a result a priority weapon cannot produce,
        # so the reading is overruled rather than reported — see the docstring.
        # This runs before the inconsistency gate below because the one-lamp form
        # of it is a case that gate would otherwise discard whole.
        if priority_weapon and len(sides) == len(SIDES):
            detail = PriorityRuleApplication(
                rule=RULE_LAMP_OVER_SCORE if len(lit) == 1 else RULE_NO_SIMULTANEOUS,
                weapon=weapon.strip().lower(),
                changed=tuple(s for s in SIDES if s in sides),
                lit=tuple(s for s in SIDES if s in lit),
                similarity=dict(comparison.similarity),
            )
            if detail.rule == RULE_LAMP_OVER_SCORE:
                scorer = detail.lit[0]
                score = (
                    (before[0] + 1, before[1]) if scorer == LEFT
                    else (before[0], before[1] + 1)
                )
                resolutions.append(TouchResolution(
                    event, scorer, VERDICT_TOUCH, before, score, event.both_valid,
                    reliable, priority_rule=detail))
                continue
            # Both lamps lit: the point belongs to one of them and nothing here
            # says which, so no point is awarded and the tally stops being
            # trustworthy — the same treatment any unreadable event gets.
            resolutions.append(TouchResolution(
                event, None, VERDICT_UNDETERMINED, before, before, event.both_valid,
                reliable, priority_rule=detail))
            reliable = False
            continue

        # A fencer cannot score without their own coloured lamp. If a side's
        # score moved while only the other side's lamp fired, the two readings
        # contradict each other and there is no way to arbitrate between them —
        # so neither is reported as fact. This gate exists because output that
        # said "left lamp only" and "both scores went up" in the same breath
        # was allowed through once; it was the tracker reading a wall.
        if not sides <= lit:
            resolutions.append(TouchResolution(
                event, None, VERDICT_INCONSISTENT, before, before, event.both_valid,
                reliable))
            reliable = False
            continue

        if sides == {LEFT}:
            scorer = LEFT
            score = (before[0] + 1, before[1])
        elif sides == {RIGHT}:
            scorer = RIGHT
            score = (before[0], before[1] + 1)
        else:
            scorer = "both"
            score = (before[0] + 1, before[1] + 1)

        resolutions.append(TouchResolution(
            event, scorer, VERDICT_TOUCH, before, score, event.both_valid, reliable))

    return resolutions


#: Bout formats and the score that ends them.
END_OF_BOUT_TARGET = {"pool": 5, "de": 15}

#: How close to the end of the file a lamp has to fire for
#: :func:`infer_end_of_bout_touch` to treat the recording stopping as evidence.
#: Measured: the two bouts this rule exists for cut 3.0 s and 0.8 s after their
#: final lamp. 10 s leaves room for a slower hand on the stop button without
#: reaching a lamp the referee annulled mid-bout, which is followed by however
#: much bout was left to fence — the case that must keep failing.
END_OF_BOUT_TAIL_SEC = 10.0


@dataclass(frozen=True)
class EndOfBoutInference:
    """The verdict of :func:`infer_end_of_bout_touch`, applied or refused."""

    applied: bool
    #: Machine-readable. ``"applied"``, or the first condition that failed:
    #: ``"clock_unknown"``, ``"clock_expired"``, ``"no_events"``,
    #: ``"last_event_resolved"``, ``"not_in_tail_window"``, ``"not_match_point"``,
    #: ``"lamp_not_leader"``.
    reason: str
    #: Index into the caller's ``resolutions`` of the promoted event.
    index: Optional[int] = None
    scorer: Optional[str] = None
    score_after: Optional[Tuple[int, int]] = None


def infer_end_of_bout_touch(
    resolutions: Sequence[TouchResolution],
    *,
    target_score: int,
    frame_count: int,
    fps: float,
    clock_running_at_cut: Optional[bool],
    tail_window_sec: float = END_OF_BOUT_TAIL_SEC,
) -> EndOfBoutInference:
    """Promote a final unconfirmed lamp to a touch when the bout can only have ended.

    Why this exists
    ---------------
    Our own recordings sometimes stop a second or two after the last touch. The
    lamp has fired but the scoreboard operator has not pressed the button yet, so
    the digits never move and :func:`resolve_touches` — correctly — refuses to
    call it a touch. It lands as ``undetermined`` (the score was not comparable
    at all) or ``annulled`` (lamp lit, digits unchanged, which from the outside
    is exactly what a referee waving a hit off looks like). That gate is right in
    general and is not weakened here.

    In one specific situation the missing point is certain rather than ambiguous.
    Measured on two real bouts. In a pool bout the last event is a red lamp at
    frame 4903 of 4992 with the score frozen at 4–2 and 1:04 still on the clock;
    it finished 5–2. In a second, a red lamp fires at frame 6280 of 6305 with the
    score frozen at 4–0 and 1:02 on the clock; it finished 5–0. In both, the
    leader was on match point, time had not expired, their own coloured lamp
    fired, and then the file simply ended. A bout in that state has exactly one
    continuation.

    The failure mode being prevented
    --------------------------------
    Reporting a referee's annulment as a touch. That is the same failure the
    score cross-check exists to prevent, and it is why every condition below is
    *required* rather than weighed: on the evidence available, the promoted event
    is indistinguishable from a genuine annulment. Nothing in the pixels tells
    the two apart. What separates them is the surrounding circumstance — match
    point, a running clock, the leader's own lamp, and no footage afterwards —
    and if any one of those is missing the ambiguity is back and the rule must
    stay silent. The conservatism is the point: this fires on the last event of a
    bout or not at all, and a missed inference costs one point in a report that
    already says its score is a lower bound, while a wrong one invents a touch
    that never happened.

    Args:
        resolutions: The bout's resolutions, in any order — the last is taken by
            ``onset_frame``, not by position.
        target_score: The score that ends this format — see
            :data:`END_OF_BOUT_TARGET`.
        frame_count: Work-file frames in the recording.
        fps: Work-file frame rate. ``<= 0`` collapses the tail window to nothing,
            so an unknown frame rate refuses rather than guesses.
        clock_running_at_cut: Whether time was still on the clock when the
            recording stopped. ``None`` means nobody read it, and unknown is not
            permission.
        tail_window_sec: How close to the end the lamp must be. Non-positive
            collapses the window, same as an unusable ``fps``.

    Returns:
        :class:`EndOfBoutInference`. On success ``score_after`` is
        ``score_before`` with the leader raised to ``target_score``.
    """
    # 1. The clock. An expired clock means the bout ended on time, not on a
    #    point; an unread one means we know nothing and must not pretend to.
    if clock_running_at_cut is not True:
        return EndOfBoutInference(
            False, "clock_expired" if clock_running_at_cut is False else "clock_unknown")

    # 2. Something to promote. An already-resolved last event is either a touch
    #    already counted or an off-target/inconsistent read, and neither is a
    #    point the box failed to record.
    if not resolutions:
        return EndOfBoutInference(False, "no_events")
    index = max(
        range(len(resolutions)),
        key=lambda i: (resolutions[i].event.onset_frame, i),
    )
    resolution = resolutions[index]
    if resolution.verdict not in (VERDICT_UNDETERMINED, VERDICT_ANNULLED):
        return EndOfBoutInference(False, "last_event_resolved")

    # 3. The recording has to stop right after the lamp. This is the condition
    #    that separates "the operator never got to press the button" from "the
    #    referee annulled it and the bout carried on" — the latter is followed by
    #    more footage, and often by more lamps.
    tail_frames = tail_window_sec * fps if fps > 0 and tail_window_sec > 0 else 0.0
    if resolution.event.onset_frame < frame_count - tail_frames:
        return EndOfBoutInference(False, "not_in_tail_window")

    # 4. Exactly one side one point from the target. 4–4 or 14–14 is two fencers
    #    on match point and no leader, so which of them the missing point belongs
    #    to is precisely what is unknown.
    before = resolution.score_before
    on_match_point = [side for side, value in zip(SIDES, before) if value == target_score - 1]
    if len(on_match_point) != 1:
        return EndOfBoutInference(False, "not_match_point")
    scorer = on_match_point[0]

    # 5. The leader's own chromatic lamp. A lamp belonging only to the trailing
    #    fencer says nothing about whether the leader finished the bout.
    event = resolution.event
    if not (event.left_valid if scorer == LEFT else event.right_valid):
        return EndOfBoutInference(False, "lamp_not_leader")

    after = (target_score, before[1]) if scorer == LEFT else (before[0], target_score)
    return EndOfBoutInference(True, "applied", index=index, scorer=scorer, score_after=after)


# ----------------------------------------------------------------------
# Whole-video driver
# ----------------------------------------------------------------------


@dataclass
class ScoreboardAnalysis:
    """Everything the tracked read produced for one scoreboard work file."""

    resolutions: List[TouchResolution]
    events: List[LampEvent]
    coverage_gaps: List[CoverageGap]
    comparisons: List[ScoreComparison]
    tracks: List[PanelTrack]
    frame_count: int
    fps: float
    template_frame: int
    #: The baseline the touch tally counted from.
    start_score: Tuple[int, int] = (0, 0)
    #: ``"caller"`` when :func:`track_scoreboard_video` was given a start score,
    #: ``"read"`` when it used :class:`StartScoreReader` — including the case
    #: where the reader declined and 0-0 was assumed. ``start_score_reading``
    #: separates those two.
    start_score_source: str = "caller"
    #: What the digit reader made of the opening frames, whether or not its
    #: answer was used. ``None`` only for analyses built by hand in tests.
    start_score_reading: Optional[StartScoreReading] = None
    #: The weapon the resolutions were decided under, or ``None`` if the caller
    #: named none — see :func:`resolve_touches`. Recorded because it changes what
    #: the same pixels resolve to, so a stored analysis without it cannot be
    #: reproduced.
    weapon: Optional[str] = None

    @property
    def start_score_assumed(self) -> bool:
        """True when the tally starts at 0-0 because nothing could be read.

        The dangerous case, and the one a report has to surface: a clip that
        opens mid-bout reads as if it opened at 0-0, and every score in it is
        then low by the same amount with nothing else to show for it.
        """
        return (
            self.start_score_source == "read"
            and self.start_score_reading is not None
            and self.start_score_reading.score is None
        )

    @property
    def lock_rate(self) -> float:
        """Fraction of frames whose position the tracker vouched for."""
        if not self.tracks:
            return 0.0
        return sum(1 for t in self.tracks if t.locked) / len(self.tracks)

    @property
    def readable_rate(self) -> float:
        """Fraction of frames whose lamps were actually read."""
        if not self.tracks:
            return 0.0
        gap_frames = sum(g.frame_count for g in self.coverage_gaps)
        return (len(self.tracks) - gap_frames) / len(self.tracks)

    @property
    def touches(self) -> List[TouchResolution]:
        return [r for r in self.resolutions if r.verdict == VERDICT_TOUCH]

    @property
    def annulled(self) -> List[TouchResolution]:
        return [r for r in self.resolutions if r.verdict == VERDICT_ANNULLED]

    @property
    def undetermined(self) -> List[TouchResolution]:
        return [r for r in self.resolutions if r.verdict == VERDICT_UNDETERMINED]

    @property
    def inconsistent(self) -> List[TouchResolution]:
        return [r for r in self.resolutions if r.verdict == VERDICT_INCONSISTENT]

    @property
    def final_score(self) -> Tuple[int, int]:
        touches = self.touches
        return touches[-1].score_after if touches else (0, 0)

    @property
    def score_reliable(self) -> bool:
        """False when the touch count is a lower bound rather than the score.

        Two things spoil it, and both are observed rather than assumed. An
        undetermined event is a lamp whose outcome could not be checked. A
        coverage gap is worse: the lamps were not visible at all, so a whole
        touch can have happened inside it leaving no trace in this list —
        measured on ``260815_bout_b``, where the true score is 4–0 and the
        visible lamps account for only three of those points.
        """
        return not self.coverage_gaps and all(r.tally_reliable for r in self.resolutions)


def _read_frames(capture, count: int) -> List[np.ndarray]:
    frames = []
    for _ in range(count):
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(frame)
    return frames


def _bootstrap_tracker(
    video_path: str,
    housing_bbox: Rect,
    placard_bbox: Optional[Rect],
    profile: MachineProfile,
    anchor_frame: int,
    tracker_config: TrackerConfig,
    lamp_config: LampConfig,
) -> Tuple[PanelTracker, int, float]:
    """Cut the templates and report ``(tracker, template_frame, fps)``.

    Shared so that :func:`read_start_score` reproduces
    :func:`track_scoreboard_video`'s track exactly rather than approximating it;
    a start score read off a differently-anchored track is a start score for a
    different set of pixels.
    """
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise FileNotFoundError(f"cannot open scoreboard video: {video_path}")
    try:
        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        if anchor_frame:
            capture.set(cv2.CAP_PROP_POS_FRAMES, int(anchor_frame))
            head = _read_frames(capture, 1)
        else:
            head = _read_frames(capture, max(1, tracker_config.init_scan_frames))
    finally:
        capture.release()
    if not head:
        raise ValueError(f"scoreboard video has no frame {anchor_frame}: {video_path}")

    if anchor_frame:
        offset = int(anchor_frame)
        template = head[0]
    else:
        offset = select_template_frame(
            [_head_lamp_activity(f, housing_bbox, profile, lamp_config) for f in head]
        )
        template = head[offset]
    tracker = PanelTracker.from_frame(
        template, housing_bbox, placard_bbox, tracker_config
    )
    return tracker, offset, float(fps)


#: How far into a clip :func:`read_start_score` will look for the opening score
#: when the caller names no other limit. 30 s at 30 fps: long enough that a
#: panel briefly occluded or out of frame at the start still gets read, short
#: enough that the reader never wanders into the middle of a bout when there is
#: no lamp event to stop it.
START_SCORE_SCAN_FRAMES = 900


def read_start_score(
    video_path: str,
    *,
    housing_bbox: Rect,
    placard_bbox: Optional[Rect] = None,
    profile: MachineProfile = KOR_DOMESTIC_V1,
    anchor_frame: int = 0,
    tracker_config: TrackerConfig = TrackerConfig(),
    lamp_config: LampConfig = LampConfig(),
    score_config: ScoreChangeConfig = ScoreChangeConfig(),
    read_config: DigitReadConfig = DigitReadConfig(),
    scan_frames: int = START_SCORE_SCAN_FRAMES,
) -> Optional[Tuple[int, int]]:
    """Read the score already on the panel when a clip starts, or ``None``.

    A standalone pass over the opening of the file, for callers that want the
    number without running a whole analysis. :func:`track_scoreboard_video` does
    not use this — it feeds the same :class:`StartScoreReader` from its own loop
    and can stop the read at the first lamp event, which this cannot.

    ``None`` means the panel could not be read with confidence, not that the
    score is 0-0, and on every venue calibrated so far ``None`` is what comes
    back — see the module docstring. Use :meth:`StartScoreReader.read` directly
    for the reason it declined.
    """
    if profile.lamp_config is not None:
        lamp_config = profile.lamp_config
    if profile.score_config is not None:
        score_config = profile.score_config
    if profile.read_config is not None:
        read_config = profile.read_config

    tracker, _, _ = _bootstrap_tracker(
        video_path, housing_bbox, placard_bbox, profile,
        anchor_frame, tracker_config, lamp_config,
    )
    reader = StartScoreReader(profile, score_config, read_config, tracker_config)

    capture = cv2.VideoCapture(str(video_path))
    try:
        for _ in range(max(0, int(scan_frames))):
            ok, frame = capture.read()
            if not ok:
                break
            track = tracker.update(frame)
            reader.feed(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV), track)
    finally:
        capture.release()
    return reader.read().score


def track_scoreboard_video(
    video_path: str,
    *,
    housing_bbox: Rect,
    placard_bbox: Optional[Rect] = None,
    profile: MachineProfile = KOR_DOMESTIC_V1,
    anchor_frame: int = 0,
    tracker_config: TrackerConfig = TrackerConfig(),
    lamp_config: LampConfig = LampConfig(),
    score_config: ScoreChangeConfig = ScoreChangeConfig(),
    read_config: DigitReadConfig = DigitReadConfig(),
    start_score: Optional[Tuple[int, int]] = None,
    start_score_scan_frames: int = START_SCORE_SCAN_FRAMES,
    weapon: Optional[str] = None,
    progress=None,
) -> ScoreboardAnalysis:
    """Track, read and cross-validate a whole scoreboard work file.

    ``housing_bbox`` / ``placard_bbox`` are rectangles in this video's own crop
    coordinates, measured on frame ``anchor_frame``; they say where to cut the
    templates, and everything else follows the panel wherever it goes.

    ``start_score`` is the score already on the panel when the clip opens. Left
    at ``None`` it is read off the digits (see :class:`StartScoreReader`), which
    matters because a DE period 2 or 3 opens on the previous period's score and
    a tally from 0-0 would be wrong for the whole clip. An explicit value always
    wins: a caller who has looked at the panel outranks the reader. Whichever
    way it was decided, :attr:`ScoreboardAnalysis.start_score_reading` records
    it, so a report can say which happened.

    ``weapon`` is passed straight to :func:`resolve_touches`, where it decides
    whether a reading of both sides scoring at once is possible at all. Leaving
    it ``None`` leaves those rules off.

    ``anchor_frame`` defaults to 0 because a clip normally opens on the panel.
    It exists because one does not: on ``260816_venue2_bout`` the panel is
    outside the crop at frame 0 entirely, so there is nothing at frame 0 to cut a
    template from. Tracking still *starts* at frame 0 either way — the frames
    before the panel appears simply do not lock, which is the truth about them,
    and full-frame reacquisition picks the panel up the moment it enters.

    The file is opened twice on purpose. With ``anchor_frame=0`` the first pass
    looks at the opening ``TrackerConfig.init_scan_frames`` frames and picks the
    one with the least lamp glare, because a template cut while a lamp is lit
    bakes that glare into every subsequent correlation. With an explicit
    ``anchor_frame`` that search is skipped and the named frame is used as-is —
    the panel may have drifted far enough by then that neighbouring frames no
    longer share its bbox, so choosing a lamps-off frame is the caller's job.
    """
    # A machine that carries its own lamp thresholds wins over the caller's: the
    # numbers describe this box under this exposure, and a caller passing the
    # default would otherwise silently un-calibrate the venue.
    if profile.lamp_config is not None:
        lamp_config = profile.lamp_config
    if profile.score_config is not None:
        score_config = profile.score_config
    if profile.read_config is not None:
        read_config = profile.read_config

    tracker, template_frame, fps = _bootstrap_tracker(
        video_path, housing_bbox, placard_bbox, profile,
        anchor_frame, tracker_config, lamp_config,
    )

    scanner = LampEventScanner(profile, lamp_config, tracker_config, score_config)
    score_detector = ScoreChangeDetector(profile, score_config, tracker_config)
    start_reader = StartScoreReader(profile, score_config, read_config, tracker_config)
    scan_limit = max(0, int(start_score_scan_frames))
    tracks: List[PanelTrack] = []

    capture = cv2.VideoCapture(str(video_path))
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            track = tracker.update(frame)
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            scanner.feed(hsv, track)
            score_detector.feed(hsv, track)
            if track.frame < scan_limit:
                start_reader.feed(hsv, track)
            tracks.append(track)
            if progress is not None and track.frame % 500 == 0:
                progress(track.frame)
    finally:
        capture.release()

    events, gaps = scanner.finish()
    # Stop the start-score read at the first lamp, because that is where the
    # tally starts: a read taken after it already includes the touch the tally
    # is about to add, and the baseline would come out one too high.
    reading = start_reader.read(events[0].onset_frame if events else None)
    baseline = start_score if start_score is not None else reading.score or (0, 0)
    intervals = event_intervals(
        [e.onset_frame for e in events], len(tracks), score_config
    )
    comparisons = [
        score_detector.compare(intervals[i], intervals[i + 1])
        for i in range(len(events))
    ]
    late = late_entry_comparisons(events, intervals, score_detector, fps=float(fps))
    return ScoreboardAnalysis(
        resolutions=resolve_touches(
            events, comparisons, start_score=(int(baseline[0]), int(baseline[1])),
            late_comparisons=late, fps=float(fps), weapon=weapon,
        ),
        events=events,
        coverage_gaps=gaps,
        comparisons=comparisons,
        tracks=tracks,
        frame_count=len(tracks),
        fps=float(fps),
        template_frame=template_frame,
        start_score=(int(baseline[0]), int(baseline[1])),
        start_score_source="caller" if start_score is not None else "read",
        start_score_reading=reading,
        weapon=weapon,
    )


def _head_lamp_activity(
    frame: np.ndarray,
    housing_bbox: Rect,
    profile: MachineProfile,
    config: LampConfig,
) -> Optional[float]:
    """Total lamp glare at the *frame-0* panel position, for template selection.

    The panel barely moves across the first three seconds, so the frame-0
    rectangle is a good enough stand-in for a tracked position here; if it were
    not, the resulting template would simply correlate slightly worse and the
    tracker would say so.
    """
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    total = 0.0
    for side in SIDES:
        value = lamp_activity(
            hsv, absolute_roi((housing_bbox[0], housing_bbox[1]), profile.lamp_rois[side]), config
        )
        if value is None:
            return None
        total += value
    return total


def resolutions_to_match_events(
    resolutions: Sequence[TouchResolution],
    fps: float = 30.0,
) -> List["object"]:
    """Convert resolutions into the ``MatchEvent``s the LED converter consumes.

    Every resolution becomes an event, including the non-scoring ones: the
    converter drops anything whose ``scorer`` is not a side, and passing them
    through keeps ``--dry-run`` able to show what the box did as opposed to only
    what counted.

    ``lamp_red`` / ``lamp_green`` mean "the left/right fencer's valid lamp fired",
    which is the sense ``app.led_report_converter.lamp_pattern`` and
    ``analyzer.touch_matching`` use. A side's chromatic lamp is the only way that
    side can score, so the mapping is side-to-lamp, not hue-to-lamp; the observed
    hue is preserved in ``description`` for diagnosis.
    """
    from analyzer.models import MatchEvent

    events = []
    for resolution in resolutions:
        event = resolution.event
        seconds = int(event.onset_frame / fps) if fps > 0 else 0
        events.append(MatchEvent(
            frame=event.onset_frame,
            video_timestamp=f"{seconds // 60}:{seconds % 60:02d}",
            match_time="",
            event_type=_event_type(resolution),
            lamp_red=event.left_valid,
            lamp_green=event.right_valid,
            score_before=f"{resolution.score_before[0]}-{resolution.score_before[1]}",
            score_after=f"{resolution.score_after[0]}-{resolution.score_after[1]}",
            scorer=resolution.scorer,
            description=_describe(resolution),
        ))
    return events


def _event_type(resolution: TouchResolution) -> str:
    from analyzer.models import EventType

    if resolution.verdict != VERDICT_TOUCH:
        return EventType.INVALID_TOUCH.value
    if resolution.scorer == "both":
        return EventType.SIMULTANEOUS.value
    return EventType.SINGLE_TOUCH.value


def _describe(resolution: TouchResolution) -> str:
    event = resolution.event
    lamps = ", ".join(
        f"{side} {colour}"
        for side, colour in ((LEFT, event.left_colour), (RIGHT, event.right_colour))
        if colour is not None
    ) or "no lamp"
    if resolution.verdict == VERDICT_ANNULLED:
        return f"{lamps} — 점수 변화 없음 (심판 무효 처리로 추정)"
    if resolution.verdict == VERDICT_OFF_TARGET:
        return f"{lamps} — 무효면 (득점 아님)"
    if resolution.verdict == VERDICT_UNDETERMINED:
        if resolution.priority_rule is not None:
            return f"{lamps} — {resolution.priority_rule.describe()}"
        return f"{lamps} — 점수판 확인 불가 (득점 여부 미확정)"
    if resolution.verdict == VERDICT_INCONSISTENT:
        return f"{lamps} — 램프와 점수 변화가 모순됨 (판독 신뢰 불가)"
    if resolution.priority_call:
        text = f"{lamps} — 양측 유효, 우선권 판정으로 {resolution.scorer} 득점"
    else:
        text = f"{lamps} — {resolution.scorer} 득점"
    if resolution.promotion is not None:
        text = f"{text} ({resolution.promotion.describe()})"
    if resolution.priority_rule is not None:
        text = f"{text} ({resolution.priority_rule.describe()})"
    return text
