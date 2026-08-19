"""
One-time preprocessing for multi-piste coach footage: pick a piste, build work files.

A raw venue recording holds several pistes in one 4K frame and is far too large to
decode per analysis (57GB / ~6 min decode for a 166s ProRes clip). This script runs
ONCE per (video, piste) pair and produces two small work files from a single decode:

  1. piste work file       - vertical band crop around the target piste,
                             scaled to 1280 wide, 30fps, audio preserved
                             (roadmap 8-8 wants the audio for Allez/Halt detection).
  2. scoreboard work file  - scoreboard crop at NATIVE resolution, 30fps, no audio
                             (7-seg OCR needs the original pixels).

Both outputs come from the same `fps=30` filter on the same source, so their frame
indices are 1:1 — every downstream frame number in this pipeline refers to the WORK
FILE, never to the 120fps original. The script asserts the two frame counts match
before it exits (plan 4.3).

THREE COORDINATE SYSTEMS COEXIST (plan trap 4). Conversion happens ONLY here:

  * 4K source coords      - everything the operator types on the CLI
                            (--crop-band, --foot-band, --scoreboard)
  * piste work-file coords- config["piste"]["foot_band_work"], derived from the 4K
                            foot band via (y_4k - crop.y) * scale_width / source_width
  * scoreboard-crop coords- config["scoreboard"]["rois"], stored unconverted; they are
                            measured on the scoreboard crop itself

Usage:
    cd services/analytics

    # fully non-interactive (geometry from the CLI)
    PYTHONPATH=. .venv/bin/python3 scripts/prepare_piste_video.py \\
        "/Volumes/Film/DCIM/100APPLE/260815_Pool.mov" --piste 3 --no-gui \\
        --crop-band 950:1700 --foot-band 1340:1595 --scoreboard 1800:960:480:280 \\
        --scoreboard-roi lamp_left=40:60:120:90 --scoreboard-roi lamp_right=560:60:120:90 \\
        --scoreboard-roi score_left=80:200:140:160 --scoreboard-roi score_right=500:200:140:160 \\
        --scoreboard-roi clock=260:180:200:140

    # interactive geometry (cv2.selectROI, needs a display)
    PYTHONPATH=. .venv/bin/python3 scripts/prepare_piste_video.py VIDEO --piste 3

    # re-run transcode/previews from an existing config, no prompts at all
    PYTHONPATH=. .venv/bin/python3 scripts/prepare_piste_video.py VIDEO --piste 3 \\
        --config data/piste_configs/260815_Pool_piste3.json
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# ----------------------------------------------------------------------
# Constants (plan 1.2 / 2.1 - the config schema defaults live here)
# ----------------------------------------------------------------------

SCHEMA_VERSION = 1
CONFIG_SOURCE_MANUAL = "manual"

CROP_MARGIN_PX = 120          # camera-drift margin above/below the piste crop band (4K px)
SCOREBOARD_PAD_PX = 120       # camera-drift padding on all four scoreboard sides (4K px)

WORK_FPS = 30
SCALE_WIDTH = 1280
POSE_IMGSZ = 1280
POSE_MAX_DET = 8
POSE_CONF = 0.35

PISTE_CRF = 20
SCOREBOARD_CRF = 18
X264_PRESET = "fast"
AUDIO_BITRATE = "96k"

# Outputs of this script are *not* scratch: reports point at the piste crop via
# ``meta.video_path`` and clip generation re-reads it long after the cut. They are
# also derived from footage we filmed ourselves, and ``data/raw/own/`` is both the
# directory reserved for our own footage and the only part of ``data/raw`` the web
# server serves without the SERVE_RAW_VIDEOS gate — so a report made here is
# playable out of the box. ``--work-dir`` still overrides this.
DEFAULT_WORK_DIR = Path("data/raw/own")
DEFAULT_CONFIG_DIR = Path("data/piste_configs")
PREVIEW_SUBDIR = "previews"

PREVIEW_EDGE_OFFSET_SEC = 10.0
GATE_PREVIEW_MAX_DET = 10

SCOREBOARD_ROI_KEYS: Tuple[str, ...] = (
    "lamp_left",
    "lamp_right",
    "score_left",
    "score_right",
    "clock",
)

# COCO keypoint indices for the ankles (foot tip proxy).
ANKLE_KEYPOINT_INDICES = (15, 16)

_COLOR_PASS = (0, 200, 0)      # BGR green - inside the foot band
_COLOR_FAIL = (0, 0, 220)      # BGR red   - outside the foot band
_COLOR_BAND = (0, 220, 220)    # BGR yellow - band boundary lines
_COLOR_ROI = (0, 220, 220)


# ----------------------------------------------------------------------
# Pure helpers: argument parsing
# ----------------------------------------------------------------------

def parse_band(text: str) -> Tuple[int, int]:
    """Parse a ``Y0:Y1`` vertical band (4K source coords).

    Raises:
        argparse.ArgumentTypeError: on malformed input or a non-increasing band.
    """
    parts = str(text).split(":")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(
            f"band must be 'Y0:Y1' (got {text!r})"
        )
    try:
        y0, y1 = (int(p) for p in parts)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"band values must be integers (got {text!r})"
        ) from None
    if y0 < 0 or y1 < 0:
        raise argparse.ArgumentTypeError(f"band values must be >= 0 (got {text!r})")
    if y1 <= y0:
        raise argparse.ArgumentTypeError(f"band must be increasing, Y1 > Y0 (got {text!r})")
    return y0, y1


def parse_rect(text: str) -> Tuple[int, int, int, int]:
    """Parse an ``X:Y:W:H`` rectangle.

    Raises:
        argparse.ArgumentTypeError: on malformed input or non-positive size.
    """
    parts = str(text).split(":")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            f"rect must be 'X:Y:W:H' (got {text!r})"
        )
    try:
        x, y, w, h = (int(p) for p in parts)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"rect values must be integers (got {text!r})"
        ) from None
    if x < 0 or y < 0:
        raise argparse.ArgumentTypeError(f"rect origin must be >= 0 (got {text!r})")
    if w <= 0 or h <= 0:
        raise argparse.ArgumentTypeError(f"rect size must be > 0 (got {text!r})")
    return x, y, w, h


def parse_scoreboard_roi(text: str) -> Tuple[str, Tuple[int, int, int, int]]:
    """Parse a ``KEY=X:Y:W:H`` scoreboard ROI (SCOREBOARD-CROP coords).

    Raises:
        argparse.ArgumentTypeError: on an unknown key or a malformed rect.
    """
    if "=" not in str(text):
        raise argparse.ArgumentTypeError(
            f"scoreboard ROI must be 'KEY=X:Y:W:H' (got {text!r})"
        )
    key, _, rect_text = str(text).partition("=")
    key = key.strip()
    if key not in SCOREBOARD_ROI_KEYS:
        raise argparse.ArgumentTypeError(
            f"unknown scoreboard ROI key {key!r}; expected one of {', '.join(SCOREBOARD_ROI_KEYS)}"
        )
    return key, parse_rect(rect_text)


# ----------------------------------------------------------------------
# Pure helpers: geometry derivation
# ----------------------------------------------------------------------

def even_down(value: int) -> int:
    """Round down to the nearest even number (x264 / chroma-subsampling constraint)."""
    value = int(value)
    return value - (value % 2)


def derive_piste_crop(
    crop_band: Tuple[int, int],
    source_width: int,
    source_height: int,
    margin: int = CROP_MARGIN_PX,
) -> Dict[str, int]:
    """Widen the operator's 4K crop band by ``margin`` px above and below.

    Full source width, x=0. Offsets and dimensions are forced EVEN: ffmpeg's crop
    filter silently rounds odd x/y for subsampled video (``exact=0`` default), and
    x264 rejects odd w/h. Doing it here keeps ``crop.y`` honest, which matters
    because the foot-band conversion below is anchored on it.
    """
    y0, y1 = crop_band
    if y1 <= y0:
        raise ValueError(f"crop band must be increasing (got {crop_band})")

    top = even_down(max(0, y0 - margin))
    bottom = min(int(source_height), y1 + margin)
    h = even_down(bottom - top)
    w = even_down(source_width)
    if h <= 0 or w <= 0:
        raise ValueError(
            f"crop band {crop_band} yields an empty crop in a {source_width}x{source_height} frame"
        )
    return {"x": 0, "y": top, "w": w, "h": h}


def derive_scoreboard_crop(
    rect: Tuple[int, int, int, int],
    source_width: int,
    source_height: int,
    pad: int = SCOREBOARD_PAD_PX,
) -> Dict[str, int]:
    """Pad the operator's 4K scoreboard rect by ``pad`` px on all four sides."""
    x, y, w, h = rect
    x0 = even_down(max(0, x - pad))
    y0 = even_down(max(0, y - pad))
    x1 = min(int(source_width), x + w + pad)
    y1 = min(int(source_height), y + h + pad)
    cw = even_down(x1 - x0)
    ch = even_down(y1 - y0)
    if cw <= 0 or ch <= 0:
        raise ValueError(
            f"scoreboard rect {rect} yields an empty crop in a {source_width}x{source_height} frame"
        )
    return {"x": x0, "y": y0, "w": cw, "h": ch}


