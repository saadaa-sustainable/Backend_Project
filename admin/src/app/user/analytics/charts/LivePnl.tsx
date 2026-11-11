"use client";

import { useState, useSyncExternalStore } from "react";
import type { HourlyRow, HourlyTotals } from "@/lib/api";

/**
 * Contribution margin for the window, from Shopify's own Total sales
 * and a set of editable assumptions.
 *
 * The model is the one the standalone tracker (`tracker/index.html`)
 * runs, ported line for line so the two pages cannot disagree: the
 * same defaults, the same storage key, the same arithmetic.
 *
 * Only Total sales and its breakdown are measured. Everything under
 * Realisable sales is a model, and the panel says so rather than
 * letting a margin look like a fact.
 */

const KEY = "tracker_pnl_assumptions";

type Assumptions = {
  /** A forward-looking allowance for cancellations still to come.
   *  ZERO by default: Shopify has already taken cancellations out of
   *  Total sales via the Sales reversals line, so a standing allowance
   *  deducted them twice. Signed. */
  extraCancelRate: number;
  /** Dispatched, refused or undeliverable, carried back. Shopify books
   *  none of it. Zero until someone sets it. */
  rtoRate: number;
  /** Returns BEYOND the reversals Shopify has already booked. */
  returnsRate: number;
  /** Share of orders that come back as an exchange. */
  exchangeRate: number;
  /** Rupees to service one exchange. */
  exchangeCost: number;
  gstRate: number;      // GST charged on ad spend
  logistics: number;    // rupees per order
  pgRate: number;       // payment-gateway fee, share of realisable sales
  coinCost: number;     // rupees per coin shipped
  cogsRate: number;     // share of realisable sales
  /** Not a cost: the margin to clear after ads. Only sets the second
   *  ROAS on the rail. */
  minMargin: number;
  /** Override the MEASURED ad spend with a cost per order. NULL means
   *  "follow the measured figure"; zero means spend nothing. */
  adPerOrder: number | null;
  /** Migration marker, shared with the standalone tracker. */
  pnlV?: number;
};

const DEFAULTS: Assumptions = {
  extraCancelRate: 0,
  rtoRate: 0,
  returnsRate: 0,
  // 1% is MEASURED across the whole order history; the Exchange tag
  // lands days after the order, so a recent window understates it.
  exchangeRate: 0.01,
  exchangeCost: 200,
  // 18% is the Indian GST on advertising services -- a default to
  // correct rather than a claim.
  gstRate: 0.18,
  logistics: 120,
  pgRate: 0.01,
  coinCost: 500,
  cogsRate: 0.28,
  minMargin: 0.15,
  adPerOrder: null,
};

type Field = { key: Exclude<keyof Assumptions, "pnlV">; label: string; pct: boolean;
               hint: string; signed?: boolean };
const FIELDS: Field[] = [
  { key: "extraCancelRate", label: "Further cancellation", pct: true, signed: true,
    hint: "Cancellations are already out of Total sales. Set this only as a forward-looking allowance for a day still running." },
  { key: "rtoRate", label: "RTO impact", pct: true, signed: true,
    hint: "Dispatched, refused or undeliverable, carried back. Shopify books none of it." },
  { key: "returnsRate", label: "Incremental returns", pct: true, signed: true,
    hint: "Returns still to come, beyond the reversals Shopify has already booked." },
  { key: "exchangeRate", label: "Exchange rate", pct: true,
    hint: "Share of orders exchanged. Default 1%, measured across the whole order history." },
  { key: "exchangeCost", label: "Cost / exchange", pct: false,
    hint: "Rupees per exchange: a second dispatch plus a collection, on top of logistics." },
  { key: "cogsRate", label: "COGS", pct: true, hint: "Share of realisable sales." },
  { key: "gstRate", label: "GST on ad spend", pct: true,
    hint: "18% is the Indian GST on advertising services — a default, not a measured figure." },
  { key: "pgRate", label: "PG fees", pct: true, hint: "Share of realisable sales." },
  { key: "logistics", label: "Logistics / order", pct: false, hint: "Rupees per order placed." },
  { key: "coinCost", label: "Silver coin / coin", pct: false,
    hint: "Rupees per coin shipped — an order can carry more than one." },
  { key: "adPerOrder", label: "Ad spend / order", pct: false,
    hint: "Shows the measured figure. Edit it to model a different cost of acquisition." },
  { key: "minMargin", label: "Target margin", pct: true,
    hint: "Costs nothing. It only sets the second ROAS on the rail." },
];

/** What computePnl reads. A day total and an hour row both fit. */
type PnlInput = {
  pnl_sales?: number | null; pnl_orders?: number | null; pnl_qty?: number | null;
  silver_coin_orders?: number | null; silver_coin_qty?: number | null;
  spend?: number | null; meta_spend?: number | null; google_spend?: number | null;
  kwikchat_spend?: number | null;
  pnl_cancelled_orders?: number | null; pnl_refunds?: number | null;
  rp_return_value?: number | null; rp_return_orders?: number | null;
  rp_return_qty?: number | null;
  pnl_exchange_orders?: number | null;
  shopify_total_sales?: number | null; shopify_returns?: number | null;
  shopify_gross_sales?: number | null; shopify_discounts?: number | null;
  shopify_shipping?: number | null; shopify_return_fees?: number | null;
  shopify_taxes?: number | null; shopify_duties?: number | null;
  shopify_additional_fees?: number | null;
  ql_net_sales?: number | null; ql_orders?: number | null; ql_orders_all?: number | null;
};

/** How Shopify reaches Total sales. Discounts and reversals are kept
 *  NEGATIVE, as stored, so both identities are plain additions. */
