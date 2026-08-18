/**
 * FencingMind - Player Search with Autocomplete
 *
 * Player-centric data presentation: Focus on making it easy for users
 * to find themselves or players they want to watch.
 *
 * Features:
 * - Real-time autocomplete with dropdown
 * - Auto-highlight on search
 * - DE prediction table integration
 * - Head-to-head record display
 */

class PlayerSearch {
    constructor(options) {
        this.inputElement = options.inputElement;
        this.dropdownContainer = options.dropdownContainer;
        this.eventCd = options.eventCd || null;
        this.subEventCd = options.subEventCd || null;
        this.onSelect = options.onSelect || (() => {});
        this.minChars = options.minChars || 1;
        this.debounceMs = options.debounceMs || 200;
        this.searchTypeElement = options.searchTypeElement || null;  // 검색 타입 선택 요소

        this.dropdown = null;
        this.selectedIndex = -1;
        this.suggestions = [];
        this.debounceTimer = null;

        this.init();
    }

    init() {
        // Create dropdown element
        this.dropdown = document.createElement('div');
        this.dropdown.className = 'autocomplete-dropdown';
        this.dropdown.style.display = 'none';
        this.dropdownContainer.appendChild(this.dropdown);

        // Input event listeners
        this.inputElement.addEventListener('input', (e) => this.handleInput(e));
        this.inputElement.addEventListener('keydown', (e) => this.handleKeydown(e));
        this.inputElement.addEventListener('blur', () => {
            // Delay hide to allow click on dropdown
            setTimeout(() => this.hideDropdown(), 150);
        });
        this.inputElement.addEventListener('focus', () => {
            if (this.suggestions.length > 0) {
                this.showDropdown();
            }
        });
    }

    handleInput(e) {
        const query = e.target.value.trim();

        if (this.debounceTimer) {
            clearTimeout(this.debounceTimer);
        }

        if (query.length < this.minChars) {
            this.hideDropdown();
            return;
        }

        this.debounceTimer = setTimeout(() => {
            this.fetchSuggestions(query);
        }, this.debounceMs);
    }

    handleKeydown(e) {
        if (!this.dropdown || this.dropdown.style.display === 'none') {
            if (e.key === 'Enter') {
                // Search with current value if no dropdown
                this.onSelect({
                    name: this.inputElement.value.trim(),
                    team: '',
                    display: this.inputElement.value.trim()
                }, 'enter');
            }
            return;
        }

        const items = this.dropdown.querySelectorAll('.autocomplete-item');

        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                this.selectedIndex = Math.min(this.selectedIndex + 1, items.length - 1);
                this.updateSelection(items);
                break;
            case 'ArrowUp':
                e.preventDefault();
                this.selectedIndex = Math.max(this.selectedIndex - 1, -1);
                this.updateSelection(items);
                break;
            case 'Enter':
                e.preventDefault();
                if (this.selectedIndex >= 0 && this.suggestions[this.selectedIndex]) {
                    this.selectSuggestion(this.suggestions[this.selectedIndex]);
                } else {
                    // Search with current value
                    this.onSelect({
                        name: this.inputElement.value.trim(),
                        team: '',
                        display: this.inputElement.value.trim()
                    }, 'enter');
                }
                break;
            case 'Escape':
                this.hideDropdown();
                break;
        }
    }

    updateSelection(items) {
        items.forEach((item, index) => {
            item.classList.toggle('selected', index === this.selectedIndex);
        });

        // Scroll selected item into view
        if (this.selectedIndex >= 0 && items[this.selectedIndex]) {
            items[this.selectedIndex].scrollIntoView({ block: 'nearest' });
        }
    }

    async fetchSuggestions(query) {
        try {
            let url = `/api/players/autocomplete?q=${encodeURIComponent(query)}&limit=10`;
            if (this.eventCd) {
                url += `&event_cd=${encodeURIComponent(this.eventCd)}`;
            }
            // 특정 이벤트(종목) 내 검색 - 소속 검색 시 해당 이벤트 참가자만 표시
            if (this.subEventCd) {
                url += `&sub_event_cd=${encodeURIComponent(this.subEventCd)}`;
            }

            const response = await fetch(url);
            if (!response.ok) throw new Error('Failed to fetch suggestions');

            const data = await response.json();
            this.suggestions = data.suggestions || [];
            this.renderDropdown();
        } catch (error) {
            console.error('Autocomplete error:', error);
            this.hideDropdown();
        }
    }

    renderDropdown() {
        if (this.suggestions.length === 0) {
            this.hideDropdown();
            return;
        }

        this.dropdown.innerHTML = this.suggestions.map((s, index) => {
            const teamHtml = s.blurred
                ? '<span class="player-team blurred-text">소속 정보</span>'
                : `<span class="player-team">${this.escapeHtml(s.team || '')}</span>`;
            return `
            <div class="autocomplete-item" data-index="${index}">
                <span class="player-name">${this.escapeHtml(s.name)}</span>
                ${teamHtml}
                ${s.event_name ? `<span class="player-event">${this.escapeHtml(s.event_name)}</span>` : ''}
            </div>`;
        }).join('');

        // Add click handlers
        this.dropdown.querySelectorAll('.autocomplete-item').forEach((item) => {
            item.addEventListener('mousedown', (e) => {
                e.preventDefault();
                const index = parseInt(item.dataset.index);
                if (this.suggestions[index]) {
                    this.selectSuggestion(this.suggestions[index]);
                }
            });
            item.addEventListener('mouseenter', () => {
                this.selectedIndex = parseInt(item.dataset.index);
                this.updateSelection(this.dropdown.querySelectorAll('.autocomplete-item'));
            });
        });

        this.selectedIndex = -1;
        this.showDropdown();
    }

    selectSuggestion(suggestion) {
        this.inputElement.value = suggestion.name;
        this.hideDropdown();
        this.onSelect(suggestion, 'select');
    }

    showDropdown() {
        this.dropdown.style.display = 'block';
    }

    hideDropdown() {
        this.dropdown.style.display = 'none';
        this.selectedIndex = -1;
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    clear() {
        this.inputElement.value = '';
        this.suggestions = [];
        this.hideDropdown();
    }
}

