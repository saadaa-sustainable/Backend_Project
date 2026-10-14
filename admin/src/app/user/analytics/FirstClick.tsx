"use client";

/**
 * First Click — where attribution credit MOVES between the first and
 * last touch.
 *
 * Deliberately not "the last-click table with first-click numbers in
 * it". Both ends of every order already sit in ga4_order_attribution,
 * so the figure no other section can give is the DIFFERENCE: which
 * sources introduce buyers that somebody else is credited for closing.
 *
 * Three counts per source, and each answers a different question:
 *
 *   Kept        introduced here AND closed here. Uncontested.
 *   Handed off  introduced here, closed elsewhere. Last click never
 *               counts these, so they are exactly what it understates.
 *   Captured    closed here, introduced elsewhere. Last click counts
 *               all of these, so they are what it overstates.
 *
 * They partition every order the source touched, so they add up. The
 * two revenue columns do NOT: an order the source both started and
 * closed appears under both, which is why they sit side by side rather
 * than being summed into a total.
 */
import { useEffect, useMemo, useState } from "react";
import { DateRangePicker } from "@/components/DateRangePicker";
import { ApiError, FirstClickRow, fetchFirstClick } from "@/lib/api";
import { ExportButton } from "@/components/ExportButton";
import { SectionHeader } from "./SectionChrome";

/** What the journey's two ends are keyed on.
 *
 *  Ad grain is the one that pays: 17.6% of orders change SOURCE between
 *  the first and last click, but 46% change AD. Most hand-offs happen
 *  inside one channel, between its own creatives, and the source view
 *  hides every one of them.
 *
 *  Campaign is absent on purpose — GA4's campaign id carries a
 *  per-session suffix, so first and last never match and the grain
 *  reported every campaign handing off 100% of its orders. */
const GRAIN_OPTIONS: { value: string; label: string }[] = [
  { value: "ad", label: "Ad" },
  { value: "adset", label: "Ad set" },
  { value: "source", label: "Source" },
];

const SORT_OPTIONS: { value: string; label: string }[] = [
  { value: "spend", label: "Spend" },  // hidden at source grain, see below
  { value: "first_click_revenue", label: "First-click revenue" },
  { value: "last_click_revenue", label: "Last-click revenue" },
  { value: "avg_days_to_convert", label: "Days to convert" },
  { value: "avg_sessions", label: "Sessions" },
];

