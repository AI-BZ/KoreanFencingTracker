/**
 * FencingMind - Dual DE Bracket Controller
 *
 * Handles tab switching, state management, and player highlighting
 * for Dual DE format (국가대표 선발전 등)
 *
 * Dual DE Format:
 * - First DE (예선 DE): 비시드 선수들의 예선 토너먼트 (32명 진출)
 * - Second DE (본선 DE): 시드 32명 + First DE 진출자 32명 = 64명
 */

class DualDEController {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        if (!this.container) {
            console.log('DualDEController: Container not found:', containerId);
            return;
        }

        this.status = this.container.dataset.status || 'pending';
        this.currentPhase = 'first';
        this.isInitialized = false;

        this.init();
    }

    init() {
        this.bindPhaseToggle();
        this.bindSeededToggle();
        this.bindKeyboardNavigation();
        this.restoreState();
        this.initPlayerHighlighting();
        this.updateAriaAttributes();
        this.isInitialized = true;

        console.log('DualDEController initialized:', {
            status: this.status,
            currentPhase: this.currentPhase
        });
    }

    /**
     * Bind click events to phase toggle buttons
     */
    bindPhaseToggle() {
        const phaseBtns = this.container.querySelectorAll('.de-phase-btn');
        const panels = this.container.querySelectorAll('.de-phase-panel');

        phaseBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                if (btn.disabled || btn.classList.contains('active')) return;

                const phase = btn.dataset.phase;
                this.switchToPhase(phase);
            });
        });
    }

    /**
     * Bind toggle events for seeded players section
     */
    bindSeededToggle() {
        const seedDetails = this.container.querySelector('.seeded-players-section');
        if (!seedDetails) return;

        seedDetails.addEventListener('toggle', () => {
            const toggleIcon = seedDetails.querySelector('.seeded-toggle-icon');
            if (toggleIcon) {
                toggleIcon.textContent = seedDetails.open ? '▲' : '▼';
            }
        });
    }

    /**
     * Keyboard navigation for accessibility
     */
    bindKeyboardNavigation() {
        const phaseBtns = this.container.querySelectorAll('.de-phase-btn');

        phaseBtns.forEach((btn, index) => {
            btn.addEventListener('keydown', (e) => {
                let targetBtn = null;

                switch (e.key) {
                    case 'ArrowLeft':
                    case 'ArrowUp':
                        e.preventDefault();
                        targetBtn = phaseBtns[index - 1] || phaseBtns[phaseBtns.length - 1];
                        break;
                    case 'ArrowRight':
                    case 'ArrowDown':
                        e.preventDefault();
                        targetBtn = phaseBtns[index + 1] || phaseBtns[0];
                        break;
                    case 'Home':
                        e.preventDefault();
                        targetBtn = phaseBtns[0];
                        break;
                    case 'End':
                        e.preventDefault();
                        targetBtn = phaseBtns[phaseBtns.length - 1];
                        break;
                }

                if (targetBtn && !targetBtn.disabled) {
                    targetBtn.focus();
                    targetBtn.click();
                }
            });
        });
    }

    /**
     * Switch to a specific phase
     */
    switchToPhase(phase) {
        if (!this.canSwitchTo(phase)) return;

        const phaseBtns = this.container.querySelectorAll('.de-phase-btn');
        const panels = this.container.querySelectorAll('.de-phase-panel');

        // Update buttons
        phaseBtns.forEach(b => {
            const isActive = b.dataset.phase === phase;
            b.classList.toggle('active', isActive);
            b.setAttribute('aria-selected', isActive ? 'true' : 'false');
            b.setAttribute('tabindex', isActive ? '0' : '-1');
        });

        // Update panels
        panels.forEach(p => {
            const isActive = p.dataset.phase === phase;
            p.classList.toggle('active', isActive);
            p.hidden = !isActive;
        });

        this.currentPhase = phase;
        this.saveState();
        this.updateAriaAttributes();

        // Dispatch custom event for external listeners
        this.container.dispatchEvent(new CustomEvent('phasechange', {
            detail: { phase: phase, status: this.status }
        }));

        // Re-apply highlights if player search is active
        if (window.playerHighlighter && window.playerHighlighter.highlightedName) {
            window.playerHighlighter.highlight(window.playerHighlighter.highlightedName);
        }
    }

    /**
     * Check if switching to a phase is allowed
     */
    canSwitchTo(phase) {
        if (phase === 'first') return true;

        // Second DE only available if First DE is complete
        const secondBtn = this.container.querySelector('.de-phase-btn[data-phase="second"]');
        return secondBtn && !secondBtn.disabled;
    }

    /**
     * Save current state to localStorage
     */
    saveState() {
        try {
            const eventId = this.getEventId();
            if (eventId) {
                localStorage.setItem(`dualDE_phase_${eventId}`, this.currentPhase);
            }
        } catch (e) {
            // localStorage might not be available
            console.warn('Could not save state to localStorage:', e);
        }
    }

    /**
     * Restore state from localStorage or auto-select based on status
     */
    restoreState() {
        // Auto-select phase based on tournament status
        if (this.status === 'second_de_in_progress' || this.status === 'completed') {
            if (this.canSwitchTo('second')) {
                this.switchToPhase('second');
                return;
            }
        }

        // Try to restore from localStorage
        try {
            const eventId = this.getEventId();
            if (eventId) {
                const savedPhase = localStorage.getItem(`dualDE_phase_${eventId}`);
                if (savedPhase && this.canSwitchTo(savedPhase)) {
                    this.switchToPhase(savedPhase);
                    return;
                }
            }
        } catch (e) {
            console.warn('Could not restore state from localStorage:', e);
        }

        // Default: First DE
        this.switchToPhase('first');
    }

    /**
     * Get event ID from URL or data attribute
     */
    getEventId() {
        // Try to get from URL
        const pathMatch = window.location.pathname.match(/\/event\/([^\/]+)/);
        if (pathMatch) return pathMatch[1];

        // Try to get from container
        return this.container.dataset.eventId || null;
    }

    /**
     * Update ARIA attributes for accessibility
     */
    updateAriaAttributes() {
        const phaseBtns = this.container.querySelectorAll('.de-phase-btn');
        const activePanel = this.container.querySelector('.de-phase-panel.active');

        phaseBtns.forEach(btn => {
            const isActive = btn.classList.contains('active');
            btn.setAttribute('aria-selected', isActive.toString());
            btn.setAttribute('tabindex', isActive ? '0' : '-1');
        });

        if (activePanel) {
            activePanel.setAttribute('tabindex', '0');
        }
    }

    /**
     * Initialize player highlighting for Dual DE sections
     */
    initPlayerHighlighting() {
        // Extend PlayerHighlighter if it exists
        if (typeof PlayerHighlighter !== 'undefined') {
            const originalHighlight = PlayerHighlighter.prototype.highlight;

            PlayerHighlighter.prototype.highlight = function(playerName) {
                // Call original method
                const result = originalHighlight.call(this, playerName);

                // Also highlight in seeded/qualifier sections
                if (!playerName) return result;

                const normalizedName = playerName.trim().toLowerCase();
                let additionalFound = 0;

                // Highlight in seeded items
                document.querySelectorAll('.seeded-item').forEach(item => {
                    const nameEl = item.querySelector('.seeded-name');
                    if (nameEl && nameEl.textContent.trim().toLowerCase() === normalizedName) {
                        item.classList.add('player-highlighted');
                        additionalFound++;
                    }
                });

                // Highlight in qualifier items
                document.querySelectorAll('.qualifier-item').forEach(item => {
                    const nameEl = item.querySelector('.qualifier-name');
                    if (nameEl && nameEl.textContent.trim().toLowerCase() === normalizedName) {
                        item.classList.add('player-highlighted');
                        additionalFound++;
                    }
                });

                return {
                    found: result.found + additionalFound,
                    firstElement: result.firstElement
                };
            };

            console.log('DualDEController: PlayerHighlighter extended');
        }
    }

    /**
     * Get all player names in the current phase
     * Useful for search autocomplete
     */
    getPlayersInCurrentPhase() {
        const panel = this.container.querySelector(`.de-phase-panel[data-phase="${this.currentPhase}"]`);
        if (!panel) return [];

        const players = new Set();

        // From bracket matches
        panel.querySelectorAll('.player-name, .bout-player-name').forEach(el => {
            const name = el.textContent.trim();
            if (name && !['Seed', 'BYE', 'None', '-', ''].includes(name)) {
                players.add(name);
            }
        });

        // From seeded players (always visible)
        this.container.querySelectorAll('.seeded-name').forEach(el => {
            const name = el.textContent.trim();
            if (name) players.add(name);
        });

        // From qualifiers (always visible when First DE complete)
        this.container.querySelectorAll('.qualifier-name').forEach(el => {
            const name = el.textContent.trim();
            if (name) players.add(name);
        });

        return Array.from(players);
    }

    /**
     * Get all players across both phases
     */
    getAllPlayers() {
        const players = new Set();

        this.container.querySelectorAll('.player-name, .bout-player-name, .seeded-name, .qualifier-name').forEach(el => {
            const name = el.textContent.trim();
            if (name && !['Seed', 'BYE', 'None', '-', ''].includes(name)) {
                players.add(name);
            }
        });

        return Array.from(players);
    }

    /**
     * Find a player across all sections and highlight
     */
    findAndHighlightPlayer(playerName) {
        if (!playerName) return null;

        const normalizedName = playerName.trim().toLowerCase();

        // Check seeded players
        const seededItem = Array.from(this.container.querySelectorAll('.seeded-item')).find(item => {
            const nameEl = item.querySelector('.seeded-name');
            return nameEl && nameEl.textContent.trim().toLowerCase() === normalizedName;
        });

        if (seededItem) {
            // Switch to First DE to show seeded section
            this.switchToPhase('first');
            seededItem.scrollIntoView({ behavior: 'smooth', block: 'center' });
            return { found: true, phase: 'first', type: 'seeded', element: seededItem };
        }

        // Check qualifiers
        const qualifierItem = Array.from(this.container.querySelectorAll('.qualifier-item')).find(item => {
            const nameEl = item.querySelector('.qualifier-name');
            return nameEl && nameEl.textContent.trim().toLowerCase() === normalizedName;
        });

        if (qualifierItem) {
            this.switchToPhase('first');
            qualifierItem.scrollIntoView({ behavior: 'smooth', block: 'center' });
            return { found: true, phase: 'first', type: 'qualifier', element: qualifierItem };
        }

        // Check First DE brackets
        const firstDEPanel = this.container.querySelector('.de-phase-panel[data-phase="first"]');
        if (firstDEPanel) {
            const firstDEMatch = this.findPlayerInPanel(firstDEPanel, normalizedName);
            if (firstDEMatch) {
                this.switchToPhase('first');
                firstDEMatch.scrollIntoView({ behavior: 'smooth', block: 'center' });
                return { found: true, phase: 'first', type: 'bracket', element: firstDEMatch };
            }
        }

        // Check Second DE brackets
        const secondDEPanel = this.container.querySelector('.de-phase-panel[data-phase="second"]');
        if (secondDEPanel && this.canSwitchTo('second')) {
            const secondDEMatch = this.findPlayerInPanel(secondDEPanel, normalizedName);
            if (secondDEMatch) {
                this.switchToPhase('second');
                secondDEMatch.scrollIntoView({ behavior: 'smooth', block: 'center' });
                return { found: true, phase: 'second', type: 'bracket', element: secondDEMatch };
            }
        }

        return { found: false };
    }

    /**
     * Find player in a panel
     */
    findPlayerInPanel(panel, normalizedName) {
        const matches = panel.querySelectorAll('.bracket-bout, .bout-card, .match-card');
        for (const match of matches) {
            const playerNames = match.querySelectorAll('.player-name, .bout-player-name');
            for (const nameEl of playerNames) {
                if (nameEl.textContent.trim().toLowerCase() === normalizedName) {
                    return match;
                }
            }
        }
        return null;
    }

    /**
     * Get current tournament status
     */
    getStatus() {
        return this.status;
    }

    /**
     * Get current phase
     */
    getCurrentPhase() {
        return this.currentPhase;
    }

    /**
     * Check if initialized
     */
    isReady() {
        return this.isInitialized;
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    const container = document.getElementById('dual-de-container');
    if (container) {
        window.dualDEController = new DualDEController('dual-de-container');
    }
});

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = DualDEController;
}
