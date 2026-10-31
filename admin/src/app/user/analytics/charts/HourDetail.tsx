"use client";

import type { HourlyRow } from "@/lib/api";

/**
 * One hour, opened out: every metric the row holds, this day against
 * the comparison day.
 *
 * The table can only carry as many metrics as fit across a screen, and
 * several that matter are not among them -- the session and order
 * splits, what was excluded, what GA4 saw. Those are the figures you
 * want precisely when one hour looks wrong, which is the moment you
 * click it.
 *
 * Grouped rather than listed. "Sessions up, orders flat" is a different
 * story from "sessions flat, orders down", and the grouping is what
 * makes the two readable at a glance.
 */

type Fmt = (n: number | null | undefined) => string;

const money: Fmt = (n) =>
  n === null || n === undefined ? "—"
    : n.toLocaleString("en-IN", { style: "currency", currency: "INR",
        minimumFractionDigits: 0, maximumFractionDigits: 0 });
const money2: Fmt = (n) =>
  n === null || n === undefined ? "—"
    : n.toLocaleString("en-IN", { style: "currency", currency: "INR",
        minimumFractionDigits: 2, maximumFractionDigits: 2 });
const count: Fmt = (n) =>
  n === null || n === undefined ? "—" : Math.round(n).toLocaleString("en-IN");
const pct2: Fmt = (n) =>
  n === null || n === undefined ? "—" : `${(n * 100).toFixed(2)}%`;
const pct1: Fmt = (n) =>
  n === null || n === undefined ? "—" : `${(n * 100).toFixed(1)}%`;
const ratio: Fmt = (n) =>
  n === null || n === undefined ? "—" : `${n.toFixed(2)}x`;

type Item = {
  key: keyof HourlyRow;
  label: string;
  fmt: Fmt;
  /** A share: its change is points, not per cent of a per cent. */
  points?: boolean;
  /** Only cost inverts — a fall there is a saving. */
  lowerIsBetter?: boolean;
  /** No judgement: the traffic mix is a choice, not a score. */
  neutral?: boolean;
};

const GROUPS: { title: string; note?: string; items: Item[] }[] = [
  {
    title: "Traffic",
    note: "Paid means attributed, not bought — any utm_source that is not direct.",
    items: [
      { key: "sessions", label: "Sessions", fmt: count },
      { key: "sessions_paid", label: "Paid sessions", fmt: count },
      { key: "sessions_direct", label: "Direct sessions", fmt: count },
      { key: "sessions_meta", label: "Meta sessions", fmt: count },
      { key: "sessions_google", label: "Google sessions", fmt: count },
      { key: "pct_paid", label: "% paid", fmt: pct1, points: true, neutral: true },
      { key: "pct_direct", label: "% direct", fmt: pct1, points: true, neutral: true },
    ],
  },
  {
    title: "Conversion",
    items: [
      { key: "orders", label: "Orders", fmt: count },
      { key: "orders_paid", label: "Paid orders", fmt: count },
      { key: "orders_direct", label: "Direct orders", fmt: count },
      { key: "conversion_rate", label: "CR", fmt: pct2, points: true },
      { key: "conversion_rate_paid", label: "CR / paid", fmt: pct2, points: true },
      { key: "conversion_rate_direct", label: "CR / direct", fmt: pct2, points: true },
    ],
  },
  {
    title: "Revenue",
    items: [
      { key: "revenue", label: "Revenue", fmt: money },
      { key: "revenue_paid", label: "Paid revenue", fmt: money },
      { key: "aov", label: "AOV", fmt: money2 },
      { key: "revenue_per_session", label: "Rev / session", fmt: money2 },
      { key: "revenue_per_paid_session", label: "Rev / paid session", fmt: money2 },
      { key: "revenue_shopifyql", label: "ShopifyQL cross-check", fmt: money },
    ],
  },
  {
    title: "Spend",
    note: "Only Meta is measured hourly; Google and Kwikchat are daily totals shared across the hours.",
    items: [
      { key: "spend", label: "Spend", fmt: money },
      { key: "meta_spend", label: "Meta", fmt: money },
      { key: "google_spend", label: "Google", fmt: money },
      { key: "kwikchat_spend", label: "Kwikchat", fmt: money },
      { key: "meta_impressions", label: "Impressions (Meta)", fmt: count },
      { key: "cost_per_session", label: "Cost / session", fmt: money2, lowerIsBetter: true },
      { key: "cost_per_paid_session", label: "Cost / paid session", fmt: money2, lowerIsBetter: true },
    ],
  },
  {
    title: "Acquisition",
    items: [
      { key: "new_customers", label: "New customers", fmt: count },
      { key: "new_customer_revenue", label: "New-customer revenue", fmt: money },
      { key: "amer", label: "AMER", fmt: ratio },
    ],
  },
  {
    title: "GA4",
    note: "A different tool and a different denominator — ARPU divides by active users, not sessions. GA4 lags, so the newest hours are often absent.",
    items: [
      { key: "ga4_active_users", label: "Active users", fmt: count },
      { key: "ga4_sessions", label: "Sessions (GA4)", fmt: count },
      { key: "ga4_revenue", label: "Revenue (GA4)", fmt: money },
      { key: "ga4_arpu", label: "ARPU", fmt: money2 },
    ],
  },
  {
    title: "Not counted",
    note: "Cancelled, or returned without an exchange. Set aside rather than dropped silently, so a gap against Shopify's admin has an explanation.",
    items: [
      { key: "orders_excluded", label: "Orders excluded", fmt: count, neutral: true },
      { key: "revenue_excluded", label: "Revenue excluded", fmt: money, neutral: true },
    ],
  },
];