def foot_band_to_work(
    foot_band: Tuple[int, int],
    crop: Dict[str, int],
    scale_width: int,
    source_width: int,
) -> List[int]:
    """Convert a 4K foot-tip band into PISTE WORK-FILE coordinates.

    ``(y_4k - crop.y) * scale_width / source_width`` — the single place in the whole
    pipeline where a 4K y is turned into a work-file y (plan trap 4).
    """
    y0, y1 = foot_band
    crop_y = crop["y"]
    crop_bottom = crop_y + crop["h"]
    if y0 < crop_y or y1 > crop_bottom:
        raise ValueError(
            f"foot band {foot_band} falls outside the piste crop "
            f"[{crop_y}, {crop_bottom}] — widen --crop-band or fix --foot-band"
        )
    scale = float(scale_width) / float(source_width)
    return [int(round((y0 - crop_y) * scale)), int(round((y1 - crop_y) * scale))]


def work_file_paths(stem: str, piste_number: int, work_dir) -> Dict[str, str]:
    """Work-file paths for a (source stem, piste number) pair."""
    work_dir = Path(work_dir)
    return {
        "piste": str(work_dir / f"{stem}_piste{piste_number}.mp4"),
        "scoreboard": str(work_dir / f"{stem}_piste{piste_number}_scoreboard.mp4"),
    }


