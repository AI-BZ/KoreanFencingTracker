#!/usr/bin/env python3
"""
Auto-pipeline: Download → OCR → Report → Clips → Labels → Fine-tune

Processes all USA Fencing bout videos from a list through:
1. Download from YouTube (720p)
2. OCR score tracking (TVOverlayOCR + TVScoreTracker)
3. Match report generation (JSON)
4. Clip extraction around touch events (ffmpeg)
5. Heuristic action labeling (FACTS 8-class)
6. labels.csv for VideoMAE training
7. VideoMAE fine-tuning (after all collection)

Resume-capable: tracks progress in data/pipeline_progress.json.
Disk-efficient: deletes raw videos after clip extraction.
"""

import csv
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import cv2

from analyzer.tv_overlay_ocr import TVOverlayOCR, TVScoreTracker
from app.metadata_parser import parse_fencing_metadata
from app.tv_report_converter import tv_ocr_to_match_report
from pipeline.action_heuristic_labeler import (
    ActionHeuristicLabeler,
    TouchEvent as HeuristicTouchEvent,
)
from pipeline.downloader import VideoDownloader

# ── Configuration ──────────────────────────────────────────────────
VIDEO_LIST = "/tmp/usaf_clean.txt"
DATA_DIR = Path("data")
RAW_DIR = DATA_DIR / "raw"
CLIPS_DIR = DATA_DIR / "clips"
REPORTS_DIR = DATA_DIR / "reports"
PROGRESS_FILE = DATA_DIR / "pipeline_progress.json"
PIPELINE_LABELS = DATA_DIR / "labels.csv"
# FencingActionDataset reads from this hardcoded path (ml/training/config.py)
TRAINING_LABELS = DATA_DIR / "labeled" / "labels.csv"

SAMPLE_INTERVAL = 30  # Every 30 frames (~1fps OCR at 30fps video)
CLIP_BEFORE_SEC = 3.0
CLIP_AFTER_SEC = 3.0
MIN_CLIPS_FOR_TRAINING = 100


# ── Video list parser ──────────────────────────────────────────────
def parse_video_list(path: str) -> list:
    """Parse usaf_clean.txt → [{id, title, duration}, ...]."""
    videos = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            video_id = parts[0]
            try:
                duration = float(parts[-1])
            except ValueError:
                duration = 0
            title = " ".join(parts[1:-1])
            videos.append({"id": video_id, "title": title, "duration": duration})
    return videos


# ── Progress tracking ──────────────────────────────────────────────
def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {
        "processed": {},
        "failed": {},
        "stats": {
            "total_videos": 0,
            "total_touches": 0,
            "total_clips": 0,
            "total_labels": 0,
        },
    }


def save_progress(progress: dict):
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2, default=str)


