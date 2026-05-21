/**
 * FencingMind Analytics - Report chart initialization
 * Reads REPORT_DATA (injected by Jinja2) and creates Chart.js charts.
 */
(function () {
    'use strict';

    if (typeof REPORT_DATA === 'undefined') return;

    var ACTION_LABELS_KO = {
        'attack': '공격',
        'riposte': '리포스트',
        'counter_attack': '카운터 어택',
        'remise': '르미즈',
        'parry': '파리',
        'lunge': '런지',
        'fleche': '플레쉬',
        'retreat': '후퇴',
        'advance': '전진',
        'unknown': '미분류',
    };

    var ACTION_COLORS = [
        '#6366f1', '#ef4444', '#f59e0b', '#10b981',
        '#8b5cf6', '#ec4899', '#14b8a6', '#f97316',
        '#64748b', '#a3a3a3',
    ];

    // -- Score Timeline Chart --

    var touches = REPORT_DATA.touches || [];
    if (touches.length > 0) {
        var canvas = document.getElementById('score-timeline-chart');
        if (canvas) {
            var labels = ['시작'];
            var leftScores = [0];
            var rightScores = [0];

            touches.forEach(function (t) {
                labels.push('#' + t.touch_number);
                var parts = t.score_after.split('-');
                leftScores.push(parseInt(parts[0]) || 0);
                rightScores.push(parseInt(parts[1]) || 0);
            });

            new Chart(canvas, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [
                        {
                            label: 'Left',
                            data: leftScores,
                            borderColor: '#3b82f6',
                            backgroundColor: 'rgba(59, 130, 246, 0.1)',
                            fill: true,
                            tension: 0.3,
                            pointRadius: 5,
                            pointHoverRadius: 7,
                            borderWidth: 2,
                        },
                        {
                            label: 'Right',
                            data: rightScores,
                            borderColor: '#ef4444',
                            backgroundColor: 'rgba(239, 68, 68, 0.1)',
                            fill: true,
                            tension: 0.3,
                            pointRadius: 5,
                            pointHoverRadius: 7,
                            borderWidth: 2,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: 'top',
                            labels: { usePointStyle: true, padding: 20 },
                        },
                        tooltip: {
                            callbacks: {
                                afterLabel: function (ctx) {
                                    var idx = ctx.dataIndex - 1;
                                    if (idx >= 0 && idx < touches.length) {
                                        var t = touches[idx];
                                        var parts = [];
                                        if (t.match_time) parts.push(t.match_time);
                                        if (t.action_scorer) parts.push(t.action_scorer);
                                        return parts.join(' | ');
                                    }
                                    return '';
                                },
                            },
                        },
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: { stepSize: 1 },
                            title: { display: true, text: '점수' },
                        },
                        x: {
                            title: { display: true, text: '터치' },
                        },
                    },
                },
            });
        }
    }

    // -- Action Distribution Doughnut Charts --

    function createActionChart(canvasId, distribution) {
        var canvas = document.getElementById(canvasId);
        if (!canvas || !distribution || distribution.length === 0) return;

        var labels = [];
        var data = [];
        var bgColors = [];

        distribution.forEach(function (d, i) {
            labels.push(ACTION_LABELS_KO[d.action] || d.action);
            data.push(d.count);
            bgColors.push(ACTION_COLORS[i % ACTION_COLORS.length]);
        });

        new Chart(canvas, {
            type: 'doughnut',
            data: {
                labels: labels,
                datasets: [{
                    data: data,
                    backgroundColor: bgColors,
                    borderWidth: 2,
                    borderColor: '#fff',
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '55%',
                plugins: {
                    legend: {
                        position: 'right',
                        labels: {
                            boxWidth: 12,
                            padding: 12,
                            font: { size: 12 },
                        },
                    },
                    tooltip: {
                        callbacks: {
                            label: function (ctx) {
                                var total = ctx.dataset.data.reduce(function (a, b) { return a + b; }, 0);
                                var pct = total > 0 ? Math.round((ctx.raw / total) * 100) : 0;
                                return ctx.label + ': ' + ctx.raw + '회 (' + pct + '%)';
                            },
                        },
                    },
                },
            },
        });
    }

    if (REPORT_DATA.left_fencer) {
        createActionChart('left-action-chart', REPORT_DATA.left_fencer.action_distribution);
    }
    if (REPORT_DATA.right_fencer) {
        createActionChart('right-action-chart', REPORT_DATA.right_fencer.action_distribution);
    }

    // -- Share Button --

    var shareBtn = document.getElementById('share-btn');
    if (shareBtn) {
        shareBtn.addEventListener('click', function () {
            var url = window.location.href;
            if (navigator.clipboard) {
                navigator.clipboard.writeText(url).then(function () {
                    shareBtn.textContent = '링크 복사됨!';
                    setTimeout(function () {
                        shareBtn.innerHTML =
                            '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">' +
                            '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" ' +
                            'd="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z"/>' +
                            '</svg> 공유 링크 생성';
                    }, 2000);
                });
            } else {
                prompt('아래 링크를 복사하세요:', url);
            }
        });
    }
})();
