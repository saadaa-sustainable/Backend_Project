"use client";

import { useEffect, useMemo, useState } from "react";

import {
  ApiError,
  CampaignAnalysis as Campaign,
  CampaignAnalysisResponse,
  CampaignMetrics,
  fetchCampaignAnalysis,
} from "@/lib/api";
import { CATEGORICAL_PALETTE } from "@/lib/theme";
import { LineChart } from "./charts/LineChart";
import { TableFrame } from "./SectionChrome";
import { StatTile } from "./StatTile";

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

type Kpi = { label: string; value: (m: CampaignMetrics) => number | null; fmt: Fmt; better: "high" | "low" };

/** The four headline cards, each with its own colour. */
const HERO: (Kpi & { color: string })[] = [
  { label: "Spend", value: (m) => m.spend, fmt: "inr", better: "high", color: CATEGORICAL_PALETTE[0] },
  { label: "Last-click revenue", value: (m) => m.lc_revenue, fmt: "inr", better: "high", color: CATEGORICAL_PALETTE[1] },
  { label: "Last-click ROAS", value: (m) => div(m.lc_revenue, m.spend), fmt: "x", better: "high", color: CATEGORICAL_PALETTE[2] },
  { label: "Cost / NCP", value: (m) => div(m.spend, m.ncp), fmt: "inr", better: "low", color: CATEGORICAL_PALETTE[5] },
];

const TILES: Kpi[] = [
  { label: "LC orders", value: (m) => m.lc_orders, fmt: "num", better: "high" },
  { label: "AOV", value: (m) => div(m.lc_revenue, m.lc_orders), fmt: "inr", better: "high" },
  { label: "NCP", value: (m) => m.ncp, fmt: "num", better: "high" },
  { label: "New-cust. share", value: (m) => div(m.lc_new_orders * 100, m.lc_orders), fmt: "pct", better: "high" },
  { label: "FC revenue", value: (m) => m.fc_revenue, fmt: "inr", better: "high" },
  { label: "FC ROAS", value: (m) => div(m.fc_revenue, m.spend), fmt: "x", better: "high" },
  { label: "Meta ROAS", value: (m) => div(m.conv_value, m.spend), fmt: "x", better: "high" },
  { label: "CTR", value: (m) => div(m.clicks * 100, m.impressions), fmt: "pct", better: "high" },
  { label: "CPM", value: (m) => div(m.spend * 1000, m.impressions), fmt: "inr", better: "low" },
  { label: "CPC", value: (m) => div(m.spend, m.clicks), fmt: "inr", better: "low" },
];

/** Change against the window before, as a fraction; null when there is nothing to compare. */
const change = (cur: number | null, prev: number | null) =>
  cur === null || prev === null || prev === 0 ? null : (cur - prev) / Math.abs(prev);

function Delta({ d, better, onColor }: { d: number | null; better: "high" | "low"; onColor?: boolean }) {
  if (d === null) return <span>no earlier data</span>;
  const good = d === 0 ? null : (d > 0) === (better === "high");
  const tone = onColor ? "" : good === null ? "" : good ? "text-success-text" : "text-error-text";
  return (
    <span className={tone}>
      {d >= 0 ? "▲" : "▼"} {Math.abs(d * 100).toFixed(1)}%
      <span className={onColor ? "opacity-80" : "text-text-tertiary"}> vs previous</span>
    </span>
  );
}

/** A trend line with no axes, for a card. Days without a value are skipped. */
function Spark({ values, color }: { values: (number | null)[]; color: string }) {
  const pts = values.map((v, i) => [i, v] as const).filter((p): p is readonly [number, number] => p[1] !== null);
  if (pts.length < 2) return null;
  const lo = Math.min(...pts.map((p) => p[1]));
  const hi = Math.max(...pts.map((p) => p[1]));
  const n = Math.max(1, values.length - 1);
  const line = pts.map(([i, v]) => `${(i / n) * 100},${30 - ((v - lo) / (hi - lo || 1)) * 28}`).join(" ");
  return (
    <svg viewBox="0 0 100 32" preserveAspectRatio="none" className="h-10 w-24 shrink-0" aria-hidden>
      <polyline points={line} fill="none" stroke={color} strokeWidth={2} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  );
}

