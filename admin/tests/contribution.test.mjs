import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(
  new URL("../src/app/user/analytics/charts/contribution.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
});
const { buildContribution } = await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

const sum = (bars) => bars.reduce((t, b) => t + b.change, 0);
const row = (key, current, baseline) => ({ key, current, baseline });

// Shopify landing pages, 9 Oct against 9 Sept. Sessions fell 1,944 in
// total; the head of the movement is a handful of pages.
const LIVE = [
  row("/", 7912, 5192),
  row("/collections/new-color-launch", 1113, 1),
  row("/collections/women-airy-linen-split-neck-short-kurta", 1798, 828),
  row("/collections/short-kurtas", 1088, 5369),
  row("/collections/men-cotton-pant", 11294, 12666),
  row("/collections/cotton-trousers", 3895, 4764),
];

test("bars sum to the headline change", () => {
  const { bars, total } = buildContribution(LIVE, { maxRows: 12 });
  assert.equal(total, sum(bars));
});

test("a truncated list still sums, because the remainder is drawn", () => {
  const { bars, total } = buildContribution(LIVE, { maxRows: 2 });
  const named = bars.filter((b) => !b.faint);
  const rest = bars.filter((b) => b.faint);
  assert.equal(named.length, 2);
  assert.equal(rest.length, 1);
  assert.match(rest[0].key, /all other rows \(4\)/);
  // The whole point: truncating the chart must not change its total.
  assert.equal(sum(bars), total);
  assert.equal(sum(bars), buildContribution(LIVE, { maxRows: 12 }).total);
});

test("the two biggest MOVERS are kept, not the two biggest rows", () => {
  const { bars } = buildContribution(LIVE, { maxRows: 2 });
  const named = bars.filter((b) => !b.faint).map((b) => b.key);
  // /men-cotton-pant is far the largest page by volume (11,294) but
  // only moved -1,372, so it is not a top mover.
  assert.deepEqual(named.sort(), [
    "/",
    "/collections/short-kurtas",
  ].sort());
  assert.ok(!named.includes("/collections/men-cotton-pant"));
});

test("gains first, losses last", () => {
  const { bars } = buildContribution(LIVE, { maxRows: 12 });
  const named = bars.filter((b) => !b.faint).map((b) => b.change);
  assert.deepEqual(named, [...named].sort((a, b) => b - a));
  assert.ok(named[0] > 0 && named[named.length - 1] < 0);
});

test("a row present on only one day contributes nothing", () => {
  // "new" is a real state in this data and the table says so. Charting
  // the whole current value as change would invent movement.
  const { bars, total } = buildContribution([
    row("/new", 500, null),
    row("/gone", null, 300),
    row("/real", 120, 100),
  ]);
  assert.equal(total, 20);
  assert.deepEqual(bars.map((b) => b.key), ["/real"]);
});

test("unmoved rows are left out entirely", () => {
  const { bars, movers } = buildContribution([
    row("/flat", 100, 100),
    row("/moved", 110, 100),
  ]);
  assert.equal(movers, 1);
  assert.deepEqual(bars.map((b) => b.key), ["/moved"]);
});

test("a rate gets no remainder bar, because points do not add up", () => {
  // Percentage points across rows cannot sum to the total's movement:
  // the total is weighted by sessions. A remainder bar here would
  // assert arithmetic that is false.
  const data = [
    row("/a", 3.0, 1.0), row("/b", 2.5, 1.0), row("/c", 0.5, 2.0), row("/d", 0.4, 1.0),
  ];
  const { bars } = buildContribution(data, { maxRows: 2, additive: false });
  assert.equal(bars.length, 2);
  assert.ok(bars.every((b) => !b.faint));
});

test("an exactly-zero remainder draws no bar", () => {
  const { bars } = buildContribution([
    row("/big", 200, 100), row("/up", 110, 100), row("/down", 90, 100),
  ], { maxRows: 1 });
  assert.deepEqual(bars.map((b) => b.key), ["/big"]);
});

test("empty input yields nothing rather than a zero bar", () => {
  const { bars, total, movers } = buildContribution([]);
  assert.deepEqual(bars, []);
  assert.equal(total, 0);
  assert.equal(movers, 0);
});

test("the live figures reconcile to the measured net", () => {
  // Measured in the browser 2026-10-16: Shopify sessions on the 50
  // returned pages went 47,977 -> 46,033 for the full set. On this
  // six-row slice the arithmetic is what matters, not the headline.
  const { total } = buildContribution(LIVE);
  const expected = (7912 - 5192) + (1113 - 1) + (1798 - 828)
    + (1088 - 5369) + (11294 - 12666) + (3895 - 4764);
  assert.equal(total, expected);
});
