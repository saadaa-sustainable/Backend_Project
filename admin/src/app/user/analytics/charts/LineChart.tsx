"use client";

import { useState } from "react";
import { CATEGORICAL_PALETTE, theme } from "@/lib/theme";

export interface LineSeries {
  name: string;
  values: (number | null)[];
}

interface Props {
  categories: string[];
  series: LineSeries[];
  height?: number;
  valueFormat?: (n: number) => string;
}

const MARGIN = { top: 16, right: 16, bottom: 36, left: 56 };

/** Line chart -- 2px stroke, rounded caps, crosshair + tooltip on hover
 * (single axis only, per the skill's "never dual-axis" rule -- multiple
 * series share one y scale). */
export function LineChart({ categories, series, height = 280, valueFormat }: Props) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const width = Math.max(480, categories.length * 24 + MARGIN.left + MARGIN.right);
  const plotW = width - MARGIN.left - MARGIN.right;
  const plotH = height - MARGIN.top - MARGIN.bottom;

  const allValues = series.flatMap((s) => s.values.filter((v): v is number => v !== null));
  const maxValue = Math.max(1, ...allValues, 0);
  const minValue = Math.min(0, ...allValues);
  const x = (i: number) => (categories.length <= 1 ? plotW / 2 : (i / (categories.length - 1)) * plotW);
  const y = (v: number) => plotH - ((v - minValue) / (maxValue - minValue || 1)) * plotH;
  const fmt = valueFormat ?? ((n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 1 }));

  const gridLines = 4;
  const gridValues = Array.from({ length: gridLines + 1 }, (_, i) => minValue + ((maxValue - minValue) / gridLines) * i);

  function pathFor(values: (number | null)[]): string {
    let d = "";
    let started = false;
    values.forEach((v, i) => {
      if (v === null) {
        started = false;
        return;
      }
      d += `${started ? "L" : "M"}${x(i)},${y(v)} `;
      started = true;
    });
    return d.trim();
  }

  // Show at most ~10 x-axis labels so long ranges don't overlap.
  const labelStride = Math.max(1, Math.ceil(categories.length / 10));

  return (
    <div className="overflow-x-auto">
      <svg width={width} height={height} role="img" aria-label="Line chart">
        <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
          {gridValues.map((v, i) => (
            <g key={i}>
              <line x1={0} x2={plotW} y1={y(v)} y2={y(v)} stroke={theme.borderPrimary} strokeWidth={1} />
              <text x={-8} y={y(v)} textAnchor="end" dominantBaseline="middle" fontSize={10} fill={theme.textTertiary}>
                {fmt(v)}
              </text>
            </g>
          ))}

          {categories.map(
            (cat, i) =>
              i % labelStride === 0 && (
                <text key={cat} x={x(i)} y={plotH + 16} textAnchor="middle" fontSize={10} fill={theme.textSecondary}>
                  {cat.length > 10 ? `${cat.slice(0, 9)}…` : cat}
                </text>
              ),
          )}

          {series.map((s, si) => (
            <path
              key={s.name}
              d={pathFor(s.values)}
              fill="none"
              stroke={CATEGORICAL_PALETTE[si % CATEGORICAL_PALETTE.length]}
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          ))}

          {hoverIdx !== null && (
            <line x1={x(hoverIdx)} x2={x(hoverIdx)} y1={0} y2={plotH} stroke={theme.textTertiary} strokeWidth={1} strokeDasharray="3,3" />
          )}
          {hoverIdx !== null &&
            series.map((s, si) => {
              const v = s.values[hoverIdx];
              if (v === null) return null;
              return (
                <circle
                  key={s.name}
                  cx={x(hoverIdx)}
                  cy={y(v)}
                  r={4}
                  fill={CATEGORICAL_PALETTE[si % CATEGORICAL_PALETTE.length]}
                  stroke={theme.bgWhite}
                  strokeWidth={2}
                />
              );
            })}

          {/* invisible hover targets */}
          {categories.map((_, i) => (
            <rect
              key={i}
              x={x(i) - plotW / Math.max(1, categories.length) / 2}
              y={0}
              width={plotW / Math.max(1, categories.length)}
              height={plotH}
              fill="transparent"
              onMouseEnter={() => setHoverIdx(i)}
              onMouseLeave={() => setHoverIdx(null)}
            />
          ))}
        </g>
      </svg>

      {hoverIdx !== null && (
        <div className="mt-1 flex flex-wrap gap-3 text-xs text-text-secondary">
          <span className="font-medium text-text-primary">{categories[hoverIdx]}</span>
          {series.map((s, i) => (
            <span key={s.name} className="flex items-center gap-1">
              <span className="inline-block h-2 w-2 rounded-full" style={{ background: CATEGORICAL_PALETTE[i % CATEGORICAL_PALETTE.length] }} />
              {s.name}: {s.values[hoverIdx] !== null ? fmt(s.values[hoverIdx] as number) : "—"}
            </span>
          ))}
        </div>
      )}

      {series.length > 1 && (
        <div className="mt-2 flex flex-wrap gap-3">
          {series.map((s, i) => (
            <span key={s.name} className="flex items-center gap-1.5 text-xs text-text-secondary">
              <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: CATEGORICAL_PALETTE[i % CATEGORICAL_PALETTE.length] }} />
              {s.name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
