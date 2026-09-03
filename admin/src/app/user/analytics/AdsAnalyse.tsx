"use client";

/**
 * Ads Analyse (Creative Testing) — CTD-structure port.
 *
 * Layout follows CTD dashboard.js:7447 (renderAE) exactly:
 *   1. Level toggle (Ad / Adset / Campaign) — Adset/Campaign disabled
 *      in Phase 1 because grouped rollups need backend RPCs that don't
 *      exist yet in Backend_Project.
 *   2. Filter row: Account / Group By / Category / Ad Status / Date Field
 *      / Date Range — Date Range disabled in Phase 1 (needs /api/delivery
 *      equivalent).
 *   3. F1..F4 threshold input row — editable, client-side recategorises
 *      rows without a backend round-trip (matches CTD's aeCategorise).
 *   4. Inline text multi-filter (Add / Apply / Clear).
 *   5. 7 category KPI tiles with click-to-filter and CTD's colour classes
 *      (cat-iw / cat-winner / cat-priority / cat-a1 / cat-a2 / cat-ra /
 *      cat-disc — see globals.css).
 *   6. Column picker (▤) + Inspector drawer (⚙) — Shopify-style, backed
 *      by localStorage 'aeHiddenCols_v1'.
 *   7. 68-column table — the columns backend has data for render live;
 *      Tier-3 columns (efficiency scores, reach snapshots) render "—"
 *      with a tooltip explaining what Silver-layer work would unlock
 *      them (see docs/backend_project_upgrade_plan.md).
 *   8. Footer: pagination + row-count cascade + diagnostics.
 *
 * Everything data-derivable in-Silver already comes through
 * /admin/analytics/ads-analyse (widened backend). Client-side F1..F4
 * recategorisation runs against the raw metrics, so if a user sets F3
 * threshold to 400 (from CTD's default 525) they see the impact
 * immediately without re-hitting the backend.
 */

import { useEffect, useMemo, useState } from "react";
import { AdsAnalyseRow, AdsAnalyseTotals, ApiError, fetchAdsAnalyse } from "@/lib/api";
import { KwikTile } from "./KwikTile";
import { AdsAnalyseCharts } from "./AdsAnalyseCharts";

// ─────────────────────────────────────────────────────────────────────
// Category definitions — mirrors CTD dashboard.js:5874-5896 (aeCategorise)
// ─────────────────────────────────────────────────────────────────────

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

const CATEGORY_CLASS: Record<CategoryKey, string> = {
  "Incremental Winner": "cat-iw",
  Winner: "cat-winner",
  "P0 analysis": "cat-priority",
  "P1 analysis": "cat-a1",
  "P2 analysis": "cat-a2",
  "Result Awaited": "cat-ra",
  Discarded: "cat-disc",
};

const CATEGORY_TILE_CLASS: Record<CategoryKey, string> = {
  "Incremental Winner": "cat-tile-iw",
  Winner: "cat-tile-winner",
  "P0 analysis": "cat-tile-priority",
  "P1 analysis": "cat-tile-a1",
  "P2 analysis": "cat-tile-a2",
  "Result Awaited": "cat-tile-ra",
  Discarded: "cat-tile-disc",
};

// Kwikengage-style icon color per category (matches the category
// meaning: winners → emerald, priorities → amber, analyses → sky,
// awaited → slate, discarded → rose). Icons are just SVG glyphs so
// they render clean at 18px.
const CATEGORY_ICON_COLOR: Record<CategoryKey, "emerald" | "amber" | "sky" | "slate" | "rose"> = {
  "Incremental Winner": "emerald",
  Winner: "emerald",
  "P0 analysis": "amber",
  "P1 analysis": "sky",
  "P2 analysis": "sky",
  "Result Awaited": "slate",
  Discarded: "rose",
};
const CATEGORY_ICON: Record<CategoryKey, string> = {
  "Incremental Winner": "★",
  Winner: "★",
  "P0 analysis": "◆",
  "P1 analysis": "▲",
  "P2 analysis": "▲",
  "Result Awaited": "⌛",
  Discarded: "✕",
};

// CTD default thresholds — dashboard.js:5863 (AE_DEFAULTS)
interface FThresholds {
  f1Imp: number; // impressions minimum
  f2Roas: number; // ROAS minimum
  f3CostPerNcp: number; // Cost/NCP maximum
  f4CostPerFtewv: number; // Cost/FTEWV maximum
  bufferDays: number; // Result Awaited window (days since ad_created)
}

const DEFAULT_THRESHOLDS: FThresholds = {
  f1Imp: 50_000,
  f2Roas: 3,
  f3CostPerNcp: 525,
  f4CostPerFtewv: 12,
  bufferDays: 14,
};

function evaluateFlags(row: AdsAnalyseRow, t: FThresholds) {
  const p1 = (row.impressions ?? 0) >= t.f1Imp;
  const p2 = (row.roas ?? 0) >= t.f2Roas;
  const p3 = row.cost_per_ncp !== null && row.cost_per_ncp <= t.f3CostPerNcp;
  const p4 = row.cost_per_ftewv !== null && row.cost_per_ftewv <= t.f4CostPerFtewv;
  return { p1, p2, p3, p4 };
}

function categorise(row: AdsAnalyseRow, t: FThresholds): CategoryKey {
  const { p1, p2, p3, p4 } = evaluateFlags(row, t);
  if (p1 && (p2 || p3) && p4) return "Incremental Winner";
  if (p1 && (p2 || p3)) return "Winner";
  if (p1 && p4) return "P0 analysis"; // p1 && p4 but not p2/p3
  if (p1) return "P1 analysis";
  if (p2) return "P2 analysis"; // p2 only (no p1)
  // Result Awaited: within CT_BUFFER_DAYS of ad_created_date
  const created = row.ad_created_date ? Date.parse(row.ad_created_date) : NaN;
  if (!Number.isNaN(created)) {
    const ageDays = (Date.now() - created) / 86_400_000;
    if (ageDays < t.bufferDays) return "Result Awaited";
  }
  return "Discarded";
}

// ─────────────────────────────────────────────────────────────────────
// 68-column definition — mirrors index_v2.html:1114-1191 exactly
// ─────────────────────────────────────────────────────────────────────

type ColKind = "text" | "num" | "int" | "pct" | "money" | "date" | "flag" | "cat" | "status" | "link";
interface ColDef {
  key: string;
  header: string;
  kind: ColKind;
  /** null = Tier-3 (backend doesn't return it yet — render "—"). */
  render: (r: AdsAnalyseRow, cat: CategoryKey) => React.ReactNode | null;
  /** Whether the column is on by default (matches CTD's default-visible set). */
  defaultVisible?: boolean;
  /** Group for the column picker's grouping. */
  group: "Identity" | "Timeline" | "Category" | "Delivery" | "Reach" | "Efficiency" | "Meta metrics" | "Shopify" | "Links";
}

function fmt(n: number | null | undefined, opts: Intl.NumberFormatOptions = {}) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toLocaleString(undefined, opts);
}
function money(n: number | null | undefined) {
  return fmt(n, { maximumFractionDigits: 0 });
}
function pct(n: number | null | undefined) {
  return fmt(n, { maximumFractionDigits: 2 });
}
function fmtCompact(n: number | null | undefined) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e7) return `${(n / 1e7).toFixed(2)}Cr`;
  if (abs >= 1e5) return `${(n / 1e5).toFixed(2)}L`;
  if (abs >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return Math.round(n).toLocaleString();
}
function fmtMoney(n: number | null | undefined) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return "₹" + fmtCompact(n);
}
function num2(n: number | null | undefined) {
  return fmt(n, { maximumFractionDigits: 2 });
}
function num3(n: number | null | undefined) {
  return fmt(n, { maximumFractionDigits: 3 });
}

/** Renders "—" with a tooltip for Tier-3 columns that need Silver-layer work. */
function Placeholder({ reason }: { reason: string }) {
  return (
    <span className="text-text-tertiary" title={reason}>
      —
    </span>
  );
}

function FBadge({ pass, name }: { pass: boolean | null; name: string }) {
  const cls = pass === null ? "u" : pass ? "y" : "n";
  const label = pass === null ? "unknown" : pass ? "passed" : "failed";
  return (
    <span className={`ae-flag ${cls}`} title={`${name}: ${label}`}>
      {pass === null ? "?" : pass ? "Y" : "N"}
    </span>
  );
}

