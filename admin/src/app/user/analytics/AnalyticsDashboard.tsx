"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AdLifecycleRow,
  AdLifecycleSort,
  ApiError,
  ChatMessage,
  fetchAdLifecycle,
  sendChatMessage,
} from "@/lib/api";
import { AssistantMarkdown } from "@/app/assistant/ChatAssistant";

const PAGE_SIZE = 50;

const STATUS_OPTIONS = ["ACTIVE", "PAUSED", "WITH_ISSUES", "ARCHIVED", "DELETED"];

// Fixed order matches the CASE statement in app/services/silver/ad_lifecycle.py
// -- these are the only categories that classification logic can produce.
const CATEGORY_ORDER = [
  "Incremental Winner",
  "Winner",
  "P0 analysis",
  "P1 analysis",
  "P2 analysis",
  "Result Awaited",
  "Discarded",
];

// Legacy's own KPI-tile colors (GUIDEBOOK.md's sidebar-nav section):
// Incremental Winner = dark green, Winner = green, P0 = amber, P1 = muted
// amber, P2 = terracotta, Discarded = red -- mapped onto this project's
// ported status tokens (globals.css, from the legacy dashboard.css).
const CATEGORY_STYLES: Record<string, string> = {
  "Incremental Winner": "bg-success-bg text-success-text",
  Winner: "bg-info-bg text-info-text",
  "P0 analysis": "bg-warning-bg text-warning-text",
  "P1 analysis": "bg-warning-bg text-warning-mid",
  "P2 analysis": "bg-accent-pink-bg text-accent-pink",
  "Result Awaited": "bg-bg-muted text-text-secondary",
  Discarded: "bg-error-bg text-error-text",
};

const SORT_OPTIONS: { value: AdLifecycleSort; label: string }[] = [
  { value: "spend", label: "Spend" },
  { value: "roas", label: "ROAS" },
  { value: "impressions", label: "Impressions" },
  { value: "cost_per_ncp", label: "Cost / NCP" },
  { value: "cost_per_ftewv", label: "Cost / FTEWV" },
];

function formatNumber(n: number | null, opts: Intl.NumberFormatOptions = {}): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString(undefined, opts);
}

const INSIGHTS_PROMPT: ChatMessage = {
  role: "user",
  content:
    "Summarize current ad performance in the ad_lifecycle table: call out the top Incremental Winners, " +
    "any notable Losers or Discarded ads worth reviewing, and any concerning cost trends (cost per NCP, " +
    "cost per FTEWV). Be concise -- a few bullet points, not an essay.",
};

