"use client";

import { useEffect, useMemo, useState } from "react";

import {
  ApiError,
  CampaignAnalysis as Campaign,
  CampaignAnalysisResponse,
  CampaignMetrics,
  fetchCampaignAnalysis,
} from "@/lib/api";
import { LineChart } from "./charts/LineChart";
import { FilterCell, TableFrame, filterControlClass } from "./SectionChrome";

/**
 * One campaign in depth, and up to four others beside it, over one window.
 *
 * Meta's own figures (spend, clicks, purchases, NCP), last click (the
 * order's own UTM -- the same mapping Ads Analyse uses) and first click
 * (GA4's first ad, so only orders GA4 saw) all come from one endpoint as
 * additive counts. Every ratio is worked out here from those counts.
 */

type Fmt = "inr" | "num" | "x" | "pct";
type Row = {
  label: string;
  value: (m: CampaignMetrics) => number | null;
  fmt: Fmt;
  better?: "high" | "low";
  title?: string;
};

const div = (a: number, b: number) => (b > 0 ? a / b : null);

const SECTIONS: { title: string; rows: Row[] }[] = [
  {
    title: "Meta",
    rows: [
      { label: "Spend", value: (m) => m.spend, fmt: "inr" },
      { label: "Impressions", value: (m) => m.impressions, fmt: "num" },
      { label: "Link clicks", value: (m) => m.clicks, fmt: "num" },
      { label: "CTR", value: (m) => div(m.clicks * 100, m.impressions), fmt: "pct", better: "high" },
      { label: "CPC", value: (m) => div(m.spend, m.clicks), fmt: "inr", better: "low" },
      { label: "CPM", value: (m) => div(m.spend * 1000, m.impressions), fmt: "inr", better: "low" },
      { label: "Purchases (Meta)", value: (m) => m.purchases, fmt: "num" },
      { label: "Revenue (Meta)", value: (m) => m.conv_value, fmt: "inr" },
      { label: "ROAS (Meta)", value: (m) => div(m.conv_value, m.spend), fmt: "x", better: "high" },
      { label: "Cost / purchase (Meta)", value: (m) => div(m.spend, m.purchases), fmt: "inr", better: "low" },
      { label: "NCP", value: (m) => m.ncp, fmt: "num", title: "Meta's new-customer purchases." },
      { label: "Cost / NCP", value: (m) => div(m.spend, m.ncp), fmt: "inr", better: "low" },
    ],
  },
  {
    title: "Last click (Shopify UTM)",
    rows: [
      { label: "Orders", value: (m) => m.lc_orders, fmt: "num" },
      { label: "Revenue", value: (m) => m.lc_revenue, fmt: "inr" },
      { label: "ROAS", value: (m) => div(m.lc_revenue, m.spend), fmt: "x", better: "high" },
      { label: "Cost / order", value: (m) => div(m.spend, m.lc_orders), fmt: "inr", better: "low" },
      { label: "AOV", value: (m) => div(m.lc_revenue, m.lc_orders), fmt: "inr", better: "high" },
      { label: "New-customer orders", value: (m) => m.lc_new_orders, fmt: "num" },
      { label: "New-customer revenue", value: (m) => m.lc_new_revenue, fmt: "inr" },
      {
        label: "New-customer ROAS",
        value: (m) => div(m.lc_new_revenue, m.spend),
        fmt: "x",
        better: "high",
        title: "Last-click revenue from first-time customers ÷ spend.",
      },
      {
        label: "New-customer share",
        value: (m) => div(m.lc_new_orders * 100, m.lc_orders),
        fmt: "pct",
        title: "Share of last-click orders placed by first-time customers.",
      },
    ],
  },
  {
    title: "First click (GA4)",
    rows: [
      {
        label: "Orders",
        value: (m) => m.fc_orders,
        fmt: "num",
        title: "Orders whose first GA4 session came from this campaign's ads. GA4 sees about three in four orders, so this undercounts.",
      },
      { label: "Revenue", value: (m) => m.fc_revenue, fmt: "inr" },
      { label: "ROAS", value: (m) => div(m.fc_revenue, m.spend), fmt: "x", better: "high" },
    ],
  },
];

