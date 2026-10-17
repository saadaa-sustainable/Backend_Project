/**
 * Which rows moved the total, and by how much.
 *
 * Separated from the SVG so the one property the chart promises can be
 * tested: the bars ADD UP to the headline change. A chart that ranks
 * movers but silently drops the tail is a chart that disagrees with the
 * number printed above it, and the reader has no way to tell.
 */

export interface ContributionDatum {
  key: string;
  current: number | null;
  baseline: number | null;
}

export interface ContributionBar {
  key: string;
  change: number;
  /** The rolled-up remainder, drawn quieter than a named row. */
  faint?: boolean;
}

export interface Contribution {
  bars: ContributionBar[];
  /** Net change across every row with both days present. */
  total: number;
  /** How many rows had a non-zero move, before the top-N cut. */
  movers: number;
}

export function buildContribution(
  data: ContributionDatum[],
  { maxRows = 12, additive = true }: { maxRows?: number; additive?: boolean } = {},
): Contribution {
  // A row missing either day has no movement to attribute. Charting a
  // new row's whole current value as "change" would overstate what
  // moved -- the table already says "new", which is the honest word.
  const changes = data
    .filter((d) => d.current !== null && d.baseline !== null)
    .map((d) => ({ key: d.key, change: (d.current as number) - (d.baseline as number) }))
    .filter((d) => d.change !== 0);

  const total = changes.reduce((sum, d) => sum + d.change, 0);

  // Rank by SIZE of movement, then restore signed order for drawing, so
  // the biggest gains sit at the top and the biggest losses at the
  // bottom with the quiet middle left out.
  const ranked = [...changes].sort((a, b) => Math.abs(b.change) - Math.abs(a.change));
  const bars: ContributionBar[] = ranked.slice(0, maxRows).sort((a, b) => b.change - a.change);
  const rest = ranked.slice(maxRows).reduce((sum, d) => sum + d.change, 0);

  // Without this the bars would silently fall short of the total.
  // Suppressed for a rate: percentage points across rows do not add to
  // the total's movement, because the total is weighted by volume, so
  // a remainder bar would assert an arithmetic that is false.
  if (additive && rest !== 0) {
    bars.push({ key: `all other rows (${ranked.length - maxRows})`, change: rest, faint: true });
  }

  return { bars, total, movers: ranked.length };
}
