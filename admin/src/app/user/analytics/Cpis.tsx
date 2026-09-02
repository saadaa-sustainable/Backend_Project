"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ApiError,
  CpisMatchedAdRow,
  CpisUtmRow,
  CpisUtmSort,
  CpisUtmWindow,
  SaturationCurveResponse,
  SaturationYMetric,
  fetchCpisDataFreshness,
  fetchCpisMatchedAds,
  fetchCpisSpendTrend,
  fetchCpisUtm,
  fetchSaturationCurve,
  type CpisDataFreshness,
} from "@/lib/api";
import { SaturationCurveChart } from "./charts/SaturationCurveChart";
import { KwikTile } from "./KwikTile";

// Bumped from 50 -> 500 (2026-09-02) so the KPI strip's client-side
// sums represent the entire matched SKU set, not just the first page.
// Total distinct SKUs across every window stays <100, so a single-page
// fetch is still fast.
const PAGE_SIZE = 500;
const SATURATION_Y_METRICS: { value: SaturationYMetric; label: string }[] = [
  { value: "ncp_count", label: "NCP" },
  { value: "purchases", label: "Purchases" },
  { value: "ftewv_count", label: "First-time EWV" },
];

/** Details of a single clicked ad on the saturation curve. Kept in
 *  parent state so the drilldown panel stays anchored to the selection
 *  when the chart re-fits after control changes. */
interface SelectedAd {
  ad_id: string;
  ad_name: string | null;
  spend: number;
  y: number;
  y_label: string;
}

