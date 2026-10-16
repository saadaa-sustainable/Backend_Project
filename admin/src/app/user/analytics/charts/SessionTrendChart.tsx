"use client";

import { useId, useState } from "react";
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
const CURRENCY = { top: 26, height: 108 };
const ARPU = { top: 174, height: 76 };
const CONVERSION = { top: 290, height: 72 };
const COLORS = [CATEGORICAL_PALETTE[0], CATEGORICAL_PALETTE[1], CATEGORICAL_PALETTE[2],
                CATEGORICAL_PALETTE[3]];
const money = (n: number | null) => n === null ? "—"
  : n.toLocaleString("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const percent = (n: number | null) => n === null ? "—"
  : n.toLocaleString("en-IN", { style: "percent", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const shortDay = (day: string) => new Date(`${day}T12:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short" });

/** Aligned plots keep rupees and percentages on separate, labelled scales. */
export function SessionTrendChart({ points }: { points: DashboardSessionTrendPoint[] }) {
  const titleId = useId();
  const [selected, setSelected] = useState<number | null>(null);
  const active = Math.min(selected ?? points.length - 1, points.length - 1);
  const point = points[active];
  const hasMetrics = points.some((p) => p.cost_per_session !== null
    || p.revenue_per_session !== null || p.conversion_rate !== null
    || p.ga4_arpu != null);
  if (!point || !hasMetrics) {
    return <p className="py-8 text-sm text-text-secondary">No daily session metrics are available for this period.</p>;
  }

  const currencyValues = points.flatMap((p) => [p.cost_per_session, p.revenue_per_session])
    .filter((n): n is number => n !== null);
  const currencyMin = Math.min(0, ...currencyValues);
  const currencyMax = Math.max(1, ...currencyValues) * 1.08;
  const rateMax = Math.max(0.01, ...points.map((p) => p.conversion_rate ?? 0)) * 1.08;
  // ARPU's own extent. Floored at its own minimum rather than at zero:
  // the series sits in a narrow band well above zero, and anchoring to
  // zero would compress every real movement into a few pixels.
  const arpuValues = points.map((p) => p.ga4_arpu).filter((n): n is number => n != null);
  const arpuMin = arpuValues.length ? Math.min(...arpuValues) * 0.92 : 0;
  const arpuMax = arpuValues.length ? Math.max(...arpuValues) * 1.08 : 1;
  const x = (i: number) => LEFT + (points.length === 1 ? PLOT_WIDTH / 2 : i / (points.length - 1) * PLOT_WIDTH);
  const yMoney = (value: number) => CURRENCY.top + CURRENCY.height * (1 - (value - currencyMin) / (currencyMax - currencyMin));
  const yRate = (value: number) => CONVERSION.top + CONVERSION.height * (1 - value / rateMax);
  const yArpu = (value: number) => ARPU.top + ARPU.height
    * (1 - (value - arpuMin) / Math.max(arpuMax - arpuMin, 1e-9));
  const lines = [
    { name: "Cost / session", key: "cost_per_session" as const, color: COLORS[0], y: yMoney, dash: undefined },
    { name: "Revenue / session", key: "revenue_per_session" as const, color: COLORS[1], y: yMoney, dash: "6 3" },
    { name: "Conversion rate", key: "conversion_rate" as const, color: COLORS[2], y: yRate, dash: undefined },
    // GA4 end to end, on its own band: the two rupee lines above
    // divide by Meta-driven Shopify sessions, this divides by GA4's
    // deduplicated user count for the day.
    { name: "ARPU (GA4)", key: "ga4_arpu" as const, color: COLORS[3], y: yArpu, dash: undefined },
  ];
  const labelCount = Math.min(7, points.length);
  const labelIndices = [...new Set(Array.from({ length: labelCount }, (_, i) =>
    Math.round(i * (points.length - 1) / Math.max(1, labelCount - 1))))];

  function pathFor(line: typeof lines[number]): string {
    let started = false;
    return points.map((p, i) => {
      const value = p[line.key];
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
          <span key={line.key} className="inline-flex items-center gap-2">
            <svg width="24" height="8" aria-hidden="true"><line x1="0" y1="4" x2="24" y2="4" stroke={line.color} strokeWidth="2" strokeDasharray={line.dash} /></svg>
            {line.name}{line.key === "conversion_rate" ? " (%) · attributed" : " (₹)"}
          </span>
        ))}
      </div>
      <div className="mt-3 overflow-x-auto">
        <svg viewBox={`0 0 ${WIDTH} 400`} className="w-full min-w-[560px]" role="img" aria-labelledby={titleId}
          onPointerMove={(event) => {
            const box = event.currentTarget.getBoundingClientRect();
            const position = (event.clientX - box.left) / box.width * WIDTH;
            setSelected(Math.max(0, Math.min(points.length - 1, Math.round((position - LEFT) / PLOT_WIDTH * (points.length - 1)))));
          }}>
          <title id={titleId}>Daily cost and revenue per session in rupees, ARPU in rupees per GA4 active user, and attributed conversion rate in percent. Use the day slider below to inspect values.</title>
          <text x={LEFT} y="12" fontSize="11" fill={theme.textSecondary}>Cost and revenue / session · ₹</text>
          <text x={LEFT} y="160" fontSize="11" fill={theme.textSecondary}>ARPU · ₹ per GA4 active user that day</text>
          <text x={LEFT} y="276" fontSize="11" fill={theme.textSecondary}>Conversion rate · %</text>
          {[0, 1, 2, 3].map((i) => {
            const value = currencyMin + (currencyMax - currencyMin) * i / 3;
            return <g key={`money-${i}`}>
              <line x1={LEFT} x2={WIDTH - RIGHT} y1={yMoney(value)} y2={yMoney(value)} stroke={theme.borderSoft} />
              <text x={LEFT - 10} y={yMoney(value)} dominantBaseline="middle" textAnchor="end" fontSize="11" fill={theme.textSecondary}>{money(value)}</text>
            </g>;
          })}
          {[0, 1, 2].map((i) => {
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
          {lines.map((line) => <g key={line.key}>
            <path d={pathFor(line)} fill="none" stroke={line.color} strokeWidth="2" strokeDasharray={line.dash} strokeLinejoin="round" />
            {points.map((p, i) => p[line.key] === null ? null : (
              // Dots preserve single-day ranges and isolated points beside gaps.
              <circle key={p.day} cx={x(i)} cy={line.y(p[line.key]!)} r={i === active ? 4 : points.length <= 90 || points[i - 1]?.[line.key] == null || points[i + 1]?.[line.key] == null ? 2 : 0} fill={line.color} />
            ))}
          </g>)}
          {[CURRENCY, ARPU, CONVERSION].map((plot) => <line key={plot.top} x1={x(active)} x2={x(active)} y1={plot.top} y2={plot.top + plot.height} stroke={theme.textTertiary} strokeDasharray="3 3" />)}
          {labelIndices.map((i) => <text key={points[i].day} x={x(i)} y="388" textAnchor={i === 0 ? "start" : i === points.length - 1 ? "end" : "middle"} fontSize="11" fill={theme.textSecondary}>{shortDay(points[i].day)}</text>)}
        </svg>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-5 gap-y-2 text-xs text-text-secondary" aria-live="off">
        <span className="font-medium text-text-primary">{point.day}</span>
        <span>{point.sessions === null ? "Sessions unavailable" : `${point.sessions.toLocaleString("en-IN")} Meta sessions`}</span>
        <span>Cost / session: <strong className="font-medium text-text-primary">{money(point.cost_per_session)}</strong></span>
        <span>Revenue / session: <strong className="font-medium text-text-primary">{money(point.revenue_per_session)}</strong></span>
        <span>ARPU (GA4): <strong className="font-medium text-text-primary">{money(point.ga4_arpu ?? null)}</strong></span>
        <span>Conversion: <strong className="font-medium text-text-primary">{percent(point.conversion_rate)}</strong></span>
      </div>
      {points.length > 1 && <input type="range" min="0" max={points.length - 1} value={active}
        aria-label="Inspect daily session metrics" aria-valuetext={`${point.day}, cost per session ${money(point.cost_per_session)}, revenue per session ${money(point.revenue_per_session)}, conversion ${percent(point.conversion_rate)}`}
        onChange={(event) => setSelected(Number(event.target.value))} className="mt-3 h-5 w-full cursor-pointer accent-[var(--accent-yellow)]" />}
      <p className="mt-1 text-xs text-text-secondary">Daily ratios use the same definitions as the cards above. Cost and revenue per session divide by Meta-driven Shopify sessions. ARPU sits on its own scale because it divides by something else entirely — GA4's deduplicated count of users active that day, so each visitor is counted once however many times they came back. That makes a point on the ARPU line exact, unlike the figure on the card above, which adds those daily counts together. Gaps mark days with no data.</p>
    </div>
  );
}
