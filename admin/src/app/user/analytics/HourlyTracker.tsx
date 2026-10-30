"use client";

import { Fragment, useEffect, useMemo, useState } from "react";

import {
  ApiError,
  HourlyRow,
  HourlyTotals,
  HourlyTrackerResponse,
  fetchHourlyTracker,
} from "@/lib/api";
import {
  FilterCell,
  SectionHeader,
  TableFrame,
  filterControlClass,
} from "./SectionChrome";
import { HourlyTrendChart } from "./charts/HourlyTrendChart";
import { SessionSourceDonut } from "./charts/SessionSourceDonut";

/**
 * The campaign tracker, hour by hour, for a day you are still inside.
 *
 * Everything here answers one question: is this hour better or worse
 * than the same hour yesterday. That is why nothing is shown without a
 * comparison beside it -- a cost per session of Rs 6.14 means nothing
 * alone, and means a great deal against Rs 6.72 at the same hour
 * yesterday.
 *
 * The baseline is CLAMPED to the hours today has reached. Comparing a
 * part-finished day against a full one flatters the full one every
 * time, and at 10am it would say the day is going catastrophically.
 */

const IST_OFFSET_MIN = 330;

/** Today in Asia/Kolkata, whatever the viewer's own clock says. The
 *  store reports in IST, so the dashboard has to think in IST. */
function istToday(): string {
  const now = new Date();
  const ist = new Date(now.getTime() + (IST_OFFSET_MIN + now.getTimezoneOffset()) * 60000);
  return ist.toISOString().slice(0, 10);
}

const money = (n: number | null | undefined, dp = 2) =>
  n === null || n === undefined
    ? "—"
    : n.toLocaleString("en-IN", { style: "currency", currency: "INR",
        minimumFractionDigits: dp, maximumFractionDigits: dp });
const compact = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : n.toLocaleString("en-IN");
const pct = (n: number | null | undefined, dp = 1) =>
  n === null || n === undefined ? "—" : `${(n * 100).toFixed(dp)}%`;
const ratio = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : `${n.toFixed(2)}x`;

/** Where a bigger number is the GOOD outcome. Cost per session is the
 *  obvious exception, and getting it backwards would colour a saving
 *  red.
 *
 *  "flat" is for the traffic-mix figures. Whether a rising paid share
 *  is good depends entirely on what you were trying to do that hour --
 *  buying harder, or letting organic carry the day -- so the change is
 *  shown and the judgement is left to the reader rather than guessed
 *  at in colour. */
type Dir = "up" | "down" | "flat";

/** "Oct 30, 2026" — each stacked line carries its own full date,
 *  because two bare "12:00" rows do not say which day each belongs to. */
const dayLabel = (iso: string) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-US",
    { timeZone: "UTC", month: "short", day: "numeric", year: "numeric" });

const hourLabel = (iso: string, h: number) =>
  `${dayLabel(iso)}, ${(h % 12) || 12}:00 ${h < 12 ? "AM" : "PM"}`;

/** The change on a line of its own: an arrow and a rounded figure,
 *  rather than the signed decimal that belongs beside a value. */
function Change({ now, was, dir = "up", points = false }:
  { now: number | null | undefined; was: number | null | undefined;
    dir?: Dir; points?: boolean }) {
  if (now === null || now === undefined || !was) {
    return <span className="text-text-tertiary">—</span>;
  }
  if (points) {
    const pts = (now - was) * 100;
    const flat = Math.abs(pts) < 0.05 || dir === "flat";
    const good = dir === "up" ? pts > 0 : pts < 0;
    return (
      <span className={flat ? "text-text-tertiary" : good ? "text-success-text" : "text-warning-text"}>
        {pts > 0 ? "↗ +" : pts < 0 ? "↘ " : ""}{pts.toFixed(1)} pt
      </span>
    );
  }
  const ch = (now - was) / Math.abs(was);
  const flat = Math.abs(ch) < 0.005 || dir === "flat";
  const good = dir === "up" ? ch > 0 : ch < 0;
  return (
    <span className={flat ? "text-text-tertiary" : good ? "text-success-text" : "text-warning-text"}>
      {flat ? "" : ch > 0 ? "↗ " : "↘ "}{Math.abs(ch * 100).toFixed(0)}%
    </span>
  );
}

