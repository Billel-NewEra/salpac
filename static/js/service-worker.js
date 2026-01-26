const CACHE_NAME = "novoprint-cache-v1";
const urlsToCache = [
  "/novoprint/",
  "/novoprint/static/css/style.css",
  "/novoprint/static/icons/novoprint_icon_192.png",
  "/novoprint/static/icons/novoprint_icon_512.png"
];

// Install SW
self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(urlsToCache);
    })
  );
});

// Fetch from cache
self.addEventListener("fetch", event => {
  event.respondWith(
    caches.match(event.request).then(response => {
      return response || fetch(event.request);
    })
  );
});
