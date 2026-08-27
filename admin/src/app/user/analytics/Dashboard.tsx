"use client";

import { useEffect, useState } from "react";
import { ApiError, OverviewSummaryResponse, fetchOverviewSummary } from "@/lib/api";
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
    // Guard against a stale saved order missing/adding widgets across deploys.
    if (Array.isArray(parsed) && DEFAULT_ORDER.every((id) => parsed.includes(id)) && parsed.length === DEFAULT_ORDER.length) {
      return parsed;
    }
    return DEFAULT_ORDER;
  } catch {
    return DEFAULT_ORDER;
  }
}

export function Dashboard() {
  const [data, setData] = useState<OverviewSummaryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [order, setOrder] = useState<string[]>(DEFAULT_ORDER);

  useEffect(() => {
    setOrder(loadOrder());
    fetchOverviewSummary()
      .then(setData)
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Could not reach the FastAPI backend. Is it running?"));
  }, []);

  function handleReorder(next: string[]) {
    setOrder(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      // localStorage unavailable (private window, etc.) -- reordering still works for this session, just doesn't persist.
    }
  }

  if (error) {
    return <div className="rounded-md border border-error-mid bg-error-bg p-3 text-sm text-error-text">{error}</div>;
  }
  if (!data) {
    return <p className="text-sm text-text-secondary">Loading…</p>;
  }

  const items: GridItem[] = [
    {
      id: "kpis",
      span: 3,
      content: (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div>
            <p className="tabular-nums text-2xl font-semibold text-text-primary">{formatCurrency(data.total_spend)}</p>
            <p className="mt-0.5 text-xs text-text-secondary">Total ad spend</p>
          </div>
          <div>
            <p className="tabular-nums text-2xl font-semibold text-text-primary">{formatCurrency(data.total_shopify_revenue)}</p>
            <p className="mt-0.5 text-xs text-text-secondary">Shopify revenue (attributed)</p>
          </div>
          <div>
            <p className="tabular-nums text-2xl font-semibold text-text-primary">{data.total_shopify_orders.toLocaleString()}</p>
            <p className="mt-0.5 text-xs text-text-secondary">Attributed orders</p>
          </div>
          <div>
            <p className="tabular-nums text-2xl font-semibold text-text-primary">
              {(data.total_impressions / 1_000_000).toFixed(1)}M
            </p>
            <p className="mt-0.5 text-xs text-text-secondary">Impressions</p>
          </div>
        </div>
      ),
    },
    {
      id: "category",
      span: 2,
      content: (
        <div>
          <h3 className="text-sm font-medium text-text-primary">Spend by category</h3>
          <div className="mt-3">
            <BarChart
              categories={data.category_breakdown.map((c) => c.label)}
              series={[{ name: "Spend", values: data.category_breakdown.map((c) => c.value) }]}
              height={220}
              valueFormat={(n) => `₹${(n / 100000).toFixed(1)}L`}
            />
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
            {data.channel_breakdown
              .sort((a, b) => b.value - a.value)
              .map((c) => (
                <div key={c.label} className="flex items-center justify-between text-xs">
                  <span className="text-text-secondary">{c.label}</span>
                  <span className="tabular-nums font-medium text-text-primary">{formatCurrency(c.value)}</span>
                </div>
              ))}
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
            {data.top_landing_pages.map((p) => (
              <div key={p.landing_page_path} className="flex items-center justify-between text-xs">
                <span className="truncate text-text-secondary" title={p.landing_page_path}>
                  {p.landing_page_path}
                </span>
                <span className="tabular-nums font-medium text-text-primary">{p.sessions.toLocaleString()}</span>
              </div>
            ))}
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
            {data.top_cpis_skus.map((s) => (
              <div key={s.master_sku} className="flex items-center justify-between text-xs">
                <span className="font-mono text-text-secondary">{s.master_sku}</span>
                <span className="tabular-nums text-text-secondary">
                  {formatCurrency(s.ad_spend)} · ₹{s.cost_per_ncp?.toFixed(0) ?? "—"}/NCP
                </span>
              </div>
            ))}
          </div>
        </div>
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-text-secondary">
        Drag any tile to rearrange — your layout is remembered on this device.
      </p>
      <DraggableGrid items={items} order={order} onReorder={handleReorder} />
    </div>
  );
}
