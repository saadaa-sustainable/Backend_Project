"use client";

import { Fragment, useState } from "react";
import {
  fetchDashboardComparative,
  type ComparativeBasis,
  type ComparativeMetrics,
  type ComparativeRow,
} from "@/lib/api";
import { useCachedFetch } from "@/lib/useCachedFetch";
import { ContributionChart } from "./charts/ContributionChart";
import {
  FieldLabel, FilterCell, FilterRule, Segmented, SectionHeader, TableFrame,
  filterControlClass,
} from "./SectionChrome";

/**
 * One day read three ways.
 *
 * The section answers "is today normal?", and that question has no
 * single baseline. Yesterday catches a sudden break but is itself a
 * single noisy day. Seven days back puts a Friday against a Friday,
 * which matters because this catalogue's traffic is strongly
 * weekday-shaped -- comparing Friday with Thursday mostly measures the
 * day of the week. A calendar month back puts the 16th against the
 * 16th, whatever weekday that lands on, which is what a month-on-month
 * read of a DATE is asking for.
 *
 * So the basis is a toggle, not a choice made for the reader. All three
 * arrive in one response, so flipping between them costs nothing.
 */

type Dimension = "products" | "landing-pages";
type Source = "ga4" | "shopify";

const DIMENSIONS: { value: Dimension; label: string; title: string }[] = [
  { value: "products", label: "Products", title: "Sales and units sold per master SKU" },
  { value: "landing-pages", label: "Landing pages", title: "Sessions, add-to-carts and conversion rate per landing page" },
];

const SOURCES: { value: Source; label: string; title: string }[] = [
  { value: "ga4", label: "GA4", title: "Sessions, add-to-carts and purchases from Google Analytics" },
  { value: "shopify", label: "Shopify", title: "Sessions and cart additions from Shopify. No purchase event at this grain, so the rate is reached-checkout instead." },
];

const BASES: { value: ComparativeBasis; label: string; title: string }[] = [
  { value: "yesterday", label: "vs yesterday", title: "The day before the anchor" },
  { value: "last_week", label: "vs last week", title: "Seven days back, so the same weekday" },
  { value: "last_month", label: "vs last month", title: "One calendar month back, so the same date" },
];

/** What each dimension puts in the table, in column order. */
interface MetricSpec {
  key: keyof ComparativeMetrics;
  label: string;
  format: (n: number) => string;
  /** A rate compares as a difference in percentage points, not as a
   *  percent change of a percent -- "conversion went from 2% to 3%" is
   *  +1pp, and calling it +50% is true but unreadable. */
  pointsNotPercent?: boolean;
}

