"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ApiError,
  CustomerJourneyDetailResponse,
  CustomerJourneyOrderRow,
  fetchCustomerJourney,
  fetchCustomerJourneyDetail,
} from "@/lib/api";

const PAGE_SIZE = 50;

function formatNumber(n: number | null, opts: Intl.NumberFormatOptions = {}): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString(undefined, opts);
}

function formatDate(s: string | null): string {
  if (!s) return "—";
  return new Date(s).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/** shopify_order_attribution.customer_id is a full GID
 * ("gid://shopify/Customer/123"); shopify_customer_analytics (the
 * drill-down source) keys on the bare numeric id -- same prefix strip
 * the backend join does, mirrored here so the link target matches. */
function bareCustomerId(gid: string): string {
  return gid.split("/").pop() ?? gid;
}

function CustomerPanel({ customerId, onClose }: { customerId: string; onClose: () => void }) {
  const [detail, setDetail] = useState<CustomerJourneyDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchCustomerJourneyDetail(customerId)
      .then((res) => !cancelled && setDetail(res))
      .catch((err: unknown) => !cancelled && setError(err instanceof ApiError ? err.message : "Could not load this customer's journey."))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [customerId]);

  return (
    <div className="rounded-lg border border-warning-border bg-warning-bg/40 p-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-text-primary">Customer journey</h3>
        <button onClick={onClose} className="text-xs text-text-secondary hover:text-text-primary">
          Close ✕
        </button>
      </div>
      {error && <p className="mt-2 text-xs text-error-text">{error}</p>}
      {loading ? (
        <p className="mt-2 text-xs text-text-secondary">Loading…</p>
      ) : detail ? (
        <div className="mt-2 flex flex-col gap-3">
          <div className="flex flex-wrap gap-4 text-xs text-text-secondary">
            <span>
              <span className="font-medium text-text-primary">{detail.customer_name ?? "—"}</span> · {detail.email ?? "—"}
            </span>
            <span>
              Lifetime: {formatNumber(detail.lifetime_orders)} orders · ₹{formatNumber(detail.lifetime_spend, { maximumFractionDigits: 0 })}
            </span>
            <span>RFM: {detail.rfm_group ?? "—"}</span>
            <span>
              First order {formatDate(detail.first_order_date)} → last {formatDate(detail.last_order_date)}
            </span>
          </div>
          {detail.ads_touched.length > 0 && (
            <div className="text-xs text-text-secondary">
              <span className="font-medium text-text-primary">Ads touched: </span>
              {detail.ads_touched.join(", ")}
            </div>
          )}
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-warning-border text-text-secondary">
                <th className="px-3 py-1.5 font-medium">Order</th>
                <th className="px-3 py-1.5 font-medium">Date</th>
                <th className="px-3 py-1.5 text-right font-medium">Total</th>
                <th className="px-3 py-1.5 font-medium">Tier</th>
                <th className="px-3 py-1.5 font-medium">Matched ad</th>
              </tr>
            </thead>
            <tbody>
              {detail.orders.map((o) => (
                <tr key={o.order_id} className="border-b border-warning-border/60">
                  <td className="px-3 py-1.5 text-text-primary">{o.name ?? "—"}</td>
                  <td className="px-3 py-1.5 text-text-secondary">{formatDate(o.created_at)}</td>
                  <td className="px-3 py-1.5 text-right font-mono text-text-primary">
                    {formatNumber(o.total_price, { maximumFractionDigits: 0 })}
                  </td>
                  <td className="px-3 py-1.5 text-text-secondary">{o.tier ?? "—"}</td>
                  <td className="max-w-[220px] truncate px-3 py-1.5 text-text-primary" title={o.matched_ad_name ?? ""}>
                    {o.matched_ad_name ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

export function CustomerJourney() {
  const [rfmGroup, setRfmGroup] = useState("");
  const [onlyMatched, setOnlyMatched] = useState(false);
  const [search, setSearch] = useState("");
  const [selectedCustomer, setSelectedCustomer] = useState<string | null>(null);

  const [rows, setRows] = useState<CustomerJourneyOrderRow[]>([]);
  const [total, setTotal] = useState(0);
  const [rfmCounts, setRfmCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const filters = useMemo(
    () => ({
      rfm_group: rfmGroup || undefined,
      only_matched: onlyMatched,
      only_with_customer: true,
      search: search || undefined,
    }),
    [rfmGroup, onlyMatched, search],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchCustomerJourney({ ...filters, limit: PAGE_SIZE, offset: 0 })
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setTotal(res.total);
        setRfmCounts(res.rfm_counts);
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
      const res = await fetchCustomerJourney({ ...filters, limit: PAGE_SIZE, offset: rows.length });
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
        Ad → order → customer, in one row: which ad (if any) last-click-matched this order, and who the customer
        is — their RFM group, lifetime orders, and lifetime spend. Click a row for that customer&apos;s full order
        history and every ad that has touched them.
      </p>

      {/* RFM tiles */}
      <div className="flex flex-wrap gap-3">
        {Object.entries(rfmCounts).map(([group, count]) => (
          <button
            key={group}
            onClick={() => setRfmGroup((prev) => (prev === group ? "" : group))}
            className={`rounded-lg border p-3 text-left transition-colors ${
              rfmGroup === group ? "border-accent-yellow bg-accent-yellow-bg" : "border-border-primary bg-white hover:bg-bg-surface"
            }`}
          >
            <p className="text-lg font-semibold text-text-primary">{count.toLocaleString()}</p>
            <p className="mt-0.5 text-[11px] capitalize text-text-secondary">{group}</p>
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border-primary bg-white shadow-sm p-3">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search order #, customer name, or email…"
          className="w-72 rounded-md border border-border-primary bg-white px-3 py-1.5 text-sm text-text-primary placeholder:text-text-tertiary focus:border-accent-yellow focus:outline-none"
        />
        <label className="flex items-center gap-1.5 text-sm text-text-primary">
          <input type="checkbox" checked={onlyMatched} onChange={(e) => setOnlyMatched(e.target.checked)} />
          Only ad-matched orders
        </label>
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
                <th className="px-4 py-2 text-right font-medium">Total</th>
                <th className="px-4 py-2 font-medium">Matched ad</th>
                <th className="px-4 py-2 font-medium">Customer</th>
                <th className="px-4 py-2 font-medium">RFM</th>
                <th className="px-4 py-2 text-right font-medium">Lifetime orders</th>
                <th className="px-4 py-2 text-right font-medium">Lifetime spend</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const custId = row.customer_id ? bareCustomerId(row.customer_id) : null;
                return (
                  <>
                    <tr
                      key={row.order_id}
                      onClick={() => custId && setSelectedCustomer((prev) => (prev === custId ? null : custId))}
                      className={`border-b border-border-soft hover:bg-bg-surface ${custId ? "cursor-pointer" : ""}`}
                    >
                      <td className="px-4 py-2 text-text-primary">{row.name ?? "—"}</td>
                      <td className="px-4 py-2 text-right font-mono text-xs text-text-primary">
                        {formatNumber(row.total_price, { maximumFractionDigits: 0 })}
                      </td>
                      <td className="max-w-[220px] truncate px-4 py-2 text-text-secondary" title={row.matched_ad_name ?? ""}>
                        {row.matched_ad_name ?? "—"}
                      </td>
                      <td className="px-4 py-2 text-text-primary">{row.customer_name ?? "—"}</td>
                      <td className="px-4 py-2 capitalize text-text-secondary">{row.rfm_group ?? "—"}</td>
                      <td className="px-4 py-2 text-right font-mono text-xs text-text-primary">
                        {formatNumber(row.customer_lifetime_orders)}
                      </td>
                      <td className="px-4 py-2 text-right font-mono text-xs text-text-primary">
                        {formatNumber(row.customer_lifetime_spend, { maximumFractionDigits: 0 })}
                      </td>
                    </tr>
                    {selectedCustomer === custId && custId && (
                      <tr key={`${row.order_id}-panel`}>
                        <td colSpan={7} className="px-4 py-3">
                          <CustomerPanel customerId={custId} onClose={() => setSelectedCustomer(null)} />
                        </td>
                      </tr>
                    )}
                  </>
                );
              })}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-6 text-center text-text-secondary">
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
