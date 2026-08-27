"use client";

import { useEffect, useMemo, useState } from "react";
import { ApiError, UtmChannel, UtmOrderRow, fetchLastClickUtm } from "@/lib/api";

const PAGE_SIZE = 50;

const CHANNELS: UtmChannel[] = ["Meta", "Google", "Retention", "Other"];

const CHANNEL_STYLES: Record<UtmChannel, string> = {
  Meta: "border-accent-indigo bg-accent-indigo-bg",
  Google: "border-warning-mid bg-warning-bg",
  Retention: "border-success-mid bg-success-bg",
  Other: "border-border-mid bg-bg-surface",
};

function formatNumber(n: number | null, opts: Intl.NumberFormatOptions = {}): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString(undefined, opts);
}

function formatDate(s: string | null): string {
  if (!s) return "—";
  return new Date(s).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function LastClickUtm() {
  const [channel, setChannel] = useState<UtmChannel | "">("");
  const [tier, setTier] = useState("");
  const [search, setSearch] = useState("");

  const [rows, setRows] = useState<UtmOrderRow[]>([]);
  const [total, setTotal] = useState(0);
  const [channelCounts, setChannelCounts] = useState<Record<UtmChannel, { count: number; sales: number }> | null>(
    null,
  );
  const [tierCounts, setTierCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const filters = useMemo(
    () => ({
      channel: channel || undefined,
      tier: tier || undefined,
      search: search || undefined,
    }),
    [channel, tier, search],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchLastClickUtm({ ...filters, limit: PAGE_SIZE, offset: 0 })
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setTotal(res.total);
        setChannelCounts(res.channel_counts);
        setTierCounts(res.tier_counts);
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
      const res = await fetchLastClickUtm({ ...filters, limit: PAGE_SIZE, offset: rows.length });
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
        Order-level view (legacy&apos;s &quot;Ad Intelligence&quot;) — every Shopify order and how it was attributed
        back to a Meta ad via UTM matching.
      </p>

      {/* Channel tiles */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {CHANNELS.map((c) => (
          <button
            key={c}
            onClick={() => setChannel((prev) => (prev === c ? "" : c))}
            className={`rounded-lg border p-3 text-left transition-colors ${
              channel === c ? CHANNEL_STYLES[c] : "border-border-primary bg-white hover:bg-bg-surface"
            }`}
          >
            <p className="text-lg font-semibold text-text-primary">
              {(channelCounts?.[c]?.count ?? 0).toLocaleString()}
            </p>
            <p className="mt-0.5 text-[11px] text-text-secondary">
              {c} · ₹{formatNumber(channelCounts?.[c]?.sales ?? 0, { maximumFractionDigits: 0 })}
            </p>
          </button>
        ))}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border-primary bg-white shadow-sm p-3">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search order #…"
          className="w-48 rounded-md border border-border-primary bg-white px-3 py-1.5 text-sm text-text-primary placeholder:text-text-tertiary focus:border-accent-yellow focus:outline-none"
        />
        <select
          value={tier}
          onChange={(e) => setTier(e.target.value)}
          className="rounded-md border border-border-primary bg-white px-2 py-1.5 text-sm text-text-primary focus:border-accent-yellow focus:outline-none"
        >
          <option value="">All match tiers</option>
          {Object.entries(tierCounts).map(([t, count]) => (
            <option key={t} value={t}>
              {t} ({count.toLocaleString()})
            </option>
          ))}
        </select>
        <span className="ml-auto text-xs text-text-secondary">{total.toLocaleString()} orders match</span>
      </div>

      {error && <div className="rounded-md border border-error-mid bg-error-bg p-3 text-sm text-error-text">{error}</div>}
      {loading ? (
        <p className="text-sm text-text-secondary">Loading…</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border-primary bg-white shadow-sm">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border-primary text-xs text-text-secondary">
                <th className="px-4 py-2 font-medium">Order</th>
                <th className="px-4 py-2 font-medium">Date</th>
                <th className="px-4 py-2 text-right font-medium">Total</th>
                <th className="px-4 py-2 font-medium">Channel</th>
                <th className="px-4 py-2 font-medium">utm_source</th>
                <th className="px-4 py-2 font-medium">utm_campaign</th>
                <th className="px-4 py-2 font-medium">Tier</th>
                <th className="px-4 py-2 font-medium">Matched ad</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.order_id} className="border-b border-border-soft hover:bg-bg-surface">
                  <td className="px-4 py-2 text-text-primary">{row.name ?? "—"}</td>
                  <td className="px-4 py-2 text-text-secondary">{formatDate(row.created_at)}</td>
                  <td className="px-4 py-2 text-right font-mono text-xs text-text-primary">
                    {formatNumber(row.total_price, { maximumFractionDigits: 0 })}
                  </td>
                  <td className="px-4 py-2 text-text-secondary">{row.channel}</td>
                  <td className="px-4 py-2 text-text-secondary">{row.utm_source ?? "—"}</td>
                  <td className="max-w-[200px] truncate px-4 py-2 text-text-secondary" title={row.utm_campaign ?? ""}>
                    {row.utm_campaign ?? "—"}
                  </td>
                  <td className="px-4 py-2 text-text-secondary">{row.tier ?? "—"}</td>
                  <td className="max-w-[240px] truncate px-4 py-2 text-text-primary" title={row.matched_ad_name ?? ""}>
                    {row.matched_ad_name ?? "—"}
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-6 text-center text-text-secondary">
                    No orders match these filters.
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
