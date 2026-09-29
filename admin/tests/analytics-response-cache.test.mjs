import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test, { beforeEach } from "node:test";
import ts from "typescript";

function asModule(source) {
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
  });
  return `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`;
}
const cache = asModule(await readFile(new URL("../src/lib/apiCache.ts", import.meta.url), "utf8"));
const source = (await readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8"))
  .replace('from "./apiCache"', `from "${cache}"`);
const api = await import(asModule(source));

beforeEach((t) => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "window", { configurable: true, value: {} });
  api.clearAnalyticsCache();
  t.after(() => {
    api.clearAnalyticsCache();
    if (previous) Object.defineProperty(globalThis, "window", previous);
    else delete globalThis.window;
  });
});

test("filter results are reused for five minutes, then fetched again", async (t) => {
  let now = 0;
  let calls = 0;
  t.mock.method(Date, "now", () => now);
  t.mock.method(globalThis, "fetch", async () => Response.json({ version: ++calls }));
  const load = (search) => api.fetchInstagram({ search });
  assert.deepEqual(await load("video"), { version: 1 });
  assert.deepEqual(await load("graphic"), { version: 2 });
  now = 299_999;
  assert.deepEqual(await load("video"), { version: 1 });
  now = 300_000;
  assert.deepEqual(await load("video"), { version: 3 });
  assert.equal(calls, 3);
});

for (const [name, query] of [
  ["Shopify Explorer", api.queryShopifyExplorer],
  ["Meta Explorer", api.queryMetaExplorer],
]) {
  test(`${name} shares duplicate reads, scopes bodies, and preserves other section caches`, async (t) => {
    let reads = 0;
    let posts = 0;
    t.mock.method(globalThis, "fetch", async (_url, init) => {
      if (init.method === "POST") {
        posts++;
        assert.ok(init.signal, "Read-only POSTs also receive the analytics timeout");
        return Response.json({ body: JSON.parse(init.body) });
      }
      reads++;
      return Response.json({ rows: ["cached Instagram"] });
    });
    const params = { dataset: "ads", dimensions: ["day"], metrics: ["spend"] };
    await api.fetchInstagram();
    assert.deepEqual(await Promise.all([query(params), query(params)]), [{ body: params }, { body: params }]);
    const changed = { ...params, metrics: ["impressions"] };
    assert.deepEqual(await query(changed), { body: changed });
    assert.deepEqual(await query(params), { body: params });
    await api.fetchInstagram();
    assert.equal(posts, 2);
    assert.equal(reads, 1);
  });
}

test("explicit refresh clears results and a successful write invalidates cached analytics", async (t) => {
  let reads = 0;
  let writes = 0;
  t.mock.method(globalThis, "fetch", async (_url, init) => {
    if (init.method === "POST") return Response.json({ run_id: `run-${++writes}` });
    return Response.json({ version: ++reads });
  });
  assert.deepEqual(await api.fetchShopifyAnalytics({}), { version: 1 });
  api.clearAnalyticsCache();
  assert.deepEqual(await api.fetchShopifyAnalytics({}), { version: 2 });
  await api.triggerSilverRefresh();
  assert.deepEqual(await api.fetchShopifyAnalytics({}), { version: 3 });
  await api.triggerSilverRefresh();
  assert.equal(writes, 2, "Writes must never be cached");
});

test("a failed query is not cached and does not evict another section's result", async (t) => {
  let queries = 0;
  let reads = 0;
  t.mock.method(globalThis, "fetch", async (_url, init) => {
    if (init.method !== "POST") return Response.json({ version: ++reads });
    queries++;
    return queries === 1 ? new Response("Unavailable", { status: 503 }) : Response.json({ rows: [] });
  });
  await api.fetchInstagram();
  const params = { dataset: "ads", metrics: ["spend"], dimensions: [] };
  await assert.rejects(api.queryMetaExplorer(params), (error) => error.status === 503);
  assert.deepEqual(await api.queryMetaExplorer(params), { rows: [] });
  assert.deepEqual(await api.fetchInstagram(), { version: 1 });
  assert.equal(queries, 2);
});

test("server-side reads do not reuse a browser's cached response", async (t) => {
  let calls = 0;
  t.mock.method(globalThis, "fetch", async () => Response.json({ version: ++calls }));
  await api.fetchInstagram();
  delete globalThis.window;
  assert.deepEqual(await api.fetchInstagram(), { version: 2 });
  assert.deepEqual(await api.fetchInstagram(), { version: 3 });
});
