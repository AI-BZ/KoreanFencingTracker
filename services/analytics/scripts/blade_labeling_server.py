#!/usr/bin/env python3
"""Web tool for marking blade guards and tips on extracted 4K frames.

Feeds on what ``scripts/extract_blade_windows.py`` wrote. Two things get
labelled, at two different granularities:

  * per frame  - four points, in order: left guard, left tip, right guard,
                 right tip. A blade hidden behind a body or out of frame is
                 marked not-visible for that side instead of guessed at.
  * per window - did the blades touch during this phrase? contact / no_contact
                 / unclear, plus the frame the contact is on when there is one.

The frame labels are geometry for a detector; the window label is the answer a
priority judge actually needs. Both come from the same pass so a labeller only
watches each phrase once.

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
WINDOWS_CSV_HEADER = ["window_id", "contact_label", "contact_frame"]


# ----------------------------------------------------------------------
# Request models
# ----------------------------------------------------------------------


class FrameLabel(BaseModel):
    window_id: str
    frame: int
    points: Dict[str, Optional[List[float]]] = {}
    not_visible: Dict[str, bool] = {}
    skipped: bool = False


class WindowLabel(BaseModel):
    window_id: str
    contact_label: str
    contact_frame: Optional[int] = None


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
    """Read ``windows.csv`` back into memory. Missing file means nothing judged."""
    windows: Dict[str, dict] = {}
    if not path.exists():
        return windows
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            window_id = row.get("window_id")
            if not window_id:
                continue
            raw_frame = (row.get("contact_frame") or "").strip()
            windows[window_id] = {
                "window_id": window_id,
                "contact_label": row.get("contact_label") or "",
                "contact_frame": int(raw_frame) if raw_frame.isdigit() else None,
            }
    return windows


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


def write_windows_csv(path: Path, manifest: dict, window_labels: Dict[str, dict]) -> None:
    """Rewrite ``windows.csv`` in manifest order, judged windows only.

    Unlike the frame log this is rewritten rather than appended: there are tens
    of windows, one row each, and a reader that has to de-duplicate a log of
    them for no benefit is a reader that will get it wrong.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(WINDOWS_CSV_HEADER)
        for window in manifest.get("windows", []):
            label = window_labels.get(window["window_id"])
            if not label:
                continue
            writer.writerow([
                label["window_id"],
                label["contact_label"],
                "" if label.get("contact_frame") is None else label["contact_frame"],
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
                "label": self.window_labels.get(row["window_id"]),
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
            "ts": time.time(),
        }
        self.labels_path.parent.mkdir(parents=True, exist_ok=True)
        with self.labels_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.labels[row["frame"]] = row
        return row

    # -- windows -------------------------------------------------------

    def save_window_label(self, req: WindowLabel) -> dict:
        if req.window_id not in self.windows:
            raise ValueError(f"unknown window: {req.window_id}")
        if req.contact_label not in CONTACT_LABELS:
            raise ValueError(f"contact_label must be one of {CONTACT_LABELS}, got {req.contact_label!r}")
        frames = {f["source_frame"] for f in self.windows[req.window_id].get("frames", [])}
        if req.contact_frame is not None and req.contact_frame not in frames:
            raise ValueError(f"frame {req.contact_frame} is not in {req.window_id}")

        row = {
            "window_id": req.window_id,
            "contact_label": req.contact_label,
            "contact_frame": req.contact_frame,
        }
        self.window_labels[req.window_id] = row
        write_windows_csv(self.windows_path, self.manifest, self.window_labels)
        return row

    # -- progress ------------------------------------------------------

    def stats(self) -> dict:
        done = sum(1 for row in self.frames if is_frame_done(self.labels.get(row["frame"])))
        skipped = sum(
            1 for row in self.frames
            if (self.labels.get(row["frame"]) or {}).get("skipped")
        )
        contact_counts: Dict[str, int] = {}
        for label in self.window_labels.values():
            key = label["contact_label"]
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
            "windows_judged": len(self.window_labels),
            "contact_distribution": contact_counts,
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
  <span class="keys">
    <kbd>click</kbd> point &nbsp; <kbd>u</kbd> undo &nbsp; <kbd>s</kbd> skip &nbsp;
    <kbd>1</kbd>/<kbd>2</kbd> blade hidden L/R &nbsp; <kbd>c</kbd> contact frame &nbsp;
    <kbd>&larr;</kbd>/<kbd>&rarr;</kbd> prev/next &nbsp; <kbd>n</kbd> next unlabeled
  </span>
</header>
<div id="stage"><canvas id="main"></canvas><canvas id="mag" width="240" height="240"></canvas></div>
<div id="panel">
  <span class="slot" id="slot-lg">1 L guard</span>
  <span class="slot" id="slot-lt">2 L tip</span>
  <span class="slot" id="slot-rg">3 R guard</span>
  <span class="slot" id="slot-rt">4 R tip</span>
  <span class="muted">|</span>
  <span>window contact:</span>
  <button id="b-contact">contact</button>
  <button id="b-no">no_contact</button>
  <button id="b-unclear">unclear</button>
  <span class="muted" id="wlabel">-</span>
</div>
<div id="toast"></div>
<script>
const KEYS = ["lg","lt","rg","rt"];
const COLORS = {lg:"#5ab0ff", lt:"#5ab0ff", rg:"#ff7a5a", rt:"#ff7a5a"};
const MAG_ZOOM = 5;
let idx = 0, info = null, img = new Image(), pts = {}, hidden = {l:false,r:false};
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
  pts = {}; hidden = {l:false, r:false};
  if (info.label) {
    for (const k of KEYS) if (info.label.points && info.label.points[k]) pts[k] = info.label.points[k];
    hidden = {l: !!(info.label.not_visible||{}).l, r: !!(info.label.not_visible||{}).r};
  }
  img = new Image();
  img.onload = draw;
  img.src = info.image_url;
  const w = info.window;
  document.getElementById("pos").textContent =
    `${idx+1}/${info.total}  frame ${info.frame}  t=${info.time_sec}s`;
  document.getElementById("winfo").textContent =
    `${w.window_id} (${w.position}/${w.frame_count})  ${w.reasons.join(",")}  ${w.start_sec}-${w.end_sec}s`;
  paintWindowLabel();
  refreshStats();
}

