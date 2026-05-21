"""
VideoMAE fine-tuning script for fencing action classification.

Usage (Colab / Lambda / local):
    python -m ml.training.train_videomae --epochs 10 --batch-size 4

    # Use FACTS dataset directory structure
    python -m ml.training.train_videomae --dataset-format facts --data-dir data/facts

The script:
1. Loads labeled fencing clips from data/labeled/ (CSV) or data/facts/ (FACTS dirs)
2. Fine-tunes VideoMAE (Kinetics-400 pretrained) with 8-class head
3. Uses gradient accumulation for effective larger batch sizes
4. Saves best model to ml/models/videomae-fencing-v1/
"""

import argparse
import json
import time
from pathlib import Path
from typing import List

import numpy as np


def parse_args():
    parser = argparse.ArgumentParser(
        description="Fine-tune VideoMAE on fencing action clips",
    )
    parser.add_argument(
        "--data-dir", type=str, default="data/labeled",
        help="Root directory for labeled clips",
    )
    parser.add_argument(
        "--output-dir", type=str, default="ml/models/videomae-fencing-v1",
        help="Directory to save fine-tuned model",
    )
    parser.add_argument(
        "--dataset-format", type=str, default="csv",
        choices=["csv", "facts"],
        help="Dataset format: 'csv' (labels.csv) or 'facts' (FACTS directory structure)",
    )
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--grad-accum", type=int, default=2,
                        help="Gradient accumulation steps (effective batch = batch-size * grad-accum)")
    parser.add_argument("--lr", type=float, default=5e-5)
    parser.add_argument("--warmup-epochs", type=int, default=3)
    parser.add_argument("--label-smoothing", type=float, default=0.1)
    parser.add_argument("--device", type=str, default=None, help="cuda/mps/cpu")
    return parser.parse_args()


