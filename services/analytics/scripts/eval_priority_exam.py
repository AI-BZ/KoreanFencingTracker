#!/usr/bin/env python3
"""Score :class:`FoilPriorityJudge` against an FIE referee exam answer key.

``PRIORITY_ESTIMATION_ENABLED`` is off because the judge's thresholds were
tuned on sixteen labels from three bouts and did not survive a bout-level
holdout (see ``analyzer/config.py``). The blocker recorded there is not a
missing idea but missing labels: *"more labelled bouts settle it"*. An FIE
referee exam is exactly that — fifteen phrases, each with a published,
referee-authoritative answer, from bouts the thresholds have never seen. This
script measures the judge against them and changes nothing about it.

The judge is used exactly as production would use it, through
``build_priority_judge``, with ``enabled=True`` forced the same way
``calibrate_foil_priority.py`` forces it: a flag that is off cannot be measured,
and measurement is the only thing that could ever turn it back on.

Two adaptations are needed, and both are in *this* script rather than in any
shipped module:

* **Clip scope.** The judge answers per exchange, and the report pipeline that
  normally feeds it does not exist for a bare clip. Here each clip is one
  phrase, so its touch is the last exchange the detector finds, and that is the
  exchange whose call is scored.
* **Broadcast framing.** These are TV frames: the fencers occupy a fraction of
  the height and a referee, and sometimes spectators, stand in shot. The default
  estimator keeps YOLO's top two detections *by confidence*, which on this
  footage can be the referee. ``--select largest`` raises ``max_det`` and keeps
  the two largest bodies instead, which on a piste shot is the two fencers.

Usage:
    cd services/analytics
    PYTHONPATH=. .venv/bin/python3 scripts/eval_priority_exam.py \\
        --manifest data/ref_exam/p2_manifest.json
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import cv2

from analyzer.config import (
    POSE_KEYPOINT_CONFIDENCE,
    PRIORITY_WINDOW_LEAD_SEC,
)
from analyzer.models import PoseResult
from ml.weapon_analyzers import build_priority_judge

SIDES = ("left", "right")

#: Sampling stride, matching the continuous-report pipeline's default.
DEFAULT_SAMPLE_EVERY = 3

#: Detection confidence. Below the shipped 0.5 default because a fencer 10% of
#: the frame high scores lower than one filling half of it; the exam footage is
#: the far end of that range.
DEFAULT_POSE_CONFIDENCE = 0.25

#: Detections YOLO may return per frame under ``--select largest``. Has to
#: exceed two so that a referee or a spectator can be *outranked* rather than
#: silently occupying one of the two slots.
DEFAULT_MAX_DET = 8

#: Reasons that are not a call. Kept separate from the judge's own reason codes
#: so the evaluator can distinguish "the judge declined" from "there was
#: nothing to hand the judge".
REASON_NO_EXCHANGE = "no_exchange_detected"


# ------------------------------------------------------------------
# Pose adaptation for broadcast framing
# ------------------------------------------------------------------


def _bbox_area(fencer) -> float:
    x1, y1, x2, y2 = fencer.bbox
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def _bbox_height_ratio(fencer, frame_height: float) -> float:
    if frame_height <= 0:
        return 0.0
    return (fencer.bbox[3] - fencer.bbox[1]) / frame_height


def keep_two_largest(result: PoseResult) -> PoseResult:
    """Reduce a frame's detections to the two largest bodies, sides reassigned.

    Size is the right discriminator on a piste shot: the fencers are on the
    strip nearest the camera and the referee stands behind them, so the referee
    is smaller even when YOLO is more confident about him (he is unoccluded and
    standing still). Sides are then assigned by bbox x-centre, reproducing what
    ``PoseEstimator._parse_results`` does when it happens to see exactly two
    people — the assignment rule is not being changed, only the choice of which
    two people it is applied to.
    """
    fencers = sorted(result.fencers, key=_bbox_area, reverse=True)[:2]
    if len(fencers) == 2:
        cx0 = (fencers[0].bbox[0] + fencers[0].bbox[2]) / 2
        cx1 = (fencers[1].bbox[0] + fencers[1].bbox[2]) / 2
        if cx0 <= cx1:
            fencers[0].side, fencers[1].side = "left", "right"
        else:
            fencers[0].side, fencers[1].side = "right", "left"
    elif len(fencers) == 1:
        # One body is never enough for a distance series, so which side it is
        # called does not affect any measurement. Left unchanged rather than
        # guessed.
        pass
    return PoseResult(
        frame_idx=result.frame_idx,
        fencers=fencers,
        inference_time_ms=result.inference_time_ms,
    )


def pose_quality(
    pose_results: Sequence[PoseResult], frame_height: float,
) -> dict:
    """How much of the clip the estimator actually saw two fencers in.

    Reported per question because a wrong call caused by a missing body and a
    wrong call caused by the judge's thresholds are different findings, and
    without this they are indistinguishable in the results table.
    """
    total = len(pose_results)
    both = 0
    heights: List[float] = []
    for pr in pose_results:
        sides = {f.side for f in pr.fencers}
        if "left" in sides and "right" in sides:
            both += 1
        for f in pr.fencers:
            heights.append(_bbox_height_ratio(f, frame_height))
    return {
        "sampled_frames": total,
        "two_fencer_frames": both,
        "two_fencer_rate": round(both / total, 3) if total else 0.0,
        "mean_body_height_ratio": (
            round(sum(heights) / len(heights), 3) if heights else 0.0
        ),
    }


# ------------------------------------------------------------------
# Per-clip analysis
# ------------------------------------------------------------------


def read_sampled_frames(
    clip_path: Path, sample_every: int,
) -> Tuple[List, float, float]:
    """Every ``sample_every``-th frame of the clip, plus its fps and height."""
    cap = cv2.VideoCapture(str(clip_path))
    if not cap.isOpened():
        raise SystemExit(f"ERROR: cannot open clip: {clip_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 720.0
    frames = []
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % sample_every == 0:
            frames.append(frame)
        idx += 1
    cap.release()
    return frames, float(fps), float(height)


def select_exchange(exchanges: Sequence[dict], strategy: str) -> Optional[dict]:
    """The exchange whose priority call answers this question.

    ``last`` takes the final exchange, which is the touch: an exam clip is cut
    to one phrase and ends on the hit. ``closest`` takes the nearest approach of
    the whole clip instead, which differs only when the detector splits the
    phrase and the real contact lands in an earlier fragment.
    """
    if not exchanges:
        return None
    if strategy == "closest":
        return min(
            exchanges,
            key=lambda ex: (
                ex.get("min_distance_bh")
                if ex.get("min_distance_bh") is not None
                else float("inf")
            ),
        )
    return exchanges[-1]


def evaluate_question(
    clip_path: Path,
    answer: Optional[str],
    question: int,
    args,
    estimator,
    analyzer_cls,
) -> dict:
    """Run the pipeline over one clip and score its priority call."""
    t0 = time.time()
    frames, fps, frame_height = read_sampled_frames(clip_path, args.sample_every)
    if not frames:
        return {
            "question": question,
            "clip": clip_path.name,
            "answer": answer,
            "verdict": None,
            "reason": "empty_clip",
            "correct": False,
        }

    pose_results = estimator.estimate_poses_batch(frames)
    if args.select == "largest":
        pose_results = [keep_two_largest(pr) for pr in pose_results]

    quality = pose_quality(pose_results, frame_height)

    # analyze_continuous is handed an already-sampled sequence, so its frame
    # indices are sample indices and its effective frame rate is the clip's
    # divided by the stride. Every downstream duration — the priority decision
    # window above all — is expressed in seconds, so getting this wrong would
    # silently rescale the judge's window rather than fail.
    effective_fps = fps / args.sample_every
    analyzer = analyzer_cls()
    analyzer.fps = effective_fps
    priority_lead_samples = max(1, round(PRIORITY_WINDOW_LEAD_SEC * effective_fps))

    result = analyzer.analyze_continuous(
        pose_sequence=pose_results,
        sample_every_n=1,
        priority_lead_samples=priority_lead_samples,
    )
    exchanges = [ex.to_dict() for ex in result.exchanges]

    judge = build_priority_judge("foil", exchanges, effective_fps, enabled=True)

    per_exchange = []
    if judge is not None:
        for i, ex in enumerate(exchanges):
            call = judge.judge(ex)
            per_exchange.append({
                "index": i,
                "start_frame": ex.get("start_frame"),
                "min_distance_frame": ex.get("min_distance_frame"),
                "min_distance_bh": ex.get("min_distance_bh"),
                "footwork_left": ex.get("footwork_left"),
                "footwork_right": ex.get("footwork_right"),
                "attacker": call.attacker,
                "reason": call.reason,
                "detail": call.detail,
            })

    target = select_exchange(exchanges, args.exchange)
    verdict: Optional[str] = None
    reason = REASON_NO_EXCHANGE
    detail = None
    footwork = None
    if target is not None and judge is not None:
        call = judge.judge(target)
        verdict = call.attacker
        reason = call.reason
        detail = call.detail
        footwork = {
            "left": target.get("footwork_left"),
            "right": target.get("footwork_right"),
        }
    elif target is not None and judge is None:
        # build_priority_judge declines when no exchange carries a priority
        # series at all, which here means the pose never held both fencers long
        # enough for the window to exist.
        reason = "no_priority_series"

    return {
        "question": question,
        "clip": clip_path.name,
        "answer": answer,
        "verdict": verdict,
        "reason": reason,
        "correct": bool(verdict) and verdict == answer,
        "exchanges_detected": len(exchanges),
        "target_exchange": (
            None if target is None
            else {
                "start_frame": target.get("start_frame"),
                "end_frame": target.get("end_frame"),
                "min_distance_frame": target.get("min_distance_frame"),
                "min_distance_bh": target.get("min_distance_bh"),
                "footwork": footwork,
            }
        ),
        "detail": detail,
        "pose_quality": quality,
        "per_exchange": per_exchange,
        "analysis_sec": round(time.time() - t0, 1),
    }


# ------------------------------------------------------------------
# Reporting
# ------------------------------------------------------------------


def format_table(rows: Sequence[dict]) -> str:
    """The per-question table, printed and kept identical in the JSON result."""
    lines = [
        "  Q   verdict   answer   hit   reason         "
        "ex  commitL commitR margin  qual  fw(L,R)",
        "  " + "-" * 96,
    ]
    for row in rows:
        detail = row.get("detail") or {}
        target = row.get("target_exchange") or {}
        fw = target.get("footwork") or {}
        hit = "✔" if row["correct"] else ("·" if row["verdict"] is None else "✘")

        def num(value, width=7):
            return f"{value:>{width}.3f}" if isinstance(value, (int, float)) else " " * width

        def fw_type(entry):
            if isinstance(entry, dict):
                return entry.get("footwork_type") or "-"
            return entry or "-"

        lines.append(
            f"  {row['question']:>2}  {str(row['verdict'] or '-'):<8}  "
            f"{str(row['answer'] or '-'):<7}  {hit:^3}  "
            f"{row['reason']:<14} {row['exchanges_detected']:>2}  "
            f"{num(detail.get('commit_left'))} {num(detail.get('commit_right'))} "
            f"{num(detail.get('margin'), 6)} {num(detail.get('window_quality'), 5)}  "
            f"{fw_type(fw.get('left'))},{fw_type(fw.get('right'))}"
        )
    return "\n".join(lines)


def summarise(rows: Sequence[dict]) -> dict:
    """Accuracy over calls made, over all questions, and the decline breakdown."""
    total = len(rows)
    called = [r for r in rows if r["verdict"] is not None]
    correct = [r for r in called if r["correct"]]
    unknown = [r for r in rows if r["verdict"] is None]
    reasons: dict = {}
    for r in unknown:
        reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1

    answers = [r["answer"] for r in rows if r["answer"]]
    majority = 0
    if answers:
        majority = max(answers.count("left"), answers.count("right")) / len(answers)

    return {
        "questions": total,
        "calls_made": len(called),
        "correct": len(correct),
        "unknown": len(unknown),
        "accuracy_over_all": round(len(correct) / total, 3) if total else 0.0,
        "accuracy_over_calls": (
            round(len(correct) / len(called), 3) if called else None
        ),
        "majority_class_baseline": round(majority, 3),
        "decline_reasons": reasons,
        "verdict_distribution": {
            side: sum(1 for r in called if r["verdict"] == side) for side in SIDES
        },
        "answer_distribution": {
            side: answers.count(side) for side in SIDES
        },
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--manifest", default="data/ref_exam/p2_manifest.json",
        help="Manifest written by scripts/build_referee_exam_set.py",
    )
    parser.add_argument(
        "--out", default=None,
        help="Result JSON path (default: <manifest dir>/<prefix>_eval_result.json)",
    )
    parser.add_argument("--sample-every", type=int, default=DEFAULT_SAMPLE_EVERY)
    parser.add_argument(
        "--pose-confidence", type=float, default=DEFAULT_POSE_CONFIDENCE,
    )
    parser.add_argument("--max-det", type=int, default=DEFAULT_MAX_DET)
    parser.add_argument(
        "--select", choices=("largest", "confidence"), default="largest",
        help="Which two detections are the fencers (see module docstring)",
    )
    parser.add_argument(
        "--exchange", choices=("last", "closest"), default="last",
        help="Which detected exchange carries the question's touch",
    )
    parser.add_argument(
        "--only", type=int, nargs="*", default=None,
        help="Evaluate only these question numbers",
    )
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        print(
            "       Run scripts/build_referee_exam_set.py first.", file=sys.stderr,
        )
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    clip_dir = manifest_path.parent

    questions = manifest.get("questions", [])
    if args.only:
        questions = [q for q in questions if q["question"] in set(args.only)]
    if not questions:
        print("ERROR: no questions selected.", file=sys.stderr)
        return 1

    from ml.pose_estimator import PoseEstimator
    from ml.pose_analyzer import PoseAnalyzer

    print(f"{'=' * 60}")
    print("  FIE referee exam — foil priority evaluation")
    print(f"{'=' * 60}")
    print(f"  Manifest:     {manifest_path}")
    print(f"  Source:       {manifest.get('source')}")
    print(f"  Questions:    {len(questions)}")
    print(f"  Sample every: {args.sample_every}")
    print(
        f"  Pose:         conf={args.pose_confidence} max_det={args.max_det} "
        f"select={args.select} kp_conf={POSE_KEYPOINT_CONFIDENCE}"
    )
    print(f"  Exchange:     {args.exchange}")
    print(f"{'=' * 60}\n")

    estimator = PoseEstimator(
        confidence=args.pose_confidence,
        max_det=(args.max_det if args.select == "largest" else 2),
    )

    rows = []
    for q in questions:
        clip_path = clip_dir / q["clip"]
        if not clip_path.exists():
            print(f"  q{q['question']:02d}: MISSING {clip_path}")
            continue
        row = evaluate_question(
            clip_path, q.get("answer"), q["question"], args,
            estimator, PoseAnalyzer,
        )
        rows.append(row)
        print(
            f"  q{row['question']:02d} → {str(row['verdict'] or 'unknown'):<8}"
            f"(answer {row['answer']}, {row['reason']}, "
            f"{row['exchanges_detected']} exchange(s), "
            f"pose {row['pose_quality']['two_fencer_rate']:.2f}, "
            f"{row['analysis_sec']}s)"
        )

    summary = summarise(rows)
    print("\n" + format_table(rows))
    print(
        f"\n  Accuracy: {summary['correct']}/{summary['questions']} "
        f"({summary['accuracy_over_all'] * 100:.0f}%) over all questions; "
        f"{summary['correct']}/{summary['calls_made']} "
        f"({(summary['accuracy_over_calls'] or 0) * 100:.0f}%) over calls made."
    )
    print(f"  Unknown:  {summary['unknown']}  {summary['decline_reasons']}")
    print(
        f"  Majority-class baseline: "
        f"{summary['majority_class_baseline'] * 100:.0f}% "
        f"(answers {summary['answer_distribution']}); "
        f"judge answered {summary['verdict_distribution']}"
    )

    out_path = Path(args.out) if args.out else (
        clip_dir / f"{manifest_path.stem.replace('_manifest', '')}_eval_result.json"
    )
    out_path.write_text(
        json.dumps(
            {
                "manifest": str(manifest_path),
                "source": manifest.get("source"),
                "settings": {
                    "sample_every": args.sample_every,
                    "pose_confidence": args.pose_confidence,
                    "max_det": args.max_det,
                    "select": args.select,
                    "exchange": args.exchange,
                },
                "summary": summary,
                "table": format_table(rows),
                "questions": rows,
            },
            indent=2, ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\n  wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
