/**
 * FencingMind Club - Toast Notification System
 *
 * Usage:
 *   showToast('체크인 완료!', 'success');
 *   showToast('오류가 발생했습니다', 'error');
 *   showToast('주의가 필요합니다', 'warning');
 *   showToast('새 공지가 등록되었습니다', 'info');
 *   showToast('제목 있는 알림', 'success', { title: '성공' });
 *   showToast('긴 알림', 'info', { duration: 5000 });
 */

(function (root) {
    'use strict';

    var CONTAINER_ID = 'toast-container';
    var MAX_TOASTS = 5;
    var DEFAULT_DURATION = 3000;

    var ICONS = {
        success: '\u2705',
        error: '\u274C',
        warning: '\u26A0\uFE0F',
        info: '\u2139\uFE0F'
    };

    var activeToasts = [];

    /**
     * Ensure the toast container exists in the DOM.
     */
    function getContainer() {
        var container = document.getElementById(CONTAINER_ID);
        if (!container) {
            container = document.createElement('div');
            container.id = CONTAINER_ID;
            container.className = 'toast-container';
            container.setAttribute('role', 'alert');
            container.setAttribute('aria-live', 'polite');
            container.setAttribute('aria-atomic', 'true');
            document.body.appendChild(container);
        }
        return container;
    }

    /**
     * Show a toast notification.
     * @param {string} message - Toast message text
     * @param {string} [type='info'] - Type: 'success', 'error', 'warning', 'info'
     * @param {object} [options] - Configuration
     * @param {string} [options.title] - Optional title above message
     * @param {number} [options.duration=3000] - Auto-dismiss in ms. Set 0 for persistent.
     * @param {boolean} [options.closable=true] - Show close button
     * @returns {HTMLElement} The toast element
     */
    function showToast(message, type, options) {
        type = type || 'info';
        var opts = Object.assign({
            title: null,
            duration: DEFAULT_DURATION,
            closable: true
        }, options || {});

        var container = getContainer();

        // Limit max toasts
        while (activeToasts.length >= MAX_TOASTS) {
            removeToast(activeToasts[0]);
        }

        // Create toast element
        var toast = document.createElement('div');
        toast.className = 'toast toast-' + type;
        toast.setAttribute('role', 'status');

        // Build inner HTML
        var html = '';
        html += '<span class="toast-icon">' + (ICONS[type] || ICONS.info) + '</span>';
        html += '<div class="toast-body">';
        if (opts.title) {
            html += '<div class="toast-title">' + escapeHtml(opts.title) + '</div>';
        }
        html += '<div class="toast-message">' + escapeHtml(message) + '</div>';
        html += '</div>';

        if (opts.closable) {
            html += '<button class="toast-close" aria-label="\uB2EB\uAE30" type="button">\u00D7</button>';
        }

        if (opts.duration > 0) {
            html += '<div class="toast-progress" style="animation-duration:' + opts.duration + 'ms;"></div>';
        }

        toast.innerHTML = html;

        // Close button handler
        var closeBtn = toast.querySelector('.toast-close');
        if (closeBtn) {
            closeBtn.addEventListener('click', function () {
                removeToast(toast);
            });
        }

        // Swipe to dismiss (touch support)
        setupSwipeDismiss(toast);

        // Add to DOM
        container.appendChild(toast);
        activeToasts.push(toast);

        // Auto dismiss
        if (opts.duration > 0) {
            toast._dismissTimer = setTimeout(function () {
                removeToast(toast);
            }, opts.duration);
        }

        return toast;
    }

    /**
     * Remove a toast with animation.
     * @param {HTMLElement} toast
     */
    function removeToast(toast) {
        if (!toast || !toast.parentNode) return;

        // Clear timer
        if (toast._dismissTimer) {
            clearTimeout(toast._dismissTimer);
            toast._dismissTimer = null;
        }

        // Trigger exit animation
        toast.classList.add('removing');

        var onEnd = function () {
            if (toast.parentNode) {
                toast.parentNode.removeChild(toast);
            }
            var idx = activeToasts.indexOf(toast);
            if (idx > -1) {
                activeToasts.splice(idx, 1);
            }
        };

        toast.addEventListener('animationend', onEnd, { once: true });

        // Fallback if animation doesn't fire
        setTimeout(onEnd, 300);
    }

    /**
     * Remove all active toasts.
     */
    function clearToasts() {
        var toasts = activeToasts.slice();
        toasts.forEach(function (t) {
            removeToast(t);
        });
    }

    /**
     * Enable swipe-to-dismiss on touch devices.
     * @param {HTMLElement} toast
     */
    function setupSwipeDismiss(toast) {
        var startX = 0;
        var startY = 0;
        var currentX = 0;
        var isDragging = false;

        toast.addEventListener('touchstart', function (e) {
            startX = e.touches[0].clientX;
            startY = e.touches[0].clientY;
            currentX = 0;
            isDragging = false;
            toast.style.transition = 'none';
        }, { passive: true });

        toast.addEventListener('touchmove', function (e) {
            var dx = e.touches[0].clientX - startX;
            var dy = e.touches[0].clientY - startY;

            // Only handle horizontal swipe
            if (!isDragging && Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 10) {
                isDragging = true;
            }

            if (isDragging) {
                currentX = dx;
                var opacity = Math.max(0, 1 - Math.abs(currentX) / 200);
                toast.style.transform = 'translateX(' + currentX + 'px)';
                toast.style.opacity = opacity;
            }
        }, { passive: true });

        toast.addEventListener('touchend', function () {
            toast.style.transition = '';

            if (Math.abs(currentX) > 80) {
                // Dismiss
                removeToast(toast);
            } else {
                // Snap back
                toast.style.transform = '';
                toast.style.opacity = '';
            }

            isDragging = false;
            currentX = 0;
        }, { passive: true });
    }

    /**
     * Escape HTML to prevent XSS.
     * @param {string} str
     * @returns {string}
     */
    function escapeHtml(str) {
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }

    // Expose globally
    root.showToast = showToast;
    root.removeToast = removeToast;
    root.clearToasts = clearToasts;

})(window);
