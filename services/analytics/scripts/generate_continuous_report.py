"""
Generate a continuous analysis report from a full bout video.

Runs YOLO11-Pose → PoseAnalyzer.analyze_continuous() → FencerProfileBuilder
and saves the result as a report-compatible JSON for the web dashboard.

Usage:
    cd services/analytics
    PYTHONPATH=. .venv/bin/python3 scripts/generate_continuous_report.py data/raw/usa_fencing_sample_0HeqT9us5wA.mp4
    PYTHONPATH=. .venv/bin/python3 scripts/generate_continuous_report.py data/raw/usa_fencing_sample_0HeqT9us5wA.mp4 --my-fencer left
"""

import argparse
import json
import resource
import sys
import time
from dataclasses import dataclass
from pathlib import Path

try:
    import cv2
except ImportError:
    print("ERROR: opencv-python required.")
    sys.exit(1)

from analyzer.config import POSE_KEYPOINT_CONFIDENCE, PRIORITY_WINDOW_LEAD_SEC
from analyzer.touch_matching import (
    annotate_touch_lamp,
    annotate_touch_outcomes,
    classify_exchange_sides,
    summarize_attack_outcomes,
)
from ml.weapon_analyzers import build_priority_judge


def format_timestamp(frame: int, fps: float) -> str:
    """Convert frame number to MM:SS string."""
    seconds = frame / fps
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}:{s:02d}"


def peak_memory_gb() -> float:
    """Peak resident set size of this process, in GB.

    ``ru_maxrss`` is bytes on macOS/BSD but kilobytes on Linux, so the raw value
    is off by 1024x depending on where the pipeline runs. Normalising here keeps
    the number printed at the end of a run comparable across machines.
    """
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform != "darwin":
        peak *= 1024
    return peak / (1024 ** 3)


# How many sampled frames to hold in memory before handing them to the pose
# estimator. This buys nothing in throughput — PoseEstimator.estimate_poses_batch
# is a per-frame loop, so pose results are byte-identical at any chunk size — it
# exists purely to bound the live frame buffer. At 720p a decoded BGR frame is
# ~2.8MB, so 256 caps the buffer near 0.7GB regardless of bout length, while
# still passing a list to the batch API so a future implementation that does
# real batching keeps something worth batching.
POSE_CHUNK_FRAMES = 256


# Capture-pipeline prefixes that the OCR report filename never carries.
_VIDEO_STEM_PREFIXES = ("usaf_", "usa_fencing_sample_")
_YOUTUBE_ID_LEN = 11
# Below this length a bare substring match is too loose to trust.
_MIN_SUBSTRING_BASE_LEN = 8


def find_ocr_report(video_stem: str, output_dir) -> "Path | None":
    """Locate the OCR report JSON that belongs to ``video_stem``.

    Video files are often named ``<description>_<youtubeID>.mp4`` while their OCR
    report is just ``<youtubeID>_report.json``. Stripping known prefixes is not
    enough for those — the whole stem is not a substring of the candidate — so
    matching runs in tiers, strictest first, and an exact hit always beats a
    substring hit regardless of directory order:

    1. exact: candidate base equals the stem, the prefix-stripped stem, or the
       trailing 11-char YouTube ID
    2. boundary: the stem starts or ends with the candidate base at an
       underscore boundary
    3. substring (legacy behaviour), only for bases long enough to be specific

    Returns the matching path, or None — callers must warn rather than silently
    produce a report with no touches.
    """
    candidates = sorted(
        p for p in Path(output_dir).glob("*_report.json")
        if "_continuous_report" not in p.stem
    )
    if not candidates:
        return None

    stripped = video_stem
    for prefix in _VIDEO_STEM_PREFIXES:
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix):]
            break

    tail = video_stem.rsplit("_", 1)[-1]
    youtube_id = tail if len(tail) == _YOUTUBE_ID_LEN else None

    def _base(path) -> str:
        return path.stem[: -len("_report")] if path.stem.endswith("_report") else path.stem

    exact = {video_stem, stripped}
    if youtube_id:
        exact.add(youtube_id)

    for candidate in candidates:
        if _base(candidate) in exact:
            return candidate

    for candidate in candidates:
        base = _base(candidate)
        if not base:
            continue
        if (
            video_stem.endswith(f"_{base}")
            or stripped.endswith(f"_{base}")
            or video_stem.startswith(f"{base}_")
        ):
            return candidate

    for candidate in candidates:
        base = _base(candidate)
        if len(base) < _MIN_SUBSTRING_BASE_LEN:
            continue
        if stripped in base or base in stripped:
            return candidate

    return None


PRIORITY_SERIES_KEYS = (
    "arm_series_left", "arm_series_right",
    "hip_x_series_left", "hip_x_series_right",
)


def validate_priority_series_frames(exchanges: list, lead_frames: int) -> None:
    """Raise if a serialized priority series sits outside the window it describes.

    ``analyze_continuous`` works in sample indices while the report is written in
    original video frames, and the two are a factor of ``--sample-every`` apart.
    Forgetting that multiplication once already cost this pipeline a silently
    wrong ``min_distance_frame``; here it would attach one exchange's arm motion
    to another's verdict, which no downstream check would catch. So the invariant
    is asserted at write time instead of being left to code review.

    Every series frame must fall within
    ``[start_frame − lead_frames − slack, min_distance_frame + slack]``.
    """
    slack = 1
    for ex in exchanges:
        low = ex["start_frame"] - lead_frames - slack
        high = ex.get("min_distance_frame", ex["end_frame"]) + slack
        for key in PRIORITY_SERIES_KEYS:
            for frame, _value in ex.get(key) or ():
                if not (low <= frame <= high):
                    raise ValueError(
                        f"exchange {ex.get('exchange_number')}: {key} frame "
                        f"{frame} outside [{low}, {high}] — sample-index to "
                        "video-frame conversion is wrong",
                    )


def _distance_zone(bh: float) -> str:
    """Map BH distance to zone name."""
    if bh > 1.8:
        return "out_of_distance"
    elif bh > 1.5:
        return "advance_lunge"
    elif bh > 1.2:
        return "lunge"
    elif bh > 0.8:
        return "extension"
    else:
        return "infighting"


