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
import { SectionHeader, FilterRule, FilterCell, FieldLabel, filterControlClass } from "./SectionChrome";
import { MarkClose } from "./Pictograms";

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
  /** Opens a group -- draws the divider on this column's left edge and
   *  starts a new span in the group header row above. */
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
  { key: "sessions_delta", label: "Δ sessions", band: "delta", bandStart: "delta", signed: true,
    title: "GA4 sessions minus Shopify sessions. Negative is the usual direction: client-side tracking loses sessions that Shopify's server-side count keeps." },
  { key: "sessions_delta_pct", label: "Δ sessions %", band: "delta", percent: true, signed: true,
    title: "The session gap as a share of Shopify's count. Comparable across pages in a way the raw difference is not." },
  { key: "bounce_rate_delta", label: "Δ bounce rate", band: "delta", points: true, signed: true,
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

/* ── which source a column came from, said rather than tinted ──────
 *
 * This was three fills -- green cells for Shopify, blue for GA4,
 * orange for the gap -- plus a fourth left-border tint for the ratios,
 * decoded by a legend of four swatches above the table. Eighteen
 * columns of wash and a key to read it is the clutter the user named,
 * and the hues were off-palette besides.
 *
 * The same fact, stated: a group header row that NAMES the source over
 * its own columns, and one hairline where a group begins. Nothing is
 * lost -- the legend's four entries are now four headings, each sitting
 * directly above the columns it describes instead of a swatch the
 * reader has to carry across the page.
 */
type GroupKey = "shopify" | "ga4" | "delta" | "ratios";

const GROUP_LABEL: Record<GroupKey, string> = {
  shopify: "Shopify",
  ga4: "GA4 counts",
  delta: "GA4 − Shopify",
  ratios: "GA4 funnel ratios",
};

const GROUP_TITLE: Record<GroupKey, string> = {
  shopify: "Shopify's own figures. Reliable at the top of the funnel; its checkout count is not, because GoKwik owns the checkout.",
  ga4: "GA4's figures. The two sources count sessions and bounces differently, so these will not agree with Shopify's.",
  delta: "GA4 minus Shopify, on the two things both of them measure.",
  ratios: "Derived from the GA4 counts to their left — the same five numbers divided by each other. The funnel above is the quick read; these are the per-page detail.",
};

/** Column spans for the group header row, derived from the columns
 *  themselves so adding a column cannot leave a hand-written colSpan
 *  one short and shear the whole header. */
const COLUMN_GROUPS: { key: GroupKey; span: number }[] = (() => {
  const out: { key: GroupKey; span: number }[] = [];
  METRIC_COLUMNS.forEach((c, i) => {
    const opens: GroupKey | undefined = i === 0 ? "shopify" : c.bandStart;
    if (opens) out.push({ key: opens, span: 0 });
    out[out.length - 1].span += 1;
  });
  return out;
})();

/** Height of the group header row, in px. The column header row sticks
 *  directly beneath it, so the two numbers have to agree. */
const GROUP_ROW_H = 24;

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

/* ── the funnel ────────────────────────────────────────────────────
 *
 * Sixteen ratio columns are the same five counts divided by each other.
 * The columns stay -- per page, divided every way, is what the table is
 * for -- but nobody reads sixteen percentages to find the worst step.
 * One row of five figures, each bar shorter than the last, and the
 * drop between every pair, answers that before the table is reached.
 */
const FUNNEL_STEPS: {
  key: "ga4_sessions" | "ga4_pdp_views" | "ga4_add_to_carts" | "ga4_checkouts" | "ga4_purchases";
  label: string;
  bar: string;
  title: string;
}[] = [
  { key: "ga4_sessions", label: "Sessions", bar: "bg-text-primary",
    title: "GA4 sessions that landed on the pages in view." },
  { key: "ga4_pdp_views", label: "PDP views", bar: "bg-text-secondary",
    title: "GA4 view_item events — product detail page views." },
  { key: "ga4_add_to_carts", label: "Add to cart", bar: "bg-text-tertiary",
    title: "GA4 add_to_cart count." },
  { key: "ga4_checkouts", label: "Checkout", bar: "bg-text-tertiary",
    title: "GA4 checkouts. Shopify's own count reads ~10x low because GoKwik owns the checkout." },
  { key: "ga4_purchases", label: "Purchases", bar: "bg-accent-yellow",
    title: "GA4 ecommerce purchases. GA4 records about 76% of orders." },
];

/** Red where a step loses most of what reached it, amber where it loses
 *  a lot, green where the loss is ordinary. Thresholds, not a gradient:
 *  three bands are readable at 11px, a ramp is not. */
function dropTone(dropPct: number): string {
  if (dropPct >= 65) return "text-error-text";
  if (dropPct >= 35) return "text-warning-text";
  return "text-success-text";
}

function FunnelBand({ rows, total }: { rows: LandingPageRow[]; total: number }) {
  const totals = useMemo(
    () => FUNNEL_STEPS.map((s) => rows.reduce((n, r) => n + (r[s.key] ?? 0), 0)),
    [rows],
  );
  const head = totals[0] ?? 0;

  // A fourth root, not a linear scale. Purchases are ~2% of sessions,
  // so proportional heights would draw the last bar at one pixel and
  // the four steps between would be indistinguishable. The compressed
  // scale keeps every step visible; the DROP figures beside them, not
  // the bar lengths, are what the reader is meant to measure with.
  const BAR_MAX = 58;
  const barHeight = (v: number) => (head > 0 ? Math.max(Math.round(BAR_MAX * Math.pow(v / head, 0.25)), 7) : 7);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border-primary pb-1.5">
        <FieldLabel>Where the funnel leaks</FieldLabel>
        <span className="text-[11.5px] text-text-tertiary tabular-nums">
          GA4 · summed over the {rows.length.toLocaleString()} of {total.toLocaleString()} pages loaded
        </span>
      </div>
      <div className="flex items-end overflow-x-auto pb-1">
        {FUNNEL_STEPS.map((s, i) => {
          const v = totals[i] ?? 0;
          const prev = i > 0 ? totals[i - 1] ?? 0 : 0;
          const drop = i > 0 && prev > 0 ? (1 - v / prev) * 100 : null;
          return (
            <React.Fragment key={s.key}>
              {i > 0 && (
                <div className="shrink-0 px-2.5 pb-5">
                  {drop === null ? (
                    <span className="text-[11.5px] text-text-tertiary">—</span>
                  ) : (
                    <span
                      className={`text-[11.5px] tabular-nums ${dropTone(drop)}`}
                      title={
                        `${prev.toLocaleString("en-IN")} ${FUNNEL_STEPS[i - 1].label} to ${v.toLocaleString("en-IN")} ${s.label} — ` +
                        (drop >= 0
                          ? `${(prev - v).toLocaleString("en-IN")} lost at this step`
                          : `${(v - prev).toLocaleString("en-IN")} MORE than the step before it. GA4 counts events, not people: one session can fire view_item many times, so this step can exceed the one above it.`)
                      }
                    >
                      {/* A step can read ABOVE the one before it -- GA4
                          counts view_item events, not sessions, so PDP
                          views regularly exceed sessions. Signed both
                          ways rather than always "−", which printed
                          "−-23.6%" and asserted a fall that is a rise. */}
                      {drop >= 0 ? "−" : "+"}
                      {Math.abs(drop).toFixed(1)}%
                    </span>
                  )}
                </div>
              )}
              <div className="flex min-w-[108px] flex-1 flex-col gap-1.5" title={s.title}>
                <FieldLabel>{s.label}</FieldLabel>
                <div className="text-[21px] font-medium leading-none tracking-[-0.02em] text-text-primary tabular-nums">
                  {v.toLocaleString("en-IN")}
                </div>
                <div className={s.bar} style={{ height: barHeight(v) }} />
              </div>
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
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
    <div className="bg-bg-surface px-4 py-3">
      <div className="flex items-center justify-between border-b border-border-primary pb-1.5">
        <FieldLabel>Ads linking to {path}</FieldLabel>
        <button
          onClick={onClose}
          title="Close this breakdown"
          aria-label="Close this breakdown"
          className="text-text-tertiary transition-colors hover:text-text-primary"
        >
          <MarkClose />
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
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="text-text-tertiary">
                <th className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-[0.08em]">Ad</th>
                <th className="px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em]">Spend</th>
                <th className="px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em]">Meta ROAS</th>
                <th className="px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em]">Shopify orders</th>
                <th className="px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em]">Shopify ROAS</th>
                <th className="px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em]">ROAS gap %</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.ad_id} className="border-t border-border-soft">
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
    <div className="flex flex-col gap-5">
      {/* Why GA4 and Shopify disagree, and which supplies which end of
          the funnel, is the single most load-bearing fact on this page
          -- and it is a fact about the data, not about today's numbers.
          It moved to Help, behind the ? on the title. */}
      <SectionHeader title="Landing Page Analysis" helpId="freshness" />

      {/* One rule of labelled cells. Was four boxed controls and a
          floating count, in three different shapes. */}
      <FilterRule
        actions={
          <>
            <span className="text-[11.5px] text-text-tertiary tabular-nums">
              {total.toLocaleString()} {total === 1 ? "page" : "pages"}
            </span>
            <ExportButton
              rows={rows as unknown as Record<string, unknown>[]}
              filename="landing_page_analysis"
              disabled={loading || !rows.length}
            />
          </>
        }
      >
        <FilterCell label="Date range">
          <DateRangePicker
            value={{ from: fromDate, to: toDate }}
            preset={datePreset}
            bare
            align="left"
            onApply={(r, pk) => {
              setDatePreset(pk);
              setFromDate(r.from);
              setToDate(r.to);
            }}
          />
        </FilterCell>

        <FilterCell label="Page path" className="w-56" htmlFor="lp-search">
          <input
            id="lp-search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search…"
            className={filterControlClass}
          />
        </FilterCell>

        <FilterCell label="Section" className="w-40" htmlFor="lp-page-type">
          <select
            id="lp-page-type"
            value={pageType}
            onChange={(e) => setPageType(e.target.value)}
            className={filterControlClass}
          >
            {PAGE_TYPE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </FilterCell>

        <FilterCell label="Sort by" className="w-52" htmlFor="lp-sort">
          <select
            id="lp-sort"
            value={sort}
            onChange={(e) => setSort(e.target.value as typeof sort)}
            className={filterControlClass}
          >
            {SORT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </FilterCell>
      </FilterRule>

      {error && <div className="bg-error-bg px-3 py-2 text-sm text-error-text">{error}</div>}

      {!loading && rows.length > 0 && <FunnelBand rows={rows} total={total} />}

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

          Hairlines top and bottom and no shadow: on this surface
          nothing carries both a border and a shadow, and the box was
          carrying both.

          This sits ABOVE the conditional on purpose: a JSX comment
          cannot open a ternary branch -- the branch takes one
          expression, and a comment followed by an element is two. */}
      {loading ? (
        <p className="text-sm text-text-secondary">Loading…</p>
      ) : (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border-primary pb-1.5">
            <FieldLabel>By landing page</FieldLabel>
            <span className="text-[11.5px] text-text-tertiary">
              The two sources count sessions and bounces differently, so their numbers will not agree.
            </span>
          </div>
          <div
            className="max-h-[70vh] overflow-auto border-y border-border-primary bg-bg-white"
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
                <tr>
                  <th
                    className="sticky left-0 top-0 z-40 border-r border-border-primary bg-bg-muted px-2 text-left"
                    style={{ height: GROUP_ROW_H }}
                  />
                  {COLUMN_GROUPS.map((g, i) => (
                    <th
                      key={g.key}
                      colSpan={g.span}
                      title={GROUP_TITLE[g.key]}
                      className={
                        "sticky top-0 z-30 whitespace-nowrap bg-bg-muted px-2 text-left align-middle text-[10px] font-semibold uppercase tracking-[0.08em] text-text-tertiary" +
                        (i > 0 ? " border-l border-border-primary" : "")
                      }
                      style={{ height: GROUP_ROW_H }}
                    >
                      {GROUP_LABEL[g.key]}
                    </th>
                  ))}
                </tr>
                <tr>
                  <th
                    className="sticky left-0 z-40 h-9 whitespace-nowrap border-b border-r border-border-primary bg-bg-muted px-2 py-2 text-left align-middle text-[10px] font-semibold uppercase tracking-[0.08em] text-text-tertiary"
                    style={{ top: GROUP_ROW_H }}
                  >
                    Page
                  </th>
                  {METRIC_COLUMNS.map((c) => (
                    <th
                      key={c.key}
                      title={c.title}
                      className={
                        "sticky z-30 h-9 whitespace-nowrap border-b border-border-primary bg-bg-muted px-2 py-2 text-right align-middle text-[10px] font-semibold uppercase tracking-[0.08em] leading-tight text-text-tertiary" +
                        (c.bandStart ? " border-l border-border-primary" : "")
                      }
                      style={{ top: GROUP_ROW_H }}
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
                      className="cursor-pointer hover:bg-bg-surface"
                    >
                      {/* Wide enough for the paths that matter: the longest
                          among the 200 pages that carry real traffic is 62
                          characters, and p90 across every page is 72. The cap
                          still exists for the 128-character outliers -- one of
                          those unbounded would push all 18 metric columns off
                          screen to spare a page nobody opens. Those truncate,
                          and the title attribute still carries the full path. */}
                      <td
                        className={`sticky left-0 z-10 max-w-[440px] truncate border-b border-r border-border-soft px-2 py-1.5 text-xs text-text-primary ${
                          selectedPath === row.landing_page_path ? "bg-bg-surface" : "bg-bg-white"
                        }`}
                        title={row.landing_page_path}
                      >
                        {row.landing_page_path}
                      </td>
                      {METRIC_COLUMNS.map((c) => {
                        const v = row[c.key];
                        return (
                          <td
                            key={c.key}
                            className={
                              "border-b border-border-soft px-2 py-1.5 text-right font-mono text-[11px] text-text-primary" +
                              (c.bandStart ? " border-l border-l-border-primary" : "")
                            }
                          >
                            {formatMetric(v, c)}
                          </td>
                        );
                      })}
                    </tr>
                    {selectedPath === row.landing_page_path && (
                      <tr key={`${row.landing_page_path}-panel`}>
                        <td colSpan={COL_COUNT} className="border-b border-border-primary p-0">
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
          </div>
          {rows.length < total && (
            <div className="flex justify-center">
              <button
                onClick={loadMore}
                disabled={loadingMore}
                className="text-[12.5px] text-text-secondary transition-colors hover:text-text-primary disabled:opacity-40"
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