function Delta({ now, was, dir = "up", points = false }:
  { now: number | null | undefined; was: number | null | undefined;
    dir?: Dir; points?: boolean }) {
  // `undefined` as well as null: the baseline day may not be in the
  // tracker at all, and a missing comparison is a dash, not a zero.
  if (now === null || now === undefined || !was) {
    return <span className="text-text-tertiary">—</span>;
  }
  // A share moves in POINTS. "90.2% is 2% up on 88.4%" is a different
  // and much smaller claim than "up 1.8 points", and the second is the
  // one anyone reading a traffic mix means.
  if (points) {
    const pts = (now - was) * 100;
    const tone = Math.abs(pts) < 0.05 || dir === "flat" ? "text-text-tertiary"
      : (dir === "up" ? pts > 0 : pts < 0) ? "text-success-text" : "text-warning-text";
    return (
      <span className={`tabular-nums ${tone}`}>
        {pts > 0 ? "+" : ""}{pts.toFixed(1)} pt
      </span>
    );
  }
  const change = (now - was) / Math.abs(was);
  // Within half a per cent is noise at hour grain, not a move.
  const noise = Math.abs(change) < 0.005;
  const good = dir === "up" ? change > 0 : change < 0;
  const tone = noise || dir === "flat" ? "text-text-tertiary"
    : good ? "text-success-text" : "text-warning-text";
  return (
    <span className={`tabular-nums ${tone}`}>
      {change > 0 ? "+" : ""}{(change * 100).toFixed(1)}%
    </span>
  );
}

/** One headline figure with yesterday beneath it.
 *
 *  Deliberately takes no direction: the hero shows the two numbers and
 *  lets the reader compare them. The coloured judgement lives in the
 *  Delta row below, in one place, where the up-is-good rule is applied
 *  per metric and cost per session is the exception. */
/** What "paid" means everywhere on this page. Written once so the two
 *  cost/revenue heroes and the conversion ones cannot drift apart. */
const PAID_SESSION_HINT =
  "Paid sessions are every session carrying a utm_source that is not direct or none"
  + " — which includes organic-looking tags, so read it as 'attributed', not 'bought'.";

function Hero({ label, value, was, hint, parts }: {
  label: string; value: string; was: string; hint?: string;
  /** Components of `value`, listed under it. For a figure that adds
   *  together things of different kinds -- Spend is one measured
   *  channel and two day-level allocations -- the total alone hides
   *  what it is made of. */
  parts?: { label: string; value: string }[];
}) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] uppercase tracking-wide text-text-tertiary" title={hint}>
        {label}
      </dt>
      <dd className="mt-1 truncate tabular-nums text-2xl font-semibold text-text-primary">
        {value}
      </dd>
      <dd className="mt-0.5 text-[11.5px] text-text-secondary">
        <span className="tabular-nums">{was}</span> same time yesterday
      </dd>
      {parts?.length ? (
        <dd className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-text-tertiary">
          {parts.map((p) => (
            <span key={p.label}>
              {p.label} <span className="tabular-nums">{p.value}</span>
            </span>
          ))}
        </dd>
      ) : null}
    </div>
  );
}