def build_preview_timestamps(
    duration_sec: float,
    edge_offset: float = PREVIEW_EDGE_OFFSET_SEC,
) -> List[float]:
    """Three sample points: start+10s, midpoint, end-10s (clamped for short clips)."""
    duration = max(0.0, float(duration_sec))
    if duration <= 2 * edge_offset:
        return [0.0, round(duration / 2, 2), round(max(0.0, duration - 0.1), 2)]
    return [
        round(edge_offset, 2),
        round(duration / 2, 2),
        round(duration - edge_offset, 2),
    ]


def preview_label(timestamp_sec: float) -> str:
    """Filename fragment for a preview timestamp, e.g. ``t83``."""
    return f"t{int(round(timestamp_sec))}"


# ----------------------------------------------------------------------
# Pure helpers: config + ffmpeg command
# ----------------------------------------------------------------------

def build_config(
    *,
    source_video,
    piste_number: int,
    source_fps: float,
    source_resolution: Sequence[int],
    crop_band: Tuple[int, int],
    foot_band: Tuple[int, int],
    scoreboard_rect: Optional[Tuple[int, int, int, int]] = None,
    scoreboard_rois: Optional[Dict[str, Sequence[int]]] = None,
    work_dir=DEFAULT_WORK_DIR,
    source_override=None,
) -> Dict:
    """Build the piste config dict (schema: plan 1.2).

    All CLI-supplied geometry is in 4K SOURCE coords; ``piste.foot_band_work`` comes
    out in PISTE WORK-FILE coords and ``scoreboard.rois`` stay in SCOREBOARD-CROP
    coords, unconverted.
    """
    source_width, source_height = int(source_resolution[0]), int(source_resolution[1])
    crop = derive_piste_crop(crop_band, source_width, source_height)
    stem = Path(source_video).stem

    config: Dict = {
        "schema_version": SCHEMA_VERSION,
        "source": CONFIG_SOURCE_MANUAL,
        "source_video": str(source_video),
        "piste_number": int(piste_number),
        "source_fps": float(source_fps),
        "source_resolution": [source_width, source_height],
        "work_fps": WORK_FPS,
        "piste": {
            "crop": crop,
            "scale_width": SCALE_WIDTH,
            "foot_band_work": foot_band_to_work(foot_band, crop, SCALE_WIDTH, source_width),
            "pose_imgsz": POSE_IMGSZ,
            "pose_max_det": POSE_MAX_DET,
            "pose_conf": POSE_CONF,
        },
        "scoreboard": None,
        "work_files": work_file_paths(stem, piste_number, work_dir),
    }

    if scoreboard_rect is not None:
        config["scoreboard"] = {
            "crop": derive_scoreboard_crop(scoreboard_rect, source_width, source_height),
            "rois": {k: [int(v) for v in rect] for k, rect in (scoreboard_rois or {}).items()},
        }
    else:
        config["work_files"]["scoreboard"] = None

    if source_override is not None:
        # Recorded so nothing downstream believes the original was analysed.
        config["source_override"] = str(source_override)

    return config


def config_decode_path(config: Dict) -> str:
    """The file ffmpeg actually decodes: the dev override when set, else the source."""
    return str(config.get("source_override") or config["source_video"])


