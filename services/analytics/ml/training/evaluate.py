"""
Evaluate fine-tuned VideoMAE model on test set.

Usage:
    python -m ml.training.evaluate --model-dir ml/models/videomae-fencing-v1

Outputs:
- Per-class precision, recall, F1-score
- Overall accuracy and weighted F1
- Confusion matrix (printed + saved as JSON)
"""

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import List, Dict

import numpy as np


def parse_args():
    parser = argparse.ArgumentParser(
        description="Evaluate fine-tuned VideoMAE on fencing test set",
    )
    parser.add_argument(
        "--model-dir", type=str, default="ml/models/videomae-fencing-v1",
        help="Directory with fine-tuned model",
    )
    parser.add_argument(
        "--data-dir", type=str, default="data/labeled",
        help="Root directory for labeled clips",
    )
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--device", type=str, default=None)
    parser.add_argument(
        "--output", type=str, default=None,
        help="Path to save evaluation results JSON",
    )
    return parser.parse_args()


def compute_metrics(
    y_true: List[int],
    y_pred: List[int],
    num_classes: int,
    label_names: Dict[int, str],
) -> dict:
    """Compute per-class and overall metrics without sklearn."""
    # Confusion matrix
    cm = np.zeros((num_classes, num_classes), dtype=int)
    for t, p in zip(y_true, y_pred):
        cm[t][p] += 1

    # Per-class metrics
    per_class = {}
    for i in range(num_classes):
        tp = cm[i][i]
        fp = sum(cm[j][i] for j in range(num_classes)) - tp
        fn = sum(cm[i][j] for j in range(num_classes)) - tp

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        support = sum(cm[i])

        name = label_names.get(i, f"class_{i}")
        per_class[name] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": int(support),
        }

    # Overall metrics
    correct = sum(cm[i][i] for i in range(num_classes))
    total = len(y_true)
    accuracy = correct / total if total > 0 else 0.0

    # Weighted F1
    weighted_f1 = sum(
        per_class[label_names.get(i, f"class_{i}")]["f1"]
        * per_class[label_names.get(i, f"class_{i}")]["support"]
        for i in range(num_classes)
    ) / max(1, total)

    return {
        "accuracy": round(accuracy, 4),
        "weighted_f1": round(weighted_f1, 4),
        "total_samples": total,
        "per_class": per_class,
        "confusion_matrix": cm.tolist(),
        "class_names": [label_names.get(i, f"class_{i}") for i in range(num_classes)],
    }


def print_report(metrics: dict):
    """Pretty-print evaluation report."""
    print("\n" + "=" * 60)
    print("FENCING ACTION CLASSIFICATION — EVALUATION REPORT")
    print("=" * 60)
    print(f"\nOverall Accuracy: {metrics['accuracy']:.1%}")
    print(f"Weighted F1:      {metrics['weighted_f1']:.4f}")
    print(f"Total Samples:    {metrics['total_samples']}")

    print(f"\n{'Class':<18} {'Precision':>10} {'Recall':>10} {'F1':>10} {'Support':>10}")
    print("-" * 60)
    for name, m in metrics["per_class"].items():
        print(
            f"{name:<18} {m['precision']:>10.3f} {m['recall']:>10.3f} "
            f"{m['f1']:>10.3f} {m['support']:>10}"
        )

    # Confusion matrix
    names = metrics["class_names"]
    cm = metrics["confusion_matrix"]
    print(f"\nConfusion Matrix:")
    header = "           " + "".join(f"{n[:6]:>7}" for n in names)
    print(header)
    for i, row in enumerate(cm):
        row_str = "".join(f"{v:>7}" for v in row)
        print(f"{names[i]:<11}{row_str}")

    print()


def evaluate(args):
    """Run evaluation on test set."""
    import torch
    from torch.utils.data import DataLoader
    from transformers import (
        VideoMAEForVideoClassification,
        VideoMAEImageProcessor,
    )
    from ml.training.dataset import FencingActionDataset
    from ml.training.config import NUM_CLASSES, IDX_TO_LABEL

    model_dir = Path(args.model_dir)
    if not model_dir.exists():
        print(f"ERROR: Model directory not found: {model_dir}")
        print("Run train_videomae.py first to create a fine-tuned model.")
        return

    device = args.device
    if device is None:
        if torch.cuda.is_available():
            device = "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"

    print(f"Loading model from: {model_dir}")
    print(f"Device: {device}")

    model = VideoMAEForVideoClassification.from_pretrained(str(model_dir))
    processor = VideoMAEImageProcessor.from_pretrained(str(model_dir))
    model.to(device)
    model.eval()

    test_ds = FencingActionDataset(
        data_dir=Path(args.data_dir), split="test", augment=False,
    )

    if len(test_ds) == 0:
        print("ERROR: No test samples found.")
        return

    print(f"Test samples: {len(test_ds)}")

    def collate_fn(batch):
        all_frames = []
        all_labels = []
        for frames_list, label in batch:
            all_frames.append(frames_list)
            all_labels.append(label)
        inputs = processor(all_frames, return_tensors="pt")
        labels = torch.tensor(all_labels, dtype=torch.long)
        return inputs, labels

    test_loader = DataLoader(
        test_ds,
        batch_size=args.batch_size,
        shuffle=False,
        collate_fn=collate_fn,
        num_workers=0,
    )

    # Collect predictions
    all_true: List[int] = []
    all_pred: List[int] = []

    with torch.no_grad():
        for inputs, labels in test_loader:
            inputs = {k: v.to(device) for k, v in inputs.items()}
            outputs = model(**inputs)
            preds = outputs.logits.argmax(dim=-1).cpu().tolist()
            all_true.extend(labels.tolist())
            all_pred.extend(preds)

    metrics = compute_metrics(all_true, all_pred, NUM_CLASSES, IDX_TO_LABEL)
    print_report(metrics)

    # Save results
    output_path = args.output or str(model_dir / "eval_results.json")
    with open(output_path, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"Results saved to: {output_path}")


if __name__ == "__main__":
    args = parse_args()
    evaluate(args)
