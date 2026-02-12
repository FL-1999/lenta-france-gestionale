const CACHE_NAME = 'app-cache-v20260212a';
const PRECACHE_NAME = `${CACHE_NAME}-precache`;
const RUNTIME_NAME = `${CACHE_NAME}-runtime`;
const OFFLINE_URL = '/offline';

const PRECACHE_URLS = [
  OFFLINE_URL,
  '/static/manifest.webmanifest',
  '/static/css/style.css?v=20260212c',
  '/static/js/theme_switcher.js?v=20260212c',
  '/static/js/sw_register.js?v=20260212c',
  '/static/img/logo.png',
  '/static/img/icon-192.png',
  '/static/img/icon-512.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(PRECACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => ![PRECACHE_NAME, RUNTIME_NAME].includes(key))
            .map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

const staleWhileRevalidate = (request) =>
  caches.open(RUNTIME_NAME).then((cache) =>
    cache.match(request).then((cachedResponse) => {
      const fetchPromise = fetch(request)
        .then((response) => {
          if (response && response.ok) {
            cache.put(request, response.clone());
          }
          return response;
        })
        .catch(() => cachedResponse);
      return cachedResponse || fetchPromise;
    })
  );

self.addEventListener('fetch', (event) => {
  const { request } = event;

  if (request.method !== 'GET') {
    return;
  }

  const url = new URL(request.url);

  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => response)
        .catch(() => caches.match(OFFLINE_URL))
    );
    return;
  }

  const isSameOrigin = url.origin === self.location.origin;
  const isCssOrJs =
    isSameOrigin &&
    (url.pathname.startsWith('/static/css/') || url.pathname.startsWith('/static/js/'));

  if (isCssOrJs) {
    event.respondWith(staleWhileRevalidate(request));
    return;
  }

  if (isSameOrigin && url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request).then((cachedResponse) => {
        if (cachedResponse) {
          return cachedResponse;
        }

        return fetch(request).then((response) => {
          if (response && response.ok) {
            caches.open(RUNTIME_NAME).then((cache) => cache.put(request, response.clone()));
          }
          return response;
        });
      })
    );
    return;
  }

  event.respondWith(fetch(request).catch(() => caches.match(request)));
});
