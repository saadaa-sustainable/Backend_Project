"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ApiError,
  CpisMatchedAdRow,
  CpisRow,
  CpisWindow,
  SaturationCurveResponse,
  SaturationYMetric,
  fetchCpis,
  fetchCpisMatchedAds,
  fetchSaturationCurve,
} from "@/lib/api";
import { SaturationCurveChart } from "./charts/SaturationCurveChart";

const PAGE_SIZE = 50;
const WINDOWS: CpisWindow[] = ["1d", "7d", "30d"];
const SATURATION_Y_METRICS: { value: SaturationYMetric; label: string }[] = [
  { value: "ncp_count", label: "NCP" },
  { value: "purchases", label: "Purchases" },
  { value: "ftewv_count", label: "First-time EWV" },
];

function SaturationCurveSection({ masterSkuFilter }: { masterSkuFilter: string | null }) {
  const [yMetric, setYMetric] = useState<SaturationYMetric>("ncp_count");
  const [scopeToSku, setScopeToSku] = useState(false);
  const [data, setData] = useState<SaturationCurveResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const masterSku = scopeToSku ? masterSkuFilter ?? undefined : undefined;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchSaturationCurve({ y_metric: yMetric, master_sku: masterSku })
      .then((res) => !cancelled && setData(res))
      .catch((err: unknown) => !cancelled && setError(err instanceof ApiError ? err.message : "Could not compute the saturation curve."))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [yMetric, masterSku]);

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border-primary bg-white shadow-sm p-4">
      <div>
        <h3 className="text-sm font-medium text-text-primary">Saturation curve</h3>
        <p className="mt-1 text-xs text-text-secondary">
          Real-time fit (log-log regression, computed in Python on every selection) of ad spend vs. conversions
          across {scopeToSku && masterSkuFilter ? `ads matching ${masterSkuFilter}` : "every ad"} — where the curve
          bends down is where more spend stops paying off proportionally.
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
            points={data.points.filter((p) => p.spend > 0 && p.y > 0).map((p) => ({ label: p.ad_name ?? p.ad_id, x: p.spend, y: p.y }))}
            curve={data.fit?.curve_points ?? null}
            xLabel="Ad spend"
            yLabel={data.y_label}
          />
        </>
      ) : null}
    </div>
  );
}

const SORT_OPTIONS: { value: "ad_spend" | "cost_per_ncp" | "cost_per_unit_sold" | "units_sold"; label: string }[] = [
  { value: "ad_spend", label: "Ad spend" },
  { value: "cost_per_ncp", label: "Cost / NCP" },
  { value: "cost_per_unit_sold", label: "Cost / item sold" },
  { value: "units_sold", label: "Units sold" },
];

function formatNumber(n: number | null, opts: Intl.NumberFormatOptions = {}): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString(undefined, opts);
}

