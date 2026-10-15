import type { AdsAnalyseRow, AdsAnalyseTotals, RollupRow } from "@/lib/api";

export type TableTotals = Record<string, number | null>;

// Only additive measures belong here. Reach, distinct repeat customers,
// dates, verdicts and benchmark efficiencies cannot be added across ads.
const ADDITIVE = [
  "spend", "impressions", "purchases", "conv_value", "shopify_orders",
  "shopify_revenue", "ncp_count", "ftewv_count", "link_clicks_raw",
  "atc_count", "ci_count", "engagement_count", "new_customers",
  "new_customer_sales", "repeat_customer_sales", "clicks", "ads",
  ...[3, 7, 14, 28].flatMap((days) => [
    `d${days}_spend`, `d${days}_lc_revenue`, `d${days}_ftewv`,
  ]),
];

function ratios(totals: TableTotals): TableTotals {
  const divide = (numerator: string, denominator: string, scale = 1) => {
    const n = totals[numerator], d = totals[denominator];
    return n != null && d != null && d > 0 ? n / d * scale : null;
  };
  const result: TableTotals = {
    ...totals,
    roas: divide("conv_value", "spend"),
    shopify_roas: divide("shopify_revenue", "spend"),
    cost_per_1000: divide("spend", "impressions", 1000),
    cpm: divide("spend", "impressions", 1000),
    cpc_link: divide("spend", "link_clicks_raw"),
    ctr_pct: divide("link_clicks_raw", "impressions", 100),
    ctr: divide("clicks", "impressions", 100),
    cost_per_purchase: divide("spend", "purchases"),
    cost_per_shopify_order: divide("spend", "shopify_orders"),
    cost_per_ncp: divide("spend", "ncp_count"),
    // Acquisition, the same two figures the Dashboard's AMER card
    // divides -- here per ad. Ratios of the SUMS, never a mean of the
    // per-row ratios: an ad that acquired one customer for ₹200 would
    // otherwise weigh as heavily in the total as one that acquired two
    // thousand.
    cost_per_new_customer: divide("spend", "new_customers"),
    acq_mer: divide("new_customer_sales", "spend"),
    new_customer_aov: divide("new_customer_sales", "new_customers"),
    cost_per_ftewv: divide("spend", "ftewv_count"),
    atc_lc_pct: divide("atc_count", "link_clicks_raw", 100),
    ci_atc_pct: divide("ci_count", "atc_count", 100),
    checkout_compl_pct: divide("purchases", "ci_count", 100),
    cr_lc_pct: divide("purchases", "link_clicks_raw", 100),
  };
  if (totals.conv_value != null && totals.spend != null) {
    result.profit_efficiency = totals.conv_value - totals.spend;
    result.contrib_margin_pct = totals.conv_value > 0
      ? result.profit_efficiency / totals.conv_value * 100 : null;
  }
  if (totals.shopify_revenue != null && totals.conv_value != null && totals.conv_value > 0) {
    result.meta_shop_diff_pct = (totals.shopify_revenue - totals.conv_value) / totals.conv_value * 100;
  }
  for (const days of [3, 7, 14, 28]) {
    result[`d${days}_lc_roas`] = divide(`d${days}_lc_revenue`, `d${days}_spend`);
    result[`d${days}_cost_per_ftewv`] = divide(`d${days}_spend`, `d${days}_ftewv`);
    // The decision columns repeat these measures under separate column keys.
    result[`d${days}_lc_roas_v`] = result[`d${days}_lc_roas`];
    result[`d${days}_cost_per_ftewv_v`] = result[`d${days}_cost_per_ftewv`];
  }
  return result;
}

export function sumTableRows(rows: readonly (AdsAnalyseRow | RollupRow)[]): TableTotals {
  const sums: TableTotals = {};
  for (const key of ADDITIVE) {
    let sum: number | null = 0;
    for (const row of rows) {
      const value = (row as unknown as Record<string, unknown>)[key];
      // A partial customer breakdown or unavailable source is unknown,
      // not zero. Never publish a partial sum as a complete total.
      if (typeof value !== "number" || !Number.isFinite(value)) {
        sum = null;
        break;
      }
      sum += value;
    }
    sums[key] = sum;
  }
  return ratios(sums);
}

export function getAdTableTotals({ rows, totals, total, loadedCount, hasLocalFilters }: {
  rows: readonly AdsAnalyseRow[];
  totals: AdsAnalyseTotals | null;
  total: number;
  loadedCount: number;
  hasLocalFilters: boolean;
}): { values: TableTotals; count: number; partial: boolean } {
  if (hasLocalFilters || !totals) {
    return { values: sumTableRows(rows), count: rows.length, partial: loadedCount < total };
  }
  // Use the existing response's full-filter aggregates, not the visible
  // page. No new request or automatic loading of thousands of rows.
  const sums: TableTotals = loadedCount >= total ? sumTableRows(rows) : {};
  for (const key of ADDITIVE) {
    if (key in totals) {
      sums[key] = (totals as unknown as TableTotals)[key];
    }
  }
  // avg_* can be unweighted lifetime averages. Derive blended rates
  // from these totals so they divide out to the spend/revenue displayed.
  return { values: ratios(sums), count: totals.ad_count, partial: false };
}

export function totalUnavailableReason(key: string): string {
  if (key.includes("reach") || key.includes("frequency") || key === "cpr_1000") {
    return "Reach overlaps across ads and entities; a deduplicated total is not available.";
  }
  if (key === "repeat_customers") {
    return "One repeat customer can appear in several rows; a distinct total is not available.";
  }
  return "No aggregate is available for this column and scope. Missing values are not treated as zero.";
}
