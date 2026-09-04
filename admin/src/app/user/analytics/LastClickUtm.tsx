"use client";

/**
 * Last Click UTM (a.k.a. Ad Intelligence) — CTD-structure port.
 *
 * Layout follows CTD dashboard.js:1499-1868 (index_v2.html view-ai + JS):
 *   1. Header row — title, date range picker (Last 30d default), "Only
 *      matched" / "Only unmatched" toggles, Export CSV.
 *   2. 10 channel tiles (Total + 9 channels) with click-to-filter +
 *      click-again-to-drill-down. Selected tile expands the utm_source
 *      breakdown row.
 *   3. Channel drill-down row (only when a channel is selected) — top-N
 *      utm_source × count × sales for the picked channel.
 *   4. Tier KPI cards (Backend_Project's 6 tiers: ad_direct, ad_name_match,
 *      adset_scoped, adset_only, campaign_only, unmatched) — styled with
 *      CTD's colour intent (ad_direct → green, adset → blue, weaker →
 *      amber, unmatched → gray). Click a tier card to filter.
 *   5. Filter row — utm_source (multi-select popover), utm_medium,
 *      tier, utm_campaign / content / term / matched_value (all with
 *      IN/EX comma syntax matching CTD's pill mechanic).
 *   6. Order table — 15 sortable columns matching CTD's Ad Intelligence
 *      table exactly (index_v2.html:1835-1862).
 *   7. Footer — pagination + cascade counts + CSV export.
 *
 * CTD's IN/EX pill mechanic (dashboard.js:4937) is expressed here as
 * comma-separated terms in a single text field where a leading "!"
 * excludes. E.g. `sale, !flash` means "contains sale AND NOT contains
 * flash". The backend parses this via _parse_text_filter in
 * analytics.py.
 */

import { useEffect, useMemo, useState } from "react";
import {
  ApiError,
  ChannelSummary,
  LastClickUtmParams,
  SourceBreakdown,
  UtmChannel,
  UtmOrderRow,
  fetchLastClickUtm,
} from "@/lib/api";
import { KwikTile } from "./KwikTile";
import { TableSkeleton } from "./TableSkeleton";
import { ExportButton } from "@/components/ExportButton";

// ─────────────────────────────────────────────────────────────────────
// Channel + tier catalog
// ─────────────────────────────────────────────────────────────────────

const CHANNEL_ORDER: UtmChannel[] = [
  "Meta",
  "Google",
  "Organic (IG)",
  "Retention",
  "Brand Collab",
  "AI",
  "Organic (Direct)",
  "Loyalty",
  "Other",
];

const CHANNEL_CLASS: Record<UtmChannel, string> = {
  Meta: "ai-ch-meta",
  Google: "ai-ch-google",
  "Organic (IG)": "ai-ch-ig",
  Retention: "ai-ch-retention",
  "Brand Collab": "ai-ch-collab",
  AI: "ai-ch-ai",
  "Organic (Direct)": "ai-ch-direct",
  Loyalty: "ai-ch-loyalty",
  Other: "ai-ch-other",
};

// KwikTile icon-square colour per channel (matches kwikengage's
// coloured icon container -- meta blue, google green, retention
// purple, etc.). Icons are unicode glyphs so no external dep.
const CHANNEL_ICON_COLOR: Record<UtmChannel | "Total", "slate" | "sky" | "emerald" | "amber" | "rose" | "purple" | "teal"> = {
  Total: "slate",
  Meta: "sky",
  Google: "emerald",
  "Organic (IG)": "rose",
  Retention: "purple",
  "Brand Collab": "amber",
  AI: "teal",
  "Organic (Direct)": "teal",
  Loyalty: "rose",
  Other: "slate",
};
const CHANNEL_ICON: Record<UtmChannel | "Total", string> = {
  Total: "Σ",
  Meta: "M",
  Google: "G",
  "Organic (IG)": "IG",
  Retention: "R",
  "Brand Collab": "B",
  AI: "AI",
  "Organic (Direct)": "D",
  Loyalty: "L",
  Other: "?",
};

/** Backend's tier values (verified live 2026-08-29 in shopify_order_attribution).
 * Order matches attribution strength: strongest first, unmatched last. */
const TIER_ORDER = [
  "ad_direct",
  "ad_name_match",
  "adset_scoped",
  "adset_only",
  "campaign_only",
  "unmatched",
] as const;
type TierKey = (typeof TIER_ORDER)[number];

