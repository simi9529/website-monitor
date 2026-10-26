"use strict";

const $ = (id) => document.getElementById(id);
let registration;
let config;

function decodeKey(value) {
  const raw = atob(value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - value.length % 4) % 4));
  return Uint8Array.from(raw, (char) => char.charCodeAt(0));
}

function showSubscription(subscription) {
  $("subscription").value = JSON.stringify(subscription.toJSON());
  $("setup").hidden = false;
  $("test").hidden = false;
  $("subscribe").textContent = "이 기기의 연결 정보 다시 보기";
  $("status").textContent = "알림 허용 완료. 아래 구독 정보를 GitHub에 등록하면 연결됩니다.";
}

function showReceived() {
  if (!location.hash.startsWith("#notification=")) return;
  try {
    const payload = JSON.parse(decodeURIComponent(location.hash.slice(14)));
    if (!Array.isArray(payload.links) || payload.links.length > 100) return;
    $("received-title").textContent = String(payload.title || "도착한 알림");
    for (const item of payload.links) {
      const url = new URL(item.url);
      if (!["https:", "http:"].includes(url.protocol) || url.username || url.password) continue;
      const li = document.createElement("li");
      const anchor = document.createElement("a");
      anchor.href = url.href;
      anchor.textContent = String(item.title || url.href);
      anchor.target = "_blank";
      anchor.rel = "noopener noreferrer";
      li.append(anchor);
      $("received-links").append(li);
    }
    $("received").hidden = false;
    history.replaceState(null, "", location.pathname);
  } catch (_) {
    $("status").textContent = "알림 링크를 읽지 못했습니다.";
  }
}

async function initialize() {
  showReceived();
  if (!isSecureContext || !("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
    $("status").textContent = "갤럭시 Chrome에서 HTTPS 주소로 접속해 주세요. 앱 안의 브라우저에서는 동작하지 않을 수 있어요.";
    return;
  }
  try {
    const response = await fetch("config.json", { cache: "no-store" });
    if (!response.ok) throw new Error("config");
    config = await response.json();
    registration = await navigator.serviceWorker.register("sw.js");
    await navigator.serviceWorker.ready;
    const subscription = await registration.pushManager.getSubscription();
    const expectedKey = decodeKey(config.publicKey);
    const keyMatches = subscription && subscription.options.applicationServerKey &&
      String(new Uint8Array(subscription.options.applicationServerKey)) === String(expectedKey);
    if (keyMatches && Notification.permission === "granted") showSubscription(subscription);
    else $("status").textContent = Notification.permission === "denied"
      ? "알림이 차단되어 있어요. 크롬 주소창의 사이트 설정에서 알림을 허용해 주세요."
      : "버튼을 누른 뒤 크롬의 알림 허용을 선택하세요.";
    $("subscribe").disabled = false;
  } catch (_) {
    $("status").textContent = "연결 준비에 실패했습니다. 인터넷 연결을 확인하고 새로고침해 주세요.";
  }
}

$("subscribe").addEventListener("click", async () => {
  try {
    // Request permission directly from a user gesture, never on page load.
    const permission = await Notification.requestPermission();
    if (permission !== "granted") {
      $("status").textContent = "알림이 허용되지 않았어요. 크롬의 사이트 설정에서 변경할 수 있어요.";
      return;
    }
    const old = await registration.pushManager.getSubscription();
    const wanted = decodeKey(config.publicKey);
    if (old && old.options.applicationServerKey &&
        String(new Uint8Array(old.options.applicationServerKey)) !== String(wanted)) {
      await old.unsubscribe();
    }
    const subscription = await registration.pushManager.getSubscription() || await registration.pushManager.subscribe({
      userVisibleOnly: true, applicationServerKey: wanted,
    });
    showSubscription(subscription);
  } catch (_) {
    $("status").textContent = "구독하지 못했어요. 크롬 알림 권한과 네트워크를 확인하고 다시 시도해 주세요.";
  }
});

$("copy").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("subscription").value);
    $("status").textContent = "복사했습니다. GitHub의 WEB_PUSH_SUBSCRIPTIONS Secret에 붙여넣으세요.";
  } catch (_) {
    $("subscription").parentElement.open = true;
    $("subscription").select();
    $("status").textContent = "구독 정보를 길게 눌러 직접 복사해 주세요.";
  }
});

$("test").addEventListener("click", async () => {
  try {
    await registration.showNotification("알림 표시 시험", {
      body: "이 기기에서 알림을 표시할 수 있습니다. 실제 서버 연결은 GitHub의 test_push로 확인하세요.",
      tag: "local-test", icon: "icon.svg", data: { links: [{ url: location.href, title: "알림 설정" }] },
      actions: [{ action: "open-link", title: "링크 바로가기" }],
    });
  } catch (_) {
    $("status").textContent = "폰 설정에서 크롬 알림이 허용되어 있는지 확인해 주세요.";
  }
});

initialize();
