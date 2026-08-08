"""
Active Learning pipeline for fencing clip labeling.

After reviewing 200-300 clips, trains an initial VideoMAE model, then predicts
on remaining clips. Clips where model disagrees with Gemini are prioritized
for human review in the next labeling round.

Usage:
    # Step 1: Generate priority queue (after 200+ reviewed labels)
    PYTHONPATH=. .venv/bin/python3 scripts/active_learning.py --generate-queue

    # Step 2: Export queue to labeling server
    PYTHONPATH=. .venv/bin/python3 scripts/active_learning.py --export-queue

    # Step 3: After more reviews, retrain + regenerate queue
    PYTHONPATH=. .venv/bin/python3 scripts/active_learning.py --retrain --generate-queue
"""

import argparse
import csv
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

# Paths
DATA_DIR = Path("data")
CLIPS_DIR = DATA_DIR / "clips"
GEMINI_RESULTS = DATA_DIR / "labeled" / "gemini_results.json"
REVIEWED_CSV = DATA_DIR / "labeled" / "labels_reviewed.csv"
QUEUE_OUTPUT = DATA_DIR / "labeled" / "active_learning_queue.json"
MODEL_DIR = Path("ml/models/videomae-fencing-v1")
TRAINING_LABELS = DATA_DIR / "labeled" / "labels_al_train.csv"


def load_gemini_results(required: bool = False) -> dict:
    """Load Gemini auto-labels."""
    if not GEMINI_RESULTS.exists():
        if required:
            print(f"ERROR: Gemini results not found: {GEMINI_RESULTS}")
            print(f"  Run gemini_labeler.py first.")
            sys.exit(1)
        return {}
    with open(GEMINI_RESULTS, "r", encoding="utf-8") as f:
        return json.load(f)


