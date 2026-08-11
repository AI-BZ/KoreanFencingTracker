# Dual DE (First DE + Second DE) UI Component Design

## Overview

Korean National Team Selection (국가대표 선발전) uses a unique **Dual DE format**:
1. **First DE**: Preliminary elimination for non-seeded players
2. **Second DE**: Main elimination tournament combining seeded players + First DE survivors

This document specifies the UI component design for displaying this format.

---

## 1. Component Structure

### Option A: Extend Existing bracket.html (Recommended)
Add conditional logic to handle dual DE data structure within the existing component.

### Option B: Create New dual-bracket.html
Separate component that includes bracket.html twice with wrapper logic.

**Recommendation: Option A** - Maintains single source of truth, easier maintenance.

---

## 2. Data Model Requirements

### Expected Data Structure (from server)
```python
class DualDEBracket:
    """Dual DE bracket for national team selection"""
    format: str = "dual_de"  # Identifies this as dual DE

    # First DE (Preliminary)
    first_de: {
        "rounds": ["64강", "32강", "16강"],
        "bouts_by_round": {...},
        "seeding": [...],  # Non-seeded participants
        "participant_count": int,
        "starting_round": str,
        "is_in_progress": bool,
        "is_complete": bool,
        "qualifiers": [...]  # Players who advance to Second DE
    }

    # Second DE (Main)
    second_de: {
        "rounds": ["32강", "16강", "8강", "4강", "결승"],
        "bouts_by_round": {...},
        "seeding": [...],  # Seeded players (exempted from First DE)
        "first_de_qualifiers": [...],  # From First DE
        "participant_count": int,
        "starting_round": str,
        "is_in_progress": bool,
        "is_complete": bool
    }

    # Overall status
    status: str  # "first_de_in_progress" | "second_de_in_progress" | "completed"
    seeded_players: [...]  # Players exempt from First DE
```

---

## 3. Wireframe / ASCII Mockup

