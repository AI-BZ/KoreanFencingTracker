/**
 * FencingMind App - PWA install affordances (Phase 5)
 *
 * Two install paths handled here, dependency-free vanilla JS:
 *
 *   1. iOS Safari guide banner
 *      iOS Safari never fires `beforeinstallprompt`. The user must manually
 *      tap Share → "Add to Home Screen". We show a dismissible guide banner
 *      ONLY when the browser is iOS Safari AND not already running standalone
 *      AND the user has not previously dismissed it. Installing is also what
 *      unlocks web push on iOS 16.4+.
 *
 *   2. Android / desktop install (centralized `beforeinstallprompt`)
 *      We capture the deferred prompt in ONE place and expose it. The home
 *      page button (#installBtn) keeps working by listening to the same
 *      deferred prompt; the site-wide banner also surfaces an install button
 *      when a deferred prompt is available.
 *
 * Already-installed (standalone) state: never show any install affordance.
 *
 * Markup contract (base.html):
 *   #install-banner          — the banner container (hidden by default)
 *   #install-banner-text     — guide / message text element
 *   #install-banner-action   — Android/desktop "install" button (hidden until prompt)
 *   #install-banner-close    — dismiss (×) button
 * Text comes from data-* attributes on #install-banner so i18n stays in the
 * template (t('key','default')).
 */
(function () {
  'use strict';

  var DISMISS_KEY = 'fm_ios_install_dismissed';

  var banner = document.getElementById('install-banner');
  if (!banner) return;

  var textEl = document.getElementById('install-banner-text');
  var actionBtn = document.getElementById('install-banner-action');
  var closeBtn = document.getElementById('install-banner-close');

  // ── i18n text (injected from template via data-*) ─────────────
  var TXT = {
    iosGuide: banner.dataset.txtIosGuide ||
      'Safari 공유 버튼 → "홈 화면에 추가"로 앱을 설치하세요.',
    iosPush: banner.dataset.txtIosPush ||
      '설치하면 푸시 알림을 받을 수 있습니다.',
    installPrompt: banner.dataset.txtInstallPrompt ||
      'FencingMind를 앱으로 설치하면 푸시 알림과 빠른 접근이 가능합니다.',
    installAction: banner.dataset.txtInstallAction || '앱 설치',
  };

  // ── Helpers ───────────────────────────────────────────────────
  function isStandalone() {
    return (
      window.matchMedia('(display-mode: standalone)').matches ||
      window.navigator.standalone === true
    );
  }

  function isIOS() {
    return (
      /iphone|ipad|ipod/i.test(navigator.userAgent) ||
      // iPadOS 13+ reports as Mac; detect a touch-capable "Mac".
      (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
    );
  }

  // iOS Safari (not Chrome/Firefox/in-app webviews on iOS, which can't install).
  function isIOSSafari() {
    if (!isIOS()) return false;
    var ua = navigator.userAgent;
    // Exclude other iOS browsers / in-app webviews that report their own tokens.
    var notSafari = /CriOS|FxiOS|EdgiOS|OPiOS|mercury|GSA/i.test(ua);
    return !notSafari;
  }

  function dismissed() {
    try {
      return window.localStorage.getItem(DISMISS_KEY) === '1';
    } catch (e) {
      return false;
    }
  }

  function persistDismiss() {
    try {
      window.localStorage.setItem(DISMISS_KEY, '1');
    } catch (e) {
      /* localStorage unavailable (private mode etc.) — ignore */
    }
  }

  function showBanner() {
    banner.classList.add('is-visible');
    banner.setAttribute('aria-hidden', 'false');
  }

  function hideBanner() {
    banner.classList.remove('is-visible');
    banner.setAttribute('aria-hidden', 'true');
  }

  // ── Close handler ─────────────────────────────────────────────
  if (closeBtn) {
    closeBtn.addEventListener('click', function () {
      hideBanner();
      persistDismiss();
    });
  }

  // Never prompt when already installed.
  if (isStandalone()) {
    return;
  }

  // ── Path 1: iOS Safari guide banner ───────────────────────────
  if (isIOSSafari() && !dismissed()) {
    if (textEl) {
      textEl.textContent = TXT.iosGuide + ' ' + TXT.iosPush;
    }
    // No actionable install button on iOS (manual Share flow only).
    if (actionBtn) actionBtn.hidden = true;
    showBanner();
    return;
  }

  // ── Path 2: Android / desktop centralized beforeinstallprompt ──
  var deferredPrompt = null;

  // Expose for the home page button to reuse the same captured prompt.
  window.fmGetInstallPrompt = function () {
    return deferredPrompt;
  };
  window.fmClearInstallPrompt = function () {
    deferredPrompt = null;
  };

  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();
    deferredPrompt = e;

    // Let the home page (or anyone) react to availability.
    window.dispatchEvent(new CustomEvent('fm-install-available'));

    // Surface the site-wide banner with an install button, unless dismissed.
    if (!dismissed() && actionBtn) {
      if (textEl) {
        textEl.textContent = TXT.installPrompt;
      }
      actionBtn.hidden = false;
      actionBtn.textContent = TXT.installAction;
      showBanner();
    }
  });

  if (actionBtn) {
    actionBtn.addEventListener('click', function () {
      var prompt = deferredPrompt;
      if (!prompt) return;
      actionBtn.disabled = true;
      prompt.prompt();
      prompt.userChoice
        .then(function () {
          deferredPrompt = null;
          hideBanner();
        })
        .catch(function () {
          actionBtn.disabled = false;
        });
    });
  }

  // If the app gets installed, drop any pending affordance.
  window.addEventListener('appinstalled', function () {
    deferredPrompt = null;
    hideBanner();
  });
})();
