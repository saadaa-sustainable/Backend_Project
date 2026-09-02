"use client";

/**
 * Untested Assets — three media types side-by-side under one tab:
 *
 *   * Video       -> content_asset_register    (ad_id IS NULL)
 *   * Graphic     -> content_graphic_register  (computed_is_tested = false)
 *   * Influencer  -> content_influencer_posts  (computed_is_tested = false)
 *
 * The backend returns a normalized row shape across all three so this
 * single component renders all of them, with a few column tweaks per
 * media (title col label; thumbnail col only for influencer; SKU
 * enrichment for video + graphic only — influencer nomenclature carries
 * no SKU code).
 *
 * SKU mapping: `candidate_master_sku` is derived per-media on the
 * backend; `matched_master_sku` is populated only when that prefix
 * exists in cpis_by_sku_utm (30d). The three metric columns show that
 * SKU's recent orders / spend / cost-per-order so merchants can
 * prioritise concepts for SKUs already selling.
 *
 * Data source: three tables mirrored one-shot from the legacy CTD
 * dashboard (scripts/migrate_asset_register_from_ctd.py). Re-run that
 * script to refresh.
 */

import { useEffect, useMemo, useState } from "react";
import {
  ApiError,
  UntestedAssetRow,
  UntestedAssetsResponse,
  UntestedMedia,
  fetchUntestedAssets,
} from "@/lib/api";

type SkuFilter = "all" | "matched" | "unmatched";

