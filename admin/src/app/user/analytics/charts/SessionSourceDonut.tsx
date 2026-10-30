"use client";

import { useId, useState } from "react";
import type { SourceSlice } from "@/lib/api";
import { CATEGORICAL_PALETTE, theme } from "@/lib/theme";

/**
 * The day's sessions split by raw utm_source.
 *
 * The table's sessions_meta / sessions_google / direct columns are
 * BUCKETS -- a classifier folds forty-odd tags into four numbers. This
 * is the same sessions, unfolded, which is the only place you can see
 * that (say) `facebook` is being tagged separately from `meta`, or that
 * a channel nobody is watching has started sending traffic.
 *
 * Six slices, never more: the server ranks the sources and folds the
 * tail into one "other" entry, so the fixed categorical palette is
 * never asked for a seventh hue. The legend carries the numbers; the
 * ring only carries the proportion, which is all a ring can carry
 * honestly.
 */

const SIZE = 196;
const R_OUT = 92;
const R_IN = 58;
const C = SIZE / 2;

const pct = (f: number) => `${(f * 100).toFixed(1)}%`;
const count = (n: number) => n.toLocaleString("en-IN");

/** One slice as a filled annulus wedge. */
function wedge(from: number, to: number, rOut: number, rIn: number): string {
  // A single slice at 100% would make start and end the same point and
  // the arc would collapse to nothing, so it is drawn as two halves.
  if (to - from >= 0.9999) {
    return [wedge(0, 0.5, rOut, rIn), wedge(0.5, 1, rOut, rIn)].join(" ");
  }
  const a = (f: number) => (f * 2 - 0.5) * Math.PI; // 0 = 12 o'clock
  const [a0, a1] = [a(from), a(to)];
  const p = (ang: number, r: number) =>
    `${C + r * Math.cos(ang)},${C + r * Math.sin(ang)}`;
  const big = to - from > 0.5 ? 1 : 0;
  return [
    `M${p(a0, rOut)}`,
    `A${rOut},${rOut} 0 ${big} 1 ${p(a1, rOut)}`,
    `L${p(a1, rIn)}`,
    `A${rIn},${rIn} 0 ${big} 0 ${p(a0, rIn)}`,
    "Z",
  ].join(" ");
}

export function SessionSourceDonut({ sources }: { sources: SourceSlice[] }) {
  const titleId = useId();
  const [hover, setHover] = useState<string | null>(null);

  if (!sources.length) return null;

  const total = sources.reduce((a, s) => a + s.sessions, 0);
  // Prefix sum rather than a running variable: the lint rule is right
  // that a closure mutating an outer binding during render is a trap.
  const slices = sources.map((s, i) => {
    const from = sources.slice(0, i).reduce((a, p) => a + p.share, 0);
    return {
      ...s,
      from,
      to: from + s.share,
      // "other" always takes the last ink so a source does not change
      // colour when the day's ranking shifts under it.
      color: s.source === "other"
        ? CATEGORICAL_PALETTE[CATEGORICAL_PALETTE.length - 1]
        : CATEGORICAL_PALETTE[i % CATEGORICAL_PALETTE.length],
    };
  });

  const active = slices.find((s) => s.source === hover) ?? null;

  return (
    <div className="rounded-md border border-border-primary bg-bg-white p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-[13px] font-medium text-text-primary">
          Sessions by utm_source
        </h3>
        <span className="text-[11.5px] text-text-tertiary">
          {count(total)} sessions today
        </span>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-4">
        <svg
          width={SIZE}
          height={SIZE}
          viewBox={`0 0 ${SIZE} ${SIZE}`}
          role="img"
          aria-labelledby={titleId}
          className="shrink-0"
        >
          <title id={titleId}>
            {`Today's ${count(total)} sessions by utm_source: ` +
              slices.map((s) => `${s.source} ${pct(s.share)}`).join(", ")}
          </title>
          {slices.map((s) => {
            const on = active === null || active.source === s.source;
            return (
              <path
                key={s.source}
                d={wedge(s.from, s.to, R_OUT, R_IN)}
                fill={s.color}
                opacity={on ? 1 : 0.28}
                stroke={theme.bgWhite}
                strokeWidth="1.5"
                onPointerEnter={() => setHover(s.source)}
                onPointerLeave={() => setHover(null)}
              />
            );
          })}
          <text
            x={C}
            y={C - 6}
            textAnchor="middle"
            fontSize="18"
            fontWeight="600"
            fill={theme.textPrimary}
          >
            {active ? pct(active.share) : count(total)}
          </text>
          <text
            x={C}
            y={C + 14}
            textAnchor="middle"
            fontSize="10.5"
            fill={theme.textSecondary}
          >
            {active ? active.source : "sessions"}
          </text>
        </svg>

        <ul className="min-w-[200px] flex-1 space-y-1">
          {slices.map((s) => (
            <li
              key={s.source}
              className="flex items-baseline gap-2 text-[11.5px]"
              onPointerEnter={() => setHover(s.source)}
              onPointerLeave={() => setHover(null)}
            >
              <span
                aria-hidden="true"
                className="mt-[3px] size-2.5 shrink-0 rounded-sm"
                style={{
                  background: s.color,
                  opacity: active === null || active.source === s.source ? 1 : 0.28,
                }}
              />
              <span className="flex-1 truncate text-text-primary">{s.source}</span>
              <span className="tabular-nums text-text-secondary">{count(s.sessions)}</span>
              <span className="w-12 text-right tabular-nums text-text-tertiary">
                {pct(s.share)}
              </span>
            </li>
          ))}
        </ul>
      </div>

      <p className="mt-3 text-[11px] leading-snug text-text-tertiary">
        Raw tags, case-folded. The Meta and Google session columns in the table
        are buckets built from these by a classifier, so a source here can land
        in a bucket whose name it does not share — <code>facebook</code> counts
        as Meta. Sources past the top five are summed into <em>other</em>.
      </p>
    </div>
  );
}
