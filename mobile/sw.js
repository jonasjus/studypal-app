// Keeps StudyPal working offline once it has opened. The app's own files are fetched fresh when there's a
// connection (so updates arrive) and taken from the cache when there isn't; Pyodide's files never change
// for a version, so they come from the cache first.

const CACHE = "studypal-v1";  // a new name would make everyone download Python again

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil((async () => {
  for (const key of await caches.keys()) if (key !== CACHE) await caches.delete(key);
  await self.clients.claim();
})()));

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.hostname === "cdn.jsdelivr.net") {
    e.respondWith(caches.open(CACHE).then(async (cache) => {
      const hit = await cache.match(req);
      if (hit) return hit;
      const res = await fetch(req);
      if (res.ok) cache.put(req, res.clone());
      return res;
    }));
  } else if (url.origin === location.origin) {
    // "no-cache" asks GitHub whether the file changed (a quick 304 when it didn't), rather than taking the
    // browser's copy, which GitHub Pages lets it keep for 10 minutes after an update.
    e.respondWith(fetch(req, { cache: "no-cache" }).then((res) => {
      if (res.ok) caches.open(CACHE).then((cache) => cache.put(req, res.clone()));
      return res;
    }).catch(() => caches.match(req, { ignoreSearch: true })));
  }
});
