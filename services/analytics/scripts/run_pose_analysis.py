"""
Batch pose analysis for fencing action clips.

Runs YOLO11-Pose → PoseAnalyzer on each clip to produce:
- Footwork classification (lunge, fleche, advance, retreat, stationary)
- Parry detection (blade deflection)
- Distance measurement (Body Height units)
- Suggested action label
- Joint angles (hip, knee, trunk lean, arm extension)  [Phase 6]
- Continuous analysis (exchange detection, non-scoring events)  [Phase 6]

Usage:
    PYTHONPATH=. .venv/bin/python3 scripts/run_pose_analysis.py
    PYTHONPATH=. .venv/bin/python3 scripts/run_pose_analysis.py --clips-dir data/clips
    PYTHONPATH=. .venv/bin/python3 scripts/run_pose_analysis.py --output data/labeled/pose_analysis_results.json
    PYTHONPATH=. .venv/bin/python3 scripts/run_pose_analysis.py --max-clips 10  # test run
    PYTHONPATH=. .venv/bin/python3 scripts/run_pose_analysis.py --continuous --my-fencer left
"""

import argparse
import csv
import json
import sys
import time
from pathlib import Path

try:
    import cv2
except ImportError:
    print("ERROR: opencv-python required. Install: pip install opencv-python")
    sys.exit(1)


def parse_scorer_from_filename(filename: str) -> str | None:
    """Extract scorer direction from clip filename convention.

    Expected: touch_XXXX_left.mp4 or touch_XXXX_right.mp4
    """
    name = Path(filename).stem.lower()
    if "left" in name:
        return "left"
    elif "right" in name:
        return "right"
    return None


