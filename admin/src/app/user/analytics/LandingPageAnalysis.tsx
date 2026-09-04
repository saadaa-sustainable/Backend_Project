"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ApiError,
  LandingPageAdRow,
  LandingPageRow,
  fetchLandingPageAdBreakdown,
  fetchLandingPages,
} from "@/lib/api";
import { ExportButton } from "@/components/ExportButton";

const PAGE_SIZE = 50;

const SORT_OPTIONS: { value: "sessions" | "ad_spend" | "cost_per_session" | "checkout_rate"; label: string }[] = [
  { value: "sessions", label: "Sessions" },
  { value: "ad_spend", label: "Ad spend" },
  { value: "cost_per_session", label: "Cost / session" },
  { value: "checkout_rate", label: "Checkout rate" },
];

function formatNumber(n: number | null, opts: Intl.NumberFormatOptions = {}): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString(undefined, opts);
}

function AdBreakdownPanel({ path, onClose }: { path: string; onClose: () => void }) {
  const [rows, setRows] = useState<LandingPageAdRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchLandingPageAdBreakdown(path)
      .then((res) => !cancelled && setRows(res.rows))
      .catch((err: unknown) => !cancelled && setError(err instanceof ApiError ? err.message : "Could not load ad breakdown."))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [path]);

  return (
    <div className="rounded-lg border border-warning-border bg-warning-bg/40 p-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-text-primary">Ads linking to {path}</h3>
        <button onClick={onClose} className="text-xs text-text-secondary hover:text-text-primary">
          Close ✕
        </button>
      </div>
      {error && <p className="mt-2 text-xs text-error-text">{error}</p>}
      {loading ? (
        <p className="mt-2 text-xs text-text-secondary">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="mt-2 text-xs text-text-secondary">
          No ads currently link to this page (or ad-creative link data hasn&apos;t been fetched yet).
        </p>
      ) : (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-warning-border text-text-secondary">
                <th className="px-3 py-1.5 font-medium">Ad</th>
                <th className="px-3 py-1.5 text-right font-medium">Spend</th>
                <th className="px-3 py-1.5 text-right font-medium">Meta ROAS</th>
                <th className="px-3 py-1.5 text-right font-medium">Shopify orders</th>
                <th className="px-3 py-1.5 text-right font-medium">Shopify ROAS</th>
                <th className="px-3 py-1.5 text-right font-medium">ROAS gap %</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.ad_id} className="border-b border-warning-border/60">
                  <td className="max-w-[220px] truncate px-3 py-1.5 text-text-primary" title={r.ad_name ?? ""}>
                    {r.ad_name ?? "—"}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono text-text-primary">
                    {formatNumber(r.spend, { maximumFractionDigits: 0 })}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono text-text-primary">
                    {formatNumber(r.meta_roas, { maximumFractionDigits: 2 })}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono text-text-primary">
                    {formatNumber(r.shopify_orders, { maximumFractionDigits: 0 })}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono text-text-primary">
                    {formatNumber(r.shopify_roas, { maximumFractionDigits: 2 })}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono text-text-primary">
                    {formatNumber(r.roas_gap_pct, { maximumFractionDigits: 1 })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function LandingPageAnalysis() {
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<"sessions" | "ad_spend" | "cost_per_session" | "checkout_rate">("sessions");
  const [selectedPath, setSelectedPath] = useState<string | null>(null);

  const [rows, setRows] = useState<LandingPageRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const filters = useMemo(() => ({ search: search || undefined, sort }), [search, sort]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchLandingPages({ ...filters, limit: PAGE_SIZE, offset: 0 })
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setTotal(res.total);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Could not reach the FastAPI backend. Is it running?");
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters]);

  async function loadMore() {
    setLoadingMore(true);
    try {
      const res = await fetchLandingPages({ ...filters, limit: PAGE_SIZE, offset: rows.length });
      setRows((prev) => [...prev, ...res.rows]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load more rows.");
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-text-secondary">
        30-day rolling session-vs-ad-spend rollup per page (legacy&apos;s{" "}
        <code className="text-xs">landing_page_analysis_30d</code>). Ads are matched to a page by the ad
        creative&apos;s own destination URL, not UTM tags — click a row to see which ads link there.
      </p>

      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border-primary bg-white shadow-sm p-3">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search page path…"
          className="w-64 rounded-md border border-border-primary bg-white px-3 py-1.5 text-sm text-text-primary placeholder:text-text-tertiary focus:border-accent-yellow focus:outline-none"
        />
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as typeof sort)}
          className="rounded-md border border-border-primary bg-white px-2 py-1.5 text-sm text-text-primary focus:border-accent-yellow focus:outline-none"
        >
          {SORT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              Sort: {o.label}
            </option>
          ))}
        </select>
        <span className="ml-auto text-xs text-text-secondary">{total.toLocaleString()} pages</span>
        <ExportButton
          rows={rows as unknown as Record<string, unknown>[]}
          filename="landing_page_analysis"
          disabled={loading || !rows.length}
        />
      </div>

      {error && <div className="rounded-md border border-error-mid bg-error-bg p-3 text-sm text-error-text">{error}</div>}
      {loading ? (
        <p className="text-sm text-text-secondary">Loading…</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border-primary bg-white shadow-sm">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border-primary text-xs text-text-secondary">
                <th className="px-4 py-2 font-medium">Page</th>
                <th className="px-4 py-2 text-right font-medium">Sessions</th>
                <th className="px-4 py-2 text-right font-medium">ATC rate</th>
                <th className="px-4 py-2 text-right font-medium">Checkout rate</th>
                <th className="px-4 py-2 text-right font-medium">Bounce rate</th>
                <th className="px-4 py-2 text-right font-medium">Ad spend</th>
                <th className="px-4 py-2 text-right font-medium">Distinct ads</th>
                <th className="px-4 py-2 text-right font-medium">Cost/session</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <>
                  <tr
                    key={row.landing_page_path}
                    onClick={() => setSelectedPath((prev) => (prev === row.landing_page_path ? null : row.landing_page_path))}
                    className="cursor-pointer border-b border-border-soft hover:bg-bg-surface"
                  >
                    <td className="max-w-[280px] truncate px-4 py-2 text-text-primary" title={row.landing_page_path}>
                      {row.landing_page_path}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs text-text-primary">
                      {formatNumber(row.sessions)}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs text-text-primary">
                      {formatNumber(row.atc_rate, { maximumFractionDigits: 1 })}%
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs text-text-primary">
                      {formatNumber(row.checkout_rate, { maximumFractionDigits: 1 })}%
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs text-text-primary">
                      {formatNumber(row.bounce_rate, { maximumFractionDigits: 1 })}%
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs text-text-primary">
                      {formatNumber(row.ad_spend, { maximumFractionDigits: 0 })}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs text-text-primary">
                      {formatNumber(row.distinct_ads)}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs text-text-primary">
                      {formatNumber(row.cost_per_session, { maximumFractionDigits: 2 })}
                    </td>
                  </tr>
                  {selectedPath === row.landing_page_path && (
                    <tr key={`${row.landing_page_path}-panel`}>
                      <td colSpan={8} className="px-4 py-3">
                        <AdBreakdownPanel path={row.landing_page_path} onClose={() => setSelectedPath(null)} />
                      </td>
                    </tr>
                  )}
                </>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-6 text-center text-text-secondary">
                    No pages match these filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          {rows.length < total && (
            <div className="border-t border-border-soft p-3 text-center">
              <button
                onClick={loadMore}
                disabled={loadingMore}
                className="rounded-md bg-bg-muted px-4 py-1.5 text-xs font-medium text-text-primary transition-colors hover:bg-bg-muted disabled:opacity-40"
              >
                {loadingMore ? "Loading…" : `Load more (${rows.length} of ${total})`}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