function HeroCard({ k, cur, prev, daily }: { k: (typeof HERO)[number]; cur: CampaignMetrics; prev?: CampaignMetrics; daily: (number | null)[] }) {
  const v = k.value(cur);
  return (
    <div className="flex flex-col justify-between gap-3 rounded-xl p-4 text-white shadow-sm" style={{ backgroundColor: k.color }}>
      <span className="text-[12.5px] font-medium opacity-90">{k.label}</span>
      <div className="flex items-end justify-between gap-2">
        <span className="text-[26px] font-semibold leading-none tabular-nums">{fmt(v, k.fmt)}</span>
        <Spark values={daily} color="#FFFFFF" />
      </div>
      <span className="text-[11.5px] tabular-nums">
        <Delta d={prev ? change(v, k.value(prev)) : null} better={k.better} onColor />
      </span>
    </div>
  );
}

/** Horizontal share bars. `overlapping` rows are views of the same thing, so they are
 * drawn against the largest and get no share, since a sum of them means nothing. */
function ShareBars({ title, rows, overlapping }: { title: string; rows: { label: string; value: number; color: string; text: string }[]; overlapping?: boolean }) {
  const total = overlapping ? Math.max(0, ...rows.map((r) => r.value)) : rows.reduce((a, r) => a + r.value, 0);
  return (
    <div className="flex flex-col gap-2.5">
      <h5 className="text-[12px] font-semibold uppercase tracking-wide text-text-secondary">{title}</h5>
      {rows.map((r) => {
        const share = total > 0 ? r.value / total : 0;
        return (
          <div key={r.label} className="flex flex-col gap-1">
            <div className="flex items-baseline justify-between gap-2 text-[12px]">
              <span className="flex min-w-0 items-center gap-1.5 text-text-primary">
                <span className="inline-block h-2 w-2 shrink-0 rounded-full" style={{ background: r.color }} />
                <span className="truncate" title={r.label}>{r.label}</span>
              </span>
              <span className="shrink-0 tabular-nums text-text-secondary">
                {overlapping ? <span className="font-semibold text-text-primary">{r.text}</span> : <>{r.text} · <span className="font-semibold text-text-primary">{(share * 100).toFixed(1)}%</span></>}
              </span>
            </div>
            <div className="h-1.5 rounded-full bg-bg-muted">
              <div className="h-1.5 rounded-full" style={{ width: `${share * 100}%`, background: r.color }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

const card = "rounded-xl border border-border-primary bg-bg-white p-4 shadow-sm";

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
    prev?: CampaignAnalysisResponse;
    error?: string;
  } | null>(null);

  // Yesterday: Meta lands a day in arrears, so today would read as a drop.
  // The window before it, of the same length, feeds the cards' change figures.
  const range = useMemo(() => {
    const to = new Date();
    to.setDate(to.getDate() - 1);
    const from = new Date(to);
    from.setDate(from.getDate() - (days - 1));
    const prevTo = new Date(from);
    prevTo.setDate(prevTo.getDate() - 1);
    const prevFrom = new Date(prevTo);
    prevFrom.setDate(prevFrom.getDate() - (days - 1));
    return { from: isoDay(from), to: isoDay(to), prevFrom: isoDay(prevFrom), prevTo: isoDay(prevTo) };
  }, [days]);

  const key = ids.join(",");
  const req = `${key}|${range.from}|${range.to}`;
  useEffect(() => {
    let cancelled = false;
    const list = key.split(",");
    Promise.all([
      fetchCampaignAnalysis(list, range.from, range.to),
      // The comparison is a nicety; a failure here must not blank the panel.
      fetchCampaignAnalysis(list, range.prevFrom, range.prevTo).catch(() => undefined),
    ])
      .then(([data, prev]) => !cancelled && setResult({ req, data, prev }))
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
  const prevOf = (id: string) => result?.prev?.campaigns.find((c) => c.campaign_id === id)?.totals;
  const categories = data ? daysBetween(data.from_date, data.to_date) : [];
  const byDay = (c: Campaign) => new Map(c.daily.map((d) => [d.day, d]));
  /** One metric for every day of the window; ratios stay empty on a day with nothing to divide. */
  const series = (c: Campaign, f: (m: CampaignMetrics) => number | null, ratio: boolean) => {
    const m = byDay(c);
    return categories.map((d) => {
      const row = m.get(d);
      return row ? f(row) : ratio ? null : 0;
    });
  };

  /** The best value in a row, when there is something to compare. */
  function best(row: Row): number | null {
    if (!row.better || campaigns.length < 2) return null;
    const vals = campaigns.map((c) => row.value(c.totals)).filter((v): v is number => v !== null);
    if (!vals.length) return null;
    return row.better === "high" ? Math.max(...vals) : Math.min(...vals);
  }

  const cm = CHART_METRICS[chartMetric];
  const pill = (on: boolean) =>
    `rounded-md px-2.5 py-1 text-[12px] font-medium transition-colors ${
      on ? "bg-accent-yellow text-white" : "text-text-secondary hover:bg-bg-muted hover:text-text-primary"
    }`;

  return (
    <section className="flex flex-col gap-4 rounded-xl border border-border-primary bg-bg-base p-4">
      <div className="flex flex-wrap items-start gap-3">
        <div className="mr-auto min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-text-tertiary">Campaign analysis</p>
          <h3 className="truncate text-[18px] font-semibold text-text-primary" title={primary?.campaign_name ?? undefined}>
            {primary?.campaign_name ?? "Loading…"}
          </h3>
          <p className="text-[11.5px] text-text-tertiary">
            {primary ? [primary.status, primary.objective, primary.bid_strategy, primary.account_name].filter(Boolean).join(" · ") : ""}
            {primary?.daily_budget ? ` · ${fmt(primary.daily_budget / 100, "inr")}/day` : ""}
            {primary?.created ? ` · since ${primary.created}` : ""}
          </p>
          <p className="text-[11.5px] text-text-tertiary">
            {data ? `${data.from_date} to ${data.to_date}, change vs ${range.prevFrom} to ${range.prevTo}` : ""}
            {loading && data ? " · updating…" : ""}
          </p>
        </div>
        <div className="flex items-center gap-1 rounded-lg border border-border-primary bg-bg-white p-1" role="group" aria-label="Window">
          {WINDOWS.map((d) => (
            <button key={d} type="button" aria-pressed={days === d} onClick={() => setDays(d)} className={pill(days === d)}>
              {d}d
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg border border-border-primary bg-bg-white px-3 py-1.5 text-[12.5px] text-text-secondary hover:text-text-primary"
        >
          Close
        </button>
      </div>

      {campaigns.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-[12px]">
          <span className="text-text-tertiary">{campaigns.length > 1 ? "Comparing" : "Tick other campaigns below to compare"}</span>
          {campaigns.length > 1 &&
            campaigns.map((c, i) => (
              <span key={c.campaign_id} className="flex max-w-[280px] items-center gap-1.5 rounded-full border border-border-primary bg-bg-white px-2.5 py-1">
                <span className="inline-block h-2 w-2 shrink-0 rounded-full" style={{ background: CATEGORICAL_PALETTE[i % CATEGORICAL_PALETTE.length] }} />
                <span className="truncate text-text-primary" title={c.campaign_name ?? c.campaign_id}>
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
              </span>
            ))}
        </div>
      )}

      {error && (
        <p className="rounded-md border border-warning-border bg-warning-bg px-4 py-3 text-sm text-warning-text">{error}</p>
      )}
      {loading && !data && <p className="py-6 text-sm text-text-secondary">Loading analysis…</p>}

      {primary && (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {HERO.map((k) => (
              <HeroCard key={k.label} k={k} cur={primary.totals} prev={prevOf(primary.campaign_id)} daily={series(primary, k.value, k.fmt !== "inr" || k.label.startsWith("Cost"))} />
            ))}
          </div>

          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
            {TILES.map((k, i) => {
              const v = k.value(primary.totals);
              const p = prevOf(primary.campaign_id);
              return (
                <StatTile
                  key={k.label}
                  label={k.label}
                  value={fmt(v, k.fmt)}
                  color={CATEGORICAL_PALETTE[i % CATEGORICAL_PALETTE.length]}
                  sub={<Delta d={p ? change(v, k.value(p)) : null} better={k.better} />}
                />
              );
            })}
          </div>

          <div className="grid grid-cols-1 gap-3 xl:grid-cols-3">
            <div className={`${card} flex min-w-0 flex-col gap-3 xl:col-span-2`}>
              <div className="flex flex-wrap items-center gap-2">
                <h4 className="mr-auto text-[14px] font-semibold text-text-primary">
                  {campaigns.length > 1 ? "Day by day, side by side" : "Day by day"}
                </h4>
                <div className="flex flex-wrap items-center gap-1 rounded-lg border border-border-primary p-1" role="group" aria-label="Metric to plot">
                  {CHART_METRICS.map((m, i) => (
                    <button key={m.label} type="button" aria-pressed={chartMetric === i} onClick={() => setChartMetric(i)} className={pill(chartMetric === i)}>
                      {m.label}
                    </button>
                  ))}
                </div>
              </div>
              <LineChart
                fluid
                area
                height={300}
                categories={categories.map((d) => d.slice(5))}
                series={campaigns.map((c) => ({ name: c.campaign_name ?? c.campaign_id, values: series(c, cm.value, cm.fmt !== "inr" || cm.label.startsWith("Cost")) }))}
                valueFormat={(n) => fmt(n, cm.fmt)}
              />
            </div>

            <div className={`${card} flex flex-col gap-5`}>
              {campaigns.length > 1 && (
                <ShareBars
                  title="Share of spend"
                  rows={campaigns.map((c, i) => ({
                    label: c.campaign_name ?? c.campaign_id,
                    value: c.totals.spend,
                    color: CATEGORICAL_PALETTE[i % CATEGORICAL_PALETTE.length],
                    text: fmt(c.totals.spend, "inr"),
                  }))}
                />
              )}
              <ShareBars
                title="Last-click orders by customer"
                rows={[
                  { label: "New customers", value: primary.totals.lc_new_orders, color: CATEGORICAL_PALETTE[1], text: fmt(primary.totals.lc_new_orders, "num") },
                  { label: "Returning", value: primary.totals.lc_orders - primary.totals.lc_new_orders, color: CATEGORICAL_PALETTE[0], text: fmt(primary.totals.lc_orders - primary.totals.lc_new_orders, "num") },
                ]}
              />
              <ShareBars
                title="Revenue by attribution"
                overlapping
                rows={[
                  { label: "Meta reported", value: primary.totals.conv_value, color: CATEGORICAL_PALETTE[3], text: fmt(primary.totals.conv_value, "inr") },
                  { label: "Last click", value: primary.totals.lc_revenue, color: CATEGORICAL_PALETTE[1], text: fmt(primary.totals.lc_revenue, "inr") },
                  { label: "First click (GA4)", value: primary.totals.fc_revenue, color: CATEGORICAL_PALETTE[2], text: fmt(primary.totals.fc_revenue, "inr") },
                ]}
              />
            </div>
          </div>

          <div className={`${card} flex flex-col gap-2`}>
            <h4 className="text-[14px] font-semibold text-text-primary">All metrics{campaigns.length > 1 ? ", side by side" : ""}</h4>
            <TableFrame>
              <table className="w-full border-collapse text-[12.5px]">
                <thead>
                  <tr className="text-[11px] uppercase tracking-wide text-text-tertiary">
                    <th className="border-b border-border-primary px-3 py-2 text-left font-medium">Metric</th>
                    {campaigns.map((c, i) => (
                      <th key={c.campaign_id} className="border-b border-border-primary px-3 py-2 text-right font-medium normal-case">
                        <span className="inline-flex max-w-[220px] items-center gap-1.5 text-text-primary" title={`${c.campaign_name} · ${c.campaign_id}`}>
                          <span className="inline-block h-2 w-2 shrink-0 rounded-full" style={{ background: CATEGORICAL_PALETTE[i % CATEGORICAL_PALETTE.length] }} />
                          <span className="truncate">{c.campaign_name ?? c.campaign_id}</span>
                        </span>
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
          </div>

          <div className={card}>
            <AdsetTable campaign={primary} />
          </div>

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