### Desktop View (Wide Screen)
```
┌────────────────────────────────────────────────────────────────────────────┐
│ DE Bracket                                            [Tree] [List]  64명  │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────────┐ │   │
│  │  │ ● First DE   │  │ ○ Second DE  │  │ Status: First DE 진행 중   │ │   │
│  │  │   (예선 DE)   │  │   (본선 DE)   │  │                            │ │   │
│  │  └──────────────┘  └──────────────┘  └────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                            │
│  ┌─ Seeded Players (First DE 면제) ──────────────────────────────────────┐ │
│  │  ⭐ 김선수 [1] 국가대표팀    ⭐ 이선수 [2] 국가대표팀               │ │
│  │  ⭐ 박선수 [3] 경희대         ⭐ 최선수 [4] 한체대                   │ │
│  │                        [ + 더보기 (8명) ]                            │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                            │
│  ┌─ First DE Bracket ───────────────────────────────────────────────────┐  │
│  │                                                                      │  │
│  │  64강              32강              16강           → Second DE     │  │
│  │  ┌────────────┐    ┌────────────┐    ┌────────────┐   ┌──────────┐  │  │
│  │  │ A vs B     │───→│            │───→│            │──→│ Qualifier │  │  │
│  │  │ [5] vs [60]│    │ Winner     │    │ Winner     │   │ [16명]    │  │  │
│  │  │  15 - 8    │    │            │    │            │   │ → 2nd DE  │  │  │
│  │  └────────────┘    └────────────┘    └────────────┘   └──────────┘  │  │
│  │        ...              ...              ...                        │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                            │
│  ┌─ First DE Qualifiers (Second DE 진출자) ─────────────────────────────┐  │
│  │  ✅ 정선수 [9]    ✅ 강선수 [12]    ✅ 조선수 [17]    ...          │  │
│  │  (16명 진출 / 48명 탈락)                                             │  │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

### Mobile View (Narrow Screen)
```
┌────────────────────────────┐
│ DE Bracket         [List]  │
├────────────────────────────┤
│ ┌────────────────────────┐ │
│ │ ● First DE  ○ Second DE│ │
│ └────────────────────────┘ │
│                            │
│ ⚠️ First DE 진행 중         │
│                            │
│ ─── Seeded Players ─────── │
│ ⭐ 김선수 [1] 국가대표팀    │
│ ⭐ 이선수 [2] 국가대표팀    │
│        [ 더보기 ]          │
│                            │
│ ─── Round Tabs ─────────── │
│ [64강] [32강] [16강]       │
│                            │
│ ─── 64강 (32경기) ──────── │
│ ┌────────────────────────┐ │
│ │ Match 1         완료   │ │
│ │ [5] 홍선수   서울팀     │ │
│ │     15                 │ │
│ │ VS                     │ │
│ │ [60] 유선수  부산팀     │ │
│ │      8                 │ │
│ │ 🏆 Winner: 홍선수       │ │
│ └────────────────────────┘ │
│        ...                 │
└────────────────────────────┘
```

---

## 4. Component File Structure

### New/Modified Files
```
templates/
├── components/
│   ├── bracket.html           # Modified: Add dual DE conditional
│   └── dual-bracket-tabs.html # NEW: Tab navigation component
│
static/
├── css/
│   └── bracket.css            # Modified: Add dual DE styles
│
├── js/
│   └── dual-bracket.js        # NEW: Tab switching, state management
```

---

## 5. HTML Component Design

### 5.1 dual-bracket-tabs.html (New Component)
```html
{#
  Dual DE Tab Navigation Component
  Usage: {% include 'components/dual-bracket-tabs.html' %}
  Requires: dual_bracket (DualDEBracket data)
#}

<div class="dual-de-container" id="dual-de-container" data-status="{{ dual_bracket.status }}">

    <!-- DE Phase Selector -->
    <div class="dual-de-header">
        <div class="de-phase-toggle">
            <button class="de-phase-btn active"
                    data-phase="first"
                    {% if not dual_bracket.first_de.is_complete %}aria-current="true"{% endif %}>
                <span class="phase-indicator {% if dual_bracket.status == 'first_de_in_progress' %}active{% elif dual_bracket.first_de.is_complete %}complete{% endif %}"></span>
                <span class="phase-label">First DE</span>
                <span class="phase-sublabel">예선 DE</span>
            </button>
            <button class="de-phase-btn"
                    data-phase="second"
                    {% if dual_bracket.status == 'second_de_in_progress' %}aria-current="true"{% endif %}
                    {% if not dual_bracket.first_de.is_complete %}disabled{% endif %}>
                <span class="phase-indicator {% if dual_bracket.status == 'second_de_in_progress' %}active{% elif dual_bracket.second_de.is_complete %}complete{% endif %}"></span>
                <span class="phase-label">Second DE</span>
                <span class="phase-sublabel">본선 DE</span>
            </button>
        </div>

        <!-- Status Badge -->
        <div class="dual-de-status">
            {% if dual_bracket.status == 'first_de_in_progress' %}
            <span class="status-badge in-progress">
                <span class="status-dot pulse"></span>
                First DE 진행 중
            </span>
            {% elif dual_bracket.status == 'second_de_in_progress' %}
            <span class="status-badge in-progress">
                <span class="status-dot pulse"></span>
                Second DE 진행 중
            </span>
            {% elif dual_bracket.status == 'completed' %}
            <span class="status-badge complete">
                <span class="status-icon">✓</span>
                대회 종료
            </span>
            {% else %}
            <span class="status-badge pending">
                <span class="status-icon">○</span>
                대기 중
            </span>
            {% endif %}
        </div>
    </div>

    <!-- Seeded Players Section (Always visible when relevant) -->
    {% if dual_bracket.seeded_players %}
    <details class="seeded-players-section" {% if dual_bracket.status == 'first_de_in_progress' %}open{% endif %}>
        <summary class="seeded-header">
            <span class="seeded-icon">⭐</span>
            <span class="seeded-title">Seeded Players</span>
            <span class="seeded-subtitle">(First DE 면제 - Second DE 직행)</span>
            <span class="seeded-count">{{ dual_bracket.seeded_players|length }}명</span>
            <span class="seeded-toggle">+</span>
        </summary>
        <div class="seeded-grid">
            {% for player in dual_bracket.seeded_players %}
            <div class="seeded-item">
                <span class="seeded-rank">[{{ player.seed }}]</span>
                <a href="/player/{{ player.name|urlencode }}?team={{ player.team|urlencode }}"
                   class="seeded-name player-link">{{ player.name }}</a>
                <span class="seeded-team">{{ player.team }}</span>
                <span class="seeded-badge">Seed</span>
            </div>
            {% endfor %}
        </div>
    </details>
    {% endif %}

    <!-- First DE Panel -->
    <div class="de-phase-panel active" id="first-de-panel" data-phase="first">
        {% if dual_bracket.first_de %}

        <!-- First DE Progress Indicator -->
        <div class="de-progress-bar">
            <div class="progress-track">
                {% for round_name in dual_bracket.first_de.rounds %}
                <div class="progress-step {% if dual_bracket.first_de.completed_rounds and round_name in dual_bracket.first_de.completed_rounds %}completed{% elif dual_bracket.first_de.current_round == round_name %}current{% endif %}">
                    <span class="step-label">{{ round_name }}</span>
                </div>
                {% endfor %}
                <div class="progress-step final {% if dual_bracket.first_de.is_complete %}completed{% endif %}">
                    <span class="step-label">→ Second DE</span>
                </div>
            </div>
        </div>

        <!-- Include Standard Bracket Component -->
        {% set bracket = dual_bracket.first_de %}
        {% set bracket_id = "first-de-bracket" %}
        {% include 'components/bracket.html' %}

        <!-- First DE Qualifiers (who advance to Second DE) -->
        {% if dual_bracket.first_de.qualifiers %}
        <div class="qualifiers-section">
            <div class="qualifiers-header">
                <span class="qualifiers-icon">✅</span>
                <span class="qualifiers-title">Second DE 진출자</span>
                <span class="qualifiers-count">
                    {{ dual_bracket.first_de.qualifiers|length }}명 진출 /
                    {{ dual_bracket.first_de.participant_count - dual_bracket.first_de.qualifiers|length }}명 탈락
                </span>
            </div>
            <div class="qualifiers-grid">
                {% for player in dual_bracket.first_de.qualifiers %}
                <div class="qualifier-item">
                    <span class="qualifier-seed">[{{ player.final_seed }}]</span>
                    <a href="/player/{{ player.name|urlencode }}?team={{ player.team|urlencode }}"
                       class="qualifier-name player-link">{{ player.name }}</a>
                    <span class="qualifier-team">{{ player.team }}</span>
                </div>
                {% endfor %}
            </div>
        </div>
        {% endif %}

        {% else %}
        <div class="bracket-empty">
            <p>First DE 데이터가 없습니다</p>
        </div>
        {% endif %}
    </div>

    <!-- Second DE Panel -->
    <div class="de-phase-panel" id="second-de-panel" data-phase="second">
        {% if dual_bracket.second_de %}

        <!-- Second DE Participant Sources -->
        <div class="second-de-sources">
            <div class="source-group seeded">
                <span class="source-icon">⭐</span>
                <span class="source-label">Seeded Players</span>
                <span class="source-count">{{ dual_bracket.seeded_players|length }}명</span>
            </div>
            <span class="source-connector">+</span>
            <div class="source-group qualifiers">
                <span class="source-icon">✅</span>
                <span class="source-label">First DE 진출자</span>
                <span class="source-count">{{ dual_bracket.second_de.first_de_qualifiers|length }}명</span>
            </div>
            <span class="source-connector">=</span>
            <div class="source-group total">
                <span class="source-icon">👥</span>
                <span class="source-label">Total</span>
                <span class="source-count">{{ dual_bracket.second_de.participant_count }}명</span>
            </div>
        </div>

        <!-- Include Standard Bracket Component -->
        {% set bracket = dual_bracket.second_de %}
        {% set bracket_id = "second-de-bracket" %}
        {% include 'components/bracket.html' %}

        {% else %}
        <div class="bracket-empty">
            {% if not dual_bracket.first_de.is_complete %}
            <div class="waiting-notice">
                <span class="waiting-icon">⏳</span>
                <p>First DE가 완료되면 Second DE가 표시됩니다</p>
                <p class="waiting-sublabel">현재 First DE 진행 중</p>
            </div>
            {% else %}
            <p>Second DE 데이터가 없습니다</p>
            {% endif %}
        </div>
        {% endif %}
    </div>

    <!-- Connection Visualization (Desktop only) -->
    <div class="de-connection-flow desktop-only">
        <svg class="connection-svg" viewBox="0 0 100 30">
            <path d="M10,15 Q30,5 50,15 T90,15"
                  stroke="var(--accent-primary)"
                  stroke-width="2"
                  fill="none"
                  stroke-dasharray="5,5"/>
            <circle cx="10" cy="15" r="4" fill="var(--bracket-accent)"/>
            <circle cx="90" cy="15" r="4" fill="var(--bracket-winner-border)"/>
        </svg>
        <div class="connection-labels">
            <span>First DE 진출자</span>
            <span class="arrow">→</span>
            <span>Second DE 참가</span>
        </div>
    </div>
</div>
```

---

## 6. CSS Design (Dark Theme)

### 6.1 Dual DE Specific Styles
```css
/* ========================================
   DUAL DE CONTAINER
   ======================================== */
.dual-de-container {
    background: var(--bracket-bg);
    border-radius: 12px;
    padding: 16px;
    margin: 16px 0;
}

/* ========================================
   DE PHASE TOGGLE (Tab Navigation)
   ======================================== */
.dual-de-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 16px;
    flex-wrap: wrap;
    gap: 12px;
}

