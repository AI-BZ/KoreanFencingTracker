#!/usr/bin/env python3
"""Measure and tune :class:`FoilPriorityJudge` against referee-derived labels.

Ground truth comes from the scoring box, not from a human watching clips. In
foil a *double* lamp means both fencers landed a valid hit, so the referee had
to apply priority to award the point — the scorer is therefore the priority
holder, recorded by the referee at full speed with the blades visible. A single
lamp means no priority ruling was ever made, so those touches carry no label at
all and are excluded rather than guessed at.

That gives a small, honest sample. Two things follow, and both are printed:

* **The majority-class baseline is high.** Answering "left" every time already
  scores well above chance on this data. An accuracy figure that is not shown
  next to that baseline is not evidence of anything.
* **Tuning accuracy is not generalisation.** A grid search over ~15 labels finds
  thresholds fitted to those 15. Leave-one-out and bout-level holdout are
  therefore reported separately, and the bout-level number is the one that
  predicts behaviour on an unseen bout.

Usage:
    cd services/analytics
    PYTHONPATH=. .venv/bin/python3 scripts/calibrate_foil_priority.py \\
        --bout data/reports/<id>_continuous_report.json,data/labels_priority_<id>.csv \\
        --bout ...
"""

import argparse
import csv
import itertools
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from analyzer.touch_matching import determine_attacker
from ml.weapon_analyzers.foil import (
    FoilPriorityJudge,
    REASON_ESTIMATED,
    compute_session_baselines,
)

#: Only a double lamp carries a priority ruling to be right or wrong about.
LABELLED_LAMP = "double"

#: Grid searched for the shipped thresholds. Deliberately coarse: a finer grid
#: over 15 labels would only fit noise more precisely.
GRID = {
    "clear_margin": [0.05, 0.10, 0.15, 0.20, 0.25, 0.30],
    "min_commit": [0.00, 0.05, 0.10, 0.15, 0.20],
    "stationary_weight": [0.0, 0.3],
    "normalise": [False, True],
    "decision_end_offset_sec": [0.0, 0.3, 0.6],
    "decision_window_sec": [1.5, 2.5],
}

#: Release gate from the design: below this an estimated grade does not ship.
ACCURACY_GATE = 0.75


@dataclass
class Sample:
    """One labelled touch with the exchange the judge would see."""

    bout: str
    touch_number: int
    exchange_number: int
    label: str
    footwork_side: str
    exchange: dict

    @property
    def is_deployment_case(self) -> bool:
        """True when footwork left this unclear — the only case the judge runs on.

        Doubles that footwork already decides are still scored, because they
        carry ground truth and there is no reason to throw information away, but
        they are an easier population than the one the judge actually faces and
        are reported separately.
        """
        return self.footwork_side not in ("left", "right")


def load_bout(report_path: Path, labels_path: Path) -> List[Sample]:
    """Join a report's exchanges to its priority labels."""
    report = json.loads(report_path.read_text())
    exchanges = {e.get("exchange_number"): e for e in report.get("exchanges") or []}
    touches = {t.get("touch_number"): t for t in report.get("touches") or []}
    bout = report_path.stem.replace("_continuous_report", "")

    samples: List[Sample] = []
    with labels_path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("lamp") != LABELLED_LAMP:
                continue
            label = (row.get("priority_attacker") or "").strip()
            if label not in ("left", "right"):
                continue
            number = int(row["touch_number"])
            # The CSV's exchange column can be blank on reports generated before
            # touch→exchange matching existed; fall back to the report itself,
            # which is the same match the judge would be handed at runtime.
            raw = (row.get("exchange_number") or "").strip()
            ex_number = (
                int(raw) if raw
                else touches.get(number, {}).get("matched_exchange_number")
            )
            exchange = exchanges.get(ex_number)
            if exchange is None:
                print(
                    f"  skip {bout} touch {number}: no matched exchange "
                    "(unjudgeable, not a miss)",
                )
                continue
            samples.append(Sample(
                bout=bout,
                touch_number=number,
                exchange_number=ex_number,
                label=label,
                footwork_side=determine_attacker(exchange),
                exchange=exchange,
            ))
    return samples


