"use client";

import { useEffect, useMemo, useState } from "react";
import { AdsAnalyseRow, AdsAnalyseSort, ApiError, fetchAdsAnalyse } from "@/lib/api";

const PAGE_SIZE = 50;

const SORT_OPTIONS: { value: AdsAnalyseSort; label: string }[] = [
  { value: "spend", label: "Spend" },
  { value: "meta_roas", label: "Meta ROAS" },
  { value: "shopify_roas", label: "Shopify ROAS" },
  { value: "shopify_revenue", label: "Shopify revenue" },
  { value: "impressions", label: "Impressions" },
];

function formatNumber(n: number | null, opts: Intl.NumberFormatOptions = {}): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString(undefined, opts);
}

export function AdsAnalyse() {
  const [accountName, setAccountName] = useState("");
  const [search, setSearch] = useState("");
  const [onlyWithOrders, setOnlyWithOrders] = useState(false);
  const [sort, setSort] = useState<AdsAnalyseSort>("spend");

  const [rows, setRows] = useState<AdsAnalyseRow[]>([]);
  const [total, setTotal] = useState(0);
  const [accountOptions, setAccountOptions] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const filters = useMemo(
    () => ({
      account_name: accountName || undefined,
      search: search || undefined,
      only_with_shopify_orders: onlyWithOrders,
      sort,
    }),
    [accountName, search, onlyWithOrders, sort],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchAdsAnalyse({ ...filters, limit: PAGE_SIZE, offset: 0 })
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setTotal(res.total);
        setAccountOptions((prev) => {
          const next = new Set(prev);
          res.rows.forEach((r) => r.account_name && next.add(r.account_name));
          return next;
        });
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
      const res = await fetchAdsAnalyse({ ...filters, limit: PAGE_SIZE, offset: rows.length });
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
        Row-level table (legacy&apos;s &quot;Ads Analyse&quot;) — every Meta metric alongside real Shopify-attributed
        revenue, so Meta&apos;s own ROAS and the order-backed ROAS sit side by side.
      </p>

      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border-primary bg-white shadow-sm p-3">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search ad name…"
          className="w-56 rounded-md border border-border-primary bg-white px-3 py-1.5 text-sm text-text-primary placeholder:text-text-tertiary focus:border-accent-yellow focus:outline-none"
        />
        <select
          value={accountName}
          onChange={(e) => setAccountName(e.target.value)}
          className="rounded-md border border-border-primary bg-white px-2 py-1.5 text-sm text-text-primary focus:border-accent-yellow focus:outline-none"
        >
          <option value="">All accounts</option>
          {[...accountOptions].sort().map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-1.5 text-sm text-text-primary">
          <input type="checkbox" checked={onlyWithOrders} onChange={(e) => setOnlyWithOrders(e.target.checked)} />
          Only ads with Shopify orders
        </label>
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as AdsAnalyseSort)}
          className="rounded-md border border-border-primary bg-white px-2 py-1.5 text-sm text-text-primary focus:border-accent-yellow focus:outline-none"
        >
          {SORT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              Sort: {o.label}
            </option>
          ))}
        </select>
        <span className="ml-auto text-xs text-text-secondary">{total.toLocaleString()} ads match</span>
      </div>

      {error && <div className="rounded-md border border-error-mid bg-error-bg p-3 text-sm text-error-text">{error}</div>}
      {loading ? (
        <p className="text-sm text-text-secondary">Loading…</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border-primary bg-white shadow-sm">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border-primary text-xs text-text-secondary">
                <th className="px-4 py-2 font-medium">Ad</th>
                <th className="px-4 py-2 font-medium">Account</th>
                <th className="px-4 py-2 font-medium">Category</th>
                <th className="px-4 py-2 text-right font-medium">Spend</th>
                <th className="px-4 py-2 text-right font-medium">Meta ROAS</th>
                <th className="px-4 py-2 text-right font-medium">Shopify orders</th>
                <th className="px-4 py-2 text-right font-medium">Shopify revenue</th>
                <th className="px-4 py-2 text-right font-medium">Shopify ROAS</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.ad_id} className="border-b border-border-soft hover:bg-bg-surface">
                  <td className="max-w-[260px] truncate px-4 py-2 text-text-primary" title={row.ad_name ?? ""}>
                    {row.ad_name ?? "—"}
                  </td>
                  <td className="px-4 py-2 text-text-secondary">{row.account_name ?? "—"}</td>
                  <td className="px-4 py-2 text-text-secondary">{row.category ?? "—"}</td>
                  <td className="px-4 py-2 text-right font-mono text-xs text-text-primary">
                    {formatNumber(row.spend, { maximumFractionDigits: 0 })}
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-xs text-text-primary">
                    {formatNumber(row.meta_roas, { maximumFractionDigits: 2 })}
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-xs text-text-primary">
                    {formatNumber(row.shopify_orders, { maximumFractionDigits: 0 })}
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-xs text-text-primary">
                    {formatNumber(row.shopify_revenue, { maximumFractionDigits: 0 })}
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-xs text-text-primary">
                    {formatNumber(row.shopify_roas, { maximumFractionDigits: 2 })}
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-6 text-center text-text-secondary">
                    No ads match these filters.
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