function MatchedAdsPanel({ masterSku, onClose }: { masterSku: string; onClose: () => void }) {
  const [ads, setAds] = useState<CpisMatchedAdRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchCpisMatchedAds(masterSku)
      .then((res) => !cancelled && setAds(res.ads))
      .catch((err: unknown) => !cancelled && setError(err instanceof ApiError ? err.message : "Could not load matched ads."))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [masterSku]);

  return (
    <div className="rounded-lg border border-warning-border bg-warning-bg/40 p-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-text-primary">
          Ads matched to <span className="font-mono">{masterSku}</span>
        </h3>
        <button onClick={onClose} className="text-xs text-text-secondary hover:text-text-primary">
          Close ✕
        </button>
      </div>
      <p className="mt-1 text-xs text-text-secondary">
        Every ad whose name contains &quot;{masterSku}&quot; (case-insensitive) — this is how spend/NCP are attributed
        to the SKU. Check here if a total looks off — it may be picking up a coincidental name match.
      </p>
      {error && <p className="mt-2 text-xs text-error-text">{error}</p>}
      {loading ? (
        <p className="mt-2 text-xs text-text-secondary">Loading…</p>
      ) : (
        <div className="mt-2 max-h-72 overflow-y-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-warning-border text-text-secondary">
                <th className="px-3 py-1.5 font-medium">Ad</th>
                <th className="px-3 py-1.5 font-medium">Category</th>
                <th className="px-3 py-1.5 text-right font-medium">Spend</th>
                <th className="px-3 py-1.5 text-right font-medium">NCP</th>
              </tr>
            </thead>
            <tbody>
              {ads.map((ad) => (
                <tr key={ad.ad_id} className="border-b border-warning-border/60">
                  <td className="max-w-[260px] truncate px-3 py-1.5 text-text-primary" title={ad.ad_name ?? ""}>
                    {ad.ad_name ?? "—"}
                  </td>
                  <td className="px-3 py-1.5 text-text-secondary">{ad.category ?? "—"}</td>
                  <td className="px-3 py-1.5 text-right font-mono text-text-primary">
                    {formatNumber(ad.spend, { maximumFractionDigits: 0 })}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono text-text-primary">{formatNumber(ad.ncp_count)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function Cpis() {
  const [window_, setWindow] = useState<CpisWindow>("7d");
  const [search, setSearch] = useState("");
  const [onlyMatched, setOnlyMatched] = useState(true);
  const [sort, setSort] = useState<"ad_spend" | "cost_per_ncp" | "cost_per_unit_sold" | "units_sold">("ad_spend");
  const [selectedSku, setSelectedSku] = useState<string | null>(null);

  const [rows, setRows] = useState<CpisRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const filters = useMemo(
    () => ({ window: window_, search: search || undefined, only_matched: onlyMatched, sort }),
    [window_, search, onlyMatched, sort],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchCpis({ ...filters, limit: PAGE_SIZE, offset: 0 })
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setTotal(res.total);
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
      const res = await fetchCpis({ ...filters, limit: PAGE_SIZE, offset: rows.length });
      setRows((prev) => [...prev, ...res.rows]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load more rows.");
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-text-secondary">
        Cost per master SKU (women=SD, men=SM, unisex=SU prefix), ported from the legacy dashboard&apos;s CPIS
        section. Legacy&apos;s own <code className="text-xs">cpis</code> formula was never actually finished there
        (always written as a placeholder) — this shows what it shipped instead (<strong>cost / NCP</strong>) plus the
        literal cost-per-item-sold formula legacy left undone. <strong>Units sold is a real {window_} window</strong>{" "}
        (daily inventory data); <strong>ad spend and NCP are lifetime totals</strong> for matched ads — this project
        doesn&apos;t have day-by-day ad spend yet, so they can&apos;t be windowed the same way. Click a row to see
        exactly which ads were matched to that SKU.
      </p>

      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border-primary bg-white shadow-sm p-3">
        <div className="flex overflow-hidden rounded-md border border-border-primary">
          {WINDOWS.map((w) => (
            <button
              key={w}
              onClick={() => setWindow(w)}
              className={`px-3 py-1.5 text-sm font-medium transition-colors ${
                window_ === w ? "bg-accent-yellow text-text-primary" : "bg-white text-text-secondary hover:bg-bg-surface"
              }`}
            >
              {w}
            </button>
          ))}
        </div>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search master SKU…"
          className="w-48 rounded-md border border-border-primary bg-white px-3 py-1.5 text-sm text-text-primary placeholder:text-text-tertiary focus:border-accent-yellow focus:outline-none"
        />
        <label className="flex items-center gap-1.5 text-sm text-text-primary">
          <input type="checkbox" checked={onlyMatched} onChange={(e) => setOnlyMatched(e.target.checked)} />
          Only SKUs with matched ads
        </label>
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as typeof sort)}
          className="rounded-md border border-border-primary bg-white px-2 py-1.5 text-sm text-text-primary focus:border-accent-yellow focus:outline-none"
        >
          {SORT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              Sort: {o.label}
            </option>
          ))}
        </select>
        <span className="ml-auto text-xs text-text-secondary">{total.toLocaleString()} SKUs match</span>
      </div>

      {error && <div className="rounded-md border border-error-mid bg-error-bg p-3 text-sm text-error-text">{error}</div>}
      {loading ? (
        <p className="text-sm text-text-secondary">Loading…</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border-primary bg-white shadow-sm">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border-primary text-xs text-text-secondary">
                <th className="px-4 py-2 font-medium">Master SKU</th>
                <th className="px-4 py-2 text-right font-medium">Units sold ({window_})</th>
                <th className="px-4 py-2 text-right font-medium">Matched ads</th>
                <th className="px-4 py-2 text-right font-medium">Ad spend (lifetime)</th>
                <th className="px-4 py-2 text-right font-medium">NCP (lifetime)</th>
                <th className="px-4 py-2 text-right font-medium">Cost / NCP</th>
                <th className="px-4 py-2 text-right font-medium">Cost / item sold</th>
                <th className="px-4 py-2 text-right font-medium">Sell-through</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <>
                  <tr
                    key={row.master_sku}
                    onClick={() => setSelectedSku((prev) => (prev === row.master_sku ? null : row.master_sku))}
                    className="cursor-pointer border-b border-border-soft hover:bg-bg-surface"
                  >
                    <td className="px-4 py-2 font-mono text-text-primary">{row.master_sku}</td>
                    <td className="px-4 py-2 text-right font-mono text-xs text-text-primary">
                      {formatNumber(row.units_sold)}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs text-text-primary">
                      {formatNumber(row.matched_ad_count)}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs text-text-primary">
                      {formatNumber(row.ad_spend, { maximumFractionDigits: 0 })}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs text-text-primary">
                      {formatNumber(row.ncp_count)}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs text-text-primary">
                      {formatNumber(row.cost_per_ncp, { maximumFractionDigits: 2 })}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs text-text-primary">
                      {formatNumber(row.cost_per_unit_sold, { maximumFractionDigits: 2 })}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs text-text-primary">
                      {row.avg_sell_through_rate !== null
                        ? `${(row.avg_sell_through_rate * 100).toFixed(1)}%`
                        : "—"}
                    </td>
                  </tr>
                  {selectedSku === row.master_sku && (
                    <tr key={`${row.master_sku}-panel`}>
                      <td colSpan={8} className="px-4 py-3">
                        <MatchedAdsPanel masterSku={row.master_sku} onClose={() => setSelectedSku(null)} />
                      </td>
                    </tr>
                  )}
                </>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-6 text-center text-text-secondary">
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

      <SaturationCurveSection masterSkuFilter={selectedSku} />
    </div>
  );
}