def build_judges(
    reports: Dict[str, dict],
    fps: float,
    **params,
) -> Dict[str, FoilPriorityJudge]:
    """One judge per bout — baselines are a per-bout property of the fencers."""
    # Constructed directly rather than through build_priority_judge, which
    # honours PRIORITY_ESTIMATION_ENABLED. That flag's value is what this script
    # exists to decide, so measuring through it would be circular.
    return {
        bout: FoilPriorityJudge(
            baselines=compute_session_baselines(report.get("exchanges") or []),
            fps=fps,
            **params,
        )
        for bout, report in reports.items()
    }


@dataclass
class Score:
    """Accuracy plus the two numbers that stop it from being read naively.

    ``majority`` is what "always answer the commoner side" would have scored on
    *exactly the touches this judge chose to call*. Comparing against the
    baseline over the whole sample is not enough: a judge that declines every
    hard touch and calls only easy ones would look good against it.

    ``balanced`` averages the two per-class recalls, so a judge that reaches high
    accuracy by always naming the commoner side scores 50% here regardless of how
    lopsided the sample is.
    """

    judged: int = 0
    correct: int = 0
    per_class: Dict[str, List[int]] = None  # label -> [correct, total]

    def __post_init__(self) -> None:
        if self.per_class is None:
            self.per_class = {"left": [0, 0], "right": [0, 0]}

    @property
    def accuracy(self) -> Optional[float]:
        return None if not self.judged else self.correct / self.judged

    @property
    def majority(self) -> Optional[float]:
        """Score of the trivial rule on the judged subset."""
        if not self.judged:
            return None
        totals = [self.per_class[s][1] for s in ("left", "right")]
        return max(totals) / self.judged

    @property
    def interval(self) -> Optional[Tuple[float, float]]:
        """95% Wilson score interval on the accuracy.

        Reported because the sample is tiny and a bare percentage invites being
        read as precise. Wilson rather than the normal approximation: at n≈10
        with p near 1 the normal interval runs past 100% and understates the
        lower bound, which is the end that decides whether the release gate is
        met.
        """
        if not self.judged:
            return None
        z, n, p = 1.96, self.judged, self.accuracy
        denom = 1 + z * z / n
        centre = (p + z * z / (2 * n)) / denom
        spread = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
        return (max(0.0, centre - spread), min(1.0, centre + spread))

    @property
    def balanced(self) -> Optional[float]:
        recalls = [
            c / t for c, t in
            (self.per_class[s] for s in ("left", "right")) if t
        ]
        return sum(recalls) / len(recalls) if recalls else None

    def add(self, label: str, correct: bool) -> None:
        self.judged += 1
        self.correct += int(correct)
        self.per_class[label][1] += 1
        self.per_class[label][0] += int(correct)

    def merge(self, other: "Score") -> None:
        self.judged += other.judged
        self.correct += other.correct
        for side in ("left", "right"):
            self.per_class[side][0] += other.per_class[side][0]
            self.per_class[side][1] += other.per_class[side][1]


def evaluate(
    samples: Sequence[Sample],
    judges: Dict[str, FoilPriorityJudge],
) -> Tuple[Score, Score, List[dict]]:
    """Score ``samples``; returns (all doubles, deployment subset, per-touch rows)."""
    overall, deployment = Score(), Score()
    rows: List[dict] = []
    for s in samples:
        call = judges[s.bout].judge(s.exchange)
        decided = call.reason == REASON_ESTIMATED
        correct = decided and call.attacker == s.label
        if decided:
            overall.add(s.label, correct)
            if s.is_deployment_case:
                deployment.add(s.label, correct)
        rows.append({
            "bout": s.bout,
            "touch": s.touch_number,
            "exchange": s.exchange_number,
            "label": s.label,
            "footwork": s.footwork_side,
            "called": call.attacker,
            "reason": call.reason,
            "detail": call.detail,
            "correct": correct if decided else None,
        })
    return overall, deployment, rows


def majority_baseline(samples: Sequence[Sample]) -> Tuple[str, float]:
    """The 'always answer the commoner side' rule any judge has to beat."""
    if not samples:
        return ("left", 0.0)
    lefts = sum(1 for s in samples if s.label == "left")
    side = "left" if lefts * 2 >= len(samples) else "right"
    hits = lefts if side == "left" else len(samples) - lefts
    return (side, hits / len(samples))


