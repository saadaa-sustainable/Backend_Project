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
 * exists in cpis_by_sku_utm (30d). Tested assets open the matched-ad
 * drill-down, using the same mapping as the table's ad counts.
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
import { AssetAdsModal } from "./AssetAdsModal";

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
 *  Every media tab exposes the source filter, including empty sources. */
const ORIGIN_LABELS: Record<
  UntestedMedia,
  { all: string; database: string; historical: string;
    databaseHint: string; historicalHint: string }
> = {
  video: {
    all: "All video assets",
    database: "DAM Project",
    historical: "Historical · from Sheets",
    databaseHint:
      "Assets recorded in the DAM Project.",
    historicalHint:
      "Iterated video, recorded only in the \u201cIterated Content\u201d Google Sheet from before that register existed.",
  },
  graphic: {
    all: "All graphic assets",
    database: "DAM Project",
    historical: "Historical · from Sheets",
    databaseHint: "Graphic assets recorded in the DAM Project.",
    historicalHint:
      "The Creative Mastersheet (Graphics) Google Sheet — the only source graphics has ever had.",
  },
  influencer: {
    all: "All influencer assets",
    // Influencer assets live in creatorhub, not the DAM, and the
    // historical label below already said so -- calling the live half
    // "DAM Project" made one register read as two systems.
    database: "Creator Hub Project",
    // NOT "from Sheets": influencer history lives in creatorhub too.
    historical: "Historical · creatorhub archive",
    databaseHint:
      "Creator posts recorded in the Creator Hub Project.",
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
  const [retryCount, setRetryCount] = useState(0);
  const [openAsset, setOpenAsset] = useState<UntestedAssetRow | null>(null);
  const [skuFilter, setSkuFilter] = useState<SkuFilter>("all");
  const [kindFilter, setKindFilter] = useState<string>("all");
  const [search, setSearch] = useState<string>("");
  // Influencer alone returns 13,612 rows, and every one of them was
  // being mounted: the table rendered filteredRows directly. Paging the
  // DOM keeps the export whole (it still reads every filtered row) while
  // the browser only ever holds a screenful.
  const [page, setPage] = useState(0);
  // Each media tab opens on its live register -- the DAM Project, or
  // the Creator Hub Project on influencer -- with historical assets
  // available through the visible source filter.
  const [originFilter, setOriginFilter] = useState<"all" | "database" | "historical">("database");
  // Testing status filters the loaded register locally. Cards continue
  // to summarize every asset in the selected source.
  const [matchState, setMatchState] = useState<"untested" | "matched" | "pending" | "all">("all");

  function beginLoad() {
    setLoading(true);
    setError(null);
    setData(null);
  }

  // Refetch whenever the media tab changes. The row shape is the same
  // across all three -- just different populated fields.
  useEffect(() => {
    let cancelled = false;
    fetchUntestedAssets({ media, match_state: "all" })
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
  }, [media, retryCount]);

  // Source controls remain visible even when a selected source is empty.
  // Mixed origins only determine whether the table needs a source column.
  const hasMixedOrigins = !!data && data.from_database > 0 && data.from_historical > 0;

  const kinds = useMemo(() => {
    if (!data) return [] as string[];
    const s = new Set<string>();
    for (const r of data.rows) if (r.kind) s.add(r.kind);
    // Keep an active filter visible if a different testing status has
    // no assets of this kind, so it can still be cleared.
    if (kindFilter !== "all") s.add(kindFilter);
    return Array.from(s).sort();
  }, [data, kindFilter]);

  // What "has a file" means, in one place, so the cards and the table
  // can never disagree about which assets exist here.
  // An empty string is not a link -- the registers are hand-maintained
  // and a cleared cell arrives as '' rather than null.
  const hasLink = (r: UntestedAssetRow) => !!(r.link && r.link.trim());

  // KPI scope: the selected media and source, independent of table filters.
  const sourceRows = useMemo(() => {
    if (!data) return [] as UntestedAssetRow[];
    return data.rows.filter((row) => originFilter === "all" || row.origin === originFilter);
  }, [data, originFilter]);

  // Video and graphic describe only assets the register holds a link
  // for: an asset with no file cannot be put in an ad, so counting it
  // would overstate what anyone can act on.
  //
  // Influencer is different, and deliberately so. There a missing link
  // is not noise to be hidden -- it is the dominant state, 12,314 of
  // 14,709 posts, and it has its own name: Pending. A category that is
  // counted has to have rows behind it, so the whole register is in
  // scope here.
  const scopeRows = useMemo(
    () => (media === "influencer" ? sourceRows : sourceRows.filter(hasLink)),
    [sourceRows, media]);

  const filteredRows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return scopeRows.filter((r) => {
      // These have to mean exactly what the cards above count, or
      // picking "Not Tested" shows 13,453 rows under a card reading
      // 1,139 and there is nothing on screen to explain the gap.
      //   Tested      the id appears in an ad name
      //   Not Tested  a link exists, but the id matches no ad
      //   Pending     no link yet (influencer only; elsewhere those
      //               rows are out of scope entirely)
      if (matchState === "matched" && r.matched_ads <= 0) return false;
      if (matchState === "untested"
          && !(r.matched_ads === 0 && (media !== "influencer" || hasLink(r)))) return false;
      if (matchState === "pending" && !(r.matched_ads === 0 && !hasLink(r))) return false;
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
  }, [scopeRows, matchState, media, skuFilter, kindFilter, search]);

  // Summarize a population. One definition of "tested", used by both
  // card rows, so they cannot count it differently.
  const summarise = (rows: UntestedAssetRow[]) => {
    let tested = 0;
    let notTested = 0;
    let pending = 0;
    let matchedAds = 0;
    let withSku = 0;
    for (const row of rows) {
      // Tested wins over Pending. 45 influencer posts match an ad but
      // carry no link: they demonstrably ran, so the missing link is a
      // register gap rather than an open testing question, and filing
      // them under Pending would ask someone to chase work already
      // done. Without a precedence they would be counted twice and the
      // three buckets would not sum to the total.
      if (row.matched_ads > 0) tested += 1;
      else if (hasLink(row)) notTested += 1;
      else pending += 1;
      matchedAds += row.matched_ads;
      if (row.matched_master_sku) withSku += 1;
    }
    return { total: rows.length, tested, notTested, pending, matchedAds, withSku };
  };

  // The card rows are per-SOURCE and deliberately do NOT follow the
  // Source switch: that switch chooses what the TABLE lists, while the
  // cards exist to show both populations at once. Both are narrowed to
  // assets that have a link, the same rule the table uses.
  const inScope = (r: UntestedAssetRow) => media === "influencer" || hasLink(r);
  const damMetrics = useMemo(
    () => summarise((data?.rows ?? []).filter((r) => r.origin === "database" && inScope(r))),
    [data, media]);
  const histMetrics = useMemo(
    () => summarise((data?.rows ?? []).filter((r) => r.origin === "historical" && inScope(r))),
    [data, media]);

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
  const columnCount = 7 + Number(showThumbnail) + Number(titleColLabel !== "—")
    + (showSkuColumns ? 2 : 0) + Number(hasMixedOrigins);
  const populationLabel = matchState === "untested" ? "not tested" : matchState === "matched" ? "tested" : "registered";

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h2 className="text-[18px] font-semibold tracking-[-0.02em] text-text-primary">Untested Assets</h2>
        <p className="text-sm text-text-secondary">
          Browse registered assets and filter by whether they have run in a Meta ad.
          Click a tested asset to view its matched ads and their performance.
        </p>
      </div>

      {/* Media tab strip */}
      <div className="flex flex-wrap items-end gap-1 border-b border-border-primary">
        {MEDIA_TABS.map((t) => {
          const active = media === t.value;
          return (
            <button
              key={t.value}
              aria-pressed={active}
              onClick={() => {
                if (media === t.value) return;
                // A different media tab is a different list -- start at
                // the top. Done here rather than in an effect so it is
                // one render, not two.
                beginLoad();
                setMedia(t.value);
                setKindFilter("all");
                // Pending only exists on influencer. Carrying it to
                // another tab would show an empty table under a filter
                // that tab does not offer.
                if (t.value !== "influencer") setMatchState("all");
                setOriginFilter("database");
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

      {/* One row per source, both always visible.
          They answer different questions and used to share a single row
          that changed under the Source switch: DAM Project is the live
          backlog someone can action today, Historical is the sheet-era
          archive whose ids may predate the naming convention the
          matcher relies on. Reading one set of numbers without knowing
          which of the two it described was the problem.

          Graphic has no DAM Project rows at all, so that row reads zero
          there -- the honest answer, and it says where the graphics
          actually live. */}
      <KpiRow
        title={ORIGIN_LABELS[media].database}
        m={damMetrics}
        showSkuColumns={showSkuColumns}
        loading={loading}
        ready={!!data}
        showPending={media === "influencer"}
      />
      <KpiRow
        title={ORIGIN_LABELS[media].historical}
        m={histMetrics}
        showSkuColumns={showSkuColumns}
        loading={loading}
        ready={!!data}
        showPending={media === "influencer"}
      />

      {/* Testing status narrows the selected source without changing it. */}
      <div className="flex flex-wrap items-center gap-3 rounded-md border border-border-primary bg-bg-surface px-3 py-2">
        <label className="text-xs font-medium text-text-secondary">Show:</label>
        <div className="flex overflow-hidden rounded border border-border-primary">
          {([
            ["all", ORIGIN_LABELS[media].all, "Every asset this media type holds, matched or not."],
            ["matched", "Tested", "The asset id appears in an ad name."],
            ["untested", "Not Tested",
              media === "influencer"
                ? "Post link present, but the id matches no ad."
                : "Assets with no matched ads."],
            // Only influencer counts link-less rows, so only influencer
            // can filter to them.
            ...(media === "influencer"
              ? [["pending", "Pending", "No post link yet — nothing to test until one is added."] as const]
              : []),
          ] as const).map(([v, label, hint]) => (
            <button
              key={v}
              title={hint}
              aria-pressed={matchState === v}
              onClick={() => {
                if (matchState === v) return;
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

      {/* Keep all sources selectable, including DAM Project (0), so an
          empty source never silently broadens into historical assets. */}
      {data && (
        <div className="flex flex-wrap items-center gap-3 rounded-md border border-border-primary bg-bg-surface px-3 py-2">
          <label className="text-xs font-medium text-text-secondary">Source:</label>
          <div className="flex overflow-hidden rounded border border-border-primary">
            {([
              ["all", `All (${data.total_rows.toLocaleString("en-IN")})`,
               "Every listed asset in this media type, whichever register recorded it."],
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
                aria-pressed={originFilter === v}
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
        <div role="alert" className="flex items-center justify-between gap-3 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">
          <span>{error}</span>
          <button
            type="button"
            onClick={() => {
              beginLoad();
              setRetryCount((count) => count + 1);
            }}
            disabled={loading}
            className="shrink-0 rounded border border-red-300 px-3 py-1 font-medium hover:bg-red-100 disabled:opacity-40"
          >
            Retry
          </button>
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
                </>
              )}
              <Th align="right">Ads matched</Th>
              <Th>Produced</Th>
              {/* Only when the tab mixes both -- otherwise every row
                  would repeat the same value. */}
              {hasMixedOrigins && <Th>Source</Th>}
              <Th>Links</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-primary bg-bg-white">
            {loading && (
              <tr>
                <td colSpan={columnCount} className="px-3 py-6 text-center text-text-secondary">
                  Loading…
                </td>
              </tr>
            )}
            {!loading && !error && filteredRows.length === 0 && (
              <tr>
                <td colSpan={columnCount} className="px-3 py-6 text-center text-text-secondary">
                  {originFilter === "database" && data?.from_database === 0
                    ? `No ${ORIGIN_LABELS[media].database} assets match this view. Select Historical or All to browse other sources.`
                    : `No ${populationLabel} ${media} assets match the current filters.`}
                </td>
              </tr>
            )}
            {!loading &&
              pageRows.map((r) => (
                <tr
                  key={`${r.media}:${r.id}`}
                  className={`hover:bg-bg-surface ${r.matched_ads > 0 ? "cursor-pointer" : ""}`}
                  onClick={r.matched_ads > 0 ? () => setOpenAsset(r) : undefined}
                >
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
                  <Td className="font-mono">
                    {r.matched_ads > 0 ? (
                      <button
                        type="button"
                        aria-haspopup="dialog"
                        aria-label={`View matched ads for asset ${r.id}`}
                        onClick={(event) => { event.stopPropagation(); setOpenAsset(r); }}
                        className="text-text-link underline decoration-dotted underline-offset-4 hover:decoration-solid focus-visible:outline-2 focus-visible:outline-offset-2"
                      >
                        {r.id}
                      </button>
                    ) : r.id}
                  </Td>
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
                    </>
                  )}
                  <Td align="right">
                    <span
                      className={
                        "font-mono text-[11px] " +
                        (r.matched_ads > 0 ? "text-text-primary" : "text-text-tertiary")
                      }
                      title={r.matched_ads > 0
                        ? `View ${r.matched_ads} matched ad${r.matched_ads === 1 ? "" : "s"}`
                        : "No ad name carries this asset id — that is what makes it untested"}
                    >
                      {r.matched_ads}
                    </span>
                  </Td>
                  <Td>{fmtDate(r.date_produced)}</Td>
                  {hasMixedOrigins && (
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
                      <span className="flex flex-wrap gap-1" onClick={(event) => event.stopPropagation()}>
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
          {populationLabel} asset
          {filteredRows.length === 1 ? "" : "s"}
          {filteredRows.length !== (data?.total_rows ?? 0) &&
            ` (${(data?.total_rows ?? 0).toLocaleString("en-IN")} registered ${media} assets in total)`}
          .
          {data && ` Computed at ${new Date(data.computed_at).toLocaleString()}.`}
        </span>
        {pageCount > 1 && (
          <span className="ml-auto inline-flex items-center gap-2">
            <button
              onClick={() => setPage(Math.max(0, safePage - 1))}
              disabled={safePage === 0}
              className="rounded-md border border-border-primary px-2 py-1 disabled:opacity-40"
            >
              ← Prev
            </button>
            <span>
              Page {safePage + 1} of {pageCount.toLocaleString("en-IN")}
            </span>
            <button
              onClick={() => setPage(Math.min(pageCount - 1, safePage + 1))}
              disabled={safePage >= pageCount - 1}
              className="rounded-md border border-border-primary px-2 py-1 disabled:opacity-40"
            >
              Next →
            </button>
          </span>
        )}
      </div>
      {openAsset && (
        <AssetAdsModal
          key={`${openAsset.media}:${openAsset.id}`}
          assetId={openAsset.id}
          assetName={openAsset.nomenclature || openAsset.title || openAsset.id}
          appearance="standard"
          requestTimeoutMs={30_000}
          onClose={() => setOpenAsset(null)}
        />
      )}
    </div>
  );
}

type RowMetrics = {
  total: number; tested: number; notTested: number; pending: number;
  matchedAds: number; withSku: number;
};

/** One labelled row of KPI cards for a single source.
 *
 *  Influencer reads differently from the other two. There a post with
 *  no link is the dominant state rather than an edge case -- 12,314 of
 *  14,709 -- so it gets its own card, Pending, and the row drops the
 *  SKU card, which only ever said "No SKU mapping" because SIF-…
 *  nomenclature carries no product code.
 *
 *      Total = Tested + Not Tested + Pending, always. */
function KpiRow({ title, m, showSkuColumns, loading, ready, showPending }: {
  title: string;
  m: RowMetrics;
  showSkuColumns: boolean;
  loading: boolean;
  ready: boolean;
  showPending?: boolean;
}) {
  const v = (n: number) => (ready ? fmtInt(n) : "\u2014");
  return (
    <div className="flex flex-col gap-2">
      <div className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
        {title}
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {/* Counts assets the register holds a LINK for, because that is
            the only set anyone can act on -- an asset with no file
            cannot be put in an ad. One number: the register's own row
            count is deliberately not shown beside it, because two
            totals on one card got the bigger one read as the backlog. */}
        <KpiTile
          label="Total Assets"
          value={v(m.total)}
          hint={showPending ? "Every post in this source" : "Assets with a link"}
        />
        <KpiTile
          label="Tested"
          value={v(m.tested)}
          hint={ready && m.total
            ? `${Math.round((m.tested / m.total) * 100)}% \u2014 the asset id appears in an ad name`
            : "The asset id appears in an ad name"}
        />
        <KpiTile
          label="Not Tested"
          value={v(m.notTested)}
          hint={loading
            ? "Loading\u2026"
            : showPending
              ? "Post link present, but the id matches no ad"
              : "Assets with no matched ads"}
        />
        {showPending && (
          <KpiTile
            label="Pending"
            value={v(m.pending)}
            hint="No post link yet \u2014 nothing to test until one is added"
          />
        )}
        <KpiTile label="Matched Ads" value={v(m.matchedAds)} hint="Ads matched to these assets" />
        {showPending ? null : showSkuColumns ? (
          <KpiTile
            label="SKU Matched"
            value={ready ? `${fmtInt(m.withSku)} / ${fmtInt(m.total)}` : "\u2014"}
            hint="Assets with a catalog SKU"
          />
        ) : (
          <KpiTile
            label="SKU Matched"
            value="No SKU mapping"
            hint="Influencer nomenclature (SIF-\u2026) doesn't carry a product SKU code"
          />
        )}
      </div>
    </div>
  );
}

function KpiTile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div role="group" aria-label={label} className="rounded-md border border-border-primary bg-bg-white px-4 py-3">
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