const CHART_METRICS: { label: string; value: (m: CampaignMetrics) => number | null; fmt: Fmt }[] = [
  { label: "Spend", value: (m) => m.spend, fmt: "inr" },
  { label: "Last-click revenue", value: (m) => m.lc_revenue, fmt: "inr" },
  { label: "Last-click ROAS", value: (m) => div(m.lc_revenue, m.spend), fmt: "x" },
  { label: "First-click revenue", value: (m) => m.fc_revenue, fmt: "inr" },
  { label: "Cost / NCP", value: (m) => div(m.spend, m.ncp), fmt: "inr" },
];

function fmt(n: number | null | undefined, kind: Fmt): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "—";
  if (kind === "x") return `${n.toFixed(2)}x`;
  if (kind === "pct") return `${n.toFixed(1)}%`;
  const s = n.toLocaleString("en-IN", { maximumFractionDigits: kind === "inr" && Math.abs(n) < 100 ? 1 : 0 });
  return kind === "inr" ? `₹${s}` : s;
}

function isoDay(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Every day of the window, so a day with no spend still gets a point. */
function daysBetween(from: string, to: string): string[] {
  const out: string[] = [];
  for (let d = new Date(`${from}T00:00:00`); isoDay(d) <= to; d.setDate(d.getDate() + 1)) out.push(isoDay(d));
  return out;
}

const WINDOWS = [7, 14, 30, 60, 90];

export function CampaignAnalysis({
  ids,
  onRemove,
  onClose,
}: {
  ids: string[];
  onRemove: (id: string) => void;
  onClose: () => void;
}) {
  const [days, setDays] = useState(30);
  const [chartMetric, setChartMetric] = useState(0);
  // Each answer is kept with the request it answers; "loading" is simply an
  // answer for some other request. The last answer stays on screen meanwhile.
  const [result, setResult] = useState<{
    req: string;
    data?: CampaignAnalysisResponse;
    error?: string;
  } | null>(null);

  // Yesterday: Meta lands a day in arrears, so today would read as a drop.
  const range = useMemo(() => {
    const to = new Date();
    to.setDate(to.getDate() - 1);
    const from = new Date(to);
    from.setDate(from.getDate() - (days - 1));
    return { from: isoDay(from), to: isoDay(to) };
  }, [days]);

  const key = ids.join(",");
  const req = `${key}|${range.from}|${range.to}`;
  useEffect(() => {
    let cancelled = false;
    fetchCampaignAnalysis(key.split(","), range.from, range.to)
      .then((data) => !cancelled && setResult({ req, data }))
      .catch((e) => !cancelled && setResult({ req, error: e instanceof ApiError ? e.message : String(e) }));
    return () => {
      cancelled = true;
    };
  }, [key, range, req]);

  const loading = result?.req !== req;
  const data = result?.data ?? null;
  const error = loading ? null : result?.error ?? null;

  const campaigns: Campaign[] = data?.campaigns ?? [];
  const primary = campaigns[0];
  const categories = data ? daysBetween(data.from_date, data.to_date) : [];
  const byDay = (c: Campaign) => new Map(c.daily.map((d) => [d.day, d]));

  /** The best value in a row, when there is something to compare. */
  function best(row: Row): number | null {
    if (!row.better || campaigns.length < 2) return null;
    const vals = campaigns.map((c) => row.value(c.totals)).filter((v): v is number => v !== null);
    if (!vals.length) return null;
    return row.better === "high" ? Math.max(...vals) : Math.min(...vals);
  }

  const cm = CHART_METRICS[chartMetric];

  return (
    <section className="flex flex-col gap-4 rounded-lg border border-border-primary bg-bg-base p-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="mr-auto">
          <h3 className="text-[15px] font-semibold text-text-primary">
            {primary?.campaign_name ?? "Campaign analysis"}
          </h3>
          <p className="text-[11.5px] text-text-tertiary">
            {data ? `${data.from_date} to ${data.to_date}` : ""}
            {ids.length > 1 ? ` · compared with ${ids.length - 1} other${ids.length > 2 ? "s" : ""}` : " · tick other campaigns below to compare"}
            {loading && data ? " · updating…" : ""}
          </p>
        </div>
        <FilterCell label="Window" className="w-32" htmlFor="ca-days">
          <select id="ca-days" value={days} onChange={(e) => setDays(Number(e.target.value))} className={filterControlClass}>
            {WINDOWS.map((d) => (
              <option key={d} value={d}>
                Last {d} days
              </option>
            ))}
          </select>
        </FilterCell>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md border border-border-primary px-3 py-1.5 text-[12.5px] text-text-secondary hover:text-text-primary"
        >
          Close
        </button>
      </div>

      {error && (
        <p className="rounded-md border border-warning-border bg-warning-bg px-4 py-3 text-sm text-warning-text">{error}</p>
      )}
      {loading && !data && <p className="py-6 text-sm text-text-secondary">Loading analysis…</p>}

      {campaigns.length > 0 && (
        <>
          <TableFrame>
            <table className="w-full border-collapse text-[12.5px]">
              <thead>
                <tr className="text-[11px] uppercase tracking-wide text-text-tertiary">
                  <th className="border-b border-border-primary px-3 py-2 text-left font-medium">Metric</th>
                  {campaigns.map((c, i) => (
                    <th key={c.campaign_id} className="border-b border-border-primary px-3 py-2 text-right font-medium normal-case">
                      <div className="flex items-start justify-end gap-1.5">
                        <span className="max-w-[220px] truncate text-text-primary" title={`${c.campaign_name} · ${c.campaign_id}`}>
                          {i === 0 ? "★ " : ""}
                          {c.campaign_name ?? c.campaign_id}
                        </span>
                        {i > 0 && (
                          <button
                            type="button"
                            onClick={() => onRemove(c.campaign_id)}
                            aria-label={`Remove ${c.campaign_name ?? c.campaign_id} from the comparison`}
                            className="text-text-tertiary hover:text-text-primary"
                          >
                            ×
                          </button>
                        )}
                      </div>
                      <div className="text-[10.5px] text-text-tertiary">
                        {[c.status, c.objective, c.bid_strategy].filter(Boolean).join(" · ")}
                      </div>
                      <div className="text-[10.5px] text-text-tertiary">
                        {c.daily_budget ? `${fmt(c.daily_budget / 100, "inr")}/day` : c.lifetime_budget ? `${fmt(c.lifetime_budget / 100, "inr")} lifetime` : "Ad set budgets"}
                        {c.created ? ` · since ${c.created}` : ""}
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {SECTIONS.map((sec) => (
                  <SectionRows key={sec.title} title={sec.title} rows={sec.rows} campaigns={campaigns} best={best} />
                ))}
              </tbody>
            </table>
          </TableFrame>

          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-end gap-3">
              <h4 className="mr-auto text-[13px] font-semibold text-text-primary">
                {campaigns.length > 1 ? "Day by day, side by side" : "Day by day"}
              </h4>
              <FilterCell label="Plot" className="w-48" htmlFor="ca-metric">
                <select id="ca-metric" value={chartMetric} onChange={(e) => setChartMetric(Number(e.target.value))} className={filterControlClass}>
                  {CHART_METRICS.map((m, i) => (
                    <option key={m.label} value={i}>
                      {m.label}
                    </option>
                  ))}
                </select>
              </FilterCell>
            </div>
            <div className="overflow-x-auto">
              <LineChart
                categories={categories.map((d) => d.slice(5))}
                series={campaigns.map((c) => {
                  const m = byDay(c);
                  return {
                    name: c.campaign_name ?? c.campaign_id,
                    values: categories.map((d) => {
                      const row = m.get(d);
                      return row ? cm.value(row) : cm.fmt === "x" ? null : 0;
                    }),
                  };
                })}
                valueFormat={(n) => fmt(n, cm.fmt)}
              />
            </div>
          </div>

          {primary && <AdsetTable campaign={primary} />}

          <p className="text-[11.5px] text-text-tertiary">
            Last click credits an order to the ad in its own UTM, as Ads Analyse does. First click is the
            ad behind GA4&rsquo;s first session for the order, so it only covers orders GA4 saw (about three in
            four). Both count an order on its IST order date; Meta&rsquo;s figures are on Meta&rsquo;s own day.
          </p>
        </>
      )}
    </section>
  );
}

function SectionRows({
  title,
  rows,
  campaigns,
  best,
}: {
  title: string;
  rows: Row[];
  campaigns: Campaign[];
  best: (r: Row) => number | null;
}) {
  return (
    <>
      <tr>
        <td colSpan={campaigns.length + 1} className="border-b border-border-soft bg-bg-muted px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-text-secondary">
          {title}
        </td>
      </tr>
      {rows.map((r) => {
        const b = best(r);
        return (
          <tr key={`${title}-${r.label}`}>
            <td className="border-b border-border-soft px-3 py-1.5 text-text-secondary" title={r.title}>
              {r.label}
            </td>
            {campaigns.map((c) => {
              const v = r.value(c.totals);
              const isBest = b !== null && v !== null && v === b;
              return (
                <td
                  key={c.campaign_id}
                  className={`border-b border-border-soft px-3 py-1.5 text-right font-mono text-[11.5px] ${
                    isBest ? "font-semibold text-success-text" : "text-text-primary"
                  }`}
                >
                  {fmt(v, r.fmt)}
                </td>
              );
            })}
          </tr>
        );
      })}
    </>
  );
}

function AdsetTable({ campaign }: { campaign: Campaign }) {
  const cols: [string, (m: CampaignMetrics) => number | null, Fmt][] = [
    ["Spend", (m) => m.spend, "inr"],
    ["LC orders", (m) => m.lc_orders, "num"],
    ["LC revenue", (m) => m.lc_revenue, "inr"],
    ["LC ROAS", (m) => div(m.lc_revenue, m.spend), "x"],
    ["FC revenue", (m) => m.fc_revenue, "inr"],
    ["FC ROAS", (m) => div(m.fc_revenue, m.spend), "x"],
    ["Meta ROAS", (m) => div(m.conv_value, m.spend), "x"],
    ["NCP", (m) => m.ncp, "num"],
    ["Cost / NCP", (m) => div(m.spend, m.ncp), "inr"],
    ["CTR", (m) => div(m.clicks * 100, m.impressions), "pct"],
  ];
  return (
    <div className="flex flex-col gap-2">
      <h4 className="text-[13px] font-semibold text-text-primary">Ad sets in {campaign.campaign_name ?? campaign.campaign_id}</h4>
      <TableFrame>
        <table className="w-full border-collapse text-[12.5px]">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wide text-text-tertiary">
              <th className="border-b border-border-primary px-3 py-2 font-medium">Ad set</th>
              <th className="border-b border-border-primary px-3 py-2 font-medium">Status</th>
              {cols.map(([label]) => (
                <th key={label} className="border-b border-border-primary px-3 py-2 text-right font-medium">
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {campaign.adsets.map((a) => (
              <tr key={a.adset_id ?? "none"}>
                <td className="max-w-[300px] truncate border-b border-border-soft px-3 py-1.5 text-text-primary" title={a.adset_id ?? undefined}>
                  {a.adset_id ? a.adset_name ?? a.adset_id : "Not tied to an ad set"}
                </td>
                <td className="border-b border-border-soft px-3 py-1.5 text-text-secondary">{a.status ?? "—"}</td>
                {cols.map(([label, f, k]) => (
                  <td key={label} className="border-b border-border-soft px-3 py-1.5 text-right font-mono text-[11px] text-text-primary">
                    {fmt(f(a), k)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </TableFrame>
    </div>
  );
}
