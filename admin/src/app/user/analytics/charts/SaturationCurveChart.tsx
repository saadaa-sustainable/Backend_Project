"use client";

import { useMemo, useState } from "react";
import { theme } from "@/lib/theme";

export interface ScatterPoint {
  label: string;
  x: number;
  y: number;
  /** Optional caller-provided extra identifiers -- e.g. ad_id -- so a
   *  drilldown target can open the right detail view without needing
   *  another round-trip. */
  meta?: Record<string, unknown>;
}

interface Props {
  points: ScatterPoint[];
  curve: { x: number; y: number }[] | null;
  xLabel: string;
  yLabel: string;
  /** SVG intrinsic height in the viewBox. Actual rendered height scales
   *  with container width because we use aspect-ratio via viewBox. */
  height?: number;
  /** Fires when a point is clicked -- lets the parent open a drilldown
   *  panel / modal / filter with the ad's details. */
  onPointClick?: (point: ScatterPoint) => void;
  /** Highlights this point (e.g. currently-selected in a drilldown). */
  selectedLabel?: string | null;
}

const MARGIN = { top: 24, right: 32, bottom: 44, left: 72 };
// SVG's intrinsic viewBox size. The <svg> tag itself renders at
// width=100% so it scales to the container; viewBox keeps proportions.
const VB_WIDTH = 1200;

/** Scatter of raw (spend, conversions) points with a fitted power-law
 *  curve overlaid.
 *
 *  Auto-uses log scale on both axes when the data range spans 2+ orders
 *  of magnitude -- essential for ad-spend data because a few ads at
 *  ₹20L completely flatten every other ad against the y-axis if the
 *  axis is linear (which is exactly what the earlier version did). Log
 *  spreads the cloud out so every ad is visible.
 *
 *  Points are click-target-sized (r=6) so drilldown click targets are
 *  reachable, and onPointClick lets the parent open whatever detail
 *  view it wants (modal / drawer / filter). Selected point pulses so
 *  the drilldown stays visually anchored to the point. */
