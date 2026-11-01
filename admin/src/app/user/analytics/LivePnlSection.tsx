"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchHourlyTracker, type HourlyTrackerResponse } from "@/lib/api";
import { FilterCell, SectionHeader, filterControlClass } from "./SectionChrome";
import { LivePnl } from "./charts/LivePnl";

/**
 * The Live P&L, as its own section rather than a panel inside the
 * Hourly Tracker.
 *
 * It reads the same endpoint and the same day, but it answers a
 * different question -- the tracker asks whether the day is working,
 * this asks whether it is paying -- and the two are read by different
 * people at different moments. Buried under eighteen columns of hourly
 * detail, the margin was something you had to go looking for.
 */

const IST_OFFSET_MIN = 330;

function istToday(): string {
  // No getTimezoneOffset: getTime() is already epoch, so adding the
  // browser's offset corrects a second time for something already
  // correct. It only broke for browsers in IST -- between 00:00 and
  // 05:30 the UTC date is still yesterday, so the page showed yesterday.
  const now = new Date();
  return new Date(now.getTime() + IST_OFFSET_MIN * 60000).toISOString().slice(0, 10);
}

export function LivePnlSection() {
  const [day, setDay] = useState(istToday);
  /** Did someone CHOOSE this day, or did it default to today? Only the
   *  default may roll forward at midnight. */
  const [dayPinned, setDayPinned] = useState(false);
  const [data, setData] = useState<HourlyTrackerResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const params = useMemo(() => ({ day }), [day]);

  useEffect(() => {
    let cancelled = false;
    fetchHourlyTracker(params)
      .then((res) => { if (!cancelled) { setData(res); setError(null); } })
      .catch((e) => { if (!cancelled) setError(String(e?.message ?? e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [params, tick]);

  // Once an hour, matching the ingest. The same tick rolls the date
  // forward at midnight unless a day has been chosen.
  useEffect(() => {
    const id = window.setInterval(() => {
      setDay((d) => (dayPinned ? d : istToday()));
      setTick((n) => n + 1);
    }, 60 * 60000);
    return () => window.clearInterval(id);
  }, [dayPinned]);

  const refresh = useCallback(() => setTick((n) => n + 1), []);
  const t = data?.today ?? null;
  const isToday = day === istToday();

  return (
    <div className="space-y-4">
      <SectionHeader title="Live P&amp;L">
        <span className="text-[11.5px] text-text-tertiary">
          {t ? `${t.hours} hours of ${t.day}` : "no data"}
          {isToday ? " · refreshes hourly" : ""}
        </span>
      </SectionHeader>

      <div className="flex flex-wrap items-end gap-3">
        <FilterCell label="Day" className="w-44" htmlFor="pnl-day">
          <input id="pnl-day" type="date" value={day} max={istToday()}
                 onChange={(e) => { setDayPinned(true); setDay(e.target.value); }}
                 className={filterControlClass} />
        </FilterCell>
        <button type="button" onClick={refresh}
                className="rounded-md border border-border-primary px-3 py-1.5 text-[12.5px] text-text-primary hover:bg-bg-muted">
          Refresh
        </button>
      </div>

      {error && (
        <p className="py-6 text-sm text-warning-text">Could not load: {error}</p>
      )}
      {loading && !data ? (
        <p className="py-8 text-sm text-text-secondary">Loading the day&rsquo;s figures…</p>
      ) : !t || !t.pnl_orders ? (
        <p className="py-8 text-sm text-text-secondary">
          Nothing to show for {day}.
          {data?.first_day && data?.last_day
            ? ` This tracker holds ${data.first_day} to ${data.last_day}.`
            : ""}
        </p>
      ) : (
        <LivePnl totals={t} rows={data?.rows ?? []}
                 liveHour={isToday ? data?.latest_hour : null} />
      )}
    </div>
  );
}
