#!/usr/bin/env python3
"""
Bootstrap training data for FACTS VideoMAE fine-tuning.

Pipeline orchestrator that chains:
1. Download video (YouTube or local)
2. Auto-detect ROIs (ScoreboardDetector)
3. Extract clips at touch events (ClipCutter)
4. Label scorers (AutoLabeler → L/R/T/X)
5. Classify actions (ActionHeuristicLabeler → FACTS 8-class)
6. Organize into FACTS directory structure
7. Optionally augment with horizontal flips

Usage:
    # From local video
    python -m scripts.bootstrap_training_data --video /path/to/match.mp4

    # From YouTube URL
    python -m scripts.bootstrap_training_data --url "https://youtube.com/watch?v=..."

    # Batch from file list
    python -m scripts.bootstrap_training_data --list videos.txt --output data/bootstrap_facts/
"""

import argparse
import shutil
import sys
from pathlib import Path
from typing import Optional, List

# Ensure project root is importable
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def download_video(url: str, output_dir: Path) -> Optional[Path]:
    """Download a video from YouTube using yt-dlp."""
    from pipeline.downloader import download_video as _download
    try:
        path = _download(url, str(output_dir))
        return Path(path) if path else None
    except Exception as e:
        print(f"  [ERROR] Download failed: {e}")
        return None


def detect_rois(video_path: Path) -> Optional[dict]:
    """Auto-detect scoreboard ROIs."""
    from analyzer.scoreboard_detector import ScoreboardDetector
    detector = ScoreboardDetector()
    rois = detector.detect_from_video(str(video_path))
    if rois:
        print(f"  [OK] ROIs detected: {list(rois.keys())}")
    else:
        print("  [WARN] No scoreboard detected — skipping clip extraction")
    return rois


def extract_clips(video_path: Path, rois: dict, output_dir: Path) -> List[Path]:
    """Extract clips at touch events using ClipCutter."""
    from pipeline.clip_cutter import ClipCutter
    clip_dir = output_dir / "clips"
    clip_dir.mkdir(parents=True, exist_ok=True)

    cutter = ClipCutter(rois=rois)
    clips = cutter.cut_clips(str(video_path), str(clip_dir))
    print(f"  [OK] Extracted {len(clips)} clips")
    return [Path(c) for c in clips]


def label_scorers(clip_dir: Path, rois: dict, output_dir: Path) -> list:
    """Label clips by scorer (L/R/T/X)."""
    from pipeline.auto_labeler import AutoLabeler
    labeled_dir = output_dir / "labeled"
    labeled_dir.mkdir(parents=True, exist_ok=True)

    labeler = AutoLabeler(rois=rois)
    results = labeler.label_clips(str(clip_dir), str(labeled_dir))
    return results


def classify_actions(labeled_clips: list, fps: float = 30.0) -> list:
    """
    Convert L/R/T labels to FACTS 8-class labels using heuristics.

    Args:
        labeled_clips: List of LabeledClip from AutoLabeler.
        fps: Video FPS for time estimation.

    Returns:
        List of (clip_path, facts_label, confidence) tuples.
    """
    from pipeline.action_heuristic_labeler import (
        ActionHeuristicLabeler, TouchEvent,
    )

    # Convert labeled clips to touch events with estimated timestamps
    touches = []
    for i, clip in enumerate(labeled_clips):
        # Estimate timestamp from clip index (rough, ~5s per clip as heuristic)
        est_time = i * 5.0
        touches.append(TouchEvent(
            timestamp_sec=est_time,
            scorer=clip.label,
            lamp_state=clip.lamp_state,
            clip_path=str(clip.clip_path),
        ))

    labeler = ActionHeuristicLabeler()
    actions = labeler.label_sequence(touches)

    results = []
    for action in actions:
        results.append((
            action.touch.clip_path,
            action.action,
            action.confidence,
        ))

    return results


def organize_facts_dirs(
    action_results: list,
    output_dir: Path,
) -> dict:
    """
    Organize clips into FACTS directory structure.

    Structure:
        output_dir/
            AL/   (attack_left)
            AR/   (attack_right)
            RL/   (riposte_left)
            ...
    """
    from pipeline.action_heuristic_labeler import FACTS_DIR_MAP

    # Create all FACTS directories
    for dir_code in FACTS_DIR_MAP.values():
        (output_dir / dir_code).mkdir(parents=True, exist_ok=True)

    stats = {}
    for clip_path, action_label, confidence in action_results:
        dir_code = FACTS_DIR_MAP.get(action_label)
        if not dir_code:
            continue

        src = Path(clip_path)
        if not src.exists():
            continue

        dest = output_dir / dir_code / src.name
        shutil.copy2(src, dest)

        stats[dir_code] = stats.get(dir_code, 0) + 1

    return stats


