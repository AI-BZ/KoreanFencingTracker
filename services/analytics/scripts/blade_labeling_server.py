#!/usr/bin/env python3
"""Web tool for marking blade guards and tips on extracted 4K frames.

Feeds on what ``scripts/extract_blade_windows.py`` wrote. Two things get
labelled, at two different granularities:

  * per frame  - four points, in order: left guard, left tip, right guard,
                 right tip. A blade hidden behind a body or out of frame is
                 marked not-visible for that side instead of guessed at. The
                 frame also carries whether the blades met on it.
  * per window - did the blades touch during this phrase? no_contact / unclear
                 explicitly; contact is derived from the frames marked above,
                 since a phrase can hold several blade meetings.

The frame labels are geometry for a detector; the window verdict is the answer
a priority judge actually needs. Both come from the same pass so a labeller
only watches each phrase once.

Contact means the blades *changed each other*: a real one shows as the blade
leaving on a different path in the following frame. Two blades crossing in the
image are not touching — the projection hides depth — and a hit too soft to
deflect anything cannot carry a parry, so neither is marked.

Zoom is not optional here. A blade at 4K is around 200px long and a few px
wide, and the tip — the whole point of the exercise — is a handful of pixels.
The page carries a magnifier that follows the cursor at 5x, and the click lands
on the magnified pixel, not the fitted one.

Everything is written append-only to ``labels.jsonl``: relabelling a frame adds
a row rather than rewriting one, and the loader keeps the last row per frame.
Restarting the server therefore resumes exactly where the last one stopped, and
a crash mid-session cannot corrupt earlier work.

Usage:
    cd services/analytics
    PYTHONPATH=. .venv/bin/python3 scripts/blade_labeling_server.py \\
        --data-dir data/blade_labels/260716_de64_s1_piste3 --port 7777
    # then open http://localhost:7777
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import secrets
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

MANIFEST_NAME = "manifest.json"
LABELS_NAME = "labels.jsonl"
WINDOWS_NAME = "windows.csv"

POINT_KEYS = ("lg", "lt", "rg", "rt")
CONTACT_LABELS = ("contact", "no_contact", "unclear")
WINDOWS_CSV_HEADER = ["window_id", "contact_label", "contact_frames"]


# ----------------------------------------------------------------------
# Request models
# ----------------------------------------------------------------------


class FrameLabel(BaseModel):
    window_id: str
    frame: int
    points: Dict[str, Optional[List[float]]] = {}
    not_visible: Dict[str, bool] = {}
    skipped: bool = False
    contact: bool = False


class WindowLabel(BaseModel):
    window_id: str
    contact_label: str


# ----------------------------------------------------------------------
# Pure helpers
# ----------------------------------------------------------------------


def flatten_frames(manifest: dict) -> List[dict]:
    """Manifest -> flat, ordered list of every labellable frame.

    Order is manifest order: windows in time order, frames in time order. The
    labeller walks the bout forwards, which is the only order in which a
    contact judgement makes sense.
    """
    rows: List[dict] = []
    for window in manifest.get("windows", []):
        for frame in window.get("frames", []):
            rows.append({
                "window_id": window["window_id"],
                "file": frame["file"],
                "frame": frame["source_frame"],
                "work_frame": frame.get("work_frame"),
                "time_sec": frame.get("time_sec"),
            })
    return rows


def load_frame_labels(path: Path) -> Dict[int, dict]:
    """Replay the append-only label log, last row per frame wins.

    Malformed lines are skipped rather than fatal: the file is appended to
    live, so a session killed mid-write can leave a truncated last line, and
    losing one label is better than refusing to open the whole set.
    """
    labels: Dict[int, dict] = {}
    if not path.exists():
        return labels
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            frame = row.get("frame")
            if frame is None:
                continue
            labels[int(frame)] = row
    return labels


def load_window_labels(path: Path) -> Dict[str, dict]:
    """Read ``windows.csv`` back into memory. Missing file means nothing judged.

    Only the explicit verdict is read back. Which frames the blades met on
    lives on the frame labels, so it is derived rather than trusted from here;
    the ``contact_frames`` column exists for whoever reads the CSV downstream.
    """
    windows: Dict[str, dict] = {}
    if not path.exists():
        return windows
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            window_id = row.get("window_id")
            if not window_id:
                continue
            windows[window_id] = {
                "window_id": window_id,
                "contact_label": row.get("contact_label") or "",
            }
    return windows


def build_stamp() -> str:
    """A visible marker of which build of this page is on screen.

    Stale-cache confusion costs more than the stamp does: with it, "the fix is
    not working" and "you are looking at the old page" can be told apart in one
    glance instead of an hour.
    """
    try:
        return time.strftime("%m-%d %H:%M", time.localtime(Path(__file__).stat().st_mtime))
    except OSError:
        return "unknown"


def frame_has_contact(label: Optional[dict]) -> bool:
    """Did the labeller mark the blades as meeting on this frame?"""
    return bool(label and label.get("contact"))


def is_frame_done(label: Optional[dict]) -> bool:
    """A frame counts as done when it is skipped, or every side is resolved.

    Resolved means: two points marked, or the side declared not visible.
    Anything partial stays in the queue — a half-labelled frame is worse than
    an unlabelled one because it looks finished in the counts.
    """
    if not label:
        return False
    if label.get("skipped"):
        return True
    points = label.get("points") or {}
    not_visible = label.get("not_visible") or {}
    for side, keys in (("l", ("lg", "lt")), ("r", ("rg", "rt"))):
        if not_visible.get(side):
            continue
        if not all(points.get(key) for key in keys):
            return False
    return True


def next_unlabeled_index(frames: Sequence[dict], labels: Dict[int, dict], start: int) -> int:
    """First frame at or after ``start`` that still needs work; wraps once."""
    total = len(frames)
    if total == 0:
        return 0
    for offset in range(total):
        index = (max(0, start) + offset) % total
        if not is_frame_done(labels.get(frames[index]["frame"])):
            return index
    return max(0, min(start, total - 1))


def write_windows_csv(
    path: Path,
    manifest: dict,
    window_labels: Dict[str, dict],
    contact_frames: Optional[Dict[str, List[int]]] = None,
) -> None:
    """Rewrite ``windows.csv`` in manifest order, judged windows only.

    Unlike the frame log this is rewritten rather than appended: there are tens
    of windows, one row each, and a reader that has to de-duplicate a log of
    them for no benefit is a reader that will get it wrong.

    A window with any frame marked as contact is written as a contact whatever
    the explicit verdict says — the marked frames are the more specific claim,
    and they are what a downstream reader wants anyway.
    """
    contact_frames = contact_frames or {}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(WINDOWS_CSV_HEADER)
        for window in manifest.get("windows", []):
            window_id = window["window_id"]
            label = window_labels.get(window_id)
            frames = contact_frames.get(window_id) or []
            if not label and not frames:
                continue
            verdict = "contact" if frames else (label or {}).get("contact_label", "")
            writer.writerow([
                window_id,
                verdict,
                ";".join(str(f) for f in frames),
            ])


# ----------------------------------------------------------------------
# State
# ----------------------------------------------------------------------


class BladeLabelingState:
    """Manifest, frame labels and window judgements for one extracted bout."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.manifest_path = data_dir / MANIFEST_NAME
        self.labels_path = data_dir / LABELS_NAME
        self.windows_path = data_dir / WINDOWS_NAME

        if not self.manifest_path.exists():
            raise FileNotFoundError(
                f"no {MANIFEST_NAME} in {data_dir} — run scripts/extract_blade_windows.py first"
            )
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.frames = flatten_frames(self.manifest)
        self.index_by_frame = {row["frame"]: i for i, row in enumerate(self.frames)}
        self.windows = {w["window_id"]: w for w in self.manifest.get("windows", [])}
        self.labels = load_frame_labels(self.labels_path)
        self.window_labels = load_window_labels(self.windows_path)
        if self.window_labels or any(frame_has_contact(l) for l in self.labels.values()):
            # The CSV is derived state. Rewriting it once at startup migrates
            # an older schema and repairs any hand edit, so the file on disk
            # always agrees with the labels it is supposed to summarise.
            self._flush_windows_csv()

    # -- frames --------------------------------------------------------

    def frame_info(self, index: int) -> Optional[dict]:
        if index < 0 or index >= len(self.frames):
            return None
        row = dict(self.frames[index])
        window = self.windows.get(row["window_id"], {})
        window_frames = window.get("frames", [])
        row.update({
            "index": index,
            "total": len(self.frames),
            "image_url": f"/image/{row['window_id']}/{row['file']}",
            "label": self.labels.get(row["frame"]),
            "done": is_frame_done(self.labels.get(row["frame"])),
            "window": {
                "window_id": row["window_id"],
                "reasons": window.get("reasons", []),
                "start_sec": window.get("start_sec"),
                "end_sec": window.get("end_sec"),
                "crop": window.get("crop"),
                "crop_source": window.get("crop_source"),
                "frame_count": len(window_frames),
                "position": next(
                    (i + 1 for i, f in enumerate(window_frames) if f["source_frame"] == row["frame"]), None
                ),
                "label": self.window_verdict(row["window_id"]),
            },
        })
        return row

    def save_frame_label(self, req: FrameLabel) -> dict:
        if req.window_id not in self.windows:
            raise ValueError(f"unknown window: {req.window_id}")
        if req.frame not in self.index_by_frame:
            raise ValueError(f"unknown frame: {req.frame}")

        points: Dict[str, Optional[List[float]]] = {}
        for key in POINT_KEYS:
            value = req.points.get(key)
            if value is None:
                points[key] = None
                continue
            if len(value) != 2:
                raise ValueError(f"point {key} must be [x, y], got {value!r}")
            points[key] = [round(float(value[0]), 1), round(float(value[1]), 1)]

        row = {
            "frame": int(req.frame),
            "window_id": req.window_id,
            "points": points,
            "not_visible": {"l": bool(req.not_visible.get("l")), "r": bool(req.not_visible.get("r"))},
            "skipped": bool(req.skipped),
            "contact": bool(req.contact),
            "ts": time.time(),
        }
        self.labels_path.parent.mkdir(parents=True, exist_ok=True)
        with self.labels_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.labels[row["frame"]] = row
        # The window verdict is derived from these flags, so the CSV has to
        # follow every frame that gains or loses one.
        self._flush_windows_csv()
        return row

    # -- windows -------------------------------------------------------

    def window_contact_frames(self, window_id: str) -> List[int]:
        """Frames in this window the labeller marked as blade contact, in order."""
        window = self.windows.get(window_id) or {}
        return [
            f["source_frame"]
            for f in window.get("frames", [])
            if frame_has_contact(self.labels.get(f["source_frame"]))
        ]

    def window_verdict(self, window_id: str) -> Optional[dict]:
        """The window's judgement, with marked contact frames folded in.

        Marked frames win over the stored verdict. A verdict is per window but
        the labeller works frame by frame, so a no_contact pressed later in the
        same phrase used to silently erase a contact marked earlier in it.
        """
        frames = self.window_contact_frames(window_id)
        stored = self.window_labels.get(window_id)
        if frames:
            return {"window_id": window_id, "contact_label": "contact", "contact_frames": frames}
        if stored:
            return {**stored, "contact_frames": []}
        return None

    def save_window_label(self, req: WindowLabel) -> dict:
        if req.window_id not in self.windows:
            raise ValueError(f"unknown window: {req.window_id}")
        if req.contact_label not in CONTACT_LABELS:
            raise ValueError(f"contact_label must be one of {CONTACT_LABELS}, got {req.contact_label!r}")
        marked = self.window_contact_frames(req.window_id)
        if marked and req.contact_label != "contact":
            # Refusing beats overwriting: the marked frames are a specific
            # claim about specific images, and a sweeping verdict pressed
            # afterwards should not be able to delete them by accident.
            raise ValueError(
                f"{req.window_id} has contact marked on frame(s) "
                f"{', '.join(str(f) for f in marked)} — clear those first (c) "
                f"to judge it {req.contact_label}"
            )

        row = {"window_id": req.window_id, "contact_label": req.contact_label}
        self.window_labels[req.window_id] = row
        self._flush_windows_csv()
        return {**row, "contact_frames": marked}

    def _flush_windows_csv(self) -> None:
        contact_frames = {
            window_id: self.window_contact_frames(window_id) for window_id in self.windows
        }
        write_windows_csv(self.windows_path, self.manifest, self.window_labels, contact_frames)

    # -- progress ------------------------------------------------------

    def stats(self) -> dict:
        done = sum(1 for row in self.frames if is_frame_done(self.labels.get(row["frame"])))
        skipped = sum(
            1 for row in self.frames
            if (self.labels.get(row["frame"]) or {}).get("skipped")
        )
        contact_counts: Dict[str, int] = {}
        judged = 0
        for window_id in self.windows:
            verdict = self.window_verdict(window_id)
            if not verdict:
                continue
            judged += 1
            key = verdict["contact_label"]
            contact_counts[key] = contact_counts.get(key, 0) + 1
        total = len(self.frames)
        return {
            "report_id": self.manifest.get("report_id"),
            "frames_total": total,
            "frames_done": done,
            "frames_skipped": skipped,
            "frames_remaining": total - done,
            "progress_pct": round(done / total * 100, 1) if total else 0.0,
            "windows_total": len(self.windows),
            "windows_judged": judged,
            "contact_distribution": contact_counts,
            "contact_frames_total": sum(
                1 for row in self.frames if frame_has_contact(self.labels.get(row["frame"]))
            ),
        }


