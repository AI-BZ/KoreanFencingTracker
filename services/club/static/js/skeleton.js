/**
 * FencingMind Club - Skeleton Loading Utilities
 * Show/hide skeleton loading placeholders.
 */

(function (root) {
    'use strict';

    /**
     * Show skeleton loading state in a container.
     * @param {string} containerId - ID of the container element
     * @param {object} [options] - Configuration options
     * @param {string} [options.type='list'] - Skeleton type: 'list', 'cards', 'table', 'stat'
     * @param {number} [options.count=3] - Number of skeleton items to show
     */
    function showSkeleton(containerId, options) {
        var container = document.getElementById(containerId);
        if (!container) return;

        var opts = Object.assign({ type: 'list', count: 3 }, options || {});
        var html = '';

        switch (opts.type) {
            case 'cards':
                html = '<div class="skeleton-container" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:1rem;">';
                for (var i = 0; i < opts.count; i++) {
                    html += '<div class="skeleton skeleton-card"></div>';
                }
                html += '</div>';
                break;

            case 'table':
                html = '<div class="skeleton-container">';
                for (var j = 0; j < opts.count; j++) {
                    html += '<div class="skeleton skeleton-table-row">' +
                        '<div class="skeleton skeleton-table-cell"></div>' +
                        '<div class="skeleton skeleton-table-cell"></div>' +
                        '<div class="skeleton skeleton-table-cell"></div>' +
                        '</div>';
                }
                html += '</div>';
                break;

            case 'stat':
                html = '<div class="skeleton-container" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:1rem;">';
                for (var k = 0; k < opts.count; k++) {
                    html += '<div class="skeleton skeleton-stat-card">' +
                        '<div class="skeleton skeleton-text" style="width:60%;height:0.85em;"></div>' +
                        '<div class="skeleton skeleton-stat"></div>' +
                        '<div class="skeleton skeleton-text-sm" style="width:80%;height:0.75em;"></div>' +
                        '</div>';
                }
                html += '</div>';
                break;

            case 'list':
            default:
                html = '<div class="skeleton-container">';
                for (var l = 0; l < opts.count; l++) {
                    html += '<div class="skeleton skeleton-list-item">' +
                        '<div class="skeleton skeleton-avatar-sm"></div>' +
                        '<div style="flex:1;display:flex;flex-direction:column;gap:0.375rem;">' +
                        '<div class="skeleton skeleton-text" style="width:' + (60 + Math.random() * 30) + '%;"></div>' +
                        '<div class="skeleton skeleton-text-sm" style="width:' + (40 + Math.random() * 30) + '%;"></div>' +
                        '</div>' +
                        '</div>';
                }
                html += '</div>';
                break;
        }

        // Store original content for restoration
        container.setAttribute('data-skeleton-original', container.innerHTML);
        container.innerHTML = html;
    }

    /**
     * Hide skeleton loading and restore original content.
     * @param {string} containerId - ID of the container element
     * @param {string} [newContent] - Optional new content to replace skeleton with.
     *                                If not provided, restores original content.
     */
    function hideSkeleton(containerId, newContent) {
        var container = document.getElementById(containerId);
        if (!container) return;

        if (typeof newContent === 'string') {
            container.innerHTML = newContent;
        } else {
            var original = container.getAttribute('data-skeleton-original');
            if (original !== null) {
                container.innerHTML = original;
            }
        }

        container.removeAttribute('data-skeleton-original');
    }

    /**
     * Check if a container is currently showing skeleton.
     * @param {string} containerId - ID of the container element
     * @returns {boolean}
     */
    function isSkeletonActive(containerId) {
        var container = document.getElementById(containerId);
        if (!container) return false;
        return container.hasAttribute('data-skeleton-original');
    }

    // Expose globally
    root.showSkeleton = showSkeleton;
    root.hideSkeleton = hideSkeleton;
    root.isSkeletonActive = isSkeletonActive;

})(window);