def load_scorer_from_labels(labels_csv: Path) -> dict[str, str]:
    """Load scorer direction from labels.csv (heuristic or reviewed).

    Extracts direction from action_label suffix: attack_left → "left".
    Returns dict of filename → scorer direction.
    """
    scorer_map: dict[str, str] = {}
    if not labels_csv.exists():
        return scorer_map

    with open(labels_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            clip_path = row.get("clip_path", "")
            action_label = row.get("action_label", "")
            filename = Path(clip_path).name

            # Extract direction from label suffix
            if action_label.endswith("_left"):
                scorer_map[filename] = "left"
            elif action_label.endswith("_right"):
                scorer_map[filename] = "right"

    return scorer_map


def analyze_clip(
    clip_path: Path,
    pose_estimator,
    pose_analyzer,
    scorer_override: str | None = None,
    my_fencer: str | None = None,
    continuous: bool = False,
    sample_every_n: int = 5,
) -> dict | None:
    """Run pose analysis on a single clip.

    Args:
        clip_path: Path to clip video file.
        pose_estimator: PoseEstimator instance.
        pose_analyzer: PoseAnalyzer instance.
        scorer_override: Scorer direction from labels.csv (overrides filename parsing).
        my_fencer: Fencer side for perspective analysis ("left" or "right").
        continuous: If True, run continuous exchange analysis on the clip.
        sample_every_n: Frame sampling interval for continuous analysis.

    Returns dict with analysis results or None on failure.
    """
    cap = cv2.VideoCapture(str(clip_path))
    if not cap.isOpened():
        return None

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    pose_analyzer.fps = fps

    # Extract all frames
    frames = []
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frames.append(frame)
    cap.release()

    if not frames:
        return None

    # Run pose estimation on all frames
    pose_results = pose_estimator.estimate_poses_batch(frames)

    # Determine scorer: labels.csv override > filename parsing
    scorer = scorer_override or parse_scorer_from_filename(clip_path.name)

    # Run pose analyzer (touch-moment analysis)
    result = pose_analyzer.analyze(
        pose_sequence=pose_results,
        scorer=scorer,
        my_fencer=my_fencer,
    )

    # Build output dict
    output = result.to_dict()
    output["filename"] = clip_path.name
    output["n_frames"] = len(frames)
    output["fps"] = fps
    output["scorer"] = scorer
    output["scorer_source"] = "labels_csv" if scorer_override else ("filename" if scorer else "none")

    # Continuous analysis (exchange detection)
    if continuous:
        continuous_result = pose_analyzer.analyze_continuous(
            pose_sequence=pose_results,
            sample_every_n=sample_every_n,
            my_fencer=my_fencer,
        )
        output["continuous"] = continuous_result.to_dict()

    return output


def main():
    parser = argparse.ArgumentParser(description="Batch pose analysis for fencing clips")
    parser.add_argument(
        "--clips-dir", type=str, default="data/clips",
        help="Directory containing clip videos",
    )
    parser.add_argument(
        "--output", type=str, default="data/labeled/pose_analysis_results.json",
        help="Output JSON file path",
    )
    parser.add_argument(
        "--max-clips", type=int, default=0,
        help="Max clips to process (0 = all)",
    )
    parser.add_argument(
        "--labels-csv", type=str, default="data/labeled/labels.csv",
        help="Labels CSV with scorer direction (clip_path,action_label)",
    )
    parser.add_argument(
        "--continuous", action="store_true",
        help="Enable continuous exchange analysis (full-bout, not just touch moments)",
    )
    parser.add_argument(
        "--my-fencer", type=str, default=None, choices=["left", "right"],
        help="Fencer side for perspective analysis (generates narratives)",
    )
    parser.add_argument(
        "--sample-every", type=int, default=5,
        help="Frame sampling interval for continuous analysis (default: 5)",
    )
    args = parser.parse_args()

    clips_dir = Path(args.clips_dir)
    output_path = Path(args.output)
    labels_csv = Path(args.labels_csv)

    if not clips_dir.exists():
        print(f"ERROR: Clips directory not found: {clips_dir}")
        sys.exit(1)

    # Load scorer directions from labels CSV
    scorer_map = load_scorer_from_labels(labels_csv)

    # Find clip files
    clip_files = sorted(
        [f for f in clips_dir.iterdir() if f.suffix.lower() in (".mp4", ".avi", ".mov")]
    )
    if args.max_clips > 0:
        clip_files = clip_files[:args.max_clips]

    scorer_matched = sum(1 for f in clip_files if f.name in scorer_map)

    print(f"\n{'='*60}")
    print(f"  Pose Analysis — Batch Processing")
    print(f"{'='*60}")
    print(f"  Clips dir:   {clips_dir}")
    print(f"  Total clips: {len(clip_files)}")
    print(f"  Labels CSV:  {labels_csv} ({'found' if labels_csv.exists() else 'not found'})")
    print(f"  Scorer info: {scorer_matched}/{len(clip_files)} clips matched")
    print(f"  Continuous:  {'YES' if args.continuous else 'no'}")
    print(f"  My fencer:   {args.my_fencer or 'none'}")
    if args.continuous:
        print(f"  Sample rate: every {args.sample_every} frames")
    print(f"  Output:      {output_path}")
    print(f"{'='*60}\n")

    if not clip_files:
        print("No clips found.")
        return

    # Initialize models
    from ml.pose_estimator import PoseEstimator
    from ml.pose_analyzer import PoseAnalyzer

    print("Loading YOLO11-Pose model...")
    estimator = PoseEstimator()
    analyzer = PoseAnalyzer()

    results = {}
    t0 = time.time()

    for i, clip_path in enumerate(clip_files):
        pct = (i + 1) / len(clip_files) * 100
        print(f"  [{i+1}/{len(clip_files)}] ({pct:.1f}%) {clip_path.name}...", end=" ", flush=True)

        t_clip = time.time()
        scorer = scorer_map.get(clip_path.name)
        result = analyze_clip(
            clip_path, estimator, analyzer,
            scorer_override=scorer,
            my_fencer=args.my_fencer,
            continuous=args.continuous,
            sample_every_n=args.sample_every,
        )

        if result is not None:
            results[clip_path.name] = result
            label = result.get("suggested_label", "?")
            conf = result.get("suggestion_confidence", 0)
            elapsed = time.time() - t_clip
            print(f"→ {label} ({conf:.0%}) [{elapsed:.1f}s]")
        else:
            print("→ FAILED")

    elapsed_total = time.time() - t0

    # Save results
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # Summary
    print(f"\n{'='*60}")
    print(f"  Completed: {len(results)}/{len(clip_files)} clips")
    print(f"  Time:      {elapsed_total:.1f}s ({elapsed_total/max(len(clip_files),1):.1f}s/clip)")
    print(f"  Output:    {output_path}")

    # Label distribution
    from collections import Counter
    labels = Counter(r.get("suggested_label", "unknown") for r in results.values())
    print(f"\n  Label distribution:")
    for label, count in sorted(labels.items()):
        print(f"    {label}: {count}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