def resolve_device(preferred: str = None) -> str:
    """Auto-select best device."""
    import torch
    if preferred:
        return preferred
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def train(args):
    """Main training loop."""
    import torch
    from torch.utils.data import DataLoader
    from transformers import (
        VideoMAEForVideoClassification,
        VideoMAEImageProcessor,
    )
    from ml.training.dataset import FencingActionDataset
    from ml.training.config import (
        BASE_MODEL,
        NUM_CLASSES,
        NUM_FRAMES,
        LABEL_TO_IDX,
        IDX_TO_LABEL,
    )

    device = resolve_device(args.device)
    print(f"Device: {device}")
    print(f"Data dir: {args.data_dir}")
    print(f"Dataset format: {args.dataset_format}")
    print(f"Output dir: {args.output_dir}")
    print(f"Batch size: {args.batch_size} × {args.grad_accum} accum = {args.batch_size * args.grad_accum} effective")

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    if args.dataset_format == "facts":
        # Convert FACTS directory structure to CSV, then load normally
        from ml.training.dataset import FACTSDatasetAdapter
        adapter = FACTSDatasetAdapter(facts_dir=Path(args.data_dir))
        if len(adapter) == 0:
            print("ERROR: No FACTS clips found. Check directory structure.")
            print(f"  Expected: {args.data_dir}/AL/, AR/, RL/, RR/, CAL/, CAR/, ReL/, ReR/")
            return
        print(f"FACTS adapter found {len(adapter)} clips")
        dist = adapter.get_class_distribution()
        for label, count in dist.items():
            print(f"  {label}: {count}")

        # Write temporary labels.csv for FencingActionDataset
        tmp_csv = Path(args.data_dir) / "labels.csv"
        adapter.to_csv(tmp_csv)
        print(f"Wrote temporary labels.csv: {tmp_csv}")

        train_ds = FencingActionDataset(
            data_dir=Path(args.data_dir),
            labels_file=tmp_csv,
            split="train", augment=True,
        )
        val_ds = FencingActionDataset(
            data_dir=Path(args.data_dir),
            labels_file=tmp_csv,
            split="val", augment=False,
        )
    else:
        train_ds = FencingActionDataset(
            data_dir=Path(args.data_dir), split="train", augment=True,
        )
        val_ds = FencingActionDataset(
            data_dir=Path(args.data_dir), split="val", augment=False,
        )

    if len(train_ds) == 0:
        print("ERROR: No training samples found.")
        if args.dataset_format == "csv":
            print(f"  Expected: {args.data_dir}/labels.csv")
        else:
            print(f"  Expected: {args.data_dir}/<class_code>/*.mp4")
        return

    print(f"Train samples: {len(train_ds)}, Val samples: {len(val_ds)}")

    processor = VideoMAEImageProcessor.from_pretrained(BASE_MODEL)

    def collate_fn(batch):
        """Custom collate: process frames through VideoMAE processor."""
        all_frames = []
        all_labels = []
        for frames_list, label in batch:
            all_frames.append(frames_list)
            all_labels.append(label)

        inputs = processor(all_frames, return_tensors="pt")
        labels = torch.tensor(all_labels, dtype=torch.long)
        return inputs, labels

    train_loader = DataLoader(
        train_ds,
        batch_size=args.batch_size,
        shuffle=True,
        collate_fn=collate_fn,
        num_workers=0,  # Safe for MPS/CUDA
    )
    val_loader = DataLoader(
        val_ds,
        batch_size=args.batch_size,
        shuffle=False,
        collate_fn=collate_fn,
        num_workers=0,
    )

    # ------------------------------------------------------------------
    # Model
    # ------------------------------------------------------------------
    model = VideoMAEForVideoClassification.from_pretrained(
        BASE_MODEL,
        num_labels=NUM_CLASSES,
        ignore_mismatched_sizes=True,  # Replace classifier head
    )
    model.config.id2label = IDX_TO_LABEL
    model.config.label2id = LABEL_TO_IDX
    model.to(device)

    # ------------------------------------------------------------------
    # Optimizer + Scheduler
    # ------------------------------------------------------------------
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=args.lr,
        weight_decay=0.05,
    )

    total_steps = len(train_loader) * args.epochs
    warmup_steps = len(train_loader) * args.warmup_epochs

    def lr_lambda(step):
        if step < warmup_steps:
            return step / max(1, warmup_steps)
        progress = (step - warmup_steps) / max(1, total_steps - warmup_steps)
        return max(0.0, 0.5 * (1.0 + np.cos(np.pi * progress)))

    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lr_lambda)

    loss_fn = torch.nn.CrossEntropyLoss(
        label_smoothing=args.label_smoothing,
    )

    # ------------------------------------------------------------------
    # Training loop (with gradient accumulation)
    # ------------------------------------------------------------------
    best_val_acc = 0.0
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    history: List[dict] = []
    grad_accum = args.grad_accum

    for epoch in range(args.epochs):
        model.train()
        train_loss = 0.0
        train_correct = 0
        train_total = 0
        t0 = time.time()
        optimizer.zero_grad()

        for batch_idx, (inputs, labels) in enumerate(train_loader):
            inputs = {k: v.to(device) for k, v in inputs.items()}
            labels = labels.to(device)

            outputs = model(**inputs)
            loss = loss_fn(outputs.logits, labels)
            # Scale loss for gradient accumulation
            scaled_loss = loss / grad_accum
            scaled_loss.backward()

            # Step optimizer every grad_accum batches (or at end of epoch)
            if (batch_idx + 1) % grad_accum == 0 or (batch_idx + 1) == len(train_loader):
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad()

            train_loss += loss.item()
            preds = outputs.logits.argmax(dim=-1)
            train_correct += (preds == labels).sum().item()
            train_total += labels.size(0)

        train_acc = train_correct / max(1, train_total)
        avg_loss = train_loss / max(1, len(train_loader))
        epoch_time = time.time() - t0

        # Validation
        val_acc, val_loss = _evaluate(model, val_loader, loss_fn, device)

        epoch_info = {
            "epoch": epoch + 1,
            "train_loss": round(avg_loss, 4),
            "train_acc": round(train_acc, 4),
            "val_loss": round(val_loss, 4),
            "val_acc": round(val_acc, 4),
            "lr": optimizer.param_groups[0]["lr"],
            "time_sec": round(epoch_time, 1),
        }
        history.append(epoch_info)
        print(
            f"Epoch {epoch+1}/{args.epochs} — "
            f"loss: {avg_loss:.4f}, acc: {train_acc:.3f}, "
            f"val_loss: {val_loss:.4f}, val_acc: {val_acc:.3f}, "
            f"time: {epoch_time:.1f}s"
        )

        # Save best model
        if val_acc > best_val_acc:
            best_val_acc = val_acc
            model.save_pretrained(output_dir)
            processor.save_pretrained(output_dir)
            print(f"  → Best model saved (val_acc={val_acc:.3f})")

    # Save training history
    with open(output_dir / "training_history.json", "w") as f:
        json.dump(history, f, indent=2)

    print(f"\nTraining complete. Best val accuracy: {best_val_acc:.3f}")
    print(f"Model saved to: {output_dir}")


def _evaluate(model, dataloader, loss_fn, device) -> tuple:
    """Evaluate model on dataloader. Returns (accuracy, avg_loss)."""
    import torch
    model.eval()
    total_loss = 0.0
    correct = 0
    total = 0

    with torch.no_grad():
        for inputs, labels in dataloader:
            inputs = {k: v.to(device) for k, v in inputs.items()}
            labels = labels.to(device)

            outputs = model(**inputs)
            loss = loss_fn(outputs.logits, labels)

            total_loss += loss.item()
            preds = outputs.logits.argmax(dim=-1)
            correct += (preds == labels).sum().item()
            total += labels.size(0)

    accuracy = correct / max(1, total)
    avg_loss = total_loss / max(1, len(dataloader))
    return accuracy, avg_loss


if __name__ == "__main__":
    args = parse_args()
    train(args)