def load_reviewed_labels() -> dict:
    """Load human-reviewed labels from CSV."""
    reviewed = {}
    if not REVIEWED_CSV.exists():
        return reviewed
    with open(REVIEWED_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            filename = Path(row["clip_path"]).name
            reviewed[filename] = row["action_label"]
    return reviewed


def get_unreviewed_clips(gemini: dict, reviewed: dict) -> list:
    """Get clips that haven't been human-reviewed yet."""
    return [f for f in gemini if f not in reviewed]


def predict_with_model(clip_paths: list) -> dict:
    """
    Run model inference on a list of clip paths.

    Returns dict: filename -> {predicted_label, confidence}
    """
    try:
        import torch
        from transformers import VideoMAEForVideoClassification, VideoMAEImageProcessor

        from ml.training.config import (
            BASE_MODEL,
            IDX_TO_LABEL,
            NUM_CLASSES,
            NUM_FRAMES,
        )
        from ml.training.dataset import FencingActionDataset
    except ImportError as e:
        print(f"ERROR: Required packages not installed: {e}")
        return {}

    # Load model
    model_path = MODEL_DIR if MODEL_DIR.exists() else None
    if model_path is None:
        print("WARNING: No fine-tuned model found. Using base model (predictions will be poor).")
        model_name = BASE_MODEL
    else:
        model_name = str(model_path)
        print(f"Using fine-tuned model: {model_path}")

    try:
        model = VideoMAEForVideoClassification.from_pretrained(
            model_name,
            num_labels=NUM_CLASSES,
            ignore_mismatched_sizes=True,
        )
        processor = VideoMAEImageProcessor.from_pretrained(BASE_MODEL)
    except Exception as e:
        print(f"ERROR loading model: {e}")
        return {}

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = model.to(device)
    model.eval()

    predictions = {}

    for i, clip_path in enumerate(clip_paths):
        if not Path(clip_path).exists():
            continue

        if (i + 1) % 50 == 0:
            print(f"  Predicting {i+1}/{len(clip_paths)}...")

        try:
            # Load frames using dataset logic
            import cv2
            import numpy as np

            cap = cv2.VideoCapture(str(clip_path))
            frames = []
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                frames.append(frame[:, :, ::-1].copy())
            cap.release()

            if not frames:
                continue

            # Sample frames
            n = len(frames)
            if n > NUM_FRAMES:
                indices = np.linspace(0, n - 1, NUM_FRAMES, dtype=int)
                frames = [frames[i] for i in indices]
            elif n < NUM_FRAMES:
                while len(frames) < NUM_FRAMES:
                    frames.append(frames[-1])

            # Process
            inputs = processor(frames, return_tensors="pt")
            inputs = {k: v.to(device) for k, v in inputs.items()}

            with torch.no_grad():
                outputs = model(**inputs)
                probs = torch.softmax(outputs.logits, dim=-1)
                pred_idx = probs.argmax(dim=-1).item()
                confidence = probs[0, pred_idx].item()

            predicted_label = IDX_TO_LABEL.get(pred_idx, "unknown")
            filename = Path(clip_path).name
            predictions[filename] = {
                "predicted_label": predicted_label,
                "confidence": round(confidence, 4),
            }

        except Exception as e:
            filename = Path(clip_path).name
            predictions[filename] = {
                "predicted_label": "error",
                "confidence": 0.0,
                "error": str(e),
            }

    return predictions


def generate_priority_queue(
    gemini: dict,
    reviewed: dict,
    model_predictions: Optional[dict] = None,
) -> list:
    """
    Generate priority queue for next review round.

    Priority (highest first):
    1. Model vs Gemini disagreement (if model available)
    2. Low Gemini confidence
    3. Remaining unreviewed clips

    Returns: sorted list of dicts with filename, priority_score, reasons
    """
    unreviewed = get_unreviewed_clips(gemini, reviewed)
    queue = []

    for filename in unreviewed:
        g = gemini[filename]
        gemini_label = g.get("combined_label", "unknown")
        gemini_conf = g.get("confidence", 0.5)
        reasons = []
        priority = 0.0

        # Factor 1: Model disagreement (most important)
        if model_predictions and filename in model_predictions:
            mp = model_predictions[filename]
            model_label = mp.get("predicted_label", "unknown")
            model_conf = mp.get("confidence", 0.0)

            if model_label != gemini_label and model_label != "error":
                priority += 100  # Strong disagreement signal
                reasons.append(f"Model says {model_label} ({model_conf:.0%}) vs Gemini {gemini_label}")

            # Also boost if model is very uncertain
            if model_conf < 0.4:
                priority += 30
                reasons.append(f"Model uncertain ({model_conf:.0%})")

        # Factor 2: Low Gemini confidence
        if gemini_conf < 0.5:
            priority += 50
            reasons.append(f"Low Gemini confidence ({gemini_conf:.0%})")
        elif gemini_conf < 0.7:
            priority += 20
            reasons.append(f"Medium Gemini confidence ({gemini_conf:.0%})")

        # Factor 3: Gemini had parse error or error
        if g.get("error") or g.get("parse_error"):
            priority += 80
            reasons.append("Gemini error/parse failure")

        # Factor 4: Rare class boost (help balance dataset)
        if gemini_label in ("counter_attack_left", "counter_attack_right",
                           "remise_left", "remise_right"):
            priority += 10
            reasons.append(f"Rare class ({gemini_label})")

        if not reasons:
            reasons.append("Standard review")

        queue.append({
            "filename": filename,
            "priority_score": round(priority, 1),
            "gemini_label": gemini_label,
            "gemini_confidence": gemini_conf,
            "model_label": model_predictions.get(filename, {}).get("predicted_label") if model_predictions else None,
            "model_confidence": model_predictions.get(filename, {}).get("confidence") if model_predictions else None,
            "reasons": reasons,
        })

    # Sort by priority (highest first)
    queue.sort(key=lambda x: -x["priority_score"])
    return queue


def export_queue_to_labeling_server(queue: list):
    """
    Reorder Gemini results by priority for the labeling server.

    The labeling server sorts by confidence, but this reorders so that
    highest-priority clips come first regardless of confidence.
    """
    # The labeling server reads gemini_results.json and sorts by confidence.
    # We can influence the order by adjusting confidence values in a separate
    # priority file that the server can optionally use.
    # For now, we just save the queue and print instructions.

    QUEUE_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(QUEUE_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2, ensure_ascii=False)

    print(f"\nPriority queue saved to {QUEUE_OUTPUT}")
    print(f"Total in queue: {len(queue)}")

    if queue:
        print(f"\nTop 10 priority clips:")
        for item in queue[:10]:
            reasons_str = "; ".join(item["reasons"])
            print(f"  [{item['priority_score']:5.1f}] {item['filename']}")
            print(f"         Gemini: {item['gemini_label']} ({item['gemini_confidence']:.0%})")
            if item.get("model_label"):
                print(f"         Model:  {item['model_label']} ({item['model_confidence']:.0%})")
            print(f"         Reason: {reasons_str}")

    # Distribution of priority scores
    if queue:
        high = sum(1 for q in queue if q["priority_score"] >= 50)
        medium = sum(1 for q in queue if 10 <= q["priority_score"] < 50)
        low = sum(1 for q in queue if q["priority_score"] < 10)
        print(f"\nPriority distribution:")
        print(f"  High (>=50):  {high}")
        print(f"  Medium (10-50): {medium}")
        print(f"  Low (<10):    {low}")


def prepare_training_csv(reviewed: dict):
    """
    Prepare a labels CSV from reviewed data for training.

    Writes to a separate file so the original labels.csv is untouched.
    """
    TRAINING_LABELS.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(TRAINING_LABELS, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["clip_path", "action_label"])
        for filename, label in sorted(reviewed.items()):
            clip_path = CLIPS_DIR / filename
            if clip_path.exists():
                # Relative to data/labeled (what FencingActionDataset expects)
                writer.writerow([f"../clips/{filename}", label])
                count += 1

    print(f"Training CSV: {TRAINING_LABELS} ({count} samples)")
    dist = Counter(reviewed.values())
    print("Distribution:")
    for label, cnt in sorted(dist.items()):
        print(f"  {label:25s}: {cnt}")

    return count


def run_training():
    """Run VideoMAE fine-tuning with reviewed labels."""
    print("\n=== Starting VideoMAE Fine-tuning ===")

    cmd = [
        sys.executable,
        "-m", "ml.training.train_videomae",
        "--data-dir", str(DATA_DIR / "labeled"),
        "--epochs", "10",
        "--batch-size", "4",
        "--grad-accum", "2",
    ]

    # Point to our training labels
    # The training script uses DATA_DIR/labels.csv by default.
    # We need to copy our reviewed labels there temporarily or pass as arg.
    # For now, copy to the expected location.
    import shutil
    target = DATA_DIR / "labeled" / "labels.csv"
    backup = DATA_DIR / "labeled" / "labels_original_backup.csv"

    # Backup original
    if target.exists() and not backup.exists():
        shutil.copy2(target, backup)

    # Copy reviewed labels
    if TRAINING_LABELS.exists():
        shutil.copy2(TRAINING_LABELS, target)
        print(f"Copied {TRAINING_LABELS} -> {target}")

    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(Path.cwd()))

    if result.returncode == 0:
        print("\nTraining completed successfully!")
    else:
        print(f"\nTraining failed with return code {result.returncode}")

    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Active Learning for fencing clip labeling")
    parser.add_argument("--generate-queue", action="store_true",
                       help="Generate priority queue from model vs Gemini disagreements")
    parser.add_argument("--export-queue", action="store_true",
                       help="Export queue for labeling server")
    parser.add_argument("--retrain", action="store_true",
                       help="Retrain model with current reviewed labels")
    parser.add_argument("--status", action="store_true",
                       help="Show current labeling status")
    parser.add_argument("--prepare-csv", action="store_true",
                       help="Prepare training CSV from reviewed labels")
    parser.add_argument("--skip-model", action="store_true",
                       help="Generate queue without model predictions (Gemini-only)")

    args = parser.parse_args()

    # Default: show status
    if not any([args.generate_queue, args.export_queue, args.retrain,
                args.status, args.prepare_csv]):
        args.status = True

    required = args.generate_queue or args.export_queue
    gemini = load_gemini_results(required=required)
    reviewed = load_reviewed_labels()
    unreviewed = get_unreviewed_clips(gemini, reviewed)

    if args.status:
        print(f"\n=== Active Learning Status ===")
        print(f"Gemini results:  {len(gemini)}")
        print(f"Reviewed:        {len(reviewed)}")
        print(f"Unreviewed:      {len(unreviewed)}")
        print(f"Model exists:    {MODEL_DIR.exists()}")
        print(f"Queue exists:    {QUEUE_OUTPUT.exists()}")

        if reviewed:
            dist = Counter(reviewed.values())
            print(f"\nReviewed label distribution:")
            for label, count in sorted(dist.items()):
                print(f"  {label:25s}: {count}")

            # Gemini agreement
            agreements = sum(
                1 for f, l in reviewed.items()
                if gemini.get(f, {}).get("combined_label") == l
            )
            print(f"\nGemini agreement: {agreements}/{len(reviewed)} "
                  f"({agreements/len(reviewed)*100:.1f}%)")

        if len(reviewed) < 200:
            remaining = 200 - len(reviewed)
            print(f"\n** Need {remaining} more reviews before training **")
            print(f"   Run labeling server: PYTHONPATH=. .venv/bin/python3 scripts/labeling_server.py")
        else:
            print(f"\n** Ready for training! Run with --retrain **")

        return

    if args.prepare_csv:
        if not reviewed:
            print("No reviewed labels found. Label some clips first.")
            return
        prepare_training_csv(reviewed)
        return

    if args.retrain:
        if len(reviewed) < 50:
            print(f"Only {len(reviewed)} reviewed labels. Need at least 50 for training.")
            return
        count = prepare_training_csv(reviewed)
        if count > 0:
            run_training()

    if args.generate_queue:
        print(f"\n=== Generating Priority Queue ===")

        model_predictions = None
        if not args.skip_model and MODEL_DIR.exists():
            print("Running model predictions on unreviewed clips...")
            clip_paths = [CLIPS_DIR / f for f in unreviewed]
            model_predictions = predict_with_model(clip_paths)
            print(f"Got {len(model_predictions)} predictions")
        elif not args.skip_model:
            print("No fine-tuned model found. Using Gemini-only priority.")
        else:
            print("Skipping model predictions (--skip-model)")

        queue = generate_priority_queue(gemini, reviewed, model_predictions)
        export_queue_to_labeling_server(queue)

    elif args.export_queue:
        # Re-export existing queue
        if QUEUE_OUTPUT.exists():
            with open(QUEUE_OUTPUT, "r", encoding="utf-8") as f:
                queue = json.load(f)
            print(f"Loaded existing queue: {len(queue)} items")
            export_queue_to_labeling_server(queue)
        else:
            print("No queue file found. Run --generate-queue first.")


if __name__ == "__main__":
    main()