# ----------------------------------------------------------------------
# Page
# ----------------------------------------------------------------------

PAGE_HTML = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>Blade labeling</title>
<style>
  :root { color-scheme: dark; }
  body { margin:0; background:#111418; color:#e6e9ee; font:13px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
  header { display:flex; gap:18px; align-items:baseline; padding:8px 14px; background:#171b21; border-bottom:1px solid #262c35; flex-wrap:wrap; }
  header b { font-size:14px; }
  .muted { color:#8b95a3; }
  #stage { position:relative; padding:10px 14px; }
  canvas#main { max-width:100%; cursor:crosshair; background:#000; }
  #mag { position:fixed; width:240px; height:240px; border:2px solid #4d5867; border-radius:4px; pointer-events:none; display:none; background:#000; z-index:20; }
  #panel { display:flex; gap:22px; padding:8px 14px; flex-wrap:wrap; align-items:center; border-top:1px solid #262c35; }
  .slot { padding:2px 8px; border-radius:3px; border:1px solid #333b46; }
  .slot.next { border-color:#e8b04b; color:#e8b04b; }
  .slot.filled { border-color:#4d9f5f; color:#79d18c; }
  .slot.hidden { border-color:#3a3f47; color:#6a7480; text-decoration:line-through; }
  .keys { color:#8b95a3; }
  .rule { display:block; width:100%; margin-top:4px; color:#b9c4d4; font-size:12px; line-height:1.5; }
  #jump { width:170px; background:#151a21; color:#e6ecf3; border:1px solid #39424e;
          border-radius:3px; padding:3px 7px; font:inherit; font-size:12px; }
  #jump::placeholder { color:#6b7684; }
  .mark { margin-left:6px; background:#3a2130; border:1px solid #7d3350; color:#ffb3c8;
          border-radius:3px; padding:2px 8px; cursor:pointer; font:inherit; font-size:12px; }
  .mark.here { background:#7d3350; color:#fff; }
  #fcontact { padding:2px 8px; border-radius:3px; border:1px solid #39424e; color:#8b95a3; }
  #fcontact.on { background:#7d3350; border-color:#a3455f; color:#fff; }
  .keys kbd { background:#232a33; border:1px solid #39424e; border-radius:3px; padding:0 5px; }
  button { background:#232a33; color:#e6e9ee; border:1px solid #39424e; border-radius:4px; padding:4px 10px; cursor:pointer; }
  button.on { background:#2f6b46; border-color:#3f8b5c; }
  #toast { position:fixed; right:14px; bottom:14px; background:#232a33; border:1px solid #39424e; border-radius:4px; padding:6px 12px; display:none; z-index:30; }
</style>
</head>
<body>
<header>
  <b id="pos">-</b>
  <span class="muted" id="winfo">-</span>
  <span class="muted" id="stats">-</span>
  <span class="muted" title="이 페이지 버전">build __BUILD__</span>
  <span class="keys">
    <kbd>click</kbd> point &nbsp; <kbd>u</kbd> undo &nbsp; <kbd>s</kbd> skip &nbsp; <kbd>r</kbd> repeat prev &nbsp;
    <kbd>1</kbd>/<kbd>2</kbd> blade hidden L/R &nbsp; <kbd>c</kbd> 이 프레임 접촉 표시/해제 &nbsp;
    <kbd>&larr;</kbd>/<kbd>&rarr;</kbd> &plusmn;1 &nbsp; <kbd>,</kbd>/<kbd>.</kbd> &plusmn;10 &nbsp;
    <kbd>&lt;</kbd>/<kbd>&gt;</kbd> &plusmn;20 &nbsp; <kbd>g</kbd> 프레임 이동 &nbsp; <kbd>n</kbd> next unlabeled
  </span>
  <span class="rule">접촉 = 다음 프레임에서 블레이드 경로가 바뀐 것. 화면상 교차만으로는 접촉이 아니고,
    튕김이 안 보일 만큼 약한 접촉은 빠라드가 못 되므로 no_contact.</span>
</header>
<div id="stage"><canvas id="main"></canvas><canvas id="mag" width="240" height="240"></canvas></div>
<div id="panel">
  <span class="slot" id="slot-lg">1 L guard</span>
  <span class="slot" id="slot-lt">2 L tip</span>
  <span class="slot" id="slot-rg">3 R guard</span>
  <span class="slot" id="slot-rt">4 R tip</span>
  <span class="muted">|</span>
  <input id="jump" type="text" placeholder="frame 4478 · 순번 #476" autocomplete="off">
  <span class="muted">|</span>
  <span id="fcontact">이 프레임: -</span>
  <span class="muted">|</span>
  <span>창 판정:</span>
  <button id="b-contact">contact</button>
  <button id="b-no">no_contact</button>
  <button id="b-unclear">unclear</button>
  <span class="muted" id="wlabel">-</span>
  <span id="marks"></span>
</div>
<div id="toast"></div>
<script>
const KEYS = ["lg","lt","rg","rt"];
const COLORS = {lg:"#5ab0ff", lt:"#5ab0ff", rg:"#ff7a5a", rt:"#ff7a5a"};
const MAG_ZOOM = 5;
let idx = 0, info = null, img = new Image(), pts = {}, hidden = {l:false,r:false}, contact = false;
let busy = false;  // one async key action at a time — key auto-repeat plus network latency otherwise double-fires handlers
let fit = 1, mouse = null;

const cv = document.getElementById("main"), ctx = cv.getContext("2d");
const mag = document.getElementById("mag"), mctx = mag.getContext("2d");

function toast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg; el.style.display = "block";
  clearTimeout(el._t); el._t = setTimeout(() => el.style.display = "none", 1400);
}

function nextSlot() {
  for (const k of KEYS) {
    if (hidden[k[0]]) continue;
    if (!pts[k]) return k;
  }
  return null;
}

async function load(i) {
  const r = await fetch(`/api/frame/${i}`);
  if (!r.ok) return;
  info = await r.json();
  idx = info.index;
  pts = {}; hidden = {l:false, r:false}; contact = false;
  if (info.label) {
    contact = !!info.label.contact;
    for (const k of KEYS) if (info.label.points && info.label.points[k]) pts[k] = info.label.points[k];
    hidden = {l: !!(info.label.not_visible||{}).l, r: !!(info.label.not_visible||{}).r};
  }
  img = new Image();
  img.onload = draw;
  img.src = info.image_url;
  const w = info.window;
  document.getElementById("pos").textContent =
    // Two numbers, and they get confused for each other: the queue position
    // is what a labeller reads off the screen, the source frame is what every
    // saved label and every downstream tool refers to. Name both.
    `순번 ${idx+1}/${info.total} · 원본 frame ${info.frame} · t=${info.time_sec}s`;
  document.getElementById("winfo").textContent =
    `${w.window_id} (${w.position}/${w.frame_count})  ${w.reasons.join(",")}  ${w.start_sec}-${w.end_sec}s`;
  paintWindowLabel();
  refreshStats();
}

function paintWindowLabel() {
  const l = info.window.label;
  const marks = (l && l.contact_frames) || [];
  document.getElementById("wlabel").textContent = l ? l.contact_label : "unjudged";
  for (const [id, val] of [["b-contact","contact"],["b-no","no_contact"],["b-unclear","unclear"]]) {
    document.getElementById(id).classList.toggle("on", !!l && l.contact_label === val);
  }
  // The verdict belongs to the whole phrase, so it shows on every frame of it
  // and reads as a claim about the frame on screen. Say which frame carries
  // the mark, make it one click away, and state this frame's own answer.
  const box = document.getElementById("marks");
  box.textContent = "";
  for (const f of marks) {
    const b = document.createElement("button");
    b.className = "mark" + (f === info.frame ? " here" : "");
    b.textContent = "접촉 " + f;
    b.title = "이 프레임으로 이동 (c 로 해제)";
    b.onclick = async () => {
      const r = await fetch(`/api/locate/${f}`);
      if (r.ok) go((await r.json()).index);
    };
    box.appendChild(b);
  }
  const fc = document.getElementById("fcontact");
  fc.textContent = contact ? "이 프레임: 접촉 ✓" : "이 프레임: 접촉 아님";
  fc.classList.toggle("on", contact);
}

function draw() {
  const maxW = window.innerWidth - 28;
  fit = Math.min(1, maxW / img.naturalWidth);
  cv.width = Math.round(img.naturalWidth * fit);
  cv.height = Math.round(img.naturalHeight * fit);
  ctx.drawImage(img, 0, 0, cv.width, cv.height);
  drawMarks(ctx, fit);
  paintSlots();
}

function drawMarks(c, scale, ox = 0, oy = 0) {
  for (const side of [["lg","lt"],["rg","rt"]]) {
    const g = pts[side[0]], t = pts[side[1]];
    if (g && t) {
      c.strokeStyle = COLORS[side[0]]; c.lineWidth = 2;
      c.beginPath();
      c.moveTo(g[0]*scale-ox, g[1]*scale-oy);
      c.lineTo(t[0]*scale-ox, t[1]*scale-oy);
      c.stroke();
    }
  }
  for (const k of KEYS) {
    const p = pts[k];
    if (!p) continue;
    const x = p[0]*scale-ox, y = p[1]*scale-oy;
    c.fillStyle = COLORS[k];
    c.beginPath();
    c.arc(x, y, k.endsWith("t") ? 3 : 5, 0, Math.PI*2);
    c.fill();
    c.strokeStyle = "#000"; c.lineWidth = 1; c.stroke();
  }
}

function paintSlots() {
  const nxt = nextSlot();
  for (const k of KEYS) {
    const el = document.getElementById("slot-" + k);
    el.className = "slot" + (hidden[k[0]] ? " hidden" : pts[k] ? " filled" : k === nxt ? " next" : "");
  }
}

cv.addEventListener("mousemove", (e) => {
  const r = cv.getBoundingClientRect();
  mouse = {cx: e.clientX, cy: e.clientY,
           nx: (e.clientX - r.left) / (r.width / img.naturalWidth),
           ny: (e.clientY - r.top) / (r.height / img.naturalHeight)};
  const half = mag.width / (2 * MAG_ZOOM);
  mctx.imageSmoothingEnabled = false;
  mctx.fillStyle = "#000"; mctx.fillRect(0, 0, mag.width, mag.height);
  mctx.drawImage(img, mouse.nx - half, mouse.ny - half, half*2, half*2, 0, 0, mag.width, mag.height);
  drawMarks(mctx, MAG_ZOOM, (mouse.nx - half) * MAG_ZOOM, (mouse.ny - half) * MAG_ZOOM);
  mctx.strokeStyle = "#e8b04b"; mctx.lineWidth = 1;
  mctx.beginPath();
  mctx.moveTo(mag.width/2, 0); mctx.lineTo(mag.width/2, mag.height);
  mctx.moveTo(0, mag.height/2); mctx.lineTo(mag.width, mag.height/2);
  mctx.stroke();
  mag.style.display = "block";
  mag.style.left = Math.min(window.innerWidth - 250, e.clientX + 18) + "px";
  mag.style.top = Math.max(6, e.clientY - 258) + "px";
});
cv.addEventListener("mouseleave", () => { mag.style.display = "none"; mouse = null; });

cv.addEventListener("click", (e) => {
  const slot = nextSlot();
  if (!slot) { toast("all points set — press u to undo"); return; }
  const r = cv.getBoundingClientRect();
  pts[slot] = [(e.clientX - r.left) / (r.width / img.naturalWidth),
               (e.clientY - r.top) / (r.height / img.naturalHeight)];
  draw();
  if (!nextSlot()) save().then((out) => { if (out) go(idx + 1); });
});

async function save(extra = {}) {
  const body = Object.assign({
    window_id: info.window_id, frame: info.frame,
    points: {lg: pts.lg||null, lt: pts.lt||null, rg: pts.rg||null, rt: pts.rt||null},
    not_visible: hidden, skipped: false, contact: contact,
  }, extra);
  try {
    const r = await fetch("/api/label", {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
    });
    if (!r.ok) { toast(`저장 실패 (${r.status}) — 다시 시도하세요`); return null; }
    return await r.json();
  } catch (err) {
    // Server briefly down (restart, network blip): stay on this frame so the
    // labeller retries instead of silently losing the row and advancing.
    toast("저장 실패 — 서버 연결 안 됨, 다시 시도하세요");
    return null;
  }
}

async function judge(label) {
  const r = await fetch("/api/window", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({window_id: info.window_id, contact_label: label,
                          contact_frame: info.window.label ? info.window.label.contact_frame : null}),
  });
  const out = await r.json();
  if (out.ok) { info.window.label = out.label; paintWindowLabel(); toast(label); }
  else toast(out.error || "failed");
}

async function markContactFrame() {
  // Contact belongs to the frame, not to the phrase: a phrase can hold several
  // blade meetings, and the window verdict is derived from these marks so a
  // later keystroke elsewhere in the phrase cannot erase one.
  contact = !contact;
  const out = await save();
  if (!out) { contact = !contact; return; }
  const fresh = await (await fetch(`/api/frame/${idx}`)).json();
  info.window = fresh.window;
  paintWindowLabel(); draw();
  toast(contact ? `접촉 표시 @ ${info.frame}` : `접촉 해제 @ ${info.frame}`);
}

function go(i) { if (i >= 0 && i < info.total) return load(i); }

/** Step by n frames, clamped to the ends rather than refusing near them. */
function step(n) {
  const target = Math.max(0, Math.min(info.total - 1, idx + n));
  if (target !== idx) return load(target);
}

/** "4478" is a source frame, "#476" a queue position; a bare number that is
 *  no frame falls back to the position rather than just failing. */
async function jumpTo(raw) {
  const text = (raw || "").trim();
  if (!text) return;
  const m = text.match(/^#?\s*(\d+)$/);
  if (!m) { toast("숫자를 입력하세요 (예: 4478 또는 #476)"); return; }
  const n = parseInt(m[1], 10);
  if (text.startsWith("#")) {
    if (n < 1 || n > info.total) { toast(`순번은 1-${info.total} 범위입니다`); return; }
    await go(n - 1);
    toast(`순번 ${n}`);
    return;
  }
  const r = await fetch(`/api/locate/${n}`);
  if (r.ok) {
    const out = await r.json();
    await go(out.index);
    toast(`원본 frame ${n}`);
    return;
  }
  if (n >= 1 && n <= info.total) {
    await go(n - 1);
    toast(`frame ${n} 없음 → 순번 ${n}로 이동`);
    return;
  }
  toast(`frame ${n}을 찾을 수 없습니다`);
}

async function refreshStats() {
  const s = await (await fetch("/api/stats")).json();
  document.getElementById("stats").textContent =
    `${s.frames_done}/${s.frames_total} frames (${s.progress_pct}%) · ${s.windows_judged}/${s.windows_total} windows`;
}

document.addEventListener("keydown", async (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.target && e.target.id === "jump") return;
  const k = e.key.toLowerCase();
  // Holding a key must not queue concurrent async handlers: over a
  // high-latency link the interleaved saves double-write one frame and
  // stride past the next. Arrows are safe (no writes) and want repeat.
  const NAV = ["arrowleft", "arrowright", ",", ".", "<", ">"];
  if (busy && !NAV.includes(k)) return;
  if (e.repeat && (k === "r" || k === "s" || k === "n" || k === "c")) return;
  if (k === "u") {
    for (let i = KEYS.length - 1; i >= 0; i--) if (pts[KEYS[i]]) { delete pts[KEYS[i]]; break; }
    draw();
  } else if (k === "s") {
    busy = true;
    try { if (await save({skipped: true})) await go(idx + 1); } finally { busy = false; }
  } else if (k === "r") {
    // Static stretches: copy labels from the nearest labelled frame earlier
    // in the same window — a copied label is a free correct sample, where a
    // skip would just discard the frame. Searching backwards (not only idx-1)
    // rides over frames a race or a skip left unlabelled. Same-window only:
    // each window has its own crop box, so pixel coordinates do not carry
    // across the boundary.
    busy = true;
    try {
      let pl = null;
      for (let j = idx - 1; j >= 0; j--) {
        const prev = await (await fetch(`/api/frame/${j}`)).json();
        if (prev.window_id !== info.window_id) break;
        const cand = prev.label;
        if (cand && !cand.skipped && cand.points && Object.values(cand.points).some(Boolean)) { pl = cand; break; }
      }
      if (!pl) { toast("no labeled frame earlier in this window"); return; }
      pts = {...pl.points};
      hidden = {l: !!(pl.not_visible||{}).l, r: !!(pl.not_visible||{}).r};
      contact = false;  // contact is a claim about this frame, never copied
      draw();
      if (!(await save())) return;
      toast(`copied frame ${pl.frame} → saved`);
      await go(idx + 1);
    } finally { busy = false; }
  } else if (k === "1" || k === "2") {
    const side = k === "1" ? "l" : "r";
    hidden[side] = !hidden[side];
    if (hidden[side]) { delete pts[side + "g"]; delete pts[side + "t"]; }
    draw();
    if (!nextSlot() && (hidden.l || hidden.r)) { if (await save()) go(idx + 1); }
  } else if (k === "c") {
    await markContactFrame();
  } else if (k === "arrowright") { step(1); }
  else if (k === "arrowleft") { step(-1); }
  else if (k === ".") { step(10); }
  else if (k === ",") { step(-10); }
  else if (k === ">") { step(20); }
  else if (k === "<") { step(-20); }
  else if (k === "g") { e.preventDefault(); document.getElementById("jump").focus(); }
  else if (k === "n") {
    const r = await (await fetch(`/api/next-unlabeled/${idx + 1}`)).json();
    go(r.index);
  }
});

document.getElementById("jump").addEventListener("keydown", async (e) => {
  if (e.key === "Enter") { const v = e.target.value; e.target.value = ""; e.target.blur(); await jumpTo(v); }
  else if (e.key === "Escape") { e.target.value = ""; e.target.blur(); }
});

document.getElementById("b-contact").onclick = () => judge("contact");
document.getElementById("b-no").onclick = () => judge("no_contact");
document.getElementById("b-unclear").onclick = () => judge("unclear");
window.addEventListener("resize", () => { if (img.complete) draw(); });

(async () => {
  const r = await (await fetch("/api/resume")).json();
  load(r.index);
})();
</script>
</body>
</html>
"""


# ----------------------------------------------------------------------
# App
# ----------------------------------------------------------------------


def create_app(state: BladeLabelingState, token: Optional[str] = None) -> FastAPI:
    app = FastAPI(title="Blade Labeling Tool")

    if token:
        # The frames behind this server are private footage; when the port is
        # exposed beyond localhost every request must carry the shared token,
        # either as ?token=... (first visit — we then set a cookie so the
        # in-page fetch() calls inherit it) or as the cookie itself.
        @app.middleware("http")
        async def _require_token(request: Request, call_next):
            supplied = request.query_params.get("token") or request.cookies.get("blade_token") or ""
            if not secrets.compare_digest(supplied, token):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            response = await call_next(request)
            if request.query_params.get("token"):
                response.set_cookie("blade_token", token, httponly=True, samesite="lax", max_age=7 * 86400)
            return response

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        # The page is one inline document that changes whenever this file does,
        # and a browser holding yesterday's copy keeps yesterday's bugs — which
        # is indistinguishable, from the labeller's side, from the fix never
        # having been made. Never let it be cached.
        return HTMLResponse(
            PAGE_HTML.replace("__BUILD__", build_stamp()),
            headers={"Cache-Control": "no-store, must-revalidate", "Pragma": "no-cache"},
        )

    @app.get("/api/resume")
    async def resume() -> dict:
        # Where a refreshed page should land: the first frame still needing
        # work at or after the most recently *saved* frame — not the first gap
        # in the whole set, which yanks the labeller back to wherever a skip
        # or race left a hole.
        start = 0
        if state.labels:
            latest = max(state.labels.values(), key=lambda row: row.get("ts") or 0)
            start = state.index_by_frame.get(latest.get("frame"), 0)
        return {"index": next_unlabeled_index(state.frames, state.labels, start)}

    @app.get("/api/stats")
    async def stats() -> dict:
        return state.stats()

    @app.get("/api/frames")
    async def frames() -> dict:
        return {
            "total": len(state.frames),
            "frames": [
                {**row, "index": i, "done": is_frame_done(state.labels.get(row["frame"]))}
                for i, row in enumerate(state.frames)
            ],
        }

    @app.get("/api/frame/{index}")
    async def frame(index: int):
        info = state.frame_info(index)
        if info is None:
            return JSONResponse({"error": "index out of range"}, status_code=404)
        return info

    @app.get("/api/locate/{frame}")
    async def locate(frame: int):
        """Queue position of a source frame, for jump-to-frame.

        Only source frames resolve here. A queue position is a property of the
        page, not of the data, so the client handles that half itself.
        """
        index = state.index_by_frame.get(frame)
        if index is None:
            return JSONResponse({"error": f"frame {frame} is not in this set"}, status_code=404)
        return {"index": index, "frame": frame}

    @app.get("/api/next-unlabeled/{start}")
    async def next_unlabeled(start: int) -> dict:
        return {"index": next_unlabeled_index(state.frames, state.labels, start)}

    @app.get("/image/{window_id}/{filename}")
    async def image(window_id: str, filename: str):
        # Both parts are matched against the manifest rather than joined onto
        # the data dir: an unchecked path segment here would serve any file on
        # the machine to anything that can reach the port.
        window = state.windows.get(window_id)
        if not window or not any(f["file"] == filename for f in window.get("frames", [])):
            return JSONResponse({"error": "unknown frame"}, status_code=404)
        path = state.data_dir / window_id / filename
        if not path.exists():
            return JSONResponse({"error": "file missing on disk"}, status_code=404)
        return FileResponse(path, media_type="image/jpeg")

    @app.post("/api/label")
    async def label(req: FrameLabel):
        try:
            row = state.save_frame_label(req)
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        return {"ok": True, "label": row, "done": is_frame_done(row)}

    @app.post("/api/window")
    async def window(req: WindowLabel):
        try:
            row = state.save_window_label(req)
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        return {"ok": True, "label": row}

    return app


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Label blade guards and tips on extracted 4K frames.")
    parser.add_argument("--data-dir", required=True, type=Path, help="directory written by extract_blade_windows.py")
    parser.add_argument("--port", type=int, default=7777)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--token",
        default=os.environ.get("BLADE_LABEL_TOKEN") or None,
        help="require this access token on every request (default: $BLADE_LABEL_TOKEN; unset = no auth, localhost only)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    state = BladeLabelingState(args.data_dir)
    stats = state.stats()
    print("=" * 60)
    print("  Blade Labeling Tool")
    print("=" * 60)
    print(f"  Data dir:  {args.data_dir}")
    print(f"  Report:    {stats['report_id']}")
    print(f"  Frames:    {stats['frames_done']}/{stats['frames_total']} labelled ({stats['progress_pct']}%)")
    print(f"  Windows:   {stats['windows_judged']}/{stats['windows_total']} judged")
    print(f"  Labels:    {state.labels_path}")
    print(f"  Windows:   {state.windows_path}")
    print(f"  Open:      http://{args.host}:{args.port}")
    print("=" * 60)
    if args.token:
        print("  Auth:      token required (?token=... on first visit)")
    elif args.host not in ("127.0.0.1", "localhost"):
        print("  Auth:      ⚠️  NONE — non-localhost bind without --token")
    uvicorn.run(create_app(state, token=args.token), host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
