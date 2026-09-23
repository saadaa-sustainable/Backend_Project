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

const cacheModule = asModule(await readFile(new URL("../src/lib/apiCache.ts", import.meta.url), "utf8"));
const source = (await readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8"))
  .replace('from "./apiCache"', `from "${cacheModule}"`);
const { ApiError, clearAnalyticsCache, fetchAdsAnalyse, fetchAdsAnalyseRollup, ANALYTICS_REQUEST_TIMEOUT_MS } = await import(asModule(source));

beforeEach((t) => {
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "window", { configurable: true, value: {} });
  clearAnalyticsCache();
  t.mock.timers.enable({ apis: ["setTimeout"] });
  t.after(() => {
    clearAnalyticsCache();
    if (previousWindow) Object.defineProperty(globalThis, "window", previousWindow);
    else delete globalThis.window;
  });
});

function rejectOnAbort(signal) {
  return new Promise((_, reject) => {
    signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
  });
}

const callers = [
  ["ads", () => fetchAdsAnalyse({ limit: 500, account_name: "Main" }), /\/ads-analyse\?account_name=Main&limit=500$/],
  ["ad sets", () => fetchAdsAnalyseRollup({ level: "adset", limit: 500 }), /\/rollup\?level=adset&limit=500$/],
  ["campaigns", () => fetchAdsAnalyseRollup({ level: "campaign", limit: 500 }), /\/rollup\?level=campaign&limit=500$/],
];

for (const [name, load, path] of callers) {
  // From master: a slow response that eventually arrives must render,
  // not be cancelled. The bound exists to expose Retry on a stall, not
  // to cap how long a healthy query may take.
  test(`${name}: a slow but healthy response still renders without retry`, async (t) => {
    let calls = 0;
    let requestSignal;
    const response = { rows: [{ ad_id: "slow-but-healthy" }], total: 1 };
    t.mock.method(globalThis, "fetch", async (_url, init) => {
      calls += 1;
      requestSignal = init.signal;
      await new Promise((resolve) => setTimeout(resolve, 12_000));
      assert.equal(init.signal.aborted, false);
      return Response.json(response);
    });
    const pending = load();
    await Promise.resolve();
    t.mock.timers.tick(10_000);
    assert.equal(requestSignal.aborted, false);
    t.mock.timers.tick(2_000);
    assert.deepEqual(await pending, response);
    assert.equal(calls, 1);
    t.mock.timers.tick(ANALYTICS_REQUEST_TIMEOUT_MS);
    assert.equal(requestSignal.aborted, false);
  });

  test(`${name}: one shared request stops at the analytics bound and manual retry succeeds`, async (t) => {
    let calls = 0;
    let requestSignal;
    const response = { rows: [{ ad_id: "ad-1" }], total: 1 };
    t.mock.method(globalThis, "fetch", async (url, init) => {
      assert.match(String(url), path);
      calls += 1;
      requestSignal = init.signal;
      return calls === 1 ? rejectOnAbort(init.signal) : Response.json(response);
    });
    const outcomes = Promise.allSettled([load(), load()]);
    await Promise.resolve();
    assert.equal(calls, 1);
    // One tick short of the bound, then over it -- follows the constant
    // rather than pinning a number it no longer has.
    t.mock.timers.tick(ANALYTICS_REQUEST_TIMEOUT_MS - 1);
    assert.equal(requestSignal.aborted, false);
    t.mock.timers.tick(1);
    for (const result of await outcomes) {
      assert.equal(result.status, "rejected");
      assert.ok(result.reason instanceof ApiError);
      assert.equal(result.reason.status, 408);
      assert.match(result.reason.message,
        new RegExp(`${Math.round(ANALYTICS_REQUEST_TIMEOUT_MS / 1000)} seconds`));
    }
    // No automatic retries; the next explicit request can recover.
    assert.equal(calls, 1);
    assert.deepEqual(await load(), response);
    assert.equal(calls, 2);
    t.mock.timers.tick(90_000);
    assert.equal(requestSignal.aborted, false);
    assert.deepEqual(await load(), response);
    assert.equal(calls, 2);
  });

  test(`${name}: the deadline also covers a stalled response body`, async (t) => {
    let readingBody = false;
    t.mock.method(globalThis, "fetch", async (_url, init) => ({
      ok: true,
      json: () => {
        readingBody = true;
        return rejectOnAbort(init.signal);
      },
    }));
    const rejected = assert.rejects(load(), (error) => error instanceof ApiError && error.status === 408);
    await Promise.resolve();
    await Promise.resolve();
    assert.equal(readingBody, true);
    t.mock.timers.tick(ANALYTICS_REQUEST_TIMEOUT_MS);
    await rejected;
  });

  test(`${name}: an HTTP failure is not cached and retains its status`, async (t) => {
    let calls = 0;
    t.mock.method(globalThis, "fetch", async () => {
      calls += 1;
      return calls === 1 ? new Response("Backend unavailable", { status: 503 }) : Response.json({ rows: [] });
    });
    await assert.rejects(load(), (error) => error instanceof ApiError && error.status === 503);
    assert.deepEqual(await load(), { rows: [] });
    assert.equal(calls, 2);
  });
}
