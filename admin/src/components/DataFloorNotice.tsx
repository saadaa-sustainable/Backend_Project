"use client";

/**
 * "Everything here starts 1 Jan 2026."
 *
 * Not decoration. Before this, `Lifetime` meant an unbounded range, which
 * made endpoints fall back to Meta's LIFETIME spend and conversion value
 * while Shopify orders covered 2026 only -- 376,348 of 377,215 orders
 * are in 2026, against 794 in all of 2025. The result was 2,751 ads
 * showing 36.9 Cr of Meta conversion value against zero Shopify revenue,
 * which reads as total failure rather than as missing history.
 *
 * Lifetime is now bounded at DATA_FLOOR so every metric shares one
 * basis. The visible cost is that headline spend and conversion value
 * dropped, because they stopped counting years we cannot match orders
 * to. This notice exists so that drop is explained where it is seen,
 * rather than looking like a regression.
 */

import { useEffect, useState } from "react";
import { DATA_FLOOR } from "@/components/DateRangePicker";

const STORAGE_KEY = "dataFloorNoticeDismissed_v1";

function fmt(iso: string) {
  const [y, m, d] = iso.split("-");
  return `${d} ${["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][Number(m) - 1]} ${y}`;
}

export function DataFloorNotice({ className = "" }: { className?: string }) {
  // Dismissal is per-browser and deliberately not persisted anywhere
  // shared: it is a reading aid, not a setting.
  const [hidden, setHidden] = useState(true);

  useEffect(() => {
    try {
      setHidden(window.localStorage.getItem(STORAGE_KEY) === "1");
    } catch {
      setHidden(false);
    }
  }, []);

  if (hidden) return null;

  return (
    <div
      className={`flex items-start gap-2 rounded-md border border-info-mid/40 bg-info-bg px-3 py-2 text-[12px] text-info-text ${className}`}
      role="note"
    >
      <span aria-hidden className="mt-[1px] shrink-0">ⓘ</span>
      <div className="flex-1">
        <b>All figures start {fmt(DATA_FLOOR)}.</b>{" "}
        Shopify order history effectively begins then, so Meta spend and
        conversion value are bounded to the same window rather than to
        Meta&apos;s own lifetime. Without that bound, an ad that ran in 2025
        showed real Meta revenue against zero Shopify revenue — a gap in
        coverage, not a result. <b>Lifetime</b> means &ldquo;since{" "}
        {fmt(DATA_FLOOR)}&rdquo;.
      </div>
      <button
        onClick={() => {
          setHidden(true);
          try {
            window.localStorage.setItem(STORAGE_KEY, "1");
          } catch {}
        }}
        className="shrink-0 rounded px-1.5 py-0.5 text-[11px] hover:bg-info-mid/20"
        aria-label="Dismiss"
      >
        ✕
      </button>
    </div>
  );
}

export default DataFloorNotice;
