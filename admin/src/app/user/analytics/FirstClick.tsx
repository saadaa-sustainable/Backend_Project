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
 *
 * Which is also why the section now LEADS with the gap rather than the
 * two columns: a table of two revenue figures invites exactly the
 * subtraction-by-eye that the overlap makes unsafe. One diverging bar
 * per row, centred on zero, does the subtraction once and shows its
 * direction.
 */
import { useEffect, useMemo, useState } from "react";
import { DateRangePicker } from "@/components/DateRangePicker";
import {
  ApiError,
  FirstClickRow,
  FirstClickDailyResponse,
  fetchFirstClick,
  fetchFirstClickDaily,
} from "@/lib/api";
import { ExportButton } from "@/components/ExportButton";
import { SectionHeader, FilterRule, FilterCell, FieldLabel, FigureBand, filterControlClass } from "./SectionChrome";

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
  { value: "spend", label: "Ad spend" },
  { value: "first_click_revenue", label: "First-click revenue" },
  { value: "last_click_revenue", label: "Last-click revenue" },
  { value: "lifetime_spend", label: "Lifetime spend" },
  { value: "lifetime_first_click_roas", label: "Lifetime FC ROAS" },
  { value: "first_click_roas", label: "First-click ROAS" },  // hidden at source grain
  { value: "last_click_roas", label: "Last-click ROAS" },    // hidden at source grain
  { value: "avg_days_to_convert", label: "Days to convert" },
  { value: "avg_sessions", label: "Sessions" },
];

/** How many rows the diverging chart draws. The whole table sits
 *  beneath it, so this is a lead, not a cap: twelve is as many bars as
 *  stay legible at one glance, and they are the twelve whose two ends
 *  disagree most — which is the only question the chart is asked. */
const DIVERGING_ROWS = 12;
const SPEND_SORTS = ["spend", "first_click_roas", "last_click_roas",
                     "lifetime_spend", "lifetime_first_click_roas"];

