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
