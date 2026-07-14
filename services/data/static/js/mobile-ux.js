/**
 * FencingMind Mobile UX - mobile-ux.js
 * Mobile navigation, onboarding, follow system, bottom sheet
 */
(function() {
    'use strict';

    // ============================================
    // 1. BOTTOM NAV - Active Page Detection
    // ============================================
    function initBottomNav() {
        const nav = document.getElementById('mobileBottomNav');
        if (!nav) return;

        const path = window.location.pathname;
        const items = nav.querySelectorAll('.bnav-item[data-page]');

        items.forEach(function(item) {
            const page = item.dataset.page;
            let isActive = false;

            if (page === 'home' && (path === '/' || /^\/[a-z]{2}\/?$/.test(path))) {
                isActive = true;
            } else if (page === 'rankings' && path.includes('/rankings')) {
                isActive = true;
            } else if (page === 'competitions' && (path.includes('/competitions') || path.includes('/competition/'))) {
                isActive = true;
            } else if (page === 'search' && (path.includes('/search') || path.includes('/player/'))) {
                isActive = true;
            }

            if (isActive) {
                item.classList.add('active');
            }
        });
    }

    // ============================================
    // 2. HAMBURGER MENU
    // ============================================
    window.toggleMobileMenu = function() {
        var overlay = document.getElementById('mobileMenuOverlay');
        var backdrop = document.getElementById('mobileMenuBackdrop');
        if (!overlay || !backdrop) return;

        var isOpen = overlay.classList.contains('open');
        if (isOpen) {
            closeMobileMenu();
        } else {
            overlay.classList.add('open');
            backdrop.classList.add('open');
            document.body.style.overflow = 'hidden';
        }
    };

    window.closeMobileMenu = function() {
        var overlay = document.getElementById('mobileMenuOverlay');
        var backdrop = document.getElementById('mobileMenuBackdrop');
        if (overlay) overlay.classList.remove('open');
        if (backdrop) backdrop.classList.remove('open');
        document.body.style.overflow = '';
    };

    // ============================================
    // 3. ONBOARDING / PREFERENCES (v2)
    // ============================================
    var _pendingWeapon = null;
    var _pendingGender = null;
    var _pendingAgeGroup = null;

    // Preferences manager — single JSON key in localStorage
    var FMPreferences = {
        KEY: 'fm_preferences',
        get: function() {
            try {
                var raw = localStorage.getItem(this.KEY);
                if (raw) {
                    var p = JSON.parse(raw);
                    if (p && p.version === 2) return p;
                }
            } catch (e) {}

            // v1 → v2 migration
            if (localStorage.getItem('fm_onboarded')) {
                var weapon = localStorage.getItem('fm_weapon');
                var migrated = {
                    weapon: (weapon && weapon !== 'all') ? weapon : null,
                    gender: null,
                    age_group: null,
                    onboarded: true,
                    version: 2
                };
                this.save(migrated);
                localStorage.removeItem('fm_onboarded');
                localStorage.removeItem('fm_weapon');
                return migrated;
            }
            return null;
        },
        save: function(prefs) {
            if (!prefs) return;
            prefs.version = 2;
            localStorage.setItem(this.KEY, JSON.stringify(prefs));
        },
        isOnboarded: function() {
            var p = this.get();
            return p && p.onboarded === true;
        }
    };

    window.showOnboardingHook = function() {
        if (FMPreferences.isOnboarded()) return;
        var overlay = document.getElementById('onboarding-overlay');
        if (overlay) {
            setTimeout(function() {
                overlay.classList.add('visible');
            }, 500);
        }
    };

    // Step 1: Select weapon + gender card
    var _pendingWeaponLabel = '';
    var _pendingGenderLabel = '';

    window.selectWeaponGender = function(btn, weapon, gender) {
        _pendingWeapon = weapon;
        _pendingGender = gender;

        // Extract translated labels from the card's visible text
        var wEl = btn.querySelector('.weapon-name');
        var gEl = btn.querySelector('.gender-label');
        _pendingWeaponLabel = wEl ? wEl.textContent.trim() : weapon;
        _pendingGenderLabel = gEl ? gEl.textContent.trim() : gender;

        // Highlight selected card
        var grid = btn.parentElement;
        grid.querySelectorAll('.weapon-gender-card').forEach(function(c) {
            c.classList.remove('selected');
        });
        btn.classList.add('selected');

        // Slide to step 2 after brief delay
        setTimeout(function() {
            showOnboardingStep2();
        }, 300);
    };

    function showOnboardingStep2() {
        var step1 = document.getElementById('onboarding-step1');
        var step2 = document.getElementById('onboarding-step2');
        if (!step1 || !step2) return;

        // Build label showing selected weapon+gender (using translated labels)
        var label = document.getElementById('onboarding-step2-label');
        if (label) {
            label.innerHTML = '&mdash; <span class="onboarding-step2-selected">' + _pendingGenderLabel + ' ' + _pendingWeaponLabel + '</span> &mdash;';
        }

        step1.classList.remove('active');
        step1.classList.add('slide-out');
        step2.classList.add('active', 'slide-in');
    }

    // Step 2: Select age group
    window.selectAgeGroup = function(btn, ageGroup) {
        _pendingAgeGroup = ageGroup;

        var grid = btn.parentElement;
        grid.querySelectorAll('.age-group-choice').forEach(function(c) {
            c.classList.remove('selected');
        });
        btn.classList.add('selected');

        // Enable CTA
        var cta = document.getElementById('onboarding-cta');
        if (cta) cta.disabled = false;
    };

    window.completeOnboarding = function() {
        if (!_pendingWeapon) return;
        FMPreferences.save({
            weapon: _pendingWeapon,
            gender: _pendingGender,
            age_group: _pendingAgeGroup,
            onboarded: true
        });
        var overlay = document.getElementById('onboarding-overlay');
        if (overlay) overlay.classList.remove('visible');

        // Load events immediately based on selected preferences
        if (typeof autoLoadFromPreferences === 'function') {
            autoLoadFromPreferences();
        }

        // Show ranking preview for selected category
        if (typeof fetchAndRenderRankingPreview === 'function') {
            fetchAndRenderRankingPreview(_pendingWeapon, _pendingGender, _pendingAgeGroup);
        }
    };

    window.skipOnboarding = function() {
        FMPreferences.save({
            weapon: null,
            gender: null,
            age_group: null,
            onboarded: true
        });
        var overlay = document.getElementById('onboarding-overlay');
        if (overlay) overlay.classList.remove('visible');
    };

    // Homepage: apply preferences — ranking preview + event auto-load
    function applyPreferencesToHomepage() {
        var prefs = FMPreferences.get();
        if (!prefs) return;

        // Show ranking preview for returning visitors
        if (typeof fetchAndRenderRankingPreview === 'function') {
            fetchAndRenderRankingPreview(prefs.weapon, prefs.gender, prefs.age_group);
        }

        // Auto-load events based on preferences
        if (typeof autoLoadFromPreferences === 'function') {
            autoLoadFromPreferences();
        }
    }

    // Rankings page: preset <select> values
    function applyPreferencesToRankings() {
        var prefs = FMPreferences.get();
        if (!prefs) return;

        var AGE_MAP = { elementary: 'E3', middle_school: 'MS', high_school: 'HS', senior: 'SR' };

        var wSel = document.getElementById('weapon-select');
        var gSel = document.getElementById('gender-select');
        var aSel = document.getElementById('age-group-select');

        if (wSel && prefs.weapon) wSel.value = prefs.weapon;
        if (gSel && prefs.gender) gSel.value = prefs.gender;
        if (aSel && prefs.age_group && AGE_MAP[prefs.age_group]) {
            aSel.value = AGE_MAP[prefs.age_group];
        }

        // Sync bottom sheet selects
        var bsW = document.getElementById('bs-weapon-select');
        var bsG = document.getElementById('bs-gender-select');
        var bsA = document.getElementById('bs-age-select');
        if (bsW && prefs.weapon) bsW.value = prefs.weapon;
        if (bsG && prefs.gender) bsG.value = prefs.gender;
        if (bsA && prefs.age_group && AGE_MAP[prefs.age_group]) bsA.value = AGE_MAP[prefs.age_group];
    }

    // ============================================
    // 4. PLAYER FOLLOW SYSTEM
    // ============================================
    function getFollows() {
        try {
            return JSON.parse(localStorage.getItem('fm_follows') || '[]');
        } catch (e) {
            return [];
        }
    }

    function saveFollows(follows) {
        localStorage.setItem('fm_follows', JSON.stringify(follows));
    }

    window.toggleFollow = function(playerName) {
        // 1. localStorage 즉시 업데이트 (optimistic)
        var follows = getFollows();
        var idx = follows.indexOf(playerName);
        var isAdding = idx < 0;
        if (isAdding) {
            follows.push(playerName);
        } else {
            follows.splice(idx, 1);
        }
        saveFollows(follows);
        updateFollowBtn(playerName);

        // 2. 서버 동기화 (member 이상만 — 실패해도 localStorage는 유지)
        try {
            if (isAdding) {
                fetch('/api/favorites', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({player_name: playerName})
                }).catch(function() {});
            } else {
                fetch('/api/favorites/' + encodeURIComponent(playerName), {
                    method: 'DELETE'
                }).catch(function() {});
            }
        } catch (e) { /* guest면 401, 무시 */ }
    };

    function updateFollowBtn(playerName) {
        var btn = document.getElementById('followBtn');
        if (!btn) return;
        var follows = getFollows();
        var isFollowing = follows.indexOf(playerName) >= 0;
        btn.classList.toggle('following', isFollowing);
        btn.title = isFollowing ? (_t('following') || 'Following') : (_t('follow_player') || 'Follow');
    }

    // Initialize follow button state on player profile
    function initFollowBtn() {
        var btn = document.getElementById('followBtn');
        if (!btn) return;
        var playerName = btn.dataset.player;
        if (playerName) {
            updateFollowBtn(playerName);
        }
    }

    // Import localStorage favorites to server DB (one-time migration)
    function importLocalFavoritesToServer() {
        var follows = getFollows();
        if (!follows.length || localStorage.getItem('fm_follows_imported')) return;

        fetch('/api/favorites/import', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({player_names: follows})
        }).then(function(r) {
            if (r.ok) localStorage.setItem('fm_follows_imported', 'true');
        }).catch(function() {});
    }

    // Render followed players section on home page (guest: chips, member+: dashboard)
    function renderFollowedPlayers() {
        // Guest fallback: localStorage chips
        var section = document.getElementById('followedPlayersSection');
        if (section) {
            var follows = getFollows();
            if (follows.length === 0) {
                section.classList.remove('has-follows');
            } else {
                section.classList.add('has-follows');
                var container = section.querySelector('.followed-players-list');
                if (container) {
                    container.innerHTML = follows.map(function(name) {
                        return '<a href="/player/' + encodeURIComponent(name) + '" class="followed-player-chip">' +
                            '<span class="heart-icon">&#9829;</span>' +
                            '<span>' + name + '</span>' +
                            '</a>';
                    }).join('');
                }
            }
        }

        // Member+ dashboard: fetch from server
        var dashboard = document.getElementById('favoritesDashboard');
        if (dashboard) {
            importLocalFavoritesToServer();
            renderFavoritesDashboard();
        }
    }

    // Favorites Dashboard: render cards with latest competition result
    function renderFavoritesDashboard() {
        var dashboard = document.getElementById('favoritesDashboard');
        if (!dashboard) return;

        fetch('/api/favorites/dashboard')
            .then(function(r) { return r.ok ? r.json() : null; })
            .then(function(data) {
                if (!data || !data.favorites || data.favorites.length === 0) {
                    dashboard.style.display = 'none';
                    return;
                }

                dashboard.style.display = 'block';
                var cardsContainer = document.getElementById('favoritesCards');
                if (!cardsContainer) return;

                var lang = document.documentElement.lang || 'ko';
                var html = '';
                var VISIBLE_COUNT = 5;
                var favorites = data.favorites;

                for (var i = 0; i < favorites.length; i++) {
                    var fav = favorites[i];
                    var hidden = i >= VISIBLE_COUNT ? ' fav-card-hidden' : '';
                    var displayName = (lang === 'ko') ? fav.player_name : (fav.display_name || fav.player_name);
                    var teamDisplay = (lang === 'ko') ? (fav.current_team || '') : (fav.display_team || fav.current_team || '');

                    html += '<div class="favorite-card' + hidden + '">';

                    if (fav.latest_result) {
                        var r = fav.latest_result;
                        var compName = (lang === 'ko') ? r.competition_name : (r.display_competition_name || r.competition_name);
                        var eventName = (lang === 'ko') ? r.event_name : (r.display_event_name || r.event_name);
                        var rankText = r.rank ? (r.rank + (_t('위') || 'th') + '/' + (r.total_participants || '?')) : '-';
                        var poolSeed = r.pool_rank ? ('#' + r.pool_rank + ' ') : '';
                        var poolText = poolSeed + 'Pool ' + (r.pool_wins || 0) + 'W-' + (r.pool_losses || 0) + 'L';
                        var deText = 'DE ' + (r.de_wins || 0) + 'W-' + (r.de_losses || 0) + 'L';
                        var eventUrl = '/competition/' + encodeURIComponent(r.sub_event_cd || r.event_cd || '');

                        html += '<a href="' + eventUrl + '?highlight=' + encodeURIComponent(fav.player_name) + '" class="favorite-card-link">';
                        html += '<div class="favorite-card-header">';
                        html += '<span class="favorite-heart">&#9829;</span> ';
                        html += '<span class="favorite-player-name">' + displayName + '</span>';
                        if (teamDisplay) html += '<span class="favorite-team">' + teamDisplay + '</span>';
                        html += '</div>';
                        html += '<div class="favorite-comp-info">' + compName + ' &middot; ' + eventName + '</div>';
                        html += '<div class="favorite-result-row">';
                        html += '<span>' + poolText + '</span>';
                        html += '<span>' + deText + '</span>';
                        html += '<span class="favorite-rank">' + rankText + '</span>';
                        html += '</div>';
                        html += '</a>';
                    } else {
                        html += '<a href="/player/' + encodeURIComponent(fav.player_name) + '" class="favorite-card-link">';
                        html += '<div class="favorite-card-header">';
                        html += '<span class="favorite-heart">&#9829;</span> ';
                        html += '<span class="favorite-player-name">' + displayName + '</span>';
                        if (teamDisplay) html += '<span class="favorite-team">' + teamDisplay + '</span>';
                        html += '</div>';
                        html += '<div class="favorite-no-result">' + (_t('최근 대회 참가 기록 없음') || 'No recent competition records') + '</div>';
                        html += '</a>';
                    }

                    html += '</div>';
                }

                cardsContainer.innerHTML = html;

                // "더보기" 버튼
                var expandBtn = document.getElementById('favExpandBtn');
                if (expandBtn && favorites.length > VISIBLE_COUNT) {
                    var moreCount = favorites.length - VISIBLE_COUNT;
                    document.getElementById('favMoreCount').textContent = moreCount;
                    expandBtn.style.display = 'inline-block';
                }
            })
            .catch(function() {
                dashboard.style.display = 'none';
            });
    }

    // Toggle expand/collapse for favorites beyond top 5
    window.toggleFavoriteExpand = function() {
        var cards = document.querySelectorAll('.fav-card-hidden');
        var btn = document.getElementById('favExpandBtn');
        if (!cards.length) return;

        var isHidden = cards[0].style.display === 'none' || cards[0].style.display === '';
        for (var i = 0; i < cards.length; i++) {
            cards[i].style.display = isHidden ? 'block' : 'none';
        }
        if (btn) {
            btn.textContent = isHidden
                ? (_t('접기') || 'Show Less')
                : (_t('더보기') || 'Show More') + ' (' + cards.length + ')';
        }
    };

    // Render favorites banner on event result page
    function renderFavoritesEventBanner() {
        var banner = document.getElementById('favoritesEventBanner');
        if (!banner) return;

        var subEventCd = banner.dataset.subEventCd;
        if (!subEventCd) return;

        fetch('/api/favorites/event/' + encodeURIComponent(subEventCd))
            .then(function(r) { return r.ok ? r.json() : null; })
            .then(function(data) {
                if (!data || !data.favorites_in_event || data.favorites_in_event.length === 0) return;

                banner.style.display = 'block';
                var list = document.getElementById('favoritesEventList');
                if (!list) return;

                var lang = document.documentElement.lang || 'ko';
                var html = '';
                data.favorites_in_event.forEach(function(f) {
                    var displayName = (lang === 'ko') ? f.player_name : (f.display_name || f.player_name);
                    var rankText = f.rank ? (f.rank + (_t('위') || 'th') + '/' + (f.total_participants || '?')) : '-';
                    // 풀 번호(pool_number) — 렌더된 풀 DOM 에서 조회 (event_result.html 의 window.findPlayerPoolNumber)
                    var poolNum = (typeof window.findPlayerPoolNumber === 'function') ? window.findPlayerPoolNumber(f.player_name) : null;
                    var poolNumLabel = poolNum ? ('Pool ' + poolNum) : '';
                    var seedLabel = f.pool_rank ? ((_t('풀내') || '풀내') + ' #' + f.pool_rank) : ''; // pool_rank = 풀내 순위
                    // 풀 번호와 풀내 순위를 명확히 구분: "Pool 3 (풀내 #1)"
                    var poolHead = poolNumLabel;
                    if (seedLabel) poolHead = poolNumLabel ? (poolNumLabel + ' (' + seedLabel + ')') : seedLabel;
                    var poolText = (f.pool_wins || 0) + 'W-' + (f.pool_losses || 0) + 'L';
                    var deText = (f.de_wins || 0) + 'W-' + (f.de_losses || 0) + 'L';
                    var statsStr = (poolHead ? poolHead + ' · ' : '') + poolText + ' | DE ' + deText;

                    var nmEsc = f.player_name.replace(/'/g, "\\'");
                    // 클릭 시 해당 풀로 점프 + 하이라이트(event 페이지). 미정의 시 조용히 무시.
                    var onClick = "if(window.jumpToPlayerPool){window.jumpToPlayerPool('" + nmEsc + "')}";
                    html += '<div class="favorite-event-row" onclick="' + onClick + '">';
                    html += '<span class="favorite-heart">&#9829;</span> ';
                    html += '<span class="fev-name">' + displayName + '</span>';
                    html += '<span class="fev-stats">' + statsStr + '</span>';
                    html += '<span class="fev-rank">' + rankText + '</span>';
                    html += '</div>';
                });
                list.innerHTML = html;
            })
            .catch(function() {});
    }

    // ============================================
    // 5. BOTTOM SHEET
    // ============================================
    window.openBottomSheet = function(sheetId) {
        var sheet = document.getElementById(sheetId);
        var backdrop = document.getElementById(sheetId + '-backdrop');
        if (!sheet) return;

        sheet.classList.add('open');
        if (backdrop) backdrop.classList.add('open');
        document.body.style.overflow = 'hidden';

        // Init touch drag
        initBottomSheetDrag(sheet);
    };

    window.closeBottomSheet = function(sheetId) {
        var sheet = document.getElementById(sheetId);
        var backdrop = document.getElementById(sheetId + '-backdrop');
        if (sheet) {
            sheet.classList.remove('open');
            sheet.style.transform = '';
        }
        if (backdrop) backdrop.classList.remove('open');
        document.body.style.overflow = '';
    };

    function initBottomSheetDrag(el) {
        var handle = el.querySelector('.bottom-sheet-handle');
        if (!handle) return;

        var startY = 0;
        var currentY = 0;
        var isDragging = false;

        handle.addEventListener('touchstart', function(e) {
            startY = e.touches[0].clientY;
            isDragging = true;
            el.style.transition = 'none';
        }, { passive: true });

        handle.addEventListener('touchmove', function(e) {
            if (!isDragging) return;
            currentY = e.touches[0].clientY;
            var diff = currentY - startY;
            if (diff > 0) {
                el.style.transform = 'translateY(' + diff + 'px)';
            }
        }, { passive: true });

        handle.addEventListener('touchend', function() {
            isDragging = false;
            el.style.transition = '';
            var diff = currentY - startY;
            if (diff > 100) {
                // Find sheet id from element
                var sheetId = el.id;
                closeBottomSheet(sheetId);
            } else {
                el.style.transform = 'translateY(0)';
            }
            startY = 0;
            currentY = 0;
        }, { passive: true });
    }

    // ============================================
    // 6. RANKINGS FILTER - Bottom Sheet Integration
    // ============================================
    function initRankingsFilterSheet() {
        var trigger = document.getElementById('mobileFilterTrigger');
        if (!trigger) return;

        trigger.addEventListener('click', function() {
            openBottomSheet('rankingsFilterSheet');
        });
    }

    // Sync bottom sheet filter values with desktop filters
    window.applyBottomSheetFilters = function() {
        var bsWeapon = document.getElementById('bs-weapon-select');
        var bsGender = document.getElementById('bs-gender-select');
        var bsAge = document.getElementById('bs-age-select');
        var bsYear = document.getElementById('bs-year-select');

        // Copy values to desktop selects
        var dWeapon = document.getElementById('weapon-select');
        var dGender = document.getElementById('gender-select');
        var dAge = document.getElementById('age-group-select');
        var dYear = document.getElementById('year-select');

        if (bsWeapon && dWeapon) dWeapon.value = bsWeapon.value;
        if (bsGender && dGender) dGender.value = bsGender.value;
        if (bsAge && dAge) {
            dAge.value = bsAge.value;
            // Trigger change event for category show/hide
            dAge.dispatchEvent(new Event('change'));
        }
        if (bsYear && dYear) dYear.value = bsYear.value;

        // Trigger ranking load
        if (dWeapon) dWeapon.dispatchEvent(new Event('change'));

        closeBottomSheet('rankingsFilterSheet');
    };

    // ============================================
    // 7. INITIALIZATION
    // ============================================
    function init() {
        initBottomNav();
        initFollowBtn();
        renderFollowedPlayers();
        renderFavoritesEventBanner();
        initRankingsFilterSheet();

        var path = window.location.pathname;

        // Home page: onboarding + preference application
        if (path === '/' || /^\/[a-z]{2}\/?$/.test(path)) {
            showOnboardingHook();
            // Apply preferences after filters are loaded from API
            document.addEventListener('filtersReady', function() {
                if (FMPreferences.isOnboarded()) {
                    applyPreferencesToHomepage();
                }
            });
        }

        // Rankings page: preset selects before loadRankings()
        if (path.indexOf('/rankings') !== -1) {
            applyPreferencesToRankings();
        }
    }

    // Run on DOMContentLoaded
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