# ── OCR scan ───────────────────────────────────────────────────────
def scan_video_ocr(video_path: str) -> tuple:
    """Run OCR scan → (events, summary, fps, total_frames, ocr_rate).

    Uses frame seeking (cap.set) instead of reading every frame to avoid
    the massive overhead of decoding frames we don't need.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return [], {}, 30.0, 0, 0.0

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    ocr = TVOverlayOCR(layout="usa_fencing")
    tracker = TVScoreTracker()

    ocr_count = 0
    read_count = 0
    left_names: Counter = Counter()
    right_names: Counter = Counter()
    frame_num = SAMPLE_INTERVAL  # start at first sample point

    while frame_num < total_frames:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        ret, frame = cap.read()
        if not ret:
            break

        data = ocr.read_overlay(frame)
        ocr_count += 1

        if data is not None:
            read_count += 1
            tracker.update(frame_num, data, fps=fps)
            if data.left_name:
                left_names[data.left_name] += 1
            if data.right_name:
                right_names[data.right_name] += 1

        if ocr_count % 200 == 0:
            events_so_far = tracker.get_all_events()
            pct = (frame_num / total_frames) * 100
            print(
                f"    Frame {frame_num}/{total_frames} ({pct:.0f}%): "
                f"{len(events_so_far)} touches, "
                f"reads: {read_count}/{ocr_count}"
            )

        frame_num += SAMPLE_INTERVAL

    cap.release()

    events = tracker.get_all_events()
    summary = tracker.get_match_summary()
    ocr_rate = read_count / ocr_count if ocr_count > 0 else 0.0

    # Inject most common names into summary
    if left_names:
        summary["left_name"] = left_names.most_common(1)[0][0]
    if right_names:
        summary["right_name"] = right_names.most_common(1)[0][0]

    return events, summary, fps, total_frames, ocr_rate


# ── Report generation ──────────────────────────────────────────────
def generate_report(events, summary, metadata, video_path, analysis_time, fps, total_frames):
    """Generate match report dict from OCR events."""
    if not events:
        return None

    left_name = summary.get("left_name", "Left")
    right_name = summary.get("right_name", "Right")

    report = tv_ocr_to_match_report(
        events=events,
        summary=summary,
        left_name=left_name,
        right_name=right_name,
        video_path=str(video_path),
        analysis_time_sec=analysis_time,
        total_frames=total_frames,
        fps=fps,
        expected_final_score=metadata.get("expected_final_score"),
    )

    report["summary"]["weapon"] = metadata.get("weapon", "unknown")
    report["summary"]["gender"] = metadata.get("gender", "unknown")
    report["summary"]["age_group"] = metadata.get("age_group", "unknown")
    report["summary"]["bout_type"] = metadata.get("bout_type", "unknown")

    return report


# ── Clip extraction ────────────────────────────────────────────────
def extract_clips(video_path: str, events: list) -> list:
    """Extract short clips around each touch event using ffmpeg."""
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    video_stem = Path(video_path).stem
    clips = []

    for i, event in enumerate(events):
        ts = event.timestamp
        start = max(0, ts - CLIP_BEFORE_SEC)
        duration = CLIP_BEFORE_SEC + CLIP_AFTER_SEC
        clip_path = CLIPS_DIR / f"{video_stem}_touch{i:04d}.mp4"

        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{start:.3f}",
            "-i", video_path,
            "-t", f"{duration:.3f}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-an",
            str(clip_path),
        ]

        try:
            subprocess.run(
                cmd, capture_output=True, timeout=60, check=True,
            )
            clips.append(clip_path)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass  # Skip failed clips

    return clips


# ── Heuristic labeling ─────────────────────────────────────────────
def label_events(events: list, clips: list) -> list:
    """Apply FACTS 8-class heuristic labels."""
    labeler = ActionHeuristicLabeler()

    heuristic_events = []
    for event in events:
        scorer = "L" if event.scorer == "left" else "R"
        heuristic_events.append(
            HeuristicTouchEvent(
                timestamp_sec=event.timestamp,
                scorer=scorer,
                lamp_state="On-No" if scorer == "L" else "No-On",
            )
        )

    labeled = labeler.label_sequence(heuristic_events)

    results = []
    for i, la in enumerate(labeled):
        clip_path = str(clips[i]) if i < len(clips) else None
        results.append(
            {
                "clip_path": clip_path,
                "action": la.action,
                "confidence": la.confidence,
                "reason": la.reason,
                "timestamp": la.touch.timestamp_sec,
                "scorer": la.touch.scorer,
            }
        )

    return results


# ── CSV writers ────────────────────────────────────────────────────
def append_labels(labels: list, weapon: str = "unknown"):
    """Append to both pipeline labels and training labels CSV."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 1) Pipeline labels (full metadata)
    pipe_fields = [
        "clip_path", "action", "confidence", "reason",
        "timestamp", "scorer", "weapon",
    ]
    pipe_exists = PIPELINE_LABELS.exists()
    with open(PIPELINE_LABELS, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=pipe_fields)
        if not pipe_exists:
            w.writeheader()
        for row in labels:
            w.writerow(
                {
                    "clip_path": row["clip_path"],
                    "action": row["action"],
                    "confidence": row["confidence"],
                    "reason": row["reason"],
                    "timestamp": row["timestamp"],
                    "scorer": row["scorer"],
                    "weapon": weapon,
                }
            )

    # 2) Training labels (VideoMAE-compatible: clip_path, action_label)
    #    clip_path must be relative to --data-dir (which will be "data")
    TRAINING_LABELS.parent.mkdir(parents=True, exist_ok=True)
    train_fields = ["clip_path", "action_label"]
    train_exists = TRAINING_LABELS.exists()
    with open(TRAINING_LABELS, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=train_fields)
        if not train_exists:
            w.writeheader()
        for row in labels:
            if row["clip_path"]:
                # Make relative to DATA_DIR (e.g. "clips/usaf_xxx_touch0001.mp4")
                rel_path = os.path.relpath(row["clip_path"], str(DATA_DIR))
                w.writerow(
                    {
                        "clip_path": rel_path,
                        "action_label": row["action"],
                    }
                )


