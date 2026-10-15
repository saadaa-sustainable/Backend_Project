import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/app/user/analytics/acquisitionMer.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
});
const { fromKpis } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

const base = { total_spend: 11079793, total_impressions: 0, total_shopify_revenue: 0, total_shopify_orders: 0 };
// 2026-10-15 live figures: 23,873 customers acquired on Rs 1.11 Cr of
// spend, spending Rs 3.16 Cr on their first order.

test("the live shape: new-customer sales over spend, plus the rupee cost", () => {
  const f = fromKpis({ ...base, new_customers: 23873, new_customer_revenue: 31560800 });
  assert.equal(f.newCustomers, 23873);
  // Money over money -- comparable with the account MER beside it.
  assert.ok(Math.abs(f.acquisitionMer - 2.8485) < 0.001,
    `expected ~2.85x, got ${f.acquisitionMer}`);
  assert.ok(Math.abs(f.costPerNewCustomer - 464.11) < 0.01);
});

test("the head count does NOT drive the ratio", () => {
  // Same spend and same revenue, ten times the customers: the ratio
  // must not move, because it is revenue over spend. This is the whole
  // difference between the two readings of "acquisition MER".
  const few = fromKpis({ ...base, new_customers: 100, new_customer_revenue: 31560800 });
  const many = fromKpis({ ...base, new_customers: 1000, new_customer_revenue: 31560800 });
  assert.equal(few.acquisitionMer, many.acquisitionMer);
  assert.ok(few.costPerNewCustomer > many.costPerNewCustomer,
    "cost per acquisition IS driven by the head count, and must still move");
});

test("a cached payload without the field reads as unavailable, never as zero", () => {
  // The exact failure that took the Dashboard down: sessionStorage
  // held a KPI object from before this field shipped, and the card
  // called .toLocaleString() on undefined.
  const f = fromKpis({ ...base });
  assert.equal(f.newCustomers, null);
  assert.equal(f.acquisitionMer, null);
  assert.equal(f.costPerNewCustomer, null);
});

test("no data at all is the same as an unusable payload", () => {
  for (const input of [null, undefined]) {
    const f = fromKpis(input);
    assert.equal(f.newCustomers, null);
    assert.equal(f.acquisitionMer, null);
  }
});

test("zero acquisitions is a finding, and keeps its zero", () => {
  const f = fromKpis({ ...base, new_customers: 0, new_customer_revenue: 0 });
  assert.equal(f.newCustomers, 0, "0 must survive -- it is not absence");
  assert.equal(f.acquisitionMer, 0, "we spent and earned nothing new: that IS zero");
  assert.equal(f.costPerNewCustomer, null, "cost per nobody has no value");
});

test("no spend yields no ratio rather than Infinity", () => {
  const f = fromKpis({ ...base, total_spend: 0, new_customers: 40, new_customer_revenue: 8000 });
  assert.equal(f.newCustomers, 40);
  assert.equal(f.acquisitionMer, null, "Infinity would render as a record-best month");
  assert.equal(f.costPerNewCustomer, 0);
});
