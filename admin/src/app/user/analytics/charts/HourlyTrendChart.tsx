"use client";

import { useId, useState } from "react";
import type { HourlyRow } from "@/lib/api";
import { CATEGORICAL_PALETTE, theme } from "@/lib/theme";

/**
 * Today's hourly curve against the same hours yesterday.
 *
 * Three bands, because these are three different units and sharing an
 * axis would flatten two of them: sessions run in thousands, the two
 * per-session ratios in tens of rupees, AMER around 2. The point of
 * the chart is the SHAPE -- where today pulls away from yesterday --
 * so the baseline is drawn as a muted line under today's rather than
 * in a second colour competing with it.
 *
 * The x axis is hour 0..23 always, not the hours we happen to have, so
 * a part-finished day visibly stops rather than stretching to fill the
 * width and looking complete.
 */

const WIDTH = 1000;
const LEFT = 56;
const RIGHT = 20;
const PLOT = WIDTH - LEFT - RIGHT;

const BANDS = [
  { key: "sessions" as const, label: "Sessions", top: 24, height: 86, money: false },
  { key: "ratios" as const, label: "Cost and revenue / session · ₹", top: 148, height: 86, money: true },
  { key: "amer" as const, label: "AMER · new-customer revenue ÷ spend", top: 272, height: 70, money: false },
];
const HEIGHT = 380;

const COST = CATEGORICAL_PALETTE[0];
const REV = CATEGORICAL_PALETTE[1];
const SESS = CATEGORICAL_PALETTE[2];
const AMER = CATEGORICAL_PALETTE[3];

const money = (n: number) =>
  n.toLocaleString("en-IN", { style: "currency", currency: "INR",
    minimumFractionDigits: 0, maximumFractionDigits: 0 });

