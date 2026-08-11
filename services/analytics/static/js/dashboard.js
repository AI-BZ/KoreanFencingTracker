/**
 * FencingMind Analytics - Dashboard auto-refresh
 * Polls job status every 5 seconds for queued/processing jobs.
 */
(function () {
    'use strict';

    // PROCESSING_JOB_IDS is injected by the Jinja2 template
    if (typeof PROCESSING_JOB_IDS === 'undefined' || PROCESSING_JOB_IDS.length === 0) {
        return; // Nothing to poll
    }

    var activeJobs = PROCESSING_JOB_IDS.slice();
    var POLL_INTERVAL = 5000;

    function pollJobs() {
        if (activeJobs.length === 0) return;

        activeJobs.forEach(function (jobId) {
            fetch('/api/analytics/jobs/' + jobId)
                .then(function (resp) { return resp.json(); })
                .then(function (data) {
                    updateJobRow(jobId, data);

                    // Remove from active if terminal state
                    if (data.status === 'completed' || data.status === 'failed') {
                        var idx = activeJobs.indexOf(jobId);
                        if (idx !== -1) activeJobs.splice(idx, 1);
                    }
                })
                .catch(function () {
                    // Ignore fetch errors, retry next cycle
                });
        });

        if (activeJobs.length > 0) {
            setTimeout(pollJobs, POLL_INTERVAL);
        }
    }

    function updateJobRow(jobId, data) {
        var row = document.querySelector('tr[data-job-id="' + jobId + '"]');
        if (!row) return;

        var statusCell = row.querySelector('.job-status');
        if (!statusCell) return;

        var currentStatus = statusCell.getAttribute('data-status');
        if (currentStatus === data.status) return; // No change

        statusCell.setAttribute('data-status', data.status);

        if (data.status === 'completed') {
            statusCell.innerHTML =
                '<span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700">' +
                '<span class="w-1.5 h-1.5 rounded-full bg-green-500"></span>' +
                '완료</span>';

            // Update action column
            var actionCell = row.querySelector('td:last-child');
            if (actionCell) {
                actionCell.innerHTML =
                    '<a href="/report/' + jobId + '" ' +
                    'class="text-sm font-medium text-brand-600 hover:text-brand-800 transition-colors">' +
                    '결과 보기 &rarr;</a>';
            }
        } else if (data.status === 'failed') {
            statusCell.innerHTML =
                '<span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700">' +
                '<span class="w-1.5 h-1.5 rounded-full bg-red-500"></span>' +
                '실패</span>';

            var actionCell = row.querySelector('td:last-child');
            if (actionCell) {
                actionCell.innerHTML =
                    '<span class="text-sm text-red-500">오류 확인</span>';
            }
        } else if (data.status === 'processing') {
            statusCell.innerHTML =
                '<span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800">' +
                '<span class="w-1.5 h-1.5 rounded-full bg-yellow-500 animate-pulse"></span>' +
                '분석 중</span>';
        }
    }

    // Start polling
    setTimeout(pollJobs, POLL_INTERVAL);
})();
