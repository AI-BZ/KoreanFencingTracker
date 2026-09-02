#!/usr/bin/env python3
"""Read a physical LED scoreboard and write the OCR report the merge picks up.

Step 2 of the piste-selection pipeline. ``prepare_piste_video.py`` has already
produced two work files from one source video (a piste crop and a scoreboard
crop, both at 30 fps) plus a config JSON holding the five scoreboard ROIs in
*scoreboard-crop* coordinates. This script runs the v3 headless detector
(``LampDetector`` + ``ScoreReader`` + ``VideoProcessor``) over the scoreboard
work file and converts the resulting ``MatchEvent``s into
``<piste stem>_report.json``.

Usage:
    cd services/analytics
    PYTHONPATH=. .venv/bin/python3 scripts/analyze_led_scoreboard.py \\
        --config data/piste_configs/<stem>_piste3.json --weapon foil

    # inspect the detected events without writing anything
    PYTHONPATH=. .venv/bin/python3 scripts/analyze_led_scoreboard.py \\
        --config ... --weapon foil --dry-run

    # track the panel instead of trusting fixed ROIs (see below)
    PYTHONPATH=. .venv/bin/python3 scripts/analyze_led_scoreboard.py \\
        --config ... --weapon foil --tracked

Two detection modes
-------------------
The default reads the five fixed ``scoreboard.rois`` and is correct only when the
camera does not move. Our own coach footage does move: on the 166 s reference
bout the panel drifts 367x306 px, and the fixed-ROI read of it produced 40 lamp
events for a 6-touch bout and the wrong final score.

``--tracked`` swaps the detection layer for ``analyzer.scoreboard_tracker``,
which follows the panel and reads lamps and score digits relative to wherever it
currently is. It uses the config's ``tracker`` block instead of
``scoreboard.rois``, needs no clock ROI, and cross-checks every lamp against the
score digits so a referee-annulled lamp is not reported as a touch. On the same
reference bout it recovers all six touches with no false positives.

Everything after detection — the ``MatchEvent`` list, the converter, the report
filename, the merge — is identical in both modes.

The end-of-bout rule
--------------------
``--tracked --clock-at-cut running`` additionally lets
``analyzer.scoreboard_tracker.infer_end_of_bout_touch`` promote a final
unconfirmed lamp to the winning touch, for a recording that stopped before the
operator entered the last point. It is off by default and refuses on anything
but a bout that can only have ended — read that function before using it.

Why the report is named after the PISTE work file, not the scoreboard one:
``generate_continuous_report.py`` analyses the piste work file and locates its
OCR report by ``find_ocr_report(video_path.stem, output_dir)``, whose first tier
matches a candidate whose base equals the analysed video's stem. Naming the
report ``<piste stem>_report.json`` therefore hits that exact tier. Naming it
after the scoreboard file (``<piste stem>_scoreboard``) would fall through to
the looser boundary/substring tiers, where an unrelated report in the same
directory could win.

Frame indices in the output are work-file frames at 30 fps, matching the piste
work file 1:1 and matching the 120 fps source not at all — see
``app/led_report_converter``.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

from app.led_report_converter import led_events_to_match_report

#: ``services/analytics/`` — config paths like ``data/work/foo.mp4`` are written
#: relative to it, and the CLI is documented as being run from there.
SERVICE_ROOT = Path(__file__).resolve().parent.parent

#: The five ROIs ``VideoProcessor.process_video_headless`` consumes. All are
#: required: a missing ``clock`` silently produces empty match times, and a
#: missing lamp or score ROI silently produces zero touches. Failing loudly
#: sends the user back to ``prepare_piste_video.py`` instead.
REQUIRED_ROI_KEYS = ("lamp_left", "lamp_right", "score_left", "score_right", "clock")

WEAPONS = ("foil", "epee", "sabre")

#: ``config["tracker"]`` keys. The two bboxes anchor the templates on frame 0 of
#: the scoreboard work file; everything after frame 0 is found by tracking, so
#: these are the only coordinates the tracked mode needs and they are the only
#: thing that changes when the crop changes.
TRACKER_HOUSING_KEY = "housing_bbox_f0"
TRACKER_PLACARD_KEY = "placard_bbox_f0"
TRACKER_PROFILE_KEY = "machine_profile"

#: The ``scoreboard.crop`` origin the two bboxes above were measured against.
#: Re-cropping the scoreboard from the source moves every pixel in the work file,
#: which would leave the stored anchors pointing at the wrong place — and because
#: a template is cut from wherever it is told, the failure is silent: the tracker
#: locks perfectly onto the wrong patch and reads lamps off the wall. Recording
#: the origin lets :func:`extract_tracker` re-base the anchors instead.
TRACKER_CROP_ORIGIN_KEY = "crop_origin"

#: Frame the anchor bboxes were measured on. Normally 0; needed when the panel
#: is not in the crop at frame 0 at all, which happens on a camera that starts
#: pointed elsewhere. Pick a frame with every lamp off — the housing template
#: spans the lamps, so lit ones get baked into every later correlation.
TRACKER_ANCHOR_FRAME_KEY = "anchor_frame"


class ConfigError(ValueError):
    """The piste config is missing or malformed in a way the user must fix."""


# ------------------------------------------------------------------
# Config handling (importable — no argparse, no I/O beyond the read)
# ------------------------------------------------------------------


def load_piste_config(config_path) -> dict:
    """Read and JSON-parse a piste config, with actionable errors."""
    path = Path(config_path)
    if not path.exists():
        raise ConfigError(f"config not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"config is not valid JSON: {path} ({exc})") from exc


def resolve_work_file(raw_path: str, service_root: Path = SERVICE_ROOT) -> Path:
    """Resolve a ``work_files.*`` entry to a concrete path.

    Config paths are written relative to ``services/analytics/`` but the script
    may be invoked from elsewhere, so an absolute path is used as-is, and a
    relative one is tried against the current directory first and the service
    root second. When neither exists the service-root candidate is returned so
    the "not found" message names the path the config actually meant.
    """
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate
    if candidate.exists():
        return candidate.resolve()
    return (service_root / candidate).resolve()


def extract_scoreboard_video(config: dict, service_root: Path = SERVICE_ROOT) -> Path:
    """Path to the scoreboard work file named by ``work_files.scoreboard``."""
    work_files = config.get("work_files")
    if not isinstance(work_files, dict):
        raise ConfigError("config has no 'work_files' object")
    raw = work_files.get("scoreboard")
    if not raw:
        raise ConfigError("config has no 'work_files.scoreboard' entry")
    return resolve_work_file(raw, service_root)


def extract_report_stem(config: dict) -> str:
    """Report filename stem — the PISTE work file's stem (see module docstring)."""
    work_files = config.get("work_files")
    if not isinstance(work_files, dict):
        raise ConfigError("config has no 'work_files' object")
    raw = work_files.get("piste")
    if not raw:
        raise ConfigError("config has no 'work_files.piste' entry")
    return Path(raw).stem


