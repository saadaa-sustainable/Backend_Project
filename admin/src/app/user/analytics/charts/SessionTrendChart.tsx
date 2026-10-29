"use client";

import { Fragment, useId, useState } from "react";
import type { DashboardSessionTrendPoint } from "@/lib/api";
import { CATEGORICAL_PALETTE, theme } from "@/lib/theme";

const WIDTH = 1000;
const LEFT = 64;
const RIGHT = 24;
const PLOT_WIDTH = WIDTH - LEFT - RIGHT;
// Three bands, not two. ARPU had been sharing the rupee axis with
// cost and revenue per session, which made it look like a third
// measure of the same thing -- it is not. Those two divide by
// Meta-driven Shopify sessions; ARPU divides by GA4's own
// deduplicated user count for that day. A shared axis also let a
// revenue/session spike (14 Oct hit Rs 195 on a collapsed session
// count) flatten ARPU's whole range against the floor.
//
// Its own band gives it its own scale, so day-to-day movement in the
// Rs 26-35 range is legible instead of being a flat line.
//
// The bands are laid out from a list rather than fixed, because the
// ARPU band is not always there: it is GA4's figure, so it has nothing
// to draw on the Shopify tab and leaving an empty labelled band would
// claim a measurement that does not exist.
const BAND_GAP = 40;
const CURRENCY_H = 108;
const ARPU_H = 76;
const CONVERSION_H = 72;
const COLORS = [CATEGORICAL_PALETTE[0], CATEGORICAL_PALETTE[1], CATEGORICAL_PALETTE[2],
                CATEGORICAL_PALETTE[3]];