# ── Single video pipeline ─────────────────────────────────────────
def process_one_video(video_info: dict) -> dict:
    """Full pipeline for one video: download → OCR → report → clips → labels."""
    vid = video_info["id"]
    title = video_info["title"]
    url = f"https://www.youtube.com/watch?v={vid}"
    metadata = parse_fencing_metadata(title)
    weapon = metadata.get("weapon", "unknown")

    print(f"  [{vid}] {title[:65]}")
    print(
        f"    weapon={weapon} gender={metadata.get('gender')} "
        f"age={metadata.get('age_group')} type={metadata.get('bout_type')}"
    )

    # Step 1: Download
    filename = f"usaf_{vid}"
    video_path = RAW_DIR / f"{filename}.mp4"

    if not video_path.exists():
        print("    Downloading...")
        dl = VideoDownloader(output_dir=str(RAW_DIR), anti_bot=False)
        result = dl.download(url, filename=filename)
        if not result.success:
            return {"error": f"Download failed: {result.error}", "video_id": vid}
        video_path = result.output_path or video_path
    else:
        print("    Already downloaded, reusing")

    # Step 2: OCR scan
    print(f"    OCR scanning (interval={SAMPLE_INTERVAL})...")
    t0 = time.time()
    events, summary, fps, total_frames, ocr_rate = scan_video_ocr(str(video_path))
    analysis_time = time.time() - t0

    if not events:
        print("    WARNING: No touches detected")
        _safe_remove(video_path)
        return {"error": "No touches", "video_id": vid}

    # Step 3: Match report
    report = generate_report(
        events, summary, metadata, video_path, analysis_time, fps, total_frames,
    )
    if report:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        rpath = REPORTS_DIR / f"{vid}_report.json"
        with open(rpath, "w") as f:
            json.dump(report, f, indent=2, default=str)

    # Step 4: Clip extraction
    print(f"    Extracting {len(events)} clips...")
    clips = extract_clips(str(video_path), events)

    # Step 5: Heuristic labeling
    labels = label_events(events, clips)
    append_labels(labels, weapon=weapon)

    # Step 6: Keep raw video (avoid re-download on resume)
    # _safe_remove(video_path)

    final_score = report["summary"].get("final_score", "N/A") if report else "N/A"
    left = summary.get("left_name", "?")
    right = summary.get("right_name", "?")

    print(
        f"    DONE: {left} vs {right}, score={final_score}, "
        f"{len(events)} touches, {len(clips)} clips, {analysis_time:.0f}s"
    )

    return {
        "video_id": vid,
        "title": title,
        "weapon": weapon,
        "left_name": left,
        "right_name": right,
        "final_score": final_score,
        "touches": len(events),
        "clips": len(clips),
        "labels": len(labels),
        "ocr_rate": round(ocr_rate, 3),
        "analysis_sec": round(analysis_time, 1),
    }


def _safe_remove(path):
    try:
        if Path(path).exists():
            os.remove(path)
    except OSError:
        pass


# ── Fine-tuning ────────────────────────────────────────────────────
def run_fine_tuning() -> bool:
    """Run VideoMAE fine-tuning with collected clips."""
    print("\n" + "=" * 70)
    print("PHASE 4: VIDEOMAE FINE-TUNING")
    print("=" * 70)

    if not TRAINING_LABELS.exists():
        print("ERROR: No training labels found")
        return False

    with open(TRAINING_LABELS) as f:
        count = sum(1 for _ in csv.DictReader(f))
    print(f"Training data: {count} labeled clips")

    if count < MIN_CLIPS_FOR_TRAINING:
        print(f"Only {count} clips, need {MIN_CLIPS_FOR_TRAINING}. Skipping.")
        return False

    # Show class distribution
    dist = {}
    with open(TRAINING_LABELS) as f:
        for row in csv.DictReader(f):
            action = row["action_label"]
            dist[action] = dist.get(action, 0) + 1
    print("Class distribution:")
    for action, cnt in sorted(dist.items()):
        print(f"  {action:25s}: {cnt}")

    cmd = [
        sys.executable, "-m", "ml.training.train_videomae",
        "--dataset-format", "csv",
        "--data-dir", str(DATA_DIR),
        "--epochs", "10",
        "--batch-size", "4",
        "--grad-accum", "2",
        "--lr", "5e-5",
    ]

    print(f"\nRunning: {' '.join(cmd)}")
    result = subprocess.run(cmd, timeout=14400)  # 4h timeout
    return result.returncode == 0


