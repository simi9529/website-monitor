const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

function worker(fetchRequest = async () => new Response(null, { status: 204 })) {
  const handlers = {};
  const notifications = [];
  const windows = [];
  const visible = new Map();
  const self = {
    addEventListener: (name, handler) => { handlers[name] = handler; },
    registration: {
      scope: 'https://simi9529.github.io/website-monitor/',
      showNotification: async (title, options) => {
        notifications.push({ title, options });
        visible.set(options.tag, { title, ...options, close: () => visible.delete(options.tag) });
      },
      getNotifications: async ({ tag }) => visible.has(tag) ? [visible.get(tag)] : [],
    },
    clients: { openWindow: async (url) => { windows.push(url); } },
  };
  vm.runInNewContext(fs.readFileSync('docs/sw.js', 'utf8'), { self, URL, atob, Blob, Response, DecompressionStream, fetch: fetchRequest, AbortSignal });
  return { handlers, notifications, windows, visible };
}

test('background push shows all links and a multi-link tap opens a private fragment', async () => {
  const { handlers, notifications, windows } = worker();
  let done;
  const links = [{ title: '첫 글', url: 'https://example.com/1' }, { title: '둘째 글', url: 'https://example.com/2' }];
  handlers.push({ data: { json: () => ({ title: '새 글', body: '본문', links, tag: 'stable' }) }, waitUntil: (value) => { done = value; } });
  await done;
  assert.equal(notifications[0].options.data.links.length, 2);
  assert.equal(notifications[0].options.renotify, false);
  assert.equal(notifications[0].options.actions[0].title, '링크 모두 보기');
  handlers.notificationclick({ notification: { close() {}, data: notifications[0].options.data }, waitUntil: (value) => { done = value; } });
  await done;
  const url = new URL(windows[0]);
  assert.equal(url.origin, 'https://simi9529.github.io');
  assert.equal(url.search, '');
  assert.equal(JSON.parse(decodeURIComponent(url.hash.slice(14))).links.length, 2);
});

test('a single valid link opens directly; unsafe links never open', async () => {
  const { handlers, windows } = worker();
  for (const [url, expected] of [
    ['https://example.com/watch', 'https://example.com/watch'],
    ['javascript:alert(1)', 'https://simi9529.github.io/website-monitor/'],
    ['https://user:secret@example.com', 'https://simi9529.github.io/website-monitor/'],
  ]) {
    let done;
    handlers.notificationclick({ action: 'open-link', notification: { close() {}, data: { links: [{ url }] } }, waitUntil: (value) => { done = value; } });
    await done;
    assert.equal(windows.at(-1), expected);
  }
});

test('a compressed post still produces one notification containing all its links', async () => {
  const { deflateSync } = require('node:zlib');
  const { handlers, notifications } = worker();
  const links = Array.from({ length: 30 }, (_, i) => ({ title: '링크', url: `https://example.com/${i}` }));
  const payload = { title: '글 하나', body: '첨부 링크 30개', links, tag: 'post-1' };
  const encoded = deflateSync(Buffer.from(JSON.stringify(payload))).toString('base64');
  let done;
  handlers.push({ data: { json: () => ({ z: encoded }) }, waitUntil: (value) => { done = value; } });
  await done;
  assert.equal(notifications.length, 1);
  assert.equal(notifications[0].options.data.links.length, 30);
});

test('click acknowledges independently of opening the link; dismiss closes only its own tag', async () => {
  const calls = [];
  const { handlers, windows, visible } = worker(async (url, options) => {
    calls.push({ url, body: JSON.parse(options.body) });
    return new Response(null, { status: 204 });
  });
  const tag = 'a'.repeat(24), other = 'b'.repeat(24);
  let done;
  for (const value of [tag, other]) {
    handlers.push({ data: { json: () => ({ tag: value, title: value, links: [] }) }, waitUntil: p => { done = p; } });
    await done;
  }
  handlers.notificationclick({ notification: { close() {}, data: {
    links: [{ url: 'https://example.com/item' }], sync: { url: 'https://sync.example.com', token: 'secret' },
  } }, waitUntil: p => { done = p; } });
  await done;
  assert.equal(windows[0], 'https://example.com/item');
  assert.equal(calls[0].url, 'https://sync.example.com/ack');
  handlers.push({ data: { json: () => ({ type: 'dismiss', tag }) }, waitUntil: p => { done = p; } });
  await done;
  assert.equal(visible.has(tag), false);
  assert.equal(visible.has(other), true);
});
