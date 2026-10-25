const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

function worker() {
  const handlers = {};
  const notifications = [];
  const windows = [];
  const self = {
    addEventListener: (name, handler) => { handlers[name] = handler; },
    registration: {
      scope: 'https://simi9529.github.io/website-monitor/',
      showNotification: async (title, options) => { notifications.push({ title, options }); },
    },
    clients: { openWindow: async (url) => { windows.push(url); } },
  };
  vm.runInNewContext(fs.readFileSync('docs/sw.js', 'utf8'), { self, URL });
  return { handlers, notifications, windows };
}

test('background push shows all links and a multi-link tap opens a private fragment', async () => {
  const { handlers, notifications, windows } = worker();
  let done;
  const links = [{ title: '첫 글', url: 'https://example.com/1' }, { title: '둘째 글', url: 'https://example.com/2' }];
  handlers.push({ data: { json: () => ({ title: '새 글', body: '본문', links, tag: 'stable' }) }, waitUntil: (value) => { done = value; } });
  await done;
  assert.equal(notifications[0].options.data.links.length, 2);
  assert.equal(notifications[0].options.renotify, false);
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
    handlers.notificationclick({ notification: { close() {}, data: { links: [{ url }] } }, waitUntil: (value) => { done = value; } });
    await done;
    assert.equal(windows.at(-1), expected);
  }
});
