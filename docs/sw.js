"use strict";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  event.waitUntil((async () => {
    let payload;
    try { payload = event.data.json(); } catch (_) { payload = {}; }
    const links = Array.isArray(payload.links) ? payload.links.filter((item) => {
      try {
        const url = new URL(item.url);
        return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password;
      } catch (_) { return false; }
    }) : [];
    await self.registration.showNotification(String(payload.title || "새 글 알림"), {
      body: String(payload.body || "새 알림이 도착했습니다.") + (links.length > 1 ? `\n링크 ${links.length}개 · 눌러서 모두 보기` : ""),
      icon: "icon.svg", tag: String(payload.tag || "website-monitor"),
      renotify: false, data: { title: String(payload.title || "새 글 알림"), links },
    });
  })());
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const data = event.notification.data || {};
  const page = new URL("./", self.registration.scope);
  let target = page.href;
  if (Array.isArray(data.links) && data.links.length === 1) {
    try {
      const url = new URL(data.links[0].url);
      if (["http:", "https:"].includes(url.protocol) && !url.username && !url.password) target = url.href;
    } catch (_) { /* Open the settings page for an invalid URL. */ }
  } else if (Array.isArray(data.links) && data.links.length > 1) {
    // Only a local fragment contains protected titles/links; nothing is sent
    // to the public Pages server, and app.js removes it after rendering.
    page.hash = "notification=" + encodeURIComponent(JSON.stringify(data));
    target = page.href;
  }
  event.waitUntil(self.clients.openWindow(target));
});