def extract_rois(config: dict) -> Dict[str, Tuple[int, int, int, int]]:
    """Convert ``scoreboard.rois`` lists into the tuples the detector wants.

    Values are already in scoreboard-crop coordinates — the same coordinate
    system as the frames the detector will read — so no transform is applied.
    """
    scoreboard = config.get("scoreboard")
    if not isinstance(scoreboard, dict):
        raise ConfigError("config has no 'scoreboard' object")
    rois_raw = scoreboard.get("rois")
    if not isinstance(rois_raw, dict):
        raise ConfigError("config has no 'scoreboard.rois' object")

    missing = [k for k in REQUIRED_ROI_KEYS if k not in rois_raw]
    if missing:
        raise ConfigError(
            f"scoreboard.rois is missing required keys: {', '.join(missing)}. "
            "Re-run prepare_piste_video.py and select all five regions."
        )

    rois: Dict[str, Tuple[int, int, int, int]] = {}
    for key in REQUIRED_ROI_KEYS:
        value = rois_raw[key]
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            raise ConfigError(f"scoreboard.rois['{key}'] must be [x, y, w, h]")
        try:
            x, y, w, h = (int(v) for v in value)
        except (TypeError, ValueError) as exc:
            raise ConfigError(
                f"scoreboard.rois['{key}'] must contain four integers"
            ) from exc
        if w <= 0 or h <= 0:
            raise ConfigError(
                f"scoreboard.rois['{key}'] has non-positive size: w={w}, h={h}"
            )
        rois[key] = (x, y, w, h)
    return rois


def extract_tracker(config: dict) -> dict:
    """Read and validate the ``tracker`` block used by ``--tracked``.

    Returns ``{"housing_bbox", "placard_bbox", "profile_name"}``. The placard is
    optional — it is the redundancy that keeps the track alive when the housing
    is clipped by the top of the crop, so a config without one still works, just
    with less headroom.
    """
    tracker = config.get("tracker")
    if not isinstance(tracker, dict):
        raise ConfigError(
            "config has no 'tracker' object, which --tracked requires. Add "
            f"{{'{TRACKER_HOUSING_KEY}': [x, y, w, h], "
            f"'{TRACKER_PROFILE_KEY}': 'kor_domestic_v1'}}."
        )

    def rect(key: str, required: bool):
        value = tracker.get(key)
        if value is None:
            if required:
                raise ConfigError(f"tracker is missing required key '{key}'")
            return None
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            raise ConfigError(f"tracker['{key}'] must be [x, y, w, h]")
        try:
            x, y, w, h = (int(v) for v in value)
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"tracker['{key}'] must contain four integers") from exc
        if w <= 0 or h <= 0:
            raise ConfigError(f"tracker['{key}'] has non-positive size: w={w}, h={h}")
        return (x, y, w, h)

    shift = _crop_shift(config, tracker)

    def shifted(box):
        if box is None:
            return None
        return (box[0] + shift[0], box[1] + shift[1], box[2], box[3])

    anchor = tracker.get(TRACKER_ANCHOR_FRAME_KEY, 0)
    try:
        anchor = int(anchor)
    except (TypeError, ValueError) as exc:
        raise ConfigError(
            f"tracker['{TRACKER_ANCHOR_FRAME_KEY}'] must be a frame index"
        ) from exc
    if anchor < 0:
        raise ConfigError(
            f"tracker['{TRACKER_ANCHOR_FRAME_KEY}'] must be >= 0 (got {anchor})"
        )

    return {
        "housing_bbox": shifted(rect(TRACKER_HOUSING_KEY, required=True)),
        "placard_bbox": shifted(rect(TRACKER_PLACARD_KEY, required=False)),
        "profile_name": tracker.get(TRACKER_PROFILE_KEY, "kor_domestic_v1"),
        "crop_shift": shift,
        "anchor_frame": anchor,
    }


