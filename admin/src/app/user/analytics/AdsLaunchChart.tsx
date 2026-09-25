"use client";

/**
 * Ads launched per day, over the selected window.
 *
 * Replaces the three client-side charts that used to sit here (spend by
 * category, top-10 by spend, category donut). Those were computed from
 * `derived.filtered` — the rows already paged in, 50–100 of them — while
 * presenting themselves as a view of the whole filter set. That is the
 * same defect that had the category tiles reading "P2 analysis 3"
 * against a real 1,768, so this one is a server-side aggregate over
 * every matching ad and cannot drift with paging.
 *
 * "Launched" has two honest readings and the toggle picks between them:
 *
 *   Created     the day the ad was built (ad_lifecycle.ad_created_time)
 *   First seen  the day it first actually delivered an impression
 *               (MIN(day) from insights_daily_by_ad)
 *
 * An ad can be created and never run, so Created counts intent while
 * First seen counts activity. Over 2026-08-16..09-15 that is 1,384
 * against 830 — the gap is real and worth being able to see.
 */

import { useEffect, useState } from "react";
import { ApiError, LaunchPoint, fetchAdsAnalyseLaunches } from "@/lib/api";
import { BarChart } from "./charts/BarChart";

type Basis = "created" | "first_seen";

export function AdsLaunchChart({
  fromDate,
  toDate,
  accountName,
  category,
  adStatus,
  search,
  exclCopy,
}: {
  fromDate: string;
  toDate: string;
  accountName?: string;
  category?: string;
  adStatus?: string;
  search?: string;
  exclCopy?: boolean;
}) {
  const [basis, setBasis] = useState<Basis>("created");
  const [points, setPoints] = useState<LaunchPoint[]>([]);
  const [totalAds, setTotalAds] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!fromDate || !toDate) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchAdsAnalyseLaunches({
      from_date: fromDate,
      to_date: toDate,
      basis,
      account_name: accountName,
      category,
      ad_effective_status: adStatus,
      search,
      excl_copy: exclCopy,
    })
      .then((res) => {
        if (cancelled) return;
        setPoints(res.points);
        setTotalAds(res.total_ads);
      })
      .catch((e) => {
        if (!cancelled)
          setError(e instanceof ApiError ? e.message : "Could not load the launch series.");
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [fromDate, toDate, basis, accountName, category, adStatus, search, exclCopy]);

  if (!fromDate || !toDate) {
    return (
      <div className="rounded-lg border border-border-primary bg-white p-4 text-sm text-text-tertiary shadow-sm">
        Pick a date range to see how many ads were launched in it.
      </div>
    );
  }

  const peak = points.reduce(
    (best, p) => (p.ads > (best?.ads ?? -1) ? p : best),
    null as LaunchPoint | null,
  );
  const activeDays = points.length;
  const perDay = activeDays ? totalAds / activeDays : 0;

  return (
    <div className="rounded-lg border border-border-primary bg-white p-3 shadow-sm">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <div className="text-sm font-semibold">Ads launched</div>
          <div className="text-[11px] text-text-tertiary">
            {basis === "created"
              ? "by the day the ad was created"
              : "by the day the ad first delivered an impression"}
            {" · "}
            {fromDate} → {toDate}
          </div>
        </div>
        <div className="inline-flex overflow-hidden rounded-md border border-border-primary">
          {(
            [
              ["created", "Created"],
              ["first_seen", "First seen"],
            ] as [Basis, string][]
          ).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setBasis(key)}
              title={
                key === "created"
                  ? "When the ad was built — counts intent, including ads that never ran"
                  : "When the ad first delivered an impression — counts activity"
              }
              className={
                "px-2.5 py-1 text-xs " +
                (basis === key
                  ? "bg-text-primary text-white"
                  : "text-text-primary hover:bg-bg-muted")
              }
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="py-6 text-center text-sm text-error-text">{error}</div>}
      {loading && !error && (
        <div className="py-10 text-center text-sm text-text-tertiary">Loading…</div>
      )}
      {!loading && !error && points.length === 0 && (
        <div className="py-10 text-center text-sm text-text-tertiary">
          No ads {basis === "created" ? "created" : "first delivered"} in this window.
        </div>
      )}

      {!loading && !error && points.length > 0 && (
        <>
          <div className="mb-2 flex flex-wrap gap-4 text-xs">
            <span>
              <b className="text-base">{totalAds.toLocaleString("en-IN")}</b>{" "}
              <span className="text-text-tertiary">ads</span>
            </span>
            <span className="text-text-tertiary">
              {activeDays} active day{activeDays === 1 ? "" : "s"} · {perDay.toFixed(1)}/day avg
            </span>
            {peak && (
              <span className="text-text-tertiary">
                peak {peak.ads.toLocaleString("en-IN")} on {peak.day}
              </span>
            )}
          </div>
          <div className="overflow-x-auto">
            <BarChart
              categories={points.map((p) => p.day.slice(5))}
              series={[{ name: "Ads launched", values: points.map((p) => p.ads) }]}
              height={260}
              valueFormat={(n) => n.toLocaleString("en-IN")}
            />
          </div>
          <p className="mt-2 text-[11px] leading-relaxed text-text-tertiary">
            Counted server-side across every ad matching the current filters, not just the rows
            paged into the table below. <b>Created</b> counts ads that were built — including any
            that never ran; <b>First seen</b> counts ads that actually delivered.
          </p>
        </>
      )}
    </div>
  );
}

export default AdsLaunchChart;