function num(n: number | null | undefined, digits = 0) {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function rupees(n: number) {
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
}

export function FirstClick() {
  const [grain, setGrain] = useState("ad");
  // Which date the window means for the FIRST-click side. The last-click
  // side never moves: the last touch IS the converting session.
  const [basis, setBasis] = useState<"order" | "first_touch">("order");
  const [sort, setSort] = useState("first_click_revenue");
  // Header clicks sort server-side, not in the page. That matters because
  // the table is a TOP-N: reversing the direction changes which rows come
  // back, not just their order. Ascending is how you find the ads opening
  // least, and client-side sorting could only ever reorder the 200 the
  // server already picked as the highest.
  const [direction, setDirection] = useState<"asc" | "desc">("desc");
  // First click on a column sorts it descending -- the common question is
  // "which is biggest". Clicking the same one again reverses it.
  const toggleSort = (key: string) => {
    if (sort === key) setDirection((d) => (d === "desc" ? "asc" : "desc"));
    else { setSort(key); setDirection("desc"); }
  };

  // Width of the first column, draggable from its right edge.
  //
  // An ad name here is not a label, it is the ad's spec sheet:
  // `CLP-SDAMK+MU+NA+IHP+SDVSK_VRP_CI_CCL001-1066-02/10/26` carries the
  // placement, the SKUs, the format, the creative code and the date.
  // Truncated at 300px it reads as `CLP-SDAMK+MU+NA+IHP+SDVSK_VRP_CI`,
  // which is the same opening for dozens of different ads -- so the one
  // thing that tells two rows apart is the part that gets cut off.
  // Hence a handle rather than a bigger fixed width: the names are long
  // enough that any width wide enough to read them would crowd out the
  // numbers for everyone who does not need them.
  const LABEL_MIN = 160;
  const LABEL_MAX = 900;
  const LABEL_DEFAULT = 300;
  const [labelWidth, setLabelWidth] = useState(LABEL_DEFAULT);

  // Pointer events, not mouse: one path covers trackpad, mouse and touch.
  // Capture on the handle so a fast drag that leaves the element still
  // tracks, instead of sticking at the last position inside it.
  const startLabelResize = (e: React.PointerEvent<HTMLSpanElement>) => {
    e.preventDefault();
    const handle = e.currentTarget;
    const startX = e.clientX;
    const startWidth = labelWidth;
    handle.setPointerCapture(e.pointerId);
    const onMove = (ev: PointerEvent) => {
      const next = startWidth + (ev.clientX - startX);
      setLabelWidth(Math.min(LABEL_MAX, Math.max(LABEL_MIN, next)));
    };
    const onUp = () => {
      handle.releasePointerCapture(e.pointerId);
      handle.removeEventListener("pointermove", onMove);
      handle.removeEventListener("pointerup", onUp);
      handle.removeEventListener("pointercancel", onUp);
    };
    handle.addEventListener("pointermove", onMove);
    handle.addEventListener("pointerup", onUp);
    handle.addEventListener("pointercancel", onUp);
  };
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
  const [unpairedOrders, setUnpairedOrders] = useState(0);
  const [unpairedRevenue, setUnpairedRevenue] = useState(0);
  const [windowFirst, setWindowFirst] = useState(0);
  const [windowLast, setWindowLast] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  /** Which question the chart above the table answers. "gap" is the
   *  section's own: which entities the two models disagree about.
   *  "daily" is the other one people keep asking of it -- WHEN the
   *  window's revenue was opened, as against when it arrived.
   *
   *  A separate fetch, and only once the reader asks for it: the
   *  day-wise query reads every order in the window rather than the
   *  aggregate the table already has, and most visits never open it. */
  const [chartView, setChartView] = useState<"gap" | "daily">("gap");
  const [daily, setDaily] = useState<FirstClickDailyResponse | null>(null);
  const [dailyLoading, setDailyLoading] = useState(false);
  const [dailyError, setDailyError] = useState<string | null>(null);

  const filters = useMemo(
    () => ({ grain, sort, direction, from_date: fromDate, to_date: toDate, limit, basis }),
    [grain, sort, direction, fromDate, toDate, limit, basis],
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
        setUnpairedOrders(res.orders_unpaired ?? 0);
        setUnpairedRevenue(res.revenue_unpaired ?? 0);
        setWindowFirst(res.first_click_revenue_total ?? 0);
        setWindowLast(res.last_click_revenue_total ?? 0);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Could not reach the FastAPI backend. Is it running?");
      })
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, [filters]);

  useEffect(() => {
    if (chartView !== "daily") return;
    let cancelled = false;
    setDailyLoading(true);
    setDailyError(null);
    fetchFirstClickDaily({ grain, from_date: fromDate, to_date: toDate })
      .then((res) => { if (!cancelled) setDaily(res); })
      .catch((err: unknown) => {
        if (cancelled) return;
        setDailyError(err instanceof ApiError ? err.message : "Could not load the day-wise view.");
      })
      .finally(() => !cancelled && setDailyLoading(false));
    return () => { cancelled = true; };
  }, [chartView, grain, fromDate, toDate]);

  const pct = ordersTotal ? (reattributed * 100) / ordersTotal : 0;
  const grainNoun = grain === "ad" ? "Ad" : grain === "adset" ? "Ad set" : "Source";

  /** One scale for both series, so a day's opened and closed columns are
   *  read against each other rather than each against its own max.
   *
   *  Carried-in is deliberately NOT in it. Drawn to the daily scale it
   *  was 5.1x the TALLEST real day at account scale -- Rs 86.3L of
   *  backlog against Rs 16.8L -- and flattened every other column into a
   *  stub.
   *  It is a backlog of journeys opened before these dates, not a day,
   *  so it gets its own detached block to the left of the axis instead
   *  of a bar competing with days it is not comparable to. */
  const dailyMax = useMemo(() => {
    if (!daily) return 0;
    return daily.rows.reduce(
      (m, d) => Math.max(m, d.opened_revenue, d.closed_revenue),
      0,
    );
  }, [daily]);

  /** The gap, biggest first, both directions. Sorted on the ABSOLUTE
   *  difference so a source that last click over-credits is as visible
   *  as one it under-credits -- the section is about disagreement, and
   *  a signed sort would bury one half of it at the bottom. */
  const diverging = useMemo(() => {
    const scored = rows
      .map((r) => ({ row: r, delta: r.first_click_revenue - r.last_click_revenue }))
      .filter((d) => d.delta !== 0)
      .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
      .slice(0, DIVERGING_ROWS);
    const maxAbs = scored.reduce((m, d) => Math.max(m, Math.abs(d.delta)), 0);
    return { scored, maxAbs };
  }, [rows]);

  return (
    <div className="flex flex-col gap-5">
      {/* "Full credit on each end, never split -- read a column, not a
          row" is the rule this whole section rests on. It is in Help as
          "first-vs-last", behind the ? -- a rule you learn once, not a
          paragraph above the controls every day. */}
      <SectionHeader title="First Click" helpId="first-vs-last" />

      <FilterRule
        actions={
          <>
            {matched > rows.length && (
              <span
                className="bg-warning-bg px-1.5 py-0.5 text-[11.5px] font-medium text-warning-text tabular-nums"
                title="The row cap is below the number of entities matched in this window. Raise Rows to see the rest."
              >
                showing {rows.length.toLocaleString()} of {matched.toLocaleString()}
              </span>
            )}
            <span className="text-[11.5px] text-text-tertiary tabular-nums">
              {ordersTotal.toLocaleString()} orders ·{" "}
              <strong className="font-medium text-text-primary">{reattributed.toLocaleString()}</strong> reattributed
              {" "}({pct.toFixed(1)}%)
            </span>
            <ExportButton
              rows={rows as unknown as Record<string, unknown>[]}
              columns={Object.keys(rows[0] ?? {})
                .filter((key) => key !== "first_click_spend" && key !== "last_click_spend")
                .map((key) => ({ key }))}
              filename="first_vs_last_click"
              disabled={loading || !rows.length}
            />
          </>
        }
      >
        <FilterCell label="Date range">
          <DateRangePicker
            value={{ from: fromDate, to: toDate }}
            preset={datePreset}
            bare
            align="left"
            onApply={(r, pk) => { setDatePreset(pk); setFromDate(r.from); setToDate(r.to); }}
          />
        </FilterCell>

        <FilterCell label="Grain" className="w-32" htmlFor="fc-grain">
          <select
            id="fc-grain"
            value={grain}
            onChange={(e) => {
              const next = e.target.value;
              setGrain(next);
              // Reset in the same event, avoiding an extra request sorted on
              // an unavailable spend column when switching to Source.
              if (next === "source" && SPEND_SORTS.includes(sort)) setSort("first_click_revenue");
            }}
            className={filterControlClass}
          >
            {GRAIN_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </FilterCell>

        <FilterCell label="Window means" className="w-56" htmlFor="fc-basis">
          <select
            id="fc-basis"
            value={basis}
            onChange={(e) => setBasis(e.target.value as "order" | "first_touch")}
            className={filterControlClass}
            title={basis === "order"
              ? "Orders that CLOSED in these dates. First-click revenue can come from journeys opened weeks earlier, while spend is in-window only — so first-click ROAS reads high for an established ad."
              : "Journeys this entity OPENED in these dates. First-click revenue and spend then describe the same clicks, but journeys not yet converted carry no revenue, and the two sides no longer cover the same orders."}
          >
            <option value="order">Order date</option>
            <option value="first_touch">First-touch date</option>
          </select>
        </FilterCell>

        <FilterCell label="Sort by" className="w-48" htmlFor="fc-sort">
          <select
            id="fc-sort"
            value={sort}
            onChange={(e) => { setSort(e.target.value); setDirection("desc"); }}
            className={filterControlClass}
          >
            {SORT_OPTIONS.filter(
              (o) => !(grain === "source"
                       && SPEND_SORTS.includes(o.value)),
            ).map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </FilterCell>

        <FilterCell label="Rows" className="w-24" htmlFor="fc-limit">
          <select
            id="fc-limit"
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className={filterControlClass}
          >
            {[50, 200, 1000, 5000].map((n) => (
              <option key={n} value={n}>{n === 5000 ? "All" : n}</option>
            ))}
          </select>
        </FilterCell>
      </FilterRule>

      {error && <div className="bg-error-bg px-3 py-2 text-sm text-error-text">{error}</div>}

      {loading ? (
        <p className="text-sm text-text-secondary">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-text-secondary">No attributed orders in this window.</p>
      ) : (
        <>
          <FigureBand
            figures={[
              // The WINDOW's totals, not the page's. Summed over the
              // rows on screen the two disagree — the table sorts by
              // first-click revenue, so the top 200 by that measure are
              // not the top 200 by last-click revenue, and at 200 rows
              // the pair came out ₹56,746 apart while every entity
              // totalled identically. A headline that moves when you
              // change the row limit is a trap, so these do not.
              {
                label: "First-click revenue",
                value: rupees(windowFirst),
                basis: `full value of every order opened by any of the ${matched.toLocaleString()} ${grainNoun.toLowerCase()}s in this window`,
              },
              {
                label: "Last-click revenue",
                value: rupees(windowLast),
                basis: "equal to the figure beside it by construction — the same orders counted at their other end, so never add the two",
              },
              {
                label: "Orders",
                value: ordersTotal.toLocaleString(),
                basis: "GA4-attributed orders in this window",
              },
              {
                label: "Reattributed",
                value: reattributed.toLocaleString(),
                basis: `${pct.toFixed(1)}% of orders change hands between the first and last click`,
              },
              // The cost of making the two revenue columns agree. An
              // order with an ad at one end only cannot appear on both
              // sides, so counting it would reopen the gap — but it is
              // real revenue, and a section that drops it without
              // saying so reads as if it covered every order.
              {
                label: "Not attributed",
                value: rupees(unpairedRevenue),
                basis: `${unpairedOrders.toLocaleString()} orders carried an ad at one end only, so neither column counts them`,
              },
            ]}
          />

          {/* ═══════════════════════════════════════════════════════════
              Two questions, one slot.

              The gap view is the section's own: WHICH entities the two
              models disagree about. The daily view is WHEN the window's
              revenue was opened as against when it arrived — a different
              axis entirely, and the only one that has to decide which
              day an order opened before the window belongs to.
             ═══════════════════════════════════════════════════════════ */}
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border-primary pb-1.5">
              <div className="flex items-center gap-1">
                {([["gap", "Where the two disagree"], ["daily", "Day by day"]] as const).map(
                  ([v, label]) => (
                    <button
                      key={v}
                      type="button"
                      onClick={() => setChartView(v)}
                      aria-pressed={chartView === v}
                      className={`px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider ${
                        chartView === v
                          ? "text-text-primary border-b-2 border-text-primary"
                          : "text-text-tertiary border-b-2 border-transparent hover:text-text-secondary"
                      }`}
                    >
                      {label}
                    </button>
                  ),
                )}
              </div>
              <span className="text-[11.5px] text-text-tertiary">
                {chartView === "gap"
                  ? `first-click minus last-click revenue, by ${grainNoun.toLowerCase()} · widest ${diverging.scored.length} of ${rows.length.toLocaleString()}`
                  : `revenue by IST day · every ${grainNoun.toLowerCase()} at this grain`}
              </span>
            </div>
          </div>

          {/* The point of the section, drawn once. Two revenue columns
              side by side ask the reader to subtract eighteen pairs of
              seven-digit numbers by eye, and the subtraction is the only
              thing either column is here for. A bar right of the zero
              line is credit first click claims and last click gives to
              somebody else; a bar left of it is credit last click takes
              from an opener elsewhere.

              Neutral ink on both sides, deliberately: a hand-off is not
              a failure, it is where the two models part, and colouring
              one direction red would make a fact look like a verdict. */}
          {chartView === "gap" && diverging.scored.length > 0 && (
            <div className="flex flex-col gap-2">
              {/* Capped, not full-bleed. The zero line is the thing
                  being read against, and at 1600px a full-width axis
                  pushed it 600px from the labels with nothing in
                  between -- the bars stopped reading as one scale. */}
              <div className="flex max-w-[1100px] flex-col">
                {diverging.scored.map(({ row: r, delta }) => {
                  const width = diverging.maxAbs > 0 ? (Math.abs(delta) / diverging.maxAbs) * 100 : 0;
                  const right = delta > 0;
                  return (
                    <div
                      key={`${r.source}-${r.channel}`}
                      className="flex items-center gap-3 border-t border-border-soft py-1.5 first:border-t-0"
                      title={`${r.label}  ·  opened ₹${num(r.first_click_revenue)}, closed ₹${num(r.last_click_revenue)}`}
                    >
                      <div className="w-[230px] shrink-0 truncate text-[13px] text-text-primary">{r.label}</div>
                      <div className="flex min-w-[120px] flex-1 items-center">
                        <div className="flex w-1/2 justify-end">
                          {!right && <div className="h-2 bg-text-tertiary" style={{ width: `${width}%` }} />}
                        </div>
                        <div className="h-4 w-px shrink-0 bg-border-primary" />
                        <div className="w-1/2">
                          {right && <div className="h-2 bg-text-primary" style={{ width: `${width}%` }} />}
                        </div>
                      </div>
                      <div
                        className={`w-[140px] shrink-0 text-right text-[13px] tabular-nums ${
                          right ? "text-text-primary" : "text-text-secondary"
                        }`}
                      >
                        {right ? "+" : "−"}₹{num(Math.abs(delta))}
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="flex max-w-[1100px] justify-between border-t border-border-soft pt-1.5 text-[11px] text-text-tertiary">
                <span>last click credits more</span>
                <span>first click credits more</span>
              </div>
            </div>
          )}

          {/* ═══════════════════════════════════════════════════════════
              Day by day.

              A window total never has to say which DAY an order belongs
              to. A daily series does, and the two bases on the selector
              above each answer it in a way that is wrong for a chart: by
              order date an ad's work shows on the day the money arrived,
              and by first-touch date an order opened before the window
              vanishes from the view entirely — measured on one real ad,
              Rs 3,112 of the window's Rs 26,471, gone with nothing on
              the page to say so.

              So every order the window contains is kept and placed on
              the day it opened, or on day one where that is earlier. The
              clamped part is drawn as its OWN segment rather than folded
              in: folding turned Rs 806 of real same-day opening into a
              Rs 3,918 bar, 4.9x, an artifact of where the window was cut
              that moves when you scroll it. Hatched, because it is the
              one segment that does not describe the day it sits on.
             ═══════════════════════════════════════════════════════════ */}
          {chartView === "daily" && (
            dailyError ? (
              <p className="text-sm text-error-text">{dailyError}</p>
            ) : dailyLoading || !daily ? (
              <p className="text-sm text-text-secondary">Loading…</p>
            ) : daily.rows.length === 0 ? (
              <p className="text-sm text-text-secondary">No attributed orders in this window.</p>
            ) : (
              <div className="flex flex-col gap-3">
                <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-[11.5px] text-text-secondary">
                  <span className="flex items-center gap-1.5">
                    <span className="inline-block h-2.5 w-3.5 bg-text-primary" />opened that day
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="inline-block h-2.5 w-3.5" style={{ background:
                      "repeating-linear-gradient(45deg,currentColor 0 2px,transparent 2px 4px)" }} />
                    carried in from before the window
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="inline-block h-2.5 w-3.5 bg-text-tertiary" />closed that day
                  </span>
                </div>

                <div className="flex items-stretch gap-3 overflow-x-auto">
                  {daily.carried_in_total > 0 && (
                    /* Off the daily axis on purpose: this is every journey
                       opened before the window, not a day, and at account
                       scale it is 5.1x the tallest real one. Full height,
                       labelled with its own value, divided from the days
                       by a rule so it cannot be read as one of them. */
                    <div className="flex shrink-0 flex-col">
                      <div
                        className="flex h-[200px] w-[72px] items-end justify-center border-b border-border-primary"
                        title={`₹${num(daily.carried_in_total)} from ${daily.carried_in_orders_total.toLocaleString()} journeys opened before ${daily.rows[0]?.day}`}
                      >
                        <div
                          className="w-[30px] text-text-primary"
                          style={{
                            height: "100%",
                            background:
                              "repeating-linear-gradient(45deg,currentColor 0 2px,transparent 2px 4px)",
                          }}
                        />
                      </div>
                      <div className="w-[72px] pt-1 text-center text-[9.5px] leading-tight text-text-tertiary">
                        before
                      </div>
                    </div>
                  )}
                  {daily.carried_in_total > 0 && (
                    <div className="shrink-0 self-stretch border-l border-dashed border-border-primary" />
                  )}
                  <div className="min-w-max">
                  <div className="flex h-[200px] items-end gap-[3px] border-b border-border-primary">
                    {daily.rows.map((d) => {
                      const h = (v: number) => (dailyMax > 0 ? (v / dailyMax) * 100 : 0);
                      return (
                        <div
                          key={d.day}
                          className="flex h-full w-[26px] shrink-0 items-end justify-center gap-[2px]"
                          title={[
                            d.day,
                            `opened ₹${num(d.opened_revenue)} (${d.opened_orders} orders)`,
                            d.carried_in_revenue > 0
                              ? `carried in ₹${num(d.carried_in_revenue)} (${d.carried_in_orders} orders)`
                              : null,
                            `closed ₹${num(d.closed_revenue)} (${d.closed_orders} orders)`,
                            d.spend !== null ? `spend ₹${num(d.spend)}` : null,
                          ].filter(Boolean).join("\n")}
                        >
                          <div className="w-[11px] bg-text-primary" style={{ height: `${h(d.opened_revenue)}%` }} />
                          <div className="w-[11px] bg-text-tertiary" style={{ height: `${h(d.closed_revenue)}%` }} />
                          {d.opened_revenue === 0 && d.closed_revenue === 0 && (
                            <div className="h-px w-full bg-border-soft" />
                          )}
                        </div>
                      );
                    })}
                  </div>
                  <div className="flex min-w-max gap-[3px] pt-1">
                    {daily.rows.map((d, i) => (
                      <div
                        key={d.day}
                        className="w-[26px] shrink-0 text-center text-[9.5px] tabular-nums text-text-tertiary"
                      >
                        {/* Every day on a short window, every third on a
                            long one -- thirty labels at 26px collide. */}
                        {daily.rows.length <= 10 || i % 3 === 0 ? d.day.slice(8) : ""}
                      </div>
                    ))}
                  </div>
                  </div>
                </div>

                <div className="flex flex-wrap gap-x-8 gap-y-1 border-t border-border-soft pt-2 text-[12px] tabular-nums text-text-secondary">
                  <span>opened <strong className="text-text-primary">{rupees(daily.opened_total)}</strong></span>
                  <span>carried in <strong className="text-text-primary">{rupees(daily.carried_in_total)}</strong></span>
                  <span>
                    = first-click revenue{" "}
                    <strong className="text-text-primary">
                      {rupees(daily.opened_total + daily.carried_in_total)}
                    </strong>
                  </span>
                  <span>closed <strong className="text-text-primary">{rupees(daily.closed_total)}</strong></span>
                  {daily.spend_total !== null && (
                    <span>spend <strong className="text-text-primary">{rupees(daily.spend_total)}</strong></span>
                  )}
                </div>

                <p className="text-[11.5px] text-text-tertiary">
                  Opened plus carried-in is the window&rsquo;s whole first-click revenue across all{" "}
                  {matched.toLocaleString()} {grainNoun.toLowerCase()}s at this grain — not the{" "}
                  {rows.length.toLocaleString()} the table below is limited to, so the two headline
                  figures differ by design.{" "}
                  {daily.carried_in_total > 0 ? (
                    <>
                      The hatched block is <strong>{rupees(daily.carried_in_total)}</strong> from{" "}
                      {daily.carried_in_orders_total.toLocaleString()} journeys opened{" "}
                      <strong>before</strong> {daily.rows[0]?.day}. It sits off the day axis because
                      it is a backlog, not a day: it has no width in time, it dwarfs any real day,
                      and it changes if you move the window.
                    </>
                  ) : (
                    <>Every journey in this window also opened inside it, so nothing is carried in.</>
                  )}
                </p>
              </div>
            )
          )}

          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border-primary pb-1.5">
              <FieldLabel>By {grainNoun.toLowerCase()}</FieldLabel>
              <span className="text-[11.5px] text-text-tertiary tabular-nums">
                {rows.length.toLocaleString()} rows
              </span>
            </div>
            {grain !== "source" && <p className="text-[11.5px] text-text-tertiary">
              Ad spend covers the selected date range, counted once per matched {grainNoun.toLowerCase()}. Both ROAS columns use this spend. The two lifetime columns ignore the dates entirely and cover all history held.
            </p>}
            {basis === "first_touch" && <p className="text-[11.5px] text-warning-text">
              First-click columns count journeys <strong>opened</strong> in these dates, so they line up with the spend that bought them. Journeys opened here but not yet converted carry no revenue, which understates recent {grainNoun.toLowerCase()}s. The two sides no longer cover the same orders — do not reconcile against Last Click on this setting.
            </p>}
            {/* Hairlines and a sticky first column, no container: the
                box this replaces carried a rounded border AND a shadow,
                which is the one combination this surface does not use. */}
            <div className="max-h-[70vh] overflow-auto border-b border-border-primary">
              <table className="w-full min-w-max table-auto border-separate border-spacing-0 text-left text-sm">
                <thead>
                  <tr>
                    <th
                      style={{ width: labelWidth, minWidth: labelWidth, maxWidth: labelWidth }}
                      className="sticky left-0 top-0 z-30 h-9 whitespace-nowrap border-b border-r border-border-primary bg-bg-muted px-0 py-0 text-left align-middle text-[10px] font-semibold uppercase tracking-[0.08em] text-text-tertiary"
                    >
                      {/* `relative` has to live on an inner div: the th is
                          already `sticky`, and an element can only hold one
                          position value. */}
                      <div
                        style={{ width: labelWidth }}
                        className="relative flex h-9 items-center overflow-hidden px-3"
                      >
                        <span className="truncate">{grainNoun}</span>
                        <span className="ml-1 text-[9px] font-normal normal-case text-text-tertiary">
                          {labelWidth !== LABEL_DEFAULT ? `${labelWidth}px` : ""}
                        </span>
                        <span
                          role="separator"
                          aria-orientation="vertical"
                          aria-label="Drag to resize the name column"
                          title="Drag to widen — the end of an ad name is the part that tells two rows apart. Double-click to reset."
                          onPointerDown={startLabelResize}
                          onDoubleClick={() => setLabelWidth(LABEL_DEFAULT)}
                          className="absolute right-0 top-0 h-full w-1.5 cursor-col-resize bg-transparent hover:bg-border-primary"
                        />
                      </div>
                    </th>
                    {grain !== "source" && (
                      <th
                        title="The channel this belongs to. Also what explains a row showing a raw id: only Meta ad ids resolve to names, while kwikengage, sagepilot-ai and google put their own tokens in the same GA4 field."
                        className="sticky top-0 z-20 h-9 whitespace-nowrap border-b border-border-primary bg-bg-muted px-3 py-2 text-left align-middle text-[10px] font-semibold uppercase tracking-[0.08em] text-text-tertiary"
                      >
                        Channel
                      </th>
                    )}
                    {([
                      // Spend is dropped entirely at source grain rather than
                      // rendered as a column of dashes: a "source" like META or
                      // affiliate is not a billable entity, so there is no number
                      // being withheld -- the question does not apply.
                      ...(grain === "source" ? [] : [
                        ["Ad spend", "This ad or ad set's total Meta spend over the selected date range, counted once regardless of how many orders it opened or closed. Both ROAS columns use this amount. A dash means spend is unavailable.", "spend"] as const,
                      ]),
                      ["First-click revenue", "Full value of every order this one OPENED — the first session of the journey came from here. Not a fractional split.", "first_click_revenue"],
                      ["Last-click revenue", "Full value of every order this one CLOSED. Deliberately overlaps the column before it: the same order's value appears under both its opener and its closer, so do not add the two across.", "last_click_revenue"],
                      // Both ROAS columns share the spend denominator, so they
                      // are dropped at source grain for the same reason spend
                      // is: there is no billable entity to divide by.
                      ...(grain === "source" ? [] : [
                        ["First-click ROAS", "First-click revenue divided by Ad spend for the selected date range. A dash means spend is unavailable, below ₹1,000, or there are no first-click orders. The first touch can predate this order window.", "first_click_roas"] as const,
                        ["Last-click ROAS", "Last-click revenue divided by the same Ad spend. A dash means spend is unavailable, below ₹1,000, or there are no last-click orders.", "last_click_roas"] as const,
                        // Lifetime pair: the same two questions asked of the
                        // whole history rather than the picked dates, so a
                        // row shows recent form beside total return.
                        ["Lifetime spend", "Everything Meta has billed this " + grainNoun.toLowerCase() + " across all history held, ignoring the selected dates. Equals Ad spend for anything whose whole life sits inside the window.", "lifetime_spend"] as const,
                        ["Lifetime FC ROAS", "Lifetime first-click revenue divided by lifetime spend. Compare it with First-click ROAS beside it: a higher windowed number means the " + grainNoun.toLowerCase() + " is doing better lately than it has overall. A dash means lifetime spend is unavailable or below ₹1,000.", "lifetime_first_click_roas"] as const,
                      ]),
                      ["Days to convert", "Average days from first session to order, over the orders this one started.", "avg_days_to_convert"],
                      ["Sessions", "Average sessions before the order, over the orders this one started.", "avg_sessions"],
                    ] as const).map(([label, title, key]) => {
                      const active = sort === key;
                      return (
                        <th
                          key={label}
                          // Native title stays the explanation. The sort hint
                          // goes on the button so a hover does not replace the
                          // column's meaning with a UI instruction.
                          title={title}
                          aria-sort={active ? (direction === "desc" ? "descending" : "ascending") : "none"}
                          className={`sticky top-0 z-20 h-9 whitespace-nowrap border-b border-border-primary px-0 py-0 text-right align-middle text-[10px] font-semibold uppercase tracking-[0.08em] ${active ? "bg-bg-surface text-text-primary" : "bg-bg-muted text-text-tertiary"}`}
                        >
                          <button
                            type="button"
                            onClick={() => toggleSort(key)}
                            aria-label={`Sort by ${label}, ${active && direction === "desc" ? "ascending" : "descending"}`}
                            className="flex h-9 w-full items-center justify-end gap-1 px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] hover:text-text-primary"
                          >
                            {label}
                            {/* Reserve the caret's width on every header so the
                                row does not shift when the active column moves. */}
                            <span aria-hidden="true" className={`w-2 text-[8px] ${active ? "opacity-100" : "opacity-0"}`}>
                              {direction === "desc" ? "\u25bc" : "\u25b2"}
                            </span>
                          </button>
                        </th>
                      );
                    })}
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
                      <tr key={`${r.source}-${r.channel}`} className="hover:bg-bg-surface">
                        <td
                          style={{ width: labelWidth, minWidth: labelWidth, maxWidth: labelWidth }}
                          className="sticky left-0 z-10 border-b border-r border-border-soft bg-bg-white px-3 py-1.5 text-xs text-text-primary"
                          title={r.label === r.source ? r.source : `${r.label}  ·  ${r.source}`}
                        >
                          {/* Definite width here, not just on the td -- see the
                              header's note on table-auto. */}
                          <div style={{ width: labelWidth - 24 }} className="truncate">
                            {r.label}
                          </div>
                        </td>
                        {grain !== "source" && (
                          <td className="border-b border-border-soft px-3 py-1.5 text-xs text-text-secondary">
                            {r.channel}
                          </td>
                        )}
                        {grain !== "source" && (
                          <td className="border-b border-border-soft px-3 py-1.5 text-right font-mono text-[11px] text-text-primary">
                            {r.spend == null
                              ? <span className="text-text-tertiary" title="Meta spend is unavailable for this entity in the selected date range">—</span>
                              : num(r.spend)}
                          </td>
                        )}
                        <td
                          className={`border-b border-border-soft px-3 py-1.5 text-right font-mono text-[11px] ${unbilled > 0 ? "font-semibold text-warning-text" : "text-text-primary"}`}
                          title={unbilled > 0 ? `₹${num(unbilled)} more opened than closed — credit last click gives to another ad` : undefined}
                        >
                          {num(r.first_click_revenue)}
                        </td>
                        <td className="border-b border-border-soft px-3 py-1.5 text-right font-mono text-[11px] text-text-primary">{num(r.last_click_revenue)}</td>
                        {grain !== "source" && (
                          <td
                            className={`border-b border-border-soft px-3 py-1.5 text-right font-mono text-[11px] ${unbilled > 0 ? "font-semibold text-warning-text" : "text-text-primary"}`}
                            title={r.first_click_roas == null
                              ? "No first-click orders, spend unavailable, or below ₹1,000 in this window"
                              : unbilled > 0
                                ? "Revenue from journeys opened earlier; compare with last-click ROAS beside it"
                                : undefined}
                          >
                            {num(r.first_click_roas, 2)}
                          </td>
                        )}
                        {grain !== "source" && (
                          <td
                            className="border-b border-border-soft px-3 py-1.5 text-right font-mono text-[11px] text-text-primary"
                            title={r.last_click_roas == null
                              ? "No last-click orders, spend unavailable, or below ₹1,000 in this window"
                              : undefined}
                          >
                            {num(r.last_click_roas, 2)}
                          </td>
                        )}
                        {grain !== "source" && (
                          <td
                            className="border-b border-border-soft px-3 py-1.5 text-right font-mono text-[11px] text-text-primary"
                            title={r.lifetime_spend == null
                              ? "Meta never billed this entity, so it has no lifetime cost"
                              : undefined}
                          >
                            {r.lifetime_spend == null
                              ? <span className="text-text-tertiary">&mdash;</span>
                              : num(r.lifetime_spend)}
                          </td>
                        )}
                        {grain !== "source" && (
                          <td
                            className={`border-b border-border-soft px-3 py-1.5 text-right font-mono text-[11px] ${
                              // Flag the ad whose recent form is running ahead of
                              // what it has returned overall -- the comparison the
                              // column exists for, and easy to miss by eye.
                              r.first_click_roas != null && r.lifetime_first_click_roas != null
                              && r.first_click_roas > r.lifetime_first_click_roas
                                ? "text-success-text" : "text-text-primary"}`}
                            title={r.lifetime_first_click_roas == null
                              ? "Lifetime spend unavailable or below ₹1,000"
                              : r.first_click_roas != null && r.first_click_roas > r.lifetime_first_click_roas
                                ? "Doing better in the selected range than over its whole life"
                                : undefined}
                          >
                            {num(r.lifetime_first_click_roas, 2)}
                          </td>
                        )}
                        <td className="border-b border-border-soft px-3 py-1.5 text-right font-mono text-[11px] text-text-primary">{num(r.avg_days_to_convert, 1)}</td>
                        <td className="border-b border-border-soft px-3 py-1.5 text-right font-mono text-[11px] text-text-primary">{num(r.avg_sessions, 1)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      <p className="text-[11.5px] text-text-tertiary">
        GA4 sees about 76% of orders, so these counts are a subset of Shopify&rsquo;s. Use them to compare
        sources against each other, not as an order total. Windowed on the order&rsquo;s IST day, the same
        boundary the Shopify columns elsewhere use.
      </p>
    </div>
  );
}
