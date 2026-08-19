#!/usr/bin/env python3
"""Offline handedness detection from a report's keypoint sidecar.

Reads the joint sidecar the pipeline already wrote beside a report and runs
:func:`detect_handedness_v2` over it — which anatomical limb each fencer keeps
pointed at the opponent, voted over the whole bout. The video is never opened:
the sidecar holds every joint of both fencers on every sampled frame, which is
the entire input the detector needs, so re-deciding handedness on an existing
report costs seconds instead of a full pose pass.

    python3 scripts/detect_handedness_v2.py <report_id>            # print verdicts
    python3 scripts/detect_handedness_v2.py <report_id> --json     # machine-readable
    python3 scripts/detect_handedness_v2.py <report_id> --write    # store on the report

``--write`` touches exactly three fields per fencer — ``handedness``,
``handedness_confidence``, ``handedness_source`` — and rewrites the file
atomically. Everything else in the report, including field order, is left as it
was found: this script is a corrector, not a regenerator, and a report carries
lamp readings and share tokens that no other tool would put back.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

# Import the service package regardless of cwd — an admin runs this from anywhere.
_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

from analyzer.models import FencerPose, PoseKeypoint, PoseResult  # noqa: E402
from app.sharing import (  # noqa: E402
    private_dir,
    resolve_keypoints_path,
    resolve_report_path,
)
from ml.pose_analysis.kinematics import (  # noqa: E402
    HandednessVerdict,
    detect_handedness_v2,
)

#: Resolved from the script's own location, not the cwd, for the same reason.
REPORTS_DIR = _SERVICE_ROOT / "data" / "reports"

#: Written into the report so a later reader can tell a detected value from a
#: hand-entered one, and this detector's answer from the v1 detector's.
HANDEDNESS_SOURCE = "detected_v2"

#: COCO poses are 17 joints of (x, y, confidence).
_SIDECAR_JOINTS = 17
_SIDECAR_FLAT_LEN = _SIDECAR_JOINTS * 3

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NOT_FOUND = 2


def normalize_report_id(report_id: str) -> str:
    """Strip a typed-out ``.json`` so both spellings of an id work."""
    return report_id[:-5] if report_id.endswith(".json") else report_id


# ------------------------------------------------------------------
# Sidecar decoding
# ------------------------------------------------------------------


def decode_fencer(
    flat: Optional[list],
    side: str,
    conf_scale: float,
) -> Optional[FencerPose]:
    """One sidecar entry back into a :class:`FencerPose`, or None.

    ``None`` in the sidecar means "no detection in this sample" and stays a
    dropped frame here rather than becoming a pose at the origin, which the
    detector would happily read limb positions off.

    Confidences are stored as small ints to keep the file down; ``conf_scale``
    is the divisor that restores the 0-1 float. A malformed row — wrong length,
    non-numeric — is dropped for the same reason as a null.
    """
    if not isinstance(flat, list) or len(flat) != _SIDECAR_FLAT_LEN:
        return None

    keypoints: List[PoseKeypoint] = []
    for i in range(_SIDECAR_JOINTS):
        try:
            x = float(flat[3 * i])
            y = float(flat[3 * i + 1])
            conf = float(flat[3 * i + 2]) / conf_scale
        except (TypeError, ValueError):
            return None
        keypoints.append(PoseKeypoint(x=x, y=y, confidence=conf))

    # The sidecar stores no bbox or person confidence; the box is recovered from
    # the joints so the object is usable, and person_confidence stays 0.0 rather
    # than being invented. Nothing on the handedness path reads either.
    xs = [kp.x for kp in keypoints]
    ys = [kp.y for kp in keypoints]
    return FencerPose(
        keypoints=keypoints,
        bbox=[min(xs), min(ys), max(xs), max(ys)],
        person_confidence=0.0,
        side=side,
    )


def decode_sidecar(doc: dict) -> List[PoseResult]:
    """Sidecar document into the per-frame pose sequence the detector expects.

    Sample *i* of both sides is one frame: the sidecar's two arrays are parallel
    by construction, so pairing them by index is what puts the two fencers in
    the same :class:`PoseResult`. Frame indices are sample numbers, not source
    video frames — handedness is a bout-long tally and never asks what time it
    is, so multiplying by ``sample_every`` would only invite the number to be
    mistaken for a seekable frame.
    """
    try:
        conf_scale = float(doc.get("conf_scale") or 1.0)
    except (TypeError, ValueError):
        conf_scale = 1.0
    if conf_scale <= 0:
        conf_scale = 1.0

    poses = doc.get("poses") or {}
    columns = {
        side: (poses.get(side) if isinstance(poses.get(side), list) else [])
        for side in ("left", "right")
    }
    sample_count = max((len(col) for col in columns.values()), default=0)

    sequence: List[PoseResult] = []
    for i in range(sample_count):
        fencers = []
        for side in ("left", "right"):
            column = columns[side]
            flat = column[i] if i < len(column) else None
            fencer = decode_fencer(flat, side, conf_scale)
            if fencer is not None:
                fencers.append(fencer)
        sequence.append(PoseResult(frame_idx=i, fencers=fencers))
    return sequence


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ------------------------------------------------------------------
# Report writing
# ------------------------------------------------------------------


def write_report(path: Path, report: dict) -> None:
    """Write the report to ``path`` atomically, creating its directory.

    A report is several hundred KB and is the only copy of an analysis that
    took minutes to produce. Writing in place would leave it truncated and
    unparseable if the process died mid-write, so the new content lands in a
    sibling temp file first (same directory as the *destination*, so
    ``os.replace`` is a same-filesystem rename) and only then takes over the
    name.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp_name, path)
    except BaseException:
        # Never leave a stray dot-file behind; both report dirs are scanned by
        # the server's token index.
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def apply_verdicts(report: dict, verdicts: dict) -> None:
    """Set the three handedness fields on both fencer blocks, in place.

    Assignment rather than reconstruction: the fencer block holds touch counts,
    action distributions and names that this script has no business rewriting,
    and assigning to an existing key leaves it where it was in the file.
    """
    for side, key in (("left", "left_fencer"), ("right", "right_fencer")):
        block = report[key]
        verdict = verdicts[side]
        block["handedness"] = verdict.handedness
        block["handedness_confidence"] = verdict.confidence
        block["handedness_source"] = HANDEDNESS_SOURCE


