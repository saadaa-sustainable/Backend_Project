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
const apiSource = (await readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8"))
  .replace('from "./apiCache"', `from "${cacheModule}"`);
const { ApiError, clearAnalyticsCache, fetchUntestedAssets, fetchCreativeTestingAds, fetchTables } = await import(asModule(apiSource));

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

test("a shared Untested request times out at 90 seconds and a subsequent retry can succeed", async (t) => {
  let calls = 0;
  let requestSignal;
  const response = { media: "video", rows: [], total_rows: 0 };
  t.mock.method(globalThis, "fetch", async (_url, init) => {
    calls += 1;
    if (calls === 1) {
      requestSignal = init.signal;
      return rejectOnAbort(init.signal);
    }
    return Response.json(response);
  });

  const params = { media: "video", match_state: "all" };
  const results = Promise.allSettled([fetchUntestedAssets(params), fetchUntestedAssets(params)]);
  await Promise.resolve();
  assert.equal(calls, 1);
  t.mock.timers.tick(89_999);
  assert.equal(requestSignal.aborted, false);
  t.mock.timers.tick(1);
  assert.equal(requestSignal.aborted, true);
  for (const result of await results) {
    assert.equal(result.status, "rejected");
    assert.ok(result.reason instanceof ApiError);
    assert.equal(result.reason.status, 408);
    assert.match(result.reason.message, /90 seconds/);
  }

  assert.deepEqual(await fetchUntestedAssets(params), response);
  assert.equal(calls, 2);
  assert.deepEqual(await fetchUntestedAssets(params), response);
  assert.equal(calls, 2);
});

test("the timeout also covers a response body that stalls after headers arrive", async (t) => {
  let readingBody = false;
  t.mock.method(globalThis, "fetch", async (_url, init) => ({
    ok: true,
    json: () => {
      readingBody = true;
      return rejectOnAbort(init.signal);
    },
  }));
  const request = fetchUntestedAssets({ media: "influencer", match_state: "all" });
  const rejected = assert.rejects(request, (error) => error instanceof ApiError && error.status === 408);
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(readingBody, true);
  t.mock.timers.tick(90_000);
  await rejected;
});

test("a successful request clears its timeout and retains cached results", async (t) => {
  let requestSignal;
  let calls = 0;
  t.mock.method(globalThis, "fetch", async (_url, init) => {
    calls += 1;
    requestSignal = init.signal;
    return Response.json({ rows: [{ id: "asset-1" }] });
  });
  const params = { media: "graphic", match_state: "matched" };
  assert.deepEqual(await fetchUntestedAssets(params), { rows: [{ id: "asset-1" }] });
  t.mock.timers.tick(90_000);
  assert.equal(requestSignal.aborted, false);
  assert.deepEqual(await fetchUntestedAssets(params), { rows: [{ id: "asset-1" }] });
  assert.equal(calls, 1);
});

test("an HTTP failure keeps its status and permits retry", async (t) => {
  let calls = 0;
  t.mock.method(globalThis, "fetch", async () => {
    calls += 1;
    return calls === 1 ? new Response("temporary failure", { status: 503 }) : Response.json({ rows: [] });
  });
  await assert.rejects(fetchUntestedAssets(), (error) => error instanceof ApiError && error.status === 503);
  assert.deepEqual(await fetchUntestedAssets(), { rows: [] });
  assert.equal(calls, 2);
});

test("other API callers do not acquire the Untested timeout", async (t) => {
  t.mock.method(globalThis, "fetch", async (_url, init) => {
    assert.equal(init.signal, undefined);
    return Response.json({ tables: [] });
  });
  assert.deepEqual(await fetchTables(), { tables: [] });
});

test("the matched-ad popup times out and can retry without limiting its returned ads", async (t) => {
  const ads = Array.from({ length: 125 }, (_, index) => ({ ad_id: String(index) }));
  let calls = 0;
  t.mock.method(globalThis, "fetch", async (url, init) => {
    assert.match(String(url), /\/creative-testing\/GAD-Sep-340\/ads$/);
    calls += 1;
    if (calls === 1) return rejectOnAbort(init.signal);
    return Response.json({ asset_id: "GAD-Sep-340", media: "graphic", ads });
  });
  const request = fetchCreativeTestingAds("GAD-Sep-340", 30_000);
  const rejected = assert.rejects(request, (error) => error instanceof ApiError && error.status === 408);
  await Promise.resolve();
  t.mock.timers.tick(30_000);
  await rejected;
  const response = await fetchCreativeTestingAds("GAD-Sep-340", 30_000);
  assert.deepEqual(response.ads, ads);
  assert.equal(calls, 2);
});

test("Creative Testing callers receive the shared analytics timeout", async (t) => {
  t.mock.method(globalThis, "fetch", async (_url, init) => {
    assert.ok(init.signal);
    return Response.json({ asset_id: "GAD-Sep-340", media: "graphic", ads: [] });
  });
  assert.deepEqual((await fetchCreativeTestingAds("GAD-Sep-340")).ads, []);
});
