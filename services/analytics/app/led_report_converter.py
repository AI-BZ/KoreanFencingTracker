"""Convert physical-LED scoreboard ``MatchEvent``s into an OCR report dict.

``analyzer.video_processor.VideoProcessor.process_video_headless`` reads a
physical scoring box (LED lamps + 7-segment score + clock) and returns a list of
:class:`analyzer.models.MatchEvent`. This module turns that list into the
``<stem>_report.json`` shape that ``scripts/generate_continuous_report.py``
merges into a continuous pose report — the same role
``app/tv_report_converter.py`` plays for the TV-broadcast path, but for a
different source and a different (smaller) set of fields.

Frame indices — read this before touching anything numeric
----------------------------------------------------------
``touch["frame"]`` is the **work-file frame index at 30 fps**, copied straight
from ``MatchEvent.frame`` with no conversion, and it must stay that way.

The piste preprocessing step produces two work files from one source video in a
single ffmpeg pass — a piste crop and a scoreboard crop — both through the same
``fps=30`` filter. Their frame indices therefore correspond 1:1, which is what
lets a touch detected on the scoreboard file address a pose exchange measured on
the piste file. **Neither index corresponds to the 120 fps source frame index**
(they are a factor of 4 apart). Converting frames "helpfully" at any point in
this chain is a recurring bug class in this pipeline; the correct action here is
no action.

Downstream consumers of this dict
---------------------------------
``scripts/generate_continuous_report.py`` reads, and nothing else in the merge
path does:

* ``touches`` → ``t["frame"]``, ``t["scorer"]``, ``t["match_time"]``,
  ``t["video_timestamp"]``; the list is then handed to
  ``analyzer.touch_matching.annotate_touch_outcomes`` (reads ``frame`` /
  ``scorer``) and ``summarize_attack_outcomes`` (reads ``lamp_pattern`` and
  ``lamp_scorer_conflict``).
* ``summary`` → ``final_score``, ``weapon``, ``bout_type``, ``gender``,
  ``age_group``.
* ``left_fencer`` / ``right_fencer`` → ``name``, ``club``.
* ``warnings`` → appended verbatim to the merged report.
* ``clock_events`` → not produced here (physical-scoreboard allez/halt is out of
  scope for v1), so the key is omitted rather than emitted empty.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from analyzer.touch_matching import lamp_scorer_conflict

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

#: ``MatchEvent.scorer`` values that represent a confirmed point on the box.
#: Everything else — ``None`` (invalid touch / lamp with no score change) and
#: ``"none"`` — is not a touch and is dropped.
SCORING_SCORERS = ("left", "right", "both")

#: Lamp patterns. These are exactly the strings
#: ``analyzer.touch_matching._LAMP_PATTERNS`` recognises and
#: ``_SINGLE_LAMP_SIDE`` keys on, so a report produced here is tallied by
#: ``summarize_attack_outcomes`` the same way a TV-path report is. ``"white"``
#: (non-valid-target) is deliberately absent: the physical-box path has no white
#: lamp ROI, so this converter can never observe one.
LAMP_DOUBLE = "double"
LAMP_SINGLE_LEFT = "single_left"
LAMP_SINGLE_RIGHT = "single_right"

#: Nominal confidence attached to a lamp read off a physical box.
#:
#: This is a constant, not a measurement. ``LampDetector`` is a hard pixel-count
#: threshold — a lamp is on or it is off — so unlike the TV ``LampBarReader``
#: there is no per-reading score to report. 0.9 marks the reading as trustworthy
#: without claiming certainty, and sits above
#: ``app.report_renderer.LAMP_LOW_CONFIDENCE_MAX`` (0.7) so the UI does not flag
#: every physical-box touch as low confidence.
LED_LAMP_CONFIDENCE = 0.9

#: Fencer-name placeholders for a scoreboard that carries no names.
#:
#: These exact strings matter: ``generate_continuous_report.py`` merges an OCR
#: name only when it is ``not in ("Left", "Right")``, so these two are the
#: pipeline's established "no name was read" sentinels and leave the continuous
#: report's own defaults untouched. Any other placeholder would overwrite them.
DEFAULT_LEFT_NAME = "Left"
DEFAULT_RIGHT_NAME = "Right"

#: Warning types emitted by :func:`build_warnings`.
WARNING_NO_TOUCHES = "no_touches_detected"
WARNING_CLOCK_UNREAD = "clock_roi_unread"
WARNING_SCORE_UNREADABLE = "score_after_unreadable"
WARNING_SCORE_NOT_MONOTONIC = "score_not_monotonic"


# ------------------------------------------------------------------
# Pure helpers
# ------------------------------------------------------------------


def lamp_pattern(lamp_red: bool, lamp_green: bool) -> Optional[str]:
    """Map a ``MatchEvent``'s two lamp booleans to a lamp pattern string.

    Both lamps → ``"double"``; red alone → ``"single_left"``; green alone →
    ``"single_right"``; neither → ``None``.

    ``None`` is returned rather than a pattern when no lamp fired, because "we
    saw no lamp" is not a lamp reading. ``summarize_attack_outcomes`` counts a
    ``None`` pattern as ``"unread"``, which is exactly right — inventing a
    pattern would put a fabricated reading into the priority statistics.
    """
    if lamp_red and lamp_green:
        return LAMP_DOUBLE
    if lamp_red:
        return LAMP_SINGLE_LEFT
    if lamp_green:
        return LAMP_SINGLE_RIGHT
    return None


def parse_score(score: Optional[str]) -> Optional[Tuple[int, int]]:
    """Parse a ``"L-R"`` score string into ``(left, right)``, or ``None``.

    Returns ``None`` for anything the 7-segment reader could not resolve into
    two non-negative integers (empty string, ``"?-3"``, ``None``), so callers can
    tell "unreadable" apart from a genuine ``0-0``.
    """
    if not isinstance(score, str):
        return None
    parts = score.split("-")
    if len(parts) != 2:
        return None
    left, right = parts[0].strip(), parts[1].strip()
    if not (left.isdigit() and right.isdigit()):
        return None
    return (int(left), int(right))


def format_timestamp(frame: int, fps: float) -> str:
    """Frame index → ``"M:SS"``.

    Recomputed from the frame rather than reusing ``MatchEvent.video_timestamp``,
    which is a truncated ``str(timedelta)`` (``"0:02:47"``). Every other report
    in this pipeline uses ``"M:SS"``, and the merge substitutes
    ``video_timestamp`` into ``match_time`` when the clock ROI fails — so the two
    fields have to be in the same format to be interchangeable.
    """
    if fps <= 0:
        return "0:00"
    total_seconds = int(frame / fps)
    return f"{total_seconds // 60}:{total_seconds % 60:02d}"


def scoring_events(events: Sequence) -> list:
    """Keep only the ``MatchEvent``s that represent a confirmed point.

    ``VideoProcessor`` emits an event for every lamp activation, including ones
    that never produced a score change (``scorer=None``, described as
    "invalid"). Those are lamp noise or off-target hits, not touches.
    """
    return [e for e in events if getattr(e, "scorer", None) in SCORING_SCORERS]


def build_touches(events: Sequence, fps: float = 30.0) -> List[dict]:
    """Build the ``touches`` list from already-filtered scoring events.

    ``touch_number`` is a 1-based sequence over the surviving events, so dropped
    non-scoring events leave no gaps.
    """
    touches: List[dict] = []
    for number, event in enumerate(events, start=1):
        lamp_red = bool(getattr(event, "lamp_red", False))
        lamp_green = bool(getattr(event, "lamp_green", False))
        pattern = lamp_pattern(lamp_red, lamp_green)
        scorer = getattr(event, "scorer", None)

        touches.append({
            "touch_number": number,
            # Work-file frame index at 30 fps — NOT converted. See module docstring.
            "frame": int(getattr(event, "frame", 0)),
            "video_timestamp": format_timestamp(int(getattr(event, "frame", 0)), fps),
            "match_time": getattr(event, "match_time", "") or "",
            "scorer": scorer,
            "score_before": getattr(event, "score_before", "") or "",
            "score_after": getattr(event, "score_after", "") or "",
            "description": getattr(event, "description", "") or "",
            "lamp_red": lamp_red,
            "lamp_green": lamp_green,
            "lamp_pattern": pattern,
            "lamp_confidence": LED_LAMP_CONFIDENCE if pattern is not None else 0.0,
            "lamp_scorer_conflict": lamp_scorer_conflict(pattern, scorer),
        })
    return touches


def derive_final_score(touches: Sequence[dict]) -> str:
    """Final score from the last touch whose ``score_after`` is readable.

    Falls back to ``"0-0"`` when there are no touches, and to the last touch's
    raw ``score_after`` when none of them parse — never invents a number.
    """
    for touch in reversed(list(touches)):
        parsed = parse_score(touch.get("score_after"))
        if parsed is not None:
            return f"{parsed[0]}-{parsed[1]}"
    if touches:
        return touches[-1].get("score_after") or "0-0"
    return "0-0"


def count_by_scorer(touches: Sequence[dict], side: str) -> int:
    """Touches scored by ``side``. ``"both"`` counts for each side."""
    return sum(
        1 for t in touches
        if t.get("scorer") == side or t.get("scorer") == "both"
    )


def build_warnings(touches: Sequence[dict]) -> List[dict]:
    """Quality warnings about the scoreboard read itself.

    Each warning is a ``{type, message, severity}`` dict, the shape
    ``templates/report.html`` renders and the merge appends verbatim.
    """
    warnings: List[dict] = []

    if not touches:
        warnings.append({
            "type": WARNING_NO_TOUCHES,
            "message": (
                "점수판에서 확정된 득점을 하나도 읽지 못했습니다 (터치 0개). "
                "램프/점수 ROI 설정을 확인하세요."
            ),
            "severity": "error",
        })
        return warnings

    # Clock ROI failure: ScoreReader returns the same value on every frame (or
    # "" on every frame) when it cannot find the clock digits. One identical
    # match_time across a whole bout is not a real clock reading. Needs >= 2
    # touches to mean anything — a single touch trivially has one value.
    match_times = {t.get("match_time", "") for t in touches}
    if len(touches) >= 2 and len(match_times) == 1:
        only = next(iter(match_times))
        detail = "값이 비어 있음" if not only else f"모든 터치가 '{only}'"
        warnings.append({
            "type": WARNING_CLOCK_UNREAD,
            "message": (
                f"경기 시계를 읽지 못했습니다 ({detail}). "
                "clock ROI 설정을 확인하세요 — 리포트는 영상 타임스탬프로 대체합니다."
            ),
            "severity": "warning",
        })

    unreadable = [
        t["touch_number"] for t in touches
        if parse_score(t.get("score_after")) is None
    ]
    if unreadable:
        warnings.append({
            "type": WARNING_SCORE_UNREADABLE,
            "message": (
                f"점수 판독 실패 터치 {len(unreadable)}개 "
                f"(터치 번호 {', '.join(str(n) for n in unreadable)}). "
                "7세그먼트 OCR이 숫자를 확정하지 못했습니다."
            ),
            "severity": "warning",
        })

    # A side's score can only ever go up. A decrease means a misread digit, and
    # every touch after it inherits the error, so it is worth naming loudly.
    regressions: List[int] = []
    previous: Optional[Tuple[int, int]] = None
    for touch in touches:
        current = parse_score(touch.get("score_after"))
        if current is None:
            continue
        if previous is not None and (current[0] < previous[0] or current[1] < previous[1]):
            regressions.append(touch["touch_number"])
        previous = current
    if regressions:
        warnings.append({
            "type": WARNING_SCORE_NOT_MONOTONIC,
            "message": (
                f"점수가 감소한 터치 {len(regressions)}개 "
                f"(터치 번호 {', '.join(str(n) for n in regressions)}). "
                "점수 OCR 오독 가능성이 높습니다."
            ),
            "severity": "warning",
        })

    return warnings


def format_duration(total_frames: int, fps: float, touches: Sequence[dict]) -> str:
    """Bout duration as ``"M:SS"``.

    Prefers the video's own length; falls back to the last touch's frame when
    the frame count is unknown (0), so the field is never silently ``"0:00"``
    for a bout that clearly ran longer.
    """
    if total_frames > 0:
        return format_timestamp(total_frames, fps)
    if touches:
        return format_timestamp(touches[-1].get("frame", 0), fps)
    return "0:00"


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------


def led_events_to_match_report(
    events: Sequence,
    *,
    video_path: str,
    weapon: str,
    bout_type: str = "pool",
    left_name: Optional[str] = None,
    right_name: Optional[str] = None,
    fps: float = 30.0,
    total_frames: int = 0,
    analysis_time_sec: float = 0.0,
) -> dict:
    """Convert ``VideoProcessor`` ``MatchEvent``s into an OCR report dict.

    Args:
        events: ``MatchEvent`` list from ``process_video_headless``. Non-scoring
            events are dropped (see :func:`scoring_events`).
        video_path: Path to the scoreboard work file that was analysed. Recorded
            for provenance only — the merged report's ``summary.video_path``
            keeps pointing at the *piste* work file, which is what clip
            generation re-reads.
        weapon: ``"foil"`` / ``"epee"`` / ``"sabre"``. Required, never guessed:
            the foil priority cascade is gated on it and silently switches off
            for an unrecognised value.
        bout_type: ``"pool"`` or ``"de"``.
        left_name, right_name: Fencer names. A physical scoreboard carries none,
            so these come from the CLI; ``None`` falls back to
            :data:`DEFAULT_LEFT_NAME` / :data:`DEFAULT_RIGHT_NAME`.
        fps: Work-file frame rate. Used only to format timestamps — ``frame``
            itself is never scaled.
        total_frames: Work-file frame count, for ``summary``.
        analysis_time_sec: Wall-clock seconds spent detecting.

    Returns:
        A report dict ready to be written as ``<piste stem>_report.json``.
    """
    touches = build_touches(scoring_events(events), fps=fps)
    left_touches = count_by_scorer(touches, "left")
    right_touches = count_by_scorer(touches, "right")

    return {
        "summary": {
            "video_path": str(video_path),
            "final_score": derive_final_score(touches),
            "total_touches": len(touches),
            "match_duration": format_duration(total_frames, fps, touches),
            "total_frames_analyzed": int(total_frames),
            "analysis_time_sec": round(analysis_time_sec, 1),
            "weapon": weapon,
            "bout_type": bout_type,
            "gender": None,
            "age_group": None,
        },
        "touches": touches,
        "left_fencer": {
            "side": "left",
            "name": left_name or DEFAULT_LEFT_NAME,
            "club": "",
            "total_touches_scored": left_touches,
            "total_touches_conceded": right_touches,
        },
        "right_fencer": {
            "side": "right",
            "name": right_name or DEFAULT_RIGHT_NAME,
            "club": "",
            "total_touches_scored": right_touches,
            "total_touches_conceded": left_touches,
        },
        "warnings": build_warnings(touches),
        "meta": {
            "source_type": "coach",
            "analysis_mode": "led_scoreboard_ocr",
            "converter": "led_report_converter",
        },
    }