/**
 * Player Highlighter - Auto-highlight all player appearances
 */
class PlayerHighlighter {
    constructor() {
        this.highlightedName = null;
    }

    highlight(playerName) {
        this.clear();

        if (!playerName) return { found: 0 };

        this.highlightedName = playerName.trim().toLowerCase();
        let foundCount = 0;
        let firstFound = null;

        // 1. Pool tables
        document.querySelectorAll('.result-table tbody tr, .matrix-table tbody tr, .final-table tbody tr').forEach(row => {
            const nameCell = row.querySelector('.player-name a, .player-col a, .name-cell a');
            if (nameCell && nameCell.textContent.trim().toLowerCase() === this.highlightedName) {
                row.classList.add('player-highlighted');
                foundCount++;
                if (!firstFound) firstFound = row;
            }
        });

        // 2. Bout players
        document.querySelectorAll('.bout-player').forEach(el => {
            const nameLink = el.querySelector('a');
            if (nameLink && nameLink.textContent.trim().toLowerCase() === this.highlightedName) {
                el.classList.add('player-highlighted');
                foundCount++;
                if (!firstFound) firstFound = el;
            }
        });

        // 3. Match cards (DE)
        document.querySelectorAll('.match-card').forEach(card => {
            const playerNames = card.querySelectorAll('.player-name');
            playerNames.forEach(nameEl => {
                if (nameEl.textContent.trim().toLowerCase() === this.highlightedName) {
                    card.classList.add('player-highlighted');
                    foundCount++;
                    if (!firstFound) firstFound = card;
                }
            });
        });

        // 4. Podium
        document.querySelectorAll('.podium-place').forEach(podium => {
            const nameEl = podium.querySelector('.podium-name a');
            if (nameEl && nameEl.textContent.trim().toLowerCase() === this.highlightedName) {
                podium.classList.add('player-highlighted');
                foundCount++;
                if (!firstFound) firstFound = podium;
            }
        });

        // 5. Pool Total Ranking
        document.querySelectorAll('.pool-container[data-pool-id="total"] tbody tr').forEach(row => {
            const nameCell = row.querySelector('.player-name a');
            if (nameCell && nameCell.textContent.trim().toLowerCase() === this.highlightedName) {
                row.classList.add('player-highlighted');
                foundCount++;
            }
        });

        // 6. Bracket component — 트리뷰(.bracket-match)·리스트뷰·레거시 모두 포함.
        //    .bracket-match 가 빠져 있어 데스크톱 기본 뷰에서 하이라이트가 무동작이었다.
        document.querySelectorAll('.bracket-bout, .bout-card, .bracket-match').forEach(bout => {
            const playerNames = bout.querySelectorAll('.player-name, .bout-player-name');
            playerNames.forEach(nameEl => {
                const textContent = nameEl.textContent || nameEl.innerText;
                if (textContent.trim().toLowerCase() === this.highlightedName) {
                    bout.classList.add('player-highlighted');
                    foundCount++;
                    if (!firstFound) firstFound = bout;
                }
            });
        });

        // 7. Dual DE 시드/진출자 명단
        document.querySelectorAll('.seeded-item, .qualifier-item').forEach(item => {
            const nameEl = item.querySelector('.seeded-name, .qualifier-name');
            if (nameEl && nameEl.textContent.trim().toLowerCase() === this.highlightedName) {
                item.classList.add('player-highlighted');
                foundCount++;
                if (!firstFound) firstFound = item;
            }
        });

        // Scroll to first found
        if (firstFound) {
            firstFound.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }

        return { found: foundCount, firstElement: firstFound };
    }

