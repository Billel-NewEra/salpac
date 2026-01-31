const CACHE_NAME = "salpac-cache-v1";

const STATIC_ASSETS = [
  "/static/css/style.css",
  "/static/icons/salpac_icon_192.png",
  "/static/icons/salpac_icon_512.png"
];

// INSTALL
self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(async cache => {
      await Promise.all(
        STATIC_ASSETS.map(async asset => {
          try {
            const res = await fetch(asset);
            if (res.ok) await cache.put(asset, res);
          } catch (_) {}
        })
      );
    })
  );
  self.skipWaiting();
});

// ACTIVATE
self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// FETCH
self.addEventListener("fetch", event => {
  if (!event.request.url.startsWith(self.location.origin + "/salpac")) return;
  if (event.request.method !== "GET") return;

  event.respondWith(
    caches.match(event.request).then(cached => cached || fetch(event.request))
  );
});