def _crop_shift(config: dict, tracker: dict) -> Tuple[int, int]:
    """How far the anchors must move because the scoreboard crop was re-cut.

    Returns ``(0, 0)`` — the historical behaviour — when the tracker block does
    not record which crop it was measured against, since there is then nothing to
    compare and inventing a shift would be worse than not shifting.
    """
    recorded = tracker.get(TRACKER_CROP_ORIGIN_KEY)
    if recorded is None:
        return (0, 0)
    if not isinstance(recorded, (list, tuple)) or len(recorded) != 2:
        raise ConfigError(f"tracker['{TRACKER_CROP_ORIGIN_KEY}'] must be [x, y]")
    scoreboard = config.get("scoreboard")
    crop = scoreboard.get("crop") if isinstance(scoreboard, dict) else None
    if not isinstance(crop, dict) or "x" not in crop or "y" not in crop:
        raise ConfigError(
            f"tracker['{TRACKER_CROP_ORIGIN_KEY}'] is set but "
            "'scoreboard.crop' has no x/y to compare it against"
        )
    return (int(recorded[0]) - int(crop["x"]), int(recorded[1]) - int(crop["y"]))


def check_crop_matches_video(config: dict, width: int, height: int) -> None:
    """Fail when the scoreboard work file is not the crop the config describes.

    The tracked anchors are expressed in the coordinates of the crop named by
    ``scoreboard.crop``. If someone widens that crop but the re-transcode has not
    run yet — or ran to a different path — the anchors land somewhere arbitrary in
    the stale file, the tracker locks confidently onto whatever is there, and the
    run produces a full report of nonsense with no error. Comparing the declared
    crop size against the file's actual size costs nothing and makes that state
    impossible to reach silently.
    """
    scoreboard = config.get("scoreboard")
    crop = scoreboard.get("crop") if isinstance(scoreboard, dict) else None
    if not isinstance(crop, dict) or "w" not in crop or "h" not in crop:
        return
    if (int(crop["w"]), int(crop["h"])) == (int(width), int(height)):
        return
    raise ConfigError(
        f"scoreboard work file is {width}x{height} but the config's "
        f"scoreboard.crop describes {crop['w']}x{crop['h']}. The work file is "
        "stale — re-run prepare_piste_video.py with --only scoreboard, or revert "
        "the crop."
    )


def load_existing_meta(path) -> dict:
    """Read ``meta`` from the report this run is about to replace, or ``{}``.

    The I/O half of the preserve-meta rule, kept apart from the pure merge in
    :func:`app.led_report_converter.preserve_existing_meta`. An absent,
    unreadable or malformed previous report all come back as ``{}``: a
    regeneration must never fail because of the file it is replacing.
    """
    path = Path(path)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}
    if not isinstance(existing, dict):
        return {}
    meta = existing.get("meta")
    return meta if isinstance(meta, dict) else {}


# ------------------------------------------------------------------
# Tracked-mode warnings (importable, pure)
# ------------------------------------------------------------------


def _clock(frame: int, fps: float) -> str:
    seconds = int(frame / fps) if fps > 0 else 0
    return f"{seconds // 60}:{seconds % 60:02d}"


#: Why the lamps could not be read, in the reader's terms. Each reason implies a
#: different fix, so they must not collapse into one vague sentence — in
#: particular ``no_display`` is not low confidence. The tracker was *confident*
#: and wrong, which is the more alarming case and the one that needs the crop or
#: the anchor looked at rather than a threshold nudged.
_GAP_REASON_KO = {
    "off_frame": "점수판이 화면 밖으로 벗어남",
    "unlocked": "점수판 추적 신뢰도 미달",
    "disputed": "두 템플릿이 서로 다른 위치를 가리킴 (오탐 가능성)",
    "no_display": "추적 위치에 점등된 점수판이 없음 (엉뚱한 곳을 추적 중일 가능성)",
}


