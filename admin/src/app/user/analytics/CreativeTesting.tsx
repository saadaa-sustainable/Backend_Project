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
import { KwikTile } from "./KwikTile";
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
const CAT_ICON: Record<CategoryKey, string> = {
  "Incremental Winner": "★", Winner: "★", "P0 analysis": "◆",
  "P1 analysis": "▲", "P2 analysis": "▲", "Result Awaited": "⌛", Discarded: "✕",
};
const CAT_ICON_COLOR: Record<CategoryKey, "emerald" | "amber" | "sky" | "slate" | "rose"> = {
  "Incremental Winner": "emerald", Winner: "emerald", "P0 analysis": "amber",
  "P1 analysis": "sky", "P2 analysis": "sky", "Result Awaited": "slate", Discarded: "rose",
};

const DATE_PRESETS: { key: string; label: string; days: number | null }[] = [
  { key: "7d", label: "Last 7 days", days: 6 },
  { key: "14d", label: "Last 14 days", days: 13 },
  { key: "30d", label: "Last 30 days", days: 29 },
  { key: "60d", label: "Last 60 days", days: 59 },
  { key: "90d", label: "Last 90 days", days: 89 },
  { key: "custom", label: "Custom…", days: null },
];

const today = () => new Date().toISOString().slice(0, 10);
const daysAgo = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
};

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