const money = (n: number) =>
  n.toLocaleString("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
const count = (n: number) => n.toLocaleString("en-IN");
const rate = (n: number) => `${n.toFixed(2)}%`;

const METRICS: Record<Dimension, MetricSpec[]> = {
  products: [
    { key: "sales", label: "Sales", format: money },
    { key: "units", label: "Units", format: count },
  ],
  "landing-pages": [
    { key: "sessions", label: "Sessions", format: count },
    { key: "atc", label: "ATC", format: count },
    { key: "conversion_rate", label: "Conv. rate", format: rate, pointsNotPercent: true },
  ],
};

const DAY_LABEL = (iso: string) =>
  new Date(`${iso}T12:00:00`).toLocaleDateString("en-IN", {
    weekday: "short", day: "numeric", month: "short",
  });

/** Column headings carry the date without the weekday -- the weekday is
 *  already stated once above the table and repeating it in every column
 *  pair crowds out the figures. */
const SHORT_DAY = (iso: string) =>
  new Date(`${iso}T12:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short" });

/** Movement from baseline to current, or null when it cannot be stated.
 *  A baseline of zero has no percent change -- going 0 -> 40 is not
 *  "+infinity%", it is new. */
function delta(current: number | null, baseline: number | null, points: boolean) {
  if (current === null || baseline === null) return null;
  if (points) return { value: current - baseline, suffix: "pp", isNew: false };
  if (baseline === 0) return current === 0 ? null : { value: null, suffix: "", isNew: true };
  return { value: ((current - baseline) / baseline) * 100, suffix: "%", isNew: false };
}

function DeltaCell({ current, baseline, points }: {
  current: number | null; baseline: number | null; points: boolean;
}) {
  const d = delta(current, baseline, points);
  if (d === null) {
    return <span className="text-text-tertiary">—</span>;
  }
  if (d.isNew) {
    return <span className="text-success-text" title="No figure on the comparison day">new</span>;
  }
  const v = d.value as number;
  // Exact zero is neither good nor bad; colouring it green reads as a
  // rise that did not happen.
  const tone = v > 0 ? "text-success-text" : v < 0 ? "text-error-text" : "text-text-tertiary";
  const sign = v > 0 ? "+" : "";
  return (
    <span className={tone}>
      {sign}{d.suffix === "pp" ? v.toFixed(2) : v.toFixed(1)}{d.suffix}
    </span>
  );
}

const TODAY_ISO = () => new Date().toLocaleDateString("en-CA");

/** Short heads for the three bases. The full wording is stated once
 *  above the table; repeating "vs last month" in nine column headings
 *  spends the width on grammar instead of on figures. */
const BASIS_SHORT: Record<ComparativeBasis, string> = {
  yesterday: "yest", last_week: "wk", last_month: "mo",
};

/**
 * One metric, with all three comparisons under it.
 *
 * Showing only the selected basis made the reader toggle three times to
 * answer one question, and left the band mostly empty while they did.
 * All three fit on one line, so all three are shown; the selected one
 * is marked rather than being the only one present.
 */
function MetricFigure({ spec, row, basis, days }: {
  spec: MetricSpec; row: ComparativeRow; basis: ComparativeBasis;
  days: Record<ComparativeBasis, string>;
}) {
  const current = row.current[spec.key];
  return (
    <div className="min-w-0">
      <FieldLabel>{spec.label}</FieldLabel>
      <p className="mt-0.5 truncate font-mono text-[22px] font-semibold tabular-nums text-text-primary">
        {current === null ? "—" : spec.format(current)}
      </p>
      {/* The figure being compared against, not just the movement. A
          delta on its own cannot be sized -- "-86.7%" says nothing
          about whether the day lost four thousand rupees or four lakh.
          Three rows of basis / baseline / delta, aligned so the eye
          runs down the column.

          The selected basis is marked by weight rather than by dimming
          the other two: they are figures to be read, not decoration. */}
      <div className="mt-1 grid grid-cols-[auto_1fr_auto] items-baseline gap-x-2 gap-y-0.5 text-[11.5px] tabular-nums">
        {BASES.map((b) => {
          const baseline = row[b.value][spec.key];
          const on = b.value === basis;
          return (
            <Fragment key={b.value}>
              <span className={on ? "font-medium text-text-secondary" : "text-text-tertiary"}
                title={`${b.label.replace(/^vs /, "")} · ${days[b.value] ?? ""}`}>
                {BASIS_SHORT[b.value]}
              </span>
              <span className="text-right font-mono text-text-secondary">
                {baseline === null ? "—" : spec.format(baseline)}
              </span>
              <span className="text-right font-mono">
                <DeltaCell current={current} baseline={baseline}
                  points={!!spec.pointsNotPercent} />
              </span>
            </Fragment>
          );
        })}
      </div>
    </div>
  );
}

export function ComparativeAnalysis() {
  const [dimension, setDimension] = useState<Dimension>("products");
  const [source, setSource] = useState<Source>("ga4");
  const [basis, setBasis] = useState<ComparativeBasis>("yesterday");
  // One DAY, not a range. Every other section picks a window because it
  // sums over one; this section compares single days, and a window has
  // no single day to stand for it. Empty means "the newest day this
  // source holds", which is not the same day for GA4 as for Shopify --
  // so the server resolves it and the figures above the table say which
  // day came back.
  const [day, setDay] = useState<string>("");
  // Which metric the chart plots. The table shows every metric at once;
  // a bar chart can only carry one, so this picks it.
  const [metricKey, setMetricKey] = useState<string>("sales");

  // Source is only part of the key for landing pages; including it for
  // products would split the cache on a parameter the server ignores.
  const scope = dimension === "products" ? "products" : `landing-pages:${source}`;
  const { data, error, loading, refetch } = useCachedFetch(
    `dashboard-comparative:${scope}:${day || "latest"}`,
    () => fetchDashboardComparative(dimension, source, day || null, 50),
  );

  const specs = METRICS[dimension];
  // The metric list changes with the dimension, so a key chosen under
  // Products ("sales") is meaningless under Landing pages. Fall back
  // rather than render an empty chart.
  const chartSpec = specs.find((m) => m.key === metricKey) ?? specs[0];

  return (
    <section className="flex flex-col gap-4">
      {/* Which of the two dimensions, and whose numbers, belong to the
          title -- they reframe the whole section. The basis sits on the
          filter rule beside the day it compares against, because the
          pair is one thought: this day, against that one. */}
      <SectionHeader title="Comparative Analysis">
        <Segmented
          options={DIMENSIONS.map((d) => ({ value: d.value, label: d.label, title: d.title }))}
          value={dimension}
          onChange={(v) => setDimension(v as Dimension)}
        />
        {dimension === "landing-pages" && (
          <Segmented
            options={SOURCES.map((s) => ({ value: s.value, label: s.label, title: s.title }))}
            value={source}
            onChange={(v) => setSource(v as Source)}
          />
        )}
      </SectionHeader>

      <FilterRule
        actions={
          data && (
            <span className="text-[11.5px] text-text-tertiary tabular-nums">
              {data.row_count} {dimension === "products" ? "SKUs" : "pages"}
            </span>
          )
        }
      >
        <FilterCell label="Day" className="w-44" htmlFor="comparative-day">
          <input
            id="comparative-day"
            type="date"
            value={day}
            max={TODAY_ISO()}
            onChange={(e) => setDay(e.target.value)}
            className={filterControlClass}
          />
        </FilterCell>
        <FilterCell label="Highlight" className="w-48" htmlFor="comparative-basis">
          <select
            id="comparative-basis"
            value={basis}
            onChange={(e) => setBasis(e.target.value as ComparativeBasis)}
            className={filterControlClass}
          >
            {BASES.map((b) => (
              <option key={b.value} value={b.value} title={b.title}>
                {b.label.replace(/^vs /, "")}
              </option>
            ))}
          </select>
        </FilterCell>
      </FilterRule>

      {error ? (
        <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-error-text">
          <span>Could not load the comparison.</span>
          <button type="button" className="underline underline-offset-2" onClick={() => refetch()}>
            Retry
          </button>
        </div>
      ) : loading || !data ? (
        <div className="animate-pulse rounded bg-bg-surface" style={{ minHeight: 220 }}
          role="status" aria-label="Loading comparative analysis" />
      ) : data.rows.length === 0 ? (
        <p className="py-6 text-sm text-text-secondary">
          No data on {DAY_LABEL(data.anchor)} for this dimension.
        </p>
      ) : (
        <>
          {/* Anchor is today, so it holds part of a day against whole
              ones. Stated before the figures rather than under them --
              every delta on screen is wrong by the hours not yet run. */}
          {data.anchor_is_partial && (
            <p className="border-l-2 border-warning-text pl-2 text-[12px] text-warning-text">
              {DAY_LABEL(data.anchor)} is still running. Its figures cover only the hours so
              far, so every movement below reads low against the full days beside it.
            </p>
          )}

          {/* Totals first: the section's job is the whole-business read,
              and the table under it says which rows drove it. One cell
              per metric, each carrying all three comparisons. */}
          <div className="grid grid-cols-2 gap-x-6 gap-y-4 border-b border-border-soft pb-3 sm:grid-cols-3 lg:grid-cols-4">
            <div className="min-w-0">
              <FieldLabel>Day</FieldLabel>
              <p className="mt-0.5 truncate text-[22px] font-semibold text-text-primary">
                {DAY_LABEL(data.anchor)}
              </p>
              <p className="mt-1 text-[11.5px] text-text-tertiary">
                {BASES.map((b) => `${BASIS_SHORT[b.value]} ${SHORT_DAY(data.basis_days[b.value])}`).join(" · ")}
              </p>
            </div>
            {specs.map((spec) => (
              <MetricFigure key={spec.key} spec={spec} row={data.totals}
                basis={basis} days={data.basis_days} />
            ))}
          </div>

          {/* Percent change is the table's job. The chart plots the
              CHANGE ITSELF, because percent is unplottable on this
              catalogue -- one page moved 1 -> 1,113 sessions, which is
              +111,200% and would flatten every other bar to nothing. */}
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <FieldLabel>
                What moved · {SHORT_DAY(data.basis_days[basis])} → {SHORT_DAY(data.anchor)}
              </FieldLabel>
              <Segmented
                options={specs.map((m) => ({ value: m.key as string, label: m.label }))}
                value={chartSpec.key as string}
                onChange={setMetricKey}
              />
            </div>
            <ContributionChart
              data={data.rows.map((r) => ({
                key: r.key,
                current: r.current[chartSpec.key],
                baseline: r[basis][chartSpec.key],
              }))}
              // A rate's bars are percentage POINTS, and "+1.53%" beside
              // a header saying "percentage points" reads as a percent
              // change of a percent. Same pp suffix the table column uses.
              format={(n) => chartSpec.pointsNotPercent
                ? `${n.toFixed(2)}pp`
                : chartSpec.format(n)}
              metricLabel={chartSpec.label}
              anchorLabel={DAY_LABEL(data.anchor)}
              baselineLabel={DAY_LABEL(data.basis_days[basis])}
              additive={!chartSpec.pointsNotPercent}
            />
          </div>

          <TableFrame
            footer={
              <span className="text-[11.5px] text-text-tertiary">
                Top {data.row_count} by {dimension === "products" ? "sales" : "sessions"}.
                {dimension === "products"
                  ? " Totals cover the tracked master-SKU catalogue, not every order."
                  : source === "shopify"
                    ? " Shopify has no purchase event at this grain, so the rate is sessions that reached checkout."
                    : " Conversion rate is GA4 purchases over GA4 sessions."}
              </span>
            }
          >
            {/* Every basis on the row, not just the selected one. The
                table was four numeric columns in a 1300px frame, which
                left most of the width blank and made the reader toggle
                three times to see three comparisons they could have
                read at once. The selected basis is tinted rather than
                being the only column present. */}
            <table className="w-full min-w-[760px] border-collapse text-[12px]">
              <thead>
                <tr className="border-b border-border-primary text-[11px] uppercase tracking-wide text-text-tertiary">
                  {/* No w-full here: letting the label column swallow the slack
                      pushed every figure against the right edge and left
                      the middle of the table blank. Auto layout spreads
                      the spare width across the numeric columns instead. */}
                  <th scope="col" rowSpan={2} className="min-w-[130px] py-1.5 pr-2 text-left align-bottom font-medium">
                    {dimension === "products" ? "SKU" : "Landing page"}
                  </th>
                  {specs.map((spec) => (
                    <th key={spec.key} scope="col" colSpan={4}
                      className="border-l border-border-primary px-2 py-1.5 text-center font-medium">
                      {spec.label}
                    </th>
                  ))}
                </tr>
                <tr className="border-b border-border-soft text-[10.5px] text-text-tertiary">
                  {specs.map((spec) => [
                    <th key={`${spec.key}-v`} scope="col"
                      className="whitespace-nowrap border-l border-border-primary px-1.5 py-1 text-right font-normal">
                      {SHORT_DAY(data.anchor)}
                    </th>,
                    ...BASES.map((b) => (
                      <th key={`${spec.key}-${b.value}`} scope="col"
                        title={`${spec.label} on ${SHORT_DAY(data.basis_days[b.value])} (${b.label.replace(/^vs /, "")}), and the move from it`}
                        className={`whitespace-nowrap px-1.5 py-1 text-right font-normal ${
                          b.value === basis ? "bg-bg-surface text-text-secondary" : ""}`}>
                        {BASIS_SHORT[b.value]} {SHORT_DAY(data.basis_days[b.value])}
                      </th>
                    )),
                  ])}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={row.key} className="border-b border-border-soft last:border-0 hover:bg-bg-surface/60">
                    <td className="max-w-[270px] truncate py-1.5 pr-2 font-mono text-[12px] text-text-primary"
                      title={row.key}>
                      {row.key}
                    </td>
                    {specs.map((spec) => {
                      const current = row.current[spec.key];
                      return [
                        <td key={`${spec.key}-v`}
                          className="whitespace-nowrap border-l border-border-primary px-1.5 py-1.5 text-right font-mono tabular-nums text-text-primary">
                          {current === null ? "—" : spec.format(current)}
                        </td>,
                        // Each basis cell carries BOTH numbers: what the
                        // day was, and how far it moved. The percentage
                        // alone was unsizeable -- "-77.9%" reads the same
                        // whether the row lost four hundred rupees or four
                        // lakh, and the baseline was buried in a tooltip.
                        ...BASES.map((b) => {
                          const baseline = row[b.value][spec.key];
                          return (
                            <td key={`${spec.key}-${b.value}`}
                              className={`whitespace-nowrap px-1.5 py-1.5 text-right font-mono text-[11px] tabular-nums ${
                                b.value === basis ? "bg-bg-surface" : ""}`}>
                              <span className="text-[10.5px] text-text-tertiary">
                                {baseline === null ? "—" : spec.format(baseline)}
                              </span>
                              {" "}
                              <DeltaCell current={current} baseline={baseline}
                                points={!!spec.pointsNotPercent} />
                            </td>
                          );
                        }),
                      ];
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </TableFrame>
        </>
      )}
    </section>
  );
}
