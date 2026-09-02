"use client";

/**
 * Untested Assets — assets briefed & produced (present in
 * content_asset_register) but never run in a Meta ad (ad_id IS NULL).
 *
 * SKU mapping: `candidate_master_sku` is split_part(planning_nomenclature,
 * '_', 1). When that prefix matches a SKU already in cpis_by_sku_utm,
 * `matched_master_sku` is populated + the SKU's 30d attributed orders /
 * spend / cost-per-order are surfaced so merchants can prioritise
 * concepts for SKUs already selling.
 *
 * Data source: public.content_asset_register — mirrored one-shot from
 * the legacy CTD dashboard (scripts/migrate_asset_register_from_ctd.py).
 * Re-run that script to refresh.
 */

import { useEffect, useMemo, useState } from "react";
import {
  ApiError,
  UntestedAssetRow,
  UntestedAssetsResponse,
  fetchUntestedAssets,
} from "@/lib/api";

type SkuFilter = "all" | "matched" | "unmatched";

function fmtInt(n: number | null | undefined) {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString();
}
function fmtCurrency(n: number | null | undefined) {
  if (n === null || n === undefined) return "—";
  return `₹${Math.round(n).toLocaleString()}`;
}
function fmtDate(s: string | null) {
  if (!s) return "—";
  return s.slice(0, 10);
}

