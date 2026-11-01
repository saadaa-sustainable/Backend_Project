"use client";

import { useState, useSyncExternalStore } from "react";
import type { HourlyRow, HourlyTotals } from "@/lib/api";

/**
 * Contribution margin for the day so far, from the day's own numbers
 * and six assumptions.
 *
 * Every deduction below the Net Sales line is an estimate, not a
 * measurement — a rate someone chose. So the rates are inputs rather
 * than constants: the point of the section is to ask "at what COGS does
 * this day stop working", and that question needs the figure to move
 * while you type.
 *
 * Only the top two lines are measured. Everything under them is a
 * model, and the panel says so rather than letting a margin look like a
 * fact.
 */

const KEY = "tracker_pnl_assumptions";

type Assumptions = {
  cancelRate: number;   // share of sales lost to cancellation / RTO
  gstRate: number;      // GST charged on ad spend
  logistics: number;    // rupees per order
  pgRate: number;       // payment-gateway fee, share of net sales
  coinCost: number;     // rupees per order that shipped a coin
  cogsRate: number;     // share of net sales
};

const DEFAULTS: Assumptions = {
  cancelRate: 0.05,
  // 18% is the Indian GST on advertising services. Not given in the
  // brief, so it is a default to correct rather than a claim.
  gstRate: 0.18,
  logistics: 120,
  pgRate: 0.01,
  coinCost: 500,
  cogsRate: 0.28,
};

const FIELDS: { key: keyof Assumptions; label: string; pct: boolean; hint: string }[] = [
  { key: "cancelRate", label: "Cancellation / RTO", pct: true,
    hint: "Share of sales that never completes. Applied to total sales to give Net Sales." },
  { key: "cogsRate", label: "COGS", pct: true, hint: "Share of NET sales." },
  { key: "gstRate", label: "GST on ad spend", pct: true,
    hint: "18% is the Indian GST on advertising services — a default, not a measured figure." },
  { key: "pgRate", label: "PG fees", pct: true, hint: "Share of NET sales." },
  { key: "logistics", label: "Logistics / order", pct: false, hint: "Rupees per P&L order." },
  { key: "coinCost", label: "Silver coin / order", pct: false,
    hint: "Rupees per order that shipped a coin — per order, not per coin." },
];

/** One period's P&L. The day and each hour run through this, so the
 *  footer cannot drift from the rows beneath it. */
export type Pnl = {
  sales: number; orders: number; units: number; coinOrders: number;
  asp: number | null; aov: number | null;
  cancellation: number; netSales: number;
  adSpend: number; adGst: number; logistics: number;
  pgFees: number; coins: number; cogs: number;
  totalDeductions: number; cm: number; cmPct: number | null;
};

function computePnl(r: {
  pnl_sales: number | null; pnl_orders: number | null; pnl_qty: number | null;
  silver_coin_orders: number | null; spend: number | null;
}, a: Assumptions): Pnl {
  const sales = r.pnl_sales ?? 0;
  const orders = r.pnl_orders ?? 0;
  const units = r.pnl_qty ?? 0;
  const coinOrders = r.silver_coin_orders ?? 0;
  const adSpend = r.spend ?? 0;

  const cancellation = sales * a.cancelRate;
  const netSales = sales - cancellation;
  const adGst = adSpend * a.gstRate;
  const logistics = orders * a.logistics;
  const pgFees = netSales * a.pgRate;
  const coins = coinOrders * a.coinCost;
  const cogs = netSales * a.cogsRate;
  const totalDeductions = adSpend + adGst + logistics + pgFees + coins + cogs;
  const cm = netSales - totalDeductions;

  return {
    sales, orders, units, coinOrders,
    asp: units ? sales / units : null,
    aov: orders ? sales / orders : null,
    cancellation, netSales, adSpend, adGst, logistics, pgFees, coins, cogs,
    totalDeductions, cm, cmPct: netSales ? cm / netSales : null,
  };
}

const money = (n: number | null | undefined, dp = 0) =>
  n === null || n === undefined || !Number.isFinite(n) ? "—"
    : n.toLocaleString("en-IN", { style: "currency", currency: "INR",
        minimumFractionDigits: dp, maximumFractionDigits: dp });
const pct = (n: number | null | undefined, dp = 1) =>
  n === null || n === undefined || !Number.isFinite(n) ? "—" : `${(n * 100).toFixed(dp)}%`;

// A tiny external store rather than state loaded in an effect.
//
// localStorage does not exist on the server, so reading it during
// render would make the first client render disagree with the server's;
// reading it in an effect instead costs a second render of the whole
// panel. useSyncExternalStore is what React provides for exactly this:
// a server snapshot, a client snapshot, and a subscription.
let memo: Assumptions | null = null;
const listeners = new Set<() => void>();