# ---------------------------------------------------------------------------
# Lamp fields supplied by the OCR report itself (physical LED scoreboard)
#
# Two OCR sources reach this merge and they deliver lamps differently:
#
# * TV broadcast — the OCR report has no lamp fields at all. Lamps are read off
#   the broadcast overlay afterwards by ``scripts/detect_touch_lamps.py``, which
#   calls ``annotate_touch_lamp`` on the finished report.
# * Physical LED box (``app/led_report_converter.py``) — the lamps come from the
#   scoring box itself and are already on every touch when it arrives here.
#   ``detect_touch_lamps.py`` cannot serve this path: it reads the lamp bar out
#   of the *analysed* video, which in piste mode is the piste crop — the
#   scoreboard is not in that frame.
#
# So for the LED path nothing ever ran the ``unclear`` → ``no_priority_call``
# promotion that lives in ``annotate_touch_lamp``: the lamp fields landed in the
# report, but ``attack_outcome_detail``/``_ko`` stayed unset and
# ``no_priority_call_touches`` counted 0 no matter how many single-lamp touches
# there were. The promotion is applied here instead, by handing the touch's own
# lamp fields back to the same function, so both paths produce the same verdicts.
# ---------------------------------------------------------------------------

#: Marks a lamp reading that came from a physical scoring box rather than from
#: pixel measurements of a broadcast overlay.
LED_LAMP_SOURCE = "led_scoreboard"


@dataclass
class _SuppliedLampReading:
    """Minimal stand-in for ``analyzer.tv_overlay_ocr.LampReading``.

    ``annotate_touch_lamp`` only ever touches ``pattern``, ``confidence``,
    ``start_frame`` and ``to_dict()``, so reusing it needs no more than this.
    A real ``LampReading`` is deliberately *not* constructed: its per-side
    fields (peak fill, on-frames, sampled frames) are measurements of a
    broadcast overlay that nobody made here, and defaulting them to zeros would
    write invented numbers into ``lamp_detail``.

    ``start_frame`` stays ``None`` for the same reason — the LED path records
    one frame per event, so there is no separately observed lamp-onset frame and
    therefore no honest ``lead_frames``.
    """

    pattern: "str | None"
    confidence: float = 0.0
    start_frame: "int | None" = None

    def to_dict(self) -> dict:
        return {
            "pattern": self.pattern,
            "confidence": self.confidence,
            "source": LED_LAMP_SOURCE,
        }


def report_carries_lamp_fields(touches) -> bool:
    """True when the OCR report arrived with its own per-touch lamp readings.

    The discriminator between the two OCR sources. A TV-broadcast report has no
    ``lamp_pattern`` key on any touch at merge time, so this is False and the
    merge behaves exactly as it always has.
    """
    return any("lamp_pattern" in t for t in touches or ())


