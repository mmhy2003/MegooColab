// MegooColab's service worker (PWA). It keeps the app's static files for fast starts and shows offline.html when a page
// cannot load. It never stores API answers or pages: what you see is always live, and nothing private is kept.
const CACHE = "megoo-v1";
// plain HTML: a Next.js page would need the network to start
const OFFLINE = "/offline.html";
const PRECACHE = [OFFLINE, "/icons/icon-192.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;

  // pages: always from the network; the offline page when there is none
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match(OFFLINE)));
    return;
  }
  // built files carry a hash in their name and never change: keep each the first time it is fetched
  if (url.pathname.startsWith("/_next/static/")) {
    event.respondWith(
      caches.match(request).then(
        (hit) =>
          hit ||
          fetch(request).then((res) => {
            if (res.ok) {
              const copy = res.clone();
              caches.open(CACHE).then((c) => c.put(request, copy));
            }
            return res;
          }),
      ),
    );
  }
});

// web push: a MegooColab notification, shown with its title and text; repeats about the same page replace each other
self.addEventListener("push", (event) => {
  const { title, body, link } = event.data ? event.data.json() : { title: "MegooColab", body: "", link: "/" };
  event.waitUntil(
    self.registration.showNotification(title, { body, icon: "/icons/icon-192.png", tag: link, data: { link } }),
  );
});

// tapping it opens its page: in a MegooColab window already open, or a new one
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const link = (event.notification.data && event.notification.data.link) || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      const open = windows.find((w) => w.url.startsWith(self.location.origin));
      if (open) return open.navigate(self.location.origin + link).then(() => open.focus());
      return self.clients.openWindow(link);
    }),
  );
});
