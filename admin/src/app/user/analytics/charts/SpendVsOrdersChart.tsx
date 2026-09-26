"use client";

/**
 * Daily ad spend against the orders credited to it, small.
 *
 * WHY EACH LINE HAS ITS OWN SCALE. Spend runs in lakhs and orders in
 * hundreds. On one axis the order line flattens onto the floor and
 * carries no information. A twin axis would fit, but at this size two
 * sets of labels cost more room than the plot itself — so each line is
 * drawn against its own range and that range is printed in the legend.
 * The shapes are then honestly comparable and the heights explicitly
 * are not, which the caption says out loud.
 *
 * WHY THE FLOOR IS NOT ZERO. Both series sit between roughly 70 and
 * 100% of their peak, so anchored at zero they compress into the top
 * third of the box and the variation this chart exists to show becomes
 * a wobble. A zero baseline is what keeps a single-axis chart honest
 * about magnitude — but magnitude is already off the table here, since
 * the two lines are on different scales by construction. So each is
 * scaled across its own low-to-high and the legend prints both ends,
 * which is where the magnitude actually lives.
 *
 * It fills the content column. An earlier cut capped it at 640px
 * because a 13:1 aspect flattened both series into a band a few pixels
 * tall — but that was the zero-anchored scale doing the flattening,
 * not the width. Scaled low-to-high the shape uses the whole box, and
 * the extra width buys resolution: 30 days across 1280px gives each
 * day room to show a real move rather than a kink.
 *
 * The series arrives already stopped at the last COMPLETE day, so
 * there is no partial final point to draw. `truncatedTo` says where it
 * ends when that is short of the range asked for.
 */

import { useId, useState } from "react";

import { theme } from "@/lib/theme";

export interface SpendVsOrdersPoint {
  day: string;
  ad_spend: number;
  attributed_orders: number;
}

const H = 140;
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
  truncatedTo,
}: {
  points: SpendVsOrdersPoint[];
  maxSpend: number;
  maxOrders: number;
  truncatedTo?: string | null;
}) {
  const clipId = useId();
  const [hover, setHover] = useState<number | null>(null);
  if (points.length < 2) return null;

  const plotH = H - PAD.top - PAD.bottom;
  const xs = (i: number) => (i / (points.length - 1)) * 100; // percent

  const spendVals = points.map((p) => p.ad_spend);
  const orderVals = points.map((p) => p.attributed_orders);
  const loSpend = Math.min(...spendVals);
  const loOrders = Math.min(...orderVals);
  // A flat series would divide by zero; give it a mid-height line.
  const band = (v: number, lo: number, hi: number) =>
    hi > lo ? PAD.top + plotH - ((v - lo) / (hi - lo)) * plotH : PAD.top + plotH / 2;
  const ySpend = (v: number) => band(v, loSpend, maxSpend);
  const yOrders = (v: number) => band(v, loOrders, maxOrders);

  const spendPath = points
    .map((p, i) => `${i ? "L" : "M"}${xs(i)},${ySpend(p.ad_spend)}`)
    .join("");
  const ordersPath = points
    .map((p, i) => `${i ? "L" : "M"}${xs(i)},${yOrders(p.attributed_orders)}`)
    .join("");

  const h = hover !== null ? points[hover] : null;

  return (
    <div className="flex w-full flex-col gap-1">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-0.5 text-[10px]">
        <span className="inline-flex items-center gap-1.5 text-text-secondary">
          <span className="h-[2px] w-3" style={{ background: theme.accentYellow }} />
          Ad spend · {inr(loSpend)}–{inr(maxSpend)}
        </span>
        <span className="inline-flex items-center gap-1.5 text-text-secondary">
          <span className="h-[2px] w-3" style={{ background: theme.warningMid }} />
          Orders credited · {loOrders.toLocaleString()}–{maxOrders.toLocaleString()}
        </span>
        {h && (
          <span className="ml-auto font-medium text-text-primary">
            {h.day} · {inr(h.ad_spend)} ·{" "}
            {h.attributed_orders.toLocaleString()} orders
          </span>
        )}
      </div>

      <svg
        viewBox={`0 0 100 ${H}`}
        preserveAspectRatio="none"
        className="h-[140px] w-full"
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
        {/* Marks each line's own low, not zero. */}
        <line x1="0" y1={PAD.top + plotH} x2="100" y2={PAD.top + plotH}
              stroke={theme.borderSoft} strokeWidth="1"
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
        Each line runs between its own low and high, so compare the{" "}
        <em>shape</em>, not the height. The floor is each line&rsquo;s own
        minimum, not zero.
        {truncatedTo ? ` Ends ${truncatedTo} — the newest days are still partial.` : ""}
      </p>
    </div>
  );
}