    clear() {
        document.querySelectorAll('.player-highlighted').forEach(el => {
            el.classList.remove('player-highlighted');
        });
        this.highlightedName = null;
    }
}

/**
 * MyPlayerBracket — DE 대진표에서 "내 선수" 여러 명을 동시에 표시하고 위치로 데려간다.
 *
 * 왜 필요한가: 128강이면 경기 블록이 50개가 넘는다. 색만 살짝 바뀌는 단일 하이라이트로는
 * 대회장에서 폰을 든 학부모가 자기 아이 경기를 찾을 수 없다.
 *
 * 설계 원칙
 * - 식별은 색이 아니라 "형태"로 한다: 선수마다 슬롯 번호 배지(1,2,3...)를 붙인다.
 *   색은 보조 채널로만 쓰고 최대 2계열(태극 레드/블루)로 제한한다. (색약·야외 화면 대응)
 * - 트리뷰(.bracket-match)와 리스트뷰(.match-card)는 같은 경기를 각각 렌더한다.
 *   표시는 양쪽 모두에, 이동은 "지금 보이는 뷰"의 요소로 한다.
 * - 상태는 DOM 이 이미 말하고 있는 것만 쓴다. 예상 대진을 결과처럼 보이게 하지 않는다.
 */
class MyPlayerBracket {
    constructor(options) {
        options = options || {};
        this.root = typeof options.root === 'string'
            ? document.querySelector(options.root)
            : (options.root || document);
        this.translate = options.translate || function (s) { return s; };
        this.t = options.t || function (s) { return s; };
        this.players = [];        // [{ko, display, team, slot, keys}]
        this.byslot = {};         // slot -> {player, bouts: [entry], cursor}
        this._locator = null;
        this._locatorTarget = null;
        this._rafPending = false;
        this._onScroll = null;
    }

    static get MAX_SLOTS() { return 8; }

    static norm(s) { return String(s == null ? '' : s).trim().toLowerCase(); }

    static reducedMotion() {
        try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { return false; }
    }

    /* ------------------------------------------------------------------ *
     * 스캔
     * ------------------------------------------------------------------ */

    _containers() {
        if (!this.root || !this.root.querySelectorAll) return [];
        return Array.from(this.root.querySelectorAll('.bracket-container'));
    }

    _roundOrder(container) {
        let rounds = Array.from(container.querySelectorAll('.bracket-tree .bracket-round'))
            .map(r => r.dataset.round);
        if (!rounds.length) {
            rounds = Array.from(container.querySelectorAll('.round-panel'))
                .map(p => p.dataset.roundPanel);
        }
        return rounds;
    }

    _phaseOf(container) {
        const panel = container.closest ? container.closest('.de-phase-panel') : null;
        return panel ? (panel.dataset.phase || '') : '';
    }

    static _roundOf(el) {
        const treeRound = el.closest('.bracket-round');
        if (treeRound) return treeRound.dataset.round || '';
        const panel = el.closest('.round-panel');
        if (panel) return panel.dataset.roundPanel || '';
        return '';
    }

    static _slotName(slot) {
        const el = slot.querySelector('.player-name');
        if (!el || el.classList.contains('bye-text')) return '';
        const txt = (el.textContent || '').trim();
        return txt === 'None' ? '' : txt;
    }

    static _slotScore(slot) {
        const el = slot.querySelector('.player-score, .player-score-badge');
        const txt = el ? (el.textContent || '').trim() : '';
        return (txt === '-' || txt === '') ? null : txt;
    }

    /**
     * 내 선수 목록을 세팅하고 대진표를 훑어 표시까지 끝낸다.
     * @param {Array} list [{ko, display, team}]
     * @returns {Array} 선수별 요약 (스트립 칩 렌더용)
     */
    setPlayers(list) {
        this.clear();
        const players = (list || []).slice(0, MyPlayerBracket.MAX_SLOTS);
        this.players = players.map((p, i) => {
            const ko = String(p.ko || p.name || '').trim();
            const display = String(p.display || this.translate(ko) || ko).trim();
            const keys = {};
            if (ko) keys[MyPlayerBracket.norm(ko)] = true;
            if (display) keys[MyPlayerBracket.norm(display)] = true;
            return { ko: ko, display: display, team: String(p.team || '').trim(), slot: i + 1, keys: keys };
        }).filter(p => p.ko);

        this.players.forEach(p => { this.byslot[p.slot] = { player: p, bouts: [], cursor: -1 }; });
        if (!this.players.length) return [];

        this._scan();
        return this.summaries();
    }

