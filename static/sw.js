const CACHE_VERSION = 'v1';
const PRECACHE_NAME = `precache-${CACHE_VERSION}`;
const RUNTIME_NAME = `runtime-${CACHE_VERSION}`;
const OFFLINE_URL = '/offline';

const PRECACHE_URLS = [
  '/',
  OFFLINE_URL,
  '/static/manifest.webmanifest',
  '/static/css/style.css',
  '/static/js/theme_switcher.js',
  '/static/js/sw_register.js',
  '/static/img/logo.png',
  '/static/img/icon-192.png',
  '/static/img/icon-512.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(PRECACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => ![PRECACHE_NAME, RUNTIME_NAME].includes(key))
          .map((key) => caches.delete(key))
      )
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;

  if (request.method !== 'GET') {
    return;
  }

  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const responseClone = response.clone();
          caches.open(RUNTIME_NAME).then((cache) => cache.put(request, responseClone));
          return response;
        })
        .catch(() => caches.match(OFFLINE_URL))
    );
    return;
  }

  const url = new URL(request.url);
  if (url.origin === self.location.origin && url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request).then((cachedResponse) =>
        cachedResponse ||
        fetch(request).then((response) => {
          const responseClone = response.clone();
          caches.open(RUNTIME_NAME).then((cache) => cache.put(request, responseClone));
          return response;
        })
      )
    );
    return;
  }

  event.respondWith(
    fetch(request)
      .then((response) => {
        const responseClone = response.clone();
        caches.open(RUNTIME_NAME).then((cache) => cache.put(request, responseClone));
        return response;
      })
      .catch(() => caches.match(request))
  );
});