function CatBadge({ cat }: { cat: CategoryKey }) {
  return <span className={`cat-badge ${CATEGORY_CLASS[cat]}`}>{cat}</span>;
}

function StatusPill({ status }: { status: string | null }) {
  if (!status) return <span>—</span>;
  const active = status.toUpperCase() === "ACTIVE";
  return <span className={`ae-status ${active ? "active" : ""}`}>{status}</span>;
}

// Asset ID cell — shows the mapped asset with a small badge indicating
// how the mapping was resolved. Backend chain (highest confidence first):
//   direct           workflow-optimiser explicit ad_id link
//   ctd_matched      CTD's fuzzy substring matcher hit
//   name_parsed      regex-extracted from ad_name AND verified in a register table
//   name_synthetic   regex-extracted only — surfaced so a merchant can
//                    trace which brief the ad_name refers to, even if
//                    that brief isn't in the register yet
const ASSET_SOURCE_META: Record<
  NonNullable<AdsAnalyseRow["asset_match_source"]>,
  { label: string; cls: string }
> = {
  direct: { label: "direct", cls: "bg-emerald-100 text-emerald-800 border-emerald-200" },
  ctd_matched: { label: "match", cls: "bg-sky-100 text-sky-800 border-sky-200" },
  name_parsed: { label: "parsed", cls: "bg-amber-100 text-amber-800 border-amber-200" },
  name_synthetic: { label: "synth", cls: "bg-slate-100 text-slate-600 border-slate-200" },
};

const ASSET_MEDIA_ICON: Record<NonNullable<AdsAnalyseRow["asset_media"]>, string> = {
  video: "🎬",
  graphic: "🖼",
  influencer: "👤",
};

function AssetIdCell({ row }: { row: AdsAnalyseRow }) {
  if (!row.asset_id) return <span className="text-text-tertiary">—</span>;
  const src = row.asset_match_source;
  const media = row.asset_media;
  const meta = src ? ASSET_SOURCE_META[src] : null;
  return (
    <span className="inline-flex items-center gap-1">
      {media && <span title={media}>{ASSET_MEDIA_ICON[media]}</span>}
      <span className="font-mono text-[11px]">{row.asset_id}</span>
      {meta && (
        <span
          className={`rounded border px-1 text-[10px] font-medium ${meta.cls}`}
          title={`Mapped via ${src?.replace("_", " ")}`}
        >
          {meta.label}
        </span>
      )}
    </span>
  );
}

