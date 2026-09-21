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
import { MultiFilter, MultiFilterState } from "./MultiFilter";
import { DateRangePicker, resolvePreset } from "@/components/DateRangePicker";

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

/** The category matrix, exactly as `ad_lifecycle`'s CASE evaluates it
 *  (app/services/silver/ad_lifecycle.py). Rows are tried top-down and the
 *  FIRST match wins, which is why a "-" can mean "not checked" rather
 *  than "must fail": by the time P0 is reached, the Winner rows have
 *  already been ruled out.
 *
 *  Presented as 3 filters, matching the legacy dashboard, while the
 *  backend stores 4 -- the legacy F2 is the OR of the backend's F2
 *  (ROAS) and F3 (Cost/NCP), and the legacy F3 is the backend's F4
 *  (Cost/FTEWV). Same logic, different numbering.
 *
 *  One row genuinely differs from the legacy dashboard and is marked:
 *  P2 is reached on ROAS ALONE here. Cost/NCP does not qualify an asset
 *  for P2, because the backend's P2 branch tests F2 only, not (F2 OR
 *  F3). Rendering it as the full OR would describe a rule this project
 *  does not run. */
type Mark = "pass" | "either" | "unchecked";

const CAT_MATRIX: {
  cat: CategoryKey;
  f1: Mark;
  f2: Mark;
  f3: Mark;
  f2Note?: string;
  action: string;
}[] = [
  {
    cat: "Incremental Winner", f1: "pass", f2: "pass", f3: "pass",
    action: "Scale aggressively. Top-tier proven creative.",
  },
  {
    cat: "Winner", f1: "pass", f2: "pass", f3: "either",
    action: "Scale. F3 close-second; iterate on cost-per-FTEWV.",
  },
  {
    cat: "P0 analysis", f1: "pass", f2: "unchecked", f3: "pass",
    action: "Impressions met and FTEWV cheap, but neither ROAS nor cost/NCP cleared. Iteration target.",
  },
  {
    cat: "P1 analysis", f1: "pass", f2: "unchecked", f3: "unchecked",
    action: "Impressions met, nothing else cleared. The creative itself is the lever.",
  },
  {
    cat: "P2 analysis", f1: "unchecked", f2: "pass", f3: "either",
    f2Note: "ROAS only",
    action: "ROAS cleared without the impressions to prove it. Give it volume before judging.",
  },
  {
    cat: "Result Awaited", f1: "unchecked", f2: "unchecked", f3: "unchecked",
    action: "Inside the 14-day buffer and matched no filter yet. Too early to call.",
  },
  {
    cat: "Discarded", f1: "unchecked", f2: "unchecked", f3: "unchecked",
    action: "Past day 14 having lit no filter. Stop spending.",
  },
];

/** One ✓ / ~ / — cell of the matrix. */
function MarkCell({ mark, note }: { mark: Mark; note?: string }) {
  const style =
    mark === "pass"
      ? { bg: "#EAF3EC", fg: "#2E7755", border: "#CBE3D3", glyph: "\u2713" }
      : mark === "either"
        ? { bg: "#FDF6E3", fg: "#B07E12", border: "#EBDCB4", glyph: "~" }
        : { bg: "transparent", fg: "#B8B2A4", border: "transparent", glyph: "\u2014" };
  return (
    <div className="flex flex-col items-center gap-0.5">
      <span
        className="inline-flex h-7 w-7 items-center justify-center rounded-md border text-sm font-semibold"
        style={{ backgroundColor: style.bg, color: style.fg, borderColor: style.border }}
      >
        {style.glyph}
      </span>
      {note && (
        <span className="text-[9px] font-medium uppercase tracking-wide" style={{ color: CT.muted }}>
          {note}
        </span>
      )}
    </div>
  );
}

/** Centred section rule, as on the legacy dashboard. */
function SectionRule({ label }: { label: string }) {
  return (
    <div className="my-4 flex items-center gap-3">
      <span className="h-px flex-1" style={{ backgroundColor: CT.border }} />
      <span className="text-[11px] font-semibold uppercase tracking-[0.12em]" style={{ color: CT.muted }}>
        {label}
      </span>
      <span className="h-px flex-1" style={{ backgroundColor: CT.border }} />
    </div>
  );
}

/** One amber call-out. */
function Callout({ icon, children }: { icon: string; children: React.ReactNode }) {
  return (
    <div
      className="mb-2 flex gap-3 rounded-lg border p-3 text-sm leading-relaxed"
      style={{ backgroundColor: "#FDF9EC", borderColor: "#EBDCB4", color: CT.ink }}
    >
      <span className="shrink-0" style={{ color: CT.goldDeep }}>{icon}</span>
      <div>{children}</div>
    </div>
  );
}

const PAGE_SIZE = 50;

type KindTab = "all" | "new" | "historical_discarded" | "refresh_discarded";

/** Lifetime impressions a creative has to reach to count as genuinely
 *  tested. Mirrors _CT_IMPRESSION_FLOOR in the API -- change both. */
const IMPRESSION_FLOOR = 50_000;
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
/** One inspector column, mirroring Ads Analyse's ColDef so the two
 *  tables behave the same way: pick what you want to see, filter on a
 *  rule set, read a wide row.
 *
 *  BASIS matters and is printed in the header. The date filter can only
 *  scope what insights_daily_by_ad reliably carries -- spend,
 *  impressions, purchases, conv value, NCP and FTEWV. Clicks, reach,
 *  ATC, checkouts, Shopify and the video counters are lifetime, so every
 *  ratio built from them is computed from lifetime inputs on BOTH sides
 *  rather than mixing a windowed numerator into a lifetime denominator.
 *  That mix is what once rendered a 90% hook rate where the truth was
 *  9.1%. */
