"use client";

/**
 * Creative Testing — the focused view for evaluating recently-launched
 * creatives. Always filters ads by `ad_created_date` inside the picked
 * window (defaults to Last 30 Days) -- unlike Ads Analyse which is the
 * full lifetime table with a windowed-overlay option. The two coexist:
 * Creative Testing answers "how are the ads I launched recently
 * performing?"; Ads Analyse answers "what's the current state of every
 * ad we've ever run?".
 *
 * KPI strip is the classic CTD Creative Testing set (matches the old
 * AnalyticsDashboard's row): Total Ads · Total Spend · Purchases · NCP ·
 * FTEWV · Avg ROAS · Avg Cost/NCP · Avg Cost/FTEWV. Category KwikTiles
 * (Incremental Winner ... Discarded) sit below and click-to-filter.
 * Table is a slim 10-column view -- name, account, category, F1..F4,
 * ad_created_date, spend, ROAS, cost/NCP, cost/FTEWV, purchases.
 *
 * Reuses fetchAdsAnalyse with date_field="created" + a required date
 * range so the server does the filtering.
 */

import { useEffect, useMemo, useState } from "react";
import {
  AdsAnalyseRow,
  AdsAnalyseTotals,
  ApiError,
  fetchAdsAnalyse,
} from "@/lib/api";
import { ExportButton } from "@/components/ExportButton";

const PAGE_SIZE = 100;

// Same category catalog + colors as the wider Ads Analyse view -- users
// switch between the two sections and the badges shouldn't shift.
type CategoryKey =
  | "Incremental Winner"
  | "Winner"
  | "P0 analysis"
  | "P1 analysis"
  | "P2 analysis"
  | "Result Awaited"
  | "Discarded";
const CATEGORY_ORDER: CategoryKey[] = [
  "Incremental Winner",
  "Winner",
  "P0 analysis",
  "P1 analysis",
  "P2 analysis",
  "Result Awaited",
  "Discarded",
];
const CAT_CLASS: Record<CategoryKey, string> = {
  "Incremental Winner": "cat-iw",
  Winner: "cat-winner",
  "P0 analysis": "cat-priority",
  "P1 analysis": "cat-a1",
  "P2 analysis": "cat-a2",
  "Result Awaited": "cat-ra",
  Discarded: "cat-disc",
};
type DateFieldKey = "created" | "first_seen" | "delivery";
const DATE_FIELDS: { key: DateFieldKey; label: string; hint: string }[] = [
  { key: "created",    label: "Created date",   hint: "Ad went live in Meta on this day (default -- what CTD Creative Testing uses)." },
  { key: "first_seen", label: "First seen",     hint: "First day this ad had any insights row (impressions began delivering)." },
  { key: "delivery",   label: "Delivery date",  hint: "Keep every ad, but re-sum spend/impressions/etc. over daily rows in the picked window." },
];

// Naming-convention tokens Meta ad-ops uses in ad_name. Values are the
// substring passed to the backend's ILIKE filter; labels are what the
// merchant reads. Kept in a shared constant so the same list can seed
// the dropdown in the future filter grid + any URL-hash preset.
const CONTENT_TYPES: { key: string; label: string }[] = [
  { key: "IFAD",   label: "IFAD" },
  { key: "GAD",    label: "Graphic AD" },
  { key: "VID",    label: "Video" },
  { key: "STATIC", label: "Static" },
];

// Status values match ad_lifecycle.ad_effective_status. Full-text so
// the merchant doesn't have to know Meta's internal enum spelling.
const AD_STATUSES: string[] = [
  "ACTIVE",
  "PAUSED",
  "WITH_ISSUES",
  "CAMPAIGN_PAUSED",
  "ADSET_PAUSED",
  "ARCHIVED",
];

const DATE_PRESETS: { key: string; label: string; days: number | null; thisMonth?: boolean }[] = [
  { key: "7d",         label: "Last 7 days",   days: 6 },
  { key: "14d",        label: "Last 14 days",  days: 13 },
  { key: "30d",        label: "Last 30 days",  days: 29 },
  { key: "60d",        label: "Last 60 days",  days: 59 },
  { key: "90d",        label: "Last 90 days",  days: 89 },
  { key: "thisMonth",  label: "This Month",    days: null, thisMonth: true },
  { key: "custom",     label: "Custom…",       days: null },
];

const today = () => new Date().toISOString().slice(0, 10);
const daysAgo = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
};
const firstOfThisMonth = () => {
  const d = new Date();
  d.setDate(1);
  return d.toISOString().slice(0, 10);
};

// Product Focus buckets -- verbatim port of CTD's Product-in-Focus
// detection off ad_name substrings. Matches what the merchant sees on
// the legacy dashboard's Product Focus strip. Priority top-down; the
// first bucket wins.
type ProductFocusKey = "Home" | "Category" | "Collection" | "Product" | "Others";
const PRODUCT_FOCUS_ORDER: ProductFocusKey[] = ["Home", "Category", "Collection", "Product", "Others"];
const PRODUCT_FOCUS_COLOR: Record<ProductFocusKey, string> = {
  Home: "#3B6BF5",
  Category: "#0891B2",
  Collection: "#2E7D32",
  Product: "#D97706",
  Others: "#9A9384",
};
function detectProductFocus(name: string | null | undefined): ProductFocusKey {
  const n = (name || "").toUpperCase();
  if (n.includes("HP+") || /(^|[_ +-])HP([_ +-]|$)/.test(n) || n.includes("HOME")) return "Home";
  if (n.includes("CTG") || n.includes("CATEGORY")) return "Category";
  if (n.includes("CLP") || n.includes("COLLECTION")) return "Collection";
  if (n.includes("PDP") || n.includes("VRP") || n.includes("CTP") || n.includes("PRODUCT")) return "Product";
  return "Others";
}