    _scan() {
        const seen = {};
        this._containers().forEach(container => {
            const order = this._roundOrder(container);
            const phase = this._phaseOf(container);
            const phaseRank = phase === 'second' ? 1 : 0;

            container.querySelectorAll('.bracket-match, .match-card').forEach(el => {
                const slots = el.querySelectorAll('.match-player, .card-player');
                if (slots.length !== 2) return;

                const names = [MyPlayerBracket._slotName(slots[0]), MyPlayerBracket._slotName(slots[1])];
                const mine = [];
                this.players.forEach(p => {
                    if (p.keys[MyPlayerBracket.norm(names[0])]) mine.push({ p: p, idx: 0 });
                    else if (p.keys[MyPlayerBracket.norm(names[1])]) mine.push({ p: p, idx: 1 });
                });
                if (!mine.length) return;

                const round = MyPlayerBracket._roundOf(el);
                const roundIdx = Math.max(0, order.indexOf(round));
                const boutId = el.getAttribute('data-match-id') || '';
                const isBye = el.classList.contains('bye-match');

                // DOM 표시 마킹 — 트리뷰·리스트뷰 양쪽 모든 인스턴스에 붙인다
                el.classList.add('mp-match');
                el.setAttribute('data-mp-slots', mine.map(m => m.p.slot).join(','));

                mine.forEach(m => {
                    const meSlot = slots[m.idx];
                    const oppSlot = slots[1 - m.idx];
                    meSlot.classList.add('mp-me');
                    meSlot.setAttribute('data-mp-slot', String(m.p.slot));
                    if (!meSlot.querySelector('.mp-slot-badge')) {
                        const badge = document.createElement('span');
                        badge.className = 'mp-slot-badge mp-slot-' + ((m.p.slot - 1) % 2 === 0 ? 'a' : 'b');
                        badge.textContent = String(m.p.slot);
                        badge.setAttribute('aria-label', this.t('내 선수') + ' ' + m.p.display);
                        badge.title = this.t('내 선수') + ': ' + m.p.display;
                        meSlot.insertBefore(badge, meSlot.firstChild);
                    }

                    // 상태 판정 — DOM 이 이미 확정한 것만 쓴다
                    let state;
                    if (isBye) state = 'bye';
                    else if (meSlot.classList.contains('forfeit') || oppSlot.classList.contains('forfeit')) {
                        state = meSlot.classList.contains('forfeit') ? 'forfeit' : 'win';
                    } else if (meSlot.classList.contains('winner')) state = 'win';
                    else if (oppSlot.classList.contains('winner')) state = 'loss';
                    else if (names[0] && names[1]) state = 'scheduled';   // 대진 확정, 결과 전
                    else state = 'tbd';                                   // 상대 미정

                    const key = phase + '|' + round + '|' + (boutId || (names[0] + '~' + names[1]));
                    const dedupe = m.p.slot + '#' + key;
                    if (seen[dedupe]) return;
                    seen[dedupe] = true;

                    const myScore = MyPlayerBracket._slotScore(meSlot);
                    const oppScore = MyPlayerBracket._slotScore(oppSlot);
                    this.byslot[m.p.slot].bouts.push({
                        slot: m.p.slot,
                        boutId: boutId,
                        phase: phase,
                        round: round,
                        order: phaseRank * 1000 + roundIdx,
                        state: state,
                        opponent: names[1 - m.idx],
                        score: (myScore !== null && oppScore !== null) ? (myScore + '-' + oppScore) : null,
                        container: container
                    });
                });
            });
        });

        Object.keys(this.byslot).forEach(slot => {
            this.byslot[slot].bouts.sort((a, b) => a.order - b.order);
        });
    }

    /* ------------------------------------------------------------------ *
     * 요약 (칩 텍스트)
     * ------------------------------------------------------------------ */

    _isChampion(entry) {
        if (!entry.container) return false;
        const champ = entry.container.querySelector('.bracket-champion .champion-name');
        if (!champ) return false;
        const name = MyPlayerBracket.norm(champ.textContent);
        const p = this.byslot[entry.slot].player;
        return !!p.keys[name];
    }

    summaries() {
        return this.players.map(p => {
            const rec = this.byslot[p.slot];
            const bouts = rec.bouts;
            const out = {
                slot: p.slot, ko: p.ko, display: p.display, team: p.team,
                count: bouts.length, kind: 'none', round: '', detail: ''
            };
            if (!bouts.length) { out.kind = 'absent'; return out; }

            const last = bouts[bouts.length - 1];
            const lost = bouts.filter(b => b.state === 'loss' || b.state === 'forfeit')[0];
            const nextUp = bouts.filter(b => b.state === 'scheduled' || b.state === 'tbd')[0];

            if (lost) {
                // 결승 패배는 정의상 준우승이다 (추론이 아니라 규칙). 그 외 라운드는
                // 최종순위를 함부로 단정하지 않고 "N강 탈락"으로만 말한다.
                if (lost.state !== 'forfeit' && /^결승$/.test(String(lost.round).trim())) {
                    out.kind = 'runnerup';
                } else {
                    out.kind = lost.state === 'forfeit' ? 'forfeit' : 'out';
                }
                out.round = lost.round;
                out.detail = lost.score || '';
            } else if (nextUp) {
                out.kind = nextUp.state === 'tbd' ? 'tbd' : 'next';
                out.round = nextUp.round;
            } else if (this._isChampion(last)) {
                out.kind = 'champion';
                out.round = last.round;
            } else {
                out.kind = 'won';
                out.round = last.round;
                out.detail = last.score || '';
            }
            return out;
        });
    }

