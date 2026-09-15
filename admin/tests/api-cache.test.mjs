import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

// Exercise the production TypeScript without relying on Node's optional
// type-stripping support or adding a test framework to the application.
const source = await readFile(new URL("../src/lib/apiCache.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const { RequestCache } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, resolve, reject };
}

test("parallel reads of the same request run the fetcher once and reuse the result", async () => {
  const cache = new RequestCache();
  const response = deferred();
  let calls = 0;
  const fetcher = () => {
    calls += 1;
    return response.promise;
  };

  const first = cache.get("/kpis?window=30d", fetcher);
  const second = cache.get("/kpis?window=30d", fetcher);
  await Promise.resolve();
  assert.equal(calls, 1);
  response.resolve({ orders: 12 });
  assert.deepEqual(await Promise.all([first, second]), [{ orders: 12 }, { orders: 12 }]);
  assert.deepEqual(await cache.get("/kpis?window=30d", fetcher), { orders: 12 });
  assert.equal(calls, 1);
});

test("requests with different filters retain independent values", async () => {
  const cache = new RequestCache();
  let calls = 0;
  const fetcher = (orders) => async () => {
    calls += 1;
    return { orders };
  };

  assert.deepEqual(await Promise.all([
    cache.get("/kpis?window=7d", fetcher(7)),
    cache.get("/kpis?window=30d", fetcher(30)),
  ]), [{ orders: 7 }, { orders: 30 }]);
  assert.deepEqual(await cache.get("/kpis?window=7d", fetcher(-1)), { orders: 7 });
  assert.deepEqual(await cache.get("/kpis?window=30d", fetcher(-1)), { orders: 30 });
  assert.equal(calls, 2);
});

test("a response expires at its TTL boundary", async () => {
  let now = 0;
  let calls = 0;
  const cache = new RequestCache(64, () => now);
  const fetcher = async () => ++calls;

  assert.equal(await cache.get("kpis", fetcher, 100), 1);
  now = 99;
  assert.equal(await cache.get("kpis", fetcher, 100), 1);
  now = 100;
  assert.equal(await cache.get("kpis", fetcher, 100), 2);
  assert.equal(calls, 2);
});

test("TTL starts when the response completes", async () => {
  let now = 0;
  const cache = new RequestCache(64, () => now);
  const response = deferred();
  const pending = cache.get("slow-query", () => response.promise, 100);
  await Promise.resolve();
  now = 500;
  response.resolve("fresh");
  assert.equal(await pending, "fresh");
  now = 599;
  assert.equal(await cache.get("slow-query", async () => "replacement", 100), "fresh");
  now = 600;
  assert.equal(await cache.get("slow-query", async () => "replacement", 100), "replacement");
});

test("a rejected shared request is removed so the next request can retry", async () => {
  const cache = new RequestCache();
  const response = deferred();
  const failure = new Error("temporary database failure");
  let calls = 0;
  const fetcher = () => {
    calls += 1;
    return response.promise;
  };
  const results = Promise.allSettled([
    cache.get("kpis", fetcher),
    cache.get("kpis", fetcher),
  ]);
  await Promise.resolve();
  response.reject(failure);
  assert.deepEqual(await results, [
    { status: "rejected", reason: failure },
    { status: "rejected", reason: failure },
  ]);
  assert.equal(calls, 1);
  assert.equal(await cache.get("kpis", async () => "recovered"), "recovered");
});

test("a synchronous fetcher failure also permits retry", async () => {
  const cache = new RequestCache();
  await assert.rejects(cache.get("kpis", () => {
    throw new Error("invalid response");
  }), /invalid response/);
  assert.equal(await cache.get("kpis", async () => "recovered"), "recovered");
});

test("an invalidated pending response cannot repopulate the cache", async () => {
  const cache = new RequestCache();
  const obsolete = deferred();
  const first = cache.get("kpis", () => obsolete.promise);
  await Promise.resolve();
  cache.clear();
  obsolete.resolve("obsolete");
  assert.equal(await first, "obsolete");

  let calls = 0;
  assert.equal(await cache.get("kpis", async () => {
    calls += 1;
    return "fresh";
  }), "fresh");
  assert.equal(calls, 1);
});

test("an obsolete response cannot remove the replacement pending request", async () => {
  const cache = new RequestCache();
  const obsolete = deferred();
  const replacement = deferred();
  const first = cache.get("kpis", () => obsolete.promise);
  await Promise.resolve();
  cache.clear();

  let calls = 0;
  const replacementFetcher = () => {
    calls += 1;
    return replacement.promise;
  };
  const second = cache.get("kpis", replacementFetcher);
  await Promise.resolve();
  obsolete.resolve("obsolete");
  assert.equal(await first, "obsolete");

  const joined = cache.get("kpis", replacementFetcher);
  await Promise.resolve();
  assert.equal(calls, 1);
  replacement.resolve("fresh");
  assert.deepEqual(await Promise.all([second, joined]), ["fresh", "fresh"]);
  assert.equal(await cache.get("kpis", replacementFetcher), "fresh");
  assert.equal(calls, 1);
});

test("the cache evicts the least recently used entry at its size limit", async () => {
  const cache = new RequestCache(2);
  const calls = { a: 0, b: 0, c: 0 };
  const get = (key) => cache.get(key, async () => `${key}:${++calls[key]}`);

  assert.equal(await get("a"), "a:1");
  assert.equal(await get("b"), "b:1");
  assert.equal(await get("a"), "a:1");
  assert.equal(await get("c"), "c:1");
  assert.equal(await get("a"), "a:1");
  assert.equal(await get("c"), "c:1");
  assert.equal(await get("b"), "b:2");
  assert.deepEqual(calls, { a: 1, b: 2, c: 1 });
});