function num(n: number | null | undefined, digits = 0) {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

export function FirstClick() {
  const [grain, setGrain] = useState("ad");
  const [sort, setSort] = useState("first_click_revenue");
  // Source grain has no spend, so a spend sort there would order every row
  // by NULL and look like the control had broken. Fall back instead.
  useEffect(() => {
    if (grain === "source" && sort === "spend") setSort("first_click_revenue");
  }, [grain, sort]);
  const [datePreset, setDatePreset] = useState<string>("last30");
  const [fromDate, setFromDate] = useState<string>(() => {
    const d = new Date(); d.setDate(d.getDate() - 29);
    return d.toISOString().slice(0, 10);
  });
  const [toDate, setToDate] = useState<string>(() => new Date().toISOString().slice(0, 10));

  // 200, not 50. At ad grain a 30-day window holds ~2,300 entities, and a
  // silent top-50 made the table read as the complete list of ads when it
  // was hiding 98% of them -- including every ad that only ever appears at
  // ONE end of a journey, which is exactly what this section exists to show.
  const [limit, setLimit] = useState(200);
  const [rows, setRows] = useState<FirstClickRow[]>([]);
  const [matched, setMatched] = useState(0);
  const [reattributed, setReattributed] = useState(0);
  const [ordersTotal, setOrdersTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const filters = useMemo(
    () => ({ grain, sort, from_date: fromDate, to_date: toDate, limit }),
    [grain, sort, fromDate, toDate, limit],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchFirstClick(filters)
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setMatched(res.matched ?? res.rows.length);
        setReattributed(res.orders_reattributed);
        setOrdersTotal(res.orders_total);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Could not reach the FastAPI backend. Is it running?");
      })
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, [filters]);

  const pct = ordersTotal ? (reattributed * 100) / ordersTotal : 0;

  return (
    <div className="flex flex-col gap-4">
      {/* "Full credit on each end, never split -- read a column, not a
          row" is the rule this whole section rests on. It is in Help as
          "first-vs-last", behind the ? -- a rule you learn once, not a
          paragraph above the controls every day. */}
      <SectionHeader title="First Click" helpId="first-vs-last" />

      <div className="flex flex-wrap items-center gap-2 border-b border-border-primary pb-3">
        <DateRangePicker
          value={{ from: fromDate, to: toDate }}
          preset={datePreset}
          align="left"
          onApply={(r, pk) => { setDatePreset(pk); setFromDate(r.from); setToDate(r.to); }}
        />
        <select
          value={grain}
          onChange={(e) => setGrain(e.target.value)}
          className="rounded-md border border-border-primary bg-white px-2 py-1.5 text-sm text-text-primary focus:border-accent-yellow focus:outline-none"
        >
          {GRAIN_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>By: {o.label}</option>
          ))}
        </select>
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value)}
          className="rounded-md border border-border-primary bg-white px-2 py-1.5 text-sm text-text-primary focus:border-accent-yellow focus:outline-none"
        >
          {SORT_OPTIONS.filter((o) => !(grain === "source" && o.value === "spend")).map((o) => (
            <option key={o.value} value={o.value}>Sort: {o.label}</option>
          ))}
        </select>
        <select
          value={limit}
          onChange={(e) => setLimit(Number(e.target.value))}
          className="rounded-md border border-border-primary bg-white px-2 py-1.5 text-sm text-text-primary focus:border-accent-yellow focus:outline-none"
        >
          {[50, 200, 1000, 5000].map((n) => (
            <option key={n} value={n}>Rows: {n === 5000 ? "All" : n}</option>
          ))}
        </select>
        <span className="ml-auto text-xs text-text-secondary">
          {matched > rows.length && (
            <span className="mr-2 rounded bg-amber-50 px-1.5 py-0.5 font-medium text-amber-800">
              showing {rows.length.toLocaleString()} of {matched.toLocaleString()}
            </span>
          )}
          {ordersTotal.toLocaleString()} orders ·{" "}
          <strong className="text-text-primary">{reattributed.toLocaleString()}</strong> reattributed
          {" "}({pct.toFixed(1)}%)
        </span>
        <ExportButton
          rows={rows as unknown as Record<string, unknown>[]}
          filename="first_vs_last_click"
          disabled={loading || !rows.length}
        />
      </div>

      {error && <div className="rounded-md border border-error-mid bg-error-bg p-3 text-sm text-error-text">{error}</div>}

      {loading ? (
        <p className="text-sm text-text-secondary">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-text-secondary">No attributed orders in this window.</p>
      ) : (
        <div className="max-h-[70vh] overflow-auto rounded-lg border border-border-primary bg-white shadow-sm">
          <table className="w-full min-w-max table-auto border-separate border-spacing-0 text-left text-sm">
            <thead>
              <tr>
                <th className="sticky left-0 top-0 z-30 h-10 whitespace-nowrap border-b border-r border-border-primary bg-bg-muted px-3 py-2 text-left align-middle text-[11px] font-medium">
                  {grain === "ad" ? "Ad" : grain === "adset" ? "Ad set" : "Source"}
                </th>
                {grain !== "source" && (
                  <th
                    title="The channel this belongs to. Also what explains a row showing a raw id: only Meta ad ids resolve to names, while kwikengage, sagepilot-ai and google put their own tokens in the same GA4 field."
                    className="sticky top-0 z-20 h-10 whitespace-nowrap border-b border-border-primary bg-bg-muted px-3 py-2 text-left align-middle text-[11px] font-medium"
                  >
                    Channel
                  </th>
                )}
                {([
                  // Spend is dropped entirely at source grain rather than
                  // rendered as a column of dashes: a "source" like META or
                  // affiliate is not a billable entity, so there is no number
                  // being withheld -- the question does not apply.
                  ...(grain === "source" ? [] : [["Spend", "Meta spend for this ad over the selected date range. A dash means Meta never billed this id — kwikengage, affiliate and google tokens share the same GA4 field and have no Meta spend to report."] as const]),
                  ["First-click revenue", "Full value of every order this one OPENED — the first session of the journey came from here. Not a fractional split."],
                  ["Last-click revenue", "Full value of every order this one CLOSED. Deliberately overlaps the column before it: the same order's value appears under both its opener and its closer, so do not add the two across."],
                  ["Days to convert", "Average days from first session to order, over the orders this one started."],
                  ["Sessions", "Average sessions before the order, over the orders this one started."],
                ] as const).map(([label, title]) => (
                  <th
                    key={label}
                    title={title}
                    className="sticky top-0 z-20 h-10 whitespace-nowrap border-b border-border-primary bg-bg-muted px-3 py-2 text-right align-middle text-[11px] font-medium"
                  >
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                // Opening more value than it closes. The gap is the credit
                // the last-click table moves to someone else. Flagged on the
                // first-click column, which is the one carrying the claim
                // last click never makes.
                const unbilled = r.first_click_revenue - r.last_click_revenue;
                return (
                  <tr key={`${r.source}-${r.channel}`} className="border-b border-border-soft hover:bg-bg-surface">
                    <td
                      className="sticky left-0 z-10 max-w-[300px] truncate border-r border-border-soft bg-white px-3 py-1.5 text-xs text-text-primary"
                      title={r.label === r.source ? r.source : `${r.label}  ·  ${r.source}`}
                    >
                      {r.label}
                    </td>
                    {grain !== "source" && (
                      <td className="border-b border-border-soft px-3 py-1.5 text-xs text-text-secondary">
                        {r.channel}
                      </td>
                    )}
                    {grain !== "source" && (
                      <td className="border-b border-border-soft px-3 py-1.5 text-right font-mono text-[11px] text-text-primary">
                        {r.spend === null || r.spend === undefined
                          ? <span className="text-text-tertiary" title="Meta never billed this id">—</span>
                          : num(r.spend)}
                      </td>
                    )}
                    <td
                      className={`border-b border-border-soft px-3 py-1.5 text-right font-mono text-[11px] ${unbilled > 0 ? "font-semibold text-amber-700" : "text-text-primary"}`}
                      title={unbilled > 0 ? `₹${num(unbilled)} more opened than closed — credit last click gives to another ad` : undefined}
                    >
                      {num(r.first_click_revenue)}
                    </td>
                    <td className="border-b border-border-soft px-3 py-1.5 text-right font-mono text-[11px] text-text-primary">{num(r.last_click_revenue)}</td>
                    <td className="border-b border-border-soft px-3 py-1.5 text-right font-mono text-[11px] text-text-primary">{num(r.avg_days_to_convert, 1)}</td>
                    <td className="border-b border-border-soft px-3 py-1.5 text-right font-mono text-[11px] text-text-primary">{num(r.avg_sessions, 1)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-xs text-text-tertiary">
        GA4 sees about 76% of orders, so these counts are a subset of Shopify&rsquo;s. Use them to compare
        sources against each other, not as an order total. Windowed on the order&rsquo;s IST day, the same
        boundary the Shopify columns elsewhere use.
      </p>
    </div>
  );
}
