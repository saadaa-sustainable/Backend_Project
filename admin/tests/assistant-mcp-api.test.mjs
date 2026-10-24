import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

async function load(path) {
  const source = await readFile(new URL(path, import.meta.url), 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022,
  } }).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
}
const api = await load('../src/lib/assistant-api.ts');
const proxy = await load('../src/app/api/assistant/api/[action]/route.ts');
const context = action => ({ params: Promise.resolve({ action }) });

test('Render HTTPS origin works behind an internal HTTP proxy without an explicit override', async t => {
  t.mock.method(globalThis, 'fetch', async (_url, init) => {
    assert.equal(init.headers.get('Origin'), 'https://dashboard.onrender.com');
    return Response.json({ message: 'Disconnected' });
  });
  const previous = { ...process.env };
  try {
    delete process.env.ASSISTANT_API_PUBLIC_ORIGIN;
    process.env.RENDER_EXTERNAL_URL = 'https://dashboard.onrender.com';
    process.env.NODE_ENV = 'production';
    const response = await proxy.POST(new Request('http://localhost:10000/api/assistant/api/disconnect', {
      method: 'POST', headers: { Origin: 'https://dashboard.onrender.com' }, body: '{}',
    }), context('disconnect'));
    assert.equal(response.status, 200);
    assert.ok(response.headers.getSetCookie().some(value => value.includes('; Secure')));
  } finally { process.env = previous; }
});

test('explicit custom origin wins over Render default and tolerates pasted whitespace and slash', async t => {
  t.mock.method(globalThis, 'fetch', async (_url, init) => {
    assert.equal(init.headers.get('Origin'), 'https://dashboard.example');
    return Response.json({ message: 'Answer' });
  });
  const previous = { ...process.env };
  try {
    process.env.ASSISTANT_API_PUBLIC_ORIGIN = ' https://dashboard.example/ ';
    process.env.RENDER_EXTERNAL_URL = 'https://dashboard.onrender.com';
    const response = await proxy.POST(new Request('http://localhost:10000/test', {
      method: 'POST', headers: { Origin: 'https://dashboard.example' }, body: '{}',
    }), context('chat'));
    assert.equal(response.status, 200);
  } finally { process.env = previous; }
});

test('production origin checks reject missing, null and spoofed origins without forwarding', async t => {
  t.mock.method(globalThis, 'fetch', () => assert.fail('Must not reach backend'));
  const previous = { ...process.env };
  try {
    delete process.env.ASSISTANT_API_PUBLIC_ORIGIN;
    process.env.RENDER_EXTERNAL_URL = 'https://dashboard.onrender.com';
    process.env.NODE_ENV = 'production';
    for (const origin of [undefined, 'null', 'https://attacker.example', 'https://dashboard.onrender.com.attacker.example']) {
      const headers = { Host: 'attacker.example', 'X-Forwarded-Host': 'attacker.example', 'X-Forwarded-Proto': 'https' };
      if (origin !== undefined) headers.Origin = origin;
      const response = await proxy.POST(new Request('https://attacker.example/test', {
        method: 'POST', headers, body: '{}',
      }), context('chat'));
      assert.equal(response.status, 403);
    }
  } finally { process.env = previous; }
});

test('missing or malformed production origin reports configuration error without forwarding', async t => {
  t.mock.method(globalThis, 'fetch', () => assert.fail('Must not reach backend'));
  const previous = { ...process.env };
  try {
    delete process.env.RENDER_EXTERNAL_URL;
    process.env.NODE_ENV = 'production';
    for (const origin of [undefined, '', 'https://dashboard.example/user/assistant', 'http://dashboard.example', 'https://user:password@dashboard.example', 'https://dashboard.example?redirect=1']) {
      if (origin === undefined) delete process.env.ASSISTANT_API_PUBLIC_ORIGIN;
      else process.env.ASSISTANT_API_PUBLIC_ORIGIN = origin;
      const response = await proxy.POST(new Request('https://dashboard.example/test', {
        method: 'POST', headers: { Origin: 'https://dashboard.example' }, body: '{}',
      }), context('chat'));
      assert.equal(response.status, 503);
      assert.match((await response.json()).detail, /ASSISTANT_API_PUBLIC_ORIGIN/);
    }
  } finally { process.env = previous; }
});

test('both chat proxies and browsers leave headroom beyond the 240-second backend turn', async () => {
  const chatgpt = await load('../src/lib/chatgpt.ts');
  const chatgptProxy = await load('../src/app/api/assistant/chatgpt/[action]/route.ts');
  const originalFetch = globalThis.fetch;
  const originalTimeout = AbortSignal.timeout;
  const budgets = [];
  AbortSignal.timeout = ms => { budgets.push(ms); return new AbortController().signal; };
  globalThis.fetch = async () => Response.json({ message: 'Fixture', sources: [] });
  try {
    for (const [transport, route] of [[api.assistantAPITransport, proxy], [chatgpt.chatgptTransport, chatgptProxy]]) {
      await transport.send([{ role: 'user', content: 'Spend for last 7 days?' }]);
      await route.POST(new Request('http://localhost:3000/test', {
        method: 'POST', headers: { Origin: 'http://localhost:3000' }, body: '{}',
      }), context('chat'));
    }
    assert.deepEqual(budgets, [260_000, 250_000, 260_000, 250_000]);
  } finally { globalThis.fetch = originalFetch; AbortSignal.timeout = originalTimeout; }
});

