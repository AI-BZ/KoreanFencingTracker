"""
Measure the start offset between two cameras that filmed the same bout.

Two phones on two tripods are never started at the same instant, so the wide
piste camera and the zoomed-in camera disagree by several seconds. Playing them
side by side is only useful once that constant is known: the report seeks both
players from one clock, and the zoom player's clock is

    zoom_time = wide_time + offset_sec          (offset_sec is negative when the
                                                 zoom camera was started later)

WHY AUDIO AND NOT PICTURE
    The two cameras see different framings of the same piste, so no pixel-level
    match exists between them. What they do share is the room: the same buzzer,
    the same referee, the same crowd. The loudness envelope of that room is
    identical in both recordings up to a time shift, which is exactly what a
    cross-correlation recovers.

METHOD (each step earns its place)
    1. decode both audio tracks to 8 kHz mono PCM       — speech/buzzer band is
       well under 4 kHz, and 8 kHz keeps the arrays small
    2. envelope = moving average of |sample|, window 400 (50 ms)
                                                        — the raw waveform's
       phase is meaningless across two microphones metres apart; only the
       loudness contour is shared
    3. decimate by 100 -> 80 Hz                         — 12.5 ms resolution,
       finer than a video frame at 30 fps, and 100x less work
    4. z-normalise each envelope                        — cancels the two
       cameras' different gain and distance from the piste
    5. np.correlate(wide, zoom, "full"), take the argmax

REJECTION
    A wrong offset is worse than no offset: it puts two unrelated moments side
    by side and invites the coach to draw a conclusion from them. So a weak peak
    is refused rather than reported.

    ``MIN_PEAK = 0.40`` is set from measurement, not taste. The one pair
    validated frame-by-frame against the scoreboard
    (20260828 김창환배 송예솔vs박소윤, wide 199.85 s / zoom 188.33 s) peaks at
    **0.832**, and its runner-up candidates all sit within +-0.05 s of the winner
    — a genuine match is both strong and sharp. 0.40 is less than half that
    measured peak, so it passes real matches with a wide margin while refusing
    the flat, ambiguous correlation surface that two unrelated recordings give.
    Raise it, never lower it, if a bad pair ever slips through.

Usage:
    cd services/analytics

    # measure only
    PYTHONPATH=. .venv/bin/python3 scripts/sync_camera_pair.py \\
        data/raw/own/BOUT_piste6.mp4 data/raw/own/BOUT_piste6_zoom.mp4

    # measure and record into the piste config the report reads
    PYTHONPATH=. .venv/bin/python3 scripts/sync_camera_pair.py \\
        data/raw/own/BOUT_piste6.mp4 data/raw/own/BOUT_piste6_zoom.mp4 \\
        --config data/piste_configs/BOUT_piste6.json --write
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np

# ---- envelope parameters (see METHOD above) ----
SAMPLE_RATE = 8000        # Hz, mono
ENVELOPE_WINDOW = 400     # samples of |x| averaged = 50 ms
DECIMATION = 100          # -> 80 Hz envelope, 12.5 ms per step
ENVELOPE_RATE = SAMPLE_RATE / DECIMATION

# See REJECTION in the module docstring: measured peak on the validated pair is
# 0.832; this sits at less than half of it.
MIN_PEAK = 0.40

# How far apart two cameras' start times may plausibly be. Someone walking from
# one tripod to the other and hitting record bounds this in practice; capping it
# also stops the correlation from "matching" a repeated crowd noise minutes away.
MAX_ABS_OFFSET_SEC = 120.0


class SyncRejected(RuntimeError):
    """The correlation was too weak to trust. Callers must not use an offset."""


# ----------------------------------------------------------------------
# audio -> envelope
# ----------------------------------------------------------------------


def read_audio(path: Path) -> np.ndarray:
    """Decode one media file's first audio stream to mono float32 at SAMPLE_RATE.

    ``0:a:0`` and not all audio streams: an iPhone HEVC .MOV carries a second
    spatial-audio stream (tag ``apac``) that ffmpeg cannot decode, and asking for
    it kills the whole command.
    """
    cmd = [
        "ffmpeg", "-v", "error", "-i", str(path),
        "-map", "0:a:0",
        "-ac", "1", "-ar", str(SAMPLE_RATE),
        "-f", "s16le", "-",
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(
            f"could not decode audio from {path}: "
            f"{proc.stderr.decode('utf-8', 'replace').strip()}"
        )
    pcm = np.frombuffer(proc.stdout, dtype=np.int16)
    if pcm.size == 0:
        raise RuntimeError(f"{path} has no audio to synchronise on")
    return pcm.astype(np.float32) / 32768.0


def envelope(samples: np.ndarray) -> np.ndarray:
    """Loudness contour: moving average of |x|, decimated, z-normalised."""
    rectified = np.abs(samples)
    # cumulative-sum moving average — O(n) and exact, unlike a convolution kernel
    csum = np.cumsum(np.concatenate(([0.0], rectified), dtype=np.float64))
    if csum.size <= ENVELOPE_WINDOW:
        raise RuntimeError("audio is shorter than one envelope window")
    smoothed = (csum[ENVELOPE_WINDOW:] - csum[:-ENVELOPE_WINDOW]) / ENVELOPE_WINDOW
    env = smoothed[::DECIMATION]

    std = env.std()
    if std == 0:
        raise RuntimeError("audio envelope is flat — silent track, nothing to match")
    return ((env - env.mean()) / std).astype(np.float64)


# ----------------------------------------------------------------------
# correlation
# ----------------------------------------------------------------------


def correlate_envelopes(
    wide_env: np.ndarray,
    zoom_env: np.ndarray,
) -> Tuple[float, float, np.ndarray]:
    """Return ``(offset_sec, peak, scores)``.

    ``offset_sec`` is the constant in ``zoom_time = wide_time + offset_sec``.
    ``peak`` is a normalised correlation coefficient in [-1, 1]: both envelopes
    are z-normalised, so dividing by ``sqrt(len(a) * len(b))`` bounds it at 1 for
    a perfect match and leaves an unrelated pair near 0.
    """
    raw = np.correlate(wide_env, zoom_env, mode="full")
    scores = raw / np.sqrt(float(wide_env.size) * float(zoom_env.size))

    # np.correlate index i corresponds to zoom being shifted by
    # (i - (len(zoom) - 1)) envelope steps relative to wide.
    lags = (np.arange(scores.size) - (zoom_env.size - 1)) / ENVELOPE_RATE

    # Restrict to physically plausible start differences before taking the max.
    allowed = np.abs(lags) <= MAX_ABS_OFFSET_SEC
    if not allowed.any():
        raise RuntimeError("no candidate offset within the plausible range")
    masked = np.where(allowed, scores, -np.inf)

    best = int(np.argmax(masked))
    # A positive lag here means wide had to be shifted forward to meet zoom,
    # i.e. the zoom camera started EARLIER. The report needs the opposite sign.
    offset_sec = -float(lags[best])
    return offset_sec, float(scores[best]), scores


def peak_sharpness(scores: np.ndarray, window: int = 8) -> float:
    """Spread, in seconds, of the strongest candidates around the winner.

    A real match is not just strong but sharp — the runner-up lags cluster
    against the winner. On the validated pair they all fall within +-0.05 s.
    Reported for the operator to eyeball; it is not a gate.
    """
    order = np.argsort(scores)[::-1][:window]
    return float((order.max() - order.min()) / ENVELOPE_RATE)


def measure_offset(wide: Path, zoom: Path, min_peak: float = MIN_PEAK) -> Dict:
    """Measure the wide->zoom offset, raising SyncRejected on a weak peak."""
    wide_env = envelope(read_audio(wide))
    zoom_env = envelope(read_audio(zoom))
    offset_sec, peak, scores = correlate_envelopes(wide_env, zoom_env)

    result = {
        "offset_sec": round(offset_sec, 3),
        "peak": round(peak, 4),
        "spread_sec": round(peak_sharpness(scores), 3),
        "method": "audio_envelope_xcorr",
        "min_peak": min_peak,
        "measured_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    if peak < min_peak:
        raise SyncRejected(
            f"correlation peak {peak:.3f} is below {min_peak:.2f} — refusing to "
            f"report an offset. A mis-synced pair shows two unrelated moments "
            f"side by side, which is worse than showing one camera."
        )
    return result


# ----------------------------------------------------------------------
# config write-back
# ----------------------------------------------------------------------


def apply_to_config(config: Dict, zoom_path: Path, sync: Dict, work_file: Optional[str]) -> Dict:
    """Merge a measured offset into a piste config's ``zoom`` block, in place."""
    block = config.setdefault("zoom", {})
    block["source_video"] = str(zoom_path)
    if work_file:
        block["work_file"] = work_file
    block["offset_sec"] = sync["offset_sec"]
    block["sync"] = {k: v for k, v in sync.items() if k != "offset_sec"}
    return config


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("wide", type=Path, help="wide / piste camera file (the report's main video)")
    ap.add_argument("zoom", type=Path, help="zoomed-in camera file")
    ap.add_argument("--config", type=Path, help="piste config to record the offset into")
    ap.add_argument("--work-file", help="zoom work file path to store in the config")
    ap.add_argument("--write", action="store_true", help="actually write --config (otherwise dry run)")
    ap.add_argument("--min-peak", type=float, default=MIN_PEAK,
                    help=f"reject below this normalised peak (default {MIN_PEAK})")
    args = ap.parse_args(argv)

    for p in (args.wide, args.zoom):
        if not p.is_file():
            print(f"not a file: {p}", file=sys.stderr)
            return 2

    try:
        sync = measure_offset(args.wide, args.zoom, min_peak=args.min_peak)
    except SyncRejected as exc:
        print(f"REJECTED: {exc}", file=sys.stderr)
        return 3

    print(f"offset_sec : {sync['offset_sec']:+.3f}   (zoom_time = wide_time + offset)")
    print(f"peak       : {sync['peak']:.4f}   (threshold {args.min_peak})")
    print(f"spread     : {sync['spread_sec']:.3f}s  (top candidates' lag spread)")

    if args.config:
        if not args.config.is_file():
            print(f"config not found: {args.config}", file=sys.stderr)
            return 2
        config = json.loads(args.config.read_text(encoding="utf-8"))
        apply_to_config(config, args.zoom, sync, args.work_file)
        if args.write:
            args.config.write_text(
                json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(f"wrote zoom block to {args.config}")
        else:
            print("\n--- would write (pass --write) ---")
            print(json.dumps(config["zoom"], ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
