import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/fetchAllPages.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
});
const { fetchAllPages } = await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

/** A fake endpoint over `total` rows that records how it was called. */
function endpoint(total, { lies = false } = {}) {
  const calls = [];
  const page = async (offset, limit) => {
    calls.push({ offset, limit });
    const rows = [];
    for (let i = offset; i < Math.min(offset + limit, total); i++) rows.push({ i });
    return { rows, total: lies ? total + 5000 : total };
  };
  return { page, calls };
}

test("walks every page and returns every row in order", async () => {
  const { page, calls } = endpoint(1250);
  const rows = await fetchAllPages(page, { pageSize: 500 });
  assert.equal(rows.length, 1250);
  assert.equal(rows[0].i, 0);
  assert.equal(rows[1249].i, 1249);
  assert.deepEqual(calls.map((c) => c.offset), [0, 500, 1000]);
});

test("a single short page ends the walk without a second request", async () => {
  const { page, calls } = endpoint(12);
  const rows = await fetchAllPages(page, { pageSize: 500 });
  assert.equal(rows.length, 12);
  assert.equal(calls.length, 1);
});

test("an exactly-full last page does not cost an extra empty request", async () => {
  // total hits the page boundary, so `total` is what stops it.
  const { page, calls } = endpoint(1000);
  const rows = await fetchAllPages(page, { pageSize: 500 });
  assert.equal(rows.length, 1000);
  assert.equal(calls.length, 2);
});

test("a short page wins over a total that claims more", async () => {
  // These totals are window aggregates and a row can drop out between
  // requests. Trusting `total` alone would loop on an endpoint that
  // has already run out of rows.
  const { page, calls } = endpoint(600, { lies: true });
  const rows = await fetchAllPages(page, { pageSize: 500 });
  assert.equal(rows.length, 600);
  assert.equal(calls.length, 2);
});

test("an endpoint that ignores offset cannot hang the browser", async () => {
  let calls = 0;
  const stuck = async (_offset, limit) => {
    calls++;
    return { rows: Array.from({ length: limit }, (_, i) => ({ i })), total: 1e9 };
  };
  const rows = await fetchAllPages(stuck, { pageSize: 500, hardCap: 2000 });
  assert.equal(rows.length, 2000);
  assert.equal(calls, 4);
});

test("the cap is never overshot, even mid-page", async () => {
  const { page, calls } = endpoint(10000);
  const rows = await fetchAllPages(page, { pageSize: 500, hardCap: 1200 });
  assert.equal(rows.length, 1200);
  // The last request asks for the remainder only, not a full page.
  assert.equal(calls[calls.length - 1].limit, 200);
});

test("an empty first page returns nothing and asks once", async () => {
  const { page, calls } = endpoint(0);
  const rows = await fetchAllPages(page, { pageSize: 500 });
  assert.deepEqual(rows, []);
  assert.equal(calls.length, 1);
});

test("a response with no total still terminates on a short page", async () => {
  let calls = 0;
  const noTotal = async (offset, limit) => {
    calls++;
    const rows = [];
    for (let i = offset; i < Math.min(offset + limit, 70); i++) rows.push({ i });
    return { rows };
  };
  const rows = await fetchAllPages(noTotal, { pageSize: 50 });
  assert.equal(rows.length, 70);
  assert.equal(calls, 2);
});

test("requests are sequential, never fired in parallel", async () => {
  // These endpoints aggregate the full window per call; a burst is how
  // you take the dashboard down for everyone else looking at it.
  let inFlight = 0;
  let maxInFlight = 0;
  const page = async (offset, limit) => {
    inFlight++;
    maxInFlight = Math.max(maxInFlight, inFlight);
    await new Promise((r) => setTimeout(r, 1));
    inFlight--;
    const rows = [];
    for (let i = offset; i < Math.min(offset + limit, 300); i++) rows.push({ i });
    return { rows, total: 300 };
  };
  await fetchAllPages(page, { pageSize: 100 });
  assert.equal(maxInFlight, 1);
});

test("progress reports the running count", async () => {
  const { page } = endpoint(250);
  const seen = [];
  await fetchAllPages(page, { pageSize: 100, onProgress: (n, t) => seen.push([n, t]) });
  assert.deepEqual(seen, [[100, 250], [200, 250], [250, 250]]);
});