def build_ffmpeg_command(config: Dict) -> List[str]:
    """Build the single-decode / two-output ffmpeg invocation (plan 2.1).

    Every crop, scale and fps number comes from ``config`` — nothing is hardcoded.
    When the config has no scoreboard, this degrades to one output and no ``split``.
    """
    piste = config["piste"]
    crop = piste["crop"]
    fps = int(config.get("work_fps", WORK_FPS))
    scale_w = int(piste["scale_width"])
    piste_out = config["work_files"]["piste"]
    scoreboard = config.get("scoreboard")

    piste_chain = (
        f"crop={crop['w']}:{crop['h']}:{crop['x']}:{crop['y']},"
        f"scale={scale_w}:-2,fps={fps}"
    )

    cmd: List[str] = ["ffmpeg", "-y", "-i", config_decode_path(config)]

    if scoreboard is None:
        cmd += ["-filter_complex", f"[0:v]{piste_chain}[piste]"]
    else:
        sb_crop = scoreboard["crop"]
        sb_chain = (
            f"crop={sb_crop['w']}:{sb_crop['h']}:{sb_crop['x']}:{sb_crop['y']},fps={fps}"
        )
        cmd += [
            "-filter_complex",
            f"[0:v]split=2[p][s];[p]{piste_chain}[piste];[s]{sb_chain}[sb]",
        ]

    # Output 1: piste band, downscaled, audio kept for roadmap 8-8.
    cmd += [
        "-map", "[piste]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-crf", str(PISTE_CRF),
        "-preset", X264_PRESET,
        "-c:a", "aac",
        "-b:a", AUDIO_BITRATE,
        str(piste_out),
    ]

    # Output 2: scoreboard crop at native resolution, video only.
    if scoreboard is not None:
        cmd += [
            "-map", "[sb]",
            "-c:v", "libx264",
            "-crf", str(SCOREBOARD_CRF),
            "-preset", X264_PRESET,
            "-an",
            str(config["work_files"]["scoreboard"]),
        ]

    return cmd


def classify_foot_y(
    foot_y: Optional[float],
    foot_band: Sequence[float],
) -> bool:
    """True when a person's foot y falls inside the work-file foot band."""
    if foot_y is None:
        return False
    return float(foot_band[0]) <= float(foot_y) <= float(foot_band[1])


# ----------------------------------------------------------------------
# Video probing (ffprobe)
# ----------------------------------------------------------------------

def _run_checked(cmd: List[str], what: str) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"{what} failed (exit {proc.returncode}): {' '.join(shlex.quote(c) for c in cmd)}\n"
            f"{proc.stderr.strip()}"
        )
    return proc.stdout


def _parse_rational(text: str) -> float:
    text = (text or "").strip()
    if "/" in text:
        num, _, den = text.partition("/")
        try:
            den_f = float(den)
            return float(num) / den_f if den_f else 0.0
        except ValueError:
            return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def probe_video(path) -> Dict:
    """Read width/height/fps/duration from a video via ffprobe."""
    out = _run_checked(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate:format=duration",
            "-of", "json", str(path),
        ],
        f"ffprobe {path}",
    )
    data = json.loads(out)
    streams = data.get("streams") or []
    if not streams:
        raise RuntimeError(f"no video stream found in {path}")
    stream = streams[0]
    duration = float((data.get("format") or {}).get("duration") or 0.0)
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": round(_parse_rational(stream.get("r_frame_rate", "0/1")), 3),
        "duration": duration,
    }


def probe_frame_count(path) -> int:
    """Frame count of a video's first video stream (packet count for h264/mp4)."""
    out = _run_checked(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-count_packets",
            "-show_entries", "stream=nb_read_packets",
            "-of", "csv=p=0", str(path),
        ],
        f"ffprobe frame count {path}",
    )
    text = out.strip().splitlines()[0].strip().rstrip(",") if out.strip() else ""
    try:
        return int(text)
    except ValueError:
        raise RuntimeError(f"could not read frame count from {path} (got {out!r})") from None


# ----------------------------------------------------------------------
# Preview extraction
# ----------------------------------------------------------------------

def extract_source_previews(
    decode_path,
    preview_dir: Path,
    stem: str,
    piste_number: int,
    timestamps: Sequence[float],
) -> List[Path]:
    """Extract full-resolution JPEG previews with ffmpeg input seeking (fast on 4K ProRes)."""
    preview_dir.mkdir(parents=True, exist_ok=True)
    paths: List[Path] = []
    for ts in timestamps:
        out_path = preview_dir / f"{stem}_piste{piste_number}_{preview_label(ts)}.jpg"
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{ts:.3f}", "-i", str(decode_path),
            "-frames:v", "1", "-q:v", "2", str(out_path),
        ]
        _run_checked(cmd, f"preview extraction at t={ts:.1f}s")
        paths.append(out_path)
        print(f"  preview: {out_path}")
    return paths