    /* ------------------------------------------------------------------ *
     * 이동
     * ------------------------------------------------------------------ */

    /** 활성 뷰(트리/리스트) 안에서 해당 경기의 실제 DOM 요소를 찾는다. */
    _resolveElement(entry) {
        const container = entry.container;
        if (!container) return null;
        const activeView = container.querySelector('.bracket-view.active') || container;
        let el = null;
        if (entry.boutId) {
            el = activeView.querySelector('[data-match-id="' + CSS.escape(entry.boutId) + '"]');
        }
        if (!el) {
            // bout_id 가 없는 레거시 데이터 폴백: 같은 라운드에서 슬롯 마킹된 첫 경기
            const scope = activeView.querySelector('.round-panel[data-round-panel="' + CSS.escape(entry.round) + '"]')
                || activeView.querySelector('.bracket-round[data-round="' + CSS.escape(entry.round) + '"]')
                || activeView;
            el = scope.querySelector('[data-mp-slots~="' + entry.slot + '"], [data-mp-slots*="' + entry.slot + '"]');
        }
        return el;
    }

    /** 필요한 phase / 라운드 탭을 먼저 연다. */
    _openContext(entry) {
        // Dual DE: 다른 phase 면 전환 (dual-bracket.js 가 노출한 컨트롤러만 사용)
        if (entry.phase && window.dualDEController &&
            typeof window.dualDEController.switchToPhase === 'function' &&
            window.dualDEController.getCurrentPhase &&
            window.dualDEController.getCurrentPhase() !== entry.phase) {
            try { window.dualDEController.switchToPhase(entry.phase); } catch (e) {}
        }
        // 리스트뷰: 해당 라운드 탭 활성화
        const container = entry.container;
        if (!container) return;
        const listView = container.querySelector('.bracket-list-view');
        if (listView && listView.classList.contains('active') && entry.round) {
            const tab = container.querySelector('.round-tab[data-round="' + CSS.escape(entry.round) + '"]');
            if (tab && !tab.classList.contains('active')) tab.click();
        }
    }

    /**
     * 슬롯(선수)의 다음 경기로 이동. 여러 경기가 있으면 호출할 때마다 순환한다.
     * @returns {object|null} {index, total, entry}
     */
    jump(slot) {
        const rec = this.byslot[slot];
        if (!rec || !rec.bouts.length) return null;
        rec.cursor = (rec.cursor + 1) % rec.bouts.length;
        const entry = rec.bouts[rec.cursor];
        this._openContext(entry);
        // phase/라운드 전환 후 레이아웃이 잡히도록 한 프레임 양보
        setTimeout(() => {
            const el = this._resolveElement(entry);
            if (el) this.revealElement(el);
        }, 60);
        return { index: rec.cursor + 1, total: rec.bouts.length, entry: entry };
    }