def augment_data(facts_dir: Path) -> int:
    """Apply horizontal flip augmentation to double the dataset."""
    from pipeline.data_augmentor import DataAugmentor
    augmentor = DataAugmentor()
    count = augmentor.augment_directory(str(facts_dir))
    print(f"  [OK] Augmented: {count} new clips created")
    return count


def bootstrap_single_video(
    video_path: Path,
    output_dir: Path,
    augment: bool = True,
) -> dict:
    """
    Run full bootstrap pipeline on a single video.

    Returns:
        Stats dict with counts per FACTS class.
    """
    print(f"\n{'='*60}")
    print(f"Processing: {video_path.name}")
    print(f"{'='*60}")

    # Step 1: Detect ROIs
    rois = detect_rois(video_path)
    if rois is None:
        return {}

    # Step 2: Extract clips
    work_dir = output_dir / "work" / video_path.stem
    work_dir.mkdir(parents=True, exist_ok=True)
    clips = extract_clips(video_path, rois, work_dir)
    if not clips:
        return {}

    # Step 3: Label scorers
    labeled_clips = label_scorers(work_dir / "clips", rois, work_dir)
    if not labeled_clips:
        print("  [WARN] No clips labeled — skipping")
        return {}

    # Step 4: Classify actions
    action_results = classify_actions(labeled_clips)
    print(f"  [OK] Classified {len(action_results)} actions")

    # Step 5: Organize into FACTS dirs
    facts_dir = output_dir / "facts"
    stats = organize_facts_dirs(action_results, facts_dir)
    print(f"  [OK] Organized into FACTS: {stats}")

    # Step 6: Augment (optional)
    if augment:
        augment_data(facts_dir)

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Bootstrap FACTS training data from fencing videos"
    )
    parser.add_argument("--video", type=str, help="Local video file path")
    parser.add_argument("--url", type=str, help="YouTube URL to download")
    parser.add_argument("--list", type=str, help="Text file with video paths/URLs (one per line)")
    parser.add_argument(
        "--output", type=str, default="data/bootstrap_facts",
        help="Output directory (default: data/bootstrap_facts/)"
    )
    parser.add_argument("--no-augment", action="store_true", help="Skip augmentation")

    args = parser.parse_args()
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    videos: List[Path] = []

    if args.video:
        p = Path(args.video)
        if not p.exists():
            print(f"ERROR: Video not found: {args.video}")
            sys.exit(1)
        videos.append(p)

    elif args.url:
        dl_dir = output_dir / "downloads"
        dl_dir.mkdir(parents=True, exist_ok=True)
        downloaded = download_video(args.url, dl_dir)
        if downloaded:
            videos.append(downloaded)
        else:
            sys.exit(1)

    elif args.list:
        list_file = Path(args.list)
        if not list_file.exists():
            print(f"ERROR: List file not found: {args.list}")
            sys.exit(1)
        for line in list_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("http"):
                dl_dir = output_dir / "downloads"
                dl_dir.mkdir(parents=True, exist_ok=True)
                downloaded = download_video(line, dl_dir)
                if downloaded:
                    videos.append(downloaded)
            else:
                p = Path(line)
                if p.exists():
                    videos.append(p)
                else:
                    print(f"  [WARN] Skipping missing file: {line}")
    else:
        parser.print_help()
        sys.exit(1)

    # Process all videos
    total_stats: dict = {}
    for video in videos:
        stats = bootstrap_single_video(video, output_dir, augment=not args.no_augment)
        for k, v in stats.items():
            total_stats[k] = total_stats.get(k, 0) + v

    # Summary
    print(f"\n{'='*60}")
    print("BOOTSTRAP COMPLETE")
    print(f"{'='*60}")
    print(f"Videos processed: {len(videos)}")
    print(f"FACTS directory: {output_dir / 'facts'}")
    print(f"Class distribution: {total_stats}")
    total_clips = sum(total_stats.values())
    print(f"Total clips: {total_clips}")

    if total_clips > 0:
        print("\nNext step: Fine-tune VideoMAE")
        print(f"  PYTHONPATH=. python3 -m ml.training.train_videomae \\")
        print(f"    --dataset-format facts --data-dir {output_dir / 'facts'} \\")
        print(f"    --epochs 10 --batch-size 4 --grad-accum 2")


if __name__ == "__main__":
    main()
