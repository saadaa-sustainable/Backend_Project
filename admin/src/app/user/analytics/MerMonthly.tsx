"use client";

import { useState } from "react";
import type { MerGrain, MerMonth } from "@/lib/api";
import { FieldLabel, Segmented, TableFrame, filterControlClass } from "./SectionChrome";

/**
 * The media plan's Blended MER tab: one period against the one before
 * it, with the full run behind it.
 *
 * The RUN is the default: every period on screen, in the plan's own
 * orientation -- metrics down the rows, periods across the columns.
 * That is what a reader wants first, the whole shape.
 *
 * COMPARE is opt-in, behind its own button. It answers a narrower
 * question, about one period in particular: September against August,
 * Q3 against Q2, 2026 against 2025. A single month's MER says little
 * alone -- 3.35x is good or bad only against what it was last month --
 * but that is a question asked OF the run, not instead of it.
 *
 * Where the prior period does not exist the comparison says so once,
 * in a sentence, rather than showing a dash on every row. The
 * warehouse starts on 2026-01-01, so the YEAR comparison has nothing
 * to answer to and will keep saying so until 2027.
 *
 * Both views are recomputed from the daily rows at the chosen grain,
 * never rolled up from each other.
 *
 * Formulas track the tab as it stood on 2026-10-19, the morning it
 * changed: returning-customer % stopped double-counting the new cohort,
 * GST left the A-MER denominator for the contribution-margin line, and
 * CM % arrived. The tab's "Ad spend + GST@18%" label is now stale -- it
 * no longer adds GST -- so this says "ad spend" and applies the 18%
 * only inside CM, which is where the tab now applies it too.
 */

function periodLabel(iso: string, grain: MerGrain): string {
  const d = new Date(`${iso}T12:00:00`);
  if (grain === "year") return String(d.getFullYear());
  if (grain === "quarter") {
    return `Q${Math.floor(d.getMonth() / 3) + 1} ${String(d.getFullYear()).slice(2)}`;
  }
  return d.toLocaleDateString("en-IN", { month: "short", year: "2-digit" });
}

const GRAINS: { value: MerGrain; label: string; title: string }[] = [
  { value: "month", label: "Month", title: "Compare a month with the month before it" },
  { value: "quarter", label: "Quarter", title: "Compare a quarter with the quarter before it" },
  { value: "year", label: "Year", title: "Compare a year with the year before it" },
];

const WORD: Record<MerGrain, string> = { month: "month", quarter: "quarter", year: "year" };

/** `== null` catches undefined as well as null, and that is the point.
 *
 * These read fields straight off a cached API payload. When a row is
 * added server-side, a reader whose sessionStorage still holds the
 * PREVIOUS shape gets `undefined` for it -- and a `=== null` guard let
 * that through to `.toLocaleString`, which took the whole table down
 * with "Cannot read properties of undefined". A missing field must
 * render as an em dash, exactly like a null one; the cache key below
 * stops it happening, this stops it being fatal when it does. */
type Num = number | null | undefined;

function compact(n: Num): string {
  if (n == null) return "—";
  const a = Math.abs(n);
  if (a >= 1e7) return `${(n / 1e7).toFixed(2)} Cr`;
  if (a >= 1e5) return `${(n / 1e5).toFixed(2)} L`;
  return n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}
