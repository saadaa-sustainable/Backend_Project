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

const STORAGE_KEY = "analytics-dashboard-widget-order";
const DEFAULT_ORDER = ["kpis", "category", "channel", "landing-pages", "cpis-skus"];

function formatCurrency(n: number): string {
  return `₹${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
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

  // Each widget owns its own cached fetch, so switching tabs and coming
  // back is an instant cache-hit render (sessionStorage, 5min TTL) and
  // no widget blocks another. If any one fails, only that tile goes
  // dark -- the rest still render.
  const kpis     = useCachedFetch<DashboardKpis>("dashboard/kpis",              fetchDashboardKpis);
  const category = useCachedFetch<BreakdownItem[]>("dashboard/category-breakdown", fetchDashboardCategoryBreakdown);
  const channel  = useCachedFetch<BreakdownItem[]>("dashboard/channel-breakdown",  fetchDashboardChannelBreakdown);
  const landing  = useCachedFetch<TopLandingPage[]>("dashboard/top-landing-pages", fetchDashboardTopLandingPages);
  const cpisSkus = useCachedFetch<TopCpisSku[]>("dashboard/top-cpis-skus",         fetchDashboardTopCpisSkus);

  const error =
    kpis.error?.message ||
    category.error?.message ||
    channel.error?.message ||
    landing.error?.message ||
    cpisSkus.error?.message ||
    null;

  useEffect(() => {
    setOrder(loadOrder());
  }, []);

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
            <p className="mt-0.5 text-xs text-text-secondary">Total ad spend</p>
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
          <h3 className="text-sm font-medium text-text-primary">Spend by category</h3>
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
          <h3 className="text-sm font-medium text-text-primary">Shopify revenue by channel</h3>
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
          <h3 className="text-sm font-medium text-text-primary">Top landing pages</h3>
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
          <h3 className="text-sm font-medium text-text-primary">Top SKUs by ad spend (cost / NCP)</h3>
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
      <p className="text-sm text-text-secondary">
        Drag any tile to rearrange — your layout is remembered on this device.
      </p>
      <DraggableGrid items={items} order={order} onReorder={handleReorder} />
    </div>
  );
}