#: ``--clock-at-cut`` choices → the ``clock_running_at_cut`` argument of
#: ``infer_end_of_bout_touch``. The tracked profile has no clock ROI, so nothing
#: in the pipeline can read the clock; this is the operator asserting what it
#: showed when the recording stopped. ``unknown`` is the default and maps to
#: ``None``, which the rule treats as refusal — an operator who says nothing
#: must not be taken to have said "running".
CLOCK_AT_CUT_CHOICES = {"running": True, "expired": False, "unknown": None}


def _promoted_resolution(analysis, inference):
    """The resolution ``inference`` promoted, or ``None``.

    Resolved through ``analysis.resolutions`` by index rather than trusted from
    the inference alone, so a stale inference computed against different
    resolutions cannot silence a warning about an unrelated event.
    """
    if inference is None or not getattr(inference, "applied", False):
        return None
    index = getattr(inference, "index", None)
    resolutions = getattr(analysis, "resolutions", None) or []
    if index is None or not (0 <= index < len(resolutions)):
        return None
    return resolutions[index]


def end_of_bout_event(analysis, inference, fps: float, clock_at_cut: str):
    """The ``InferredMatchEvent`` for an applied end-of-bout inference.

    Built here rather than inside the rule because the rule is pure and knows
    nothing about ``MatchEvent``. Appending this to the detector's event list is
    all it takes for the point to reach the report by the ordinary route:
    ``scoring_events`` keeps it because it has a real ``scorer``, and
    ``build_touches`` numbers it last because it has the highest frame.
    """
    from analyzer.models import EventType, InferredMatchEvent
    from analyzer.scoreboard_tracker import LEFT, RIGHT
    from app.led_report_converter import TOUCH_SOURCE_END_OF_BOUT

    resolution = analysis.resolutions[inference.index]
    event = resolution.event
    before = resolution.score_before
    after = inference.score_after
    lamps_lit = [
        side for side, lit in ((LEFT, event.left_valid), (RIGHT, event.right_valid))
        if lit
    ]
    seconds = int(event.onset_frame / fps) if fps > 0 else 0

    return InferredMatchEvent(
        frame=event.onset_frame,
        video_timestamp=f"{seconds // 60}:{seconds % 60:02d}",
        match_time="",
        event_type=EventType.SINGLE_TOUCH.value,
        lamp_red=event.left_valid,
        lamp_green=event.right_valid,
        score_before=f"{before[0]}-{before[1]}",
        score_after=f"{after[0]}-{after[1]}",
        scorer=inference.scorer,
        description=(
            f"{'+'.join(lamps_lit) or 'no lamp'} 램프 — 점수판 갱신 전 영상 종료, "
            f"경기 종료 규칙으로 {inference.scorer} 득점 확정"
        ),
        touch_source=TOUCH_SOURCE_END_OF_BOUT,
        inference_basis={
            "onset_frame": int(event.onset_frame),
            "frames_remaining": int(analysis.frame_count - event.onset_frame),
            "clock_at_cut": clock_at_cut,
            "score_at_match_point": f"{before[0]}-{before[1]}",
            "lamps_lit": lamps_lit,
        },
    )


