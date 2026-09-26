"use client";

/**
 * Daily ad spend against the orders credited to it, small.
 *
 * WHY EACH LINE HAS ITS OWN SCALE. Spend runs in lakhs and orders in
 * hundreds. On one axis the order line flattens onto the floor and
 * carries no information. A twin axis would fit, but at this size two
 * sets of labels cost more room than the plot itself — so each line is
 * drawn against its own maximum and that maximum is printed in the
 * legend. The shapes are then honestly comparable and the heights
 * explicitly are not, which the caption says out loud.
 *
 * A null spend day breaks the line rather than dropping it to zero:
 * Meta reports a day in arrears, so the newest point in any window has
 * orders against no spend yet, and a line diving to the floor on the
 * most-looked-at day of the chart is a lie about delivery.
 */

import { useId, useState } from "react";

import { theme } from "@/lib/theme";

export interface SpendVsOrdersPoint {
  day: string;
  ad_spend: number | null;
  attributed_orders: number;
}

const H = 96;
const PAD = { top: 10, right: 2, bottom: 16, left: 2 };

function inr(n: number): string {
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)}Cr`;
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(2)}L`;
  if (n >= 1e3) return `₹${(n / 1e3).toFixed(1)}k`;
  return `₹${Math.round(n)}`;
}

export function SpendVsOrdersChart({
  points,
  maxSpend,
  maxOrders,
}: {
  points: SpendVsOrdersPoint[];
  maxSpend: number;
  maxOrders: number;
}) {
  const clipId = useId();
  const [hover, setHover] = useState<number | null>(null);
  if (points.length < 2) return null;

  const plotH = H - PAD.top - PAD.bottom;
  const xs = (i: number) => (i / (points.length - 1)) * 100; // percent
  const ySpend = (v: number) => PAD.top + plotH - (v / (maxSpend || 1)) * plotH;
  const yOrders = (v: number) => PAD.top + plotH - (v / (maxOrders || 1)) * plotH;

  // A null breaks the path rather than interpolating across it.
  const spendPath = points.reduce((d, p, i) => {
    if (p.ad_spend === null) return d;
    const prevNull = i === 0 || points[i - 1].ad_spend === null;
    return d + `${prevNull ? "M" : "L"}${xs(i)},${ySpend(p.ad_spend)}`;
  }, "");
  const ordersPath = points
    .map((p, i) => `${i ? "L" : "M"}${xs(i)},${yOrders(p.attributed_orders)}`)
    .join("");

  const h = hover !== null ? points[hover] : null;

  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-0.5 text-[10px]">
        <span className="inline-flex items-center gap-1.5 text-text-secondary">
          <span className="h-[2px] w-3" style={{ background: theme.accentYellow }} />
          Ad spend · peak {inr(maxSpend)}
        </span>
        <span className="inline-flex items-center gap-1.5 text-text-secondary">
          <span className="h-[2px] w-3" style={{ background: theme.warningMid }} />
          Orders credited · peak {maxOrders.toLocaleString()}
        </span>
        {h && (
          <span className="ml-auto font-medium text-text-primary">
            {h.day} · {h.ad_spend === null ? "spend not in yet" : inr(h.ad_spend)} ·{" "}
            {h.attributed_orders.toLocaleString()} orders
          </span>
        )}
      </div>

      <svg
        viewBox={`0 0 100 ${H}`}
        preserveAspectRatio="none"
        className="h-[96px] w-full"
        role="img"
        aria-label={`Daily ad spend against orders credited to it, ${points.length} days`}
        onMouseLeave={() => setHover(null)}
      >
        <defs>
          <clipPath id={clipId}>
            <rect x="0" y="0" width="100" height={H} />
          </clipPath>
        </defs>
        {/* One baseline rule. No box, no grid — at this height a grid is
            more ink than the data. */}
        <line x1="0" y1={PAD.top + plotH} x2="100" y2={PAD.top + plotH}
              stroke={theme.borderPrimary} strokeWidth="1"
              vectorEffect="non-scaling-stroke" />
        <g clipPath={`url(#${clipId})`}>
          <path d={ordersPath} fill="none" stroke={theme.warningMid}
                strokeWidth="1.5" vectorEffect="non-scaling-stroke"
                strokeLinejoin="round" strokeLinecap="round" />
          <path d={spendPath} fill="none" stroke={theme.accentYellow}
                strokeWidth="1.5" vectorEffect="non-scaling-stroke"
                strokeLinejoin="round" strokeLinecap="round" />
        </g>
        {hover !== null && (
          <line x1={xs(hover)} y1={PAD.top} x2={xs(hover)} y2={PAD.top + plotH}
                stroke={theme.textTertiary} strokeWidth="1"
                vectorEffect="non-scaling-stroke" />
        )}
        {/* Invisible hit strips: one per day, full height, so the value
            readout does not depend on hitting a 1.5px line. */}
        {points.map((p, i) => (
          <rect
            key={p.day}
            x={i === 0 ? 0 : xs(i) - 50 / (points.length - 1)}
            y="0"
            width={100 / (points.length - 1)}
            height={H}
            fill="transparent"
            onMouseEnter={() => setHover(i)}
          />
        ))}
      </svg>

      <p className="text-[10px] text-text-tertiary">
        Each line is drawn against its own peak, so compare the{" "}
        <em>shape</em>, not the height. A break in the spend line is a day
        Meta has not reported yet.
      </p>
    </div>
  );
}
