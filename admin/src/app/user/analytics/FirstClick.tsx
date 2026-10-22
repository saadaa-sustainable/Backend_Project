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
import { ApiError, FirstClickRow, fetchFirstClick } from "@/lib/api";
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
  { value: "spend", label: "Spend" },  // hidden at source grain, see below
  { value: "first_click_revenue", label: "First-click revenue" },
  { value: "last_click_revenue", label: "Last-click revenue" },
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

function num(n: number | null | undefined, digits = 0) {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function rupees(n: number) {
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
}

export function FirstClick() {
  const [grain, setGrain] = useState("ad");
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
  // Source grain has no spend, so a spend sort there would order every row
  // by NULL and look like the control had broken. Fall back instead.
  useEffect(() => {
    // Source grain has no Meta spend, so spend and both ROAS columns are
    // absent there -- sorting on any of them would order every row by null.
    if (grain === "source" && ["spend", "first_click_roas", "last_click_roas"].includes(sort))
      setSort("first_click_revenue");
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
    () => ({ grain, sort, direction, from_date: fromDate, to_date: toDate, limit }),
    [grain, sort, direction, fromDate, toDate, limit],
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
  const grainNoun = grain === "ad" ? "Ad" : grain === "adset" ? "Ad set" : "Source";

  const totals = useMemo(() => {
    let first = 0;
    let last = 0;
    for (const r of rows) {
      first += r.first_click_revenue;
      last += r.last_click_revenue;
    }
    return { first, last };
  }, [rows]);

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
            onChange={(e) => setGrain(e.target.value)}
            className={filterControlClass}
          >
            {GRAIN_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
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
                       && ["spend", "first_click_roas", "last_click_roas"].includes(o.value)),
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
              {
                label: "First-click revenue",
                value: rupees(totals.first),
                basis: `full value of every order opened by the ${rows.length.toLocaleString()} ${grainNoun.toLowerCase()}s shown`,
              },
              {
                label: "Last-click revenue",
                value: rupees(totals.last),
                basis: "overlaps the figure beside it — do not add the two",
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
            ]}
          />

          {/* ═══════════════════════════════════════════════════════════
              Where the two disagree.

              The point of the section, drawn once. Two revenue columns
              side by side ask the reader to subtract eighteen pairs of
              seven-digit numbers by eye, and the subtraction is the only
              thing either column is here for. A bar right of the zero
              line is credit first click claims and last click gives to
              somebody else; a bar left of it is credit last click takes
              from an opener elsewhere.

              Neutral ink on both sides, deliberately: a hand-off is not
              a failure, it is where the two models part, and colouring
              one direction red would make a fact look like a verdict.
             ═══════════════════════════════════════════════════════════ */}
          {diverging.scored.length > 0 && (
            <div className="flex flex-col gap-2">
              <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border-primary pb-1.5">
                <FieldLabel>Where the two disagree</FieldLabel>
                <span className="text-[11.5px] text-text-tertiary">
                  first-click minus last-click revenue, by {grainNoun.toLowerCase()} · widest {diverging.scored.length} of{" "}
                  {rows.length.toLocaleString()}
                </span>
              </div>
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

          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border-primary pb-1.5">
              <FieldLabel>By {grainNoun.toLowerCase()}</FieldLabel>
              <span className="text-[11.5px] text-text-tertiary tabular-nums">
                {rows.length.toLocaleString()} rows
              </span>
            </div>
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
                      ...(grain === "source" ? [] : [["Spend", "Meta spend for this ad over the selected date range. A dash means Meta never billed this id — kwikengage, affiliate and google tokens share the same GA4 field and have no Meta spend to report.", "spend"] as const]),
                      ["First-click revenue", "Full value of every order this one OPENED — the first session of the journey came from here. Not a fractional split.", "first_click_revenue"],
                      ["Last-click revenue", "Full value of every order this one CLOSED. Deliberately overlaps the column before it: the same order's value appears under both its opener and its closer, so do not add the two across.", "last_click_revenue"],
                      // Both ROAS columns share the spend denominator, so they
                      // are dropped at source grain for the same reason spend
                      // is: there is no billable entity to divide by.
                      ...(grain === "source" ? [] : [
                        ["First-click ROAS", "First-click revenue over this ad's own spend in the window. A dash means Meta billed it under ₹1,000 here, where the quotient stops being a rate. Runs high for an ad winding down: the revenue comes from journeys it opened up to weeks earlier while its spend falls away — so compare it with this row's last-click ROAS, not another row's.", "first_click_roas"] as const,
                        ["Last-click ROAS", "Last-click revenue over the same spend — what every rupee it CLOSED returned. The closing click sits near the order, so this one lines up with the window far better than first-click ROAS does.", "last_click_roas"] as const,
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
                            {r.spend === null || r.spend === undefined
                              ? <span className="text-text-tertiary" title="Meta never billed this id">—</span>
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
                              ? "Under ₹1,000 of spend in this window — too little to divide by"
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
                              ? "Under ₹1,000 of spend in this window — too little to divide by"
                              : undefined}
                          >
                            {num(r.last_click_roas, 2)}
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
