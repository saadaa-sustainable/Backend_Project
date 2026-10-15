import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/app/user/analytics/adsTableTotals.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
});
const { getAdTableTotals, sumTableRows } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
const rows = [
  { spend: 100, conv_value: 1000, shopify_revenue: 300, impressions: 1000, purchases: 2, ncp_count: 1, ftewv_count: 20, new_customer_sales: 200, repeat_customers: 2, reach: 800 },
  { spend: 900, conv_value: 1800, shopify_revenue: 1700, impressions: 9000, purchases: 3, ncp_count: 3, ftewv_count: 80, new_customer_sales: 500, repeat_customers: 2, reach: 800 },
];
const totals = { ad_count: 200, spend: 10000, conv_value: 30000, shopify_revenue: 40000, impressions: 100000, purchases: 200, ncp_count: 20, ftewv_count: 400, reach: 80000, avg_meta_roas: 99, avg_shopify_roas: 88 };
const args = { rows, totals, total: 200, loadedCount: 2, hasLocalFilters: false };

test("full-filter totals cover unloaded pages and ignore simple averages", () => {
  const result = getAdTableTotals(args);
  assert.equal(result.count, 200);
  assert.equal(result.partial, false);
  assert.equal(result.values.spend, 10000);
  assert.equal(result.values.roas, 3);
  assert.equal(result.values.shopify_roas, 4);
  assert.equal(result.values.cost_per_ncp, 500);
  assert.equal(result.values.new_customer_sales, undefined);
});
test("numeric/custom-category filters total matching loaded rows with explicit partial scope", () => {
  const result = getAdTableTotals({ ...args, rows: [rows[1]], hasLocalFilters: true });
  assert.equal(result.count, 1);
  assert.equal(result.partial, true);
  assert.equal(result.values.spend, 900);
  assert.equal(result.values.roas, 2);
});
test("complete local results are not marked partial", () => {
  const result = getAdTableTotals({ ...args, total: 2, hasLocalFilters: true });
  assert.equal(result.partial, false);
  assert.equal(result.values.spend, 1000);
});
test("ratios divide combined values, never sum or average row ratios", () => {
  const result = sumTableRows(rows);
  assert.equal(result.roas, 2.8);
  assert.equal(result.shopify_roas, 2);
  assert.equal(result.cost_per_1000, 100);
  assert.equal(result.cost_per_ncp, 250);
  assert.equal(result.cost_per_ftewv, 10);
  assert.equal(result.profit_efficiency, 1800);
});
test("reach, distinct people, milestones and benchmark efficiencies have no false total", () => {
  for (const result of [sumTableRows(rows), getAdTableTotals(args).values]) {
    for (const key of ["reach", "latest_reach", "frequency", "repeat_customers", "blended_eff", "days_to_50k"]) {
      assert.equal(result[key], undefined, key);
    }
  }
});
test("unknown and partly missing metrics stay unknown", () => {
  const result = sumTableRows([rows[0], { ...rows[1], new_customer_sales: null, spend: NaN }]);
  assert.equal(result.new_customer_sales, null);
  assert.equal(result.spend, null);
  assert.equal(result.roas, null);
  assert.equal(getAdTableTotals({ ...args, totals: { ...totals, shopify_revenue: null } }).values.shopify_roas, null);
});
test("zero denominator produces a dash value, empty selection has zero additive totals", () => {
  const result = sumTableRows([]);
  assert.equal(result.spend, 0);
  assert.equal(result.roas, null);
  assert.equal(result.cost_per_ncp, null);
});
test("loading the full dataset fills optional totals without replacing full-filter amounts", () => {
  const result = getAdTableTotals({ ...args, total: 2, totals: { ...totals, ad_count: 2 } });
  assert.equal(result.values.new_customer_sales, 700);
  assert.equal(result.values.spend, 10000);
});
test("rollup rolling ROAS and decision-column aliases use the same weighted basis", () => {
  const result = sumTableRows([
    { ...rows[0], ads: 1, d3_spend: 100, d3_lc_revenue: 1000, d3_ftewv: 10 },
    { ...rows[1], ads: 3, d3_spend: 900, d3_lc_revenue: 1800, d3_ftewv: 90 },
  ]);
  assert.equal(result.ads, 4);
  assert.equal(result.d3_lc_roas, 2.8);
  assert.equal(result.d3_lc_roas_v, 2.8);
  assert.equal(result.d3_cost_per_ftewv_v, 10);
});
test("absent server totals fall back to explicitly partial loaded-row totals", () => {
  const result = getAdTableTotals({ ...args, totals: null });
  assert.equal(result.partial, true);
  assert.equal(result.values.spend, 1000);
});

// The acquisition ratios live in `ratios()`, which runs on the
// server-totals path -- the same place roas and cost_per_purchase are
// derived. Local-filter totals deliberately carry sums only.
const acqArgs = (serverTotals) => ({
  rows: [], totals: serverTotals, total: serverTotals.ad_count,
  loadedCount: 0, hasLocalFilters: false,
});

test("acquisition ratios in the totals row divide the sums, not average the rows", () => {
  // One ad acquired 1 customer for 100, another 9 for 900. Averaging
  // the per-row costs would give 100 and 100 -- the same answer by
  // luck -- so the sales column is skewed to make the two differ.
  const { values } = getAdTableTotals(acqArgs({
    ad_count: 2, spend: 1000, new_customers: 10, new_customer_sales: 11000,
  }));
  assert.equal(values.spend, 1000);
  assert.equal(values.new_customers, 10);
  assert.equal(values.cost_per_new_customer, 100, "1000 spend / 10 customers");
  assert.equal(values.acq_mer, 11, "11,000 new-customer sales / 1000 spend");
  assert.equal(values.new_customer_aov, 1100, "11,000 sales / 10 customers");
});

test("acquisition ratios are null rather than Infinity when a side is empty", () => {
  const spentNothingAcquired = getAdTableTotals(acqArgs({
    ad_count: 1, spend: 500, new_customers: 0, new_customer_sales: 0,
  })).values;
  assert.equal(spentNothingAcquired.cost_per_new_customer, null,
    "cost per nobody has no value");
  assert.equal(spentNothingAcquired.acq_mer, 0,
    "we spent and earned nothing from new customers: that IS zero");
  assert.equal(spentNothingAcquired.new_customer_aov, null);

  const acquiredWithoutSpend = getAdTableTotals(acqArgs({
    ad_count: 1, spend: 0, new_customers: 4, new_customer_sales: 800,
  })).values;
  assert.equal(acquiredWithoutSpend.acq_mer, null,
    "Infinity would render as perfect efficiency");
  assert.equal(acquiredWithoutSpend.cost_per_new_customer, 0,
    "four customers acquired at no cost really did cost 0 each -- it is the "
    + "DENOMINATOR being zero that makes a ratio undefined, not the numerator");
  assert.equal(acquiredWithoutSpend.new_customer_aov, 200);
});
