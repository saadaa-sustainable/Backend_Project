import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const compile = source => ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const asUrl = source => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const cacheSource = await readFile(new URL('../src/lib/apiCache.ts', import.meta.url), 'utf8');
const apiSource = await readFile(new URL('../src/lib/api.ts', import.meta.url), 'utf8');
const api = await import(asUrl(compile(apiSource).replace('"./apiCache"', JSON.stringify(asUrl(compile(cacheSource))))));

test('chat sends only conversation content and does not invalidate retained analytics', async () => {
  const originalFetch = globalThis.fetch, originalWindow = globalThis.window;
  const requests = [];
  globalThis.window = {};
  globalThis.fetch = async (url, init) => {
    requests.push({ url, init });
    return Response.json(url.includes('/assistant/chat') ? { message: 'Test answer', sources: [] } : { total_spend: 100 });
  };
  try {
    api.clearAnalyticsCache();
    await api.fetchDashboardKpis('2026-01-01', '2026-01-31');
    const messages = [{ role: 'assistant', content: 'Previous answer', sources: [{ label: 'not sent to model' }] },
      { role: 'user', content: 'Show spend' }];
    await api.sendChatMessage(messages, undefined, 'analytics');
    await api.fetchDashboardKpis('2026-01-01', '2026-01-31');
    assert.equal(requests.length, 2);
    const chat = JSON.parse(requests[1].init.body);
    assert.equal(chat.mode, 'analytics');
    assert.deepEqual(chat.messages, messages.map(({ role, content }) => ({ role, content })));
    assert.ok(requests[1].init.signal, 'chat requests must have a timeout signal');
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
    api.clearAnalyticsCache();
  }
});