def promote_supplied_lamp_outcomes(touches) -> int:
    """Apply ``annotate_touch_lamp`` using each touch's own lamp fields.

    Must run *after* ``annotate_touch_outcomes`` (it refines a decided outcome)
    and *before* ``summarize_attack_outcomes`` (which counts the promoted
    outcome). Returns how many touches changed ``attack_outcome``.

    Touches with no lamp pattern are annotated with ``None`` rather than skipped,
    so every touch in the report ends up with the same set of keys — the same
    shape the TV path produces once ``detect_touch_lamps.py`` has run.

    All the judgement — single lamp promotes, double lamp does not, a lamp that
    contradicts the scorer is ignored, a decided verdict is never downgraded —
    stays in ``analyzer.touch_matching``; duplicating it here would let the two
    paths drift.
    """
    promoted = 0
    for touch in touches or ():
        pattern = touch.get("lamp_pattern")
        if pattern is None:
            annotate_touch_lamp(touch, None)
            continue
        try:
            confidence = float(touch.get("lamp_confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        before = touch.get("attack_outcome")
        annotate_touch_lamp(
            touch, _SuppliedLampReading(pattern=pattern, confidence=confidence),
        )
        if touch.get("attack_outcome") != before:
            promoted += 1
    return promoted


# ---------------------------------------------------------------------------
# Piste mode (multi-piste venue recordings)
#
# A tripod-side recording of a venue shows several pistes at once, plus
# referees and scorekeepers in the foreground. ``scripts/prepare_piste_video.py``
# crops one piste into a "work file" and writes a config JSON describing it; the
# flags below feed that config into the pose estimator so only the two fencers
# on the target piste are analysed.
#
# EVERY pixel value read from the config's ``piste`` block is in WORK-FILE
# coordinates — the cropped, downscaled video this script is pointed at — never
# 4K-source and never scoreboard-crop coordinates. The conversion happens once,
# in the preparation script.
# ---------------------------------------------------------------------------

# Defaults for the optional pose knobs, from the design doc (§1.2). They only
# ever apply in piste mode: without --piste-config the estimator is constructed
# with no arguments at all, so TV-broadcast output is unaffected.
PISTE_DEFAULT_POSE_CONF = 0.35
PISTE_DEFAULT_POSE_IMGSZ = 1280
PISTE_DEFAULT_POSE_MAX_DET = 8

GATE_AUDIT_DIR = Path("data/work/audit")

# COCO limb pairs, for drawing a readable skeleton on the gate-audit images.
_GATE_SKELETON_EDGES = (
    (5, 6), (5, 7), (7, 9), (6, 8), (8, 10),
    (5, 11), (6, 12), (11, 12),
    (11, 13), (13, 15), (12, 14), (14, 16),
)
_GATE_SIDE_COLORS = {
    "left": (0, 255, 0),        # BGR green
    "right": (0, 165, 255),     # BGR orange
    None: (200, 200, 200),
}
_GATE_BAND_COLOR = (0, 255, 255)  # BGR yellow


class PisteConfigError(ValueError):
    """A --piste-config file is missing, unreadable, or missing required fields.

    Raised rather than returning None so a typo in the config path can never be
    mistaken for "run in normal mode": piste mode changes which people are
    analysed at all, and silently falling back would produce a plausible-looking
    report built from referees.
    """


def load_piste_config(path) -> dict:
    """Load and minimally validate a piste config JSON.

    Only the structure this script depends on is checked here — the ``piste``
    block. The ``scoreboard`` block is consumed by the LED/OCR path and may be
    absent for a pose-only run.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise PisteConfigError(f"piste config not found: {config_path}")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as exc:
        raise PisteConfigError(
            f"piste config is not valid JSON: {config_path} ({exc})",
        ) from exc
    except OSError as exc:
        raise PisteConfigError(
            f"piste config could not be read: {config_path} ({exc})",
        ) from exc

    if not isinstance(config, dict):
        raise PisteConfigError(
            f"piste config must be a JSON object, got {type(config).__name__}: "
            f"{config_path}",
        )
    piste = config.get("piste")
    if piste is None:
        raise PisteConfigError(
            f"piste config has no 'piste' block: {config_path}",
        )
    if not isinstance(piste, dict):
        raise PisteConfigError(
            f"piste config 'piste' must be an object, got "
            f"{type(piste).__name__}: {config_path}",
        )
    return config


def _positive_number(piste: dict, key: str, default, *, kind):
    value = piste.get(key, default)
    if isinstance(value, bool) or not isinstance(value, kind):
        raise PisteConfigError(
            f"piste.{key} must be a number, got {value!r}",
        )
    if value <= 0:
        raise PisteConfigError(f"piste.{key} must be > 0, got {value!r}")
    return value


def piste_estimator_kwargs(config: dict) -> dict:
    """Translate a piste config into PoseEstimator constructor arguments.

    Returns a dict with ``confidence``, ``imgsz``, ``max_det`` and
    ``foot_band_work`` (a ``(min, max)`` tuple of WORK-FILE pixel rows, which the
    caller wraps in a ``PisteGate``). Kept free of any ``ml`` import so it can be
    tested without loading YOLO.
    """
    piste = config["piste"]

    band = piste.get("foot_band_work")
    if band is None:
        raise PisteConfigError(
            "piste.foot_band_work is required — it is the work-file foot band "
            "that selects the target piste's fencers",
        )
    if isinstance(band, (str, bytes)) or not isinstance(band, (list, tuple)):
        raise PisteConfigError(
            f"piste.foot_band_work must be a [y_min, y_max] list, got {band!r}",
        )
    if len(band) != 2:
        raise PisteConfigError(
            f"piste.foot_band_work must have exactly 2 values, got {len(band)}: "
            f"{band!r}",
        )
    for v in band:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise PisteConfigError(
                f"piste.foot_band_work values must be numbers, got {band!r}",
            )
    y_min, y_max = float(band[0]), float(band[1])
    if y_min >= y_max:
        raise PisteConfigError(
            f"piste.foot_band_work must be [y_min, y_max] with y_min < y_max, "
            f"got {band!r}",
        )

    confidence = _positive_number(
        piste, "pose_conf", PISTE_DEFAULT_POSE_CONF, kind=(int, float),
    )
    if confidence > 1:
        raise PisteConfigError(
            f"piste.pose_conf must be in (0, 1], got {confidence!r}",
        )
    imgsz = _positive_number(
        piste, "pose_imgsz", PISTE_DEFAULT_POSE_IMGSZ, kind=int,
    )
    max_det = _positive_number(
        piste, "pose_max_det", PISTE_DEFAULT_POSE_MAX_DET, kind=int,
    )

    return {
        "confidence": float(confidence),
        "imgsz": int(imgsz),
        "max_det": int(max_det),
        "foot_band_work": (y_min, y_max),
    }


def report_source_type(piste_config) -> str:
    """Which ``meta.source_type`` this run produces.

    A piste work file comes from a tripod at the side of the strip — the "coach"
    source type. Everything else keeps the historical ``tv_broadcast`` value, so
    existing reports and the dashboard branches that read this field do not
    shift.
    """
    return "coach" if piste_config else "tv_broadcast"


def format_piste_banner(config_path, kwargs: dict) -> str:
    """Operator-visible confirmation that the piste gate is actually on.

    Silently running with the gate off looks identical in the logs but analyses
    whoever YOLO ranked highest — often a foreground referee — so the settings
    are printed where they cannot be missed.
    """
    y_min, y_max = kwargs["foot_band_work"]
    return "\n".join([
        "-" * 60,
        "  PISTE MODE ACTIVE (target-piste gate on)",
        f"    config:       {config_path}",
        f"    foot band:    y {y_min:g}–{y_max:g}  (work-file pixels)",
        f"    pose imgsz:   {kwargs['imgsz']}",
        f"    pose max_det: {kwargs['max_det']}",
        f"    pose conf:    {kwargs['confidence']}",
        "-" * 60,
    ])


def resolve_gate_audit(gate_audit, piste_config) -> "tuple[int, str | None]":
    """Decide how many gate-audit frames to write, and why not if zero.

    ``--gate-audit`` draws the gate's decisions, so it means nothing without a
    gate. Rather than failing a multi-minute run over a flag combination, the
    request is dropped and the reason returned for printing.
    """
    count = int(gate_audit or 0)
    if count <= 0:
        return 0, None
    if not piste_config:
        return 0, (
            "--gate-audit ignored: it visualises the piste gate, which is only "
            "active with --piste-config."
        )
    return count, None


def audit_frame_indices(total_frames: int, count: int, sample_every: int = 1) -> list:
    """Pick ``count`` frame indices spread across the video.

    Indices land on multiples of ``sample_every`` so every audited frame is one
    the pipeline actually posed, and are taken at bin centres so the first and
    last frames (often black or truncated) are not the sample.
    """
    if count <= 0 or total_frames <= 0:
        return []
    stride = max(1, int(sample_every))
    picked = set()
    for i in range(count):
        pos = int((i + 0.5) * total_frames / count)
        pos = min(max(pos, 0), total_frames - 1)
        picked.add(pos - (pos % stride))
    return sorted(picked)


def _display_foot_y(fencer, keypoint_conf: float = POSE_KEYPOINT_CONFIDENCE):
    """Foot line used for the audit label only.

    Mirrors the estimator's rule (lowest confident ankle, else bbox bottom) so
    the drawn number can be read against the band, but it is a display aid — the
    selection itself already happened inside the estimator.
    """
    ankles = [
        fencer.keypoints[i].y
        for i in (15, 16)
        if len(fencer.keypoints) > i
        and fencer.keypoints[i].confidence > keypoint_conf
    ]
    if ankles:
        return max(ankles)
    if fencer.bbox and len(fencer.bbox) >= 4:
        return float(fencer.bbox[3])
    return None


def annotate_gate_frame(frame, fencers, foot_band, keypoint_conf: float = POSE_KEYPOINT_CONFIDENCE):
    """Draw the gate's verdict on a copy of ``frame`` for human inspection.

    Only fencers that survived the gate are passed in (the estimator drops the
    rest), so the check the operator performs is: are the two labelled skeletons
    the intended pair, and do their feet sit inside the drawn band?
    """
    canvas = frame.copy()
    height, width = canvas.shape[:2]

    y_min, y_max = foot_band
    for y in (y_min, y_max):
        row = int(round(y))
        if 0 <= row < height:
            cv2.line(canvas, (0, row), (width - 1, row), _GATE_BAND_COLOR, 2)
    cv2.putText(
        canvas, f"foot band {y_min:g}-{y_max:g}", (8, 22),
        cv2.FONT_HERSHEY_SIMPLEX, 0.6, _GATE_BAND_COLOR, 2,
    )

    for fencer in fencers:
        color = _GATE_SIDE_COLORS.get(fencer.side, _GATE_SIDE_COLORS[None])
        if fencer.bbox and len(fencer.bbox) >= 4:
            x1, y1, x2, y2 = (int(round(v)) for v in fencer.bbox[:4])
            cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
            foot_y = _display_foot_y(fencer, keypoint_conf)
            label = f"{fencer.side or '?'} conf={fencer.person_confidence:.2f}"
            if foot_y is not None:
                label += f" foot_y={foot_y:.0f}"
            cv2.putText(
                canvas, label, (x1, max(y1 - 6, 12)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2,
            )

        kps = fencer.keypoints or []
        for a, b in _GATE_SKELETON_EDGES:
            if len(kps) <= max(a, b):
                continue
            ka, kb = kps[a], kps[b]
            if ka.confidence <= keypoint_conf or kb.confidence <= keypoint_conf:
                continue
            cv2.line(
                canvas,
                (int(round(ka.x)), int(round(ka.y))),
                (int(round(kb.x)), int(round(kb.y))),
                color, 2,
            )
        for kp in kps:
            if kp.confidence > keypoint_conf:
                cv2.circle(canvas, (int(round(kp.x)), int(round(kp.y))), 3, color, -1)

    return canvas


def gate_audit_path(audit_dir, video_stem: str, frame_idx: int) -> Path:
    """``<audit_dir>/<stem>_gate_<frameidx>.jpg`` — frame index is WORK-FILE."""
    return Path(audit_dir) / f"{video_stem}_gate_{frame_idx:06d}.jpg"


def write_gate_audit_frames(
    video_path, estimator, frame_indices, foot_band, audit_dir, video_stem: str,
) -> list:
    """Re-read the chosen frames and write annotated JPEGs.

    Deliberately a second pass with its own ``VideoCapture``: buffering these
    frames during the main loop is what the chunked streaming loop exists to
    avoid (see ``_flush_chunk``). Here exactly one decoded frame is alive at a
    time, so the cost is a seek per audit image and nothing added to the peak.
    """
    if not frame_indices:
        return []

    audit_dir = Path(audit_dir)
    audit_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"  WARNING: gate audit skipped, cannot reopen video: {video_path}")
        return []

    written = []
    try:
        for idx in frame_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if not ret:
                print(f"  WARNING: gate audit could not read frame {idx}")
                continue
            # Seeking a long-GOP file can land on a nearby frame; name the image
            # after the frame actually decoded so the operator can scrub to it.
            pos = int(cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1
            actual_idx = pos if pos >= 0 else idx
            result = estimator.estimate_pose(frame, frame_idx=actual_idx)
            annotated = annotate_gate_frame(frame, result.fencers, foot_band)
            out_path = gate_audit_path(audit_dir, video_stem, actual_idx)
            if cv2.imwrite(str(out_path), annotated):
                written.append(out_path)
            else:
                print(f"  WARNING: gate audit could not write {out_path}")
            frame = None
            annotated = None
    finally:
        cap.release()

    return written


def main():
    parser = argparse.ArgumentParser(description="Generate continuous analysis report")
    parser.add_argument("video", type=str, help="Path to video file")
    parser.add_argument(
        "--my-fencer", type=str, default="left", choices=["left", "right"],
        help="Fencer side for perspective analysis",
    )
    parser.add_argument(
        "--sample-every", type=int, default=3,
        help="Frame sampling interval (default: 3)",
    )
    parser.add_argument(
        "--output-dir", type=str, default="data/reports",
        help="Output directory for report JSON",
    )
    parser.add_argument(
        "--merge-ocr", type=str, default=None,
        help="Path to existing OCR report JSON to merge scoring data (auto-detected if not specified)",
    )
    parser.add_argument(
        "--weapon", type=str, default=None,
        choices=["foil", "epee", "sabre"],
        help=(
            "Override the weapon when the filename defeats the metadata parser. "
            "Foil priority estimation is gated on this, so an unrecognised "
            "filename would otherwise silently disable it."
        ),
    )
    parser.add_argument(
        "--piste-config", type=str, default=None,
        help=(
            "Path to a piste config JSON from prepare_piste_video.py. Analyses a "
            "cropped single-piste work file: restricts pose detection to the "
            "fencers whose feet fall in the config's work-file foot band, and "
            "records the report as a coach-side recording. Without it the "
            "estimator runs exactly as before."
        ),
    )
    parser.add_argument(
        "--gate-audit", type=int, default=0, metavar="N",
        help=(
            "Write N annotated frames spread across the video to "
            "data/work/audit/ so the piste gate's fencer selection can be "
            "checked by eye. Requires --piste-config; ignored without it."
        ),
    )
    parser.add_argument(
        "--with-overlays", action="store_true",
        help="Generate pose-overlay mp4 clips for each event after report generation",
    )
    parser.add_argument(
        "--overlays-all", action="store_true",
        help="Generate overlay clips for all exchanges (not just touches). Implies --with-overlays",
    )
    args = parser.parse_args()

    if args.overlays_all:
        args.with_overlays = True

    # Resolve piste mode before anything expensive: a typo in the config path
    # must fail now, not after several minutes of pose estimation.
    piste_kwargs = None
    if args.piste_config:
        try:
            piste_config = load_piste_config(args.piste_config)
            piste_kwargs = piste_estimator_kwargs(piste_config)
        except PisteConfigError as exc:
            print(f"ERROR: {exc}")
            sys.exit(1)

    gate_audit_count, gate_audit_note = resolve_gate_audit(
        args.gate_audit, args.piste_config,
    )
    if gate_audit_note:
        print(f"  WARNING: {gate_audit_note}")

    video_path = Path(args.video)
    if not video_path.exists():
        print(f"ERROR: Video not found: {video_path}")
        sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Video info
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"ERROR: Cannot open video: {video_path}")
        sys.exit(1)

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_sec = total_frames / fps

    # Extract frames
    print(f"\n{'='*60}")
    print(f"  Continuous Analysis Report Generator")
    print(f"{'='*60}")
    print(f"  Video:       {video_path.name}")
    print(f"  Duration:    {int(duration_sec//60)}:{int(duration_sec%60):02d}")
    print(f"  FPS:         {fps:.1f}")
    print(f"  Total frames:{total_frames}")
    print(f"  Sample every:{args.sample_every}")
    print(f"  My fencer:   {args.my_fencer}")
    print(f"{'='*60}\n")

    # Import ML modules
    from ml.pose_estimator import PisteGate, PoseEstimator
    from ml.pose_analyzer import PoseAnalyzer
    from ml.fencer_profile import FencerProfileBuilder

    print("Loading YOLO11-Pose model...")
    if piste_kwargs is not None:
        print(format_piste_banner(args.piste_config, piste_kwargs))
        estimator = PoseEstimator(
            confidence=piste_kwargs["confidence"],
            imgsz=piste_kwargs["imgsz"],
            max_det=piste_kwargs["max_det"],
            piste_gate=PisteGate(*piste_kwargs["foot_band_work"]),
        )
    else:
        # Unchanged default path — TV-broadcast output must stay byte-identical.
        estimator = PoseEstimator()
    analyzer = PoseAnalyzer()
    analyzer.fps = fps

    # Decode every frame, keep only the sampled ones, and run pose estimation on
    # each chunk before reading the next.
    #
    # The previous shape collected every sampled frame into one list and only
    # then called the estimator. At 720p / --sample-every 3 that accumulates
    # ~1.7GB per minute of video, which held 32.7GB for a 20-minute bout and got
    # the process killed with no traceback. Nothing downstream needs the pixels:
    # `pose_results` carries joint coordinates only (a few KB per frame), so the
    # frames can be dropped the moment inference returns.
    print("Reading frames + estimating poses...")
    t0 = time.time()
    pose_results = []
    chunk = []
    read_count = 0
    sampled_count = 0

    def _flush_chunk():
        """Infer on the buffered frames, then drop the references."""
        nonlocal chunk, sampled_count
        if not chunk:
            return
        # start_idx keeps frame_idx continuous across chunks, so pose_results is
        # indexed exactly as it was when the whole video went in as one list.
        pose_results.extend(
            estimator.estimate_poses_batch(chunk, start_idx=sampled_count)
        )
        sampled_count += len(chunk)
        chunk = []

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if read_count % args.sample_every == 0:
            chunk.append(frame)
            if len(chunk) >= POSE_CHUNK_FRAMES:
                _flush_chunk()
                print(
                    f"  {sampled_count} sampled frames posed "
                    f"({read_count + 1}/{total_frames} read, "
                    f"peak {peak_memory_gb():.1f}GB)",
                    flush=True,
                )
        read_count += 1
        frame = None  # release the decoded frame we chose not to sample
    cap.release()
    _flush_chunk()
    print(
        f"  {read_count} frames read, {sampled_count} sampled, "
        f"{len(pose_results)} poses estimated."
    )
    print(f"  Peak memory after pose estimation: {peak_memory_gb():.2f}GB")

    # Load OCR report early so we can extract scoring_frames for analyze_continuous()
    ocr_report = None
    ocr_path = args.merge_ocr
    if ocr_path is None:
        auto_detected = find_ocr_report(video_path.stem, output_dir)
        if auto_detected is not None:
            ocr_path = str(auto_detected)
            print(f"  Auto-detected OCR report: {auto_detected.name}")
        else:
            print(
                f"\n  WARNING: no OCR report auto-detected for '{video_path.stem}' "
                f"in {output_dir}; touches will be empty."
            )
            print("           Pass --merge-ocr <path> to supply it explicitly.\n")

    scoring_frames_sampled: set = set()
    if ocr_path and Path(ocr_path).exists():
        print(f"  Loading OCR data from: {ocr_path}")
        with open(ocr_path, "r", encoding="utf-8") as f:
            ocr_report = json.load(f)
        ocr_touches = ocr_report.get("touches", [])
        if ocr_touches:
            # Extract scoring frame indices and convert to sampled indices
            scoring_frames_raw = {t.get("frame", 0) for t in ocr_touches}
            scoring_frames_sampled = {f // args.sample_every for f in scoring_frames_raw}
            print(f"  Scoring frames: {len(scoring_frames_sampled)} (from {len(ocr_touches)} OCR touches)")

    # Run continuous analysis. The priority lead is converted from seconds into
    # samples *here*, where both fps and the sampling stride are known — inside
    # analyze_continuous the sequence is already sampled and its true frame rate
    # is not recoverable.
    priority_lead_samples = max(
        1, round(PRIORITY_WINDOW_LEAD_SEC * fps / args.sample_every),
    )
    print("Running continuous analysis...")
    continuous_result = analyzer.analyze_continuous(
        pose_sequence=pose_results,
        sample_every_n=1,  # Already sampled
        my_fencer=args.my_fencer,
        scoring_frames=scoring_frames_sampled if scoring_frames_sampled else None,
        priority_lead_samples=priority_lead_samples,
    )
    t_analysis = time.time() - t0

    print(f"  Exchanges detected: {continuous_result.total_exchanges}")
    print(f"  Analysis time: {t_analysis:.1f}s")

    # Build FencerProfile from continuous data
    builder_left = FencerProfileBuilder("left")
    builder_right = FencerProfileBuilder("right")
    builder_left.add_continuous(continuous_result)
    builder_right.add_continuous(continuous_result)
    profile_left = builder_left.build()
    profile_right = builder_right.build()

    # Detect handedness
    handedness_left, hconf_left = analyzer.detect_handedness(pose_results, "left")
    handedness_right, hconf_right = analyzer.detect_handedness(pose_results, "right")

    profile_left.handedness = handedness_left
    profile_left.handedness_confidence = hconf_left
    profile_right.handedness = handedness_right
    profile_right.handedness_confidence = hconf_right

    if handedness_left:
        hand_ko = "오른손잡이" if handedness_left == "right" else "왼손잡이"
        print(f"  Left fencer: {hand_ko} (confidence: {hconf_left})")
    if handedness_right:
        hand_ko = "오른손잡이" if handedness_right == "right" else "왼손잡이"
        print(f"  Right fencer: {hand_ko} (confidence: {hconf_right})")

    # Build exchange list for report
    exchanges_list = []
    event_type_ko = {
        "failed_attack": "실패한 공격",
        "successful_defense": "방어 성공",
        "mutual_retreat": "상호 후퇴",
        "off_target": "비유효면",
        "missed_entirely": "완전 빗나감",
        "unknown_exchange": "분류 미정",
        "neutral": "판정 보류",
    }

    for i, ex in enumerate(continuous_result.exchanges, 1):
        # Adjust frame numbers for sampling
        actual_start = ex.start_frame * args.sample_every
        actual_end = ex.end_frame * args.sample_every
        actual_min = ex.min_distance_frame * args.sample_every
        duration = (actual_end - actual_start) / fps

        ex_dict = {
            "exchange_number": i,
            "start_time": format_timestamp(actual_start, fps),
            "end_time": format_timestamp(actual_end, fps),
            "start_frame": actual_start,
            "end_frame": actual_end,
            "event_type": ex.event_type.value,
            "event_type_ko": event_type_ko.get(ex.event_type.value, ex.event_type.value),
            "duration_sec": round(duration, 1),
            "min_distance_frame": actual_min,
            "min_distance_bh": round(ex.min_distance_bh, 2),
        }

        # Add footwork info
        fw_left_val = None
        fw_right_val = None
        if ex.footwork_left is not None:
            fw_left_val = ex.footwork_left.footwork_type.value
            ex_dict["footwork_left"] = fw_left_val
        if ex.footwork_right is not None:
            fw_right_val = ex.footwork_right.footwork_type.value
            ex_dict["footwork_right"] = fw_right_val
        if ex.parry_left is not None and ex.parry_left.parry_detected:
            ex_dict["parry_left"] = True
        if ex.parry_right is not None and ex.parry_right.parry_detected:
            ex_dict["parry_right"] = True

        # Attacker/defender from footwork — the same rule that decides each
        # touch's attack_outcome. Dropping this assignment leaves every
        # exchange with attacker=None, which silently zeroes
        # continuous_summary.fencer_stats and renders as "0 attacks, 0
        # defenses" for both fencers in the report. It has gone missing once
        # already, so it stays next to the footwork values it reads.
        ex_dict["attacker"], ex_dict["defender"] = classify_exchange_sides(
            fw_left_val, fw_right_val,
        )

        # Priority signal series. Sample indices → original video frames, the
        # same ×sample_every conversion applied to every other frame number
        # above. Getting this wrong would silently place the series outside the
        # exchange it belongs to, so it is asserted rather than trusted.
        for name in (
            "arm_series_left", "arm_series_right",
            "hip_x_series_left", "hip_x_series_right",
        ):
            series = getattr(ex, name)
            if not series:
                continue
            ex_dict[name] = [
                [frame * args.sample_every,
                 None if value is None else round(value, 3)]
                for frame, value in series
            ]

        exchanges_list.append(ex_dict)

    validate_priority_series_frames(
        exchanges_list, priority_lead_samples * args.sample_every,
    )

    # Count exchange types
    from collections import Counter
    type_counts = Counter(ex.event_type.value for ex in continuous_result.exchanges)

    # Build per-fencer exchange stats from exchanges_list
    fencer_exchange_stats = {"left": {"attacks": 0, "defenses": 0}, "right": {"attacks": 0, "defenses": 0}}
    for ex in exchanges_list:
        att = ex.get("attacker")
        if att == "left":
            fencer_exchange_stats["left"]["attacks"] += 1
            fencer_exchange_stats["right"]["defenses"] += 1
        elif att == "right":
            fencer_exchange_stats["right"]["attacks"] += 1
            fencer_exchange_stats["left"]["defenses"] += 1
        elif att == "both":
            fencer_exchange_stats["left"]["attacks"] += 1
            fencer_exchange_stats["right"]["attacks"] += 1

    # Build report dict
    match_duration = f"{int(duration_sec//60)}:{int(duration_sec%60):02d}"
    video_stem = video_path.stem

    report_dict = {
        "summary": {
            "video_path": str(video_path),
            "final_score": "연속 분석",
            "total_touches": 0,
            "match_duration": match_duration,
            "total_frames_analyzed": sampled_count,
            "analysis_time_sec": round(t_analysis, 1),
            "weapon": "epee",
            "bout_type": "de",
            "gender": None,
            "age_group": None,
        },
        "touches": [],
        "left_fencer": {
            "name": "Left Fencer",
            "club": "",
            "handedness": handedness_left,
            "handedness_confidence": hconf_left,
            "total_touches_scored": 0,
            "total_touches_conceded": 0,
            "most_common_action": None,
            "most_common_action_pct": 0,
            "action_distribution": [],
        },
        "right_fencer": {
            "name": "Right Fencer",
            "club": "",
            "handedness": handedness_right,
            "handedness_confidence": hconf_right,
            "total_touches_scored": 0,
            "total_touches_conceded": 0,
            "most_common_action": None,
            "most_common_action_pct": 0,
            "action_distribution": [],
        },
        "fencer_profile": {
            "left": profile_left.to_dict(),
            "right": profile_right.to_dict(),
        },
        "exchanges": exchanges_list,
        "continuous_summary": {
            "total_exchanges": continuous_result.total_exchanges,
            "scoring_exchanges": continuous_result.scoring_exchanges,
            "non_scoring_exchanges": continuous_result.non_scoring_exchanges,
            "camera_cut_ratio": round(continuous_result.camera_cut_ratio, 3),
            "type_distribution": dict(type_counts),
            "fencer_stats": fencer_exchange_stats,
        },
        "insights": [],
        "warnings": [],
        "meta": {
            "phase": 6,
            "pose_model": "YOLO11-Pose",
            "action_model": None,
            "pose_enabled": True,
            "action_enabled": False,
            "confidence_threshold": 0.0,
            "source_type": report_source_type(args.piste_config),
            "analysis_mode": "continuous_only",
            "fps": fps,
        },
    }

    if args.piste_config:
        report_dict["meta"]["piste_config"] = str(args.piste_config)

    # Add my_fencer_summary if available
    if continuous_result.my_fencer_summary is not None:
        report_dict["my_fencer_summary"] = continuous_result.my_fencer_summary.to_dict()

    # Add frame action state summary (not individual frames — too large)
    if continuous_result.frame_actions:
        from collections import Counter as _Ctr
        action_state_summary = {}
        for side in ("left", "right"):
            states = continuous_result.frame_actions.get(side, [])
            if states:
                state_counts = _Ctr(s.state.value for s in states)
                total = sum(state_counts.values())
                action_state_summary[side] = {
                    "total_frames": total,
                    "distribution": {
                        state: {"count": count, "pct": round(count / total * 100, 1)}
                        for state, count in state_counts.most_common()
                    },
                }
        if action_state_summary:
            report_dict["action_state_summary"] = action_state_summary

    # Store scoring frames for transparency
    if scoring_frames_sampled:
        report_dict["scoring_frames"] = sorted([f * args.sample_every for f in scoring_frames_sampled])

    # Merge OCR scoring data if available (ocr_report already loaded above)
    if ocr_report is not None:
        print(f"\n  Merging OCR data from: {ocr_path}")

        # Merge scoring data
        ocr_touches = ocr_report.get("touches", [])
        if ocr_touches:
            # Fix match_time: if all values are the same (e.g. "3:00"), OCR
            # failed to read the clock — fall back to video_timestamp
            match_times = [t.get("match_time") for t in ocr_touches]
            all_same = len(set(match_times)) <= 1
            if all_same:
                for t in ocr_touches:
                    t["match_time"] = t.get("video_timestamp", t.get("match_time", ""))

            # Enrich touches with nearest exchange pose data + derive action labels
            prev_scorer = None
            prev_frame = -99999
            for t in ocr_touches:
                touch_frame = t.get("frame", 0)
                scorer = t.get("scorer", "left")
                best_ex = None
                best_dist = float("inf")
                for ex in exchanges_list:
                    # Find exchange closest to this touch frame
                    mid = (ex["start_frame"] + ex["end_frame"]) // 2
                    d = abs(touch_frame - mid)
                    if d < best_dist:
                        best_dist = d
                        best_ex = ex
                if best_ex and best_dist < fps * 10:  # within 10 seconds
                    opponent = "right" if scorer == "left" else "left"
                    parry_detected = best_ex.get(f"parry_{opponent}", False)
                    fw_scorer = best_ex.get(f"footwork_{scorer}", None)
                    fw_opponent = best_ex.get(f"footwork_{opponent}", None)

                    t["pose_analysis"] = {
                        "distance_bh": best_ex.get("min_distance_bh", 0),
                        "distance_zone": _distance_zone(best_ex.get("min_distance_bh", 0)),
                        "footwork_scorer": fw_scorer,
                        "footwork_opponent": fw_opponent,
                        "parry_detected": parry_detected,
                    }

                    # Derive action label from pose analysis
                    is_remise = (
                        scorer == prev_scorer
                        and (touch_frame - prev_frame) / fps < 2.0
                    )
                    if is_remise:
                        action = "remise"
                        t["action_confidence"] = 0.8
                    elif parry_detected:
                        action = "riposte"
                        t["action_confidence"] = 0.85
                    else:
                        action = "attack"
                        t["action_confidence"] = 0.7
                    t["action_scorer"] = action
                    t["action_opponent"] = "parry" if parry_detected else "unknown"

                prev_scorer = scorer
                prev_frame = touch_frame

            # Part B — attack success/failure. Uses the touch→exchange match that
            # also drives the clip window (analyzer.touch_matching), which is
            # stricter than the nearest-midpoint heuristic used for
            # `pose_analysis` above: only the *preceding* exchange within the
            # measured OCR delay counts, so an unmatched touch stays "unclear"
            # rather than borrowing footwork from an unrelated exchange.
            # Foil priority estimation, when it is enabled and the bout is foil.
            # The weapon has to be resolved before the OCR summary merge further
            # down, because the cascade is gated on it: an unrecognised weapon
            # would silently skip estimation rather than fail loudly.
            weapon = args.weapon or ocr_report.get("summary", {}).get("weapon")
            judge = build_priority_judge(weapon, exchanges_list, fps)
            if judge is not None:
                print(f"  Priority estimation active (weapon={weapon})")
            annotate_touch_outcomes(ocr_touches, exchanges_list, fps, judge=judge)

            # LED-scoreboard reports arrive with their lamps already read, so
            # the lamp-informed refinement that detect_touch_lamps.py performs
            # for the TV path has to happen here — before the summary counts it.
            # No-op for TV reports, which carry no lamp fields at this point.
            if report_carries_lamp_fields(ocr_touches):
                promoted = promote_supplied_lamp_outcomes(ocr_touches)
                print(
                    f"  Lamp readings supplied by OCR report: "
                    f"{promoted} touch(es) promoted to no_priority_call"
                )

            attack_outcomes = summarize_attack_outcomes(ocr_touches)
            report_dict["continuous_summary"]["attack_outcomes"] = attack_outcomes
            for side in ("left", "right"):
                report_dict[f"{side}_fencer"]["attack_outcomes"] = attack_outcomes[side]
            print(
                f"  Attack outcomes: left {attack_outcomes['left']['attack_success']}/"
                f"{attack_outcomes['left']['attack_attempts']}, "
                f"right {attack_outcomes['right']['attack_success']}/"
                f"{attack_outcomes['right']['attack_attempts']}, "
                f"unclear {attack_outcomes['unclear_touches']}/{attack_outcomes['total_touches']}, "
                f"no priority call {attack_outcomes['no_priority_call_touches']}/"
                f"{attack_outcomes['total_touches']}"
            )

            report_dict["touches"] = ocr_touches
            report_dict["summary"]["total_touches"] = len(ocr_touches)
            report_dict["summary"]["final_score"] = ocr_report.get("summary", {}).get("final_score", "연속 분석")

        # Compute per-fencer action distribution from derived labels
        from collections import Counter as _Counter
        for side in ("left", "right"):
            side_key = f"{side}_fencer"
            scored = [t for t in ocr_touches if t.get("scorer") == side]
            conceded = [t for t in ocr_touches if t.get("scorer") != side]
            report_dict[side_key]["total_touches_scored"] = len(scored)
            report_dict[side_key]["total_touches_conceded"] = len(conceded)

            action_counts = _Counter(
                t.get("action_scorer", "unknown") for t in scored
            )
            total = sum(action_counts.values())
            if total > 0:
                most_common = action_counts.most_common(1)[0]
                report_dict[side_key]["most_common_action"] = most_common[0]
                report_dict[side_key]["most_common_action_pct"] = round(most_common[1] / total * 100)
                report_dict[side_key]["action_distribution"] = [
                    {"action": a, "count": c, "pct": round(c / total * 100)}
                    for a, c in action_counts.most_common()
                ]

        # Merge fencer names from OCR
        for side in ("left_fencer", "right_fencer"):
            ocr_fencer = ocr_report.get(side, {})
            if ocr_fencer.get("name") and ocr_fencer["name"] not in ("Left", "Right"):
                report_dict[side]["name"] = ocr_fencer["name"]
            if ocr_fencer.get("club"):
                report_dict[side]["club"] = ocr_fencer["club"]

        # Merge summary fields from OCR (weapon, bout_type, gender, age_group)
        ocr_summary = ocr_report.get("summary", {})
        for key in ("weapon", "bout_type", "gender", "age_group"):
            if ocr_summary.get(key):
                report_dict["summary"][key] = ocr_summary[key]

        # Merge metadata
        report_dict["meta"]["analysis_mode"] = "continuous_with_ocr"
        report_dict["meta"]["ocr_source"] = Path(ocr_path).name

        # Merge OCR warnings
        for w in ocr_report.get("warnings", []):
            report_dict["warnings"].append(w)

        # Store clock events (Allez/Halt proxy) from OCR if available
        clock_events = ocr_report.get("clock_events", [])
        if clock_events:
            report_dict["clock_events"] = clock_events
            print(f"  Clock events: {len(clock_events)} (allez/halt)")

        print(f"  OCR touches merged: {len(ocr_touches)}")
        print(f"  Final score: {report_dict['summary']['final_score']}")
    else:
        if args.merge_ocr and not ocr_report:
            print(f"\n  WARNING: OCR report not found: {args.merge_ocr}")

    # An explicit --weapon outranks both the OCR report's guess and the
    # filename parse, and must apply whether or not an OCR report was merged.
    # This override used to sit inside the merge branch, so a pose-only run —
    # the normal case for a piste crop, which has no OCR report — silently kept
    # the filename's guess. Foil priority estimation is gated on the weapon, so
    # the flag appeared accepted while the analysis it exists to enable stayed
    # off.
    if args.weapon:
        report_dict["summary"]["weapon"] = args.weapon

    # Auto-generate insights from continuous analysis
    insights = []
    if continuous_result.total_exchanges > 0:
        insights.append({
            "category": "exchange_summary",
            "target": "both",
            "message": f"총 {continuous_result.total_exchanges}회 교환 감지",
            "severity": "info",
            "evidence": f"실패 공격 {type_counts.get('failed_attack', 0)}회, "
                       f"방어 성공 {type_counts.get('successful_defense', 0)}회, "
                       f"상호 후퇴 {type_counts.get('mutual_retreat', 0)}회",
        })

    # Per-fencer attack/defense insights from exchange stats
    for side in ("left", "right"):
        side_ko = "왼쪽" if side == "left" else "오른쪽"
        stats = fencer_exchange_stats[side]
        if stats["attacks"] > 0:
            insights.append({
                "category": "attack_analysis",
                "target": side,
                "message": f"{side_ko} 선수: 비득점 교환 중 공격 시도 {stats['attacks']}회",
                "severity": "info",
                "evidence": f"적극적 풋워크(전진/런지/플레쉬) 기반 공격 감지",
            })
        if stats["defenses"] > 0:
            insights.append({
                "category": "defense_analysis",
                "target": side,
                "message": f"{side_ko} 선수: 상대 공격 방어 {stats['defenses']}회",
                "severity": "info",
                "evidence": f"상대의 적극적 접근에 대한 방어/후퇴 감지",
            })

    # Add FencerProfile insights
    for side, profile in [("left", profile_left), ("right", profile_right)]:
        for s in profile.strengths:
            insights.append({
                "category": "strength",
                "target": side,
                "message": s,
                "severity": "info",
                "evidence": "",
            })
        for w in profile.weaknesses:
            insights.append({
                "category": "weakness",
                "target": side,
                "message": w,
                "severity": "warning",
                "evidence": "",
            })

    report_dict["insights"] = insights

    # Add warnings
    for qw in continuous_result.quality_warnings:
        report_dict["warnings"].append(qw)
    report_dict["warnings"].append({
        "type": "continuous_only",
        "message": "이 리포트는 연속 포즈 분석 결과입니다. 득점 정보(OCR/LED)가 포함되지 않아 공격 성공률이 정확하지 않을 수 있습니다.",
        "severity": "info",
    })

    # Save
    report_id = f"{video_stem}_continuous_report"
    output_path = output_dir / f"{report_id}.json"

    # Store video_path in meta for clip generation
    report_dict["meta"]["video_path"] = str(video_path.resolve())

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report_dict, f, indent=2, ensure_ascii=False)

    # Gate audit (optional): a second, one-frame-at-a-time pass over the video
    # so the operator can see which people the piste gate kept. It runs after
    # the report is on disk — a failed audit must not cost the analysis.
    audit_paths = []
    if gate_audit_count and piste_kwargs is not None:
        indices = audit_frame_indices(
            total_frames, gate_audit_count, args.sample_every,
        )
        print(f"\nWriting {len(indices)} gate-audit frames...")
        audit_paths = write_gate_audit_frames(
            video_path, estimator, indices,
            piste_kwargs["foot_band_work"], GATE_AUDIT_DIR, video_stem,
        )
        print(f"  {len(audit_paths)} images written to: {GATE_AUDIT_DIR.resolve()}")

    # Generate overlay clips (optional)
    clip_results = []
    if args.with_overlays:
        print("\nGenerating pose-overlay clips...")
        from ml.clip_overlay import ClipOverlayGenerator
        # for_report re-reads meta.piste_config so the clip's skeleton tracks the
        # same two people the analysis did. A bare ClipOverlayGenerator() builds a
        # default estimator, which on a piste crop locks onto the foreground
        # referee — the clips then disagree with the report they illustrate.
        # Falls back to the default generator for non-piste reports.
        clip_gen = ClipOverlayGenerator.for_report(report_dict)
        clips_dir = Path("data/clips/overlay") / report_id
        touches_only = not args.overlays_all
        t_clips_start = time.time()
        clip_results = clip_gen.generate_clips_for_report(
            str(video_path), report_dict, str(clips_dir),
            touches_only=touches_only,
        )
        t_clips = time.time() - t_clips_start
        print(f"  {len(clip_results)} clips generated in {t_clips:.1f}s")

        # Add clip paths to report
        report_dict["clip_paths"] = clip_results
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report_dict, f, indent=2, ensure_ascii=False)

    # Print summary
    print(f"\n{'='*60}")
    print(f"  Report Generated")
    print(f"{'='*60}")
    print(f"  Output:      {output_path}")
    print(f"  Exchanges:   {continuous_result.total_exchanges}")
    for etype, count in sorted(type_counts.items()):
        print(f"    {etype}: {count}")
    my_stats = fencer_exchange_stats.get(args.my_fencer, {})
    if my_stats:
        print(f"  {args.my_fencer} fencer:")
        print(f"    Attacks:  {my_stats.get('attacks', 0)}")
        print(f"    Defenses: {my_stats.get('defenses', 0)}")
    print(f"  Duration:    {match_duration}")
    print(f"  Processing:  {t_analysis:.1f}s ({t_analysis/duration_sec:.2f}x realtime)")
    print(f"  Peak memory: {peak_memory_gb():.2f}GB")
    if clip_results:
        print(f"  Clips:       {len(clip_results)} generated")
    if audit_paths:
        print(f"  Gate audit:  {len(audit_paths)} images in {GATE_AUDIT_DIR.resolve()}")
    print(f"{'='*60}")
    print(f"\n  View at: http://localhost:76/report/saved/{report_id}")


if __name__ == "__main__":
    main()