def grid_search(
    samples: Sequence[Sample],
    reports: Dict[str, dict],
    fps: float,
    gate: float = ACCURACY_GATE,
) -> Optional[dict]:
    """Best parameters on ``samples``: most calls made, subject to the gate.

    Ties on coverage break toward higher accuracy, then toward the larger
    margin — the more conservative setting of the two, which is the right way to
    break a tie that the data cannot.
    """
    best = None
    for values in itertools.product(*GRID.values()):
        params = dict(zip(GRID.keys(), values))
        judges = build_judges(reports, fps, **params)
        overall, _deployment, _rows = evaluate(samples, judges)
        if not overall.judged or overall.accuracy < gate:
            continue
        key = (overall.judged, overall.accuracy, params["clear_margin"])
        if best is None or key > best["key"]:
            best = {"key": key, "params": params, "score": overall}
    return best


def leave_one_out(
    samples: Sequence[Sample],
    reports: Dict[str, dict],
    fps: float,
) -> Score:
    """Tune on every sample but one, then judge that one. Repeat."""
    score = Score()
    for i, held in enumerate(samples):
        rest = [s for j, s in enumerate(samples) if j != i]
        best = grid_search(rest, reports, fps)
        if best is None:
            continue
        judges = build_judges(reports, fps, **best["params"])
        overall, _dep, _rows = evaluate([held], judges)
        score.merge(overall)
    return score


def bout_holdout(
    samples: Sequence[Sample],
    reports: Dict[str, dict],
    fps: float,
) -> List[dict]:
    """Tune on all bouts but one, evaluate on the held-out bout.

    Stricter than leave-one-out and closer to the real question: the thresholds
    that ship will meet bouts whose fencers, camera and referee were never in the
    tuning set. Leave-one-out still lets a bout's own touches set its thresholds.
    """
    bouts = sorted({s.bout for s in samples})
    results = []
    for held in bouts:
        train = [s for s in samples if s.bout != held]
        test = [s for s in samples if s.bout == held]
        best = grid_search(train, reports, fps)
        if best is None:
            results.append({"bout": held, "params": None, "score": Score(), "n": len(test)})
            continue
        judges = build_judges(reports, fps, **best["params"])
        overall, deployment, _rows = evaluate(test, judges)
        results.append({
            "bout": held,
            "params": best["params"],
            "score": overall,
            "deployment": deployment,
            "n": len(test),
        })
    return results


