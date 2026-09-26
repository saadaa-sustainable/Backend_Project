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
 *   7. 68-column table — including efficiency ratios from the API.
 *      Columns that still need source data, such as reach snapshots,
 *      render "—" with a tooltip explaining the missing calculation.
 *   8. Footer: pagination + row-count cascade + diagnostics.
 *
 * Everything data-derivable in-Silver already comes through
 * /admin/analytics/ads-analyse (widened backend). Client-side F1..F4
 * recategorisation runs against the raw metrics, so if a user sets F3
 * threshold to 400 (from CTD's default 525) they see the impact
 * immediately without re-hitting the backend.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { AdsAnalyseRow, AdsAnalyseTotals, ApiError, fetchAdsAnalyse,
  fetchScalableCreatives,
  ScalableCreativeRow,
  fetchCpisDataFreshness,
} from "@/lib/api";
import { useDebouncedValue } from "@/lib/useDebouncedValue";
import { InfoBasis, InfoDot } from "./InfoDot";
import { KwikTile } from "./KwikTile";
import { AdsLaunchChart } from "./AdsLaunchChart";
import { DateRangePicker, resolvePreset } from "@/components/DateRangePicker";
import { MultiFilter, MultiFilterState } from "./MultiFilter";
import { TableSkeleton } from "./TableSkeleton";
import { ExportButton } from "@/components/ExportButton";
import { theme } from "@/lib/theme";
import { RollupRow, fetchAdsAnalyseRollup } from "@/lib/api";

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
/** Plain-language definition of each verdict, for the (i) on its tile.
 *
 *  Written without the F1-F4 shorthand and without the threshold
 *  numbers: the thresholds are editable in the panel above the table,
 *  so any number repeated here would be wrong the moment someone
 *  changes one. "Enough people", "the limit" and so on track whatever
 *  is set. */
const CATEGORY_RULE: Record<CategoryKey, string> = {
  "Incremental Winner":
    "Reached enough people, sold well, and brought in new visitors cheaply. The best result an ad can have.",
  Winner:
    "Reached enough people and sold well, but each new visitor cost more than the limit.",
  "P0 analysis":
    "Reached enough people and brought visitors in cheaply, but they are not buying yet.",
  "P1 analysis":
    "Reached enough people to be judged, and nothing else worked.",
  "P2 analysis":
    "Selling well, but too few people have seen it to trust the result yet.",
  "Result Awaited":
    "Still new. It is inside its trial period and has not been judged.",
  Discarded:
    "Had its run and nothing worked.",
};

/** Where each tile's two numbers come from.
 *
 *  The count and the spend do NOT cover the same set of ads, and the
 *  card cannot show that, so it is said here. Getting this wrong once
 *  made a tile read "3" against a real 1,768. */
function categoryBasis(cat: CategoryKey, thresholdsEdited: boolean): InfoBasis {
  return {
    count: thresholdsEdited
      ? "Only the ads loaded so far, because you changed a threshold. Scroll for more to raise it."
      : "Every ad that matches the filters above — not only the ones visible in the table.",
    spend: "Only the ads loaded so far, not the whole list. It is a running total.",
    rule: CATEGORY_RULE[cat],
  };
}

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

/** The app's own tokens, mirrored for the few inline styles that cannot
 *  take a Tailwind class. An earlier pass gave this section a cream/gold
 *  scheme borrowed from the legacy dashboard, which left Ads Analyse the
 *  only blue-less tab in the panel. */
const AE = {
  cream: theme.bgMuted,
  border: theme.borderPrimary,
  muted: theme.textTertiary,
  ink: theme.textPrimary,
};

/** One labelled filter cell: uppercase caption above, control below,
 *  boxed. Matches the legacy layout, where every filter is its own card
 *  rather than a bare select floating in a strip. */
function FilterCard({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div
      className="rounded-lg border p-2.5"
      style={{ backgroundColor: AE.cream, borderColor: AE.border }}
    >
      <div
        className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider"
        style={{ color: AE.muted }}
      >
        {label}
      </div>
      {children}
    </div>
  );
}

function CardSelect({
  value,
  onChange,
  children,
}: {
  value: string;
  onChange: (v: string) => void;
  children: React.ReactNode;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full rounded-md border bg-white px-3 py-2 text-sm"
      style={{ borderColor: AE.border, color: AE.ink }}
    >
      {children}
    </select>
  );
}

function CardNumber({
  value,
  onChange,
  step = 1,
}: {
  value: number;
  onChange: (n: number) => void;
  step?: number;
}) {
  return (
    <input
      type="number"
      step={step}
      value={value}
      onChange={(e) => {
        const n = Number(e.target.value);
        // Reject NaN rather than writing it into a threshold -- every
        // comparison against NaN is false, which would silently empty
        // the table instead of showing an invalid-input state.
        if (!Number.isNaN(n)) onChange(n);
      }}
      className="w-full rounded-md border bg-white px-3 py-2 text-sm tabular-nums"
      style={{ borderColor: AE.border, color: AE.ink }}
    />
  );
}

function evaluateFlags(row: AdsAnalyseRow, t: FThresholds) {
  const p1 = (row.impressions ?? 0) >= t.f1Imp;
  const p2 = (row.roas ?? 0) >= t.f2Roas;
  const p3 = row.cost_per_ncp !== null && row.cost_per_ncp <= t.f3CostPerNcp;
  const p4 = row.cost_per_ftewv !== null && row.cost_per_ftewv <= t.f4CostPerFtewv;
  return { p1, p2, p3, p4 };
}

/** The ad's verdict.
 *
 *  At DEFAULT thresholds the server's stored `category` is authoritative
 *  and is what the tile counts (`category_counts`) are computed from, so
 *  we use it verbatim. Re-deriving it here would let the two disagree --
 *  and because the server has already filtered the rows by category, a
 *  client-side disagreement can only ever DROP rows the tiles counted,
 *  never add any. That is what made the P2 analysis and Discarded tiles
 *  look empty: the tile showed the server's count while the table
 *  re-filtered on a locally recomputed verdict.
 *
 *  Once the user edits a threshold the server's verdict no longer
 *  describes these rows, so we fall through to the local calculation --
 *  which is the entire point of the threshold panel. `filters` stops
 *  sending `category` to the server in that mode, so only one filter is
 *  ever applied.
 */
function categorise(row: AdsAnalyseRow, t: FThresholds, useServer = false): CategoryKey {
  if (useServer && row.category) return row.category as CategoryKey;
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
  group: "Identity" | "Timeline" | "Category" | "Delivery" | "Reach" | "Efficiency" | "Meta metrics" | "Shopify" | "Customers" | "Links";
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
  // Full figures, Indian grouping. These used to abbreviate to Cr / L / K,
  // which reads fine in a headline and badly everywhere else: 1.27Cr hides
  // the difference between 1,27,11,045 and 1,27,49,980, and those are the
  // comparisons this table exists to make. Charts pass their own axis
  // formatter, so nothing here widens an axis label.
  return Math.round(n).toLocaleString("en-IN");
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

/**
 * One de-duplicated-reach figure, with the snapshot date it describes.
 *
 * `asOf` is not decoration. The snapshots are fetched per anchor date,
 * and a custom range can land between two of them — the backend then
 * answers with the newest snapshot at or before the anchor rather than
 * refusing. A number that quietly describes 2026-08-31 while the header
 * says 2026-09-05 is the kind of thing nobody catches, so when the
 * snapshot trails the window the cell says so on hover and marks itself.
 */
function ReachCell({
  value,
  asOf,
  asOfFrom,
  what,
  emptyReason = "No reach snapshot covers this window yet — run scripts/fetch_reach_cumulative.py.",
}: {
  value: number | null;
  asOf: string | null;
  /** Opening end of the span, for a figure that is a difference rather
   *  than a level. Without it an Incr. Reach of 0 looks like a bug
   *  instead of "this ad added nobody between these two dates". */
  asOfFrom?: string | null;
  what: string;
  emptyReason?: string;
}) {
  if (value == null) {
    return (
      <span className="num text-text-tertiary" title={emptyReason}>
        —
      </span>
    );
  }
  return (
    <span className="num" title={`${what}.\nSnapshot: ${asOfFrom ? `${asOfFrom} \u2192 ${asOf ?? "unknown"}` : asOf ?? "unknown"}`}>
      {fmt(value, { maximumFractionDigits: 0 })}
    </span>
  );
}

/** Framework verdict. Colour carries the urgency, the tooltip carries
 *  the arithmetic — a verdict nobody can check is a verdict nobody
 *  should act on. */
/** The framework's verdicts, in the order it presents them: act, then
 *  watch, then the ones needing no action. Thresholds live server-side;
 *  these are labels only. */
/** What every verdict tile counts and sums. Identical across the six,
 *  so it is stated once -- the differences live in each tile's `rule`.
 *
 *  Both lines exist because the count and the rupee sub-line are NOT on
 *  the same footing: the count is a server-side figure over the whole
 *  filter set, while the ROAS that produced the verdict is measured on
 *  trailing windows that ignore the date range the spend obeys. A reader
 *  who assumes one window governs the card will misread it. */
const VERDICT_COUNT_BASIS =
  "Every ad set or campaign that matches the filters above — not only the " +
  "ones visible in the table.";
const VERDICT_SPEND_BASIS =
  "What they spent during the dates you picked.";
const VERDICT_NOTE =
  "R3 / R7 = money back per ₹1 spent, over the last 3 and 7 days. " +
  "C3 / C7 = ₹ paid per new visitor over the same. " +
  "L = that account’s limit (₹15 Raho Saadaa, ₹12 Fourth). " +
  "The 3- and 7-day figures use the most recent days Meta has sent, so they " +
  "do not move with the dates above.";

function verdictBasis(rule: string): InfoBasis {
  return {
    count: VERDICT_COUNT_BASIS,
    spend: VERDICT_SPEND_BASIS,
    rule,
    note: VERDICT_NOTE,
  };
}

/** Every verdict the engine can return, written as the condition it
 *  actually tests.
 *
 *  Symbols beat prose here: "both windows above 2.5" and "R3 > 2.5 AND
 *  R7 > 2.5" say the same thing, but only one of them is impossible to
 *  read two ways.
 *
 *  OK and UNRATED are in this list even though neither has a tile --
 *  they appear in the Decision column, so their definition has to be
 *  reachable from somewhere. This is that somewhere.
 *
 *  OK's condition is the simplification of "no other rule matched",
 *  verified exact against the engine on 2026-09-24: 66 ad sets either
 *  way. It follows because failing the kill branch and the recovery
 *  branch together forces R7 >= 1.5. */
const DECISION_RULES: { key: string; label: string; color: string; maths: string }[] = [
  { key: "SCALE", label: "Scale", color: "#2F6B3A",
    maths: "R3 > 2.5  AND  R7 > 2.5" },
  { key: "PAUSE", label: "Pause", color: "#C8102E",
    maths: "R3 < 1.5  AND  R7 < 1.5  AND  C3 > L  AND  C7 > L" },
  { key: "MONITOR", label: "Monitor", color: "#B45309",
    maths: "R7 < 1.5 ≤ R3   — or —   R3 < 1.5  AND  R7 < 1.5  AND  exactly one of C3, C7 > L" },
  { key: "REPORT", label: "Report", color: "#1D4E89",
    maths: "R3 < 1.5  AND  R7 < 1.5  AND  C3 ≤ L  AND  C7 ≤ L" },
  { key: "OK", label: "No action", color: "#57534A",
    maths: "R7 ≥ 1.5  AND  NOT (R3 > 2.5 AND R7 > 2.5)   — nothing else matched" },
  { key: "UNRATED", label: "No verdict", color: "#716D64",
    maths: "R3 or R7 does not exist — it did not spend in that window" },
];

const DECISION_TILES: { key: string; label: string; color: string; basis: InfoBasis }[] = [
  { key: "SCALE", label: "Scale", color: "#2F6B3A",
    basis: verdictBasis("R3 > 2.5  AND  R7 > 2.5") },
  { key: "PAUSE", label: "Pause", color: "#C8102E",
    basis: verdictBasis("R3 < 1.5  AND  R7 < 1.5  AND  C3 > L  AND  C7 > L") },
  { key: "MONITOR", label: "Monitor", color: "#B45309",
    basis: verdictBasis(
      "R7 < 1.5 ≤ R3,  or  R3 < 1.5 AND R7 < 1.5 with exactly one of " +
      "C3, C7 above L. The two windows disagree, so the call waits.") },
  { key: "REPORT", label: "Report", color: "#1D4E89",
    basis: verdictBasis("R3 < 1.5  AND  R7 < 1.5  AND  C3 ≤ L  AND  C7 ≤ L") },
  // OK and UNRATED have no tile -- every tile names something to DO,
  // and those two name its absence. Their definitions live in
  // DECISION_RULES, shown under the tiles.
];

/** The full rule table, always reachable under the verdict tiles.
 *
 *  Closed by default: it is a reference, not part of the flow. */
function DecisionRules() {
  return (
    <details className="mb-3 rounded-lg border border-border-primary bg-white px-3 py-2">
      <summary className="cursor-pointer select-none text-[11px] font-semibold uppercase tracking-wide text-text-tertiary">
        How each verdict is decided
      </summary>
      <div className="mt-2 space-y-1.5">
        {DECISION_RULES.map((r) => (
          <div key={r.key} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <span className="w-24 shrink-0 text-[11px] font-bold uppercase" style={{ color: r.color }}>
              {r.label}
            </span>
            <code className="num text-[11px] text-text-primary">{r.maths}</code>
          </div>
        ))}
        <p className="border-t border-border-primary pt-1.5 text-[11px] leading-snug text-text-tertiary">
          <strong className="text-text-secondary">R3 / R7</strong> — money back per ₹1 spent, over the
          last 3 and 7 days. <strong className="text-text-secondary">C3 / C7</strong> — ₹ paid per new
          visitor over the same. <strong className="text-text-secondary">L</strong> — that account’s
          limit (₹15 Raho Saadaa, ₹12 Fourth). Spending a whole window with no new visitors counts
          as C &gt; L. The 3- and 7-day figures use the most recent days Meta has sent, so they do
          not move with the dates picked above.
        </p>
      </div>
    </details>
  );
}

/** Section 3 of the audit framework, made clickable.
 *
 *  "We kill weak ad sets, but we do not kill good creatives." A PAUSE
 *  verdict is only actionable once you know what is worth lifting out
 *  first, so the count on the row opens the list of ads that cleared
 *  all four gates, with the numbers that got them there. */
function ScalableCreativesDrawer({
  level, entityId, entityName, fromDate, toDate, onClose,
}: {
  level: "adset" | "campaign";
  entityId: string;
  entityName: string | null;
  fromDate: string;
  toDate: string;
  onClose: () => void;
}) {
  const [ads, setAds] = useState<ScalableCreativeRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    fetchScalableCreatives({ level, entity_id: entityId, from_date: fromDate, to_date: toDate })
      .then((r) => { if (live) setAds(r.ads); })
      .catch((e) => { if (live) setError(e instanceof Error ? e.message : "Could not load"); });
    return () => { live = false; };
  }, [level, entityId, fromDate, toDate]);

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/20" onClick={onClose}>
      <div
        className="h-full w-[38rem] max-w-full overflow-y-auto bg-white p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-1 flex items-start justify-between gap-3">
          <h3 className="text-sm font-semibold text-text-primary">Creatives worth scaling</h3>
          <button onClick={onClose} className="text-xs text-text-tertiary hover:text-text-primary">
            Close
          </button>
        </div>
        <p className="mb-3 text-[11px] leading-snug text-text-tertiary">
          Inside <strong className="text-text-secondary">{entityName ?? entityId}</strong>, over the
          dates selected. An ad appears only if it clears all four:
          {" "}LC&nbsp;ROAS&nbsp;&gt;&nbsp;2, new-customer&nbsp;ROAS&nbsp;&gt;&nbsp;2.5,
          {" "}cost/NCP&nbsp;&lt;&nbsp;₹525, cost/FTEWV&nbsp;&lt;&nbsp;the account limit.
        </p>
        {error && <div className="text-xs text-error-text">{error}</div>}
        {!ads && !error && <div className="text-xs text-text-tertiary">Loading…</div>}
        {ads?.length === 0 && (
          <div className="rounded-md border border-border-primary bg-bg-muted p-3 text-xs text-text-secondary">
            No creative here clears all four gates. Nothing to rescue before pausing.
          </div>
        )}
        {ads?.map((a) => (
          <div key={a.ad_id} className="mb-2 rounded-lg border border-border-primary p-3">
            <div className="mb-1.5 text-[12px] font-medium text-text-primary">{a.ad_name ?? a.ad_id}</div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
              <Metric label="Spend" value={`₹${money(a.spend)}`} pass />
              <Metric label="LC ROAS" value={a.lc_roas.toFixed(2)} bar="> 2" pass />
              <Metric label="New-cust. ROAS" value={a.nc_roas.toFixed(2)} bar="> 2.5" pass />
              <Metric label="Cost / NCP" value={`₹${num2(a.cost_per_ncp)}`} bar="< ₹525" pass />
              <Metric label="Cost / FTEWV" value={`₹${num2(a.cost_per_ftewv)}`}
                      bar={`< ₹${a.ftewv_benchmark.toFixed(0)}`} pass />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Metric({ label, value, bar, pass }: {
  label: string; value: string; bar?: string; pass?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-text-tertiary">{label}</span>
      <span className="flex items-baseline gap-1">
        <span className={"num font-semibold " + (pass ? "text-success-text" : "text-text-primary")}>
          {value}
        </span>
        {bar && <span className="text-[10px] text-text-tertiary">{bar}</span>}
      </span>
    </div>
  );
}

function DecisionBadge({ v, why }: { v: string | null; why: string | null }) {
  if (!v) return <span className="text-text-tertiary" title={why ?? undefined}>—</span>;
  const cls: Record<string, string> = {
    SCALE: "bg-success-bg text-success-text",
    PAUSE: "bg-error-bg text-error-text",
    MONITOR: "bg-warning-bg text-warning-text",
    REPORT: "bg-info-bg text-info-text",
    OK: "bg-bg-muted text-text-secondary",
  };
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${cls[v] ?? ""}`}
          title={why ?? undefined}>
      {v}
    </span>
  );
}

/** Flags an ad set or campaign Meta created in the last 7 days.
 *
 *  It sits beside the status badge on purpose. 26 ad sets and 5
 *  campaigns built in the last week are already non-ACTIVE, and a
 *  paused entity three days old has not been judged -- it is pipeline,
 *  not a failure. Without this the two are indistinguishable in the
 *  table, and the older one is the only reading anyone makes. */
function NewEntityBadge() {
  return (
    <span
      className="ml-1 rounded bg-info-bg px-1 py-0.5 text-[9px] font-bold uppercase text-info-text"
      title={"Created in the last 7 days. Too new to judge — if it is paused, "
           + "that is not necessarily a verdict on its performance."}
    >
      new
    </span>
  );
}

/** Effective delivery status. Only ACTIVE is green: CAMPAIGN_PAUSED
 *  looks like an on switch in Meta's UI but delivers nothing, so it is
 *  coloured with the other stopped states rather than the running one. */
function StatusBadge({ v }: { v: string | null }) {
  if (!v) return <span className="text-text-tertiary">—</span>;
  const cls: Record<string, string> = {
    ACTIVE: "bg-success-bg text-success-text",
    PAUSED: "bg-bg-muted text-text-secondary",
    CAMPAIGN_PAUSED: "bg-warning-bg text-warning-text",
    WITH_ISSUES: "bg-error-bg text-error-text",
    ARCHIVED: "bg-bg-muted text-text-secondary",
  };
  const label = v === "CAMPAIGN_PAUSED" ? "CAMP. PAUSED" : v;
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${cls[v] ?? "bg-bg-muted text-text-secondary"}`}
          title={v === "CAMPAIGN_PAUSED"
            ? "Switched on, but its campaign is paused — it is not delivering."
            : undefined}>
      {label}
    </span>
  );
}

function BudgetBadge({ v }: { v: string | null }) {
  if (!v || v === "NONE") return <span className="text-text-tertiary">—</span>;
  // CBO and ABO are a structural fact about the account, not a verdict,
  // so both get a neutral tint rather than good/bad colouring.
  const cls = v === "CBO"
    ? "bg-accent-purple/15 text-accent-purple"
    : "bg-info-bg text-info-text";
  return <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${cls}`}>{v}</span>;
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

// The day-14 verdict. Same badge styling as the live Category column so
// the two read as the same vocabulary, with a subtle ring when they
// DISAGREE -- an ad that won its first fortnight and has since decayed
// is exactly what this column exists to surface, and it is invisible if
// both cells just render the same-looking pill.
//
// `status` explains a blank rather than leaving it ambiguous: Meta
// insights in bronze start 2026-01-01, so an ad created before that has
// no first fortnight to replay and its verdict is genuinely unknown --
// which is not the same as "Discarded".
const HISTORY_STATUS_REASON: Record<string, string> = {
  not_yet_14_days: "Not 14 days old yet — no verdict until its first fortnight is complete.",
  partial_history: "Created before 2026-01-01, where Meta insights in bronze begin. The first fortnight is only partly covered, so this verdict is approximate.",
  no_history:      "No daily Meta insight rows for this ad. Meta insights in bronze start 2026-01-01; ads created earlier cannot be replayed.",
};

function Day14Badge({ cat, status, now }: { cat: string | null; status: string | null; now: string | null }) {
  if (!cat) {
    return <Placeholder reason={HISTORY_STATUS_REASON[status ?? ""] ?? "No day-14 verdict available."} />;
  }
  const changed = now != null && now !== cat;
  const approx = status === "partial_history";
  return (
    <span
      className={`cat-badge ${CATEGORY_CLASS[cat as CategoryKey] ?? ""}${changed ? " ring-1 ring-accent-yellow" : ""}`}
      title={
        (changed ? `Was "${cat}" on day 14, now "${now}".` : `Still "${cat}".`) +
        (approx ? " Approximate — " + HISTORY_STATUS_REASON.partial_history : "")
      }
    >
      {cat}{approx ? " ~" : ""}
    </span>
  );
}

function StatusPill({ status }: { status: string | null }) {
  if (!status) return <span>—</span>;
  const active = status.toUpperCase() === "ACTIVE";
  return <span className={`ae-status ${active ? "active" : ""}`}>{status}</span>;
}

// Asset ID cell — the asset whose identifier appears in this ad's name.
// Source is public.ad_asset_map (scripts/refresh_ad_asset_map.py), which
// matches STRICTLY on one identifier per media and nothing else:
//   video       content_asset_register.asset_id          CPL012-0963
//   graphic     content_graphic_register.requisition_id  GAD-Sep-1493
//   influencer  content_influencer_posts.post_id         SIF-15233-P1
// No nomenclature, no username, no register ad_id column, and no regex
// scrape of ad_name that a register can't vouch for. So there is only
// one match source and it needs no badge — a value here means a real
// registered asset was named by the ad. The only thing worth flagging is
// an ad naming more than one.
const ASSET_MEDIA_ICON: Record<NonNullable<AdsAnalyseRow["asset_media"]>, string> = {
  video: "🎬",
  graphic: "🖼",
  influencer: "👤",
};

function AssetIdCell({ row }: { row: AdsAnalyseRow }) {
  if (!row.asset_id) return <span className="text-text-tertiary">—</span>;
  const media = row.asset_media;
  return (
    <span className="inline-flex items-center gap-1">
      {media && <span title={media}>{ASSET_MEDIA_ICON[media]}</span>}
      <span className="font-mono text-[11px]">{row.asset_id}</span>
      {row.asset_name_conflict && (
        <span
          className="rounded border border-border-primary bg-warning-bg px-1 text-[10px] font-medium text-warning-text"
          title="This ad name resolves to more than one registered asset. A winner was picked deterministically — worth a human check."
        >
          ⚠ multi
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
/** Geometry for cropping a social embed down to a thumbnail.
 *
 *  The IG and FB embeds are whole post CARDS -- avatar row, then media,
 *  then caption. Scaled naively into a 40px box that reads as a grey
 *  smear with a sliver of username. So the iframe is rendered at its
 *  natural width (the embeds reflow badly below these) and then scaled
 *  and pushed up so the MEDIA band alone fills the square.
 *
 *  `headerPx` is the card chrome above the media at that width, measured
 *  against the live embeds. Tune these two numbers if Meta restyles the
 *  cards -- nothing else here depends on them. */
/** Preview cell edge, px. The embeds are scaled against this, so the
 *  cell size and the crop maths cannot drift apart. */
const PREVIEW_PX = 40;

const EMBED_CROP = {
  ig: { width: 320, headerPx: 54 },
  fb: { width: 500, headerPx: 74 },
} as const;

/** A social embed cropped to its media and rendered as a thumbnail.
 *
 *  Mounted only once the row is actually near the viewport. Without
 *  that, paging the table would fire 50-100 third-party iframes at once
 *  -- slow, and enough traffic for Meta to start refusing embeds. The
 *  observer disconnects after the first hit, so a row that scrolls away
 *  keeps what it already loaded.
 *
 *  `pointer-events-none` matters: the iframe would otherwise swallow the
 *  click that opens the full-size lightbox. */
function MiniEmbed({
  src,
  kind,
  size,
  title,
}: {
  src: string;
  kind: "ig" | "fb";
  size: number;
  title: string;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = box.current;
    if (!el || visible) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setVisible(true);
          io.disconnect();
        }
      },
      { rootMargin: "300px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [visible]);

  const geom = EMBED_CROP[kind];
  const scale = size / geom.width;

  return (
    <div ref={box} className="relative h-full w-full overflow-hidden bg-bg-muted">
      {visible && (
        <iframe
          src={src}
          title={title}
          scrolling="no"
          loading="lazy"
          tabIndex={-1}
          aria-hidden
          className="pointer-events-none absolute left-0 top-0 origin-top-left border-0"
          style={{
            width: geom.width,
            // Tall enough that the media band is inside the frame before
            // the crop; the wrapper clips the rest.
            height: geom.width + geom.headerPx,
            transform: `scale(${scale}) translateY(-${geom.headerPx}px)`,
          }}
        />
      )}
    </div>
  );
}

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
        style={{ width: PREVIEW_PX, height: PREVIEW_PX }}
        className="flex items-center justify-center rounded bg-bg-muted text-[9px] text-text-tertiary"
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
        style={{ width: PREVIEW_PX, height: PREVIEW_PX }}
        className="group relative overflow-hidden rounded ring-1 border-border-primary hover:border-border-primary"
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
          // The real post, cropped to its media. This used to be a flat
          // "IG" gradient tile -- it told you a preview EXISTED but
          // nothing about the creative, which is the one thing a preview
          // column is for. 68% of rows land here rather than on a cached
          // thumbnail, so it was most of the column.
          <MiniEmbed
            src={igEmbedUrl}
            kind="ig"
            size={PREVIEW_PX}
            title={row.ad_name ?? "Instagram post preview"}
          />
        ) : fbIframeUrl ? (
          <MiniEmbed
            src={fbIframeUrl}
            kind="fb"
            size={PREVIEW_PX}
            title={row.ad_name ?? "Facebook post preview"}
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center bg-bg-muted text-[9px] text-text-tertiary">
            —
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

/** Rollup (ad set / campaign) columns. Separate from COLUMNS because
 *  the grain differs: there is no ad id, no asset, no F1-F4 verdict, and
 *  reach here is Meta's own per-entity figure rather than anything
 *  summable from ads.
 *
 *  Shopify columns are last-click attribution rolled up to this level --
 *  the same source the ad level uses. */
type RollupColDef = {
  key: string;
  header: string;
  group: string;
  defaultVisible?: boolean;
  align?: "right";
  title?: string;
  render: (r: RollupRow) => React.ReactNode;
};

const rInt = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : Math.round(n).toLocaleString("en-IN");
const rMoney = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : "₹" + Math.round(n).toLocaleString("en-IN");
const rNum = (n: number | null | undefined, dp = 2) =>
  n === null || n === undefined ? "—" : n.toFixed(dp);

const ROLLUP_COLUMNS: RollupColDef[] = [
  { key: "entity_name", header: "Name", group: "Identity", defaultVisible: true,
    render: (r) => (
      <span className="block max-w-[26rem] truncate" title={r.entity_name ?? ""}>
        {r.entity_name ?? r.entity_id}
      </span>
    ) },
  { key: "entity_id", header: "ID", group: "Identity",
    render: (r) => <span className="num whitespace-nowrap">{r.entity_id}</span> },
  { key: "account_name", header: "Account", group: "Identity", defaultVisible: true,
    render: (r) => <>{r.account_name ?? "—"}</> },
  // First after the name: this is the column the section exists to
  // answer. Hover gives the numbers behind it.
  { key: "decision", header: "Decision", group: "Identity", defaultVisible: true,
    render: (r) => <DecisionBadge v={r.decision} why={r.decision_reason} /> },
  { key: "budget_type", header: "Budget", group: "Identity", defaultVisible: true,
    render: (r) => <BudgetBadge v={r.budget_type} /> },
  { key: "scalable_creatives", header: "Scale-worthy", group: "Identity", defaultVisible: true, align: "right",
    title: "Ads inside this ad set or campaign that clear all four creative-scaling "
         + "gates from the audit framework: LC ROAS > 2, new-customer ROAS > 2.5, "
         + "cost per new customer < ₹525, cost per first-time visitor < the account "
         + "limit. On a Pause row these are the creatives to lift out before you "
         + "switch it off — the framework's rule is that killing a weak ad set must "
         + "not kill the good creatives in it. Click to see them.",
    render: (r) => {
      const n = r.scalable_creatives ?? 0;
      if (n === 0) return <span className="text-text-tertiary">—</span>;
      // Loud only where it changes a decision: a Pause row with a
      // creative still worth keeping is the case the rule exists for.
      const urgent = r.decision === "PAUSE";
      return (
        <button
          type="button"
          data-scalable={r.entity_id}
          className={"rounded px-1.5 py-0.5 text-[11px] font-bold " + (urgent
            ? "bg-warning-bg text-warning-text hover:bg-warning-bg"
            : "bg-bg-muted text-text-secondary hover:bg-border-primary")}
          title={urgent
            ? `${n} creative(s) here still qualify for scaling — lift them out before pausing.`
            : `${n} creative(s) here qualify for scaling.`}
        >
          {n}
        </button>
      );
    } },
  { key: "campaign_name", header: "Campaign", group: "Identity", defaultVisible: true,
    title: "The campaign this ad set sits under. Blank on campaign rows, which "
         + "are already the campaign.",
    render: (r) => (
      <span className="block max-w-[18rem] truncate text-[12px]" title={r.campaign_name ?? ""}>
        {r.campaign_name ?? "—"}
      </span>
    ) },
  { key: "created_date", header: "Created", group: "Identity", defaultVisible: true, align: "right",
    title: "When Meta created this entity — not the first day it delivered. "
         + "Entities under 7 days old are badged NEW beside their status.",
    render: (r) => (
      <span className="text-[12px] text-text-tertiary">{r.created_date ?? "—"}</span>
    ) },
  { key: "effective_status", header: "Status", group: "Identity", defaultVisible: true,
    title: "Meta's EFFECTIVE status — whether it is actually delivering, not "
         + "whether it is switched on. An ad set under a paused campaign reads "
         + "ACTIVE on itself and CAMPAIGN_PAUSED here.",
    render: (r) => (
      <span className="whitespace-nowrap">
        <StatusBadge v={r.effective_status} />
        {r.is_new_entity && <NewEntityBadge />}
      </span>
    ) },
  // The four inputs the verdict is computed from, on by default so the
  // call can be audited without opening the column picker.
  { key: "d3_lc_roas_v", header: "3D ROAS", group: "Identity", defaultVisible: true, align: "right",
    render: (r) => <span className="num">{num2(r.d3_lc_roas)}</span> },
  { key: "d7_lc_roas_v", header: "7D ROAS", group: "Identity", defaultVisible: true, align: "right",
    render: (r) => <span className="num">{num2(r.d7_lc_roas)}</span> },
  // The two values the Pause/Monitor/Report split is decided on, so
  // they say whose number it is: this entity's own spend / its own
  // FTEWV, per window. The benchmark they are compared against is the
  // per-account one, and that is the ONLY part of the rule that is not
  // entity-level. Both are shown because a kill now needs BOTH windows
  // to agree -- seeing only one of them cannot explain the verdict.
  { key: "ncp_count", header: "NCP", group: "Identity", defaultVisible: true, align: "right",
    title: "New customer purchases inside the selected dates. Meta reports NCP at "
         + "ad grain only, so this is summed from the ad-level daily table through "
         + "each ad's parent — every ad has exactly one, so nothing double-counts.",
    render: (r) => <span className="num">{num2(r.ncp_count)}</span> },
  { key: "cost_per_ncp", header: "Cost/NCP", group: "Identity", defaultVisible: true, align: "right",
    title: "Spend in the selected dates ÷ new customer purchases in the same "
         + "dates. Both sides share the window, so the ratio divides like for like.",
    render: (r) => <span className="num">₹{num2(r.cost_per_ncp)}</span> },
  { key: "d3_cost_per_ftewv_v", header: "3D ₹/FTEWV", group: "Identity", defaultVisible: true, align: "right",
    title: "This entity's own 3-day spend ÷ its own FTEWV — not an account average. "
         + "A pause needs THIS and the 7D figure both above the account's benchmark: "
         + "₹15 in Raho Saadaa, ₹12 in Fourth Ad Account - SD.",
    render: (r) => <span className="num">₹{num2(r.d3_cost_per_ftewv)}</span> },
  { key: "d7_cost_per_ftewv_v", header: "7D ₹/FTEWV", group: "Identity", defaultVisible: true, align: "right",
    title: "This entity's own 7-day spend ÷ its own FTEWV — not an account average. "
         + "A pause needs THIS and the 3D figure both above the account's benchmark: "
         + "₹15 in Raho Saadaa, ₹12 in Fourth Ad Account - SD. If the two windows "
         + "disagree the verdict is Monitor, not Pause.",
    render: (r) => <span className="num">₹{num2(r.d7_cost_per_ftewv)}</span> },
  { key: "ads", header: "Ads", group: "Identity", defaultVisible: true, align: "right",
    render: (r) => <>{r.ads.toLocaleString("en-IN")}</> },

  { key: "spend", header: "Spend", group: "Meta", defaultVisible: true, align: "right",
    render: (r) => <>{rMoney(r.spend)}</> },
  { key: "impressions", header: "Impressions", group: "Meta", defaultVisible: true, align: "right",
    render: (r) => <>{rInt(r.impressions)}</> },
  { key: "reach", header: "Reach", group: "Meta", defaultVisible: true, align: "right",
    title: "Meta-deduplicated — not a sum of ad reach",
    render: (r) => <>{rInt(r.reach)}</> },
  { key: "frequency", header: "Freq.", group: "Meta", defaultVisible: true, align: "right",
    render: (r) => <>{rNum(r.frequency)}</> },
  { key: "clicks", header: "Clicks", group: "Meta", align: "right",
    render: (r) => <>{rInt(r.clicks)}</> },
  { key: "ctr", header: "CTR", group: "Meta", align: "right",
    render: (r) => <>{r.ctr === null ? "—" : r.ctr.toFixed(2) + "%"}</> },
  { key: "cpm", header: "CPM", group: "Meta", align: "right",
    render: (r) => <>{rMoney(r.cpm)}</> },
  { key: "cpr_1000", header: "₹/1k reach", group: "Meta", defaultVisible: true, align: "right",
    render: (r) => <>{rMoney(r.cpr_1000)}</> },
  { key: "purchases", header: "Purch.", group: "Meta", defaultVisible: true, align: "right",
    render: (r) => <>{rInt(r.purchases)}</> },
  { key: "conv_value", header: "Conv. value", group: "Meta", align: "right",
    render: (r) => <>{rMoney(r.conv_value)}</> },
  { key: "roas", header: "ROAS", group: "Meta", defaultVisible: true, align: "right",
    render: (r) => <>{rNum(r.roas)}</> },
  { key: "cost_per_purchase", header: "₹/purchase", group: "Meta", align: "right",
    render: (r) => <>{rMoney(r.cost_per_purchase)}</> },

  { key: "shopify_orders", header: "Shop. orders", group: "Shopify", defaultVisible: true, align: "right",
    title: "Shopify orders last-click-attributed to this entity, over the selected dates",
    render: (r) => <>{!r.shopify_orders ? "—" : r.shopify_orders.toLocaleString("en-IN")}</> },
  { key: "shopify_revenue", header: "Shop. revenue", group: "Shopify", defaultVisible: true, align: "right",
    render: (r) => <>{!r.shopify_revenue ? "—" : rMoney(r.shopify_revenue)}</> },
  { key: "new_customers", header: "New cust.", group: "Customers", defaultVisible: true, align: "right",
    title: "Customers whose FIRST EVER order came through this ad, over the selected dates. Judged against the whole order history, not just this window.",
    render: (r) => <>{!r.new_customers ? "—" : r.new_customers.toLocaleString("en-IN")}</> },
  { key: "repeat_customers", header: "Repeat cust.", group: "Customers", defaultVisible: true, align: "right",
    title: "Distinct people who had bought before and bought again through this ad. Counted DISTINCT, so this column does not add up across rows -- one person can buy from two ads in the same window.",
    render: (r) => <>{!r.repeat_customers ? "—" : r.repeat_customers.toLocaleString("en-IN")}</> },
  { key: "new_customer_sales", header: "New cust. sales", group: "Customers", defaultVisible: true, align: "right",
    title: "Order value from first-time customers",
    render: (r) => <>{!r.new_customer_sales ? "—" : rMoney(r.new_customer_sales)}</> },
  { key: "repeat_customer_sales", header: "Repeat cust. sales", group: "Customers", defaultVisible: true, align: "right",
    title: "Order value from returning customers",
    render: (r) => <>{!r.repeat_customer_sales ? "—" : rMoney(r.repeat_customer_sales)}</> },

  { key: "shopify_roas", header: "Shop. ROAS", group: "Shopify", defaultVisible: true, align: "right",
    title: "Shopify revenue ÷ Meta spend",
    render: (r) => <>{rNum(r.shopify_roas)}</> },
  { key: "cost_per_shopify_order", header: "₹/order", group: "Shopify", defaultVisible: true, align: "right",
    title: "Meta spend ÷ Shopify orders",
    render: (r) => <>{rMoney(r.cost_per_shopify_order)}</> },
  // Same measure and the same thresholds as the ad-level column, so a
  // number means the same thing at both grains. Red past -20% only
  // flags worse-than-usual: Meta over-reports by ~1.49x fleet-wide, so
  // a moderate negative is the expected reading, not a problem.
  { key: "meta_shop_diff_pct", header: "% Meta vs Shop", group: "Shopify", defaultVisible: true, align: "right",
    render: (r) => (
      <span className={
        r.meta_shop_diff_pct == null ? "" :
        r.meta_shop_diff_pct < -20 ? "text-error-text" :
        r.meta_shop_diff_pct > 20 ? "text-success-text" : ""
      }>
        {r.meta_shop_diff_pct == null ? "—" : `${pct(r.meta_shop_diff_pct)}%`}
      </span>
    ) },
  // Rolling windows anchored on the data's LAST DATE, not today --
  // Meta's daily insights arrive a day late, so "today" would put an
  // empty day inside every 3D window. All hidden by default: 32 extra
  // columns would otherwise bury the 12 that are on by default.
  { key: "d3_spend", header: "3D Spend", group: "Rolling 3D", align: "right",
    render: (r) => <span className="num">₹{money(r.d3_spend)}</span> },
  { key: "d3_lc_revenue", header: "3D LC Revenue", group: "Rolling 3D", align: "right",
    render: (r) => <span className="num">₹{money(r.d3_lc_revenue)}</span> },
  { key: "d3_lc_roas", header: "3D LC ROAS", group: "Rolling 3D", align: "right",
    render: (r) => <span className="num">{num2(r.d3_lc_roas)}</span> },
  { key: "d3_reach_proxy", header: "3D Reach Proxy", group: "Rolling 3D", align: "right",
    render: (r) => <span className="num" title="Summed daily reach — person-days, NOT de-duplicated people. Directional volume only; the Reach column is the de-duplicated figure.">{fmt(r.d3_reach_proxy, { maximumFractionDigits: 0 })}</span> },
  { key: "d3_reach_delta", header: "3D Reach Δ", group: "Rolling 3D", align: "right",
    render: (r) => <span className={"num " + ((r.d3_reach_delta ?? 0) < 0 ? "text-error-text" : (r.d3_reach_delta ?? 0) > 0 ? "text-success-text" : "")}>{fmt(r.d3_reach_delta, { maximumFractionDigits: 0, signDisplay: "exceptZero" })}</span> },
  { key: "d3_reach_delta_pct", header: "3D Reach Δ%", group: "Rolling 3D", align: "right",
    render: (r) => <span className={"num " + ((r.d3_reach_delta_pct ?? 0) < 0 ? "text-error-text" : (r.d3_reach_delta_pct ?? 0) > 0 ? "text-success-text" : "")}>{pct(r.d3_reach_delta_pct)}%</span> },
  { key: "d3_ftewv", header: "3D FTEWV", group: "Rolling 3D", align: "right",
    render: (r) => <span className="num">{fmt(r.d3_ftewv, { maximumFractionDigits: 0 })}</span> },
  { key: "d3_cost_per_ftewv", header: "3D Cost/FTEWV", group: "Rolling 3D", align: "right",
    render: (r) => <span className="num">₹{num2(r.d3_cost_per_ftewv)}</span> },
  { key: "d7_spend", header: "7D Spend", group: "Rolling 7D", align: "right",
    render: (r) => <span className="num">₹{money(r.d7_spend)}</span> },
  { key: "d7_lc_revenue", header: "7D LC Revenue", group: "Rolling 7D", align: "right",
    render: (r) => <span className="num">₹{money(r.d7_lc_revenue)}</span> },
  { key: "d7_lc_roas", header: "7D LC ROAS", group: "Rolling 7D", align: "right",
    render: (r) => <span className="num">{num2(r.d7_lc_roas)}</span> },
  { key: "d7_reach_proxy", header: "7D Reach Proxy", group: "Rolling 7D", align: "right",
    render: (r) => <span className="num" title="Summed daily reach — person-days, NOT de-duplicated people. Directional volume only; the Reach column is the de-duplicated figure.">{fmt(r.d7_reach_proxy, { maximumFractionDigits: 0 })}</span> },
  { key: "d7_reach_delta", header: "7D Reach Δ", group: "Rolling 7D", align: "right",
    render: (r) => <span className={"num " + ((r.d7_reach_delta ?? 0) < 0 ? "text-error-text" : (r.d7_reach_delta ?? 0) > 0 ? "text-success-text" : "")}>{fmt(r.d7_reach_delta, { maximumFractionDigits: 0, signDisplay: "exceptZero" })}</span> },
  { key: "d7_reach_delta_pct", header: "7D Reach Δ%", group: "Rolling 7D", align: "right",
    render: (r) => <span className={"num " + ((r.d7_reach_delta_pct ?? 0) < 0 ? "text-error-text" : (r.d7_reach_delta_pct ?? 0) > 0 ? "text-success-text" : "")}>{pct(r.d7_reach_delta_pct)}%</span> },
  { key: "d7_ftewv", header: "7D FTEWV", group: "Rolling 7D", align: "right",
    render: (r) => <span className="num">{fmt(r.d7_ftewv, { maximumFractionDigits: 0 })}</span> },
  { key: "d7_cost_per_ftewv", header: "7D Cost/FTEWV", group: "Rolling 7D", align: "right",
    render: (r) => <span className="num">₹{num2(r.d7_cost_per_ftewv)}</span> },
  { key: "d14_spend", header: "14D Spend", group: "Rolling 14D", align: "right",
    render: (r) => <span className="num">₹{money(r.d14_spend)}</span> },
  { key: "d14_lc_revenue", header: "14D LC Revenue", group: "Rolling 14D", align: "right",
    render: (r) => <span className="num">₹{money(r.d14_lc_revenue)}</span> },
  { key: "d14_lc_roas", header: "14D LC ROAS", group: "Rolling 14D", align: "right",
    render: (r) => <span className="num">{num2(r.d14_lc_roas)}</span> },
  { key: "d14_reach_proxy", header: "14D Reach Proxy", group: "Rolling 14D", align: "right",
    render: (r) => <span className="num" title="Summed daily reach — person-days, NOT de-duplicated people. Directional volume only; the Reach column is the de-duplicated figure.">{fmt(r.d14_reach_proxy, { maximumFractionDigits: 0 })}</span> },
  { key: "d14_reach_delta", header: "14D Reach Δ", group: "Rolling 14D", align: "right",
    render: (r) => <span className={"num " + ((r.d14_reach_delta ?? 0) < 0 ? "text-error-text" : (r.d14_reach_delta ?? 0) > 0 ? "text-success-text" : "")}>{fmt(r.d14_reach_delta, { maximumFractionDigits: 0, signDisplay: "exceptZero" })}</span> },
  { key: "d14_reach_delta_pct", header: "14D Reach Δ%", group: "Rolling 14D", align: "right",
    render: (r) => <span className={"num " + ((r.d14_reach_delta_pct ?? 0) < 0 ? "text-error-text" : (r.d14_reach_delta_pct ?? 0) > 0 ? "text-success-text" : "")}>{pct(r.d14_reach_delta_pct)}%</span> },
  { key: "d14_ftewv", header: "14D FTEWV", group: "Rolling 14D", align: "right",
    render: (r) => <span className="num">{fmt(r.d14_ftewv, { maximumFractionDigits: 0 })}</span> },
  { key: "d14_cost_per_ftewv", header: "14D Cost/FTEWV", group: "Rolling 14D", align: "right",
    render: (r) => <span className="num">₹{num2(r.d14_cost_per_ftewv)}</span> },
  { key: "d28_spend", header: "28D Spend", group: "Rolling 28D", align: "right",
    render: (r) => <span className="num">₹{money(r.d28_spend)}</span> },
  { key: "d28_lc_revenue", header: "28D LC Revenue", group: "Rolling 28D", align: "right",
    render: (r) => <span className="num">₹{money(r.d28_lc_revenue)}</span> },
  { key: "d28_lc_roas", header: "28D LC ROAS", group: "Rolling 28D", align: "right",
    render: (r) => <span className="num">{num2(r.d28_lc_roas)}</span> },
  { key: "d28_reach_proxy", header: "28D Reach Proxy", group: "Rolling 28D", align: "right",
    render: (r) => <span className="num" title="Summed daily reach — person-days, NOT de-duplicated people. Directional volume only; the Reach column is the de-duplicated figure.">{fmt(r.d28_reach_proxy, { maximumFractionDigits: 0 })}</span> },
  { key: "d28_reach_delta", header: "28D Reach Δ", group: "Rolling 28D", align: "right",
    render: (r) => <span className={"num " + ((r.d28_reach_delta ?? 0) < 0 ? "text-error-text" : (r.d28_reach_delta ?? 0) > 0 ? "text-success-text" : "")}>{fmt(r.d28_reach_delta, { maximumFractionDigits: 0, signDisplay: "exceptZero" })}</span> },
  { key: "d28_reach_delta_pct", header: "28D Reach Δ%", group: "Rolling 28D", align: "right",
    render: (r) => <span className={"num " + ((r.d28_reach_delta_pct ?? 0) < 0 ? "text-error-text" : (r.d28_reach_delta_pct ?? 0) > 0 ? "text-success-text" : "")}>{pct(r.d28_reach_delta_pct)}%</span> },
  { key: "d28_ftewv", header: "28D FTEWV", group: "Rolling 28D", align: "right",
    render: (r) => <span className="num">{fmt(r.d28_ftewv, { maximumFractionDigits: 0 })}</span> },
  { key: "d28_cost_per_ftewv", header: "28D Cost/FTEWV", group: "Rolling 28D", align: "right",
    render: (r) => <span className="num">₹{num2(r.d28_cost_per_ftewv)}</span> },
  { key: "window", header: "Window", group: "Timeline", defaultVisible: true, align: "right",
    title: "The period these Meta figures actually cover — rows refresh independently",
    render: (r) => (
      <span className="text-[11px] text-text-tertiary">
        {r.date_start ?? "—"} → {r.date_stop ?? "—"}
      </span>
    ) },
];

/** Numeric columns of the rollup, for the inspector's rule builder.
 *  Derived from ROLLUP_COLUMNS so a column added there shows up here
 *  automatically, minus the ones that are not numbers. */
const ROLLUP_NUMERIC_FIELDS = ROLLUP_COLUMNS
  .filter((c) => !["entity_name", "entity_id", "account_name", "window"].includes(c.key))
  .map((c) => ({ key: c.key, label: c.header }));

const ROLLUP_GROUPS = Array.from(new Set(ROLLUP_COLUMNS.map((c) => c.group)));
const ROLLUP_DEFAULT_HIDDEN = new Set(
  ROLLUP_COLUMNS.filter((c) => !c.defaultVisible).map((c) => c.key),
);

const COLUMNS: ColDef[] = [
  // Identity
  { key: "preview_thumb", header: "Preview", kind: "link", group: "Identity", defaultVisible: true,
    render: (r) => <ThumbnailCell row={r} /> },
  { key: "ad_name", header: "Ad Name", kind: "text", group: "Identity", defaultVisible: true,
    render: (r) => <span title={r.ad_name ?? ""}>{r.ad_name ?? "—"}</span> },
  { key: "ad_id", header: "Ad ID", kind: "text", group: "Identity", defaultVisible: true,
    // Full id. These were sliced to 12 chars with an ellipsis, which made
    // every Meta id look alike (120215851600… / 120215866514…) and left
    // the one thing you need an id column FOR -- copying it into Ads
    // Manager or a query -- impossible without opening the inspector.
    render: (r) => <span className="num whitespace-nowrap">{r.ad_id}</span> },
  { key: "asset_id", header: "Asset ID", kind: "text", group: "Identity", defaultVisible: true,
    render: (r) => <AssetIdCell row={r} /> },
  { key: "campaign_name", header: "Campaign", kind: "text", group: "Identity", defaultVisible: true,
    render: (r) => <span title={r.campaign_name ?? ""}>{r.campaign_name ?? "—"}</span> },
  { key: "adset_id", header: "Ad Set ID", kind: "text", group: "Identity",
    // Also fixes a null bug: the old form put the ellipsis outside the
    // ?? fallback, so a missing adset rendered as "—…".
    render: (r) => <span className="num whitespace-nowrap">{r.adset_id ?? "—"}</span> },
  { key: "attribution", header: "Attribution", kind: "link", group: "Identity",
    render: () => <Placeholder reason="Daily attribution drill-down needs new /admin/analytics/ad-daily endpoint" /> },
  { key: "account_name", header: "Account", kind: "text", group: "Identity", defaultVisible: true,
    render: (r) => <span>{r.account_name ?? "—"}</span> },
  // Timeline
  { key: "ad_created_date", header: "Created", kind: "date", group: "Timeline", defaultVisible: true,
    render: (r) => <span>{r.ad_created_date ?? "—"}</span> },
  { key: "first_seen_date", header: "First Seen", kind: "date", group: "Timeline",
    render: (r) => <span>{r.first_seen_date ?? "—"}</span> },
  // Lifetime milestones come from the API's recorded ad history, even
  // when delivery metrics are filtered to a shorter date range.
  { key: "impressions_50k_date", header: "50k Imp. Date", kind: "date", group: "Timeline", defaultVisible: true,
    render: (r) => r.impressions_50k_date
      ? <span title={r.days_to_50k != null ? `${r.days_to_50k} days after first delivery` : undefined}>
          {r.impressions_50k_date}
        </span>
      : <Placeholder reason="No recorded 50,000-impression crossing date. The ad may not have reached the threshold or its historical date is unavailable." /> },
  { key: "date_of_result", header: "Result Date", kind: "date", group: "Timeline",
    render: (r) => r.date_of_result
      ? <span title="The recorded 50,000-impression crossing date; otherwise 14 days after first delivery, falling back to creation date. This date can be in the future.">{r.date_of_result}</span>
      : <Placeholder reason="Result date is unavailable because the crossing date, first delivery date, and creation date are unknown." /> },
  { key: "days_to_result", header: "Days Result", kind: "int", group: "Timeline",
    render: (r) => <span className="num" title="Days from first delivery to Result Date; unavailable when first delivery is unknown.">{r.days_to_result ?? "—"}</span> },
  { key: "days_to_50k", header: "Days to 50k", kind: "int", group: "Timeline",
    render: (r) => <span className="num" title="Days from first delivery to the recorded 50,000-impression crossing.">{r.days_to_50k ?? "—"}</span> },
  // Category / Flags
  { key: "category", header: "Category (now)", kind: "cat", group: "Category", defaultVisible: true,
    render: (_r, cat) => <CatBadge cat={cat} /> },
  { key: "category_at_day_14", header: "Category (day 14)", kind: "cat", group: "Category", defaultVisible: true,
    render: (r, cat) => <Day14Badge cat={r.category_at_day_14} status={r.history_status} now={cat} /> },
  { key: "f1_pass", header: "F1", kind: "flag", group: "Category", defaultVisible: true,
    render: (r, _c, ) => <FBadge pass={r.f1_pass} name="F1" /> },
  { key: "f2_pass", header: "F2", kind: "flag", group: "Category", defaultVisible: true,
    render: (r) => <FBadge pass={r.f2_pass} name="F2" /> },
  { key: "f3_pass", header: "F3", kind: "flag", group: "Category", defaultVisible: true,
    render: (r) => <FBadge pass={r.f3_pass} name="F3" /> },
  { key: "f4_pass", header: "F4", kind: "flag", group: "Category", defaultVisible: true,
    render: (r) => <FBadge pass={r.f4_pass} name="F4" /> },
  { key: "budget_type", header: "Budget", kind: "cat", group: "Category", defaultVisible: true,
    render: (r) => <BudgetBadge v={r.budget_type} /> },
  { key: "ad_status", header: "Ad Status", kind: "status", group: "Category", defaultVisible: true,
    render: (r) => <StatusPill status={r.ad_effective_status ?? r.ad_status} /> },
  // Delivery
  { key: "impressions", header: "Impressions", kind: "int", group: "Delivery", defaultVisible: true,
    render: (r) => <span className="num">{fmt(r.impressions, { maximumFractionDigits: 0 })}</span> },
  // UPPER BOUND on a windowed view. This is summed from the daily rows,
  // and reach de-duplicates per day, so anyone who saw the ad on more
  // than one day is counted once per day. Measured against Meta over
  // 2026-09-01..15: the daily sum said 13,995,699 where the true
  // de-duplicated figure was 5,481,912. Latest Reach / Incr. Reach in
  // this same group are the de-duplicated ones.
  { key: "reach", header: "Reach", kind: "int", group: "Reach", defaultVisible: true,
    render: (r) => <span className="num" title="Summed from daily rows, so it counts a person once per day they saw the ad — an upper bound, not unique people. Use Latest Reach / Incr. Reach for de-duplicated figures.">{fmt(r.reach, { maximumFractionDigits: 0 })}</span> },
  // The four snapshot columns below read public.ad_reach_cumulative,
  // filled by scripts/fetch_reach_cumulative.py. They are the only reach
  // figures in this table Meta de-duplicated: the `Reach` column above
  // is a sum of daily rows, which counts a person once per day they saw
  // the ad (measured at 2.55x the truth over a 15-day window).
  //
  // Each carries the snapshot date it actually came from, because a
  // sparse backfill can leave an anchor trailing the requested window
  // and a figure that silently describes a different day is worse than
  // no figure at all.
  { key: "reach_weight_pct", header: "Reach Weight %", kind: "pct", group: "Reach", defaultVisible: true,
    render: (r) => <span className="num" title="Share of the reach of every ad under the current filters.">{r.reach_weight_pct == null ? "—" : `${pct(r.reach_weight_pct)}%`}</span> },
  { key: "previous_reach", header: "Prev Reach", kind: "int", group: "Reach", defaultVisible: true,
    render: (r) => <ReachCell value={r.previous_reach} asOf={r.reach_prev_as_of}
      what="Cumulative unique people reached from the reach epoch up to the day before this window"
      emptyReason="Needs a bounded date range: an unbounded window (Lifetime) has no 'before' to compare against. Also blank when no snapshot predates this ad." /> },
  { key: "latest_reach", header: "Latest Reach", kind: "int", group: "Reach", defaultVisible: true,
    render: (r) => <ReachCell value={r.latest_reach} asOf={r.reach_latest_as_of}
      what="Cumulative unique people reached from the reach epoch up to the end of this window" /> },
  { key: "incremental_reach", header: "Incr. Reach", kind: "int", group: "Reach", defaultVisible: true,
    render: (r) => <ReachCell value={r.incremental_reach} asOf={r.reach_latest_as_of} asOfFrom={r.reach_prev_as_of}
      what="Latest − Prev: people reached during this window who had never been reached before it"
      emptyReason="Needs a bounded date range: an unbounded window (Lifetime) has no 'before' to compare against. Also blank when no snapshot predates this ad." /> },
  { key: "cost_per_1000_incremental_reach", header: "Cost / 1k Incr.", kind: "money", group: "Reach", defaultVisible: true,
    render: (r) => <span className="num" title={
      r.cost_per_1000_incremental_reach == null
        ? "Needs windowed spend beside a non-zero incremental reach. Blank on the 'created' / 'first seen' date modes, where spend is lifetime and dividing it by a windowed reach would mix two periods."
        : "Windowed spend per 1,000 genuinely new people reached."
    }>{r.cost_per_1000_incremental_reach == null ? "—" : `₹${num2(r.cost_per_1000_incremental_reach)}`}</span> },
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
  { key: "new_customers", header: "New Cust", kind: "int", group: "Customers", defaultVisible: true,
    render: (r) => <span className="num">{fmt(r.new_customers, { maximumFractionDigits: 0 })}</span> },
  { key: "repeat_customers", header: "Repeat Cust", kind: "int", group: "Customers", defaultVisible: true,
    render: (r) => <span className="num">{fmt(r.repeat_customers, { maximumFractionDigits: 0 })}</span> },
  { key: "new_customer_sales", header: "New Cust Sales", kind: "money", group: "Customers", defaultVisible: true,
    render: (r) => <span className="num">₹{money(r.new_customer_sales)}</span> },
  { key: "repeat_customer_sales", header: "Repeat Cust Sales", kind: "money", group: "Customers", defaultVisible: true,
    render: (r) => <span className="num">₹{money(r.repeat_customer_sales)}</span> },
  { key: "meta_shop_diff_pct", header: "% Meta vs Shop", kind: "pct", group: "Shopify", defaultVisible: true,
    render: (r) => (
      <span
        className={
          "num " +
          (r.meta_shop_diff_pct === null
            ? ""
            : r.meta_shop_diff_pct < -20
              ? "text-error-text"
              : r.meta_shop_diff_pct > 20
                ? "text-success-text"
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
  // Efficiency ratios from the API, using lifetime fleet benchmarks.
  { key: "blended_eff", header: "Blended Eff", kind: "num", group: "Efficiency",
    render: (r) => <span className="num" title="Lifetime efficiency relative to all ads">{num3(r.blended_eff)}</span> },
  { key: "delivery_eff", header: "Delivery Eff", kind: "num", group: "Efficiency",
    render: (r) => <span className="num" title="Lifetime efficiency relative to all ads">{num3(r.delivery_eff)}</span> },
  { key: "sales_spend_eff", header: "Sales/Spend Eff", kind: "num", group: "Efficiency",
    render: (r) => <span className="num" title="Lifetime efficiency relative to all ads">{num3(r.sales_spend_eff)}</span> },
  { key: "cpr_eff", header: "CPR Eff", kind: "num", group: "Efficiency",
    render: (r) => <span className="num" title="Lifetime efficiency relative to all ads">{num3(r.cpr_eff)}</span> },
  { key: "ftv_contrib_eff", header: "FTV Contrib Eff", kind: "num", group: "Efficiency",
    render: (r) => <span className="num" title="Lifetime efficiency relative to all ads">{num3(r.ftv_contrib_eff)}</span> },
  { key: "ftev_volume", header: "FTEV Volume", kind: "num", group: "Efficiency",
    render: (r) => <span className="num" title="Lifetime efficiency relative to all ads">{num3(r.ftev_volume)}</span> },
  { key: "ncp_cost_eff", header: "NCP Cost Eff", kind: "num", group: "Efficiency",
    render: (r) => <span className="num" title="Lifetime efficiency relative to all ads">{num3(r.ncp_cost_eff)}</span> },
  { key: "roas_eff", header: "ROAS Eff", kind: "num", group: "Efficiency",
    render: (r) => <span className="num" title="Lifetime efficiency relative to all ads">{num3(r.roas_eff)}</span> },
  { key: "profit_vol_eff", header: "Profit Vol Eff", kind: "num", group: "Efficiency",
    render: (r) => <span className="num" title="Lifetime efficiency relative to all ads">{num3(r.profit_vol_eff)}</span> },
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
/** Columns that shipped hidden-by-default and have since been promoted.
 *  Only consulted when migrating the legacy bare-array storage format,
 *  which cannot distinguish "the user hid this" from "this did not
 *  exist yet". The five de-duplicated reach columns are here because
 *  they were placeholders until 2026-09-21 and were therefore written
 *  into every existing user's hidden list. */
const NEWLY_DEFAULT_VISIBLE = [
  "reach_weight_pct", "previous_reach", "latest_reach",
  "incremental_reach", "cost_per_1000_incremental_reach",
];
const LEGACY_COLUMN_KEYS: Record<string, string> = {
  date_target_imp_achieved: "impressions_50k_date",
  days_to_target_f1: "days_to_50k",
};

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
  const [slowLoading, setSlowLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryCount, setRetryCount] = useState(0);
  const [failedLoadMore, setFailedLoadMore] = useState(false);

  // ── filters ──────────────────────────────────────────────────
  const [levelToggle, setLevelToggle] = useState<"ad" | "adset" | "campaign">("ad");
  // Rollup-only controls. The rule builder and the ad search do not
  // apply to entity rows, so these are the two the endpoint actually
  // honours: a name substring and an ORDER BY.
  const [rollupSearch, setRollupSearch] = useState("");
  const debouncedRollupSearch = useDebouncedValue(rollupSearch.trim());
  const [rollupSort, setRollupSort] = useState("spend");
  const [rollupHidden, setRollupHidden] = useState<Set<string>>(new Set(ROLLUP_DEFAULT_HIDDEN));
  const [showRollupCols, setShowRollupCols] = useState(false);
  const [showRollupRules, setShowRollupRules] = useState(false);
  const rollupCols = ROLLUP_COLUMNS.filter((c) => !rollupHidden.has(c.key));
  // Ad Sets / Campaigns read adset_insights / campaign_insights via the
  // rollup endpoint. Reach there is Meta's own per-entity figure -- it
  // is NOT summable from the ad rows, which is exactly why this needs a
  // separate call rather than a client-side group-by.
  const [rollupRows, setRollupRows] = useState<RollupRow[]>([]);
  const [rollupNumeric, setRollupNumeric] = useState<NumericFilter[]>([]);
  // Applied client-side over the fetched page, exactly as the ad level
  // does: the rollup endpoint has no numeric-rule parameter, and the
  // alternative -- pretending to filter server-side -- would quietly
  // drop rows beyond the 500 fetched.
  const rollupFiltered = useMemo(
    () =>
      rollupRows.filter((r) =>
        rollupNumeric.every((nf) => {
          const v = (r as unknown as Record<string, number | null>)[nf.field];
          if (v === null || v === undefined) return false;
          return applyOperator(v, nf.op, nf.value);
        }),
      ),
    [rollupRows, rollupNumeric],
  );

  const [rollupTotal, setRollupTotal] = useState(0);
  const [rollupLoading, setRollupLoading] = useState(false);
  const [rollupError, setRollupError] = useState<string | null>(null);
  const [rollupRetryCount, setRollupRetryCount] = useState(0);

  const [account, setAccount] = useState("");
  const [groupBy, setGroupBy] = useState<"ad" | "ad_name" | "adset" | "campaign">("ad");
  const [categoryFilter, setCategoryFilter] = useState<CategoryKey | "">("");
  const [adStatus, setAdStatus] = useState("");
  // Default to 'created' -- matches CTD's Creative Testing philosophy
  // where the point of the section is to evaluate recently-launched
  // creatives. Picking "Last 7 days" then means "ads launched in the
  // last 7 days" instead of "ads that ran in the last 7 days".
  // 'delivery', not 'created'. Only the delivery mode re-sums metrics
  // from the daily grain; 'created' and 'first_seen' merely filter WHICH
  // ads appear and leave every metric at its lifetime value. With the
  // date floor that distinction matters: an ad that last ran in 2024
  // would still show its full Meta conversion value beside zero Shopify
  // revenue -- 2,751 ads carried 36.9 Cr that way. Under 'delivery' it
  // drops out instead, because it delivered nothing in the window.
  const [dateField, setDateField] = useState<"delivery" | "created" | "first_seen">("delivery");
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search.trim());
  const [onlyWithOrders, setOnlyWithOrders] = useState(false);
  // "" = no filter, "yes" = Asset ID populated, "no" = Asset ID empty.
  // A tri-state string rather than boolean|undefined so it binds
  // straight to a <select> without the false/undefined ambiguity.
  const [assetFilter, setAssetFilter] = useState<"" | "yes" | "no">("");
  // CBO / ABO. Shared by the ad table and both rollup levels so one
  // choice survives switching between them -- the classification is a
  // property of the account structure, not of the grain being viewed.
  const [budgetType, setBudgetType] = useState<"" | "CBO" | "ABO" | "NONE">("");
  // Ad sets and campaigns Meta created in the last 7 days -- the ones
  // wearing the NEW badge. Rollup-only: at ad grain "new" is a
  // different question, answered by the F1-F4 category.
  const [newEntities, setNewEntities] = useState<"" | "exclude" | "only">("");
  // Meta's EFFECTIVE delivery status. Rollup levels only: the ad table
  // has its own `adStatus` control reading a different column.
  //
  // "Active" here means actually delivering. An ad set switched on
  // under a paused campaign reports ACTIVE on itself but Meta calls it
  // CAMPAIGN_PAUSED, and it spends nothing -- 1,471 ad sets are
  // switched on, 255 are running.
  const [statusFilter, setStatusFilter] = useState<string>("");
  // Rolling last-click ROAS bounds, the rollup's answer to the F1-F4
  // threshold panel on the ad table. Blank means "no bound" -- 0 is a
  // real value (spent, earned nothing), so these are strings until they
  // reach the request.
  const [roasBounds, setRoasBounds] = useState<Record<string, string>>({
    d3_roas_min: "", d3_roas_max: "", d7_roas_min: "", d7_roas_max: "",
  });
  // Which entity's scalable-creative list is open, if any.
  const [scalableFor, setScalableFor] =
    useState<{ id: string; name: string | null } | null>(null);
  // Framework verdict filter, driven by the tiles above the table.
  const [decisionFilter, setDecisionFilter] = useState<string>("");
  const [decisionCounts, setDecisionCounts] =
    useState<Record<string, { count: number; spend: number }>>({});
  // Date range window -- when both are set, spend / impressions /
  // purchases / conv_value / roas in the response are overwritten
  // with values summed from Bronze raw_dump_meta within the window.
  // Seeded from the preset rather than left blank. Blank meant NO date
  // params were sent at all, so the backend kept every lifetime column
  // -- Meta spend and conversion value reaching back years against
  // Shopify orders that only exist for 2026. `Lifetime` now resolves to
  // a real bounded range (see DATA_FLOOR), and it has to be applied on
  // first load, not only after someone opens the picker and hits Apply.
  const [rawFrom, setFromDate] = useState(() => resolvePreset("lifetime").from);
  const [rawTo, setToDate] = useState(() => resolvePreset("lifetime").to);
  const [datePreset, setDatePreset] = useState<string>("lifetime");
  // The newest day Meta's insights actually cover. Presets are anchored
  // on it rather than on the clock: Meta reports a day in arrears, so a
  // clock-anchored "Last 7 Days" asks for a window whose last day does
  // not exist and silently sums six days against Meta's seven -- a
  // whole day of spend missing from every row.
  const [dataThrough, setDataThrough] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    fetchCpisDataFreshness()
      .then((f) => { if (live && f.max_meta_day) setDataThrough(f.max_meta_day); })
      .catch(() => { /* fall back to the clock; the picker still works */ });
    return () => { live = false; };
  }, []);
  // The window the page actually queries. Derived, not stored: once the
  // anchor arrives every preset re-resolves against the data instead of
  // the clock, without a second render pass writing state back.
  //
  // A custom range is the user's own choice and is never re-anchored.
  const { from: winFrom, to: winTo } = useMemo(() => {
    if (!dataThrough || datePreset === "custom") return { from: rawFrom, to: rawTo };
    return resolvePreset(datePreset as Parameters<typeof resolvePreset>[0], dataThrough);
  }, [dataThrough, datePreset, rawFrom, rawTo]);

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
  //
  // The stored value used to be a bare array of hidden keys, which made
  // a saved preference outrank every later change to the defaults: a
  // column added after the user last opened this picker was absent from
  // that array's `known` context, so it inherited "hidden" and could
  // never appear on its own. Five de-duplicated reach columns shipped
  // straight into that hole -- present in the API response, rendered by
  // the table, and invisible.
  //
  // So the stored shape now carries which keys existed when it was
  // written. A key the saved state never saw is not a decision the user
  // made, and falls back to its default. The legacy array still loads;
  // it simply has no `known` list, so every column is treated as new
  // and the current defaults win once.
  const [hiddenCols, setHiddenCols] = useState<Set<string>>(() => {
    const fallback = () => new Set(ALL_KEYS.filter((k) => !DEFAULT_VISIBLE_KEYS.has(k)));
    if (typeof window === "undefined") return fallback();
    try {
      const raw = window.localStorage.getItem(HIDDEN_STORAGE_KEY);
      if (!raw) return fallback();
      const stored: unknown = JSON.parse(raw);

      const isKeyList = (v: unknown): v is string[] =>
        Array.isArray(v) && v.every((k) => typeof k === "string");
      const rename = (k: string) => LEGACY_COLUMN_KEYS[k] ?? k;

      // Legacy: a bare array of hidden keys, with no record of what it
      // knew about. Trust it for everything -- wiping a user's column
      // choices to surface new ones would be a worse trade -- and apply
      // a one-off un-hide for the columns that shipped hidden and have
      // since become default-visible. Anything added from here on is
      // handled by `known` below and needs no such list.
      if (isKeyList(stored)) {
        const hidden = new Set(stored.map(rename));
        for (const key of NEWLY_DEFAULT_VISIBLE) hidden.delete(key);
        return hidden;
      }

      const hiddenRaw = (stored as { hidden?: unknown })?.hidden;
      if (!isKeyList(hiddenRaw)) return fallback();

      const knownRaw = (stored as { known?: unknown }).known;
      const known = new Set((isKeyList(knownRaw) ? knownRaw : []).map(rename));
      const hidden = new Set(hiddenRaw.map(rename));

      for (const key of ALL_KEYS) {
        if (known.has(key)) continue;
        // Never seen by the saved state -> honour the column's default.
        if (DEFAULT_VISIBLE_KEYS.has(key)) hidden.delete(key);
        else hidden.add(key);
      }
      return hidden;
    } catch {
      return fallback();
    }
  });
  const [colPickerOpen, setColPickerOpen] = useState(false);
  const [colSearch, setColSearch] = useState("");
  useEffect(() => {
    try {
      window.localStorage.setItem(
        HIDDEN_STORAGE_KEY,
        JSON.stringify({ hidden: [...hiddenCols], known: ALL_KEYS }),
      );
    } catch {}
  }, [hiddenCols]);
  const visibleCols = COLUMNS.filter((c) => !hiddenCols.has(c.key));

  // ── inspector drawer ─────────────────────────────────────────
  const [multiFilter, setMultiFilter] = useState<MultiFilterState | null>(null);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [inspectorTab, setInspectorTab] = useState<"metrics" | "filters">("metrics");
  const [numericFilters, setNumericFilters] = useState<NumericFilter[]>([]);

  // ── sort ────────────────────────────────────────────────────
  const [sortKey, setSortKey] = useState<string>("spend");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  // ── pagination ──────────────────────────────────────────────
  const [page, setPage] = useState(0);

  // A slow response can still succeed. Give feedback without aborting it
  // or launching duplicate requests while the backend is waking up.
  useEffect(() => {
    setSlowLoading(false);
    if (!loading && !rollupLoading) return;
    const timer = window.setTimeout(() => setSlowLoading(true), 10_000);
    return () => window.clearTimeout(timer);
  }, [loading, rollupLoading]);

  // ── fetch data ──────────────────────────────────────────────
  useEffect(() => {
    if (levelToggle === "ad") return;
    let cancelled = false;
    setRollupLoading(true);
    setRollupError(null);
    fetchAdsAnalyseRollup({
      level: levelToggle,
      account_name: account || undefined,
      search: debouncedRollupSearch || undefined,
      sort: rollupSort,
      budget_type: budgetType || undefined,
      status: statusFilter || undefined,
      ...Object.fromEntries(
        Object.entries(roasBounds)
          .filter(([, v]) => v.trim() !== "" && Number.isFinite(Number(v)))
          .map(([k, v]) => [k, Number(v)]),
      ),
      decision: decisionFilter || undefined,
      new_entities: newEntities || undefined,
      limit: 500,
      // The Shopify columns follow the section's own date range, so the
      // rollup answers the same question the ad level does.
      from_date: winFrom || undefined,
      to_date: winTo || undefined,
    })
      .then((res) => {
        if (cancelled) return;
        setRollupRows(res.rows);
        setRollupTotal(res.total);
        setDecisionCounts(res.decision_counts ?? {});
      })
      .catch((err: unknown) => {
        if (!cancelled) setRollupError(err instanceof ApiError ? err.message : "Could not reach the analytics backend. Please retry.");
      })
      .finally(() => !cancelled && setRollupLoading(false));
    return () => {
      cancelled = true;
    };
  }, [levelToggle, account, debouncedRollupSearch, rollupSort, rollupRetryCount, winFrom, winTo, budgetType, statusFilter, roasBounds, decisionFilter, newEntities]);

  const filters = useMemo(
    () => ({
      account_name: account || undefined,
      search: debouncedSearch || undefined,
      // With custom thresholds the server's stored category is the wrong
      // answer, so we fetch unfiltered and narrow it client-side instead.
      category: thresholdsChanged ? undefined : categoryFilter || undefined,
      ad_effective_status: adStatus || undefined,
      only_with_shopify_orders: onlyWithOrders,
      has_asset_id: assetFilter === "" ? undefined : assetFilter === "yes",
      budget_type: budgetType || undefined,
      multi_filter: multiFilter ? JSON.stringify(multiFilter) : undefined,
      // Only send both together -- one without the other has no meaning
      // on the server side (the overlay/filter branch keys on both being set).
      from_date: winFrom && winTo ? winFrom : undefined,
      to_date: winFrom && winTo ? winTo : undefined,
      date_field: winFrom && winTo ? dateField : undefined,
    }),
    [account, debouncedSearch, categoryFilter, thresholdsChanged, adStatus, onlyWithOrders, assetFilter, budgetType, multiFilter, winFrom, winTo, dateField],
  );

  // sessionStorage cache -- /ads-analyse takes several seconds cold,
  // so tab-switching / hard-refresh needs to skip the fetch when the
  // filter set is unchanged. 5-min TTL matches Dashboard.tsx's
  // useCachedFetch default. Filter-scoped key so a filter change
  // always misses the cache and fetches fresh. Version 3 invalidates
  // cached rows from before the API included the restored timeline data.
  useEffect(() => {
    let cancelled = false;
    const cacheKey = "ae-ads-analyse-v3|" + JSON.stringify(filters);
    const TTL_MS = 5 * 60 * 1000;
    type Cached = {
      rows: AdsAnalyseRow[];
      total: number;
      totals: AdsAnalyseTotals | null;
      category_counts: Record<string, number>;
      ts: number;
    };
    if (typeof window !== "undefined") {
      try {
        const raw = window.sessionStorage.getItem(cacheKey);
        if (raw) {
          const c = JSON.parse(raw) as Cached;
          if (Date.now() - c.ts < TTL_MS) {
            setError(null);
            setFailedLoadMore(false);
            setRows(c.rows);
            setTotal(c.total);
            setCategoryCountsFromApi(c.category_counts);
            setTotals(c.totals);
            setPage(0);
            setLoading(false);
            return () => {
              cancelled = true;
            };
          }
        }
      } catch {
        // Ignore quota / parse errors; fall through to network.
      }
    }
    setLoading(true);
    setError(null);
    setFailedLoadMore(false);
    // Load the visible page first. KPI totals and category counts still
    // cover all matching ads; Load More fetches subsequent 500-row batches.
    fetchAdsAnalyse({ ...filters, limit: PAGE_SIZE, offset: 0 })
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
        if (typeof window !== "undefined") {
          try {
            window.sessionStorage.setItem(
              cacheKey,
              JSON.stringify({
                rows: res.rows,
                total: res.total,
                totals: res.totals ?? null,
                category_counts: res.category_counts ?? {},
                ts: Date.now(),
              } satisfies Cached),
            );
          } catch {
            // Quota exceeded -- skip caching this response.
          }
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Could not reach the analytics backend. Please retry.");
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [filters, retryCount]);

  async function loadMore() {
    setLoadingMore(true);
    setError(null);
    setFailedLoadMore(false);
    try {
      const res = await fetchAdsAnalyse({ ...filters, limit: 500, offset: rows.length });
      setRows((prev) => [...prev, ...res.rows]);
    } catch (err) {
      setFailedLoadMore(true);
      setError(err instanceof ApiError ? err.message : "Could not load more rows.");
    } finally {
      setLoadingMore(false);
    }
  }

  // ── client-side recategorise + numeric filter + sort ─────────
  const derived = useMemo(() => {
    const withCat = rows.map((r) => ({ row: r, cat: categorise(r, thresholds, !thresholdsChanged) }));
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
      // Only filter here when the server could NOT -- i.e. custom
      // thresholds. At defaults the server already returned exactly this
      // category and filtering again can only lose rows.
      if (thresholdsChanged && categoryFilter && rc.cat !== categoryFilter) return false;
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
  }, [rows, thresholds, thresholdsChanged, categoryFilter, numericFilters, sortKey, sortDir]);

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
    setDatePreset("lifetime");
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
        {/* Was "Creative Testing" -- a leftover from the CTD port that
            became actively wrong once Creative Testing existed as its
            own tab. */}
        <h2 className="text-[18px] font-semibold tracking-[-0.02em] text-text-primary">Ads Analyse</h2>
        <div className="inline-flex rounded-md border border-border-primary bg-white shadow-sm">
          {(["ad", "adset", "campaign"] as const).map((lv) => (
            <button
              key={lv}
              onClick={() => setLevelToggle(lv)}
              title={
                lv === "ad"
                  ? "Ad level"
                  : `${lv} rollup — Meta-deduplicated reach from ${lv}_insights`
              }
              className={
                "px-3 py-1 text-xs first:rounded-l-md last:rounded-r-md " +
                (levelToggle === lv
                  ? "bg-text-primary text-white"
                  : "text-text-primary hover:bg-bg-muted")
              }
            >
              {lv === "ad" ? "Ads" : lv === "adset" ? "Ad Sets" : "Campaigns"}
            </button>
          ))}
        </div>
        <span className="ml-auto text-xs text-text-tertiary">
          {levelToggle !== "ad"
            ? rollupLoading
              ? "loading…"
              : `${rollupRows.length.toLocaleString()} of ${rollupTotal.toLocaleString()} ${levelToggle === "adset" ? "ad sets" : "campaigns"}`
            : loading
              ? "loading…"
              : `${derived.filtered.length.toLocaleString()} of ${total.toLocaleString()} ads`}
        </span>
      </div>


      {/* ═══════════════════════════════════════════════════════════
          Filter cards — ACCOUNT / GROUP BY / CATEGORY / AD STATUS /
          DATE FIELD / DATE RANGE. Six labelled cards on one row, matching
          the legacy Ads Analyse layout: uppercase label above, control
          below, each in its own bordered card rather than a loose strip
          of bare selects.
         ═══════════════════════════════════════════════════════════ */}
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
        <FilterCard label="Account">
          <CardSelect value={account} onChange={setAccount}>
            <option value="">All Accounts</option>
            {[...accountOptions].sort().map((a) => (
              <option key={a} value={a}>{a}</option>
            ))}
          </CardSelect>
        </FilterCard>

        <FilterCard label="Group by">
          <CardSelect
            value={levelToggle}
            onChange={(v) => setLevelToggle(v as typeof levelToggle)}
          >
            <option value="ad">Ad Level</option>
            <option value="adset">Ad Set</option>
            <option value="campaign">Campaign</option>
          </CardSelect>
        </FilterCard>

        {/* Ad-column filters. The rollup endpoint takes account,
            search and a date window only, so on the Ad set / Campaign
            levels these would be controls that visibly do nothing. */}
        {levelToggle === "ad" && (
          <>
        <FilterCard label="Category">
          <CardSelect
            value={categoryFilter}
            onChange={(v) => setCategoryFilter(v as CategoryKey | "")}
          >
            <option value="">All Categories</option>
            {CATEGORY_ORDER.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </CardSelect>
        </FilterCard>

        <FilterCard label="Ad status">
          <CardSelect value={adStatus} onChange={setAdStatus}>
            <option value="">All Statuses</option>
            {[...statusOptions].sort().map((s2) => (
              <option key={s2} value={s2}>{s2}</option>
            ))}
          </CardSelect>
        </FilterCard>

        <FilterCard label="Date field">
          <CardSelect
            value={dateField}
            onChange={(v) => setDateField(v as typeof dateField)}
          >
            <option value="delivery">Delivery Date</option>
            <option value="created">Ad Created</option>
            <option value="first_seen">First Seen</option>
          </CardSelect>
        </FilterCard>
          </>
        )}

        <FilterCard label="Date range">
          <DateRangePicker
            value={{ from: winFrom, to: winTo }}
            preset={datePreset}
            anchor={dataThrough}
            // Opens rightwards. This card is third of six, so hanging the
            // ~700px panel off its RIGHT edge pushed the preset rail off
            // the left of the viewport entirely -- the calendar showed
            // but Today / Last 7 Days / Lifetime were unreachable.
            align="left"
            onApply={(r, pk) => {
              setFromDate(r.from);
              setToDate(r.to);
              setDatePreset(pk);
            }}
          />
        </FilterCard>

        {/* Rollup-only, in the SAME grid as the shared cards above so
            all five filters read as one row rather than a second block
            floating under the first. */}
        {levelToggle !== "ad" && (
          <>
            <FilterCard label={levelToggle === "adset" ? "Ad set name" : "Campaign name"}>
              <input
                value={rollupSearch}
                onChange={(e) => setRollupSearch(e.target.value)}
                placeholder="Contains…"
                className="w-full rounded-md border border-border-primary px-2 py-1 text-sm"
              />
            </FilterCard>
            <FilterCard label="Sort by">
              <CardSelect value={rollupSort} onChange={setRollupSort}>
                <option value="spend">Spend</option>
                <option value="impressions">Impressions</option>
                <option value="reach">Reach</option>
                <option value="roas">Meta ROAS</option>
                <option value="ads">Ads</option>
                <option value="shopify_orders">Shopify orders</option>
                <option value="shopify_revenue">Shopify revenue</option>
                <option value="shopify_roas">Shopify ROAS</option>
              </CardSelect>
            </FilterCard>
            {/* Same `budgetType` state the ad view uses, so the choice
                survives switching level -- CBO/ABO is a property of the
                account's structure, not of the grain being looked at.
                The verdict tiles recompute against it server-side. */}
            {/* Meta's effective status. "Active" is deliberately the
                delivering set, not the switched-on set -- see the
                option labels. */}
            <FilterCard label="Delivery status">
              <CardSelect value={statusFilter} onChange={setStatusFilter}>
                <option value="">All statuses</option>
                <option value="ACTIVE">Active — delivering</option>
                <option value="PAUSED">Paused</option>
                {levelToggle === "adset" && (
                  <option value="CAMPAIGN_PAUSED">Campaign paused — on, but not running</option>
                )}
                {levelToggle === "adset" && (
                  <option value="WITH_ISSUES">With issues</option>
                )}
                <option value="ARCHIVED">Archived</option>
              </CardSelect>
            </FilterCard>
            {/* Newly created entities. A pause on something three days
                old is a decision not to continue a test, not a verdict
                on performance -- and 36 ad sets and 10 campaigns are
                currently inside that window, enough to move any average
                read across the table. "Only new" is the other half of
                the same question: what did we just launch? */}
            <FilterCard label="New ad sets & campaigns">
              <CardSelect
                value={newEntities}
                onChange={(v) => setNewEntities(v as "" | "exclude" | "only")}
              >
                <option value="">Include new</option>
                <option value="exclude">Exclude new — created in last 7 days</option>
                <option value="only">Only new — created in last 7 days</option>
              </CardSelect>
            </FilterCard>
            <FilterCard label="Budget level">
              <CardSelect
                value={budgetType}
                onChange={(v) => setBudgetType(v as "" | "CBO" | "ABO" | "NONE")}
              >
                <option value="">All budgets</option>
                <option value="CBO">CBO — campaign holds it</option>
                <option value="ABO">ABO — ad set holds it</option>
                <option value="NONE">No budget set</option>
              </CardSelect>
            </FilterCard>
            {/* Last-click ROAS bounds -- the rollup's counterpart to the
                F1-F4 threshold panel on the ad table: type the numbers
                rather than pick a preset bucket.

                Laid out as two ranges rather than four labelled boxes.
                "3D min / 3D max" spent half the card's width restating
                a word the heading already said, and left the inputs too
                narrow to read a value in.

                Empty means no bound, and that is deliberately NOT the
                same as 0: an entity that spent and earned nothing has a
                real ROAS of 0 and must stay reachable by a max bound. */}
            <FilterCard label="Last-click ROAS">
              <div className="space-y-1.5">
                {([["d3_roas_min", "d3_roas_max", "3D"],
                   ["d7_roas_min", "d7_roas_max", "7D"]] as const).map(
                  ([minKey, maxKey, label]) => (
                    <div key={label} className="flex items-center gap-1.5">
                      <span className="w-6 shrink-0 text-[11px] font-semibold text-text-tertiary">
                        {label}
                      </span>
                      {([minKey, maxKey] as const).map((key, i) => (
                        <div key={key} className="flex flex-1 items-center gap-1.5">
                          {i === 1 && <span className="text-text-tertiary">–</span>}
                          <input
                            type="number"
                            step="0.1"
                            min="0"
                            inputMode="decimal"
                            aria-label={`${label} last-click ROAS ${i === 0 ? "minimum" : "maximum"}`}
                            value={roasBounds[key]}
                            onChange={(e) =>
                              setRoasBounds((prev) => ({ ...prev, [key]: e.target.value }))}
                            placeholder={i === 0 ? "min" : "max"}
                            className="w-full min-w-0 rounded-md border bg-white px-2 py-1.5 text-xs tabular-nums"
                            style={{ borderColor: AE.border, color: AE.ink }}
                          />
                        </div>
                      ))}
                    </div>
                  ),
                )}
                {Object.values(roasBounds).some((v) => v.trim() !== "") && (
                  <button
                    type="button"
                    onClick={() => setRoasBounds({
                      d3_roas_min: "", d3_roas_max: "", d7_roas_min: "", d7_roas_max: "",
                    })}
                    className="text-[11px] text-text-tertiary underline underline-offset-2 hover:text-text-primary"
                  >
                    Clear
                  </button>
                )}
              </div>
            </FilterCard>
          </>
        )}
      </div>

      {/* ═══════════════════════════════════════════════════════════
          Ad Set / Campaign rollup. Replaces the ad table entirely when a
          level is picked -- the columns differ (reach and frequency are
          Meta's own per-entity figures, not summable from ads) and the
          F1-F4 verdicts are an ad-level concept that does not apply here.
         ═══════════════════════════════════════════════════════════ */}
      {slowLoading && (loading || rollupLoading) && (
        <p role="status" className="text-sm text-text-secondary">
          This is taking longer than usual. Your data is still loading…
        </p>
      )}

      {levelToggle !== "ad" && (
        <div className="space-y-2">
          {rollupError && (
            <div role="alert" className="flex items-center justify-between gap-3 rounded-lg border border-border-primary bg-error-bg p-3 text-sm text-error-text">
              <span>{rollupError}</span>
              <button type="button" onClick={() => setRollupRetryCount((count) => count + 1)} disabled={rollupLoading}
                className="shrink-0 rounded border border-current px-3 py-1 font-medium disabled:opacity-40">
                Retry
              </button>
            </div>
          )}
          {/* Inspector controls, same shape as the ad level's. */}
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => setShowRollupCols((v) => !v)}
              className="rounded-md border border-border-primary bg-white px-2.5 py-1.5 text-xs hover:bg-bg-muted"
            >
              ▤ Columns ({rollupCols.length}/{ROLLUP_COLUMNS.length})
            </button>
            {rollupHidden.size !== ROLLUP_DEFAULT_HIDDEN.size && (
              <button
                onClick={() => setRollupHidden(new Set(ROLLUP_DEFAULT_HIDDEN))}
                className="rounded-md border border-border-primary bg-white px-2.5 py-1.5 text-xs hover:bg-bg-muted"
              >
                Reset to default
              </button>
            )}
            <button
              onClick={() => setShowRollupRules((v) => !v)}
              className="rounded-md border border-border-primary bg-white px-2.5 py-1.5 text-xs hover:bg-bg-muted"
            >
              ⚖ Metric rules{rollupNumeric.length ? ` (${rollupNumeric.length})` : ""}
            </button>
            {rollupNumeric.length > 0 && (
              <span className="text-[11px] text-text-tertiary">
                {rollupFiltered.length.toLocaleString("en-IN")} of{" "}
                {rollupRows.length.toLocaleString("en-IN")} rows match
              </span>
            )}
          </div>

          {showRollupRules && (
            <div className="rounded-lg border border-border-primary bg-white p-3 shadow-sm">
              <div className="mb-2 text-[11px] text-text-tertiary">
                Rules apply to the {rollupRows.length.toLocaleString("en-IN")} rows fetched for
                this level — not to the whole table server-side.
              </div>
              <NumericFiltersPanel
                filters={rollupNumeric}
                onChange={setRollupNumeric}
                fields={ROLLUP_NUMERIC_FIELDS}
              />
            </div>
          )}

          {showRollupCols && (
            <div className="rounded-lg border border-border-primary bg-white p-3 shadow-sm">
              <div className="mb-2 flex items-center gap-2">
                <button
                  onClick={() => setRollupHidden(new Set())}
                  className="rounded-md border border-border-primary px-2 py-1 text-xs hover:bg-bg-muted"
                >
                  Show all
                </button>
                <button
                  onClick={() => setRollupHidden(new Set(ROLLUP_COLUMNS.map((c) => c.key)))}
                  className="rounded-md border border-border-primary px-2 py-1 text-xs hover:bg-bg-muted"
                >
                  Hide all
                </button>
              </div>
              <div className="grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-4">
                {ROLLUP_GROUPS.map((grp) => (
                  <div key={grp}>
                    <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-text-tertiary">
                      {grp}
                    </div>
                    {ROLLUP_COLUMNS.filter((c) => c.group === grp).map((c) => (
                      <label key={c.key} className="flex items-center gap-1.5 py-0.5 text-xs">
                        <input
                          type="checkbox"
                          checked={!rollupHidden.has(c.key)}
                          onChange={() =>
                            setRollupHidden((prev) => {
                              const next = new Set(prev);
                              if (next.has(c.key)) next.delete(c.key);
                              else next.add(c.key);
                              return next;
                            })
                          }
                        />
                        <span>{c.header}</span>
                      </label>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Framework verdicts. Counts come from the server over EVERY
              matching entity -- deriving them from the 500 loaded rows
              would describe a page while claiming to describe 3,008.
              Clicking filters the table server-side for the same reason. */}
          {/* Four across, not six: the OK and UNRATED tiles were dropped. */}
          <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {DECISION_TILES.map((t) => {
              const d = decisionCounts[t.key] ?? { count: 0, spend: 0 };
              const on = decisionFilter === t.key;
              return (
                // The (i) is a SIBLING of the button, not a child: the
                // tile is itself a button, and nesting one inside
                // another is invalid HTML. As a sibling it also cannot
                // bubble a click into the filter.
                <div key={t.key} className="relative">
                  <button
                    onClick={() => setDecisionFilter(on ? "" : t.key)}
                    className={
                      "w-full rounded-lg border bg-white p-2.5 text-left shadow-sm transition " +
                      (on ? "ring-2 ring-offset-1 " : "hover:bg-bg-muted ") +
                      (d.count === 0 ? "opacity-50 " : "")
                    }
                    style={on ? { borderColor: t.color, boxShadow: `0 0 0 1px ${t.color}` } : undefined}
                  >
                    {/* pr-5 keeps the label clear of the dot above it. */}
                    <div className="pr-5 text-[10px] font-semibold uppercase tracking-wide"
                         style={{ color: t.color }}>{t.label}</div>
                    <div className="num text-lg font-bold">{d.count.toLocaleString("en-IN")}</div>
                    <div className="text-[10px] text-text-tertiary">₹{money(d.spend)}</div>
                  </button>
                  <span className="absolute right-2 top-2">
                    <InfoDot basis={t.basis} />
                  </span>
                </div>
              );
            })}
          </div>
          <DecisionRules />
          {scalableFor && (
            <ScalableCreativesDrawer
              level={levelToggle === "adset" ? "adset" : "campaign"}
              entityId={scalableFor.id}
              entityName={scalableFor.name}
              fromDate={winFrom}
              toDate={winTo}
              onClose={() => setScalableFor(null)}
            />
          )}

          <div className="overflow-x-auto rounded-lg border border-border-primary bg-white shadow-sm">
            <table className="ae-table w-full min-w-full text-sm">
              <thead className="bg-bg-muted text-left text-[11px] uppercase tracking-wide text-text-tertiary">
                <tr>
                  {rollupCols.map((c) => (
                    <th
                      key={c.key}
                      title={c.title}
                      className={"px-3 py-2 " + (c.align === "right" ? "text-right" : "")}
                    >
                      {c.key === "entity_name"
                        ? levelToggle === "adset" ? "Ad set" : "Campaign"
                        : c.header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rollupLoading && (
                  <tr>
                    <td colSpan={rollupCols.length} className="px-3 py-6 text-center text-text-tertiary">
                      Loading…
                    </td>
                  </tr>
                )}
                {!rollupLoading && rollupFiltered.length === 0 && (
                  <tr>
                    <td colSpan={rollupCols.length} className="px-3 py-6 text-center text-text-tertiary">
                      No {levelToggle === "adset" ? "ad sets" : "campaigns"} found.
                    </td>
                  </tr>
                )}
                {!rollupLoading &&
                  rollupFiltered.map((r) => (
                    <tr
                      key={r.entity_id}
                      className="border-t border-border-soft hover:bg-bg-surface"
                      // The column definitions are module-level, so the
                      // Scale-worthy button cannot reach component state
                      // directly. It tags itself and the row opens the
                      // drawer -- one handler instead of one per cell.
                      onClick={(e) => {
                        const hit = (e.target as HTMLElement).closest("[data-scalable]");
                        if (hit) setScalableFor({ id: r.entity_id, name: r.entity_name });
                      }}
                    >
                      {rollupCols.map((c) => (
                        <td
                          key={c.key}
                          className={"px-3 py-2 " + (c.align === "right" ? "text-right" : "")}
                        >
                          {c.render(r)}
                        </td>
                      ))}
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          <p className="text-[11px] leading-relaxed text-text-tertiary">
            Reach and frequency are Meta&rsquo;s own per-{levelToggle} figures, not a sum of the
            ads underneath — Meta dedupes a person per entity, so adding ad-level reach counts the
            same person once per ad they saw. Each row&rsquo;s <b>Window</b> shows the period its
            figures actually cover; rows are refreshed independently, so they are not all the same
            period.
          </p>
        </div>
      )}

      {/* The rule builder works over AD columns and the rollup endpoint
          does not take it, so it is ad-level only. */}
      {levelToggle === "ad" && (
        <MultiFilter applied={multiFilter} onApply={setMultiFilter} />
      )}

      {/* Everything below is AD-GRAIN: the thresholds, the verdict
          tiles, the launch chart and the main table all describe
          individual ads. On the Ad set / Campaign levels they would be
          answering a different question than the table above them, so
          they are not rendered at all rather than left showing ad
          numbers under an ad-set heading. */}
      {levelToggle === "ad" && (
        <>
      {/* F1–F4 thresholds, same card treatment. */}
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-5">
        <FilterCard label="F1 — Impressions">
          <CardNumber
            value={thresholds.f1Imp}
            onChange={(n) => setThresholds({ ...thresholds, f1Imp: n })}
          />
        </FilterCard>
        <FilterCard label="F2 — ROAS">
          <CardNumber
            value={thresholds.f2Roas}
            step={0.1}
            onChange={(n) => setThresholds({ ...thresholds, f2Roas: n })}
          />
        </FilterCard>
        <FilterCard label="F3 — Cost / NCP">
          <CardNumber
            value={thresholds.f3CostPerNcp}
            onChange={(n) => setThresholds({ ...thresholds, f3CostPerNcp: n })}
          />
        </FilterCard>
        <FilterCard label="F4 — Cost / FTEWV">
          <CardNumber
            value={thresholds.f4CostPerFtewv}
            onChange={(n) => setThresholds({ ...thresholds, f4CostPerFtewv: n })}
          />
        </FilterCard>
        <FilterCard label="Reset">
          <button
            onClick={() => setThresholds(DEFAULT_THRESHOLDS)}
            disabled={!thresholdsChanged}
            className="w-full rounded-md border bg-white px-3 py-2 text-sm disabled:opacity-40"
            style={{ borderColor: AE.border }}
          >
            Defaults
          </button>
        </FilterCard>
      </div>

      {/* ═══════════════════════════════════════════════════════════
          Row controls. The standalone "Search ad name" box was removed
          2026-09-16: Multi-Filter's Ad Name + "contains all of" does the
          same job and six other fields besides, so the two were just
          competing ways to type the same query.
          Shop-orders toggle + collapsed thresholds button.
          Thresholds were previously in a 5-input row above the KPI
          tiles which visually competed with everything else -- moved
          to a popover so the primary flow (KPIs → filters → table)
          stays clean. A "modified" pill flags when the user has
          diverged from CTD's defaults (2026-08-29 declutter pass).
         ═══════════════════════════════════════════════════════════ */}
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border-primary bg-white p-2 shadow-sm">
        <label className="flex items-center gap-1.5 text-xs">
          <input type="checkbox" checked={onlyWithOrders} onChange={(e) => setOnlyWithOrders(e.target.checked)} />
          Has Shopify orders
        </label>
        <label className="flex items-center gap-1.5 text-xs">
          Asset ID
          <select
            value={assetFilter}
            onChange={(e) => setAssetFilter(e.target.value as "" | "yes" | "no")}
            className="rounded-md border border-border-primary px-2 py-1 text-xs"
            title="Filter by whether the ad resolved to a creative asset. Matched includes every match source (direct / ctd_matched / name_parsed / name_synthetic)."
          >
            <option value="">All ads</option>
            <option value="yes">Has asset ID</option>
            <option value="no">No asset ID</option>
          </select>
        </label>
        <label className="flex items-center gap-1.5 text-xs">
          Budget
          <select
            value={budgetType}
            onChange={(e) => setBudgetType(e.target.value as "" | "CBO" | "ABO" | "NONE")}
            className="rounded-md border border-border-primary px-2 py-1 text-xs"
            title="Where the budget is set. CBO: on the campaign, so Meta moves money between its ad sets. ABO: on each ad set, so the split is fixed. Mutually exclusive — no entity has both."
          >
            <option value="">All budgets</option>
            <option value="CBO">CBO (campaign)</option>
            <option value="ABO">ABO (ad set)</option>
            <option value="NONE">No budget set</option>
          </select>
        </label>
        {/* The F1-F4 threshold popover was removed 2026-09-16: those
            controls now sit in their own labelled cards above, matching
            the legacy layout. Two editors bound to the same state would
            only drift. `bufferDays` moved with them -- it is still used
            by categorise() for the Result Awaited grace window. */}
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={clearAllFilters}
            className="rounded-md border border-border-primary bg-white px-2.5 py-1 text-xs hover:bg-bg-muted"
          >
            Clear Filters
          </button>
          <button
            onClick={() => setColPickerOpen((v) => !v)}
            className="rounded-md border border-border-primary bg-white px-2.5 py-1 text-xs hover:bg-bg-muted"
          >
            ▤ Columns ({visibleCols.length}/{COLUMNS.length})
          </button>
          <button
            onClick={() => setInspectorOpen((v) => !v)}
            className="rounded-md border border-border-primary bg-white px-2.5 py-1 text-xs hover:bg-bg-muted"
            title="Inspector: Metrics + numeric Filters"
          >
            ⚙ Inspector
            {numericFilters.length > 0 && (
              <span className="ml-1 rounded bg-warning-bg px-1 text-warning-text">
                {numericFilters.length}
              </span>
            )}
          </button>
        </div>
        <ExportButton
          rows={rows as unknown as Record<string, unknown>[]}
          filename="ads_analyse"
          window={datePreset}
          disabled={loading || !rows.length}
        />
      </div>

      {/* The 8-tile aggregate strip (Ads / Spend / Impressions / Reach /
          Purchases / Meta ROAS / Shop orders / Shop ROAS) was removed
          2026-09-16: the original CTD Ads Analyse leads with the F1-F4
          verdict buckets and the threshold controls, not a second
          summary row above them. The same figures remain available in
          the table's own columns and in Creative Testing's Overview. */}

      {/* ═══════════════════════════════════════════════════════════
          7 KPI category tiles — click to filter
          Rebuilt on top of KwikTile (2026-08-29) to match the
          kwikengage Marketing Insights KPI-card aesthetic — icon
          square, uppercase label, big monospaced count, spend sub-line.
         ═══════════════════════════════════════════════════════════ */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
        {CATEGORY_ORDER.map((cat) => {
          // Counts come from the SERVER (`category_counts`), which covers
          // every matching ad. derived.tileCounts only ever sees the rows
          // currently paged in, so it showed "P2 analysis 3" against a
          // real 1,768. The client figure is used only with custom
          // thresholds, where the server's counts no longer apply.
          const count = thresholdsChanged
            ? derived.tileCounts[cat]
            : (categoryCountsFromApi[cat] ?? 0);
          // Spend stays page-scoped either way -- the totals payload is
          // for the whole filter set, not per category -- so it is
          // labelled as such rather than implying a full-dataset figure.
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
              info={categoryBasis(cat, thresholdsChanged)}
              active={selected}
              onClick={() => setCategoryFilter(selected ? "" : cat)}
            />
          );
        })}
      </div>

      {/* Ads launched per day. Replaces the three client-side charts
          that were computed from derived.filtered -- i.e. one page of
          rows -- while presenting themselves as a view of the whole
          filter set. This one aggregates server-side. */}
      <AdsLaunchChart
        fromDate={winFrom}
        toDate={winTo}
        accountName={account || undefined}
        category={categoryFilter || undefined}
        adStatus={adStatus || undefined}
        search={debouncedSearch || undefined}
      />

      {/* Total ads bar */}
      <div className="rounded-lg border border-border-primary bg-white px-3 py-1.5 text-xs text-text-secondary shadow-sm">
        Total shown in table: <strong className="text-text-primary">{derived.filtered.length.toLocaleString()}</strong> ads
        {categoryFilter && <> · filtered to <strong className="text-text-primary">{categoryFilter}</strong></>}
        {numericFilters.length > 0 && <> · {numericFilters.length} numeric rule{numericFilters.length > 1 ? "s" : ""}</>}
        · {total.toLocaleString()} total in DB
        {rows.length < total && <> · fetched first {rows.length.toLocaleString()}</>}
      </div>

      {/* Errors */}
      {error && (
        <div role="alert" className="flex items-center justify-between gap-3 rounded-md border border-error-mid bg-error-bg p-2 text-sm text-error-text">
          <span>{error}</span>
          <button type="button" onClick={() => failedLoadMore ? void loadMore() : setRetryCount((count) => count + 1)}
            disabled={loading || loadingMore}
            className="shrink-0 rounded border border-current px-3 py-1 font-medium disabled:opacity-40">
            Retry
          </button>
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════
          Main table
         ═══════════════════════════════════════════════════════════ */}
      {loading ? (
        <TableSkeleton rows={12} columns={14} />
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
                      "cursor-pointer whitespace-nowrap px-2.5 py-2.5 font-medium hover:bg-bg-muted " +
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
                    <td key={c.key} className="px-2.5 py-1.5">
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

        </>
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
                    (inspectorTab === tab ? "border-b-2 border-text-primary font-medium" : "text-text-secondary")
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

function NumericFiltersPanel({
  filters,
  onChange,
  fields = NUMERIC_FIELDS,
}: {
  filters: NumericFilter[];
  onChange: (f: NumericFilter[]) => void;
  /** Which columns the rules can target. Defaults to the ad-grain list;
   *  the rollup passes its own, since half the ad fields do not exist at
   *  entity level and a rule on a missing field silently matches
   *  nothing. */
  fields?: { key: string; label: string }[];
}) {
  function update(idx: number, patch: Partial<NumericFilter>) {
    onChange(filters.map((f, i) => (i === idx ? { ...f, ...patch } : f)));
  }
  return (
    <div className="flex flex-col gap-2">
      {filters.map((nf, idx) => (
        <div key={idx} className="flex items-center gap-1 rounded-md border border-border-primary p-1.5">
          <select value={nf.field} onChange={(e) => update(idx, { field: e.target.value })} className="rounded border px-1 py-0.5 text-xs">
            {fields.map((f) => (
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
          <button onClick={() => onChange(filters.filter((_, i) => i !== idx))} className="rounded px-1 text-error-text hover:bg-error-bg">
            ✕
          </button>
        </div>
      ))}
      <button
        onClick={() =>
          // Seed with a field the CALLER offers. "spend" exists in both
          // lists today, but a hardcoded default would produce a silent
          // no-op rule the moment a caller's list drops it.
          onChange([...filters, { field: fields[0]?.key ?? "spend", op: "gte", value: 1000 }])
        }
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