// Creative Focus buckets -- the four merchant-facing ctypes. Same
// classifier as detectCtype below, only labelled differently for the
// pill strip; keeping the two side-by-side would drift as CTD evolves.
type CreativeFocusKey = "IFAD" | "GAD" | "VID" | "Others";
const CREATIVE_FOCUS_ORDER: CreativeFocusKey[] = ["IFAD", "GAD", "VID", "Others"];
const CREATIVE_FOCUS_COLOR: Record<CreativeFocusKey, string> = {
  IFAD: "#7C3AED",
  GAD: "#D97706",
  VID: "#0891B2",
  Others: "#9A9384",
};
function detectCreativeFocus(name: string | null | undefined): CreativeFocusKey {
  const n = (name || "").toUpperCase();
  if (n.includes("IFAD")) return "IFAD";
  if (n.includes("GAD")) return "GAD";
  if (
    n.includes("VRP") || n.includes("NNC") || n.includes("VIDEO") ||
    n.includes("IGP") || n.includes("NO-ID") || /^VID-AD/.test(n) ||
    n.includes("OSP") || n.includes("CPL") || n.includes("USP") ||
    n.includes("CSR") || n.includes("ITE")
  ) return "VID";
  return "Others";
}

// Content-type detection from ad_name -- verbatim port of CTD's
// detectCtype() so the funnel matches the numbers you'd see on the
// legacy dashboard. Legacy tokens (VRP, NNC, VIDEO, IGP, NO-ID,
// VID-AD prefix) and the CT-team's later tokens (OSP, CPL, USP, CSR,
// ITE) all resolve to VID; STATIC is only when the ad name says so
// explicitly; IFAD and GAD take precedence in that order.
function detectCtype(name: string | null | undefined): "IFAD" | "Graphic AD" | "VID" | "STATIC" {
  const n = (name || "").toUpperCase();
  if (n.includes("IFAD")) return "IFAD";
  if (n.includes("GAD")) return "Graphic AD";
  if (
    n.includes("VRP") || n.includes("NNC") || n.includes("VIDEO") ||
    n.includes("IGP") || n.includes("NO-ID") || /^VID-AD/.test(n) ||
    n.includes("OSP") || n.includes("CPL") || n.includes("USP") ||
    n.includes("CSR") || n.includes("ITE")
  ) return "VID";
  if (n.includes("STATIC") || n.includes("_ST_") || n.includes("+ST+")) return "STATIC";
  return "VID";
}

// The 7 sub-categories the funnel shows, in the exact order CTD lays
// them out. Order matters -- the master row spans (Winner=2, P0=1,
// P1/P2=2, Awaited=1, Discarded=1) assume this order.
const FUNNEL_SUB: CategoryKey[] = [
  "Incremental Winner", "Winner", "P0 analysis",
  "P1 analysis", "P2 analysis", "Result Awaited", "Discarded",
];
const FUNNEL_SUB_SHORT: string[] = [
  "Inc. Winner", "Winner", "P0", "P1", "P2", "Awaited", "Discarded",
];

const CTYPES: ("IFAD" | "Graphic AD" | "VID" | "STATIC")[] = [
  "IFAD", "Graphic AD", "VID", "STATIC",
];