    /** 요소로 스크롤 + 펄스. 트리뷰의 가로 스크롤 컨테이너까지 함께 움직인다. */
    revealElement(el) {
        if (!el) return;
        const smooth = !MyPlayerBracket.reducedMotion();
        try {
            el.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'center', inline: 'center' });
        } catch (e) {
            el.scrollIntoView();
        }
        el.classList.remove('mp-pulse');
        // 리플로우로 애니메이션 재시작
        void el.offsetWidth;
        el.classList.add('mp-pulse');
        window.setTimeout(() => el.classList.remove('mp-pulse'), 1600);
    }

    /* ------------------------------------------------------------------ *
     * 화면 밖 방향 안내
     *
     * 미니맵 대신 방향 인디케이터를 택한 이유: 미니맵은 스크롤 동기화·리사이즈 처리
     * 비용이 크고 390px 화면에서는 표시 면적이 안 나온다. 방향 표시는 세로(페이지)와
     * 가로(.bracket-tree) 두 축을 같은 방식으로 다루고, 학부모의 실제 질문
     * "어느 쪽으로 넘겨야 우리 애가 나오나"에 직접 답한다.
     * ------------------------------------------------------------------ */

    startLocator() {
        if (this._locator) return;
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'mp-locator';
        btn.hidden = true;
        btn.setAttribute('aria-live', 'polite');
        btn.innerHTML = '<span class="mp-locator-arrow" aria-hidden="true">↓</span>' +
                        '<span class="mp-locator-label"></span>';
        btn.addEventListener('click', () => {
            if (this._locatorTarget) this.revealElement(this._locatorTarget);
        });
        document.body.appendChild(btn);
        this._locator = btn;

        this._onScroll = () => {
            if (this._rafPending) return;
            this._rafPending = true;
            window.requestAnimationFrame(() => {
                this._rafPending = false;
                this._updateLocator();
            });
        };
        window.addEventListener('scroll', this._onScroll, { passive: true });
        window.addEventListener('resize', this._onScroll, { passive: true });
        document.querySelectorAll('.bracket-tree').forEach(t => {
            t.addEventListener('scroll', this._onScroll, { passive: true });
        });
        this._updateLocator();
    }

    stopLocator() {
        if (this._onScroll) {
            window.removeEventListener('scroll', this._onScroll);
            window.removeEventListener('resize', this._onScroll);
            document.querySelectorAll('.bracket-tree').forEach(t => {
                t.removeEventListener('scroll', this._onScroll);
            });
            this._onScroll = null;
        }
        if (this._locator) { this._locator.remove(); this._locator = null; }
        this._locatorTarget = null;
    }

    /** DE 탭이 안 보이면 인디케이터도 감춘다. */
    _rootVisible() {
        const host = (this.root && this.root.nodeType === 1) ? this.root : null;
        return !host || host.offsetParent !== null || host.classList.contains('active');
    }

    _updateLocator() {
        const btn = this._locator;
        if (!btn) return;
        if (!this._rootVisible()) { btn.hidden = true; return; }

        const els = Array.from(document.querySelectorAll('.mp-match[data-mp-slots]'))
            .filter(el => el.offsetParent !== null);
        if (!els.length) { btn.hidden = true; this._locatorTarget = null; return; }

        const vh = window.innerHeight || document.documentElement.clientHeight;
        const vw = window.innerWidth || document.documentElement.clientWidth;
        const pad = 72;   // 상·하단 고정 UI 만큼은 "보인다"고 치지 않는다
        let offscreen = 0;
        let best = null;
        let bestDist = Infinity;
        let bestDir = 'down';

        els.forEach(el => {
            const r = el.getBoundingClientRect();
            let dir = null;
            if (r.bottom < pad) dir = 'up';
            else if (r.top > vh - pad) dir = 'down';
            else if (r.right < 0) dir = 'left';
            else if (r.left > vw) dir = 'right';
            else {
                // 트리뷰 가로 스크롤 컨테이너 안에서 잘렸는지 확인
                const tree = el.closest('.bracket-tree');
                if (tree) {
                    const tr = tree.getBoundingClientRect();
                    if (r.right < tr.left + 8) dir = 'left';
                    else if (r.left > tr.right - 8) dir = 'right';
                }
            }
            if (!dir) return;
            offscreen++;
            const cx = r.left + r.width / 2;
            const cy = r.top + r.height / 2;
            const dist = (dir === 'up' || dir === 'down')
                ? Math.abs(cy - vh / 2)
                : Math.abs(cx - vw / 2);
            if (dist < bestDist) { bestDist = dist; best = el; bestDir = dir; }
        });

        if (!offscreen || !best) { btn.hidden = true; this._locatorTarget = null; return; }

        const arrows = { up: '↑', down: '↓', left: '←', right: '→' };
        btn.querySelector('.mp-locator-arrow').textContent = arrows[bestDir];
        const label = this.t('내 선수');
        btn.querySelector('.mp-locator-label').textContent =
            offscreen > 1 ? (label + ' ' + offscreen) : label;
        btn.setAttribute('aria-label', label + ' ' + this.t('경기로 이동'));
        btn.dataset.dir = bestDir;
        btn.hidden = false;
        this._locatorTarget = best;
    }

    clear() {
        document.querySelectorAll('.mp-slot-badge').forEach(b => b.remove());
        document.querySelectorAll('.mp-match').forEach(el => {
            el.classList.remove('mp-match', 'mp-pulse');
            el.removeAttribute('data-mp-slots');
        });
        document.querySelectorAll('.mp-me').forEach(el => {
            el.classList.remove('mp-me');
            el.removeAttribute('data-mp-slot');
        });
        this.players = [];
        this.byslot = {};
        this._locatorTarget = null;
        if (this._locator) this._locator.hidden = true;
    }
}

/**
 * DE Prediction Table - Show potential opponents
 */
class DEPredictionTable {
    constructor(container, subEventCd) {
        this.container = container;
        this.subEventCd = subEventCd;
        this.playerName = null;
    }

    async load(playerName) {
        this.playerName = playerName;

        if (!this.container || !this.subEventCd || !playerName) {
            console.warn('DE Prediction: Missing required parameters');
            return;
        }

        try {
            const url = `/api/events/${encodeURIComponent(this.subEventCd)}/de-prediction/${encodeURIComponent(playerName)}`;
            const response = await fetch(url);

            if (!response.ok) {
                throw new Error('Failed to fetch DE prediction');
            }

            const data = await response.json();
            this.render(data);
        } catch (error) {
            console.error('DE Prediction error:', error);
            this.container.innerHTML = `
                <div class="de-prediction-error">
                    <p>DE 예측 정보를 불러올 수 없습니다</p>
                </div>
            `;
        }
    }

