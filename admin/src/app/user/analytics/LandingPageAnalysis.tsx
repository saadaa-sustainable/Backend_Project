"use client";

// React is imported for React.Fragment: the row map renders a <tr> plus
// an optional detail <tr>, and a bare <> fragment cannot carry the key
// React needs, which logged a "unique key prop" warning on every render.
import React, { useEffect, useMemo, useState } from "react";
import { DateRangePicker } from "@/components/DateRangePicker";
import {
  ApiError,
  LandingPageAdRow,
  LandingPageRow,
  fetchLandingPageAdBreakdown,
  fetchLandingPages,
} from "@/lib/api";
import { ExportButton } from "@/components/ExportButton";

const PAGE_SIZE = 50;

type LandingSort = string;

const SORT_OPTIONS: { value: LandingSort; label: string }[] = [
  { value: "ga4_sessions", label: "GA4 sessions" },
  { value: "ga4_purchases", label: "GA4 purchases" },
  { value: "ga4_pdp_views", label: "GA4 PDP views" },
  { value: "ga4_add_to_carts", label: "GA4 add to carts" },
  { value: "ga4_checkouts", label: "GA4 checkouts" },
  { value: "ga4_bounce_rate", label: "GA4 bounce rate" },
  { value: "shopify_sessions", label: "Shopify sessions" },
  { value: "conversion_rate", label: "Conversion rate" },
  { value: "pdp_to_atc_rate", label: "PDP → ATC %" },
  { value: "pdp_to_checkout_rate", label: "PDP → Checkout %" },
  { value: "atc_to_checkout_rate", label: "ATC → Checkout %" },
  { value: "checkout_to_purchase_rate", label: "Checkout → Purchase %" },
  { value: "pdp_to_purchase_rate", label: "PDP → Purchase %" },
  { value: "shopify_atc_rate", label: "Shopify ATC rate" },
  { value: "shopify_bounce_rate", label: "Shopify bounce rate" },
  { value: "sessions_delta", label: "Δ sessions" },
  { value: "sessions_delta_pct", label: "Δ sessions %" },
  { value: "bounce_rate_delta", label: "Δ bounce rate" },
];

// Ordered by traffic, not alphabetically: collections take ~1.1M of the
// last 30 days' GA4 sessions and products ~324k, so the two pages a
// reader actually wants sit at the top of the list. "" is all pages and
// is sent as no param at all.
const PAGE_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "All pages" },
  { value: "collections", label: "Collections" },
  { value: "products", label: "Products" },
  { value: "home", label: "Home" },
  { value: "pages", label: "Content pages" },
  { value: "other", label: "Other" },
];

// The sidebar is `w-64` on UserNav's <aside>. The table escapes the
// centred, max-w-[1600px] page container by spanning that much less
// than the viewport -- see the wrapper's style prop for why centring
// is what makes this exact.
const SIDEBAR_WIDTH = "16rem";

type Band = "shopify" | "ga4" | "delta";

type MetricColumn = {
  key: Exclude<keyof LandingPageRow, "landing_page_path">;
  /** The header, on one line. Every header renders through one code
   *  path, so none can drift from its neighbours -- hand-wrapping each
   *  <th> separately is what let "Checkout → Purchase" fall onto three
   *  lines while the rest used two. */
  label: string;
  title: string;
  band: Band;
  /** Opens a colour band -- draws the divider on this column's left edge. */
  bandStart?: "ga4" | "delta" | "ratios";
  percent?: boolean;
  /** Percentage POINTS. A difference between two rates is not itself a
   *  rate, and labelling it "%" invites reading a 14-point gap as a 14%
   *  relative change -- here it is the gap between 54% and 40%. */
  points?: boolean;
  /** Always render the sign, so "+" and "-" read as a direction rather
   *  than "-" looking like a stray minus on an ordinary figure. */
  signed?: boolean;
};

