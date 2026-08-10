"""
Web-based labeling review tool for fencing clips.

Supports two data sources:
1. Pose analysis results (primary) — ml/pose_analyzer.py output
2. Gemini results (legacy fallback) — scripts/gemini_labeler.py output

Clips sorted by confidence (low first) so uncertain ones get reviewed first.

Usage:
    PYTHONPATH=. .venv/bin/python3 scripts/labeling_server.py
    # Then open http://localhost:7600

Output:
    data/labeled/labels_reviewed.csv  (compatible with ml/training/dataset.py)
    data/labeled/review_state.json    (review progress state)
"""

import csv
import json
import os
import sys
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Paths
BASE_DIR = Path("data")
CLIPS_DIR = BASE_DIR / "clips"
POSE_RESULTS_PATH = BASE_DIR / "labeled" / "pose_analysis_results.json"
GEMINI_RESULTS_PATH = BASE_DIR / "labeled" / "gemini_results.json"
REVIEWED_CSV_PATH = BASE_DIR / "labeled" / "labels_reviewed.csv"
STATE_PATH = BASE_DIR / "labeled" / "review_state.json"
TEMPLATE_PATH = Path("templates") / "labeling.html"

# Valid labels
VALID_LABELS = [
    "attack_left", "attack_right",
    "riposte_left", "riposte_right",
    "counter_attack_left", "counter_attack_right",
    "remise_left", "remise_right",
]


class LabelRequest(BaseModel):
    filename: str
    action_label: str


class SkipRequest(BaseModel):
    filename: str


class SortRequest(BaseModel):
    sort_by: str  # "confidence", "filename", "action"