const METRICS: {
  key: keyof HourlyRow;
  label: string;
  fmt: (n: number | null) => string;
  dir: Dir;
  w: number;
  /** A share: its change is points, not per cent of a per cent. */
  points?: boolean;
}[] = [
  { key: "sessions", label: "Sessions", fmt: compact, dir: "up", w: 90 },
  { key: "pct_paid", label: "% paid", fmt: (n) => pct(n), dir: "flat", w: 95, points: true },
  { key: "pct_direct", label: "% direct", fmt: (n) => pct(n), dir: "flat", w: 95, points: true },
  // Orders ÷ sessions, split on the same denominators as the two
  // shares above. A rising paid share that does not lift CR / paid is
  // traffic bought at the wrong quality, and that is the whole reason
  // to carry the split rather than one site-wide number.
  { key: "conversion_rate", label: "CR", fmt: (n) => pct(n, 2), dir: "up", w: 90, points: true },
  { key: "conversion_rate_paid", label: "CR / paid", fmt: (n) => pct(n, 2), dir: "up", w: 100, points: true },
  { key: "conversion_rate_direct", label: "CR / direct", fmt: (n) => pct(n, 2), dir: "up", w: 105, points: true },
  { key: "meta_impressions", label: "Impressions", fmt: compact, dir: "up", w: 110 },
  { key: "spend", label: "Spend", fmt: (n) => money(n, 0), dir: "up", w: 105 },
  { key: "cost_per_session", label: "Cost / session", fmt: (n) => money(n), dir: "down", w: 115 },
  { key: "cost_per_paid_session", label: "Cost / paid sess", fmt: (n) => money(n), dir: "down", w: 125 },
  { key: "orders", label: "Orders", fmt: compact, dir: "up", w: 85 },
  { key: "revenue", label: "Revenue", fmt: (n) => money(n, 0), dir: "up", w: 115 },
  // Basket size, not traffic quality: the one revenue column here whose
  // denominator is orders rather than sessions. An hour can lift
  // Rev / session by converting more of the same traffic while AOV sits
  // still, and the two moving apart is the useful signal.
  { key: "aov", label: "AOV", fmt: (n) => money(n), dir: "up", w: 100 },
  { key: "revenue_per_session", label: "Rev / session", fmt: (n) => money(n), dir: "up", w: 115 },
  // Per-channel revenue columns are deliberately absent. Google Ads
  // spend comes from a BigQuery export that cannot run hourly, so a
  // revenue-per-Google-session next to a spend figure that excludes
  // Google invites exactly the comparison it cannot support. Rev / paid
  // session stays: it is revenue over the traffic we bought, on the
  // same denominator as Cost / paid session beside it.
  { key: "revenue_per_paid_session", label: "Rev / paid sess", fmt: (n) => money(n), dir: "up", w: 125 },
  { key: "amer", label: "AMER", fmt: ratio, dir: "up", w: 85 },
  { key: "ga4_arpu", label: "ARPU (GA4)", fmt: (n) => money(n), dir: "up", w: 110 },
];