def tracked_warnings(analysis, fps: float = 30.0, inference=None) -> List[dict]:
    """Warnings only the tracked detector can raise, newest concern first.

    Everything here is about what the run could *not* see. The point of naming
    them in the report is that a missing touch is otherwise indistinguishable
    from a touch that never happened — which is exactly how this pipeline lost a
    real point on ``260815_bout_b`` before the panel was tracked at all.

    ``inference`` is the :class:`~analyzer.scoreboard_tracker.EndOfBoutInference`
    for this analysis, when the end-of-bout rule ran. An applied one is handled
    *here*, in the same pass that writes the undetermined and annulled lines,
    rather than by editing the list afterwards: the promoted event stops being
    reported as unconfirmed and gains an ``end_of_bout_inferred`` line instead.
    Doing it anywhere else risks a report that counts the point as a touch and
    warns in the same breath that it could not be confirmed.
    """
    from app.led_report_converter import (
        WARNING_COVERAGE_GAP,
        WARNING_DELAYED_SCORE_ENTRY,
        WARNING_END_OF_BOUT_INFERRED,
        WARNING_LAMP_ANNULLED,
        WARNING_LAMP_INCONSISTENT,
        WARNING_LAMP_OVER_SCORE,
        WARNING_LAMP_UNDETERMINED,
        WARNING_LATE_SCORE_ENTRY,
        WARNING_SIMULTANEOUS_IMPOSSIBLE,
        WARNING_SCORE_LOWER_BOUND,
        WARNING_START_SCORE_ASSUMED,
        WARNING_START_SCORE_READ,
    )

    promoted = _promoted_resolution(analysis, inference)
    warnings: List[dict] = []

    reading = getattr(analysis, "start_score_reading", None)
    start = getattr(analysis, "start_score", (0, 0))
    if getattr(analysis, "start_score_source", "caller") == "read" and reading is not None:
        if reading.score is not None:
            warnings.append({
                "type": WARNING_START_SCORE_READ,
                "message": (
                    f"경기 시작 점수 {start[0]}-{start[1]}을 점수판에서 직접 읽었습니다 "
                    f"(판독 일치율 {reading.agreement:.0%}). 이후 점수는 여기서부터 누적됩니다."
                ),
                "severity": "info",
            })
        else:
            warnings.append({
                "type": WARNING_START_SCORE_ASSUMED,
                "message": (
                    "영상 시작 시점의 점수판 숫자를 읽지 못해 0-0에서 시작한 것으로 "
                    f"가정했습니다 (사유: {reading.reason}). DE 2·3세트처럼 이전 점수를 "
                    "승계한 영상이라면 모든 점수가 그만큼 낮게 나옵니다 — "
                    "--start-score 로 직접 지정하세요."
                ),
                "severity": "warning",
            })

    for gap in analysis.coverage_gaps:
        detail = _GAP_REASON_KO.get(gap.reason, gap.reason)
        warnings.append({
            "type": WARNING_COVERAGE_GAP,
            "message": (
                f"{_clock(gap.start_frame, fps)}–{_clock(gap.end_frame, fps)} "
                f"구간 램프 판독 불가 ({detail}, {gap.frame_count}프레임). "
                "이 구간의 터치는 리포트에 없을 수 있습니다."
            ),
            "severity": "warning",
        })

    for resolution in analysis.undetermined:
        if resolution is promoted:
            continue
        # An event the priority rule demoted is a different observation from one
        # the digits could not be read for, and saying "could not compare" about
        # it would point whoever reads this at the wrong thing entirely: the
        # digits compared fine, they just said something the weapon does not
        # allow.
        rule = getattr(resolution, "priority_rule", None)
        if rule is not None:
            warnings.append({
                "type": WARNING_SIMULTANEOUS_IMPOSSIBLE,
                "message": (
                    f"{_clock(resolution.event.onset_frame, fps)} 양쪽 램프가 켜지고 "
                    f"양쪽 점수가 함께 오른 것으로 읽혔습니다. {rule.weapon}에는 양측 "
                    "동시 득점이 없으므로 둘 중 한쪽의 점수 판독이 잘못된 것이며, "
                    "어느 쪽인지 알 수 없어 이 이벤트는 미확정으로 두고 집계하지 "
                    "않았습니다."
                ),
                "severity": "warning",
            })
            continue
        warnings.append({
            "type": WARNING_LAMP_UNDETERMINED,
            "message": (
                f"{_clock(resolution.event.onset_frame, fps)} 램프 점등을 확인했으나 "
                "점수판 변화를 대조할 수 없어 득점 여부를 확정하지 못했습니다."
            ),
            "severity": "warning",
        })

    for resolution in getattr(analysis, "inconsistent", []):
        warnings.append({
            "type": WARNING_LAMP_INCONSISTENT,
            "message": (
                f"{_clock(resolution.event.onset_frame, fps)} 램프와 점수 변화가 서로 모순됩니다 "
                "(한쪽 램프만 점등됐는데 다른 쪽 점수가 변함). "
                "둘 중 하나가 오독이므로 터치로 집계하지 않았습니다."
            ),
            "severity": "warning",
        })

    for resolution in getattr(analysis, "touches", []):
        late = getattr(resolution, "promotion", None)
        if late is None:
            continue
        skipped = ", ".join(_clock(f, fps) for f in late.skipped_off_target)
        # Why the lamp was unconfirmed matters to whoever reads this: "could not
        # be compared" and "did not move" are different observations, and only
        # the second is what a referee's annulment looks like.
        immediate = (
            "점수판이 그대로였고" if late.from_verdict == "annulled"
            else "점수판을 대조할 수 없었고"
        )
        warnings.append({
            "type": WARNING_LATE_SCORE_ENTRY,
            "message": (
                f"{_clock(resolution.event.onset_frame, fps)} 유효 램프 직후에는 {immediate}, "
                f"무효 램프({skipped}) 뒤 {late.delay_sec:.1f}초 안에 "
                f"{resolution.scorer} 점수가 올랐습니다. 무효 램프는 판정과 무관하므로 "
                "이 득점을 해당 유효 램프의 터치로 집계했습니다."
            ),
            "severity": "info",
        })

    # A touch the obvious reading of the same interval called "no change". Named
    # because the alternative — reporting it as an ordinary touch — hides that
    # the score cross-check, the thing that keeps annulled lamps out of the
    # report, said no here and was overridden.
    for resolution in getattr(analysis, "touches", []):
        if not getattr(resolution, "delayed_entry", False):
            continue
        warnings.append({
            "type": WARNING_DELAYED_SCORE_ENTRY,
            "message": (
                f"{_clock(resolution.event.onset_frame, fps)} 램프 직후 몇 초 동안은 "
                "점수판이 그대로였고, 같은 구간이 끝날 무렵에야 숫자가 바뀌어 그대로 "
                f"멈춰 있었습니다. 조작원의 입력 지연으로 보고 구간 후반의 정착된 "
                f"숫자로 대조해 {resolution.scorer} 득점으로 집계했습니다."
            ),
            "severity": "info",
        })

    for resolution in getattr(analysis, "touches", []):
        rule = getattr(resolution, "priority_rule", None)
        if rule is None:
            continue
        side = "왼쪽" if resolution.scorer == "left" else "오른쪽"
        warnings.append({
            "type": WARNING_LAMP_OVER_SCORE,
            "message": (
                f"{_clock(resolution.event.onset_frame, fps)} {side} 유효 램프만 "
                "켜졌는데 양쪽 점수가 모두 변한 것으로 읽혔습니다. "
                f"{rule.weapon}에는 양측 동시 득점이 없고 램프가 점수판 픽셀 대조보다 "
                f"신뢰도가 높으므로, 램프가 지목한 {side} 득점으로 집계했습니다."
            ),
            "severity": "info",
        })

    annulled = [r for r in analysis.annulled if r is not promoted]
    if annulled:
        times = ", ".join(_clock(r.event.onset_frame, fps) for r in annulled)
        warnings.append({
            "type": WARNING_LAMP_ANNULLED,
            "message": (
                f"유효 램프가 점등됐으나 점수가 변하지 않은 이벤트 {len(annulled)}건 "
                f"({times}). 심판 무효 처리로 보고 터치에서 제외했습니다."
            ),
            "severity": "info",
        })

    if promoted is not None:
        before = promoted.score_before
        warnings.append({
            "type": WARNING_END_OF_BOUT_INFERRED,
            "message": (
                f"{_clock(promoted.event.onset_frame, fps)} 마지막 램프 이후 점수판이 갱신되기 전에 "
                f"영상이 끝났습니다. 세 조건이 모두 성립하여 "
                f"({before[0]}-{before[1]} 매치 포인트, 경기 시계 진행 중, "
                f"{inference.scorer} 선수 본인 유효 램프 점등) "
                f"경기 종료 규칙으로 마지막 득점을 {inference.scorer} 득점으로 확정했습니다."
            ),
            "severity": "info",
        })

    if not analysis.score_reliable:
        warnings.append({
            "type": WARNING_SCORE_LOWER_BOUND,
            "message": (
                "판독 불가 구간이 있어 점수는 확정값이 아니라 최소값입니다. "
                "터치별 득점자는 유효하지만 합계 점수는 실제보다 낮을 수 있습니다."
            ),
            "severity": "warning",
        })

    return warnings


