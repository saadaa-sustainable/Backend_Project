"use client";

import { useState } from "react";
import { theme } from "@/lib/theme";

export interface ScatterPoint {
  label: string;
  x: number;
  y: number;
}

interface Props {
  points: ScatterPoint[];
  curve: { x: number; y: number }[] | null;
  xLabel: string;
  yLabel: string;
  height?: number;
}

const MARGIN = { top: 16, right: 16, bottom: 40, left: 64 };

/** Scatter of raw (spend, conversions) points with a fitted power-law
 * curve overlaid -- the curve is server-computed (real log-log
 * regression), this just renders it. Points get the muted secondary
 * accent (identity doesn't matter here, the SHAPE of the cloud does);
 * the fit line uses the brand accent so it reads as "the answer" against
 * the scatter. */
export function SaturationCurveChart({ points, curve, xLabel, yLabel, height = 360 }: Props) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const width = 640;
  const plotW = width - MARGIN.left - MARGIN.right;
  const plotH = height - MARGIN.top - MARGIN.bottom;

  if (points.length === 0) {
    return <p className="text-sm text-text-secondary">No ads with both spend and {yLabel.toLowerCase()} for this selection.</p>;
  }

  const allX = [...points.map((p) => p.x), ...(curve?.map((c) => c.x) ?? [])];
  const allY = [...points.map((p) => p.y), ...(curve?.map((c) => c.y) ?? [])];
  const xMax = Math.max(...allX, 1);
  const yMax = Math.max(...allY, 1);

  const px = (v: number) => (v / xMax) * plotW;
  const py = (v: number) => plotH - (v / yMax) * plotH;

  const fmt = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 1 });

  const gridX = Array.from({ length: 5 }, (_, i) => (xMax / 4) * i);
  const gridY = Array.from({ length: 5 }, (_, i) => (yMax / 4) * i);

  const curvePath = curve && curve.length > 0
    ? curve.map((c, i) => `${i === 0 ? "M" : "L"}${px(c.x)},${py(c.y)}`).join(" ")
    : null;

  return (
    <div className="overflow-x-auto">
      <svg width={width} height={height} role="img" aria-label="Saturation curve">
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
            <circle
              key={i}
              cx={px(p.x)}
              cy={py(p.y)}
              r={hoverIdx === i ? 5 : 3.5}
              fill={theme.textTertiary}
              fillOpacity={hoverIdx === i ? 0.9 : 0.45}
              onMouseEnter={() => setHoverIdx(i)}
              onMouseLeave={() => setHoverIdx(null)}
            />
          ))}

          {curvePath && <path d={curvePath} fill="none" stroke={theme.accentYellow} strokeWidth={3} strokeLinecap="round" />}

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
          {yLabel}: {fmt(points[hoverIdx].y)}
        </div>
      )}
      <div className="mt-2 flex items-center gap-4 text-[11px] text-text-tertiary">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full" style={{ background: theme.textTertiary, opacity: 0.6 }} />
          Individual ads
        </span>
        {curvePath && (
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-0.5 w-4" style={{ background: theme.accentYellow }} />
            Fitted saturation curve
          </span>
        )}
      </div>
    </div>
  );
}