.de-phase-toggle {
    display: flex;
    background: var(--bracket-card-bg);
    border-radius: 10px;
    padding: 4px;
    box-shadow: var(--bracket-shadow);
}

.de-phase-btn {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
    padding: 12px 24px;
    border: none;
    background: transparent;
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.3s ease;
    min-width: 120px;
}

.de-phase-btn:hover:not(:disabled) {
    background: var(--bracket-score-bg);
}

.de-phase-btn.active {
    background: var(--primary, #3b82f6);
    box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);
}

.de-phase-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

.phase-indicator {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: var(--bracket-text-muted);
    transition: all 0.3s ease;
}

.phase-indicator.active {
    background: #fbbf24;
    box-shadow: 0 0 12px rgba(251, 191, 36, 0.6);
    animation: pulse-indicator 2s infinite;
}

.phase-indicator.complete {
    background: var(--bracket-winner-border);
}

@keyframes pulse-indicator {
    0%, 100% { transform: scale(1); opacity: 1; }
    50% { transform: scale(1.2); opacity: 0.8; }
}

.phase-label {
    font-size: 14px;
    font-weight: 700;
    color: var(--bracket-text-secondary);
    transition: color 0.3s ease;
}

.de-phase-btn.active .phase-label {
    color: white;
}

.phase-sublabel {
    font-size: 11px;
    color: var(--bracket-text-muted);
}

