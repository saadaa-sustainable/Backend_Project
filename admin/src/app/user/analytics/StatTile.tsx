"use client";

/**
 * The one tile used across Last Click UTM -- channel KPIs, cascade step
 * tiles, and the name-miss worklist's KPI cards.
 *
 * Extracted rather than copied. The channel tile and the step tile had
 * already drifted into two near-identical blocks of JSX, and adding a
 * third copy for the worklist would have guaranteed that "match the
 * stepwise styling" stopped being true the first time any one of them
 * was touched. One component, three callers, no drift.
 *
 * The accent is carried as a 3px rail on the top edge and, when a badge
 * is present, as that badge's text and 10%-alpha background -- so a tile
 * reads as coloured without nine tinted backgrounds fighting each other
 * for attention.
 *
 * Selection is a 1px ring rather than a thicker border, so selecting a
 * tile never reflows the ones beside it.
 */

import { theme } from "@/lib/theme";

export function StatTile({
  eyebrow,
  label,
  value,
  sub,
  badge,
  color,
  title,
  dim,
  selected,
  onClick,
}: {
  /** Small line above the label -- the step number, where there is one. */
  eyebrow?: string;
  label: string;
  value: string;
  /** ReactNode, not string: callers pass a coloured delta element here. */
  sub?: React.ReactNode;
  /** Top-right pill, e.g. a share percentage. */
  badge?: string;
  color: string;
  title?: string;
  /** Renders faded, for a branch that is real but currently empty. */
  dim?: boolean;
  selected?: boolean;
  onClick?: () => void;
}) {
  const Tag = onClick ? "button" : "div";
  return (
    <Tag
      onClick={onClick}
      title={title}
      className={
        "relative overflow-hidden rounded-lg border bg-white px-3 py-2.5 text-left shadow-sm " +
        (onClick ? "transition-shadow hover:shadow-md " : "") +
        (dim ? "opacity-55 " : "")
      }
      style={{
        borderColor: selected ? color : theme.borderPrimary,
        boxShadow: selected ? `0 0 0 1px ${color}` : undefined,
      }}
    >
      <span className="absolute inset-x-0 top-0 h-[3px]" style={{ backgroundColor: color }} />
      {eyebrow && (
        <div
          className="mt-0.5 text-[9px] font-semibold uppercase tracking-wider"
          style={{ color }}
        >
          {eyebrow}
        </div>
      )}
      <div className={"flex items-center justify-between gap-2" + (eyebrow ? "" : " mt-0.5")}>
        <span
          className="truncate text-[10px] font-semibold uppercase tracking-wider text-text-secondary"
          title={label}
        >
          {label}
        </span>
        {badge && (
          <span
            className="shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-semibold tabular-nums"
            // 8-digit hex: the accent at ~10% alpha.
            style={{ backgroundColor: `${color}1A`, color }}
          >
            {badge}
          </span>
        )}
      </div>
      <div className="mt-1 text-xl font-semibold tabular-nums leading-none">{value}</div>
      {sub && <div className="mt-1 text-[11px] tabular-nums text-text-tertiary">{sub}</div>}
    </Tag>
  );
}

export default StatTile;