const MEDIA_TABS: { value: UntestedMedia; label: string; desc: string }[] = [
  { value: "video", label: "Video", desc: "content_asset_register — briefed videos never run in a Meta ad" },
  { value: "graphic", label: "Graphic", desc: "content_graphic_register — static / carousel graphics never tested" },
  { value: "influencer", label: "Influencer", desc: "content_influencer_posts — creator posts not yet whitelisted into an ad" },
];

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
  const [media, setMedia] = useState<UntestedMedia>("video");
  const [data, setData] = useState<UntestedAssetsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [skuFilter, setSkuFilter] = useState<SkuFilter>("all");
  const [kindFilter, setKindFilter] = useState<string>("all");
  const [search, setSearch] = useState<string>("");

  // Refetch whenever the media tab changes. The row shape is the same
  // across all three -- just different populated fields.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setData(null);
    fetchUntestedAssets({ media })
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
  }, [media]);

  // Reset kind filter when switching media (kinds are per-media).
  useEffect(() => {
    setKindFilter("all");
  }, [media]);

  const kinds = useMemo(() => {
    if (!data) return [] as string[];
    const s = new Set<string>();
    for (const r of data.rows) if (r.kind) s.add(r.kind);
    return Array.from(s).sort();
  }, [data]);

  const filteredRows = useMemo(() => {
    if (!data) return [] as UntestedAssetRow[];
    const q = search.trim().toLowerCase();
    return data.rows.filter((r) => {
      if (media !== "influencer") {
        if (skuFilter === "matched" && !r.matched_master_sku) return false;
        if (skuFilter === "unmatched" && r.matched_master_sku) return false;
      }
      if (kindFilter !== "all" && r.kind !== kindFilter) return false;
      if (!q) return true;
      const hay = [r.id, r.title, r.nomenclature, r.candidate_master_sku, r.matched_master_sku, r.sub_kind]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }, [data, media, skuFilter, kindFilter, search]);

  // Per-media column labels. Kept in one place so it's obvious which
  // source column each header maps to.
  const titleColLabel = media === "influencer" ? "Username" : media === "graphic" ? "Product (SKU tag)" : "—";
  const kindColLabel = media === "video" ? "Asset Type" : media === "graphic" ? "Graphic Type" : "Content Type";
  const subKindColLabel = media === "video" ? "Category" : media === "graphic" ? "Audience" : "Deliverable";
  const showThumbnail = media === "influencer";
  const showSkuColumns = media !== "influencer";

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h2 className="text-lg font-semibold text-text-primary">Untested Assets</h2>
        <p className="text-sm text-text-secondary">
          Assets briefed &amp; produced but never run in a Meta ad. Mapped to master SKUs via
          the planning-nomenclature prefix; SKU-side 30d metrics show how each mapped SKU is
          currently selling. Switch media below.
        </p>
      </div>

      {/* Media tab strip */}
      <div className="flex flex-wrap items-end gap-1 border-b border-border-primary">
        {MEDIA_TABS.map((t) => {
          const active = media === t.value;
          return (
            <button
              key={t.value}
              onClick={() => setMedia(t.value)}
              className={`relative px-3 pb-2 pt-1 text-[13px] font-medium transition-colors ${
                active ? "text-text-primary" : "text-text-secondary hover:text-text-primary"
              }`}
              title={t.desc}
            >
              {t.label}
              {active && (
                <span className="absolute inset-x-2 -bottom-px h-[2px] rounded-full bg-accent-yellow" />
              )}
            </button>
          );
        })}
      </div>

      {/* KPI tiles */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <KpiTile
          label="Total untested"
          value={data ? fmtInt(data.total_rows) : "—"}
          hint={loading ? "Loading…" : MEDIA_TABS.find((t) => t.value === media)?.desc}
        />
        {showSkuColumns ? (
          <>
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
          </>
        ) : (
          <KpiTile
            label="Note"
            value="No SKU mapping"
            hint="Influencer nomenclature (SIF-…) doesn't carry a product SKU code"
          />
        )}
      </div>

      {/* Filter row */}
      <div className="flex flex-wrap items-center gap-3 rounded-md border border-border-primary bg-surface-secondary px-3 py-2">
        {showSkuColumns && (
          <>
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
          </>
        )}

        <label className={`text-xs font-medium text-text-secondary ${showSkuColumns ? "ml-2" : ""}`}>
          {kindColLabel}:
        </label>
        <select
          value={kindFilter}
          onChange={(e) => setKindFilter(e.target.value)}
          className="rounded border border-border-primary bg-surface-primary px-2 py-1 text-xs text-text-primary"
        >
          <option value="all">All</option>
          {kinds.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>

        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search id / title / nomenclature / SKU…"
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
              {showThumbnail && <Th>Thumb</Th>}
              <Th>ID</Th>
              {titleColLabel !== "—" && <Th>{titleColLabel}</Th>}
              <Th>{kindColLabel}</Th>
              <Th>{subKindColLabel}</Th>
              <Th>Nomenclature</Th>
              {showSkuColumns && (
                <>
                  <Th>Candidate SKU</Th>
                  <Th>Matched SKU</Th>
                  <Th align="right">SKU Orders (30d)</Th>
                  <Th align="right">SKU Spend (30d)</Th>
                  <Th align="right">SKU CPO (30d)</Th>
                </>
              )}
              <Th>Produced</Th>
              <Th>Link</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-primary bg-surface-primary">
            {loading && (
              <tr>
                <td colSpan={20} className="px-3 py-6 text-center text-text-secondary">
                  Loading…
                </td>
              </tr>
            )}
            {!loading && filteredRows.length === 0 && (
              <tr>
                <td colSpan={20} className="px-3 py-6 text-center text-text-secondary">
                  No untested {media} assets match the current filters.
                </td>
              </tr>
            )}
            {!loading &&
              filteredRows.map((r) => (
                <tr key={`${r.media}:${r.id}`} className="hover:bg-surface-secondary">
                  {showThumbnail && (
                    <Td>
                      {r.thumbnail ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={r.thumbnail}
                          alt=""
                          className="h-10 w-10 rounded object-cover"
                          loading="lazy"
                        />
                      ) : (
                        <div className="h-10 w-10 rounded bg-surface-tertiary" />
                      )}
                    </Td>
                  )}
                  <Td className="font-mono">{r.id}</Td>
                  {titleColLabel !== "—" && <Td>{r.title ?? "—"}</Td>}
                  <Td>{r.kind ?? "—"}</Td>
                  <Td>{r.sub_kind ?? "—"}</Td>
                  <Td className="font-mono text-text-secondary">{r.nomenclature ?? "—"}</Td>
                  {showSkuColumns && (
                    <>
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
                    </>
                  )}
                  <Td>{fmtDate(r.date_produced)}</Td>
                  <Td>
                    {r.link ? (
                      <a
                        href={r.link}
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
        Showing {filteredRows.length} of {data?.total_rows ?? 0} untested {media} assets.
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
