"""
Generate phrase boundary annotated dataset from continuous analysis reports.

Reads all *_continuous_report.json files in the specified directory and
produces a phrase boundary annotation dataset for future ML training.

Usage:
    cd services/analytics
    PYTHONPATH=. .venv/bin/python3 scripts/generate_phrase_dataset.py data/reports/
    PYTHONPATH=. .venv/bin/python3 scripts/generate_phrase_dataset.py data/reports/ --output data/datasets/phrase_boundaries.json
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from analyzer.config import EXCHANGE_MERGE_SEPARATION_FRAMES
from analyzer.models import PhraseAnnotation


def _frame_to_time(frame: int, fps: float = 30.0) -> str:
    """Convert frame number to M:SS string."""
    seconds = frame / fps
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}:{s:02d}"


def _merge_short_separations(
    exchanges: List[dict],
    merge_frames: int,
) -> List[dict]:
    """Merge exchanges separated by short gaps into single phrases.

    If two consecutive exchanges have a gap smaller than merge_frames,
    they are combined into one phrase spanning both.
    """
    if not exchanges:
        return []

    merged: List[dict] = [exchanges[0].copy()]
    for ex in exchanges[1:]:
        prev = merged[-1]
        gap = ex["start_frame"] - prev["end_frame"]
        if gap <= merge_frames:
            # Merge into previous
            prev["end_frame"] = ex["end_frame"]
            prev["end_time"] = ex.get("end_time", "")
            # Keep min distance of the closer approach
            if ex.get("min_distance_bh", 99) < prev.get("min_distance_bh", 99):
                prev["min_distance_bh"] = ex["min_distance_bh"]
            # Combine footwork / event types for action sequence
            prev.setdefault("_merged_events", [prev.get("event_type", "")])
            prev["_merged_events"].append(ex.get("event_type", ""))
            prev.setdefault("_merged_footworks", [])
            for side in ("footwork_left", "footwork_right"):
                fw = ex.get(side)
                if fw and fw != "unknown":
                    prev["_merged_footworks"].append(fw)
        else:
            merged.append(ex.copy())

    return merged


def _determine_outcome(
    phrase: dict,
    scoring_frames: set,
    fps: float = 30.0,
    tolerance_frames: int = 90,  # 3 seconds at 30fps
) -> str:
    """Determine phrase outcome based on scoring frames proximity."""
    if not scoring_frames:
        return "halt"

    start = phrase["start_frame"]
    end = phrase["end_frame"]

    # Check if any scoring frame falls within or near this phrase
    for sf in scoring_frames:
        if start - tolerance_frames <= sf <= end + tolerance_frames:
            # Determine which side scored based on touch data (if available)
            scorer = phrase.get("_scorer")
            if scorer == "left":
                return "touch_left"
            elif scorer == "right":
                return "touch_right"
            return "touch_left"  # default if scorer unknown

    return "halt"


def _build_action_sequence(phrase: dict) -> List[str]:
    """Build action sequence from merged exchange data."""
    sequence: List[str] = []

    # Use merged footworks if available
    merged_fws = phrase.get("_merged_footworks", [])
    if merged_fws:
        sequence.extend(merged_fws)

    # Add primary footwork from the phrase itself
    for side in ("footwork_left", "footwork_right"):
        fw = phrase.get(side)
        if fw and fw != "unknown" and fw not in sequence:
            sequence.append(fw)

    # Map event type to action
    event_type = phrase.get("event_type", "")
    merged_events = phrase.get("_merged_events", [event_type])
    for evt in merged_events:
        if evt == "failed_attack" and "attack" not in sequence:
            sequence.append("attack")
        elif evt == "successful_defense" and "defense" not in sequence:
            sequence.append("defense")

    # Add parry if detected
    if phrase.get("parry_left") or phrase.get("parry_right"):
        if "parade" not in sequence:
            sequence.append("parade")

    return sequence if sequence else ["unknown"]


def _compute_confidence(phrase: dict, has_ocr: bool, has_clock: bool) -> float:
    """Compute annotation confidence based on available data sources."""
    base = 0.3  # distance-based detection baseline

    # Scoring data adds confidence
    if has_ocr:
        base += 0.3

    # Clock data adds confidence
    if has_clock:
        base += 0.2

    # Footwork data adds confidence
    has_fw = False
    for side in ("footwork_left", "footwork_right"):
        fw = phrase.get(side)
        if fw and fw != "unknown":
            has_fw = True
    if has_fw:
        base += 0.1

    # Short phrases are less reliable
    duration_frames = phrase["end_frame"] - phrase["start_frame"]
    if duration_frames < 10:
        base -= 0.1

    return min(max(base, 0.1), 1.0)


def process_report(
    report_path: Path,
    fps: float = 30.0,
) -> List[PhraseAnnotation]:
    """Process a single continuous report into phrase annotations."""
    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    # Extract video ID from filename
    video_id = report_path.stem.replace("_continuous_report", "")

    exchanges = report.get("exchanges", [])
    if not exchanges:
        return []

    touches = report.get("touches", [])
    has_ocr = len(touches) > 0

    # Build scoring frames set from OCR touches
    scoring_frames: set = set()
    touch_scorer_map: dict = {}  # frame -> scorer
    for t in touches:
        frame = t.get("frame", 0)
        scoring_frames.add(frame)
        touch_scorer_map[frame] = t.get("scorer", "unknown")

    # Check for clock events (from OCR report metadata)
    has_clock = report.get("meta", {}).get("ocr_source") is not None

    # Merge short separations
    merged = _merge_short_separations(
        exchanges,
        merge_frames=EXCHANGE_MERGE_SEPARATION_FRAMES * 3,  # 3x config for phrase-level merge
    )

    # Annotate scorer for merged phrases near scoring frames
    tolerance = int(fps * 3)  # 3 seconds
    for phrase in merged:
        for sf, scorer in touch_scorer_map.items():
            if phrase["start_frame"] - tolerance <= sf <= phrase["end_frame"] + tolerance:
                phrase["_scorer"] = scorer
                break

    # Generate annotations
    annotations: List[PhraseAnnotation] = []
    for i, phrase in enumerate(merged, 1):
        outcome = _determine_outcome(phrase, scoring_frames, fps)
        action_seq = _build_action_sequence(phrase)
        confidence = _compute_confidence(phrase, has_ocr, has_clock)

        trigger = "distance"  # default: distance-based detection
        if outcome.startswith("touch_"):
            trigger = "scoring"

        ann = PhraseAnnotation(
            video_id=video_id,
            phrase_id=i,
            start_frame=phrase["start_frame"],
            end_frame=phrase["end_frame"],
            start_time=phrase.get("start_time", _frame_to_time(phrase["start_frame"], fps)),
            end_time=phrase.get("end_time", _frame_to_time(phrase["end_frame"], fps)),
            trigger=trigger,
            outcome=outcome,
            action_sequence=action_seq,
            confidence=round(confidence, 2),
            reviewed=False,
        )
        annotations.append(ann)

    return annotations


def main():
    parser = argparse.ArgumentParser(
        description="Generate phrase boundary annotated dataset from continuous reports",
    )
    parser.add_argument(
        "reports_dir",
        type=str,
        help="Directory containing *_continuous_report.json files",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/datasets/phrase_boundaries.json",
        help="Output path for dataset JSON (default: data/datasets/phrase_boundaries.json)",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=30.0,
        help="Video FPS for time calculations (default: 30.0)",
    )
    args = parser.parse_args()

    reports_dir = Path(args.reports_dir)
    if not reports_dir.exists():
        print(f"ERROR: Directory not found: {reports_dir}")
        sys.exit(1)

    # Find all continuous reports
    report_files = sorted(reports_dir.glob("*_continuous_report.json"))
    if not report_files:
        print(f"No *_continuous_report.json files found in {reports_dir}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  Phrase Boundary Dataset Generator")
    print(f"{'='*60}")
    print(f"  Reports dir: {reports_dir}")
    print(f"  Reports found: {len(report_files)}")
    print(f"  FPS: {args.fps}")
    print(f"{'='*60}\n")

    all_annotations: List[PhraseAnnotation] = []
    video_ids: List[str] = []

    for report_path in report_files:
        print(f"  Processing: {report_path.name}...")
        annotations = process_report(report_path, fps=args.fps)
        all_annotations.extend(annotations)
        if annotations:
            video_ids.append(annotations[0].video_id)
        print(f"    → {len(annotations)} phrases")

    # Build dataset
    dataset = {
        "version": "1.0",
        "generated": datetime.now().strftime("%Y-%m-%d"),
        "total_phrases": len(all_annotations),
        "total_videos": len(video_ids),
        "videos": video_ids,
        "config": {
            "merge_separation_frames": EXCHANGE_MERGE_SEPARATION_FRAMES * 3,
            "fps": args.fps,
        },
        "annotations": [a.to_dict() for a in all_annotations],
    }

    # Compute stats
    outcome_counts: dict = {}
    trigger_counts: dict = {}
    for a in all_annotations:
        outcome_counts[a.outcome] = outcome_counts.get(a.outcome, 0) + 1
        trigger_counts[a.trigger] = trigger_counts.get(a.trigger, 0) + 1
    dataset["stats"] = {
        "outcome_distribution": outcome_counts,
        "trigger_distribution": trigger_counts,
        "avg_confidence": round(
            sum(a.confidence for a in all_annotations) / max(len(all_annotations), 1), 2
        ),
    }

    # Save
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)

    # Print summary
    print(f"\n{'='*60}")
    print(f"  Dataset Generated")
    print(f"{'='*60}")
    print(f"  Output:     {output_path}")
    print(f"  Videos:     {len(video_ids)}")
    print(f"  Phrases:    {len(all_annotations)}")
    print(f"  Avg conf:   {dataset['stats']['avg_confidence']}")
    print(f"  Outcomes:   {outcome_counts}")
    print(f"  Triggers:   {trigger_counts}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
