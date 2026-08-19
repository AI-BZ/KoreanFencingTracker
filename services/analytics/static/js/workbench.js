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

    var SPEEDS = [1, 0.5, 0.25, 1 / 6];
    var ZOOM_MIN = 1;
    var ZOOM_MAX = 8;
    var LOOP_TAIL_SEC = 0.3;          // let the end of the action land before looping
    var TOUCH_LEAD_SEC = 3;           // touch rows without a matched exchange
    var TOUCH_TAIL_SEC = 1;
    var COLLAPSE_KEY = 'fm-workbench-collapsed';

    // ---- elements ----
    var viewport = document.getElementById('wb-viewport');
    var stage = document.getElementById('wb-stage');
    var video = document.getElementById('wb-video');
    var canvas = document.getElementById('wb-canvas');
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
    var toast = document.getElementById('wb-toast');

    var ctx = canvas ? canvas.getContext('2d') : null;

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
        applyTransform();
        redraw();
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
                btn.title = 'AI 오버레이 클립 준비됨 — 즉시 재생';
            }
        });
    }

    function stopClipTimer() {
        if (clipTimer) { clearInterval(clipTimer); clipTimer = null; }
    }

    function showStage() {
        root.classList.remove('workbench--empty');
        if (placeholder) placeholder.classList.add('hidden');
        if (stage) stage.classList.remove('hidden');
    }

    function restoreMainVideo() {
        if (!hasMainVideo || !showingClip) return;
        showingClip = false;
        if (clipBlobUrl) { URL.revokeObjectURL(clipBlobUrl); clipBlobUrl = null; }
        video.src = mainSrc;
        video.load();
        shapes = [];
        zoom = 1; panX = 0; panY = 0;
        if (sourceChip) sourceChip.classList.add('hidden');
        setLoop(null);
        showStage();
    }

    async function playClip(type, number, label) {
        if (!CLIP_REPORT_ID) return;
        var url = clipUrl('/api/analytics/clips/' + CLIP_REPORT_ID + '/' + type + '/' + number);
        var key = type + ':' + number;
        var isCached = cachedClips.has(key);

        showStage();
        setLoop(null);
        if (stage) stage.style.visibility = 'hidden';
        root.classList.add('workbench--loading');
        if (loading) loading.classList.remove('hidden');
        if (errorEl) errorEl.classList.add('hidden');
        stopClipTimer();

        if (isCached) {
            if (loadingTitle) loadingTitle.textContent = 'AI 오버레이 클립 불러오는 중...';
            if (loadingSub) loadingSub.textContent = '이미 생성된 클립 — 곧 재생됩니다.';
            if (progressTrack) progressTrack.classList.add('hidden');
        } else {
            if (loadingTitle) loadingTitle.textContent = 'AI 포즈 오버레이 클립을 처음 생성하고 있습니다';
            if (progressTrack) progressTrack.classList.remove('hidden');
            if (progressBar) progressBar.style.width = '3%';
            var startedAt = Date.now();
            var expectedSec = 60;
            var tick = function () {
                var elapsed = Math.round((Date.now() - startedAt) / 1000);
                if (loadingSub) {
                    loadingSub.textContent = '약 1분 소요 · ' + elapsed +
                        '초 경과 — 한 번 생성된 클립은 다음부터 즉시 재생됩니다.';
                }
                if (progressBar) {
                    progressBar.style.width = Math.min(95, 3 + (elapsed / expectedSec) * 92) + '%';
                }
            };
            tick();
            clipTimer = setInterval(tick, 1000);
        }

        root.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

        try {
            var resp = await fetch(url);
            if (!resp.ok) {
                var detail;
                try { detail = (await resp.json()).detail; } catch (_) { /* body was not json */ }
                throw new Error(detail || '클립 생성 실패 (' + resp.status + ')');
            }
            var blob = await resp.blob();
            if (clipBlobUrl) URL.revokeObjectURL(clipBlobUrl);
            clipBlobUrl = URL.createObjectURL(blob);
            showingClip = true;
            shapes = [];
            zoom = 1; panX = 0; panY = 0;
            video.src = clipBlobUrl;
            video.load();

            video.oncanplay = function () {
                stopClipTimer();
                if (loading) loading.classList.add('hidden');
                root.classList.remove('workbench--loading');
                if (stage) stage.style.visibility = '';
                updateLayout();
                video.play().catch(function () {});
                cachedClips.add(key);
                markCachedRows();
                if (sourceChip && hasMainVideo) sourceChip.classList.remove('hidden');
            };
            video.onerror = function () {
                stopClipTimer();
                if (loading) loading.classList.add('hidden');
                root.classList.remove('workbench--loading');
                if (stage) stage.style.visibility = '';
                if (errorEl) {
                    errorEl.textContent = '클립을 재생할 수 없습니다.';
                    errorEl.classList.remove('hidden');
                }
            };
        } catch (e) {
            stopClipTimer();
            if (loading) loading.classList.add('hidden');
            root.classList.remove('workbench--loading');
            if (stage) stage.style.visibility = '';
            if (errorEl) {
                errorEl.textContent = e.message || '클립을 불러올 수 없습니다.';
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
    video.addEventListener('play', syncPlayLabel);
    video.addEventListener('pause', syncPlayLabel);
    video.addEventListener('timeupdate', onTimeUpdate);
    window.addEventListener('resize', updateLayout);

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
