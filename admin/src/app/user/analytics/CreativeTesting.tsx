"use client";

/**
 * Creative Testing — uniquely tested creative ASSETS in a window,
 * laid out to match the legacy CTD dashboard's Creative Testing page
 * (creative-testing-dashboard.onrender.com/creative-testing):
 *
 *   1. New / Iteration / All tabs          (this project's addition)
 *   2. Verdict buckets   Incremental Winner … Discarded, click-to-filter
 *   3. Overview — Performance              8-tile strip, CT ROAS highlighted
 *   4. Creative Type funnel                ctype × verdict matrix
 *   5. Product Focus + Creative Focus      pill strips
 *   6. Asset table
 *
 * The unit is the ASSET, counted once — NOT the ad. One creative
 * routinely runs in several ads, so at ad grain "how many creatives did
 * we test" was unanswerable.
 *
 * NEW vs ITERATION is decided by the asset's own creation date in its
 * register, never by an ad date:
 *
 *     created inside the window, with a non-copy ad -> New Creative
 *     created before the window                     -> Iteration
 *     only ever ran as a "copy" ad                  -> Iteration
 *     no creation date on record                    -> Iteration
 *
 * That is the whole point. Measured 2026-09-15: 1,833 of 3,911 mapped
 * ads (46%) carry "copy" in the name and 604 of 1,219 assets (50%)
 * appear in at least one. Meta's duplication flow appends "- Copy" to
 * the child ad, so dating off ads would make a creative first tested in
 * March look like a brand-new September test. Anchoring on the register
 * makes that impossible by construction. Copy ads still contribute
 * spend and conversions — the same creative really did deliver through
 * them — they just never make an asset count as new.
 *
 * The funnel and both focus strips are derived client-side from the full
 * row set (the endpoint returns every asset in the window, table
 * pagination is local), using verbatim ports of CTD's detectCtype /
 * detectProductFocus so the numbers match the legacy dashboard.
 */

import { useEffect, useMemo, useState } from "react";
import {
  ApiError,
  CreativeTestingRow,
  CreativeTestingTotals,
  fetchCreativeTesting,
} from "@/lib/api";
import { ExportButton } from "@/components/ExportButton";
import { useDebouncedValue } from "@/lib/useDebouncedValue";
import { AssetAdsModal } from "./AssetAdsModal";
import { AssetPreviewCell } from "./AssetPreview";
import { AdPreviewLinks, DestinationLink } from "./AdLinks";

/** CTD's cream/gold palette. Scoped here rather than pushed into the
 *  app's design tokens, which are blue-based for every other tab. */
const CT = {
  cream: "#FAF8F3",
  border: "#E8E2D5",
  muted: "#9A9384",
  gold: "#C9A227",
  goldDeep: "#B07E12",
  goldFill: "#B8860B",
  ink: "#3A362E",
};

const PAGE_SIZE = 50;

type KindTab = "all" | "new" | "iteration";
type MediaKey = "video" | "graphic" | "influencer";
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

const CAT_ACCENT: Record<CategoryKey, string> = {
  "Incremental Winner": "#15803D",
  Winner: "#2E7D32",
  "P0 analysis": "#3B6BF5",
  "P1 analysis": "#D97706",
  "P2 analysis": "#8B5A2B",
  "Result Awaited": "#C9A227",
  Discarded: "#C0392B",
};

/** Funnel column groups, matching CTD's two-row header. */
const FUNNEL_GROUPS: { label: string; cats: CategoryKey[]; tint: string }[] = [
  { label: "Winner", cats: ["Incremental Winner", "Winner"], tint: "#EFF5EF" },
  { label: "P0 analysis", cats: ["P0 analysis"], tint: "#EEF3FF" },
  { label: "P1 / P2 analysis", cats: ["P1 analysis", "P2 analysis"], tint: "#F5F1EA" },
  { label: "Awaited", cats: ["Result Awaited"], tint: "#FDF8E8" },
  { label: "Discarded", cats: ["Discarded"], tint: "#FBEFEC" },
];
const FUNNEL_SHORT: Record<CategoryKey, string> = {
  "Incremental Winner": "Inc. Winner",
  Winner: "Winner",
  "P0 analysis": "P0",
  "P1 analysis": "P1",
  "P2 analysis": "P2",
  "Result Awaited": "Awaited",
  Discarded: "Discarded",
};