# ------------------------------------------------------------------
# Presentation helpers (importable, pure)
# ------------------------------------------------------------------


def format_event_line(event) -> str:
    """One-line dump of a ``MatchEvent`` for ``--dry-run``."""
    lamps = []
    if getattr(event, "lamp_red", False):
        lamps.append("RED")
    if getattr(event, "lamp_green", False):
        lamps.append("GREEN")
    lamp_str = "+".join(lamps) if lamps else "-"
    return (
        f"  frame {getattr(event, 'frame', 0):>7}  "
        f"video {getattr(event, 'video_timestamp', ''):>9}  "
        f"clock {getattr(event, 'match_time', '') or '?':>6}  "
        f"lamp {lamp_str:<10} "
        f"{getattr(event, 'score_before', '') or '?'} -> "
        f"{(getattr(event, 'score_after', '') or '?'):<6} "
        f"scorer={getattr(event, 'scorer', None)}"
    )


def summary_lines(report: dict) -> List[str]:
    """Human-readable run summary from a converted report dict."""
    summary = report.get("summary", {})
    touches = report.get("touches", [])
    left = report.get("left_fencer", {}).get("total_touches_scored", 0)
    right = report.get("right_fencer", {}).get("total_touches_scored", 0)

    lines = [
        f"  Total touches: {len(touches)}",
        f"  Final score:   {summary.get('final_score')}",
        f"  Per side:      left {left}, right {right}",
    ]
    warnings = report.get("warnings", [])
    if warnings:
        lines.append(f"  Warnings:      {len(warnings)}")
        for w in warnings:
            lines.append(f"    [{w.get('severity')}] {w.get('type')}: {w.get('message')}")
    else:
        lines.append("  Warnings:      none")
    return lines


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read a physical LED scoreboard into an OCR report JSON.",
    )
    parser.add_argument(
        "--config", required=True,
        help="Piste config JSON written by prepare_piste_video.py",
    )
    parser.add_argument(
        "--weapon", required=True, choices=WEAPONS,
        help="Weapon. Required — the foil priority cascade is gated on it and "
             "an unrecognised value silently disables it.",
    )
    parser.add_argument(
        "--bout-type", default="pool", choices=("pool", "de"),
        help="Bout format (default: pool)",
    )
    parser.add_argument(
        "--output-dir", default="data/reports/private",
        help="Where to write <piste stem>_report.json "
             "(default: data/reports/private — these are named after real people, "
             "and private/ is the directory this repo keeps such files out of "
             "version control in)",
    )
    parser.add_argument("--left-name", default=None, help="Left fencer name")
    parser.add_argument("--right-name", default=None, help="Right fencer name")
    parser.add_argument(
        "--tracked", action="store_true",
        help="Track the panel instead of using fixed ROIs. Required for handheld "
             "or drifting footage, where fixed ROIs read the wall. Uses the "
             "config's 'tracker' block rather than 'scoreboard.rois'.",
    )
    parser.add_argument(
        "--clock-at-cut", default="unknown", choices=tuple(CLOCK_AT_CUT_CHOICES),
        help="What the match clock showed when the recording stopped (--tracked "
             "only; the tracked profile has no clock ROI, so this is your "
             "assertion, not a reading). 'running' is what lets the end-of-bout "
             "rule promote a final unconfirmed lamp to the winning touch. "
             "Default 'unknown' — the rule can never fire.",
    )
    parser.add_argument(
        "--start-score", nargs=2, type=int, default=None, metavar=("LEFT", "RIGHT"),
        help="Score already on the panel when the recording starts (--tracked "
             "only). The tracked reader tallies score *changes*, so a clip that "
             "opens mid-bout — a DE period 2 or 3, say — would otherwise report "
             "1-0 for what the panel actually shows as 8-6. Omit it and the "
             "digits are read off the panel; pass it and your value wins. When "
             "the read is declined the run says so and assumes 0-0.",
    )
    parser.add_argument(
        "--not-for-merge", default=None, metavar="REASON",
        help="Mark the report as never mergeable, with the reason. For a read "
             "that is known to be wrong in a way its own numbers do not show — "
             "a partial recovery, or a clip starting mid-bout whose score "
             "progression is therefore not the real one.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print detected events and the derived score; write nothing.",
    )
    return parser