.de-phase-btn.active .phase-sublabel {
    color: rgba(255, 255, 255, 0.8);
}

/* ========================================
   STATUS BADGE
   ======================================== */
.dual-de-status {
    display: flex;
    align-items: center;
}

.status-badge {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 8px 16px;
    border-radius: 20px;
    font-size: 13px;
    font-weight: 600;
}

.status-badge.in-progress {
    background: rgba(251, 191, 36, 0.15);
    color: #fbbf24;
    border: 1px solid rgba(251, 191, 36, 0.3);
}

.status-badge.complete {
    background: rgba(34, 197, 94, 0.15);
    color: #4ade80;
    border: 1px solid rgba(34, 197, 94, 0.3);
}

.status-badge.pending {
    background: rgba(107, 107, 123, 0.15);
    color: var(--bracket-text-muted);
    border: 1px solid rgba(107, 107, 123, 0.3);
}

.status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: currentColor;
}

.status-dot.pulse {
    animation: pulse-dot 1.5s infinite;
}

@keyframes pulse-dot {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
}

/* ========================================
   SEEDED PLAYERS SECTION
   ======================================== */
.seeded-players-section {
    background: linear-gradient(135deg, rgba(212, 165, 116, 0.1), rgba(212, 165, 116, 0.05));
    border: 1px solid rgba(212, 165, 116, 0.3);
    border-radius: 10px;
    margin-bottom: 16px;
    overflow: hidden;
}

.seeded-header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 18px;
    cursor: pointer;
    font-weight: 600;
    color: var(--accent-gold, #d4a574);
    background: rgba(212, 165, 116, 0.08);
    border-bottom: 1px solid rgba(212, 165, 116, 0.2);
}

.seeded-header::-webkit-details-marker {
    display: none;
}

.seeded-icon {
    font-size: 18px;
}

.seeded-title {
    font-size: 14px;
    font-weight: 700;
}

.seeded-subtitle {
    font-size: 12px;
    color: var(--bracket-text-muted);
    font-weight: 400;
}

