const origin = 'https://simi9529.github.io';
const hosts = new Set(['fcm.googleapis.com', 'android.googleapis.com', 'updates.push.services.mozilla.com', 'web.push.apple.com']);
const ttl = { expirationTtl: 172800 };
const hash = async (value) => [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)))].map(x => x.toString(16).padStart(2, '0')).join('');
const reply = (status, data) => new Response(data ? JSON.stringify(data) : null, {
  status, headers: { 'Access-Control-Allow-Origin': origin, 'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization', 'Cache-Control': 'no-store',
    'Content-Type': 'application/json', 'Vary': 'Origin' },
});

function validPacket(packet) {
  try {
    const url = new URL(packet.endpoint);
    return url.protocol === 'https:' && hosts.has(url.hostname) && !url.username && !url.password &&
      (!url.port || url.port === '443') && typeof packet.body === 'string' && packet.body.length < 10000 &&
      packet.headers && typeof packet.headers === 'object';
  } catch { return false; }
}

export default {
  async fetch(request, env) {
    if (request.headers.get('Origin') && request.headers.get('Origin') !== origin) return reply(403);
    if (request.method === 'OPTIONS') return reply(204);
    if (request.method !== 'POST') return reply(405);
    if (Number(request.headers.get('Content-Length') || 0) > 200000) return reply(413);
    let data;
    try {
      const raw = await request.text();
      if (raw.length > 200000) return reply(413);
      data = JSON.parse(raw);
    } catch { return reply(400); }
    if (!data || typeof data !== 'object' || Array.isArray(data)) return reply(400);
    const path = new URL(request.url).pathname;
    if (path === '/register') {
      if (!env.SYNC_API_KEY || request.headers.get('Authorization') !== 'Bearer ' + env.SYNC_API_KEY) return reply(401);
      if (!/^[a-f0-9]{24}$/.test(data.id) || !Array.isArray(data.devices) || !data.devices.length || data.devices.length > 10) return reply(400);
      if (data.devices.some(d => !/^[a-f0-9]{64}$/.test(d.id) || !/^[\w-]{40,100}$/.test(d.token) || !validPacket(d.packet))) return reply(400);
      const packetKey = 'message:' + data.id;
      await env.ACK_STORE.put(packetKey, JSON.stringify(data.devices.map(d => ({ id: d.id, packet: d.packet }))), ttl);
      for (const device of data.devices) {
        await env.ACK_STORE.put('token:' + await hash(device.token), JSON.stringify({ message: data.id, device: device.id }), ttl);
      }
      return reply(204);
    }
    if (!['/ack', '/status'].includes(path) || typeof data.token !== 'string' || !/^[\w-]{40,100}$/.test(data.token)) return reply(400);
    const entry = await env.ACK_STORE.get('token:' + await hash(data.token), 'json');
    if (!entry) return reply(404);
    const readKey = 'read:' + entry.message;
    if (path === '/status') return reply(200, { read: Boolean(await env.ACK_STORE.get(readKey)) });
    await env.ACK_STORE.put(readKey, '1', ttl);
    const devices = await env.ACK_STORE.get('message:' + entry.message, 'json') || [];
    const results = await Promise.allSettled(devices.filter(d => d.id !== entry.device).map(async d => {
      const bytes = Uint8Array.from(atob(d.packet.body), c => c.charCodeAt(0));
      const headers = {};
      for (const [key, value] of Object.entries(d.packet.headers)) {
        if (['authorization', 'crypto-key', 'encryption', 'content-encoding', 'content-type', 'ttl', 'urgency'].includes(key.toLowerCase())) headers[key] = String(value);
      }
      const response = await fetch(d.packet.endpoint, { method: 'POST', body: bytes, headers, redirect: 'error' });
      if (!response.ok && response.status !== 404 && response.status !== 410) throw new Error('push failed');
    }));
    return reply(results.some(r => r.status === 'rejected') ? 503 : 204);
  },
};