const MEDIA_META: Record<MediaKey, { icon: string; label: string; cls: string }> = {
  video: { icon: "🎬", label: "Video", cls: "bg-violet-100 text-violet-800 border-violet-200" },
  graphic: { icon: "🖼", label: "Graphic", cls: "bg-sky-100 text-sky-800 border-sky-200" },
  influencer: { icon: "👤", label: "Influencer", cls: "bg-rose-100 text-rose-800 border-rose-200" },
};

const DATE_PRESETS: { key: string; label: string; days: number | null }[] = [
  { key: "7", label: "Last 7 days", days: 7 },
  { key: "30", label: "Last 30 days", days: 30 },
  { key: "90", label: "Last 90 days", days: 90 },
  { key: "180", label: "Last 6 months", days: 180 },
  { key: "365", label: "Last 12 months", days: 365 },
];

// ── CTD-verbatim classifiers ────────────────────────────────────────
type ProductFocusKey = "Home" | "Category" | "Collection" | "Product" | "Others";
const PRODUCT_FOCUS_ORDER: ProductFocusKey[] = [
  "Home",
  "Category",
  "Collection",
  "Product",
  "Others",
];
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
  if (n.includes("PDP") || n.includes("VRP") || n.includes("CTP") || n.includes("PRODUCT"))
    return "Product";
  return "Others";
}

type CtypeKey = "IFAD" | "Graphic AD" | "VID" | "STATIC";
const CTYPES: CtypeKey[] = ["IFAD", "Graphic AD", "VID", "STATIC"];
const CREATIVE_FOCUS_COLOR: Record<string, string> = {
  IFAD: "#7C3AED",
  "Graphic AD": "#D97706",
  VID: "#0891B2",
  STATIC: "#9A9384",
};
/** Asset media is a stronger signal than the ad name here — the asset
 *  register already knows what kind of thing it is. Fall back to CTD's
 *  ad-name classifier only when media is missing. */
function detectCtype(row: CreativeTestingRow): CtypeKey {
  if (row.media === "influencer") return "IFAD";
  if (row.media === "graphic") return "Graphic AD";
  if (row.media === "video") return "VID";
  const n = (row.sample_ad_name || "").toUpperCase();
  if (n.includes("IFAD")) return "IFAD";
  if (n.includes("GAD")) return "Graphic AD";
  if (n.includes("STATIC") || n.includes("_ST_") || n.includes("+ST+")) return "STATIC";
  return "VID";
}

function iso(d: Date) {
  return d.toISOString().slice(0, 10);
}
function presetRange(days: number) {
  const to = new Date();
  const from = new Date();
  from.setDate(from.getDate() - days + 1);
  return { from: iso(from), to: iso(to) };
}
function fmtMoney(n: number | null | undefined) {
  if (n === null || n === undefined) return "—";
  return "₹" + Math.round(n).toLocaleString("en-IN");
}
function fmtCompact(n: number | null | undefined) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  // Full figures, Indian grouping. These used to abbreviate to Cr / L / K,
  // which reads fine in a headline and badly everywhere else: 1.27Cr hides
  // the difference between 1,27,11,045 and 1,27,49,980, and those are the
  // comparisons this table exists to make. Charts pass their own axis
  // formatter, so nothing here widens an axis label.
  return Math.round(n).toLocaleString("en-IN");
}
function fmtNum(n: number | null | undefined, digits = 2) {
  if (n === null || n === undefined) return "—";
  return n.toFixed(digits);
}
function pct(num: number, den: number): string {
  if (!den) return "—";
  return ((num / den) * 100).toFixed(2) + "%";
}