class LabelingState:
    """Manages labeling state: pose/Gemini results, reviewed labels, undo stack."""

    def __init__(self):
        self.pose_results: dict = {}   # filename -> pose analysis result
        self.gemini_results: dict = {}
        self.reviewed: dict = {}  # filename -> action_label
        self.skipped: set = set()
        self.history: list = []  # undo stack: (action, filename, prev_label)
        self.sort_order: str = "confidence"  # confidence | filename | action
        self._sorted_files: list = []
        self.data_source: str = "none"  # "pose", "gemini", or "none"

        self._load()

    def _load(self):
        """Load pose/Gemini results and existing review state."""
        # Load pose analysis results (primary)
        if POSE_RESULTS_PATH.exists():
            with open(POSE_RESULTS_PATH, "r", encoding="utf-8") as f:
                self.pose_results = json.load(f)
            self.data_source = "pose"

        # Load Gemini results (fallback)
        if GEMINI_RESULTS_PATH.exists():
            with open(GEMINI_RESULTS_PATH, "r", encoding="utf-8") as f:
                self.gemini_results = json.load(f)
            if not self.pose_results:
                self.data_source = "gemini"

        # Load review state
        if STATE_PATH.exists():
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                state = json.load(f)
                self.reviewed = state.get("reviewed", {})
                self.skipped = set(state.get("skipped", []))
                self.sort_order = state.get("sort_order", "confidence")

        # Also load from CSV if exists (source of truth for training)
        if REVIEWED_CSV_PATH.exists():
            with open(REVIEWED_CSV_PATH, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    clip_path = row["clip_path"]
                    filename = Path(clip_path).name
                    self.reviewed[filename] = row["action_label"]

        self._update_sort()

    def _get_all_files(self) -> list:
        """Get all known clip filenames from available data sources."""
        files = set()
        files.update(self.pose_results.keys())
        files.update(self.gemini_results.keys())
        return list(files)

    def _get_confidence(self, filename: str) -> float:
        """Get suggestion confidence for a clip from best available source."""
        if filename in self.pose_results:
            return self.pose_results[filename].get("suggestion_confidence", 0)
        if filename in self.gemini_results:
            return self.gemini_results[filename].get("confidence", 0)
        return 0

    def _get_suggested_label(self, filename: str) -> str:
        """Get suggested label from best available source."""
        if filename in self.pose_results:
            return self.pose_results[filename].get("suggested_label", "unknown")
        if filename in self.gemini_results:
            return self.gemini_results[filename].get("combined_label", "unknown")
        return "unknown"

    def _update_sort(self):
        """Update sorted file list based on current sort order."""
        files = self._get_all_files()

        if self.sort_order == "confidence":
            # Low confidence first (most uncertain first for review)
            files.sort(key=lambda f: self._get_confidence(f))
        elif self.sort_order == "filename":
            files.sort()
        elif self.sort_order == "action":
            files.sort(key=lambda f: self._get_suggested_label(f))

        self._sorted_files = files

    def _save_state(self):
        """Save review state."""
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "reviewed": self.reviewed,
            "skipped": list(self.skipped),
            "sort_order": self.sort_order,
        }
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)

    def _save_csv(self):
        """Save reviewed labels as CSV compatible with FencingActionDataset."""
        REVIEWED_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(REVIEWED_CSV_PATH, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["clip_path", "action_label"])
            for filename, label in sorted(self.reviewed.items()):
                # Path relative to data/labeled (where FencingActionDataset looks)
                # Since clips are in data/clips/, relative path from data/labeled is ../clips/
                clip_rel = f"../clips/{filename}"
                writer.writerow([clip_rel, label])

    def get_clip_info(self, index: int) -> Optional[dict]:
        """Get clip info at given index in sorted list."""
        if not self._sorted_files or index < 0 or index >= len(self._sorted_files):
            return None

        filename = self._sorted_files[index]
        gemini = self.gemini_results.get(filename, {})
        pose = self.pose_results.get(filename, {})
        clip_path = CLIPS_DIR / filename

        info = {
            "index": index,
            "total": len(self._sorted_files),
            "filename": filename,
            "exists": clip_path.exists(),
            "data_source": self.data_source,
            # Gemini data (legacy)
            "gemini_action": gemini.get("action", "unknown"),
            "gemini_direction": gemini.get("direction", "unknown"),
            "gemini_label": gemini.get("combined_label", "unknown"),
            "gemini_confidence": gemini.get("confidence", 0),
            "gemini_reasoning": gemini.get("reasoning", ""),
            # Pose analysis data
            "pose_suggested_label": pose.get("suggested_label"),
            "pose_confidence": pose.get("suggestion_confidence", 0),
            "pose_reasoning": pose.get("suggestion_reasoning", ""),
            "pose_footwork_left": pose.get("footwork_left"),
            "pose_footwork_right": pose.get("footwork_right"),
            "pose_parry_left": pose.get("parry_left"),
            "pose_parry_right": pose.get("parry_right"),
            "pose_distance": pose.get("distance_at_touch"),
            # Review status
            "is_reviewed": filename in self.reviewed,
            "reviewed_label": self.reviewed.get(filename, ""),
            "is_skipped": filename in self.skipped,
        }

        # Best suggestion (pose preferred over gemini)
        if pose.get("suggested_label"):
            label = pose["suggested_label"]
            parts = label.rsplit("_", 1)
            info["suggested_action"] = parts[0] if len(parts) == 2 else label
            info["suggested_direction"] = parts[1] if len(parts) == 2 else "unknown"
            info["suggested_label"] = label
            info["suggested_confidence"] = pose.get("suggestion_confidence", 0)
            info["suggested_reasoning"] = pose.get("suggestion_reasoning", "")
        elif gemini.get("combined_label"):
            info["suggested_action"] = gemini.get("action", "unknown")
            info["suggested_direction"] = gemini.get("direction", "unknown")
            info["suggested_label"] = gemini.get("combined_label", "unknown")
            info["suggested_confidence"] = gemini.get("confidence", 0)
            info["suggested_reasoning"] = gemini.get("reasoning", "")
        else:
            info["suggested_action"] = "unknown"
            info["suggested_direction"] = "unknown"
            info["suggested_label"] = "unknown"
            info["suggested_confidence"] = 0
            info["suggested_reasoning"] = ""

        return info

    def save_label(self, filename: str, action_label: str):
        """Save a human-reviewed label."""
        if action_label not in VALID_LABELS:
            raise ValueError(f"Invalid label: {action_label}")

        # Push to undo stack
        prev = self.reviewed.get(filename)
        self.history.append(("label", filename, prev))

        self.reviewed[filename] = action_label
        self.skipped.discard(filename)
        self._save_state()
        self._save_csv()

    def skip_clip(self, filename: str):
        """Mark clip as skipped."""
        self.history.append(("skip", filename, self.reviewed.get(filename)))
        self.skipped.add(filename)
        self._save_state()

    def undo(self) -> Optional[str]:
        """Undo last action. Returns filename that was undone."""
        if not self.history:
            return None

        action_type, filename, prev_label = self.history.pop()

        if action_type == "label":
            if prev_label is None:
                self.reviewed.pop(filename, None)
            else:
                self.reviewed[filename] = prev_label
        elif action_type == "skip":
            self.skipped.discard(filename)
            if prev_label is not None:
                self.reviewed[filename] = prev_label

        self._save_state()
        self._save_csv()
        return filename

    def get_next_unreviewed(self, current: int) -> int:
        """Find next unreviewed clip after current index."""
        for i in range(current + 1, len(self._sorted_files)):
            f = self._sorted_files[i]
            if f not in self.reviewed and f not in self.skipped:
                return i
        # Wrap around
        for i in range(0, current):
            f = self._sorted_files[i]
            if f not in self.reviewed and f not in self.skipped:
                return i
        return current

    def get_stats(self) -> dict:
        """Get labeling progress statistics."""
        from collections import Counter

        total = len(self._sorted_files)
        reviewed_count = len(self.reviewed)
        skipped_count = len(self.skipped)

        # Label distribution
        label_dist = Counter(self.reviewed.values())

        # Suggestion agreement rate (pose or gemini)
        agreements = 0
        for filename, label in self.reviewed.items():
            suggested = self._get_suggested_label(filename)
            if suggested == label:
                agreements += 1
        agreement_rate = agreements / reviewed_count if reviewed_count else 0

        return {
            "total": total,
            "reviewed": reviewed_count,
            "skipped": skipped_count,
            "remaining": total - reviewed_count - skipped_count,
            "progress_pct": round(reviewed_count / total * 100, 1) if total else 0,
            "label_distribution": dict(sorted(label_dist.items())),
            "suggestion_agreement_rate": round(agreement_rate * 100, 1),
            "data_source": self.data_source,
            "undo_available": len(self.history) > 0,
        }

    def set_sort(self, sort_by: str):
        """Change sort order."""
        if sort_by in ("confidence", "filename", "action"):
            self.sort_order = sort_by
            self._update_sort()
            self._save_state()