def track_from_config(video, tracker, start_score=None, weapon=None):
    """Run the tracked detector for a validated ``tracker`` block.

    Split out of :func:`run_tracked` so a second tool can reproduce this exact
    read — same profile, same anchor, same defaults — without reimplementing it
    and drifting from what the report was generated with. Returns
    ``(analysis, elapsed_seconds)``.

    ``weapon`` is part of "this exact read", not decoration: under priority it
    decides what a comparison reading both sides as changed resolves to, so a
    second tool re-reading the same file without it can get a different set of
    touches than the report holds.
    """
    from analyzer.scoreboard_tracker import get_machine_profile, track_scoreboard_video

    profile = get_machine_profile(tracker["profile_name"])
    started = time.time()
    analysis = track_scoreboard_video(
        str(video),
        housing_bbox=tracker["housing_bbox"],
        placard_bbox=tracker["placard_bbox"],
        profile=profile,
        anchor_frame=tracker["anchor_frame"],
        start_score=(
            (int(start_score[0]), int(start_score[1]))
            if start_score is not None else None
        ),
        weapon=weapon,
    )
    return analysis, time.time() - started


def run_tracked(video, tracker, fps, clock_at_cut="unknown", bout_type="pool",
                start_score=None, weapon=None):
    """``--tracked`` detection: returns ``(events, extra_warnings, elapsed)``."""
    from analyzer.scoreboard_tracker import (
        END_OF_BOUT_TARGET,
        get_machine_profile,
        infer_end_of_bout_touch,
        resolutions_to_match_events,
    )

    profile = get_machine_profile(tracker["profile_name"])
    print(f"  Mode:       tracked (profile {profile.name})")
    print(
        f"  Anchor:     frame {tracker['anchor_frame']} "
        f"housing={tracker['housing_bbox']} placard={tracker['placard_bbox']}"
    )

    if start_score is not None:
        print(
            f"  Start:      {start_score[0]}-{start_score[1]} (given; the digit "
            f"reader is not consulted)"
        )
    analysis, elapsed = track_from_config(
        video, tracker, start_score=start_score, weapon=weapon)

    reading = analysis.start_score_reading
    if reading is not None and start_score is None:
        got = analysis.start_score
        if reading.score is not None:
            print(
                f"  Start:      {got[0]}-{got[1]} read off the panel "
                f"(agreement {reading.agreement:.0%}, "
                f"{reading.samples['left']}/{reading.samples['right']} reads L/R)"
            )
        else:
            print(
                f"  Start:      NOT READ ({reading.reason}, "
                f"{reading.samples['left']}/{reading.samples['right']} reads L/R) "
                f"— assuming 0-0. Pass --start-score if the clip opens mid-bout."
            )

    gap_frames = sum(g.frame_count for g in analysis.coverage_gaps)
    print(
        f"  Tracking:   lock {analysis.lock_rate:.2%}, lamps readable "
        f"{analysis.readable_rate:.2%} ({gap_frames} frames in "
        f"{len(analysis.coverage_gaps)} gaps)"
    )
    print(
        f"  Lamps:      {len(analysis.events)} events -> "
        f"{len(analysis.touches)} touches, {len(analysis.annulled)} annulled, "
        f"{len(analysis.undetermined)} undetermined"
    )
    if not analysis.score_reliable:
        print("  Score:      LOWER BOUND — coverage was incomplete")

    inference = infer_end_of_bout_touch(
        analysis.resolutions,
        target_score=END_OF_BOUT_TARGET[bout_type],
        frame_count=analysis.frame_count,
        fps=analysis.fps,
        clock_running_at_cut=CLOCK_AT_CUT_CHOICES[clock_at_cut],
    )
    events = resolutions_to_match_events(analysis.resolutions, fps=fps)
    if inference.applied:
        promoted = analysis.resolutions[inference.index]
        print(
            f"  End-of-bout: APPLIED — frame {promoted.event.onset_frame} promoted to a "
            f"{inference.scorer} touch, score {inference.score_after[0]}-"
            f"{inference.score_after[1]} (clock asserted {clock_at_cut})"
        )
        events.append(end_of_bout_event(analysis, inference, fps, clock_at_cut))
    else:
        print(f"  End-of-bout: not applied (reason: {inference.reason})")

    return (
        events,
        tracked_warnings(analysis, fps=fps, inference=inference),
        elapsed,
    )


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.clock_at_cut != "unknown" and not args.tracked:
        # The fixed-ROI path produces no TouchResolutions, so there is nothing
        # for the end-of-bout rule to promote. Accepting the assertion and
        # quietly doing nothing with it would look exactly like applying it.
        parser.error("--clock-at-cut only applies to --tracked runs")

    try:
        config = load_piste_config(args.config)
        video = extract_scoreboard_video(config)
        rois = {} if args.tracked else extract_rois(config)
        tracker = extract_tracker(config) if args.tracked else None
        stem = extract_report_stem(config)
    except ConfigError as exc:
        print(f"ERROR: {exc}")
        return 1

    if not video.exists():
        print(f"ERROR: scoreboard work file not found: {video}")
        print("       Run prepare_piste_video.py first.")
        return 1

    # Imported late: cv2/numpy pull in a heavy stack that the config-parsing
    # helpers above (and their tests) do not need.
    try:
        import cv2
    except ImportError:
        print("ERROR: opencv-python required.")
        return 1
    if not args.tracked:
        from analyzer.video_processor import VideoProcessor

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        print(f"ERROR: cannot open scoreboard video: {video}")
        return 1
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    if args.tracked:
        try:
            check_crop_matches_video(config, width, height)
        except ConfigError as exc:
            print(f"ERROR: {exc}")
            return 1

    print("LED scoreboard analysis")
    print(f"  Config:     {args.config}")
    print(f"  Scoreboard: {video}")
    print(f"  Frames:     {total_frames} @ {fps:.2f}fps")

    if args.tracked:
        events, extra_warnings, elapsed = run_tracked(
            video, tracker, fps,
            clock_at_cut=args.clock_at_cut,
            bout_type=args.bout_type,
            start_score=args.start_score,
            weapon=args.weapon,
        )
    else:
        print(f"  ROIs:       {', '.join(f'{k}={v}' for k, v in rois.items())}")
        started = time.time()
        events = VideoProcessor().process_video_headless(str(video), rois)
        elapsed = time.time() - started
        extra_warnings = []
    print(f"  Detected {len(events)} lamp events in {elapsed:.1f}s")

    # Read the meta of the report we are about to replace BEFORE building the
    # new one, so a hand-set share token survives regeneration. Done even for
    # --dry-run so the preview is the file that would actually be written.
    output_path = Path(args.output_dir) / f"{stem}_report.json"
    existing_meta = load_existing_meta(output_path)

    report = led_events_to_match_report(
        events,
        video_path=str(video),
        weapon=args.weapon,
        bout_type=args.bout_type,
        left_name=args.left_name,
        right_name=args.right_name,
        fps=fps,
        total_frames=total_frames,
        analysis_time_sec=elapsed,
        clock_available=not args.tracked,
        extra_warnings=extra_warnings,
        analysis_mode="led_scoreboard_tracked" if args.tracked else "led_scoreboard_ocr",
        existing_meta=existing_meta,
        not_for_merge=args.not_for_merge,
    )
    carried = [k for k in existing_meta if k not in ("source_type", "analysis_mode", "converter")]
    if carried:
        print(f"  Carried over from the previous report: {', '.join(sorted(carried))}")

    if args.dry_run:
        print("\nAll MatchEvents (including non-scoring):")
        if not events:
            print("  (none)")
        for event in events:
            print(format_event_line(event))
        print("\nDerived:")
        for line in summary_lines(report):
            print(line)
        print("\n  --dry-run: nothing written.")
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n  Saved: {output_path}")
    for line in summary_lines(report):
        print(line)
    print(
        f"\n  generate_continuous_report.py will auto-match this report when it "
        f"analyses a video whose stem is '{stem}'."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
