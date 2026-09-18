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
import { ExportButton } from "@/components/ExportButton";

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

/** Rows mounted at once. The influencer backlog is 13,612 assets and
 *  every one of them used to be in the DOM. */
/** What to call each origin, per media. Generic "Live register" /
 *  "Sheet archive" was vague AND, for influencer, wrong: that tab's
 *  historical rows are creatorhub's own historic_posts / cleaned_data
 *  tables, not a spreadsheet. Naming the actual upstream keeps the
 *  distinction honest where the two media differ.
 *
 *  Graphics has one origin (a sheet), so it never renders this toggle. */
const ORIGIN_LABELS: Record<
  UntestedMedia,
  { all: string; database: string; historical: string;
    databaseHint: string; historicalHint: string }
> = {
  video: {
    all: "All video assets",
    database: "From Supabase",
    historical: "Historical · from Sheets",
    databaseHint:
      "Recorded in the Supabase asset-register, which the team maintains today.",
    historicalHint:
      "Iterated video, recorded only in the \u201cIterated Content\u201d Google Sheet from before that register existed.",
  },
  graphic: {
    all: "All graphic assets",
    database: "From Supabase",
    historical: "Historical · from Sheets",
    databaseHint: "No Supabase source — graphics are sheet-only.",
    historicalHint:
      "The Creative Mastersheet (Graphics) Google Sheet — the only source graphics has ever had.",
  },
  influencer: {
    all: "All influencer assets",
    database: "From Supabase · live posts",
    // NOT "from Sheets": influencer history lives in creatorhub too.
    historical: "Historical · creatorhub archive",
    databaseHint:
      "creatorhub public.posts — the live table the team maintains today.",
    historicalHint:
      "creatorhub historic_posts and cleaned_data: the same Supabase project, but its archive tables rather than the live one. No spreadsheet involved.",
  },
};

const PAGE_SIZE = 100;

