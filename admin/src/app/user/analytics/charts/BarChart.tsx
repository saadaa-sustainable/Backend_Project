"use client";

import { useState } from "react";
import { CATEGORICAL_PALETTE, theme } from "@/lib/theme";

export interface BarSeries {
  name: string;
  values: number[];
}

interface Props {
  categories: string[];
  series: BarSeries[];
  height?: number;
  valueFormat?: (n: number) => string;
}

const MARGIN = { top: 16, right: 16, bottom: 36, left: 56 };

/** Grouped bar chart -- thin bars, 4px rounded tops, 2px gaps, recessive
 * grid, per-mark hover tooltip. Categorical color assigned in FIXED order
 * from the validated palette (never cycled/reassigned per filter). */
export function BarChart({ categories, series, height = 280, valueFormat }: Props) {
  const [hover, setHover] = useState<{ cat: number; s: number } | null>(null);
  const width = Math.max(480, categories.length * Math.max(48, series.length * 22) + MARGIN.left + MARGIN.right);
  const plotW = width - MARGIN.left - MARGIN.right;
  const plotH = height - MARGIN.top - MARGIN.bottom;

  const maxValue = Math.max(1, ...series.flatMap((s) => s.values));
  const y = (v: number) => plotH - (v / maxValue) * plotH;
  const fmt = valueFormat ?? ((n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 1 }));

  const groupWidth = plotW / Math.max(1, categories.length);
  const barGap = 2;
  const barWidth = Math.max(4, (groupWidth - barGap * (series.length + 1)) / series.length);

  const gridLines = 4;
  const gridValues = Array.from({ length: gridLines + 1 }, (_, i) => (maxValue / gridLines) * i);

  return (
    <div className="overflow-x-auto">
      <svg width={width} height={height} role="img" aria-label="Bar chart">
        <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
          {/* recessive grid */}
          {gridValues.map((v, i) => (
            <g key={i}>
              <line x1={0} x2={plotW} y1={y(v)} y2={y(v)} stroke={theme.borderPrimary} strokeWidth={1} />
              <text x={-8} y={y(v)} textAnchor="end" dominantBaseline="middle" fontSize={10} fill={theme.textTertiary}>
                {fmt(v)}
              </text>
            </g>
          ))}

          {categories.map((cat, ci) => (
            <g key={cat} transform={`translate(${ci * groupWidth},0)`}>
              {series.map((s, si) => {
                const val = s.values[ci] ?? 0;
                const barH = plotH - y(val);
                const isHover = hover?.cat === ci && hover?.s === si;
                return (
                  <rect
                    key={s.name}
                    x={barGap + si * (barWidth + barGap)}
                    y={y(val)}
                    width={barWidth}
                    height={Math.max(0, barH)}
                    rx={4}
                    fill={CATEGORICAL_PALETTE[si % CATEGORICAL_PALETTE.length]}
                    opacity={isHover ? 1 : 0.88}
                    onMouseEnter={() => setHover({ cat: ci, s: si })}
                    onMouseLeave={() => setHover(null)}
                  />
                );
              })}
              <text
                x={groupWidth / 2}
                y={plotH + 16}
                textAnchor="middle"
                fontSize={10}
                fill={theme.textSecondary}
              >
                {cat.length > 14 ? `${cat.slice(0, 13)}…` : cat}
              </text>
            </g>
          ))}
        </g>
      </svg>

      {hover && (
        <div className="mt-1 text-xs text-text-secondary">
          <span className="font-medium text-text-primary">{categories[hover.cat]}</span>
          {series.length > 1 && <> · {series[hover.s].name}</>}: {fmt(series[hover.s].values[hover.cat] ?? 0)}
        </div>
      )}

      {series.length > 1 && (
        <div className="mt-2 flex flex-wrap gap-3">
          {series.map((s, i) => (
            <span key={s.name} className="flex items-center gap-1.5 text-xs text-text-secondary">
              <span
                className="inline-block h-2.5 w-2.5 rounded-full"
                style={{ background: CATEGORICAL_PALETTE[i % CATEGORICAL_PALETTE.length] }}
              />
              {s.name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
