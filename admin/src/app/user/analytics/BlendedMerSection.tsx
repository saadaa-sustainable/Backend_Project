"use client";

import { useState } from "react";
import {
  fetchDashboardBlendedMer,
  fetchDashboardMerByPeriod,
  type BlendedMerResponse,
  type MerGrain,
  type MerMonth,
} from "@/lib/api";
import { useCachedFetch } from "@/lib/useCachedFetch";
import { DateRangePicker } from "@/components/DateRangePicker";
import { BlendedMer } from "./BlendedMer";
import { MerMonthly } from "./MerMonthly";
import { FilterCell, FilterRule, SectionHeader } from "./SectionChrome";

/**
 * Blended MER, as its own section rather than two widgets in the
 * dashboard grid.
 *
 * The two views answer different questions and belong together: the
 * band on top is "how are we doing right now", over whatever window is
 * picked; the table under it is "how has that moved month over month",
 * in the media plan's own orientation. Splitting them across the
 * dashboard's draggable grid buried both -- a reader who had ever
 * rearranged their widgets found them at the bottom, under the SKU
 * table.
 *
 * The period table deliberately does NOT follow the picker. It runs on
 * whole calendar periods -- month, quarter or year -- because the
 * comparison with the plan only works if the columns line up with it,
 * and a quarter cut to an arbitrary range is not a quarter.
 */

/** How much history each grain is worth showing. A year of months, two
 *  years of quarters, five years of years -- enough to see a trend
 *  without a column per week of the company's life. */
const PERIODS: Record<MerGrain, number> = { month: 12, quarter: 8, year: 5 };

export function BlendedMerSection() {
  const [datePreset, setDatePreset] = useState<string>("last30");
  const [fromDate, setFromDate] = useState<string>(() => {
    const d = new Date();
    d.setDate(d.getDate() - 29);
    return d.toISOString().slice(0, 10);
  });
  const [toDate, setToDate] = useState<string>(() => new Date().toISOString().slice(0, 10));
  const [grain, setGrain] = useState<MerGrain>("month");

  const current = useCachedFetch<BlendedMerResponse>(
    `blended-mer|${fromDate}|${toDate}`,
    () => fetchDashboardBlendedMer(fromDate, toDate),
  );
  const monthly = useCachedFetch<MerMonth[]>(
    `mer-by-period|v1|${grain}`,
    () => fetchDashboardMerByPeriod(grain, PERIODS[grain]),
  );

  const rangeLabel = `${fromDate} – ${toDate}`;

  return (
    <div className="flex flex-col gap-5">
      <SectionHeader title="Blended MER" />

      {/* The picker drives the band only; the table below is fixed to
          calendar months, and the footer under it says so. */}
      <FilterRule>
        <FilterCell label="Date range">
          <DateRangePicker
            value={{ from: fromDate, to: toDate }}
            preset={datePreset}
            bare
            align="left"
            onApply={(r, pk) => {
              setDatePreset(pk);
              setFromDate(r.from);
              setToDate(r.to);
            }}
          />
        </FilterCell>
      </FilterRule>

      {current.error ? (
        <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-error-text">
          <span>Could not load MER.</span>
          <button type="button" className="underline underline-offset-2"
            onClick={() => current.refetch()}>Retry</button>
        </div>
      ) : current.data ? (
        <BlendedMer data={current.data} rangeLabel={rangeLabel} />
      ) : (
        <div className="animate-pulse rounded bg-bg-surface" style={{ minHeight: 170 }}
          role="status" aria-label="Loading MER" />
      )}

      {monthly.error ? (
        <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-error-text">
          <span>Could not load the monthly table.</span>
          <button type="button" className="underline underline-offset-2"
            onClick={() => monthly.refetch()}>Retry</button>
        </div>
      ) : monthly.data ? (
        <MerMonthly months={monthly.data} grain={grain} onGrain={setGrain} />
      ) : (
        <div className="animate-pulse rounded bg-bg-surface" style={{ minHeight: 260 }}
          role="status" aria-label="Loading the monthly table" />
      )}
    </div>
  );
}