# ── Main ───────────────────────────────────────────────────────────
def main():
    print("=" * 70)
    print("FENCINGMIND AUTO-COLLECTION + FINE-TUNING PIPELINE")
    print(f"Video list: {VIDEO_LIST}")
    print(f"Sample interval: {SAMPLE_INTERVAL} (OCR every {SAMPLE_INTERVAL} frames)")
    print(f"Clip window: -{CLIP_BEFORE_SEC}s / +{CLIP_AFTER_SEC}s")
    print("=" * 70)

    # Parse video list
    videos = parse_video_list(VIDEO_LIST)
    print(f"\nTotal videos in list: {len(videos)}")

    # Weapon distribution in list
    weapon_dist = {}
    for v in videos:
        m = parse_fencing_metadata(v["title"])
        w = m.get("weapon", "unknown")
        weapon_dist[w] = weapon_dist.get(w, 0) + 1
    print("Weapon distribution in list:")
    for w, c in sorted(weapon_dist.items()):
        print(f"  {w}: {c}")

    # Load progress
    progress = load_progress()
    done_ids = set(progress["processed"]) | set(progress["failed"])
    remaining = [v for v in videos if v["id"] not in done_ids]

    print(f"\nAlready processed: {len(progress['processed'])}")
    print(f"Previously failed: {len(progress['failed'])}")
    print(f"Remaining: {len(remaining)}")

    # ── Phase 1-3: Collection ──
    if remaining:
        total_start = time.time()

        for i, vinfo in enumerate(remaining):
            print(f"\n{'─'*70}")
            print(f"[{i + 1}/{len(remaining)}]")

            try:
                result = process_one_video(vinfo)

                if "error" in result:
                    progress["failed"][vinfo["id"]] = {
                        "error": result["error"],
                        "ts": time.time(),
                    }
                else:
                    progress["processed"][vinfo["id"]] = result
                    s = progress["stats"]
                    s["total_videos"] = len(progress["processed"])
                    s["total_touches"] += result.get("touches", 0)
                    s["total_clips"] += result.get("clips", 0)
                    s["total_labels"] += result.get("labels", 0)

            except Exception as e:
                print(f"    EXCEPTION: {e}")
                progress["failed"][vinfo["id"]] = {
                    "error": str(e)[:200],
                    "ts": time.time(),
                }

            save_progress(progress)

            # Periodic summary
            if (i + 1) % 5 == 0 or (i + 1) == len(remaining):
                s = progress["stats"]
                elapsed = time.time() - total_start
                rate = (i + 1) / (elapsed / 60) if elapsed > 0 else 0
                eta = (len(remaining) - i - 1) / rate if rate > 0 else 0
                print(
                    f"\n  ── Progress: {s['total_videos']} videos, "
                    f"{s['total_touches']} touches, {s['total_clips']} clips | "
                    f"{elapsed/60:.0f}min elapsed, ~{eta:.0f}min remaining ──"
                )

        total_time = time.time() - total_start
        print(f"\n{'='*70}")
        print("COLLECTION COMPLETE")
        s = progress["stats"]
        print(f"Time: {total_time:.0f}s ({total_time / 3600:.1f}h)")
        print(f"Videos: {s['total_videos']} processed, {len(progress['failed'])} failed")
        print(f"Touches: {s['total_touches']}")
        print(f"Clips: {s['total_clips']}")
        print(f"Labels: {s['total_labels']}")
        print(f"{'='*70}")
    else:
        print("\nAll videos already processed.")

    # ── Phase 4: Fine-tuning ──
    total_clips = progress["stats"].get("total_clips", 0)
    print(f"\nTotal clips collected: {total_clips}")

    if total_clips >= MIN_CLIPS_FOR_TRAINING:
        success = run_fine_tuning()
        if success:
            print("\n✓ FINE-TUNING COMPLETE")
            progress["stats"]["finetuning_complete"] = True
            progress["stats"]["finetuning_timestamp"] = time.time()
        else:
            print("\n✗ Fine-tuning failed")
            progress["stats"]["finetuning_complete"] = False
    else:
        print(
            f"Not enough clips for fine-tuning ({total_clips} < {MIN_CLIPS_FOR_TRAINING}). "
            f"Consider adding more videos."
        )

    save_progress(progress)
    print("\nDone. Progress saved to:", PROGRESS_FILE)


if __name__ == "__main__":
    main()