function paintWindowLabel() {
  const l = info.window.label;
  document.getElementById("wlabel").textContent =
    l ? `${l.contact_label}${l.contact_frame != null ? " @ " + l.contact_frame : ""}` : "unjudged";
  for (const [id, val] of [["b-contact","contact"],["b-no","no_contact"],["b-unclear","unclear"]]) {
    document.getElementById(id).classList.toggle("on", !!l && l.contact_label === val);
  }
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
  if (!nextSlot()) save().then(() => go(idx + 1));
});

async function save(extra = {}) {
  const body = Object.assign({
    window_id: info.window_id, frame: info.frame,
    points: {lg: pts.lg||null, lt: pts.lt||null, rg: pts.rg||null, rt: pts.rt||null},
    not_visible: hidden, skipped: false,
  }, extra);
  const r = await fetch("/api/label", {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
  });
  if (!r.ok) toast("save failed");
  return r.json();
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
  const cur = info.window.label;
  const r = await fetch("/api/window", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({window_id: info.window_id,
                          contact_label: cur ? cur.contact_label : "contact",
                          contact_frame: info.frame}),
  });
  const out = await r.json();
  if (out.ok) { info.window.label = out.label; paintWindowLabel(); toast("contact @ " + info.frame); }
  else toast(out.error || "failed");
}

function go(i) { if (i >= 0 && i < info.total) load(i); }

async function refreshStats() {
  const s = await (await fetch("/api/stats")).json();
  document.getElementById("stats").textContent =
    `${s.frames_done}/${s.frames_total} frames (${s.progress_pct}%) · ${s.windows_judged}/${s.windows_total} windows`;
}

document.addEventListener("keydown", async (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const k = e.key.toLowerCase();
  if (k === "u") {
    for (let i = KEYS.length - 1; i >= 0; i--) if (pts[KEYS[i]]) { delete pts[KEYS[i]]; break; }
    draw();
  } else if (k === "s") {
    await save({skipped: true}); go(idx + 1);
  } else if (k === "1" || k === "2") {
    const side = k === "1" ? "l" : "r";
    hidden[side] = !hidden[side];
    if (hidden[side]) { delete pts[side + "g"]; delete pts[side + "t"]; }
    draw();
    if (!nextSlot() && (hidden.l || hidden.r)) { await save(); go(idx + 1); }
  } else if (k === "c") {
    await markContactFrame();
  } else if (k === "arrowright") { go(idx + 1); }
  else if (k === "arrowleft") { go(idx - 1); }
  else if (k === "n") {
    const r = await (await fetch(`/api/next-unlabeled/${idx + 1}`)).json();
    go(r.index);
  }
});

document.getElementById("b-contact").onclick = () => judge("contact");
document.getElementById("b-no").onclick = () => judge("no_contact");
document.getElementById("b-unclear").onclick = () => judge("unclear");
window.addEventListener("resize", () => { if (img.complete) draw(); });

(async () => {
  const r = await (await fetch("/api/next-unlabeled/0")).json();
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
        return HTMLResponse(PAGE_HTML)

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
