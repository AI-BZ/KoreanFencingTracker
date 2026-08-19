/* ============================================================================
   DE 매치 시트 (Phase 3)
   대진표의 경기 블록을 누르면 열리는 상세 시트.

   답해야 하는 질문 (대회장에서 폰을 든 학부모 기준):
     1) 이 경기 누구랑 누구고, 어떻게 됐나
     2) 둘이 전에 붙은 적 있나 — 특히 DE 에서
     3) 이기면 다음에 누구를 만나나
     4) 이 선수가 여기까지 어떻게 왔나 (경로) — 시트 안에서 뷰를 바꿔 답한다

   설계 원칙
   - 데이터의 1차 소스는 이미 렌더된 대진표 DOM 이다. 화면에 없는 것을 지어내지 않는다.
   - "다음 상대" 는 예측이 아니라 대진표의 인접성(형제 경기)이라는 수학적 사실로만 계산한다.
     계산 전제(라운드 경기 수가 2의 거듭제곱, 다음 라운드가 정확히 절반)가 깨지면
     후보를 나열하지 않고 "계산할 수 없다" 고 말한다. (제1원칙)
   - 확정과 예상은 형태(실선/점선)와 글자(배지)로 구분한다. 색만으로 구분하지 않는다.
   - 시트는 body 직속 position:fixed 라 128강 트리의 레이아웃을 건드리지 않는다.

   소유: 이 파일 + bracket.css 의 "DE MATCH SHEET" 섹션 + event_result.html 의 시트 마크업.
   bracket.html 은 건드리지 않는다 — #tab-tournament 이벤트 위임으로 클릭을 받는다.
   ============================================================================ */
