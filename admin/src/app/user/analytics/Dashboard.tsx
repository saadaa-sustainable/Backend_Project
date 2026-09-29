"use client";

import { useEffect, useState } from "react";
import {
  BreakdownItem,
  DashboardKpis,
  TopCpisSku,
  TopLandingPage,
  fetchDashboardCategoryBreakdown,
  fetchDashboardChannelBreakdown,
  fetchDashboardKpis,
  fetchDashboardTopCpisSkus,
  fetchDashboardTopLandingPages,
} from "@/lib/api";
import { useCachedFetch } from "@/lib/useCachedFetch";
import { DraggableGrid, GridItem } from "./DraggableGrid";
import { BarChart } from "./charts/BarChart";
import { DateRangePicker } from "@/components/DateRangePicker";

const STORAGE_KEY = "analytics-dashboard-widget-order";
const RANGE_KEY = "analytics-dashboard-date-range";
const DEFAULT_ORDER = ["kpis", "category", "channel", "landing-pages", "cpis-skus"];

function formatCurrency(n: number): string {
  return `₹${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

// ── Per-tile time frame ──────────────────────────────────────────────
// The five tiles do NOT share a window, and never did. Before this filter
// existed the dashboard already mixed lifetime, a fixed 30-day rollup and a
// fixed 7-day bucket with nothing on screen saying so. A single picker would
// have made that worse by implying one global range, so every tile states
// the window it actually used:
//
//   kpis, category   ad_performance_summary is a lifetime aggregate with no
//                    date column -> always "Lifetime", filter does not apply.
//   channel          shopify_order_attribution.created_at -> exact range.
//   landing-pages    shopify_landing_page_analysis.day -> exact range, and
//                    falls back to the fixed 30d rollup when no range is set.
//   cpis-skus        cpis_by_sku is precomputed per window_key, so the range
//                    SNAPS to 1d / 7d / 30d. A 14-day pick reads 7d.
function cpisWindowFor(from: string, to: string): string {
  const span =
    Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000) + 1;
  return [
    ["1d", 1],
    ["7d", 7],
    ["30d", 30],
  ].reduce((best, w) =>
    Math.abs((w[1] as number) - span) < Math.abs((best[1] as number) - span) ? w : best,
  )[0] as string;
}

function fmtDay(d: string): string {
  const t = Date.parse(d);
  return Number.isNaN(t)
    ? d
    : new Date(t).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** Small caption under a widget title naming the window it really covers. */
function WindowBadge({ text, muted = false }: { text: string; muted?: boolean }) {
  return (
    <span
      className={`ml-2 rounded px-1.5 py-0.5 align-middle text-[10px] font-normal ${
        muted
          ? "bg-bg-surface text-text-secondary"
          : "bg-accent-bg text-accent-text"
      }`}
    >
      {text}
    </span>
  );
}

function loadOrder(): string[] {
  if (typeof window === "undefined") return DEFAULT_ORDER;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_ORDER;
    const parsed = JSON.parse(raw) as string[];
    if (Array.isArray(parsed) && DEFAULT_ORDER.every((id) => parsed.includes(id)) && parsed.length === DEFAULT_ORDER.length) {
      return parsed;
    }
    return DEFAULT_ORDER;
  } catch {
    return DEFAULT_ORDER;
  }
}

// Small placeholder shown inside a widget while it's fetching. Keeps
// the widget's height stable so the grid doesn't reflow when data
// lands. Sized to roughly the widget's final height.
function WidgetSkeleton({ heightPx = 96 }: { heightPx?: number }) {
  return (
    <div
      className="animate-pulse rounded bg-bg-surface"
      style={{ minHeight: heightPx }}
    />
  );
}

export function Dashboard() {
  const [order, setOrder] = useState<string[]>(DEFAULT_ORDER);

  // Default to lifetime so the first paint matches what this tab has always
  // shown -- switching the default would silently change every number for
  // anyone who had bookmarked a figure.
  const [preset, setPreset] = useState<string>("lifetime");
  const [range, setRange] = useState<{ from: string; to: string } | null>(null);

  useEffect(() => {
    setOrder(loadOrder());
    try {
      const raw = window.localStorage.getItem(RANGE_KEY);
      if (raw) {
        const p = JSON.parse(raw) as { preset: string; from: string; to: string };
        if (p?.preset) {
          setPreset(p.preset);
          setRange(p.preset === "lifetime" ? null : { from: p.from, to: p.to });
        }
      }
    } catch {
      // localStorage unavailable -- the picker still works for this session.
    }
  }, []);

  const from = range?.from ?? null;
  const to = range?.to ?? null;

  // Each widget owns its own cached fetch, so switching tabs and coming
  // back is an instant cache-hit render (sessionStorage, 5min TTL) and
  // no widget blocks another. If any one fails, only that tile goes
  // dark -- the rest still render.
  //
  // The range is part of the cache key for the three tiles that honour it,
  // or last-30d and lifetime would share one cached payload.
  const rangeKey = from && to ? `${from}|${to}` : "lifetime";
  const kpis     = useCachedFetch<DashboardKpis>(`dashboard/kpis|${rangeKey}`,
                                                   () => fetchDashboardKpis(from, to));
  const category = useCachedFetch<BreakdownItem[]>(`dashboard/category-breakdown|${rangeKey}`,
                                                   () => fetchDashboardCategoryBreakdown(from, to));
  const channel  = useCachedFetch<BreakdownItem[]>(`dashboard/channel-breakdown|${rangeKey}`,
                                                   () => fetchDashboardChannelBreakdown(from, to));
  const landing  = useCachedFetch<TopLandingPage[]>(`dashboard/top-landing-pages|${rangeKey}`,
                                                   () => fetchDashboardTopLandingPages(from, to));
  const cpisSkus = useCachedFetch<TopCpisSku[]>(`dashboard/top-cpis-skus|${rangeKey}`,
                                                   () => fetchDashboardTopCpisSkus(from, to));

  const rangeLabel = from && to ? `${fmtDay(from)} – ${fmtDay(to)}` : "Lifetime";
  // Set by the backend only when the chosen window starts before the daily
  // spend table begins, i.e. spend/impressions are genuinely partial. Without
  // saying so, a range reaching into 2025 shows a far smaller spend and reads
  // as a collapse rather than as missing history.
  const spendFloorNote = kpis.data?.spend_data_from
    ? `Spend and impressions only exist from ${fmtDay(kpis.data.spend_data_from)} onwards — earlier days in this range are not included.`
    : null;
  const cpisLabel  = from && to ? `Last ${cpisWindowFor(from, to).replace("d", " days")}` : "Last 7 days";
  const landingLabel = from && to ? rangeLabel : "Last 30 days";

  const error =
    kpis.error?.message ||
    category.error?.message ||
    channel.error?.message ||
    landing.error?.message ||
    cpisSkus.error?.message ||
    null;

  function handleApplyRange(r: { from: string; to: string }, pk: string) {
    setPreset(pk);
    setRange(pk === "lifetime" ? null : { from: r.from, to: r.to });
    try {
      window.localStorage.setItem(RANGE_KEY, JSON.stringify({ preset: pk, from: r.from, to: r.to }));
    } catch {
      // non-fatal: the range still applies, it just won't persist.
    }
  }

  function handleReorder(next: string[]) {
    setOrder(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      // localStorage unavailable — reordering still works for this session, just doesn't persist.
    }
  }

  const items: GridItem[] = [
    {
      id: "kpis",
      span: 3,
      content: kpis.data ? (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div>
            <p className="tabular-nums text-2xl font-semibold text-text-primary">{formatCurrency(kpis.data.total_spend)}</p>
            <p className="mt-0.5 text-xs text-text-secondary">
              Total ad spend<WindowBadge text={rangeLabel} />
            </p>
          </div>
          <div>
            <p className="tabular-nums text-2xl font-semibold text-text-primary">{formatCurrency(kpis.data.total_shopify_revenue)}</p>
            <p className="mt-0.5 text-xs text-text-secondary">Shopify revenue (attributed)</p>
          </div>
          <div>
            <p className="tabular-nums text-2xl font-semibold text-text-primary">{kpis.data.total_shopify_orders.toLocaleString()}</p>
            <p className="mt-0.5 text-xs text-text-secondary">Attributed orders</p>
          </div>
          <div>
            <p className="tabular-nums text-2xl font-semibold text-text-primary">
              {(kpis.data.total_impressions / 1_000_000).toFixed(1)}M
            </p>
            <p className="mt-0.5 text-xs text-text-secondary">Impressions</p>
          </div>
        </div>
      ) : (
        <WidgetSkeleton heightPx={80} />
      ),
    },
    {
      id: "category",
      span: 2,
      content: (
        <div>
          <h3 className="text-sm font-medium text-text-primary">
            Spend by category<WindowBadge text={rangeLabel} />
          </h3>
          <div className="mt-3">
            {category.data ? (
              <BarChart
                categories={category.data.map((c) => c.label)}
                series={[{ name: "Spend", values: category.data.map((c) => c.value) }]}
                height={220}
                valueFormat={(n) => `₹${(n / 100000).toFixed(1)}L`}
              />
            ) : (
              <WidgetSkeleton heightPx={220} />
            )}
          </div>
        </div>
      ),
    },
    {
      id: "channel",
      span: 1,
      content: (
        <div>
          <h3 className="text-sm font-medium text-text-primary">
            Shopify revenue by channel<WindowBadge text={rangeLabel} />
          </h3>
          <div className="mt-3 flex flex-col gap-2">
            {channel.data ? (
              channel.data
                .slice()
                .sort((a, b) => b.value - a.value)
                .map((c) => (
                  <div key={c.label} className="flex items-center justify-between text-xs">
                    <span className="text-text-secondary">{c.label}</span>
                    <span className="tabular-nums font-medium text-text-primary">{formatCurrency(c.value)}</span>
                  </div>
                ))
            ) : (
              <WidgetSkeleton heightPx={200} />
            )}
          </div>
        </div>
      ),
    },
    {
      id: "landing-pages",
      span: 1,
      content: (
        <div>
          <h3 className="text-sm font-medium text-text-primary">
            Top landing pages<WindowBadge text={landingLabel} />
          </h3>
          <div className="mt-3 flex flex-col gap-2">
            {landing.data ? (
              landing.data.map((p) => (
                <div key={p.landing_page_path} className="flex items-center justify-between text-xs">
                  <span className="truncate text-text-secondary" title={p.landing_page_path}>
                    {p.landing_page_path}
                  </span>
                  <span className="tabular-nums font-medium text-text-primary">{p.sessions.toLocaleString()}</span>
                </div>
              ))
            ) : (
              <WidgetSkeleton heightPx={140} />
            )}
          </div>
        </div>
      ),
    },
    {
      id: "cpis-skus",
      span: 2,
      content: (
        <div>
          <h3 className="text-sm font-medium text-text-primary">
            Top SKUs by ad spend (cost / NCP)<WindowBadge text={cpisLabel} />
          </h3>
          <div className="mt-3 flex flex-col gap-2">
            {cpisSkus.data ? (
              cpisSkus.data.map((s) => (
                <div key={s.master_sku} className="flex items-center justify-between text-xs">
                  <span className="font-mono text-text-secondary">{s.master_sku}</span>
                  <span className="tabular-nums text-text-secondary">
                    {formatCurrency(s.ad_spend)} · ₹{s.cost_per_ncp?.toFixed(0) ?? "—"}/NCP
                  </span>
                </div>
              ))
            ) : (
              <WidgetSkeleton heightPx={140} />
            )}
          </div>
        </div>
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-3">
      {error && (
        <div className="rounded-md border border-error-mid bg-error-bg p-3 text-sm text-error-text">{error}</div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-text-secondary">
          Drag any tile to rearrange — your layout is remembered on this device.
        </p>
        <DateRangePicker
          value={{ from: from ?? "", to: to ?? "" }}
          preset={preset}
          align="right"
          onApply={handleApplyRange}
        />
      </div>
      {/* Every tile carries its own window badge, because they still do not
          all resolve the same way -- Top SKUs snaps to a precomputed bucket,
          and spend has a data floor. Saying so here beats leaving it to be
          discovered by comparing tiles. */}
      <p className="text-xs text-text-secondary">
        Each tile shows the period it actually covers.
        {spendFloorNote && <> {spendFloorNote}</>}
      </p>
      <DraggableGrid items={items} order={order} onReorder={handleReorder} />
    </div>
  );
}
