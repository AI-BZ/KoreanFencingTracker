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
    var skeletonBtn = document.getElementById('wb-skeleton-toggle');
    var muteBtn = document.getElementById('wb-mute');
    var toast = document.getElementById('wb-toast');

    var ctx = canvas ? canvas.getContext('2d') : null;
    var skelCtx = skelCanvas ? skelCanvas.getContext('2d') : null;

    // ---- state ----
    var hasMainVideo = root.dataset.hasVideo === '1';
    var mainSrc = hasMainVideo ? (root.dataset.mainSrc || '') : '';
    var showingClip = false;
    var clipBlobUrl = null;
    var clipTimer = null;

    var zoom = 1, panX = 0, panY = 0;
    var stageW = 0, stageH = 0, centerX = 0;
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

    var cachedClips = new Set();

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
        var vpW = viewport.clientWidth;
        if (!vpW) return;
        var vw = video.videoWidth || 16;
        var vh = video.videoHeight || 9;
        var ratio = vw / vh;
        var maxH = window.innerHeight * (isDesktop() ? 0.45 : 0.32);

        var w = vpW;
        var h = w / ratio;
        if (h > maxH) { h = maxH; w = h * ratio; }

        stageW = w;
        stageH = h;
        centerX = Math.max(0, (vpW - w) / 2);

        stage.style.width = w + 'px';
        stage.style.height = h + 'px';
        stage.style.left = centerX + 'px';
        viewport.style.height = h + 'px';

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
        var top = r.top + panY;
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

    function drawSkeleton() {
        if (!skelCtx) return;
        skelCtx.clearRect(0, 0, skelCanvas.width, skelCanvas.height);
        // An AI clip already has a skeleton burned in by the server, and its
        // frame numbers do not line up with the main video's, so a second
        // overlay there would be drawing the wrong pose on the wrong frame.
        if (!skeletonOn || showingClip || !skeletonData) return;

        var poses = skeletonData.poses || {};
        var idx = skeletonSampleIndex(video.currentTime);
        // Normally 1:1 — the sidecar is in the video's own pixel space. The
        // ratio only matters if the served video was re-encoded at another size.
        var sx = skeletonData.frame_width > 0 ? skelCanvas.width / skeletonData.frame_width : 1;
        var sy = skeletonData.frame_height > 0 ? skelCanvas.height / skeletonData.frame_height : 1;
        // Scaled to the frame so the overlay looks the same on 720p and 1080p;
        // the floor keeps it legible on the small crops some reports carry.
        var lw = Math.max(2.5, skelCanvas.width / 420);

        drawSkeletonSide(poses.left, idx, SKELETON_LEFT_COLOR, lw, sx, sy);
        drawSkeletonSide(poses.right, idx, SKELETON_RIGHT_COLOR, lw, sx, sy);
    }

    function skeletonTick() {
        skelRaf = null;
        drawSkeleton();
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

    function syncSkeletonBtn() {
        if (!skeletonBtn) return;
        skeletonBtn.classList.toggle('wb-btn--on', skeletonOn && !showingClip);
        skeletonBtn.disabled = showingClip;
        skeletonBtn.title = showingClip
            ? 'AI 정밀 분석 클립에는 이미 스켈레톤이 입혀져 있습니다 — 원본 영상으로 돌아가면 다시 사용할 수 있습니다'
            : '추적된 두 선수의 관절을 원본 영상 위에 그대로 그립니다 — 클립을 만들지 않고 즉시 표시됩니다';
    }

    function applySkeletonState(on, persist) {
        skeletonOn = !!on;
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
        if (loadingTitle) loadingTitle.textContent = 'AI 정밀 분석 클립 불러오는 중...';
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
            loadingTitle.textContent = 'AI 정밀 분석 클립을 처음 생성하고 있습니다';
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
    }

    function setZoom(next) {
        zoom = clamp(next, ZOOM_MIN, ZOOM_MAX);
        if (zoom === 1) { panX = 0; panY = 0; }
        applyTransform();
    }

    function wireStageInteraction() {
        if (!viewport) return;

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
            var top = r.top + panY;
            var localX = (e.clientX - left) / zoom;
            var localY = (e.clientY - top) / zoom;
            var next = clamp(zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15), ZOOM_MIN, ZOOM_MAX);
            panX = (e.clientX - r.left) - centerX - localX * next;
            panY = (e.clientY - r.top) - localY * next;
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
                case '1': setSpeed(SPEEDS[0]); break;
                case '2': setSpeed(SPEEDS[1]); break;
                case '3': setSpeed(SPEEDS[2]); break;
                case '4': setSpeed(SPEEDS[3]); break;
                case 'd': case 'D': if (isDesktop()) setTool('line'); break;
                case 'm': case 'M': if (isDesktop()) setTool('measure'); break;
                case 'v': case 'V': setTool('navigate'); break;
                case 'Escape': setLoop(null); if (calibrating) endCalibration(false); break;
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

    wireControls();
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
        restoreMainVideo: restoreMainVideo
    };
})();