type Breakdown = {
  gross: number; discounts: number; reversals: number; netSales: number;
  shipping: number; returnFees: number; taxes: number; other: number; total: number;
  /** Do the lines reach the headline? Drawn only when they do. */
  ok: boolean;
  /** Shopify's own order count and the AOV its admin shows. */
  orders: number | null; aov: number | null;
  revPerOrder: number | null; discPerOrder: number | null;
};

/** One period's P&L. The window and each hour run through this, so the
 *  summary cannot drift from the rows beneath it. */
export type Pnl = {
  bd: Breakdown | null;
  /** Shopify's OWN Total sales, already net of cancellations. */
  sales: number;
  /** Every order placed, cancelled or not. */
  orders: number; units: number;
  coinOrders: number; coinQty: number;
  cancelledOrders: number; cancelPct: number | null; coinPct: number | null;
  refunds: number; extraCancellation: number; rto: number; incReturns: number;
  /** Returns filed through Return Prime against these orders: MEASURED,
   *  dated by the order. Null where returns are not loaded. */
  returns: number | null; returnOrders: number; returnUnits: number;
  returnPct: number | null;
  /** Realisable sales: Total sales less refunds and the allowances. */
  net: number;
  asp: number | null; aov: number | null;
  /** Ad spend: measured, unless overridden per order. */
  adAssumed: boolean; measuredAd: number; adSpend: number;
  /** Orders advertising could have bought: exchange legs out. */
  adOrders: number; exchangeOrders: number | null; adPerOrder: number | null;
  metaSpend: number | null; googleSpend: number | null; kwikSpend: number | null;
  adGst: number; logistics: number; pgFees: number; coins: number;
  exchanges: number; exchangeCost: number; cogs: number;
  totalDed: number; cm: number; cmPct: number | null;
  /** Contribution with nothing taken for advertising yet. */
  preAd: number; preAdMargin: number | null;
  roas: number | null; beRoas: number | null; targetRoas: number | null;
};

function computePnl(r: PnlInput, a: Assumptions): Pnl {
  // Shopify's own Total sales, so the P&L opens on the number the
  // Shopify admin shows. Falls back to the order-derived figure only
  // for rows written before the column existed.
  const sales = r.shopify_total_sales ?? r.pnl_sales ?? 0;
  const orders = r.pnl_orders ?? 0;
  const units = r.pnl_qty ?? 0;
  const coinOrders = r.silver_coin_orders ?? 0;
  // COINS, not coin orders: an order can ship more than one.
  const coinQty = r.silver_coin_qty ?? coinOrders;

  // Ad spend is measured, and can be overridden per order. The
  // denominator is NOT the order count: an exchange leg is the second
  // half of a sale already paid for, so no advertising bought it.
  const measuredAd = r.spend ?? 0;
  const exchangeOrders = r.pnl_exchange_orders ?? null;
  const adOrders = Math.max(0, orders - (exchangeOrders ?? 0));
  const adAssumed = a.adPerOrder != null && Number.isFinite(a.adPerOrder);
  const adSpend = adAssumed ? (a.adPerOrder as number) * adOrders : measuredAd;
  // No split of a figure nobody spent.
  const metaSpend = adAssumed ? null : r.meta_spend ?? null;
  const googleSpend = adAssumed ? null : r.google_spend ?? null;
  const kwikSpend = adAssumed ? null : r.kwikchat_spend ?? null;

  // CANCELLATION IS NOT DEDUCTED HERE. Shopify reverses the goods value
  // of a cancellation whether or not cash moved, so Total sales is
  // already net of it; the measured share only informs the rail.
  const cancelledOrders = r.pnl_cancelled_orders ?? 0;
  // Money already handed back on orders that still stand.
  const refunds = r.pnl_refunds ?? 0;
  // RETURNS ARE MEASURED, from Return Prime, and come straight off
  // Total sales. Shopify books none of them: its Sales reversals line is
  // cancellation, and Return Prime settles outside Shopify's returns.
  // They are dated by the order, so a recent window always reads low --
  // a return is filed days after the order it belongs to. That gap is
  // what the Incremental returns allowance below is for.
  const returns = r.rp_return_value ?? null;
  const returnOrders = r.rp_return_orders ?? 0;
  const returnUnits = r.rp_return_qty ?? 0;
  const afterRefunds = sales - refunds - (returns ?? 0);
  // Three allowances, one base, none applied to another -- so the
  // order they are listed in cannot change the answer.
  const extraCancellation = afterRefunds * (a.extraCancelRate || 0);
  const rto = afterRefunds * (a.rtoRate || 0);
  const incReturns = afterRefunds * (a.returnsRate || 0);
  const net = afterRefunds - extraCancellation - rto - incReturns;

  const adGst = adSpend * a.gstRate;
  // Per order PLACED: the allowance is the one adjustment for
  // cancellation anywhere in the section.
  const logistics = orders * a.logistics;
  const pgFees = net * a.pgRate;
  const coins = coinQty * a.coinCost;
  const exchanges = orders * (a.exchangeRate || 0);
  const exchangeCost = exchanges * (a.exchangeCost || 0);
  const cogs = net * a.cogsRate;
  const totalDed = adSpend + adGst + logistics + pgFees + coins + exchangeCost + cogs;
  const cm = net - totalDed;

  // What the media has to return.
  //   break-even:   ROAS = sales(1 + gst) / preAd
  //   at a floor m: ROAS = (1 + gst) / (preAd/sales - m)
  // Null where there is no answer, never Infinity.
  const preAd = cm + adSpend + adGst;
  const preAdMargin = sales ? preAd / sales : null;
  const gst = 1 + (a.gstRate || 0);
  const roas = adSpend ? sales / adSpend : null;
  const beRoas = preAd > 0 ? sales * gst / preAd : null;
  const targetRoas = preAdMargin != null && preAdMargin > (a.minMargin || 0)
    ? gst / (preAdMargin - (a.minMargin || 0)) : null;

  // How Shopify gets to the headline. Two identities hold to the paisa:
  //   gross + discounts + returns = net sales
  //   net + shipping + return fees + taxes + duties + fees = total sales
  const bd = ((): Breakdown | null => {
    const g = r.shopify_gross_sales, disc = r.shopify_discounts;
    const rev = r.shopify_returns, ns = r.ql_net_sales;
    const ship = r.shopify_shipping, rfee = r.shopify_return_fees;
    const tax = r.shopify_taxes;
    if (g == null || disc == null || rev == null || ns == null
        || ship == null || rfee == null || tax == null) return null;
    const other = (r.shopify_duties ?? 0) + (r.shopify_additional_fees ?? 0);
    const ok = Math.abs((g + disc + rev) - ns) < 1
            && Math.abs((ns + ship + rfee + tax + other) - sales) < 1;
    // Shopify's admin counts EVERY order, Return Prime's zero-value
    // return legs included, and only that count reproduces its AOV.
    const qo = r.ql_orders_all || r.ql_orders || null;
    return { gross: g, discounts: disc, reversals: rev, netSales: ns,
             shipping: ship, returnFees: rfee, taxes: tax, other, total: sales, ok,
             orders: qo,
             aov: qo ? (ns - rev) / qo : null,
             revPerOrder: qo ? -rev / qo : null,
             discPerOrder: qo ? -disc / qo : null };
  })();

  return {
    bd, sales, orders, units, coinOrders, coinQty,
    cancelledOrders, refunds, extraCancellation, rto, incReturns, net,
    returns, returnOrders, returnUnits,
    returnPct: orders ? returnOrders / orders : null,
    adAssumed, measuredAd, adSpend, adOrders, exchangeOrders,
    adPerOrder: adOrders ? adSpend / adOrders : null,
    metaSpend, googleSpend, kwikSpend,
    adGst, logistics, pgFees, coins, exchanges, exchangeCost, cogs, totalDed, cm,
    preAd, preAdMargin, roas, beRoas, targetRoas,
    // Value per order PLACED and per unit, on realisable sales.
    asp: units ? net / units : null,
    aov: orders ? net / orders : null,
    cancelPct: orders ? cancelledOrders / orders : null,
    coinPct: orders ? coinOrders / orders : null,
    cmPct: net ? cm / net : null,
  };
}