export function UntestedAssets() {
  const [data, setData] = useState<UntestedAssetsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [skuFilter, setSkuFilter] = useState<SkuFilter>("all");
  const [assetTypeFilter, setAssetTypeFilter] = useState<string>("all");
  const [search, setSearch] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchUntestedAssets({})
      .then((r) => {
        if (!cancelled) setData(r);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const msg = err instanceof ApiError ? err.message : "Failed to load untested assets";
        setError(msg);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const assetTypes = useMemo(() => {
    if (!data) return [] as string[];
    const s = new Set<string>();
    for (const r of data.rows) if (r.asset_type) s.add(r.asset_type);
    return Array.from(s).sort();
  }, [data]);

  const filteredRows = useMemo(() => {
    if (!data) return [] as UntestedAssetRow[];
    const q = search.trim().toLowerCase();
    return data.rows.filter((r) => {
      if (skuFilter === "matched" && !r.matched_master_sku) return false;
      if (skuFilter === "unmatched" && r.matched_master_sku) return false;
      if (assetTypeFilter !== "all" && r.asset_type !== assetTypeFilter) return false;
      if (!q) return true;
      const hay = [
        r.asset_id,
        r.planning_nomenclature,
        r.candidate_master_sku,
        r.matched_master_sku,
        r.category,
        r.source_parent,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }, [data, skuFilter, assetTypeFilter, search]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h2 className="text-lg font-semibold text-text-primary">Untested Assets</h2>
        <p className="text-sm text-text-secondary">
          Assets briefed & produced but never run in a Meta ad. Mapped to master SKUs via the
          planning-nomenclature prefix; SKU-side 30d metrics show how each mapped SKU is
          currently selling.
        </p>
      </div>

      {/* KPI tiles */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <KpiTile
          label="Total untested"
          value={data ? fmtInt(data.total_rows) : "—"}
          hint={loading ? "Loading…" : "ad_id IS NULL in content_asset_register"}
        />
        <KpiTile
          label="Mapped to catalog SKU"
          value={data ? fmtInt(data.with_sku_match) : "—"}
          hint="SKU prefix has recent CPIS window row"
        />
        <KpiTile
          label="Unmapped"
          value={data ? fmtInt(data.without_sku_match) : "—"}
          hint="No SKU prefix / prefix not in catalog"
        />
      </div>

      {/* Filter row */}
      <div className="flex flex-wrap items-center gap-3 rounded-md border border-border-primary bg-surface-secondary px-3 py-2">
        <label className="text-xs font-medium text-text-secondary">SKU match:</label>
        <div className="flex overflow-hidden rounded border border-border-primary">
          {(["all", "matched", "unmatched"] as SkuFilter[]).map((v) => (
            <button
              key={v}
              onClick={() => setSkuFilter(v)}
              className={`px-3 py-1 text-xs font-medium transition-colors ${
                skuFilter === v
                  ? "bg-accent-yellow text-black"
                  : "bg-surface-primary text-text-secondary hover:text-text-primary"
              }`}
            >
              {v === "all" ? "All" : v === "matched" ? "Matched" : "Unmatched"}
            </button>
          ))}
        </div>

        <label className="ml-2 text-xs font-medium text-text-secondary">Asset type:</label>
        <select
          value={assetTypeFilter}
          onChange={(e) => setAssetTypeFilter(e.target.value)}
          className="rounded border border-border-primary bg-surface-primary px-2 py-1 text-xs text-text-primary"
        >
          <option value="all">All</option>
          {assetTypes.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>

        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search asset id / SKU / planning nomenclature…"
          className="ml-auto w-64 rounded border border-border-primary bg-surface-primary px-2 py-1 text-xs text-text-primary placeholder:text-text-tertiary"
        />
      </div>

      {error && (
        <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">
          {error}
        </div>
      )}

      {/* Table */}
      <div className="overflow-x-auto rounded-md border border-border-primary">
        <table className="min-w-full text-xs">
          <thead className="bg-surface-secondary text-text-secondary">
            <tr>
              <Th>Asset ID</Th>
              <Th>Type</Th>
              <Th>Category</Th>
              <Th>Planning Nomenclature</Th>
              <Th>Candidate SKU</Th>
              <Th>Matched SKU</Th>
              <Th align="right">SKU Orders (30d)</Th>
              <Th align="right">SKU Spend (30d)</Th>
              <Th align="right">SKU CPO (30d)</Th>
              <Th>Produced</Th>
              <Th>Link</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-primary bg-surface-primary">
            {loading && (
              <tr>
                <td colSpan={11} className="px-3 py-6 text-center text-text-secondary">
                  Loading…
                </td>
              </tr>
            )}
            {!loading && filteredRows.length === 0 && (
              <tr>
                <td colSpan={11} className="px-3 py-6 text-center text-text-secondary">
                  No untested assets match the current filters.
                </td>
              </tr>
            )}
            {!loading &&
              filteredRows.map((r) => (
                <tr key={r.asset_id} className="hover:bg-surface-secondary">
                  <Td className="font-mono">{r.asset_id}</Td>
                  <Td>{r.asset_type ?? "—"}</Td>
                  <Td>{r.category ?? "—"}</Td>
                  <Td className="font-mono text-text-secondary">
                    {r.planning_nomenclature ?? "—"}
                  </Td>
                  <Td className="font-mono">{r.candidate_master_sku ?? "—"}</Td>
                  <Td>
                    {r.matched_master_sku ? (
                      <span className="rounded bg-emerald-100 px-1.5 py-0.5 font-mono text-[11px] text-emerald-800">
                        {r.matched_master_sku}
                      </span>
                    ) : (
                      <span className="text-text-tertiary">—</span>
                    )}
                  </Td>
                  <Td align="right">{fmtInt(r.sku_attributed_orders)}</Td>
                  <Td align="right">{fmtCurrency(r.sku_ad_spend)}</Td>
                  <Td align="right">{fmtCurrency(r.sku_cost_per_order)}</Td>
                  <Td>{fmtDate(r.date_of_production)}</Td>
                  <Td>
                    {r.link_to_asset ? (
                      <a
                        href={r.link_to_asset}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-accent-blue underline"
                      >
                        Open
                      </a>
                    ) : (
                      <span className="text-text-tertiary">—</span>
                    )}
                  </Td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>

      <div className="text-[11px] text-text-tertiary">
        Showing {filteredRows.length} of {data?.total_rows ?? 0} untested assets.
        {data && ` Computed at ${new Date(data.computed_at).toLocaleString()}.`}
      </div>
    </div>
  );
}

function KpiTile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-md border border-border-primary bg-surface-primary px-4 py-3">
      <div className="text-xs font-medium uppercase tracking-wide text-text-secondary">
        {label}
      </div>
      <div className="mt-1 text-2xl font-semibold text-text-primary">{value}</div>
      {hint && <div className="mt-0.5 text-[11px] text-text-tertiary">{hint}</div>}
    </div>
  );
}

function Th({ children, align }: { children: React.ReactNode; align?: "right" }) {
  return (
    <th
      className={`px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide ${
        align === "right" ? "text-right" : ""
      }`}
    >
      {children}
    </th>
  );
}

function Td({
  children,
  className,
  align,
}: {
  children: React.ReactNode;
  className?: string;
  align?: "right";
}) {
  return (
    <td
      className={`px-3 py-2 text-text-primary ${align === "right" ? "text-right" : ""} ${
        className ?? ""
      }`}
    >
      {children}
    </td>
  );
}