const TIER_LABEL: Record<TierKey, string> = {
  ad_direct: "Ad Direct",
  ad_name_match: "Ad Name Match",
  adset_scoped: "Adset Scoped",
  adset_only: "Adset Only",
  campaign_only: "Campaign Only",
  unmatched: "Unmatched",
};

const TIER_CLASS: Record<TierKey, string> = {
  ad_direct: "ai-tier-ad_direct",
  ad_name_match: "ai-tier-ad_name_match",
  adset_scoped: "ai-tier-adset_scoped",
  adset_only: "ai-tier-adset_only",
  campaign_only: "ai-tier-campaign_only",
  unmatched: "ai-tier-unmatched",
};

// ─────────────────────────────────────────────────────────────────────
// Formatters
// ─────────────────────────────────────────────────────────────────────

const fmtInt = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : n.toLocaleString();
const fmtRs = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : `₹${Math.round(n).toLocaleString()}`;
const fmtDT = (s: string | null | undefined) => {
  if (!s) return "—";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return s.slice(0, 16);
  return d.toISOString().slice(0, 16).replace("T", " ");
};

/** CTD strips "gid://shopify/Order/" from the Shopify GID for display. */
const stripOrderGid = (id: string) => id.replace(/^gid:\/\/shopify\/Order\//, "");
const stripCustomerGid = (id: string | null) =>
  id ? id.replace(/^gid:\/\/shopify\/Customer\//, "") : "";

const daysAgoDate = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
};
const today = () => new Date().toISOString().slice(0, 10);

// ─────────────────────────────────────────────────────────────────────
// Date range presets (from CTD dashboard.js:4569-4577)
// ─────────────────────────────────────────────────────────────────────

const DATE_PRESETS: { key: string; label: string; range: () => { from: string; to: string } }[] = [
  { key: "today", label: "Today", range: () => ({ from: today(), to: today() }) },
  { key: "yesterday", label: "Yesterday", range: () => ({ from: daysAgoDate(1), to: daysAgoDate(1) }) },
  { key: "7d", label: "Last 7 Days", range: () => ({ from: daysAgoDate(6), to: today() }) },
  { key: "15d", label: "Last 15 Days", range: () => ({ from: daysAgoDate(14), to: today() }) },
  { key: "30d", label: "Last 30 Days", range: () => ({ from: daysAgoDate(29), to: today() }) },
  { key: "90d", label: "Last 90 Days", range: () => ({ from: daysAgoDate(89), to: today() }) },
  {
    key: "mtd",
    label: "This Month",
    range: () => {
      const now = new Date();
      const start = new Date(now.getFullYear(), now.getMonth(), 1);
      return { from: start.toISOString().slice(0, 10), to: today() };
    },
  },
  {
    key: "last_month",
    label: "Last Month",
    range: () => {
      const now = new Date();
      const start = new Date(now.getFullYear(), now.getMonth() - 1, 1);
      const end = new Date(now.getFullYear(), now.getMonth(), 0);
      return { from: start.toISOString().slice(0, 10), to: end.toISOString().slice(0, 10) };
    },
  },
];

// ─────────────────────────────────────────────────────────────────────
// 15-column table config — CTD index_v2.html:1835-1862
// ─────────────────────────────────────────────────────────────────────

type ColKind = "text" | "num" | "money" | "date" | "tier" | "id" | "status";
interface ColDef {
  key: string;
  header: string;
  kind: ColKind;
  extract: (r: UtmOrderRow) => unknown;
  render: (r: UtmOrderRow) => React.ReactNode;
}

const COLS: ColDef[] = [
  {
    key: "created_at",
    header: "Order Date",
    kind: "date",
    extract: (r) => r.created_at,
    render: (r) => <span className="font-mono text-[11px]">{fmtDT(r.created_at)}</span>,
  },
  {
    key: "order_id",
    header: "Order ID",
    kind: "id",
    extract: (r) => r.order_id,
    render: (r) => <span className="font-mono text-[11px]">{stripOrderGid(r.order_id)}</span>,
  },
  {
    key: "customer_id",
    header: "Customer ID",
    kind: "id",
    extract: (r) => r.customer_id,
    render: (r) => (
      <span className="font-mono text-[11px]" title={r.contact_email ?? undefined}>
        {stripCustomerGid(r.customer_id) || "—"}
      </span>
    ),
  },
  {
    key: "customer_num_orders",
    header: "Orders",
    kind: "num",
    extract: (r) => r.customer_num_orders,
    render: (r) => <span className="num">{fmtInt(r.customer_num_orders)}</span>,
  },
  {
    key: "total_price",
    header: "Total ₹",
    kind: "money",
    extract: (r) => r.total_price,
    render: (r) => <span className="num">{fmtRs(r.total_price)}</span>,
  },
  {
    key: "tier",
    header: "Tier",
    kind: "tier",
    extract: (r) => r.tier,
    render: (r) => {
      const t = (r.tier ?? "unmatched") as TierKey;
      const cls = TIER_CLASS[t] ?? "ai-tier-none";
      const label = TIER_LABEL[t] ?? r.tier ?? "—";
      return <span className={`ai-tier ${cls}`}>{label}</span>;
    },
  },
  { key: "utm_source", header: "utm_source", kind: "text", extract: (r) => r.utm_source, render: (r) => <span>{r.utm_source ?? "—"}</span> },
  { key: "utm_medium", header: "utm_medium", kind: "text", extract: (r) => r.utm_medium, render: (r) => <span>{r.utm_medium ?? "—"}</span> },
  {
    key: "utm_campaign",
    header: "utm_campaign",
    kind: "text",
    extract: (r) => r.utm_campaign,
    render: (r) => (
      <span className="max-w-[200px] truncate inline-block" title={r.utm_campaign ?? ""}>
        {r.utm_campaign ?? "—"}
      </span>
    ),
  },
  {
    key: "utm_content",
    header: "utm_content",
    kind: "text",
    extract: (r) => r.utm_content,
    render: (r) => (
      <span className="max-w-[200px] truncate inline-block" title={r.utm_content ?? ""}>
        {r.utm_content ?? "—"}
      </span>
    ),
  },
  {
    key: "utm_term",
    header: "utm_term",
    kind: "text",
    extract: (r) => r.utm_term,
    render: (r) => (
      <span className="max-w-[160px] truncate inline-block" title={r.utm_term ?? ""}>
        {r.utm_term ?? "—"}
      </span>
    ),
  },
  {
    key: "matched_ad_id",
    header: "Ad ID",
    kind: "id",
    extract: (r) => r.matched_ad_id,
    render: (r) => <span className="font-mono text-[11px]">{r.matched_ad_id ?? "—"}</span>,
  },
  {
    key: "matched_adset_id",
    header: "Adset ID",
    kind: "id",
    extract: (r) => r.matched_adset_id,
    render: (r) => <span className="font-mono text-[11px]">{r.matched_adset_id ?? "—"}</span>,
  },
  {
    key: "matched_ad_name",
    header: "Ad Name",
    kind: "text",
    extract: (r) => r.matched_ad_name,
    render: (r) => (
      <span className="max-w-[420px] truncate inline-block" title={r.matched_ad_name ?? ""}>
        {r.matched_ad_name ?? "—"}
      </span>
    ),
  },
  {
    key: "matched_campaign_name",
    header: "Campaign",
    kind: "text",
    extract: (r) => r.matched_campaign_name,
    render: (r) => (
      <span className="max-w-[280px] truncate inline-block" title={r.matched_campaign_name ?? ""}>
        {r.matched_campaign_name ?? "—"}
      </span>
    ),
  },
];

// ─────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────

const PAGE_SIZE = 100;
const BATCH_SIZE = 1000;

export function LastClickUtm() {
  // Data
  const [rows, setRows] = useState<UtmOrderRow[]>([]);
  const [total, setTotal] = useState(0);
  const [channelCounts, setChannelCounts] = useState<Record<UtmChannel, ChannelSummary> | null>(null);
  const [tierCounts, setTierCounts] = useState<Record<string, number>>({});
  const [channelSources, setChannelSources] = useState<Record<UtmChannel, SourceBreakdown[]> | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const initial = DATE_PRESETS.find((p) => p.key === "30d")!.range();
  const [fromDate, setFromDate] = useState(initial.from);
  const [toDate, setToDate] = useState(initial.to);
  const [preset, setPreset] = useState<string>("30d");
  const [channel, setChannel] = useState<UtmChannel | "">("");
  const [drillOpen, setDrillOpen] = useState(false);
  const [tier, setTier] = useState<TierKey | "">("");
  const [utmSources, setUtmSources] = useState<Set<string>>(new Set()); // multi-select
  const [utmSourcePickerOpen, setUtmSourcePickerOpen] = useState(false);
  const [utmSourceSearch, setUtmSourceSearch] = useState("");
  const [utmMedium, setUtmMedium] = useState("");
  const [utmCampaign, setUtmCampaign] = useState("");
  const [utmContent, setUtmContent] = useState("");
  const [utmTerm, setUtmTerm] = useState("");
  const [matchedValue, setMatchedValue] = useState("");
  const [onlyMatched, setOnlyMatched] = useState(false);
  const [onlyUnmatched, setOnlyUnmatched] = useState(false);
  const [search, setSearch] = useState("");

  // Table state
  const [sortKey, setSortKey] = useState<string>("created_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(0);

  // Discovered options
  const [mediumOptions, setMediumOptions] = useState<Set<string>>(new Set());
  const [sourceOptions, setSourceOptions] = useState<Set<string>>(new Set());

  const filters: LastClickUtmParams = useMemo(
    () => ({
      channel: channel || undefined,
      tier: tier || undefined,
      utm_source: utmSources.size > 0 ? [...utmSources].join(",") : undefined,
      utm_medium: utmMedium || undefined,
      utm_campaign: utmCampaign || undefined,
      utm_content: utmContent || undefined,
      utm_term: utmTerm || undefined,
      matched_value: matchedValue || undefined,
      only_matched: onlyMatched || undefined,
      only_unmatched: onlyUnmatched || undefined,
      search: search || undefined,
      from_date: fromDate,
      to_date: toDate,
      sort: sortKey === "total_price" ? "total_price" : sortKey === "customer_num_orders" ? "customer_num_orders" : "created_at",
    }),
    [channel, tier, utmSources, utmMedium, utmCampaign, utmContent, utmTerm, matchedValue, onlyMatched, onlyUnmatched, search, fromDate, toDate, sortKey],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchLastClickUtm({ ...filters, limit: BATCH_SIZE, offset: 0 })
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setTotal(res.total);
        setChannelCounts(res.channel_counts);
        setTierCounts(res.tier_counts);
        setChannelSources(res.channel_sources);
        setPage(0);
        // Discover filter options from the response
        setMediumOptions((prev) => {
          const next = new Set(prev);
          res.rows.forEach((r) => r.utm_medium && next.add(r.utm_medium));
          return next;
        });
        setSourceOptions((prev) => {
          const next = new Set(prev);
          res.rows.forEach((r) => r.utm_source && next.add(r.utm_source));
          return next;
        });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Could not reach the FastAPI backend.");
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [filters]);

  async function loadMore() {
    setLoadingMore(true);
    try {
      const res = await fetchLastClickUtm({ ...filters, limit: BATCH_SIZE, offset: rows.length });
      setRows((prev) => [...prev, ...res.rows]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load more rows.");
    } finally {
      setLoadingMore(false);
    }
  }

  function applyPreset(key: string) {
    const p = DATE_PRESETS.find((x) => x.key === key);
    if (!p) return;
    const r = p.range();
    setFromDate(r.from);
    setToDate(r.to);
    setPreset(key);
  }

  function clearFilters() {
    setChannel("");
    setDrillOpen(false);
    setTier("");
    setUtmSources(new Set());
    setUtmMedium("");
    setUtmCampaign("");
    setUtmContent("");
    setUtmTerm("");
    setMatchedValue("");
    setOnlyMatched(false);
    setOnlyUnmatched(false);
    setSearch("");
  }

  function toggleSort(k: string) {
    if (sortKey === k) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(k);
      setSortDir("desc");
    }
  }

  // Client-side sort on already-fetched batch
  const sorted = useMemo(() => {
    const col = COLS.find((c) => c.key === sortKey);
    if (!col) return rows;
    const dir = sortDir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const av = col.extract(a);
      const bv = col.extract(b);
      const aNull = av === null || av === undefined || av === "";
      const bNull = bv === null || bv === undefined || bv === "";
      if (aNull && bNull) return 0;
      if (aNull) return 1;
      if (bNull) return -1;
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
      return String(av).localeCompare(String(bv)) * dir;
    });
  }, [rows, sortKey, sortDir]);

  const pageRows = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));

  // Total tile aggregates
  const totalOrders = channelCounts ? Object.values(channelCounts).reduce((a, s) => a + s.count, 0) : 0;
  const totalSales = channelCounts ? Object.values(channelCounts).reduce((a, s) => a + s.sales, 0) : 0;

  function exportCsv() {
    const cols = COLS.filter((c) => c.key !== "customer_num_orders"); // include everything
    const headers = ["Order Date", "Order ID", "Customer ID", "Contact Email", "Orders", "Total", "Tier", "Channel", "Has Match", "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "Ad ID", "Adset ID", "Ad Name", "Campaign"];
    const lines = [headers.join(",")];
    sorted.forEach((r) => {
      const csv = [
        r.created_at ?? "",
        stripOrderGid(r.order_id),
        stripCustomerGid(r.customer_id),
        r.contact_email ?? "",
        String(r.customer_num_orders ?? ""),
        String(r.total_price ?? ""),
        r.tier ?? "",
        r.channel,
        String(r.has_match),
        r.utm_source ?? "",
        r.utm_medium ?? "",
        r.utm_campaign ?? "",
        r.utm_content ?? "",
        r.utm_term ?? "",
        r.matched_ad_id ?? "",
        r.matched_adset_id ?? "",
        r.matched_ad_name ?? "",
        r.matched_campaign_name ?? "",
      ].map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",");
      lines.push(csv);
    });
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `ad_intelligence_${today()}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
    void cols; // silence unused
    void headers; // (kept for readability of the mapping)
  }

  return (
    <div className="flex flex-col gap-3">
      {/* ═══════════════════════════════════════════════════════════════
          Header row — title + date range + toggles + export
         ═══════════════════════════════════════════════════════════════ */}
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h2 className="text-base font-semibold">Last Click UTM analysis</h2>
          <p className="text-xs text-text-secondary">step-wise UTM matches from shopify_order_attribution ({total.toLocaleString()} orders in range)</p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <select
            value={preset}
            onChange={(e) => applyPreset(e.target.value)}
            className="rounded-md border border-border-primary bg-white px-2 py-1 text-sm"
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
            onChange={(e) => { setFromDate(e.target.value); setPreset("custom"); }}
            className="rounded-md border border-border-primary px-2 py-1 text-sm"
          />
          <span className="text-text-secondary">→</span>
          <input
            type="date"
            value={toDate}
            onChange={(e) => { setToDate(e.target.value); setPreset("custom"); }}
            className="rounded-md border border-border-primary px-2 py-1 text-sm"
          />
          <button
            onClick={exportCsv}
            className="rounded-md border border-border-primary bg-white px-2 py-1 text-xs hover:bg-bg-muted"
          >
            Export CSV
          </button>
          <ExportButton
            rows={sorted as unknown as Record<string, unknown>[]}
            filename="last_click_utm"
            window={preset}
            disabled={loading || !sorted.length}
          />
        </div>
      </div>

      {/* ═══════════════════════════════════════════════════════════════
          Channel tiles — kwikengage-style, 2 rows of 5 instead of one
          cramped row of 10 (2026-08-29). At sm/md breakpoints wraps to
          2 rows of 5; at lg+ stays 2 rows of 5 (never a single-line 10
          which is unreadable on any typical screen). Total is the
          first tile; the 9 channels follow in size order (Meta first).
         ═══════════════════════════════════════════════════════════════ */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-5">
        <KwikTile
          icon={<span className="text-sm font-bold">{CHANNEL_ICON.Total}</span>}
          iconColor={CHANNEL_ICON_COLOR.Total}
          label="Total Orders"
          value={totalOrders.toLocaleString()}
          subLine={fmtRs(totalSales)}
          active={channel === ""}
          onClick={() => { setChannel(""); setDrillOpen(false); }}
        />
        {CHANNEL_ORDER.map((ch) => {
          const s = channelCounts?.[ch] ?? { count: 0, sales: 0 };
          const selected = channel === ch;
          const sharePct = totalOrders > 0 ? (s.count / totalOrders) * 100 : 0;
          return (
            <KwikTile
              key={ch}
              icon={<span className="text-xs font-bold">{CHANNEL_ICON[ch]}</span>}
              iconColor={CHANNEL_ICON_COLOR[ch]}
              label={ch}
              value={s.count.toLocaleString()}
              subLine={`${fmtRs(s.sales)} · ${sharePct.toFixed(1)}%`}
              active={selected}
              onClick={() => {
                if (selected) {
                  setDrillOpen((d) => !d);
                } else {
                  setChannel(ch);
                  setDrillOpen(true);
                }
              }}
            />
          );
        })}
      </div>

      {/* Channel drill-down -- compact, capped height so it doesn't
          push the order table below the fold when Meta (which has
          20+ utm_source variants) is selected. Sticky header + inner
          scroll after the first ~6 rows. */}
      {drillOpen && channel && channelSources && (
        <div className="rounded-lg border border-border-primary bg-white p-3 shadow-sm">
          <div className="mb-2 flex items-center justify-between">
            <h4 className="text-sm font-semibold">
              {channel} · utm_source breakdown
              <span className="ml-2 text-xs font-normal text-text-tertiary">
                ({(channelSources[channel]?.length ?? 0)} sources)
              </span>
            </h4>
            <button
              onClick={() => setDrillOpen(false)}
              className="text-xs text-text-secondary hover:text-text-primary"
            >
              Close ✕
            </button>
          </div>
          <div className="max-h-52 overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-white text-text-secondary">
                <tr>
                  <th className="py-1 text-left font-medium">utm_source</th>
                  <th className="py-1 text-right font-medium">Orders</th>
                  <th className="py-1 text-right font-medium">Sales</th>
                  <th className="py-1 text-right font-medium">Share</th>
                </tr>
              </thead>
              <tbody>
                {channelSources[channel]?.map((sb) => (
                  <tr
                    key={sb.utm_source ?? "(none)"}
                    className="cursor-pointer border-t border-border-soft hover:bg-bg-surface"
                    onClick={() => {
                      if (!sb.utm_source) return;
                      setUtmSources(new Set([sb.utm_source]));
                    }}
                  >
                    <td className="py-1 font-mono">{sb.utm_source ?? "(none)"}</td>
                    <td className="py-1 text-right font-mono">{sb.count.toLocaleString()}</td>
                    <td className="py-1 text-right font-mono">{fmtRs(sb.sales)}</td>
                    <td className="py-1 text-right font-mono text-text-tertiary">
                      {((sb.count / (channelCounts?.[channel]?.count || 1)) * 100).toFixed(1)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════════
          Compact tier chip strip -- 6 rounded chips inline. Replaces
          the previous 6 KPI cards which took a lot of vertical space
          for what's really just a click-to-filter control. Selected
          chip gets a dark ring so the filter state is obvious.
         ═══════════════════════════════════════════════════════════════ */}
      <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-border-primary bg-white p-2 shadow-sm">
        <span className="text-xs font-medium text-text-secondary">Tiers:</span>
        {TIER_ORDER.map((t) => {
          const count = tierCounts[t] ?? 0;
          const selected = tier === t;
          return (
            <button
              key={t}
              onClick={() => setTier(selected ? "" : t)}
              className={
                `inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs transition-all ` +
                (selected
                  ? "border-slate-900 bg-slate-900 text-white"
                  : "border-border-primary bg-white hover:border-slate-400")
              }
            >
              <span>{TIER_LABEL[t]}</span>
              <span className={"font-mono " + (selected ? "text-white/90" : "text-text-secondary")}>
                {count.toLocaleString()}
              </span>
            </button>
          );
        })}
      </div>

      {/* ═══════════════════════════════════════════════════════════════
          Simplified filter row -- primary controls only. All the
          niche text filters (utm_campaign / content / term /
          matched_value) and matched/unmatched toggles are moved into
          the Advanced filters popover so the row doesn't wrap into
          three lines on typical screens (2026-08-29 declutter pass).
         ═══════════════════════════════════════════════════════════════ */}
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border-primary bg-white p-2 shadow-sm">
        <div className="relative">
          <button
            onClick={() => setUtmSourcePickerOpen((v) => !v)}
            className="rounded-md border border-border-primary bg-white px-2 py-1 text-sm hover:bg-bg-muted"
          >
            utm_source: {utmSources.size === 0 ? "All" : `${utmSources.size} selected`}
          </button>
          {utmSourcePickerOpen && (
            <div
              onClick={(e) => e.stopPropagation()}
              className="absolute left-0 top-full z-30 mt-1 w-72 max-h-80 overflow-auto rounded-lg border border-border-primary bg-white p-2 shadow-lg"
            >
              <input
                value={utmSourceSearch}
                onChange={(e) => setUtmSourceSearch(e.target.value)}
                placeholder="Search sources…"
                className="mb-1 w-full rounded border border-border-primary px-2 py-1 text-xs"
              />
              <div className="mb-1 flex gap-1 text-xs">
                <button onClick={() => setUtmSources(new Set())} className="rounded border px-2 py-0.5 hover:bg-bg-muted">
                  Clear
                </button>
                <button
                  onClick={() => {
                    const next = new Set(utmSources);
                    [...sourceOptions].filter((s) => s.toLowerCase().includes(utmSourceSearch.toLowerCase())).forEach((s) => next.add(s));
                    setUtmSources(next);
                  }}
                  className="rounded border px-2 py-0.5 hover:bg-bg-muted"
                >
                  All (filtered)
                </button>
              </div>
              {[...sourceOptions]
                .filter((s) => s.toLowerCase().includes(utmSourceSearch.toLowerCase()))
                .sort()
                .map((s) => (
                  <label key={s} className="flex items-center gap-2 py-0.5 text-xs">
                    <input
                      type="checkbox"
                      checked={utmSources.has(s)}
                      onChange={(e) => {
                        const next = new Set(utmSources);
                        if (e.target.checked) next.add(s);
                        else next.delete(s);
                        setUtmSources(next);
                      }}
                    />
                    <span>{s}</span>
                  </label>
                ))}
            </div>
          )}
        </div>
        <select
          value={utmMedium}
          onChange={(e) => setUtmMedium(e.target.value)}
          className="rounded-md border border-border-primary px-2 py-1 text-sm"
        >
          <option value="">utm_medium: All</option>
          {[...mediumOptions].sort().map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search order name…"
          className="w-48 rounded-md border border-border-primary px-2 py-1 text-sm"
        />
        <AdvancedFiltersButton
          utmCampaign={utmCampaign} setUtmCampaign={setUtmCampaign}
          utmContent={utmContent} setUtmContent={setUtmContent}
          utmTerm={utmTerm} setUtmTerm={setUtmTerm}
          matchedValue={matchedValue} setMatchedValue={setMatchedValue}
          onlyMatched={onlyMatched} setOnlyMatched={setOnlyMatched}
          onlyUnmatched={onlyUnmatched} setOnlyUnmatched={setOnlyUnmatched}
        />
        <button
          onClick={clearFilters}
          className="ml-auto rounded-md border border-border-primary bg-white px-2 py-1 text-xs hover:bg-bg-muted"
        >
          Clear Filters
        </button>
      </div>

      {/* Error */}
      {error && <div className="rounded-md border border-error-mid bg-error-bg p-2 text-sm text-error-text">{error}</div>}

      {/* ═══════════════════════════════════════════════════════════════
          15-column order table
         ═══════════════════════════════════════════════════════════════ */}
      {loading ? (
        <TableSkeleton rows={12} columns={10} showKpis />
      ) : (
        <div className="max-h-[70vh] overflow-auto rounded-lg border border-border-primary bg-white shadow-sm">
          <table className="ae-table w-full text-left text-xs">
            <thead>
              <tr className="border-b border-border-primary text-[11px] text-text-secondary">
                {COLS.map((c) => (
                  <th
                    key={c.key}
                    onClick={() => toggleSort(c.key)}
                    className={
                      "cursor-pointer px-2 py-2 font-medium hover:bg-bg-muted " +
                      (c.kind === "num" || c.kind === "money" ? "text-right" : "")
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
              {pageRows.map((r) => (
                <tr key={r.order_id} className="border-b border-border-soft hover:bg-bg-surface">
                  {COLS.map((c) => (
                    <td key={c.key} className="px-2 py-1">
                      {c.render(r)}
                    </td>
                  ))}
                </tr>
              ))}
              {pageRows.length === 0 && (
                <tr>
                  <td colSpan={COLS.length} className="px-4 py-6 text-center text-text-secondary">
                    No orders match these filters in the selected date range.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════════
          Footer — pagination + cascade + fetch-more
         ═══════════════════════════════════════════════════════════════ */}
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border-primary bg-white px-3 py-1.5 text-xs text-text-secondary shadow-sm">
        <span>
          fetched <strong className="text-text-primary">{rows.length.toLocaleString()}</strong>
          {" → "}
          shown <strong className="text-text-primary">{pageRows.length.toLocaleString()}</strong>
          {" of "}
          <strong className="text-text-primary">{sorted.length.toLocaleString()}</strong>
          {" · total in range "}
          <strong className="text-text-primary">{total.toLocaleString()}</strong>
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
            {loadingMore ? "Fetching…" : `Fetch next 1000 (${rows.length}/${total})`}
          </button>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// TextFilter — CTD's IN/EX pill pattern condensed into one input
// ─────────────────────────────────────────────────────────────────────

function TextFilter({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder: string }) {
  return (
    <div className="flex items-center gap-1">
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-md border border-border-primary px-2 py-1 text-sm"
        title="Comma-separated. Prefix a term with ! to exclude. Example:  sale, !flash"
      />
      {value.split(",").map((t) => t.trim()).filter(Boolean).map((t, i) => (
        <span
          key={i}
          className={`inline-flex items-center rounded px-1 py-0.5 text-[10px] ${t.startsWith("!") ? "ai-ex-pill" : "ai-in-pill"}`}
        >
          {t.startsWith("!") ? `EX ${t.slice(1)}` : `IN ${t}`}
        </span>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// AdvancedFiltersButton — popover containing the niche text filters
// that used to clutter the main filter row.
// ─────────────────────────────────────────────────────────────────────

interface AdvancedFiltersButtonProps {
  utmCampaign: string; setUtmCampaign: (v: string) => void;
  utmContent: string; setUtmContent: (v: string) => void;
  utmTerm: string; setUtmTerm: (v: string) => void;
  matchedValue: string; setMatchedValue: (v: string) => void;
  onlyMatched: boolean; setOnlyMatched: (v: boolean) => void;
  onlyUnmatched: boolean; setOnlyUnmatched: (v: boolean) => void;
}

function AdvancedFiltersButton(p: AdvancedFiltersButtonProps) {
  const [open, setOpen] = useState(false);
  const activeCount =
    (p.utmCampaign ? 1 : 0) +
    (p.utmContent ? 1 : 0) +
    (p.utmTerm ? 1 : 0) +
    (p.matchedValue ? 1 : 0) +
    (p.onlyMatched ? 1 : 0) +
    (p.onlyUnmatched ? 1 : 0);
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className={
          "flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs transition-colors " +
          (activeCount > 0
            ? "border-amber-300 bg-amber-50 text-amber-900 hover:bg-amber-100"
            : "border-border-primary bg-white text-text-primary hover:bg-bg-muted")
        }
      >
        <span>Advanced filters</span>
        {activeCount > 0 && (
          <span className="rounded-full bg-amber-200 px-1.5 py-0.5 text-[9px] font-semibold">
            {activeCount}
          </span>
        )}
        <span className="text-text-tertiary">{open ? "▴" : "▾"}</span>
      </button>
      {open && (
        <div
          onClick={(e) => e.stopPropagation()}
          className="absolute right-0 top-full z-30 mt-1 w-96 rounded-lg border border-border-primary bg-white p-3 shadow-lg"
        >
          <h4 className="mb-2 text-sm font-semibold">Advanced filters</h4>
          <p className="mb-2 text-[10px] text-text-tertiary">
            Comma-separated terms in each text field. Prefix a term with <code>!</code> to exclude.
            Example: <code>sale, !flash</code>.
          </p>
          <div className="flex flex-col gap-2">
            <div>
              <label className="mb-0.5 block text-[10px] uppercase tracking-wide text-text-secondary">utm_campaign</label>
              <TextFilter value={p.utmCampaign} onChange={p.setUtmCampaign} placeholder="e.g. sale, !flash" />
            </div>
            <div>
              <label className="mb-0.5 block text-[10px] uppercase tracking-wide text-text-secondary">utm_content</label>
              <TextFilter value={p.utmContent} onChange={p.setUtmContent} placeholder="" />
            </div>
            <div>
              <label className="mb-0.5 block text-[10px] uppercase tracking-wide text-text-secondary">utm_term</label>
              <TextFilter value={p.utmTerm} onChange={p.setUtmTerm} placeholder="" />
            </div>
            <div>
              <label className="mb-0.5 block text-[10px] uppercase tracking-wide text-text-secondary">Matched ad name</label>
              <TextFilter value={p.matchedValue} onChange={p.setMatchedValue} placeholder="e.g. SDCP" />
            </div>
            <div className="mt-1 flex gap-3">
              <label className="flex items-center gap-1.5 text-xs">
                <input
                  type="checkbox"
                  checked={p.onlyMatched}
                  onChange={(e) => { p.setOnlyMatched(e.target.checked); if (e.target.checked) p.setOnlyUnmatched(false); }}
                />
                Only matched
              </label>
              <label className="flex items-center gap-1.5 text-xs">
                <input
                  type="checkbox"
                  checked={p.onlyUnmatched}
                  onChange={(e) => { p.setOnlyUnmatched(e.target.checked); if (e.target.checked) p.setOnlyMatched(false); }}
                />
                Only unmatched
              </label>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
