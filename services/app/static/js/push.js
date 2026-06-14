/**
 * FencingMind App - Web Push subscription (Phase 4)
 *
 * Standard Web Push API (PushManager.subscribe with VAPID applicationServerKey).
 * FCM uses standard web push under the hood, so we use the browser PushManager
 * directly — no Firebase JS SDK required.
 *
 * iOS constraints honored:
 *   - Notification.requestPermission() is called ONLY inside the button click
 *     handler (never on page load).
 *   - iOS only supports web push when installed as a PWA (display-mode:
 *     standalone) on iOS 16.4+. If iOS and not standalone, we disable the
 *     button and show an inline "install first" hint.
 *
 * Markup contract (settings.html):
 *   #push-toggle-btn   — the action button
 *   #push-status       — status/hint text element
 *   <meta name="vapid-public-key" content="...">  — server-injected VAPID key
 *
 * Text is passed in via data-* attributes on #push-toggle-btn so i18n stays in
 * the template (t('key','default')).
 */
(function () {
  'use strict';

  const btn = document.getElementById('push-toggle-btn');
  const statusEl = document.getElementById('push-status');
  if (!btn || !statusEl) return;

  // ── i18n text (injected from template via data-*) ───────────
  const TXT = {
    enable: btn.dataset.txtEnable || '푸시 알림 켜기',
    disable: btn.dataset.txtDisable || '푸시 알림 끄기',
    unsupported: btn.dataset.txtUnsupported || '이 브라우저는 푸시를 지원하지 않습니다',
    notConfigured: btn.dataset.txtNotConfigured || '푸시 미설정',
    iosInstall: btn.dataset.txtIosInstall || '먼저 홈 화면에 추가한 뒤 그 아이콘으로 실행해주세요',
    denied: btn.dataset.txtDenied || '브라우저 설정에서 알림 권한을 허용해주세요',
    enabled: btn.dataset.txtEnabled || '푸시 알림이 켜졌습니다',
    disabled: btn.dataset.txtDisabled || '푸시 알림이 꺼졌습니다',
    working: btn.dataset.txtWorking || '처리 중…',
    failed: btn.dataset.txtFailed || '요청에 실패했습니다',
  };

  const VAPID_PUBLIC_KEY = (function () {
    const meta = document.querySelector('meta[name="vapid-public-key"]');
    return (meta && meta.content || '').trim();
  })();

  // ── Helpers ─────────────────────────────────────────────────
  function setStatus(text, kind) {
    statusEl.textContent = text || '';
    statusEl.className = 'push-status' + (kind ? ' ' + kind : '');
  }

  function disableButton(label) {
    btn.disabled = true;
    btn.textContent = label;
  }

  // Standard VAPID key conversion (base64url → Uint8Array).
  function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    for (let i = 0; i < rawData.length; ++i) {
      outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
  }

  function isIOS() {
    return (
      /iphone|ipad|ipod/i.test(navigator.userAgent) ||
      // iPadOS 13+ reports as Mac; detect touch-capable "Mac"
      (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
    );
  }

  function isStandalone() {
    return (
      window.matchMedia('(display-mode: standalone)').matches ||
      window.navigator.standalone === true
    );
  }

  // ── Feature / environment gating ────────────────────────────
  const supported = 'serviceWorker' in navigator && 'PushManager' in window;

  if (!supported) {
    disableButton(TXT.unsupported);
    setStatus(TXT.unsupported, 'muted');
    return;
  }

  if (!VAPID_PUBLIC_KEY) {
    disableButton(TXT.notConfigured);
    setStatus(TXT.notConfigured, 'muted');
    return;
  }

  if (isIOS() && !isStandalone()) {
    // iOS Safari (not installed) cannot do web push — install banner is Phase 5.
    disableButton(TXT.enable);
    setStatus(TXT.iosInstall, 'muted');
    return;
  }

  // ── Subscription state sync (reflect current state on button) ─
  async function currentSubscription() {
    const reg = await navigator.serviceWorker.ready;
    return reg.pushManager.getSubscription();
  }

  async function refreshButtonState() {
    try {
      const sub = await currentSubscription();
      if (sub && Notification.permission === 'granted') {
        btn.textContent = TXT.disable;
        btn.dataset.state = 'on';
      } else {
        btn.textContent = TXT.enable;
        btn.dataset.state = 'off';
      }
      btn.disabled = false;
    } catch (e) {
      btn.textContent = TXT.enable;
      btn.dataset.state = 'off';
      btn.disabled = false;
    }
  }

  // ── Subscribe ───────────────────────────────────────────────
  async function subscribe() {
    // Permission request MUST be inside this click handler (iOS rule).
    const permission = await Notification.requestPermission();
    if (permission !== 'granted') {
      setStatus(TXT.denied, 'err');
      return;
    }

    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY),
    });

    const json = sub.toJSON();
    const keys = json.keys || {};
    const res = await fetch('/api/notifications/subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({
        endpoint: sub.endpoint,
        p256dh: keys.p256dh,
        auth: keys.auth,
      }),
    });
    if (!res.ok) throw new Error('subscribe failed: ' + res.status);

    setStatus(TXT.enabled, 'ok');
    await refreshButtonState();
  }

  // ── Unsubscribe ─────────────────────────────────────────────
  async function unsubscribe() {
    const sub = await currentSubscription();
    if (sub) {
      const endpoint = sub.endpoint;
      await sub.unsubscribe().catch(() => {});
      await fetch('/api/notifications/subscribe', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ endpoint }),
      }).catch(() => {});
    }
    setStatus(TXT.disabled, 'muted');
    await refreshButtonState();
  }

  // ── Click handler ───────────────────────────────────────────
  btn.addEventListener('click', async function () {
    if (btn.disabled) return;
    const wasOn = btn.dataset.state === 'on';
    btn.disabled = true;
    const prevLabel = btn.textContent;
    btn.textContent = TXT.working;
    try {
      if (wasOn) {
        await unsubscribe();
      } else {
        await subscribe();
      }
    } catch (e) {
      console.warn('push toggle failed:', e);
      setStatus(TXT.failed, 'err');
      btn.textContent = prevLabel;
      btn.disabled = false;
    }
  });

  // Reflect initial state once the SW is ready.
  refreshButtonState();
})();