(function () {
    'use strict';

    var SHEET_ID = 'match-sheet';
    var H2H_TIMEOUT_MS = 4000;

    var sheet = null;
    var backdrop = null;
    var originBlock = null;      // 시트를 연 경기 블록 (닫을 때 포커스 복귀용)
    var lastInfo = null;         // 현재 시트가 보여주는 경기 (경로 → 뒤로가기 때 헤더 복원)
    var lastFocus = null;
    var reqSeq = 0;              // 비동기 전적 응답이 늦게 와서 다른 경기에 얹히는 것 방지
    var routeSeq = 0;            // 최종순위 응답이 다른 선수의 경로에 얹히는 것 방지
    var dragBound = false;
    var mounted = false;

    // ---------- 유틸 ----------
    function t(s) { try { return (typeof _t === 'function') ? (_t(s) || s) : s; } catch (e) { return s; } }
    function trP(s) { try { return (typeof _tr_player === 'function') ? (_tr_player(s) || s) : s; } catch (e) { return s; } }
    function trT(s) { try { return (typeof _tr_team === 'function') ? (_tr_team(s) || s) : s; } catch (e) { return s; } }
    function trC(s) { try { return (typeof _tr_comp === 'function') ? (_tr_comp(s) || s) : s; } catch (e) { return s; } }

    function esc(s) {
        if (typeof _mpEscapeHtml === 'function') return _mpEscapeHtml(s);
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function isDesktop() {
        try { return window.matchMedia('(min-width: 1025px)').matches; } catch (e) { return window.innerWidth > 1024; }
    }
    function reducedMotion() {
        try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { return false; }
    }
    function isPow2(n) { return n > 0 && (n & (n - 1)) === 0; }

    // 숫자만 콘덴스드 서체로. 한글이 섞인 문자열에 .fm-num 을 주면 안 된다(latin 서브셋만 로드됨).
    function num(v) { return '<span class="fm-num">' + esc(v) + '</span>'; }

    // 승/패 표기: "2승 1패" — 숫자만 .fm-num 으로 감싼다
    function recordText(w, l) { return num(w) + esc(t('승')) + ' ' + num(l) + esc(t('패')); }

    function eventWeapon() {
        return (typeof window.EVENT_WEAPON === 'string') ? window.EVENT_WEAPON : '';
    }
    function competitionName() {
        return (typeof window.COMPETITION_NAME === 'string') ? window.COMPETITION_NAME : '';
    }

    // ---------- DOM 파싱 (대진표가 1차 소스) ----------

    // 한 슬롯(선수 한 명) 읽기.
    // 표시 이름은 번역될 수 있으므로 API/캐시 조회용 한글 원문은 링크 href 에서 복원한다.
    function parseSlot(slotEl) {
        var out = { ko: '', team: '', display: '', seed: '', score: '',
                    winner: false, forfeit: false, empty: true };
        if (!slotEl) return out;

        out.winner = slotEl.classList.contains('winner');
        out.forfeit = slotEl.classList.contains('forfeit');

        var seedEl = slotEl.querySelector('.player-seed, .player-seed-badge');
        if (seedEl) {
            var sd = (seedEl.textContent || '').replace(/[\[\]\s]/g, '');
            if (sd && sd !== 'None' && sd !== '-') out.seed = sd;
        }

        var link = slotEl.querySelector('a.player-name');
        if (link) {
            var href = link.getAttribute('href') || '';
            var mp = href.match(/\/player\/([^?#]+)/);
            if (mp) { try { out.ko = decodeURIComponent(mp[1]); } catch (e) { out.ko = mp[1]; } }
            var mt = href.match(/[?&]team=([^&]*)/);
            if (mt) {
                try { out.team = decodeURIComponent(mt[1].replace(/\+/g, ' ')); } catch (e) { out.team = mt[1]; }
            }
            if (!out.ko) out.ko = (link.textContent || '').trim();
            out.empty = !out.ko;
        }

        if (!out.team) {
            var teamEl = slotEl.querySelector('.player-team-tree, .player-team');
            if (teamEl) out.team = (teamEl.textContent || '').trim();
        }
        out.display = out.ko ? trP(out.ko) : '';

        var scoreEl = slotEl.querySelector('.player-score, .player-score-badge');
        if (scoreEl) out.score = (scoreEl.textContent || '').trim();

        return out;
    }

    function slotsOf(block) {
        return [].slice.call(block.querySelectorAll('.match-player, .card-player'));
    }

    function parseBlock(block) {
        var isTree = block.classList.contains('bracket-match');
        var roundEl = block.closest('.bracket-round') || block.closest('.round-panel');
        var panel = block.closest('.de-phase-panel');

        var info = {
            block: block,
            isTree: isTree,
            roundEl: roundEl,
            round: roundEl ? (roundEl.dataset.round || roundEl.dataset.roundPanel || '') : '',
            phase: panel ? (panel.dataset.phase || '') : '',
            number: '',
            state: block.dataset.state || '',
            forfeit: !!block.querySelector('.forfeit'),
            p1: null, p2: null
        };

        if (isTree) {
            var al = block.getAttribute('aria-label') || '';
            var m = al.match(/Match\s+(\d+)/i);
            if (m) info.number = m[1];
        } else {
            var mn = block.querySelector('.match-number');
            if (mn) {
                var m2 = (mn.textContent || '').match(/(\d+)/);
                if (m2) info.number = m2[1];
            }
        }

        var slots = slotsOf(block);
        info.p1 = parseSlot(slots[0]);
        info.p2 = parseSlot(slots[1]);
        return info;
    }

    // ---------- 브래킷 인접성 ----------

    function blocksIn(container, isTree) {
        if (!container) return [];
        return [].slice.call(container.querySelectorAll(isTree ? '.bracket-match' : '.match-card'));
    }

    /* 이 경기에서 다음 라운드로 올라갈 사람이 이미 정해졌으면 그 선수, 아니면 null.
       부전승은 상대가 없으므로 진출이 확정이다. 그 외에는 결과가 나온 경기만 확정으로 본다. */
    function confirmedWinner(b) {
        var slots = slotsOf(b);
        var named = [parseSlot(slots[0]), parseSlot(slots[1])].filter(function (s) { return !s.empty; });

        if (b.classList.contains('bye-match')) return named[0] || null;
        if (b.dataset.state === 'done') {
            var w = named.filter(function (s) { return s.winner; });
            if (w.length === 1) return w[0];
        }
        return null;
    }

    /* ============================================================================
       브래킷 사다리(ladder)와 경로 투영

       투영의 근거는 단 하나, 대진표의 기하다.
       라운드 k 번 경기의 승자는 다음 라운드 k>>1 번 경기로 간다 (0-based).
       그러므로 어떤 선수의 r 라운드 뒤 상대는 "형제 서브트리에 있는 사람 전원"이며,
       그 서브트리가 아직 안 끝났으면 후보가 2배씩 늘어난다 (1 → 2 → 4 → 8 …).
       아래 라운드 결과가 확정될수록 후보는 저절로 줄어든다. 예측이 아니라 산수다.

       ⚠️ 그려진 라운드만 세면 안 된다.
       한 경기도 치르지 않은 라운드는 컨테이너 자체가 DOM 에 없다.
       실측(제66회 대통령배 남자 사브르): 예선에 128강 64경기만 있고 예선 64강은 통째로 없다.
       그래서 "그려진 라운드 목록" 대신 시작 라운드의 경기 수를 반으로 접어 내려가
       이 단계가 가져야 할 라운드 사다리를 만든다. 라운드 이름은 대진표의 기하이지
       추측이 아니다 — 사람 이름은 언제나 그려진 DOM 에서만 가져온다 (제1원칙).

       ⚠️ 예선 64강과 본선 64강은 다른 경기다.
       사다리는 반드시 .de-phase-panel[data-phase] 하나 안에서만 만든다.
       라운드를 이름이 아니라 (단계, 사다리 칸) 으로 식별하므로 두 64강이 섞일 수 없다.
       ============================================================================ */

    // 라운드 이름 ↔ 경기 수. 실데이터 어휘: 256강 128강 64강 32강 16강 8강 준결승 결승
    function roundSlots(name) {
        if (!name) return 0;
        if (name === '결승') return 1;
        if (name === '준결승') return 2;
        var m = String(name).match(/^(\d+)강$/);
        if (!m) return 0;
        var n = parseInt(m[1], 10);
        return (isPow2(n) && n >= 4) ? n / 2 : 0;
    }
    function slotsRoundName(count) {
        if (count === 1) return '결승';
        if (count === 2) return '준결승';
        return String(count * 2) + '강';
    }

    function roundNameOf(roundEl) {
        return roundEl ? (roundEl.dataset.round || roundEl.dataset.roundPanel || '') : '';
    }

    /* 단계별 사다리. isTree 를 지정하면 그 뷰(트리/리스트)로만 만든다 —
       모바일은 리스트 뷰의 .match-card 를 누르므로 클릭된 블록과 같은 뷰여야 좌표가 맞는다. */
    function phaseContexts(isTree) {
        var raw = phasePanels().map(function (p) {
            var rr = phaseRounds(p.el, isTree);
            return { phase: p.phase, isTree: rr.isTree, rounds: rr.rounds };
        });

        return raw.map(function (r, i) {
            // 라운드를 이름이 아니라 경기 수로 색인한다 ('준결승'/'4강' 같은 표기 차이에 흔들리지 않게)
            var byCount = {};
            r.rounds.forEach(function (el) {
                var c = roundSlots(roundNameOf(el));
                if (c && !byCount[c]) byCount[c] = el;
            });

            /* 이 단계가 끝나는 지점.
               dual DE 의 예선은 결승까지 가지 않는다 — 본선 시작 라운드(공유 라운드)에서 멈춘다.
               예: 예선 128강 → 예선 64강 승자 32명이 본선 64강으로 합류. */
            var stopCount = 1;
            var next = raw[i + 1];
            if (next && next.rounds.length) {
                stopCount = roundSlots(roundNameOf(next.rounds[0])) || 1;
            }

            var ladder = [];
            var startCount = roundSlots(roundNameOf(r.rounds[0]));
            for (var c = startCount; c >= stopCount && c >= 1; c = c / 2) {
                var el = byCount[c] || null;
                ladder.push({
                    name: el ? roundNameOf(el) : slotsRoundName(c),
                    el: el,
                    count: c,
                    blocks: undefined      // 지연 계산 (아래 ladderBlocks)
                });
                if (c === stopCount) break;
            }

            return {
                phase: r.phase,
                isTree: r.isTree,
                ladder: ladder,
                isLastPhase: i === raw.length - 1
            };
        });
    }

    /* 좌표로 쓸 수 있는 블록 배열, 아니면 null.
       DOM 순서를 브래킷 위치로 쓰려면 그 라운드가 통째로 그려져 있어야 한다.
       실측상 렌더된 라운드는 match_number 오름차순·연속이므로 개수만 맞으면 순서는 곧 위치다.
       반쪽만 그려진 라운드(사브르 본선 64강: 32칸 중 1개)는 좌표로 인정하지 않는다. */
    function ladderBlocks(ctx, li) {
        var lv = ctx.ladder[li];
        if (!lv) return null;
        if (lv.blocks === undefined) {
            var bs = lv.el ? blocksIn(lv.el, ctx.isTree) : null;
            lv.blocks = (bs && bs.length === lv.count) ? bs : null;
        }
        return lv.blocks;
    }

    /* (li, bi) 경기의 승자 자리를 차지할 수 있는 사람들.
       확정된 승자가 있으면 그 한 명, 아니면 두 슬롯을 각각 따라 내려간다.
       빈 슬롯은 아래 라운드의 해당 경기(2·bi + slot)로 갈라진다.
       acc.resolved 는 "이 자리가 이미 경기 결과로 정해졌는가" — 확정/예상 표기의 근거다. */
    function occupants(ctx, li, bi, acc, guard) {
        if (li < 0 || guard > 10) { acc.resolved = false; return; }
        var blocks = ladderBlocks(ctx, li);
        var b = blocks ? blocks[bi] : null;

        if (!b) {                       // 아직 없는 라운드 → 아래 두 경기로 갈라진다
            acc.resolved = false;
            occupants(ctx, li - 1, bi * 2, acc, guard + 1);
            occupants(ctx, li - 1, bi * 2 + 1, acc, guard + 1);
            return;
        }

        var won = confirmedWinner(b);
        if (won) { acc.people.push(won); return; }

        acc.resolved = false;
        var slots = slotsOf(b);
        for (var k = 0; k < 2; k++) {
            var sl = parseSlot(slots[k]);
            if (!sl.empty) acc.people.push(sl);
            else occupants(ctx, li - 1, bi * 2 + k, acc, guard + 1);
        }
    }

    function dedupePeople(list) {
        var seen = {}, out = [];
        list.forEach(function (p) {
            if (!p || p.empty || !p.ko) return;
            var k = p.ko + '|' + (p.team || '');
            if (seen[k]) return;
            seen[k] = true;
            out.push(p);
        });
        return out;
    }

    /* 사다리 (ctx, level, index) 에 있는 선수가 앞으로 만날 수 있는 상대를
       startLevel 부터 이 단계 끝까지 한 라운드씩. */
    function projectFrom(ctx, anchorLevel, anchorIndex, startLevel) {
        var out = [];
        for (var lv = Math.max(startLevel, anchorLevel + 1); lv < ctx.ladder.length; lv++) {
            var k = lv - anchorLevel;                        // 기준점에서 몇 라운드 위인가
            var acc = { people: [], resolved: true };
            // 내 자리는 anchorIndex >> k. 상대는 그 형제 서브트리에서 온다.
            occupants(ctx, lv - 1, (anchorIndex >> (k - 1)) ^ 1, acc, 0);
            var people = dedupePeople(acc.people);
            out.push({
                phase: ctx.phase,
                round: ctx.ladder[lv].name,
                people: people,
                confirmed: acc.resolved && people.length === 1
            });
        }
        return out;
    }

    // 대진표에서 누른 블록의 사다리 좌표
    function locateBlock(ctxs, block) {
        var roundEl = block.closest('.bracket-round') || block.closest('.round-panel');
        if (!roundEl) return null;
        for (var i = 0; i < ctxs.length; i++) {
            for (var j = 0; j < ctxs[i].ladder.length; j++) {
                if (ctxs[i].ladder[j].el !== roundEl) continue;
                var blocks = ladderBlocks(ctxs[i], j);
                var idx = blocks ? blocks.indexOf(block) : -1;
                if (idx < 0) return null;                    // 반쪽만 그려진 라운드 → 위치 불명
                return { ctx: ctxs[i], level: j, index: idx };
            }
        }
        return null;
    }

    /* 경기 시트의 "다음 상대". 반환 kind:
         'final'    결승 (더 갈 곳이 없다)
         'to-main'  예선 DE 마지막 라운드 → 본선 진출 (시드 재배정이라 상대 확정 불가)
         'unknown'  대진 위치를 못 잡았다 → 후보를 지어내지 않는다
         'ok'       { rounds: [...] } */
    function computeNext(info) {
        var ctxs = phaseContexts(info.isTree);
        var loc = locateBlock(ctxs, info.block);
        if (!loc) return { kind: 'unknown' };
        if (loc.level >= loc.ctx.ladder.length - 1) {
            return { kind: loc.ctx.isLastPhase ? 'final' : 'to-main' };
        }
        return {
            kind: 'ok',
            rounds: projectFrom(loc.ctx, loc.level, loc.index, loc.level + 1),
            toMain: !loc.ctx.isLastPhase,
            multiPhase: ctxs.length > 1
        };
    }

    // ---------- 렌더 ----------

    function phaseLabel(phase) {
        if (phase === 'first') return t('예선 DE');
        if (phase === 'second') return t('본선 DE');
        return '';
    }

    function statusBadge(info) {
        var cls = 'fm-badge fm-badge--micro fm-badge--pill ms-status-badge';
        if (info.forfeit) return '<span class="' + cls + ' ms-status--forfeit">' + esc(t('기권')) + '</span>';
        if (info.state === 'done') return '<span class="' + cls + ' ms-status--done">' + esc(t('완료')) + '</span>';
        if (info.state === 'tbd') return '<span class="' + cls + ' ms-status--tbd">' + esc(t('상대 미정')) + '</span>';
        return '<span class="' + cls + ' ms-status--pending">' + esc(t('경기 예정')) + '</span>';
    }

    function playerLink(p) {
        if (!p || p.empty) return '<span class="ms-pname ms-pname--tbd">' + esc(t('상대 미정')) + '</span>';
        var href = '/player/' + encodeURIComponent(p.ko) + (p.team ? '?team=' + encodeURIComponent(p.team) : '');
        return '<a class="ms-pname" href="' + esc(href) + '">' + esc(p.display || p.ko) + '</a>';
    }

    function sideHtml(p, side) {
        if (!p || p.empty) {
            return '<div class="ms-side ms-side--' + side + '">' +
                   '<div class="ms-pname ms-pname--tbd">' + esc(t('상대 미정')) + '</div>' +
                   '<div class="ms-hint">' + esc(t('이전 경기 진행 중')) + '</div></div>';
        }
        var cls = 'ms-side ms-side--' + side;
        if (p.winner) cls += ' is-winner';
        if (p.forfeit) cls += ' is-forfeit';

        var tags = '';
        if (p.winner) tags += '<span class="fm-badge fm-badge--micro fm-badge--pill ms-tag ms-tag--win">' + esc(t('승')) + '</span>';
        if (p.forfeit) tags += '<span class="fm-badge fm-badge--micro fm-badge--pill ms-tag ms-tag--forfeit">' + esc(t('기권')) + '</span>';

        return '<div class="' + cls + '">' +
                 (p.seed ? '<div class="ms-seed">[' + num(p.seed) + ']</div>' : '') +
                 '<div class="ms-pname-row">' + playerLink(p) + tags + '</div>' +
                 (p.team ? '<div class="ms-team">' + esc(trT(p.team)) + '</div>' : '') +
               '</div>';
    }

    function scoreHtml(info) {
        var a = info.p1, b = info.p2;
        var hasScore = info.state === 'done' &&
                       a && b && a.score && b.score &&
                       a.score !== '-' && b.score !== '-';
        if (info.forfeit) {
            return '<div class="ms-score ms-score--word">' + esc(t('기권')) + '</div>';
        }
        if (!hasScore) return '<div class="ms-score ms-score--word">VS</div>';
        return '<div class="ms-score">' + num(a.score) + '<span class="ms-score-sep">:</span>' + num(b.score) + '</div>';
    }

    function candidateHtml(p, confirmed) {
        var cls = 'ms-cand ' + (confirmed ? 'ms-cand--confirmed' : 'ms-cand--maybe');
        var pill = confirmed
            ? '<span class="fm-badge fm-badge--micro fm-badge--pill ms-pill ms-pill--sure">' + esc(t('확정')) + '</span>'
            : '<span class="fm-badge fm-badge--micro fm-badge--pill ms-pill">' + esc(t('예상')) + '</span>';
        return '<div class="' + cls + '">' +
                 (p.seed ? '<span class="ms-cand-seed">[' + num(p.seed) + ']</span>' : '') +
                 '<span class="ms-cand-name">' + esc(p.display || p.ko) + '</span>' +
                 (p.team ? '<span class="ms-cand-team">' + esc(trT(p.team)) + '</span>' : '') +
                 pill +
               '</div>';
    }

    function renderNext(info, next) {
        var el = document.getElementById('ms-next');
        if (!el) return;

        if (info.state === 'tbd') { el.hidden = true; el.innerHTML = ''; return; }
        el.hidden = false;

        if (next.kind === 'final') {
            el.innerHTML = '<div class="ms-note ms-note--final">' + esc(t('결승전입니다')) + '</div>';
            return;
        }
        if (next.kind === 'to-main') {
            el.innerHTML = '<div class="ms-sec-title">' + esc(t('다음 상대')) + '</div>' +
                           '<div class="ms-note">' + esc(t('이 경기 승자는 본선 DE로 올라갑니다')) + '</div>' +
                           '<div class="ms-hint">' + esc(t('본선은 시드를 다시 매기므로 상대를 확정할 수 없습니다')) + '</div>';
            return;
        }
        if (next.kind === 'unknown') {
            el.innerHTML = '<div class="ms-sec-title">' + esc(t('다음 상대')) + '</div>' +
                           '<div class="ms-hint">' + esc(t('다음 상대 정보를 계산할 수 없습니다')) + '</div>';
            return;
        }

        // 누구 기준인지 정직하게: 이 경기가 끝났으면 "{승자}의 다음 상대", 아니면 "이 경기 승자의 다음 상대"
        var winner = null;
        if (info.state === 'done') {
            if (info.p1 && info.p1.winner && !info.p1.empty) winner = info.p1;
            else if (info.p2 && info.p2.winner && !info.p2.empty) winner = info.p2;
        }
        // 조사("~의")가 붙는 자리라 이름을 문자열로 이어붙이면 번역이 어순을 못 바꾼다.
        // 자리표시자 한 개짜리 키로 두고 치환한다.
        var who = winner
            ? t('{name}의 다음 상대').replace('{name}', esc(winner.display || winner.ko))
            : esc(t('이 경기 승자의 다음 상대'));

        // 같은 페이지에 예선 64강과 본선 64강이 함께 있다. 라운드명만 쓰면 어느 쪽인지 알 수 없다.
        var first = next.rounds[0];
        var sub = first ? routeRoundLabel(first, next.multiPhase) : '';
        var head = '<div class="ms-sec-title">' + esc(t('다음 상대')) +
                   (sub ? ' <span class="ms-sec-sub">' + esc(sub) + '</span>' : '') + '</div>' +
                   '<div class="ms-who">' + who + '</div>';

        var body;
        var people = first ? first.people : [];
        if (first && first.confirmed && people.length === 1) {
            body = candidateHtml(people[0], true);
        } else if (people.length === 2) {
            body = candidateHtml(people[0], false) +
                   '<div class="ms-or">' + esc(t('또는')) + '</div>' +
                   candidateHtml(people[1], false);
        } else if (people.length === 1) {
            body = candidateHtml(people[0], false);
        } else {
            body = '<div class="ms-hint">' + esc(t('아직 상대가 정해지지 않았습니다')) + '</div>';
        }
        el.innerHTML = head + body;
    }

    /* 후보 칩. inline-flex + gap 이라 텍스트 노드를 그대로 두면 "[ 48 ] 이름" 처럼 벌어진다.
       시드 전체를 span 하나로 묶어 플렉스 아이템을 2개로 만든다.

       ⚠️ 대괄호 숫자는 고정된 선수 시드가 아니라 "그 선수가 있는 라운드에서의 자리 번호"다.
       실측(제54회 문체부장관기 남중 플뢰레, 하주원/알레펜싱클럽): 128강 41 → 32강 24 → 16강 9 → 8강 8.
       그래서 같은 사람이라도 어느 라운드에서 읽었느냐에 따라 숫자가 달라진다.
       동일인 판정은 반드시 이름+소속으로 한다 (dedupePeople 이 그렇게 한다). 숫자로 묶지 말 것. */
    function chipHtml(p) {
        var href = '/player/' + encodeURIComponent(p.ko) + (p.team ? '?team=' + encodeURIComponent(p.team) : '');
        return '<a class="ms-chip" href="' + esc(href) + '">' +
               (p.seed ? '<span class="ms-chip-seed">[' + num(p.seed) + ']</span>' : '') +
               '<span>' + esc(p.display || p.ko) + '</span></a>';
    }

    /* "8명 중 1명" — 후보 수를 숨기지 않는다. 색이 아니라 글자로 확신의 정도를 말한다.
       .fm-badge 는 inline-flex + gap:4px 이라 숫자 span 과 뒤 텍스트가 두 아이템으로 갈라져
       "8 명 중 1명" 처럼 벌어진다. 전체를 span 하나로 묶어 플렉스 아이템을 1개로 만든다. */
    function oddsLabel(n) {
        return '<span>' + t('{n}명 중 1명').replace('{n}', num(n)) + '</span>';
    }

    function renderAfter(info, after, multiPhase) {
        var el = document.getElementById('ms-after');
        if (!el) return;
        if (!after || !after.people.length || info.state === 'tbd') {
            el.hidden = true; el.innerHTML = ''; return;
        }
        el.hidden = false;

        var sure = after.confirmed && after.people.length === 1;
        var pill = sure
            ? '<span class="fm-badge fm-badge--micro fm-badge--pill ms-pill ms-pill--sure">' + esc(t('확정')) + '</span>'
            : '<span class="fm-badge fm-badge--micro fm-badge--pill ms-pill">' + oddsLabel(after.people.length) + '</span>';
        var sub = routeRoundLabel(after, multiPhase);

        el.innerHTML =
            '<details class="ms-details">' +
              '<summary class="ms-summary">' + esc(t('그다음 라운드')) +
              (sub ? ' <span class="ms-sec-sub">' + esc(sub) + '</span>' : '') +
              ' ' + pill + '</summary>' +
              '<div class="ms-chips">' + after.people.map(chipHtml).join('') + '</div>' +
              // 한 명으로 확정된 자리에 "이 중 한 명" 은 거짓말이 된다
              (sure ? '' : '<div class="ms-hint">' + esc(t('이 중 한 명과 만날 수 있습니다')) + '</div>') +
            '</details>';
    }

    function renderActions(info) {
        var el = document.getElementById('ms-actions');
        if (!el) return;
        var people = [info.p1, info.p2].filter(function (p) { return p && !p.empty; });
        if (!people.length) { el.hidden = true; el.innerHTML = ''; return; }
        el.hidden = false;

        // 경로는 대진표 DOM 에서 만든다 — 선수 루트 위젯이 없어도 열 수 있다.
        // 대진표에서 눌린 경기의 선수이므로 경로는 최소 한 경기 이상 존재한다.
        var html = people.map(function (p) {
            return '<button type="button" class="ms-btn ms-btn--route" data-ms-route="' + esc(p.ko) +
                   '" data-ms-team="' + esc(p.team || '') + '">' +
                   esc(p.display || p.ko) + ' ' + esc(t('경로 보기')) + '</button>';
        }).join('');

        html += people.map(function (p) {
            var href = '/player/' + encodeURIComponent(p.ko) + (p.team ? '?team=' + encodeURIComponent(p.team) : '');
            return '<a class="ms-btn ms-btn--ghost" href="' + esc(href) + '">' +
                   esc(p.display || p.ko) + ' ' + esc(t('프로필')) + '</a>';
        }).join('');

        el.innerHTML = html;
    }

    // ---------- 상대 전적 ----------

    function h2hSkeleton() {
        var el = document.getElementById('ms-h2h');
        if (!el) return;
        el.hidden = false;
        el.innerHTML = '<div class="ms-sec-title">' + esc(t('상대 전적')) + '</div>' +
                       '<div class="ms-skel"></div><div class="ms-skel ms-skel--short"></div>';
    }

    function renderH2H(base, opp, rec, approximate) {
        var el = document.getElementById('ms-h2h');
        if (!el) return;

        var baseName = esc(base.display || base.ko);
        var lines = [];
        var deTotal = (typeof rec.de_total === 'number') ? rec.de_total : null;
        var total = rec.total || 0;

        if (total === 0) {
            lines.push('<div class="ms-h2h-main">' +
                '<span class="fm-badge fm-badge--micro fm-badge--pill h2h-badge h2h-badge--first">' +
                esc(t('첫 대결')) + '</span></div>');
        } else if (deTotal === null) {
            // de_* 필드가 없는 응답(구버전 서버) — 합산만 정직하게 보여준다
            lines.push('<div class="ms-h2h-main"><span class="ms-h2h-label">' + esc(t('전체 전적')) + '</span> ' +
                       baseName + ' ' + recordText(rec.wins || 0, rec.losses || 0) + '</div>');
        } else if (deTotal > 0) {
            lines.push('<div class="ms-h2h-main"><span class="ms-h2h-label">' + esc(t('DE 전적')) + '</span> ' +
                       baseName + ' ' + recordText(rec.de_wins || 0, rec.de_losses || 0) + '</div>');
            if (rec.de_last_score) {
                var parts = [];
                parts.push(esc(rec.de_last_score) + ' ' + esc(rec.de_last_result === 'V' ? t('승') : t('패')));
                if (rec.de_last_tournament) parts.push(esc(trC(rec.de_last_tournament)));
                if (rec.de_last_round) parts.push(esc(rec.de_last_round));
                lines.push('<div class="ms-h2h-sub">' + esc(t('최근 DE')) + ': ' + parts.join(' · ') + '</div>');
            }
            lines.push('<div class="ms-h2h-sub ms-h2h-sub--muted">' + esc(t('전체 전적')) + ' ' +
                       recordText(rec.wins || 0, rec.losses || 0) + ' <span class="ms-hint-inline">(' +
                       esc(t('풀 포함')) + ')</span></div>');
        } else {
            lines.push('<div class="ms-h2h-main">' +
                '<span class="fm-badge fm-badge--micro fm-badge--pill h2h-badge h2h-badge--first">' +
                esc(t('DE 첫 대결')) + '</span></div>');
            lines.push('<div class="ms-h2h-sub ms-h2h-sub--muted">' + esc(t('전체 전적')) + ' ' +
                       baseName + ' ' + recordText(rec.wins || 0, rec.losses || 0) +
                       ' <span class="ms-hint-inline">(' + esc(t('풀 포함')) + ')</span></div>');
        }

        lines.push('<div class="ms-hint">' + esc(t('이 대회 이전 전적')) + '</div>');
        if (approximate && total > 0) {
            lines.push('<div class="ms-hint">' + esc(t('※ 동명이인의 기록이 섞였을 수 있습니다')) + '</div>');
        }

        el.hidden = false;
        el.innerHTML = '<div class="ms-sec-title">' + esc(t('상대 전적')) + '</div>' +
                       '<div class="ms-fade-in">' + lines.join('') + '</div>';
    }

    function hideH2H() {
        var el = document.getElementById('ms-h2h');
        if (el) { el.hidden = true; el.innerHTML = ''; }
    }

    function fetchJson(url, timeoutMs) {
        return new Promise(function (resolve) {
            var done = false;
            var timer = setTimeout(function () { if (!done) { done = true; resolve(null); } }, timeoutMs);
            fetch(url)
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) { if (!done) { done = true; clearTimeout(timer); resolve(d); } })
                .catch(function () { if (!done) { done = true; clearTimeout(timer); resolve(null); } });
        });
    }

    // 경로 2 (임의 두 선수): /api/players/{a}/head-to-head/{b}
    // 이 엔드포인트는 matches 를 통째로 내려주므로 DE 한정 집계를 클라에서 한다.
    // 실제 응답 형태(코드 확인): { record, matches:[{competition, date, event, round, player_score, opponent_score, result:"win"|"loss"}] }
    //  - 풀 경기의 round 는 "Pool 3" 처럼 번호가 붙는다 → 접두사로 판정
    //  - team 파라미터가 없어 동명이인을 구분하지 못한다 → 각주 표시
    //  - 지금 보고 있는 대회를 포함하므로 EventH2H 와 같은 기준이 되도록 제외한다
    function buildRecordFromMatches(d) {
        var comp = competitionName();
        var matches = ((d && d.matches) || []).filter(function (m) {
            return !comp || (m.competition || '') !== comp;
        });
        var isPool = function (m) { return /^\s*pool/i.test(String(m.round || '')); };
        var de = matches.filter(function (m) { return !isPool(m); });

        var wins = matches.filter(function (m) { return m.result === 'win'; }).length;
        var deWins = de.filter(function (m) { return m.result === 'win'; }).length;
        var last = de[0] || null;

        var rec = {
            wins: wins,
            losses: matches.length - wins,
            total: matches.length,
            first_meeting: matches.length === 0,
            de_wins: deWins,
            de_losses: de.length - deWins,
            de_total: de.length,
            de_last_result: '', de_last_score: '', de_last_round: '', de_last_tournament: ''
        };
        if (last) {
            rec.de_last_result = last.result === 'win' ? 'V' : 'D';
            if (last.player_score != null && last.opponent_score != null) {
                rec.de_last_score = String(last.player_score) + '-' + String(last.opponent_score);
            }
            rec.de_last_round = last.round || '';
            rec.de_last_tournament = last.competition || '';
        }
        return rec;
    }

    function loadH2H(info, seq) {
        var a = info.p1, b = info.p2;
        if (!a || !b || a.empty || b.empty) { hideH2H(); return; }

        // 경로 1: EventH2H 가 이미 받아둔 내 선수 전적 (추가 요청 0회)
        if (window.EventH2H && typeof window.EventH2H.getRecord === 'function') {
            var hit = window.EventH2H.getRecord(a.ko, b.ko);
            var base = a;
            if (!hit) { hit = window.EventH2H.getRecord(b.ko, a.ko); base = b; }
            if (hit && hit.rec) { renderH2H(base, base === a ? b : a, hit.rec, false); return; }
        }

        // 경로 2: 임의 두 선수
        h2hSkeleton();
        var url = '/api/players/' + encodeURIComponent(a.ko) + '/head-to-head/' + encodeURIComponent(b.ko);
        var w = eventWeapon();
        if (w) url += '?weapon=' + encodeURIComponent(w);

        fetchJson(url, H2H_TIMEOUT_MS).then(function (d) {
            if (seq !== reqSeq) return;          // 다른 경기가 열렸다 — 늦게 온 응답은 버린다
            if (!d) { hideH2H(); return; }       // 실패/타임아웃 → 빈 프레임을 남기지 않는다
            renderH2H(a, b, buildRecordFromMatches(d), true);
        });
    }

    // ---------- 선수 경로 (시트 안에서) ----------
    /* 경로도 이미 렌더된 대진표 DOM 이 1차 소스다. 서버를 새로 부르지 않는다.

       ⚠️ 예선 64강과 본선 64강은 다른 경기다.
       국가대표 선발 대회는 dual DE 라 "64강" 이 예선·본선 양쪽에 존재한다.
       라운드명만으로 묶으면 두 경기가 한 줄로 섞인다. 그래서
         - 스캔을 반드시 .de-phase-panel[data-phase] 단위로 돌고
         - 노드마다 어느 단계에서 나온 경기인지 들고 다니고
         - 화면에도 "예선 64강" / "본선 64강" 으로 단계를 붙여 표시한다.
       단계 패널이 없는 단일 DE 에서는 접두사를 붙이지 않는다. */

    // 이 페이지의 대진 단계. dual DE 가 아니면 단계 구분이 없는 하나의 묶음으로 본다.
    function phasePanels() {
        var root = document.getElementById('tab-tournament');
        if (!root) return [];
        var panels = [].slice.call(root.querySelectorAll('.de-phase-panel'));
        if (panels.length) {
            return panels.map(function (p) { return { el: p, phase: p.dataset.phase || '' }; });
        }
        return [{ el: root, phase: '' }];
    }

    /* 한 단계의 라운드 컨테이너를 DOM 순서(=시간 순서)대로.
       트리 뷰와 리스트 뷰는 같은 경기를 두 번 렌더하므로 하나만 골라 중복 집계를 막는다.
       want: true=트리만, false=리스트만, 생략=트리 우선.
       모바일에서 눌린 것은 리스트 뷰의 .match-card 라 좌표 계산은 그 뷰로 맞춰야 한다. */
    function phaseRounds(panelEl, want) {
        if (want !== false) {
            var tree = panelEl.querySelector('.bracket-tree');
            if (tree) {
                return { isTree: true, rounds: [].slice.call(tree.querySelectorAll(':scope > .bracket-round')) };
            }
            if (want === true) return { isTree: true, rounds: [] };
        }
        var list = panelEl.querySelector('.bracket-list-view');
        if (list) {
            return { isTree: false, rounds: [].slice.call(list.querySelectorAll(':scope > .round-panel')) };
        }
        return { isTree: false, rounds: [] };
    }

    /* 이 종목 DE 참가자 전원 (예선 DE + 본선 시드).

       출처는 대진표의 경기 블록 슬롯 뿐이다. 이유가 둘 있다.
       1) 어떤 블록에도 없는 선수는 애초에 보여줄 경로가 없다.
       2) 시드/진출자 명단(.qualifier-item 등)은 team 칸에 소속이 아닌 값이
          들어오는 경우가 있다 — 남자 에페 first_de_qualifiers 에 실제로
          이우빈/"김광수의기권", 김도완/"황현일의기권" 이 있다. 그걸 후보로 넣으면
          한 사람이 둘로 갈라지고 동명이인으로도 잘못 표시된다.
       자동완성 API 도 쓰지 않는다 — 이 종목 DE 에 없는 선수까지 섞여 오고
       (남자 에페 '김': DOM 35명 vs API 49명) limit 50 에서 실제 참가자가 잘린다. */
    function participants() {
        var index = {}, out = [];

        function add(phase, ko, team, seed) {
            if (!ko) return;
            var k = ko + '|' + (team || '');
            var e = index[k];
            if (!e) {
                e = { ko: ko, team: team || '', seed: seed || '', display: trP(ko) || ko, phases: [] };
                index[k] = e;
                out.push(e);
            }
            if (!e.seed && seed) e.seed = seed;
            if (phase && e.phases.indexOf(phase) < 0) e.phases.push(phase);
        }

        phasePanels().forEach(function (p) {
            var rr = phaseRounds(p.el);
            rr.rounds.forEach(function (roundEl) {
                blocksIn(roundEl, rr.isTree).forEach(function (b) {
                    slotsOf(b).forEach(function (s) {
                        var sl = parseSlot(s);
                        if (!sl.empty) add(p.phase, sl.ko, sl.team, sl.seed);
                    });
                });
            });
        });

        out.sort(function (a, b) {
            try { return a.ko.localeCompare(b.ko, 'ko'); } catch (e) { return a.ko < b.ko ? -1 : 1; }
        });

        // 동명이인 표시용 — 소속만으로 구분해야 하는 이름을 미리 표시해둔다
        var byName = {};
        out.forEach(function (p) { byName[p.ko] = (byName[p.ko] || 0) + 1; });
        out.forEach(function (p) { p.homonym = byName[p.ko] > 1; });
        return out;
    }

    // 동명이인 방어: 소속을 둘 다 알고 있으면 소속까지 같아야 같은 사람으로 본다.
    function samePlayer(slot, ko, team) {
        if (!slot || slot.empty || !slot.ko) return false;
        if (slot.ko !== ko) return false;
        if (team && slot.team && slot.team !== team) return false;
        return true;
    }

    // data-state 가 없는 레거시 마크업 폴백 (표시 클래스로 역추론)
    function blockState(block, me, opp) {
        var st = block.dataset.state || '';
        if (st) return st;
        if (block.classList.contains('bye-match')) return 'bye';
        if (block.querySelector('.winner')) return 'done';
        return (me && !me.empty && opp && !opp.empty) ? 'scheduled' : 'tbd';
    }

    function buildRoute(ko, team) {
        var ctxs = phaseContexts();
        var multiPhase = ctxs.length > 1;
        var nodes = [];
        var player = null;

        ctxs.forEach(function (ctx) {
            ctx.ladder.forEach(function (lv, li) {
                if (!lv.el) return;                       // 아직 한 경기도 없는 라운드
                var blocks = blocksIn(lv.el, ctx.isTree);
                // 좌표로 쓸 수 있는 라운드에서만 위치를 기록한다 (반쪽 렌더는 위치 불명)
                var trusted = ladderBlocks(ctx, li);

                blocks.forEach(function (b) {
                    var slots = slotsOf(b);
                    if (slots.length < 2) return;
                    var s0 = parseSlot(slots[0]);
                    var s1 = parseSlot(slots[1]);
                    var me = null, opp = null;
                    if (samePlayer(s0, ko, team)) { me = s0; opp = s1; }
                    else if (samePlayer(s1, ko, team)) { me = s1; opp = s0; }
                    if (!me) return;
                    if (!player) player = me;

                    var isBye = b.classList.contains('bye-match');
                    var st = blockState(b, me, opp);
                    var result;
                    if (isBye || st === 'bye') result = 'bye';
                    else if (st === 'done') result = me.winner ? 'win' : 'lose';
                    else if (!opp || opp.empty) result = 'tbd';
                    else result = 'scheduled';

                    nodes.push({
                        phase: ctx.phase,
                        round: lv.name,
                        me: me,
                        opp: opp,
                        result: result,
                        forfeitMine: !!me.forfeit,
                        forfeitOpp: !!(opp && opp.forfeit),
                        isLastRoundOfPhase: li === ctx.ladder.length - 1,
                        isLastPhase: ctx.isLastPhase,
                        roundRealCount: lv.count,
                        ctx: ctx,
                        level: li,
                        index: trusted ? trusted.indexOf(b) : -1
                    });
                });
            });
        });

        /* 한 선수가 같은 단계·같은 라운드에서 두 경기를 뛸 수는 없다(단일 토너먼트).
           그런 데이터가 오면 경로를 그럴듯하게 이어붙이지 말고 그 사실을 알린다.
           실제로 남자 에페에서 기권 표기가 소속 칸에 들어가 한 선수의 경기가
           갈라지는 사례가 있다 — 그때 이 경고가 뜬다. */
        var seenRound = {}, conflict = false;
        nodes.forEach(function (n) {
            var k = n.phase + '|' + n.round;
            if (seenRound[k]) conflict = true;
            seenRound[k] = true;
        });

        return {
            player: player || { ko: ko, team: team, display: trP(ko), seed: '' },
            nodes: nodes,
            multiPhase: multiPhase,
            conflict: conflict
        };
    }

    function phaseShort(phase) {
        if (phase === 'first') return t('예선');
        if (phase === 'second') return t('본선');
        return '';
    }

    // "예선 64강". 자리표시자 키로 두어야 번역이 어순을 바꿀 수 있다.
    function routeRoundLabel(node, multiPhase) {
        var r = node.round ? t(node.round) : '';
        if (!multiPhase) return r;
        var ph = phaseShort(node.phase);
        if (!ph || !r) return r || ph;
        return t('{phase} {round}').replace('{phase}', ph).replace('{round}', r);
    }

    // 배지 색은 시트가 이미 쓰는 상태 배지 클래스를 그대로 재사용한다 (새 색 도입 없음).
    function routeBadge(node) {
        var base = 'fm-badge fm-badge--micro fm-badge--pill ms-status-badge msr-badge ';
        if (node.result === 'bye') return '<span class="' + base + 'ms-status--tbd">' + esc(t('부전승')) + '</span>';
        if (node.result === 'tbd') return '<span class="' + base + 'ms-status--tbd">' + esc(t('상대 미정')) + '</span>';
        if (node.result === 'scheduled') return '<span class="' + base + 'ms-status--pending">' + esc(t('예정')) + '</span>';
        if (node.result === 'win') {
            if (node.forfeitOpp) return '<span class="' + base + 'ms-status--done">' + esc(t('상대 기권')) + '</span>';
            return '<span class="' + base + 'ms-status--done">' + esc(t('승')) + '</span>';
        }
        if (node.forfeitMine) return '<span class="' + base + 'ms-status--forfeit">' + esc(t('기권')) + '</span>';
        return '<span class="' + base + 'ms-status--forfeit">' + esc(t('패')) + '</span>';
    }

    function routeScore(node) {
        if (node.result !== 'win' && node.result !== 'lose') return '';
        var a = node.me.score, b = node.opp ? node.opp.score : '';
        if (!a || !b || a === '-' || b === '-') return '';
        return '<span class="msr-score">' + num(a) + '<span class="msr-score-sep">:</span>' + num(b) + '</span>';
    }

    function routeOpponent(node) {
        if (node.result === 'bye') {
            return '<span class="msr-opp msr-opp--none">' + esc(t('부전승')) + '</span>';
        }
        if (!node.opp || node.opp.empty) {
            return '<span class="msr-opp msr-opp--none">' + esc(t('상대 미정')) + '</span>';
        }
        var href = '/player/' + encodeURIComponent(node.opp.ko) +
                   (node.opp.team ? '?team=' + encodeURIComponent(node.opp.team) : '');
        return '<a class="msr-opp" href="' + esc(href) + '">' + esc(node.opp.display || node.opp.ko) + '</a>' +
               (node.opp.seed ? ' <span class="msr-oseed">[' + num(node.opp.seed) + ']</span>' : '') +
               (node.opp.team ? '<span class="msr-oteam">' + esc(trT(node.opp.team)) + '</span>' : '');
    }

    // 마지막 노드로부터 결론을 낸다. 확신할 수 있을 때만 붙인다 (제1원칙).
    function routeEndNode(route) {
        var last = route.nodes[route.nodes.length - 1];
        if (!last) return '';
        if (last.result === 'lose') {
            var lbl = routeRoundLabel(last, route.multiPhase);
            return '<li class="msr-end msr-end--out">' +
                   esc(t('{round} 탈락').replace('{round}', lbl)) + '</li>';
        }
        if (last.result !== 'win') return '';
        if (!last.isLastRoundOfPhase) return '';
        if (last.isLastPhase) {
            if (last.roundRealCount === 1) {
                return '<li class="msr-end msr-end--champ">' + esc(t('우승')) + '</li>';
            }
            return '';
        }
        return '<li class="msr-end msr-end--up">' + esc(t('본선 DE 진출')) + '</li>';
    }

    /* ---------- 앞으로 만날 상대 (경로 투영) ----------

       기준점(anchor) 을 왜 따로 잡는가:
       진행 중 대회는 최신 라운드가 반쪽만 그려져 DOM 순서가 브래킷 위치가 아니다.
       그럴 때는 같은 단계에서 위치를 신뢰할 수 있는 가장 나중 노드를 기준점으로 삼고
       거기서 위치를 접어 올린다 (라운드 하나 올라갈 때마다 index >> 1).
       기준점이 아예 없으면 후보를 지어내지 않고 그 사실을 말한다. */
    function projectRoute(route) {
        var nodes = route.nodes;
        var last = nodes[nodes.length - 1];
        if (!last || !last.ctx) return null;
        if (last.result === 'lose') return null;          // 탈락 — 앞이 없다

        var ctx = last.ctx;
        var anchor = null;
        nodes.forEach(function (n) {
            if (n.ctx === ctx && n.index >= 0) anchor = n;   // 같은 단계의 마지막 신뢰 좌표
        });
        if (!anchor) return { unresolved: true, toMain: !ctx.isLastPhase, rounds: [] };

        var rounds = projectFrom(ctx, anchor.level, anchor.index, last.level + 1);

        // 방어: 나 자신이 상대 후보로 들어오면 안 된다 (형제 서브트리라 원래 불가능하다)
        var meKo = route.player.ko, meTeam = route.player.team;
        rounds.forEach(function (r) {
            r.people = r.people.filter(function (p) {
                return !(p.ko === meKo && (!p.team || !meTeam || p.team === meTeam));
            });
        });

        return { unresolved: false, toMain: !ctx.isLastPhase, rounds: rounds };
    }

    /* 펼침 규칙:
       가까운 두 라운드는 기본으로 펼쳐 둔다 — 대회장에서 지금 궁금한 건 그 두 개다.
       그보다 먼 라운드는 후보가 8·16·32명으로 불어나 목록이 화면을 삼키므로
       접어 두고 요약(라운드 + "N명 중 1명")만 보여준다.
       단, 먼 라운드라도 결과가 나와 후보가 2명 이하로 줄었으면 접지 않는다 —
       접는 이유는 거리(距離)가 아니라 길이(長)이기 때문이다. */
    function projOpen(distance, people) {
        return distance <= 2 || people.length <= 2;
    }

    function projRow(r, distance, multiPhase) {
        var label = esc(routeRoundLabel({ round: r.round, phase: r.phase }, multiPhase));
        var sure = r.confirmed && r.people.length === 1;

        if (!r.people.length) {
            return '<li class="msr-proj msr-proj--none">' +
                     '<div class="msr-proj-top"><span class="msr-round">' + label + '</span>' +
                     '<span class="fm-badge fm-badge--micro fm-badge--pill ms-pill">' +
                     esc(t('상대 미정')) + '</span></div></li>';
        }

        var pill = sure
            ? '<span class="fm-badge fm-badge--micro fm-badge--pill ms-pill ms-pill--sure">' + esc(t('확정')) + '</span>'
            : '<span class="fm-badge fm-badge--micro fm-badge--pill ms-pill">' + oddsLabel(r.people.length) + '</span>';
        var top = '<span class="msr-round">' + label + '</span>' + pill;
        var chips = '<div class="ms-chips">' + r.people.map(chipHtml).join('') + '</div>';
        var cls = 'msr-proj' + (sure ? ' msr-proj--sure' : '');

        if (projOpen(distance, r.people)) {
            return '<li class="' + cls + '">' +
                     '<div class="msr-proj-top">' + top + '</div>' + chips + '</li>';
        }
        return '<li class="' + cls + ' msr-proj--fold">' +
                 '<details><summary class="msr-proj-top">' + top + '</summary>' + chips + '</details>' +
               '</li>';
    }

    function projectionHtml(route, proj) {
        if (!proj) return '';
        var out = '<li class="msr-sep"><span>' + esc(t('앞으로 만날 상대')) + '</span></li>';

        if (proj.unresolved) {
            out += '<li class="msr-proj msr-proj--none"><div class="ms-hint">' +
                   esc(t('대진 위치를 확인할 수 없어 이후 상대를 계산하지 않습니다')) + '</div></li>';
        } else if (!proj.rounds.length && !proj.toMain) {
            return '';
        } else {
            // rounds 는 현재 라운드 바로 다음부터 연속이므로 i+1 이 곧 "몇 라운드 뒤"다
            proj.rounds.forEach(function (r, i) {
                out += projRow(r, i + 1, route.multiPhase);
            });
        }

        // 예선 DE 는 여기서 멈춘다. 본선은 시드를 다시 매기므로 상대를 이어 붙일 수 없다.
        if (proj.toMain) {
            out += '<li class="msr-proj msr-proj--stop"><div class="ms-hint">' +
                   esc(t('본선은 시드를 다시 매기므로 상대를 확정할 수 없습니다')) + '</div></li>';
        }
        return out;
    }

    function renderRoute(ko, team) {
        var el = document.getElementById('ms-route-view');
        if (!el) return;

        var route;
        try { route = buildRoute(ko, team); } catch (e) { route = null; }

        if (!route || !route.nodes.length) {
            el.innerHTML = '<div class="ms-hint">' + esc(t('이 선수의 대진 경로를 찾을 수 없습니다')) + '</div>';
            return;
        }

        var p = route.player;
        var href = '/player/' + encodeURIComponent(p.ko) + (p.team ? '?team=' + encodeURIComponent(p.team) : '');
        var head = '<div class="msr-player">' +
                     '<a class="msr-pname" href="' + esc(href) + '">' + esc(p.display || p.ko) + '</a>' +
                     (p.seed ? '<span class="msr-pseed">[' + num(p.seed) + ']</span>' : '') +
                     (p.team ? '<span class="msr-pteam">' + esc(trT(p.team)) + '</span>' : '') +
                   '</div>';

        var items = route.nodes.map(function (n) {
            var cls = 'msr-node msr-node--' + n.result;
            return '<li class="' + cls + '">' +
                     '<span class="msr-round">' + esc(routeRoundLabel(n, route.multiPhase)) + '</span>' +
                     '<span class="msr-vs">' + routeOpponent(n) + '</span>' +
                     '<span class="msr-right">' + routeScore(n) + routeBadge(n) + '</span>' +
                   '</li>';
        }).join('');

        var notice = route.conflict
            ? '<p class="msr-notice" role="status">' +
              esc(t('같은 라운드에 경기가 둘 이상 기록되어 있어 경로가 정확하지 않을 수 있습니다')) +
              '</p>'
            : '';

        var proj;
        try { proj = projectRoute(route); } catch (e) { proj = null; }

        el.innerHTML = head + notice + '<ol class="msr-list">' +
                       items +
                       routeEndNode(route) +
                       projectionHtml(route, proj) +
                       '<li class="msr-final" id="msr-final" hidden></li>' +
                       '</ol>';
        if (!reducedMotion()) {
            el.classList.remove('ms-fade-in');
            void el.offsetWidth;
            el.classList.add('ms-fade-in');
        }
        loadFinalRank(p, ++routeSeq);
    }

    /* KFA 최종 순위. 자체 계산이 아니라 서버가 확정한 값을 그대로 붙인다.
       비동기 — 못 받으면 아무것도 붙이지 않는다 (빈 칸을 지어내지 않는다). */
    function loadFinalRank(p, seq) {
        var sub = (typeof window.SUB_EVENT_CD === 'string') ? window.SUB_EVENT_CD : '';
        if (!sub || !p || !p.ko) return;
        var url = '/api/events/' + encodeURIComponent(sub) +
                  '/players/search?q=' + encodeURIComponent(p.ko);
        fetchJson(url, H2H_TIMEOUT_MS).then(function (d) {
            if (seq !== routeSeq) return;              // 다른 선수의 경로로 바뀌었다
            var list = (d && d.players) || [];
            if (!list.length) return;
            var hit = list.filter(function (x) {
                return !p.team || (x.team || '') === p.team;
            })[0] || (p.team ? null : list[0]);        // 소속을 아는데 못 맞추면 붙이지 않는다
            if (!hit || typeof hit.final_rank !== 'number' || hit.final_rank <= 0) return;
            var el = document.getElementById('msr-final');
            if (!el) return;
            el.hidden = false;
            // "127위" / "127th" — 숫자 자리를 자리표시자로 두어야 언어별 어순을 바꿀 수 있다
            el.innerHTML = '<span class="msr-final-label">' + esc(t('최종 순위')) + '</span>' +
                           '<span class="msr-final-rank">' +
                           t('{n}위').replace('{n}', num(hit.final_rank)) + '</span>';
        });
    }

    // ---------- 뷰 전환 (경기 정보 ↔ 경로) ----------

    function setView(v) {
        if (!sheet) return;
        sheet.dataset.view = v;
        var body = document.getElementById('ms-body');
        var rv = document.getElementById('ms-route-view');
        var back = document.getElementById('ms-back');
        var status = document.getElementById('ms-status');
        if (body) body.hidden = (v === 'route');
        if (rv) rv.hidden = (v !== 'route');
        // 검색으로 바로 연 경로에는 돌아갈 경기가 없다 → 뒤로가기를 주지 않는다.
        if (back) back.hidden = !(v === 'route' && lastInfo);
        if (status) status.hidden = (v === 'route');
        try { sheet.scrollTop = 0; } catch (e) {}
    }

    // 경기 시트 안에서 경로로 전환 (뒤로가기 있음)
    function showRoute(ko, team) {
        if (!ensure() || !ko) return;
        var title = document.getElementById('ms-title');
        if (title) title.textContent = t('선수 경로');
        renderRoute(ko, team);
        setView('route');
        var back = document.getElementById('ms-back');
        if (back && !back.hidden) { try { back.focus({ preventScroll: true }); } catch (e) { back.focus(); } }
    }

    /* 이름 검색에서 곧바로 경로를 연다 (경기 시트를 거치지 않음).
       선수 검색 위젯이 쓰는 진입점 — 렌더는 위와 같은 것을 그대로 쓴다. */
    function openRoute(ko, team) {
        if (!ensure() || !ko) return;
        reqSeq++;                                  // 진행 중인 전적 응답 무효화
        var wasOpen = sheet.classList.contains('open');
        if (!wasOpen) lastFocus = document.activeElement;
        originBlock = null;
        lastInfo = null;                           // 돌아갈 경기가 없다

        var title = document.getElementById('ms-title');
        if (title) title.textContent = t('선수 경로');
        renderRoute(ko, team);
        setView('route');
        showSheet(wasOpen);

        var closeBtn = document.getElementById('ms-close');
        if (closeBtn) { try { closeBtn.focus({ preventScroll: true }); } catch (e) { closeBtn.focus(); } }
    }

    function backToMatch() {
        if (!sheet || sheet.hidden) return;
        var rv = document.getElementById('ms-route-view');
        if (rv) rv.innerHTML = '';
        if (lastInfo) renderHead(lastInfo);
        setView('match');
        var closeBtn = document.getElementById('ms-close');
        if (closeBtn) { try { closeBtn.focus({ preventScroll: true }); } catch (e) { closeBtn.focus(); } }
    }

    function inRouteView() {
        return !!sheet && sheet.dataset.view === 'route';
    }

    // ---------- 시트 열기/닫기 ----------

    function ensure() {
        if (mounted) return !!sheet;
        sheet = document.getElementById(SHEET_ID);
        backdrop = document.getElementById(SHEET_ID + '-backdrop');
        if (!sheet) return false;
        // position:fixed 가 조상 transform 에 갇히지 않도록 body 직속으로 옮긴다.
        if (sheet.parentNode !== document.body) document.body.appendChild(sheet);
        if (backdrop && backdrop.parentNode !== document.body) document.body.appendChild(backdrop);
        bindDrag();
        mounted = true;
        return true;
    }

    // 스와이프 다운 닫기. mobile-ux.js 의 initBottomSheetDrag 는 열 때마다 리스너를
    // 새로 붙이므로(중복 누적) 여기서 1회만 직접 바인딩한다.
    function bindDrag() {
        if (dragBound || !sheet) return;
        var handle = sheet.querySelector('.bottom-sheet-handle');
        if (!handle) return;
        var startY = 0, curY = 0, dragging = false;

        handle.addEventListener('touchstart', function (e) {
            startY = e.touches[0].clientY; curY = startY; dragging = true;
            sheet.style.transition = 'none';
        }, { passive: true });

        handle.addEventListener('touchmove', function (e) {
            if (!dragging) return;
            curY = e.touches[0].clientY;
            var diff = curY - startY;
            if (diff > 0) sheet.style.transform = 'translateY(' + diff + 'px)';
        }, { passive: true });

        handle.addEventListener('touchend', function () {
            if (!dragging) return;
            dragging = false;
            sheet.style.transition = '';
            var diff = curY - startY;
            sheet.style.transform = '';
            if (diff > 100) close();
        }, { passive: true });

        dragBound = true;
    }

    // 원본 블록 펄스. .bracket-match 는 ::before/::after 가 이미 쓰이고 있어
    // (부전승 라벨 / "예정" 라벨) 오버레이 자식 요소를 잠깐 넣었다 뺀다.
    // --fm-glow-primary 는 라이트 테마에서 transparent 라 글로우 대신 액센트 오버레이를 쓴다.
    function pulse(block) {
        if (!block || reducedMotion()) return;
        var old = block.querySelector(':scope > .ms-pulse-fx');
        if (old) old.remove();
        block.classList.add('ms-origin-pulse');
        var fx = document.createElement('span');
        fx.className = 'ms-pulse-fx';
        fx.setAttribute('aria-hidden', 'true');
        fx.addEventListener('animationend', function () {
            fx.remove();
            if (!block.querySelector(':scope > .ms-pulse-fx')) block.classList.remove('ms-origin-pulse');
        });
        block.appendChild(fx);
    }

    // 헤더만 따로 그린다 — 경로 뷰에서 뒤로 돌아올 때 다시 쓴다.
    function renderHead(info) {
        var head = document.getElementById('ms-title');
        var status = document.getElementById('ms-status');

        var bits = [];
        var pl = phaseLabel(info.phase);
        if (pl) bits.push(esc(pl));
        if (info.round) bits.push(esc(t(info.round)));
        if (info.number) bits.push('Match ' + num(info.number));
        if (head) head.innerHTML = bits.join(' <span class="ms-dot">·</span> ') || esc(t('경기 정보'));
        if (status) status.innerHTML = statusBadge(info);
    }

    function render(info) {
        var versus = document.getElementById('ms-versus');
        renderHead(info);

        if (versus) {
            versus.innerHTML = '<div class="ms-vs-grid">' +
                sideHtml(info.p1, 'left') + scoreHtml(info) + sideHtml(info.p2, 'right') +
            '</div>';
        }

        var next = computeNext(info);
        renderNext(info, next);
        renderAfter(info, next.kind === 'ok' ? next.rounds[1] : null, next.multiPhase);
        renderActions(info);

        if (info.state === 'tbd') hideH2H();
        else loadH2H(info, reqSeq);
    }

    function open(block) {
        if (!ensure()) return;
        reqSeq++;

        var info;
        try { info = parseBlock(block); } catch (e) { return; }
        if (!info.p1 || !info.p2) return;

        var wasOpen = sheet.classList.contains('open');
        if (!wasOpen) lastFocus = document.activeElement;
        originBlock = block;
        lastInfo = info;

        // 다른 경기를 누르면 이전 경로 상태는 남기지 않는다.
        var rv = document.getElementById('ms-route-view');
        if (rv) rv.innerHTML = '';
        setView('match');

        render(info);

        var body = document.getElementById('ms-body');
        if (wasOpen && body) {
            // 이미 열려 있으면 다시 슬라이드하지 않고 내용만 교체 (데스크톱에서 블록을 이어 누를 때)
            body.classList.remove('ms-fade-in');
            void body.offsetWidth;
            if (!reducedMotion()) body.classList.add('ms-fade-in');
        }

        showSheet(wasOpen);

        pulse(block);
        var closeBtn = document.getElementById('ms-close');
        if (closeBtn) { try { closeBtn.focus({ preventScroll: true }); } catch (e) { closeBtn.focus(); } }
    }

    // 시트를 화면에 올린다 (경기 진입 / 이름 검색 진입 공통)
    function showSheet(wasOpen) {
        sheet.hidden = false;
        // 데스크톱은 백드롭 없이 띄운다 — 시트를 열어둔 채 대진표를 계속 볼 수 있어야 한다.
        // (라이트 테마의 .bottom-sheet-backdrop 배경은 !important 라 CSS 로 투명하게 못 만든다)
        var withBackdrop = !isDesktop();
        if (withBackdrop) {
            sheet.setAttribute('aria-modal', 'true');
            document.body.style.overflow = 'hidden';
        } else {
            sheet.removeAttribute('aria-modal');
        }

        if (!wasOpen) {
            sheet.style.willChange = 'transform';
            requestAnimationFrame(function () {
                requestAnimationFrame(function () {
                    sheet.classList.add('open');
                    if (backdrop && withBackdrop) backdrop.classList.add('open');
                });
            });
            var clearWill = function () { sheet.style.willChange = ''; sheet.removeEventListener('transitionend', clearWill); };
            sheet.addEventListener('transitionend', clearWill);
        }
    }

    function close() {
        if (!sheet || sheet.hidden) return;
        reqSeq++;
        sheet.classList.remove('open');
        sheet.style.transform = '';
        if (backdrop) backdrop.classList.remove('open');
        document.body.style.overflow = '';

        var finish = function () {
            sheet.hidden = true;
            sheet.style.willChange = '';
        };
        if (reducedMotion()) finish();
        else setTimeout(finish, 320);   // .bottom-sheet transition 300ms + 여유

        // 경로 상태는 닫는 순간 버린다 — 다음에 열 때 남아 있으면 안 된다.
        var rv = document.getElementById('ms-route-view');
        if (rv) rv.innerHTML = '';
        setView('match');
        lastInfo = null;

        if (originBlock) { pulse(originBlock); originBlock = null; }
        if (lastFocus && document.contains(lastFocus)) {
            try { lastFocus.focus({ preventScroll: true }); } catch (e) { lastFocus.focus(); }
        }
        lastFocus = null;
    }

    // ---------- 이벤트 위임 ----------

    function blockFrom(target) {
        if (!target || !target.closest) return null;
        if (target.closest('a, button, summary, input, select')) return null;   // 링크/버튼은 원래 동작 유지
        var block = target.closest('.bracket-match, .match-card');
        if (!block) return null;
        if (block.classList.contains('bye-match')) return null;                 // 부전승 블록은 시트 없음
        return block;
    }

    function init() {
        var root = document.getElementById('tab-tournament');
        if (!root) return;
        if (!document.getElementById(SHEET_ID)) return;

        root.addEventListener('click', function (e) {
            var block = blockFrom(e.target);
            if (!block) return;
            open(block);
        });

        root.addEventListener('keydown', function (e) {
            if (e.key !== 'Enter' && e.key !== ' ' && e.key !== 'Spacebar') return;
            var el = e.target;
            if (!el || !el.classList) return;
            if (!el.classList.contains('bracket-match') && !el.classList.contains('match-card')) return;
            if (el.classList.contains('bye-match')) return;
            e.preventDefault();
            open(el);
        });

        // 키보드로도 열 수 있도록 블록을 포커스 가능하게 만든다.
        // (리스트 뷰는 활성 라운드 패널만 display:block 이라 실제 탭 스톱은 그 패널 몫만 늘어난다)
        var mark = function () {
            root.querySelectorAll('.bracket-match, .match-card').forEach(function (b) {
                if (b.classList.contains('bye-match')) return;
                if (!b.hasAttribute('tabindex')) b.setAttribute('tabindex', '0');
            });
        };
        mark();
        // dual DE 탭/뷰 전환으로 뒤늦게 보이는 블록도 챙긴다
        root.addEventListener('bracketviewchange', mark);
        root.addEventListener('bracketroundchange', mark);
        var deTab = document.querySelector('.tab-btn[data-tab="tournament"]');
        if (deTab) deTab.addEventListener('click', function () { setTimeout(mark, 250); });

        // Esc: 경로 뷰에서는 한 단계만 되돌린다 (바로 닫지 않는다).
        document.addEventListener('keydown', function (e) {
            if (e.key !== 'Escape' || !sheet || sheet.hidden) return;
            if (inRouteView()) backToMatch();
            else close();
        });

        // 액션의 "경로 보기" — 시트 안에서 경로 뷰로 전환한다 (페이지 스크롤 점프 없음)
        var actions = document.getElementById('ms-actions');
        if (actions) {
            actions.addEventListener('click', function (e) {
                var btn = e.target.closest('[data-ms-route]');
                if (!btn) return;
                e.preventDefault();
                showRoute(btn.getAttribute('data-ms-route'), btn.getAttribute('data-ms-team') || '');
            });
        }
    }

    window.MatchSheet = {
        open: open,
        close: close,
        init: init,
        backToMatch: backToMatch,
        openRoute: openRoute,       // 이름 검색 → 경로 뷰 (선수 검색 위젯이 쓴다)
        participants: participants  // 이 종목 DE 참가자 전원
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
