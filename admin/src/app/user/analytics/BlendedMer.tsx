"use client";

import type { BlendedMerResponse } from "@/lib/api";
import { FieldLabel } from "./SectionChrome";

/**
 * Revenue over paid spend, with no attribution in it anywhere.
 *
 * Every other efficiency figure on this dashboard divides an ATTRIBUTED
 * numerator by spend, and attribution here is partial by construction:
 * GA4 sees 76% of orders, Shopify's own journey data is empty for 96%
 * because GoKwik owns the checkout, and about half of ad ids never
 * resolve to a named ad. This needs none of it -- two totals, both
 * measured directly.
 *
 * It names Meta + Google on its face on purpose. The media plan tracks
 * a D2C MER that also carries Kwikchat spend and reads about 11% lower
 * (3.22 against 3.58 for Sep 2026), and a TOTAL MER over every channel.
 * Someone holding this card next to that deck has to be able to see why
 * the two differ without being told.
 */

const money = (n: number) =>
  n.toLocaleString("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });

/** Rupees at dashboard scale: crore and lakh, the units the figures are
 *  actually discussed in. A nine-digit number in full is read digit by
 *  digit; "4.70 Cr" is read at a glance. */
function compact(n: number): string {
  if (Math.abs(n) >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (Math.abs(n) >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
  return money(n);
}

const DAY = (iso: string) =>
  new Date(`${iso}T12:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short" });

export function BlendedMer({ data, rangeLabel }: {
  data: BlendedMerResponse;
  rangeLabel: string;
}) {
  const { mer, revenue, meta_spend, google_spend, total_spend } = data;
  const share = (n: number) => (total_spend > 0 ? (100 * n) / total_spend : 0);
  const metaShare = share(meta_spend);
  const googleShare = share(google_spend);
  const kwikShare = share(data.kwikchat_spend);
  // Days carrying revenue but no spend inflate the ratio, so they are
  // counted and stated rather than quietly averaged in.
  const gaps = Math.max(data.days_missing_meta, data.days_missing_google);

  return (
    <section aria-labelledby="dashboard-blended-mer" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-border-primary pb-1.5">
        <h3 id="dashboard-blended-mer" className="text-sm font-medium text-text-primary">
          MER &amp; customer mix
        </h3>
        {/* The window MEASURED, not the one on the picker. Meta reports
            a day behind Google, so "to today" almost always means "to
            yesterday", and both sides of the ratio are cut to the days
            the two platforms share. */}
        <span className="text-[11.5px] text-text-tertiary">
          {data.window_from && data.window_to
            ? `${DAY(data.window_from)} – ${DAY(data.window_to)}`
            : rangeLabel}
        </span>
      </div>

      <div className="flex flex-wrap items-end gap-x-10 gap-y-4">
        <div className="min-w-0">
          <FieldLabel>MER</FieldLabel>
          <p className="mt-0.5 font-mono text-[34px] font-semibold leading-none tabular-nums text-text-primary">
            {mer === null ? "—" : `${mer.toFixed(2)}×`}
          </p>
          <p className="mt-1.5 text-[11.5px] text-text-tertiary">
            Shopify sales ÷ Meta + Google + Kwikchat spend
          </p>
        </div>

        {/* The two sides of the ratio, so the number can be checked
            rather than taken on trust. */}
        <div className="min-w-0">
          <FieldLabel>Shopify sales</FieldLabel>
          <p className="mt-0.5 font-mono text-[19px] tabular-nums text-text-primary">{compact(revenue)}</p>
          <p className="mt-1 text-[11.5px] text-text-tertiary">all orders, not attributed</p>
        </div>

        <div className="min-w-0">
          <FieldLabel>Ad spend</FieldLabel>
          <p className="mt-0.5 font-mono text-[19px] tabular-nums text-text-primary">{compact(total_spend)}</p>
          <p className="mt-1 flex flex-wrap gap-x-2 text-[11.5px] tabular-nums text-text-tertiary">
            <span>Meta {compact(meta_spend)}</span>
            <span>·</span>
            <span>Google {compact(google_spend)}</span>
            <span>·</span>
            <span>Kwikchat {compact(data.kwikchat_spend)}
              {data.kwikchat_estimated_days > 0 && <span className="text-warning-text"> *</span>}
            </span>
          </p>
        </div>
      </div>

      {/* How much of the denominator each platform carries. Google was
          9.3% of September's spend, and that share is the whole reason
          the figure moved when Google was first ingested -- revenue over
          Meta alone read 3.97x where the two together give 3.61x. */}
      {total_spend > 0 && (
        <div className="flex flex-col gap-1">
          <div className="flex h-2 w-full overflow-hidden rounded-sm bg-bg-surface" role="img"
            aria-label={`Meta ${metaShare.toFixed(1)}%, Google ${googleShare.toFixed(1)}% and Kwikchat ${kwikShare.toFixed(1)}% of ad spend`}>
            <div className="bg-accent-yellow" style={{ width: `${metaShare}%` }} />
            <div className="bg-success-mid" style={{ width: `${googleShare}%` }} />
            {/* Hatched rather than solid: this slice is an estimate and
                should not sit on the bar looking like the other two. */}
            <div className="bg-warning-text opacity-60" style={{ width: `${kwikShare}%` }} />
          </div>
          <div className="flex flex-wrap gap-x-4 text-[11px] tabular-nums text-text-tertiary">
            <span>Meta {metaShare.toFixed(1)}% of spend</span>
            <span>Google {googleShare.toFixed(1)}%</span>
            <span>Kwikchat {kwikShare.toFixed(1)}%</span>
          </div>
        </div>
      )}

      {data.window_clamped && (
        <p className="text-[11.5px] text-text-tertiary">
          Measured {DAY(data.window_from!)} – {DAY(data.window_to!)}, the days both platforms
          report. Meta&apos;s spend lands a day behind Google&apos;s, and counting revenue
          against a denominator missing one of its two halves would read high.
        </p>
      )}

      {/* The media plan's D2C block, same window as the ratio above.
          Every figure here is Shopify's own column, so it reconciles
          with the plan to the rupee -- which is why the two that do
          NOT are called out rather than quietly shown. */}
      <div className="grid grid-cols-2 gap-x-6 gap-y-4 border-t border-border-soft pt-3 sm:grid-cols-3 lg:grid-cols-5">
        <div className="min-w-0">
          <FieldLabel>New customers</FieldLabel>
          <p className="mt-0.5 font-mono text-[19px] tabular-nums text-text-primary">
            {data.new_customers.toLocaleString("en-IN")}
          </p>
          <p className="mt-1 text-[11.5px] text-text-tertiary">
            {data.blended_cac === null ? "—" : `${money(data.blended_cac)} each`}
          </p>
        </div>

        <div className="min-w-0">
          <FieldLabel>Returning customers</FieldLabel>
          <p className="mt-0.5 font-mono text-[19px] tabular-nums text-text-primary">
            {data.returning_customers.toLocaleString("en-IN")}
          </p>
          <p className="mt-1 text-[11.5px] text-text-tertiary">
            {data.returning_customer_pct === null ? "—" : `${data.returning_customer_pct}% of buyers`}
          </p>
        </div>

        <div className="min-w-0">
          <FieldLabel>Sales · first-time</FieldLabel>
          <p className="mt-0.5 font-mono text-[19px] tabular-nums text-text-primary">
            {compact(data.sales_first_time)}
          </p>
          <p className="mt-1 text-[11.5px] text-text-tertiary">
            {data.returning_revenue_pct === null ? "—" : `${(100 - data.returning_revenue_pct).toFixed(2)}% of revenue`}
          </p>
        </div>

        <div className="min-w-0">
          <FieldLabel>Sales · returning</FieldLabel>
          <p className="mt-0.5 font-mono text-[19px] tabular-nums text-text-primary">
            {compact(data.sales_returning)}
          </p>
          <p className="mt-1 text-[11.5px] text-text-tertiary">
            {data.returning_revenue_pct === null ? "—" : `${data.returning_revenue_pct}% of revenue`}
          </p>
        </div>

        <div className="min-w-0">
          <FieldLabel>Blended CAC</FieldLabel>
          <p className="mt-0.5 font-mono text-[19px] tabular-nums text-text-primary">
            {data.blended_cac === null ? "—" : money(data.blended_cac)}
          </p>
          <p className="mt-1 text-[11.5px] text-text-tertiary">ad spend ÷ new customers</p>
        </div>
      </div>

      {data.kwikchat_estimated_days > 0 && (
        <p className="border-l-2 border-warning-text pl-2 text-[11.5px] text-warning-text">
          Kwikchat spend is a flat placeholder on {data.kwikchat_estimated_days} of these days, not
          a measured figure. It is in the denominator because leaving it out made every ratio read
          high — but MER, CAC, A-MER and contribution margin all move when the real numbers land.
        </p>
      )}

      {gaps > 0 && (
        <p className="border-l-2 border-warning-text pl-2 text-[11.5px] text-warning-text">
          {gaps === 1
            ? "1 day inside this window carries revenue with no spend recorded"
            : `${gaps} days inside this window carry revenue with no spend recorded`}
          {" — those days push the ratio up."}
        </p>
      )}

      {/* Three figures in the plan's D2C block are NOT here, and
          saying which is cheaper than someone finding out by
          disagreeing with the deck in a meeting. */}
      <p className="text-[11.5px] text-text-tertiary">
        Returning customers reads Shopify&apos;s own count, which runs above the plan&apos;s manually
        entered figure ({data.returning_customers.toLocaleString("en-IN")} against 12,107 for Sep).
        Returning-customer % is <b className="font-medium">not</b> the plan&apos;s: its cell divides by
        new + RTO-adjusted-new + returning, counting the new cohort twice and roughly halving the
        result. Over-revenue reporting and attribution overlap are absent entirely — both need
        Kwikchat&apos;s claimed purchase value, which the warehouse does not hold.
      </p>

      <p className="text-[11.5px] text-text-tertiary">
        No attribution in the ratio: it divides every Shopify order by every rupee of Meta,
        Google and Kwikchat spend, so it does not depend on GA4 coverage or on an ad id resolving.
        It covers the plan&apos;s three D2C channels, but not its Total MER across every channel — the
        warehouse holds no marketplace revenue, content, influencer or tech cost.
      </p>
    </section>
  );
}
