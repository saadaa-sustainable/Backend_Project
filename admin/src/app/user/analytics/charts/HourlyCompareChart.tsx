"use client";

import { useId, useMemo, useState } from "react";
import type { HourlyRow } from "@/lib/api";
import { CATEGORICAL_PALETTE, theme } from "@/lib/theme";

/**
 * One metric, hour by hour, against the same hours of another day.
 *
 * The trend chart already draws both days as lines, which is the right
 * shape for SHAPE -- where the curve bends, when the peak lands. It is
 * the wrong shape for reading a gap: two lines a few pixels apart at
 * 04:00 and far apart at 20:00 do not tell you which hours actually
 * carried the difference, because the eye compares vertical distance
 * against a changing baseline.
 *
 * Paired bars fix that. Each hour gets today beside the comparison day,
 * sharing one axis, so the gap is a length rather than a distance.
 *
 * A metric picker rather than a fixed series: the question "which hour
 * beat yesterday" is asked of sessions one day and cost per session the
 * next, and three near-identical charts would be worse than one that
 * changes.
 */

const WIDTH = 1000;
const HEIGHT = 300;
const LEFT = 64;
const RIGHT = 16;
const TOP = 16;
const BOTTOM = 46;
const PLOT_W = WIDTH - LEFT - RIGHT;
const PLOT_H = HEIGHT - TOP - BOTTOM;

const NOW_INK = CATEGORICAL_PALETTE[0];

type Fmt = (n: number | null | undefined) => string;

const money: Fmt = (n) =>
  n === null || n === undefined ? "—"
    : n.toLocaleString("en-IN", { style: "currency", currency: "INR",
        minimumFractionDigits: 0, maximumFractionDigits: 0 });
const count: Fmt = (n) =>
  n === null || n === undefined ? "—" : Math.round(n).toLocaleString("en-IN");
const pct2: Fmt = (n) =>
  n === null || n === undefined ? "—" : `${(n * 100).toFixed(2)}%`;
const pct1: Fmt = (n) =>
  n === null || n === undefined ? "—" : `${(n * 100).toFixed(1)}%`;
const ratio: Fmt = (n) =>
  n === null || n === undefined ? "—" : `${n.toFixed(2)}x`;

/** Higher is better unless stated — only cost inverts. */
const METRICS: { key: keyof HourlyRow; label: string; fmt: Fmt; lowerIsBetter?: boolean }[] = [
  { key: "sessions", label: "Sessions", fmt: count },
  { key: "orders", label: "Orders", fmt: count },
  { key: "revenue", label: "Total sales", fmt: money },
  { key: "spend", label: "Spend", fmt: money },
  { key: "cost_per_session", label: "Cost / session", fmt: money, lowerIsBetter: true },
  { key: "revenue_per_session", label: "Rev / session", fmt: money },
  { key: "aov", label: "AOV", fmt: money },
  { key: "conversion_rate", label: "Conversion rate", fmt: pct2 },
  { key: "pct_paid", label: "% paid sessions", fmt: pct1 },
  { key: "amer", label: "AMER", fmt: ratio },
];

const hourLabel = (h: number) => `${(h % 12) || 12}${h < 12 ? "am" : "pm"}`;

