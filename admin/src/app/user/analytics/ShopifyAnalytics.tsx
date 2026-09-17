"use client";

/**
 * Shopify Analytics -- customer acquisition, day by day.
 *
 * Port of the store's own ShopifyQL report (FROM sales ... GROUP BY day
 * WITH TOTALS, PERCENT_CHANGE, COMPARE TO
 * previous_year_match_day_of_week), served from the mirrored
 * `shopify_sales` table rather than a live ShopifyQL call.
 *
 * Three things the UI states rather than hides, because each one is a
 * place the port is NOT a literal translation:
 *
 *   * "New" and "Returning" are ORDER counts split by whether the buyer
 *     was new. ShopifyQL's sales table has no distinct-customer metric
 *     at this grain, so the separate Customers tile comes from
 *     shopify_orders and will not equal new + returning.
 *
 *   * Units is `quantity_ordered`, which is GROSS of returns. The
 *     original asked for net_items_sold; the mirrored dataset has no
 *     such column, so the tile is labelled for what it actually is.
 *
 *   * The comparison is 364 days back, not 365 -- 52 whole weeks, so the
 *     weekday lines up. Retail demand is weekday-shaped.
 *
 * The Return Prime channel is excluded by default. Those rows are
 * refunds, and including them makes a day's revenue read low or
 * negative -- which is exactly what the store's own report guards
 * against with `WHERE sales_channel != 'Return Prime: Order Return'`.
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
  { key: "new_customers", label: "New (orders)" },
  { key: "units", label: "Units" },
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
          <h2 className="text-base font-semibold">Shopify Analytics</h2>
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
          {/* Say which days are partial, and why. The Customers tile
              reads from shopify_orders while everything else reads from
              shopify_sales; the two are fetched by different jobs, so on
              any given morning one is hours behind the other. Left
              unsaid, that looks like customers collapsing. */}
          {(() => {
            const notes: string[] = [];
            if (data.sales_through && data.sales_through < range.to)
              notes.push(`sales data ends ${data.sales_through}`);
            if (data.orders_through && data.orders_through < range.to)
              notes.push(`order data (Customers) ends ${data.orders_through}`);
            const lastDay = data.rows.at(-1)?.day;
            if (lastDay && data.orders_through && lastDay >= data.orders_through)
              notes.push(`${lastDay} is a partial day`);
            if (!notes.length) return null;
            return (
              <div
                className="rounded-md border px-3 py-2 text-[11px] leading-relaxed"
                style={{ backgroundColor: theme.warningBg, borderColor: theme.warningMid,
                         color: theme.warningText }}
              >
                <b>Partial window.</b> {notes.join(" \u00b7 ")}. Sales metrics and the Customers
                tile come from two separately-fetched tables, so the newest day can be
                incomplete in one but not the other.
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
              title="Distinct buyers over the whole window -- a repeat shopper counts once, so this is NOT the sum of the daily figures. Taken from shopify_orders for the same orders every other metric here uses; guest checkouts count as one buyer each. Will NOT equal new + returning, which are order counts."
            />
            <StatTile
              label="Avg order value" color={theme.accentPurple}
              value={rs(t.average_order_value)}
              sub={<Delta now={t.average_order_value} before={p.average_order_value} />}
              title="Total sales / orders, computed over the whole window -- not an average of the daily averages."
            />
            <StatTile
              label="Units" color={theme.warningMid}
              value={num(t.units)}
              sub={`${dec(t.units_per_order)} per order`}
              title="quantity_ordered -- GROSS of returns. The original report asked for net_items_sold, which the mirrored dataset does not carry."
            />
          </div>

          {/* acquisition split */}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <StatTile
              label="New (orders)" color={theme.successMid}
              value={num(t.new_customers)}
              sub={rs(t.total_sales_first_time)}
              title="Orders placed by a first-time buyer, and the revenue from them."
            />
            <StatTile
              label="Returning (orders)" color={theme.infoMid}
              value={num(t.returning_customers)}
              sub={rs(t.total_sales_returning)}
              title="Orders placed by a returning buyer, and the revenue from them."
            />
            <StatTile
              label="Returning rate" color={theme.accentPink}
              value={pct(t.returning_customer_rate)}
              sub={<Delta now={t.returning_customer_rate} before={p.returning_customer_rate} />}
              title="Returning orders / (new + returning). Share of ORDERS, not of customers."
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
                        ? "bg-slate-900 text-white"
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
                  {["Day", "Orders", "Customers", "Total sales", "AOV", "Units", "Units/order",
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
                    <td className="px-2 py-1.5 text-right tabular-nums"
                        style={(r.customers_coverage_pct ?? 100) < COVERAGE_OK
                                 ? { color: theme.warningText }
                                 : undefined}
                        title={(r.customers_coverage_pct ?? 100) < COVERAGE_OK
                                 ? `Partial: the order mirror holds ${pct(r.customers_coverage_pct, 0)} `
                                   + "of this day's orders, so the buyer count is that fraction of the day."
                                 : undefined}>
                      {num(r.customers)}
                      {(r.customers_coverage_pct ?? 100) < COVERAGE_OK ? " *" : ""}
                    </td>
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
            <b>New</b> and <b>Returning</b> count <b>orders</b> split by whether the buyer was
            new — ShopifyQL&rsquo;s sales dataset has no distinct-customer metric at this grain, so
            they will not sum to <b>Customers</b>, which comes from the order table.
            <b> Units</b> is <code>quantity_ordered</code>, gross of returns. Changes compare
            against the same window <b>364 days</b> back — 52 whole weeks, so the weekday lines up. They are blank where that window predates the mirrored data, which starts 2026-01-01.
          </p>
        </>
      )}
    </div>
  );
}

export default ShopifyAnalytics;