test('API chat sends only the conversation and selected model through same-origin cookies', async () => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, init) => { calls.push({ url, init }); return Response.json({ message: 'Fixture', sources: [] }); };
  try {
    await api.assistantAPITransport.send([{ role: 'user', content: 'Spend?', sources: ['not conversation input'] }], 'configured-model');
    assert.equal(calls[0].url, '/api/assistant/api/chat');
    assert.equal(calls[0].init.credentials, 'same-origin');
    assert.equal(calls[0].init.cache, 'no-store');
    assert.deepEqual(JSON.parse(calls[0].init.body), { messages: [{ role: 'user', content: 'Spend?' }], model: 'configured-model', mode: 'analytics' });
    assert.equal(calls[0].init.headers.Authorization, undefined);
  } finally { globalThis.fetch = original; }
});

test('API connection failure stops after one request', async () => {
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => { calls++; throw new Error('fixture network failure'); };
  try {
    await assert.rejects(api.assistantAPITransport.models(), e => e.status === 503 && e.message.includes('without retrying'));
    assert.equal(calls, 1);
  } finally { globalThis.fetch = original; }
});

test('switching Claude to GPT sends the selected model and preserves conversation history', async () => {
  const original = globalThis.fetch;
  const bodies = [];
  globalThis.fetch = async (_url, init) => {
    bodies.push(JSON.parse(init.body));
    return Response.json({ message: 'Answer', sources: [] });
  };
  try {
    const first = [{ role: 'user', content: 'Spend?' }];
    await api.assistantAPITransport.send(first, 'claude-sonnet-5-5');
    const followup = [...first, { role: 'assistant', content: 'Spend was ₹50.' }, { role: 'user', content: 'Explain that' }];
    await api.assistantAPITransport.send(followup, 'configured-gpt');
    assert.equal(bodies[0].model, 'claude-sonnet-5-5');
    assert.equal(bodies[1].model, 'configured-gpt');
    assert.deepEqual(bodies[1].messages, followup);
  } finally { globalThis.fetch = original; }
});

test('API proxy denies cross-origin, unknown routes and oversized bodies without forwarding', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = () => assert.fail('Must not reach backend');
  try {
    const cross = new Request('http://localhost:3000/test', { method: 'POST', headers: { Origin: 'https://attacker.example' } });
    assert.equal((await proxy.POST(cross, context('connect'))).status, 403);
    assert.equal((await proxy.GET(new Request('http://localhost:3000/test'), context('../context'))).status, 404);
    const large = new Request('http://localhost:3000/test', { method: 'POST', headers: { Origin: 'http://localhost:3000' }, body: 'a'.repeat(256001) });
    assert.equal((await proxy.POST(large, context('chat'))).status, 413);
  } finally { globalThis.fetch = original; }
});

test('API proxy forwards only its own cookie and fixed backend path, without bearer or OAuth credentials', async () => {
  const original = globalThis.fetch;
  let received;
  globalThis.fetch = async (url, init) => {
    received = { url, init };
    const headers = new Headers();
    headers.append('Set-Cookie', 'saadaa_assistant_api=signed; Path=/api/assistant/api; HttpOnly');
    headers.append('Set-Cookie', 'other=private');
    return Response.json({ message: 'fixture' }, { headers });
  };
  try {
    const request = new Request('http://localhost:3000/test?target=https://attacker.example', {
      method: 'POST', body: '{}', headers: { Origin: 'http://localhost:3000', Authorization: 'Bearer DO_NOT_FORWARD',
        Cookie: 'saadaa_chatgpt_session=PRIVATE; unrelated=PRIVATE; saadaa_assistant_api=signed' },
    });
    const response = await proxy.POST(request, context('chat'));
    assert.equal(received.url.pathname, '/admin/assistant/api/chat');
    assert.equal(received.url.search, '');
    assert.equal(received.init.headers.get('Cookie'), 'saadaa_assistant_api=signed');
    assert.equal(received.init.headers.get('Authorization'), null);
    assert.equal(response.headers.getSetCookie().length, 2);
    assert.match(received.init.headers.get('X-Assistant-Visitor'), /^[0-9a-f-]{36}$/);
    assert.ok(response.headers.getSetCookie().some(value => value.startsWith('saadaa_assistant_visitor=') && value.includes('HttpOnly')));
    assert.equal(response.headers.get('Cache-Control'), 'no-store');
  } finally { globalThis.fetch = original; }
});

test('API proxy stops on backend failure or redirect', async () => {
  const original = globalThis.fetch;
  let calls = 0;
  try {
    globalThis.fetch = async () => { calls++; throw new Error('offline fixture'); };
    const request = () => new Request('http://localhost:3000/test');
    assert.equal((await proxy.GET(request(), context('status'))).status, 503);
    assert.equal(calls, 1);
    globalThis.fetch = async () => new Response(null, { status: 307, headers: { Location: 'https://attacker.example' } });
    const response = await proxy.GET(request(), context('status'));
    assert.equal(response.status, 502);
    assert.equal(response.headers.get('Location'), null);
  } finally { globalThis.fetch = original; }
});
