"use client";

/**
 * Shopify Analytics -- customer acquisition, day by day.
 *
 * The store's own ShopifyQL report (FROM sales ... GROUP BY day WITH
 * TOTALS, PERCENT_CHANGE, COMPARE TO previous_year_match_day_of_week),
 * mirrored at day grain into `shopify_sales_daily` and read back
 * verbatim. Every daily figure is Shopify's own, so the section
 * reconciles with Shopify Analytics by construction -- verified metric
 * by metric against the store's report for Aug 18 - Sep 17 2026.
 *
 * An earlier build derived these from the order-grain `shopify_sales`
 * table instead, and three families of metric came out wrong, which is
 * why the day-grain mirror exists:
 *
 *   * customers / new_customers / returning_customers are DISTINCT
 *     counts and do not sum. Adding order-grain rows gave 635 returning
 *     "customers" on 2026-08-30 where Shopify counts 601 buyers.
 *
 *   * Units must be net_items_sold, NET of returns -- 1,889 against a
 *     gross quantity_ordered of 2,074 on 2026-08-18. Both are shown.
 *
 *   * average_order_value is the MEAN of per-order values, not
 *     total_sales / orders: 1,227.60 against a derived 1,158.40.
 *
 * Two places the port still is not a literal translation, both stated
 * in the UI rather than hidden:
 *
 *   * Window totals for Customers and Returning customers cannot come
 *     from the day rows, because distinct counts do not sum. They come
 *     from our own order mirror, which can de-duplicate across the
 *     window but runs hours behind the sales fetch.
 *
 *   * The comparison is 364 days back, not 365 -- 52 whole weeks, so the
 *     weekday lines up. Retail demand is weekday-shaped.
 *
 * The Return Prime channel is excluded, exactly as the store's report
 * does with `WHERE sales_channel != 'Return Prime: Order Return'`.
 * Those rows are refund records carrying orders but no revenue.
 * Including them means leaving Shopify's own numbers behind, so that
 * toggle switches to a derived fallback and says so.
 */

import { useEffect, useMemo, useState } from "react";
import {
  ApiError,
  ShopifyAnalyticsResponse,
  ShopifyTotals,
  fetchShopifyAnalytics,
} from "@/lib/api";
import { DateRangePicker, resolvePreset } from "@/components/DateRangePicker";
import { StatTile } from "./StatTile";
import { BarChart } from "./charts/BarChart";
import { ExportButton } from "@/components/ExportButton";
import { theme } from "@/lib/theme";

const rs = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : `₹${Math.round(n).toLocaleString("en-IN")}`;
const num = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : Math.round(n).toLocaleString("en-IN");
const pct = (n: number | null | undefined, dp = 1) =>
  n === null || n === undefined ? "—" : `${n.toFixed(dp)}%`;
const dec = (n: number | null | undefined, dp = 2) =>
  n === null || n === undefined ? "—" : n.toFixed(dp);

/** Percent change vs the comparison window. Returns null when the base
 *  is zero -- "infinite growth" is not a useful thing to render. */
function change(now: number | null | undefined, before: number | null | undefined) {
  if (now === null || now === undefined || !before) return null;
  return ((now - before) / Math.abs(before)) * 100;
}

function Delta({ now, before }: { now: number | null | undefined; before: number | null | undefined }) {
  const d = change(now, before);
  if (d === null) return null;
  const up = d >= 0;
  return (
    <span style={{ color: up ? theme.successText : theme.errorText }}>
      {up ? "▲" : "▼"} {Math.abs(d).toFixed(1)}%
    </span>
  );
}

/** Below this, the order mirror holds only part of the day, so its
 *  buyer count is a fraction of the day rather than the day. */
const COVERAGE_OK = 99;

type Metric = "total_sales" | "orders" | "new_customers" | "units";
const METRICS: { key: Metric; label: string; money?: boolean }[] = [
  { key: "total_sales", label: "Total sales", money: true },
  { key: "orders", label: "Orders" },
  { key: "new_customers", label: "New customers" },
  { key: "units", label: "Net items" },
];