.seeded-count {
    margin-left: auto;
    background: rgba(212, 165, 116, 0.2);
    padding: 4px 10px;
    border-radius: 12px;
    font-size: 12px;
}

.seeded-toggle {
    font-size: 16px;
    font-weight: bold;
    color: var(--bracket-text-secondary);
    transition: transform 0.3s ease;
}

details[open] .seeded-toggle {
    transform: rotate(45deg);
}

.seeded-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 10px;
    padding: 14px;
}

.seeded-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 14px;
    background: rgba(212, 165, 116, 0.08);
    border-radius: 8px;
    border: 1px solid rgba(212, 165, 116, 0.15);
}

.seeded-rank {
    font-size: 12px;
    font-weight: 700;
    color: var(--accent-gold, #d4a574);
    min-width: 28px;
}

.seeded-name {
    flex: 1;
    font-weight: 600;
    color: var(--bracket-text-primary);
    text-decoration: none;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.seeded-name:hover {
    color: var(--accent-gold, #d4a574);
}

.seeded-team {
    font-size: 11px;
    color: var(--bracket-text-secondary);
    max-width: 80px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.seeded-badge {
    font-size: 9px;
    font-weight: 700;
    text-transform: uppercase;
    padding: 2px 6px;
    background: var(--accent-gold, #d4a574);
    color: var(--bracket-bg);
    border-radius: 4px;
}

/* ========================================
   DE PHASE PANELS
   ======================================== */
.de-phase-panel {
    display: none;
    animation: fadeIn 0.3s ease;
}

.de-phase-panel.active {
    display: block;
}

/* ========================================
   PROGRESS BAR
   ======================================== */
.de-progress-bar {
    margin-bottom: 20px;
    padding: 16px;
    background: var(--bracket-card-bg);
    border-radius: 10px;
}

.progress-track {
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: relative;
}

.progress-track::before {
    content: '';
    position: absolute;
    top: 50%;
    left: 0;
    right: 0;
    height: 3px;
    background: var(--bracket-border);
    transform: translateY(-50%);
    z-index: 0;
}

.progress-step {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    position: relative;
    z-index: 1;
}

.progress-step::before {
    content: '';
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: var(--bracket-card-bg);
    border: 3px solid var(--bracket-border);
    transition: all 0.3s ease;
}

.progress-step.completed::before {
    background: var(--bracket-winner-border);
    border-color: var(--bracket-winner-border);
}

.progress-step.current::before {
    background: #fbbf24;
    border-color: #fbbf24;
    box-shadow: 0 0 12px rgba(251, 191, 36, 0.5);
    animation: pulse-step 2s infinite;
}

@keyframes pulse-step {
    0%, 100% { transform: scale(1); }
    50% { transform: scale(1.15); }
}

.progress-step.final::before {
    width: 20px;
    height: 20px;
    background: linear-gradient(135deg, var(--primary, #3b82f6), #2563eb);
    border-color: var(--primary, #3b82f6);
}

.step-label {
    font-size: 11px;
    font-weight: 600;
    color: var(--bracket-text-muted);
    white-space: nowrap;
}

.progress-step.completed .step-label,
.progress-step.current .step-label {
    color: var(--bracket-text-primary);
}

/* ========================================
   QUALIFIERS SECTION
   ======================================== */
.qualifiers-section {
    margin-top: 20px;
    background: linear-gradient(135deg, rgba(34, 197, 94, 0.1), rgba(34, 197, 94, 0.05));
    border: 1px solid rgba(34, 197, 94, 0.3);
    border-radius: 10px;
    overflow: hidden;
}

.qualifiers-header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 18px;
    background: rgba(34, 197, 94, 0.08);
    border-bottom: 1px solid rgba(34, 197, 94, 0.2);
}

.qualifiers-icon {
    font-size: 18px;
}

.qualifiers-title {
    font-size: 14px;
    font-weight: 700;
    color: #4ade80;
}

.qualifiers-count {
    margin-left: auto;
    font-size: 12px;
    color: var(--bracket-text-secondary);
}

.qualifiers-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 8px;
    padding: 14px;
}

.qualifier-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    background: rgba(34, 197, 94, 0.08);
    border-radius: 6px;
}

.qualifier-seed {
    font-size: 11px;
    font-weight: 700;
    color: #4ade80;
    min-width: 24px;
}

.qualifier-name {
    flex: 1;
    font-weight: 500;
    color: var(--bracket-text-primary);
    text-decoration: none;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.qualifier-name:hover {
    color: #4ade80;
}

.qualifier-team {
    font-size: 10px;
    color: var(--bracket-text-muted);
}

/* ========================================
   SECOND DE SOURCES
   ======================================== */
.second-de-sources {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 16px;
    padding: 16px;
    margin-bottom: 16px;
    background: var(--bracket-card-bg);
    border-radius: 10px;
    flex-wrap: wrap;
}

.source-group {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 16px;
    border-radius: 8px;
}

.source-group.seeded {
    background: rgba(212, 165, 116, 0.15);
    border: 1px solid rgba(212, 165, 116, 0.3);
}

.source-group.qualifiers {
    background: rgba(34, 197, 94, 0.15);
    border: 1px solid rgba(34, 197, 94, 0.3);
}

.source-group.total {
    background: rgba(59, 130, 246, 0.15);
    border: 1px solid rgba(59, 130, 246, 0.3);
}

.source-icon {
    font-size: 16px;
}

.source-label {
    font-size: 12px;
    color: var(--bracket-text-secondary);
}

.source-count {
    font-size: 14px;
    font-weight: 700;
    color: var(--bracket-text-primary);
}

.source-connector {
    font-size: 18px;
    font-weight: 700;
    color: var(--bracket-text-muted);
}

/* ========================================
   WAITING NOTICE
   ======================================== */
.waiting-notice {
    text-align: center;
    padding: 60px 20px;
}

.waiting-icon {
    font-size: 48px;
    display: block;
    margin-bottom: 16px;
    animation: bounce 2s infinite;
}

@keyframes bounce {
    0%, 100% { transform: translateY(0); }
    50% { transform: translateY(-10px); }
}

.waiting-notice p {
    font-size: 16px;
    color: var(--bracket-text-secondary);
    margin: 0;
}

.waiting-sublabel {
    font-size: 13px !important;
    color: var(--bracket-text-muted) !important;
    margin-top: 8px !important;
}

/* ========================================
   CONNECTION FLOW (Desktop)
   ======================================== */
.de-connection-flow {
    margin: 24px 0;
    text-align: center;
}

.connection-svg {
    width: 200px;
    height: 30px;
    margin-bottom: 8px;
}

.connection-labels {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
    font-size: 12px;
    color: var(--bracket-text-muted);
}

.connection-labels .arrow {
    color: var(--primary, #3b82f6);
    font-weight: 700;
}

/* ========================================
   RESPONSIVE
   ======================================== */
@media (max-width: 768px) {
    .dual-de-header {
        flex-direction: column;
        align-items: stretch;
    }

    .de-phase-toggle {
        width: 100%;
    }

    .de-phase-btn {
        flex: 1;
        min-width: unset;
        padding: 10px 12px;
    }

    .phase-sublabel {
        display: none;
    }

    .dual-de-status {
        justify-content: center;
    }

    .seeded-grid {
        grid-template-columns: 1fr;
    }

    .seeded-subtitle {
        display: none;
    }

    .progress-track {
        overflow-x: auto;
        padding-bottom: 8px;
    }

    .step-label {
        font-size: 10px;
    }

    .second-de-sources {
        flex-direction: column;
        gap: 8px;
    }

    .source-connector {
        display: none;
    }

    .desktop-only {
        display: none;
    }

    .qualifiers-grid {
        grid-template-columns: 1fr;
    }
}

/* ========================================
   PLAYER HIGHLIGHT INTEGRATION
   ======================================== */
.seeded-item.player-highlighted,
.qualifier-item.player-highlighted {
    background: rgba(245, 158, 11, 0.2) !important;
    border-color: #f59e0b !important;
    box-shadow: 0 0 10px rgba(245, 158, 11, 0.3);
}
```

---

## 7. JavaScript Interactions

### 7.1 dual-bracket.js
```javascript
/**
 * Dual DE Bracket Controller
 * Handles tab switching, state management, and player highlighting
 */

class DualDEController {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        if (!this.container) return;

        this.status = this.container.dataset.status;
        this.currentPhase = 'first';

        this.init();
    }

    init() {
        this.bindPhaseToggle();
        this.bindSeededToggle();
        this.restoreState();
        this.initPlayerHighlighting();
    }

    bindPhaseToggle() {
        const phaseBtns = this.container.querySelectorAll('.de-phase-btn');
        const panels = this.container.querySelectorAll('.de-phase-panel');

        phaseBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                if (btn.disabled) return;

                const phase = btn.dataset.phase;

                // Update buttons
                phaseBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');

                // Update panels
                panels.forEach(p => {
                    p.classList.toggle('active', p.dataset.phase === phase);
                });

                this.currentPhase = phase;
                this.saveState();

                // Re-apply highlights if player search is active
                if (window.playerHighlighter) {
                    window.playerHighlighter.refresh();
                }
            });
        });
    }

    bindSeededToggle() {
        const seedDetails = this.container.querySelector('.seeded-players-section');
        if (!seedDetails) return;

        seedDetails.addEventListener('toggle', () => {
            const toggle = seedDetails.querySelector('.seeded-toggle');
            toggle.textContent = seedDetails.open ? '-' : '+';
        });
    }

    saveState() {
        localStorage.setItem('dualDE_phase', this.currentPhase);
    }

    restoreState() {
        // Auto-select phase based on tournament status
        if (this.status === 'second_de_in_progress') {
            this.switchToPhase('second');
        } else {
            const savedPhase = localStorage.getItem('dualDE_phase');
            if (savedPhase && this.canSwitchTo(savedPhase)) {
                this.switchToPhase(savedPhase);
            }
        }
    }

    canSwitchTo(phase) {
        if (phase === 'first') return true;

        const secondBtn = this.container.querySelector('.de-phase-btn[data-phase="second"]');
        return secondBtn && !secondBtn.disabled;
    }

    switchToPhase(phase) {
        const btn = this.container.querySelector(`.de-phase-btn[data-phase="${phase}"]`);
        if (btn && !btn.disabled) {
            btn.click();
        }
    }

    initPlayerHighlighting() {
        // Extend PlayerHighlighter to include seeded and qualifier sections
        if (window.PlayerHighlighter) {
            const originalHighlight = PlayerHighlighter.prototype.highlightInSection;

            PlayerHighlighter.prototype.highlightInSection = function(section, playerName) {
                originalHighlight.call(this, section, playerName);

                // Also highlight in seeded/qualifier sections
                const seededItems = section.querySelectorAll('.seeded-item, .qualifier-item');
                seededItems.forEach(item => {
                    const nameEl = item.querySelector('.seeded-name, .qualifier-name');
                    if (nameEl && nameEl.textContent.trim() === playerName) {
                        item.classList.add('player-highlighted');
                    }
                });
            };
        }
    }

    // Get all player names in current phase (for search autocomplete)
    getPlayersInCurrentPhase() {
        const panel = this.container.querySelector(`.de-phase-panel[data-phase="${this.currentPhase}"]`);
        if (!panel) return [];

        const players = new Set();

        // From bracket matches
        panel.querySelectorAll('.player-name').forEach(el => {
            const name = el.textContent.trim();
            if (name && name !== 'Seed' && name !== 'None') {
                players.add(name);
            }
        });

        // From seeded players
        this.container.querySelectorAll('.seeded-name').forEach(el => {
            players.add(el.textContent.trim());
        });

        // From qualifiers
        this.container.querySelectorAll('.qualifier-name').forEach(el => {
            players.add(el.textContent.trim());
        });

        return Array.from(players);
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.dualDEController = new DualDEController('dual-de-container');
});
```

---

## 8. Integration with Existing Components

### 8.1 Modify event_result.html
```html
<!-- In the DE Tab Section -->
<div id="tab-tournament" class="tab-content">
    {% if event.normalized_bracket %}
        {% if event.normalized_bracket.format == 'dual_de' %}
            {# Dual DE format - use special component #}
            {% set dual_bracket = event.normalized_bracket %}
            {% include 'components/dual-bracket-tabs.html' %}
        {% else %}
            {# Standard single DE format #}
            {% set bracket = event.normalized_bracket %}
            {% include 'components/bracket.html' %}
        {% endif %}
    {% else %}
        <div class="empty">DE 데이터가 없습니다</div>
    {% endif %}
</div>
```

### 8.2 Extend PlayerHighlighter
```javascript
// In player-search.js, extend the highlight function
PlayerHighlighter.prototype.highlightAll = function(playerName) {
    // ... existing code ...

    // Add support for dual DE sections
    this.highlightInSeededSection(playerName);
    this.highlightInQualifiersSection(playerName);
};

PlayerHighlighter.prototype.highlightInSeededSection = function(playerName) {
    document.querySelectorAll('.seeded-item').forEach(item => {
        const nameEl = item.querySelector('.seeded-name');
        if (nameEl && nameEl.textContent.trim() === playerName) {
            item.classList.add('player-highlighted');
            this.highlightedElements.push(item);
        }
    });
};

PlayerHighlighter.prototype.highlightInQualifiersSection = function(playerName) {
    document.querySelectorAll('.qualifier-item').forEach(item => {
        const nameEl = item.querySelector('.qualifier-name');
        if (nameEl && nameEl.textContent.trim() === playerName) {
            item.classList.add('player-highlighted');
            this.highlightedElements.push(item);
        }
    });
};
```

---

## 9. Accessibility Considerations

### ARIA Labels
```html
<div class="de-phase-toggle" role="tablist" aria-label="DE Phase Selection">
    <button role="tab"
            aria-selected="true"
            aria-controls="first-de-panel"
            id="first-de-tab">
        First DE
    </button>
    <button role="tab"
            aria-selected="false"
            aria-controls="second-de-panel"
            id="second-de-tab">
        Second DE
    </button>
</div>

<div id="first-de-panel"
     role="tabpanel"
     aria-labelledby="first-de-tab"
     tabindex="0">
    ...
</div>
```

### Keyboard Navigation
- Tab: Move between interactive elements
- Enter/Space: Activate phase toggle buttons
- Arrow keys: Navigate within bracket matches

### Screen Reader Support
- Clear labels for phase status
- Announce when switching between phases
- Describe player relationships (seeded vs qualifier)

---

## 10. Implementation Checklist

### Phase 1: Core Structure
- [ ] Create `dual-bracket-tabs.html` component
- [ ] Add dual DE CSS to `bracket.css`
- [ ] Create `dual-bracket.js` controller

### Phase 2: Integration
- [ ] Modify `event_result.html` to detect dual DE format
- [ ] Update server to provide dual DE data structure
- [ ] Extend `PlayerHighlighter` for new sections

### Phase 3: Testing
- [ ] Test with mock dual DE data
- [ ] Verify responsive design on mobile/tablet
- [ ] Test player search and highlighting
- [ ] Verify accessibility compliance

### Phase 4: Polish
- [ ] Add loading states and animations
- [ ] Optimize performance for large brackets
- [ ] Add print styles
- [ ] Document component usage

---

## 11. Example Data for Testing

```python
mock_dual_de_data = {
    "format": "dual_de",
    "status": "first_de_in_progress",
    "seeded_players": [
        {"seed": 1, "name": "김국대", "team": "국가대표팀"},
        {"seed": 2, "name": "이선발", "team": "국가대표팀"},
        {"seed": 3, "name": "박시드", "team": "경희대"},
        {"seed": 4, "name": "최강자", "team": "한체대"},
    ],
    "first_de": {
        "rounds": ["64강", "32강", "16강"],
        "starting_round": "64강",
        "participant_count": 48,
        "is_in_progress": True,
        "is_complete": False,
        "bouts_by_round": {...},
        "qualifiers": []
    },
    "second_de": {
        "rounds": ["32강", "16강", "8강", "4강", "결승"],
        "starting_round": "32강",
        "participant_count": 32,
        "is_in_progress": False,
        "is_complete": False,
        "first_de_qualifiers": [],
        "bouts_by_round": {}
    }
}
```

---

## Summary

This design provides:
1. **Clear Visual Separation**: Tab-based navigation between First DE and Second DE
2. **Status Awareness**: Visual indicators showing current tournament phase
3. **Seed Visibility**: Dedicated section explaining why seeded players skip First DE
4. **Connection Clarity**: Visual representation of how First DE feeds into Second DE
5. **Responsive Design**: Mobile-optimized layout with tab navigation
6. **Player Tracking**: Integration with existing highlight system
7. **Accessibility**: ARIA labels, keyboard navigation, screen reader support

The implementation leverages existing components (bracket.html) while adding a wrapper layer for the dual DE logic, maintaining code reusability and consistency.