export function HourlyTracker() {
  const [day, setDay] = useState(istToday);
  const [compareTo, setCompareTo] = useState("");
  const [showDeltas, setShowDeltas] = useState(true);
  const [data, setData] = useState<HourlyTrackerResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const params = useMemo(
    () => ({ day, compare_to: compareTo || undefined }), [day, compareTo]);

  useEffect(() => {
    let cancelled = false;
    // No setState in the effect body: every state change happens in a
    // callback. That satisfies the cascading-render rule, and on a view
    // that refetches itself every five minutes it is also the better
    // behaviour -- the table keeps showing the last good figures
    // instead of blanking to a spinner on every tick.
    fetchHourlyTracker(params)
      .then((r) => { if (!cancelled) { setData(r); setError(null); } })
      .catch((e) => { if (!cancelled) setError(e instanceof ApiError ? e.message : String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [params, tick]);

  // The point of an hourly tracker is that it does not need reloading.
  useEffect(() => {
    const id = window.setInterval(() => setTick((n) => n + 1), 5 * 60000);
    return () => window.clearInterval(id);
  }, []);

  const rows = data?.rows ?? [];
  const baseline = useMemo(() => {
    const m = new Map<number, HourlyRow>();
    for (const r of data?.compare_rows ?? []) m.set(r.hour_of_day, r);
    return m;
  }, [data?.compare_rows]);

  const t: HourlyTotals | null = data?.today ?? null;
  const c: HourlyTotals | null = data?.compare ?? null;
  /** The label for line two of every stacked cell. Falls back to the
   *  day the baseline WOULD have been, so a missing day still says
   *  which day is missing rather than leaving the line blank. */
  const baseDay = c?.day ?? (compareTo
    || new Date(new Date(`${day}T00:00:00Z`).getTime() - 86400000)
         .toISOString().slice(0, 10));
  /** The day the baseline WOULD have been, for when it is not there. */
  const baselineDay = compareTo
    || new Date(new Date(`${day}T00:00:00Z`).getTime() - 86400000)
         .toISOString().slice(0, 10);
  const isToday = day === istToday();

  return (
    <div className="flex flex-col gap-5">
      <SectionHeader title="Hourly Tracker">
        <span className="text-[11.5px] text-text-tertiary">
          {data?.latest_hour !== null && data?.latest_hour !== undefined
            ? `${String(data.latest_hour).padStart(2, "0")}:00 IST · ${rows.length} hours`
            : "no data for this day"}
          {isToday ? " · refreshes every 5 min" : ""}
        </span>
      </SectionHeader>

      <div className="flex flex-wrap items-end gap-3">
        <FilterCell label="Day" className="w-44" htmlFor="ht-day">
          <input id="ht-day" type="date" value={day} max={istToday()}
                 onChange={(e) => setDay(e.target.value)} className={filterControlClass} />
        </FilterCell>
        <FilterCell label="Compare to" className="w-48" htmlFor="ht-cmp">
          <input id="ht-cmp" type="date" value={compareTo} max={istToday()}
                 placeholder="previous day"
                 onChange={(e) => setCompareTo(e.target.value)} className={filterControlClass} />
        </FilterCell>
        <label className="flex items-center gap-2 pb-1.5 text-[13px] text-text-secondary">
          <input type="checkbox" checked={showDeltas}
                 onChange={(e) => setShowDeltas(e.target.checked)} />
          Show % change
        </label>
        <button type="button" onClick={() => setTick((n) => n + 1)}
                className="ml-auto rounded-md border border-border-primary bg-bg-white px-3 py-1.5 text-[13px] text-text-primary hover:bg-bg-muted/60">
          Refresh
        </button>
      </div>

      {error && (
        <p role="alert" className="rounded-md border border-warning-border bg-warning-bg px-4 py-3 text-sm text-warning-text">
          {error}
        </p>
      )}

      {loading && !rows.length ? (
        <p className="py-8 text-sm text-text-secondary">Loading the hour&rsquo;s figures…</p>
      ) : !rows.length ? (
        <p className="py-8 text-sm text-text-secondary">
          Nothing recorded for {day}.{" "}
          {data?.first_day && data?.last_day
            ? <>This tracker holds {data.first_day} to {data.last_day}.{" "}</>
            : null}
          Run{" "}
          <code className="text-[12px]">scripts/fetch_hourly_tracker.py --date {day}</code>.
        </p>
      ) : (
        <>
          {/* Day to date, each against the SAME hours yesterday --
              or on its own, when the day before was never ingested. */}
          {t && (
            <div className="rounded-md border border-border-primary bg-bg-white p-4">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="text-[13px] font-medium text-text-primary">
                  Day to date · {t.hours} hours
                </h3>
                <span className="text-[11.5px] text-text-tertiary">
                  {c ? `against the same ${c.hours} hours of ${c.day}`
                     : `${baselineDay} is not in the tracker, so there is nothing to compare against`}
                </span>
              </div>
              <dl className="mt-3 grid grid-cols-2 gap-x-5 gap-y-4 sm:grid-cols-3 lg:grid-cols-3">
                <Hero label="Sessions" value={compact(t.sessions)} was={compact(c?.sessions)} />
                <Hero label="Spend" value={money(t.spend, 0)} was={money(c?.spend, 0)}
                      hint={"Meta is measured hourly. Google is a daily total shared across the"
                            + " hours by each hour's share of Google-driven sessions, and"
                            + " Kwikchat is a flat \u20B930,000 a day over 24."}
                      parts={[
                        { label: "Meta", value: money(t.meta_spend, 0) },
                        { label: "Google", value: money(t.google_spend, 0) },
                        { label: "Kwikchat", value: money(t.kwikchat_spend, 0) },
                      ]} />
                <Hero label="Revenue" value={money(t.revenue, 0)} was={money(c?.revenue, 0)} />
                <Hero label="Cost / session" value={money(t.cost_per_session)}
                      was={money(c?.cost_per_session)} />
                <Hero label="Rev / session" value={money(t.revenue_per_session)}
                      was={money(c?.revenue_per_session)} />
                <Hero label="AOV" value={money(t.aov)} was={money(c?.aov)}
                      hint="Revenue ÷ orders, re-divided from the day's totals — not the average of the hourly AOVs." />
                {/* The same two rates over bought traffic only. They sit
                    together, and next to AMER, because that is the row
                    anyone judging a campaign day actually reads. */}
                <Hero label="Cost / paid session" value={money(t.cost_per_paid_session)}
                      was={money(c?.cost_per_paid_session)}
                      hint={"Spend ÷ paid sessions. " + PAID_SESSION_HINT} />
                <Hero label="Rev / paid session" value={money(t.revenue_per_paid_session)}
                      was={money(c?.revenue_per_paid_session)}
                      hint={"Revenue from orders with a utm_source, ÷ paid sessions. "
                            + PAID_SESSION_HINT} />
                <Hero label="AMER" value={ratio(t.amer)} was={ratio(c?.amer)}
                      hint="New-customer revenue ÷ spend." />
                <Hero label="Conversion rate" value={pct(t.conversion_rate, 2)}
                      was={pct(c?.conversion_rate, 2)}
                      hint="Orders ÷ sessions. Cancelled and returned orders are not counted; exchanges are." />
                <Hero label="CR / paid" value={pct(t.conversion_rate_paid, 2)}
                      was={pct(c?.conversion_rate_paid, 2)}
                      hint="Orders from a utm_source that is not direct, over paid sessions." />
                <Hero label="CR / direct" value={pct(t.conversion_rate_direct, 2)}
                      was={pct(c?.conversion_rate_direct, 2)}
                      hint="Orders with no utm_source, over direct sessions." />
                <Hero label="% paid sessions" value={pct(t.pct_paid)} was={pct(c?.pct_paid)}
                      hint="Sessions carrying a utm_source that is not direct or none." />
                <Hero label="% direct sessions" value={pct(t.pct_direct)} was={pct(c?.pct_direct)}
                      hint="Sessions with no utm_source, or one that says direct/none. The complement of % paid." />
              </dl>
              <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2 border-t border-border-soft pt-3 text-[12px] text-text-secondary">
                <span>Sessions <Delta now={t.sessions} was={c?.sessions} /></span>
                <span>Spend <Delta now={t.spend} was={c?.spend} /></span>
                <span>Revenue <Delta now={t.revenue} was={c?.revenue} /></span>
                <span>Cost / session <Delta now={t.cost_per_session} was={c?.cost_per_session} dir="down" /></span>
                <span>Rev / session <Delta now={t.revenue_per_session} was={c?.revenue_per_session} /></span>
                <span>AOV <Delta now={t.aov} was={c?.aov} /></span>
                <span>Cost / paid sess <Delta now={t.cost_per_paid_session}
                                              was={c?.cost_per_paid_session} dir="down" /></span>
                <span>Rev / paid sess <Delta now={t.revenue_per_paid_session}
                                             was={c?.revenue_per_paid_session} /></span>
                <span>CR <Delta now={t.conversion_rate} was={c?.conversion_rate} points /></span>
                <span>AMER <Delta now={t.amer} was={c?.amer} /></span>
                <span>% paid <Delta now={t.pct_paid} was={c?.pct_paid} dir="flat" points /></span>
                <span>% direct <Delta now={t.pct_direct} was={c?.pct_direct} dir="flat" points /></span>
              </div>
            </div>
          )}

          <div className="grid gap-4 lg:grid-cols-[1fr_minmax(320px,0.52fr)]">
            <HourlyTrendChart rows={rows} baseline={data?.compare_rows ?? []}
                              baselineDay={c?.day ?? ""} />
            <SessionSourceDonut sources={data?.sources ?? []} />
          </div>

          <TableFrame
            footer={
              <>
                <span className="text-[11.5px] text-text-tertiary">
                  Every hour against the same hour of {c?.day ?? "the previous day"}
                  {isToday ? " · the live hour shows no change, it is still filling" : ""}
                </span>
                <span className="text-[11.5px] text-text-tertiary">
                  Spend is Meta + Google + Kwikchat · only Meta is measured hourly
                  {t?.google_spend_as_of
                    ? ` · Google captured ${new Date(t.google_spend_as_of)
                        .toLocaleString("en-IN", { timeZone: "Asia/Kolkata",
                                                   hour: "2-digit", minute: "2-digit",
                                                   day: "2-digit", month: "short" })} IST`
                    : ""}
                </span>
                <span className="text-[11.5px] text-text-tertiary">
                  Cancelled and returned orders excluded · exchanges counted, unlike the
                  Overview · today&rsquo;s returns are mostly not tagged yet, so past days drift down
                </span>
              </>
            }
          >
            <div className="overflow-x-auto border border-border-primary bg-bg-white">
              <table className="border-collapse bg-bg-white text-[12.5px]">
                <thead>
                  <tr className="bg-bg-white text-left text-[11px] uppercase tracking-wide text-text-tertiary">
                    <th style={{ minWidth: 172 }}
                        className="sticky left-0 z-10 whitespace-nowrap border-b border-r border-border-soft bg-bg-white px-3 py-2 font-medium">
                      Hour
                    </th>
                    {METRICS.map((m) => (
                      <th key={m.key} style={{ minWidth: m.w }}
                          className="whitespace-normal border-b border-r border-border-soft px-3 py-2 text-right align-bottom font-medium last:border-r-0">
                        {m.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {/* The aggregate, then its breakdown. Every ratio here
                      comes from the API, recomputed from the summed
                      counts -- NOT averaged down the column, which would
                      weight a dead 04:00 the same as a 21:00 peak. */}
                  {t && (
                    <tr className="bg-bg-muted/60 align-top">
                      <td style={{ minWidth: 172 }}
                          className="sticky left-0 z-10 whitespace-nowrap border-b-2 border-r border-border-primary bg-bg-muted px-3 py-2 font-mono text-[11.5px] text-text-primary">
                        <span className="block font-semibold">
                          {dayLabel(t.day)}
                          <span className="ml-1.5 font-sans text-[9.5px] uppercase tracking-wide text-text-tertiary">
                            {t.hours}h
                          </span>
                        </span>
                        <span className="mt-0.5 block text-text-tertiary">{dayLabel(baseDay)}</span>
                        {showDeltas && (
                          <span className="mt-0.5 block font-sans text-[11px] text-text-tertiary">
                            % change
                          </span>
                        )}
                      </td>
                      {METRICS.map((m) => {
                        const now = (t as unknown as Record<string, number | null>)[m.key] ?? null;
                        const was = c
                          ? (c as unknown as Record<string, number | null>)[m.key] ?? null
                          : null;
                        return (
                          <td key={m.key} style={{ minWidth: m.w }}
                              className="border-b-2 border-r border-border-primary px-3 py-2 text-right tabular-nums text-text-primary last:border-r-0">
                            <span className="block font-semibold">{m.fmt(now)}</span>
                            <span className="mt-0.5 block text-text-tertiary">{m.fmt(was)}</span>
                            {showDeltas && (
                              <span className="mt-0.5 block text-[11px]">
                                <Change now={now} was={was} dir={m.dir} points={m.points} />
                              </span>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  )}
                  {[...rows].reverse().map((r) => {
                    const prev = baseline.get(r.hour_of_day);
                    // The newest hour of TODAY is still filling. Showing
                    // its change against a complete hour yesterday reads
                    // as a collapse -- at 18:10 it said sessions -59.9%
                    // and spend -79.8% when nothing had gone wrong at
                    // all. The figures stay, the comparison does not.
                    const partial = isToday && r.hour_of_day === data?.latest_hour;
                    return (
                      <tr key={r.hour}
                          className={`align-top hover:bg-bg-muted/40 ${partial ? "bg-bg-muted/30" : "bg-bg-white"}`}>
                        <td style={{ minWidth: 172 }}
                            className={`sticky left-0 z-10 whitespace-nowrap border-b border-r border-border-soft px-3 py-1.5 font-mono text-[11.5px] text-text-primary ${partial ? "bg-bg-muted/30" : "bg-bg-white"}`}>
                          <span className="block">
                            {hourLabel(r.day_ist, r.hour_of_day)}
                            {partial && (
                              <span className="ml-1.5 font-sans text-[9.5px] uppercase tracking-wide text-text-tertiary"
                                    title="This hour is still filling. Comparing it with a complete hour yesterday would read as a fall that has not happened.">
                                live
                              </span>
                            )}
                          </span>
                          <span className="mt-0.5 block text-text-tertiary">
                            {hourLabel(baseDay, r.hour_of_day)}
                          </span>
                          {showDeltas && !partial && (
                            <span className="mt-0.5 block text-[11px]">&nbsp;</span>
                          )}
                        </td>
                        {METRICS.map((m) => {
                          const v = r[m.key] as number | null;
                          const was = (prev?.[m.key] ?? null) as number | null;
                          return (
                            <td key={m.key} style={{ minWidth: m.w }}
                                className="border-b border-r border-border-soft px-3 py-1.5 text-right tabular-nums text-text-primary last:border-r-0">
                              <span className="block">{m.fmt(v)}</span>
                              <span className="mt-0.5 block text-text-tertiary">{m.fmt(was)}</span>
                              {showDeltas && !partial && (
                                <span className="mt-0.5 block text-[11px]">
                                  <Change now={v} was={was} dir={m.dir} points={m.points} />
                                </span>
                              )}
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </TableFrame>
        </>
      )}

      <p className="text-[11.5px] text-text-tertiary">
        The Today row is the aggregate of the hours beneath it, with every ratio recomputed
        from the summed counts rather than averaged down the column &mdash; averaging would
        weight a dead 04:00 the same as a 21:00 peak.
        Same definitions as the Overview&rsquo;s session band, bucketed by hour, so a day
        summed here agrees with the daily figures. Revenue is the sum of order totals, which
        is what makes the paid column add up against it. Spend is all three channels, but only
        Meta is measured by the hour. Google arrives as one daily total from a BigQuery export
        and is shared across the hours in proportion to that hour&rsquo;s Google-driven sessions;
        Kwikchat is a flat &#8377;30,000 a day over 24. Both totals are real &mdash; the hourly
        <em>shape</em> of them is inferred, so read an individual hour&rsquo;s Google figure as an
        allocation, not a measurement. On a day still running, Google&rsquo;s total is whatever
        had been spent when the export ran this morning, so it only reaches the hours before
        that; later hours show a dash rather than a false zero.
      </p>
    </div>
  );
}