const num = (n: Num) => (n == null ? "—" : n.toLocaleString("en-IN"));
const x2 = (n: Num) => (n == null ? "—" : `${n.toFixed(2)}×`);
const pct = (n: Num) => (n == null ? "—" : `${n.toFixed(2)}%`);
const rupees = (n: Num) =>
  n == null ? "—" : n.toLocaleString("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });

/** How a row's change is expressed. A percent change OF a percent is
 *  true but unreadable, and a ratio moving 3.10x to 3.30x reads more
 *  clearly as +0.20x than as +6.5%. */
type Kind = "money" | "count" | "rupees" | "pct" | "ratio";

const FORMAT: Record<Kind, (n: Num) => string> = {
  money: compact, count: num, rupees, pct, ratio: x2,
};

/** Which direction of travel is the good one.
 *
 *  Green-for-up is wrong on half these rows. A Blended CAC falling 4%
 *  is the business getting CHEAPER to grow, and painting it red reads
 *  as a warning. Spend is neither: a month that spent less is not
 *  thereby better or worse, and colouring it invites someone to chase
 *  the colour rather than the ratio it feeds. */
type Better = "up" | "down" | "neutral";

interface Row {
  label: string;
  /** Absent on a heading row, which groups what follows.
   *
   *  Returns Num, not `number | null`: on a stale cached payload a
   *  field added server-side is undefined, and typing that away would
   *  only hide it from the compiler, not from the browser. */
  value?: (m: MerMonth) => Num;
  kind?: Kind;
  better?: Better;
  head?: boolean;
  strong?: boolean;
  note?: string;
  /** Marks a figure resting on the Kwikchat placeholder. */
  star?: (m: MerMonth) => boolean;
}

const ROWS: Row[] = [
  { label: "Ad spend", head: true },
  { label: "Meta", value: (m) => m.meta_spend, kind: "money", better: "neutral" },
  { label: "Google", value: (m) => m.google_spend, kind: "money", better: "neutral" },
  { label: "Kwikchat", value: (m) => m.kwikchat_spend, kind: "money", better: "neutral",
    star: (m) => m.kwikchat_estimated, note: "* a flat placeholder until real figures arrive" },
  { label: "Total ad spend", value: (m) => m.ad_spend, kind: "money", strong: true, better: "neutral",
    note: "Meta + Google + Kwikchat — the plan adds six further cost lines" },

  { label: "Platform claimed", head: true },
  { label: "Meta purchase value", value: (m) => m.meta_claimed, kind: "money", better: "neutral",
    note: "Meta's own attributed revenue. Matches the plan to the rupee." },
  { label: "Meta MER", value: (m) => m.meta_mer, kind: "ratio", strong: true },
  { label: "Google purchase value", value: (m) => m.google_claimed, kind: "money", better: "neutral",
    note: "Google's metrics.conversions_value — primary conversion actions only, verified "
        + "against the Google Ads API to the rupee on every settled day. Not "
        + "all_conversions_value, which reads 65× higher." },
  { label: "Google MER", value: (m) => m.google_mer, kind: "ratio", strong: true,
    note: "Google's claimed return on its own spend. Runs far above Meta's (5.7–12.6× vs "
        + "2.9–3.5× across May–Oct 2026) — Search, Shopping and PMax capturing high-intent "
        + "demand, not an error." },
  { label: "Platform claimed total", value: (m) => m.platform_claimed, kind: "money",
    better: "neutral", note: "Meta + Google attributed revenue." },
  { label: "Platform MER", value: (m) => m.platform_mer, kind: "ratio", strong: true,
    note: "Platform-reported: what the platforms say they returned, over the spend of the "
        + "platforms that said it (Meta + Google — Kwikchat claims nothing, so it is not in "
        + "the denominator). Read beside MER, not instead of it: against Shopify's own "
        + "revenue this ran −8.5% (Oct), −3.8% (Sep), −0.1% (Aug) and +14.0% (May 2026)." },

  { label: "D2C", head: true },
  { label: "Shopify sales", value: (m) => m.revenue, kind: "money" },
  { label: "New customers", value: (m) => m.new_customers, kind: "count" },
  { label: "Returning customers", value: (m) => m.returning_customers, kind: "count",
    note: "Shopify's own count; runs 8–10% above the plan's manual figure" },
  { label: "Sales · first-time", value: (m) => m.sales_first_time, kind: "money" },
  { label: "Sales · returning", value: (m) => m.sales_returning, kind: "money" },
  { label: "Returning customer %", value: (m) => m.returning_customer_pct, kind: "pct", strong: true,
    note: "returning ÷ (new + returning) — the plan's corrected formula" },
  { label: "Returning revenue %", value: (m) => m.returning_revenue_pct, kind: "pct", strong: true },

  { label: "Efficiency", head: true },
  { label: "MER", value: (m) => m.mer, kind: "ratio", strong: true,
    note: "Shopify sales ÷ Meta + Google + Kwikchat spend" },
  { label: "A-MER", value: (m) => m.a_mer, kind: "ratio", strong: true,
    note: "new-customer revenue ÷ ad spend, no GST — the plan's current shape" },
  { label: "Blended CAC", value: (m) => m.blended_cac, kind: "rupees", strong: true,
    better: "down", note: "cheaper is better, so a fall reads green" },
  { label: "Contribution margin", value: (m) => m.contribution_margin, kind: "money",
    note: "new-customer revenue − ad spend − 18% GST on that spend" },
  { label: "CM %", value: (m) => m.contribution_margin_pct, kind: "pct", strong: true },
  { label: "Incremental ROAS", value: (m) => m.incremental_roas, kind: "ratio", strong: true,
    note: "Δ Shopify sales ÷ Δ ad spend, against the prior period" },
];

/** Change between two periods, in the unit that reads clearest for the
 *  kind of figure. Null where it cannot be stated: a percent change
 *  needs a non-zero base, and 0 → 40 is not "+∞%", it is new. */
function change(now: Num, before: Num, kind: Kind) {
  // `== null` for the same reason as the formatters above: a field a
  // cached payload has never heard of is undefined, and comparing two
  // periods where one side is missing is not a change of zero.
  if (now == null || before == null) return null;
  const d = now - before;
  if (kind === "pct") return { text: `${d >= 0 ? "+" : ""}${d.toFixed(2)}pp`, up: d };
  if (kind === "ratio") return { text: `${d >= 0 ? "+" : ""}${d.toFixed(2)}×`, up: d };
  if (before === 0) return now === 0 ? null : { text: "new", up: 1 };
  const p = (d / before) * 100;
  return { text: `${p >= 0 ? "+" : ""}${p.toFixed(1)}%`, up: p };
}

function ChangeCell({ now, before, kind, better = "up" }: {
  now: Num; before: Num; kind: Kind; better?: Better;
}) {
  const c = change(now, before, kind);
  if (c === null) return <span className="text-text-tertiary">—</span>;
  // Exact zero is neither good nor bad; green would read as a rise
  // that did not happen. Neutral rows never take a colour at all.
  const good = better === "down" ? -c.up : c.up;
  const tone = better === "neutral" || good === 0
    ? "text-text-secondary"
    : good > 0 ? "text-success-text" : "text-error-text";
  return <span className={tone}>{c.text}</span>;
}

export function MerMonthly({ months, grain, onGrain }: {
  months: MerMonth[];
  grain: MerGrain;
  onGrain: (g: MerGrain) => void;
}) {
  // Which period is "now", held by index. Reset on a grain change so
  // the selection lands on the latest of the NEW grain rather than
  // carrying a stale month position into a list of quarters.
  const [picked, setPicked] = useState<number | null>(null);
  // The run is the default view. A comparison is a question asked OF
  // it, about one period in particular, so it waits to be asked.
  const [comparing, setComparing] = useState(false);

  if (months.length === 0) {
    return <p className="py-6 text-sm text-text-secondary">Nothing to show for this grain yet.</p>;
  }
  const idx = Math.min(picked ?? months.length - 1, months.length - 1);
  const now = months[idx];
  const before = idx > 0 ? months[idx - 1] : null;

  return (
    <section aria-labelledby="dashboard-mer-monthly" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2 border-b border-border-primary pb-1.5">
        <h3 id="dashboard-mer-monthly" className="text-sm font-medium text-text-primary">
          {comparing
            ? `Blended MER · ${periodLabel(now.month, grain)} vs previous ${WORD[grain]}`
            : `Blended MER · by ${WORD[grain]}`}
        </h3>
        <div className="flex flex-wrap items-center gap-3">
          {/* The picker belongs to the comparison and appears with it:
              in the run every period is already on screen, so there is
              nothing to select. */}
          {comparing && (
            <select
              aria-label="Period to compare"
              value={idx}
              onChange={(e) => setPicked(Number(e.target.value))}
              className={`${filterControlClass} rounded-md border border-border-primary px-2 py-1`}
            >
              {months.map((m, i) => (
                <option key={m.month} value={i}>
                  {periodLabel(m.month, grain)}{m.partial ? " (part)" : ""}
                </option>
              ))}
            </select>
          )}
          {/* Opt in. The run is what a reader wants first -- the whole
              shape, every period -- and a comparison is a question they
              ask of it afterwards, about one period in particular. */}
          <button
            type="button"
            aria-pressed={comparing}
            onClick={() => setComparing((v) => !v)}
            disabled={months.length < 2}
            title={months.length < 2
              ? `Only one ${WORD[grain]} of data — nothing to compare against`
              : `Compare one ${WORD[grain]} with the one before it`}
            className={`rounded-md border px-3 py-1.5 text-[12.5px] transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
              comparing
                ? "border-text-primary bg-text-primary font-medium text-bg-white"
                : "border-border-primary bg-bg-white text-text-secondary hover:text-text-primary"
            }`}
          >
            Compare
          </button>
          <Segmented
            options={GRAINS.map((g) => ({ value: g.value, label: g.label, title: g.title }))}
            value={grain}
            onChange={(v) => { setPicked(null); onGrain(v as MerGrain); }}
          />
        </div>
      </div>

      {comparing && before === null ? (
        /* Said once, plainly, rather than a dash on every row. */
        <p className="border-l-2 border-warning-text pl-2 text-[12px] text-warning-text">
          No data available for the previous {WORD[grain]} — there is nothing before{" "}
          {periodLabel(now.month, grain)} to compare against, because the warehouse starts on
          1 January 2026.{" "}
          {grain === "year"
            ? "A year-on-year comparison will not be possible until 2027."
            : `Pick a later ${WORD[grain]}, or compare by month.`}
        </p>
      ) : comparing && before !== null ? (
        <TableFrame>
          <table className="w-full min-w-[460px] border-collapse text-[12.5px]">
            <thead>
              <tr className="border-b border-border-primary text-[11px] uppercase tracking-wide text-text-tertiary">
                <th scope="col" className="w-full py-1.5 pr-3 text-left font-medium">Metric</th>
                <th scope="col" className="whitespace-nowrap border-l border-border-primary px-3 py-1.5 text-right font-medium">
                  {periodLabel(now.month, grain)}
                  {now.partial && <span className="ml-1 font-normal normal-case text-warning-text">part</span>}
                </th>
                <th scope="col" className="whitespace-nowrap px-3 py-1.5 text-right font-medium">
                  {periodLabel(before.month, grain)}
                </th>
                <th scope="col" className="whitespace-nowrap px-3 py-1.5 text-right font-medium">Change</th>
              </tr>
            </thead>
            <tbody>
              {ROWS.map((r) =>
                r.head ? (
                  <tr key={r.label}>
                    <th scope="colgroup" colSpan={4}
                      className="pb-1 pt-3 text-left text-[10.5px] uppercase tracking-wide text-text-tertiary">
                      {r.label}
                    </th>
                  </tr>
                ) : (
                  <tr key={r.label} className="border-b border-border-soft last:border-0 hover:bg-bg-surface/60">
                    <td className="py-1.5 pr-3 text-text-primary" title={r.note}>
                      {r.label}
                      {r.note && <span className="ml-1 text-text-tertiary" aria-hidden="true">·</span>}
                    </td>
                    <td className={`whitespace-nowrap border-l border-border-primary px-3 py-1.5 text-right font-mono tabular-nums ${
                      r.strong ? "text-text-primary" : "text-text-secondary"}`}>
                      {FORMAT[r.kind!](r.value!(now))}
                      {r.star?.(now) && <span className="text-warning-text"> *</span>}
                    </td>
                    <td className="whitespace-nowrap px-3 py-1.5 text-right font-mono tabular-nums text-text-tertiary">
                      {FORMAT[r.kind!](r.value!(before))}
                      {r.star?.(before) && <span className="text-warning-text"> *</span>}
                    </td>
                    <td className="whitespace-nowrap px-3 py-1.5 text-right font-mono tabular-nums">
                      <ChangeCell now={r.value!(now)} before={r.value!(before)}
                        kind={r.kind!} better={r.better} />
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </TableFrame>
      ) : (
        /* The default: the whole run, every period on screen. */
        <TableFrame
          footer={
            <span className="text-[11.5px] text-text-tertiary">
              Spend is Meta + Google + Kwikchat, the plan&apos;s three D2C channels. Kwikchat is a
              flat placeholder (marked *) until real figures land. Each {WORD[grain]} is recomputed
              from the daily rows, never averaged from the one beside it.
            </span>
          }
        >
          <table className="w-full min-w-[720px] border-collapse text-[12px]">
            <thead>
              <tr className="border-b border-border-primary text-[11px] uppercase tracking-wide text-text-tertiary">
                <th scope="col" className="w-full py-1.5 pr-3 text-left font-medium">Metric</th>
                {months.map((m) => (
                  <th key={m.month} scope="col"
                    className="whitespace-nowrap border-l border-border-soft px-2 py-1.5 text-right font-medium">
                    {periodLabel(m.month, grain)}
                    {m.partial && <span className="ml-1 font-normal normal-case text-warning-text">part</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ROWS.map((r) =>
                r.head ? (
                  <tr key={r.label}>
                    <th scope="colgroup" colSpan={months.length + 1}
                      className="pb-1 pt-3 text-left text-[10.5px] uppercase tracking-wide text-text-tertiary">
                      {r.label}
                    </th>
                  </tr>
                ) : (
                  <tr key={r.label} className="border-b border-border-soft last:border-0 hover:bg-bg-surface/60">
                    <td className="py-1.5 pr-3 text-text-primary" title={r.note}>
                      {r.label}
                      {r.note && <span className="ml-1 text-text-tertiary" aria-hidden="true">·</span>}
                    </td>
                    {months.map((m) => (
                      <td key={m.month}
                        className={`whitespace-nowrap border-l border-border-soft px-2 py-1.5 text-right font-mono tabular-nums ${
                          r.strong ? "text-text-primary" : "text-text-secondary"}`}>
                        {FORMAT[r.kind!](r.value!(m))}
                        {r.star?.(m) && <span className="text-warning-text"> *</span>}
                      </td>
                    ))}
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </TableFrame>
      )}
    </section>
  );
}
