"use client";

/**
 * AdsAnalyseCharts — the analytical view kwikengage's Marketing
 * Insights section anchors on. Three charts in a 3-col grid:
 *
 *   1. Spend by category (horizontal bar, category-colored)
 *      Answers "where is the money going" at a glance without needing
 *      to open the table.
 *   2. Top 10 ads by spend (horizontal bar list)
 *      The single most-asked question in Creative Testing surfaced as
 *      a chart instead of a sortable table row.
 *   3. Category share (donut)
 *      What proportion of the ad roster is Winners vs Discarded vs P0/P1/P2 --
 *      matches kwikengage's Channel Wise Performance donut.
 *
 * Every chart is computed CLIENT-SIDE from the already-loaded rows so
 * changing the F1..F4 thresholds re-renders instantly without a
 * network round trip -- same pattern the KPI category tiles use.
 */

import { useMemo } from "react";
import { AdsAnalyseRow } from "@/lib/api";

interface CatRow {
  row: AdsAnalyseRow;
  cat: string;
}

interface Props {
  rows: CatRow[];
}

// Kwikengage-style hex hues per category (same palette as the tiles).
const CAT_COLOR: Record<string, string> = {
  "Incremental Winner": "#10b981",
  "Winner": "#059669",
  "P0 analysis": "#f59e0b",
  "P1 analysis": "#3b82f6",
  "P2 analysis": "#8b5cf6",
  "Result Awaited": "#94a3b8",
  "Discarded": "#ef4444",
};

const CAT_ORDER = [
  "Incremental Winner",
  "Winner",
  "P0 analysis",
  "P1 analysis",
  "P2 analysis",
  "Result Awaited",
  "Discarded",
] as const;

function fmt(n: number) {
  const abs = Math.abs(n);
  if (abs >= 1e7) return `₹${(n / 1e7).toFixed(1)}Cr`;
  if (abs >= 1e5) return `₹${(n / 1e5).toFixed(1)}L`;
  if (abs >= 1e3) return `₹${(n / 1e3).toFixed(1)}K`;
  return `₹${Math.round(n).toLocaleString()}`;
}