    render(data) {
        if (!data.predictions || data.predictions.length === 0) {
            this.container.innerHTML = `
                <div class="de-prediction-empty">
                    <p>DE 대진표 정보가 없습니다</p>
                </div>
            `;
            return;
        }

        const playerInfo = data.player || {};
        // 선수 정보 페이지 링크 생성
        const playerName = playerInfo.name || '';
        const playerTeam = playerInfo.team || '';
        const playerLink = playerName
            ? `/player/${encodeURIComponent(playerName)}${playerTeam ? `?team=${encodeURIComponent(playerTeam)}` : ''}`
            : '#';

        const html = `
            <div class="de-prediction-table">
                <div class="de-prediction-header">
                    <h4>DE 예상 대진표</h4>
                    <div class="player-info">
                        <a href="${playerLink}" class="player-name player-link">${this.escapeHtml(playerName)}</a>
                        <span class="player-team">${this.escapeHtml(playerTeam)}</span>
                        ${playerInfo.seed ? `<span class="player-seed">Seed ${playerInfo.seed}</span>` : ''}
                    </div>
                    ${data.eliminated ? '<span class="eliminated-badge">탈락</span>' : ''}
                    ${data.current_round ? `<span class="current-round-badge">현재: ${data.current_round}</span>` : ''}
                </div>
                <div class="de-prediction-rounds">
                    ${data.predictions.map(round => this.renderRound(round)).join('')}
                </div>
            </div>
        `;

        this.container.innerHTML = html;

        // Add toggle handlers
        this.container.querySelectorAll('.round-header').forEach(header => {
            header.addEventListener('click', () => {
                const content = header.nextElementSibling;
                const icon = header.querySelector('.toggle-icon');
                const isExpanded = content.style.display !== 'none';

                content.style.display = isExpanded ? 'none' : 'block';
                icon.textContent = isExpanded ? '+' : '-';
            });
        });
    }

    renderRound(round) {
        const isExpanded = round.expanded_default;
        const opponents = round.potential_opponents || [];

        return `
            <div class="prediction-round">
                <div class="round-header">
                    <span class="round-name">${this.escapeHtml(round.round)}</span>
                    <span class="opponent-count">${opponents.length}명</span>
                    <span class="toggle-icon">${isExpanded ? '-' : '+'}</span>
                </div>
                <div class="round-content" style="display: ${isExpanded ? 'block' : 'none'};">
                    ${opponents.length > 0 ? this.renderOpponents(opponents) : '<p class="no-opponents">예상 상대 없음</p>'}
                </div>
            </div>
        `;
    }

    renderOpponents(opponents) {
        return `
            <table class="opponents-table">
                <thead>
                    <tr>
                        <th>Seed</th>
                        <th>선수</th>
                        <th>소속</th>
                        <th>상대전적</th>
                    </tr>
                </thead>
                <tbody>
                    ${opponents.map(opp => this.renderOpponent(opp)).join('')}
                </tbody>
            </table>
        `;
    }

    renderOpponent(opponent) {
        const h2h = opponent.head_to_head || {};
        const h2hText = h2h.total > 0
            ? `${h2h.wins}승 ${h2h.losses}패`
            : '-';
        const h2hClass = h2h.wins > h2h.losses ? 'positive' : (h2h.losses > h2h.wins ? 'negative' : '');

        // 선수 정보 페이지 링크 생성
        const playerName = opponent.name || '';
        const playerTeam = opponent.team || '';
        const playerLink = playerName
            ? `/player/${encodeURIComponent(playerName)}${playerTeam ? `?team=${encodeURIComponent(playerTeam)}` : ''}`
            : '#';

        return `
            <tr>
                <td class="seed-cell">${opponent.seed || '-'}</td>
                <td class="name-cell">
                    <a href="${playerLink}" class="player-link">${this.escapeHtml(playerName)}</a>
                </td>
                <td class="team-cell">${this.escapeHtml(playerTeam)}</td>
                <td class="h2h-cell ${h2hClass}">${h2hText}</td>
            </tr>
        `;
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    clear() {
        this.container.innerHTML = '';
        this.playerName = null;
    }
}

/**
 * DE Result Table - Show player's actual DE round results
 */
class DEResultTable {
    constructor(container, subEventCd) {
        this.container = container;
        this.subEventCd = subEventCd;
        this.playerName = null;
    }

    async load(playerName) {
        this.playerName = playerName;

        if (!this.container || !this.subEventCd || !playerName) {
            console.warn('DE Result: Missing required parameters');
            return;
        }

        try {
            const url = `/api/events/${encodeURIComponent(this.subEventCd)}/de-results/${encodeURIComponent(playerName)}`;
            const response = await fetch(url);

            if (!response.ok) {
                throw new Error('Failed to fetch DE results');
            }

            const data = await response.json();
            this.render(data);
        } catch (error) {
            console.error('DE Result error:', error);
            this.container.innerHTML = '';
            this.container.style.display = 'none';
        }
    }

