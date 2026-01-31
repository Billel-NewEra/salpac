const CACHE_NAME = "salpac-cache-v1";

const STATIC_ASSETS = [
  "/static/manifest.json",
  "/static/css/style.css",
  "/static/icons/salpac_icon_192.png",
  "/static/icons/salpac_icon_512.png"
];

// INSTALL
self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

// ACTIVATE (nettoyage anciens caches)
self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(key => key !== CACHE_NAME)
          .map(key => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

// FETCH
self.addEventListener("fetch", event => {
  // On ignore tout sauf GET
  if (event.request.method !== "GET") return;

  // On évite les endpoints dynamiques / auth
  if (event.request.url.includes("/salpac/api")) return;

  event.respondWith(
    caches.match(event.request).then(cached => {
      return cached || fetch(event.request);
    })
  );
});