// Headers never wrap (whitespace-nowrap on the <th>), so the table
// carries a min-width wide enough for the longest of them. Below that
// the box scrolls sideways rather than letting a label collide with its
// neighbour -- a header that has to wrap to fit is the thing being
// avoided here, and silently truncating one would be worse than both.
const METRIC_COLUMNS: MetricColumn[] = [
  { key: "shopify_sessions", label: "Shopify sessions", band: "shopify",
    title: "Shopify sessions. Lower than GA4's for the same page — the two define a session and a landing page differently." },
  { key: "shopify_atc_rate", label: "Shopify ATC rate", band: "shopify", percent: true,
    title: "Shopify: cart-addition sessions / sessions, summed over the window." },
  { key: "shopify_bounce_rate", label: "Shopify bounce rate", band: "shopify", percent: true,
    title: "Shopify: bounces / sessions, summed over the window." },
  { key: "ga4_sessions", label: "GA4 sessions", band: "ga4", bandStart: "ga4",
    title: "GA4 sessions. Will not match Shopify's count." },
  { key: "ga4_bounce_rate", label: "GA4 bounce rate", band: "ga4", percent: true,
    title: "GA4 bounce rate, weighted by sessions across days and channels. Runs lower than Shopify's — the two define a bounce differently." },
  { key: "ga4_pdp_views", label: "PDP views", band: "ga4",
    title: "GA4 view_item events — product detail page views." },
  { key: "ga4_add_to_carts", label: "ATC", band: "ga4", title: "GA4 add_to_cart count." },
  { key: "ga4_checkouts", label: "Checkouts", band: "ga4",
    title: "GA4 checkouts. Shopify's own count reads ~10x low because GoKwik owns the checkout." },
  { key: "ga4_purchases", label: "Purchases", band: "ga4",
    title: "GA4 ecommerce purchases. GA4 records about 76% of orders." },
  { key: "sessions_delta", label: "\u0394 sessions", band: "delta", bandStart: "delta", signed: true,
    title: "GA4 sessions minus Shopify sessions. Negative is the usual direction: client-side tracking loses sessions that Shopify's server-side count keeps." },
  { key: "sessions_delta_pct", label: "\u0394 sessions %", band: "delta", percent: true, signed: true,
    title: "The session gap as a share of Shopify's count. Comparable across pages in a way the raw difference is not." },
  { key: "bounce_rate_delta", label: "\u0394 bounce rate", band: "delta", points: true, signed: true,
    title: "GA4 bounce rate minus Shopify's, in percentage points. Differenced before rounding, so it can end .01 away from subtracting the two displayed figures." },
  { key: "conversion_rate", label: "Conv. rate", band: "ga4", bandStart: "ratios", percent: true,
    title: "purchases / GA4 sessions. GA4 on both sides — mixing sources would give a number belonging to neither." },
  { key: "pdp_to_atc_rate", label: "PDP → ATC", band: "ga4", percent: true,
    title: "GA4 add to carts / PDP views" },
  { key: "pdp_to_checkout_rate", label: "PDP → Checkout", band: "ga4", percent: true,
    title: "GA4 checkouts / PDP views" },
  { key: "atc_to_checkout_rate", label: "ATC → Checkout", band: "ga4", percent: true,
    title: "GA4 checkouts / GA4 add to carts" },
  { key: "checkout_to_purchase_rate", label: "Checkout → Purchase", band: "ga4", percent: true,
    title: "GA4 purchases / GA4 checkouts" },
  { key: "pdp_to_purchase_rate", label: "PDP → Purchase", band: "ga4", percent: true,
    title: "GA4 purchases / PDP views" },
];

const COL_COUNT = METRIC_COLUMNS.length + 1;

// Green for Shopify, blue for GA4, orange for the gap between them.
//
// Blue keeps the slot it already had, which is the twelve-column
// majority of the table -- moving those would cost the most relearning
// for the least reason. Green goes to Shopify, matching its own brand.
//
// Orange lands on the delta band because it is the "look here" colour:
// those columns exist to surface disagreement. Green would have been
// the wrong choice there -- on a signed column it reads as a verdict,
// and a -29% session gap is a fact about tracking, not a good or bad
// outcome. The tint is on the band, never on individual values, for the
// same reason.
const BAND_HEAD = {
  shopify: "bg-green-100 text-green-900",
  ga4: "bg-blue-100 text-blue-900",
  delta: "bg-orange-100 text-orange-900",
} as const;
const BAND_CELL = {
  shopify: "bg-green-50/70",
  ga4: "bg-blue-50/60",
  delta: "bg-orange-50/70",
} as const;
const BAND_EDGE_HEAD = {
  ga4: " border-l border-l-blue-300",
  delta: " border-l border-l-orange-400",
  ratios: " border-l border-l-blue-400",
} as const;
const BAND_EDGE_CELL = {
  ga4: " border-l border-l-blue-200",
  delta: " border-l border-l-orange-300",
  ratios: " border-l border-l-blue-300",
} as const;

