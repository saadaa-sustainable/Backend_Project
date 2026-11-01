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
    title: "Total sales",
    items: [
      { key: "revenue", label: "Total sales", fmt: money },
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
    note: "Cancelled, returned without an exchange, or tagged Return_Prime — a return flowing back is not a sale. Report orders (inf) are still counted. Set aside rather than dropped silently, so a gap against Shopify's admin has an explanation.",
    items: [
      { key: "orders_excluded", label: "Orders excluded", fmt: count, neutral: true },
      { key: "revenue_excluded", label: "Revenue excluded", fmt: money, neutral: true },
    ],
  },
];

/** Relative change, the quantity every bar is drawn from.
 *
 *  Relative for EVERY metric, shares included, so one axis can carry
 *  all of them and the bars mean the same thing next to each other. A
 *  share's honest unit is points, so the LABEL still says points -- the
 *  bar answers "how far did this move", the label answers "by how
 *  much", and those are different questions.
 */
function relative(now: number | null, was: number | null): number | null {
  if (now === null || now === undefined || !was) return null;
  return (now - was) / Math.abs(was);
}

function Bar({ now, was, item, scale }: {
  now: number | null; was: number | null; item: Item; scale: number;
}) {
  const ch = relative(now, was);
  if (ch === null) {
    return <div className="h-3 rounded-sm bg-border-soft" style={{ opacity: 0.4 }} />;
  }
  // Clamped, not scaled to the largest: one metric moving 900% would
  // otherwise flatten every other bar to a sliver and the chart would
  // say nothing. The clamp is marked so an outlier is still visible AS
  // an outlier.
  const frac = Math.min(Math.abs(ch) / scale, 1);
  const clipped = Math.abs(ch) > scale;
  const good = item.lowerIsBetter ? ch < 0 : ch > 0;
  const ink = item.neutral ? "bg-border-primary"
    : good ? "bg-success-mid" : "bg-warning-text";

  return (
    <div className="relative h-3" aria-hidden="true">
      {/* The zero line. Bars grow right when the figure rose and left
          when it fell, so direction is readable before any colour. */}
      <div className="absolute inset-y-0 left-1/2 w-px bg-border-primary" />
      <div
        className={`absolute inset-y-0 ${ink} ${ch > 0 ? "rounded-r-sm" : "rounded-l-sm"}`}
        style={ch > 0
          ? { left: "50%", width: `${frac * 50}%` }
          : { right: "50%", width: `${frac * 50}%` }}
      />
      {clipped && (
        <div className={`absolute inset-y-0 w-0.5 bg-text-primary ${ch > 0 ? "right-0" : "left-0"}`} />
      )}
    </div>
  );
}

function Label({ now, was, item }: {
  now: number | null; was: number | null; item: Item;
}) {
  if (now === null || now === undefined || !was) {
    return <span className="text-text-tertiary">—</span>;
  }
  const tiny = (v: number) => Math.abs(v) < (item.points ? 0.05 : 0.005);
  if (item.points) {
    const pts = (now - was) * 100;
    const ink = tiny(pts) || item.neutral ? "text-text-tertiary"
      : pts > 0 ? "text-success-text" : "text-warning-text";
    return <span className={ink}>{pts > 0 ? "+" : ""}{pts.toFixed(1)} pt</span>;
  }
  const ch = (now - was) / Math.abs(was);
  const good = item.lowerIsBetter ? ch < 0 : ch > 0;
  const ink = tiny(ch) || item.neutral ? "text-text-tertiary"
    : good ? "text-success-text" : "text-warning-text";
  return <span className={ink}>{ch > 0 ? "+" : ""}{(ch * 100).toFixed(0)}%</span>;
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
      {/* One shared scale, so a bar in Spend means the same as a bar
          in Traffic. Clamped at 100% rather than fitted to the largest:
          a single metric up 900% would flatten every other bar to a
          sliver and the chart would say nothing. */}
      <div className="mt-1 text-[10.5px] text-text-tertiary">
        Bars show movement against the comparison hour, left for a fall
        and right for a rise, on one shared scale clamped at ±100%. A
        solid end-cap means the move ran past the scale. Shares are drawn
        relative so they sit on the same axis, but labelled in points.
      </div>

      <div className="mt-3 grid gap-x-10 gap-y-4 md:grid-cols-2">
        {GROUPS.map((g) => (
          <div key={g.title} className="min-w-0">
            <div className="text-[11px] uppercase tracking-wide text-text-tertiary">
              {g.title}
            </div>
            <div className="mt-1 space-y-[3px]">
              {g.items.map((it) => {
                const now = read(row, it.key);
                const was = read(prev, it.key);
                return (
                  <div key={String(it.key)}
                       className="grid items-center gap-x-2"
                       style={{ gridTemplateColumns: "minmax(0,1fr) 72px 110px 52px" }}>
                    <span className="truncate text-[11.5px] text-text-secondary">
                      {it.label}
                    </span>
                    <span className="text-right text-[11.5px] tabular-nums text-text-primary">
                      {it.fmt(now)}
                    </span>
                    {partial
                      ? <div className="h-3 rounded-sm bg-border-soft opacity-40" />
                      : <Bar now={now} was={was} item={it} scale={1} />}
                    <span className="text-right text-[11px] tabular-nums">
                      {partial ? <span className="text-text-tertiary">—</span>
                               : <Label now={now} was={was} item={it} />}
                    </span>
                  </div>
                );
              })}
            </div>
            {g.note && (
              <p className="mt-1 text-[10.5px] leading-snug text-text-tertiary">{g.note}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
