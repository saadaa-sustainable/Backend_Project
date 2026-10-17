"use client";

import { useId } from "react";
import { theme } from "@/lib/theme";
import { buildContribution, type ContributionDatum } from "./contribution";

/**
 * What moved, and by how much, in the unit the metric is measured in.
 *
 * NOT percent change. Percent is what the table column gives, and on a
 * catalogue with a long tail it is unplottable: measured on this data,
 * /collections/new-color-launch moved from 1 session to 1,113, which is
 * +111,200% and would squash every real movement on a shared axis into
 * the width of a hairline. The same page in sessions gained is +1,112 --
 * large, legible, and on the same scale as everything else.
 *
 * The bars carry a second property worth more than their ranking: they
 * SUM to the headline change. Whatever the total did, this chart names
 * the rows that did it, and the remainder is drawn rather than dropped.
 */

export type { ContributionDatum };

const ROW_H = 22;
const TOP = 26;
//: The widest label actually present decides the gutter. A fixed one
//: left 200px blank beside four-character SKU codes and still clipped
//: long landing-page paths.
const LABEL_MIN = 70;
const LABEL_MAX = 230;
const CHAR_W = 6.1;
const VALUE_W = 86;
const WIDTH = 1000;


export function ContributionChart({
  data,
  format,
  metricLabel,
  anchorLabel,
  baselineLabel,
  /** A rate does not add up: a page's percentage-point move says nothing
   *  about how much of the total's move it caused, because the total is
   *  weighted by volume. The caption says so and the remainder bar is
   *  suppressed -- drawing one would assert an arithmetic that is false. */
  additive = true,
  maxRows = 12,
}: {
  data: ContributionDatum[];
  format: (n: number) => string;
  metricLabel: string;
  anchorLabel: string;
  baselineLabel: string;
  additive?: boolean;
  maxRows?: number;
}) {
  const titleId = useId();

  const { bars: rows, total } = buildContribution(data, { maxRows, additive });

  const trim = (k: string) => (k.length > 36 ? `…${k.slice(-35)}` : k);
  const labelW = Math.min(LABEL_MAX, Math.max(LABEL_MIN,
    ...rows.map((r) => trim(r.key).length * CHAR_W)));
  const axisX = labelW + 14;
  const plotW = WIDTH - axisX - VALUE_W - 12;

  // The zero rule sits where the data puts it, not down the middle.
  // A symmetric split wasted half the plot whenever a day moved mostly
  // one way -- which is most days -- and shrank every bar to half the
  // width it could have had. Each side now gets width in proportion to
  // how far it actually reaches, with a floor so an all-positive day
  // still shows its axis rather than pinning it to the frame edge.
  const upMax = Math.max(0, ...rows.map((r) => r.change));
  const downMax = Math.max(0, ...rows.map((r) => -r.change));
  const span = upMax + downMax || 1;
  const downW = Math.min(Math.max((downMax / span) * plotW, downMax > 0 ? 40 : 0),
                         plotW - (upMax > 0 ? 40 : 0));
  const upW = plotW - downW;
  const zeroX = axisX + downW;
  const scale = (v: number) =>
    v >= 0 ? (upMax ? (v / upMax) * upW : 0) : (downMax ? (v / downMax) * downW : 0);
  const height = TOP + rows.length * ROW_H + 20;

  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${WIDTH} ${height}`} className="w-full min-w-[640px]"
        role="img" aria-labelledby={titleId}>
        <title id={titleId}>
          {metricLabel} gained or lost per row between {baselineLabel} and {anchorLabel},
          biggest movements first.
        </title>

        {/* No caption here: the section states the metric and both days
            on the rule directly above this chart, and saying it twice
            cost a line of height for nothing. */}
        <text x={WIDTH} y={12} fontSize="11" textAnchor="end" fill={theme.textSecondary}>
          {additive
            ? `net ${total > 0 ? "+" : ""}${format(total)}`
            : "percentage points · does not sum"}
        </text>

        {/* The zero rule is the chart. Everything is read as distance
            from it, so it is drawn darker than the row separators. */}
        <line x1={zeroX} x2={zeroX} y1={TOP - 8} y2={TOP + rows.length * ROW_H + 2}
          stroke={theme.borderPrimary} />

        {rows.map((row, i) => {
          const y = TOP + i * ROW_H;
          const mid = y + ROW_H / 2 - 1;
          const w = Math.abs(scale(row.change));
          const up = row.change > 0;
          // VALUE_W is the gutter the outside label needs; past that the
          // label has nowhere to go but into the bar.
          const inside = w > (up ? upW : downW) - VALUE_W;
          const fill = row.faint
            ? theme.textTertiary
            : up ? theme.successMid : theme.errorMid;
          return (
            <g key={row.key}>
              <text x={labelW} y={mid} dominantBaseline="middle" textAnchor="end"
                fontSize="11.5" fill={row.faint ? theme.textTertiary : theme.textPrimary}>
                {trim(row.key)}
              </text>
              <rect x={up ? zeroX : zeroX - w} y={y + 5} width={Math.max(w, 1)} height={ROW_H - 11}
                fill={fill} opacity={row.faint ? 0.45 : 0.85} rx="1" />
              {/* The longest bar reaches the edge of its half, which put
                  its value straight on top of the row label. Past that
                  point the value goes INSIDE the bar instead -- there is
                  no room outside it, and the bar is the one place on the
                  row guaranteed to be wide enough. */}
              <text
                x={inside
                  ? (up ? zeroX + w - 6 : zeroX - w + 6)
                  : (up ? zeroX + w + 6 : zeroX - w - 6)}
                y={mid} dominantBaseline="middle"
                textAnchor={inside ? (up ? "end" : "start") : (up ? "start" : "end")}
                fontSize="11.5" fontFamily="ui-monospace, monospace"
                // White reads on a saturated green or red bar but not on
                // the remainder bar, which is drawn pale on purpose.
                fill={inside
                  ? (row.faint ? theme.textSecondary : theme.bgWhite)
                  : row.faint ? theme.textTertiary : up ? theme.successText : theme.errorText}>
                {up ? "+" : "−"}{format(Math.abs(row.change))}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