# --- FastAPI App ---

app = FastAPI(title="Fencing Clip Labeling Tool")
state = LabelingState()

# Serve clip videos
if CLIPS_DIR.exists():
    app.mount("/clips", StaticFiles(directory=str(CLIPS_DIR)), name="clips")


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve labeling UI."""
    if TEMPLATE_PATH.exists():
        return HTMLResponse(TEMPLATE_PATH.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Template not found</h1><p>Expected: templates/labeling.html</p>")


@app.get("/api/clip/{index}")
async def get_clip(index: int):
    """Get clip info at index."""
    info = state.get_clip_info(index)
    if info is None:
        return {"error": "Index out of range"}
    return info


@app.get("/api/next-unreviewed/{current}")
async def get_next_unreviewed(current: int):
    """Get next unreviewed clip index."""
    return {"index": state.get_next_unreviewed(current)}


@app.post("/api/label")
async def save_label(req: LabelRequest):
    """Save human label for a clip."""
    try:
        state.save_label(req.filename, req.action_label)
        return {"ok": True, "reviewed_count": len(state.reviewed)}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/skip")
async def skip_clip(req: SkipRequest):
    """Skip a clip."""
    state.skip_clip(req.filename)
    return {"ok": True}


@app.post("/api/undo")
async def undo():
    """Undo last label/skip action."""
    filename = state.undo()
    if filename is None:
        return {"ok": False, "error": "Nothing to undo"}
    # Find index of undone file
    idx = state._sorted_files.index(filename) if filename in state._sorted_files else 0
    return {"ok": True, "filename": filename, "index": idx}


@app.get("/api/stats")
async def get_stats():
    """Get labeling progress stats."""
    return state.get_stats()


@app.post("/api/sort")
async def set_sort(req: SortRequest):
    """Change clip sort order."""
    state.set_sort(req.sort_by)
    return {"ok": True, "sort_by": state.sort_order}


def main():
    print(f"\n{'='*60}")
    print(f"  Fencing Clip Labeling Tool")
    print(f"{'='*60}")
    print(f"  Data source:    {state.data_source}")
    if state.pose_results:
        print(f"  Pose results:   {POSE_RESULTS_PATH} ({len(state.pose_results)} clips)")
    if state.gemini_results:
        print(f"  Gemini results: {GEMINI_RESULTS_PATH} ({len(state.gemini_results)} clips)")
    print(f"  Clips dir:      {CLIPS_DIR}")
    print(f"  Output CSV:     {REVIEWED_CSV_PATH}")
    print(f"  Total clips:    {len(state._sorted_files)}")
    print(f"  Already reviewed: {len(state.reviewed)}")
    print(f"{'='*60}")
    print(f"  Open: http://localhost:7600")
    print(f"{'='*60}\n")

    uvicorn.run(app, host="0.0.0.0", port=7600)


if __name__ == "__main__":
    main()