export function AnalyticsDashboard() {
  const [accountName, setAccountName] = useState("");
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<AdLifecycleSort>("spend");

  const [rows, setRows] = useState<AdLifecycleRow[]>([]);
  const [total, setTotal] = useState(0);
  const [categoryCounts, setCategoryCounts] = useState<Record<string, number>>({});
  const [accountOptions, setAccountOptions] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [insights, setInsights] = useState<string | null>(null);
  const [insightsLoading, setInsightsLoading] = useState(false);
  const [insightsError, setInsightsError] = useState<string | null>(null);

  const filters = useMemo(
    () => ({
      account_name: accountName || undefined,
      category: category || undefined,
      ad_effective_status: status || undefined,
      search: search || undefined,
      sort,
    }),
    [accountName, category, status, search, sort],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchAdLifecycle({ ...filters, limit: PAGE_SIZE, offset: 0 })
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setTotal(res.total);
        setCategoryCounts(res.category_counts);
        setAccountOptions((prev) => {
          const next = new Set(prev);
          res.rows.forEach((r) => r.account_name && next.add(r.account_name));
          return next;
        });
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
      const res = await fetchAdLifecycle({ ...filters, limit: PAGE_SIZE, offset: rows.length });
      setRows((prev) => [...prev, ...res.rows]);
      setAccountOptions((prev) => {
        const next = new Set(prev);
        res.rows.forEach((r) => r.account_name && next.add(r.account_name));
        return next;
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load more rows.");
    } finally {
      setLoadingMore(false);
    }
  }

  async function generateInsights() {
    setInsightsLoading(true);
    setInsightsError(null);
    try {
      const res = await sendChatMessage([INSIGHTS_PROMPT]);
      setInsights(res.message);
    } catch (err) {
      setInsightsError(err instanceof ApiError ? err.message : "Could not generate insights.");
    } finally {
      setInsightsLoading(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
        {CATEGORY_ORDER.map((cat) => (
          <button
            key={cat}
            onClick={() => setCategory((prev) => (prev === cat ? "" : cat))}
            className={`rounded-lg border p-3 text-left transition-colors ${
              category === cat ? "border-accent-yellow bg-accent-yellow-bg" : "border-border-primary bg-white hover:bg-bg-surface"
            }`}
          >
            <p className="text-lg font-semibold text-text-primary">
              {(categoryCounts[cat] ?? 0).toLocaleString()}
            </p>
            <p className="mt-0.5 text-[11px] text-text-secondary">{cat}</p>
          </button>
        ))}
      </div>

      {/* AI insights */}
      <div className="rounded-lg border border-border-primary bg-white shadow-sm p-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-text-primary">AI Insights</h2>
          <button
            onClick={generateInsights}
            disabled={insightsLoading}
            className="rounded-md bg-accent-yellow px-3 py-1.5 text-xs font-medium text-text-primary transition-colors hover:bg-accent-yellow-hover disabled:opacity-40"
          >
            {insightsLoading ? "Generating…" : insights ? "Regenerate" : "Generate insights"}
          </button>
        </div>
        {insightsError && <p className="mt-2 text-xs text-error-text">{insightsError}</p>}
        {insights ? (
          <div className="mt-3 text-sm text-text-primary">
            <AssistantMarkdown content={insights} />
          </div>
        ) : (
          !insightsLoading && (
            <p className="mt-2 text-xs text-text-secondary">
              Generate a plain-language summary of current ad performance, powered by the same read-only AI
              assistant.
            </p>
          )
        )}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border-primary bg-white shadow-sm p-3">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search ad name…"
          className="w-56 rounded-md border border-border-primary bg-white px-3 py-1.5 text-sm text-text-primary placeholder:text-text-tertiary focus:border-accent-yellow focus:outline-none"
        />
        <select
          value={accountName}
          onChange={(e) => setAccountName(e.target.value)}
          className="rounded-md border border-border-primary bg-white px-2 py-1.5 text-sm text-text-primary focus:border-accent-yellow focus:outline-none"
        >
          <option value="">All accounts</option>
          {[...accountOptions].sort().map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="rounded-md border border-border-primary bg-white px-2 py-1.5 text-sm text-text-primary focus:border-accent-yellow focus:outline-none"
        >
          <option value="">All categories</option>
          {CATEGORY_ORDER.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="rounded-md border border-border-primary bg-white px-2 py-1.5 text-sm text-text-primary focus:border-accent-yellow focus:outline-none"
        >
          <option value="">All statuses</option>
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as AdLifecycleSort)}
          className="rounded-md border border-border-primary bg-white px-2 py-1.5 text-sm text-text-primary focus:border-accent-yellow focus:outline-none"
        >
          {SORT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              Sort: {o.label}
            </option>
          ))}
        </select>
        <span className="ml-auto text-xs text-text-secondary">{total.toLocaleString()} ads match</span>
      </div>

      {/* Table */}
      {error && (
        <div className="rounded-md border border-error-mid bg-error-bg p-3 text-sm text-error-text">{error}</div>
      )}
      {loading ? (
        <p className="text-sm text-text-secondary">Loading…</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border-primary bg-white shadow-sm">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border-primary text-xs text-text-secondary">
                <th className="px-4 py-2 font-medium">Ad</th>
                <th className="px-4 py-2 font-medium">Account</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Category</th>
                <th className="px-4 py-2 text-right font-medium">Spend</th>
                <th className="px-4 py-2 text-right font-medium">ROAS</th>
                <th className="px-4 py-2 text-right font-medium">Cost/NCP</th>
                <th className="px-4 py-2 text-right font-medium">Cost/FTEWV</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.ad_id} className="border-b border-border-soft hover:bg-bg-surface">
                  <td className="max-w-[260px] truncate px-4 py-2 text-text-primary" title={row.ad_name ?? ""}>
                    {row.ad_name ?? "—"}
                  </td>
                  <td className="px-4 py-2 text-text-secondary">{row.account_name ?? "—"}</td>
                  <td className="px-4 py-2 text-text-secondary">{row.ad_effective_status ?? "—"}</td>
                  <td className="px-4 py-2">
                    <span
                      className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                        CATEGORY_STYLES[row.category ?? ""] ?? "bg-bg-muted text-text-secondary"
                      }`}
                    >
                      {row.category ?? "—"}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-xs text-text-primary">
                    {formatNumber(row.spend, { maximumFractionDigits: 0 })}
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-xs text-text-primary">
                    {formatNumber(row.roas, { maximumFractionDigits: 2 })}
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-xs text-text-primary">
                    {formatNumber(row.cost_per_ncp, { maximumFractionDigits: 1 })}
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-xs text-text-primary">
                    {formatNumber(row.cost_per_ftewv, { maximumFractionDigits: 1 })}
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-6 text-center text-text-secondary">
                    No ads match these filters.
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
