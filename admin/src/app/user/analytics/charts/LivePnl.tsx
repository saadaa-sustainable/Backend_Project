"use client";

import { useState, useSyncExternalStore } from "react";
import type { HourlyTotals } from "@/lib/api";

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

export function LivePnl({ totals }: { totals: HourlyTotals | null }) {
  const a = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const [open, setOpen] = useState(false);

  const set = (k: keyof Assumptions, v: number) => save({ ...a, [k]: v });

  if (!totals || !totals.pnl_orders) return null;

  const sales = totals.pnl_sales;
  const orders = totals.pnl_orders;
  const units = totals.pnl_qty;

  const asp = units ? sales / units : null;
  const aov = orders ? sales / orders : null;

  const cancellation = sales * a.cancelRate;
  const netSales = sales - cancellation;

  const adSpend = totals.spend;
  const adGst = adSpend * a.gstRate;
  const logistics = orders * a.logistics;
  const pgFees = netSales * a.pgRate;
  const coins = totals.silver_coin_orders * a.coinCost;
  const cogs = netSales * a.cogsRate;

  const deductions: { label: string; value: number; note?: string }[] = [
    { label: "Ad spend", value: adSpend, note: "Meta + Google + Kwikchat" },
    { label: "GST on ad spend", value: adGst },
    { label: "Logistics", value: logistics, note: `${orders.toLocaleString("en-IN")} orders` },
    { label: "PG fees", value: pgFees },
    { label: "Silver coin", value: coins,
      note: `${totals.silver_coin_orders.toLocaleString("en-IN")} orders` },
    { label: "COGS", value: cogs },
  ];
  const totalDeductions = deductions.reduce((s, d) => s + d.value, 0);
  const cm = netSales - totalDeductions;
  const cmPct = netSales ? cm / netSales : null;

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
        <Kpi label="ASP" value={money(asp, 2)}
             hint="Total sales ÷ units sold, with the gift coin excluded from units — it is not an item sold." />
        <Kpi label="AOV" value={money(aov, 2)} hint="Total sales ÷ orders." />
        <Kpi label="Net sales" value={money(netSales)}
             hint={`Total sales ${money(sales)} less ${pct(a.cancelRate)} cancellation.`} />
        <Kpi label="Contribution margin" value={money(cm)}
             hint="Net sales less every deduction below." />
        <Kpi label="CM %" value={pct(cmPct)} hint="Contribution margin ÷ net sales." />
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
        <Line label="Total sales" value={money(sales)} strong
              note={`${orders.toLocaleString("en-IN")} orders · ${units.toLocaleString("en-IN")} units`} />
        <Line label={`Cancellation / RTO (${pct(a.cancelRate)})`} value={`− ${money(cancellation)}`} />
        <Line label="Net sales" value={money(netSales)} strong rule />
        <div />
        {deductions.map((d) => (
          <Line key={d.label} label={d.label} value={`− ${money(d.value)}`} note={d.note} />
        ))}
        <Line label="Total deductions" value={`− ${money(totalDeductions)}`} rule />
        <Line label="Contribution margin" value={money(cm)} strong rule
              note={cmPct !== null ? `${pct(cmPct)} of net sales` : undefined} />
      </div>

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

function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] uppercase tracking-wide text-text-tertiary" title={hint}>
        {label}
      </dt>
      <dd className="mt-1 truncate tabular-nums text-xl font-semibold text-text-primary">
        {value}
      </dd>
    </div>
  );
}

function Line({ label, value, note, strong, rule }: {
  label: string; value: string; note?: string; strong?: boolean; rule?: boolean;
}) {
  return (
    <div className={`flex items-baseline justify-between gap-3 py-[3px] text-[12px] ${
      rule ? "border-t border-border-soft pt-1.5" : ""}`}>
      <span className={strong ? "font-medium text-text-primary" : "text-text-secondary"}>
        {label}
        {note && <span className="ml-1.5 text-[10.5px] text-text-tertiary">{note}</span>}
      </span>
      <span className={`tabular-nums ${strong ? "font-semibold text-text-primary" : "text-text-secondary"}`}>
        {value}
      </span>
    </div>
  );
}