function fmtCompact(n: number | null | undefined) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e7) return `${(n / 1e7).toFixed(2)}Cr`;
  if (abs >= 1e5) return `${(n / 1e5).toFixed(2)}L`;
  if (abs >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return Math.round(n).toLocaleString();
}
function fmtMoney(n: number | null | undefined) {
  return n === null || n === undefined ? "—" : "₹" + fmtCompact(n);
}
function fmtNum(n: number | null | undefined, digits = 2) {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

/** CTD-style KPI card — mirrors assets/dashboard.css .kpi (26px mono
 *  value, 10px caps label, warm surface). Scoped to Creative Testing
 *  so the rest of the admin panel keeps its KwikTile look. */
function CtKpi({
  label,
  value,
  subLine,
}: {
  label: string;
  value: string;
  subLine?: React.ReactNode;
}) {
  return (
    <div
      className="flex flex-col gap-1 rounded-lg p-3"
      style={{ background: "#FFFFFF", border: "1px solid #E7E2D2" }}
    >
      <div
        style={{
          fontSize: "10px",
          fontWeight: 600,
          letterSpacing: "0.08em",
          color: "#9A9384",
          textTransform: "uppercase",
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontFamily: "'JetBrains Mono', ui-monospace, monospace",
          fontSize: "26px",
          fontWeight: 600,
          lineHeight: 1.1,
          color: "#161513",
        }}
      >
        {value}
      </div>
      {subLine && (
        <div style={{ fontSize: "11px", color: "#6E695E" }}>{subLine}</div>
      )}
    </div>
  );
}

const CAT_ACCENT: Record<CategoryKey, string> = {
  "Incremental Winner": "#2E7D32",
  Winner: "#4CAF50",
  "P0 analysis": "#D97706",
  "P1 analysis": "#3B6BF5",
  "P2 analysis": "#0891B2",
  "Result Awaited": "#9A9384",
  Discarded: "#B33A3A",
};

/** CTD-style category tile — colour-coded left border by category,
 *  active state raises the surface to the yellow accent. */
function CtCategoryTile({
  label,
  count,
  active,
  accent,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  accent: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex flex-col gap-1 rounded-lg p-3 text-left transition-colors"
      style={{
        background: active ? "#F0C61E" : "#FFFFFF",
        border: `1px solid ${active ? "#F0C61E" : "#E7E2D2"}`,
        borderLeft: `3px solid ${accent}`,
      }}
    >
      <div
        style={{
          fontSize: "10px",
          fontWeight: 600,
          letterSpacing: "0.08em",
          color: active ? "#161513" : "#6E695E",
          textTransform: "uppercase",
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontFamily: "'JetBrains Mono', ui-monospace, monospace",
          fontSize: "22px",
          fontWeight: 600,
          lineHeight: 1.1,
          color: "#161513",
        }}
      >
        {count.toLocaleString()}
      </div>
    </button>
  );
}

export function CreativeTesting() {
  const [preset, setPreset] = useState("30d");
  const [fromDate, setFromDate] = useState(daysAgo(29));
  const [toDate, setToDate] = useState(today());
  const [dateField, setDateField] = useState<DateFieldKey>("created");
  const [exclCopy, setExclCopy] = useState(true);
  const [account, setAccount] = useState("");
  const [campaign, setCampaign] = useState("");
  const [contentType, setContentType] = useState("");
  const [adStatus, setAdStatus] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<CategoryKey | "">("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<"spend" | "meta_roas" | "cost_per_ncp" | "cost_per_ftewv">("spend");

  const [rows, setRows] = useState<AdsAnalyseRow[]>([]);
  const [total, setTotal] = useState(0);
  const [totals, setTotals] = useState<AdsAnalyseTotals | null>(null);
  const [categoryCounts, setCategoryCounts] = useState<Record<string, number>>({});
  const [accountOptions, setAccountOptions] = useState<Set<string>>(new Set());
  // Campaign options accrete as rows load -- the backend does not expose a
  // dedicated "list campaigns" endpoint yet, so we seed the dropdown from
  // whatever campaign_names have appeared in this session. Same pattern as
  // accountOptions above.
  const [campaignOptions, setCampaignOptions] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showDefs, setShowDefs] = useState(false);

  // Funnel matrix -- (ctype × category) counts derived client-side from
  // the loaded rows. Runs on the CURRENT page slice, so scrolling in
  // more rows (loadMore) expands the numbers. That matches CTD's
  // behaviour: the funnel there also aggregates whatever rows are in
  // memory. If we later add server-side ctype categorisation, this
  // memo swaps out for an object off the response.
  const funnel = useMemo(() => {
    const perCtype: Record<string, {
      total: number;
      byCat: Record<CategoryKey, number>;
      f4: number;
    }> = {};
    for (const ct of CTYPES) {
      perCtype[ct] = {
        total: 0,
        f4: 0,
        byCat: {
          "Incremental Winner": 0, Winner: 0, "P0 analysis": 0,
          "P1 analysis": 0, "P2 analysis": 0, "Result Awaited": 0, Discarded: 0,
        },
      };
    }
    for (const r of rows) {
      const ct = detectCtype(r.ad_name);
      const bucket = perCtype[ct];
      if (!bucket) continue;
      bucket.total += 1;
      const cat = (r.category ?? "Discarded") as CategoryKey;
      if (bucket.byCat[cat] !== undefined) bucket.byCat[cat] += 1;
      if (r.f4_pass) bucket.f4 += 1;
    }
    const active = CTYPES.filter((c) => perCtype[c].total > 0);
    const grand = {
      total: 0,
      f4: 0,
      byCat: {
        "Incremental Winner": 0, Winner: 0, "P0 analysis": 0,
        "P1 analysis": 0, "P2 analysis": 0, "Result Awaited": 0, Discarded: 0,
      } as Record<CategoryKey, number>,
    };
    for (const ct of active) {
      grand.total += perCtype[ct].total;
      grand.f4 += perCtype[ct].f4;
      for (const s of FUNNEL_SUB) grand.byCat[s] += perCtype[ct].byCat[s];
    }
    return { perCtype, active, grand };
  }, [rows]);

  // Product Focus + Creative Focus counts, both client-side over the
  // currently-loaded rows -- matches CTD's Product-in-Focus /
  // Creative-Focus strip behaviour. Scoped to what's in memory so it
  // grows when you Load More; the aggregate KPI strip and category
  // tiles stay server-side.
  const productFocus = useMemo(() => {
    const map: Record<ProductFocusKey, number> = {
      Home: 0, Category: 0, Collection: 0, Product: 0, Others: 0,
    };
    for (const r of rows) map[detectProductFocus(r.ad_name)] += 1;
    return map;
  }, [rows]);
  const creativeFocus = useMemo(() => {
    const map: Record<CreativeFocusKey, number> = { IFAD: 0, GAD: 0, VID: 0, Others: 0 };
    for (const r of rows) map[detectCreativeFocus(r.ad_name)] += 1;
    return map;
  }, [rows]);

  const filters = useMemo(
    () => ({
      account_name: account || undefined,
      campaign_name: campaign || undefined,
      ad_effective_status: adStatus || undefined,
      content_type: contentType || undefined,
      search: search || undefined,
      category: categoryFilter || undefined,
      from_date: fromDate,
      to_date: toDate,
      date_field: dateField,
      excl_copy: exclCopy || undefined,
      sort,
    }),
    [account, campaign, adStatus, contentType, search, categoryFilter,
     fromDate, toDate, dateField, exclCopy, sort],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchAdsAnalyse({ ...filters, limit: PAGE_SIZE, offset: 0 })
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setTotal(res.total);
        setTotals(res.totals ?? null);
        setCategoryCounts(res.category_counts ?? {});
        setAccountOptions((prev) => {
          const next = new Set(prev);
          res.rows.forEach((r) => r.account_name && next.add(r.account_name));
          return next;
        });
        setCampaignOptions((prev) => {
          const next = new Set(prev);
          res.rows.forEach((r) => r.campaign_name && next.add(r.campaign_name));
          return next;
        });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Could not reach the backend.");
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [filters]);

  async function loadMore() {
    setLoadingMore(true);
    try {
      const res = await fetchAdsAnalyse({ ...filters, limit: PAGE_SIZE, offset: rows.length });
      setRows((prev) => [...prev, ...res.rows]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load more rows.");
    } finally {
      setLoadingMore(false);
    }
  }

  function applyPreset(key: string) {
    setPreset(key);
    const p = DATE_PRESETS.find((x) => x.key === key);
    if (!p) return;
    if (p.thisMonth) {
      setFromDate(firstOfThisMonth());
      setToDate(today());
    } else if (p.days !== null) {
      setFromDate(daysAgo(p.days));
      setToDate(today());
    }
  }

  return (
    <div
      className="flex flex-col gap-4 rounded-xl p-4"
      style={{ background: "#FAF8F5", border: "1px solid #E7E2D2" }}
    >
      {/* Header — CTD .page-hdr style */}
      <div className="flex flex-wrap items-baseline gap-3">
        <h1
          style={{
            fontFamily: "'Space Grotesk', system-ui, sans-serif",
            fontSize: "22px",
            fontWeight: 700,
            letterSpacing: "-0.01em",
            color: "#161513",
            margin: 0,
          }}
        >
          Creative Testing
        </h1>
        <button
          type="button"
          onClick={() => setShowDefs(true)}
          title="Show category definitions (Winner / P0 / P1 / P2 / Result Awaited / Discarded / F1-F4)"
          className="inline-flex items-center gap-1 rounded-md px-2 py-0.5"
          style={{
            fontSize: "11px",
            fontWeight: 500,
            background: "#FFFFFF",
            border: "1px solid #E7E2D2",
            color: "#6E695E",
          }}
        >
          <span aria-hidden="true">ⓘ</span>
          Definitions
        </button>
        <p
          style={{
            fontSize: "12px",
            color: "#6E695E",
            margin: 0,
            flex: "1 1 auto",
            minWidth: "240px",
          }}
        >
          Ads launched in the picked window — evaluate recently-shipped creatives before they age into the wider Ads Analyse view.
        </p>
      </div>

      {/* Filter-top card — CTD .filter-top */}
      <div
        className="flex flex-wrap items-center gap-3 rounded-lg p-3"
        style={{ background: "#F5F1EC", border: "1px solid #E7E2D2" }}
      >
        {/* Date-field selector — picks WHICH date the window filters on */}
        <select
          value={dateField}
          onChange={(e) => setDateField(e.target.value as DateFieldKey)}
          title={DATE_FIELDS.find((f) => f.key === dateField)?.hint}
          className="rounded-md px-2 py-1 text-xs"
          style={{ background: "#FAF8F5", border: "1px solid #E7E2D2", color: "#161513" }}
        >
          {DATE_FIELDS.map((f) => (
            <option key={f.key} value={f.key} title={f.hint}>{f.label}</option>
          ))}
        </select>
        {/* Preset pill row — CTD .preset-row */}
        <div className="flex flex-wrap items-center gap-1.5">
          {DATE_PRESETS.map((p) => {
            const active = preset === p.key;
            return (
              <button
                key={p.key}
                type="button"
                onClick={() => applyPreset(p.key)}
                className="rounded-full px-3 py-1 text-[11px] font-medium transition-colors"
                style={{
                  background: active ? "#F0C61E" : "transparent",
                  border: `1px solid ${active ? "#F0C61E" : "#E7E2D2"}`,
                  color: active ? "#161513" : "#6E695E",
                  fontFamily: "'Space Grotesk', system-ui, sans-serif",
                  letterSpacing: "0.02em",
                }}
              >
                {p.label}
              </button>
            );
          })}
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <input
            type="date"
            value={fromDate}
            onChange={(e) => { setFromDate(e.target.value); setPreset("custom"); }}
            className="rounded-md px-2 py-1 text-xs"
            style={{ background: "#FAF8F5", border: "1px solid #E7E2D2", color: "#161513" }}
          />
          <span style={{ fontSize: "12px", color: "#9A9384" }}>→</span>
          <input
            type="date"
            value={toDate}
            onChange={(e) => { setToDate(e.target.value); setPreset("custom"); }}
            className="rounded-md px-2 py-1 text-xs"
            style={{ background: "#FAF8F5", border: "1px solid #E7E2D2", color: "#161513" }}
          />
          {/* Excl. copy toggle — CTD .ct-toggle (yellow dot slides right when active) */}
          <button
            type="button"
            onClick={() => setExclCopy((v) => !v)}
            title="Hide ads whose ad_name contains 'copy' (Meta duplicates). Applies to KPI tiles + totals too."
            className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1"
            style={{
              fontSize: "11px",
              fontWeight: 500,
              background: exclCopy ? "#161513" : "#FAF8F5",
              border: `1px solid ${exclCopy ? "#161513" : "#E7E2D2"}`,
              color: exclCopy ? "#F5F1EC" : "#6E695E",
              fontFamily: "'Space Grotesk', system-ui, sans-serif",
              letterSpacing: "0.02em",
            }}
            aria-pressed={exclCopy}
          >
            <span
              className="inline-block h-2.5 w-2.5 rounded-full"
              style={{ background: exclCopy ? "#F0C61E" : "#C9C2AF" }}
            />
            Excl. copy
          </button>
        </div>
      </div>

      {/* Filter grid — CTD .filter-grid, warm surface, caps labels.
          Each dropdown is a base_where predicate on the backend so counts
          stay honest under the picked filters (vs client-side which would
          only filter the current 100-row page). */}
      <div
        className="grid grid-cols-1 gap-3 rounded-lg p-3 sm:grid-cols-2 md:grid-cols-4"
        style={{ background: "#F5F1EC", border: "1px solid #E7E2D2" }}
      >
        {[
          { label: "Campaign", value: campaign, setter: setCampaign, empty: "All campaigns", options: Array.from(campaignOptions).sort() },
          { label: "Content type", value: contentType, setter: setContentType, empty: "All content", options: CONTENT_TYPES.map((c) => c.key), labels: Object.fromEntries(CONTENT_TYPES.map((c) => [c.key, c.label])) as Record<string, string> },
          { label: "Status", value: adStatus, setter: setAdStatus, empty: "All statuses", options: AD_STATUSES },
          { label: "Account", value: account, setter: setAccount, empty: "All accounts", options: Array.from(accountOptions).sort() },
        ].map((f) => (
          <label key={f.label} className="flex flex-col gap-1">
            <span
              style={{
                fontSize: "10px",
                fontWeight: 600,
                letterSpacing: "0.08em",
                color: "#9A9384",
                textTransform: "uppercase",
              }}
            >
              {f.label}
            </span>
            <select
              value={f.value}
              onChange={(e) => f.setter(e.target.value)}
              className="rounded-md px-2 py-1 text-xs"
              style={{ background: "#FAF8F5", border: "1px solid #E7E2D2", color: "#161513" }}
            >
              <option value="">{f.empty}</option>
              {f.options.map((opt) => (
                <option key={opt} value={opt}>
                  {("labels" in f && f.labels ? f.labels[opt] : opt)}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>

      {/* KPI strip — CTD .kpi cards */}
      {totals && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
          <CtKpi
            label="Ads launched"
            value={totals.ad_count.toLocaleString()}
            subLine={`in ${DATE_PRESETS.find((p) => p.key === preset)?.label ?? "custom range"}`}
          />
          <CtKpi label="Total spend" value={fmtMoney(totals.spend)} />
          <CtKpi label="Purchases" value={fmtCompact(totals.purchases)} />
          <CtKpi
            label="NCP"
            value={fmtCompact(totals.ncp_count)}
            subLine="new-customer purchases"
          />
          <CtKpi
            label="FTEWV"
            value={fmtCompact(totals.ftewv_count)}
            subLine="first-time engaged"
          />
          <CtKpi
            label="Avg ROAS"
            value={totals.avg_meta_roas !== null ? totals.avg_meta_roas.toFixed(2) : "—"}
          />
          <CtKpi
            label="Cost / NCP"
            value={totals.ncp_count > 0 ? "₹" + fmtCompact(totals.spend / totals.ncp_count) : "—"}
          />
          <CtKpi
            label="Cost / FTEWV"
            value={totals.ftewv_count > 0 ? "₹" + fmtCompact(totals.spend / totals.ftewv_count) : "—"}
          />
        </div>
      )}

      {/* Category tiles — CTD-style, color-coded, click to filter */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
        {CATEGORY_ORDER.map((cat) => {
          const count = categoryCounts[cat] ?? 0;
          const selected = categoryFilter === cat;
          return (
            <CtCategoryTile
              key={cat}
              label={cat}
              count={count}
              active={selected}
              accent={CAT_ACCENT[cat]}
              onClick={() => setCategoryFilter(selected ? "" : cat)}
            />
          );
        })}
      </div>

      {/* Overview — Performance card. Ports CTD's op-grid: seven
          Meta-side rate KPIs derived from the aggregate totals + one
          highlighted CT ROAS tile on the right. All rates are blended
          (sum ÷ sum) so a Rs 200 ad with one sale doesn't outweigh a
          Rs 2,00,000 ad. Only rendered when totals arrived. */}
      {totals && (
        <div
          className="flex flex-col gap-3 rounded-lg p-4"
          style={{ background: "#FFFFFF", border: "1px solid #E7E2D2" }}
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div
              style={{
                fontFamily: "'Space Grotesk', system-ui, sans-serif",
                fontSize: "12px",
                fontWeight: 700,
                letterSpacing: "0.14em",
                color: "#161513",
                textTransform: "uppercase",
              }}
            >
              Overview <span style={{ color: "#9A9384" }}>—</span> Performance
            </div>
            <span
              className="rounded-full px-2 py-0.5"
              style={{
                fontSize: "9px",
                fontWeight: 700,
                letterSpacing: "0.1em",
                background: "#F5F1EC",
                border: "1px solid #E7E2D2",
                color: "#6E695E",
              }}
            >
              SUM &amp; AVG · EXCL. COPY
            </span>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
            {(() => {
              const impr = totals.impressions || 0;
              const spend = totals.spend || 0;
              const hookPct = impr > 0 ? (totals.three_sec_video_plays / impr) * 100 : null;
              const ctrPct = impr > 0 ? (totals.outbound_clicks / impr) * 100 : null;
              const engagePct = impr > 0 ? (totals.post_engagements / impr) * 100 : null;
              const thruplayPct = impr > 0 ? (totals.thruplays / impr) * 100 : null;
              const holdPct = totals.three_sec_video_plays > 0
                ? (totals.thruplays / totals.three_sec_video_plays) * 100
                : null;
              const ctRoas = spend > 0 ? totals.conv_value / spend : null;
              const tiles: {
                label: string;
                value: string;
                sub: string;
                highlight?: boolean;
              }[] = [
                { label: "Total spend", value: fmtMoney(totals.spend), sub: "Sum · INR" },
                { label: "Total impressions", value: fmtCompact(totals.impressions), sub: "Sum" },
                {
                  label: "Avg. hook rate",
                  value: hookPct === null ? "—" : hookPct.toFixed(2) + "%",
                  sub: "3-sec plays ÷ impressions",
                },
                {
                  label: "Avg. outbound CTR",
                  value: ctrPct === null ? "—" : ctrPct.toFixed(2) + "%",
                  sub: "Outbound clicks ÷ impressions",
                },
                {
                  label: "Avg. engagement rate",
                  value: engagePct === null ? "—" : engagePct.toFixed(2) + "%",
                  sub: "Post engagements ÷ impressions",
                },
                {
                  label: "Avg. thruplay rate",
                  value: thruplayPct === null ? "—" : thruplayPct.toFixed(2) + "%",
                  sub: "Thruplays ÷ impressions",
                },
                {
                  label: "Avg. hold rate",
                  value: holdPct === null ? "—" : holdPct.toFixed(2) + "%",
                  sub: "Thruplays ÷ 3-sec plays",
                },
                {
                  label: "CT ROAS",
                  value: ctRoas === null ? "—" : ctRoas.toFixed(2),
                  sub: "Conv. value ÷ spend",
                  highlight: true,
                },
              ];
              return tiles.map((t) => (
                <div
                  key={t.label}
                  className="flex flex-col gap-1 rounded-lg p-3"
                  style={{
                    background: t.highlight ? "#F0C61E" : "#FAF8F5",
                    border: `1px solid ${t.highlight ? "#F0C61E" : "#E7E2D2"}`,
                  }}
                >
                  <div
                    style={{
                      fontSize: "10px",
                      fontWeight: 600,
                      letterSpacing: "0.08em",
                      color: t.highlight ? "#161513" : "#9A9384",
                      textTransform: "uppercase",
                    }}
                  >
                    {t.label}
                  </div>
                  <div
                    style={{
                      fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                      fontSize: "24px",
                      fontWeight: 600,
                      lineHeight: 1.1,
                      color: "#161513",
                    }}
                  >
                    {t.value}
                  </div>
                  <div style={{ fontSize: "10px", color: t.highlight ? "#4A3E00" : "#9A9384" }}>
                    {t.sub}
                  </div>
                </div>
              ));
            })()}
          </div>
        </div>
      )}

      {/* Product Focus + Creative Focus pill strips — side-by-side.
          Counts are over the loaded rows, matching CTD's behaviour
          where the strip grows as pagination brings more rows in. */}
      {rows.length > 0 && (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {[
            {
              title: "Product in Focus",
              hint: "landing-page hierarchy from ad name",
              buckets: PRODUCT_FOCUS_ORDER.map((k) => ({
                key: k,
                label: k === "Home" ? "Home page"
                     : k === "Category" ? "Category page"
                     : k === "Collection" ? "Collection page"
                     : k === "Product" ? "Product page"
                     : "Others",
                count: productFocus[k],
                color: PRODUCT_FOCUS_COLOR[k],
              })),
            },
            {
              title: "Creative Focus",
              hint: "IFAD · GAD · VID · Others",
              buckets: CREATIVE_FOCUS_ORDER.map((k) => ({
                key: k,
                label: k === "VID" ? "Video" : k,
                count: creativeFocus[k],
                color: CREATIVE_FOCUS_COLOR[k],
              })),
            },
          ].map((panel) => (
            <div
              key={panel.title}
              className="flex flex-col gap-2 rounded-lg p-3"
              style={{ background: "#FFFFFF", border: "1px solid #E7E2D2" }}
            >
              <div className="flex items-baseline justify-between gap-2">
                <h3
                  style={{
                    fontFamily: "'Space Grotesk', system-ui, sans-serif",
                    fontSize: "13px",
                    fontWeight: 700,
                    color: "#161513",
                    margin: 0,
                  }}
                >
                  {panel.title}
                </h3>
                <span style={{ fontSize: "10px", color: "#9A9384" }}>{panel.hint}</span>
              </div>
              <div className="flex flex-wrap gap-2">
                {panel.buckets.map((b) => (
                  <div
                    key={b.key}
                    className="inline-flex items-center gap-2 rounded-full px-3 py-1"
                    style={{ background: "#FAF8F5", border: "1px solid #E7E2D2" }}
                  >
                    <span
                      className="inline-block h-2 w-2 rounded-full"
                      style={{ background: b.color }}
                    />
                    <span
                      style={{
                        fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                        fontSize: "12px",
                        fontWeight: 600,
                        color: "#161513",
                      }}
                    >
                      {b.count.toLocaleString()}
                    </span>
                    <span style={{ fontSize: "11px", color: "#6E695E" }}>{b.label}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Filter row — search + sort + clear + counters + export */}
      <div
        className="flex flex-wrap items-center gap-2 rounded-lg p-3"
        style={{ background: "#F5F1EC", border: "1px solid #E7E2D2" }}
      >
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search ad name…"
          className="w-64 rounded-md px-2 py-1 text-xs"
          style={{ background: "#FAF8F5", border: "1px solid #E7E2D2", color: "#161513" }}
        />
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as typeof sort)}
          className="rounded-md px-2 py-1 text-xs"
          style={{ background: "#FAF8F5", border: "1px solid #E7E2D2", color: "#161513" }}
        >
          <option value="spend">Sort: Spend</option>
          <option value="meta_roas">Sort: ROAS</option>
          <option value="cost_per_ncp">Sort: Cost / NCP</option>
          <option value="cost_per_ftewv">Sort: Cost / FTEWV</option>
        </select>
        <button
          onClick={() => {
            setSearch("");
            setAccount("");
            setCampaign("");
            setContentType("");
            setAdStatus("");
            setCategoryFilter("");
          }}
          className="rounded-md px-2 py-1 text-[11px] font-medium transition-colors"
          style={{ background: "#FAF8F5", border: "1px solid #E7E2D2", color: "#6E695E" }}
        >
          Clear filters
        </button>
        <span
          className="ml-auto text-[11px]"
          style={{ color: "#6E695E", fontFamily: "'JetBrains Mono', ui-monospace, monospace" }}
        >
          {loading ? "loading…" : `${rows.length.toLocaleString()} of ${total.toLocaleString()} ads`}
        </span>
        <ExportButton
          rows={rows as unknown as Record<string, unknown>[]}
          filename="creative_testing"
          window={preset}
          disabled={loading || !rows.length}
        />
      </div>

      {error && (
        <div
          className="rounded-md p-2 text-xs"
          style={{ background: "#FDEDEB", border: "1px solid #E9B4AE", color: "#8B2A22" }}
        >
          {error}
        </div>
      )}

      {/* Creative Type funnel — CTD .funnel-card, ctype × category matrix */}
      {funnel.active.length > 0 && (
        <div
          className="rounded-lg p-3"
          style={{ background: "#FFFFFF", border: "1px solid #E7E2D2" }}
        >
          <div className="mb-2 flex items-center justify-between">
            <h3
              style={{
                fontFamily: "'Space Grotesk', system-ui, sans-serif",
                fontSize: "13px",
                fontWeight: 700,
                color: "#161513",
                margin: 0,
              }}
            >
              Creative Type funnel
              <span style={{ marginLeft: "8px", fontWeight: 400, fontSize: "11px", color: "#9A9384" }}>
                distribution across categories
              </span>
            </h3>
            <span
              style={{
                fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                fontSize: "11px",
                color: "#9A9384",
              }}
            >
              {funnel.grand.total.toLocaleString()} ads loaded
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[11px]">
              <thead>
                <tr style={{ borderBottom: "1px solid #E7E2D2", background: "#F5F1EC" }}>
                  <th
                    className="px-2 py-1.5"
                    style={{
                      fontSize: "10px",
                      fontWeight: 600,
                      letterSpacing: "0.08em",
                      color: "#6E695E",
                      textTransform: "uppercase",
                    }}
                  >
                    Creative Type
                  </th>
                  <th
                    className="px-2 py-1.5 text-right"
                    style={{
                      fontSize: "10px",
                      fontWeight: 600,
                      letterSpacing: "0.08em",
                      color: "#6E695E",
                      textTransform: "uppercase",
                    }}
                  >
                    Total
                  </th>
                  {FUNNEL_SUB_SHORT.map((s) => (
                    <th
                      key={s}
                      className="px-2 py-1.5 text-right"
                      style={{
                        fontSize: "10px",
                        fontWeight: 600,
                        letterSpacing: "0.08em",
                        color: "#6E695E",
                        textTransform: "uppercase",
                      }}
                    >
                      {s}
                    </th>
                  ))}
                  <th
                    className="px-2 py-1.5 text-right"
                    style={{
                      fontSize: "10px",
                      fontWeight: 600,
                      letterSpacing: "0.08em",
                      color: "#6E695E",
                      textTransform: "uppercase",
                    }}
                    title="Count of ads passing F4 (win-rate quality gate)"
                  >
                    F4 ✓
                  </th>
                </tr>
              </thead>
              <tbody>
                {funnel.active.map((ct) => {
                  const row = funnel.perCtype[ct];
                  return (
                    <tr key={ct} style={{ borderBottom: "1px solid #F0EBDF" }} className="hover:bg-[#FAF8F5]">
                      <td className="px-2 py-1.5" style={{ fontWeight: 600, color: "#161513" }}>
                        {ct}
                      </td>
                      <td
                        className="px-2 py-1.5 text-right"
                        style={{ fontFamily: "'JetBrains Mono', ui-monospace, monospace", color: "#161513" }}
                      >
                        {row.total}
                      </td>
                      {FUNNEL_SUB.map((s) => {
                        const n = row.byCat[s];
                        const pct = row.total ? Math.round((n / row.total) * 100) : 0;
                        return (
                          <td
                            key={s}
                            className="px-2 py-1.5 text-right"
                            style={{ fontFamily: "'JetBrains Mono', ui-monospace, monospace", color: "#161513" }}
                          >
                            {n}
                            {n > 0 && (
                              <span style={{ marginLeft: "4px", fontSize: "10px", color: "#9A9384" }}>
                                {pct}%
                              </span>
                            )}
                          </td>
                        );
                      })}
                      <td
                        className="px-2 py-1.5 text-right"
                        style={{ fontFamily: "'JetBrains Mono', ui-monospace, monospace", color: "#2E7D32" }}
                      >
                        {row.f4}
                        {row.total > 0 && (
                          <span style={{ marginLeft: "4px", fontSize: "10px", color: "#9A9384" }}>
                            {Math.round((row.f4 / row.total) * 100)}%
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
                <tr
                  style={{
                    borderTop: "2px solid #E7E2D2",
                    background: "#F5F1EC",
                    fontWeight: 600,
                  }}
                >
                  <td className="px-2 py-1.5" style={{ color: "#161513" }}>
                    Grand Total
                  </td>
                  <td
                    className="px-2 py-1.5 text-right"
                    style={{ fontFamily: "'JetBrains Mono', ui-monospace, monospace", color: "#161513" }}
                  >
                    {funnel.grand.total}
                  </td>
                  {FUNNEL_SUB.map((s) => {
                    const n = funnel.grand.byCat[s];
                    const pct = funnel.grand.total ? Math.round((n / funnel.grand.total) * 100) : 0;
                    return (
                      <td
                        key={s}
                        className="px-2 py-1.5 text-right"
                        style={{ fontFamily: "'JetBrains Mono', ui-monospace, monospace", color: "#161513" }}
                      >
                        {n}
                        {n > 0 && (
                          <span style={{ marginLeft: "4px", fontSize: "10px", color: "#9A9384" }}>
                            {pct}%
                          </span>
                        )}
                      </td>
                    );
                  })}
                  <td
                    className="px-2 py-1.5 text-right"
                    style={{ fontFamily: "'JetBrains Mono', ui-monospace, monospace", color: "#2E7D32" }}
                  >
                    {funnel.grand.f4}
                    {funnel.grand.total > 0 && (
                      <span style={{ marginLeft: "4px", fontSize: "10px", color: "#9A9384" }}>
                        {Math.round((funnel.grand.f4 / funnel.grand.total) * 100)}%
                      </span>
                    )}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p style={{ marginTop: "8px", fontSize: "10px", color: "#9A9384" }}>
            Aggregated from the {rows.length.toLocaleString()} loaded row(s). Scroll / paginate to expand — server has {total.toLocaleString()} matches for the current filters.
          </p>
        </div>
      )}

      {/* Slim results table — CTD .funnel-card style */}
      {loading ? (
        <p style={{ fontSize: "12px", color: "#6E695E" }}>Loading…</p>
      ) : (
        <div
          className="overflow-x-auto rounded-lg"
          style={{ background: "#FFFFFF", border: "1px solid #E7E2D2" }}
        >
          <table className="w-full text-left text-xs">
            <thead>
              <tr style={{ borderBottom: "1px solid #E7E2D2", background: "#F5F1EC" }}>
                {["Ad", "Account", "Created", "Category", "F1234"].map((h) => (
                  <th
                    key={h}
                    className="px-3 py-2"
                    style={{
                      fontSize: "10px",
                      fontWeight: 600,
                      letterSpacing: "0.08em",
                      color: "#6E695E",
                      textTransform: "uppercase",
                    }}
                  >
                    {h}
                  </th>
                ))}
                {["Spend", "ROAS", "Purchases", "NCP", "Cost / NCP", "Cost / FTEWV"].map((h) => (
                  <th
                    key={h}
                    className="px-3 py-2 text-right"
                    style={{
                      fontSize: "10px",
                      fontWeight: 600,
                      letterSpacing: "0.08em",
                      color: "#6E695E",
                      textTransform: "uppercase",
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const cat = (r.category ?? "Discarded") as CategoryKey;
                return (
                  <tr
                    key={r.ad_id}
                    style={{ borderBottom: "1px solid #F0EBDF" }}
                    className="hover:bg-[#FAF8F5]"
                  >
                    <td
                      className="max-w-[260px] truncate px-3 py-1.5"
                      style={{ color: "#161513" }}
                      title={r.ad_name ?? ""}
                    >
                      {r.ad_name ?? "—"}
                    </td>
                    <td className="px-3 py-1.5" style={{ color: "#6E695E" }}>
                      {r.account_name ?? "—"}
                    </td>
                    <td
                      className="px-3 py-1.5"
                      style={{
                        fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                        fontSize: "11px",
                        color: "#6E695E",
                      }}
                    >
                      {r.ad_created_date ?? "—"}
                    </td>
                    <td className="px-3 py-1.5">
                      <span className={`cat-badge ${CAT_CLASS[cat] ?? "cat-disc"}`}>{r.category ?? "—"}</span>
                    </td>
                    <td className="px-3 py-1.5">
                      <div className="flex gap-0.5">
                        {(["f1_pass", "f2_pass", "f3_pass", "f4_pass"] as const).map((k, i) => {
                          const v = r[k];
                          const cls = v === null ? "u" : v ? "y" : "n";
                          return <span key={k} className={`ae-flag ${cls}`}>F{i + 1}</span>;
                        })}
                      </div>
                    </td>
                    <td
                      className="px-3 py-1.5 text-right"
                      style={{ fontFamily: "'JetBrains Mono', ui-monospace, monospace", color: "#161513" }}
                    >
                      {fmtMoney(r.spend)}
                    </td>
                    <td
                      className="px-3 py-1.5 text-right"
                      style={{ fontFamily: "'JetBrains Mono', ui-monospace, monospace", color: "#161513" }}
                    >
                      {fmtNum(r.meta_roas ?? r.roas)}
                    </td>
                    <td
                      className="px-3 py-1.5 text-right"
                      style={{ fontFamily: "'JetBrains Mono', ui-monospace, monospace", color: "#161513" }}
                    >
                      {fmtCompact(r.purchases)}
                    </td>
                    <td
                      className="px-3 py-1.5 text-right"
                      style={{ fontFamily: "'JetBrains Mono', ui-monospace, monospace", color: "#161513" }}
                    >
                      {fmtCompact(r.ncp_count)}
                    </td>
                    <td
                      className="px-3 py-1.5 text-right"
                      style={{ fontFamily: "'JetBrains Mono', ui-monospace, monospace", color: "#161513" }}
                    >
                      {fmtMoney(r.cost_per_ncp)}
                    </td>
                    <td
                      className="px-3 py-1.5 text-right"
                      style={{ fontFamily: "'JetBrains Mono', ui-monospace, monospace", color: "#161513" }}
                    >
                      {fmtMoney(r.cost_per_ftewv)}
                    </td>
                  </tr>
                );
              })}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={11} className="px-4 py-6 text-center" style={{ color: "#6E695E" }}>
                    No ads created in this window. Try widening the date range.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          {rows.length < total && (
            <div className="p-3 text-center" style={{ borderTop: "1px solid #F0EBDF" }}>
              <button
                onClick={loadMore}
                disabled={loadingMore}
                className="rounded-md px-4 py-1.5 text-[11px] font-medium disabled:opacity-40"
                style={{ background: "#F5F1EC", border: "1px solid #E7E2D2", color: "#161513" }}
              >
                {loadingMore ? "Loading…" : `Load more (${rows.length} of ${total})`}
              </button>
            </div>
          )}
        </div>
      )}

      {/* Definitions modal -- opens on Definitions button click. Covers the
          category ladder + F1-F4 gates so a new merchant can read the KPI
          strip without asking the previous ops person. */}
      {showDefs && (
        <div
          className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4"
          onClick={() => setShowDefs(false)}
        >
          <div
            className="relative max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-lg bg-white shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-border-primary p-4">
              <h3 className="text-base font-semibold text-text-primary">Creative Testing definitions</h3>
              <button
                onClick={() => setShowDefs(false)}
                className="rounded-md p-1 text-text-tertiary hover:bg-bg-hover"
                aria-label="Close"
              >
                ✕
              </button>
            </div>
            <div className="space-y-4 p-4 text-sm text-text-secondary">
              <section>
                <h4 className="mb-2 font-semibold text-text-primary">Category ladder</h4>
                <p className="text-xs">
                  Every ad gets exactly one category derived from its lifecycle metrics.
                  The ladder is evaluated top-down; the first rung that fits wins.
                </p>
                <dl className="mt-2 space-y-2">
                  <div>
                    <dt className="font-medium text-emerald-700">★ Winner / Incremental Winner</dt>
                    <dd className="text-xs">Cleared F1 + F2 + F3 + F4 and delivered enough spend to be confident (not a fluke). Incremental Winner is the subset that also beats its adset&apos;s average — a true breakthrough creative, not just a good one.</dd>
                  </div>
                  <div>
                    <dt className="font-medium text-amber-700">◆ P0 analysis</dt>
                    <dd className="text-xs">Passed F1 (impressions target) and one of F2/F3/F4 but not all — worth a deeper look this week.</dd>
                  </div>
                  <div>
                    <dt className="font-medium text-sky-700">▲ P1 / P2 analysis</dt>
                    <dd className="text-xs">Passed F1 but is falling short on multiple efficiency gates. P1 is closer to salvageable; P2 is closer to Discarded.</dd>
                  </div>
                  <div>
                    <dt className="font-medium text-slate-600">⌛ Result Awaited</dt>
                    <dd className="text-xs">Less than 14 days old OR under the F1 impressions floor — too early to judge. Sits in the buffer while it accumulates data.</dd>
                  </div>
                  <div>
                    <dt className="font-medium text-rose-700">✕ Discarded</dt>
                    <dd className="text-xs">Cleared the buffer and failed enough gates that no version of the current metric will save it. Kill or replace.</dd>
                  </div>
                </dl>
              </section>
              <section>
                <h4 className="mb-2 font-semibold text-text-primary">F1-F4 gates</h4>
                <ul className="space-y-1 text-xs">
                  <li><b>F1 — Volume</b>: impressions ≥ threshold (default 50,000). Confirms the ad had a fair delivery test.</li>
                  <li><b>F2 — ROAS</b>: meta_roas ≥ threshold (default 3.0). Efficiency at the account level.</li>
                  <li><b>F3 — Cost per NCP</b>: cost_per_ncp ≤ threshold (default ₹525). Cheap new-customer acquisition.</li>
                  <li><b>F4 — Cost per FTEWV</b>: cost_per_ftewv ≤ threshold (default ₹12). Cheap first-time engaged viewer — the quality gate for hook strength.</li>
                </ul>
              </section>
              <section>
                <h4 className="mb-2 font-semibold text-text-primary">Content types</h4>
                <p className="text-xs">
                  Derived from the ad_name naming convention. Priority: IFAD &gt; GAD (Graphic AD) &gt; VID markers (VRP/NNC/VIDEO/IGP/NO-ID/OSP/CPL/USP/CSR/ITE) &gt; STATIC (only when ad_name explicitly contains STATIC / _ST_ / +ST+). Anything else defaults to VID.
                </p>
              </section>
              <section>
                <h4 className="mb-2 font-semibold text-text-primary">Excl. copy</h4>
                <p className="text-xs">
                  When ON (default), ads whose ad_name contains &apos;copy&apos; are hidden. Meta&apos;s duplication flow appends &apos;- Copy N&apos; to child ads, so hiding them isolates the original creative under evaluation. Filter runs server-side so KPI tiles and totals reflect the toggle.
                </p>
              </section>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