function SaturationCurveSection({ masterSkuFilter }: { masterSkuFilter: string | null }) {
  const [yMetric, setYMetric] = useState<SaturationYMetric>("ncp_count");
  const [scopeToSku, setScopeToSku] = useState(false);
  const [data, setData] = useState<SaturationCurveResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedAd, setSelectedAd] = useState<SelectedAd | null>(null);

  const masterSku = scopeToSku ? masterSkuFilter ?? undefined : undefined;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setSelectedAd(null); // clear drilldown on refit
    fetchSaturationCurve({ y_metric: yMetric, master_sku: masterSku })
      .then((res) => !cancelled && setData(res))
      .catch((err: unknown) => !cancelled && setError(err instanceof ApiError ? err.message : "Could not compute the saturation curve."))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [yMetric, masterSku]);

  const fmtINR = (n: number) => {
    const abs = Math.abs(n);
    if (abs >= 1e7) return `₹${(n / 1e7).toFixed(2)}Cr`;
    if (abs >= 1e5) return `₹${(n / 1e5).toFixed(2)}L`;
    if (abs >= 1e3) return `₹${(n / 1e3).toFixed(1)}K`;
    return `₹${Math.round(n)}`;
  };

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border-primary bg-white shadow-sm p-4">
      <div>
        <h3 className="text-sm font-medium text-text-primary">Saturation curve</h3>
        <p className="mt-1 text-xs text-text-secondary">
          Real-time fit (log-log regression, computed in Python on every selection) of ad spend vs. conversions
          across {scopeToSku && masterSkuFilter ? `ads matching ${masterSkuFilter}` : "every ad"} — where the curve
          bends down is where more spend stops paying off proportionally. <strong>Click any dot to drill in.</strong>
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex overflow-hidden rounded-md border border-border-primary">
          {SATURATION_Y_METRICS.map((m) => (
            <button
              key={m.value}
              onClick={() => setYMetric(m.value)}
              className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                yMetric === m.value ? "bg-accent-yellow text-text-primary" : "bg-white text-text-secondary hover:bg-bg-surface"
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>
        {masterSkuFilter && (
          <label className="flex items-center gap-1.5 text-xs text-text-secondary">
            <input type="checkbox" checked={scopeToSku} onChange={(e) => setScopeToSku(e.target.checked)} />
            Scope to <span className="font-mono">{masterSkuFilter}</span> only
          </label>
        )}
        {data && (
          <span className="ml-auto text-xs text-text-tertiary">
            {data.points.length} ads · {data.excluded_zero_or_missing} excluded (zero spend/{data.y_label.toLowerCase()})
          </span>
        )}
      </div>

      {error && <div className="rounded-md border border-error-mid bg-error-bg p-2 text-xs text-error-text">{error}</div>}
      {loading ? (
        <p className="text-xs text-text-secondary">Fitting curve…</p>
      ) : data ? (
        <>
          {data.fit ? (
            <p className="text-xs text-text-secondary">
              Fit: y = {data.fit.a.toFixed(4)} · spend<sup>{data.fit.b.toFixed(3)}</sup> (R² = {data.fit.r_squared.toFixed(3)}) —{" "}
              {data.fit.is_saturating ? (
                <span className="font-medium text-warning-text">exponent &lt; 1: real diminishing returns signal</span>
              ) : (
                <span className="text-text-tertiary">exponent ≥ 1: no saturation signal in this data</span>
              )}
            </p>
          ) : (
            <p className="text-xs text-text-tertiary">Not enough ads with both spend and {data.y_label} to fit a curve (need 5+).</p>
          )}
          <SaturationCurveChart
            points={data.points
              .filter((p) => p.spend > 0 && p.y > 0)
              .map((p) => ({
                label: p.ad_name ?? p.ad_id,
                x: p.spend,
                y: p.y,
                meta: { ad_id: p.ad_id, ad_name: p.ad_name },
              }))}
            curve={data.fit?.curve_points ?? null}
            xLabel="Ad spend"
            yLabel={data.y_label}
            selectedLabel={selectedAd ? (selectedAd.ad_name ?? selectedAd.ad_id) : null}
            onPointClick={(p) => {
              const meta = p.meta as { ad_id: string; ad_name: string | null } | undefined;
              if (!meta) return;
              setSelectedAd({
                ad_id: meta.ad_id,
                ad_name: meta.ad_name,
                spend: p.x,
                y: p.y,
                y_label: data.y_label,
              });
            }}
          />
          {selectedAd && (
            <div className="mt-2 rounded-lg border border-accent-yellow bg-accent-yellow-bg/30 p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-[11px] uppercase tracking-wider text-text-tertiary">Selected ad</div>
                  <div className="mt-1 truncate text-[13px] font-medium text-text-primary" title={selectedAd.ad_name ?? undefined}>
                    {selectedAd.ad_name ?? <span className="text-text-tertiary">(unnamed)</span>}
                  </div>
                  <div className="mt-0.5 font-mono text-[10px] text-text-tertiary">ad_id: {selectedAd.ad_id}</div>
                </div>
                <button
                  onClick={() => setSelectedAd(null)}
                  className="rounded p-1 text-text-tertiary hover:bg-white hover:text-text-primary"
                  aria-label="Clear selection"
                >
                  ✕
                </button>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-text-tertiary">Spend</div>
                  <div className="mt-0.5 font-mono text-[15px] font-semibold text-text-primary">{fmtINR(selectedAd.spend)}</div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-text-tertiary">{selectedAd.y_label}</div>
                  <div className="mt-0.5 font-mono text-[15px] font-semibold text-text-primary">
                    {selectedAd.y.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                  </div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-text-tertiary">Cost / {selectedAd.y_label}</div>
                  <div className="mt-0.5 font-mono text-[15px] font-semibold text-text-primary">
                    {selectedAd.y > 0 ? fmtINR(selectedAd.spend / selectedAd.y) : "—"}
                  </div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-text-tertiary">Position vs. fit</div>
                  <div className="mt-0.5 font-mono text-[15px] font-semibold">
                    {data.fit ? (() => {
                      const predicted = data.fit.a * Math.pow(selectedAd.spend, data.fit.b);
                      const ratio = selectedAd.y / predicted;
                      return (
                        <span className={ratio >= 1.2 ? "text-success-text" : ratio <= 0.8 ? "text-error-text" : "text-warning-text"}>
                          {(ratio * 100).toFixed(0)}%
                          <span className="ml-1 text-[10px] text-text-tertiary">
                            {ratio >= 1.2 ? "above" : ratio <= 0.8 ? "below" : "near"}
                          </span>
                        </span>
                      );
                    })() : (
                      <span className="text-text-tertiary">—</span>
                    )}
                  </div>
                </div>
              </div>
              <p className="mt-2 text-[11px] text-text-tertiary">
                &quot;Position vs. fit&quot; is this ad&apos;s actual {selectedAd.y_label} divided by what the fitted saturation curve predicts at this spend level.
                &gt;120% = the ad outperforms peers; &lt;80% = underperforms — a triage signal for whether more spend is worth it.
              </p>
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}

const UTM_WINDOWS: CpisUtmWindow[] = ["7d", "30d", "90d"];
// Sort options exposed in the UI. These still map to columns on the base
// cpis_by_sku_utm table (which the endpoint uses as the driver) -- so
// even though we don't display UTM columns anymore, sorting by
// attributed_units still surfaces the master SKUs with the most orders,
// which is the merchant's natural "top sellers first" default.
const UTM_SORT_OPTIONS: { value: CpisUtmSort; label: string }[] = [
  { value: "attributed_units", label: "Units sold (most first)" },
  { value: "attributed_orders", label: "Orders (most first)" },
  { value: "attributed_revenue", label: "Revenue (highest first)" },
  { value: "ad_spend", label: "Ad spend (highest first)" },
];

export function Cpis() {
  // Single-view CPIS (2026-08-31 simplification per user direction):
  // SKU code as the base, matched against ad_name via word-boundary
  // regex. UTM-based attribution is dropped from this view -- it will
  // return only when we add per-color-variant attribution, since UTM
  // is the only way to distinguish "Black variant of SDCP" from "White
  // variant of SDCP" (ad_name matching is master-SKU-level only).
  return <CpisView />;
}

/** Money formatting for INR — compact (₹1.2L / ₹3.4Cr) so tiles/columns
 *  stay narrow enough to fit 5+ across without wrapping. */
function fmtINRCompact(n: number | null | undefined): string {
  if (n === null || n === undefined || !isFinite(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e7) return `₹${(n / 1e7).toFixed(2)}Cr`;
  if (abs >= 1e5) return `₹${(n / 1e5).toFixed(2)}L`;
  if (abs >= 1e3) return `₹${(n / 1e3).toFixed(1)}K`;
  return `₹${Math.round(n)}`;
}

function fmtNumCompact(n: number | null | undefined): string {
  if (n === null || n === undefined || !isFinite(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e7) return `${(n / 1e7).toFixed(2)}Cr`;
  if (abs >= 1e5) return `${(n / 1e5).toFixed(2)}L`;
  if (abs >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return `${n.toLocaleString()}`;
}

/** Full-precision Indian-format numbers for wide layouts (drill-down
 *  modal). Uses en-IN locale so 635741 renders as "6,35,741" instead of
 *  "635,741" -- matches Meta Ads Manager's own India-region display. */
function fmtINRFull(n: number | null | undefined): string {
  if (n === null || n === undefined || !isFinite(n)) return "—";
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
}

function fmtNumFull(n: number | null | undefined): string {
  if (n === null || n === undefined || !isFinite(n)) return "—";
  return Math.round(n).toLocaleString("en-IN");
}

/** Inline spend-trend sparkline that lazy-loads its own daily-series
 *  data via /cpis-utm/spend-trend when the row mounts. Split from the
 *  main /cpis-utm endpoint because the raw_dump_meta scan for 50 rows
 *  ballooned to 60+s; per-SKU the fetch is under a second. */
function LazySpendTrendCell({
  masterSku,
  window,
}: {
  masterSku: string;
  window: CpisUtmWindow;
}) {
  const [daily, setDaily] = useState<number[] | null>(null);
  const [prevTotal, setPrevTotal] = useState<number | null>(null);
  const [state, setState] = useState<"loading" | "loaded" | "error">("loading");

  useEffect(() => {
    let cancelled = false;
    setState("loading");
    fetchCpisSpendTrend(masterSku, window)
      .then((r) => {
        if (cancelled) return;
        setDaily(r.spend_trend_current);
        setPrevTotal(r.spend_trend_prev_total);
        setState("loaded");
      })
      .catch(() => !cancelled && setState("error"));
    return () => {
      cancelled = true;
    };
  }, [masterSku, window]);

  if (state === "loading") {
    return (
      <div className="flex items-center justify-end">
        <div className="h-1 w-16 animate-pulse rounded bg-bg-muted" />
      </div>
    );
  }
  if (state === "error") return <span className="text-text-tertiary">—</span>;
  return <SpendTrendSparkline daily={daily} prevTotal={prevTotal} />;
}

/** Inline spend-trend sparkline + % change badge vs. previous period.
 *  Renders a compact `~80×24` SVG so the shape of daily spend reads
 *  clearly even inside a table cell. Colored green when the current-
 *  period total exceeds the previous, red when it drops -- the merchant
 *  can eyeball "spend is rising" without stopping to read numbers. */
function SpendTrendSparkline({
  daily,
  prevTotal,
}: {
  daily: number[] | null | undefined;
  prevTotal: number | null | undefined;
}) {
  if (!daily || daily.length < 2) {
    return <span className="text-text-tertiary">—</span>;
  }
  const currTotal = daily.reduce((a, b) => a + b, 0);
  const pctChange =
    prevTotal !== null && prevTotal !== undefined && prevTotal > 0
      ? ((currTotal - prevTotal) / prevTotal) * 100
      : null;
  const max = Math.max(...daily, 1);
  const w = 72;
  const h = 22;
  const step = daily.length > 1 ? w / (daily.length - 1) : w;
  const pts = daily
    .map((v, i) => `${(i * step).toFixed(2)},${(h - (v / max) * h).toFixed(2)}`)
    .join(" ");
  const stroke =
    pctChange === null
      ? "#6B7280"
      : pctChange >= 5
        ? "#2E7D32"
        : pctChange <= -5
          ? "#DC2626"
          : "#D97706";

  return (
    <div className="flex items-center justify-end gap-2">
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className="block">
        <polyline points={pts} fill="none" stroke={stroke} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {pctChange !== null && (
        <span
          className={`font-mono text-[10px] font-semibold ${
            pctChange >= 5
              ? "text-success-text"
              : pctChange <= -5
                ? "text-error-text"
                : "text-warning-text"
          }`}
          title={`Prev period spend: ₹${Math.round(prevTotal ?? 0).toLocaleString("en-IN")}`}
        >
          {pctChange > 0 ? "+" : ""}
          {pctChange.toFixed(0)}%
        </span>
      )}
    </div>
  );
}

/** Category chip — Women (rose) / Men (sky) / Unisex (purple), matching
 *  Saadaa's category conventions from the Apps Script product-listing
 *  sheet (SD = Women, SM = Men, SU = Unisex). */
function CategoryChip({ category }: { category: string }) {
  const cls =
    category === "Women"
      ? "bg-[#FDF2F8] text-[#BE185D]"
      : category === "Men"
        ? "bg-info-bg text-info-text"
        : "bg-[#F5F3FF] text-[#6D28D9]";
  return (
    <span
      className={`inline-flex whitespace-nowrap items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${cls}`}
    >
      {category}
    </span>
  );
}

/** DoQ (Days of Quantity) cell — colored by supply health.
 *  <15d = critical (red), 15-45d = healthy (green), 45-90d = comfortable
 *  (blue), >90d = overstocked (amber). Zero rows would signal the
 *  master SKU has no matching MapleMonk data. */
function DoqCell({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return <span className="text-text-tertiary">—</span>;
  const cls =
    value < 15
      ? "text-error-text"
      : value <= 45
        ? "text-success-text"
        : value <= 90
          ? "text-info-text"
          : "text-warning-text";
  return <span className={cls}>{value.toFixed(1)}d</span>;
}

/** OOS-days cell — pale red pill if there's any stockout in the window,
 *  green if the master SKU was in-stock every day. */
function OosCell({ value, outOf }: { value: number | null | undefined; outOf: number }) {
  if (value === null || value === undefined) return <span className="text-text-tertiary">—</span>;
  const critical = value >= outOf / 2;
  const clean = value === 0;
  const cls = clean
    ? "text-success-text"
    : critical
      ? "text-error-text"
      : "text-warning-text";
  return (
    <span className={cls}>
      {value}
      <span className="text-text-tertiary">/{outOf}</span>
    </span>
  );
}

/** ROAS chip -- displayed as Meta's own decimal-multiplier convention
 *  ("3.5x" not "350%"). The underlying value is Meta's own
 *  action_values.omni_purchase / spend (stored in ad_lifecycle.conv_value
 *  / spend), so this matches what a merchant reads in Ads Manager.
 *
 *  Break points: >= 3.0x green (Meta's typical "winner" threshold),
 *  >= 1.5x blue (profitable at typical margins), >= 1.0x amber
 *  (breaking even on ad spend alone), < 1.0x red (losing money). */
function RoasChip({ roas }: { roas: number | null | undefined }) {
  if (roas === null || roas === undefined) return <span className="text-text-tertiary">—</span>;
  const cls =
    roas >= 3.0
      ? "bg-success-bg text-success-text"
      : roas >= 1.5
        ? "bg-info-bg text-info-text"
        : roas >= 1.0
          ? "bg-warning-bg text-warning-text"
          : "bg-error-bg text-error-text";
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold ${cls}`}>
      {roas.toFixed(2)}x
    </span>
  );
}

function CpisView() {
  const [window_, setWindow] = useState<CpisUtmWindow>("30d");
  const [search, setSearch] = useState("");
  const [onlyMatched, setOnlyMatched] = useState(true);
  const [sort, setSort] = useState<CpisUtmSort>("attributed_units");
  // Attribution mode toggle:
  //   equal          - ad_spend / cost_per_order / cost_per_unit_sold / roas
  //   value_weighted - ad_spend_vw / cost_per_order_vw / cost_per_unit_sold_vw / roas_vw
  // Both columns come from the same /cpis-utm response -- no refetch on toggle.
  const [attributionMode, setAttributionMode] =
    useState<"equal" | "value_weighted">("equal");
  // Date range picker -- same pattern as Ads Analyse (2026-09-01):
  // a preset <select> plus two <input type="date"> fields always
  // visible. When both dates are filled, the /cpis-utm endpoint hits
  // the daily-sum path (cpis_by_sku_daily); when empty, falls back to
  // the pre-computed cpis_by_sku_utm rollup for `window_`.
  const [datePreset, setDatePreset] = useState<string>("30d");
  const [fromDate, setFromDate] = useState<string>(() => {
    const d = new Date();
    d.setDate(d.getDate() - 29);
    return d.toISOString().slice(0, 10);
  });
  const [toDate, setToDate] = useState<string>(() => new Date().toISOString().slice(0, 10));
  // Data-freshness probe -- fetched once on mount from
  // /cpis-utm/data-freshness. Used to (a) cap the picker's `to_date`
  // default to whichever underlying table is stalest (Meta insights
  // and Shopify orders drift at different rates), and (b) show a
  // "Data through <date>" indicator so the merchant sees the freshness
  // at a glance instead of picking a range that ends in empty days.
  const [freshness, setFreshness] = useState<CpisDataFreshness | null>(null);
  useEffect(() => {
    fetchCpisDataFreshness()
      .then((f) => {
        setFreshness(f);
        // Use max_daily_day (the freshest day for which BOTH Meta spend
        // AND Shopify orders exist -- it's min(max_meta, max_orders)).
        // Fall back to max_meta_day if daily table hasn't been
        // populated. Only auto-fill when the user hasn't touched the
        // picker yet (fromDate/toDate still equal their initial values).
        const cap = f.max_daily_day || f.max_meta_day;
        if (!cap) return;
        setToDate(cap);
        // Slide fromDate back 29 days from cap for a stable "last 30d"
        // default anchored on data reality, not wall-clock today.
        const capDate = new Date(cap);
        capDate.setDate(capDate.getDate() - 29);
        setFromDate(capDate.toISOString().slice(0, 10));
      })
      .catch(() => {
        /* silent: leave the naive today-based defaults if probe fails */
      });
  }, []);
  // Collapse toggles for each of the three analytics blocks (KPI strip,
  // saturation curve, main table). Default: everything open. Merchant
  // can fold anything they don't need so the section stops eating scroll.
  const [openKpi, setOpenKpi] = useState(true);
  const [openSaturation, setOpenSaturation] = useState(true);
  const [openTable, setOpenTable] = useState(true);
  // Row-click drilldown -- opens the ads modal for the clicked master
  // SKU showing every name-matched ad's status / category / spend /
  // ROAS / cost-per-NCP. Row includes the product_name so the modal
  // header can show something readable.
  const [drilldownSku, setDrilldownSku] = useState<{
    master_sku: string;
    product_name: string | null;
  } | null>(null);

  const [rows, setRows] = useState<CpisUtmRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const filters = useMemo(
    () =>
      fromDate && toDate
        ? { from_date: fromDate, to_date: toDate, search: search || undefined, only_matched: onlyMatched, sort }
        : { window: window_, search: search || undefined, only_matched: onlyMatched, sort },
    [fromDate, toDate, window_, search, onlyMatched, sort],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchCpisUtm({ ...filters, limit: PAGE_SIZE, offset: 0 })
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setTotal(res.total);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Could not reach the FastAPI backend.");
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
      const res = await fetchCpisUtm({ ...filters, limit: PAGE_SIZE, offset: rows.length });
      setRows((prev) => [...prev, ...res.rows]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load more rows.");
    } finally {
      setLoadingMore(false);
    }
  }

  const windowLabel = window_;
  const windowFrom = rows[0]?.window_from ?? null;
  const windowTo = rows[0]?.window_to ?? null;

  return (
    <>
      <p className="text-sm text-text-secondary">
        Cost per master SKU (women=SD, men=SM, unisex=SU prefix), with ads matched by <strong>SKU code appearing in ad_name</strong>
        (word-boundary regex on <code className="font-mono text-xs">ad_lifecycle.ad_name</code>). Product identity, price,
        variants, and inventory come from the live Shopify catalog. UTM-based per-order attribution is reserved for the
        per-color-variant drill-down (coming soon) and is intentionally not shown here.
      </p>

      {/* Collapsible KPI strip. */}
      <CollapsibleSection
        title="Aggregate KPIs"
        subtitle="Sum of name-matched metrics across every SKU in view"
        open={openKpi}
        onToggle={() => setOpenKpi((v) => !v)}
      >
        {rows.length > 0 && (
          <CpisKpiStrip
            rows={rows}
            windowLabel={
              fromDate && toDate
                ? `${fromDate} → ${toDate}`
                : `Last ${window_}`
            }
          />
        )}
      </CollapsibleSection>

      {/* Collapsible saturation curve. */}
      <CollapsibleSection
        title="Saturation curve"
        subtitle="Spend vs conversions -- shape of diminishing returns across all ads"
        open={openSaturation}
        onToggle={() => setOpenSaturation((v) => !v)}
      >
        <SaturationCurveSection masterSkuFilter={null} />
      </CollapsibleSection>

      {/* Collapsible "Analytics table" block. Wraps the filter bar +
          main SKU-level table so the merchant can fold the whole
          scrolling grid away when they only care about the top
          summary cards above. Toggled independently from KPI /
          Saturation. */}
      <CollapsibleSection
        title="Analytics table"
        subtitle={`${total.toLocaleString()} SKUs, filterable + sortable`}
        open={openTable}
        onToggle={() => setOpenTable((v) => !v)}
      >
      {/* Filter bar. Kwikengage puts the window pills flush left, then a
          search box, then dropdowns/toggles trailing to the right. The
          whole strip lives inside one card so it reads as a single
          control zone, not a scatter of chips. */}
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border-primary bg-white p-3">
        {/* Date range picker -- ported directly from Ads Analyse
            (AdsAnalyse.tsx :720). A preset <select> auto-fills the two
            date inputs; typing directly into either input flips the
            preset to "custom" so the two controls always stay in sync. */}
        <select
          value={datePreset}
          onChange={(e) => {
            const v = e.target.value;
            setDatePreset(v);
            const today = new Date().toISOString().slice(0, 10);
            const daysAgo = (n: number) => {
              const d = new Date();
              d.setDate(d.getDate() - n);
              return d.toISOString().slice(0, 10);
            };
            if (v === "all")       { setFromDate(""); setToDate(""); }
            else if (v === "today") { setFromDate(today); setToDate(today); }
            else if (v === "7d")   { setFromDate(daysAgo(6));  setToDate(today); }
            else if (v === "14d")  { setFromDate(daysAgo(13)); setToDate(today); }
            else if (v === "30d")  { setFromDate(daysAgo(29)); setToDate(today); }
            else if (v === "90d")  { setFromDate(daysAgo(89)); setToDate(today); }
          }}
          className="rounded-md border border-border-primary bg-white px-2 py-1 text-[13px] text-text-primary focus:border-accent-yellow focus:outline-none"
          title="Date-range window applied to CPIS metrics"
        >
          <option value="all">All time (uses pre-computed rollup)</option>
          <option value="today">Today</option>
          <option value="7d">Last 7 days</option>
          <option value="14d">Last 14 days</option>
          <option value="30d">Last 30 days</option>
          <option value="90d">Last 90 days</option>
          <option value="custom">Custom…</option>
        </select>
        <input
          type="date"
          value={fromDate}
          onChange={(e) => { setFromDate(e.target.value); setDatePreset("custom"); }}
          className="rounded-md border border-border-primary bg-white px-2 py-1 text-[13px] text-text-primary focus:border-accent-yellow focus:outline-none"
          title="Window start (YYYY-MM-DD)"
        />
        <span className="text-[12px] text-text-secondary">→</span>
        <input
          type="date"
          value={toDate}
          onChange={(e) => { setToDate(e.target.value); setDatePreset("custom"); }}
          className="rounded-md border border-border-primary bg-white px-2 py-1 text-[13px] text-text-primary focus:border-accent-yellow focus:outline-none"
          title="Window end (YYYY-MM-DD)"
        />
        {fromDate && toDate && (
          <span
            className="rounded-full bg-sky-100 px-2 py-0.5 text-[10px] font-semibold text-sky-800"
            title="Daily-sum path (cpis_by_sku_daily) for this exact date range"
          >
            windowed
          </span>
        )}
        {freshness && (
          <span
            className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-800"
            title={
              `Meta insights through ${freshness.max_meta_day ?? "-"}` +
              ` · Shopify orders through ${freshness.max_orders_day ?? "-"}` +
              ` · cpis_by_sku_daily through ${freshness.max_daily_day ?? "-"}`
            }
          >
            Data through {freshness.max_daily_day ?? freshness.max_meta_day ?? "?"}
          </span>
        )}
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search master SKU…"
          className="w-48 rounded-md border border-border-primary bg-white px-3 py-1.5 text-[13px] text-text-primary placeholder:text-text-tertiary focus:border-accent-yellow focus:outline-none"
        />
        <label className="flex items-center gap-1.5 text-[13px] text-text-primary">
          <input type="checkbox" checked={onlyMatched} onChange={(e) => setOnlyMatched(e.target.checked)} />
          Only SKUs with attributed orders
        </label>
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as CpisUtmSort)}
          className="rounded-md border border-border-primary bg-white px-2 py-1.5 text-[13px] text-text-primary focus:border-accent-yellow focus:outline-none"
        >
          {UTM_SORT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              Sort: {o.label}
            </option>
          ))}
        </select>
        {/* Attribution-mode toggle. Both columns come from the same
            response -- the toggle just swaps which set of 4 cells the
            Last-Click group renders. No refetch. See refresh_cpis_utm.py. */}
        <div className="flex overflow-hidden rounded-md border border-border-primary">
          {(["equal", "value_weighted"] as const).map((mode) => (
            <button
              key={mode}
              onClick={() => setAttributionMode(mode)}
              title={
                mode === "equal"
                  ? "Ad spend split equally across all orders the ad drove, then within each order by line-item revenue"
                  : "Ad spend split proportional to each order's total value — larger baskets absorb more spend"
              }
              className={`px-3 py-1.5 text-[12px] font-medium transition-colors ${
                attributionMode === mode
                  ? "bg-slate-900 text-white"
                  : "bg-white text-text-secondary hover:bg-bg-surface hover:text-text-primary"
              }`}
            >
              {mode === "equal" ? "Equal / order" : "Value-weighted"}
            </button>
          ))}
        </div>
        <span className="ml-auto text-[11px] text-text-secondary">{total.toLocaleString()} SKUs</span>
      </div>

      {error && <div className="rounded-md border border-error-mid bg-error-bg p-3 text-sm text-error-text">{error}</div>}
      {loading ? (
        <p className="text-sm text-text-secondary">Loading…</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border-primary bg-white shadow-sm">
          {/* min-w on the table forces the 23-column layout to overflow
              its parent so the outer overflow-x-auto shows a scrollbar
              instead of the browser squeezing every cell narrow enough
              to fit -- which produced "SGRY" for "CATEGORY" and made all
              DoQ pills unreadable. Headers get whitespace-nowrap for the
              same reason. */}
          <table className="w-max min-w-full text-left text-sm">
            <thead>
              {/* Kwikengage Campaigns-table pattern: uppercase small
                  labels with wide tracking, sitting on top of a hairline
                  bottom border. */}
              {/* Column groups (2026-08-31 simplified per user direction:
                  UTM columns removed — they'll come back only for the
                  per-color-variant drill-down). Order:
                    [PRODUCT] identity + price + variant counts (sticky
                      first two cols so they stay in view horizontally)
                    [NAME-MATCHED] primary attribution signal
                    [INVENTORY] units_in_stock
                  Colored top-border on the first col of each group is
                  kwikengage's column-grouping treatment. */}
              <tr className="whitespace-nowrap border-b border-border-primary text-[10px] font-semibold uppercase tracking-wider text-text-tertiary">
                {/* PRODUCT group (sticky). SKU Code is pinned to a
                    fixed w-[110px] so its right edge lines up EXACTLY
                    with Product's left-[110px] sticky offset -- without
                    the explicit width the SKU column was ~90px wide and
                    the 20px gap let non-sticky columns peek through
                    while horizontally scrolling. */}
                <th className="sticky left-0 z-10 w-[110px] min-w-[110px] bg-white px-4 py-3">SKU Code</th>
                <th className="sticky left-[110px] z-10 bg-white px-3 py-3" title="Shopify productType (with 'price test' / combo / bedsheet variants excluded)">Product</th>
                <th className="px-3 py-3">Category</th>
                <th className="px-3 py-3 text-right" title="Product list price (from variants[0].price)">Price</th>
                <th className="px-3 py-3 text-right" title="Distinct variant SKUs (size × color permutations)">Variants</th>
                <th className="px-3 py-3 text-right" title="Variant SKUs with inventoryQuantity > 0">In-Stock</th>
                {/* NAME-MATCHED group -- 2026-08-31: values are now
                    WINDOWED via raw_dump_meta insights (was previously
                    lifetime from ad_lifecycle). NCP is a proportional
                    approximation since ad_lifecycle only stores lifetime
                    NCP per ad. */}
                <th className="border-l border-border-soft px-3 py-3 text-right" title="Ads whose name contains this SKU code (word-boundary regex)">Match Ads</th>
                <th className="px-3 py-3 text-right" title="Active name-matched ads (ad_effective_status = ACTIVE). Signals how much creative is currently spending on this SKU family.">Active</th>
                <th className="px-3 py-3 text-right" title="Active ads categorised as Winner or Incremental Winner. Direct signal for 'creative worth scaling right now'.">Winners</th>
                <th className="px-3 py-3 text-right" title="Active-ad spend in the picked window, divided by window length in days. Average daily burn on ads still running.">Spend/Day</th>
                <th className="px-3 py-3 text-right" title="Daily spend sparkline for the picked window + % change vs. the previous same-length period. Green ≥ +5%, amber ±5%, red ≤ -5%.">Spend Trend</th>
                <th className="px-3 py-3 text-right" title="SUM of windowed spend for name-matched ads (from raw_dump_meta insights, in the picked date range)">Spend</th>
                <th className="px-3 py-3 text-right" title="Approximate windowed NCP: lifetime_ncp × (windowed_spend / lifetime_spend). Accurate when NCP scales linearly with spend within the window.">NCP</th>
                <th className="px-3 py-3 text-right" title="Windowed ROAS: conv_value / spend for name-matched ads within the picked date range">ROAS</th>
                <th className="px-3 py-3 text-right" title="New-customer ROAS approximation: (windowed NCP × AOV of last-click orders) / windowed spend. Meta's actions[first_time_customer_purchase] would be more accurate but isn't exposed as a flat column.">NC ROAS</th>
                {/* LAST-CLICK group -- pulled straight from
                    cpis_by_sku_utm which does order.utm_content → ad_id
                    → line_items.sku attribution. */}
                <th className="border-l border-border-soft px-3 py-3 text-right" title="Revenue from orders whose last-click UTM content maps to a name-matched ad, containing this SKU">LC Revenue</th>
                <th className="px-3 py-3 text-right" title="Orders whose last-click UTM content maps to a name-matched ad, containing this SKU">LC Orders</th>
                {/* 3 mode-dependent cells: LC Ad Spend, LC Cost/Order, LC ROAS.
                    Header labels the current attribution mode so the merchant
                    can see at a glance which set of numbers they're looking at. */}
                <th className="px-3 py-3 text-right" title={
                  attributionMode === "equal"
                    ? "Equal-per-order allocation: ad spend split evenly across orders driven, then within-order by line-item revenue"
                    : "Value-weighted allocation: ad spend split proportional to each order's total revenue"
                }>
                  LC Ad Spend
                  <span className="ml-1 text-[10px] text-text-tertiary">
                    ({attributionMode === "equal" ? "eq" : "vw"})
                  </span>
                </th>
                <th className="px-3 py-3 text-right" title="Ad spend / attributed orders (toggles with attribution mode)">
                  LC Cost/Order
                  <span className="ml-1 text-[10px] text-text-tertiary">
                    ({attributionMode === "equal" ? "eq" : "vw"})
                  </span>
                </th>
                <th className="px-3 py-3 text-right" title="Attributed revenue / allocated ad spend (toggles with attribution mode)">
                  LC ROAS
                  <span className="ml-1 text-[10px] text-text-tertiary">
                    ({attributionMode === "equal" ? "eq" : "vw"})
                  </span>
                </th>
                <th className="px-3 py-3 text-right" title="Average order value of last-click orders containing this SKU">LC AOV</th>
                <th className="px-3 py-3 text-right" title="Average units of THIS SKU per attributed order (some orders will have multiple units of the same SKU)">Qty/Order</th>
                <th className="px-3 py-3 text-right" title="Average selling price NET (attributed_revenue / attributed_units)">ASP Net</th>
                {/* HALO group -- basket-effect sales attributed to this
                    SKU when the ad's own name did NOT reference it.
                    Excluded from CPIS / ROAS above. See refresh_cpis_utm.py
                    (primary_weight, default 0.70). */}
                <th className="border-l border-border-soft px-3 py-3 text-right" title="Halo revenue: revenue from ad-driven orders where this SKU was in the basket but the ad name did not reference it. Weighted by (1 - primary_weight), split evenly across the non-matched line items.">Halo Rev</th>
                <th className="px-3 py-3 text-right" title="Halo units: weighted-count of THIS SKU appearing as a secondary basket item in ad-driven orders">Halo Units</th>
                <th className="px-3 py-3 text-right" title="Halo orders: number of ad-driven orders that included this SKU as a secondary basket item">Halo Orders</th>
                <th className="px-3 py-3 text-right" title="Halo ad-spend allocation: share of ad spend proportional to halo units. Adds to primary Spend for total spend that touched this SKU.">Halo Spend</th>
                {/* INVENTORY (Shopify) */}
                <th className="border-l border-border-soft px-3 py-3 text-right" title="Current ending inventory rolled to master SKU (latest per variant, all variants including any price-test variations)">Units in Stock</th>
                {/* MAPLEMONK inventory-planning (from bq_inventory_daily, variant-latest per master_sku) */}
                <th className="border-l border-border-soft px-3 py-3 text-right" title="MapleMonk current_stock rolled to master SKU (sum across variants, latest daily snapshot)">MM Stock</th>
                <th className="px-3 py-3 text-right" title="Sum of last-45-days sales from MapleMonk inventory-planning">Sales 45d</th>
                <th className="px-3 py-3 text-right" title="Days-of-Quantity at 30-day sales rate, averaged across every variant of this master SKU. 30d is the most accurate horizon for advertising decisions -- reactive enough to catch imminent stockouts, smooth enough not to whipsaw on a single big/small day.">DoQ 30</th>
                <th className="px-3 py-3 text-right" title="Worst-case OOS days in the last 30 days (max across variants)">OOS 30d</th>
                <th className="px-3 py-3 text-right" title="Lead time (days) from MapleMonk — max across variants for conservative planning">Lead Time</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.master_sku}
                  onClick={() => setDrilldownSku({ master_sku: row.master_sku, product_name: row.product_name })}
                  className="cursor-pointer border-b border-border-soft hover:bg-bg-surface"
                  title={`Click to see every ad matched to ${row.master_sku}`}
                >
                  {/* PRODUCT group (sticky) -- must match the header's
                      w-[110px] so the sticky Product cell docks flush
                      against SKU Code with no gap for scrolled columns
                      to bleed through. */}
                  <td className="sticky left-0 z-10 w-[110px] min-w-[110px] bg-white px-4 py-2.5 font-mono text-[13px] font-medium text-text-primary">
                    {row.master_sku}
                  </td>
                  <td className="sticky left-[110px] z-10 bg-white px-3 py-2.5 text-[12px] text-text-primary max-w-[220px] truncate" title={row.product_name ?? undefined}>
                    {row.product_name ?? <span className="text-text-tertiary">—</span>}
                  </td>
                  <td className="px-3 py-2.5 text-[12px]">
                    {row.category ? (
                      <CategoryChip category={row.category} />
                    ) : (
                      <span className="text-text-tertiary">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-[12px] text-text-primary">
                    {row.price_min !== null && row.price_max !== null
                      ? row.price_min === row.price_max
                        ? fmtINRCompact(row.price_min)
                        : `${fmtINRCompact(row.price_min)}–${fmtINRCompact(row.price_max)}`
                      : "—"}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-[12px] text-text-primary">
                    {row.variant_count ?? "—"}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-[12px] text-text-primary">
                    {row.available_variant_count !== null && row.variant_count !== null ? (
                      <span>
                        <span
                          className={
                            row.available_variant_count === 0
                              ? "text-error-text"
                              : row.available_variant_count < row.variant_count / 2
                                ? "text-warning-text"
                                : "text-success-text"
                          }
                        >
                          {row.available_variant_count}
                        </span>
                        <span className="text-text-tertiary">/{row.variant_count}</span>
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  {/* NAME-MATCHED group */}
                  <td className="border-l border-border-soft px-3 py-2.5 text-right font-mono text-[12px] text-text-secondary">
                    {row.name_matched_ads ?? "—"}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-[12px] text-text-primary">
                    {row.active_creative_count ?? "—"}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-[12px]">
                    {row.winning_creative_count !== null ? (
                      <span
                        className={
                          row.winning_creative_count > 0
                            ? "text-success-text font-semibold"
                            : "text-text-tertiary"
                        }
                      >
                        {row.winning_creative_count}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-[12px] text-text-primary">
                    {fmtINRFull(row.active_spend_per_day)}
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <LazySpendTrendCell masterSku={row.master_sku} window={window_} />
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-[12px] text-text-primary">
                    {fmtINRFull(row.name_matched_spend)}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-[12px] text-text-primary">
                    {fmtNumFull(row.name_matched_ncp)}
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <RoasChip roas={row.name_matched_roas_lifetime} />
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <RoasChip roas={row.name_matched_nc_roas} />
                  </td>
                  {/* LAST-CLICK group */}
                  <td className="border-l border-border-soft px-3 py-2.5 text-right font-mono text-[12px] text-text-primary">
                    {fmtINRFull(row.attributed_revenue)}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-[12px] text-text-primary">
                    {fmtNumFull(row.attributed_orders)}
                  </td>
                  {/* 3 mode-dependent cells -- toggle with the pill above. */}
                  <td className="px-3 py-2.5 text-right font-mono text-[12px] text-text-primary">
                    {fmtINRFull(
                      attributionMode === "equal" ? row.ad_spend : row.ad_spend_vw,
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-[12px] text-text-primary">
                    {fmtINRFull(
                      attributionMode === "equal" ? row.cost_per_order : row.cost_per_order_vw,
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <RoasChip roas={attributionMode === "equal" ? row.roas : row.roas_vw} />
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-[12px] text-text-primary">
                    {fmtINRFull(row.lc_avg_order_value)}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-[12px] text-text-primary">
                    {row.lc_avg_qty_per_order !== null ? row.lc_avg_qty_per_order.toFixed(2) : "—"}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-[12px] text-text-primary">
                    {fmtINRFull(row.avg_selling_price)}
                  </td>
                  {/* HALO group */}
                  <td className="border-l border-border-soft px-3 py-2.5 text-right font-mono text-[12px] text-text-secondary">
                    {fmtINRFull(row.halo_revenue)}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-[12px] text-text-secondary">
                    {fmtNumFull(row.halo_units)}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-[12px] text-text-secondary">
                    {fmtNumFull(row.halo_orders)}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-[12px] text-text-secondary">
                    {fmtINRFull(row.halo_spend)}
                  </td>
                  {/* INVENTORY (Shopify) */}
                  <td className="border-l border-border-soft px-3 py-2.5 text-right font-mono text-[12px] text-text-primary">
                    {fmtNumFull(row.units_in_stock)}
                  </td>
                  {/* MAPLEMONK inventory-planning */}
                  <td className="border-l border-border-soft px-3 py-2.5 text-right font-mono text-[12px] text-text-primary">
                    {fmtNumFull(row.mm_current_stock)}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-[12px] text-text-primary">
                    {fmtNumFull(row.mm_total_sales_45d)}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-[12px]">
                    <DoqCell value={row.mm_doq_30} />
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-[12px]">
                    <OosCell value={row.mm_oos_days_30} outOf={30} />
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-[12px] text-text-primary">
                    {row.mm_lead_time !== null ? `${row.mm_lead_time}d` : "—"}
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={29} className="px-4 py-6 text-center text-text-secondary">
                    No SKUs match these filters.
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
      </CollapsibleSection>
      {drilldownSku && (
        <MatchedAdsModal
          masterSku={drilldownSku.master_sku}
          productName={drilldownSku.product_name}
          onClose={() => setDrilldownSku(null)}
        />
      )}
    </>
  );
}


/** Accordion-style section header with a chevron toggle. Used to fold
 *  the KPI strip / saturation curve / main table so the CPIS page stops
 *  eating scroll when the merchant isn't looking at one of them. */
function CollapsibleSection({
  title,
  subtitle,
  open,
  onToggle,
  children,
}: {
  title: string;
  subtitle?: string;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-border-primary bg-white shadow-sm">
      <button
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-bg-surface"
        aria-expanded={open}
      >
        <div className="flex flex-col">
          <span className="text-[13px] font-semibold text-text-primary">{title}</span>
          {subtitle && <span className="text-[11px] text-text-secondary">{subtitle}</span>}
        </div>
        <span className={`text-[13px] text-text-secondary transition-transform ${open ? "rotate-180" : ""}`}>▼</span>
      </button>
      {open && <div className="border-t border-border-soft p-3">{children}</div>}
    </div>
  );
}

/** Modal that opens when a CPIS row is clicked. Fetches every ad whose
 *  ad_name contains the master SKU (word-boundary match) and shows them
 *  in a compact scrollable table with status + category + Meta metrics.
 *  ACTIVE ads sort first (via the endpoint's ORDER BY), so the merchant
 *  sees what's currently spending immediately. */
function MatchedAdsModal({
  masterSku,
  productName,
  onClose,
}: {
  masterSku: string;
  productName: string | null;
  onClose: () => void;
}) {
  const [ads, setAds] = useState<CpisMatchedAdRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<"all" | "active" | "paused">("all");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchCpisMatchedAds(masterSku)
      .then((res) => !cancelled && setAds(res.ads))
      .catch((err: unknown) =>
        !cancelled && setError(err instanceof ApiError ? err.message : "Could not load matched ads."),
      )
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [masterSku]);

  // ESC-to-close for keyboard users.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const filtered = ads.filter((a) => {
    if (statusFilter === "all") return true;
    if (statusFilter === "active") return a.ad_effective_status === "ACTIVE";
    return a.ad_effective_status !== "ACTIVE";
  });

  const totals = filtered.reduce(
    (acc, a) => {
      acc.spend += a.spend ?? 0;
      acc.ncp += a.ncp_count ?? 0;
      acc.conv += a.conv_value ?? 0;
      acc.impr += a.impressions ?? 0;
      acc.clicks += a.clicks ?? 0;
      return acc;
    },
    { spend: 0, ncp: 0, conv: 0, impr: 0, clicks: 0 },
  );
  const blendedRoas = totals.spend > 0 ? totals.conv / totals.spend : null;

  const activeCount = ads.filter((a) => a.ad_effective_status === "ACTIVE").length;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={`Ads matched to ${masterSku}`}
    >
      <div
        className="flex max-h-[90vh] w-full max-w-6xl flex-col overflow-hidden rounded-xl border border-border-primary bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal header */}
        <div className="flex items-start justify-between border-b border-border-primary px-5 py-4">
          <div className="min-w-0">
            <div className="text-[11px] uppercase tracking-wider text-text-tertiary">Ads matched to</div>
            <div className="mt-1 flex items-baseline gap-3">
              <span className="font-mono text-[20px] font-bold text-text-primary">{masterSku}</span>
              {productName && <span className="truncate text-sm text-text-secondary">{productName}</span>}
            </div>
            <div className="mt-1 text-[11px] text-text-tertiary">
              Every ad whose name contains &quot;{masterSku}&quot; as a whole word (case-insensitive). Sourced
              from <code className="font-mono">ad_lifecycle</code>. Active ads listed first.
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-full p-1.5 text-text-secondary hover:bg-bg-surface hover:text-text-primary"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {/* Filter toolbar */}
        <div className="flex flex-wrap items-center gap-2 border-b border-border-primary bg-bg-base px-5 py-3">
          <div className="flex overflow-hidden rounded-md border border-border-primary">
            {(["all", "active", "paused"] as const).map((s) => (
              <button
                key={s}
                onClick={() => setStatusFilter(s)}
                className={`px-3 py-1.5 text-[12px] font-medium transition-colors ${
                  statusFilter === s
                    ? "bg-slate-900 text-white"
                    : "bg-white text-text-secondary hover:bg-bg-surface hover:text-text-primary"
                }`}
              >
                {s === "all" ? `All (${ads.length})` : s === "active" ? `Active (${activeCount})` : `Paused (${ads.length - activeCount})`}
              </button>
            ))}
          </div>
          {!loading && filtered.length > 0 && (
            <div className="ml-auto flex items-center gap-4 text-[11px] text-text-secondary">
              <span>
                Total spend: <span className="font-mono font-semibold text-text-primary">{fmtINRFull(totals.spend)}</span>
              </span>
              <span>
                Total NCP: <span className="font-mono font-semibold text-text-primary">{fmtNumFull(totals.ncp)}</span>
              </span>
              <span>
                Blended ROAS: <RoasChip roas={blendedRoas} />
              </span>
            </div>
          )}
        </div>

        {/* Ads table */}
        <div className="flex-1 overflow-auto">
          {error && (
            <div className="m-4 rounded-md border border-error-mid bg-error-bg p-3 text-sm text-error-text">{error}</div>
          )}
          {loading ? (
            <p className="p-6 text-center text-sm text-text-secondary">Loading matched ads…</p>
          ) : filtered.length === 0 ? (
            <p className="p-6 text-center text-sm text-text-secondary">No ads match this filter.</p>
          ) : (
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="whitespace-nowrap border-b border-border-primary bg-bg-base text-[10px] font-semibold uppercase tracking-wider text-text-tertiary">
                  <th className="sticky top-0 bg-bg-base px-4 py-3">Ad Name</th>
                  <th className="sticky top-0 bg-bg-base px-3 py-3">Status</th>
                  <th className="sticky top-0 bg-bg-base px-3 py-3">Category</th>
                  <th className="sticky top-0 bg-bg-base px-3 py-3">Account</th>
                  <th className="sticky top-0 bg-bg-base px-3 py-3 text-right">Spend</th>
                  <th className="sticky top-0 bg-bg-base px-3 py-3 text-right">Impr</th>
                  <th className="sticky top-0 bg-bg-base px-3 py-3 text-right">CTR</th>
                  <th className="sticky top-0 bg-bg-base px-3 py-3 text-right">NCP</th>
                  <th className="sticky top-0 bg-bg-base px-3 py-3 text-right">Cost/NCP</th>
                  <th className="sticky top-0 bg-bg-base px-3 py-3 text-right">ROAS</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((ad) => (
                  <tr key={ad.ad_id} className="border-b border-border-soft hover:bg-bg-surface">
                    <td className="max-w-[340px] px-4 py-2 text-[12px] text-text-primary">
                      <div className="truncate" title={ad.ad_name ?? undefined}>
                        {ad.ad_name ?? <span className="text-text-tertiary">(unnamed)</span>}
                      </div>
                      <div className="mt-0.5 font-mono text-[10px] text-text-tertiary">{ad.ad_id}</div>
                    </td>
                    <td className="px-3 py-2">
                      <StatusPill status={ad.ad_effective_status} />
                    </td>
                    <td className="px-3 py-2">
                      {ad.category ? <CategoryFlagPill category={ad.category} /> : <span className="text-text-tertiary">—</span>}
                    </td>
                    <td className="max-w-[160px] truncate px-3 py-2 text-[11px] text-text-secondary" title={ad.account_name ?? undefined}>
                      {ad.account_name ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-[12px] text-text-primary">
                      {fmtINRFull(ad.spend)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-[12px] text-text-secondary">
                      {fmtNumFull(ad.impressions)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-[12px] text-text-secondary">
                      {ad.ctr !== null ? `${ad.ctr.toFixed(2)}%` : "—"}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-[12px] text-text-primary">
                      {fmtNumFull(ad.ncp_count)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-[12px] text-text-primary">
                      {fmtINRFull(ad.cost_per_ncp)}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <RoasChip roas={ad.roas} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

/** ACTIVE / PAUSED / IN_PROCESS pill, matches Meta's Ads Manager
 *  convention (green = ACTIVE, gray = otherwise). */
function StatusPill({ status }: { status: string | null }) {
  if (!status) return <span className="text-text-tertiary">—</span>;
  const isActive = status === "ACTIVE";
  const cls = isActive ? "bg-success-bg text-success-text" : "bg-bg-muted text-text-secondary";
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${cls}`}>
      {status}
    </span>
  );
}

/** Category pill (Winner / Incremental Winner / P0 / P1 / P2 / Result
 *  Awaited / Discarded) using CTD's existing .cat-* CSS classes. */
function CategoryFlagPill({ category }: { category: string }) {
  const key = category
    .toLowerCase()
    .replace(/incremental winner/, "iw")
    .replace(/winner/, "winner")
    .replace(/p0.*/, "priority")
    .replace(/p1.*/, "a1")
    .replace(/p2.*/, "a2")
    .replace(/result awaited/, "ra")
    .replace(/discarded/, "disc")
    .trim();
  return <span className={`cat-badge cat-${key}`}>{category}</span>;
}

/** Aggregate KPI strip for the name-matched CPIS view. Sums are over
 *  whatever rows are currently loaded (respecting only_matched + search).
 *  All numbers come from the name-matched columns (ads whose ad_name
 *  contains the master SKU) and the product/inventory context, since UTM
 *  attribution is deferred to the per-color-variant view. */
function CpisKpiStrip({ rows, windowLabel }: { rows: CpisUtmRow[]; windowLabel: string }) {
  const totalSkus = rows.length;
  // Distinct-ad de-dupe isn't possible client-side (ad_ids aren't in the
  // row payload), so surface the raw sum labeled "matches" -- clear
  // it's (ad × SKU) pairs, not distinct ads.
  const totalMatches = rows.reduce((s, r) => s + (r.name_matched_ads ?? 0), 0);
  const totalSpend = rows.reduce((s, r) => s + (r.name_matched_spend ?? 0), 0);
  const totalNcp = rows.reduce((s, r) => s + (r.name_matched_ncp ?? 0), 0);
  const totalStock = rows.reduce((s, r) => s + (r.units_in_stock ?? 0), 0);
  const totalVariants = rows.reduce((s, r) => s + (r.variant_count ?? 0), 0);
  const totalAvailable = rows.reduce((s, r) => s + (r.available_variant_count ?? 0), 0);
  const blendedCostPerNcp = totalNcp > 0 ? totalSpend / totalNcp : null;

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <KwikTile
        icon={<span>◱</span>}
        iconColor="sky"
        label="Master SKUs"
        value={fmtNumCompact(totalSkus)}
        subLine="in current view"
      />
      <KwikTile
        icon={<span>✦</span>}
        iconColor="purple"
        label="Name matches"
        value={fmtNumCompact(totalMatches)}
        subLine="ads × SKU pairs"
      />
      <KwikTile
        icon={<span>₹</span>}
        iconColor="amber"
        label="Ad spend"
        value={fmtINRCompact(totalSpend)}
        subLine={windowLabel}
      />
      <KwikTile
        icon={<span>🛒</span>}
        iconColor="emerald"
        label="NCP"
        value={fmtNumCompact(totalNcp)}
        subLine={windowLabel}
      />
      <KwikTile
        icon={<span>💸</span>}
        iconColor={blendedCostPerNcp !== null && blendedCostPerNcp <= 500 ? "emerald" : "rose"}
        label="Cost / NCP (blended)"
        value={blendedCostPerNcp !== null ? fmtINRCompact(blendedCostPerNcp) : "—"}
        subLine={windowLabel}
      />
      <KwikTile
        icon={<span>📦</span>}
        iconColor="teal"
        label="Units in stock"
        value={fmtNumCompact(totalStock)}
        subLine={`${totalAvailable}/${totalVariants} variants available`}
      />
    </div>
  );
}

