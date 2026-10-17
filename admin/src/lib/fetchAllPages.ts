/**
 * Walk a paginated analytics endpoint to the end.
 *
 * Every section that exports "all rows" needs the same loop, and the
 * loop has three ways to go wrong that are worth writing once:
 *
 *  - An endpoint that ignores `offset` returns page one forever. The
 *    cap and the `total` check both stop that rather than hanging the
 *    browser on an infinite download.
 *  - A short page means the end, even when `total` disagrees -- the
 *    totals on these endpoints are window aggregates and a row can
 *    drop out between requests.
 *  - A page of zero rows always ends the walk, however `total` reads.
 *
 * Requests are sequential on purpose. These endpoints aggregate over
 * the full window per call, and firing ten at once is how you take the
 * dashboard down for everyone else looking at it.
 */

export interface Page<T> {
  rows: T[];
  total?: number;
}

export interface FetchAllOptions {
  /** Rows per request. The analytics endpoints cap `limit` at 500. */
  pageSize?: number;
  /** Refuse to walk past this many rows, however large `total` claims
   *  to be. A CSV beyond this is not something a browser should be
   *  building in memory, and an endpoint looping on offset would
   *  otherwise never stop. */
  hardCap?: number;
  /** Called after each page with the running count, for a progress label. */
  onProgress?: (loaded: number, total?: number) => void;
}

export async function fetchAllPages<T>(
  page: (offset: number, limit: number) => Promise<Page<T>>,
  { pageSize = 500, hardCap = 20000, onProgress }: FetchAllOptions = {},
): Promise<T[]> {
  const out: T[] = [];
  let total: number | undefined;

  while (out.length < hardCap) {
    const result = await page(out.length, Math.min(pageSize, hardCap - out.length));
    const batch = result.rows ?? [];
    if (total === undefined) total = result.total;
    out.push(...batch);
    onProgress?.(out.length, total);

    if (batch.length === 0) break;
    if (batch.length < pageSize) break;
    if (total !== undefined && out.length >= total) break;
  }
  return out;
}