export function AdsAnalyseCharts({ rows }: Props) {
  const { catSpend, catCount, topAds, totalSpend } = useMemo(() => {
    const catSpend = new Map<string, number>();
    const catCount = new Map<string, number>();
    rows.forEach((rc) => {
      const spend = rc.row.spend ?? 0;
      catSpend.set(rc.cat, (catSpend.get(rc.cat) ?? 0) + spend);
      catCount.set(rc.cat, (catCount.get(rc.cat) ?? 0) + 1);
    });
    const topAds = [...rows]
      .sort((a, b) => (b.row.spend ?? 0) - (a.row.spend ?? 0))
      .slice(0, 10);
    const totalSpend = [...catSpend.values()].reduce((a, b) => a + b, 0);
    return { catSpend, catCount, topAds, totalSpend };
  }, [rows]);

  if (rows.length === 0) {
    return null; // nothing to visualise
  }

  return (
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
      <SpendByCategoryChart catSpend={catSpend} totalSpend={totalSpend} />
      <CategoryShareDonut catCount={catCount} />
      <TopAdsChart topAds={topAds} />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// Chart 1: Spend by category (horizontal bars)
// ─────────────────────────────────────────────────────────────────

function SpendByCategoryChart({
  catSpend,
  totalSpend,
}: {
  catSpend: Map<string, number>;
  totalSpend: number;
}) {
  const rows = CAT_ORDER.map((c) => ({
    cat: c,
    spend: catSpend.get(c) ?? 0,
  }));
  const max = Math.max(1, ...rows.map((r) => r.spend));

  return (
    <ChartCard title="Spend by category" subtitle={`${fmt(totalSpend)} total`}>
      <div className="flex flex-col gap-1.5">
        {rows.map((r) => {
          const pct = totalSpend > 0 ? (r.spend / totalSpend) * 100 : 0;
          const barPct = (r.spend / max) * 100;
          return (
            <div key={r.cat} className="flex items-center gap-2 text-xs">
              <div className="w-28 truncate text-text-secondary" title={r.cat}>
                {r.cat}
              </div>
              <div className="relative h-4 flex-1 overflow-hidden rounded bg-slate-100">
                <div
                  className="h-full rounded transition-all"
                  style={{ width: `${barPct}%`, background: CAT_COLOR[r.cat] }}
                />
              </div>
              <div className="w-16 text-right font-mono text-[10px] text-text-primary">
                {fmt(r.spend)}
              </div>
              <div className="w-10 text-right font-mono text-[10px] text-text-tertiary">
                {pct.toFixed(1)}%
              </div>
            </div>
          );
        })}
      </div>
    </ChartCard>
  );
}

// ─────────────────────────────────────────────────────────────────
// Chart 2: Category share (donut)
// ─────────────────────────────────────────────────────────────────

function CategoryShareDonut({ catCount }: { catCount: Map<string, number> }) {
  const total = [...catCount.values()].reduce((a, b) => a + b, 0);
  const segments = CAT_ORDER.map((c) => ({
    cat: c,
    count: catCount.get(c) ?? 0,
  })).filter((s) => s.count > 0);

  // SVG donut: 200x200 viewbox, ring stroke 34
  const CX = 100, CY = 100, R = 66, STROKE = 34;
  const circumference = 2 * Math.PI * R;
  let offset = 0;

  return (
    <ChartCard title="Category share" subtitle={`${total.toLocaleString()} ads`}>
      <div className="flex items-center gap-3">
        <svg viewBox="0 0 200 200" className="h-40 w-40 flex-shrink-0">
          <circle cx={CX} cy={CY} r={R} fill="none" stroke="#f1f5f9" strokeWidth={STROKE} />
          {segments.map((s) => {
            const frac = s.count / total;
            const arcLen = frac * circumference;
            const dash = `${arcLen} ${circumference - arcLen}`;
            const el = (
              <circle
                key={s.cat}
                cx={CX}
                cy={CY}
                r={R}
                fill="none"
                stroke={CAT_COLOR[s.cat]}
                strokeWidth={STROKE}
                strokeDasharray={dash}
                strokeDashoffset={-offset}
                transform="rotate(-90 100 100)"
              >
                <title>{s.cat}: {s.count.toLocaleString()} ({(frac * 100).toFixed(1)}%)</title>
              </circle>
            );
            offset += arcLen;
            return el;
          })}
          <text x={CX} y={CY - 6} textAnchor="middle" className="fill-slate-900 font-semibold text-2xl">
            {total.toLocaleString()}
          </text>
          <text x={CX} y={CY + 14} textAnchor="middle" className="fill-slate-500 text-[10px]">
            ads
          </text>
        </svg>
        <div className="flex flex-1 flex-col gap-0.5 text-xs">
          {segments.map((s) => (
            <div key={s.cat} className="flex items-center gap-1.5">
              <span
                className="h-2.5 w-2.5 flex-shrink-0 rounded-sm"
                style={{ background: CAT_COLOR[s.cat] }}
              />
              <span className="flex-1 truncate text-text-secondary">{s.cat}</span>
              <span className="font-mono text-[10px] text-text-primary">
                {s.count.toLocaleString()}
              </span>
              <span className="w-9 text-right font-mono text-[10px] text-text-tertiary">
                {((s.count / total) * 100).toFixed(1)}%
              </span>
            </div>
          ))}
        </div>
      </div>
    </ChartCard>
  );
}

// ─────────────────────────────────────────────────────────────────
// Chart 3: Top 10 ads by spend
// ─────────────────────────────────────────────────────────────────

function TopAdsChart({ topAds }: { topAds: CatRow[] }) {
  const max = Math.max(1, ...topAds.map((rc) => rc.row.spend ?? 0));
  return (
    <ChartCard title="Top 10 ads by spend" subtitle={`out of ${topAds.length > 0 ? "all filtered" : "0"}`}>
      <div className="flex flex-col gap-1">
        {topAds.map((rc, i) => {
          const spend = rc.row.spend ?? 0;
          const bar = (spend / max) * 100;
          return (
            <div key={rc.row.ad_id} className="flex items-center gap-2 text-xs">
              <div className="w-4 text-right font-mono text-[10px] text-text-tertiary">
                {i + 1}
              </div>
              <div
                className="w-40 truncate text-text-primary"
                title={rc.row.ad_name ?? rc.row.ad_id}
              >
                {rc.row.ad_name ?? rc.row.ad_id.slice(0, 20)}
              </div>
              <div className="relative h-4 flex-1 overflow-hidden rounded bg-slate-100">
                <div
                  className="h-full rounded transition-all"
                  style={{
                    width: `${bar}%`,
                    background: CAT_COLOR[rc.cat] ?? "#64748b",
                  }}
                />
              </div>
              <div className="w-14 text-right font-mono text-[10px] text-text-primary">
                {fmt(spend)}
              </div>
            </div>
          );
        })}
        {topAds.length === 0 && (
          <p className="text-center text-xs text-text-tertiary">No ads to rank.</p>
        )}
      </div>
    </ChartCard>
  );
}

// ─────────────────────────────────────────────────────────────────
// Shared card wrapper
// ─────────────────────────────────────────────────────────────────

function ChartCard({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-border-primary bg-white p-3 shadow-sm">
      <div className="mb-2 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-text-primary">{title}</h3>
        {subtitle && (
          <span className="text-[10px] text-text-tertiary">{subtitle}</span>
        )}
      </div>
      {children}
    </div>
  );
}