export function HourlyCompareChart({ rows, baseline, baselineDay, liveHour }: {
  rows: HourlyRow[];
  baseline: HourlyRow[];
  baselineDay: string;
  /** Still filling. Its bar is drawn hatched and its change withheld. */
  liveHour?: number | null;
}) {
  const titleId = useId();
  const [metricKey, setMetricKey] = useState<string>("sessions");
  const [hover, setHover] = useState<number | null>(null);

  const metric = METRICS.find((m) => m.key === metricKey) ?? METRICS[0];

  const { now, was, max } = useMemo(() => {
    const pick = (rs: HourlyRow[]) => {
      const m = new Map<number, number | null>();
      for (const r of rs) m.set(r.hour_of_day, (r[metric.key] as number | null) ?? null);
      return m;
    };
    const a = pick(rows);
    const b = pick(baseline);
    const all = [...a.values(), ...b.values()].filter(
      (v): v is number => v !== null && Number.isFinite(v));
    return { now: a, was: b, max: all.length ? Math.max(...all) * 1.08 : 1 };
  }, [rows, baseline, metric.key]);

  if (!rows.length) return null;

  // Every hour of the day, not only the hours with data: a part-finished
  // day should visibly stop rather than stretch to fill the width.
  const hours = Array.from({ length: 24 }, (_, i) => i);
  const slot = PLOT_W / 24;
  const barW = Math.max(2, (slot - 4) / 2);
  const y = (v: number) => TOP + PLOT_H * (1 - v / max);
  const h = (v: number) => Math.max(0, PLOT_H - (y(v) - TOP));

  const hv = hover === null ? null : {
    hour: hover,
    now: now.get(hover) ?? null,
    was: was.get(hover) ?? null,
  };
  const change = hv && hv.now !== null && hv.was ? (hv.now - hv.was) / Math.abs(hv.was) : null;
  const good = change === null ? null
    : metric.lowerIsBetter ? change < 0 : change > 0;

  return (
    <div className="rounded-md border border-border-primary bg-bg-white p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-[13px] font-medium text-text-primary">
          Hour by hour against {baselineDay || "the previous day"}
        </h3>
        <label className="flex items-center gap-2 text-[11.5px] text-text-secondary">
          Metric
          <select
            value={metricKey}
            onChange={(e) => setMetricKey(e.target.value)}
            className="rounded border border-border-primary bg-bg-white px-2 py-1 text-[11.5px] text-text-primary"
          >
            {METRICS.map((m) => (
              <option key={m.key} value={m.key}>{m.label}</option>
            ))}
          </select>
        </label>
      </div>

      <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px] text-text-secondary">
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block size-2.5 rounded-sm" style={{ background: NOW_INK }} />
          this day
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block size-2.5 rounded-sm"
                style={{ background: theme.borderPrimary }} />
          {baselineDay || "previous day"}
        </span>
      </div>

      <div className="mt-2 overflow-x-auto">
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full min-w-[640px]"
             role="img" aria-labelledby={titleId}
             onPointerLeave={() => setHover(null)}>
          <title id={titleId}>
            {metric.label} for each hour, this day beside {baselineDay || "the previous day"}.
          </title>

          {[0, 0.5, 1].map((f) => (
            <g key={f}>
              <line x1={LEFT} x2={WIDTH - RIGHT} y1={y(max * f)} y2={y(max * f)}
                    stroke={theme.borderSoft} />
              <text x={LEFT - 8} y={y(max * f)} dominantBaseline="middle" textAnchor="end"
                    fontSize="10.5" fill={theme.textSecondary}>
                {metric.fmt(max * f)}
              </text>
            </g>
          ))}

          {hours.map((hr) => {
            const x0 = LEFT + hr * slot;
            const a = now.get(hr);
            const b = was.get(hr);
            const live = liveHour != null && hr === liveHour;
            return (
              <g key={hr} onPointerEnter={() => setHover(hr)}>
                {/* A full-height target: hovering a 2px bar at 4am is
                    not something anyone should have to aim for. */}
                <rect x={x0} y={TOP} width={slot} height={PLOT_H} fill="transparent" />
                {hover === hr && (
                  <rect x={x0} y={TOP} width={slot} height={PLOT_H} fill={theme.borderSoft}
                        opacity={0.5} />
                )}
                {b !== null && b !== undefined && Number.isFinite(b) && (
                  <rect x={x0 + 2} y={y(b)} width={barW} height={h(b)}
                        fill={theme.borderPrimary} />
                )}
                {a !== null && a !== undefined && Number.isFinite(a) && (
                  <rect x={x0 + 2 + barW} y={y(a)} width={barW} height={h(a)}
                        fill={NOW_INK} opacity={live ? 0.45 : 1} />
                )}
              </g>
            );
          })}

          {[0, 3, 6, 9, 12, 15, 18, 21].map((hr) => (
            <text key={hr} x={LEFT + hr * slot + slot / 2} y={HEIGHT - 26}
                  textAnchor="middle" fontSize="10.5" fill={theme.textSecondary}>
              {hourLabel(hr)}
            </text>
          ))}
        </svg>
      </div>

      <div className="mt-1 flex flex-wrap gap-x-5 gap-y-1 text-[11.5px]">
        {hv ? (
          <>
            <span className="font-medium text-text-primary">
              {String(hv.hour).padStart(2, "0")}:00
            </span>
            <span className="text-text-primary">{metric.fmt(hv.now)}</span>
            <span className="text-text-tertiary">
              {baselineDay || "prev"} {metric.fmt(hv.was)}
            </span>
            {liveHour != null && hv.hour === liveHour ? (
              <span className="text-text-tertiary">still filling — no comparison</span>
            ) : change !== null ? (
              <span className={good ? "text-success-text" : "text-warning-text"}>
                {change > 0 ? "↗ " : change < 0 ? "↘ " : ""}
                {Math.abs(change * 100).toFixed(0)}%
              </span>
            ) : (
              <span className="text-text-tertiary">—</span>
            )}
          </>
        ) : (
          <span className="text-text-tertiary">Hover an hour to compare it.</span>
        )}
      </div>
    </div>
  );
}