function readStored(): Assumptions {
  // Every access guarded: a private window, blocked site data, or
  // corrupt JSON must not take the section down with it.
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch { /* fall through to defaults */ }
  return DEFAULTS;
}

/** Must return a STABLE reference while nothing has changed, or React
 *  re-renders for ever. Hence the memo. */
function getSnapshot(): Assumptions {
  if (memo === null) memo = readStored();
  return memo;
}
function getServerSnapshot(): Assumptions { return DEFAULTS; }
function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}
function save(next: Assumptions) {
  memo = next;
  try { localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* not essential */ }
  listeners.forEach((fn) => fn());
}

/** The change, as a line of its own. `lowerIsBetter` only for the
 *  deduction rows, where spending less is the win. */
function Change({ now, was, lowerIsBetter }: {
  now: number | null | undefined; was: number | null | undefined; lowerIsBetter?: boolean;
}) {
  if (now === null || now === undefined || !was) {
    return <span className="text-text-tertiary">—</span>;
  }
  const ch = (now - was) / Math.abs(was);
  const flat = Math.abs(ch) < 0.005;
  const good = lowerIsBetter ? ch < 0 : ch > 0;
  return (
    <span className={flat ? "text-text-tertiary" : good ? "text-success-text" : "text-warning-text"}>
      {flat ? "" : ch > 0 ? "↗ " : "↘ "}{Math.abs(ch * 100).toFixed(0)}%
    </span>
  );
}

