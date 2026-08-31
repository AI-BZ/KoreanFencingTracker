"""
Build the browser work file for the second (zoomed-in) camera, and sync it.

The wide camera answers "where on the piste did this happen"; the zoomed camera
answers "what did the blade do". The report plays them side by side, so this
script produces the zoom work file and measures the constant that lines the two
clocks up, then records both in the piste config the report reads.

ENCODING — the rules are inherited from prepare_piste_video.py, not restated
    * ``-pix_fmt yuv420p``  : the source is an iPhone HEVC .MOV. Left alone, x264
      emits High 10 / 4:2:2 from a 10-bit source and no phone hardware decoder
      plays it. This has actually happened; it is not hypothetical.
    * ``-movflags +faststart``: the moov atom has to be at the front or playback
      cannot begin until the whole file has downloaded.
    * 30 fps: report frame numbers are work-file frames at 30 fps. The zoom
      camera shoots 120; matching the wide file's rate means one frame step moves
      both players by the same amount of time and no second mapping exists to get
      wrong.

RESOLUTION — 1920x1080, measured rather than assumed
    The zoom camera shoots 4K (3840x2160) full-frame. Downscaling choices were
    compared on the same instant (a lunge at wide t=105.70 s), cropped to the
    fencer pair and inspected 1:1:

      main piste work file (1280x334) : fencers ~90 px tall — the blade is not
                                        merely blurry, it is absent
      zoom at 1280x720                : posture and guard readable, blade fades
                                        into the green backdrop
      zoom at 1920x1080               : blade shaft traceable from hand to tip

    The purpose of this pane is the blade, so the first size that renders a blade
    wins. Going past 1080p buys nothing a coach can act on and doubles the file.

    CRF 23 rather than the piste file's 20: at 1080p the two are visually
    indistinguishable on this footage (both keep the blade traceable) and 23 is
    27% smaller — 20 s of test footage encoded to 15.6 MB at CRF 21 against
    11.4 MB at CRF 23. A 188 s bout lands near 108 MB.

Usage:
    cd services/analytics

    PYTHONPATH=. .venv/bin/python3 scripts/prepare_zoom_video.py \\
        data/piste_configs/BOUT_piste6.json \\
        "/Volumes/Film/.../BOUT_줌인.mov"
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.prepare_piste_video import DEFAULT_WORK_DIR, X264_PRESET, WORK_FPS  # noqa: E402
from scripts.sync_camera_pair import SyncRejected, apply_to_config, measure_offset  # noqa: E402

# See RESOLUTION in the module docstring — both numbers are measured.
ZOOM_SCALE_WIDTH = 1920
ZOOM_CRF = 23

# The zoom file's audio is what the offset was measured on, and keeping it lets
# anyone re-derive the sync later from the work files alone. It is a rounding
# error next to the video.
ZOOM_AUDIO_BITRATE = "96k"

WORK_SUFFIX = "_zoom.mp4"


def build_ffmpeg_command(source: Path, out_path: Path, fps: int = WORK_FPS) -> List[str]:
    """Single-output transcode: full frame, downscaled, at the work frame rate."""
    return [
        "ffmpeg", "-y", "-i", str(source),
        "-vf", f"scale={ZOOM_SCALE_WIDTH}:-2,fps={fps}",
        # ``0:a:0?`` — the first audio stream only. An iPhone HEVC .MOV carries a
        # second spatial-audio stream ffmpeg cannot decode; mapping all of them
        # aborts the transcode. The ``?`` keeps a silent source from failing.
        "-map", "0:v:0", "-map", "0:a:0?",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-crf", str(ZOOM_CRF),
        "-preset", X264_PRESET,
        "-movflags", "+faststart",
        "-c:a", "aac",
        "-b:a", ZOOM_AUDIO_BITRATE,
        str(out_path),
    ]


def default_work_path(config: dict, work_dir: Path) -> Path:
    """``<piste work file stem>_zoom.mp4`` — the pair is obvious from the names."""
    piste_out = Path(config["work_files"]["piste"])
    return work_dir / f"{piste_out.stem}{WORK_SUFFIX}"


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("config", type=Path, help="piste config of the wide camera")
    ap.add_argument("zoom_source", type=Path, help="zoomed camera's original file")
    ap.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    ap.add_argument("--out", type=Path, help="override the work-file path")
    ap.add_argument("--skip-encode", action="store_true",
                    help="the work file already exists; only measure and record the offset")
    args = ap.parse_args(argv)

    if not args.config.is_file():
        print(f"config not found: {args.config}", file=sys.stderr)
        return 2
    if not args.zoom_source.is_file():
        print(f"zoom source not found: {args.zoom_source}", file=sys.stderr)
        return 2

    config = json.loads(args.config.read_text(encoding="utf-8"))
    wide_work = Path(config["work_files"]["piste"])
    if not wide_work.is_file():
        print(f"wide work file missing — run prepare_piste_video.py first: {wide_work}",
              file=sys.stderr)
        return 2

    out_path = args.out or default_work_path(config, args.work_dir)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if args.skip_encode:
        if not out_path.is_file():
            print(f"--skip-encode but no work file at {out_path}", file=sys.stderr)
            return 2
        print(f"reusing {out_path}")
    else:
        cmd = build_ffmpeg_command(args.zoom_source, out_path)
        print(" ".join(cmd))
        proc = subprocess.run(cmd)  # inherit stdio so progress streams live
        if proc.returncode != 0:
            print(f"ffmpeg failed with exit code {proc.returncode}", file=sys.stderr)
            return 1

    # Measure on the WORK FILES, not the originals. These are the two files the
    # browser actually plays, so an offset derived from them cannot be wrong
    # about a trim or a frame-rate conversion that happened on the way here.
    try:
        sync = measure_offset(wide_work, out_path)
    except SyncRejected as exc:
        print(f"\nREJECTED: {exc}", file=sys.stderr)
        print("The work file was written but NO offset was recorded — the report "
              "will keep showing one camera.", file=sys.stderr)
        return 3

    print(f"\noffset_sec : {sync['offset_sec']:+.3f}   (zoom_time = wide_time + offset)")
    print(f"peak       : {sync['peak']:.4f}")
    print(f"spread     : {sync['spread_sec']:.3f}s")

    apply_to_config(config, args.zoom_source, sync, str(out_path))
    args.config.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote zoom block to {args.config}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