function Delta({ now, was, item }: {
  now: number | null; was: number | null; item: Item;
}) {
  if (now === null || now === undefined || !was) {
    return <span className="text-text-tertiary">—</span>;
  }
  // Colour and arrow answer different questions, so they are decided
  // separately. Grey says "no judgement" -- a traffic mix is a choice,
  // not a score. The arrow still says WHICH WAY, which is a fact and
  // worth keeping even where the direction is not good or bad.
  const tiny = (v: number) => Math.abs(v) < (item.points ? 0.05 : 0.005);
  if (item.points) {
    const pts = (now - was) * 100;
    const ink = tiny(pts) || item.neutral ? "text-text-tertiary"
      : pts > 0 ? "text-success-text" : "text-warning-text";
    return (
      <span className={ink}>
        {tiny(pts) ? "" : pts > 0 ? "↗ +" : "↘ "}{pts.toFixed(1)} pt
      </span>
    );
  }
  const ch = (now - was) / Math.abs(was);
  const good = item.lowerIsBetter ? ch < 0 : ch > 0;
  const ink = tiny(ch) || item.neutral ? "text-text-tertiary"
    : good ? "text-success-text" : "text-warning-text";
  return (
    <span className={ink}>
      {tiny(ch) ? "" : ch > 0 ? "↗ " : "↘ "}{Math.abs(ch * 100).toFixed(0)}%
    </span>
  );
}

export function HourDetail({ row, prev, dayLabel, prevLabel, partial, width }: {
  row: HourlyRow;
  prev: HourlyRow | undefined;
  dayLabel: string;
  prevLabel: string;
  /** Still filling: its figures are real, its comparison is not. */
  partial?: boolean;
  /** The VISIBLE width of the scrolling table, measured by the caller.
   *  100vw is wrong here -- the sidebar is not part of it, and the cell
   *  this sits in is as wide as a table nobody can see all of. */
  width?: number;
}) {
  const read = (r: HourlyRow | undefined, k: keyof HourlyRow) =>
    r ? ((r[k] as number | null) ?? null) : null;

  return (
    // Sticky, and exactly as wide as the visible table. The cell this
    // sits in spans a table far wider than the screen, so without both
    // the right-hand groups land off-screen and scroll away from the
    // row they describe.
    <div className="sticky left-0 bg-bg-muted/40 px-4 py-3"
         style={width ? { width } : undefined}>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-[12.5px] font-medium text-text-primary">
          {dayLabel} · {String(row.hour_of_day).padStart(2, "0")}:00
        </span>
        <span className="text-[11.5px] text-text-tertiary">against {prevLabel}</span>
        {partial && (
          <span className="text-[11px] text-text-tertiary">
            still filling — changes withheld
          </span>
        )}
      </div>

      {/* Two columns, not three. A third fits the width but not the
          CONTENT: rupee figures in the lakhs plus a label and two
          comparison columns clipped the rightmost group. */}
      <div className="mt-3 grid gap-x-10 gap-y-4 md:grid-cols-2">
        {GROUPS.map((g) => (
          <div key={g.title} className="min-w-0">
            <div className="text-[11px] uppercase tracking-wide text-text-tertiary">
              {g.title}
            </div>
            <table className="mt-1 w-full">
              <tbody>
                {g.items.map((it) => {
                  const now = read(row, it.key);
                  const was = read(prev, it.key);
                  return (
                    <tr key={String(it.key)} className="align-baseline">
                      <td className="py-[1px] pr-2 text-[11.5px] text-text-secondary">
                        {it.label}
                      </td>
                      <td className="py-[1px] pr-2 text-right text-[11.5px] tabular-nums text-text-primary">
                        {it.fmt(now)}
                      </td>
                      <td className="py-[1px] pr-2 text-right text-[11.5px] tabular-nums text-text-tertiary">
                        {it.fmt(was)}
                      </td>
                      <td className="py-[1px] text-right text-[11px] tabular-nums">
                        {partial ? <span className="text-text-tertiary">—</span>
                                 : <Delta now={now} was={was} item={it} />}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {g.note && (
              <p className="mt-1 text-[10.5px] leading-snug text-text-tertiary">{g.note}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
