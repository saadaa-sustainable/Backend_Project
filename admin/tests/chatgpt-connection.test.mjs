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
const api = await load('../src/lib/chatgpt.ts');
const proxy = await load('../src/app/api/assistant/chatgpt/[action]/route.ts');
const context = action => ({ params: Promise.resolve({ action }) });

test('ChatGPT transport uses same-origin cookies, strips sources, and never sends provider tokens', async () => {
  const original = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, init) => { requests.push({ url, init }); return Response.json({ message: 'Fixture', sources: [] }); };
  try {
    await api.chatgptTransport.send([{ role: 'user', content: 'Spend?', sources: [{ private: 'not conversation content' }] }], 'fixture');
    assert.equal(requests[0].url, '/api/assistant/chatgpt/chat');
    assert.equal(requests[0].init.credentials, 'same-origin');
    assert.equal(requests[0].init.cache, 'no-store');
    assert.deepEqual(JSON.parse(requests[0].init.body), { messages: [{ role: 'user', content: 'Spend?' }], model: 'fixture', mode: 'analytics' });
    assert.equal(requests[0].init.headers.Authorization, undefined);
  } finally { globalThis.fetch = original; }
});

test('API failure is returned once, without a retry or provider fallback', async () => {
  const original = globalThis.fetch;
  let requests = 0;
  globalThis.fetch = async () => { requests++; return Response.json({ detail: 'Connection expired.' }, { status: 401 }); };
  try {
    await assert.rejects(api.chatgptRequest('models'), e => e.status === 401 && e.message === 'Connection expired.');
    assert.equal(requests, 1);
  } finally { globalThis.fetch = original; }
});

test('proxy rejects cross-site mutations and arbitrary actions before upstream access', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = () => assert.fail('Should never reach the backend');
  try {
    const crossSite = new Request('http://localhost:3000/api/assistant/chatgpt/start', { method: 'POST', headers: { Origin: 'https://attacker.example' } });
    assert.equal((await proxy.POST(crossSite, context('start'))).status, 403);
    assert.equal((await proxy.GET(new Request('http://localhost:3000/test'), context('../context'))).status, 404);
  } finally { globalThis.fetch = original; }
});

test('proxy forwards only session cookies, preserves both callback cookies, and never caches', async () => {
  const original = globalThis.fetch;
  let received;
  globalThis.fetch = async (url, init) => {
    received = { url, init };
    const headers = new Headers({ location: 'http://localhost:3000/user/assistant' });
    headers.append('Set-Cookie', 'saadaa_chatgpt_session=random; Path=/api/assistant/chatgpt; HttpOnly; SameSite=Lax');
    headers.append('Set-Cookie', 'saadaa_chatgpt_signin=; Max-Age=0; Path=/api/assistant/chatgpt');
    headers.append('Set-Cookie', 'unrelated=do-not-forward');
    return new Response(null, { status: 303, headers });
  };
  try {
    const request = new Request('http://localhost:3000/api/assistant/chatgpt/callback?code=fixture&state=fixture', {
      headers: { Cookie: 'unrelated=SECRET; saadaa_chatgpt_signin=random', Authorization: 'Bearer MUST_NOT_FORWARD' },
    });
    const result = await proxy.GET(request, context('callback'));
    assert.equal(received.init.headers.get('Cookie'), 'saadaa_chatgpt_signin=random');
    assert.equal(received.init.headers.get('Authorization'), null);
    assert.equal(received.init.redirect, 'manual');
    assert.equal(result.status, 303);
    assert.equal(result.headers.getSetCookie().length, 2);
    assert.equal(result.headers.get('Cache-Control'), 'no-store');
    assert.equal(result.headers.get('Referrer-Policy'), 'no-referrer');
    assert.ok(!JSON.stringify([...result.headers]).includes('SECRET'));
  } finally { globalThis.fetch = original; }
});

test('proxy refuses redirect to an unrelated origin', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response(null, { status: 303, headers: { Location: 'https://attacker.example/' } });
  try {
    const result = await proxy.GET(new Request('http://localhost:3000/api/assistant/chatgpt/callback'), context('callback'));
    assert.equal(result.status, 502);
    assert.equal(result.headers.get('Location'), null);
  } finally { globalThis.fetch = original; }
});
