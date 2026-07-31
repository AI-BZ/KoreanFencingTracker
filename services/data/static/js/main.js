// Korean Fencing Tracker - Main JavaScript

// 전역 검색
document.addEventListener('DOMContentLoaded', function() {
    const globalSearch = document.getElementById('global-search');
    if (globalSearch) {
        globalSearch.addEventListener('keypress', function(e) {
            if (e.key === 'Enter' && this.value.trim().length >= 2) {
                window.location.href = '/search?q=' + encodeURIComponent(this.value.trim());
            }
        });
    }
});

// 도메인 코드 도움말 툴팁 (.fm-help)
function fmCloseAllHelp(except) {
    document.querySelectorAll('.fm-help-popup.show').forEach(function(p) {
        if (p === except) return;
        p.classList.remove('show');
        var trigger = p.previousElementSibling;
        if (trigger && trigger.classList.contains('fm-help')) {
            trigger.setAttribute('aria-expanded', 'false');
        }
    });
}

function fmToggleHelp(btn, event) {
    if (event) event.stopPropagation();
    var popup = btn.nextElementSibling;
    if (!popup || !popup.classList.contains('fm-help-popup')) return;
    var isOpen = popup.classList.contains('show');
    fmCloseAllHelp(popup);
    popup.classList.toggle('show', !isOpen);
    btn.setAttribute('aria-expanded', String(!isOpen));
}

document.addEventListener('click', function(e) {
    if (e.target.closest && e.target.closest('.fm-help-popup')) return;
    fmCloseAllHelp();
});

document.addEventListener('keydown', function(e) {
    if (e.key !== 'Escape') return;
    var open = document.querySelector('.fm-help-popup.show');
    if (!open) return;
    fmCloseAllHelp();
    var trigger = open.previousElementSibling;
    if (trigger && trigger.classList.contains('fm-help')) trigger.focus();
});

// 유틸리티 함수
function formatDate(dateStr) {
    if (!dateStr) return '-';
    return dateStr.substring(0, 10);
}

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}