// Preview cell. Renders a 40x40 thumbnail when available (Meta CDN URL
// from ad_media silver, ~19% coverage). If we don't have the raw
// thumbnail but DO have the FB post story_id (78% coverage), show a
// small Facebook-logo tile so the user still gets access to the
// iframe-embedded preview.
//
// Click -> lightbox with a fidelity ladder:
//   1. FB post iframe embed if effective_object_story_id is set
//      (this is what CTD dashboard.js does at _iframeUrlForFb -- shows
//      the ACTUAL post with caption, CTA, likes, media, etc.)
//   2. Video <video controls autoplay> if is_video + video_url set
//   3. Full-size image
//   4. Grey placeholder (no data at all)
function ThumbnailCell({ row }: { row: AdsAnalyseRow }) {
  const [open, setOpen] = useState(false);
  const hasThumb = !!row.thumbnail_url;
  const hasIg = !!row.instagram_permalink;
  const hasStory = !!row.effective_object_story_id;
  const hasVideo = !!row.video_source_url || (row.is_video && !!row.video_url);
  const hasAnyPreview = hasThumb || hasIg || hasStory;

  // Preview priority (matches CTD dashboard.js:1536-1541):
  //   1. Instagram /embed/captioned/ -- 89% coverage, works for dark posts
  //   2. Native <video> playback if we have a signed source URL
  //   3. Facebook plugin/post.php -- 78% coverage but often fails on dark posts
  //   4. Static image
  const igEmbedUrl = row.instagram_permalink
    ? (() => {
        const m = row.instagram_permalink.match(/instagram\.com\/(p|reel|tv)\/([^/?#]+)/i);
        if (!m) return null;
        return `https://www.instagram.com/${m[1]}/${m[2]}/embed/captioned/`;
      })()
    : null;
  const fbIframeUrl = row.effective_object_story_id
    ? (() => {
        const [pageId, postId] = row.effective_object_story_id.split("_");
        if (!pageId || !postId) return null;
        const href = `https://www.facebook.com/${pageId}/posts/${postId}`;
        return `https://www.facebook.com/plugins/post.php?href=${encodeURIComponent(href)}&show_text=true&width=500`;
      })()
    : null;

  if (!hasAnyPreview) {
    return (
      <div
        className="flex h-10 w-10 items-center justify-center rounded bg-slate-100 text-[9px] text-slate-400"
        title="No preview available — ad has no IG permalink, no FB story_id, and no cached thumbnail"
      >
        —
      </div>
    );
  }

  return (
    <>
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(true); }}
        className="group relative h-10 w-10 overflow-hidden rounded ring-1 ring-slate-200 hover:ring-slate-400"
        title={
          igEmbedUrl
            ? "Instagram post — click for iframe preview"
            : fbIframeUrl
              ? "Click to preview Facebook post"
              : hasVideo
                ? "Video ad — click to play"
                : "Click to enlarge"
        }
      >
        {hasThumb ? (
          <>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={row.thumbnail_url!}
              alt=""
              loading="lazy"
              className="h-full w-full object-cover"
            />
            {(row.is_video || hasVideo) && (
              <span className="absolute inset-0 flex items-center justify-center bg-black/25 text-white text-[10px] font-bold">
                ▶
              </span>
            )}
          </>
        ) : igEmbedUrl ? (
          // Instagram gradient tile as the fallback when we have the IG
          // permalink but no cached thumbnail image.
          <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-[#833AB4] via-[#FD1D1D] to-[#FCB045] text-[13px] font-bold text-white">
            IG
          </div>
        ) : (
          <div className="flex h-full w-full items-center justify-center bg-[#1877F2] text-[11px] font-bold text-white">
            f
          </div>
        )}
      </button>
      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-8"
          onClick={() => setOpen(false)}
        >
          <div
            className="relative flex max-h-[90vh] max-w-[90vw] flex-col rounded-lg bg-white p-2 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={() => setOpen(false)}
              className="absolute -right-3 -top-3 z-10 h-8 w-8 rounded-full bg-white text-lg font-bold shadow-lg"
              aria-label="Close"
            >
              ×
            </button>
            {igEmbedUrl ? (
              // Instagram post iframe embed -- Meta serves the correct
              // X-Frame-Options for this endpoint so it works for
              // dark-post ads too. Height 640 accommodates typical
              // reels/feed posts; the modal shell handles scroll.
              <iframe
                src={igEmbedUrl}
                width={400}
                height={640}
                className="rounded border-0"
                title={row.ad_name ?? "Instagram post preview"}
                allow="encrypted-media"
                allowFullScreen
                scrolling="no"
              />
            ) : row.video_source_url || (row.is_video && row.video_url) ? (
              // eslint-disable-next-line jsx-a11y/media-has-caption
              <video
                src={row.video_source_url ?? row.video_url!}
                controls
                autoPlay
                className="max-h-[85vh] max-w-[85vw] rounded"
              />
            ) : fbIframeUrl ? (
              <iframe
                src={fbIframeUrl}
                width={500}
                height={640}
                className="rounded border-0"
                title={row.ad_name ?? "Facebook post preview"}
                allow="encrypted-media"
                allowFullScreen
              />
            ) : (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={row.thumbnail_url!}
                alt={row.ad_name ?? ""}
                className="max-h-[85vh] max-w-[85vw] rounded object-contain"
              />
            )}
            <div className="mt-2 max-w-[500px] px-2 text-center text-xs text-text-secondary">
              {row.ad_name}
              {igEmbedUrl ? (
                <div className="mt-1 text-[10px] text-text-tertiary">
                  Instagram post embed ·{" "}
                  <a
                    href={row.instagram_permalink!}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="underline"
                  >
                    open on IG ↗
                  </a>
                </div>
              ) : fbIframeUrl ? (
                <div className="mt-1 text-[10px] text-text-tertiary">
                  Facebook post embed · story_id {row.effective_object_story_id}
                </div>
              ) : null}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

// Landing-page cell. Priority: real URL from ad_media silver
// (link_urls[0].website_url) > fall back to the "?" badge. Renders the
// URL type badge (Prod/Coll/Home/etc from landingType) + a clickable
// truncated URL that opens in a new tab. Hover shows the full URL.
function LandingPageCell({ row }: { row: AdsAnalyseRow }) {
  const url = row.landing_page_url;
  if (!url) {
    return (
      <span className="text-text-tertiary" title="Landing URL not in ad_media silver">—</span>
    );
  }
  const t = landingType(url);
  const pretty = url.replace(/^https?:\/\/(www\.)?/, "").slice(0, 40);
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${t.cls}`}>{t.badge}</span>
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        onClick={(e) => e.stopPropagation()}
        className="text-[12px] text-accent-blue underline hover:text-accent-blue-dark"
        title={url}
      >
        {pretty}
      </a>
    </span>
  );
}

/** Landing-page URL type from CTD dashboard.js:7600-7617. */
function landingType(url: string | null): { badge: string; cls: string } {
  if (!url) return { badge: "?", cls: "lp-other" };
  const lower = url.toLowerCase();
  if (lower.includes("/collections/")) return { badge: "Coll", cls: "lp-coll" };
  if (lower.includes("/products/")) return { badge: "Prod", cls: "lp-prod" };
  if (lower.includes("/pages/")) return { badge: "Page", cls: "lp-page" };
  if (lower.includes("/blogs/")) return { badge: "Blog", cls: "lp-blog" };
  if (/^https?:\/\/[^/]+\/?$/.test(url)) return { badge: "Home", cls: "lp-home" };
  return { badge: "Other", cls: "lp-other" };
}

const COLUMNS: ColDef[] = [
  // Identity
  { key: "preview_thumb", header: "Preview", kind: "link", group: "Identity", defaultVisible: true,
    render: (r) => <ThumbnailCell row={r} /> },
  { key: "ad_name", header: "Ad Name", kind: "text", group: "Identity", defaultVisible: true,
    render: (r) => <span title={r.ad_name ?? ""}>{r.ad_name ?? "—"}</span> },
  { key: "ad_id", header: "Ad ID", kind: "text", group: "Identity", defaultVisible: true,
    render: (r) => <span className="num">{r.ad_id.slice(0, 12)}…</span> },
  { key: "asset_id", header: "Asset ID", kind: "text", group: "Identity", defaultVisible: true,
    render: (r) => <AssetIdCell row={r} /> },
  { key: "campaign_name", header: "Campaign", kind: "text", group: "Identity", defaultVisible: true,
    render: (r) => <span title={r.campaign_name ?? ""}>{r.campaign_name ?? "—"}</span> },
  { key: "adset_id", header: "Ad Set ID", kind: "text", group: "Identity",
    render: (r) => <span className="num">{r.adset_id?.slice(0, 12) ?? "—"}…</span> },
  { key: "attribution", header: "Attribution", kind: "link", group: "Identity",
    render: () => <Placeholder reason="Daily attribution drill-down needs new /admin/analytics/ad-daily endpoint" /> },
  { key: "account_name", header: "Account", kind: "text", group: "Identity", defaultVisible: true,
    render: (r) => <span>{r.account_name ?? "—"}</span> },
  // Timeline
  { key: "ad_created_date", header: "Created", kind: "date", group: "Timeline", defaultVisible: true,
    render: (r) => <span>{r.ad_created_date ?? "—"}</span> },
  { key: "first_seen_date", header: "First Seen", kind: "date", group: "Timeline",
    render: (r) => <span>{r.first_seen_date ?? "—"}</span> },
  { key: "date_target_imp_achieved", header: "F1 Hit Date", kind: "date", group: "Timeline",
    render: () => <Placeholder reason="F1 hit date needs cumulative daily impressions scan — audit item C" /> },
  { key: "date_of_result", header: "Result Date", kind: "date", group: "Timeline",
    render: () => <Placeholder reason="Result date needs threshold-crossing timeline — audit item C" /> },
  { key: "days_to_result", header: "Days Result", kind: "int", group: "Timeline",
    render: () => <Placeholder reason="Depends on Result Date" /> },
  { key: "days_to_target_f1", header: "Days F1", kind: "int", group: "Timeline",
    render: () => <Placeholder reason="Depends on F1 Hit Date" /> },
  // Category / Flags
  { key: "category", header: "Category", kind: "cat", group: "Category", defaultVisible: true,
    render: (_r, cat) => <CatBadge cat={cat} /> },
  { key: "f1_pass", header: "F1", kind: "flag", group: "Category", defaultVisible: true,
    render: (r, _c, ) => <FBadge pass={r.f1_pass} name="F1" /> },
  { key: "f2_pass", header: "F2", kind: "flag", group: "Category", defaultVisible: true,
    render: (r) => <FBadge pass={r.f2_pass} name="F2" /> },
  { key: "f3_pass", header: "F3", kind: "flag", group: "Category", defaultVisible: true,
    render: (r) => <FBadge pass={r.f3_pass} name="F3" /> },
  { key: "f4_pass", header: "F4", kind: "flag", group: "Category", defaultVisible: true,
    render: (r) => <FBadge pass={r.f4_pass} name="F4" /> },
  { key: "ad_status", header: "Ad Status", kind: "status", group: "Category", defaultVisible: true,
    render: (r) => <StatusPill status={r.ad_effective_status ?? r.ad_status} /> },
  // Delivery
  { key: "impressions", header: "Impressions", kind: "int", group: "Delivery", defaultVisible: true,
    render: (r) => <span className="num">{fmt(r.impressions, { maximumFractionDigits: 0 })}</span> },
  { key: "reach", header: "Reach", kind: "int", group: "Reach", defaultVisible: true,
    render: (r) => <span className="num">{fmt(r.reach, { maximumFractionDigits: 0 })}</span> },
  { key: "reach_weight_pct", header: "Reach Weight %", kind: "pct", group: "Reach",
    render: () => <Placeholder reason="Needs fleet-total reach normalisation — audit item A/B" /> },
  { key: "previous_reach", header: "Prev Reach", kind: "int", group: "Reach",
    render: () => <Placeholder reason="Needs ae_reach_recent daily snapshot table — audit item B" /> },
  { key: "latest_reach", header: "Latest Reach", kind: "int", group: "Reach",
    render: () => <Placeholder reason="Needs ae_reach_recent daily snapshot table — audit item B" /> },
  { key: "incremental_reach", header: "Incr. Reach", kind: "int", group: "Reach",
    render: () => <Placeholder reason="Needs ae_reach_recent (latest − prev) — audit item B" /> },
  { key: "cost_per_1000_incremental_reach", header: "Cost / 1k Incr.", kind: "money", group: "Reach",
    render: () => <Placeholder reason="Needs reach snapshot + windowed spend — audit item B" /> },
  { key: "frequency", header: "Freq", kind: "num", group: "Delivery", defaultVisible: true,
    render: (r) => <span className="num">{num2(r.frequency)}</span> },
  { key: "spend", header: "Spend", kind: "money", group: "Delivery", defaultVisible: true,
    render: (r) => <span className="num">₹{money(r.spend)}</span> },
  { key: "cost_per_1000", header: "Cost/1k", kind: "money", group: "Delivery", defaultVisible: true,
    render: (r) => <span className="num">₹{num2(r.cost_per_1000)}</span> },
  { key: "cpc_link", header: "CPC Link", kind: "money", group: "Delivery",
    render: (r) => <span className="num">₹{num2(r.cpc_link)}</span> },
  { key: "ctr_pct", header: "CTR %", kind: "pct", group: "Delivery",
    render: (r) => <span className="num">{pct(r.ctr_pct)}%</span> },
  { key: "link_clicks_raw", header: "Link Clicks", kind: "int", group: "Delivery",
    render: (r) => <span className="num">{fmt(r.link_clicks_raw, { maximumFractionDigits: 0 })}</span> },
  { key: "atc_count", header: "ATC", kind: "int", group: "Delivery",
    render: (r) => <span className="num">{fmt(r.atc_count, { maximumFractionDigits: 0 })}</span> },
  { key: "atc_lc_pct", header: "ATC/LC %", kind: "pct", group: "Delivery",
    render: (r) => <span className="num">{pct(r.atc_lc_pct)}%</span> },
  { key: "ci_count", header: "CI", kind: "int", group: "Delivery",
    render: (r) => <span className="num">{fmt(r.ci_count, { maximumFractionDigits: 0 })}</span> },
  { key: "ci_atc_pct", header: "CI/ATC %", kind: "pct", group: "Delivery",
    render: (r) => <span className="num">{pct(r.ci_atc_pct)}%</span> },
  { key: "checkout_compl_pct", header: "Checkout %", kind: "pct", group: "Delivery",
    render: (r) => <span className="num">{pct(r.checkout_compl_pct)}%</span> },
  { key: "cr_lc_pct", header: "CR/LC %", kind: "pct", group: "Delivery",
    render: (r) => <span className="num">{pct(r.cr_lc_pct)}%</span> },
  // Meta metrics
  { key: "purchases", header: "Purchases", kind: "num", group: "Meta metrics", defaultVisible: true,
    render: (r) => <span className="num">{num2(r.purchases)}</span> },
  { key: "conv_value", header: "Conv Value", kind: "money", group: "Meta metrics",
    render: (r) => <span className="num">₹{money(r.conv_value)}</span> },
  { key: "roas", header: "ROAS", kind: "num", group: "Meta metrics", defaultVisible: true,
    render: (r) => <span className="num">{num2(r.roas)}</span> },
  // Shopify
  { key: "shopify_orders", header: "Shop Orders", kind: "int", group: "Shopify", defaultVisible: true,
    render: (r) => <span className="num">{fmt(r.shopify_orders, { maximumFractionDigits: 0 })}</span> },
  { key: "shopify_revenue", header: "Shop Sales", kind: "money", group: "Shopify", defaultVisible: true,
    render: (r) => <span className="num">₹{money(r.shopify_revenue)}</span> },
  { key: "shopify_roas", header: "Shop ROAS", kind: "num", group: "Shopify", defaultVisible: true,
    render: (r) => <span className="num">{num2(r.shopify_roas)}</span> },
  { key: "meta_shop_diff_pct", header: "% Meta vs Shop", kind: "pct", group: "Shopify", defaultVisible: true,
    render: (r) => (
      <span
        className={
          "num " +
          (r.meta_shop_diff_pct === null
            ? ""
            : r.meta_shop_diff_pct < -20
              ? "text-rose-600"
              : r.meta_shop_diff_pct > 20
                ? "text-emerald-600"
                : "")
        }
      >
        {pct(r.meta_shop_diff_pct)}%
      </span>
    ) },
  { key: "cost_per_ftewv", header: "Cost/FTEWV", kind: "money", group: "Meta metrics", defaultVisible: true,
    render: (r) => <span className="num">₹{num2(r.cost_per_ftewv)}</span> },
  { key: "ftewv_count", header: "FTEWV", kind: "int", group: "Meta metrics",
    render: (r) => <span className="num">{fmt(r.ftewv_count, { maximumFractionDigits: 0 })}</span> },
  { key: "pct_reach_ftewv", header: "% Reach FTEWV", kind: "pct", group: "Meta metrics",
    render: (r) => <span className="num">{pct(r.pct_reach_ftewv)}%</span> },
  { key: "cost_per_ncp", header: "Cost/NCP", kind: "money", group: "Meta metrics", defaultVisible: true,
    render: (r) => <span className="num">₹{money(r.cost_per_ncp)}</span> },
  { key: "ncp_count", header: "NCP", kind: "int", group: "Meta metrics", defaultVisible: true,
    render: (r) => <span className="num">{fmt(r.ncp_count, { maximumFractionDigits: 0 })}</span> },
  { key: "profit_efficiency", header: "Profit Eff", kind: "money", group: "Efficiency",
    render: (r) => <span className="num">₹{money(r.profit_efficiency)}</span> },
  { key: "contrib_margin_pct", header: "Contrib Margin %", kind: "pct", group: "Efficiency", defaultVisible: true,
    render: (r) => <span className="num">{pct(r.contrib_margin_pct)}%</span> },
  // Fleet-anchored efficiency scores — Tier 3 (audit item A)
  { key: "blended_eff", header: "Blended Eff", kind: "num", group: "Efficiency",
    render: () => <Placeholder reason="Fleet-anchored ranking (audit item A) — needs refresh_efficiency_scores.py" /> },
  { key: "delivery_eff", header: "Delivery Eff", kind: "num", group: "Efficiency",
    render: () => <Placeholder reason="Fleet-anchored ranking (audit item A)" /> },
  { key: "sales_spend_eff", header: "Sales/Spend Eff", kind: "num", group: "Efficiency",
    render: () => <Placeholder reason="Fleet-anchored ranking (audit item A)" /> },
  { key: "cpr_eff", header: "CPR Eff", kind: "num", group: "Efficiency",
    render: () => <Placeholder reason="Fleet-anchored ranking (audit item A)" /> },
  { key: "ftv_contrib_eff", header: "FTV Contrib Eff", kind: "num", group: "Efficiency",
    render: () => <Placeholder reason="Fleet-anchored ranking (audit item A)" /> },
  { key: "ftev_volume", header: "FTEV Volume", kind: "num", group: "Efficiency",
    render: () => <Placeholder reason="Fleet-anchored ranking (audit item A)" /> },
  { key: "ncp_cost_eff", header: "NCP Cost Eff", kind: "num", group: "Efficiency",
    render: () => <Placeholder reason="Fleet-anchored ranking (audit item A)" /> },
  { key: "roas_eff", header: "ROAS Eff", kind: "num", group: "Efficiency",
    render: () => <Placeholder reason="Fleet-anchored ranking (audit item A)" /> },
  { key: "profit_vol_eff", header: "Profit Vol Eff", kind: "num", group: "Efficiency",
    render: () => <Placeholder reason="Fleet-anchored ranking (audit item A)" /> },
  // Lifetime metrics
  { key: "ltv_reach", header: "LTV Reach", kind: "int", group: "Reach",
    render: (r) => <span className="num">{fmt(r.ltv_reach, { maximumFractionDigits: 0 })}</span> },
  { key: "ltv_frequency", header: "LTV Freq", kind: "num", group: "Reach",
    render: (r) => <span className="num">{num2(r.ltv_frequency)}</span> },
  { key: "engagement_count", header: "Engagement", kind: "int", group: "Delivery",
    render: (r) => <span className="num">{fmt(r.engagement_count, { maximumFractionDigits: 0 })}</span> },
  { key: "preview_link", header: "Preview", kind: "link", group: "Links",
    render: () => <Placeholder reason="Preview link needs Meta ad-preview URL construction — audit item D" /> },
  { key: "ad_link", header: "Ad Link", kind: "link", group: "Links",
    render: (r) => (
      <a
        href={`https://business.facebook.com/adsmanager/manage/ads/edit?act=${r.account_id ?? ""}&selected_ad_ids=${r.ad_id}`}
        target="_blank"
        rel="noreferrer"
        className="text-text-link hover:underline"
      >
        ▸ Open
      </a>
    ) },
  { key: "landing_page", header: "Landing page", kind: "link", group: "Links", defaultVisible: true,
    render: (r) => <LandingPageCell row={r} /> },
];

const ALL_KEYS = COLUMNS.map((c) => c.key);
const DEFAULT_VISIBLE_KEYS = new Set(COLUMNS.filter((c) => c.defaultVisible).map((c) => c.key));
const HIDDEN_STORAGE_KEY = "aeHiddenCols_v1";

// ─────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────

const PAGE_SIZE = 100;

export function AdsAnalyse() {
  // ── data ─────────────────────────────────────────────────────
  const [rows, setRows] = useState<AdsAnalyseRow[]>([]);
  const [total, setTotal] = useState(0);
  const [categoryCountsFromApi, setCategoryCountsFromApi] = useState<Record<string, number>>({});
  const [totals, setTotals] = useState<AdsAnalyseTotals | null>(null);
  const [accountOptions, setAccountOptions] = useState<Set<string>>(new Set());
  const [statusOptions, setStatusOptions] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ── filters ──────────────────────────────────────────────────
  const [levelToggle, setLevelToggle] = useState<"ad" | "adset" | "campaign">("ad");
  const [account, setAccount] = useState("");
  const [groupBy, setGroupBy] = useState<"ad" | "ad_name" | "adset" | "campaign">("ad");
  const [categoryFilter, setCategoryFilter] = useState<CategoryKey | "">("");
  const [adStatus, setAdStatus] = useState("");
  // Default to 'created' -- matches CTD's Creative Testing philosophy
  // where the point of the section is to evaluate recently-launched
  // creatives. Picking "Last 7 days" then means "ads launched in the
  // last 7 days" instead of "ads that ran in the last 7 days".
  const [dateField, setDateField] = useState<"delivery" | "created" | "first_seen">("created");
  const [search, setSearch] = useState("");
  const [onlyWithOrders, setOnlyWithOrders] = useState(false);
  // Date range window -- when both are set, spend / impressions /
  // purchases / conv_value / roas in the response are overwritten
  // with values summed from Bronze raw_dump_meta within the window.
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [datePreset, setDatePreset] = useState<string>("all");

  // ── F1..F4 thresholds ────────────────────────────────────────
  const [thresholds, setThresholds] = useState<FThresholds>(DEFAULT_THRESHOLDS);
  const [thresholdsOpen, setThresholdsOpen] = useState(false);
  const thresholdsChanged = useMemo(() => (
    thresholds.f1Imp !== DEFAULT_THRESHOLDS.f1Imp
    || thresholds.f2Roas !== DEFAULT_THRESHOLDS.f2Roas
    || thresholds.f3CostPerNcp !== DEFAULT_THRESHOLDS.f3CostPerNcp
    || thresholds.f4CostPerFtewv !== DEFAULT_THRESHOLDS.f4CostPerFtewv
    || thresholds.bufferDays !== DEFAULT_THRESHOLDS.bufferDays
  ), [thresholds]);

  // ── column picker ────────────────────────────────────────────
  const [hiddenCols, setHiddenCols] = useState<Set<string>>(() => {
    if (typeof window === "undefined") return new Set(ALL_KEYS.filter((k) => !DEFAULT_VISIBLE_KEYS.has(k)));
    try {
      const raw = window.localStorage.getItem(HIDDEN_STORAGE_KEY);
      if (raw) return new Set(JSON.parse(raw));
    } catch {}
    return new Set(ALL_KEYS.filter((k) => !DEFAULT_VISIBLE_KEYS.has(k)));
  });
  const [colPickerOpen, setColPickerOpen] = useState(false);
  const [colSearch, setColSearch] = useState("");
  useEffect(() => {
    try {
      window.localStorage.setItem(HIDDEN_STORAGE_KEY, JSON.stringify([...hiddenCols]));
    } catch {}
  }, [hiddenCols]);
  const visibleCols = COLUMNS.filter((c) => !hiddenCols.has(c.key));

  // ── inspector drawer ─────────────────────────────────────────
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [inspectorTab, setInspectorTab] = useState<"metrics" | "filters">("metrics");
  const [numericFilters, setNumericFilters] = useState<NumericFilter[]>([]);

  // ── sort ────────────────────────────────────────────────────
  const [sortKey, setSortKey] = useState<string>("spend");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  // ── pagination ──────────────────────────────────────────────
  const [page, setPage] = useState(0);

  // ── fetch data ──────────────────────────────────────────────
  const filters = useMemo(
    () => ({
      account_name: account || undefined,
      search: search || undefined,
      category: categoryFilter || undefined,
      ad_effective_status: adStatus || undefined,
      only_with_shopify_orders: onlyWithOrders,
      // Only send both together -- one without the other has no meaning
      // on the server side (the overlay/filter branch keys on both being set).
      from_date: fromDate && toDate ? fromDate : undefined,
      to_date: fromDate && toDate ? toDate : undefined,
      date_field: fromDate && toDate ? dateField : undefined,
    }),
    [account, search, categoryFilter, adStatus, onlyWithOrders, fromDate, toDate, dateField],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    // Fetch a large first batch so client-side recategorisation +
    // numeric filters have enough data to be useful without a
    // per-filter round-trip. 500 rows keeps under 1MB per fetch.
    fetchAdsAnalyse({ ...filters, limit: 500, offset: 0 })
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setTotal(res.total);
        setCategoryCountsFromApi(res.category_counts ?? {});
        setTotals(res.totals ?? null);
        setAccountOptions((prev) => {
          const next = new Set(prev);
          res.rows.forEach((r) => r.account_name && next.add(r.account_name));
          return next;
        });
        setStatusOptions((prev) => {
          const next = new Set(prev);
          res.rows.forEach((r) => r.ad_effective_status && next.add(r.ad_effective_status));
          return next;
        });
        setPage(0);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Could not reach the FastAPI backend. Is it running on :8001?");
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [filters]);

  async function loadMore() {
    setLoadingMore(true);
    try {
      const res = await fetchAdsAnalyse({ ...filters, limit: 500, offset: rows.length });
      setRows((prev) => [...prev, ...res.rows]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load more rows.");
    } finally {
      setLoadingMore(false);
    }
  }

  // ── client-side recategorise + numeric filter + sort ─────────
  const derived = useMemo(() => {
    const withCat = rows.map((r) => ({ row: r, cat: categorise(r, thresholds) }));
    // Category tile counts — from the client-side recategorisation
    // (so the F1..F4 threshold sliders update the tile numbers live).
    const tileCounts: Record<CategoryKey, number> = {
      "Incremental Winner": 0,
      Winner: 0,
      "P0 analysis": 0,
      "P1 analysis": 0,
      "P2 analysis": 0,
      "Result Awaited": 0,
      Discarded: 0,
    };
    withCat.forEach((rc) => (tileCounts[rc.cat] += 1));
    // Apply numeric filters
    const filtered = withCat.filter((rc) => {
      if (categoryFilter && rc.cat !== categoryFilter) return false;
      for (const nf of numericFilters) {
        const v = (rc.row as unknown as Record<string, number | null>)[nf.field];
        if (v === null || v === undefined || Number.isNaN(v)) return false;
        if (!applyOperator(v, nf.op, nf.value)) return false;
      }
      return true;
    });
    // Sort
    const sorted = [...filtered].sort((a, b) => {
      const av = (a.row as unknown as Record<string, unknown>)[sortKey];
      const bv = (b.row as unknown as Record<string, unknown>)[sortKey];
      const cmp = compareForSort(av, bv);
      return sortDir === "asc" ? cmp : -cmp;
    });
    return { withCat, tileCounts, filtered: sorted };
  }, [rows, thresholds, categoryFilter, numericFilters, sortKey, sortDir]);

  // ── pagination window ───────────────────────────────────────
  const pageRows = derived.filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const totalPages = Math.max(1, Math.ceil(derived.filtered.length / PAGE_SIZE));

  function toggleSort(key: string) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  function clearAllFilters() {
    setAccount("");
    setSearch("");
    setCategoryFilter("");
    setAdStatus("");
    setOnlyWithOrders(false);
    setGroupBy("ad");
    setDateField("delivery");
    setNumericFilters([]);
    setThresholds(DEFAULT_THRESHOLDS);
    setFromDate("");
    setToDate("");
    setDatePreset("all");
  }

  return (
    <div className="flex flex-col gap-3">
      {/* ═══════════════════════════════════════════════════════════
          Level toggle — CTD's Ad / Adset / Campaign pills
         ═══════════════════════════════════════════════════════════ */}
      {/* Tight header row -- kwikengage-style. Section title + level
          pills sit inline; the old "Row-level Creative Testing (CTD
          ae_table_view port)" descriptive paragraph is dropped
          (2026-08-29 declutter) since users already know which tab
          they clicked. The row count on the right replaces it as a
          more useful piece of context. */}
      <div className="flex items-baseline gap-3">
        <h2 className="text-base font-semibold text-text-primary">Creative Testing</h2>
        <div className="inline-flex rounded-md border border-border-primary bg-white shadow-sm">
          {(["ad", "adset", "campaign"] as const).map((lv) => (
            <button
              key={lv}
              onClick={() => setLevelToggle(lv)}
              disabled={lv !== "ad"}
              title={lv === "ad" ? "Ad level" : `${lv} rollup needs backend RPCs — Phase 2`}
              className={
                "px-3 py-1 text-xs first:rounded-l-md last:rounded-r-md " +
                (levelToggle === lv
                  ? "bg-slate-900 text-white"
                  : lv === "ad"
                    ? "text-text-primary hover:bg-bg-muted"
                    : "text-text-tertiary cursor-not-allowed")
              }
            >
              {lv === "ad" ? "Ads" : lv === "adset" ? "Ad Sets" : "Campaigns"}
            </button>
          ))}
        </div>
        <span className="ml-auto text-xs text-text-tertiary">
          {loading ? "loading…" : `${derived.filtered.length.toLocaleString()} of ${total.toLocaleString()} ads`}
        </span>
      </div>

      {/* ═══════════════════════════════════════════════════════════
          Filter row 1: Account / Group / Category / Status / Date field / Date range
         ═══════════════════════════════════════════════════════════ */}
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border-primary bg-white p-2 shadow-sm">
        <select
          value={account}
          onChange={(e) => setAccount(e.target.value)}
          className="rounded-md border border-border-primary px-2 py-1 text-sm"
        >
          <option value="">Account: All</option>
          {[...accountOptions].sort().map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
        <select
          value={groupBy}
          onChange={(e) => setGroupBy(e.target.value as typeof groupBy)}
          disabled
          title="Group By needs backend adset/campaign rollup RPCs — Phase 2"
          className="rounded-md border border-border-primary px-2 py-1 text-sm text-text-tertiary"
        >
          <option value="ad">Group by: Ad</option>
          <option value="ad_name">Group by: Ad Name</option>
          <option value="adset">Group by: Adset</option>
          <option value="campaign">Group by: Campaign</option>
        </select>
        <select
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value as CategoryKey | "")}
          className="rounded-md border border-border-primary px-2 py-1 text-sm"
        >
          <option value="">Category: All</option>
          {CATEGORY_ORDER.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <select
          value={adStatus}
          onChange={(e) => setAdStatus(e.target.value)}
          className="rounded-md border border-border-primary px-2 py-1 text-sm"
        >
          <option value="">Status: All</option>
          {[...statusOptions].sort().map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <select
          value={dateField}
          onChange={(e) => setDateField(e.target.value as typeof dateField)}
          title={
            "Applies to the [from, to] window: " +
            "Created hides ads outside the window (default); " +
            "First Seen filters by first_seen_date; " +
            "Delivery keeps every ad but overlays windowed spend/impressions/reach."
          }
          className="rounded-md border border-border-primary bg-white px-2 py-1 text-sm"
        >
          <option value="created">Date: Created</option>
          <option value="first_seen">Date: First Seen</option>
          <option value="delivery">Date: Delivery</option>
        </select>
        {/* Date range window -- when both bounds are set, backend
            overwrites spend/impressions/reach/purchases/conv_value/roas
            with values summed from Bronze insights in that window. */}
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
            if (v === "all") { setFromDate(""); setToDate(""); }
            else if (v === "today") { setFromDate(today); setToDate(today); }
            else if (v === "7d") { setFromDate(daysAgo(6)); setToDate(today); }
            else if (v === "14d") { setFromDate(daysAgo(13)); setToDate(today); }
            else if (v === "30d") { setFromDate(daysAgo(29)); setToDate(today); }
            else if (v === "90d") { setFromDate(daysAgo(89)); setToDate(today); }
          }}
          className="rounded-md border border-border-primary bg-white px-2 py-1 text-sm"
          title="Date-range window applied to spend/impressions/reach/purchases/conv_value/roas"
        >
          <option value="all">All time</option>
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
          className="rounded-md border border-border-primary bg-white px-2 py-1 text-sm"
          title="Window start (YYYY-MM-DD)"
        />
        <span className="text-xs text-text-secondary">→</span>
        <input
          type="date"
          value={toDate}
          onChange={(e) => { setToDate(e.target.value); setDatePreset("custom"); }}
          className="rounded-md border border-border-primary bg-white px-2 py-1 text-sm"
          title="Window end (YYYY-MM-DD)"
        />
        {fromDate && toDate && (
          <span
            className="rounded-full bg-sky-100 px-2 py-0.5 text-[10px] font-semibold text-sky-800"
            title="Spend / impressions / reach / purchases / conv_value / ROAS reflect this window; other columns stay lifetime"
          >
            windowed
          </span>
        )}
        <button
          onClick={clearAllFilters}
          className="rounded-md border border-border-primary bg-white px-2 py-1 text-xs hover:bg-bg-muted"
        >
          Clear Filters
        </button>
        <button
          onClick={() => setColPickerOpen((v) => !v)}
          className="rounded-md border border-border-primary bg-white px-2 py-1 text-xs hover:bg-bg-muted"
          title="Show/hide columns"
        >
          ▤ Columns ({visibleCols.length}/{COLUMNS.length})
        </button>
        <button
          onClick={() => setInspectorOpen((v) => !v)}
          className="rounded-md border border-border-primary bg-white px-2 py-1 text-xs hover:bg-bg-muted"
          title="Inspector: Metrics + numeric Filters"
        >
          ⚙ Inspector {numericFilters.length > 0 && <span className="ml-1 rounded bg-yellow-200 px-1 text-yellow-900">{numericFilters.length}</span>}
        </button>
      </div>

      {/* ═══════════════════════════════════════════════════════════
          Search + shop-orders toggle + collapsed thresholds button.
          Thresholds were previously in a 5-input row above the KPI
          tiles which visually competed with everything else -- moved
          to a popover so the primary flow (KPIs → filters → table)
          stays clean. A "modified" pill flags when the user has
          diverged from CTD's defaults (2026-08-29 declutter pass).
         ═══════════════════════════════════════════════════════════ */}
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border-primary bg-white p-2 shadow-sm">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search ad name…"
          className="w-64 rounded-md border border-border-primary px-2 py-1 text-sm"
        />
        <label className="flex items-center gap-1.5 text-xs">
          <input type="checkbox" checked={onlyWithOrders} onChange={(e) => setOnlyWithOrders(e.target.checked)} />
          Has Shopify orders
        </label>
        <div className="relative ml-auto">
          <button
            onClick={() => setThresholdsOpen((v) => !v)}
            className={
              "flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs transition-colors " +
              (thresholdsChanged
                ? "border-amber-300 bg-amber-50 text-amber-900 hover:bg-amber-100"
                : "border-border-primary bg-white text-text-primary hover:bg-bg-muted")
            }
          >
            <span>F1..F4 thresholds</span>
            {thresholdsChanged && (
              <span className="rounded-full bg-amber-200 px-1.5 py-0.5 text-[9px] font-semibold">
                modified
              </span>
            )}
            <span className="text-text-tertiary">{thresholdsOpen ? "▴" : "▾"}</span>
          </button>
          {thresholdsOpen && (
            <div
              onClick={(e) => e.stopPropagation()}
              className="absolute right-0 top-full z-30 mt-1 w-80 rounded-lg border border-border-primary bg-white p-3 shadow-lg"
            >
              <div className="mb-2 flex items-center justify-between">
                <h4 className="text-sm font-semibold">F1..F4 thresholds</h4>
                <button
                  onClick={() => setThresholds(DEFAULT_THRESHOLDS)}
                  className="rounded border border-border-primary bg-white px-2 py-0.5 text-[10px] hover:bg-bg-muted"
                >
                  Reset defaults
                </button>
              </div>
              <p className="mb-2 text-[10px] text-text-tertiary">
                Client-side recategorises rows on every keystroke — no round-trip.
              </p>
              <div className="flex flex-col gap-1.5">
                <NumInput label="F1 Imp ≥" value={thresholds.f1Imp} onChange={(v) => setThresholds({ ...thresholds, f1Imp: v })} />
                <NumInput label="F2 ROAS ≥" value={thresholds.f2Roas} onChange={(v) => setThresholds({ ...thresholds, f2Roas: v })} step={0.1} />
                <NumInput label="F3 C/NCP ≤" value={thresholds.f3CostPerNcp} onChange={(v) => setThresholds({ ...thresholds, f3CostPerNcp: v })} />
                <NumInput label="F4 C/FTEWV ≤" value={thresholds.f4CostPerFtewv} onChange={(v) => setThresholds({ ...thresholds, f4CostPerFtewv: v })} step={0.5} />
                <NumInput label="Result buffer (days)" value={thresholds.bufferDays} onChange={(v) => setThresholds({ ...thresholds, bufferDays: v })} />
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ═══════════════════════════════════════════════════════════
          Aggregate KPI strip — 8 tiles mirroring kwikengage's
          Marketing Insights row (Total Orders / Total Sales / Total
          Buyers / etc.). Reflects the current filter set from the
          server-side totals payload.
         ═══════════════════════════════════════════════════════════ */}
      {totals && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
          <KwikTile
            icon={<span className="text-base">◱</span>}
            iconColor="slate"
            label="Ads"
            value={totals.ad_count.toLocaleString()}
            subLine={`of ${total.toLocaleString()} in DB`}
          />
          <KwikTile
            icon={<span className="text-base">₹</span>}
            iconColor="sky"
            label="Spend"
            value={fmtMoney(totals.spend)}
          />
          <KwikTile
            icon={<span className="text-base">👁</span>}
            iconColor="purple"
            label="Impressions"
            value={fmtCompact(totals.impressions)}
          />
          <KwikTile
            icon={<span className="text-base">◉</span>}
            iconColor="teal"
            label="Reach"
            value={fmtCompact(totals.reach)}
          />
          <KwikTile
            icon={<span className="text-base">🛒</span>}
            iconColor="emerald"
            label="Purchases"
            value={fmtCompact(totals.purchases)}
            subLine={`${fmtCompact(totals.ncp_count)} NCP`}
          />
          <KwikTile
            icon={<span className="text-base">✦</span>}
            iconColor="amber"
            label="Meta ROAS"
            value={totals.avg_meta_roas !== null ? totals.avg_meta_roas.toFixed(2) : "—"}
            subLine={`${totals.avg_ctr_pct !== null ? totals.avg_ctr_pct.toFixed(2) + "% CTR" : ""}`}
          />
          <KwikTile
            icon={<span className="text-base">🛍</span>}
            iconColor="emerald"
            label="Shop orders"
            value={fmtCompact(totals.shopify_orders)}
            subLine={fmtMoney(totals.shopify_revenue)}
          />
          <KwikTile
            icon={<span className="text-base">◈</span>}
            iconColor="amber"
            label="Shop ROAS"
            value={totals.avg_shopify_roas !== null ? totals.avg_shopify_roas.toFixed(2) : "—"}
          />
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════
          7 KPI category tiles — click to filter
          Rebuilt on top of KwikTile (2026-08-29) to match the
          kwikengage Marketing Insights KPI-card aesthetic — icon
          square, uppercase label, big monospaced count, spend sub-line.
         ═══════════════════════════════════════════════════════════ */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
        {CATEGORY_ORDER.map((cat) => {
          const count = derived.tileCounts[cat];
          const spend = derived.withCat
            .filter((rc) => rc.cat === cat)
            .reduce((acc, rc) => acc + (rc.row.spend ?? 0), 0);
          const selected = categoryFilter === cat;
          return (
            <KwikTile
              key={cat}
              icon={<span className="text-base">{CATEGORY_ICON[cat]}</span>}
              iconColor={CATEGORY_ICON_COLOR[cat]}
              label={cat}
              value={count.toLocaleString()}
              subLine={`₹${money(spend)}`}
              active={selected}
              onClick={() => setCategoryFilter(selected ? "" : cat)}
            />
          );
        })}
      </div>

      {/* Analytical view — 3 charts anchor the section the way kwikengage's
          Marketing Insights row does. Re-computes from `derived.filtered`
          so filters, category selection, and threshold changes all
          propagate live without extra fetches. */}
      <AdsAnalyseCharts rows={derived.filtered} />

      {/* Total ads bar */}
      <div className="rounded-lg border border-border-primary bg-white px-3 py-1.5 text-xs text-text-secondary shadow-sm">
        Total shown in table: <strong className="text-text-primary">{derived.filtered.length.toLocaleString()}</strong> ads
        {categoryFilter && <> · filtered to <strong className="text-text-primary">{categoryFilter}</strong></>}
        {numericFilters.length > 0 && <> · {numericFilters.length} numeric rule{numericFilters.length > 1 ? "s" : ""}</>}
        · {total.toLocaleString()} total in DB
        {rows.length < total && <> · fetched first {rows.length.toLocaleString()}</>}
      </div>

      {/* Errors */}
      {error && <div className="rounded-md border border-error-mid bg-error-bg p-2 text-sm text-error-text">{error}</div>}

      {/* ═══════════════════════════════════════════════════════════
          Main table
         ═══════════════════════════════════════════════════════════ */}
      {loading ? (
        <p className="text-sm text-text-secondary">Loading…</p>
      ) : (
        <div className="max-h-[70vh] overflow-auto rounded-lg border border-border-primary bg-white shadow-sm">
          <table className="ae-table w-full text-left text-xs">
            <thead>
              <tr className="border-b border-border-primary text-[11px] text-text-secondary">
                {visibleCols.map((c) => (
                  <th
                    key={c.key}
                    onClick={() => toggleSort(c.key)}
                    className={
                      "cursor-pointer px-2 py-2 font-medium hover:bg-bg-muted " +
                      (c.kind === "num" || c.kind === "int" || c.kind === "pct" || c.kind === "money" ? "text-right" : "")
                    }
                    title={`Sort by ${c.header}`}
                  >
                    {c.header}
                    {sortKey === c.key && <span className="ml-1">{sortDir === "asc" ? "▲" : "▼"}</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {pageRows.map(({ row, cat }) => (
                <tr key={row.ad_id} className="border-b border-border-soft hover:bg-bg-surface">
                  {visibleCols.map((c) => (
                    <td key={c.key} className="px-2 py-1">
                      {c.render(row, cat)}
                    </td>
                  ))}
                </tr>
              ))}
              {pageRows.length === 0 && (
                <tr>
                  <td colSpan={visibleCols.length} className="px-4 py-6 text-center text-text-secondary">
                    No ads match these filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════
          Footer — pagination + cascade + diagnostics
         ═══════════════════════════════════════════════════════════ */}
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border-primary bg-white px-3 py-1.5 text-xs text-text-secondary shadow-sm">
        <span>
          delivered <strong className="text-text-primary">{rows.length.toLocaleString()}</strong>
          {" → "}post-filters <strong className="text-text-primary">{derived.filtered.length.toLocaleString()}</strong>
          {" → "}shown <strong className="text-text-primary">{pageRows.length.toLocaleString()}</strong>
        </span>
        <span className="ml-auto flex items-center gap-1">
          <button
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
            className="rounded border border-border-primary px-2 py-0.5 hover:bg-bg-muted disabled:opacity-40"
          >
            Prev
          </button>
          <span>
            Page {page + 1} / {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            disabled={page >= totalPages - 1}
            className="rounded border border-border-primary px-2 py-0.5 hover:bg-bg-muted disabled:opacity-40"
          >
            Next
          </button>
        </span>
        {rows.length < total && (
          <button
            onClick={loadMore}
            disabled={loadingMore}
            className="rounded border border-border-primary bg-white px-2 py-0.5 hover:bg-bg-muted disabled:opacity-40"
          >
            {loadingMore ? "Fetching…" : `Fetch next 500 (${rows.length}/${total})`}
          </button>
        )}
      </div>

      {/* ═══════════════════════════════════════════════════════════
          Column picker popover
         ═══════════════════════════════════════════════════════════ */}
      {colPickerOpen && (
        <div className="fixed inset-0 z-40 flex items-start justify-end bg-black/20" onClick={() => setColPickerOpen(false)}>
          <div className="mt-16 mr-4 w-96 max-h-[80vh] overflow-auto rounded-lg border border-border-primary bg-white p-3 shadow-lg" onClick={(e) => e.stopPropagation()}>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-sm font-semibold">Columns ({visibleCols.length}/{COLUMNS.length})</h3>
              <div className="flex gap-1">
                <button onClick={() => setHiddenCols(new Set())} className="rounded border px-2 py-0.5 text-xs hover:bg-bg-muted">All</button>
                <button onClick={() => setHiddenCols(new Set(ALL_KEYS))} className="rounded border px-2 py-0.5 text-xs hover:bg-bg-muted">None</button>
                <button
                  onClick={() => setHiddenCols(new Set(ALL_KEYS.filter((k) => !DEFAULT_VISIBLE_KEYS.has(k))))}
                  className="rounded border px-2 py-0.5 text-xs hover:bg-bg-muted"
                >
                  Reset
                </button>
              </div>
            </div>
            <input
              value={colSearch}
              onChange={(e) => setColSearch(e.target.value)}
              placeholder="Search columns…"
              className="mb-2 w-full rounded-md border border-border-primary px-2 py-1 text-sm"
            />
            {(["Identity", "Timeline", "Category", "Delivery", "Reach", "Efficiency", "Meta metrics", "Shopify", "Links"] as const).map((grp) => {
              const cols = COLUMNS.filter((c) => c.group === grp && c.header.toLowerCase().includes(colSearch.toLowerCase()));
              if (cols.length === 0) return null;
              return (
                <div key={grp} className="mb-2">
                  <div className="text-[10px] font-semibold uppercase tracking-wide text-text-secondary">{grp}</div>
                  {cols.map((c) => (
                    <label key={c.key} className="flex items-center gap-2 py-0.5 text-xs">
                      <input
                        type="checkbox"
                        checked={!hiddenCols.has(c.key)}
                        onChange={(e) => {
                          const next = new Set(hiddenCols);
                          if (e.target.checked) next.delete(c.key);
                          else next.add(c.key);
                          setHiddenCols(next);
                        }}
                      />
                      <span>{c.header}</span>
                    </label>
                  ))}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════
          Inspector drawer (right-side)
         ═══════════════════════════════════════════════════════════ */}
      {inspectorOpen && (
        <div className="fixed inset-0 z-40 flex justify-end bg-black/20" onClick={() => setInspectorOpen(false)}>
          <div className="h-full w-[420px] overflow-auto border-l border-border-primary bg-white p-4 shadow-lg" onClick={(e) => e.stopPropagation()}>
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-lg font-semibold">Inspector</h3>
              <button onClick={() => setInspectorOpen(false)} className="text-text-secondary hover:text-text-primary">
                ✕
              </button>
            </div>
            <div className="mb-3 flex gap-1 border-b border-border-primary">
              {(["metrics", "filters"] as const).map((tab) => (
                <button
                  key={tab}
                  onClick={() => setInspectorTab(tab)}
                  className={
                    "px-3 py-1.5 text-sm " +
                    (inspectorTab === tab ? "border-b-2 border-slate-900 font-medium" : "text-text-secondary")
                  }
                >
                  {tab === "metrics" ? "Metrics" : `Filters (${numericFilters.length})`}
                </button>
              ))}
            </div>
            {inspectorTab === "metrics" ? (
              <p className="text-xs text-text-secondary">
                Metrics tab mirrors the ▤ Columns picker. Use the ▤ button in the toolbar to toggle columns —
                this tab exists for parity with CTD&apos;s Inspector, both tabs share the same localStorage state.
              </p>
            ) : (
              <NumericFiltersPanel filters={numericFilters} onChange={setNumericFilters} />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Numeric filter panel — CTD dashboard.js:3760-3824 port
// ─────────────────────────────────────────────────────────────────────

type NumericOp = "gte" | "gt" | "lte" | "lt" | "eq" | "ne";
interface NumericFilter {
  field: string;
  op: NumericOp;
  value: number;
}

// Subset of CTD's AE_MF_FIELDS (dashboard.js:3658-3681) — only fields the
// backend actually returns.
const NUMERIC_FIELDS: { key: string; label: string }[] = [
  { key: "spend", label: "Spend" },
  { key: "roas", label: "ROAS" },
  { key: "shopify_roas", label: "Shopify ROAS" },
  { key: "impressions", label: "Impressions" },
  { key: "reach", label: "Reach" },
  { key: "frequency", label: "Frequency" },
  { key: "purchases", label: "Meta Purchases" },
  { key: "conv_value", label: "Meta Conv Value" },
  { key: "shopify_orders", label: "Shopify Orders" },
  { key: "shopify_revenue", label: "Shopify Sales" },
  { key: "ctr_pct", label: "CTR %" },
  { key: "atc_lc_pct", label: "ATC/LC %" },
  { key: "ci_atc_pct", label: "CI/ATC %" },
  { key: "checkout_compl_pct", label: "Checkout %" },
  { key: "cost_per_1000", label: "Cost/1k" },
  { key: "cpc_link", label: "CPC Link" },
  { key: "cost_per_ncp", label: "Cost/NCP" },
  { key: "cost_per_ftewv", label: "Cost/FTEWV" },
  { key: "ftewv_count", label: "FTEWV" },
  { key: "ncp_count", label: "NCP" },
  { key: "atc_count", label: "ATC" },
  { key: "ci_count", label: "CI" },
  { key: "link_clicks_raw", label: "Link Clicks" },
  { key: "contrib_margin_pct", label: "Contrib Margin %" },
];

const NUMERIC_OPS: { key: NumericOp; label: string }[] = [
  { key: "gte", label: "≥" },
  { key: "gt", label: ">" },
  { key: "lte", label: "≤" },
  { key: "lt", label: "<" },
  { key: "eq", label: "=" },
  { key: "ne", label: "≠" },
];

function applyOperator(v: number, op: NumericOp, target: number): boolean {
  switch (op) {
    case "gte": return v >= target;
    case "gt": return v > target;
    case "lte": return v <= target;
    case "lt": return v < target;
    case "eq": return v === target;
    case "ne": return v !== target;
  }
}

function NumericFiltersPanel({ filters, onChange }: { filters: NumericFilter[]; onChange: (f: NumericFilter[]) => void }) {
  function update(idx: number, patch: Partial<NumericFilter>) {
    onChange(filters.map((f, i) => (i === idx ? { ...f, ...patch } : f)));
  }
  return (
    <div className="flex flex-col gap-2">
      {filters.map((nf, idx) => (
        <div key={idx} className="flex items-center gap-1 rounded-md border border-border-primary p-1.5">
          <select value={nf.field} onChange={(e) => update(idx, { field: e.target.value })} className="rounded border px-1 py-0.5 text-xs">
            {NUMERIC_FIELDS.map((f) => (
              <option key={f.key} value={f.key}>{f.label}</option>
            ))}
          </select>
          <select value={nf.op} onChange={(e) => update(idx, { op: e.target.value as NumericOp })} className="rounded border px-1 py-0.5 text-xs">
            {NUMERIC_OPS.map((o) => (
              <option key={o.key} value={o.key}>{o.label}</option>
            ))}
          </select>
          <input
            type="number"
            value={nf.value}
            onChange={(e) => update(idx, { value: parseFloat(e.target.value) || 0 })}
            className="w-24 rounded border px-1 py-0.5 text-xs"
          />
          <button onClick={() => onChange(filters.filter((_, i) => i !== idx))} className="rounded px-1 text-rose-600 hover:bg-rose-50">
            ✕
          </button>
        </div>
      ))}
      <button
        onClick={() => onChange([...filters, { field: "spend", op: "gte", value: 1000 }])}
        className="rounded-md border border-dashed border-border-primary bg-white px-2 py-1 text-xs hover:bg-bg-muted"
      >
        + Add filter rule
      </button>
      {filters.length > 0 && (
        <button
          onClick={() => onChange([])}
          className="rounded-md border border-border-primary bg-white px-2 py-1 text-xs hover:bg-bg-muted"
        >
          Clear all rules
        </button>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Misc helpers
// ─────────────────────────────────────────────────────────────────────

function NumInput({ label, value, onChange, step = 1 }: { label: string; value: number; onChange: (v: number) => void; step?: number }) {
  return (
    <label className="flex items-center gap-1 text-xs">
      <span className="text-text-secondary">{label}</span>
      <input
        type="number"
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
        className="w-20 rounded border border-border-primary px-1 py-0.5 text-xs"
      />
    </label>
  );
}

function compareForSort(a: unknown, b: unknown): number {
  const aNull = a === null || a === undefined || a === "";
  const bNull = b === null || b === undefined || b === "";
  if (aNull && bNull) return 0;
  if (aNull) return 1; // nulls sink
  if (bNull) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  if (typeof a === "boolean" && typeof b === "boolean") return (a ? 1 : 0) - (b ? 1 : 0);
  const as = String(a);
  const bs = String(b);
  const an = parseFloat(as);
  const bn = parseFloat(bs);
  if (!Number.isNaN(an) && !Number.isNaN(bn)) return an - bn;
  return as.localeCompare(bs);
}
