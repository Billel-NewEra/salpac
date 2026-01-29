const CACHE_NAME = "salpac-cache-v1";
const urlsToCache = [
  "/salpac/",
  "/salpac/static/css/style.css",
  "/salpac/static/icons/salpac_icon_192.png",
  "/salpac/static/icons/salpac_icon_512.png"
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
