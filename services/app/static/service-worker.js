/**
 * FencingMind App - Service Worker
 *
 * Cache strategy:
 *   API/HTML  → network-first (stale cache prevention)
 *   static/*  → cache-first  (CACHE_NAME version bust on deploy)
 *   external  → network-only (no caching for CDN fonts etc.)
 */

const CACHE_NAME = 'fencingmind-app-v1';

const PRECACHE_ASSETS = [
  '/offline.html',
  '/static/images/icons/icon-192.png',
  '/static/images/icons/icon-512.png',
  '/static/images/logo/FencingMind_logo_long_white.png',
  '/static/images/logo/FencingMind_logo_long.png',
];

// ── Install: precache static assets ──────────────────────────
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_ASSETS))
  );
  // Activate immediately without waiting for existing tabs to close
  self.skipWaiting();
});

// ── Activate: purge old caches ───────────────────────────────
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    )
  );
  // Claim all open clients so the new SW takes effect immediately
  self.clients.claim();
});

// ── Fetch: route by request type ─────────────────────────────
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip non-GET requests (POST, etc.)
  if (request.method !== 'GET') return;

  // Skip cross-origin requests (CDN fonts, external scripts)
  if (url.origin !== self.location.origin) return;

  // Route: static assets → cache-first
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(cacheFirst(request));
    return;
  }

  // Route: API endpoints → network-only (no caching for dynamic data)
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/auth/')) {
    return; // Let browser handle normally
  }

  // Route: HTML pages → network-first with offline fallback
  event.respondWith(networkFirstWithOfflineFallback(request));
});

// ── Strategy: cache-first ────────────────────────────────────
async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;

  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    // Static asset not available — return 404-like response
    return new Response('', { status: 404 });
  }
}

// ── Strategy: network-first with offline fallback ────────────
async function networkFirstWithOfflineFallback(request) {
  try {
    const response = await fetch(request);
    // Cache successful HTML responses for offline fallback
    if (response.ok && request.headers.get('accept')?.includes('text/html')) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    // Network failed — try cache, then offline page
    const cached = await caches.match(request);
    if (cached) return cached;

    // Final fallback: offline page (only for HTML requests)
    if (request.headers.get('accept')?.includes('text/html')) {
      return caches.match('/offline.html');
    }

    return new Response('', { status: 503 });
  }
}

// ── Push notification handler (Phase 4: FCM integration) ─────
self.addEventListener('push', (event) => {
  if (!event.data) return;

  const data = event.data.json();
  const options = {
    body: data.body || '',
    icon: '/static/images/icons/icon-192.png',
    badge: '/static/images/icons/icon-192.png',
    data: { url: data.url || '/' },
    tag: data.tag || 'fencingmind-notification',
  };

  event.waitUntil(
    self.registration.showNotification(data.title || 'FencingMind', options)
  );
});

// ── Notification click: open the target URL ──────────────────
self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  const targetUrl = event.notification.data?.url || '/';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      // Focus existing tab if already open
      for (const client of clients) {
        if (new URL(client.url).pathname === targetUrl && 'focus' in client) {
          return client.focus();
        }
      }
      // Otherwise open a new tab
      return self.clients.openWindow(targetUrl);
    })
  );
});