function formatNumber(n: number | null, opts: Intl.NumberFormatOptions = {}): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString(undefined, opts);
}

/** One cell's text, so a column's unit and sign are decided in exactly
 *  one place rather than per <td>. The em dash is not 0: a null here
 *  means the figure is undefined -- no denominator, or a page only one
 *  source ever saw -- and showing 0 would assert something false. */
function formatMetric(v: number | null, c: MetricColumn): string {
  if (v === null || v === undefined) return "—";
  const decimals = c.percent || c.points ? 2 : 0;
  const body = v.toLocaleString(undefined, {
    maximumFractionDigits: decimals,
    ...(c.signed ? { signDisplay: "exceptZero" as const } : {}),
  });
  return c.percent ? `${body}%` : c.points ? `${body} pp` : body;
}

function AdBreakdownPanel({ path, onClose }: { path: string; onClose: () => void }) {
  const [rows, setRows] = useState<LandingPageAdRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchLandingPageAdBreakdown(path)
      .then((res) => !cancelled && setRows(res.rows))
      .catch((err: unknown) => !cancelled && setError(err instanceof ApiError ? err.message : "Could not load ad breakdown."))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [path]);

  return (
    <div className="rounded-lg border border-warning-border bg-warning-bg/40 p-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-text-primary">Ads linking to {path}</h3>
        <button onClick={onClose} className="text-xs text-text-secondary hover:text-text-primary">
          Close ✕
        </button>
      </div>
      {error && <p className="mt-2 text-xs text-error-text">{error}</p>}
      {loading ? (
        <p className="mt-2 text-xs text-text-secondary">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="mt-2 text-xs text-text-secondary">
          No ads currently link to this page (or ad-creative link data hasn&apos;t been fetched yet).
        </p>
      ) : (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-warning-border text-text-secondary">
                <th className="px-3 py-2 text-left font-medium">Ad</th>
                <th className="px-3 py-2 text-right font-medium">Spend</th>
                <th className="px-3 py-2 text-right font-medium">Meta ROAS</th>
                <th className="px-3 py-2 text-right font-medium">Shopify orders</th>
                <th className="px-3 py-2 text-right font-medium">Shopify ROAS</th>
                <th className="px-3 py-2 text-right font-medium">ROAS gap %</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.ad_id} className="border-b border-warning-border/60">
                  <td className="max-w-[220px] truncate px-3 py-1.5 text-text-primary" title={r.ad_name ?? ""}>
                    {r.ad_name ?? "—"}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono text-text-primary">
                    {formatNumber(r.spend, { maximumFractionDigits: 0 })}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono text-text-primary">
                    {formatNumber(r.meta_roas, { maximumFractionDigits: 2 })}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono text-text-primary">
                    {formatNumber(r.shopify_orders, { maximumFractionDigits: 0 })}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono text-text-primary">
                    {formatNumber(r.shopify_roas, { maximumFractionDigits: 2 })}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono text-text-primary">
                    {formatNumber(r.roas_gap_pct, { maximumFractionDigits: 1 })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function LandingPageAnalysis() {
  const [search, setSearch] = useState("");
  const [pageType, setPageType] = useState("");
  const [sort, setSort] = useState<LandingSort>("ga4_sessions");
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  // The shared picker, the same control Ads Analyse and CPIS use, so
  // the three sections speak one vocabulary of presets.
  //
  // Dates are sent on EVERY request rather than left empty for a
  // default: the funnel ratios are computed over whatever window is
  // asked for, so "which window" is never implicit here.
  const [datePreset, setDatePreset] = useState<string>("last30");
  const [fromDate, setFromDate] = useState<string>(() => {
    const d = new Date(); d.setDate(d.getDate() - 29);
    return d.toISOString().slice(0, 10);
  });
  const [toDate, setToDate] = useState<string>(() => new Date().toISOString().slice(0, 10));

  const [rows, setRows] = useState<LandingPageRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const filters = useMemo(
    () => ({
      search: search || undefined,
      page_type: pageType || undefined,
      sort,
      from_date: fromDate,
      to_date: toDate,
    }),
    [search, pageType, sort, fromDate, toDate],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchLandingPages({ ...filters, limit: PAGE_SIZE, offset: 0 })
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setTotal(res.total);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Could not reach the FastAPI backend. Is it running?");
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters]);

  async function loadMore() {
    setLoadingMore(true);
    try {
      const res = await fetchLandingPages({ ...filters, limit: PAGE_SIZE, offset: rows.length });
      setRows((prev) => [...prev, ...res.rows]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load more rows.");
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-text-secondary">
        Shopify and GA4 side by side for the same page, over the dates you pick. Shopify supplies the top of the funnel, where it is reliable; GA4 supplies the tail, because Shopify&rsquo;s own checkout count reads about 10&times; low on this store &mdash; GoKwik owns the checkout and Shopify never sees the completion. The two count sessions differently, so their numbers will not agree, and every ratio is computed within one source rather than across them.
      </p>

      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border-primary bg-white shadow-sm p-3">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search page path…"
          className="w-64 rounded-md border border-border-primary bg-white px-3 py-1.5 text-sm text-text-primary placeholder:text-text-tertiary focus:border-accent-yellow focus:outline-none"
        />
        <DateRangePicker
          value={{ from: fromDate, to: toDate }}
          preset={datePreset}
          align="left"
          onApply={(r, pk) => {
            setDatePreset(pk);
            setFromDate(r.from);
            setToDate(r.to);
          }}
        />
        <select
          value={pageType}
          onChange={(e) => setPageType(e.target.value)}
          className="rounded-md border border-border-primary bg-white px-2 py-1.5 text-sm text-text-primary focus:border-accent-yellow focus:outline-none"
        >
          {PAGE_TYPE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.value === "" ? o.label : `Section: ${o.label}`}
            </option>
          ))}
        </select>
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as typeof sort)}
          className="rounded-md border border-border-primary bg-white px-2 py-1.5 text-sm text-text-primary focus:border-accent-yellow focus:outline-none"
        >
          {SORT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              Sort: {o.label}
            </option>
          ))}
        </select>
        <span className="ml-auto text-xs text-text-secondary">
          {total.toLocaleString()} {total === 1 ? "page" : "pages"}
        </span>
        <ExportButton
          rows={rows as unknown as Record<string, unknown>[]}
          filename="landing_page_analysis"
          disabled={loading || !rows.length}
        />
      </div>

      {error && <div className="rounded-md border border-error-mid bg-error-bg p-3 text-sm text-error-text">{error}</div>}
      {/* A colour band is only worth having if it is decoded somewhere.
          The whole point of the two tints is that a reader can tell at a
          glance which source a number came from, which matters here
          because the two disagree on the same page by design. */}
      <div className="flex flex-wrap items-center gap-4 text-xs text-text-secondary">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-3 w-3 rounded-sm border border-green-300 bg-green-100" />
          Shopify
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-3 w-3 rounded-sm border border-blue-300 bg-blue-100" />
          GA4 counts
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-3 w-3 rounded-sm border border-orange-400 bg-orange-100" />
          GA4 &minus; Shopify
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-3 w-3 rounded-sm border-l-2 border-blue-400 bg-blue-100" />
          GA4 funnel ratios
        </span>
        <span className="text-text-tertiary">
          The two sources count sessions and bounces differently, so their numbers will not agree.
        </span>
      </div>

      {/* Full-bleed, escaping the page container's centred
          max-w-[1600px]. The arithmetic on the box below works ONLY
          because every wrapper above is horizontally centred inside
          <main>: that makes the box's centre the same as <main>'s, so a
          box exactly (100vw - sidebar) wide, pulled left by half the
          difference, lands flush on the sidebar edge and the window
          edge. No ancestor has to know how much slack the cap left.

          The box scrolls on BOTH axes, which is what lets the header
          stick to its top and the page column to its left. A bare
          overflow-x-auto has no bounded height, so a sticky thead would
          have nothing to stick within and would scroll away with the
          page.

          This sits ABOVE the conditional on purpose: a JSX comment
          cannot open a ternary branch -- the branch takes one
          expression, and a comment followed by an element is two. */}
      {loading ? (
        <p className="text-sm text-text-secondary">Loading…</p>
      ) : (
        <div
          className="max-h-[70vh] overflow-auto border-y border-border-primary bg-white shadow-sm"
          style={{
            width: `calc(100vw - ${SIDEBAR_WIDTH})`,
            marginLeft: `calc((100% - 100vw + ${SIDEBAR_WIDTH}) / 2)`,
          }}
        >
          {/* Columns size to their content (table-auto), NOT to an equal
              share. Equal shares and single-line headers cannot both
              hold: the widest label, "Checkout → Purchase", needs 180px,
              and 15 columns at 180 plus the page column is 2960px --
              wider than the display, so uniform widths would force the
              table to scroll sideways forever. Sized to content the same
              15 columns come to ~1870px, which fits. The columns differ
              in width; every header stays on one line and nothing
              scrolls. Equal padding and right-aligned figures carry the
              orderly look that equal widths used to.

              min-w-max is the floor, not a pixel figure: it is whatever
              the content actually needs, so adding a column or renaming
              a header cannot silently push the table past a hardcoded
              number and start clipping labels. Below that width the box
              scrolls sideways; w-full still lets it fill a wider one. */}
          <table className="w-full min-w-max table-auto border-separate border-spacing-0 text-left text-sm">
            <thead>
              <tr className="border-b border-border-primary text-xs text-text-secondary">
                <th className="sticky left-0 top-0 z-30 h-10 whitespace-nowrap border-b border-r border-border-primary bg-bg-muted px-2 py-2 text-left align-middle text-[11px] font-medium">
                  Page
                </th>
                {METRIC_COLUMNS.map((c) => (
                  <th
                    key={c.key}
                    title={c.title}
                    className={
                      "sticky top-0 z-20 h-10 whitespace-nowrap border-b border-border-primary px-2 py-2 text-right align-middle text-[11px] font-medium leading-tight " +
                      BAND_HEAD[c.band] +
                      (c.bandStart ? BAND_EDGE_HEAD[c.bandStart] : "")
                    }
                  >
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <React.Fragment key={row.landing_page_path}>
                  <tr
                    onClick={() => setSelectedPath((prev) => (prev === row.landing_page_path ? null : row.landing_page_path))}
                    className="cursor-pointer border-b border-border-soft hover:bg-bg-surface"
                  >
                    {/* Wide enough for the paths that matter: the longest
                        among the 200 pages that carry real traffic is 62
                        characters, and p90 across every page is 72. The cap
                        still exists for the 128-character outliers -- one of
                        those unbounded would push all 18 metric columns off
                        screen to spare a page nobody opens. Those truncate,
                        and the title attribute still carries the full path. */}
                    <td className="sticky left-0 z-10 max-w-[440px] truncate border-r border-border-soft bg-white px-2 py-1.5 text-xs text-text-primary" title={row.landing_page_path}>
                      {row.landing_page_path}
                    </td>
                    {METRIC_COLUMNS.map((c) => {
                      const v = row[c.key];
                      return (
                        <td
                          key={c.key}
                          className={
                            "border-b border-border-soft px-2 py-1.5 text-right font-mono text-[11px] text-text-primary " +
                            BAND_CELL[c.band] +
                            (c.bandStart ? BAND_EDGE_CELL[c.bandStart] : "")
                          }
                        >
                          {formatMetric(v, c)}
                        </td>
                      );
                    })}
                  </tr>
                  {selectedPath === row.landing_page_path && (
                    <tr key={`${row.landing_page_path}-panel`}>
                      <td colSpan={COL_COUNT} className="px-4 py-3">
                        <AdBreakdownPanel path={row.landing_page_path} onClose={() => setSelectedPath(null)} />
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={COL_COUNT} className="px-4 py-6 text-center text-text-secondary">
                    No pages match these filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          {rows.length < total && (
            <div className="border-t border-border-soft p-3 text-center">
              <button
                onClick={loadMore}
                disabled={loadingMore}
                className="rounded-md bg-bg-muted px-4 py-1.5 text-xs font-medium text-text-primary transition-colors hover:bg-bg-muted disabled:opacity-40"
              >
                {loadingMore ? "Loading…" : `Load more (${rows.length} of ${total})`}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
