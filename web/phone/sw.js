// Service worker for the installed phone app (registered only over HTTPS).
//
// Network first, cache as fallback: whenever the hub is reachable the page
// always gets the current files (no stale-cache surprises while we iterate),
// and the shell still opens if the network blips. WebSockets never pass
// through a service worker, so the live links are unaffected.
const CACHE = "neuromech-phone-v1";
const SHELL = ["./", "index.html", "style.css", "phone.js", "flicker.js", "video.js", "net.js",
               "demo.js", "manifest.json", "icons/icon-192.png", "icons/apple-touch-icon.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET" || new URL(req.url).origin !== location.origin) return;
  e.respondWith(fetch(req).then((res) => {
    if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
    return res;
  }).catch(() => caches.match(req)));
});
