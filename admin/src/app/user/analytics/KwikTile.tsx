"use client";

/**
 * KwikTile — kwikengage-style KPI card. Refactored 2026-08-31 to match
 * the Marketing Insights KPI-card screenshot exactly:
 *
 *   [colored icon square]              [ⓘ]
 *   Total Orders                          <- small gray uppercase label
 *   1,022                                 <- big bold value (mono, ~24px)
 *   [Great Rally +130 (0.86%)]            <- pale-green delta pill
 *   subLine (small gray, optional)
 *
 * The icon square is now a bright saturated color with a white glyph
 * (vs. the earlier pale bg + dark text) so tiles pop against the gray
 * canvas the way kwikengage's do. Delta is rendered as a pill (not text
 * with arrow) to mirror the "Great Rally +130 (0.86%)" chip on their
 * cards.
 *
 * Backward compatible with the pre-refactor API: existing callers pass
 * icon/iconColor/label/value/subLine/pillLabel/onClick/active and get
 * the new visual style automatically.
 */

import { ReactNode } from "react";

export interface KwikTileProps {
  icon?: ReactNode;
  iconColor?: "slate" | "sky" | "emerald" | "amber" | "rose" | "purple" | "teal";
  label: string;
  value: string;
  /** Optional small extra pill next to the value ("Smart Retry",
   *  "Active"). Rare — most KwikEngage tiles just have the delta chip. */
  pillLabel?: string;
  pillTone?: "success" | "warning" | "info" | "neutral";
  /** Delta chip below the value. `label` is the descriptive prefix
   *  (kwikengage uses "Great Rally", "Solid Growth", etc.); `text` is
   *  the numeric delta ("+130 (0.86%)"). Green chip for up, red for
   *  down, neutral for flat. */
  delta?: { direction: "up" | "down" | "flat"; label?: string; text: string };
  /** Second small line under everything (e.g. "in Last 30 Days"). */
  subLine?: ReactNode;
  /** Info tooltip shown on the (i) icon top-right. */
  info?: string;
  /** When set, the whole tile becomes a filter button (CTD's tile-click
   *  behaviour). */
  onClick?: () => void;
  active?: boolean;
}

/** Icon squares: bright saturated bg + white glyph, ~36px. Matches
 *  kwikengage's colored circles which are the visual anchor of each
 *  KPI card. */
const ICON_BG: Record<NonNullable<KwikTileProps["iconColor"]>, string> = {
  slate: "bg-slate-700 text-white",
  sky: "bg-[#3B6BF5] text-white",
  emerald: "bg-[#2E7D32] text-white",
  amber: "bg-[#D97706] text-white",
  rose: "bg-[#DC2626] text-white",
  purple: "bg-[#7C3AED] text-white",
  teal: "bg-[#0891B2] text-white",
};

const PILL_TONE: Record<NonNullable<KwikTileProps["pillTone"]>, string> = {
  success: "bg-success-bg text-success-text",
  warning: "bg-warning-bg text-warning-text",
  info: "bg-info-bg text-info-text",
  neutral: "bg-bg-muted text-text-secondary",
};

/** Delta chip: pale bg + dark text pattern, matches kwikengage's
 *  "Great Rally +130 (0.86%)" chip on Total Orders card. */
const DELTA_TONE: Record<"up" | "down" | "flat", string> = {
  up: "bg-success-bg text-success-text",
  down: "bg-error-bg text-error-text",
  flat: "bg-bg-muted text-text-secondary",
};

export function KwikTile({
  icon,
  iconColor = "slate",
  label,
  value,
  pillLabel,
  pillTone = "success",
  delta,
  subLine,
  info,
  onClick,
  active = false,
}: KwikTileProps) {
  const wrapperCls =
    "group flex flex-col gap-2 rounded-lg border p-4 transition-all " +
    (active
      ? "border-slate-900 bg-slate-50 shadow-sm"
      : "border-border-primary bg-white hover:border-border-mid hover:shadow-sm");

  const inner = (
    <>
      {/* Row 1: icon top-left, ⓘ top-right */}
      <div className="flex items-start justify-between">
        {icon ? (
          <div
            className={`flex h-9 w-9 items-center justify-center rounded-lg text-[16px] ${ICON_BG[iconColor]}`}
          >
            {icon}
          </div>
        ) : (
          <div />
        )}
        {info && (
          <span
            title={info}
            className="flex h-4 w-4 cursor-help items-center justify-center rounded-full border border-border-primary text-[9px] font-semibold text-text-tertiary"
          >
            i
          </span>
        )}
      </div>

      {/* Row 2: small gray label */}
      <div className="text-[12px] font-medium text-text-secondary">{label}</div>

      {/* Row 3: big value + optional pillLabel */}
      <div className="flex items-baseline gap-2">
        <div className="font-mono text-[22px] font-bold leading-tight text-text-primary">
          {value}
        </div>
        {pillLabel && (
          <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${PILL_TONE[pillTone]}`}>
            {pillLabel}
          </span>
        )}
      </div>

      {/* Row 4: delta chip (kwikengage's "Great Rally +130 (0.86%)") */}
      {delta && (
        <span
          className={`inline-flex w-fit items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${DELTA_TONE[delta.direction]}`}
        >
          {delta.label && <span className="font-semibold">{delta.label}</span>}
          <span className="font-mono">
            {delta.direction === "up" ? "▲" : delta.direction === "down" ? "▼" : "—"} {delta.text}
          </span>
        </span>
      )}

      {/* Row 5: subLine (tertiary hint text) */}
      {subLine && <div className="text-[11px] text-text-tertiary">{subLine}</div>}
    </>
  );

  if (onClick) {
    return (
      <button type="button" onClick={onClick} className={wrapperCls + " text-left"}>
        {inner}
      </button>
    );
  }
  return <div className={wrapperCls}>{inner}</div>;
}