export function UntestedAssets() {
  const [media, setMedia] = useState<UntestedMedia>("video");
  const [data, setData] = useState<UntestedAssetsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [skuFilter, setSkuFilter] = useState<SkuFilter>("all");
  const [kindFilter, setKindFilter] = useState<string>("all");
  const [search, setSearch] = useState<string>("");
  // Influencer alone returns 13,612 rows, and every one of them was
  // being mounted: the table rendered filteredRows directly. Paging the
  // DOM keeps the export whole (it still reads every filtered row) while
  // the browser only ever holds a screenful.
  const [page, setPage] = useState(0);
  // Assets recorded in a live Supabase register are a workable backlog;
  // assets that only ever existed in a pre-migration Google Sheet are an
  // archive. Mixing them made the video tab read as 779 actionable
  // items when 71 of those are sheet-era rows nobody maintains.
  const [originFilter, setOriginFilter] = useState<"all" | "database" | "historical">("all");
  // Server-side, because "matched" and "all" are different populations
  // rather than a subset of what is already loaded.
  // Defaults to the WHOLE register, not to untested. The Ads column is
  // the point of this table and on an untested-only list every value is
  // 0 by definition -- the filter's own evidence, and nothing else.
  // Untested is one click away and still the headline KPI.
  const [matchState, setMatchState] = useState<"untested" | "matched" | "all">("all");

  // Refetch whenever the media tab changes. The row shape is the same
  // across all three -- just different populated fields.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setData(null);
    fetchUntestedAssets({ media, match_state: matchState })
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
  }, [media, matchState]);

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
      if (originFilter !== "all" && r.origin !== originFilter) return false;
      if (!q) return true;
      const hay = [r.id, r.title, r.nomenclature, r.candidate_master_sku, r.matched_master_sku, r.sub_kind]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }, [data, media, skuFilter, kindFilter, search, originFilter]);

  const pageCount = Math.max(1, Math.ceil(filteredRows.length / PAGE_SIZE));
  // Clamp rather than reset to 0: narrowing a filter while deep in the
  // list should land on the last page that still exists, not silently
  // jump back to the top.
  const safePage = Math.min(page, pageCount - 1);
  const pageStart = safePage * PAGE_SIZE;
  const pageRows = filteredRows.slice(pageStart, pageStart + PAGE_SIZE);
  // No effect to sync `page` back down: safePage already clamps what is
  // rendered, and writing state from an effect just to agree with a
  // value derived in the same render causes a second render for nothing.

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
              onClick={() => {
                // A different media tab is a different list -- start at
                // the top. Done here rather than in an effect so it is
                // one render, not two.
                setMedia(t.value);
                setPage(0);
              }}
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

      {/* KPI tiles. "Untested" on its own has no scale to it -- 543 is
          a third of the graphics register but 3% of the influencer one,
          and those mean very different things. The register total and
          what HAS matched give it a denominator. */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <KpiTile
          label="Never tested"
          value={data ? fmtInt(data.register_total - data.matched_assets) : "—"}
          hint={loading ? "Loading…" : "Asset id appears in no ad name. Counts the whole register, so it does not move when you change the Show filter."}
        />
        <KpiTile
          label="In register"
          value={data ? fmtInt(data.register_total) : "—"}
          hint="Every asset this media type holds"
        />
        <KpiTile
          label="Matched assets"
          value={data ? fmtInt(data.matched_assets) : "—"}
          hint={data && data.register_total
            ? `${Math.round((data.matched_assets / data.register_total) * 100)}% of the register has run at least once`
            : "Assets whose id appears in at least one ad name"}
        />
        <KpiTile
          label="Ads matched"
          value={data ? fmtInt(data.matched_ads) : "—"}
          hint="Ads those matched assets account for"
        />
        {showSkuColumns ? (
          <KpiTile
            label="With catalog SKU"
            value={data ? `${fmtInt(data.with_sku_match)} / ${fmtInt(data.total_rows)}` : "—"}
            hint="Of the rows currently listed, how many have a SKU prefix with a recent CPIS window row"
          />
        ) : (
          <KpiTile
            label="Note"
            value="No SKU mapping"
            hint="Influencer nomenclature (SIF-…) doesn't carry a product SKU code"
          />
        )}
      </div>

      {/* What the tab is listing. Untested is the default and the point
          of the section, but "all" is what makes the Ads column mean
          something -- a column of zeros teaches nothing. */}
      <div className="flex flex-wrap items-center gap-3 rounded-md border border-border-primary bg-bg-surface px-3 py-2">
        <label className="text-xs font-medium text-text-secondary">Show:</label>
        <div className="flex overflow-hidden rounded border border-border-primary">
          {([
            ["all", ORIGIN_LABELS[media].all, "Every asset this media type holds, matched or not."],
            ["untested", "Never tested", "Asset id appears in NO ad name — Ads matched reads 0 for every row, which is the definition."],
            ["matched", "Has run", "Asset id appears in at least one ad name."],
          ] as const).map(([v, label, hint]) => (
            <button
              key={v}
              title={hint}
              onClick={() => {
                setMatchState(v);
                setPage(0);
              }}
              className={
                // accent-yellow is this theme's real accent token (it is
                // blue, #3B6BF5 -- the name is a leftover). `accent-primary`
                // does not exist, so it rendered white-on-transparent and
                // the selected option was invisible.
                "px-3 py-1 text-xs font-medium transition-colors " +
                (matchState === v
                  ? "bg-accent-yellow text-white"
                  : "bg-bg-white text-text-secondary hover:text-text-primary hover:bg-bg-muted")
              }
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Where the record came from. Only worth showing when the tab
          actually has both -- graphics is sheet-only, influencer is
          database-only, and a one-option toggle is just noise. */}
      {data && data.from_database > 0 && data.from_historical > 0 && (
        <div className="flex flex-wrap items-center gap-3 rounded-md border border-border-primary bg-bg-surface px-3 py-2">
          <label className="text-xs font-medium text-text-secondary">Source:</label>
          <div className="flex overflow-hidden rounded border border-border-primary">
            {([
              ["all", `All (${data.total_rows.toLocaleString("en-IN")})`,
               "Every untested asset in this media type, whichever register recorded it."],
              ["database",
               `${ORIGIN_LABELS[media].database} (${data.from_database.toLocaleString("en-IN")})`,
               ORIGIN_LABELS[media].databaseHint],
              ["historical",
               `${ORIGIN_LABELS[media].historical} (${data.from_historical.toLocaleString("en-IN")})`,
               ORIGIN_LABELS[media].historicalHint],
            ] as const).map(([v, label, hint]) => (
              <button
                key={v}
                title={hint}
                onClick={() => {
                  setOriginFilter(v);
                  setPage(0);
                }}
                className={
                  "px-3 py-1 text-xs font-medium transition-colors " +
                  (originFilter === v
                    ? "bg-accent-yellow text-white"
                    : "bg-bg-white text-text-secondary hover:text-text-primary hover:bg-bg-muted")
                }
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Filter row */}
      <div className="flex flex-wrap items-center gap-3 rounded-md border border-border-primary bg-bg-surface px-3 py-2">
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
                      : "bg-bg-white text-text-secondary hover:text-text-primary"
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
          className="rounded border border-border-primary bg-bg-white px-2 py-1 text-xs text-text-primary"
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
          className="ml-auto w-64 rounded border border-border-primary bg-bg-white px-2 py-1 text-xs text-text-primary placeholder:text-text-tertiary"
        />
        <ExportButton
          rows={filteredRows as unknown as Record<string, unknown>[]}
          filename={`untested_${media}`}
          disabled={loading || !filteredRows.length}
        />
      </div>

      {error && (
        <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">
          {error}
        </div>
      )}

      {/* Table. `min-w-full` not `w-full`, with nowrap cells: the table
          sizes to its content and the wrapper scrolls, instead of every
          column being squeezed to fit the viewport. Nomenclature strings
          here run past 60 characters and were wrapping to three lines. */}
      <div className="overflow-x-auto rounded-lg border bg-white shadow-sm border-border-primary">
        <table className="ct-asset-table min-w-full text-xs">
          <thead className="bg-bg-surface text-text-secondary">
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
              <Th align="right">Ads matched</Th>
              <Th>Produced</Th>
              {/* Only when the tab mixes both -- otherwise every row
                  would repeat the same value. */}
              {data && data.from_database > 0 && data.from_historical > 0 && <Th>Source</Th>}
              <Th>Links</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-primary bg-bg-white">
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
              pageRows.map((r) => (
                <tr key={`${r.media}:${r.id}`} className="hover:bg-bg-surface">
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
                        <div className="h-10 w-10 rounded bg-bg-muted" />
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
                  <Td align="right">
                    <span
                      className={
                        "font-mono text-[11px] " +
                        (r.matched_ads > 0 ? "text-text-primary" : "text-text-tertiary")
                      }
                      title={r.matched_ads > 0
                        ? `${r.matched_ads} ad${r.matched_ads === 1 ? "" : "s"} name this asset`
                        : "No ad name carries this asset id — that is what makes it untested"}
                    >
                      {r.matched_ads}
                    </span>
                  </Td>
                  <Td>{fmtDate(r.date_produced)}</Td>
                  {data && data.from_database > 0 && data.from_historical > 0 && (
                    <Td>
                      <span
                        title={r.source_system}
                        className={
                          "whitespace-nowrap rounded border px-1.5 py-0.5 text-[10px] " +
                          (r.origin === "database"
                            ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                            : "border-slate-200 bg-slate-100 text-slate-600")
                        }
                      >
                        {r.origin === "database"
                          ? ORIGIN_LABELS[media].database
                          : ORIGIN_LABELS[media].historical}
                      </span>
                    </Td>
                  )}
                  <Td>
                    {/* Every link the register holds, not just the
                        first. Graphics rows often carry link_1..3 plus a
                        `creative` file, and those are different cuts of
                        the requisition rather than copies of one. */}
                    {r.links?.length ? (
                      <span className="flex flex-wrap gap-1">
                        {r.links.map((l) => (
                          <a
                            key={l.label}
                            href={l.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            title={l.url}
                            className="whitespace-nowrap rounded border border-border-primary px-1.5 py-0.5 text-[10px] text-accent-blue hover:bg-bg-muted"
                          >
                            {l.label} ↗
                          </a>
                        ))}
                      </span>
                    ) : (
                      <span className="text-text-tertiary">—</span>
                    )}
                  </Td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center gap-3 text-[11px] text-text-tertiary">
        <span>
          Showing {filteredRows.length ? pageStart + 1 : 0}–{Math.min(pageStart + PAGE_SIZE, filteredRows.length)}{" "}
          of {filteredRows.length.toLocaleString("en-IN")}{" "}
          {matchState === "untested" ? "never-tested" : matchState === "matched" ? "already-run" : ""} asset
          {filteredRows.length === 1 ? "" : "s"}
          {filteredRows.length !== (data?.total_rows ?? 0) &&
            ` (${(data?.total_rows ?? 0).toLocaleString("en-IN")} untested ${media} assets in total)`}
          .
          {data && ` Computed at ${new Date(data.computed_at).toLocaleString()}.`}
        </span>
        {pageCount > 1 && (
          <span className="ml-auto inline-flex items-center gap-2">
            <button
              onClick={() => setPage((v) => Math.max(0, v - 1))}
              disabled={safePage === 0}
              className="rounded-md border border-border-primary px-2 py-1 disabled:opacity-40"
            >
              ← Prev
            </button>
            <span>
              Page {safePage + 1} of {pageCount.toLocaleString("en-IN")}
            </span>
            <button
              onClick={() => setPage((v) => Math.min(pageCount - 1, v + 1))}
              disabled={safePage >= pageCount - 1}
              className="rounded-md border border-border-primary px-2 py-1 disabled:opacity-40"
            >
              Next →
            </button>
          </span>
        )}
      </div>
    </div>
  );
}

function KpiTile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-md border border-border-primary bg-bg-white px-4 py-3">
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
      className={`whitespace-nowrap px-4 py-2.5 text-left text-[10px] font-semibold uppercase tracking-wider text-text-tertiary ${
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
      className={`px-4 py-2.5 align-middle text-text-primary ${align === "right" ? "text-right" : ""} ${
        className ?? ""
      }`}
    >
      {children}
    </td>
  );
}