# ------------------------------------------------------------------
# Output
# ------------------------------------------------------------------


def verdict_to_dict(verdict: HandednessVerdict) -> dict:
    return {
        "handedness": verdict.handedness,
        "confidence": verdict.confidence,
        "frames_used": verdict.frames_used,
        "left_weight": verdict.left_weight,
        "right_weight": verdict.right_weight,
        "per_limb": {
            limb: {"handedness": call, "confidence": conf, "frames": frames}
            for limb, (call, conf, frames) in verdict.per_limb.items()
        },
    }


def format_verdicts(report_id: str, sidecar_path: Path, doc: dict, verdicts: dict) -> str:
    """Human-readable report of both fencers' verdicts."""
    lines = [
        f"report:  {report_id}",
        f"sidecar: {sidecar_path}",
        f"samples: {doc.get('sample_count', '?')}"
        f"  (every {doc.get('sample_every', '?')} frames @ {doc.get('fps', '?')} fps)",
    ]
    for side in ("left", "right"):
        v = verdicts[side]
        call = v.handedness or "undetermined"
        lines.append("")
        lines.append(f"{side} fencer")
        lines.append(f"  verdict      {call}  (confidence {v.confidence:.3f})")
        lines.append(f"  frames used  {v.frames_used}")
        lines.append(f"  vote weight  left {v.left_weight:.1f} | right {v.right_weight:.1f}")
        for limb, (limb_call, limb_conf, limb_frames) in v.per_limb.items():
            shown = limb_call or "-"
            lines.append(
                f"  {limb:<11}  {shown:<12} conf {limb_conf:.3f}  {limb_frames} frames"
            )
    return "\n".join(lines)


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "report_id",
        help="report JSON stem, in data/reports/ or data/reports/private/ (.json optional)",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    parser.add_argument(
        "--write",
        action="store_true",
        help="store the verdicts on the report's left_fencer and right_fencer",
    )
    args = parser.parse_args(argv)

    report_id = normalize_report_id(args.report_id)

    sidecar_path = resolve_keypoints_path(REPORTS_DIR, report_id)
    if sidecar_path is None:
        # Exit 2, never create: a typo must not conjure an empty analysis.
        print(
            f"error: no keypoint sidecar for {report_id} "
            f"(looked under {private_dir(REPORTS_DIR)} and {REPORTS_DIR})",
            file=sys.stderr,
        )
        return EXIT_NOT_FOUND

    doc = load_json(sidecar_path)
    sequence = decode_sidecar(doc)
    verdicts = {
        side: detect_handedness_v2(sequence, side) for side in ("left", "right")
    }

    report_path = None
    if args.write:
        report_path = resolve_report_path(REPORTS_DIR, report_id)
        if report_path is None:
            print(
                f"error: no such report: {report_id} "
                f"(looked in {private_dir(REPORTS_DIR)} and {REPORTS_DIR})",
                file=sys.stderr,
            )
            return EXIT_NOT_FOUND

        report = load_json(report_path)
        missing = [k for k in ("left_fencer", "right_fencer") if not isinstance(report.get(k), dict)]
        if missing:
            # Creating the block would invent a fencer; refuse instead.
            print(
                f"error: report {report_id} has no {', '.join(missing)} block",
                file=sys.stderr,
            )
            return EXIT_ERROR

        apply_verdicts(report, verdicts)
        write_report(report_path, report)

    if args.json:
        payload = {
            "report_id": report_id,
            "sidecar_path": str(sidecar_path),
            "written_to": str(report_path) if report_path is not None else None,
            "fencers": {side: verdict_to_dict(v) for side, v in verdicts.items()},
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(format_verdicts(report_id, sidecar_path, doc, verdicts))
        if report_path is not None:
            print(f"\nwrote handedness ({HANDEDNESS_SOURCE}) to {report_path}")

    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
