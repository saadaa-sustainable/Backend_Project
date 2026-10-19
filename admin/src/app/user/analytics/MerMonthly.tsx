"use client";

import type { MerGrain, MerMonth } from "@/lib/api";
import { Segmented, TableFrame } from "./SectionChrome";

/**
 * The media plan's Blended MER tab, in its own orientation.
 *
 * Metrics down the rows, months across the columns -- deliberately not
 * transposed. This exists to be read beside that tab, and a reader
 * comparing two layouts of the same numbers checks the layout before
 * they trust the numbers.
 *
 * Formulas track the tab as it stood on 2026-10-19, the morning it
 * changed: returning-customer % stopped double-counting the new cohort,
 * GST left the A-MER denominator for the contribution-margin line, and
 * CM % arrived. The tab's "Ad spend + GST@18%" label is now stale -- it
 * no longer adds GST -- so this says "ad spend" and applies the 18%
 * only inside CM, which is where the tab now applies it too.
 */

/** A period's name, in the shortest form that stays unambiguous at
 *  that grain. "Q3 26" reads faster than "Jul–Sep 26" and a year needs
 *  no month at all. */
function periodLabel(iso: string, grain: MerGrain): string {
  const d = new Date(`${iso}T12:00:00`);
  if (grain === "year") return String(d.getFullYear());
  if (grain === "quarter") {
    return `Q${Math.floor(d.getMonth() / 3) + 1} ${String(d.getFullYear()).slice(2)}`;
  }
  return d.toLocaleDateString("en-IN", { month: "short", year: "2-digit" });
}

const GRAINS: { value: MerGrain; label: string; title: string }[] = [
  { value: "month", label: "Month", title: "Calendar months, the grain the media plan reports in" },
  { value: "quarter", label: "Quarter", title: "Calendar quarters" },
  { value: "year", label: "Year", title: "Calendar years" },
];

/** Crore and lakh: the units these figures are discussed in. A
 *  nine-digit number in a table cell is read digit by digit. */
function compact(n: number | null): string {
  if (n === null) return "—";
  const a = Math.abs(n);
  if (a >= 1e7) return `${(n / 1e7).toFixed(2)} Cr`;
  if (a >= 1e5) return `${(n / 1e5).toFixed(2)} L`;
  return n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}
const num = (n: number | null) => (n === null ? "—" : n.toLocaleString("en-IN"));
const x2 = (n: number | null) => (n === null ? "—" : `${n.toFixed(2)}×`);
const pct = (n: number | null) => (n === null ? "—" : `${n.toFixed(2)}%`);
const rupees = (n: number | null) =>
  n === null ? "—" : n.toLocaleString("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });

interface Row {
  label: string;
  /** Absent on a heading row, which groups what follows rather than
   *  carrying a figure of its own. */
  get?: (m: MerMonth) => string;
  /** A heading row that groups what follows, not a figure itself. */
  head?: boolean;
  /** Ratios and margins, set apart from the money they come from. */
  strong?: boolean;
  note?: string;
}

const ROWS: Row[] = [
  { label: "Ad spend", head: true },
  { label: "Meta", get: (m) => compact(m.meta_spend) },
  { label: "Google", get: (m) => compact(m.google_spend) },
  { label: "Kwikchat", get: (m) => `${compact(m.kwikchat_spend)}${m.kwikchat_estimated ? " *" : ""}`,
    note: "* a flat placeholder until the real figures arrive" },
  { label: "Total ad spend", get: (m) => compact(m.ad_spend), strong: true,
    note: "Meta + Google + Kwikchat — the plan adds six further cost lines" },

  { label: "Platform claimed", head: true },
  { label: "Meta purchase value", get: (m) => compact(m.meta_claimed),
    note: "Meta's own attributed revenue. Matches the plan to the rupee." },
  { label: "Meta MER", get: (m) => x2(m.meta_mer), strong: true },

  { label: "D2C", head: true },
  { label: "Shopify sales", get: (m) => compact(m.revenue) },
  { label: "New customers", get: (m) => num(m.new_customers) },
  { label: "Returning customers", get: (m) => num(m.returning_customers),
    note: "Shopify's own count; runs 8–10% above the plan's manual figure" },
  { label: "Sales · first-time", get: (m) => compact(m.sales_first_time) },
  { label: "Sales · returning", get: (m) => compact(m.sales_returning) },
  { label: "Returning customer %", get: (m) => pct(m.returning_customer_pct), strong: true,
    note: "returning ÷ (new + returning) — the plan's corrected formula" },
  { label: "Returning revenue %", get: (m) => pct(m.returning_revenue_pct), strong: true },

  { label: "Efficiency", head: true },
  { label: "MER", get: (m) => x2(m.mer), strong: true,
    note: "Shopify sales ÷ Meta + Google spend" },
  { label: "A-MER", get: (m) => x2(m.a_mer), strong: true,
    note: "new-customer revenue ÷ ad spend, no GST — the plan's current shape" },
  { label: "Blended CAC", get: (m) => rupees(m.blended_cac), strong: true },
  { label: "Contribution margin", get: (m) => compact(m.contribution_margin),
    note: "new-customer revenue − ad spend − 18% GST on that spend" },
  { label: "CM %", get: (m) => pct(m.contribution_margin_pct), strong: true },
  { label: "Incremental ROAS", get: (m) => x2(m.incremental_roas), strong: true,
    note: "Δ Shopify sales ÷ Δ ad spend, against the prior period" },
];

export function MerMonthly({ months, grain, onGrain }: {
  months: MerMonth[];
  grain: MerGrain;
  onGrain: (g: MerGrain) => void;
}) {
  if (months.length === 0) {
    return <p className="py-6 text-sm text-text-secondary">Nothing to show for this grain yet.</p>;
  }
  return (
    <section aria-labelledby="dashboard-mer-monthly" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-border-primary pb-1.5">
        <h3 id="dashboard-mer-monthly" className="text-sm font-medium text-text-primary">
          Blended MER · by {grain}
        </h3>
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-[11.5px] text-text-tertiary">
            {periodLabel(months[0].month, grain)} – {periodLabel(months[months.length - 1].month, grain)}
          </span>
          {/* Each grain is recomputed from the daily rows, not rolled up
              from the one beside it: a quarter's MER is its revenue over
              its spend, which is not the mean of three monthly MERs. */}
          <Segmented
            options={GRAINS.map((g) => ({ value: g.value, label: g.label, title: g.title }))}
            value={grain}
            onChange={(v) => onGrain(v as MerGrain)}
          />
        </div>
      </div>

      <TableFrame
        footer={
          <span className="text-[11.5px] text-text-tertiary">
            Spend is Meta + Google + Kwikchat, the plan&apos;s three D2C channels. Kwikchat is a
            flat placeholder (marked *) until real figures land. The plan&apos;s Total Ad spend
            adds Amazon, Myntra, Zepto, RobyLon, content, influencer and tech cost on top, so its
            Total MER differs again. Over-revenue reporting and attribution overlap are absent:
            both need Kwikchat&apos;s claimed purchase value, and our Google claimed value runs
            12–44% above the plan&apos;s, so neither can be stated honestly yet.
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
                  {/* A running month is informative as long as nobody
                      reads it as a finished one. */}
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
                      {r.get!(m)}
                    </td>
                  ))}
                </tr>
              ),
            )}
          </tbody>
        </table>
      </TableFrame>
    </section>
  );
}
