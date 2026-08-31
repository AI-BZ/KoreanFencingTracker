/**
 * FencingMind Analytics — video workbench.
 *
 * A single <video> stage that the whole page drives: the timeline seeks it, the
 * AI buttons swap a generated overlay clip into it, and the tools (speed,
 * frame stepping, zoom/pan, drawing, BH measuring) act on whatever is playing.
 * That is the whole design — the workbench is a shell around "the currently
 * active video", so main footage and on-demand clips get the same toolset.
 *
 * Coordinates: every drawn shape is stored in the video's own pixel space
 * (videoWidth x videoHeight), which is also the pixel space the pose pipeline
 * analysed. One scale factor (stage width / videoWidth) converts screen to
 * intrinsic, so zoom, pan and window resizes all fall out of the same line.
 *
 * No external libraries.
 */
(function () {
    'use strict';

    var root = document.getElementById('workbench');
    if (!root) return;

    var cfg = window.FM_REPORT || {};
    var FPS = Number(cfg.fps) > 0 ? Number(cfg.fps) : 30;
    var CLIP_REPORT_ID = cfg.clipReportId || null;
    var CLIP_TOKEN = cfg.clipToken || null;
    var KEYPOINTS_URL = cfg.keypointsUrl || null;

    var SPEEDS = [1, 0.5, 0.25, 1 / 6];
    var ZOOM_MIN = 1;
    var ZOOM_MAX = 8;
    var LOOP_TAIL_SEC = 0.3;          // let the end of the action land before looping
    var TOUCH_LEAD_SEC = 3;           // touch rows without a matched exchange
    var TOUCH_TAIL_SEC = 1;
    var COLLAPSE_KEY = 'fm-workbench-collapsed';
    var SKELETON_KEY = 'fm-workbench-skeleton';
    var MUTE_KEY = 'fm-workbench-muted';

    // COCO-17 joint order, as documented by the keypoints endpoint:
    // 0 nose, 1/2 eyes, 3/4 ears, 5/6 shoulders, 7/8 elbows, 9/10 wrists,
    // 11/12 hips, 13/14 knees, 15/16 ankles.
    var SKELETON_EDGES = [
        [5, 7], [7, 9], [6, 8], [8, 10],            // arms — the weapon side
        [5, 6], [5, 11], [6, 12], [11, 12],         // torso box
        [11, 13], [13, 15], [12, 14], [14, 16],     // legs — footwork reads here
        [0, 5], [0, 6],                             // neck
        [0, 1], [0, 2], [1, 3], [2, 4]              // face
    ];
    var SKELETON_JOINTS = 17;

    // Taegukgi blue/red, lifted toward the light end: the annotation swatches
    // (#1e3a8a / #c9302c) disappear against a bright piste, and these are read
    // over video rather than over the page background.
    var SKELETON_LEFT_COLOR = '#3d8bfd';
    var SKELETON_RIGHT_COLOR = '#ff4d4f';
    var SKELETON_OUTLINE = 'rgba(8, 8, 12, 0.85)';
    var BADGE_BG = 'rgba(8, 8, 12, 0.75)';

    // ---- in-scene annotation ----
    //
    // The joints alone are "sticks that move". Everything below turns the same
    // sidecar into the three things a coach actually reads off a phrase: how far
    // apart they are, who is pushing, and where the touch landed. All of it is
    // derived client-side from data the page already has — no new request, no
    // server change.

    // COCO-17 indices the metrics need. Same joints ml/pose_analysis/body_metrics.py
    // uses, because the number drawn on the video has to be the number printed
    // in the touch table.
    var KP_L_SHOULDER = 5, KP_R_SHOULDER = 6;
    var KP_L_HIP = 11, KP_R_HIP = 12;
    var KP_L_ANKLE = 15, KP_R_ANKLE = 16;

    // Cut points are analyzer/config.py DISTANCE_ZONE_THRESHOLDS verbatim. The
    // hexes are literal because a canvas cannot read a CSS custom property; they
    // are the light end of the zone colours the report's touch table already
    // uses, read over bright piste rather than over the page background.
    var DISTANCE_ZONES = [
        { key: 'infighting',     ko: '인파이팅',       color: '#f87171', upper: 0.8 },
        { key: 'extension',      ko: '찌르기 거리',     color: '#60a5fa', upper: 1.2 },
        { key: 'lunge',          ko: '런지 거리',       color: '#4ade80', upper: 1.5 },
        { key: 'advance_lunge',  ko: '전진 런지 거리',  color: '#fbbf24', upper: 1.8 },
        { key: 'out_of_distance', ko: '원거리',         color: 'rgba(255,255,255,0.55)', upper: Infinity }
    ];
    var ZONE_HYSTERESIS_BH = 0.05;    // stops the colour strobing on a boundary
    var DISTANCE_WINDOW = 5;          // = DISTANCE_SMOOTHING_WINDOW server-side
    var VELOCITY_BHS = 0.25;          // advance/retreat cut, BH per second
    var VELOCITY_HOLD = 2;            // samples a new state must survive
    var NEAREST_HALF_WINDOW = 3;      // frames either side of min_distance_frame
    var TOUCH_GLOW_LEAD = 3;          // frames before the touch anchor
    var TOUCH_GLOW_TAIL = 15;

    var FOOTWORK_KO = {
        advance: '전진', retreat: '후퇴', lunge: '런지',
        fleche: '플레시', stationary: '제자리'
        // unknown deliberately absent — an unnamed action is left unnamed.
    };

    var OVERLAY_KEYS = {
        bones: 'fm-wb-ov-bones',
        dist: 'fm-wb-ov-dist',
        badge: 'fm-wb-ov-badge',
        caption: 'fm-wb-ov-caption'
    };

    // ---- elements ----
    var viewport = document.getElementById('wb-viewport');
    var stage = document.getElementById('wb-stage');
    var video = document.getElementById('wb-video');
    var canvas = document.getElementById('wb-canvas');
    var skelCanvas = document.getElementById('wb-skeleton');
    var placeholder = document.getElementById('wb-placeholder');
    var loading = document.getElementById('wb-loading');
    var loadingTitle = document.getElementById('wb-loading-title');
    var loadingSub = document.getElementById('wb-loading-sub');
    var progressTrack = document.getElementById('wb-progress-track');
    var progressBar = document.getElementById('wb-progress-bar');
    var errorEl = document.getElementById('wb-error');

    var playBtn = document.getElementById('wb-play');
    var playLabel = document.getElementById('wb-play-label');
    var seekBar = document.getElementById('wb-seek');
    var timeEl = document.getElementById('wb-time');
    var frameEl = document.getElementById('wb-frame');
    var speedSelect = document.getElementById('wb-speed-select');
    var zoomVal = document.getElementById('wb-zoom-val');
    var calibBtn = document.getElementById('wb-calib');
    var calibState = document.getElementById('wb-calib-state');
    var loopChip = document.getElementById('wb-loop-chip');
    var loopLabel = document.getElementById('wb-loop-label');
    var sourceChip = document.getElementById('wb-source-chip');
    var collapseBtn = document.getElementById('wb-collapse');
    var controlsBar = document.getElementById('wb-controls');
    var fsBtn = document.getElementById('wb-fullscreen');
    var skeletonBtn = document.getElementById('wb-skeleton-toggle');
    var muteBtn = document.getElementById('wb-mute');
    var toast = document.getElementById('wb-toast');
    // The caption band and the sub-toggle popover are optional markup: reports
    // rendered before they existed must still get the canvas annotations, so
    // every use below is guarded rather than assumed.
    var captionBar = document.getElementById('wb-caption');
    var captionText = document.getElementById('wb-caption-text');
    var ovMenuBtn = document.getElementById('wb-ov-menu-btn');
    var ovMenu = document.getElementById('wb-ov-menu');

    // ---- second camera (optional) ----
    var panes = document.getElementById('wb-panes');
    var zoomPane = document.getElementById('wb-zoom');
    var zoomVideo = document.getElementById('wb-zoom-video');
    var zoomGapEl = document.getElementById('wb-zoom-gap');

    var ctx = canvas ? canvas.getContext('2d') : null;
    var skelCtx = skelCanvas ? skelCanvas.getContext('2d') : null;

    // ---- state ----
    var hasMainVideo = root.dataset.hasVideo === '1';
    var mainSrc = hasMainVideo ? (root.dataset.mainSrc || '') : '';
    var showingClip = false;
    var clipBlobUrl = null;
    var clipTimer = null;

    var zoom = 1, panX = 0, panY = 0;
    var stageW = 0, stageH = 0, centerX = 0, centerY = 0;
    var tool = 'navigate';            // navigate | line | measure
    var drawColor = '#c9302c';
    var shapes = [];
    var pending = null;               // shape being dragged
    var calibrating = false;
    var bhPixels = null;              // intrinsic px that equal 1.0 BH
    var loop = null;                  // {start, end, label}
    var panning = null;

    var skeletonOn = false;
    var skeletonData = null;          // the fetched sidecar, cached for the session
    var skeletonFetching = false;
    var skelRaf = null;

    // Which annotation layers the master toggle turns on. All four default on;
    // the popover (when present) persists departures from that.
    var overlayParts = { bones: true, dist: true, badge: true, caption: true };
    var insight = null;               // exchanges/touches/names, see buildInsight()
    var metricCache = {};             // sample index -> metrics, cleared on growth
    var zoneState = null;             // {idx, zone} — carries the hysteresis
    var motionState = { left: null, right: null };
    var captionKey = null;            // last string written, so DOM writes are rare

    var cachedClips = new Set();

    var fullscreen = false;           // the mobile CSS fullscreen mode
    var fsIdleTimer = null;
    var fsScrollY = 0;
    var FS_IDLE_MS = 3000;

    // ---- second camera ----
    // zoomOffset is the constant in `zoom_time = wide_time + offset`, measured
    // by scripts/sync_camera_pair.py and carried on the element. Both halves
    // have to be present: a source with no offset would show a different moment
    // beside the wide camera, which is worse than showing one camera.
    var zoomOffset = zoomPane ? Number(zoomPane.dataset.offset) : NaN;
    var hasZoom = !!(zoomVideo && zoomPane && isFinite(zoomOffset));
    var zoomInGap = null;             // last gap state written, so DOM writes are rare
    var solo = null;                  // null | 'wide' | 'zoom'

    // Correction thresholds, in seconds of the two clocks' disagreement.
    // Paused work is frame-accurate, so it is corrected exactly; during playback
    // a correction is a visible jump, so it waits until the drift is worth more
    // than the jump — 0.1 s is three frames at the 30 fps work rate, and browsers
    // hold two independently-decoded videos well inside that.
    var ZOOM_DRIFT_PLAYING = 0.1;

    // ------------------------------------------------------------------
    // helpers
    // ------------------------------------------------------------------

    function clamp(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); }

    function pad2(n) { return n < 10 ? '0' + n : String(n); }

    function fmtTime(sec) {
        if (!isFinite(sec) || sec < 0) sec = 0;
        var m = Math.floor(sec / 60);
        var s = Math.floor(sec % 60);
        var f = Math.floor((sec - Math.floor(sec)) * FPS);
        return m + ':' + pad2(s) + '.' + pad2(f);
    }

    function frameOf(sec) { return Math.round(sec * FPS); }

    function clipUrl(path) {
        return CLIP_TOKEN ? path + '?token=' + encodeURIComponent(CLIP_TOKEN) : path;
    }

    function showToast(msg) {
        if (!toast) return;
        toast.textContent = msg;
        toast.classList.remove('hidden');
        clearTimeout(showToast._t);
        showToast._t = setTimeout(function () { toast.classList.add('hidden'); }, 4000);
    }

    function isDesktop() { return window.matchMedia('(min-width: 1024px)').matches; }

    function hasSource() { return !!video && !!(video.currentSrc || video.src); }

    // ------------------------------------------------------------------
    // layout: the stage is sized to exactly the painted video box, so the
    // canvas can sit on top of it at inset:0 with no letterbox bookkeeping.
    // ------------------------------------------------------------------

    function updateLayout() {
        if (!viewport || !stage) return;
        if (root.classList.contains('workbench--empty')) {
            viewport.style.height = '';
            return;
        }
        // Fullscreen sizes to the box the CSS gives it (inset:0 over the
        // viewport) instead of to a fraction of the window, and centres the
        // frame in it — a 4.85:1 piste crop leaves black above and below.
        if (fullscreen) viewport.style.height = '';
        var vpW = viewport.clientWidth;
        if (!vpW) return;
        var vw = video.videoWidth || 16;
        var vh = video.videoHeight || 9;
        var ratio = vw / vh;
        var maxH = fullscreen
            ? viewport.clientHeight
            : window.innerHeight * (isDesktop() ? 0.45 : 0.32);

        var w = vpW;
        var h = w / ratio;
        if (maxH > 0 && h > maxH) { h = maxH; w = h * ratio; }

        stageW = w;
        stageH = h;
        centerX = Math.max(0, (vpW - w) / 2);
        centerY = fullscreen ? fsCenterY(h, viewport.clientHeight) : 0;

        stage.style.width = w + 'px';
        stage.style.height = h + 'px';
        stage.style.left = centerX + 'px';
        stage.style.top = centerY + 'px';
        if (!fullscreen) viewport.style.height = h + 'px';

        if (canvas) {
            if (canvas.width !== vw || canvas.height !== vh) {
                canvas.width = vw;
                canvas.height = vh;
            }
        }
        if (skelCanvas) {
            // Same intrinsic grid as the drawing canvas. Resizing a canvas also
            // clears it, so the repaint below is not optional.
            if (skelCanvas.width !== vw || skelCanvas.height !== vh) {
                skelCanvas.width = vw;
                skelCanvas.height = vh;
            }
        }
        applyTransform();
        redraw();
        drawSkeleton();
    }

    /**
     * Where the frame sits inside the fullscreen box.
     *
     * The control bar floats over the picture, and on a landscape phone a
     * centred 4.85:1 crop puts the fencers' feet directly under it — the half
     * of the frame a footwork review is about. So the frame is centred in the
     * band above the bar whenever it fits there, and only falls back to the
     * middle of the screen when the picture is too tall for that, which is the
     * case the translucent background is for.
     */
    function fsCenterY(h, boxH) {
        var stack = 0;
        for (var i = 0; i < root.children.length; i++) {
            var el = root.children[i];
            // The picture layer itself: the viewport, or the pane grid that
            // holds it once there are two cameras. (With one camera the wrapper
            // is display:contents and never appears here at all.)
            if (el === viewport || el.contains(viewport)) continue;
            stack += el.offsetHeight || 0;
        }
        if (h + stack <= boxH) return Math.max(0, (boxH - stack - h) / 2);
        return Math.max(0, (boxH - h) / 2);
    }

    function applyTransform() {
        var vpW = viewport ? viewport.clientWidth : 0;
        var vpH = stageH;
        var sw = stageW * zoom;
        var sh = stageH * zoom;
        panX = clamp(panX, Math.min(0, vpW - centerX - sw), Math.max(0, -centerX));
        panY = clamp(panY, Math.min(0, vpH - sh), 0);
        stage.style.transform = 'translate(' + panX + 'px,' + panY + 'px) scale(' + zoom + ')';
        if (zoomVal) zoomVal.textContent = zoom.toFixed(1);
        root.classList.toggle('workbench--zoomed', zoom > 1);
    }

    /** Screen point -> the video's own pixel coordinates. */
    function toIntrinsic(clientX, clientY) {
        var r = viewport.getBoundingClientRect();
        var left = r.left + centerX + panX;
        var top = r.top + centerY + panY;
        var scale = (stageW / (video.videoWidth || stageW)) * zoom;
        if (!scale) return { x: 0, y: 0 };
        return { x: (clientX - left) / scale, y: (clientY - top) / scale };
    }

    // ------------------------------------------------------------------
    // drawing
    // ------------------------------------------------------------------

    function measureLabel(px) {
        var heightInput = document.getElementById('bh-height-input');
        if (bhPixels && bhPixels > 0) {
            var bh = px / bhPixels;
            if (heightInput) {
                var cm = parseFloat(heightInput.value);
                if (cm > 0) {
                    var meters = bh * (cm * 0.7) / 100;
                    return bh.toFixed(1) + ' BH ≈ ' + meters.toFixed(2) + ' m';
                }
            }
            return bh.toFixed(1) + ' BH · ' + Math.round(px) + ' px';
        }
        return Math.round(px) + ' px';
    }

    function drawShape(s) {
        ctx.strokeStyle = s.color;
        ctx.lineWidth = 2;
        ctx.lineCap = 'round';
        ctx.beginPath();
        ctx.moveTo(s.x1, s.y1);
        ctx.lineTo(s.x2, s.y2);
        ctx.stroke();

        if (s.type !== 'measure') return;

        var px = Math.hypot(s.x2 - s.x1, s.y2 - s.y1);
        var text = measureLabel(px);
        ctx.font = '600 16px system-ui, sans-serif';
        var w = ctx.measureText(text).width;
        var cx = (s.x1 + s.x2) / 2;
        var cy = (s.y1 + s.y2) / 2;
        ctx.fillStyle = 'rgba(10, 10, 15, 0.85)';
        ctx.fillRect(cx - w / 2 - 6, cy - 20, w + 12, 22);
        ctx.strokeStyle = s.color;
        ctx.lineWidth = 1;
        ctx.strokeRect(cx - w / 2 - 6, cy - 20, w + 12, 22);
        ctx.fillStyle = '#ffffff';
        ctx.fillText(text, cx - w / 2, cy - 4);
    }

    function redraw() {
        if (!ctx) return;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        shapes.forEach(drawShape);
        if (pending) drawShape(pending);
    }

    function setTool(next) {
        tool = next;
        root.querySelectorAll('[data-tool]').forEach(function (b) {
            b.classList.toggle('wb-btn--on', b.dataset.tool === next);
        });
        if (viewport) {
            viewport.classList.toggle('wb-viewport--draw', next !== 'navigate');
        }
        if (next !== 'measure' && calibrating) endCalibration(false);
    }

    function startCalibration() {
        calibrating = true;
        setTool('measure');
        if (calibBtn) calibBtn.classList.add('wb-btn--on');
        showToast('선수의 어깨~발목을 따라 선을 그으세요 — 그 길이가 1.0 BH 기준이 됩니다.');
    }

    function endCalibration(applied) {
        calibrating = false;
        if (calibBtn) calibBtn.classList.toggle('wb-btn--on', false);
        if (applied && calibState) {
            calibState.innerHTML = '기준 <span class="fm-num">' + Math.round(bhPixels) + '</span>px';
            calibState.classList.remove('hidden');
        }
    }

    // ------------------------------------------------------------------
    // skeleton overlay
    //
    // A sidecar of per-frame joint coordinates painted straight onto the source
    // video — no clip generation, no server round trip per scrub. It lives on
    // its own canvas underneath #wb-canvas: the drawing tools clear theirs on
    // every redraw(), so sharing one would make the two layers fight, and the
    // coach's own annotations must always sit on top.
    // ------------------------------------------------------------------

    /** currentTime -> nearest sample index. Never interpolated. */
    function skeletonSampleIndex(sec) {
        var fps = skeletonData.fps > 0 ? skeletonData.fps : FPS;
        var every = skeletonData.sample_every > 0 ? skeletonData.sample_every : 1;
        var left = (skeletonData.poses && skeletonData.poses.left) || [];
        var count = skeletonData.sample_count > 0 ? skeletonData.sample_count : left.length;
        // Samples sit sample_every frames apart (0.1s at 30fps), and this tool is
        // used at 1/4–1/6 speed, so the nearest sample is close enough. Inventing
        // an in-between pose would be inventing data.
        return clamp(Math.round(Math.round(sec * fps) / every), 0, Math.max(0, count - 1));
    }

    function drawSkeletonSide(list, idx, color, lw, sx, sy) {
        if (!list) return;
        var flat = list[idx];
        // null = nothing detected for this side in this sample.
        if (!flat || flat.length < SKELETON_JOINTS * 3) return;

        var confScale = skeletonData.conf_scale > 0 ? skeletonData.conf_scale : 100;
        var minConf = typeof skeletonData.min_confidence === 'number'
            ? skeletonData.min_confidence : 0.3;

        // A joint below threshold is "not seen", not "seen at (0,0)" — dropping
        // it also drops every edge that touches it.
        var pts = [];
        for (var j = 0; j < SKELETON_JOINTS; j++) {
            var o = j * 3;
            pts.push((flat[o + 2] / confScale) >= minConf
                ? { x: flat[o] * sx, y: flat[o + 1] * sy }
                : null);
        }

        skelCtx.lineCap = 'round';
        skelCtx.lineJoin = 'round';

        // Dark pass then coloured pass: a bare stroke disappears against a
        // brightly lit piste, and a shadow blur per path is far more expensive.
        // The outline is a fixed multiple of the line so the dark halo stays a
        // thin edge at every resolution instead of swallowing the colour.
        for (var pass = 0; pass < 2; pass++) {
            skelCtx.strokeStyle = pass === 0 ? SKELETON_OUTLINE : color;
            skelCtx.lineWidth = pass === 0 ? lw * 1.9 : lw;
            skelCtx.beginPath();
            for (var e = 0; e < SKELETON_EDGES.length; e++) {
                var a = pts[SKELETON_EDGES[e][0]];
                var b = pts[SKELETON_EDGES[e][1]];
                if (!a || !b) continue;
                skelCtx.moveTo(a.x, a.y);
                skelCtx.lineTo(b.x, b.y);
            }
            skelCtx.stroke();
        }

        for (var k = 0; k < pts.length; k++) {
            if (!pts[k]) continue;
            skelCtx.beginPath();
            skelCtx.arc(pts[k].x, pts[k].y, lw * 1.5, 0, Math.PI * 2);
            skelCtx.fillStyle = SKELETON_OUTLINE;
            skelCtx.fill();
            skelCtx.beginPath();
            skelCtx.arc(pts[k].x, pts[k].y, lw * 0.95, 0, Math.PI * 2);
            skelCtx.fillStyle = color;
            skelCtx.fill();
        }
    }

    // ------------------------------------------------------------------
    // annotation metrics
    //
    // Every number here is recomputed from the sidecar in the sidecar's own
    // pixel space — never in canvas space — so it matches what the server
    // measured whatever size the video is served at.
    // ------------------------------------------------------------------

    /** Sidecar sample -> 17 points (or nulls), in the sidecar's pixel space. */
    function jointsAt(list, idx) {
        if (!list) return null;
        var flat = list[idx];
        if (!flat || flat.length < SKELETON_JOINTS * 3) return null;
        var confScale = skeletonData.conf_scale > 0 ? skeletonData.conf_scale : 100;
        var minConf = typeof skeletonData.min_confidence === 'number'
            ? skeletonData.min_confidence : 0.3;
        var pts = [];
        for (var j = 0; j < SKELETON_JOINTS; j++) {
            var o = j * 3;
            pts.push((flat[o + 2] / confScale) >= minConf
                ? { x: flat[o], y: flat[o + 1] }
                : null);
        }
        return pts;
    }

    function midOf(a, b) {
        if (!a || !b) return null;
        return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
    }

    /**
     * Shoulder-centre to ankle-centre, in pixels — one body height.
     * Mirrors compute_body_height() in ml/pose_analysis/body_metrics.py.
     */
    function bodyHeightOf(pts) {
        if (!pts) return null;
        var sh = midOf(pts[KP_L_SHOULDER], pts[KP_R_SHOULDER]);
        var ank = midOf(pts[KP_L_ANKLE], pts[KP_R_ANKLE]);
        if (!sh || !ank) return null;
        var h = Math.hypot(sh.x - ank.x, sh.y - ank.y);
        return h > 0 ? h : null;
    }

    /** Per-sample geometry, memoised: the smoothing window re-reads neighbours. */
    function metricsAt(idx) {
        var hit = metricCache[idx];
        if (hit !== undefined) return hit;

        var poses = skeletonData.poses || {};
        var lp = jointsAt(poses.left, idx);
        var rp = jointsAt(poses.right, idx);
        var m = {
            left: sideMetrics(lp),
            right: sideMetrics(rp),
            dist: null
        };
        if (m.left && m.right) {
            var avgBh = (m.left.bh + m.right.bh) / 2;
            // X only: the camera is side-on, so vertical separation is parallax,
            // not distance. Same choice as compute_distance_bh().
            if (avgBh > 0) m.dist = Math.abs(m.left.hip.x - m.right.hip.x) / avgBh;
        }

        // Bounded so a long scrub cannot grow this without limit; the window
        // only ever looks a few samples back, so dropping the rest is free.
        if (Object.keys(metricCache).length > 600) metricCache = {};
        metricCache[idx] = m;
        return m;
    }

    function sideMetrics(pts) {
        if (!pts) return null;
        var hip = midOf(pts[KP_L_HIP], pts[KP_R_HIP]);
        var bh = bodyHeightOf(pts);
        if (!hip || !bh) return null;
        var sh = midOf(pts[KP_L_SHOULDER], pts[KP_R_SHOULDER]);
        return { pts: pts, hip: hip, bh: bh, shoulder: sh || hip };
    }

    /**
     * Moving average over a DISTANCE_WINDOW-wide window *centred* on the sample
     * — which is what smooth_distances() in ml/pose_analysis/body_metrics.py
     * does, and the reason the label agrees with the report's min_distance_bh.
     * A trailing window lags the closing motion and reads high at exactly the
     * moment that matters (measured: +0.29 BH at the closest point of exchange
     * 13, against +0.02 centred).
     *
     * Computed from the sidecar on demand rather than from a running buffer, so
     * a seek lands on the same number the frame showed during playback. Both
     * poses are needed to draw the line at all, so a sample the server would
     * have filled from its neighbours is still skipped here.
     */
    function smoothedDistance(idx) {
        if (metricsAt(idx).dist === null) return null;
        var half = Math.floor(DISTANCE_WINDOW / 2);
        var sum = 0, n = 0;
        for (var i = idx - half; i <= idx + half; i++) {
            if (i < 0) continue;
            var d = metricsAt(i).dist;
            if (d !== null) { sum += d; n++; }
        }
        return n ? sum / n : null;
    }

    function zoneIndexFor(bh) {
        for (var i = 0; i < DISTANCE_ZONES.length; i++) {
            if (bh < DISTANCE_ZONES[i].upper) return i;
        }
        return DISTANCE_ZONES.length - 1;
    }

    /**
     * Zone with hysteresis: the label only moves once the distance is clear of
     * the boundary it last crossed, so a fencer sitting on 1.20 BH does not make
     * the line flash between blue and green.
     */
    function zoneFor(bh, idx) {
        var plain = zoneIndexFor(bh);
        // More than a sample or two of gap means a seek: nothing to be sticky about.
        if (!zoneState || Math.abs(idx - zoneState.idx) > 2) {
            zoneState = { idx: idx, zone: plain };
            return DISTANCE_ZONES[plain];
        }
        var held = zoneState.zone;
        var lower = held > 0 ? DISTANCE_ZONES[held - 1].upper : -Infinity;
        var upper = DISTANCE_ZONES[held].upper;
        if (bh >= lower - ZONE_HYSTERESIS_BH && bh < upper + ZONE_HYSTERESIS_BH) {
            zoneState = { idx: idx, zone: held };
            return DISTANCE_ZONES[held];
        }
        zoneState = { idx: idx, zone: plain };
        return DISTANCE_ZONES[plain];
    }

    /** Hip-centre x speed by central difference, normalised to BH per second. */
    function rawMotion(idx, side) {
        var cur = metricsAt(idx)[side];
        if (!cur) return null;
        var prev = idx > 0 ? metricsAt(idx - 1)[side] : null;
        var next = metricsAt(idx + 1)[side];
        if (!prev || !next) return null;
        var every = skeletonData.sample_every > 0 ? skeletonData.sample_every : 1;
        var fps = skeletonData.fps > 0 ? skeletonData.fps : FPS;
        var dt = (2 * every) / fps;
        var vx = (next.hip.x - prev.hip.x) / dt / cur.bh;
        // The left fencer advances toward +x, the right fencer toward -x.
        var toward = side === 'left' ? vx : -vx;
        if (toward > VELOCITY_BHS) return 'advance';
        if (toward < -VELOCITY_BHS) return 'retreat';
        return 'hold';
    }

    /**
     * The badge word, held for VELOCITY_HOLD samples before it changes. At 1/6
     * speed a raw per-sample state flickers faster than it can be read.
     */
    function motionFor(idx, side) {
        var raw = rawMotion(idx, side);
        var st = motionState[side];
        if (!st || Math.abs(idx - st.idx) > 2) {
            motionState[side] = { idx: idx, shown: raw, cand: raw, count: 0 };
            return raw;
        }
        if (st.idx !== idx) {
            if (raw === st.shown) {
                st.cand = raw;
                st.count = 0;
            } else if (raw === st.cand) {
                st.count += 1;
                if (st.count >= VELOCITY_HOLD - 1) { st.shown = raw; st.count = 0; }
            } else {
                st.cand = raw;
                st.count = 0;
            }
            st.idx = idx;
        }
        return st.shown;
    }

    var MOTION_KO = { advance: '전진', retreat: '후퇴', hold: '정지' };

    // ------------------------------------------------------------------
    // report slice: exchanges, touches and names
    // ------------------------------------------------------------------

    /**
     * The whole report JSON is already on the page, so the annotations read it
     * directly. FM_REPORT.insight is preferred when the template supplies a
     * pre-trimmed slice; the REPORT_DATA fallback keeps this working on pages
     * rendered before that slice existed.
     */
    function buildInsight() {
        var src = cfg.insight;
        if (!src) {
            /* global REPORT_DATA */
            src = (typeof REPORT_DATA !== 'undefined') ? REPORT_DATA : null;
        }
        if (!src) return null;

        var left = src.left_fencer || {};
        var right = src.right_fencer || {};
        var exchanges = (src.exchanges || []).map(function (e) {
            return {
                n: e.exchange_number,
                start: e.start_frame,
                end: e.end_frame,
                eventKo: e.event_type_ko || '',
                attacker: e.attacker || null,
                defender: e.defender || null,
                fwLeft: e.footwork_left || null,
                fwRight: e.footwork_right || null,
                minFrame: typeof e.min_distance_frame === 'number' ? e.min_distance_frame : null,
                minBh: typeof e.min_distance_bh === 'number' ? e.min_distance_bh : null,
                parryLeft: e.parry_left === true,
                parryRight: e.parry_right === true
            };
        }).filter(function (e) {
            return typeof e.start === 'number' && typeof e.end === 'number';
        }).sort(function (a, b) { return a.start - b.start; });

        var touches = (src.touches || []).map(function (t) {
            return {
                frame: t.frame,
                scorer: t.scorer || null,
                scoreAfter: t.score_after || '',
                outcomeKo: t.attack_outcome_ko || '',
                lampRed: t.lamp_red === true,
                lampGreen: t.lamp_green === true
            };
        }).filter(function (t) {
            return typeof t.frame === 'number';
        }).sort(function (a, b) { return a.frame - b.frame; });

        return {
            leftName: left.name || '좌 선수',
            rightName: right.name || '우 선수',
            exchanges: exchanges,
            touches: touches
        };
    }

    /** Last entry whose key <= frame, by binary search over ~20 rows. */
    function lastAtOrBefore(list, frame, keyOf) {
        var lo = 0, hi = list.length - 1, found = -1;
        while (lo <= hi) {
            var mid = (lo + hi) >> 1;
            if (keyOf(list[mid]) <= frame) { found = mid; lo = mid + 1; } else { hi = mid - 1; }
        }
        return found;
    }

    function activeExchange(frame) {
        if (!insight) return null;
        var i = lastAtOrBefore(insight.exchanges, frame, function (e) { return e.start; });
        if (i < 0) return null;
        var e = insight.exchanges[i];
        return frame <= e.end ? e : null;
    }

    function activeTouch(frame) {
        if (!insight) return null;
        var i = lastAtOrBefore(insight.touches, frame + TOUCH_GLOW_LEAD,
                               function (t) { return t.frame; });
        if (i < 0) return null;
        var t = insight.touches[i];
        return (frame >= t.frame - TOUCH_GLOW_LEAD && frame <= t.frame + TOUCH_GLOW_TAIL)
            ? t : null;
    }

    function sideName(side) {
        if (!insight) return '';
        return side === 'left' ? insight.leftName : (side === 'right' ? insight.rightName : '');
    }

    // ------------------------------------------------------------------
    // annotation drawing
    // ------------------------------------------------------------------

    function roundRectPath(c, x, y, w, h, r) {
        var rad = Math.min(r, h / 2, w / 2);
        c.beginPath();
        c.moveTo(x + rad, y);
        c.lineTo(x + w - rad, y);
        c.quadraticCurveTo(x + w, y, x + w, y + rad);
        c.lineTo(x + w, y + h - rad);
        c.quadraticCurveTo(x + w, y + h, x + w - rad, y + h);
        c.lineTo(x + rad, y + h);
        c.quadraticCurveTo(x, y + h, x, y + h - rad);
        c.lineTo(x, y + rad);
        c.quadraticCurveTo(x, y, x + rad, y);
        c.closePath();
    }

    /** A capsule of text, positioned by its left edge. Returns its width. */
    function drawCapsule(text, x, cy, borderColor, fontPx) {
        skelCtx.font = '600 ' + fontPx + 'px system-ui, sans-serif';
        var padX = fontPx * 0.5;
        var w = skelCtx.measureText(text).width + padX * 2;
        var h = fontPx * 1.65;
        roundRectPath(skelCtx, x, cy - h / 2, w, h, h / 2);
        skelCtx.fillStyle = BADGE_BG;
        skelCtx.fill();
        skelCtx.strokeStyle = borderColor;
        skelCtx.lineWidth = Math.max(1, fontPx / 14);
        skelCtx.stroke();
        skelCtx.fillStyle = '#ffffff';
        skelCtx.textBaseline = 'middle';
        skelCtx.fillText(text, x + padX, cy + fontPx * 0.05);
        return w;
    }

    /**
     * The distance line. Drawn between the two hip centres but levelled to their
     * mean y: a sloped line reads as a direction, not as a gap.
     */
    function drawDistanceLine(m, idx, frame, ex, sx, sy, fontPx) {
        var bh = smoothedDistance(idx);
        if (bh === null) return;
        var zone = zoneFor(bh, idx);

        var x1 = m.left.hip.x * sx;
        var x2 = m.right.hip.x * sx;
        var y = ((m.left.hip.y + m.right.hip.y) / 2) * sy;
        var tick = Math.max(6, skelCanvas.height * 0.035);

        // Dark pass then coloured pass, as the bones do. Measured on the pool-bout
        // bout: a bare line in the out-of-distance colour (55% white) is
        // invisible against the lit piste, which is exactly the zone a coach is
        // looking at while the fencers close.
        skelCtx.lineCap = 'butt';
        var lineW = Math.max(2, skelCanvas.width / 560);
        for (var pass = 0; pass < 2; pass++) {
            skelCtx.strokeStyle = pass === 0 ? SKELETON_OUTLINE : zone.color;
            skelCtx.lineWidth = pass === 0 ? lineW * 2.6 : lineW;
            skelCtx.beginPath();
            skelCtx.moveTo(x1, y);
            skelCtx.lineTo(x2, y);
            skelCtx.moveTo(x1, y - tick); skelCtx.lineTo(x1, y + tick);
            skelCtx.moveTo(x2, y - tick); skelCtx.lineTo(x2, y + tick);
            skelCtx.stroke();
        }

        // At the closing instant the label stops describing the gap and names
        // it: this frame is the one the report measured.
        var nearest = ex && ex.minFrame !== null && ex.minBh !== null &&
            Math.abs(frame - ex.minFrame) <= NEAREST_HALF_WINDOW;
        var text = nearest
            ? '최근접 ' + ex.minBh.toFixed(2) + ' BH'
            : bh.toFixed(1) + ' BH · ' + zone.ko;

        skelCtx.font = '600 ' + fontPx + 'px system-ui, sans-serif';
        var w = skelCtx.measureText(text).width + fontPx;
        var cx = clamp((x1 + x2) / 2, w / 2 + 4, skelCanvas.width - w / 2 - 4);
        drawCapsule(text, cx - w / 2, y - tick - fontPx * 1.15,
                    nearest ? '#ffffff' : zone.color, fontPx);

        if (nearest) {
            // A ring that widens across the window rather than animating on its
            // own clock — at 1/4 speed it reads as one expanding pulse, and it
            // lands on exactly the frames the report points at.
            var t = (frame - (ex.minFrame - NEAREST_HALF_WINDOW)) / (NEAREST_HALF_WINDOW * 2);
            var r = tick * (0.6 + 2.4 * clamp(t, 0, 1));
            skelCtx.beginPath();
            skelCtx.arc((x1 + x2) / 2, y, r, 0, Math.PI * 2);
            skelCtx.strokeStyle = 'rgba(255,255,255,' + (0.85 * (1 - clamp(t, 0, 1)) + 0.15).toFixed(3) + ')';
            skelCtx.lineWidth = Math.max(1.5, skelCanvas.width / 700);
            skelCtx.stroke();
        }
    }

    /**
     * Name + direction + state, parked on the fencer's outside shoulder. The
     * piste crop is ~330px tall, so there is no room above the head or below the
     * feet — but there is always room to the outside, and the space between the
     * two fencers is where the action is and must stay clear.
     *
     * The arrow is screen direction, not fencing direction: the word already
     * carries "toward the opponent", and an arrow the viewer can check against
     * the video beats one they have to decode.
     */
    function drawBadge(side, sm, motion, color, sx, sy, fontPx) {
        var name = sideName(side);
        if (!name) return;
        var label = name;
        if (motion === 'advance' || motion === 'retreat') {
            var rightward = (side === 'left') === (motion === 'advance');
            label = name + (rightward ? ' ▶ ' : ' ◀ ') + MOTION_KO[motion];
        } else if (motion === 'hold') {
            label = name + ' · 정지';
        }

        var xs = [];
        for (var i = 0; i < sm.pts.length; i++) {
            if (sm.pts[i]) xs.push(sm.pts[i].x * sx);
        }
        if (!xs.length) return;
        var minX = Math.min.apply(null, xs);
        var maxX = Math.max.apply(null, xs);

        skelCtx.font = '600 ' + fontPx + 'px system-ui, sans-serif';
        var w = skelCtx.measureText(label).width + fontPx;
        var gap = fontPx * 0.6;
        // Clamped inward at the ends of the piste — overlapping the body there
        // beats running off the frame.
        var x = side === 'left'
            ? clamp(minX - gap - w, 4, skelCanvas.width - w - 4)
            : clamp(maxX + gap, 4, skelCanvas.width - w - 4);
        var cy = clamp(sm.shoulder.y * sy, fontPx, skelCanvas.height - fontPx);
        drawCapsule(label, x, cy, color, fontPx);
    }

    /** Scorer-side edge glow. Camp colours, not lamp colours — see the caption. */
    function drawTouchGlow(touch, frame) {
        var span = TOUCH_GLOW_LEAD + TOUCH_GLOW_TAIL;
        var t = clamp((frame - (touch.frame - TOUCH_GLOW_LEAD)) / span, 0, 1);
        var alpha = 0.55 * (1 - t) + 0.1;
        var w = skelCanvas.width * 0.18;
        var h = skelCanvas.height;

        var sides = [];
        if (touch.lampRed && touch.lampGreen) {
            // Both lamps lit: both fencers landed. The caption says who was
            // awarded it; the screen shows that both arrived.
            sides = ['left', 'right'];
        } else if (touch.scorer === 'left' || touch.scorer === 'right') {
            sides = [touch.scorer];
        }

        sides.forEach(function (side) {
            var color = side === 'left' ? SKELETON_LEFT_COLOR : SKELETON_RIGHT_COLOR;
            var g = side === 'left'
                ? skelCtx.createLinearGradient(0, 0, w, 0)
                : skelCtx.createLinearGradient(skelCanvas.width, 0, skelCanvas.width - w, 0);
            g.addColorStop(0, hexToRgba(color, alpha));
            g.addColorStop(1, hexToRgba(color, 0));
            skelCtx.fillStyle = g;
            skelCtx.fillRect(side === 'left' ? 0 : skelCanvas.width - w, 0, w, h);
        });
    }

    function hexToRgba(hex, alpha) {
        var n = parseInt(hex.slice(1), 16);
        return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255) +
               ',' + alpha.toFixed(3) + ')';
    }

    // ------------------------------------------------------------------
    // caption band (DOM, not canvas)
    // ------------------------------------------------------------------

    function fwKo(v) { return (v && FOOTWORK_KO[v]) || ''; }

    function personPhrase(name, fw) {
        var word = fwKo(fw);
        return word ? name + ' ' + word : name;
    }

    function captionForTouch(t) {
        var name = sideName(t.scorer);
        if (!name) return null;
        // "단독 유효타 (우선권 판정 없음)" -> "단독 유효타": the parenthetical is
        // for the table, where there is room to read it.
        var outcome = (t.outcomeKo || '').split('(')[0].trim();
        var head = '터치 — ' + name + ' 득점' + (t.scoreAfter ? ' (' + t.scoreAfter + ')' : '');
        return outcome ? head + ' · ' + outcome : head;
    }

    function captionForExchange(e) {
        var head = '교전 ' + e.n + (e.eventKo ? ' · ' + e.eventKo : '');
        if (e.attacker === 'left' || e.attacker === 'right') {
            var defSide = e.defender === 'left' || e.defender === 'right'
                ? e.defender : (e.attacker === 'left' ? 'right' : 'left');
            var atkFw = e.attacker === 'left' ? e.fwLeft : e.fwRight;
            var defFw = defSide === 'left' ? e.fwLeft : e.fwRight;
            var parried = defSide === 'left' ? e.parryLeft : e.parryRight;
            return head + ' — ' + personPhrase(sideName(e.attacker), atkFw) + ' 공격 → ' +
                   personPhrase(sideName(defSide), defFw) + (parried ? ' (파라드)' : '');
        }
        return head + ' — ' + personPhrase(insight.leftName, e.fwLeft) +
               ' · ' + personPhrase(insight.rightName, e.fwRight);
    }

    /**
     * The band keeps its height when empty so the page never jumps; only its
     * text fades. textContent is written when the sentence changes, not per
     * frame — at 60fps rAF that is the difference between 1 write and 3600.
     */
    function setCaption(text) {
        if (!captionBar) return;
        var key = text || '';
        if (key === captionKey) return;
        captionKey = key;
        if (captionText) captionText.textContent = key;
        captionBar.classList.toggle('wb-caption--empty', !key);
    }

    function updateCaption(frame) {
        if (!captionBar) return;
        if (!overlayParts.caption || !skeletonOn || showingClip || !insight) {
            setCaption('');
            captionBar.classList.toggle('wb-caption--off', !overlayParts.caption || !skeletonOn);
            return;
        }
        captionBar.classList.remove('wb-caption--off');
        var t = activeTouch(frame);
        if (t) { setCaption(captionForTouch(t) || ''); return; }
        var e = activeExchange(frame);
        setCaption(e ? captionForExchange(e) : '');
    }

    // ------------------------------------------------------------------
    // the draw pass
    // ------------------------------------------------------------------

    function drawOverlay() {
        if (!skelCtx) return;
        skelCtx.clearRect(0, 0, skelCanvas.width, skelCanvas.height);
        // An AI clip already has a skeleton burned in by the server, and its
        // frame numbers do not line up with the main video's, so a second
        // overlay there would be drawing the wrong pose on the wrong frame.
        if (!skeletonOn || showingClip || !skeletonData) {
            updateCaption(0);
            return;
        }

        var poses = skeletonData.poses || {};
        var idx = skeletonSampleIndex(video.currentTime);
        var frame = frameOf(video.currentTime);
        // Normally 1:1 — the sidecar is in the video's own pixel space. The
        // ratio only matters if the served video was re-encoded at another size.
        var sx = skeletonData.frame_width > 0 ? skelCanvas.width / skeletonData.frame_width : 1;
        var sy = skeletonData.frame_height > 0 ? skelCanvas.height / skeletonData.frame_height : 1;
        // Scaled to the frame so the overlay looks the same on 720p and 1080p;
        // the floor keeps it legible on the small crops some reports carry.
        var lw = Math.max(2.5, skelCanvas.width / 420);
        // Text is sized against how large the video is actually painted, not
        // against its intrinsic pixels. A glyph fixed in canvas units renders
        // ~19 CSS px on a desktop stage and ~5 CSS px on a 390px phone, where it
        // is simply unreadable. Capped against the frame height so it still
        // cannot swallow a 330px piste crop, and zoom counts as painting bigger.
        var painted = (stageW || skelCanvas.width) * zoom;
        var fontPx = clamp(Math.round(18 * skelCanvas.width / painted),
                           11, Math.round(skelCanvas.height * 0.11));

        var touch = insight ? activeTouch(frame) : null;
        // Behind everything: it is a wash over the frame, not a mark on it.
        if (touch) drawTouchGlow(touch, frame);

        if (overlayParts.bones) {
            drawSkeletonSide(poses.left, idx, SKELETON_LEFT_COLOR, lw, sx, sy);
            drawSkeletonSide(poses.right, idx, SKELETON_RIGHT_COLOR, lw, sx, sy);
        }

        var m = metricsAt(idx);
        var ex = insight ? activeExchange(frame) : null;

        // A sample with no usable pose draws nothing for that layer rather than
        // interpolating one — the same policy the bones already follow.
        if (overlayParts.dist && m.left && m.right) {
            drawDistanceLine(m, idx, frame, ex, sx, sy, fontPx);
        }
        if (overlayParts.badge) {
            if (m.left) {
                drawBadge('left', m.left, motionFor(idx, 'left'), SKELETON_LEFT_COLOR, sx, sy, fontPx);
            }
            if (m.right) {
                drawBadge('right', m.right, motionFor(idx, 'right'), SKELETON_RIGHT_COLOR, sx, sy, fontPx);
            }
        }

        updateCaption(frame);
    }

    /** Kept as the old name because the media events wire straight to it. */
    function drawSkeleton() { drawOverlay(); }

    function skeletonTick() {
        skelRaf = null;
        drawOverlay();
        if (skeletonOn && !showingClip && !video.paused && !video.ended) {
            skelRaf = requestAnimationFrame(skeletonTick);
        }
    }

    /** timeupdate alone fires ~4x/sec, which reads as a stutter against 30fps. */
    function startSkeletonLoop() {
        if (skelRaf !== null) return;
        if (!skeletonOn || showingClip || !skeletonData) return;
        if (video.paused || video.ended) return;
        skelRaf = requestAnimationFrame(skeletonTick);
    }

    function stopSkeletonLoop() {
        if (skelRaf !== null) { cancelAnimationFrame(skelRaf); skelRaf = null; }
    }

    /** Everything derived from a run of samples; a seek invalidates all of it. */
    function resetOverlayState() {
        metricCache = {};
        zoneState = null;
        motionState = { left: null, right: null };
        captionKey = null;
    }

    function loadOverlayPrefs() {
        Object.keys(OVERLAY_KEYS).forEach(function (part) {
            var v = null;
            try { v = localStorage.getItem(OVERLAY_KEYS[part]); } catch (_) { /* private mode */ }
            // Everything is on unless the coach has explicitly turned it off.
            overlayParts[part] = v !== '0';
        });
    }

    function syncOverlayToggles() {
        if (!ovMenu) return;
        ovMenu.querySelectorAll('[data-ov]').forEach(function (b) {
            var part = b.dataset.ov;
            if (!(part in overlayParts)) return;
            b.classList.toggle('wb-btn--on', overlayParts[part]);
            b.setAttribute('aria-pressed', overlayParts[part] ? 'true' : 'false');
        });
    }

    function setOverlayPart(part, on) {
        if (!(part in overlayParts)) return;
        overlayParts[part] = !!on;
        try {
            localStorage.setItem(OVERLAY_KEYS[part], on ? '1' : '0');
        } catch (_) { /* private mode */ }
        syncOverlayToggles();
        drawOverlay();
    }

    function syncSkeletonBtn() {
        if (ovMenuBtn) ovMenuBtn.disabled = showingClip || !skeletonOn;
        if (!skeletonBtn) return;
        skeletonBtn.classList.toggle('wb-btn--on', skeletonOn && !showingClip);
        skeletonBtn.disabled = showingClip;
        skeletonBtn.title = showingClip
            ? 'AI 정밀 분석 클립에는 이미 오버레이가 입혀져 있습니다 — 원본 영상으로 돌아가면 다시 사용할 수 있습니다'
            : '원본 영상 위에 두 선수의 관절·거리·상태를 그대로 그립니다 — 클립을 만들지 않고 즉시 표시됩니다';
    }

    function applySkeletonState(on, persist) {
        skeletonOn = !!on;
        resetOverlayState();
        if (persist) {
            try {
                localStorage.setItem(SKELETON_KEY, skeletonOn ? '1' : '0');
            } catch (_) { /* private mode */ }
        }
        syncSkeletonBtn();
        drawSkeleton();
        if (skeletonOn) { startSkeletonLoop(); } else { stopSkeletonLoop(); }
    }

    function setSkeletonEnabled(on, fromUser) {
        if (!skeletonBtn) return;
        if (!on || skeletonData) {
            applySkeletonState(on, fromUser);
            return;
        }
        if (skeletonFetching) return;
        // ~1MB, so it is pulled on first enable rather than on every page load.
        skeletonFetching = true;
        showToast('스켈레톤 데이터를 불러오는 중...');
        fetch(clipUrl(KEYPOINTS_URL))
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (data) {
                if (!data || !data.poses) throw new Error('malformed sidecar');
                skeletonData = data;
                skeletonFetching = false;
                applySkeletonState(true, fromUser);
                if (fromUser) {
                    showToast('스켈레톤 표시 중 — 원본 영상 위에 두 선수의 관절이 그려집니다.');
                }
            })
            .catch(function () {
                // Fail loudly and back off the toggle: a control that looks on
                // but draws nothing is worse than one that says it failed. The
                // stored preference is left alone so a transient error recovers.
                skeletonFetching = false;
                applySkeletonState(false, false);
                showToast('스켈레톤 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.');
            });
    }

    // ------------------------------------------------------------------
    // audio
    //
    // Muted by default because slow-motion playback garbles the sound. The
    // preference is a property of the workbench, not of one source, and the
    // same <video> carries both the main footage and the generated clips.
    // ------------------------------------------------------------------

    var mutedPref = true;

    function syncMuteBtn() {
        if (!muteBtn) return;
        muteBtn.textContent = video.muted ? '음소거' : '소리 켬';
        muteBtn.classList.toggle('wb-btn--on', !video.muted);
        muteBtn.title = video.muted
            ? '소리 켜기 — 느린 배속에서는 소리가 뭉개지므로 기본은 음소거입니다'
            : '음소거하기';
    }

    function applyMute(muted, persist) {
        mutedPref = !!muted;
        video.muted = mutedPref;
        if (persist) {
            try {
                localStorage.setItem(MUTE_KEY, mutedPref ? '1' : '0');
            } catch (_) { /* private mode */ }
        }
        syncMuteBtn();
    }

    /** Re-assert after a src swap so the choice survives source <-> clip. */
    function reassertMute() {
        if (video.muted !== mutedPref) video.muted = mutedPref;
        syncMuteBtn();
    }

    // ------------------------------------------------------------------
    // playback
    // ------------------------------------------------------------------

    function syncPlayLabel() {
        if (!playLabel) return;
        playLabel.textContent = video.paused ? '▶' : '‖';
        if (playBtn) playBtn.title = video.paused ? '재생 (Space)' : '일시정지 (Space)';
    }

    function togglePlay() {
        if (!hasSource()) return;
        if (video.paused) { video.play().catch(function () {}); } else { video.pause(); }
    }

    function stepFrame(delta) {
        if (!hasSource()) return;
        video.pause();
        var f = Math.round(video.currentTime * FPS) + delta;
        video.currentTime = Math.max(0, f / FPS);
    }

    function jump(seconds) {
        if (!hasSource()) return;
        video.currentTime = Math.max(0, video.currentTime + seconds);
    }

    function setSpeed(rate) {
        video.playbackRate = rate;
        root.querySelectorAll('[data-speed]').forEach(function (b) {
            b.classList.toggle('wb-btn--on', Math.abs(Number(b.dataset.speed) - rate) < 1e-6);
        });
        if (speedSelect) speedSelect.value = String(rate);
    }

    function setLoop(next) {
        loop = next;
        if (!loopChip) return;
        if (!next) {
            loopChip.classList.add('hidden');
            return;
        }
        loopChip.classList.remove('hidden');
        if (loopLabel) loopLabel.textContent = next.label || '구간 반복';
    }

    function seekRange(startSec, endSec, label) {
        if (!hasSource()) return false;
        setLoop({ start: startSec, end: endSec, label: label });
        video.currentTime = startSec;
        video.play().catch(function () {});
        return true;
    }

    // ------------------------------------------------------------------
    // second camera — one clock drives both players
    // ------------------------------------------------------------------

    /**
     * Every seek, every frame step and every timeline jump goes through the main
     * video's currentTime, so the zoom player is driven entirely off that
     * element's own events rather than off each call site. Nothing that moves
     * the main video can therefore forget to move this one.
     *
     * Sync is refused, not approximated, while an AI overlay clip is on the
     * stage: that clip has its own timeline starting at zero and the offset
     * means nothing against it.
     */
    function zoomActive() {
        return hasZoom && !showingClip && hasMainVideo;
    }

    /** Where the zoom camera's clock stands when the wide camera reads `t`. */
    function zoomTimeFor(t) {
        return t + zoomOffset;
    }

    function setZoomGap(inGap) {
        if (zoomInGap === inGap) return;
        zoomInGap = inGap;
        zoomPane.classList.toggle('wb-zoom--gap', inGap);
        if (zoomGapEl) zoomGapEl.classList.toggle('hidden', !inGap);
    }

    /**
     * Put the zoom player where the wide player is.
     *
     * `hard` forces the assignment; otherwise it only corrects a drift past
     * ZOOM_DRIFT_PLAYING, because assigning currentTime mid-playback re-seeks the
     * decoder and shows as a stutter.
     */
    function syncZoom(hard) {
        if (!zoomActive()) return;
        var dur = zoomVideo.duration;
        if (!isFinite(dur) || dur <= 0) return;      // metadata not in yet

        var target = zoomTimeFor(video.currentTime);
        // The two cameras were not started or stopped together: the zoom one
        // began 9 s later here and ran out first. Outside its own recording there
        // is no matching frame, and holding the first or last one while the wide
        // camera moves would read as a synced frame that is not one.
        var gap = target < 0 || target > dur;
        setZoomGap(gap);
        if (gap) {
            if (!zoomVideo.paused) zoomVideo.pause();
            zoomVideo.currentTime = clamp(target, 0, dur);
            return;
        }

        if (hard || Math.abs(zoomVideo.currentTime - target) > ZOOM_DRIFT_PLAYING) {
            zoomVideo.currentTime = target;
        }

        // Two elements, one transport. play()/pause() are only issued on a real
        // mismatch so a paused step never starts playback.
        if (video.paused) {
            if (!zoomVideo.paused) zoomVideo.pause();
        } else if (zoomVideo.paused) {
            zoomVideo.play().catch(function () { /* autoplay refused; frames still seek */ });
        }
        if (zoomVideo.playbackRate !== video.playbackRate) {
            zoomVideo.playbackRate = video.playbackRate;
        }
    }

    /** Show one pane full width, or both. Passing the current solo clears it. */
    function setSolo(next) {
        if (!hasZoom || !panes) return;
        solo = (solo === next) ? null : next;
        panes.classList.toggle('wb-panes--solo-wide', solo === 'wide');
        panes.classList.toggle('wb-panes--solo-zoom', solo === 'zoom');
        // The wide pane's width just changed, and every stage dimension is
        // derived from it. Its zoom/pan is left alone: the coach chose it.
        updateLayout();
    }

    /**
     * An overlay clip replaces the main video's source, so the offset stops
     * meaning anything. The pane is emptied rather than frozen on a stale frame,
     * and comes back when the source video does.
     */
    function syncZoomToClipState() {
        if (!hasZoom) return;
        var showing = !!showingClip;
        panes.classList.toggle('wb-panes--clip', showing);
        if (showing) {
            zoomVideo.pause();
            if (solo === 'zoom') setSolo('zoom');   // nothing to show; go back to both
        } else {
            syncZoom(true);
        }
        updateLayout();
    }

    function wireZoom() {
        if (!hasZoom) return;
        // Always silent, whatever the mute button does to the main video: two
        // recordings of the same room playing together is an echo, not sound.
        zoomVideo.muted = true;
        zoomVideo.src = zoomPane.dataset.src || '';

        zoomVideo.addEventListener('loadedmetadata', function () { syncZoom(true); });

        // The main element is the clock. `seeked` covers frame stepping, the
        // scrub bar and timeline jumps; `timeupdate` covers drift during play.
        video.addEventListener('seeked', function () { syncZoom(true); });
        video.addEventListener('timeupdate', function () { syncZoom(false); });
        video.addEventListener('play', function () { syncZoom(true); });
        video.addEventListener('pause', function () { syncZoom(true); });
        video.addEventListener('ratechange', function () { syncZoom(false); });
        video.addEventListener('loadedmetadata', function () { syncZoom(true); });

        root.querySelectorAll('[data-solo]').forEach(function (b) {
            // The wide pane's own pointer handlers draw and pan, so this button
            // must not reach them.
            b.addEventListener('pointerdown', function (e) { e.stopPropagation(); });
            b.addEventListener('click', function (e) {
                e.stopPropagation();
                setSolo(b.dataset.solo);
            });
        });
        // The zoom pane carries no drawing tools, so its whole surface can be
        // the control the button duplicates.
        zoomPane.addEventListener('click', function () { setSolo('zoom'); });
    }

    function onTimeUpdate() {
        if (timeEl) timeEl.textContent = fmtTime(video.currentTime);
        if (frameEl) frameEl.textContent = String(frameOf(video.currentTime));
        if (seekBar && video.duration) {
            seekBar.max = String(video.duration);
            if (!seekBar.dataset.dragging) seekBar.value = String(video.currentTime);
        }
        if (loop && video.currentTime >= loop.end + LOOP_TAIL_SEC) {
            video.currentTime = loop.start;
        }
    }

    // ------------------------------------------------------------------
    // mobile fullscreen
    //
    // A CSS mode: .workbench--fs pins the section over the viewport and floats
    // the existing control bar on top of the frame, so every button keeps the
    // handler it already had. It is not the Fullscreen API, because iOS Safari
    // on iPhone exposes no requestFullscreen for ordinary elements — the only
    // thing it offers is video.webkitEnterFullscreen(), which replaces our
    // frame with Apple's player and takes the frame-step buttons, the seek bar
    // and the pose overlay with it. Native fullscreen is asked for as an extra
    // where it exists (Android Chrome), purely to drop the browser chrome, and
    // its refusal changes nothing.
    // ------------------------------------------------------------------

    function requestNativeFullscreen() {
        var el = document.documentElement;
        var fn = el.requestFullscreen || el.webkitRequestFullscreen;
        if (!fn) return;
        try {
            var p = fn.call(el);
            if (p && p.catch) p.catch(function () { /* refused; CSS mode stands */ });
        } catch (_) { /* refused; CSS mode stands */ }
    }

    function exitNativeFullscreen() {
        if (!document.fullscreenElement && !document.webkitFullscreenElement) return;
        var fn = document.exitFullscreen || document.webkitExitFullscreen;
        if (!fn) return;
        try {
            var p = fn.call(document);
            if (p && p.catch) p.catch(function () { /* nothing to undo */ });
        } catch (_) { /* nothing to undo */ }
    }

    /**
     * Reveal the controls and re-arm the idle timer. The timer is only armed
     * during playback: walking a parry one frame at a time is done paused, and
     * the buttons must not fade out from under the finger doing the walking.
     */
    function fsShowControls() {
        if (!fullscreen) return;
        root.classList.remove('workbench--fs-idle');
        if (fsIdleTimer) { clearTimeout(fsIdleTimer); fsIdleTimer = null; }
        if (!video.paused) {
            fsIdleTimer = setTimeout(function () {
                if (fullscreen && !video.paused) root.classList.add('workbench--fs-idle');
            }, FS_IDLE_MS);
        }
    }

    function setFullscreen(on) {
        on = !!on;
        if (on === fullscreen) return;
        // A collapsed viewport would give a black screen with a control bar.
        if (on && collapseBtn && root.classList.contains('workbench--collapsed')) {
            collapseBtn.click();
        }
        fullscreen = on;
        root.classList.toggle('workbench--fs', on);
        if (on) {
            // The section is sticky, so pinning it removes its box from the
            // flow and the page under it jumps. Put the reader back on exit.
            fsScrollY = window.pageYOffset || 0;
            document.body.classList.add('wb-fs-lock');
            requestNativeFullscreen();
        } else {
            root.classList.remove('workbench--fs-idle');
            if (fsIdleTimer) { clearTimeout(fsIdleTimer); fsIdleTimer = null; }
            document.body.classList.remove('wb-fs-lock');
            exitNativeFullscreen();
        }
        if (fsBtn) {
            fsBtn.setAttribute('aria-pressed', on ? 'true' : 'false');
            fsBtn.textContent = on ? '✕ 나가기' : '⛶ 전체화면';
            fsBtn.title = on ? '전체화면 나가기 (Esc)' : '전체화면으로 보기';
        }
        updateLayout();
        if (!on) window.scrollTo(0, fsScrollY);
        fsShowControls();
    }

    /**
     * The fullscreen box is not its final size at the moment the class lands —
     * the browser is still collapsing its own chrome (measured: 386px settling
     * to 390 in landscape, 786 to 844 in portrait), and on iOS Safari the URL
     * bar comes and goes again later without a resize event. Watching the box
     * itself is the only reading that stays true; a plain measurement taken on
     * entry leaves the frame off-centre for the rest of the session.
     */
    function watchFullscreenBox() {
        if (typeof ResizeObserver !== 'function' || !viewport) return;
        var lastW = 0, lastH = 0;
        new ResizeObserver(function () {
            var w = viewport.clientWidth;
            var h = viewport.clientHeight;
            // Outside fullscreen the height is ours — updateLayout writes it —
            // so reacting to it would be an echo of our own change. The width
            // is the page's, and it is what changes on the way back out.
            if (w === lastW && !(fullscreen && h !== lastH)) return;
            lastW = w;
            lastH = h;
            updateLayout();
        }).observe(viewport);
    }

    // ------------------------------------------------------------------
    // clip playback (AI pose-overlay clips, generated on demand)
    // ------------------------------------------------------------------

    function markCachedRows() {
        document.querySelectorAll('[data-clip-type]').forEach(function (el) {
            var key = el.dataset.clipType + ':' + el.dataset.clipNumber;
            if (!cachedClips.has(key)) return;
            var btn = el.classList.contains('clip-play-btn')
                ? el
                : el.querySelector('.clip-play-btn');
            if (btn) {
                btn.classList.add('clip-cached');
                btn.title = 'AI 정밀 분석 클립 준비됨 — 즉시 재생';
            }
        });
    }

    function stopClipTimer() {
        if (clipTimer) { clearInterval(clipTimer); clipTimer = null; }
    }

    /**
     * Clip generation is a background job on the server: POST /start, poll
     * /status, then GET the bytes. A single blocking GET used to work, but the
     * 1280px pose pass now runs 2-4 minutes and the tunnel in front of us gives
     * up long before that.
     */
    var CLIP_POLL_MS = 2000;              // the server ticks its job state ~1/s
    var CLIP_POLL_SLOW_MS = 3000;         // past the expected window, ease off
    var CLIP_POLL_SLOW_AFTER_SEC = 150;
    var CLIP_GIVE_UP_SEC = 600;           // 4 min worst case + queue slack
    var CLIP_NET_RETRIES = 5;             // ~10s of transient network trouble
    var CLIP_BYTES_ATTEMPTS = 3;

    var clipRunId = 0;                    // bumped to invalidate an in-flight run
    var activeClipKey = null;             // the clip currently being fetched
    var clipPollWait = null;              // pending poll delay, resolvable on cancel
    var clipProgress = null;              // per-run copy/progress state
    var activeClipLabel = null;           // that clip's row label, e.g. "교전 #12 — …"

    /**
     * Loading copy carries the row label so the coach can still tell which row
     * they clicked while the stage is covered — the timeline is scrolled away
     * behind the workbench by then, and every clip otherwise loads with the
     * same sentence.
     */
    function clipTitle(text) {
        return activeClipLabel ? activeClipLabel + ' · ' + text : text;
    }

    function clipError(message) {
        var err = new Error(message);
        err.userMessage = message;
        return err;
    }

    /** Map an HTTP failure onto something a coach can act on. */
    function clipHttpMessage(status, data) {
        var detail = data && data.detail;
        var text = typeof detail === 'string' ? detail : '';
        if (status === 404 || status === 403) {
            if (/report not found/i.test(text) || !text || /^not found$/i.test(text)) {
                if (/report not found/i.test(text)) {
                    return '이 리포트에 접근할 수 없습니다. 공유 링크가 만료되었거나 주소가 잘못되었습니다.';
                }
                return '서버가 이 클립 요청을 처리하지 못했습니다. 페이지를 새로고침한 뒤 다시 시도해 주세요.';
            }
            return text;
        }
        if (status === 405 || status === 501) {
            return '이 서버는 아직 클립 생성을 지원하지 않습니다. 페이지를 새로고침한 뒤 다시 시도해 주세요.';
        }
        if (status === 502 || status === 503 || status === 504) {
            return '서버 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.';
        }
        return text || ('클립을 불러오지 못했습니다 (' + status + ')');
    }

    /** Sleep that a cancel can cut short, so a stale run stops within a tick. */
    function clipSleep(ms) {
        return new Promise(function (resolve) {
            var handle = setTimeout(function () { clipPollWait = null; resolve(); }, ms);
            clipPollWait = { id: handle, resolve: resolve };
        });
    }

    function hideClipLoading() {
        if (loading) loading.classList.add('hidden');
        root.classList.remove('workbench--loading');
        if (stage) stage.style.visibility = '';
    }

    /**
     * Invalidate whatever clip request is in flight. Every await in the run
     * re-checks the run id afterwards, so a poll that resolves minutes later
     * cannot put a clip on the stage the coach has already navigated away from.
     */
    function cancelClipRun() {
        clipRunId += 1;
        activeClipKey = null;
        clipProgress = null;
        stopClipTimer();
        if (clipPollWait) {
            clearTimeout(clipPollWait.id);
            var wake = clipPollWait.resolve;
            clipPollWait = null;
            wake();
        }
        video.oncanplay = null;
        video.onerror = null;
        hideClipLoading();
    }

    function fmtElapsed(sec) {
        if (sec < 60) return sec + '초';
        var m = Math.floor(sec / 60);
        var s = sec % 60;
        return s ? m + '분 ' + s + '초' : m + '분';
    }

    function clipQueueCopy(pos) {
        if (typeof pos === 'number' && pos > 0) return '대기 중 ' + pos + '번째';
        return '앞선 작업이 끝나기를 기다리는 중';
    }

    /** Fetching bytes: either a clip that was already on disk, or a fresh one. */
    function showFetchCopy(sub) {
        if (loadingTitle) loadingTitle.textContent = clipTitle('AI 정밀 분석 클립 불러오는 중...');
        if (loadingSub) loadingSub.textContent = sub || '이미 생성된 클립 — 곧 재생됩니다.';
        if (progressTrack) progressTrack.classList.add('hidden');
        stopClipTimer();
        clipProgress = null;
    }

    /**
     * The bar eases toward its ceiling instead of ramping against a fixed
     * estimate: a 2-minute job and a 4-minute job both keep it visibly moving,
     * and nothing parks at 95% while the coach waits.
     */
    function clipProgressPct(runningSec) {
        return 8 + 84 * (1 - Math.exp(-runningSec / 150));
    }

    function startClipProgress(state) {
        clipProgress = state;
        if (loadingTitle) {
            loadingTitle.textContent = clipTitle('AI 정밀 분석 클립을 처음 생성하고 있습니다');
        }
        if (progressBar) {
            // Snap back to the start without animating down from the last run.
            progressBar.style.transitionDuration = '0s';
            progressBar.style.width = '0%';
            requestAnimationFrame(function () { progressBar.style.transitionDuration = ''; });
        }
        if (progressTrack) progressTrack.classList.remove('hidden');

        state.tick = function () {
            var now = Date.now();
            var elapsed = Math.round((now - state.startedAt) / 1000);
            if (state.phase === 'queued') {
                if (loadingSub) {
                    loadingSub.textContent = clipQueueCopy(state.queuePos) + ' · ' +
                        fmtElapsed(elapsed) + ' 경과 — 순서가 되면 바로 생성이 시작됩니다.';
                }
                if (progressBar) {
                    progressBar.style.width = Math.min(8, 2 + elapsed * 0.2).toFixed(1) + '%';
                }
                return;
            }
            if (loadingSub) {
                loadingSub.textContent = '보통 2~4분 걸립니다 · ' + fmtElapsed(elapsed) +
                    ' 경과 — 한 번 만들어두면 다음부터는 기다림 없이 재생됩니다.';
            }
            if (progressBar) {
                var running = (now - (state.runningSince || state.startedAt)) / 1000;
                progressBar.style.width = clipProgressPct(running).toFixed(1) + '%';
            }
        };
        state.tick();
        stopClipTimer();
        clipTimer = setInterval(state.tick, 1000);
    }

    function applyClipStatus(state, status, queuePos) {
        if (!state) return;
        state.phase = status === 'queued' ? 'queued' : 'running';
        state.queuePos = typeof queuePos === 'number' ? queuePos : null;
        if (state.phase === 'running' && !state.runningSince) state.runningSince = Date.now();
        if (state.tick) state.tick();
    }

    async function fetchClipJson(url, opts) {
        var resp;
        try {
            resp = await fetch(url, opts);
        } catch (_) {
            throw clipError('서버에 연결하지 못했습니다. 네트워크를 확인한 뒤 다시 시도해 주세요.');
        }
        var data = null;
        try { data = await resp.json(); } catch (_) { /* body was not json */ }
        return { status: resp.status, ok: resp.ok, data: data };
    }

    /** Resolves to a Blob, or null when the server says 202 (not on disk yet). */
    async function fetchClipBytes(base) {
        var resp;
        try {
            resp = await fetch(clipUrl(base));
        } catch (_) {
            throw clipError('클립을 내려받지 못했습니다. 네트워크를 확인한 뒤 다시 시도해 주세요.');
        }
        if (resp.status === 202) return null;
        if (resp.status !== 200) {
            var data = null;
            try { data = await resp.json(); } catch (_) { /* body was not json */ }
            throw clipError(clipHttpMessage(resp.status, data));
        }
        return await resp.blob();
    }

    async function startClipJob(base) {
        var res = await fetchClipJson(clipUrl(base + '/start'), { method: 'POST' });
        if (!res.ok) throw clipError(clipHttpMessage(res.status, res.data));
        return res.data || {};
    }

    /** Poll until the job is ready; throws with the server's message on failure. */
    async function pollClipJob(base, run, state) {
        var startedAt = Date.now();
        var netFails = 0;
        var idleReads = 0;
        while (true) {
            var waited = (Date.now() - startedAt) / 1000;
            await clipSleep(waited > CLIP_POLL_SLOW_AFTER_SEC ? CLIP_POLL_SLOW_MS : CLIP_POLL_MS);
            if (run !== clipRunId) return;
            if ((Date.now() - startedAt) / 1000 > CLIP_GIVE_UP_SEC) {
                throw clipError('클립 생성이 예상보다 오래 걸리고 있습니다. 잠시 후 다시 시도해 주세요.');
            }
            var res;
            try {
                res = await fetchClipJson(clipUrl(base + '/status'));
            } catch (err) {
                netFails += 1;
                if (netFails > CLIP_NET_RETRIES) throw err;
                continue;
            }
            if (run !== clipRunId) return;
            if (!res.ok) throw clipError(clipHttpMessage(res.status, res.data));
            netFails = 0;
            var data = res.data || {};
            if (data.status === 'ready') return;
            if (data.status === 'failed') {
                throw clipError(data.error || '클립 생성에 실패했습니다.');
            }
            if (data.status === 'idle') {
                // The job is not registered — server restart, or the start call
                // and this poll crossed. Let the caller re-drive it.
                idleReads += 1;
                if (idleReads > 1) return;
                continue;
            }
            idleReads = 0;
            applyClipStatus(state, data.status, data.queue_position);
        }
    }

    /** Put the fetched bytes on the stage — unchanged from the blocking flow. */
    function presentClip(blob, key, run) {
        if (clipBlobUrl) URL.revokeObjectURL(clipBlobUrl);
        clipBlobUrl = URL.createObjectURL(blob);
        showingClip = true;
        syncZoomToClipState();
        shapes = [];
        zoom = 1; panX = 0; panY = 0;
        // The clip carries a server-rendered skeleton already; ours would be
        // a second one drawn against main-video frame numbers.
        stopSkeletonLoop();
        syncSkeletonBtn();
        drawSkeleton();
        video.src = clipBlobUrl;
        video.load();

        video.oncanplay = function () {
            if (run !== clipRunId) return;
            activeClipKey = null;
            stopClipTimer();
            clipProgress = null;
            hideClipLoading();
            updateLayout();
            reassertMute();
            video.play().catch(function () {});
            cachedClips.add(key);
            markCachedRows();
            if (sourceChip && hasMainVideo) sourceChip.classList.remove('hidden');
        };
        video.onerror = function () {
            if (run !== clipRunId) return;
            activeClipKey = null;
            stopClipTimer();
            clipProgress = null;
            hideClipLoading();
            if (errorEl) {
                // The bytes are on the server either way, so a retry is quick.
                errorEl.textContent = '클립을 재생할 수 없습니다. 다시 눌러 주세요.';
                errorEl.classList.remove('hidden');
            }
        };
    }

    function showStage() {
        root.classList.remove('workbench--empty');
        if (placeholder) placeholder.classList.add('hidden');
        if (stage) stage.classList.remove('hidden');
    }

    function restoreMainVideo() {
        // Going back to the source cancels a clip that is still generating —
        // otherwise its poll would resolve minutes later and take the stage.
        var wasLoadingClip = !!activeClipKey;
        cancelClipRun();
        if (!hasMainVideo) return;
        if (!showingClip) {
            if (wasLoadingClip) showStage();
            return;
        }
        showingClip = false;
        syncZoomToClipState();
        if (clipBlobUrl) { URL.revokeObjectURL(clipBlobUrl); clipBlobUrl = null; }
        video.src = mainSrc;
        video.load();
        shapes = [];
        zoom = 1; panX = 0; panY = 0;
        if (sourceChip) sourceChip.classList.add('hidden');
        setLoop(null);
        showStage();
        // Back on the source video, so the overlay is meaningful again. The
        // actual repaint lands in updateLayout() once loadedmetadata fires.
        syncSkeletonBtn();
        drawSkeleton();
    }

    async function playClip(type, number, label) {
        if (!CLIP_REPORT_ID) return;
        var key = type + ':' + number;

        // Clicking the same row again while it is generating must not open a
        // second request cycle — the server dedupes, but we should not ask it to.
        if (activeClipKey === key) {
            root.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            return;
        }

        cancelClipRun();
        var run = clipRunId;
        activeClipKey = key;
        activeClipLabel = label || null;

        var base = '/api/analytics/clips/' + CLIP_REPORT_ID + '/' + type + '/' + number;

        showStage();
        setLoop(null);
        if (stage) stage.style.visibility = 'hidden';
        root.classList.add('workbench--loading');
        if (loading) loading.classList.remove('hidden');
        if (errorEl) errorEl.classList.add('hidden');
        root.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

        try {
            // A clip we already played this session is on disk: go straight for
            // the bytes, exactly as the old flow did, so a replay stays instant.
            var believedCached = cachedClips.has(key);
            showFetchCopy(believedCached ? null : '서버에 클립을 요청하는 중입니다...');
            var attempt = 0;
            while (true) {
                if (!believedCached) {
                    var job = await startClipJob(base);
                    if (run !== clipRunId) return;
                    if (job.status === 'ready') {
                        showFetchCopy();
                    } else {
                        var state = {
                            startedAt: Date.now(),
                            runningSince: job.status === 'running' ? Date.now() : 0,
                            phase: job.status === 'queued' ? 'queued' : 'running',
                            queuePos: null
                        };
                        startClipProgress(state);
                        await pollClipJob(base, run, state);
                        if (run !== clipRunId) return;
                        showFetchCopy('생성 완료 — 클립을 불러오는 중입니다.');
                    }
                }
                var blob = await fetchClipBytes(base);
                if (run !== clipRunId) return;
                if (blob) { presentClip(blob, key, run); return; }

                // 202: not on disk after all. Either our cache belief was stale
                // or the job vanished between the poll and the fetch.
                cachedClips.delete(key);
                believedCached = false;
                attempt += 1;
                if (attempt >= CLIP_BYTES_ATTEMPTS) {
                    throw clipError('클립을 받아오지 못했습니다. 잠시 후 다시 시도해 주세요.');
                }
            }
        } catch (e) {
            if (run !== clipRunId) return;
            activeClipKey = null;
            stopClipTimer();
            clipProgress = null;
            hideClipLoading();
            if (errorEl) {
                errorEl.textContent = e.userMessage || '클립을 불러올 수 없습니다.';
                errorEl.classList.remove('hidden');
            }
        }
    }

    // ------------------------------------------------------------------
    // timeline wiring
    // ------------------------------------------------------------------

    function rowRange(row) {
        var sf = row.dataset.startFrame;
        var ef = row.dataset.endFrame;
        if (sf !== undefined && ef !== undefined) {
            return { start: Number(sf) / FPS, end: Number(ef) / FPS };
        }
        var tf = row.dataset.touchFrame;
        if (tf !== undefined) {
            var t = Number(tf) / FPS;
            return { start: Math.max(0, t - TOUCH_LEAD_SEC), end: t + TOUCH_TAIL_SEC };
        }
        return null;
    }

    function wireTimeline() {
        document.querySelectorAll('.timeline-row[data-clip-type]').forEach(function (row) {
            row.addEventListener('click', function () {
                var label = row.dataset.clipLabel;
                var range = rowRange(row);
                if (hasMainVideo && !showingClip && range) {
                    seekRange(range.start, range.end, label);
                } else if (hasMainVideo && showingClip && range) {
                    restoreMainVideo();
                    // load() resets the media element, so wait for it to be seekable
                    video.addEventListener('loadedmetadata', function once() {
                        video.removeEventListener('loadedmetadata', once);
                        seekRange(range.start, range.end, label);
                    });
                } else {
                    playClip(row.dataset.clipType, row.dataset.clipNumber, label);
                }
                if (!isDesktop()) {
                    root.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            });
        });

        document.querySelectorAll('.clip-play-btn').forEach(function (btn) {
            btn.addEventListener('click', function (e) {
                e.stopPropagation();
                var holder = btn.closest('[data-clip-label]');
                playClip(btn.dataset.clipType, btn.dataset.clipNumber,
                         holder ? holder.dataset.clipLabel : null);
            });
        });
    }

    // ------------------------------------------------------------------
    // event wiring
    // ------------------------------------------------------------------

    function wireControls() {
        if (playBtn) playBtn.addEventListener('click', togglePlay);
        var back = document.getElementById('wb-frame-back');
        var fwd = document.getElementById('wb-frame-fwd');
        if (back) back.addEventListener('click', function () { stepFrame(-1); });
        if (fwd) fwd.addEventListener('click', function () { stepFrame(1); });
        // Bigger steps: a parry occupies three or four frames, so finding one
        // means crossing the dead time between phrases without watching it, and
        // then walking the exchange itself one frame at a time.
        [['wb-frame-back20', -20], ['wb-frame-back10', -10],
         ['wb-frame-fwd10', 10], ['wb-frame-fwd20', 20]].forEach(function (pair) {
            var el = document.getElementById(pair[0]);
            if (el) el.addEventListener('click', function () { stepFrame(pair[1]); });
        });

        root.querySelectorAll('[data-speed]').forEach(function (b) {
            b.addEventListener('click', function () { setSpeed(Number(b.dataset.speed)); });
        });
        if (speedSelect) {
            speedSelect.addEventListener('change', function () {
                setSpeed(Number(speedSelect.value));
            });
        }

        var zi = document.getElementById('wb-zoom-in');
        var zo = document.getElementById('wb-zoom-out');
        var zr = document.getElementById('wb-zoom-reset');
        if (zi) zi.addEventListener('click', function () { setZoom(zoom * 1.3); });
        if (zo) zo.addEventListener('click', function () { setZoom(zoom / 1.3); });
        if (zr) zr.addEventListener('click', function () { zoom = 1; panX = 0; panY = 0; applyTransform(); });

        root.querySelectorAll('[data-tool]').forEach(function (b) {
            b.addEventListener('click', function () { setTool(b.dataset.tool); });
        });
        root.querySelectorAll('[data-color]').forEach(function (b) {
            b.addEventListener('click', function () {
                drawColor = b.dataset.color;
                root.querySelectorAll('[data-color]').forEach(function (o) {
                    o.classList.toggle('wb-btn--on', o === b);
                });
            });
        });
        var clearBtn = document.getElementById('wb-clear');
        if (clearBtn) {
            clearBtn.addEventListener('click', function () { shapes = []; pending = null; redraw(); });
        }
        if (calibBtn) {
            calibBtn.addEventListener('click', function () {
                if (calibrating) { endCalibration(false); } else { startCalibration(); }
            });
        }

        var loopClear = document.getElementById('wb-loop-clear');
        if (loopClear) {
            loopClear.addEventListener('click', function () { setLoop(null); });
        }
        if (sourceChip) sourceChip.addEventListener('click', restoreMainVideo);

        // Sub-toggles live in an optional popover next to the master button. If
        // the markup is not there, the parts simply stay at their stored values.
        loadOverlayPrefs();
        syncOverlayToggles();
        if (ovMenu) {
            ovMenu.querySelectorAll('[data-ov]').forEach(function (b) {
                b.addEventListener('click', function () {
                    setOverlayPart(b.dataset.ov, !overlayParts[b.dataset.ov]);
                });
            });
        }
        if (ovMenuBtn && ovMenu) {
            ovMenuBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                var open = ovMenu.classList.toggle('wb-ov-menu--open');
                ovMenuBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
            });
            document.addEventListener('click', function (e) {
                if (!ovMenu.classList.contains('wb-ov-menu--open')) return;
                if (ovMenu.contains(e.target) || e.target === ovMenuBtn) return;
                ovMenu.classList.remove('wb-ov-menu--open');
                ovMenuBtn.setAttribute('aria-expanded', 'false');
            });
        }

        if (skeletonBtn && KEYPOINTS_URL) {
            skeletonBtn.addEventListener('click', function () {
                if (showingClip) return;
                setSkeletonEnabled(!skeletonOn, true);
            });
            var storedSkeleton = null;
            try { storedSkeleton = localStorage.getItem(SKELETON_KEY); } catch (_) { /* private mode */ }
            syncSkeletonBtn();
            // Default off; only a stored opt-in pays the sidecar fetch on load.
            if (storedSkeleton === '1') setSkeletonEnabled(true, false);
        } else if (skeletonBtn) {
            // Markup without a sidecar URL: nothing to draw, so do not pretend.
            skeletonBtn.classList.add('hidden');
            if (ovMenuBtn) ovMenuBtn.classList.add('hidden');
            if (captionBar) captionBar.classList.add('hidden');
        }

        if (muteBtn) {
            muteBtn.addEventListener('click', function () { applyMute(!video.muted, true); });
            var storedMute = null;
            try { storedMute = localStorage.getItem(MUTE_KEY); } catch (_) { /* private mode */ }
            // Default muted: only an explicit '0' turns the sound back on.
            applyMute(storedMute !== '0', false);
        }

        if (collapseBtn) {
            collapseBtn.addEventListener('click', function () {
                var collapsed = root.classList.toggle('workbench--collapsed');
                collapseBtn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
                collapseBtn.textContent = collapsed ? '▾ 펼치기' : '▴ 접기';
                try { localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0'); } catch (_) { /* private mode */ }
                if (!collapsed) updateLayout();
            });
            var stored = null;
            try { stored = localStorage.getItem(COLLAPSE_KEY); } catch (_) { /* private mode */ }
            if (stored === '1') collapseBtn.click();
        }

        if (seekBar) {
            seekBar.addEventListener('input', function () {
                seekBar.dataset.dragging = '1';
                video.currentTime = Number(seekBar.value);
            });
            seekBar.addEventListener('change', function () { delete seekBar.dataset.dragging; });
        }

        if (fsBtn) {
            fsBtn.addEventListener('click', function () { setFullscreen(!fullscreen); });
        }
        // Every touch of the bar counts as "still working" and restarts the
        // idle countdown, so the controls only fade while the coach is watching
        // rather than driving.
        if (controlsBar) {
            ['pointerdown', 'click', 'input', 'change'].forEach(function (ev) {
                controlsBar.addEventListener(ev, fsShowControls);
            });
        }
        // Pausing must bring the buttons straight back — that is the moment the
        // frame-stepping starts.
        video.addEventListener('play', fsShowControls);
        video.addEventListener('pause', fsShowControls);

        // Leaving native fullscreen through the browser's own UI (the system
        // gesture, or Esc on desktop Chrome) must take the CSS mode with it,
        // otherwise the page is left pinned with no way out but the button.
        ['fullscreenchange', 'webkitfullscreenchange'].forEach(function (ev) {
            document.addEventListener(ev, function () {
                if (!fullscreen) return;
                if (!document.fullscreenElement && !document.webkitFullscreenElement) {
                    setFullscreen(false);
                }
            });
        });

        // Rotating the phone changes both the box and the video's fitted size.
        // Safari reports the new metrics a beat after the event fires.
        window.addEventListener('orientationchange', function () {
            setTimeout(updateLayout, 200);
        });
    }

    function setZoom(next) {
        zoom = clamp(next, ZOOM_MIN, ZOOM_MAX);
        if (zoom === 1) { panX = 0; panY = 0; }
        applyTransform();
    }

    function wireStageInteraction() {
        if (!viewport) return;

        // Touch pinch-zoom and drag-pan. The bout video is a piste crop about
        // five times wider than it is tall, so on a phone it fits as a thin
        // strip whatever the orientation — "fullscreen" only becomes useful if
        // the coach can push the part they are watching out to fill the screen.
        var touchPinch = null;
        function touchDist(t) {
            return Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
        }
        function touchMid(t) {
            return {x: (t[0].clientX + t[1].clientX) / 2, y: (t[0].clientY + t[1].clientY) / 2};
        }
        viewport.addEventListener('touchstart', function (e) {
            if (!hasSource()) return;
            if (e.touches.length === 2) {
                var t = [e.touches[0], e.touches[1]];
                touchPinch = {dist: touchDist(t), zoom: zoom, mid: touchMid(t), panX: panX, panY: panY};
            } else if (e.touches.length === 1 && zoom > 1) {
                touchPinch = {drag: {x: e.touches[0].clientX, y: e.touches[0].clientY},
                              panX: panX, panY: panY};
            }
        }, {passive: true});
        viewport.addEventListener('touchmove', function (e) {
            if (!touchPinch || !hasSource()) return;
            if (touchPinch.drag && e.touches.length === 1) {
                e.preventDefault();
                panX = touchPinch.panX + (e.touches[0].clientX - touchPinch.drag.x);
                panY = touchPinch.panY + (e.touches[0].clientY - touchPinch.drag.y);
                applyTransform();
                return;
            }
            if (e.touches.length !== 2 || !touchPinch.dist) return;
            e.preventDefault();
            var t = [e.touches[0], e.touches[1]];
            var next = clamp(touchPinch.zoom * (touchDist(t) / touchPinch.dist), ZOOM_MIN, ZOOM_MAX);
            var r = viewport.getBoundingClientRect();
            var localX = (touchPinch.mid.x - r.left - centerX - touchPinch.panX) / touchPinch.zoom;
            var localY = (touchPinch.mid.y - r.top - centerY - touchPinch.panY) / touchPinch.zoom;
            var mid = touchMid(t);
            panX = (mid.x - r.left) - centerX - localX * next;
            panY = (mid.y - r.top) - centerY - localY * next;
            zoom = next;
            if (zoom === 1) { panX = 0; panY = 0; }
            applyTransform();
        }, {passive: false});
        viewport.addEventListener('touchend', function (e) {
            if (e.touches.length === 0) touchPinch = null;
        }, {passive: true});

        viewport.addEventListener('wheel', function (e) {
            if (!hasSource() || !isDesktop()) return;
            // The workbench is sticky and full-width, so the cursor sits over it
            // for most of the page. Swallowing every wheel event there would
            // trap the scroll; zoom only once the coach has opted in — with a
            // modifier, a trackpad pinch (which arrives as ctrlKey), or by
            // having already zoomed in with the +/- buttons.
            if (zoom === 1 && !e.ctrlKey && !e.altKey) return;
            e.preventDefault();
            var r = viewport.getBoundingClientRect();
            var left = r.left + centerX + panX;
            var top = r.top + centerY + panY;
            var localX = (e.clientX - left) / zoom;
            var localY = (e.clientY - top) / zoom;
            var next = clamp(zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15), ZOOM_MIN, ZOOM_MAX);
            panX = (e.clientX - r.left) - centerX - localX * next;
            panY = (e.clientY - r.top) - centerY - localY * next;
            zoom = next;
            if (zoom === 1) { panX = 0; panY = 0; }
            applyTransform();
        }, { passive: false });

        viewport.addEventListener('pointerdown', function (e) {
            if (!hasSource() || !isDesktop()) return;
            if (tool === 'navigate') {
                if (zoom === 1) return;
                panning = { x: e.clientX, y: e.clientY };
                viewport.setPointerCapture(e.pointerId);
                return;
            }
            var p = toIntrinsic(e.clientX, e.clientY);
            pending = { type: tool, x1: p.x, y1: p.y, x2: p.x, y2: p.y, color: drawColor };
            viewport.setPointerCapture(e.pointerId);
        });

        viewport.addEventListener('pointermove', function (e) {
            if (panning) {
                panX += e.clientX - panning.x;
                panY += e.clientY - panning.y;
                panning = { x: e.clientX, y: e.clientY };
                applyTransform();
                return;
            }
            if (!pending) return;
            var p = toIntrinsic(e.clientX, e.clientY);
            pending.x2 = p.x;
            pending.y2 = p.y;
            redraw();
        });

        function finish(e) {
            if (panning) { panning = null; return; }
            if (!pending) return;
            var len = Math.hypot(pending.x2 - pending.x1, pending.y2 - pending.y1);
            if (len >= 4) {
                if (calibrating) {
                    bhPixels = len;
                    endCalibration(true);
                } else {
                    shapes.push(pending);
                }
            }
            pending = null;
            redraw();
            if (e && e.pointerId !== undefined) {
                try { viewport.releasePointerCapture(e.pointerId); } catch (_) { /* already released */ }
            }
        }
        viewport.addEventListener('pointerup', finish);
        viewport.addEventListener('pointercancel', finish);

        // Fullscreen: a tap on the picture brings the faded controls back, and
        // dismisses them again only while something is playing — a tap while
        // paused can never hide the buttons the coach is stepping with.
        viewport.addEventListener('click', function () {
            if (!fullscreen) return;
            if (root.classList.contains('workbench--fs-idle') || video.paused) {
                fsShowControls();
                return;
            }
            if (fsIdleTimer) { clearTimeout(fsIdleTimer); fsIdleTimer = null; }
            root.classList.add('workbench--fs-idle');
        });
    }

    function wireKeyboard() {
        document.addEventListener('keydown', function (e) {
            var t = e.target;
            if (t && /^(INPUT|SELECT|TEXTAREA)$/.test(t.tagName)) return;
            if (t && t.isContentEditable) return;
            if (e.metaKey || e.ctrlKey || e.altKey) return;

            switch (e.key) {
                // Only claim the scroll/caret keys when there is something to
                // drive; an empty workbench must not break normal paging.
                case ' ':
                    if (!hasSource()) return;
                    e.preventDefault(); togglePlay(); break;
                case 'ArrowLeft':
                    if (!hasSource()) return;
                    e.preventDefault(); if (e.shiftKey) { jump(-1); } else { stepFrame(-1); } break;
                case 'ArrowRight':
                    if (!hasSource()) return;
                    e.preventDefault(); if (e.shiftKey) { jump(1); } else { stepFrame(1); } break;
                case ',':
                    e.preventDefault(); stepFrame(-10); break;
                case '<':
                    e.preventDefault(); stepFrame(-20); break;
                case '.':
                    e.preventDefault(); stepFrame(10); break;
                case '>':
                    e.preventDefault(); stepFrame(20); break;
                case '1': setSpeed(SPEEDS[0]); break;
                case '2': setSpeed(SPEEDS[1]); break;
                case '3': setSpeed(SPEEDS[2]); break;
                case '4': setSpeed(SPEEDS[3]); break;
                case 'd': case 'D': if (isDesktop()) setTool('line'); break;
                case 'm': case 'M': if (isDesktop()) setTool('measure'); break;
                case 'v': case 'V': setTool('navigate'); break;
                case 'z': case 'Z': setSolo('zoom'); break;
                case 'Escape':
                    // A hardware keyboard on a tablet is the case this covers.
                    if (fullscreen) { setFullscreen(false); break; }
                    setLoop(null); if (calibrating) endCalibration(false); break;
                default: break;
            }
        });
    }

    // ------------------------------------------------------------------
    // boot
    // ------------------------------------------------------------------

    if (hasMainVideo && mainSrc) {
        video.src = mainSrc;
    } else {
        root.classList.add('workbench--empty');
        if (stage) stage.classList.add('hidden');
        if (placeholder) placeholder.classList.remove('hidden');
    }

    video.addEventListener('loadedmetadata', updateLayout);
    video.addEventListener('loadedmetadata', reassertMute);
    video.addEventListener('play', syncPlayLabel);
    video.addEventListener('pause', syncPlayLabel);
    video.addEventListener('timeupdate', onTimeUpdate);
    window.addEventListener('resize', updateLayout);

    // The overlay follows playback on rAF, and falls back to the media events
    // for the paused cases (scrubbing, frame stepping) where no frames render.
    video.addEventListener('play', startSkeletonLoop);
    video.addEventListener('pause', function () { stopSkeletonLoop(); drawSkeleton(); });
    video.addEventListener('ended', function () { stopSkeletonLoop(); drawSkeleton(); });
    video.addEventListener('timeupdate', drawSkeleton);
    video.addEventListener('seeked', drawSkeleton);

    // Redraw measurement labels when the coach changes the height used for the
    // metre conversion — the shapes are unchanged, only their labels are.
    var heightInput = document.getElementById('bh-height-input');
    if (heightInput) heightInput.addEventListener('input', redraw);

    // The exchange/touch slice the annotations narrate. Reports without one
    // (gallery pages that ship no report payload) simply get bones and distance.
    try {
        insight = buildInsight();
    } catch (_) {
        insight = null;
    }
    // No sidecar means no overlay at all, so the caption band would be a bar of
    // dead space under the video.
    if (!KEYPOINTS_URL && captionBar) captionBar.classList.add('hidden');

    wireControls();
    wireZoom();
    watchFullscreenBox();
    wireStageInteraction();
    wireKeyboard();
    wireTimeline();
    setTool('navigate');
    setSpeed(1);
    syncPlayLabel();
    updateLayout();

    if (CLIP_REPORT_ID) {
        fetch(clipUrl('/api/analytics/clips/' + CLIP_REPORT_ID + '/status'))
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (data) {
                if (!data || !data.cached) return;
                (data.cached.touch || []).forEach(function (n) { cachedClips.add('touch:' + n); });
                (data.cached.exchange || []).forEach(function (n) { cachedClips.add('exchange:' + n); });
                markCachedRows();
            })
            .catch(function () { /* status is an optimisation, not a requirement */ });
    }

    window.FMWorkbench = {
        seekRange: seekRange,
        playClip: playClip,
        setSpeed: setSpeed,
        restoreMainVideo: restoreMainVideo,
        // The second camera's state, so the sync can be checked as numbers
        // rather than by looking at two pictures and believing them.
        zoom: {
            enabled: function () { return hasZoom; },
            offset: function () { return hasZoom ? zoomOffset : null; },
            solo: function () { return solo; },
            setSolo: setSolo,
            inGap: function () { return zoomInGap; }
        },
        // The annotation maths is pure, so the numbers drawn on the video can be
        // checked against the report's own figures without driving the UI. There
        // is no JS test runner in this repo; this is how the check is run.
        overlay: {
            sampleIndex: skeletonSampleIndex,
            metricsAt: metricsAt,
            smoothedDistance: smoothedDistance,
            zoneFor: function (bh) { return DISTANCE_ZONES[zoneIndexFor(bh)]; },
            motionAt: rawMotion,
            motionShownAt: motionFor,
            insight: function () { return insight; },
            parts: overlayParts
        }
    };
})();