    render(data) {
        if (!data.results || data.results.length === 0) {
            this.container.innerHTML = '';
            this.container.style.display = 'none';
            return;
        }

        const playerInfo = data.player || {};
        const playerName = playerInfo.name || '';
        const playerTeam = playerInfo.team || '';
        const playerLink = playerName
            ? `/player/${encodeURIComponent(playerName)}${playerTeam ? `?team=${encodeURIComponent(playerTeam)}` : ''}`
            : '#';

        const html = `
            <div class="de-result-table">
                <div class="de-result-header">
                    <h4>🏆 DE 경기 결과</h4>
                    <div class="player-info">
                        <a href="${playerLink}" class="player-name player-link">${this.escapeHtml(playerName)}</a>
                        <span class="player-team">${this.escapeHtml(playerTeam)}</span>
                        ${playerInfo.seed ? `<span class="player-seed">Seed ${playerInfo.seed}</span>` : ''}
                    </div>
                </div>
                <div class="de-result-rounds">
                    <table class="de-result-data">
                        <thead>
                            <tr>
                                <th>라운드</th>
                                <th>상대</th>
                                <th>소속</th>
                                <th>점수</th>
                                <th>결과</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${data.results.map(r => this.renderResultRow(r)).join('')}
                        </tbody>
                    </table>
                </div>
            </div>
        `;

        this.container.innerHTML = html;
        this.container.style.display = 'block';
    }

    renderResultRow(result) {
        const opponent = result.opponent || {};
        const opponentName = opponent.name || '-';
        const opponentTeam = opponent.team || '-';
        const opponentSeed = opponent.seed ? `(${opponent.seed})` : '';

        const opponentLink = opponentName && opponentName !== '-'
            ? `/player/${encodeURIComponent(opponentName)}${opponentTeam && opponentTeam !== '-' ? `?team=${encodeURIComponent(opponentTeam)}` : ''}`
            : '#';

        const resultClass = result.result === 'win' ? 'result-win' : 'result-lose';
        const resultText = result.result === 'win' ? '승리' : '패배';
        const resultIcon = result.result === 'win' ? '✅' : '❌';

        return `
            <tr class="${resultClass}">
                <td class="round-cell">${this.escapeHtml(result.round)}</td>
                <td class="opponent-cell">
                    <a href="${opponentLink}" class="player-link">${this.escapeHtml(opponentName)}</a>
                    ${opponentSeed ? `<span class="seed-badge">${opponentSeed}</span>` : ''}
                </td>
                <td class="team-cell">${this.escapeHtml(opponentTeam)}</td>
                <td class="score-cell">${this.escapeHtml(result.score || '-')}</td>
                <td class="result-cell ${resultClass}">${resultIcon} ${resultText}</td>
            </tr>
        `;
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    clear() {
        this.container.innerHTML = '';
        this.container.style.display = 'none';
        this.playerName = null;
    }
}

/**
 * Toast notification utility
 */
function showToast(message, type = 'success') {
    // Remove existing toasts
    document.querySelectorAll('.toast-notification').forEach(t => t.remove());

    const toast = document.createElement('div');
    toast.className = `toast-notification toast-${type}`;
    toast.textContent = message;

    const bgColor = type === 'success'
        ? 'linear-gradient(135deg, #10b981, #059669)'
        : type === 'warning'
            ? 'linear-gradient(135deg, #f59e0b, #d97706)'
            : type === 'error'
                ? 'linear-gradient(135deg, #ef4444, #dc2626)'
                : 'linear-gradient(135deg, #3b82f6, #2563eb)';

    toast.style.cssText = `
        position: fixed;
        bottom: 24px;
        right: 24px;
        padding: 14px 28px;
        background: ${bgColor};
        color: white;
        border-radius: 10px;
        font-weight: 600;
        font-size: 0.9rem;
        z-index: 9999;
        animation: toastSlideIn 0.3s ease-out, toastFadeOut 0.3s ease-in 2.7s forwards;
        box-shadow: 0 8px 30px rgba(0, 0, 0, 0.4);
        backdrop-filter: blur(10px);
    `;

    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

// CSS animations for toast
if (!document.getElementById('toast-animations')) {
    const style = document.createElement('style');
    style.id = 'toast-animations';
    style.textContent = `
        @keyframes toastSlideIn {
            0% { opacity: 0; transform: translateX(100px); }
            100% { opacity: 1; transform: translateX(0); }
        }
        @keyframes toastFadeOut {
            0% { opacity: 1; transform: translateX(0); }
            100% { opacity: 0; transform: translateX(100px); }
        }
    `;
    document.head.appendChild(style);
}

// Export for global use
window.PlayerSearch = PlayerSearch;
window.PlayerHighlighter = PlayerHighlighter;
window.MyPlayerBracket = MyPlayerBracket;
window.DEPredictionTable = DEPredictionTable;
window.DEResultTable = DEResultTable;
window.showToast = showToast;
