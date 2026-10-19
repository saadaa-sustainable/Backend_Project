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
  const googleShare = data.google_share_of_spend ?? 0;
  const metaShare = 100 - googleShare;
  // Days carrying revenue but no spend inflate the ratio, so they are
  // counted and stated rather than quietly averaged in.
  const gaps = Math.max(data.days_missing_meta, data.days_missing_google);

  return (
    <section aria-labelledby="dashboard-blended-mer" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-border-primary pb-1.5">
        <h3 id="dashboard-blended-mer" className="text-sm font-medium text-text-primary">
          MER · Meta + Google
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
            Shopify sales ÷ Meta + Google spend
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
            aria-label={`Meta ${metaShare.toFixed(1)}% and Google ${googleShare.toFixed(1)}% of ad spend`}>
            <div className="bg-accent-yellow" style={{ width: `${metaShare}%` }} />
            <div className="bg-success-mid" style={{ width: `${googleShare}%` }} />
          </div>
          <div className="flex flex-wrap gap-x-4 text-[11px] tabular-nums text-text-tertiary">
            <span>Meta {metaShare.toFixed(1)}% of spend</span>
            <span>Google {googleShare.toFixed(1)}%</span>
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

      {gaps > 0 && (
        <p className="border-l-2 border-warning-text pl-2 text-[11.5px] text-warning-text">
          {gaps === 1
            ? "1 day inside this window carries revenue with no spend recorded"
            : `${gaps} days inside this window carry revenue with no spend recorded`}
          {" — those days push the ratio up."}
        </p>
      )}

      <p className="text-[11.5px] text-text-tertiary">
        No attribution in this figure: it divides every Shopify order by every rupee of Meta and
        Google spend, so it does not depend on GA4 coverage or on an ad id resolving.
        It is <b className="font-medium">not</b> the media plan&apos;s D2C MER, which also carries
        Kwikchat spend and so reads lower, nor its Total MER across every channel — the warehouse
        holds no Kwikchat, marketplace, content, influencer or tech cost.
      </p>
    </section>
  );
}