const num = (n: number | null | undefined) =>
  n === null || n === undefined || !Number.isFinite(n) ? "—" : Math.round(n).toLocaleString("en-IN");
const money = (n: number | null | undefined, dp = 0) =>
  n === null || n === undefined || !Number.isFinite(n) ? "—"
    : n.toLocaleString("en-IN", { style: "currency", currency: "INR",
        minimumFractionDigits: dp, maximumFractionDigits: dp });
/** A deduction, signed. An allowance can go negative, and "− -₹57,277"
 *  reads as a typo: a negative deduction is an addition. */
const deduction = (n: number, dp = 0) =>
  n < 0 ? `+ ${money(-n, dp)}` : `− ${money(n, dp)}`;
const pct = (n: number | null | undefined, dp = 1) =>
  n === null || n === undefined || !Number.isFinite(n) ? "—" : `${(n * 100).toFixed(dp)}%`;
const times = (n: number | null) => (n == null ? "—" : `${n.toFixed(2)}×`);

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
    if (raw) {
      const a: Assumptions = { ...DEFAULTS, ...JSON.parse(raw) };
      // ONE-TIME migrations, the same two the standalone tracker runs
      // on the same key. Stored assumptions outlive a change of
      // default: the old 5% allowance double-deducted cancellation, and
      // a stored 0 for ad spend used to mean "use the measured figure".
      if (!((a.pnlV ?? 0) >= 2) && a.extraCancelRate === 0.05) a.extraCancelRate = 0;
      if (!((a.pnlV ?? 0) >= 3) && a.adPerOrder === 0) a.adPerOrder = null;
      if (a.pnlV !== 3) {
        a.pnlV = 3;
        try { localStorage.setItem(KEY, JSON.stringify(a)); } catch { /* not essential */ }
      }
      return a;
    }
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

const SPEND_PARTS = [
  { label: "Meta", cls: "bg-info-mid", key: "metaSpend" },
  { label: "Google", cls: "bg-accent-amber", key: "googleSpend" },
  { label: "Kwikchat", cls: "bg-accent-purple", key: "kwikSpend" },
] as const;

type DedKey = "adSpend" | "adGst" | "logistics" | "pgFees" | "coins" | "exchangeCost" | "cogs";