type AssetColDef = {
  key: string;
  header: string;
  group: string;
  /** Lifetime columns are marked in the picker and header tooltip. */
  lifetime?: boolean;
  defaultVisible?: boolean;
  align?: "left" | "right";
  render: (r: CreativeTestingRow) => React.ReactNode;
};

const num = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : Math.round(n).toLocaleString("en-IN");
const pctOf = (n: number | null | undefined, digits = 2) =>
  n === null || n === undefined ? "—" : n.toFixed(digits) + "%";
const yn = (b: boolean | null | undefined) =>
  b === null || b === undefined ? "—" : b ? "Yes" : "No";

/** Every column the asset table can show. The first fifteen are the
 *  set that was always here and stay visible by default; the rest are
 *  the Ads Analyse inspector rolled up to the asset.
 *
 *  `lifetime: true` marks a column the date filter CANNOT scope, because
 *  the daily insights table has no usable source for it. Those four are
 *  link clicks, thruplays, outbound clicks and post engagements -- the
 *  fields only entered the Meta fetch on 2026-09-17. Showing them
 *  windowed would render a near-empty number that reads as a collapse,
 *  so they are lifetime and say so.
 *
 *  No campaign or ad-set column: an asset runs across many of both, so
 *  the counts are what carry meaning. */
/** What each bucket actually counts, in the words of the rule that
 *  computes it. These sat in `title` attributes, which meant the
 *  definition only existed if you happened to hover -- and the 50k rule
 *  in particular is not guessable from the label. */
const BUCKET_INFO: Record<string, { what: string; rule: string; note?: string }> = {
  all: {
    what: "Every asset with at least one ad CREATED inside the selected dates.",
    rule: "ads_in_window > 0",
    note: "An asset that only ran older ads during this window does not appear — this counts creatives that were PUT INTO test here, not everything that happened to spend.",
  },
  new: {
    what: "The asset's first real test: it was produced inside this window and ran as a genuine ad rather than only as a copy.",
    rule: "register creation date is inside the window AND at least one non-\u201ccopy\u201d ad carries it",
    note: "Creation date comes from the video / graphic / influencer register, not from any ad date.",
  },
  historical_discarded: {
    what: "Retested, and across ALL its ads it has still never reached 50,000 impressions in its LIFETIME — put back in the air again and again without ever clearing the bare minimum.",
    rule: "not new AND SUM(impressions) over every ad that ever carried the asset < 50,000",
    note: "Deliberately lifetime, not the selected dates. The question is whether the creative has ever had a fair run, and a single month cannot answer that.",
  },
  refresh_discarded: {
    what: "Retested and past the 50,000 lifetime impression mark across all its ads — it cleared the bare minimum, so its performance figures carry weight.",
    rule: "not new AND SUM(impressions) over every ad that ever carried the asset >= 50,000",
    note: "The 50k test asks whether a creative got a fair run, NOT whether it was discarded: most assets here hold a Winner or live-analysis verdict.",
  },
};

/** A small \u24d8 that opens the definition. Stops propagation so clicking
 *  it never also switches the tab underneath. */
function InfoDot({ id }: { id: string }) {
  const [open, setOpen] = useState(false);
  const info = BUCKET_INFO[id];
  if (!info) return null;
  return (
    <span className="relative inline-block align-middle">
      {/* A <span role="button">, NOT a <button>: this sits inside the
          tab's own <button>, and nesting them is invalid HTML that React
          refuses to hydrate ("<button> cannot be a descendant of
          <button>"). Keyboard support is wired by hand to keep what the
          real element gave for free. */}
      <span
        role="button"
        tabIndex={0}
        aria-label="What this counts"
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            e.stopPropagation();
            setOpen((v) => !v);
          }
        }}
        className="ml-0.5 inline-flex h-[18px] w-[18px] cursor-pointer items-center justify-center rounded-full border font-semibold leading-none transition-colors hover:brightness-95"
        style={{
          borderColor: open ? CT.ink : CT.muted,
          color: open ? "#FFFFFF" : CT.ink,
          backgroundColor: open ? CT.ink : "#FFFFFF",
          fontSize: "11px",
        }}
      >
        i
      </span>
      {open && (
        <>
          {/* Click-away. Fixed and behind the panel, so anywhere outside
              closes it without each tab needing its own handler. */}
          <span
            className="fixed inset-0 z-20"
            onClick={(e) => {
              e.stopPropagation();
              setOpen(false);
            }}
          />
          <span
            onClick={(e) => e.stopPropagation()}
            className="absolute left-0 top-6 z-30 block w-80 rounded-lg border p-3 text-left normal-case shadow-xl"
            style={{
              borderColor: CT.border,
              // Explicit, not a utility: this panel sits over the table
              // and over other tiles, and anything less than fully
              // opaque let their numbers read through the definition.
              backgroundColor: "#FFFFFF",
              letterSpacing: "normal",
            }}
          >
            <span className="block text-[12px] leading-relaxed" style={{ color: CT.ink }}>
              {info.what}
            </span>
            <span
              className="mt-2 block rounded bg-bg-muted px-2 py-1 font-mono text-[10.5px] leading-relaxed"
              style={{ color: CT.muted }}
            >
              {info.rule}
            </span>
            {info.note && (
              <span className="mt-2 block text-[11px] leading-relaxed" style={{ color: CT.muted }}>
                {info.note}
              </span>
            )}
          </span>
        </>
      )}
    </span>
  );
}

