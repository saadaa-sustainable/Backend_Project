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

const SORT_OPTIONS: { value: string; label: string }[] = [
  { value: "handed_off", label: "Handed off" },
  { value: "captured", label: "Captured" },
  { value: "kept", label: "Kept" },
  { value: "first_click_revenue", label: "First-click revenue" },
  { value: "last_click_revenue", label: "Last-click revenue" },
  { value: "avg_days_to_convert", label: "Days to convert" },
];

function num(n: number | null | undefined, digits = 0) {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

export function FirstClick() {
  const [sort, setSort] = useState("handed_off");
  const [datePreset, setDatePreset] = useState<string>("last30");
  const [fromDate, setFromDate] = useState<string>(() => {
    const d = new Date(); d.setDate(d.getDate() - 29);
    return d.toISOString().slice(0, 10);
  });
  const [toDate, setToDate] = useState<string>(() => new Date().toISOString().slice(0, 10));

  const [rows, setRows] = useState<FirstClickRow[]>([]);
  const [reattributed, setReattributed] = useState(0);
  const [ordersTotal, setOrdersTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const filters = useMemo(
    () => ({ sort, from_date: fromDate, to_date: toDate, limit: 50 }),
    [sort, fromDate, toDate],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchFirstClick(filters)
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
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
      <p className="text-sm text-text-secondary">
        Both ends of each order&rsquo;s journey, from GA4. A source&rsquo;s work splits three ways:
        orders it <strong>kept</strong> (introduced and closed), orders it <strong>handed off</strong>{" "}
        (introduced, then someone else closed) and orders it <strong>captured</strong> (closed, but
        someone else introduced). Last-click reporting counts the first two groups&rsquo; closers only, so a
        source whose handed-off count far exceeds its captured count is doing work the Last Click UTM
        section bills to another channel.
      </p>

      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border-primary bg-white shadow-sm p-3">
        <DateRangePicker
          value={{ from: fromDate, to: toDate }}
          preset={datePreset}
          align="left"
          onApply={(r, pk) => { setDatePreset(pk); setFromDate(r.from); setToDate(r.to); }}
        />
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value)}
          className="rounded-md border border-border-primary bg-white px-2 py-1.5 text-sm text-text-primary focus:border-accent-yellow focus:outline-none"
        >
          {SORT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>Sort: {o.label}</option>
          ))}
        </select>
        <span className="ml-auto text-xs text-text-secondary">
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
                  Source
                </th>
                {([
                  ["Kept", "Introduced here and closed here. Uncontested by any other source."],
                  ["Handed off", "Introduced here, closed elsewhere. Last click never counts these."],
                  ["Captured", "Closed here, introduced elsewhere. Last click counts all of these."],
                  ["First-click revenue", "Value of every order this source introduced."],
                  ["Last-click revenue", "Value of every order this source closed. Overlaps the column before it — an order kept counts in both."],
                  ["Days to convert", "Average days from first session to order, over the orders this source started."],
                  ["Sessions", "Average sessions before the order, over the orders this source started."],
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
                // Doing more introducing than closing. The gap is the
                // credit the last-click table moves to someone else.
                const net = r.handed_off - r.captured;
                return (
                  <tr key={r.source} className="border-b border-border-soft hover:bg-bg-surface">
                    <td className="sticky left-0 z-10 max-w-[220px] truncate border-r border-border-soft bg-white px-3 py-1.5 text-xs text-text-primary" title={r.source}>
                      {r.source}
                    </td>
                    <td className="border-b border-border-soft px-3 py-1.5 text-right font-mono text-[11px] text-text-primary">{num(r.kept)}</td>
                    <td
                      className={`border-b border-border-soft px-3 py-1.5 text-right font-mono text-[11px] ${net > 0 ? "font-semibold text-amber-700" : "text-text-primary"}`}
                      title={net > 0 ? `${num(net)} more orders introduced than closed` : undefined}
                    >
                      {num(r.handed_off)}
                    </td>
                    <td className="border-b border-border-soft px-3 py-1.5 text-right font-mono text-[11px] text-text-primary">{num(r.captured)}</td>
                    <td className="border-b border-border-soft px-3 py-1.5 text-right font-mono text-[11px] text-text-primary">{num(r.first_click_revenue)}</td>
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
