"use client";

/**
 * Customer Journey — one order at a time, as a sequence.
 *
 * This was a seven-column table of orders, and clicking a row opened a
 * panel UNDER it holding a second table of the same customer's orders:
 * the selected order appeared twice on screen, once in each table, and
 * the panel pushed every row below it down the page. Two tables of
 * orders is the clutter; the thing neither of them showed is the one
 * the section is named after — the ORDER of the touches.
 *
 * So: orders down the left, the chosen one's journey down the right.
 * Nothing moves when a different order is picked, and the sequence is
 * drawn as a sequence.
 */

import { useEffect, useMemo, useState } from "react";
import {
  ApiError,
  CustomerJourneyDetailResponse,
  CustomerJourneyOrderRow,
  fetchCustomerJourney,
  fetchCustomerJourneyDetail,
} from "@/lib/api";
import { SectionHeader, FilterRule, FilterCell, FieldLabel, VerdictBand, filterControlClass } from "./SectionChrome";
import { MarkClose } from "./Pictograms";

const PAGE_SIZE = 50;

function formatNumber(n: number | null, opts: Intl.NumberFormatOptions = {}): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString(undefined, opts);
}

function formatDate(s: string | null): string {
  if (!s) return "—";
  return new Date(s).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/** Day and clock, the way a timeline node wants it: "11 Oct · 14:22".
 *  Falls back to the date alone when the stamp carries no time. */
function formatStamp(s: string | null): string {
  if (!s) return "—";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return s;
  const day = d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  const hasTime = /\d\d:\d\d/.test(s);
  if (!hasTime) return day;
  return `${day} · ${d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false })}`;
}

function rupees(n: number | null): string {
  if (n === null || n === undefined) return "—";
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
}

/** shopify_order_attribution.customer_id is a full GID
 * ("gid://shopify/Customer/123"); shopify_customer_analytics (the
 * drill-down source) keys on the bare numeric id -- same prefix strip
 * the backend join does, mirrored here so the link target matches. */
function bareCustomerId(gid: string): string {
  return gid.split("/").pop() ?? gid;
}

/* ── the right pane: one order's journey ──────────────────────────── */

/**
 * The timeline is the customer's ORDER sequence, because that is the
 * sequence this endpoint actually knows. Per-order ad TOUCHES — the
 * first click, the mid touches, the closing click, each with its own
 * timestamp — are not in `customer-journey/{id}`; only the ad that was
 * matched to each order is. Drawing invented touch times would be the
 * one failure a journey view cannot afford, so the nodes are the
 * orders, each carrying the ad credited with it, and the distinct ads
 * seen across the whole relationship are listed beneath.
 */
function JourneyPane({
  row,
  customerId,
  onClose,
}: {
  row: CustomerJourneyOrderRow;
  customerId: string | null;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<CustomerJourneyDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!customerId) {
      setDetail(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    setDetail(null);
    fetchCustomerJourneyDetail(customerId)
      .then((res) => !cancelled && setDetail(res))
      .catch((err: unknown) => !cancelled && setError(err instanceof ApiError ? err.message : "Could not load this customer's journey."))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [customerId]);

  // Oldest first: a journey reads forwards. The endpoint's own order is
  // not relied on -- a reversed list would silently relabel which order
  // was the first.
  const ordered = useMemo(() => {
    const list = [...(detail?.orders ?? [])];
    list.sort((a, b) => new Date(a.created_at ?? 0).getTime() - new Date(b.created_at ?? 0).getTime());
    return list;
  }, [detail]);

  return (
    <div className="flex min-w-0 flex-1 flex-col gap-4 lg:basis-[560px]">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border-primary pb-3">
        <div className="min-w-0">
          <h3 className="m-0 font-mono text-[17px] font-semibold text-text-primary">{row.name ?? "—"}</h3>
          <p className="mt-1 truncate text-[12.5px] text-text-secondary">
            {formatDate(row.created_at)}
            {row.customer_name ? ` · ${row.customer_name}` : ""}
            {row.rfm_group ? ` · ${row.rfm_group}` : ""}
            {row.tier ? ` · tier ${row.tier}` : ""}
          </p>
        </div>
        <div className="flex items-start gap-4">
          <div className="text-right">
            <FieldLabel>Order value</FieldLabel>
            <div className="mt-1 text-[23px] font-medium leading-none tracking-[-0.02em] text-text-primary tabular-nums">
              {rupees(row.total_price)}
            </div>
          </div>
          <button
            onClick={onClose}
            title="Clear the selection"
            aria-label="Clear the selection"
            className="mt-0.5 text-text-tertiary transition-colors hover:text-text-primary"
          >
            <MarkClose />
          </button>
        </div>
      </div>

      {/* The ad credited to THIS order, from the row already in hand --
          shown before the detail request resolves, and still shown if
          it fails. It is the one fact the left-hand list was carrying. */}
      <div className="flex flex-wrap gap-x-10 gap-y-3">
        <div className="min-w-0">
          <FieldLabel>Matched ad</FieldLabel>
          <div className="mt-1 max-w-[380px] truncate text-[13px] text-text-primary" title={row.matched_ad_name ?? ""}>
            {row.matched_ad_name ?? "No ad matched"}
          </div>
        </div>
        {row.matched_campaign_name && (
          <div className="min-w-0">
            <FieldLabel>Campaign</FieldLabel>
            <div className="mt-1 max-w-[320px] truncate text-[13px] text-text-primary" title={row.matched_campaign_name}>
              {row.matched_campaign_name}
            </div>
          </div>
        )}
      </div>

      {error && <div className="bg-error-bg px-3 py-2 text-[12.5px] text-error-text">{error}</div>}
      {!customerId && (
        <p className="text-[12.5px] text-text-secondary">
          This order carries no customer id, so there is no relationship to walk.
        </p>
      )}
      {loading && <p className="text-[12.5px] text-text-secondary">Loading…</p>}

      {detail && (
        <>
          <div className="flex flex-col">
            <div className="border-b border-border-primary pb-1.5">
              <FieldLabel>
                Order sequence · {ordered.length} {ordered.length === 1 ? "order" : "orders"}
              </FieldLabel>
            </div>
            <div className="flex flex-col pt-3">
              {ordered.map((o, i) => {
                const isThis = o.order_id === row.order_id;
                const last = i === ordered.length - 1;
                const role = isThis
                  ? "This order"
                  : i === 0
                    ? "First order"
                    : last
                      ? "Most recent order"
                      : "Repeat order";
                return (
                  <div key={o.order_id} className="flex gap-3.5">
                    <div className="flex flex-col items-center pt-[7px]">
                      <span
                        className={`h-[9px] w-[9px] shrink-0 rounded-full ${
                          isThis ? "bg-accent-yellow" : i === 0 ? "bg-text-primary" : "bg-text-tertiary"
                        }`}
                      />
                      {!last && <span className="w-px flex-1 bg-border-primary" />}
                    </div>
                    <div className={`min-w-0 flex-1 ${last ? "" : "pb-5"}`}>
                      <div className="flex items-baseline justify-between gap-3">
                        <span
                          className={`truncate font-mono text-[13px] ${isThis ? "font-semibold text-text-primary" : "text-text-primary"}`}
                          title={o.matched_ad_name ?? ""}
                        >
                          {o.matched_ad_name ?? "No ad matched"}
                        </span>
                        <span className="shrink-0 text-[12px] text-text-tertiary tabular-nums">
                          {formatStamp(o.created_at)}
                        </span>
                      </div>
                      <div className={`mt-0.5 truncate text-[12.5px] ${isThis ? "text-accent-yellow" : "text-text-tertiary"}`}>
                        {role} · {o.name ?? "—"} · {rupees(o.total_price)}
                        {o.tier ? ` · tier ${o.tier}` : ""}
                        {o.matched_campaign_name ? ` · ${o.matched_campaign_name}` : ""}
                      </div>
                    </div>
                  </div>
                );
              })}
              {ordered.length === 0 && (
                <p className="text-[12.5px] text-text-secondary">No orders recorded for this customer.</p>
              )}
            </div>
          </div>

          {detail.ads_touched.length > 0 && (
            <div className="flex flex-col gap-2">
              <div className="border-b border-border-primary pb-1.5">
                <FieldLabel>Ads touched · {detail.ads_touched.length}</FieldLabel>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {detail.ads_touched.map((ad) => (
                  <span key={ad} className="bg-bg-muted px-2 py-0.5 font-mono text-[11.5px] text-text-secondary">
                    {ad}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* The customer's own facts, on a rule beneath the journey --
              they describe the relationship, not this order. */}
          <div className="flex flex-wrap gap-x-10 gap-y-4 border-t border-border-primary pt-3.5">
            <div className="min-w-0">
              <FieldLabel>Customer</FieldLabel>
              <div className="mt-1 truncate text-[13px] text-text-primary">{detail.customer_name ?? "—"}</div>
            </div>
            <div className="min-w-0">
              <FieldLabel>Email</FieldLabel>
              <div className="mt-1 max-w-[240px] truncate text-[13px] text-text-primary" title={detail.email ?? ""}>
                {detail.email ?? "—"}
              </div>
            </div>
            <div>
              <FieldLabel>Lifetime orders</FieldLabel>
              <div className="mt-1 text-[13px] text-text-primary tabular-nums">
                {formatNumber(detail.lifetime_orders)}
              </div>
            </div>
            <div>
              <FieldLabel>Lifetime spend</FieldLabel>
              <div className="mt-1 text-[13px] text-text-primary tabular-nums">
                {rupees(detail.lifetime_spend)}
              </div>
            </div>
            <div>
              <FieldLabel>RFM</FieldLabel>
              <div className="mt-1 text-[13px] capitalize text-text-primary">{detail.rfm_group ?? "—"}</div>
            </div>
            {detail.predicted_spend_tier && (
              <div>
                <FieldLabel>Predicted tier</FieldLabel>
                <div className="mt-1 text-[13px] text-text-primary">{detail.predicted_spend_tier}</div>
              </div>
            )}
            <div>
              <FieldLabel>First order → last</FieldLabel>
              <div className="mt-1 text-[13px] text-text-primary tabular-nums">
                {formatDate(detail.first_order_date)} → {formatDate(detail.last_order_date)}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

/* ── the section ──────────────────────────────────────────────────── */

export function CustomerJourney() {
  const [rfmGroup, setRfmGroup] = useState("");
  const [onlyMatched, setOnlyMatched] = useState(false);
  const [search, setSearch] = useState("");
  // Keyed on the ORDER, not the customer: two orders from the same
  // buyer are two different journeys to read, and the old
  // customer-keyed selection opened both rows at once.
  const [selectedOrderId, setSelectedOrderId] = useState<string | null>(null);

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

  const selectedRow = useMemo(
    () => rows.find((r) => r.order_id === selectedOrderId) ?? null,
    [rows, selectedOrderId],
  );

  return (
    <div className="flex flex-col gap-5">
      <SectionHeader title="Customer Journey" helpId="first-vs-last" />

      <FilterRule
        actions={
          <span className="text-[11.5px] text-text-tertiary tabular-nums">
            {total.toLocaleString()} orders match
          </span>
        }
      >
        <FilterCell label="Order, customer or email" className="w-72" htmlFor="cj-search">
          <input
            id="cj-search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search…"
            className={filterControlClass}
          />
        </FilterCell>

        <FilterCell label="Ad match">
          <label className="flex items-center gap-2 py-1 text-[13px] text-text-primary">
            <input type="checkbox" checked={onlyMatched} onChange={(e) => setOnlyMatched(e.target.checked)} />
            Only ad-matched orders
          </label>
        </FilterCell>
      </FilterRule>

      {/* RFM, as a band sized by count rather than six equal tiles.
          Still the same filter: clicking a field narrows the list,
          clicking it again clears it. */}
      {Object.keys(rfmCounts).length > 0 && (
        <VerdictBand
          verdicts={Object.entries(rfmCounts).map(([group, count]) => ({
            key: group,
            label: group,
            count,
            tone: "report" as const,
            selected: rfmGroup === group,
            onSelect: () => setRfmGroup((prev) => (prev === group ? "" : group)),
          }))}
        />
      )}

      {error && <div className="bg-error-bg px-3 py-2 text-sm text-error-text">{error}</div>}

      {loading ? (
        <p className="text-sm text-text-secondary">Loading…</p>
      ) : (
        <div className="flex flex-wrap items-start gap-x-10 gap-y-6">
          {/* ── orders, down the left ──────────────────────────────── */}
          <div className="flex min-w-0 flex-1 flex-col lg:basis-[400px]">
            <div className="flex items-baseline justify-between border-b border-border-primary pb-1.5">
              <FieldLabel>Orders</FieldLabel>
              <span className="text-[11.5px] text-text-tertiary tabular-nums">
                {rows.length.toLocaleString()} of {total.toLocaleString()}
              </span>
            </div>
            <div className="max-h-[70vh] overflow-y-auto">
              {rows.map((row) => {
                const on = row.order_id === selectedOrderId;
                return (
                  <button
                    key={row.order_id}
                    type="button"
                    aria-pressed={on}
                    onClick={() => setSelectedOrderId((prev) => (prev === row.order_id ? null : row.order_id))}
                    title={
                      `${row.customer_name ?? "no customer"}  ·  ${row.rfm_group ?? "no RFM group"}  ·  ` +
                      `${formatNumber(row.customer_lifetime_orders)} lifetime orders, ` +
                      `${rupees(row.customer_lifetime_spend)} lifetime spend`
                    }
                    className={`flex w-full items-center justify-between gap-3 border-t border-l-2 border-border-soft py-2.5 pr-1 pl-3 text-left transition-colors first:border-t-0 ${
                      on ? "border-l-accent-yellow bg-accent-yellow-bg" : "border-l-transparent hover:bg-bg-surface"
                    }`}
                  >
                    <div className="min-w-0">
                      <div className="font-mono text-[13px] text-text-primary">{row.name ?? "—"}</div>
                      <div className="mt-0.5 truncate text-[12px] text-text-tertiary">
                        {formatDate(row.created_at)} · {row.matched_ad_name ?? "no ad matched"}
                      </div>
                    </div>
                    <div className="shrink-0 text-[13px] text-text-primary tabular-nums">
                      {rupees(row.total_price)}
                    </div>
                  </button>
                );
              })}
              {rows.length === 0 && (
                <p className="py-6 text-center text-sm text-text-secondary">No orders match these filters.</p>
              )}
            </div>
            {rows.length < total && (
              <div className="flex justify-center border-t border-border-primary pt-2.5">
                <button
                  onClick={loadMore}
                  disabled={loadingMore}
                  className="text-[12.5px] text-text-secondary transition-colors hover:text-text-primary disabled:opacity-40"
                >
                  {loadingMore ? "Loading…" : `Load more (${rows.length} of ${total})`}
                </button>
              </div>
            )}
          </div>

          {/* ── the chosen order's journey, down the right ──────────── */}
          {selectedRow ? (
            <JourneyPane
              key={selectedRow.order_id}
              row={selectedRow}
              customerId={selectedRow.customer_id ? bareCustomerId(selectedRow.customer_id) : null}
              onClose={() => setSelectedOrderId(null)}
            />
          ) : (
            <div className="flex min-w-0 flex-1 flex-col lg:basis-[560px]">
              <div className="border-b border-border-primary pb-1.5">
                <FieldLabel>Journey</FieldLabel>
              </div>
              <p className="pt-3 text-[13px] text-text-secondary">
                Pick an order on the left to walk the customer behind it — every order they have placed, in
                sequence, with the ad credited to each and what the relationship is worth.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