export function CreativeTesting() {
  const [preset, setPreset] = useState("30d");
  const [fromDate, setFromDate] = useState(daysAgo(29));
  const [toDate, setToDate] = useState(today());
  const [account, setAccount] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<CategoryKey | "">("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<"spend" | "meta_roas" | "cost_per_ncp" | "cost_per_ftewv">("spend");

  const [rows, setRows] = useState<AdsAnalyseRow[]>([]);
  const [total, setTotal] = useState(0);
  const [totals, setTotals] = useState<AdsAnalyseTotals | null>(null);
  const [categoryCounts, setCategoryCounts] = useState<Record<string, number>>({});
  const [accountOptions, setAccountOptions] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const filters = useMemo(
    () => ({
      account_name: account || undefined,
      search: search || undefined,
      category: categoryFilter || undefined,
      from_date: fromDate,
      to_date: toDate,
      date_field: "created" as const,
      sort,
    }),
    [account, search, categoryFilter, fromDate, toDate, sort],
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
    if (p && p.days !== null) {
      setFromDate(daysAgo(p.days));
      setToDate(today());
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Header + date range picker */}
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h2 className="text-base font-semibold text-text-primary">Creative Testing</h2>
          <p className="text-xs text-text-secondary">
            Ads launched in the picked window — evaluate recently-shipped creatives before they age into the wider Ads Analyse view.
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <select
            value={preset}
            onChange={(e) => applyPreset(e.target.value)}
            className="rounded-md border border-border-primary bg-white px-2 py-1 text-sm"
          >
            {DATE_PRESETS.map((p) => (
              <option key={p.key} value={p.key}>{p.label}</option>
            ))}
          </select>
          <input
            type="date"
            value={fromDate}
            onChange={(e) => { setFromDate(e.target.value); setPreset("custom"); }}
            className="rounded-md border border-border-primary bg-white px-2 py-1 text-sm"
          />
          <span className="text-xs text-text-secondary">→</span>
          <input
            type="date"
            value={toDate}
            onChange={(e) => { setToDate(e.target.value); setPreset("custom"); }}
            className="rounded-md border border-border-primary bg-white px-2 py-1 text-sm"
          />
        </div>
      </div>

      {/* Aggregate KPI strip — original Creative Testing metrics */}
      {totals && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
          <KwikTile
            icon={<span className="text-base">◱</span>} iconColor="slate"
            label="Ads launched" value={totals.ad_count.toLocaleString()}
            subLine={`in ${DATE_PRESETS.find((p) => p.key === preset)?.label ?? "custom range"}`}
          />
          <KwikTile
            icon={<span className="text-base">₹</span>} iconColor="sky"
            label="Total spend" value={fmtMoney(totals.spend)}
          />
          <KwikTile
            icon={<span className="text-base">🛒</span>} iconColor="emerald"
            label="Purchases" value={fmtCompact(totals.purchases)}
          />
          <KwikTile
            icon={<span className="text-base">👥</span>} iconColor="emerald"
            label="NCP" value={fmtCompact(totals.ncp_count)}
            subLine="new-customer purchases"
          />
          <KwikTile
            icon={<span className="text-base">⚡</span>} iconColor="teal"
            label="FTEWV" value={fmtCompact(totals.ftewv_count)}
            subLine="first-time engaged"
          />
          <KwikTile
            icon={<span className="text-base">✦</span>} iconColor="amber"
            label="Avg ROAS"
            value={totals.avg_meta_roas !== null ? totals.avg_meta_roas.toFixed(2) : "—"}
          />
          <KwikTile
            icon={<span className="text-base">💰</span>} iconColor="rose"
            label="Cost / NCP"
            value={totals.ncp_count > 0 ? "₹" + fmtCompact(totals.spend / totals.ncp_count) : "—"}
          />
          <KwikTile
            icon={<span className="text-base">💸</span>} iconColor="rose"
            label="Cost / FTEWV"
            value={totals.ftewv_count > 0 ? "₹" + fmtCompact(totals.spend / totals.ftewv_count) : "—"}
          />
        </div>
      )}

      {/* Category tiles — click to filter */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
        {CATEGORY_ORDER.map((cat) => {
          const count = categoryCounts[cat] ?? 0;
          const selected = categoryFilter === cat;
          return (
            <KwikTile
              key={cat}
              icon={<span className="text-base">{CAT_ICON[cat]}</span>}
              iconColor={CAT_ICON_COLOR[cat]}
              label={cat}
              value={count.toLocaleString()}
              active={selected}
              onClick={() => setCategoryFilter(selected ? "" : cat)}
            />
          );
        })}
      </div>

      {/* Filter row */}
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border-primary bg-white p-2 shadow-sm">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search ad name…"
          className="w-64 rounded-md border border-border-primary px-2 py-1 text-sm"
        />
        <select
          value={account}
          onChange={(e) => setAccount(e.target.value)}
          className="rounded-md border border-border-primary bg-white px-2 py-1 text-sm"
        >
          <option value="">All accounts</option>
          {[...accountOptions].sort().map((a) => (
            <option key={a} value={a}>{a}</option>
          ))}
        </select>
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as typeof sort)}
          className="rounded-md border border-border-primary bg-white px-2 py-1 text-sm"
        >
          <option value="spend">Sort: Spend</option>
          <option value="meta_roas">Sort: ROAS</option>
          <option value="cost_per_ncp">Sort: Cost / NCP</option>
          <option value="cost_per_ftewv">Sort: Cost / FTEWV</option>
        </select>
        <button
          onClick={() => { setSearch(""); setAccount(""); setCategoryFilter(""); }}
          className="rounded-md border border-border-primary bg-white px-2 py-1 text-xs hover:bg-bg-muted"
        >
          Clear filters
        </button>
        <span className="ml-auto text-xs text-text-secondary">
          {loading ? "loading…" : `${rows.length.toLocaleString()} of ${total.toLocaleString()} ads`}
        </span>
        <ExportButton
          rows={rows as unknown as Record<string, unknown>[]}
          filename="creative_testing"
          window={preset}
          disabled={loading || !rows.length}
        />
      </div>

      {error && <div className="rounded-md border border-error-mid bg-error-bg p-2 text-sm text-error-text">{error}</div>}

      {/* Slim table -- Creative Testing focus columns only */}
      {loading ? (
        <p className="text-sm text-text-secondary">Loading…</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border-primary bg-white shadow-sm">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-border-primary text-[11px] text-text-secondary">
                <th className="px-3 py-2 font-medium">Ad</th>
                <th className="px-3 py-2 font-medium">Account</th>
                <th className="px-3 py-2 font-medium">Created</th>
                <th className="px-3 py-2 font-medium">Category</th>
                <th className="px-3 py-2 font-medium">F1234</th>
                <th className="px-3 py-2 text-right font-medium">Spend</th>
                <th className="px-3 py-2 text-right font-medium">ROAS</th>
                <th className="px-3 py-2 text-right font-medium">Purchases</th>
                <th className="px-3 py-2 text-right font-medium">NCP</th>
                <th className="px-3 py-2 text-right font-medium">Cost / NCP</th>
                <th className="px-3 py-2 text-right font-medium">Cost / FTEWV</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const cat = (r.category ?? "Discarded") as CategoryKey;
                return (
                  <tr key={r.ad_id} className="border-b border-border-soft hover:bg-bg-surface">
                    <td className="max-w-[260px] truncate px-3 py-1.5 text-text-primary" title={r.ad_name ?? ""}>
                      {r.ad_name ?? "—"}
                    </td>
                    <td className="px-3 py-1.5 text-text-secondary">{r.account_name ?? "—"}</td>
                    <td className="px-3 py-1.5 font-mono text-[11px] text-text-secondary">{r.ad_created_date ?? "—"}</td>
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
                    <td className="px-3 py-1.5 text-right font-mono">{fmtMoney(r.spend)}</td>
                    <td className="px-3 py-1.5 text-right font-mono">{fmtNum(r.meta_roas ?? r.roas)}</td>
                    <td className="px-3 py-1.5 text-right font-mono">{fmtCompact(r.purchases)}</td>
                    <td className="px-3 py-1.5 text-right font-mono">{fmtCompact(r.ncp_count)}</td>
                    <td className="px-3 py-1.5 text-right font-mono">{fmtMoney(r.cost_per_ncp)}</td>
                    <td className="px-3 py-1.5 text-right font-mono">{fmtMoney(r.cost_per_ftewv)}</td>
                  </tr>
                );
              })}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={11} className="px-4 py-6 text-center text-text-secondary">
                    No ads created in this window. Try widening the date range.
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
                className="rounded-md bg-bg-muted px-4 py-1.5 text-xs font-medium text-text-primary hover:bg-bg-muted disabled:opacity-40"
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