export function CreativeTesting() {
  const [allRows, setAllRows] = useState<CreativeTestingRow[]>([]);
  const [totals, setTotals] = useState<CreativeTestingTotals | null>(null);
  const [kindCounts, setKindCounts] = useState<Record<string, number>>({});
  const [categoryCounts, setCategoryCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [defsOpen, setDefsOpen] = useState(false);
  const [openAsset, setOpenAsset] = useState<string | null>(null);

  const [preset, setPreset] = useState("30");
  const initial = presetRange(30);
  const [fromDate, setFromDate] = useState(initial.from);
  const [toDate, setToDate] = useState(initial.to);
  const [kindTab, setKindTab] = useState<KindTab>("all");
  const [media, setMedia] = useState<MediaKey | "">("");
  const [category, setCategory] = useState<CategoryKey | "">("");
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search.trim());
  const [page, setPage] = useState(0);

  function applyPreset(key: string) {
    setPreset(key);
    const p = DATE_PRESETS.find((x) => x.key === key);
    if (p?.days) {
      const r = presetRange(p.days);
      setFromDate(r.from);
      setToDate(r.to);
    }
    setPage(0);
  }

  const filters = useMemo(
    () => ({
      from_date: fromDate,
      to_date: toDate,
      kind: kindTab === "all" ? undefined : kindTab,
      media: media || undefined,
      category: category || undefined,
      search: debouncedSearch || undefined,
    }),
    [fromDate, toDate, kindTab, media, category, debouncedSearch],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setPage(0);
    fetchCreativeTesting({ ...filters, sort: "spend" })
      .then((res) => {
        if (cancelled) return;
        setAllRows(res.rows);
        setTotals(res.totals);
        setKindCounts(res.kind_counts);
        setCategoryCounts(res.category_counts);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(
          e instanceof ApiError
            ? e.message
            : "Could not reach the backend. Is it running, and is NEXT_PUBLIC_API_BASE_URL correct?",
        );
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [filters]);

  const newCount = kindCounts.new ?? 0;
  const iterCount = kindCounts.iteration ?? 0;

  // ── funnel + focus strips, derived over the full row set ──────────
  const derived = useMemo(() => {
    const funnel: Record<string, Record<string, number>> = {};
    for (const ct of CTYPES) {
      funnel[ct] = {};
      for (const c of CATEGORY_ORDER) funnel[ct][c] = 0;
    }
    const productFocus: Record<ProductFocusKey, number> = {
      Home: 0,
      Category: 0,
      Collection: 0,
      Product: 0,
      Others: 0,
    };
    const creativeFocus: Record<string, number> = {};
    const spendByCat: Record<string, number> = {};
    for (const r of allRows) {
      const ct = detectCtype(r);
      const cat = (r.category ?? "Discarded") as CategoryKey;
      if (funnel[ct] && cat in funnel[ct]) funnel[ct][cat] += 1;
      productFocus[detectProductFocus(r.sample_ad_name)] += 1;
      creativeFocus[ct] = (creativeFocus[ct] ?? 0) + 1;
      spendByCat[cat] = (spendByCat[cat] ?? 0) + (r.spend ?? 0);
    }
    return { funnel, productFocus, creativeFocus, spendByCat };
  }, [allRows]);

  const pageRows = allRows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const imp = totals?.impressions || 0;

  return (
    <div className="space-y-3" style={{ backgroundColor: CT.cream }}>
      {/* ── page header ───────────────────────────────────────── */}
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-2xl font-bold tracking-tight" style={{ color: CT.ink }}>
            Creative Testing <span style={{ color: CT.muted }}>—</span> Analytics
          </h2>
          <p className="text-xs" style={{ color: CT.muted }}>
            uniquely tested assets · powered by ad_asset_map (asset grain, not ad grain)
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setDefsOpen(true)}
            className="rounded-md border bg-white px-3 py-2 text-sm"
            style={{ borderColor: CT.border, color: CT.ink }}
          >
            ⓘ Definitions
          </button>
          <ExportButton
            rows={allRows as unknown as Record<string, unknown>[]}
            filename={`creative-testing-${fromDate}-to-${toDate}`}
          />
        </div>
      </div>

      {/* ── filters ───────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border-primary bg-white p-2 shadow-sm">
        <select
          value={preset}
          onChange={(e) => applyPreset(e.target.value)}
          className="rounded-md border border-border-primary px-2 py-1 text-sm"
        >
          {DATE_PRESETS.map((p) => (
            <option key={p.key} value={p.key}>
              {p.label}
            </option>
          ))}
          <option value="custom">Custom…</option>
        </select>
        <input
          type="date"
          value={fromDate}
          onChange={(e) => {
            setFromDate(e.target.value);
            setPreset("custom");
          }}
          className="rounded-md border border-border-primary px-2 py-1 text-sm"
        />
        <span className="text-xs text-text-tertiary">to</span>
        <input
          type="date"
          value={toDate}
          onChange={(e) => {
            setToDate(e.target.value);
            setPreset("custom");
          }}
          className="rounded-md border border-border-primary px-2 py-1 text-sm"
        />
        <select
          value={media}
          onChange={(e) => setMedia(e.target.value as MediaKey | "")}
          className="rounded-md border border-border-primary px-2 py-1 text-sm"
        >
          <option value="">All media</option>
          <option value="video">🎬 Video</option>
          <option value="graphic">🖼 Graphic</option>
          <option value="influencer">👤 Influencer</option>
        </select>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search asset id…"
          className="w-48 rounded-md border border-border-primary px-2 py-1 text-sm"
        />
      </div>

      {/* ── New / Iteration tabs ──────────────────────────────── */}
      <div className="flex flex-wrap gap-2">
        {(
          [
            ["all", "All tested", newCount + iterCount, "Every asset with an ad launched in this window."],
            ["new", "New creatives", newCount, "Asset was created inside this window — its first real test."],
            ["iteration", "Iterations", iterCount, "Asset predates this window, or ran only as a copy."],
          ] as [KindTab, string, number, string][]
        ).map(([key, label, count, hint]) => {
          const active = kindTab === key;
          return (
            <button
              key={key}
              title={hint}
              onClick={() => setKindTab(key)}
              className={
                "rounded-lg border px-3 py-2 text-left transition-colors " +
                (active
                  ? "border-emerald-400 bg-emerald-50 text-emerald-900"
                  : "border-border-primary bg-white hover:bg-bg-muted")
              }
            >
              <div className="text-[11px] uppercase tracking-wide opacity-70">{label}</div>
              <div className="text-lg font-semibold">{count.toLocaleString("en-IN")}</div>
            </button>
          );
        })}
      </div>

      {/* ── verdict buckets ───────────────────────────────────── */}
      <div>
        <div className="mb-1 text-[11px] uppercase tracking-wide text-text-tertiary">
          F1–F4 verdict buckets · click to filter
        </div>
        <div className="flex flex-wrap gap-2">
          {CATEGORY_ORDER.map((c) => {
            const n = categoryCounts[c] ?? 0;
            const active = category === c;
            return (
              <button
                key={c}
                onClick={() => setCategory(active ? "" : c)}
                className="min-w-[150px] flex-1 overflow-hidden rounded-lg border bg-white text-left shadow-sm transition-transform hover:-translate-y-0.5"
                style={{
                  borderColor: active ? CAT_ACCENT[c] : CT.border,
                  boxShadow: active ? `0 0 0 2px ${CAT_ACCENT[c]}33` : undefined,
                }}
              >
                <div style={{ height: 3, backgroundColor: CAT_ACCENT[c] }} />
                <div className="p-3">
                  <div
                    className="text-[10px] font-semibold uppercase tracking-wider"
                    style={{ color: CT.muted }}
                  >
                    {c}
                  </div>
                  <div className="text-2xl font-bold" style={{ color: CT.ink }}>
                    {n.toLocaleString("en-IN")}
                  </div>
                  <div className="text-[11px]" style={{ color: CT.muted }}>
                    Spend{" "}
                    <span style={{ color: CAT_ACCENT[c] }}>
                      {fmtMoney(derived.spendByCat[c] ?? 0)}
                    </span>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* ── Overview — Performance ────────────────────────────── */}
      {totals && (
        <div
          className="overflow-hidden rounded-lg border bg-white shadow-sm"
          style={{ borderColor: CT.border }}
        >
          <div
            className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-2.5"
            style={{ borderColor: CT.border }}
          >
            <div className="text-sm font-semibold tracking-wide" style={{ color: CT.ink }}>
              OVERVIEW <span style={{ color: CT.muted }}>—</span> PERFORMANCE
            </div>
            <div
              className="rounded-md border px-2 py-1 text-[10px] font-semibold uppercase tracking-wider"
              style={{ borderColor: CT.gold, color: CT.goldDeep, backgroundColor: "#FDF8E8" }}
            >
              sum &amp; avg · {fromDate} → {toDate} ·{" "}
              {totals.assets.toLocaleString("en-IN")} assets
            </div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
            {(
              [
                ["TOTAL AMOUNT SPENT", fmtMoney(totals.spend), "Sum · INR", false],
                ["TOTAL IMPRESSIONS", Math.round(totals.impressions).toLocaleString("en-IN"), "Sum", false],
                ["AVG. HOOK RATE", pct(totals.three_sec_plays, imp), "Sum(3-Sec Video Plays) ÷ Sum(Impressions)", false],
                ["AVG. OUTBOUND CTR", pct(totals.outbound_clicks, imp), "Sum(Outbound Clicks) ÷ Sum(Impressions)", false],
                ["AVG. ENGAGEMENT RATE", pct(totals.post_engagements, imp), "Sum(Post Engagements) ÷ Sum(Impressions)", false],
                ["AVG. THRUPLAY RATE", pct(totals.thruplays, imp), "Sum(ThruPlays) ÷ Sum(Impressions)", false],
                ["AVG. HOLD RATE", pct(totals.thruplays, totals.three_sec_plays), "Sum(ThruPlays) ÷ Sum(3-Sec Video Plays)", false],
                ["CT ROAS", fmtNum(totals.roas), "Sum(Conv. Value) ÷ Sum(Spend)", true],
              ] as [string, string, string, boolean][]
            ).map(([label, value, formula, hi]) => (
              <div
                key={label}
                className="border-b border-r p-4 last:border-r-0"
                style={{
                  borderColor: CT.border,
                  backgroundColor: hi ? CT.goldFill : "#FFFFFF",
                }}
              >
                <div
                  className="text-[10px] font-semibold uppercase tracking-wider"
                  style={{ color: hi ? "#F6E7C4" : CT.muted }}
                >
                  {label}
                </div>
                <div
                  className="mt-1 text-2xl font-bold tracking-tight"
                  style={{ color: hi ? "#FFFFFF" : CT.ink }}
                >
                  {value}
                </div>
                <div className="mt-1 text-[10px]" style={{ color: hi ? "#F0DDB4" : CT.goldDeep }}>
                  {formula}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── funnel + focus strips ─────────────────────────────── */}
      <div className="grid gap-3 lg:grid-cols-3">
        <div
          className="rounded-lg border bg-white p-3 shadow-sm lg:col-span-2"
          style={{ borderColor: CT.border }}
        >
          <div className="mb-2 flex items-baseline justify-between">
            <div className="text-sm font-semibold" style={{ color: CT.ink }}>
              CREATIVE TYPE FUNNEL{" "}
              <span className="text-[11px] font-normal" style={{ color: CT.muted }}>
                distribution across categories
              </span>
            </div>
            <div className="text-[11px]" style={{ color: CT.muted }}>
              {allRows.length} assets
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] border-collapse text-xs">
              <thead>
                <tr>
                  <th className="px-2 py-1" />
                  <th className="px-2 py-1" />
                  {FUNNEL_GROUPS.map((g) => (
                    <th
                      key={g.label}
                      colSpan={g.cats.length}
                      className="px-2 py-1.5 text-center text-[10px] font-semibold uppercase tracking-wider"
                      style={{ backgroundColor: g.tint, color: CAT_ACCENT[g.cats[0]] }}
                    >
                      {g.label}
                    </th>
                  ))}
                </tr>
                <tr style={{ color: CT.muted }}>
                  <th className="px-2 py-1.5 text-left text-[10px] uppercase tracking-wider">
                    Creative type
                  </th>
                  <th className="px-2 py-1.5 text-right text-[10px] uppercase tracking-wider">
                    Total
                  </th>
                  {FUNNEL_GROUPS.flatMap((g) =>
                    g.cats.map((c) => (
                      <th
                        key={c}
                        className="px-2 py-1.5 text-right text-[10px] uppercase tracking-wider"
                        style={{ backgroundColor: g.tint }}
                      >
                        {FUNNEL_SHORT[c]}
                      </th>
                    )),
                  )}
                </tr>
              </thead>
              <tbody>
                {CTYPES.map((ct) => {
                  const row = derived.funnel[ct];
                  const tot = CATEGORY_ORDER.reduce((a, c) => a + row[c], 0);
                  if (!tot) return null;
                  return (
                    <tr key={ct} className="border-t" style={{ borderColor: CT.border }}>
                      <td
                        className="px-2 py-2 font-medium"
                        style={{ color: CREATIVE_FOCUS_COLOR[ct] }}
                      >
                        {ct}
                        <div className="text-[10px] font-normal" style={{ color: CT.muted }}>
                          {tot} assets
                        </div>
                      </td>
                      <td className="px-2 py-2 text-right text-base font-bold">{tot}</td>
                      {FUNNEL_GROUPS.flatMap((g) =>
                        g.cats.map((c) => {
                          const n = row[c];
                          const share = tot ? (n / tot) * 100 : 0;
                          return (
                            <td key={c} className="px-2 py-2 align-top">
                              <div className="flex items-baseline justify-end gap-1">
                                <span className="text-sm font-semibold">{n}</span>
                                <span className="text-[10px]" style={{ color: CT.muted }}>
                                  {share.toFixed(0)}%
                                </span>
                              </div>
                              <div
                                className="mt-1 h-1 w-full rounded"
                                style={{ backgroundColor: "#EFEDE6" }}
                              >
                                <div
                                  className="h-1 rounded"
                                  style={{
                                    width: `${share}%`,
                                    backgroundColor: CAT_ACCENT[c],
                                  }}
                                />
                              </div>
                            </td>
                          );
                        }),
                      )}
                    </tr>
                  );
                })}
                <tr
                  className="border-t-2"
                  style={{ borderColor: CT.border, backgroundColor: CT.cream }}
                >
                  <td className="px-2 py-2 text-[10px] font-semibold uppercase tracking-wider">
                    Grand total
                  </td>
                  <td className="px-2 py-2 text-right text-base font-bold">{allRows.length}</td>
                  {FUNNEL_GROUPS.flatMap((g) =>
                    g.cats.map((c) => {
                      const n = categoryCounts[c] ?? 0;
                      const share = allRows.length ? (n / allRows.length) * 100 : 0;
                      return (
                        <td key={c} className="px-2 py-2 text-right">
                          <span className="text-sm font-bold">{n}</span>{" "}
                          <span className="text-[10px]" style={{ color: CT.muted }}>
                            {share.toFixed(0)}%
                          </span>
                        </td>
                      );
                    }),
                  )}
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div className="space-y-3">
          <div
            className="rounded-lg border bg-white p-3 shadow-sm"
            style={{ borderColor: CT.border }}
          >
            <div className="mb-2 flex items-baseline justify-between">
              <div className="text-sm font-semibold" style={{ color: CT.ink }}>
                PRODUCT IN FOCUS
              </div>
              <div className="text-[10px]" style={{ color: CT.muted }}>
                landing-page hierarchy from ad name
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              {PRODUCT_FOCUS_ORDER.map((k) => {
                const n = derived.productFocus[k];
                return (
                  <span
                    key={k}
                    className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs"
                    style={{
                      borderColor: CT.border,
                      backgroundColor: n ? "#FFFFFF" : CT.cream,
                      color: n ? CT.ink : CT.muted,
                    }}
                  >
                    <span
                      className="inline-block h-2 w-2 rounded-full"
                      style={{ backgroundColor: PRODUCT_FOCUS_COLOR[k] }}
                    />
                    <b>{n}</b> {k} page
                  </span>
                );
              })}
            </div>
          </div>

          <div
            className="rounded-lg border bg-white p-3 shadow-sm"
            style={{ borderColor: CT.border }}
          >
            <div className="mb-2 flex items-baseline justify-between">
              <div className="text-sm font-semibold" style={{ color: CT.ink }}>
                CREATIVE FOCUS
              </div>
              <div className="text-[10px]" style={{ color: CT.muted }}>
                IFAD · GAD · VID
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              {CTYPES.map((k) => {
                const n = derived.creativeFocus[k] ?? 0;
                if (!n) return null;
                return (
                  <span
                    key={k}
                    className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs"
                    style={{ borderColor: CT.border, color: CT.ink }}
                  >
                    <span
                      className="inline-block h-2 w-2 rounded-full"
                      style={{ backgroundColor: CREATIVE_FOCUS_COLOR[k] }}
                    />
                    <b>{n}</b> {k}
                  </span>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
          {error}
        </div>
      )}

      {/* ── asset table ───────────────────────────────────────── */}
      <p className="text-xs" style={{ color: CT.muted }}>
        Ad preview and website links show the highest-spend ad for each asset. Open a row to see links for every iteration.
      </p>
      <div
        className="overflow-x-auto rounded-lg border bg-white shadow-sm"
        style={{ borderColor: CT.border }}
      >
        <table className="w-full min-w-[1520px] text-sm">
          <thead
            className="text-left text-[10px] font-semibold uppercase tracking-wider"
            style={{ backgroundColor: CT.cream, color: CT.muted }}
          >
            <tr>
              <th className="px-3 py-2">Preview</th>
              <th className="px-3 py-2">Asset</th>
              <th className="px-3 py-2">Ad preview</th>
              <th className="px-3 py-2">Website destination</th>
              <th className="px-3 py-2">Media</th>
              <th className="px-3 py-2">Kind</th>
              <th className="px-3 py-2">Category</th>
              <th className="px-3 py-2 text-right">Created</th>
              <th className="px-3 py-2 text-right">Ads</th>
              <th className="px-3 py-2 text-right">Copies</th>
              <th className="px-3 py-2 text-right">Spend</th>
              <th className="px-3 py-2 text-right">Purch.</th>
              <th className="px-3 py-2 text-right">ROAS</th>
              <th className="px-3 py-2 text-right">₹/NCP</th>
              <th className="px-3 py-2 text-right">₹/FTEWV</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={15} className="px-3 py-6 text-center text-text-tertiary">
                  Loading…
                </td>
              </tr>
            )}
            {!loading && pageRows.length === 0 && (
              <tr>
                <td colSpan={15} className="px-3 py-6 text-center text-text-tertiary">
                  No assets tested in this window.
                </td>
              </tr>
            )}
            {!loading &&
              pageRows.map((r) => {
                const mm = r.media ? MEDIA_META[r.media] : null;
                const cat = (r.category ?? "Discarded") as CategoryKey;
                return (
                  <tr
                    key={r.asset_id}
                    onClick={() => setOpenAsset(r.asset_id)}
                    title={
                      r.kind === "new"
                        ? "Open this asset's ad"
                        : `Open all ${r.ads} ads for this asset, by iteration`
                    }
                    className="cursor-pointer border-t transition-colors"
                    style={{ borderColor: CT.border }}
                    onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "#FDF8E8")}
                    onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "")}
                  >
                    <td className="px-3 py-2">
                      <AssetPreviewCell asset={r} />
                    </td>
                    <td className="px-3 py-2 font-mono text-[12px]">
                      {r.asset_id}
                      {r.name_conflict && (
                        <span
                          className="ml-1 rounded border border-amber-300 bg-amber-100 px-1 text-[10px] text-amber-900"
                          title="An ad naming this asset also names another one."
                        >
                          ⚠
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <AdPreviewLinks adId={r.preview_ad_id} url={r.ad_preview_url} />
                    </td>
                    <td className="px-3 py-2">
                      <DestinationLink adId={r.preview_ad_id} url={r.destination_url} />
                    </td>
                    <td className="px-3 py-2">
                      {mm && (
                        <span className={`rounded border px-1.5 py-0.5 text-[11px] ${mm.cls}`}>
                          {mm.icon} {mm.label}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {r.kind === "new" ? (
                        <span className="rounded border border-emerald-200 bg-emerald-100 px-1.5 py-0.5 text-[11px] text-emerald-800">
                          New
                        </span>
                      ) : (
                        <span
                          className="rounded border border-amber-200 bg-amber-100 px-1.5 py-0.5 text-[11px] text-amber-900"
                          title={`Reused ${r.iteration_count}× beyond its first outing`}
                        >
                          Iter ×{r.iteration_count}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <span className="text-[11px] font-medium" style={{ color: CAT_ACCENT[cat] }}>
                        {cat}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right text-[12px] text-text-tertiary">
                      {r.asset_created ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-right">{r.ads}</td>
                    <td className="px-3 py-2 text-right text-text-tertiary">{r.copy_ads}</td>
                    <td className="px-3 py-2 text-right">{fmtMoney(r.spend)}</td>
                    <td className="px-3 py-2 text-right">{fmtCompact(r.purchases)}</td>
                    <td className="px-3 py-2 text-right">{fmtNum(r.roas)}</td>
                    <td className="px-3 py-2 text-right">{fmtMoney(r.cost_per_ncp)}</td>
                    <td className="px-3 py-2 text-right">{fmtMoney(r.cost_per_ftewv)}</td>
                  </tr>
                );
              })}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between text-xs" style={{ color: CT.muted }}>
        <span>
          click a row to see the ad(s) behind it ·{" "}
          {allRows.length.toLocaleString("en-IN")} asset{allRows.length === 1 ? "" : "s"} · showing{" "}
          {pageRows.length ? page * PAGE_SIZE + 1 : 0}–{page * PAGE_SIZE + pageRows.length}
        </span>
        <div className="flex gap-2">
          <button
            disabled={page === 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            className="rounded-md border border-border-primary px-2 py-1 disabled:opacity-40"
          >
            Prev
          </button>
          <button
            disabled={(page + 1) * PAGE_SIZE >= allRows.length}
            onClick={() => setPage((p) => p + 1)}
            className="rounded-md border border-border-primary px-2 py-1 disabled:opacity-40"
          >
            Next
          </button>
        </div>
      </div>

      {openAsset && (
        <AssetAdsModal assetId={openAsset} onClose={() => setOpenAsset(null)} />
      )}

      {/* ── definitions ───────────────────────────────────────── */}
      {defsOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          onClick={() => setDefsOpen(false)}
        >
          <div
            className="max-h-[80vh] w-full max-w-2xl overflow-y-auto rounded-lg bg-white p-4 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-base font-semibold">Definitions</h3>
              <button onClick={() => setDefsOpen(false)} className="text-text-tertiary">
                ✕
              </button>
            </div>
            <div className="space-y-3 text-sm">
              <div>
                <div className="font-medium">New creative vs Iteration</div>
                <p className="text-text-tertiary">
                  Decided by the asset&rsquo;s own creation date in its register, never by an ad
                  date. Created inside the window &rarr; <b>New</b>. Created earlier, or only ever
                  run as a duplicated (&ldquo;copy&rdquo;) ad, or no creation date on record &rarr;{" "}
                  <b>Iteration</b>. 46% of mapped ads carry &ldquo;copy&rdquo; in the name, so
                  dating off ads would make every duplicated creative look newly tested.
                </p>
              </div>
              <div>
                <div className="font-medium">Thresholds</div>
                <ul className="list-disc pl-5 text-text-tertiary">
                  <li>F1 — min impressions: 50,000</li>
                  <li>F2 — ROAS &ge; 3.0</li>
                  <li>F3 — Cost / NCP &le; ₹525</li>
                  <li>F4 — Cost / FTEWV &le; ₹12</li>
                </ul>
              </div>
              <div>
                <div className="font-medium">Verdict buckets</div>
                <ul className="list-disc pl-5 text-text-tertiary">
                  <li>Incremental Winner — F1 and (F2 or F3) and F4</li>
                  <li>Winner — F1 and (F2 or F3)</li>
                  <li>P0 analysis — F1 and F4</li>
                  <li>P1 analysis — F1 only</li>
                  <li>P2 analysis — F2 only</li>
                  <li>Result Awaited — created less than 14 days ago</li>
                  <li>Discarded — none of the above</li>
                </ul>
                <p className="mt-1 text-text-tertiary">
                  An asset takes the <b>best</b> verdict any of its ads reached — a creative that
                  produced one Winner is a Winner, even if another ad using it was discarded.
                </p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default CreativeTesting;