const ASSET_COLUMNS: AssetColDef[] = [
  // ---- Identity -----------------------------------------------------
  { key: "preview_thumb", header: "Preview", group: "Identity", defaultVisible: true,
    render: (r) => <AssetPreviewCell asset={r} /> },
  { key: "asset_id", header: "Asset", group: "Identity", defaultVisible: true,
    render: (r) => (
      <span className="font-mono text-[12px]">
        {r.asset_id}
        {r.name_conflict && (
          <span className="ml-1 rounded border border-amber-300 bg-amber-100 px-1 text-[10px] text-amber-900"
                title="An ad naming this asset also names another one.">⚠</span>
        )}
      </span>
    ) },
  { key: "ad_preview", header: "Ad preview", group: "Identity", defaultVisible: true,
    render: (r) => <AdPreviewLinks adId={r.preview_ad_id} url={r.ad_preview_url} /> },
  { key: "destination", header: "Website destination", group: "Identity", defaultVisible: true,
    render: (r) => (
      <span className="block max-w-[20rem] truncate">
        <DestinationLink adId={r.preview_ad_id} url={r.destination_url} />
      </span>
    ) },
  { key: "media", header: "Media", group: "Identity", defaultVisible: true,
    render: (r) => {
      const mm = r.media ? MEDIA_META[r.media] : null;
      return mm ? <span className={`rounded border px-1.5 py-0.5 text-[11px] ${mm.cls}`}>{mm.icon} {mm.label}</span> : null;
    } },
  { key: "kind", header: "Kind", group: "Identity", defaultVisible: true,
    render: (r) => r.kind === "new" ? (
      <span className="rounded border border-emerald-200 bg-emerald-100 px-1.5 py-0.5 text-[11px] text-emerald-800">New</span>
    ) : (
      <span className="rounded border border-amber-200 bg-amber-100 px-1.5 py-0.5 text-[11px] text-amber-900"
            title={`Reused ${r.iteration_count}× beyond its first outing`}>Iter ×{r.iteration_count}</span>
    ) },
  { key: "category", header: "Category", group: "Identity", defaultVisible: true,
    render: (r) => {
      const cat = (r.category ?? "Discarded") as CategoryKey;
      return <span className="text-[11px] font-medium" style={{ color: CAT_ACCENT[cat] }}>{cat}</span>;
    } },
  { key: "sample_ad_name", header: "Sample ad name", group: "Identity",
    render: (r) => (
      <span className="block max-w-[22rem] truncate text-[12px]" title={r.sample_ad_name ?? ""}>
        {r.sample_ad_name ?? "—"}
      </span>
    ) },
  { key: "account_name", header: "Account", group: "Identity",
    render: (r) => <span className="text-[12px]">{r.account_name ?? "—"}</span> },

  // ---- Timeline -----------------------------------------------------
  { key: "asset_created", header: "Created", group: "Timeline", defaultVisible: true, align: "right",
    render: (r) => <span className="text-[12px] text-text-tertiary">{r.asset_created ?? "—"}</span> },
  { key: "first_ad_date", header: "First ad", group: "Timeline", align: "right",
    render: (r) => <span className="text-[12px] text-text-tertiary">{r.first_ad_date ?? "—"}</span> },
  { key: "last_ad_date", header: "Last ad", group: "Timeline", align: "right",
    render: (r) => <span className="text-[12px] text-text-tertiary">{r.last_ad_date ?? "—"}</span> },

  // ---- Volume -------------------------------------------------------
  { key: "ads", header: "Ads", group: "Volume", defaultVisible: true, align: "right",
    render: (r) => <>{r.ads}</> },
  { key: "copy_ads", header: "Copies", group: "Volume", defaultVisible: true, align: "right",
    render: (r) => <span className="text-text-tertiary">{r.copy_ads}</span> },
  { key: "ads_in_window", header: "Ads in window", group: "Volume", align: "right",
    render: (r) => <>{r.ads_in_window}</> },
  { key: "campaigns", header: "Campaigns", group: "Volume", align: "right",
    render: (r) => <span title="Distinct campaigns this asset has run across">{r.campaigns ?? "—"}</span> },
  { key: "adsets", header: "Ad sets", group: "Volume", align: "right",
    render: (r) => <span title="Distinct ad sets this asset has run across">{r.adsets ?? "—"}</span> },
  { key: "any_active", header: "Any active", group: "Volume", align: "right",
    render: (r) => <>{yn(r.any_active)}</> },

  // ---- Delivery -----------------------------------------------------
  { key: "spend", header: "Spend", group: "Delivery", defaultVisible: true, align: "right",
    render: (r) => <>{fmtMoney(r.spend)}</> },
  { key: "impressions", header: "Impressions", group: "Delivery", align: "right",
    render: (r) => <>{num(r.impressions)}</> },
  { key: "reach_upper", header: "Reach (upper)", group: "Delivery", align: "right",
    render: (r) => <span title="Sum across ads. Reach does not de-duplicate people between ads of the same asset, so this is an upper bound.">{num(r.reach_upper)}</span> },
  { key: "frequency_upper", header: "Freq. (lower)", group: "Delivery", align: "right",
    render: (r) => <span title="Impressions ÷ upper-bound reach, so the true frequency is at least this.">{fmtNum(r.frequency_upper)}</span> },
  { key: "cost_per_1000", header: "CPM", group: "Delivery", align: "right",
    render: (r) => <>{fmtMoney(r.cost_per_1000)}</> },
  { key: "link_clicks", header: "Link clicks", group: "Delivery", align: "right",
    render: (r) => <>{num(r.link_clicks)}</> },
  { key: "ctr_pct", header: "CTR", group: "Delivery", align: "right",
    render: (r) => <>{pctOf(r.ctr_pct)}</> },
  { key: "cpc_link", header: "CPC", group: "Delivery", align: "right",
    render: (r) => <>{fmtMoney(r.cpc_link)}</> },

  // ---- Funnel -------------------------------------------------------
  { key: "atc_count", header: "Add to cart", group: "Funnel", align: "right",
    render: (r) => <>{num(r.atc_count)}</> },
  { key: "ci_count", header: "Checkouts", group: "Funnel", align: "right",
    render: (r) => <>{num(r.ci_count)}</> },
  { key: "atc_lc_pct", header: "ATC / click", group: "Funnel", align: "right",
    render: (r) => <>{pctOf(r.atc_lc_pct)}</> },
  { key: "ci_atc_pct", header: "Checkout / ATC", group: "Funnel", align: "right",
    render: (r) => <>{pctOf(r.ci_atc_pct)}</> },
  { key: "checkout_compl_pct", header: "Purchase / checkout", group: "Funnel", align: "right",
    render: (r) => <>{pctOf(r.checkout_compl_pct)}</> },
  { key: "cr_lc_pct", header: "CR / click", group: "Funnel", align: "right",
    render: (r) => <>{pctOf(r.cr_lc_pct)}</> },
  { key: "engagement_count", header: "Engagements", group: "Funnel", lifetime: true, align: "right",
    render: (r) => <>{num(r.engagement_count)}</> },

  // ---- Meta outcome -------------------------------------------------
  { key: "purchases", header: "Purch.", group: "Meta outcome", defaultVisible: true, align: "right",
    render: (r) => <>{fmtCompact(r.purchases)}</> },
  { key: "conv_value", header: "Conv. value", group: "Meta outcome", align: "right",
    render: (r) => <>{fmtMoney(r.conv_value)}</> },
  { key: "roas", header: "ROAS", group: "Meta outcome", defaultVisible: true, align: "right",
    render: (r) => <>{fmtNum(r.roas)}</> },
  { key: "ncp_count", header: "NCP", group: "Meta outcome", align: "right",
    render: (r) => <>{num(r.ncp_count)}</> },
  { key: "cost_per_ncp", header: "₹/NCP", group: "Meta outcome", defaultVisible: true, align: "right",
    render: (r) => <>{fmtMoney(r.cost_per_ncp)}</> },
  { key: "ftewv_count", header: "FTEWV", group: "Meta outcome", align: "right",
    render: (r) => <>{num(r.ftewv_count)}</> },
  { key: "cost_per_ftewv", header: "₹/FTEWV", group: "Meta outcome", defaultVisible: true, align: "right",
    render: (r) => <>{fmtMoney(r.cost_per_ftewv)}</> },
  { key: "pct_reach_ftewv", header: "FTEWV / reach", group: "Meta outcome", align: "right",
    render: (r) => <>{pctOf(r.pct_reach_ftewv)}</> },
  { key: "profit_efficiency", header: "Profit eff.", group: "Meta outcome", align: "right",
    render: (r) => <>{fmtMoney(r.profit_efficiency)}</> },
  { key: "contrib_margin_pct", header: "Contrib. margin", group: "Meta outcome", align: "right",
    render: (r) => <>{pctOf(r.contrib_margin_pct)}</> },

  // ---- Shopify ------------------------------------------------------
  { key: "shopify_orders", header: "Shopify orders", group: "Shopify", align: "right",
    render: (r) => <>{num(r.shopify_orders)}</> },
  { key: "shopify_revenue", header: "Shopify revenue", group: "Shopify", align: "right",
    render: (r) => <>{fmtMoney(r.shopify_revenue)}</> },
  { key: "shopify_roas", header: "Shopify ROAS", group: "Shopify", align: "right",
    render: (r) => <>{fmtNum(r.shopify_roas)}</> },
  { key: "cost_per_shopify_order", header: "₹/Shopify order", group: "Shopify", align: "right",
    render: (r) => <>{fmtMoney(r.cost_per_shopify_order)}</> },
  { key: "meta_shop_diff_pct", header: "Meta vs Shopify", group: "Shopify", align: "right",
    render: (r) => <>{pctOf(r.meta_shop_diff_pct)}</> },

  // ---- Video --------------------------------------------------------
  { key: "three_sec_plays", header: "3-sec plays", group: "Video", align: "right",
    render: (r) => <>{num(r.three_sec_plays)}</> },
  { key: "thruplays", header: "ThruPlays", group: "Video", lifetime: true, align: "right",
    render: (r) => <>{num(r.thruplays)}</> },
  { key: "outbound_clicks", header: "Outbound clicks", group: "Video", lifetime: true, align: "right",
    render: (r) => <>{num(r.outbound_clicks)}</> },
  { key: "post_engagements", header: "Post engagements", group: "Video", lifetime: true, align: "right",
    render: (r) => <>{num(r.post_engagements)}</> },

  // ---- Verdict flags ------------------------------------------------
  { key: "f1_pass", header: "F1", group: "Verdict", align: "right", render: (r) => <>{yn(r.f1_pass)}</> },
  { key: "f2_pass", header: "F2", group: "Verdict", align: "right", render: (r) => <>{yn(r.f2_pass)}</> },
  { key: "f3_pass", header: "F3", group: "Verdict", align: "right", render: (r) => <>{yn(r.f3_pass)}</> },
  { key: "f4_pass", header: "F4", group: "Verdict", align: "right", render: (r) => <>{yn(r.f4_pass)}</> },

  // ---- Lifetime reference -------------------------------------------
  { key: "spend_lifetime", header: "Spend (life)", group: "Lifetime", lifetime: true, align: "right",
    render: (r) => <>{fmtMoney(r.spend_lifetime)}</> },
  { key: "impressions_lifetime", header: "Impressions (life)", group: "Lifetime", lifetime: true, align: "right",
    render: (r) => <>{num(r.impressions_lifetime)}</> },
  { key: "purchases_lifetime", header: "Purch. (life)", group: "Lifetime", lifetime: true, align: "right",
    render: (r) => <>{fmtCompact(r.purchases_lifetime)}</> },
];