export function HourlyTrendChart({ rows, baseline, baselineDay }: {
  rows: HourlyRow[];
  baseline: HourlyRow[];
  baselineDay: string;
}) {
  const titleId = useId();
  const [hover, setHover] = useState<number | null>(null);

  const byHour = (rs: HourlyRow[]) => {
    const m = new Map<number, HourlyRow>();
    for (const r of rs) m.set(r.hour_of_day, r);
    return m;
  };
  const today = byHour(rows);
  const prev = byHour(baseline);
  if (!rows.length) return null;

  const all = [...rows, ...baseline];
  const maxSessions = Math.max(1, ...all.map((r) => r.sessions ?? 0)) * 1.1;
  const maxRatio = Math.max(1, ...all.flatMap((r) =>
    [r.cost_per_session ?? 0, r.revenue_per_session ?? 0])) * 1.1;
  const maxAmer = Math.max(0.5, ...all.map((r) => r.amer ?? 0)) * 1.15;

  const x = (hour: number) => LEFT + (hour / 23) * PLOT;
  const yIn = (band: typeof BANDS[number], value: number, max: number) =>
    band.top + band.height * (1 - value / max);

  function path(map: Map<number, HourlyRow>,
                pick: (r: HourlyRow) => number | null,
                band: typeof BANDS[number], max: number) {
    let started = false;
    const parts: string[] = [];
    for (let h = 0; h <= 23; h++) {
      const r = map.get(h);
      const v = r ? pick(r) : null;
      // A gap must break the line, not bridge it: an hour with no data
      // is not an hour of zero, and a straight segment across it would
      // claim a trend that was never measured.
      if (v === null || v === undefined) { started = false; continue; }
      parts.push(`${started ? "L" : "M"}${x(h)},${yIn(band, v, max)}`);
      started = true;
    }
    return parts.join(" ");
  }

  const series: {
    band: typeof BANDS[number]; max: number; color: string; name: string;
    pick: (r: HourlyRow) => number | null;
  }[] = [
    { band: BANDS[0], max: maxSessions, color: SESS, name: "Sessions", pick: (r) => r.sessions },
    { band: BANDS[1], max: maxRatio, color: COST, name: "Cost / session", pick: (r) => r.cost_per_session },
    { band: BANDS[1], max: maxRatio, color: REV, name: "Revenue / session", pick: (r) => r.revenue_per_session },
    { band: BANDS[2], max: maxAmer, color: AMER, name: "AMER", pick: (r) => r.amer },
  ];

  const hoverRow = hover === null ? null : today.get(hover);
  const hoverPrev = hover === null ? null : prev.get(hover);

  return (
    <div className="rounded-md border border-border-primary bg-bg-white p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-[13px] font-medium text-text-primary">Hour by hour</h3>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px] text-text-secondary">
          {series.map((s) => (
            <span key={s.name} className="inline-flex items-center gap-1.5">
              <svg width="18" height="8" aria-hidden="true">
                <line x1="0" y1="4" x2="18" y2="4" stroke={s.color} strokeWidth="2" />
              </svg>
              {s.name}
            </span>
          ))}
          <span className="inline-flex items-center gap-1.5">
            <svg width="18" height="8" aria-hidden="true">
              <line x1="0" y1="4" x2="18" y2="4" stroke={theme.textTertiary}
                    strokeWidth="2" strokeDasharray="3 3" />
            </svg>
            {baselineDay || "previous day"}
          </span>
        </div>
      </div>

      <div className="mt-2 overflow-x-auto">
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full min-w-[640px]"
             role="img" aria-labelledby={titleId}
             onPointerMove={(e) => {
               const box = e.currentTarget.getBoundingClientRect();
               const px = ((e.clientX - box.left) / box.width) * WIDTH;
               const h = Math.round(((px - LEFT) / PLOT) * 23);
               setHover(h >= 0 && h <= 23 ? h : null);
             }}
             onPointerLeave={() => setHover(null)}>
          <title id={titleId}>
            Sessions, cost and revenue per session, and AMER by hour, with the
            previous day drawn beneath as a dashed line.
          </title>

          {BANDS.map((b) => (
            <text key={b.key} x={LEFT} y={b.top - 8} fontSize="11" fill={theme.textSecondary}>
              {b.label}
            </text>
          ))}

          {/* Gridlines and the scale each band is on. */}
          {BANDS.map((b) => {
            const max = b.key === "sessions" ? maxSessions
              : b.key === "ratios" ? maxRatio : maxAmer;
            return [0, 0.5, 1].map((f) => {
              const v = max * f;
              return (
                <g key={`${b.key}-${f}`}>
                  <line x1={LEFT} x2={WIDTH - RIGHT} y1={yIn(b, v, max)} y2={yIn(b, v, max)}
                        stroke={theme.borderSoft} />
                  <text x={LEFT - 8} y={yIn(b, v, max)} dominantBaseline="middle"
                        textAnchor="end" fontSize="10.5" fill={theme.textSecondary}>
                    {b.money ? money(v) : b.key === "amer" ? v.toFixed(1)
                      : Math.round(v).toLocaleString("en-IN")}
                  </text>
                </g>
              );
            });
          })}

          {/* Yesterday first, so today draws over it. */}
          {series.map((s) => (
            <path key={`prev-${s.name}`} d={path(prev, s.pick, s.band, s.max)}
                  fill="none" stroke={theme.textTertiary} strokeWidth="1.5"
                  strokeDasharray="3 3" strokeLinejoin="round" opacity={0.75} />
          ))}
          {series.map((s) => (
            <path key={`now-${s.name}`} d={path(today, s.pick, s.band, s.max)}
                  fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round" />
          ))}

          {hover !== null && today.has(hover) && BANDS.map((b) => (
            <line key={b.key} x1={x(hover)} x2={x(hover)} y1={b.top} y2={b.top + b.height}
                  stroke={theme.textTertiary} strokeDasharray="2 2" />
          ))}

          {[0, 4, 8, 12, 16, 20, 23].map((h) => (
            <text key={h} x={x(h)} y={HEIGHT - 10}
                  textAnchor={h === 0 ? "start" : h === 23 ? "end" : "middle"}
                  fontSize="11" fill={theme.textSecondary}>
              {String(h).padStart(2, "0")}:00
            </text>
          ))}
        </svg>
      </div>

      <div className="mt-1 flex flex-wrap gap-x-5 gap-y-1 text-[11.5px] text-text-secondary">
        {hoverRow ? (
          <>
            <span className="font-medium text-text-primary">
              {String(hoverRow.hour_of_day).padStart(2, "0")}:00
            </span>
            <span>{(hoverRow.sessions ?? 0).toLocaleString("en-IN")} sessions</span>
            <span>cost {money(hoverRow.cost_per_session ?? 0)}</span>
            <span>rev {money(hoverRow.revenue_per_session ?? 0)}</span>
            <span>AMER {(hoverRow.amer ?? 0).toFixed(2)}x</span>
            {hoverPrev && (
              <span className="text-text-tertiary">
                yesterday {(hoverPrev.sessions ?? 0).toLocaleString("en-IN")} sessions ·
                cost {money(hoverPrev.cost_per_session ?? 0)} ·
                rev {money(hoverPrev.revenue_per_session ?? 0)}
              </span>
            )}
          </>
        ) : (
          <span className="text-text-tertiary">Hover an hour for its figures.</span>
        )}
      </div>
    </div>
  );
}