const money = (n: number | null) => n === null ? "—"
  : n.toLocaleString("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const percent = (n: number | null) => n === null ? "—"
  : n.toLocaleString("en-IN", { style: "percent", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const shortDay = (day: string) => new Date(`${day}T12:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short" });

/** Which source's lines to draw. Matches the tab above the chart. */
export type TrendSource = "meta" | "shopify" | "google" | "both";

/** The three ratios, per source. Colour carries the METRIC and dash
 *  carries the SOURCE -- so on "both" a pair sits in one colour, solid
 *  for Shopify and dashed for GA4, and the gap between them is the
 *  thing you are looking at. */
const SERIES: Record<Exclude<TrendSource, "both">, {
  cost: keyof DashboardSessionTrendPoint;
  revenue: keyof DashboardSessionTrendPoint;
  rate: keyof DashboardSessionTrendPoint;
  label: string;
  dash?: string;
}> = {
  meta: {
    cost: "cost_per_session", revenue: "revenue_per_session",
    rate: "conversion_rate", label: "Meta", dash: undefined,
  },
  shopify: {
    cost: "all_cost_per_session", revenue: "all_revenue_per_session",
    rate: "all_conversion_rate", label: "Shopify", dash: undefined,
  },
  google: {
    cost: "ga4_cost_per_session", revenue: "ga4_revenue_per_session",
    rate: "ga4_conversion_rate", label: "GA4", dash: "5 3",
  },
};

/** Aligned plots keep rupees and percentages on separate, labelled scales. */
export function SessionTrendChart({
  points, source = "meta",
}: { points: DashboardSessionTrendPoint[]; source?: TrendSource }) {
  const titleId = useId();
  const [selected, setSelected] = useState<number | null>(null);
  const active = Math.min(selected ?? points.length - 1, points.length - 1);
  const point = points[active];
  // Which sources are drawn, in draw order.
  // "both" draws the two ALL-TRAFFIC readings against each other --
  // Shopify and GA4 watching the same population. Meta is a subset of
  // Shopify, so laying it beside GA4 would compare a part with a whole
  // and most of the gap would be scope rather than measurement.
  const sources: Exclude<TrendSource, "both">[] =
    source === "both" ? ["shopify", "google"] : [source];
  // ARPU is GA4's alone: its band belongs on the tabs where GA4 is
  // actually drawn. "Not Meta" was the wrong test -- it put a GA4 line
  // on the Shopify tab, which has no GA4 figure on it anywhere.
  const showArpu = sources.includes("google");

  const num = (p: DashboardSessionTrendPoint, k: keyof DashboardSessionTrendPoint) => {
    const v = p[k];
    return typeof v === "number" ? v : null;
  };

  const hasMetrics = points.some((p) => sources.some((src) =>
    num(p, SERIES[src].cost) !== null || num(p, SERIES[src].revenue) !== null
    || num(p, SERIES[src].rate) !== null) || (showArpu && p.ga4_arpu != null));
  if (!point || !hasMetrics) {
    return <p className="py-8 text-sm text-text-secondary">No daily session metrics are available for this period.</p>;
  }

  // Scales span every drawn source, so the two columns of a "both" view
  // share one axis and can actually be compared by eye.
  const currencyValues = points.flatMap((p) => sources.flatMap((src) =>
    [num(p, SERIES[src].cost), num(p, SERIES[src].revenue)]))
    .filter((n): n is number => n !== null);
  const currencyMin = Math.min(0, ...currencyValues);
  const currencyMax = Math.max(1, ...currencyValues) * 1.08;
  const rateMax = Math.max(0.01, ...points.flatMap((p) =>
    sources.map((src) => num(p, SERIES[src].rate) ?? 0))) * 1.08;
  // ARPU's own extent. Floored at its own minimum rather than at zero:
  // the series sits in a narrow band well above zero, and anchoring to
  // zero would compress every real movement into a few pixels.
  const arpuValues = points.map((p) => p.ga4_arpu).filter((n): n is number => n != null);
  const arpuMin = arpuValues.length ? Math.min(...arpuValues) * 0.92 : 0;
  const arpuMax = arpuValues.length ? Math.max(...arpuValues) * 1.08 : 1;
  // Stack the bands that are actually drawn.
  const CURRENCY = { top: 26, height: CURRENCY_H };
  const ARPU = { top: CURRENCY.top + CURRENCY_H + BAND_GAP, height: ARPU_H };
  const CONVERSION = {
    top: showArpu ? ARPU.top + ARPU_H + BAND_GAP : CURRENCY.top + CURRENCY_H + BAND_GAP,
    height: CONVERSION_H,
  };
  const HEIGHT = CONVERSION.top + CONVERSION_H + 38;

  const x = (i: number) => LEFT + (points.length === 1 ? PLOT_WIDTH / 2 : i / (points.length - 1) * PLOT_WIDTH);
  const yMoney = (value: number) => CURRENCY.top + CURRENCY.height * (1 - (value - currencyMin) / (currencyMax - currencyMin));
  const yRate = (value: number) => CONVERSION.top + CONVERSION.height * (1 - value / rateMax);
  const yArpu = (value: number) => ARPU.top + ARPU.height
    * (1 - (value - arpuMin) / Math.max(arpuMax - arpuMin, 1e-9));

  // Colour is the metric, dash is the source.
  const lines: {
    name: string; key: keyof DashboardSessionTrendPoint; color: string;
    y: (v: number) => number; dash?: string;
  }[] = [
    ...sources.flatMap((src) => {
      const sfx = source === "both" ? ` · ${SERIES[src].label}` : "";
      return [
        { name: `Cost / session${sfx}`, key: SERIES[src].cost, color: COLORS[0], y: yMoney, dash: SERIES[src].dash },
        { name: `Revenue / session${sfx}`, key: SERIES[src].revenue, color: COLORS[1], y: yMoney, dash: SERIES[src].dash },
        { name: `Conversion rate${sfx}`, key: SERIES[src].rate, color: COLORS[2], y: yRate, dash: SERIES[src].dash },
      ];
    }),
    // GA4 end to end, on its own band: the rupee lines above divide by
    // a session count, this divides by GA4's deduplicated user count
    // for the day. Dropped entirely on the Shopify tab, which has no
    // user count to divide by.
    ...(showArpu
      ? [{ name: "ARPU (GA4)", key: "ga4_arpu" as keyof DashboardSessionTrendPoint,
           color: COLORS[3], y: yArpu, dash: undefined }]
      : []),
  ];
  const labelCount = Math.min(7, points.length);
  const labelIndices = [...new Set(Array.from({ length: labelCount }, (_, i) =>
    Math.round(i * (points.length - 1) / Math.max(1, labelCount - 1))))];

  function pathFor(line: typeof lines[number]): string {
    let started = false;
    return points.map((p, i) => {
      const value = num(p, line.key);
      // `== null`, not `=== null`: ga4_arpu is optional, so a payload
      // without it yields undefined rather than null, and a strict
      // check would pass undefined to y() and draw NaN coordinates.
      if (value == null) { started = false; return ""; }
      const command = started ? "L" : "M";
      started = true;
      return `${command}${x(i)},${line.y(value)}`;
    }).join(" ");
  }

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="text-sm font-medium text-text-primary">Daily session trends</h4>
        <span className="text-xs text-text-secondary">{shortDay(points[0].day)} – {shortDay(points[points.length - 1].day)}</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-5 gap-y-2 text-xs text-text-secondary">
        {lines.map((line) => (
          <span key={line.name} className="inline-flex items-center gap-2">
            <svg width="24" height="8" aria-hidden="true"><line x1="0" y1="4" x2="24" y2="4" stroke={line.color} strokeWidth="2" strokeDasharray={line.dash} /></svg>
            {line.name}{line.name.startsWith("Conversion") ? " (%)" : " (₹)"}
          </span>
        ))}
      </div>
      <div className="mt-3 overflow-x-auto">
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full min-w-[560px]" role="img" aria-labelledby={titleId}
          onPointerMove={(event) => {
            const box = event.currentTarget.getBoundingClientRect();
            const position = (event.clientX - box.left) / box.width * WIDTH;
            setSelected(Math.max(0, Math.min(points.length - 1, Math.round((position - LEFT) / PLOT_WIDTH * (points.length - 1)))));
          }}>
          <title id={titleId}>Daily cost and revenue per session in rupees, ARPU in rupees per GA4 active user, and attributed conversion rate in percent. Use the day slider below to inspect values.</title>
          <text x={LEFT} y={CURRENCY.top - 14} fontSize="11" fill={theme.textSecondary}>
            Cost and revenue / session · ₹{source === "both" ? " · solid Shopify, dashed GA4" : ""}
          </text>
          {showArpu && (
            <text x={LEFT} y={ARPU.top - 14} fontSize="11" fill={theme.textSecondary}>ARPU · ₹ per GA4 active user that day</text>
          )}
          <text x={LEFT} y={CONVERSION.top - 14} fontSize="11" fill={theme.textSecondary}>Conversion rate · %</text>
          {[0, 1, 2, 3].map((i) => {
            const value = currencyMin + (currencyMax - currencyMin) * i / 3;
            return <g key={`money-${i}`}>
              <line x1={LEFT} x2={WIDTH - RIGHT} y1={yMoney(value)} y2={yMoney(value)} stroke={theme.borderSoft} />
              <text x={LEFT - 10} y={yMoney(value)} dominantBaseline="middle" textAnchor="end" fontSize="11" fill={theme.textSecondary}>{money(value)}</text>
            </g>;
          })}
          {(showArpu ? [0, 1, 2] : []).map((i) => {
            const value = arpuMin + (arpuMax - arpuMin) * i / 2;
            return <g key={`arpu-${i}`}>
              <line x1={LEFT} x2={WIDTH - RIGHT} y1={yArpu(value)} y2={yArpu(value)} stroke={theme.borderSoft} />
              <text x={LEFT - 10} y={yArpu(value)} dominantBaseline="middle" textAnchor="end" fontSize="11" fill={theme.textSecondary}>{money(value)}</text>
            </g>;
          })}
          {[0, 1, 2].map((i) => {
            const value = rateMax * i / 2;
            return <g key={`rate-${i}`}>
              <line x1={LEFT} x2={WIDTH - RIGHT} y1={yRate(value)} y2={yRate(value)} stroke={theme.borderSoft} />
              <text x={LEFT - 10} y={yRate(value)} dominantBaseline="middle" textAnchor="end" fontSize="11" fill={theme.textSecondary}>{percent(value)}</text>
            </g>;
          })}
          {lines.map((line) => <g key={line.name}>
            <path d={pathFor(line)} fill="none" stroke={line.color} strokeWidth="2" strokeDasharray={line.dash} strokeLinejoin="round" />
            {points.map((p, i) => num(p, line.key) === null ? null : (
              // Dots preserve single-day ranges and isolated points beside gaps.
              <circle key={p.day} cx={x(i)} cy={line.y(num(p, line.key)!)} r={i === active ? 4 : points.length <= 90 || num(points[i - 1] ?? p, line.key) === null || num(points[i + 1] ?? p, line.key) === null ? 2 : 0} fill={line.color} />
            ))}
          </g>)}
          {[CURRENCY, ...(showArpu ? [ARPU] : []), CONVERSION].map((plot) => <line key={plot.top} x1={x(active)} x2={x(active)} y1={plot.top} y2={plot.top + plot.height} stroke={theme.textTertiary} strokeDasharray="3 3" />)}
          {labelIndices.map((i) => <text key={points[i].day} x={x(i)} y={HEIGHT - 12} textAnchor={i === 0 ? "start" : i === points.length - 1 ? "end" : "middle"} fontSize="11" fill={theme.textSecondary}>{shortDay(points[i].day)}</text>)}
        </svg>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-5 gap-y-2 text-xs text-text-secondary" aria-live="off">
        <span className="font-medium text-text-primary">{point.day}</span>
        {sources.map((src) => {
          const sfx = source === "both" ? ` · ${SERIES[src].label}` : "";
          const sess = src === "google" ? point.ga4_sessions ?? null
            : src === "shopify" ? point.all_sessions ?? null : point.sessions;
          return (
            <Fragment key={src}>
              <span>
                {sess === null ? "Sessions unavailable"
                  : `${sess.toLocaleString("en-IN")} ${SERIES[src].label} sessions`}
              </span>
              <span>Cost / session{sfx}: <strong className="font-medium text-text-primary">{money(num(point, SERIES[src].cost))}</strong></span>
              <span>Revenue / session{sfx}: <strong className="font-medium text-text-primary">{money(num(point, SERIES[src].revenue))}</strong></span>
              <span>Conversion{sfx}: <strong className="font-medium text-text-primary">{percent(num(point, SERIES[src].rate))}</strong></span>
            </Fragment>
          );
        })}
        {showArpu && <span>ARPU (GA4): <strong className="font-medium text-text-primary">{money(point.ga4_arpu ?? null)}</strong></span>}
      </div>
      {points.length > 1 && <input type="range" min="0" max={points.length - 1} value={active}
        aria-label="Inspect daily session metrics" aria-valuetext={`${point.day}, cost per session ${money(num(point, SERIES[sources[0]].cost))}, revenue per session ${money(num(point, SERIES[sources[0]].revenue))}, conversion ${percent(num(point, SERIES[sources[0]].rate))}`}
        onChange={(event) => setSelected(Number(event.target.value))} className="mt-3 h-5 w-full cursor-pointer accent-[var(--accent-yellow)]" />}
      <p className="mt-1 text-xs text-text-secondary">
        Daily ratios use the same definitions as the cards above, and follow the source tab.{" "}
        {source === "meta"
          ? "Meta's orders over Meta-driven Shopify sessions."
          : source === "shopify"
            ? "All of Shopify's orders over all of its sessions, against blended spend — Meta plus Google Ads plus Kwikchat — because the traffic is everyone's and so is the cost."
            : source === "google"
              ? "GA4's revenue and purchases over GA4 sessions — all traffic, since GA4 cannot be narrowed to Meta. Cost per session uses blended spend: Meta plus Google Ads plus Kwikchat."
              : "Two systems watching the same all-traffic population, so a solid line and its dashed twin should roughly agree — where they do not, one of them is mismeasuring."}
        {showArpu && " ARPU sits on its own scale because it divides by something else entirely — GA4's deduplicated count of users active that day, so each visitor is counted once however many times they came back. That makes a point on the ARPU line exact, unlike the figure on the card above, which adds those daily counts together."}
        {" "}Gaps mark days with no data.
      </p>
    </div>
  );
}