export function LivePnl({ totals, rows, compare, compareRows, compareDay, liveHour }: {
  totals: HourlyTotals | null;
  /** The window's hours, for the breakdown under the summary. */
  rows?: HourlyRow[];
  /** The comparison, already CLAMPED by the endpoint to the hours this
   *  day has reached. */
  compare?: HourlyTotals | null;
  compareRows?: HourlyRow[];
  compareDay?: string;
  /** Still filling: its margin is real but its hour is not over. */
  liveHour?: number | null;
}) {
  const a = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const [open, setOpen] = useState(false);

  const set = (k: Field["key"], v: number | null) => save({ ...a, [k]: v });

  if (!totals || !totals.pnl_orders) return null;

  const d = computePnl(totals, a);
  // Run through the SAME function, so a difference between the two is
  // the day's, never the arithmetic's.
  const c = compare ? computePnl(compare, a) : null;
  const byHour = new Map((compareRows ?? []).map((r) => [r.hour_of_day, r]));
  const { sales, orders, units, net, cm, cmPct, totalDed, refunds } = d;
  // The measured baseline, for reading an override against.
  const base = d.adAssumed ? computePnl(totals, { ...a, adPerOrder: null }) : d;

  const b = d.bd && d.bd.ok ? d.bd : null;
  const cb = c?.bd && c.bd.ok ? c.bd : null;

  // Ad spend is three platforms in one line; which of them moved is the
  // first question anyone asks of it. Shown only when the parts account
  // for the total.
  const parts = SPEND_PARTS
    .map((s) => ({ ...s, value: d[s.key] }))
    .filter((s): s is typeof s & { value: number } => s.value != null);
  const partsSum = parts.reduce((n, s) => n + s.value, 0);
  const split = !d.adAssumed && parts.length >= 2 && d.adSpend > 0
    && Math.abs(partsSum - d.adSpend) <= 1 ? parts : null;
  const googleAsOf = totals.google_spend_as_of
    ? new Date(totals.google_spend_as_of).toLocaleString("en-GB", {
        timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false,
        ...((totals.day_count ?? 1) > 1 ? { day: "2-digit", month: "short" } : {}),
      }).replace(",", "")
    : null;

  const deductions: { key: DedKey; label: string; note?: string }[] = [
    { key: "adSpend", label: "Ad spend",
      note: d.adAssumed
        ? `${money(a.adPerOrder)} / order assumed · ${money(d.measuredAd)} measured`
        : split ? undefined : "Meta + Google + Kwikchat" },
    { key: "adGst", label: "GST on ad spend" },
    { key: "logistics", label: "Logistics", note: `${num(orders)} orders placed` },
    { key: "pgFees", label: "PG fees" },
    { key: "coins", label: "Silver coin",
      note: `${num(d.coinQty)} coins in ${num(d.coinOrders)} orders` },
    { key: "exchangeCost", label: "Exchanges",
      note: `${num(d.exchanges)} at ${money(a.exchangeCost)} each` },
    { key: "cogs", label: "COGS" },
  ];
  // Bars are scaled to the LARGEST deduction on either day: against
  // revenue every bar but ad spend would be a sliver.
  const maxDed = Math.max(1,
    ...deductions.map((x) => Math.abs(d[x.key])),
    ...(c ? deductions.map((x) => Math.abs(c[x.key])) : []));
  const widthOf = (v: number) => Math.min(100, Math.abs(v) / maxDed * 100);
  // Ad spend divides by the orders advertising could have bought; every
  // other deduction by every order placed.
  const perOrder = (key: DedKey, v: number) => {
    const n = key === "adSpend" ? d.adOrders : orders;
    return n ? `${money(v / n)} / order` : "";
  };

  // REALISABLE SALES APPEARS ONLY WHEN IT DIFFERS FROM TOTAL SALES.
  //
  // Sales reversals are the cancelled value and are already out of
  // Total sales, and returns are not measured yet -- so until a refund
  // or an allowance is in play the two are the same number, and a
  // second line repeating the first only suggests a step that did not
  // happen. On either day, so a comparison never loses its other half.
  const same = Math.abs(net - sales) < 0.5 && (!c || Math.abs(c.net - c.sales) < 0.5);
  /** What the modelled lines are taken on, by name. */
  const baseName = same ? "Total sales" : "Realisable sales";
  const baseShort = same ? "Sales" : "Realisable";
  // Guarded: on a live day ShopifyQL lags the order feed and the
  // subtraction can go negative, which is a lag, not a leg count.
  const legs = d.bd?.orders != null && d.bd.orders > orders ? d.bd.orders - orders : null;

  // Newest first, and only hours that actually sold.
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

  /** One line of Shopify's breakdown. Discounts and reversals are
   *  stored negative: written with their own minus, and compared on
   *  magnitude, so a discount that widened reads as a rise. */
  const bdLine = (label: string, key: keyof Breakdown, opts: {
    note?: string; lowerIsBetter?: boolean; strong?: boolean; rule?: boolean } = {}) => {
    if (!b) return null;
    const now = b[key] as number;
    const was = cb ? (cb[key] as number) : null;
    const neg = now < 0 || (was != null && was < 0);
    const fmt = (v: number) => (neg ? `− ${money(-v)}` : money(v));
    return (
      <Line label={label} note={opts.note} strong={opts.strong} rule={opts.rule}
            value={fmt(now)} was={was != null ? fmt(was) : undefined}
            change={c ? <Change now={Math.abs(now)} was={was != null ? Math.abs(was) : null}
                                lowerIsBetter={opts.lowerIsBetter} /> : undefined} />
    );
  };

  return (
    <div className="rounded-md border border-border-primary bg-bg-white p-5 sm:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-[13px] font-medium text-text-primary">
          Live P&amp;L{compareDay ? ` · against ${compareDay}, same hours` : ""}
        </h3>
        <button type="button" onClick={() => setOpen((v) => !v)}
                className="text-[11.5px] text-text-secondary underline underline-offset-2">
          {open ? "Hide assumptions" : "Assumptions"}
        </button>
      </div>

      <dl className={`mt-5 grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-4 ${same ? "lg:grid-cols-7" : "lg:grid-cols-8"}`}>
        <Kpi label="Total sales" value={money(sales)} was={c ? money(c.sales) : undefined}
             now={sales} prev={c?.sales} day={compareDay}
             hint="Shopify's own Total sales, stored verbatim: the figure the Shopify admin shows. Cancellations are already out of it." />
        {!same && (
          <Kpi label="Realisable sales" value={money(net)} was={c ? money(c.net) : undefined}
               now={net} prev={c?.net} day={compareDay}
               hint="Total sales less returns measured from Return Prime, refunds on standing orders and any allowance set in Assumptions." />
        )}
        <Kpi label="Shopify AOV" value={money(d.bd?.aov, 2)}
             was={c ? money(c.bd?.aov, 2) : undefined}
             now={d.bd?.aov} prev={c?.bd?.aov} day={compareDay}
             hint={`Net sales less reversals ÷ ${num(d.bd?.orders)} orders, Shopify's own count. The AOV the Shopify admin shows.`} />
        <Kpi label={`${baseShort} / order`} value={money(d.aov, 2)}
             was={c ? money(c.aov, 2) : undefined}
             now={d.aov} prev={c?.aov} day={compareDay}
             hint={`${baseName} ÷ ${num(orders)} orders placed. Not Shopify's AOV: a different numerator and a different order count.`} />
        <Kpi label="Ad spend / order" value={money(d.adPerOrder, 2)}
             was={c ? money(c.adPerOrder, 2) : undefined}
             now={d.adPerOrder} prev={c?.adPerOrder} day={compareDay} lowerIsBetter
             hint={d.adAssumed
               ? `Assumed, overriding ${money(d.measuredAd)} of measured spend.`
               : `Measured spend ÷ ${num(d.adOrders)} orders advertising could have bought; exchange legs are excluded.`} />
        <Kpi label="ROAS achieved" value={times(d.roas)} was={c ? times(c.roas) : undefined}
             now={d.roas} prev={c?.roas} day={compareDay}
             hint={`Total sales ÷ ad spend. Break-even is ${times(d.beRoas)}.`} />
        <Kpi label="Contrib. margin" value={money(cm)} was={c ? money(c.cm) : undefined}
             now={cm} prev={c?.cm} day={compareDay}
             hint={`${baseName} less every deduction below.`} />
        <Kpi label="CM %" value={pct(cmPct)} was={c ? pct(c.cmPct) : undefined}
             now={cmPct} prev={c?.cmPct} day={compareDay}
             hint={`Contribution margin ÷ ${baseName.toLowerCase()}.`} />
      </dl>

      {open && (
        <div className="mt-6 border-t border-border-soft pt-5">
          <div className="grid gap-x-8 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
            {FIELDS.map((f) => {
              const isAd = f.key === "adPerOrder";
              const raw = a[f.key];
              // Ad spend shows the MEASURED figure until it is
              // overridden, not a nought standing in for it.
              const shown = isAd && !d.adAssumed
                ? (d.adPerOrder == null ? 0 : +d.adPerOrder.toFixed(2))
                : f.pct ? +((raw ?? 0) * 100).toFixed(2) : raw ?? 0;
              return (
                <label key={f.key} title={f.hint}
                       className="flex flex-wrap items-center justify-between gap-x-2 gap-y-0.5 text-[11.5px]">
                  <span className="text-text-secondary">{f.label}</span>
                  <span className="inline-flex items-baseline gap-1">
                    {isAd && d.adAssumed && (
                      <button type="button" onClick={() => set("adPerOrder", null)}
                              title="Back to the measured spend"
                              className="rounded border border-border-primary px-1 text-[10px] text-text-secondary hover:text-text-primary">
                        measured
                      </button>
                    )}
                    <input
                      type="number"
                      step={f.pct ? 0.1 : 1}
                      min={f.signed ? undefined : 0}
                      value={shown}
                      onChange={(e) => {
                        const v = Number(e.target.value);
                        if (!Number.isFinite(v)) return;
                        if (v < 0 && !f.signed) return;
                        set(f.key, f.pct ? v / 100 : v);
                      }}
                      className="w-20 rounded border border-border-primary bg-bg-white px-1.5 py-0.5 text-right tabular-nums"
                    />
                    <span className="text-text-tertiary">{f.pct ? "%" : "₹"}</span>
                  </span>
                  {isAd && (
                    <span className="basis-full text-[10px] text-text-tertiary">
                      {d.adAssumed
                        ? `Assumed. Measured was ${money(base.adPerOrder, 2)} / order, ${money(base.adSpend)} in all. Margin there ${money(base.cm)} (${pct(base.cmPct)}), here ${money(d.cm)} (${pct(d.cmPct)}).`
                        : `Measured: ${money(d.adSpend)} across ${num(d.adOrders)} orders${d.exchangeOrders ? `, ${num(d.exchangeOrders)} exchange legs excluded` : ""}.`}
                    </span>
                  )}
                </label>
              );
            })}
          </div>
          <p className="mt-2 text-[10.5px] leading-snug text-text-tertiary">
            Saved in this browser and shared with the standalone tracker.
            Percentages on COGS and PG fees apply to sales after any allowance set here.
            Cancellations are <strong>already out</strong> of Total sales, so
            <strong> Further cancellation</strong> starts at nil; set it only as a
            forward-looking allowance for a day still running. It, <strong>RTO</strong> and
            <strong> Incremental returns</strong> all apply to the same figure and never
            to each other. <strong>Target margin</strong> costs nothing; it only sets the
            second ROAS.
          </p>
        </div>
      )}

      <div className="mt-7 grid gap-x-10 gap-y-7 border-t border-border-soft pt-6 lg:grid-cols-[minmax(0,1fr)_260px]">
        <div className="min-w-0 space-y-8">
          {/* 1. Measured: Shopify's own figure and how it gets there. */}
          <section>
            <Cap>Measured — Shopify&rsquo;s own figure, stored verbatim</Cap>
            <Line label="Total sales" value={money(sales)} strong
                  note={same ? `${num(orders)} orders · ${num(units)} units` : undefined}
                  was={c ? money(c.sales) : undefined}
                  change={c ? <Change now={sales} was={c.sales} /> : undefined} />
            {b && (
              <div className="mt-2 border-l-2 border-border-soft pl-4">
                {bdLine("Gross sales", "gross")}
                {bdLine("Discounts", "discounts", { lowerIsBetter: true,
                  note: b.gross ? `${pct(-b.discounts / b.gross)} of gross` : undefined })}
                {/* Cancellation, whatever Shopify's own wording suggests. */}
                {bdLine("Sales reversals", "reversals", { lowerIsBetter: true,
                  note: "cancellations, dated by the cancellation" })}
                {bdLine("Net sales", "netSales", { strong: true, rule: true })}
                {bdLine("Shipping charges", "shipping")}
                {bdLine("Return fees", "returnFees")}
                {bdLine("Taxes", "taxes")}
                {(b.other !== 0 || (cb?.other ?? 0) !== 0)
                  && bdLine("Duties & additional fees", "other")}
                {bdLine("Total sales", "total", { strong: true, rule: true })}
              </div>
            )}
          </section>

          {/* 2. Allowances, and the Realisable sales they lead to.
              Absent altogether while nothing is set. */}
          {!same && (
          <section>
            <Cap>Returns and allowances — what we do not keep</Cap>
            {((d.returns ?? 0) > 0 || (c?.returns ?? 0) > 0) && (
              <Line label="Returns"
                    note={`${num(d.returnOrders)} orders · ${num(d.returnUnits)} units · measured from Return Prime, on the day the order was placed`}
                    value={`− ${money(d.returns ?? 0)}`}
                    was={c ? `− ${money(c.returns ?? 0)}` : undefined}
                    change={c ? <Change now={d.returns} was={c.returns} lowerIsBetter /> : undefined} />
            )}
            {(refunds > 0 || (c?.refunds ?? 0) > 0) && (
              <Line label="Refunds" note="on orders that still stand"
                    value={`− ${money(refunds)}`}
                    was={c ? `− ${money(c.refunds)}` : undefined}
                    change={c ? <Change now={refunds} was={c.refunds} lowerIsBetter /> : undefined} />
            )}
            {(d.extraCancellation !== 0 || (c?.extraCancellation ?? 0) !== 0) && (
              <Line label="Further cancellation"
                    note={`${pct(a.extraCancelRate)} allowance · ${num(d.cancelledOrders)} of ${num(orders)} cancelled, already out via reversals`}
                    value={deduction(d.extraCancellation)}
                    was={c ? deduction(c.extraCancellation) : undefined}
                    change={c ? <Change now={d.extraCancellation} was={c.extraCancellation} lowerIsBetter /> : undefined} />
            )}
            {(d.rto !== 0 || (c?.rto ?? 0) !== 0) && (
              <Line label="RTO impact"
                    note={`${pct(a.rtoRate)} allowance · dispatched, refused, carried back`}
                    value={deduction(d.rto)} was={c ? deduction(c.rto) : undefined}
                    change={c ? <Change now={d.rto} was={c.rto} lowerIsBetter /> : undefined} />
            )}
            {(d.incReturns !== 0 || (c?.incReturns ?? 0) !== 0) && (
              <Line label="Incremental returns"
                    note={`${pct(a.returnsRate)} allowance · beyond the reversals already booked`}
                    value={deduction(d.incReturns)} was={c ? deduction(c.incReturns) : undefined}
                    change={c ? <Change now={d.incReturns} was={c.incReturns} lowerIsBetter /> : undefined} />
            )}
            <Line label="Realisable sales" value={money(net)} strong rule
                  note={`${num(orders)} orders · ${num(units)} units`}
                  was={c ? money(c.net) : undefined}
                  change={c ? <Change now={net} was={c.net} /> : undefined} />
          </section>
          )}

        </div>

        {/* The rail: figures that are not part of the chain but are
            read against it. */}
        <aside className="self-start rounded-md border border-border-soft p-4">
          <h4 className="text-[11px] uppercase tracking-wide text-text-tertiary">
            Where the line sits
          </h4>
          <dl className="mt-2.5">
            <Rail label="ROAS achieved" value={times(d.roas)}
                  note={d.roas == null ? "no spend to divide by"
                    : d.beRoas != null ? (d.roas >= d.beRoas ? "above break-even" : "below break-even") : undefined} />
            <Rail label="Break-even ROAS" value={times(d.beRoas)}
                  note={d.beRoas == null ? "no contribution before ads" : undefined} />
            <Rail label={`ROAS at ${pct(a.minMargin, 0)} margin`} value={times(d.targetRoas)}
                  note={d.targetRoas == null ? `above the ${pct(d.preAdMargin)} available` : undefined} />
            <Rail label="Orders cancelled" value={pct(d.cancelPct)}
                  note={`${num(d.cancelledOrders)} of ${num(orders)}, measured`} />
            {d.returns != null && (
              <Rail label="Orders returned" value={pct(d.returnPct)}
                    note={`${num(d.returnOrders)} of ${num(orders)}, so far`} />
            )}
            <Rail label="Coin orders" value={pct(d.coinPct)} />
            <Rail label="Units sold" value={num(units)} />
            <Rail label="Exchanges" value={num(d.exchanges)} />
            <Rail label={cm < 0 ? "Break-even needs" : "Above break-even"}
                  value={money(Math.abs(cm))}
                  tone={cm < 0 ? "bad" : "good"} />
          </dl>
        </aside>
      </div>

      {/* Full width from here: the rail has ended, so these take the
          whole card rather than leaving its column empty. */}
      <div className="mt-8 space-y-8">
        {/* 3. Per order. Shopify's AOV and ours are side by side
            because they look like the same number and are not. */}
        <section className="border-t border-border-soft pt-6">
          <Cap>Per order</Cap>
          <div className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-3 xl:grid-cols-6">
            {d.bd?.aov != null && (
              <Stat label="Shopify AOV" value={money(d.bd.aov, 2)}
                    note={`net sales less reversals ÷ ${num(d.bd.orders)} orders`}
                    change={c ? <Change now={d.bd.aov} was={c.bd?.aov} /> : undefined} />
            )}
            <Stat label={`${baseShort} / order`} value={money(d.aov, 2)}
                  note={`÷ ${num(orders)} orders${legs ? `, ${num(legs)} Return Prime return legs excluded` : ""}`}
                  change={c ? <Change now={d.aov} was={c.aov} /> : undefined} />
            {d.bd?.revPerOrder != null && (
              <Stat label="Sales reversals / order" value={money(d.bd.revPerOrder, 2)}
                    note="already out of Total sales; shown, not deducted"
                    change={c ? <Change now={d.bd.revPerOrder} was={c.bd?.revPerOrder} lowerIsBetter /> : undefined} />
            )}
            <Stat label={`${baseShort} / unit`} value={money(d.asp, 2)}
                  note={`÷ ${num(units)} units`}
                  change={c ? <Change now={d.asp} was={c.asp} /> : undefined} />
            <Stat label="Units / order" value={orders ? `× ${(units / orders).toFixed(2)}` : "—"}
                  note={`${num(units)} units ÷ ${num(orders)} orders`}
                  change={c && c.orders ? <Change now={orders ? units / orders : null} was={c.units / c.orders} /> : undefined} />
            <Stat label="Ad spend / order" value={money(d.adPerOrder, 2)}
                  note={d.adAssumed ? `assumed, overriding ${money(d.measuredAd)} measured`
                    : `measured spend ÷ ${num(d.adOrders)} orders${d.exchangeOrders ? `, ${num(d.exchangeOrders)} exchange legs excluded` : ""}`}
                  change={c ? <Change now={d.adPerOrder} was={c.adPerOrder} lowerIsBetter /> : undefined} />
          </div>
        </section>

        {/* 4. The model: every deduction with its cost per order and
            its share of sales. */}
        <section className="border-t border-border-soft pt-6">
          <Cap>Contribution margin breakdown — modelled from the assumptions</Cap>
          <div className="mt-1">
            {deductions.map((x) => {
              const v = d[x.key];
              const was = c ? c[x.key] : null;
              return (
                <div key={x.key}>
                  <div className={`grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-4 py-1.5 text-[12px] ${c ? "sm:grid-cols-[220px_minmax(60px,1fr)_430px]" : "sm:grid-cols-[220px_minmax(60px,1fr)_300px]"}`}>
                    <span className="text-text-secondary">
                      {x.label}
                      {x.note && <span className="ml-1.5 text-[10.5px] text-text-tertiary">{x.note}</span>}
                    </span>
                    <span className="relative hidden h-2 self-center overflow-hidden rounded-sm bg-bg-muted sm:block"
                          aria-hidden="true">
                      {x.key === "adSpend" && split ? (
                        <span className="flex h-full gap-px" style={{ width: `${widthOf(v)}%` }}>
                          {split.map((s) => (
                            <span key={s.label} className={`h-full ${s.cls}`}
                                  style={{ width: `${s.value / d.adSpend * 100}%` }} />
                          ))}
                        </span>
                      ) : (
                        <span className="block h-full rounded-r-sm bg-text-tertiary"
                              style={{ width: `${widthOf(v)}%` }} />
                      )}
                      {was != null && (
                        <span className="absolute inset-y-0 w-0.5 bg-text-primary"
                              style={{ left: `calc(${Math.min(99.3, widthOf(was))}% - 1px)` }} />
                      )}
                    </span>
                    <span className="flex flex-wrap items-baseline justify-end gap-x-2 tabular-nums">
                      {was != null && (
                        <span className="text-[11px] text-text-tertiary">− {money(was)}</span>
                      )}
                      <span className="text-text-primary">− {money(v)}</span>
                      <span className="text-[10.5px] text-text-tertiary">
                        {perOrder(x.key, v)}{sales ? ` · ${pct(v / sales)}` : ""}
                      </span>
                      {c && <span className="text-[11px]"><Change now={v} was={was} lowerIsBetter /></span>}
                    </span>
                  </div>
                  {x.key === "adSpend" && split && (
                    <div className="flex flex-wrap gap-x-5 gap-y-1 pb-2.5 pt-0.5 text-[10.5px] text-text-tertiary">
                      {split.map((s) => (
                        <span key={s.label} className="inline-flex items-baseline gap-1">
                          <span className={`inline-block h-2 w-2 self-center rounded-sm ${s.cls}`} aria-hidden="true" />
                          {s.label}
                          <span className="tabular-nums text-text-secondary">{money(s.value)}</span>
                          <span className="tabular-nums">{pct(s.value / d.adSpend)}</span>
                          {s.label === "Google" && googleAsOf && <span>to {googleAsOf}</span>}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
            <Line label="Total deductions" rule value={`− ${money(totalDed)}`}
                  note={orders && sales ? `${money(totalDed / orders)} / order · ${pct(totalDed / sales)} of sales` : undefined}
                  was={c ? `− ${money(c.totalDed)}` : undefined}
                  change={c ? <Change now={totalDed} was={c.totalDed} lowerIsBetter /> : undefined} />
            <Line label="Contribution margin" strong rule value={money(cm)}
                  note={`${pct(cmPct)} of ${baseName.toLowerCase()}${orders ? ` · ${money(cm / orders, 2)} / order` : ""}`}
                  was={c ? money(c.cm) : undefined}
                  change={c ? <Change now={cm} was={c.cm} /> : undefined} />
          </div>
        </section>
      </div>

      {hourly.length > 0 && (
        <div className="mt-8 border-t border-border-soft pt-6">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h4 className="text-[12px] font-medium text-text-primary">Hour by hour</h4>
            <span className="text-[10.5px] text-text-tertiary">
              Same assumptions. Bars are contribution margin, right for a profit
              and left for a loss, on one scale.
            </span>
          </div>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full border-collapse text-[11.5px]">
              <thead>
                <tr className="text-right text-[10.5px] uppercase tracking-wide text-text-tertiary">
                  <th className="py-1 pr-3 text-left font-medium">Hour</th>
                  <th className="py-1 pr-3 font-medium">Sales</th>
                  <th className="py-1 pr-3 font-medium">Orders</th>
                  <th className="py-1 pr-3 font-medium">ASP</th>
                  <th className="py-1 pr-3 font-medium">AOV</th>
                  {!same && <th className="py-1 pr-3 font-medium">Realisable</th>}
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
                      <td className="py-1.5 pr-3 text-left text-text-primary">
                        {String(hour).padStart(2, "0")}:00
                        {live && (
                          <span className="ml-1.5 text-[9px] uppercase tracking-wide text-text-tertiary">
                            live
                          </span>
                        )}
                      </td>
                      <td className="py-1.5 pr-3 text-text-primary">{money(p.sales)}</td>
                      <td className="py-1.5 pr-3 text-text-secondary">
                        {p.orders.toLocaleString("en-IN")}
                      </td>
                      <td className="py-1.5 pr-3 text-text-secondary">{money(p.asp, 0)}</td>
                      <td className="py-1.5 pr-3 text-text-secondary">{money(p.aov, 0)}</td>
                      {!same && <td className="py-1.5 pr-3 text-text-secondary">{money(p.net)}</td>}
                      <td className="py-1.5 pr-3 text-text-secondary">{money(p.adSpend)}</td>
                      <td className={`py-1.5 pr-3 font-medium ${
                        p.cm >= 0 ? "text-success-text" : "text-warning-text"}`}>
                        {money(p.cm)}
                      </td>
                      <td className={`py-1.5 pr-3 ${
                        p.cm >= 0 ? "text-success-text" : "text-warning-text"}`}>
                        {pct(p.cmPct)}
                      </td>
                      {c && (
                        <td className="py-1.5 pr-3 text-[11px]">
                          {/* The same hour of the comparison day, by CM.
                              A margin that halved matters more than one
                              that merely fell. */}
                          {live ? <span className="text-text-tertiary">—</span>
                                : <Change now={p.cm} was={q?.cm} />}
                        </td>
                      )}
                      <td className="py-1.5">
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

      <p className="mt-8 border-t border-border-soft pt-4 text-[11px] leading-snug text-text-tertiary">
        The top line is <strong>Shopify&rsquo;s own Total sales</strong>, stored
        verbatim, so it equals what the Shopify admin shows. Cancellations are
        already out of it: the Sales reversals line is cancellation, so nothing
        is deducted for it again. <strong>Returns</strong> are measured from
        Return Prime and counted against the day the order was placed, so they
        keep arriving for weeks: a recent day reads low, and Realisable sales
        appears once a return, a refund or an allowance is in play.
        Every deduction is a model built from those assumptions, so a margin
        here is an estimate rather than a result.
      </p>
    </div>
  );
}

function Kpi({ label, value, was, now, prev, day, hint, lowerIsBetter }: {
  label: string; value: string; was?: string;
  now?: number | null; prev?: number | null; day?: string; hint?: string;
  /** Cancellation % going up is bad news. Colour follows the judgement;
   *  the arrow still follows the direction. */
  lowerIsBetter?: boolean;
}) {
  return (
    <div className="min-w-0">
      <dt className="truncate text-[11px] uppercase tracking-wide text-text-tertiary" title={hint}>
        {label}
      </dt>
      <dd className="mt-1 truncate tabular-nums text-xl font-semibold text-text-primary">
        {value}
      </dd>
      {was !== undefined && (
        <dd className="mt-0.5 flex flex-wrap items-baseline gap-x-1.5 text-[11.5px]">
          <span className="tabular-nums text-text-tertiary">{was}</span>
          <span className="text-[11px]">
            <Change now={now} was={prev} lowerIsBetter={lowerIsBetter} />
          </span>
          {day && <span className="basis-full text-[10px] text-text-tertiary">{day}</span>}
        </dd>
      )}
    </div>
  );
}

function Cap({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-2.5 text-[10.5px] uppercase tracking-wide text-text-tertiary">{children}</div>
  );
}

function Line({ label, value, was, note, strong, rule, change }: {
  label: string; value: string; was?: string; note?: string;
  strong?: boolean; rule?: boolean; change?: React.ReactNode;
}) {
  return (
    <div className={`flex flex-wrap items-baseline justify-between gap-x-3 py-1.5 text-[12px] ${
      rule ? "mt-2 border-t border-border-soft pt-3" : ""}`}>
      <span className={strong ? "font-medium text-text-primary" : "text-text-secondary"}>
        {label}
        {note && <span className="ml-1.5 text-[10.5px] font-normal text-text-tertiary">{note}</span>}
      </span>
      <span className="flex items-baseline gap-2 tabular-nums">
        {was !== undefined && (
          <span className="text-[11px] text-text-tertiary">{was}</span>
        )}
        <span className={strong ? "font-semibold text-text-primary" : "text-text-primary"}>
          {value}
        </span>
        {change !== undefined && <span className="text-[11px]">{change}</span>}
      </span>
    </div>
  );
}

function Stat({ label, value, note, change }: {
  label: string; value: string; note: string; change?: React.ReactNode;
}) {
  return (
    <div className="min-w-0">
      <div className="text-[10.5px] uppercase tracking-wide text-text-tertiary">{label}</div>
      <div className="mt-1.5 flex flex-wrap items-baseline gap-x-1.5">
        <span className="tabular-nums text-[15px] font-semibold text-text-primary">{value}</span>
        {change !== undefined && <span className="text-[11px]">{change}</span>}
      </div>
      <div className="mt-1 text-[10.5px] leading-snug text-text-tertiary">{note}</div>
    </div>
  );
}

function Rail({ label, value, note, tone }: {
  label: string; value: string; note?: string; tone?: "good" | "bad";
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-t border-border-soft py-2.5 text-[12px] first:border-t-0">
      <dt className="text-text-secondary">
        {label}
        {note && <span className="block text-[10px] text-text-tertiary">{note}</span>}
      </dt>
      <dd className={`tabular-nums font-semibold ${
        tone === "good" ? "text-success-text" : tone === "bad" ? "text-warning-text" : "text-text-primary"}`}>
        {value}
      </dd>
    </div>
  );
}
