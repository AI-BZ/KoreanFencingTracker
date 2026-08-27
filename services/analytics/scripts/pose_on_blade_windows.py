#!/usr/bin/env python3
"""Run pose estimation on every extracted blade-labelling frame.

The bout-wide keypoint sidecar samples every third work frame — every sixth
source frame, 100ms apart — which is too coarse for the thing these windows
exist to settle. A parry occupies three or four source frames; at 100ms the
frames on either side of it are all we get, and on the one clean parry in this
bout (window_010) the right fencer has no pose at all for three consecutive
samples, exactly across the action.

The extracted JPEGs are already the crop a labeller looks at, at full 4K
resolution, so posing them directly gives a wrist for every labelled frame in
the crop's own coordinates — no rescaling from work-file pixels, no gaps.

What it does not give is the blade. Line detection over these frames returns
~1,350 segments, 83 of them longer than 100px, and the blade is not separable
from piste lines, cables and clothing edges by geometry alone. The blade has to
come from the labels; this script only puts the wrist next to them.

Usage:
    cd services/analytics
    PYTHONPATH=. .venv/bin/python3 scripts/pose_on_blade_windows.py \\
        --data-dir data/blade_labels/260716_de64_s1_piste3
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import cv2

POSES_NAME = "poses.json"
MANIFEST_NAME = "manifest.json"

#: COCO keypoint indices we keep. The full 17 would triple the file for joints
#: no blade question depends on.
KEEP = {
    5: "shoulder_l", 6: "shoulder_r",
    7: "elbow_l", 8: "elbow_r",
    9: "wrist_l", 10: "wrist_r",
    11: "hip_l", 12: "hip_r",
    15: "ankle_l", 16: "ankle_r",
}


#: COCO ankle indices — where a fencer stands, which is what puts them on a
#: piste or not.
ANKLES = (15, 16)


def on_target_piste(fencer, band: Optional[Sequence[float]]) -> bool:
    """Are this fencer's feet inside the target piste's foot band?

    These crops are wide enough to include the piste behind: window_010 holds
    four fencers, and picking the leftmost and rightmost detections by
    horizontal position selected two bystanders standing further up the frame.
    Their wrists then sat almost still through the parry, which is exactly the
    signal a parry detector would be reading.
    """
    if not band:
        return True
    ys = [fencer.keypoints[i].y for i in ANKLES
          if i < len(fencer.keypoints) and fencer.keypoints[i].confidence > 0]
    if not ys:
        return False
    return band[0] <= max(ys) <= band[1]


def assign_sides(fencers: Sequence, band: Optional[Sequence[float]] = None) -> Dict[str, object]:
    """Left/right by horizontal position, among fencers on the target piste."""
    def cx(f):
        xs = [kp.x for kp in f.keypoints if kp.confidence > 0]
        return sum(xs) / len(xs) if xs else 0.0

    ordered = sorted((f for f in fencers if on_target_piste(f, band)), key=cx)
    if not ordered:
        return {}
    if len(ordered) == 1:
        return {"left": ordered[0]}
    return {"left": ordered[0], "right": ordered[-1]}


def pack(fencer) -> Optional[Dict[str, List[float]]]:
    """Keypoints of interest as {name: [x, y, conf]}, rounded."""
    if fencer is None:
        return None
    out: Dict[str, List[float]] = {}
    for idx, name in KEEP.items():
        if idx >= len(fencer.keypoints):
            continue
        kp = fencer.keypoints[idx]
        if kp.confidence <= 0:
            continue
        out[name] = [round(float(kp.x), 1), round(float(kp.y), 1), round(float(kp.confidence), 2)]
    return out or None


def weapon_wrist(packed: Optional[dict], side: str) -> Optional[List[float]]:
    """The wrist nearer the opponent.

    Not the higher-confidence one: for the right fencer that picks the rear
    hand about half the time, which lands ~190px behind the guard — far enough
    to seed a blade search in the wrong place.
    """
    if not packed:
        return None
    cands = [packed[k] for k in ("wrist_l", "wrist_r") if k in packed]
    if not cands:
        return None
    return max(cands, key=lambda p: p[0]) if side == "left" else min(cands, key=lambda p: p[0])


def foot_band_for(window: dict, piste_config: Optional[dict]) -> Optional[List[float]]:
    """The target piste's foot band, expressed in this window's crop pixels.

    The config states it in work-file pixels; the crops here are cut from the
    4K source, so it goes through the piste crop's own scale and origin before
    the window's origin is removed.
    """
    if not piste_config:
        return None
    piste = piste_config.get("piste") or {}
    band = piste.get("foot_band_work")
    crop = piste.get("crop")
    width = piste.get("scale_width")
    if not (band and crop and width):
        return None
    scale = crop["w"] / width
    cy = window["crop"]["y"]
    return [band[0] * scale + crop["y"] - cy, band[1] * scale + crop["y"] - cy]


def run(data_dir: Path, confidence: float, imgsz: int, max_det: int,
        piste_config: Optional[dict] = None) -> dict:
    from ml.pose_estimator import PoseEstimator

    manifest = json.loads((data_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    windows = manifest.get("windows", [])
    total = sum(len(w.get("frames", [])) for w in windows)
    print(f"{len(windows)} windows, {total} frames")

    estimator = PoseEstimator(confidence=confidence, imgsz=imgsz, max_det=max_det)
    poses: Dict[str, dict] = {}
    done = 0
    started = time.time()

    for window in windows:
        wid = window["window_id"]
        band = foot_band_for(window, piste_config)
        wdir = data_dir / wid
        for frame in window.get("frames", []):
            path = wdir / frame["file"]
            img = cv2.imread(str(path))
            if img is None:
                done += 1
                continue
            result = estimator.estimate_pose(img, frame_idx=frame["source_frame"])
            sides = assign_sides(result.fencers, band)
            row = {}
            for side in ("left", "right"):
                packed = pack(sides.get(side))
                if packed:
                    row[side] = packed
            if row:
                poses[str(frame["source_frame"])] = row
            done += 1
            if done % 200 == 0:
                rate = done / max(1e-6, time.time() - started)
                print(f"  {done}/{total}  ({rate:.1f} f/s, {(total-done)/rate/60:.1f} min left)")

    elapsed = time.time() - started
    out = {
        "version": 1,
        "report_id": manifest.get("report_id"),
        "source": "pose_on_blade_windows",
        "confidence": confidence,
        "imgsz": imgsz,
        "frames_total": total,
        "frames_with_pose": len(poses),
        "elapsed_sec": round(elapsed, 1),
        "poses": poses,
    }
    (data_dir / POSES_NAME).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    both = sum(1 for r in poses.values() if "left" in r and "right" in r)
    print(f"\n{len(poses)}/{total} frames posed ({len(poses)/total:.0%}), "
          f"both fencers on {both} ({both/total:.0%}) — {elapsed/60:.1f} min")
    print(f"wrote {data_dir / POSES_NAME}")
    return out


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--data-dir", required=True, type=Path)
    p.add_argument("--confidence", type=float, default=0.25)
    p.add_argument("--imgsz", type=int, default=1280)
    p.add_argument("--max-det", type=int, default=8)
    p.add_argument("--piste-config", type=Path, default=None,
                   help="piste config whose foot_band_work selects the target piste; "
                        "without it every detection in the crop is a candidate")
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    cfg = json.loads(args.piste_config.read_text(encoding="utf-8")) if args.piste_config else None
    run(args.data_dir, args.confidence, args.imgsz, args.max_det, cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