export function ShopifyAnalytics() {
  const initial = resolvePreset("last30");
  const [range, setRange] = useState(initial);
  const [preset, setPreset] = useState<string>("last30");
  const [includeReturns, setIncludeReturns] = useState(false);
  const [metric, setMetric] = useState<Metric>("total_sales");
  const [reloadKey, setReloadKey] = useState(0);

  const [loaded, setLoaded] = useState<{ key: string; res: ShopifyAnalyticsResponse } | null>(null);
  const [failed, setFailed] = useState<{ key: string; msg: string } | null>(null);

  const key = `${range.from}|${range.to}|${includeReturns}|${reloadKey}`;
  const loading = loaded?.key !== key && failed?.key !== key;
  const data = loaded?.key === key ? loaded.res : null;
  const error = failed?.key === key ? failed.msg : null;

  useEffect(() => {
    if (!range.from || !range.to) return;
    let cancelled = false;
    fetchShopifyAnalytics({
      from_date: range.from,
      to_date: range.to,
      include_returns: includeReturns,
    })
      .then((res) => !cancelled && setLoaded({ key, res }))
      .catch(
        (e) =>
          !cancelled &&
          setFailed({
            key,
            msg: e instanceof ApiError ? e.message : "Could not load Shopify analytics.",
          }),
      );
    return () => {
      cancelled = true;
    };
  }, [key, range.from, range.to, includeReturns]);

  const t: ShopifyTotals | null = data?.totals ?? null;
  const p: ShopifyTotals | null = data?.previous ?? null;

  const chart = useMemo(() => {
    const rows = data?.rows ?? [];
    return {
      categories: rows.map((r) => r.day.slice(5)),
      values: rows.map((r) => Number(r[metric] ?? 0)),
    };
  }, [data, metric]);

  return (
    <div className="flex flex-col gap-3">
      {/* header */}
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <h2 className="text-[18px] font-semibold tracking-[-0.02em] text-text-primary">Shopify Analytics</h2>
          <p className="text-xs text-text-secondary">
            Customer acquisition by day, from the mirrored ShopifyQL <code>sales</code> dataset
            {data && data.excluded_channels.length > 0 && (
              <> · excluding <b>{data.excluded_channels.join(", ")}</b></>
            )}
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs" title="Return Prime rows are refunds; including them makes a day read negative.">
            <input
              type="checkbox"
              checked={includeReturns}
              onChange={(e) => setIncludeReturns(e.target.checked)}
            />
            Include returns
          </label>
          <div className="w-64">
            <DateRangePicker
              value={range}
              preset={preset}
              onApply={(r, p2) => {
                setRange(r);
                setPreset(p2);
              }}
            />
          </div>
          <button
            onClick={() => setReloadKey((k) => k + 1)}
            disabled={loading}
            className="rounded-md border border-border-primary bg-white px-2.5 py-2 text-xs hover:bg-bg-muted disabled:opacity-40"
          >
            {loading ? "Refreshing…" : "↻ Refresh"}
          </button>
          <ExportButton
            rows={(data?.rows ?? []) as unknown as Record<string, unknown>[]}
            filename={`shopify-analytics-${range.from}-to-${range.to}`}
            disabled={loading || !data?.rows.length}
          />
        </div>
      </div>

      {error && (
        <div className="rounded-md border border-error-mid bg-error-bg p-2 text-sm text-error-text">{error}</div>
      )}
      {loading && !error && (
        <div className="py-12 text-center text-sm text-text-tertiary">Loading…</div>
      )}

      {!loading && !error && data && t && p && (
        <>
          {/* The day rows are Shopify's own and need no caveat. The two
              window-level distinct counts do: they are de-duplicated
              across the window from our order mirror, which is fetched
              by a different job and runs hours behind. Left unsaid,
              a morning's lag reads as customers collapsing. */}
          {(() => {
            const notes: string[] = [];
            if (data.sales_through && data.sales_through < range.to)
              notes.push(`Shopify's data ends ${data.sales_through}`);
            if ((t.customers_coverage_pct ?? 100) < COVERAGE_OK)
              notes.push(
                `the order mirror behind Customers covers ${pct(t.customers_coverage_pct, 0)} `
                + `of the window${data.orders_through ? ` (through ${data.orders_through})` : ""}`,
              );
            if (data.source === "derived")
              notes.push(
                "returns are included, so these are aggregated from order grain rather than "
                + "mirrored from Shopify: per-day customer counts and New customers are blank, "
                + "and Net items falls back to gross",
              );
            if (!notes.length) return null;
            return (
              <div
                className="rounded-md border px-3 py-2 text-[11px] leading-relaxed"
                style={{ backgroundColor: theme.warningBg, borderColor: theme.warningMid,
                         color: theme.warningText }}
              >
                <b>Partial window.</b> {notes.join(" \u00b7 ")}. Every per-day figure below is
                Shopify&rsquo;s own; only the Customers and Returning customers totals are
                computed here, and they understate the window by roughly the shortfall.
              </div>
            );
          })()}
          {/* KPI tiles -- each carries its change vs the same window 364
              days back, which is what PERCENT_CHANGE + COMPARE TO does
              in the original report. */}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
            <StatTile
              label="Total sales" color={theme.successMid}
              value={rs(t.total_sales)}
              sub={<Delta now={t.total_sales} before={p.total_sales} />}
              title="Sum of total_sales. Excludes tax and shipping, which is why it is below the order table's total_price."
            />
            <StatTile
              label="Orders" color={theme.infoMid}
              value={num(t.orders)}
              sub={<Delta now={t.orders} before={p.orders} />}
            />
            <StatTile
              label="Customers" color={theme.accentIndigo}
              value={num(t.customers)}
              sub={
                (t.customers_coverage_pct ?? 100) < COVERAGE_OK ? (
                  <span style={{ color: theme.warningText }}>
                    {pct(t.customers_coverage_pct, 0)} of orders known
                  </span>
                ) : (
                  <Delta now={t.customers} before={p.customers} />
                )
              }
              title="Distinct buyers over the whole window -- a repeat shopper counts once, so this is NOT the sum of the daily figures (which would give ~38,200 for a window holding ~36,100). The per-day figures in the table are Shopify's own; this total is de-duplicated across the window from our order mirror."
            />
            <StatTile
              label="Avg order value" color={theme.accentPurple}
              value={rs(t.average_order_value)}
              sub={<Delta now={t.average_order_value} before={p.average_order_value} />}
              title="Shopify's own average_order_value: the mean of the per-ORDER values, not total sales / orders. The two differ because some rows carry sales without carrying an order. The window figure weights each day's mean by the orders behind it."
            />
            <StatTile
              label="Net items sold" color={theme.warningMid}
              value={num(t.units)}
              sub={`${dec(t.units_per_order)} per order \u00b7 ${num(t.units_gross)} gross`}
              title="net_items_sold -- NET of returns, as the report asks for. The gross figure beside it is quantity_ordered, which is what the ad-side metrics divide by."
            />
          </div>

          {/* acquisition split */}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <StatTile
              label="New customers" color={theme.successMid}
              value={num(t.new_customers)}
              sub={rs(t.total_sales_first_time)}
              title="First-time buyers, and the revenue from them. Safe to sum across days: a shopper is new exactly once, ever, so no day can double-count them."
            />
            <StatTile
              label="Returning customers" color={theme.infoMid}
              value={num(t.returning_customers)}
              sub={rs(t.total_sales_returning)}
              title="Distinct returning buyers, and the revenue from them. Like Customers, this total is de-duplicated across the window rather than summed from the days."
            />
            <StatTile
              label="Returning rate" color={theme.accentPink}
              value={pct(t.returning_customer_rate)}
              sub={<Delta now={t.returning_customer_rate} before={p.returning_customer_rate} />}
              title="Shopify's definition: returning customers / all customers. A share of BUYERS, not of orders."
            />
            <StatTile
              label="Discounts" color={theme.errorMid}
              value={rs(Math.abs(t.discounts))}
              sub={`gross ${rs(t.gross_sales)}`}
              title="Discounts are stored negative; shown as a positive cost here."
            />
          </div>

          {/* trend */}
          <div className="rounded-lg border border-border-primary bg-white p-3 shadow-sm">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <div className="text-sm font-semibold">Daily trend</div>
              <div className="ml-auto inline-flex overflow-hidden rounded-md border border-border-primary">
                {METRICS.map((m) => (
                  <button
                    key={m.key}
                    onClick={() => setMetric(m.key)}
                    className={
                      "px-2.5 py-1 text-xs transition-colors " +
                      (metric === m.key
                        ? "bg-text-primary text-white"
                        : "bg-white text-text-primary hover:bg-bg-muted")
                    }
                  >
                    {m.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="overflow-x-auto">
              <BarChart
                categories={chart.categories}
                series={[{ name: METRICS.find((m) => m.key === metric)!.label, values: chart.values }]}
                height={240}
                valueFormat={(n) =>
                  METRICS.find((m) => m.key === metric)?.money ? rs(n) : num(n)
                }
              />
            </div>
          </div>

          {/* channel mix -- shows what the exclusion is filtering */}
          {data.channels.length > 0 && (
            <div className="rounded-lg border border-border-primary bg-white p-3 shadow-sm">
              <div className="mb-2 text-sm font-semibold">
                Sales channels
                <span className="ml-2 text-[11px] font-normal text-text-tertiary">
                  every channel in the window, including any excluded above
                </span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="text-[11px] text-text-secondary">
                    <tr className="border-b border-border-primary">
                      <th className="px-2 py-1.5 font-medium">Channel</th>
                      <th className="px-2 py-1.5 text-right font-medium">Orders</th>
                      <th className="px-2 py-1.5 text-right font-medium">Sales</th>
                      <th className="px-2 py-1.5 text-right font-medium">Share</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.channels.map((c) => {
                      const excluded = data.excluded_channels.includes(c.sales_channel);
                      return (
                        <tr key={c.sales_channel} className="border-b border-border-soft">
                          <td className="px-2 py-1.5">
                            {c.sales_channel}
                            {excluded && (
                              <span className="ml-2 rounded px-1.5 py-0.5 text-[10px]"
                                    style={{ backgroundColor: theme.errorBg, color: theme.errorText }}>
                                excluded
                              </span>
                            )}
                          </td>
                          <td className="px-2 py-1.5 text-right tabular-nums">{num(c.orders)}</td>
                          <td className="px-2 py-1.5 text-right tabular-nums">{rs(c.total_sales)}</td>
                          <td className="px-2 py-1.5 text-right tabular-nums text-text-tertiary">
                            {pct(c.share_pct)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* day table */}
          <div className="max-h-[60vh] overflow-auto rounded-lg border border-border-primary bg-white shadow-sm">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-white">
                <tr className="border-b border-border-primary text-[11px] text-text-secondary">
                  {["Day", "Orders", "Customers", "Total sales", "AOV", "Net items", "Units/order",
                    "New", "Returning", "Returning %", "First-time ₹", "Returning ₹", "Discounts"].map((h, i) => (
                    <th key={h} className={"px-2 py-2 font-medium " + (i === 0 ? "" : "text-right")}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.day} className="border-b border-border-soft hover:bg-bg-surface">
                    <td className="px-2 py-1.5 font-mono">{r.day}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{num(r.orders)}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{num(r.customers)}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{rs(r.total_sales)}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{rs(r.average_order_value)}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{num(r.units)}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{dec(r.units_per_order)}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{num(r.new_customers)}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{num(r.returning_customers)}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{pct(r.returning_customer_rate)}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{rs(r.total_sales_first_time)}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{rs(r.total_sales_returning)}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{rs(Math.abs(r.discounts))}</td>
                  </tr>
                ))}
                {data.rows.length === 0 && (
                  <tr>
                    <td colSpan={13} className="px-4 py-8 text-center text-text-secondary">
                      No sales rows in this window.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <p className="text-[11px] leading-relaxed text-text-tertiary">
            Every per-day figure is Shopify&rsquo;s own, mirrored from the store&rsquo;s report at
            day grain. <b>New</b> and <b>Returning</b> are distinct <b>buyers</b>, so they will not
            sum to <b>Orders</b>, and a shopper who was new and then returned inside the window is
            counted in both. <b>Net items</b> is <code>net_items_sold</code>, net of returns.
            Changes compare
            against the same window <b>364 days</b> back — 52 whole weeks, so the weekday lines up. They are blank where that window predates the mirrored data, which starts 2026-01-01.
          </p>
        </>
      )}
    </div>
  );
}

export default ShopifyAnalytics;