export function LivePnl({ totals, rows, compare, compareRows, compareDay, liveHour }: {
  totals: HourlyTotals | null;
  /** The day's hours, for the breakdown under the summary. */
  rows?: HourlyRow[];
  /** The comparison day, already CLAMPED by the endpoint to the hours
   *  this day has reached — a part-finished day against a complete one
   *  flatters the complete one every time. */
  compare?: HourlyTotals | null;
  compareRows?: HourlyRow[];
  compareDay?: string;
  /** Still filling: its margin is real but its hour is not over. */
  liveHour?: number | null;
}) {
  const a = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const [open, setOpen] = useState(false);

  const set = (k: keyof Assumptions, v: number) => save({ ...a, [k]: v });

  if (!totals || !totals.pnl_orders) return null;

  const d = computePnl(totals, a);
  // Run through the SAME function, so a difference between the two is
  // the day's, never the arithmetic's.
  const c = compare ? computePnl(compare, a) : null;
  const byHour = new Map((compareRows ?? []).map((r) => [r.hour_of_day, r]));
  const { sales, orders, units, asp, aov, cancellation, netSales, cm, cmPct,
          totalDeductions } = d;

  const deductions: { label: string; value: number; was?: number; note?: string }[] = [
    { label: "Ad spend", value: d.adSpend, was: c?.adSpend, note: "Meta + Google + Kwikchat" },
    { label: "GST on ad spend", value: d.adGst, was: c?.adGst },
    { label: "Logistics", value: d.logistics, was: c?.logistics,
      note: `${orders.toLocaleString("en-IN")} orders` },
    { label: "PG fees", value: d.pgFees, was: c?.pgFees },
    { label: "Silver coin", value: d.coins, was: c?.coins,
      note: `${totals.silver_coin_orders.toLocaleString("en-IN")} orders` },
    { label: "COGS", value: d.cogs, was: c?.cogs },
  ];

  // Newest first, and only hours that actually sold: an hour with no
  // orders has no ASP, no AOV and a margin that is just negative ad
  // spend, which says nothing and crowds out the hours that do.
  const hourly = (rows ?? [])
    .filter((r) => (r.pnl_orders ?? 0) > 0)
    .map((r) => {
      const prev = byHour.get(r.hour_of_day);
      return {
        hour: r.hour_of_day,
        p: computePnl(r, a),
        q: prev ? computePnl(prev, a) : null,
      };
    })
    .sort((x, y) => y.hour - x.hour);
  const worstCm = Math.max(1, ...hourly.map((h) => Math.abs(h.p.cm)));

  return (
    <div className="rounded-md border border-border-primary bg-bg-white p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-[13px] font-medium text-text-primary">
          Live P&amp;L · day to date
        </h3>
        <button type="button" onClick={() => setOpen((v) => !v)}
                className="text-[11.5px] text-text-secondary underline underline-offset-2">
          {open ? "Hide assumptions" : "Assumptions"}
        </button>
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-x-5 gap-y-4 sm:grid-cols-5">
        <Kpi label="ASP" value={money(asp, 2)} was={c ? money(c.asp, 2) : undefined}
             now={asp} prev={c?.asp} day={compareDay}
             hint="Total sales ÷ units sold, with the gift coin excluded from units — it is not an item sold." />
        <Kpi label="AOV" value={money(aov, 2)} was={c ? money(c.aov, 2) : undefined}
             now={aov} prev={c?.aov} day={compareDay} hint="Total sales ÷ orders." />
        <Kpi label="Net sales" value={money(netSales)} was={c ? money(c.netSales) : undefined}
             now={netSales} prev={c?.netSales} day={compareDay}
             hint={`Total sales ${money(sales)} less ${pct(a.cancelRate)} cancellation.`} />
        <Kpi label="Contribution margin" value={money(cm)} was={c ? money(c.cm) : undefined}
             now={cm} prev={c?.cm} day={compareDay}
             hint="Net sales less every deduction below." />
        <Kpi label="CM %" value={pct(cmPct)} was={c ? pct(c.cmPct) : undefined}
             now={cmPct} prev={c?.cmPct} day={compareDay}
             hint="Contribution margin ÷ net sales." />
      </dl>

      {open && (
        <div className="mt-4 border-t border-border-soft pt-3">
          <div className="grid gap-x-5 gap-y-2 sm:grid-cols-3">
            {FIELDS.map((f) => (
              <label key={f.key} className="flex items-center justify-between gap-2 text-[11.5px]"
                     title={f.hint}>
                <span className="text-text-secondary">{f.label}</span>
                <span className="inline-flex items-baseline gap-1">
                  <input
                    type="number"
                    step={f.pct ? 0.1 : 1}
                    min={0}
                    value={f.pct ? +(a[f.key] * 100).toFixed(2) : a[f.key]}
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      if (!Number.isFinite(v) || v < 0) return;
                      set(f.key, f.pct ? v / 100 : v);
                    }}
                    className="w-20 rounded border border-border-primary bg-bg-white px-1.5 py-0.5 text-right tabular-nums"
                  />
                  <span className="text-text-tertiary">{f.pct ? "%" : "₹"}</span>
                </span>
              </label>
            ))}
          </div>
          <p className="mt-2 text-[10.5px] text-text-tertiary">
            Saved in this browser. Percentages on COGS and PG fees apply to
            <strong> net</strong> sales; cancellation applies to total sales.
          </p>
        </div>
      )}

      <div className="mt-4 grid gap-x-10 gap-y-1 md:grid-cols-2">
        <Line label="Total sales" value={money(sales)} was={c ? money(c.sales) : undefined} strong
              note={`${orders.toLocaleString("en-IN")} orders · ${units.toLocaleString("en-IN")} units`} />
        <Line label={`Cancellation / RTO (${pct(a.cancelRate)})`} value={`− ${money(cancellation)}`}
              was={c ? `− ${money(c.cancellation)}` : undefined} />
        <Line label="Net sales" value={money(netSales)} was={c ? money(c.netSales) : undefined}
              strong rule />
        <div />
        {deductions.map((row) => (
          <Line key={row.label} label={row.label} value={`− ${money(row.value)}`}
                was={row.was !== undefined ? `− ${money(row.was)}` : undefined} note={row.note} />
        ))}
        <Line label="Total deductions" value={`− ${money(totalDeductions)}`}
              was={c ? `− ${money(c.totalDeductions)}` : undefined} rule />
        <Line label="Contribution margin" value={money(cm)} was={c ? money(c.cm) : undefined}
              strong rule
              note={cmPct !== null ? `${pct(cmPct)} of net sales` : undefined} />
      </div>

      {hourly.length > 0 && (
        <div className="mt-5 border-t border-border-soft pt-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h4 className="text-[12px] font-medium text-text-primary">Hour by hour</h4>
            <span className="text-[10.5px] text-text-tertiary">
              Same assumptions. Bars are contribution margin, right for a profit
              and left for a loss, on one scale.
            </span>
          </div>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full border-collapse text-[11.5px]">
              <thead>
                <tr className="text-right text-[10.5px] uppercase tracking-wide text-text-tertiary">
                  <th className="py-1 pr-3 text-left font-medium">Hour</th>
                  <th className="py-1 pr-3 font-medium">Sales</th>
                  <th className="py-1 pr-3 font-medium">Orders</th>
                  <th className="py-1 pr-3 font-medium">ASP</th>
                  <th className="py-1 pr-3 font-medium">AOV</th>
                  <th className="py-1 pr-3 font-medium">Net sales</th>
                  <th className="py-1 pr-3 font-medium">Spend</th>
                  <th className="py-1 pr-3 font-medium">CM</th>
                  <th className="py-1 pr-3 font-medium">CM %</th>
                  {c && <th className="py-1 pr-3 font-medium">vs</th>}
                  <th className="w-[120px] py-1 font-medium" />
                </tr>
              </thead>
              <tbody>
                {hourly.map(({ hour, p, q }) => {
                  const live = liveHour != null && hour === liveHour;
                  const frac = Math.min(Math.abs(p.cm) / worstCm, 1) * 50;
                  return (
                    <tr key={hour} className="border-t border-border-soft text-right tabular-nums">
                      <td className="py-[3px] pr-3 text-left text-text-primary">
                        {String(hour).padStart(2, "0")}:00
                        {live && (
                          <span className="ml-1.5 text-[9px] uppercase tracking-wide text-text-tertiary">
                            live
                          </span>
                        )}
                      </td>
                      <td className="py-[3px] pr-3 text-text-primary">{money(p.sales)}</td>
                      <td className="py-[3px] pr-3 text-text-secondary">
                        {p.orders.toLocaleString("en-IN")}
                      </td>
                      <td className="py-[3px] pr-3 text-text-secondary">{money(p.asp, 0)}</td>
                      <td className="py-[3px] pr-3 text-text-secondary">{money(p.aov, 0)}</td>
                      <td className="py-[3px] pr-3 text-text-secondary">{money(p.netSales)}</td>
                      <td className="py-[3px] pr-3 text-text-secondary">{money(p.adSpend)}</td>
                      <td className={`py-[3px] pr-3 font-medium ${
                        p.cm >= 0 ? "text-success-text" : "text-warning-text"}`}>
                        {money(p.cm)}
                      </td>
                      <td className={`py-[3px] pr-3 ${
                        p.cm >= 0 ? "text-success-text" : "text-warning-text"}`}>
                        {pct(p.cmPct)}
                      </td>
                      {c && (
                        <td className="py-[3px] pr-3 text-[11px]">
                          {/* The same hour of the comparison day, by CM.
                              A margin that halved matters more than one
                              that merely fell. */}
                          {live ? <span className="text-text-tertiary">—</span>
                                : <Change now={p.cm} was={q?.cm} />}
                        </td>
                      )}
                      <td className="py-[3px]">
                        <div className="relative h-2.5" aria-hidden="true">
                          <div className="absolute inset-y-0 left-1/2 w-px bg-border-primary" />
                          <div
                            className={`absolute inset-y-0 ${
                              p.cm >= 0 ? "rounded-r-sm bg-success-mid" : "rounded-l-sm bg-warning-text"}`}
                            style={p.cm >= 0
                              ? { left: "50%", width: `${frac}%` }
                              : { right: "50%", width: `${frac}%` }}
                          />
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <p className="mt-3 border-t border-border-soft pt-2 text-[11px] leading-snug text-text-tertiary">
        Only total sales, orders and units are measured. Everything below the
        Net sales line is a model built from the rates above, and the day is
        still running — a margin here is an estimate, not a result. Orders
        tagged <code>inf</code> (daily report) and <code>Return_Prime</code> are
        excluded; cancelled orders are kept, because cancellation is applied as
        a rate rather than order by order.
      </p>
    </div>
  );
}

function Kpi({ label, value, was, now, prev, day, hint }: {
  label: string; value: string; was?: string;
  now?: number | null; prev?: number | null; day?: string; hint?: string;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] uppercase tracking-wide text-text-tertiary" title={hint}>
        {label}
      </dt>
      <dd className="mt-1 truncate tabular-nums text-xl font-semibold text-text-primary">
        {value}
      </dd>
      {was !== undefined && (
        <dd className="mt-0.5 flex flex-wrap items-baseline gap-x-1.5 text-[11.5px]">
          <span className="tabular-nums text-text-tertiary">{was}</span>
          <span className="text-[11px]"><Change now={now} was={prev} /></span>
          {day && <span className="text-[10px] text-text-tertiary">{day}</span>}
        </dd>
      )}
    </div>
  );
}

function Line({ label, value, was, note, strong, rule }: {
  label: string; value: string; was?: string; note?: string;
  strong?: boolean; rule?: boolean;
}) {
  return (
    <div className={`flex items-baseline justify-between gap-3 py-[3px] text-[12px] ${
      rule ? "border-t border-border-soft pt-1.5" : ""}`}>
      <span className={strong ? "font-medium text-text-primary" : "text-text-secondary"}>
        {label}
        {note && <span className="ml-1.5 text-[10.5px] text-text-tertiary">{note}</span>}
      </span>
      <span className="flex items-baseline gap-2 tabular-nums">
        {was !== undefined && (
          <span className="text-[11px] text-text-tertiary">{was}</span>
        )}
        <span className={strong ? "font-semibold text-text-primary" : "text-text-secondary"}>
          {value}
        </span>
      </span>
    </div>
  );
}
