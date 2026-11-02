import test from 'node:test';
import assert from 'node:assert/strict';
import relay from '../sync-relay/worker.mjs';

test('authenticated registration, per-device acknowledgement, close fanout and status', async (t) => {
  const store = new Map();
  const env = { SYNC_API_KEY: 'server-secret', ACK_STORE: {
    async put(key, value) { store.set(key, value); },
    async get(key, format) { const value = store.get(key); return value && format === 'json' ? JSON.parse(value) : value || null; },
  } };
  const request = (path, data, auth) => new Request('https://relay.example' + path, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...(auth ? { Authorization: 'Bearer ' + auth } : {}) }, body: JSON.stringify(data),
  });
  const packet = id => ({ endpoint: 'https://fcm.googleapis.com/fcm/send/' + id,
    body: btoa('ciphertext'), headers: { Authorization: 'signed', TTL: '86400' } });
  const devices = [1, 2].map(n => ({ id: String(n).repeat(64), token: String(n).repeat(43), packet: packet(n) }));
  const data = { id: 'a'.repeat(24), devices };
  assert.equal((await relay.fetch(request('/register', data), env)).status, 401);
  assert.equal((await relay.fetch(request('/register', data, 'server-secret'), env)).status, 204);
  assert.equal((await relay.fetch(request('/ack', { token: 'x'.repeat(43) }), env)).status, 404);
  const before = await relay.fetch(request('/status', { token: devices[1].token }), env);
  assert.equal((await before.json()).read, false);
  const sent = [];
  t.mock.method(globalThis, 'fetch', async (url, options) => { sent.push({ url, options }); return new Response(null, { status: 201 }); });
  assert.equal((await relay.fetch(request('/ack', { token: devices[0].token }), env)).status, 204);
  assert.equal(sent.length, 1);
  assert.equal(sent[0].url, devices[1].packet.endpoint);
  const after = await relay.fetch(request('/status', { token: devices[1].token }), env);
  assert.equal((await after.json()).read, true);
  const bad = structuredClone(data);
  bad.devices[0].packet.endpoint = 'https://evil.example/push';
  assert.equal((await relay.fetch(request('/register', bad, 'server-secret'), env)).status, 400);
});