def _read_frames_at(video_path, timestamps: Sequence[float]):
    """Yield ``(timestamp, frame_index, frame)`` for each timestamp of a video."""
    import cv2

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {video_path}")
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or WORK_FPS
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        for ts in timestamps:
            idx = int(round(ts * fps))
            if total:
                idx = max(0, min(idx, total - 1))
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if not ok:
                print(f"  WARNING: could not read frame {idx} of {video_path}")
                continue
            yield ts, idx, frame
    finally:
        cap.release()


# ----------------------------------------------------------------------
# Interactive geometry selection (cv2.selectROI) — never runs headless
# ----------------------------------------------------------------------

def _select_roi(window_title: str, frame, hint: str):
    """One selectROI pass with the same overlay style as video_processor._select_rois."""
    import cv2

    display = frame.copy()
    overlay = display.copy()
    cv2.rectangle(overlay, (5, 5), (700, 70), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.7, display, 0.3, 0, display)
    cv2.putText(display, f"Select: {window_title}", (15, 35),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
    cv2.putText(display, hint, (15, 60),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

    roi = cv2.selectROI(window_title, display, fromCenter=False)
    cv2.destroyAllWindows()
    if roi[2] <= 0 or roi[3] <= 0:
        return None
    return tuple(int(v) for v in roi)


def select_geometry_interactive(preview_path: Path) -> Dict:
    """Ask for crop band -> foot band -> scoreboard rect on a 4K preview frame.

    Returns a dict with ``crop_band``, ``foot_band`` and ``scoreboard_rect`` in 4K
    source coords. Requires an OpenCV GUI; ``--no-gui`` bypasses this entirely.
    """
    import cv2

    frame = cv2.imread(str(preview_path))
    if frame is None:
        raise RuntimeError(f"cannot read preview frame {preview_path}")

    crop_roi = _select_roi(
        "1/3: PISTE CROP BAND (full bodies)", frame,
        "Drag the vertical band containing the whole fencers -> Enter/Space",
    )
    if crop_roi is None:
        raise RuntimeError("piste crop band is required")

    foot_roi = _select_roi(
        "2/3: FOOT BAND (piste floor strip)", frame,
        "Drag the strip where the target fencers' feet land -> Enter/Space",
    )
    if foot_roi is None:
        raise RuntimeError("foot band is required")

    sb_roi = _select_roi(
        "3/3: SCOREBOARD (skip with C if none)", frame,
        "Drag the scoreboard -> Enter/Space | C: skip",
    )

    return {
        "crop_band": (crop_roi[1], crop_roi[1] + crop_roi[3]),
        "foot_band": (foot_roi[1], foot_roi[1] + foot_roi[3]),
        "scoreboard_rect": sb_roi,
    }


def select_scoreboard_rois_interactive(
    preview_path: Path,
    scoreboard_crop: Dict[str, int],
    preview_dir: Path,
    stem: str,
    piste_number: int,
) -> Dict[str, Tuple[int, int, int, int]]:
    """Ask for the 5 inner ROIs on the scoreboard crop, in SCOREBOARD-CROP coords.

    The crop is taken from the 4K preview in memory, so the coordinates the operator
    draws are already in the work file's scoreboard-crop space — no conversion.
    """
    import cv2

    frame = cv2.imread(str(preview_path))
    if frame is None:
        raise RuntimeError(f"cannot read preview frame {preview_path}")

    x, y, w, h = scoreboard_crop["x"], scoreboard_crop["y"], scoreboard_crop["w"], scoreboard_crop["h"]
    crop_frame = frame[y:y + h, x:x + w].copy()

    crop_preview = preview_dir / f"{stem}_piste{piste_number}_scoreboard_setup.jpg"
    preview_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(crop_preview), crop_frame)
    print(f"  scoreboard setup preview: {crop_preview}")

    labels = {
        "lamp_left": "1/5: LEFT LAMP (Red)",
        "lamp_right": "2/5: RIGHT LAMP (Green)",
        "score_left": "3/5: LEFT SCORE",
        "score_right": "4/5: RIGHT SCORE",
        "clock": "5/5: CLOCK (M:SS)",
    }

    rois: Dict[str, Tuple[int, int, int, int]] = {}
    for key in SCOREBOARD_ROI_KEYS:
        display = crop_frame.copy()
        for r in rois.values():
            cv2.rectangle(display, (r[0], r[1]), (r[0] + r[2], r[1] + r[3]), _COLOR_PASS, 2)
        roi = _select_roi(labels[key], display, "Drag -> Enter/Space | C: skip")
        if roi is not None:
            rois[key] = roi
    return rois


# ----------------------------------------------------------------------
# Transcode
# ----------------------------------------------------------------------

def run_transcode(config: Dict, force: bool = False) -> bool:
    """Run the single-decode transcode. Returns True when ffmpeg actually ran."""
    piste_out = Path(config["work_files"]["piste"])
    sb_out_str = config["work_files"].get("scoreboard")
    sb_out = Path(sb_out_str) if sb_out_str else None

    existing = piste_out.exists() and (sb_out is None or sb_out.exists())
    if existing and not force:
        print("  work files already exist, skipping transcode (use --force to redo):")
        print(f"    {piste_out}")
        if sb_out:
            print(f"    {sb_out}")
        return False

    piste_out.parent.mkdir(parents=True, exist_ok=True)
    if sb_out:
        sb_out.parent.mkdir(parents=True, exist_ok=True)

    cmd = build_ffmpeg_command(config)
    print("  running:")
    print(f"    {shlex.join(cmd)}")

    proc = subprocess.run(cmd)  # inherit stdio so ffmpeg progress streams live
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg transcode failed with exit code {proc.returncode}")
    return True


def assert_frame_alignment(config: Dict) -> None:
    """Assert the two work files share a frame index (plan 4.3). Fails loudly."""
    sb_out = config["work_files"].get("scoreboard")
    if not sb_out:
        print("  frame alignment: no scoreboard work file, nothing to compare")
        return

    piste_frames = probe_frame_count(config["work_files"]["piste"])
    sb_frames = probe_frame_count(sb_out)
    delta = abs(piste_frames - sb_frames)
    print(f"  frame counts: piste={piste_frames} scoreboard={sb_frames} delta={delta}")
    if delta > 1:
        raise RuntimeError(
            f"work files are NOT frame-aligned (piste={piste_frames}, "
            f"scoreboard={sb_frames}, delta={delta}). The whole design assumes a shared "
            f"frame index — re-run with --force before using these files."
        )


# ----------------------------------------------------------------------
# Gate preview (YOLO)
# ----------------------------------------------------------------------

def _draw_header(canvas, text: str) -> None:
    """Draw a caption on a dark bar so it stays readable over any footage."""
    import cv2

    overlay = canvas.copy()
    cv2.rectangle(overlay, (0, 0), (canvas.shape[1], 28), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.6, canvas, 0.4, 0, canvas)
    cv2.putText(canvas, text, (10, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)


def _load_yolo():
    """Load the project's YOLO pose model directly.

    PoseEstimator/PisteGate are being extended in parallel, so this stays independent
    of their signature; only the model path is shared.
    """
    from ultralytics import YOLO
    from analyzer.config import POSE_MODEL_PATH
    return YOLO(str(POSE_MODEL_PATH))


def _foot_y_from_person(box, keypoints, frame_h: int, kp_conf_threshold: float):
    """Foot y for one detection, mirroring the gate rule in plan 3.2.

    Ankle keypoints when confident, else the bbox bottom — and a bbox bottom that
    touches the frame edge means a cut-off foreground person, which never passes.
    """
    ankle_ys = [
        float(keypoints[i][1])
        for i in ANKLE_KEYPOINT_INDICES
        if keypoints is not None and len(keypoints) > i and float(keypoints[i][2]) > kp_conf_threshold
    ]
    if ankle_ys:
        return max(ankle_ys), False
    y2 = float(box[3])
    return y2, y2 >= frame_h - 2


def render_gate_previews(
    config: Dict,
    preview_dir: Path,
    stem: str,
    piste_number: int,
    timestamps: Sequence[float],
) -> List[Path]:
    """Draw the foot-band gate decision on 3 piste work-file frames.

    Green = inside the band (kept), red = outside (dropped), yellow lines = the band.
    Counts and foot-y values are printed too, so a headless operator learns exactly
    what the image shows.
    """
    import cv2
    from analyzer.config import POSE_KEYPOINT_CONFIDENCE

    piste_path = Path(config["work_files"]["piste"])
    if not piste_path.exists():
        print(f"  gate preview skipped: {piste_path} does not exist")
        return []

    piste = config["piste"]
    band = piste["foot_band_work"]
    model = _load_yolo()
    preview_dir.mkdir(parents=True, exist_ok=True)

    outputs: List[Path] = []
    for ts, frame_idx, frame in _read_frames_at(piste_path, timestamps):
        frame_h, frame_w = frame.shape[:2]
        results = model(
            frame,
            imgsz=int(piste.get("pose_imgsz", POSE_IMGSZ)),
            conf=float(piste.get("pose_conf", POSE_CONF)),
            max_det=GATE_PREVIEW_MAX_DET,
            verbose=False,
        )

        canvas = frame.copy()
        cv2.line(canvas, (0, int(band[0])), (frame_w, int(band[0])), _COLOR_BAND, 2)
        cv2.line(canvas, (0, int(band[1])), (frame_w, int(band[1])), _COLOR_BAND, 2)

        passed = 0
        failed = 0
        detail: List[str] = []
        for result in results:
            boxes = result.boxes
            if boxes is None or len(boxes) == 0:
                continue
            xyxy = boxes.xyxy.cpu().numpy()
            confs = boxes.conf.cpu().numpy()
            kps = None
            if getattr(result, "keypoints", None) is not None and result.keypoints.data is not None:
                kps = result.keypoints.data.cpu().numpy()

            for i, box in enumerate(xyxy):
                person_kps = kps[i] if kps is not None and i < len(kps) else None
                foot_y, cut_off = _foot_y_from_person(
                    box, person_kps, frame_h, POSE_KEYPOINT_CONFIDENCE
                )
                ok = (not cut_off) and classify_foot_y(foot_y, band)
                color = _COLOR_PASS if ok else _COLOR_FAIL
                x1, y1, x2, y2 = (int(v) for v in box[:4])
                cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
                cv2.circle(canvas, (int((x1 + x2) / 2), int(foot_y)), 4, color, -1)
                cv2.putText(canvas, f"{foot_y:.0f}", (x1, max(12, y1 - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
                passed += int(ok)
                failed += int(not ok)
                detail.append(
                    f"{'PASS' if ok else 'fail'} foot_y={foot_y:.0f} conf={float(confs[i]):.2f}"
                    + (" cut-off" if cut_off else "")
                )

        header = f"t={ts:.0f}s frame={frame_idx} band=[{band[0]},{band[1]}] pass={passed} fail={failed}"
        _draw_header(canvas, header)

        out_path = preview_dir / f"{stem}_piste{piste_number}_gate_{preview_label(ts)}.jpg"
        cv2.imwrite(str(out_path), canvas)
        outputs.append(out_path)

        print(f"  gate {header}")
        for line in sorted(detail):
            print(f"      {line}")
        print(f"      -> {out_path}")
        if passed != 2:
            print(f"      WARNING: expected 2 fencers inside the band, got {passed}")

    return outputs


def render_scoreboard_roi_previews(
    config: Dict,
    preview_dir: Path,
    stem: str,
    piste_number: int,
    timestamps: Sequence[float],
) -> List[Path]:
    """Draw the 5 scoreboard ROI rectangles on 3 scoreboard work-file frames.

    Plan 4.4 makes this the drift acceptance check: the target element must sit
    inside its ROI in all three frames.
    """
    import cv2

    scoreboard = config.get("scoreboard")
    sb_path_str = config["work_files"].get("scoreboard")
    if not scoreboard or not sb_path_str:
        print("  scoreboard ROI preview skipped: no scoreboard configured")
        return []

    sb_path = Path(sb_path_str)
    if not sb_path.exists():
        print(f"  scoreboard ROI preview skipped: {sb_path} does not exist")
        return []

    rois = scoreboard.get("rois") or {}
    if not rois:
        print("  scoreboard ROI preview: no ROIs defined yet, drawing frames only")

    preview_dir.mkdir(parents=True, exist_ok=True)
    outputs: List[Path] = []
    for ts, frame_idx, frame in _read_frames_at(sb_path, timestamps):
        canvas = frame.copy()
        for key, rect in rois.items():
            x, y, w, h = (int(v) for v in rect)
            cv2.rectangle(canvas, (x, y), (x + w, y + h), _COLOR_ROI, 2)
            cv2.putText(canvas, key, (x, max(12, y - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, _COLOR_ROI, 1)
        _draw_header(canvas, f"t={ts:.0f}s frame={frame_idx}")

        out_path = preview_dir / f"{stem}_piste{piste_number}_scoreboard_{preview_label(ts)}.jpg"
        cv2.imwrite(str(out_path), canvas)
        outputs.append(out_path)
        print(f"  scoreboard ROI preview -> {out_path}")

    print("  CHECK: each target element must sit inside its ROI in ALL THREE frames (plan 4.4)")
    return outputs


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare per-piste work files (piste crop + scoreboard crop) from a raw match video.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("video", help="Source video (read-only; never modified)")
    parser.add_argument("--piste", type=int, required=True, help="Piste number (config key + filename key)")
    parser.add_argument("--crop-band", type=parse_band, metavar="Y0:Y1",
                        help="4K source coords: piste crop vertical band (full bodies)")
    parser.add_argument("--foot-band", type=parse_band, metavar="Y0:Y1",
                        help="4K source coords: foot-tip y band (piste floor strip)")
    parser.add_argument("--scoreboard", type=parse_rect, metavar="X:Y:W:H",
                        help="4K source coords: scoreboard rect (before padding)")
    parser.add_argument("--scoreboard-roi", type=parse_scoreboard_roi, action="append",
                        default=[], metavar="KEY=X:Y:W:H",
                        help="SCOREBOARD-CROP coords; repeatable. Keys: " + " ".join(SCOREBOARD_ROI_KEYS))
    parser.add_argument("--config", help="Load an existing config and go straight to transcode + previews")
    parser.add_argument("--no-gui", action="store_true", help="Require CLI geometry instead of cv2.selectROI")
    parser.add_argument("--work-dir", default=str(DEFAULT_WORK_DIR))
    parser.add_argument("--config-dir", default=str(DEFAULT_CONFIG_DIR))
    parser.add_argument("--force", action="store_true", help="Re-run the transcode even if work files exist")
    parser.add_argument("--source-override", help="Decode this file instead of VIDEO (dev shortcut)")
    parser.add_argument("--skip-transcode", action="store_true", help="Write config + previews only")
    return parser


def _resolve_source_metadata(video: Path, override: Optional[Path]) -> Dict:
    """Probe the TRUE source for fps/resolution; fall back to the override if unmounted."""
    if video.exists():
        return probe_video(video)
    if override is not None and override.exists():
        print(f"  WARNING: {video} is not reachable — reading metadata from the override instead.")
        print("           source_fps / source_resolution therefore describe the override file.")
        return probe_video(override)
    raise RuntimeError(f"source video not found: {video}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    video = Path(args.video)
    override = Path(args.source_override) if args.source_override else None
    config_dir = Path(args.config_dir)
    preview_dir = config_dir / PREVIEW_SUBDIR
    stem = video.stem

    # ---------------- config: load or build ----------------
    if args.config:
        config_path = Path(args.config)
        config = json.loads(config_path.read_text(encoding="utf-8"))
        print(f"[1/5] loaded config: {config_path}")
        if override is not None and not config.get("source_override"):
            config["source_override"] = str(override)
            print(f"      source_override applied: {override}")
        stem = Path(config["source_video"]).stem
        timestamps = build_preview_timestamps(
            probe_video(config_decode_path(config))["duration"]
        )
    else:
        meta = _resolve_source_metadata(video, override)
        print(f"[1/5] source: {video}")
        print(f"      {meta['width']}x{meta['height']} @ {meta['fps']}fps, {meta['duration']:.1f}s")
        if override is not None:
            print(f"      DECODING OVERRIDE: {override}")
            ov = probe_video(override)
            if (ov["width"], ov["height"]) != (meta["width"], meta["height"]):
                print(
                    f"      WARNING: override is {ov['width']}x{ov['height']} but geometry is in "
                    f"{meta['width']}x{meta['height']} coords — crops will be wrong."
                )

        timestamps = build_preview_timestamps(meta["duration"])

        crop_band = args.crop_band
        foot_band = args.foot_band
        scoreboard_rect = args.scoreboard
        scoreboard_rois = dict(args.scoreboard_roi)

        have_cli_geometry = crop_band is not None and foot_band is not None

        print(f"[2/5] previews at t={', '.join(f'{t:.0f}s' for t in timestamps)}")
        preview_paths = extract_source_previews(
            override or video, preview_dir, stem, args.piste, timestamps
        )

        if not have_cli_geometry:
            if args.no_gui:
                print("ERROR: --no-gui requires --crop-band and --foot-band", file=sys.stderr)
                return 2
            picked = select_geometry_interactive(preview_paths[0])
            crop_band = crop_band or picked["crop_band"]
            foot_band = foot_band or picked["foot_band"]
            scoreboard_rect = scoreboard_rect or picked["scoreboard_rect"]

        config = build_config(
            source_video=video,
            piste_number=args.piste,
            source_fps=meta["fps"],
            source_resolution=(meta["width"], meta["height"]),
            crop_band=crop_band,
            foot_band=foot_band,
            scoreboard_rect=scoreboard_rect,
            scoreboard_rois=scoreboard_rois,
            work_dir=args.work_dir,
            source_override=override,
        )

        if scoreboard_rect is not None and not scoreboard_rois and not args.no_gui:
            picked_rois = select_scoreboard_rois_interactive(
                preview_paths[0], config["scoreboard"]["crop"], preview_dir, stem, args.piste
            )
            config["scoreboard"]["rois"] = {k: list(v) for k, v in picked_rois.items()}

        config_path = config_dir / f"{stem}_piste{args.piste}.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"[3/5] config written: {config_path}")

    # ---------------- transcode ----------------
    if args.skip_transcode:
        print("[4/5] transcode skipped (--skip-transcode)")
    else:
        print("[4/5] transcode (one decode, two outputs)")
        run_transcode(config, force=args.force)
        assert_frame_alignment(config)

    # ---------------- previews on the work files ----------------
    print("[5/5] gate + scoreboard ROI previews")
    render_gate_previews(config, preview_dir, stem, config["piste_number"], timestamps)
    render_scoreboard_roi_previews(config, preview_dir, stem, config["piste_number"], timestamps)

    print("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