const ASSET_COL_GROUPS = Array.from(new Set(ASSET_COLUMNS.map((c) => c.group)));
const DEFAULT_HIDDEN = new Set(
  ASSET_COLUMNS.filter((c) => !c.defaultVisible).map((c) => c.key),
);

/** Fields the asset-grain multi-filter offers. Mirrors _CT_MF_FIELDS on
 *  the API -- a field missing there is silently skipped, so the two
 *  lists have to agree. */
const ASSET_FILTER_FIELDS = [
  { key: "asset_id", label: "Asset ID" },
  { key: "ad_name", label: "Ad Name" },
  { key: "media", label: "Media" },
  { key: "category", label: "Category" },
  { key: "kind", label: "Kind" },
  { key: "account_name", label: "Account" },
];

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

  const [preset, setPreset] = useState("last30");
  // resolvePreset, not a local helper: the picker owns its preset keys
  // ("last30", not "30"), and seeding state with a key it does not
  // recognise leaves its label blank on first paint.
  const initial = resolvePreset("last30");
  const [fromDate, setFromDate] = useState(initial.from);
  const [toDate, setToDate] = useState(initial.to);
  const [kindTab, setKindTab] = useState<KindTab>("all");
  const [hiddenCols, setHiddenCols] = useState<Set<string>>(new Set(DEFAULT_HIDDEN));
  const [showCols, setShowCols] = useState(false);
  const [colSearch, setColSearch] = useState("");
  const [multiFilter, setMultiFilter] = useState<MultiFilterState | null>(null);
  const visibleCols = ASSET_COLUMNS.filter((c) => !hiddenCols.has(c.key));
  const [media, setMedia] = useState<MediaKey | "">("");
  const [category, setCategory] = useState<CategoryKey | "">("");
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search.trim());
  const [page, setPage] = useState(0);

  const filters = useMemo(
    () => ({
      from_date: fromDate,
      to_date: toDate,
      kind: kindTab === "all" ? undefined : kindTab,
      multi_filter: multiFilter ? JSON.stringify(multiFilter) : undefined,
      media: media || undefined,
      category: category || undefined,
      search: debouncedSearch || undefined,
    }),
    [fromDate, toDate, kindTab, media, category, debouncedSearch, multiFilter],
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
  const histCount = kindCounts.historical_discarded ?? 0;
  const refreshCount = kindCounts.refresh_discarded ?? 0;

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
  // Denominator for the five video rates, and for the chart. Numerator
  // and denominator MUST move together: a lifetime numerator over a
  // windowed denominator once read 90% hook rate where the truth was
  // 9.1%. Both are windowed as of 2026-09-18, when the flatten started
  // extracting reach and clicks from Bronze.
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
        {/* The same dual-month picker Ads Analyse uses, rather than a
            preset dropdown beside two bare date inputs. It carries its
            own presets and applies from/to in one commit, so changing a
            range is one fetch instead of one per input. */}
        <div className="relative w-64">
          <DateRangePicker
            value={{ from: fromDate, to: toDate }}
            preset={preset}
            // Opens leftwards: this trigger sits at the left edge of the
            // filter bar and the panel is ~500px wide, so hanging it off
            // the right edge put the first month off-screen.
            align="left"
            // The section's own gold, not the app token -- which is named
            // accentYellow but is #3B6BF5, a blue nothing else here uses.
            accent={{ solid: CT.goldFill, soft: "#FBF3DF" }}
            onApply={(r, pk) => {
              setFromDate(r.from);
              setToDate(r.to);
              setPreset(pk);
              // The old preset dropdown did this; a new range is a new
              // result set, so staying on page 5 shows page 5 of
              // something else.
              setPage(0);
            }}
          />
        </div>
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
        {/* Sits with the controls, so the feedback is where the change
            was made. A 30-day window is a multi-second query and the
            date picker gave no sign it had been heard. */}
        {loading && (
          <span
            className="inline-flex items-center gap-1.5 text-xs"
            style={{ color: CT.muted }}
            role="status"
            aria-live="polite"
          >
            <span
              className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent"
              aria-hidden="true"
            />
            Loading {fromDate} → {toDate}…
          </span>
        )}
      </div>

      {/* ── New / Retested tabs ───────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-2">
        {(
          [
            ["all", "All tested", newCount + histCount + refreshCount, "Every asset with an ad launched in this window."],
            ["new", "New creatives", newCount, "Asset was created inside this window — its first real test."],
          ] as [KindTab, string, number, string][]
        ).map(([key, label, count, hint]) => {
          const active = kindTab === key;
          return (
            <button
              key={key}
              title={undefined}
              onClick={() => setKindTab(key)}
              className={
                "rounded-lg border px-3 py-2 text-left transition-colors " +
                (active
                  ? "border-emerald-400 bg-emerald-50 text-emerald-900"
                  : "border-border-primary bg-white hover:bg-bg-muted")
              }
            >
              <div className="flex items-center gap-0.5">
                <span className="text-[11px] uppercase tracking-wide opacity-70">{label}</span>
                <InfoDot id={key} />
              </div>
              <div className="text-lg font-semibold">{count.toLocaleString("en-IN")}</div>
            </button>
          );
        })}
      </div>

      {/* ── Retested creatives ────────────────────────────────── */}
      <div>
        <div className="mb-1 flex items-baseline gap-2">
          <span className="text-[11px] uppercase tracking-wide text-text-tertiary">
            Retested creatives
          </span>
          <span className="text-[11px] text-text-tertiary">
            {(histCount + refreshCount).toLocaleString("en-IN")} assets · split on{" "}
            <b>lifetime</b> impressions across every ad that ever carried the asset,
            not on the selected dates
          </span>
        </div>
        <div className="flex flex-wrap gap-2">
          {(
            [
              ["historical_discarded", "Historical Discarded", histCount,
               `Retested, and across ALL its ads it has still never reached ${IMPRESSION_FLOOR.toLocaleString("en-IN")} impressions in its lifetime \u2014 not just in this window. Put back in the air again and again and never cleared the bare minimum.`],
              ["refresh_discarded", "Refresh Discarded", refreshCount,
               `Retested and past the ${IMPRESSION_FLOOR.toLocaleString("en-IN")} lifetime impression mark across all its ads. It cleared the bare minimum, so its numbers are worth reading.`],
            ] as [KindTab, string, number, string][]
          ).map(([key, label, count, hint]) => {
            const active = kindTab === key;
            return (
              <button
                key={key}
                title={undefined}
                onClick={() => setKindTab(key)}
                className={
                  "rounded-lg border px-3 py-2 text-left transition-colors " +
                  (active
                    ? "border-emerald-400 bg-emerald-50 text-emerald-900"
                    : "border-border-primary bg-white hover:bg-bg-muted")
                }
              >
                <div className="flex items-center gap-0.5">
                  <span className="text-[11px] uppercase tracking-wide opacity-70">{label}</span>
                  <InfoDot id={key} />
                </div>
                <div className="text-lg font-semibold">{count.toLocaleString("en-IN")}</div>
              </button>
            );
          })}
        </div>
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

      {/* Everything below is derived from the fetch, so while one is in
          flight it is the PREVIOUS window's numbers. Dimming says that
          without blanking figures the eye may still want to compare. */}
      <div
        className={loading ? "pointer-events-none opacity-40 transition-opacity" : "transition-opacity"}
      >

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
                ["TOTAL AMOUNT SPENT", fmtMoney(totals.spend), "Sum · INR · inside the selected dates", false],
                ["TOTAL IMPRESSIONS", Math.round(totals.impressions).toLocaleString("en-IN"), "Sum · inside the selected dates", false],
                ["AVG. HOOK RATE", pct(totals.three_sec_plays, imp), "Sum(3-Sec Video Plays) ÷ Sum(Impressions) · inside the selected dates", false],
                ["AVG. OUTBOUND CTR", pct(totals.outbound_clicks, imp), "Sum(Outbound Clicks) ÷ Sum(Impressions) · inside the selected dates", false],
                ["AVG. ENGAGEMENT RATE", pct(totals.post_engagements, imp), "Sum(Post Engagements) ÷ Sum(Impressions) · inside the selected dates", false],
                ["AVG. THRUPLAY RATE", pct(totals.thruplays, imp), "Sum(ThruPlays) ÷ Sum(Impressions) · inside the selected dates", false],
                ["AVG. HOLD RATE", pct(totals.thruplays, totals.three_sec_plays), "Sum(ThruPlays) ÷ Sum(3-Sec Video Plays) · inside the selected dates", false],
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

      </div>{/* end dim-while-loading */}

      {/* ── inspector controls ────────────────────────────────── */}
      <MultiFilter applied={multiFilter} onApply={setMultiFilter} fields={ASSET_FILTER_FIELDS} />

      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={() => setShowCols((v) => !v)}
          className="rounded-md border border-border-primary bg-white px-2.5 py-1.5 text-xs hover:bg-bg-muted"
        >
          ▤ Columns ({visibleCols.length}/{ASSET_COLUMNS.length})
        </button>
        {hiddenCols.size !== DEFAULT_HIDDEN.size && (
          <button
            onClick={() => setHiddenCols(new Set(DEFAULT_HIDDEN))}
            className="rounded-md border border-border-primary bg-white px-2.5 py-1.5 text-xs hover:bg-bg-muted"
          >
            Reset to default
          </button>
        )}
        <span className="text-[11px]" style={{ color: CT.muted }}>
          <span className="opacity-50">∞</span> marks a lifetime metric the date filter cannot scope
        </span>
      </div>

      {showCols && (
        <div className="rounded-lg border bg-white p-3 shadow-sm" style={{ borderColor: CT.border }}>
          <div className="mb-2 flex items-center gap-2">
            <input
              value={colSearch}
              onChange={(e) => setColSearch(e.target.value)}
              placeholder="Find a column…"
              className="w-56 rounded-md border border-border-primary px-2 py-1 text-xs"
            />
            <button
              onClick={() => setHiddenCols(new Set())}
              className="rounded-md border border-border-primary px-2 py-1 text-xs hover:bg-bg-muted"
            >
              Show all
            </button>
            <button
              onClick={() => setHiddenCols(new Set(ASSET_COLUMNS.map((c) => c.key)))}
              className="rounded-md border border-border-primary px-2 py-1 text-xs hover:bg-bg-muted"
            >
              Hide all
            </button>
          </div>
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-3 lg:grid-cols-4">
            {ASSET_COL_GROUPS.map((grp) => {
              const cols = ASSET_COLUMNS.filter(
                (c) => c.group === grp &&
                  c.header.toLowerCase().includes(colSearch.toLowerCase()),
              );
              if (!cols.length) return null;
              return (
                <div key={grp}>
                  <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide"
                       style={{ color: CT.muted }}>
                    {grp}
                  </div>
                  {cols.map((c) => (
                    <label key={c.key} className="flex items-center gap-1.5 py-0.5 text-xs">
                      <input
                        type="checkbox"
                        checked={!hiddenCols.has(c.key)}
                        onChange={() =>
                          setHiddenCols((prev) => {
                            const next = new Set(prev);
                            if (next.has(c.key)) next.delete(c.key);
                            else next.add(c.key);
                            return next;
                          })
                        }
                      />
                      <span>{c.header}</span>
                      {c.lifetime && <span className="opacity-40" title="Lifetime, not windowed">∞</span>}
                    </label>
                  ))}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── asset table ───────────────────────────────────────── */}
      <p className="text-xs" style={{ color: CT.muted }}>
        Ad preview and website links show the ad that spent most in the selected dates. Open a row to see links for every iteration.
      </p>
      <div
        className="overflow-x-auto rounded-lg border bg-white shadow-sm"
        style={{ borderColor: CT.border }}
      >
        <table className="ct-asset-table min-w-full text-sm">
          <thead
            className="text-left text-[10px] font-semibold uppercase tracking-wider"
            style={{ backgroundColor: CT.cream, color: CT.muted }}
          >
            <tr>
              {visibleCols.map((c) => (
                <th
                  key={c.key}
                  className={"px-3 py-2 whitespace-nowrap " + (c.align === "right" ? "text-right" : "")}
                  title={c.lifetime
                    ? "LIFETIME — the date filter cannot scope this metric; no daily source carries it."
                    : undefined}
                >
                  {c.header}
                  {c.lifetime && <span className="ml-1 opacity-50" title="Lifetime, not windowed">∞</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {/* Skeleton rows, not a single "Loading…" line. A 30-day
                window takes seconds to come back, and a one-line message
                made the table look EMPTY rather than busy -- the shape of
                what is coming is the useful signal. */}
            {loading &&
              Array.from({ length: 8 }).map((_, i) => (
                <tr key={`sk-${i}`} className="border-t" style={{ borderColor: CT.border }}>
                  {visibleCols.map((c) => (
                    <td key={c.key} className="px-3 py-2">
                      <div
                        className="h-3 animate-pulse rounded bg-bg-muted"
                        style={{
                          // Vary the width so it reads as content rather
                          // than a progress bar, and keep it stable per
                          // cell so it does not jitter between frames.
                          width: c.align === "right" ? "3.5rem" : "70%",
                          opacity: 1 - i * 0.07,
                        }}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            {!loading && pageRows.length === 0 && (
              <tr>
                <td colSpan={visibleCols.length} className="px-3 py-6 text-center text-text-tertiary">
                  No assets tested in this window.
                </td>
              </tr>
            )}
            {!loading &&
              pageRows.map((r) => {
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
                    {visibleCols.map((c) => (
                      <td
                        key={c.key}
                        className={"px-3 py-2 " + (c.align === "right" ? "text-right" : "")}
                      >
                        {c.render(r)}
                      </td>
                    ))}
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

      {/* ── category definitions ─────────────────────── */}
      {defsOpen && (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4 sm:p-8"
          onClick={() => setDefsOpen(false)}
        >
          <div
            className="w-full max-w-5xl rounded-xl bg-white shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            {/* header */}
            <div
              className="flex items-start justify-between border-b px-6 py-4"
              style={{ borderColor: CT.border }}
            >
              <div>
                <h3 className="text-lg font-bold" style={{ color: CT.ink }}>
                  Category Definitions — 3-Filter Logic
                </h3>
                <p className="mt-0.5 text-sm" style={{ color: CT.muted }}>
                  F1 Impressions · F2 (ROAS <b>or</b> Cost/NCP) · F3 Cost/FTEWV
                </p>
              </div>
              <button
                onClick={() => setDefsOpen(false)}
                aria-label="Close"
                className="text-2xl leading-none"
                style={{ color: CT.muted }}
              >
                ✕
              </button>
            </div>

            <div className="px-6 pb-6">
              <SectionRule label="Evaluation thresholds" />

              <div className="grid gap-3 md:grid-cols-3">
                <div className="rounded-lg border p-4" style={{ backgroundColor: CT.cream, borderColor: CT.border }}>
                  <div className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: CT.ink }}>
                    F1 — Min impressions
                  </div>
                  <div className="mt-1 text-3xl font-bold" style={{ color: CT.ink }}>50,000</div>
                  <p className="mt-1 text-xs leading-relaxed" style={{ color: CT.muted }}>
                    Must pass before evaluation is considered valid.
                  </p>
                </div>

                <div className="rounded-lg border p-4" style={{ backgroundColor: CT.cream, borderColor: CT.border }}>
                  <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider" style={{ color: CT.ink }}>
                    F2 — ROAS
                    <span
                      className="rounded px-1.5 py-0.5 text-[10px] font-bold"
                      style={{ backgroundColor: "#EBDCB4", color: CT.goldDeep }}
                    >
                      OR
                    </span>
                    Cost/NCP
                  </div>
                  <div className="mt-1 flex items-end gap-6">
                    <div>
                      <div className="text-[10px] uppercase tracking-wide" style={{ color: CT.muted }}>ROAS</div>
                      <div className="text-2xl font-bold" style={{ color: CT.ink }}>&ge; 3&times;</div>
                    </div>
                    <div>
                      <div className="text-[10px] uppercase tracking-wide" style={{ color: CT.muted }}>Cost/NCP</div>
                      <div className="text-2xl font-bold" style={{ color: CT.ink }}>&le; &#8377;525</div>
                    </div>
                  </div>
                  <p className="mt-1 text-xs leading-relaxed" style={{ color: CT.muted }}>
                    Passes when <b>either</b> ROAS or Cost/NCP clears its bar.
                  </p>
                </div>

                <div className="rounded-lg border p-4" style={{ backgroundColor: CT.cream, borderColor: CT.border }}>
                  <div className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: CT.ink }}>
                    F3 — Cost / FTEWV
                  </div>
                  <div className="mt-1 text-3xl font-bold" style={{ color: CT.ink }}>&le; &#8377;12</div>
                  <p className="mt-1 text-xs leading-relaxed" style={{ color: CT.muted }}>
                    First-time engaged-view-purchase cost.
                  </p>
                </div>
              </div>

              <SectionRule label="Categorisation matrix" />

              <p className="text-sm leading-relaxed" style={{ color: CT.ink }}>
                Each ad is evaluated against the three filters. A <b>✓</b> means the filter must
                pass for that category; a <b>—</b> means it isn&rsquo;t checked; a <b>~</b> means
                either state is fine. Categories are matched top-down — the first matching row
                wins, which is why a &ldquo;—&rdquo; can mean &ldquo;already ruled out above&rdquo;.
              </p>

              <div className="mt-3">
                <Callout icon="◆">
                  <b style={{ color: CT.goldDeep }}>F3 (Cost/FTEWV) is a universal quality metric</b>{" "}
                  — it is evaluated for every ad and acts as the upgrade gate across categories
                  (F1-only &rarr; P1; F1+F3 &rarr; P0; F1+F2 &rarr; Winner; F1+F2+F3 &rarr;
                  Incremental Winner). P2 stays P2 whether F3 passes or not — ROAS clearing with
                  no F1 is the deciding signal.
                </Callout>
                <Callout icon="⌛">
                  <b style={{ color: CT.goldDeep }}>14-day evaluation buffer</b> — ads within
                  their first 14 days of <code>ad_created</code> that hit no filter drop into{" "}
                  <b style={{ color: CT.goldDeep }}>Result Awaited</b> instead of Discarded. Once an
                  ad crosses day 14 without lighting any filter, it falls through to Discarded.
                  Categories that DO match a filter (Winner / P0 / P1 / P2) are unaffected.
                </Callout>
              </div>

              <div className="mt-3 overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr style={{ backgroundColor: CT.cream }}>
                      <th className="px-3 py-2 text-[11px] font-semibold uppercase tracking-wider" style={{ color: CT.muted }}>
                        Category
                      </th>
                      <th className="px-2 py-2 text-center text-[11px] font-semibold" style={{ color: CT.muted }}>F1</th>
                      <th className="px-2 py-2 text-center text-[11px] font-semibold leading-tight" style={{ color: CT.muted }}>
                        F2<br /><span className="text-[9px] font-normal">(ROAS or Cost/NCP)</span>
                      </th>
                      <th className="px-2 py-2 text-center text-[11px] font-semibold leading-tight" style={{ color: CT.muted }}>
                        F3<br /><span className="text-[9px] font-normal">(Cost/FTEWV)</span>
                      </th>
                      <th className="px-3 py-2 text-[11px] font-semibold uppercase tracking-wider" style={{ color: CT.muted }}>
                        Action
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {CAT_MATRIX.map((r) => (
                      <tr key={r.cat} className="border-t" style={{ borderColor: CT.border }}>
                        <td className="px-3 py-2.5">
                          <span
                            className="inline-block whitespace-nowrap rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide"
                            style={{
                              color: CAT_ACCENT[r.cat],
                              borderColor: CAT_ACCENT[r.cat] + "55",
                              backgroundColor: CAT_ACCENT[r.cat] + "10",
                            }}
                          >
                            {r.cat}
                          </span>
                        </td>
                        <td className="px-2 py-2.5"><MarkCell mark={r.f1} /></td>
                        <td className="px-2 py-2.5"><MarkCell mark={r.f2} note={r.f2Note} /></td>
                        <td className="px-2 py-2.5"><MarkCell mark={r.f3} /></td>
                        <td className="px-3 py-2.5" style={{ color: CT.ink }}>{r.action}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <p className="mt-2 text-xs leading-relaxed" style={{ color: CT.muted }}>
                <b>P2 differs from the legacy dashboard.</b> Here P2 is reached on <b>ROAS alone</b>
                — Cost/NCP clearing does not qualify an asset for P2, because the backend&rsquo;s
                P2 branch tests ROAS only, not the full F2 OR. Every other row matches.
              </p>

              <SectionRule label="Asset-level rules" />

              <div className="grid gap-4 text-sm md:grid-cols-2">
                <div>
                  <div className="font-semibold" style={{ color: CT.ink }}>New creative vs Iteration</div>
                  <p className="mt-1 leading-relaxed" style={{ color: CT.muted }}>
                    Decided by the asset&rsquo;s own creation date in its register, never by an ad
                    date. Created inside the window &rarr; <b>New</b>. Created earlier, only ever run
                    as a duplicated (&ldquo;copy&rdquo;) ad, or with no creation date on record
                    &rarr; <b>Iteration</b>. 46% of mapped ads carry &ldquo;copy&rdquo; in the name,
                    so dating off ads would make every duplicated creative look newly tested.
                  </p>
                </div>
                <div>
                  <div className="font-semibold" style={{ color: CT.ink }}>One verdict per asset</div>
                  <p className="mt-1 leading-relaxed" style={{ color: CT.muted }}>
                    The matrix above categorises an <b>ad</b>. An asset takes the <b>best</b> verdict
                    any of its ads reached — a creative that produced one Winner is a Winner,
                    even if another ad using it was discarded. The creative proved itself at least
                    once, and that is what the section is asking.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}

export default CreativeTesting;