def _pct(score: Score) -> str:
    if not score.judged:
        return "n/a (no calls made)"
    left_c, left_n = score.per_class["left"]
    right_c, right_n = score.per_class["right"]
    lo, hi = score.interval
    return (
        f"{score.correct}/{score.judged} = {score.accuracy:.0%}"
        f"  [95% CI {lo:.0%}-{hi:.0%}]"
        f"  (majority rule on the same touches: {score.majority:.0%}"
        f" | balanced {score.balanced:.0%}"
        f" | left {left_c}/{left_n}, right {right_c}/{right_n})"
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bout", action="append", required=True, metavar="REPORT,LABELS",
        help="comma-separated continuous report and priority label CSV",
    )
    parser.add_argument("--fps", type=float, default=29.97)
    parser.add_argument(
        "--json-out", default=None,
        help="write the per-touch decision table here",
    )
    args = parser.parse_args(argv)

    samples: List[Sample] = []
    reports: Dict[str, dict] = {}
    for spec in args.bout:
        report_path, labels_path = (Path(p) for p in spec.split(",", 1))
        if not report_path.exists() or not labels_path.exists():
            print(f"ERROR: missing {report_path} or {labels_path}")
            return 1
        reports[report_path.stem.replace("_continuous_report", "")] = json.loads(
            report_path.read_text(),
        )
        samples.extend(load_bout(report_path, labels_path))

    if not samples:
        print("No double-lamp labels found — nothing to calibrate against.")
        return 1

    side, baseline = majority_baseline(samples)
    deployment = [s for s in samples if s.is_deployment_case]
    dep_side, dep_baseline = majority_baseline(deployment)

    print(f"\n{'='*66}")
    print("  Sample")
    print(f"{'='*66}")
    for bout in sorted({s.bout for s in samples}):
        rows = [s for s in samples if s.bout == bout]
        left = sum(1 for s in rows if s.label == "left")
        print(f"  {bout}: {len(rows)} labelled (left {left}, right {len(rows)-left})")
    print(f"  total: {len(samples)}  |  footwork-unclear subset: {len(deployment)}")
    print(f"  majority baseline (always {side}): {baseline:.0%}")
    if deployment:
        print(
            f"  majority baseline on the deployment subset "
            f"(always {dep_side}): {dep_baseline:.0%}",
        )

    print(f"\n{'='*66}")
    print("  Default thresholds (analyzer/config.py, untuned)")
    print(f"{'='*66}")
    judges = build_judges(reports, args.fps)
    overall, dep, rows = evaluate(samples, judges)
    print(f"  all doubles:        {_pct(overall)}")
    print(f"  deployment subset:  {_pct(dep)}")

    print(f"\n{'='*66}")
    print(f"  Grid search (tuning accuracy — fitted to these {len(samples)} labels)")
    print(f"{'='*66}")
    cells = 1
    for values in GRID.values():
        cells *= len(values)
    passing = 0
    beats_majority = 0
    for values in itertools.product(*GRID.values()):
        params = dict(zip(GRID.keys(), values))
        overall, _d, _r = evaluate(samples, build_judges(reports, args.fps, **params))
        if overall.judged and overall.accuracy >= ACCURACY_GATE:
            passing += 1
            if overall.accuracy > overall.majority:
                beats_majority += 1
    print(
        f"  {cells} parameter combinations searched against {len(samples)} labels.",
    )
    print(
        f"  {passing} clear the {ACCURACY_GATE:.0%} gate; "
        f"{beats_majority} of those also beat the majority rule on their own calls.",
    )
    if passing and not beats_majority:
        print(
            "  → every passing combination is matched or beaten by answering the "
            "commoner side, so the gate is being cleared by the class imbalance, "
            "not by the signal.",
        )

    best = grid_search(samples, reports, args.fps)
    if best is None:
        print(f"  No parameter set reaches the {ACCURACY_GATE:.0%} gate on any call.")
    else:
        print(f"  best params: {best['params']}")
        tuned_judges = build_judges(reports, args.fps, **best["params"])
        t_overall, t_dep, rows = evaluate(samples, tuned_judges)
        print(f"  all doubles:        {_pct(t_overall)}")
        print(f"  deployment subset:  {_pct(t_dep)}")

    print(f"\n{'='*66}")
    print("  Generalisation")
    print(f"{'='*66}")
    loo = leave_one_out(samples, reports, args.fps)
    print(f"  leave-one-out:      {_pct(loo)}")
    pooled = Score()
    for res in bout_holdout(samples, reports, args.fps):
        params = res["params"]
        pooled.merge(res["score"])
        print(
            f"  holdout {res['bout']} (n={res['n']}): {_pct(res['score'])}"
            f"   [tuned elsewhere → {params}]",
        )
    print(f"  POOLED cross-bout:  {_pct(pooled)}")

    # Separates two failure modes that the holdout numbers above conflate.
    # Re-tuning per fold measures whether *threshold selection* is stable; the
    # single shipped setting measures whether *one fixed setting* works on every
    # bout. They can disagree, and only the first is a reason not to ship.
    print()
    print("  One fixed setting (the shipped config) per bout:")
    fixed = build_judges(reports, args.fps)
    for bout in sorted({s.bout for s in samples}):
        overall, _d, _r = evaluate([s for s in samples if s.bout == bout], fixed)
        print(f"    {bout}: {_pct(overall)}")

    print(f"\n{'='*66}")
    print("  Per-touch decisions (default thresholds unless tuned above)")
    print(f"{'='*66}")
    print(f"  {'bout':<34} {'t':>3} {'ex':>4} {'label':<6} {'footwork':<8} "
          f"{'called':<7} {'reason':<13} {'margin':>7} {'ok'}")
    for r in rows:
        detail = r["detail"] or {}
        margin = detail.get("margin")
        print(
            f"  {r['bout'][:34]:<34} {r['touch']:>3} {r['exchange']:>4} "
            f"{r['label']:<6} {r['footwork']:<8} {str(r['called']):<7} "
            f"{r['reason']:<13} {'' if margin is None else f'{margin:.3f}':>7} "
            f"{'' if r['correct'] is None else ('Y' if r['correct'] else 'N')}",
        )

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        print(f"\n  decision table → {args.json_out}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
