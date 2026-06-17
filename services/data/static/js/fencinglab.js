/**
 * FencingLab - 선수 분석 시각화 모듈 v2
 * 실제 데이터 기반 통계 (가상 지표 제거)
 */

const FencingLab = {
    // Chart.js 기본 설정
    chartDefaults: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: {
            legend: { display: false }
        }
    },

    // 테마별 색상 정의
    _darkColors: {
        green: '#00ff88',
        greenDim: 'rgba(0, 255, 136, 0.2)',
        greenGradient: ['rgba(0, 255, 136, 0)', 'rgba(0, 255, 136, 0.3)'],
        blue: '#00d4ff',
        blueDim: 'rgba(0, 212, 255, 0.2)',
        red: '#ff4466',
        redDim: 'rgba(255, 68, 102, 0.2)',
        yellow: '#ffcc00',
        text: '#a0a0b0',
        grid: '#2a2a3a',
        tooltipBg: '#1a1a24',
        tooltipBorder: '#00d4ff',
        tooltipTitle: '#fff',
        pointBorder: '#0a0a0f'
    },
    _lightColors: {
        green: '#00c471',
        greenDim: 'rgba(0, 196, 113, 0.12)',
        greenGradient: ['rgba(0, 196, 113, 0)', 'rgba(0, 196, 113, 0.15)'],
        blue: '#3182f6',
        blueDim: 'rgba(49, 130, 246, 0.12)',
        red: '#f04452',
        redDim: 'rgba(240, 68, 82, 0.12)',
        yellow: '#f59f00',
        text: '#4e5968',
        grid: '#e5e8eb',
        tooltipBg: '#ffffff',
        tooltipBorder: '#e5e8eb',
        tooltipTitle: '#191f28',
        pointBorder: '#ffffff'
    },

    // 현재 테마 감지 후 적절한 색상 반환
    get colors() {
        const theme = document.documentElement.getAttribute('data-theme') || 'dark';
        return theme === 'light' ? this._lightColors : this._darkColors;
    },

    // Translate match result for i18n
    translateResult(result) {
        if (result === '승') {
            return window.i18n?.fencinglab?.wins || '승';
        } else if (result === '패') {
            return window.i18n?.fencinglab?.losses || '패';
        }
        return result;
    },

    // Check if result is a win
    isWin(result) {
        return result === '승' || result === 'W' || result === 'Win' || result === 'Wins';
    },

    /**
     * 승률 추이 라인 차트 생성
     */
    createHistoryChart(canvasId, history) {
        const ctx = document.getElementById(canvasId);
        if (!ctx || !history || history.length === 0) return null;

        const labels = history.map(h => h.month);
        const winRates = history.map(h => h.win_rate);

        return new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    data: winRates,
                    fill: true,
                    backgroundColor: (context) => {
                        const chart = context.chart;
                        const {ctx, chartArea} = chart;
                        const colors = FencingLab.colors;
                        if (!chartArea) return colors.greenDim;

                        const gradient = ctx.createLinearGradient(0, chartArea.bottom, 0, chartArea.top);
                        gradient.addColorStop(0, colors.greenGradient[0]);
                        gradient.addColorStop(1, colors.greenGradient[1]);
                        return gradient;
                    },
                    borderColor: this.colors.green,
                    borderWidth: 2,
                    tension: 0.4,
                    pointBackgroundColor: this.colors.green,
                    pointBorderColor: this.colors.pointBorder,
                    pointBorderWidth: 2,
                    pointRadius: 4,
                    pointHoverRadius: 6
                }]
            },
            options: {
                ...this.chartDefaults,
                scales: {
                    x: {
                        grid: { color: this.colors.grid },
                        ticks: { color: this.colors.text, font: { size: 10 } }
                    },
                    y: {
                        beginAtZero: true,
                        max: 100,
                        grid: { color: this.colors.grid },
                        ticks: {
                            color: this.colors.text,
                            font: { size: 10 },
                            callback: (value) => `${value}%`
                        }
                    }
                },
                plugins: {
                    tooltip: {
                        backgroundColor: this.colors.tooltipBg,
                        borderColor: this.colors.tooltipBorder,
                        borderWidth: 1,
                        titleColor: this.colors.tooltipTitle,
                        bodyColor: this.colors.text,
                        callbacks: {
                            label: (context) => `승률: ${context.raw}%`
                        }
                    }
                }
            }
        });
    },

    /**
     * Detect current language from URL path
     */
    getCurrentLanguage() {
        const path = window.location.pathname;
        if (path.startsWith('/en/')) return 'en';
        if (path.startsWith('/ko/')) return 'ko';
        return 'ko'; // default
    },

    /**
     * 선수 분석 데이터 로드
     */
    async loadPlayerAnalytics(playerName, team = null) {
        const lang = this.getCurrentLanguage();
        let url = `/api/fencinglab/player/${encodeURIComponent(playerName)}`;
        const params = new URLSearchParams();
        if (team) params.append('team', team);
        params.append('lang', lang);
        url += `?${params.toString()}`;

        try {
            const response = await fetch(url);
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to load analytics');
            }
            return await response.json();
        } catch (error) {
            console.error('FencingLab Error:', error);
            throw error;
        }
    },

    /**
     * 데모 데이터 로드
     */
    async loadDemoData() {
        try {
            const response = await fetch('/api/fencinglab/demo');
            if (!response.ok) throw new Error('Failed to load demo');
            return await response.json();
        } catch (error) {
            console.error('Demo load error:', error);
            return null;
        }
    },

    /**
     * 클럽 선수 목록 로드
     */
    async loadClubPlayers(clubName) {
        try {
            const response = await fetch(`/api/fencinglab/clubs/${encodeURIComponent(clubName)}/players`);
            if (!response.ok) throw new Error('Failed to load club players');
            return await response.json();
        } catch (error) {
            console.error('Club players load error:', error);
            return null;
        }
    },

    /**
     * 퍼센트 바 HTML 생성
     */
    _createPercentBar(value, color = 'green') {
        const colorClass = value >= 60 ? 'green' : (value >= 40 ? 'yellow' : 'red');
        return `
            <div class="fl-percent-bar">
                <div class="fl-percent-fill ${colorClass}" style="width: ${value}%"></div>
            </div>
        `;
    },

    /**
     * 선수 분석 카드 HTML 생성 - 실제 데이터 기반 v2
     */
    renderPlayerCard(analytics, containerId) {
        const container = document.getElementById(containerId);
        if (!container) return;

        const getGradeClass = (grade) => {
            if (grade.includes('강심장')) return 'strong';
            if (grade.includes('취약') || grade.includes('부족')) return 'weak';
            return 'average';
        };

        // DE 경기는 승자만 기록되므로 별도 표시
        const deNote = analytics.de_matches > 0 ?
            `<span class="fl-note">(승리 기록만)</span>` : '';

        container.innerHTML = `
            <div class="fl-player-card">
                <div class="fl-player-header">
                    <div class="fl-player-avatar">${analytics.player_name[0]}</div>
                    <div class="fl-player-info">
                        <h3>${analytics.player_name}</h3>
                        <span class="team">${analytics.team}</span>
                    </div>
                </div>

                <!-- Overall Statistics -->
                <div class="fl-section">
                    <h4 class="fl-section-title">${window.i18n?.fencinglab?.overall_stats || '전체 통계'}</h4>
                    <div class="fl-stats-grid">
                        <div class="fl-stat-item">
                            <div class="fl-stat-value">${analytics.total_matches}</div>
                            <div class="fl-stat-label">${window.i18n?.fencinglab?.total_bouts || '총 경기'}</div>
                        </div>
                        <div class="fl-stat-item">
                            <div class="fl-stat-value">${analytics.total_wins}</div>
                            <div class="fl-stat-label">${window.i18n?.fencinglab?.wins || '승'}</div>
                        </div>
                        <div class="fl-stat-item">
                            <div class="fl-stat-value red">${analytics.total_losses}</div>
                            <div class="fl-stat-label">${window.i18n?.fencinglab?.losses || '패'}</div>
                        </div>
                        <div class="fl-stat-item">
                            <div class="fl-stat-value ${analytics.win_rate >= 50 ? 'green' : 'red'}">${analytics.win_rate}%</div>
                            <div class="fl-stat-label">${window.i18n?.fencinglab?.win_rate || '승률'}</div>
                        </div>
                    </div>
                </div>

                <!-- Pool vs DE comparison -->
                <div class="fl-section">
                    <h4 class="fl-section-title">${window.i18n?.fencinglab?.performance_by_type || '경기 유형별 성적'}</h4>
                    <div class="fl-comparison">
                        <div class="fl-comparison-item">
                            <div class="fl-comparison-header">
                                <span class="fl-comparison-label">${window.i18n?.fencinglab?.pool_5pt || 'Pool (5점제)'}</span>
                                <span class="fl-comparison-value">${analytics.pool_wins}${window.i18n?.fencinglab?.wins || '승'} ${analytics.pool_losses}${window.i18n?.fencinglab?.losses || '패'}</span>
                            </div>
                            <div class="fl-comparison-bar">
                                <div class="fl-bar-fill" style="width: ${analytics.pool_win_rate}%; background: ${this.colors.green}"></div>
                            </div>
                            <div class="fl-comparison-rate">${analytics.pool_win_rate}%</div>
                        </div>
                        <div class="fl-comparison-item">
                            <div class="fl-comparison-header">
                                <span class="fl-comparison-label">${window.i18n?.fencinglab?.de_15pt || 'DE (15점제)'} ${deNote ? (window.i18n?.fencinglab?.wins_only || '(승리 기록만)') : ''}</span>
                                <span class="fl-comparison-value">${analytics.de_wins}${window.i18n?.fencinglab?.wins || '승'} ${analytics.de_losses}${window.i18n?.fencinglab?.losses || '패'}</span>
                            </div>
                            <div class="fl-comparison-bar">
                                <div class="fl-bar-fill" style="width: ${analytics.de_win_rate}%; background: ${this.colors.blue}"></div>
                            </div>
                            <div class="fl-comparison-rate">${analytics.de_win_rate}%</div>
                        </div>
                    </div>
                </div>

                <!-- Close match analysis -->
                <div class="fl-insight-card ${getGradeClass(analytics.clutch_grade)}">
                    <div class="fl-insight-title">
                        <span class="fl-badge ${getGradeClass(analytics.clutch_grade)}">${analytics.clutch_grade}</span>
                        ${window.i18n?.fencinglab?.close_match_analysis || '접전 분석 (1점차 경기)'}
                    </div>
                    <div class="fl-insight-stats">
                        <span>${analytics.clutch_wins}${window.i18n?.fencinglab?.wins || '승'} ${analytics.clutch_losses}${window.i18n?.fencinglab?.losses || '패'}</span>
                        <span class="fl-insight-rate">${analytics.clutch_rate}%</span>
                    </div>
                    <div class="fl-insight-text">${analytics.clutch_insight}</div>
                </div>

                <!-- Score difference analysis -->
                <div class="fl-section">
                    <h4 class="fl-section-title">${window.i18n?.fencinglab?.score_diff_analysis || '점수차 분석'}</h4>
                    <div class="fl-stats-grid small">
                        <div class="fl-stat-item">
                            <div class="fl-stat-value green">+${analytics.avg_win_margin}</div>
                            <div class="fl-stat-label">${window.i18n?.fencinglab?.avg_win_margin || '평균 승리 점수차'}</div>
                        </div>
                        <div class="fl-stat-item">
                            <div class="fl-stat-value red">-${analytics.avg_loss_margin}</div>
                            <div class="fl-stat-label">${window.i18n?.fencinglab?.avg_loss_margin || '평균 패배 점수차'}</div>
                        </div>
                        <div class="fl-stat-item">
                            <div class="fl-stat-value">${analytics.blowout_wins}</div>
                            <div class="fl-stat-label">${window.i18n?.fencinglab?.dominant_wins || '압승'}</div>
                        </div>
                        <div class="fl-stat-item">
                            <div class="fl-stat-value">${analytics.blowout_losses}</div>
                            <div class="fl-stat-label">${window.i18n?.fencinglab?.heavy_losses || '완패'}</div>
                        </div>
                    </div>
                </div>

                <!-- Match ending type analysis -->
                <div class="fl-section">
                    <h4 class="fl-section-title">${window.i18n?.fencinglab?.match_ending_type || '경기 종료 유형'}</h4>
                    <div class="fl-comparison">
                        <div class="fl-comparison-item">
                            <div class="fl-comparison-header">
                                <span class="fl-comparison-label">${window.i18n?.fencinglab?.full_score || '풀스코어 (목표점 도달)'}</span>
                                <span class="fl-comparison-value">${analytics.fullscore_wins}${window.i18n?.fencinglab?.wins || '승'} ${analytics.fullscore_matches - analytics.fullscore_wins}${window.i18n?.fencinglab?.losses || '패'}</span>
                            </div>
                            <div class="fl-comparison-bar">
                                <div class="fl-bar-fill" style="width: ${analytics.fullscore_win_rate}%; background: ${this.colors.green}"></div>
                            </div>
                            <div class="fl-comparison-rate">${analytics.fullscore_win_rate}%</div>
                        </div>
                        ${analytics.timeout_matches > 0 ? `
                        <div class="fl-comparison-item">
                            <div class="fl-comparison-header">
                                <span class="fl-comparison-label">${window.i18n?.fencinglab?.timeout || '시간종료 (목표점 미도달)'}</span>
                                <span class="fl-comparison-value">${analytics.timeout_wins}${window.i18n?.fencinglab?.wins || '승'} ${analytics.timeout_matches - analytics.timeout_wins}${window.i18n?.fencinglab?.losses || '패'}</span>
                            </div>
                            <div class="fl-comparison-bar">
                                <div class="fl-bar-fill" style="width: ${analytics.timeout_win_rate}%; background: ${this.colors.yellow}"></div>
                            </div>
                            <div class="fl-comparison-rate">${analytics.timeout_win_rate}%</div>
                        </div>
                        ` : ''}
                    </div>
                    ${analytics.finish_type_insight ? `
                    <p class="fl-text-secondary" style="margin-top: 0.75rem; font-size: 0.8rem;">
                        💡 ${analytics.finish_type_insight}
                    </p>
                    ` : ''}
                </div>
            </div>
        `;
    },

    /**
     * 최근 경기 목록 렌더링 (대회명, 날짜, 링크 포함)
     */
    renderRecentMatches(matches, containerId) {
        const container = document.getElementById(containerId);
        if (!container || !matches || matches.length === 0) return;

        // 날짜 포맷팅
        const formatDate = (dateStr) => {
            if (!dateStr) return '';
            const parts = dateStr.split('-');
            if (parts.length >= 3) {
                return `${parts[1]}.${parts[2]}`;  // MM.DD
            }
            return dateStr;
        };

        container.innerHTML = `
            <h4 class="fl-history-title">${window.i18n?.fencinglab?.recent_matches || '최근 경기 기록'}</h4>
            <div class="fl-matches-list">
                ${matches.map(m => `
                    <div class="fl-match-item">
                        <div class="fl-match-info">
                            ${m.event_cd ? `
                                <a href="/competition/${m.event_cd}" class="fl-match-event-link">
                                    <div class="fl-match-comp">${m.competition}</div>
                                    <div class="fl-match-event">${m.event}</div>
                                </a>
                            ` : `
                                <div class="fl-match-comp">${m.competition}</div>
                                <div class="fl-match-event">${m.event}</div>
                            `}
                            <div class="fl-match-detail">
                                ${m.date ? `<span class="fl-match-date">${formatDate(m.date)}</span>` : ''}
                                <span class="fl-match-round">${m.round}</span>
                                <span class="fl-match-type ${m.type.toLowerCase()}">${m.type}</span>
                                ${m.opponent !== '(상대)' ? `<span class="fl-match-opponent">vs ${m.opponent}</span>` : ''}
                            </div>
                        </div>
                        <div class="fl-match-score ${this.isWin(m.result) ? 'win' : 'loss'}">
                            ${m.score} ${this.translateResult(m.result)}
                        </div>
                    </div>
                `).join('')}
            </div>
        `;
    },

    /**
     * 데모 섹션 렌더링 (랜딩페이지용)
     */
    async renderDemoSection(containerId) {
        const container = document.getElementById(containerId);
        if (!container) return;

        const demo = await this.loadDemoData();
        const fl = window.i18n?.fencinglab || {};
        if (!demo || !demo.demo_players || demo.demo_players.length === 0) {
            container.innerHTML = `<p class="fl-text-secondary">${fl.cannot_load_data || '데모 데이터를 불러올 수 없습니다.'}</p>`;
            return;
        }

        container.innerHTML = `
            <div class="fl-demo-section">
                <div class="fl-demo-title">
                    <h2>Fencing<span>Lab</span></h2>
                    <p>${fl.subtitle || '실제 데이터 기반 선수 분석'}</p>
                    <a href="/fencinglab" class="fl-demo-link">${fl.view_analysis || '선수 분석 보기 →'}</a>
                </div>
                <div class="fl-demo-grid" id="demo-cards"></div>
            </div>
        `;

        const cardsContainer = document.getElementById('demo-cards');
        demo.demo_players.forEach((player, idx) => {
            const cardDiv = document.createElement('div');
            cardDiv.className = 'fl-demo-card';
            cardDiv.innerHTML = `
                <div class="fl-demo-player">
                    <div class="fl-player-avatar">${player.name[0]}</div>
                    <div class="fl-player-info">
                        <h4>${player.name}</h4>
                        <span>${player.team}</span>
                    </div>
                </div>
                <div class="fl-demo-stats">
                    <div class="fl-stat">
                        <span class="value">${player.total_matches}</span>
                        <span class="label">${fl.bouts || '경기'}</span>
                    </div>
                    <div class="fl-stat">
                        <span class="value ${player.win_rate >= 50 ? 'green' : ''}">${player.win_rate}%</span>
                        <span class="label">${fl.win_rate || '승률'}</span>
                    </div>
                    <div class="fl-stat">
                        <span class="value">${player.pool_win_rate}%</span>
                        <span class="label">${fl.pool_rate || 'Pool'}</span>
                    </div>
                </div>
                <div class="fl-demo-badge ${player.clutch_grade.includes('강심장') ? 'strong' : ''}">
                    ${player.clutch_grade}
                </div>
            `;
            cardsContainer.appendChild(cardDiv);
        });
    }
};

// 전역 객체로 노출
window.FencingLab = FencingLab;
