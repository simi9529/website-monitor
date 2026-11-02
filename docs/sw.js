"use strict";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

async function syncRequest(sync, path) {
  if (!sync || typeof sync.token !== "string") return null;
  const url = new URL(sync.url);
  if (url.protocol !== "https:" || url.username || url.password) return null;
  return fetch(url.href.replace(/\/$/, "") + path, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token: sync.token }), cache: "no-store",
    signal: AbortSignal.timeout(10000),
  });
}

async function dismiss(tag) {
  if (typeof tag !== "string" || !/^[a-f0-9]{24}$/.test(tag)) return;
  const existing = await self.registration.getNotifications({ tag });
  // Web Push is userVisibleOnly. Silently update the same notification before
  // closing it, rather than relying on a silent push that Chrome may reject.
  await self.registration.showNotification(existing[0]?.title || "다른 기기에서 확인한 알림", {
    tag, silent: true, renotify: false, body: "확인 상태 동기화", data: { synced: true },
  });
  for (const notification of await self.registration.getNotifications({ tag })) notification.close();
}

async function acknowledge(sync) {
  if (!sync) return;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const response = await syncRequest(sync, "/ack");
      if (!response || response.ok || response.status === 404) return;
    } catch (_) { /* Retry without blocking opening the user's link. */ }
  }
}

self.addEventListener("push", (event) => {
  event.waitUntil((async () => {
    let payload;
    try { payload = event.data.json(); } catch (_) { payload = {}; }
    if (payload.z) {
      try {
        const bytes = Uint8Array.from(atob(payload.z), (char) => char.charCodeAt(0));
        const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("deflate"));
        payload = await new Response(stream).json();
      } catch (_) { payload = { title: "알림을 읽지 못했습니다", body: "구독 페이지에서 연결을 확인해 주세요." }; }
    }
    if (payload.type === "dismiss") {
      await dismiss(payload.tag);
      return;
    }
    if (payload.sync) {
      try {
        const response = await syncRequest(payload.sync, "/status");
        if (response?.ok && (await response.json()).read) {
          await dismiss(payload.tag);
          return;
        }
      } catch (_) { /* A relay outage must not hide an actual alert. */ }
    }
    const links = Array.isArray(payload.links) ? payload.links.filter((item) => {
      try {
        const url = new URL(item.url);
        return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password;
      } catch (_) { return false; }
    }) : [];
    await self.registration.showNotification(String(payload.title || "새 글 알림"), {
      body: String(payload.body || "새 알림이 도착했습니다.") + (links.length > 1 ? `\n링크 ${links.length}개 · 눌러서 모두 보기` : ""),
      icon: "icon.svg", tag: String(payload.tag || "website-monitor"),
      actions: [{ action: "open-link", title: links.length > 1 ? "링크 모두 보기" : "링크 바로가기" }],
      renotify: false, data: { title: String(payload.title || "새 글 알림"), links, sync: payload.sync },
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
    page.hash = "notification=" + encodeURIComponent(JSON.stringify({ title: data.title, links: data.links }));
    target = page.href;
  }
  event.waitUntil(Promise.all([self.clients.openWindow(target), acknowledge(data.sync)]));
});
