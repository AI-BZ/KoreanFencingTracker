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

        // 6. Bracket component (new)
        document.querySelectorAll('.bracket-bout, .bout-card').forEach(bout => {
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
window.DEPredictionTable = DEPredictionTable;
window.DEResultTable = DEResultTable;
window.showToast = showToast;
