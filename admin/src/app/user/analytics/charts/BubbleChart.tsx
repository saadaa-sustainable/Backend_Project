"use client";

import { useState } from "react";
import { CATEGORICAL_PALETTE, theme } from "@/lib/theme";

export interface BubblePoint {
  label: string;
  x: number;
  y: number;
  size: number;
}

interface Props {
  points: BubblePoint[];
  xLabel: string;
  yLabel: string;
  sizeLabel: string;
  height?: number;
  valueFormat?: (n: number) => string;
}

const MARGIN = { top: 16, right: 16, bottom: 40, left: 64 };

/** Bubble chart -- x/y metrics + a 3rd metric encoded as radius. Radius
 * scaled by SQRT of value (area-proportional, not radius-proportional --
 * a linear radius scale visually overstates large values). Direct labels
 * only on the largest few points to avoid clutter; hover shows the rest. */
export function BubbleChart({ points, xLabel, yLabel, sizeLabel, height = 360, valueFormat }: Props) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const width = 640;
  const plotW = width - MARGIN.left - MARGIN.right;
  const plotH = height - MARGIN.top - MARGIN.bottom;
  const fmt = valueFormat ?? ((n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 1 }));

  if (points.length === 0) {
    return <p className="text-sm text-text-secondary">No points to plot.</p>;
  }

  const xMax = Math.max(...points.map((p) => p.x), 1);
  const xMin = Math.min(0, ...points.map((p) => p.x));
  const yMax = Math.max(...points.map((p) => p.y), 1);
  const yMin = Math.min(0, ...points.map((p) => p.y));
  const sizeMax = Math.max(...points.map((p) => p.size), 1);

  const px = (v: number) => ((v - xMin) / (xMax - xMin || 1)) * plotW;
  const py = (v: number) => plotH - ((v - yMin) / (yMax - yMin || 1)) * plotH;
  const radius = (v: number) => 4 + Math.sqrt(Math.max(0, v) / sizeMax) * 22;

  const topLabeled = new Set(
    [...points]
      .sort((a, b) => b.size - a.size)
      .slice(0, 5)
      .map((p) => p.label),
  );

  const gridX = Array.from({ length: 5 }, (_, i) => xMin + ((xMax - xMin) / 4) * i);
  const gridY = Array.from({ length: 5 }, (_, i) => yMin + ((yMax - yMin) / 4) * i);

  return (
    <div className="overflow-x-auto">
      <svg width={width} height={height} role="img" aria-label="Bubble chart">
        <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
          {gridY.map((v, i) => (
            <g key={`y${i}`}>
              <line x1={0} x2={plotW} y1={py(v)} y2={py(v)} stroke={theme.borderPrimary} strokeWidth={1} />
              <text x={-8} y={py(v)} textAnchor="end" dominantBaseline="middle" fontSize={10} fill={theme.textTertiary}>
                {fmt(v)}
              </text>
            </g>
          ))}
          {gridX.map((v, i) => (
            <g key={`x${i}`}>
              <line x1={px(v)} x2={px(v)} y1={0} y2={plotH} stroke={theme.borderPrimary} strokeWidth={1} />
              <text x={px(v)} y={plotH + 16} textAnchor="middle" fontSize={10} fill={theme.textTertiary}>
                {fmt(v)}
              </text>
            </g>
          ))}

          {points.map((p, i) => (
            <g key={p.label}>
              <circle
                cx={px(p.x)}
                cy={py(p.y)}
                r={radius(p.size)}
                fill={CATEGORICAL_PALETTE[i % CATEGORICAL_PALETTE.length]}
                fillOpacity={hoverIdx === i ? 0.85 : 0.55}
                stroke={theme.bgWhite}
                strokeWidth={2}
                onMouseEnter={() => setHoverIdx(i)}
                onMouseLeave={() => setHoverIdx(null)}
              />
              {(topLabeled.has(p.label) || hoverIdx === i) && (
                <text
                  x={px(p.x)}
                  y={py(p.y) - radius(p.size) - 4}
                  textAnchor="middle"
                  fontSize={10}
                  fill={theme.textPrimary}
                >
                  {p.label.length > 16 ? `${p.label.slice(0, 15)}…` : p.label}
                </text>
              )}
            </g>
          ))}

          <text x={plotW / 2} y={plotH + 32} textAnchor="middle" fontSize={11} fill={theme.textSecondary}>
            {xLabel}
          </text>
          <text x={-48} y={-4} fontSize={11} fill={theme.textSecondary}>
            {yLabel}
          </text>
        </g>
      </svg>

      {hoverIdx !== null && (
        <div className="mt-1 text-xs text-text-secondary">
          <span className="font-medium text-text-primary">{points[hoverIdx].label}</span> · {xLabel}: {fmt(points[hoverIdx].x)} ·{" "}
          {yLabel}: {fmt(points[hoverIdx].y)} · {sizeLabel}: {fmt(points[hoverIdx].size)}
        </div>
      )}
      <p className="mt-1 text-[11px] text-text-tertiary">Bubble size = {sizeLabel} (area-proportional).</p>
    </div>
  );
}
