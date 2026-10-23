import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
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
const { fetchCpisUtm, fetchCpisDailySeries, clearAnalyticsCache } = await import(asModule(source));

test("CPIS mode is sent to table and chart, with separate browser cache entries", async (t) => {
  const prev = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "window", { configurable: true, value: {} });
  clearAnalyticsCache();
  t.after(() => {
    clearAnalyticsCache();
    if (prev) Object.defineProperty(globalThis, "window", prev);
    else delete globalThis.window;
  });
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url) => {
    const parsed = new URL(url, "https://example.test");
    calls.push(parsed);
    return Response.json({ attribution_mode: parsed.searchParams.get("attribution_mode") });
  });
  const equal = { window: "30d", attribution_mode: "equal" };
  const weighted = { window: "30d", attribution_mode: "value_weighted" };
  assert.equal((await fetchCpisUtm(equal)).attribution_mode, "equal");
  assert.equal((await fetchCpisUtm(weighted)).attribution_mode, "value_weighted");
  assert.equal((await fetchCpisUtm(equal)).attribution_mode, "equal");
  assert.equal(calls.length, 2);
  await fetchCpisDailySeries({ attribution_mode: "value_weighted", from_date: "2026-10-21", to_date: "2026-10-22" });
  assert.equal(calls[2].searchParams.get("attribution_mode"), "value_weighted");
  assert.equal(calls[2].searchParams.get("from_date"), "2026-10-21");
  assert.equal(calls[2].searchParams.get("to_date"), "2026-10-22");
});