export function SaturationCurveChart({
  points,
  curve,
  xLabel,
  yLabel,
  height = 480,
  onPointClick,
  selectedLabel,
}: Props) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const [logX, setLogX] = useState(true);
  const [logY, setLogY] = useState(true);

  const plotW = VB_WIDTH - MARGIN.left - MARGIN.right;
  const plotH = height - MARGIN.top - MARGIN.bottom;

  if (points.length === 0) {
    return <p className="text-sm text-text-secondary">No ads with both spend and {yLabel.toLowerCase()} for this selection.</p>;
  }

  // Positive-only when log-scaling (log(0) is undefined). Drop zeros
  // silently -- they'd distort the scale anyway.
  const posPoints = useMemo(
    () => (logX || logY ? points.filter((p) => p.x > 0 && p.y > 0) : points),
    [points, logX, logY],
  );
  const visiblePoints = posPoints.length > 0 ? posPoints : points;

  const allX = [...visiblePoints.map((p) => p.x), ...(curve?.map((c) => c.x) ?? [])];
  const allY = [...visiblePoints.map((p) => p.y), ...(curve?.map((c) => c.y) ?? [])];
  const xMin = Math.max(1, Math.min(...allX));
  const xMax = Math.max(...allX, xMin * 10);
  const yMin = Math.max(1, Math.min(...allY));
  const yMax = Math.max(...allY, yMin * 10);

  const px = (v: number) => {
    if (logX) {
      const lo = Math.log10(xMin);
      const hi = Math.log10(xMax);
      return ((Math.log10(Math.max(v, xMin)) - lo) / (hi - lo || 1)) * plotW;
    }
    return (v / xMax) * plotW;
  };
  const py = (v: number) => {
    if (logY) {
      const lo = Math.log10(yMin);
      const hi = Math.log10(yMax);
      return plotH - ((Math.log10(Math.max(v, yMin)) - lo) / (hi - lo || 1)) * plotH;
    }
    return plotH - (v / yMax) * plotH;
  };

  // Compact humanized formatter -- 1.2k / 3.4L / 12.5Cr / etc. for the
  // Indian-crore audience this app is built for.
  const fmt = (n: number) => {
    const abs = Math.abs(n);
    if (abs >= 1e7) return `${(n / 1e7).toFixed(1)}Cr`;
    if (abs >= 1e5) return `${(n / 1e5).toFixed(1)}L`;
    if (abs >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
    return n.toFixed(0);
  };

  // Ticks: log gives 10^n at each power in the range; linear gives 5
  // evenly-spaced ticks.
  const gridX: number[] = logX
    ? Array.from(
        { length: Math.ceil(Math.log10(xMax)) - Math.floor(Math.log10(xMin)) + 1 },
        (_, i) => Math.pow(10, Math.floor(Math.log10(xMin)) + i),
      )
    : Array.from({ length: 5 }, (_, i) => (xMax / 4) * i);
  const gridY: number[] = logY
    ? Array.from(
        { length: Math.ceil(Math.log10(yMax)) - Math.floor(Math.log10(yMin)) + 1 },
        (_, i) => Math.pow(10, Math.floor(Math.log10(yMin)) + i),
      )
    : Array.from({ length: 5 }, (_, i) => (yMax / 4) * i);

  const curvePath = curve && curve.length > 0
    ? curve
        .filter((c) => c.x > 0 && c.y > 0)
        .map((c, i) => `${i === 0 ? "M" : "L"}${px(c.x)},${py(c.y)}`)
        .join(" ")
    : null;

  return (
    <div className="w-full">
      {/* Compact controls above the chart. Log scale defaults to on
          because ad-spend data spans multiple orders of magnitude and
          linear scale wastes 80% of the plot area on empty white space. */}
      <div className="mb-2 flex flex-wrap items-center gap-3 text-[11px]">
        <label className="flex items-center gap-1 text-text-secondary">
          <input
            type="checkbox"
            checked={logX}
            onChange={(e) => setLogX(e.target.checked)}
            className="h-3 w-3"
          />
          Log X ({xLabel.toLowerCase()})
        </label>
        <label className="flex items-center gap-1 text-text-secondary">
          <input
            type="checkbox"
            checked={logY}
            onChange={(e) => setLogY(e.target.checked)}
            className="h-3 w-3"
          />
          Log Y ({yLabel.toLowerCase()})
        </label>
        <span className="text-text-tertiary">
          {visiblePoints.length.toLocaleString()} points
          {posPoints.length < points.length && (
            <span className="ml-1 text-warning-text">
              (dropped {points.length - posPoints.length} zeros)
            </span>
          )}
        </span>
        {onPointClick && (
          <span className="ml-auto text-text-tertiary">Click a dot to drill in</span>
        )}
      </div>

      <svg
        viewBox={`0 0 ${VB_WIDTH} ${height}`}
        width="100%"
        preserveAspectRatio="none"
        role="img"
        aria-label="Saturation curve"
        className="block"
        style={{ maxHeight: height * 1.5 }}
      >
        <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
          {gridY.map((v, i) => (
            <g key={`y${i}`}>
              <line
                x1={0}
                x2={plotW}
                y1={py(v)}
                y2={py(v)}
                stroke={theme.borderPrimary}
                strokeWidth={1}
                strokeDasharray="2,4"
              />
              <text x={-10} y={py(v)} textAnchor="end" dominantBaseline="middle" fontSize={11} fill={theme.textTertiary}>
                {fmt(v)}
              </text>
            </g>
          ))}
          {gridX.map((v, i) => (
            <g key={`x${i}`}>
              <line
                x1={px(v)}
                x2={px(v)}
                y1={0}
                y2={plotH}
                stroke={theme.borderPrimary}
                strokeWidth={1}
                strokeDasharray="2,4"
              />
              <text x={px(v)} y={plotH + 18} textAnchor="middle" fontSize={11} fill={theme.textTertiary}>
                {fmt(v)}
              </text>
            </g>
          ))}

          {/* Curve first so points draw on top and are click-targets. */}
          {curvePath && (
            <path
              d={curvePath}
              fill="none"
              stroke={theme.accentYellow}
              strokeWidth={3}
              strokeLinecap="round"
              opacity={0.85}
            />
          )}

          {visiblePoints.map((p, i) => {
            const selected = selectedLabel === p.label;
            const hovered = hoverIdx === i;
            const r = selected ? 8 : hovered ? 7 : 5;
            return (
              <circle
                key={i}
                cx={px(p.x)}
                cy={py(p.y)}
                r={r}
                fill={selected ? theme.accentYellow : theme.textSecondary}
                fillOpacity={selected ? 0.95 : hovered ? 0.85 : 0.55}
                stroke={selected ? theme.accentYellow : "transparent"}
                strokeWidth={selected ? 2 : 0}
                onMouseEnter={() => setHoverIdx(i)}
                onMouseLeave={() => setHoverIdx(null)}
                onClick={onPointClick ? () => onPointClick(p) : undefined}
                style={{
                  cursor: onPointClick ? "pointer" : "default",
                  transition: "r 120ms ease",
                }}
              />
            );
          })}

          <text x={plotW / 2} y={plotH + 40} textAnchor="middle" fontSize={12} fill={theme.textSecondary}>
            {xLabel}{logX ? " (log scale)" : ""}
          </text>
          <text x={-52} y={-8} fontSize={12} fill={theme.textSecondary}>
            {yLabel}{logY ? " (log)" : ""}
          </text>
        </g>
      </svg>

      {hoverIdx !== null && visiblePoints[hoverIdx] && (
        <div className="mt-1 text-xs text-text-secondary">
          <span className="font-medium text-text-primary">{visiblePoints[hoverIdx].label}</span> · {xLabel}: {fmt(visiblePoints[hoverIdx].x)} ·{" "}
          {yLabel}: {fmt(visiblePoints[hoverIdx].y)}
        </div>
      )}
      <div className="mt-2 flex items-center gap-4 text-[11px] text-text-tertiary">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full" style={{ background: theme.textSecondary, opacity: 0.6 }} />
          Individual ads
        </span>
        {curvePath && (
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-0.5 w-4" style={{ background: theme.accentYellow }} />
            Fitted saturation curve
          </span>
        )}
        {selectedLabel && (
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-full ring-2" style={{ background: theme.accentYellow, boxShadow: `0 0 0 2px ${theme.accentYellow}33` }} />
            Selected
          </span>
        )}
      </div>
    </div>
  );
}
