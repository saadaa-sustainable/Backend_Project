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
import { getAssetPreview } from "@/lib/assetPreview";
import { AssetAdsModal } from "./AssetAdsModal";
import {
  FieldLabel,
  FigureBand,
  FilterCell,
  FilterRule,
  SectionHeader,
  Segmented,
  filterControlClass,
} from "./SectionChrome";

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

/** How long this asset has been sitting in the register unused.
 *
 *  Produced-date, not created-at: the question the backlog asks is how
 *  long ago the work was finished, not when somebody typed the row in.
 *  Null when the register carries no date, which is common enough on
 *  the sheet-era rows that it needs its own answer on the card. */
function daysWaiting(dateProduced: string | null): number | null {
  if (!dateProduced) return null;
  const d = new Date(dateProduced);
  if (Number.isNaN(d.getTime())) return null;
  const days = Math.floor((Date.now() - d.getTime()) / 86_400_000);
  return days < 0 ? 0 : days;
}

/** The wait, coloured by how long it has been. Past 50 days is signal
 *  red, which on this surface means a rule has fired; past 30 is the
 *  warning field; under that it is just a number. */
function waitTone(days: number | null): string {
  if (days === null) return "text-text-tertiary";
  if (days > 50) return "text-error-text";
  if (days > 30) return "text-warning-text";
  return "text-text-tertiary";
}

/**
 * One untested asset as a portrait card.
 *
 * Preview, name, and how long it has been waiting -- the three things
 * that decide whether to pick it up next. Everything the row carries
 * (kind, sub-kind, both SKUs, source, matched ads) is on the card's own
 * title and in full in the Table view.
 *
 * The frame is a link to the file when the register holds one, and the
 * name opens the matched-ads dialog when there are any. Two targets,
 * never nested: the card itself is not a button.
 */
function UntestedCard({
  r,
  onOpen,
}: {
  r: UntestedAssetRow;
  onOpen: () => void;
}) {
  const [failed, setFailed] = useState(false);
  const days = daysWaiting(r.date_produced);
  const name = r.nomenclature || r.title || r.id;
  const href = r.links?.[0]?.url ?? (r.link && r.link.trim() ? r.link.trim() : null);
  // Drive holds most of these files, and Drive will render a thumbnail
  // for a file id -- so the card can show the creative rather than the
  // word "video". Same derivation Creative Testing's preview uses.
  const preview = getAssetPreview({ preview_url: href, thumbnail_url: r.thumbnail });
  const thumb = failed ? null : preview.thumbnail;
  const title =
    `${r.id}\n` +
    `${r.kind ?? "—"}${r.sub_kind ? ` · ${r.sub_kind}` : ""}\n` +
    `${r.nomenclature ?? "no nomenclature"}\n` +
    (r.candidate_master_sku || r.matched_master_sku
      ? `SKU: candidate ${r.candidate_master_sku ?? "—"} · matched ${r.matched_master_sku ?? "—"}\n`
      : "") +
    `Produced ${fmtDate(r.date_produced)} · ${r.matched_ads} matched ad${r.matched_ads === 1 ? "" : "s"}\n` +
    `${r.source_system}`;
  const frameInner = thumb ? (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={thumb}
      alt=""
      loading="lazy"
      referrerPolicy="no-referrer"
      className="absolute inset-0 h-full w-full object-cover"
      onError={() => setFailed(true)}
    />
  ) : (
    <span className="text-[11px] text-text-tertiary">{r.media}</span>
  );
  const frameClass =
    "relative flex aspect-[3/4] w-full items-center justify-center overflow-hidden " +
    "border-b border-border-primary bg-bg-muted";
  return (
    <article className="flex flex-col overflow-hidden border border-border-primary bg-bg-white" title={title}>
      {href ? (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          title={`Open the file for ${r.id}`}
          className={frameClass}
        >
          {frameInner}
        </a>
      ) : (
        <div className={frameClass}>{frameInner}</div>
      )}
      <div className="px-2.5 py-2.5">
        {r.matched_ads > 0 ? (
          <button
            type="button"
            aria-haspopup="dialog"
            aria-label={`View matched ads for asset ${r.id}`}
            onClick={onOpen}
            className="block w-full truncate text-left font-mono text-[11.5px] leading-[1.35] text-text-link underline decoration-dotted underline-offset-4 hover:decoration-solid"
          >
            {name}
          </button>
        ) : (
          <span className="block truncate font-mono text-[11.5px] leading-[1.35] text-text-primary">
            {name}
          </span>
        )}
        <span className={`mt-1 block font-mono text-[11px] tabular-nums ${waitTone(days)}`}>
          {days === null ? "no production date" : `${days.toLocaleString("en-IN")} days waiting`}
        </span>
      </div>
    </article>
  );
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
      "Video recorded only in the Creative Mastersheet, from before the DAM register existed: the \u201cIterated Content\u201d tab and the newer \u201cEdited Content\u201d tab. Each row names which of the two it came from.",
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
  // Cards or rows. Neither refetches and neither narrows: it is the
  // same page of the same filtered rows, read two ways.
  const [view, setView] = useState<"grid" | "table">("grid");

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
    // The longest any untested asset in this population has been
    // waiting. Null when none of them carries a production date.
    let oldest: number | null = null;
    for (const row of rows) {
      if (row.matched_ads === 0) {
        const d = daysWaiting(row.date_produced);
        if (d !== null && (oldest === null || d > oldest)) oldest = d;
      }
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
    return { total: rows.length, tested, notTested, pending, matchedAds, withSku, oldest };
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

  // SKUs with nothing in test: every asset this source holds for that
  // prefix is still unmatched. Derived from the rows already loaded --
  // no extra request, and the same scope the table counts.
  const skusWithNothingInTest = useMemo(() => {
    if (media === "influencer") return [] as { sku: string; waiting: number }[];
    const by = new Map<string, { waiting: number; tested: number }>();
    for (const r of scopeRows) {
      const sku = r.matched_master_sku || r.candidate_master_sku;
      if (!sku) continue;
      const e = by.get(sku) ?? { waiting: 0, tested: 0 };
      if (r.matched_ads > 0) e.tested += 1;
      else e.waiting += 1;
      by.set(sku, e);
    }
    return Array.from(by.entries())
      .filter(([, e]) => e.tested === 0 && e.waiting > 0)
      .map(([sku, e]) => ({ sku, waiting: e.waiting }))
      .sort((a, b) => b.waiting - a.waiting);
  }, [scopeRows, media]);

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
      {/* The two-line "how to use this page" moved to Help. Clicking a
          row to see its matched ads is discoverable by doing it; it did
          not need announcing above every visit. */}
      <SectionHeader title="Untested Assets" helpId="data-floor">
        <div className="flex items-center gap-1.5">
          <FieldLabel className="!inline">Media</FieldLabel>
          <Segmented
            options={MEDIA_TABS.map((t) => ({ value: t.value, label: t.label, title: t.desc }))}
            value={media}
            onChange={(v) => {
              const next = v as UntestedMedia;
              if (media === next) return;
              // A different media tab is a different list -- start at
              // the top. Done here rather than in an effect so it is
              // one render, not two.
              beginLoad();
              setMedia(next);
              setKindFilter("all");
              // Pending only exists on influencer. Carrying it to
              // another tab would show an empty table under a filter
              // that tab does not offer.
              if (next !== "influencer") setMatchState("all");
              setOriginFilter("database");
              setPage(0);
            }}
          />
        </div>
        <Segmented
          options={[
            { value: "grid", label: "Grid", title: "Every asset as a card: the file, its name, and how long it has waited." },
            { value: "table", label: "Table", title: "The same assets as rows, with every register column." },
          ]}
          value={view}
          onChange={(v) => setView(v as "grid" | "table")}
        />
      </SectionHeader>

      {/* One band per source, both always visible.
          They answer different questions and used to share a single row
          that changed under the Source switch: DAM Project is the live
          backlog someone can action today, Historical is the sheet-era
          archive whose ids may predate the naming convention the
          matcher relies on. Reading one set of numbers without knowing
          which of the two it described was the problem.

          Graphic has no DAM Project rows at all, so that band reads zero
          there -- the honest answer, and it says where the graphics
          actually live.

          Ten bordered tiles became two bands of plain figures: the
          hints they carried are on each figure's own title, which is
          where this surface keeps a definition that is not worth a
          standing line. */}
      <SourceBand
        title={ORIGIN_LABELS[media].database}
        m={damMetrics}
        showSkuColumns={showSkuColumns}
        loading={loading}
        ready={!!data}
        showPending={media === "influencer"}
      />
      <SourceBand
        title={ORIGIN_LABELS[media].historical}
        m={histMetrics}
        showSkuColumns={showSkuColumns}
        loading={loading}
        ready={!!data}
        showPending={media === "influencer"}
      />

      {/* Three bordered trays of controls became one rule of labelled
          cells. Every control is the same one it was, with the same
          handler and the same tooltip. */}
      <FilterRule
        actions={
          <>
            <span className="text-[11.5px] text-text-tertiary tabular-nums">
              {filteredRows.length.toLocaleString("en-IN")} {populationLabel} asset
              {filteredRows.length === 1 ? "" : "s"}
            </span>
            <ExportButton
              rows={filteredRows as unknown as Record<string, unknown>[]}
              filename={`untested_${media}`}
              disabled={loading || !filteredRows.length}
            />
          </>
        }
      >
        {/* Testing status narrows the selected source without changing it. */}
        <FilterCell label="Show">
          <Segmented
            options={[
              { value: "all", label: ORIGIN_LABELS[media].all, title: "Every asset this media type holds, matched or not." },
              { value: "matched", label: "Tested", title: "The asset id appears in an ad name." },
              {
                value: "untested",
                label: "Not Tested",
                title:
                  media === "influencer"
                    ? "Post link present, but the id matches no ad."
                    : "Assets with no matched ads.",
              },
              // Only influencer counts link-less rows, so only influencer
              // can filter to them.
              ...(media === "influencer"
                ? [{ value: "pending", label: "Pending", title: "No post link yet — nothing to test until one is added." }]
                : []),
            ]}
            value={matchState}
            onChange={(v) => {
              if (matchState === v) return;
              setMatchState(v as typeof matchState);
              setPage(0);
            }}
          />
        </FilterCell>

        {/* Keep all sources selectable, including DAM Project (0), so an
            empty source never silently broadens into historical assets. */}
        {data && (
          <FilterCell label="Source">
            <Segmented
              options={[
                {
                  value: "all",
                  label: `All (${data.total_rows.toLocaleString("en-IN")})`,
                  title: "Every listed asset in this media type, whichever register recorded it.",
                },
                {
                  value: "database",
                  label: `${ORIGIN_LABELS[media].database} (${data.from_database.toLocaleString("en-IN")})`,
                  title: ORIGIN_LABELS[media].databaseHint,
                },
                {
                  value: "historical",
                  label: `${ORIGIN_LABELS[media].historical} (${data.from_historical.toLocaleString("en-IN")})`,
                  title: ORIGIN_LABELS[media].historicalHint,
                },
              ]}
              value={originFilter}
              onChange={(v) => {
                setOriginFilter(v as typeof originFilter);
                setPage(0);
              }}
            />
          </FilterCell>
        )}

        {showSkuColumns && (
          <FilterCell label="SKU match">
            <Segmented
              options={[
                { value: "all", label: "All" },
                { value: "matched", label: "Matched", title: "Assets whose SKU prefix exists in the catalog." },
                { value: "unmatched", label: "Unmatched", title: "Assets whose SKU prefix matches no catalog SKU." },
              ]}
              value={skuFilter}
              onChange={(v) => setSkuFilter(v as SkuFilter)}
            />
          </FilterCell>
        )}

        <FilterCell label={kindColLabel} className="w-44" htmlFor="ua-kind">
          <select
            id="ua-kind"
            value={kindFilter}
            onChange={(e) => setKindFilter(e.target.value)}
            className={filterControlClass}
          >
            <option value="all">All</option>
            {kinds.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </FilterCell>

        <FilterCell label="Search" className="w-56" htmlFor="ua-search">
          <input
            id="ua-search"
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="id / title / nomenclature / SKU…"
            className={filterControlClass}
          />
        </FilterCell>
      </FilterRule>

      {error && (
        <div role="alert" className="flex items-center justify-between gap-3 rounded-md border border-border-primary bg-error-bg px-3 py-2 text-sm text-error-text">
          <span>{error}</span>
          <button
            type="button"
            onClick={() => {
              beginLoad();
              setRetryCount((count) => count + 1);
            }}
            disabled={loading}
            className="shrink-0 rounded border border-border-primary px-3 py-1 font-medium hover:bg-error-bg disabled:opacity-40"
          >
            Retry
          </button>
        </div>
      )}

      {/* The grid. Six portrait cards a row, because a creative is a
          picture before it is a row of fields: what the file looks like
          and how long it has been sitting there is the whole decision.
          The Table switch above still carries every column. */}
      {view === "grid" &&
        (loading ? (
          <div className="grid grid-cols-3 gap-3 sm:grid-cols-4 lg:grid-cols-6">
            {Array.from({ length: 12 }).map((_, i) => (
              <div key={`uk-${i}`} className="border border-border-primary bg-bg-white" style={{ opacity: 1 - i * 0.05 }}>
                <div className="aspect-[3/4] w-full animate-pulse bg-bg-muted" />
                <div className="px-2.5 py-2.5">
                  <div className="h-3 w-3/4 animate-pulse bg-bg-muted" />
                </div>
              </div>
            ))}
          </div>
        ) : !error && filteredRows.length === 0 ? (
          <p className="border-b border-border-primary py-8 text-center text-[13px] text-text-tertiary">
            {originFilter === "database" && data?.from_database === 0
              ? `No ${ORIGIN_LABELS[media].database} assets match this view. Select Historical or All to browse other sources.`
              : `No ${populationLabel} ${media} assets match the current filters.`}
          </p>
        ) : (
          <div className="grid grid-cols-3 gap-3 sm:grid-cols-4 lg:grid-cols-6">
            {pageRows.map((r) => (
              <UntestedCard key={`${r.media}:${r.id}`} r={r} onOpen={() => setOpenAsset(r)} />
            ))}
          </div>
        ))}

      {/* Table. `min-w-full` not `w-full`, with nowrap cells: the table
          sizes to its content and the wrapper scrolls, instead of every
          column being squeezed to fit the viewport. Nomenclature strings
          here run past 60 characters and were wrapping to three lines. */}
      {view === "table" && (
      <div className="overflow-x-auto border border-border-primary bg-bg-white">
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
                          <span className="rounded bg-success-bg px-1.5 py-0.5 font-mono text-[11px] text-success-text">
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
                            ? "border-border-primary bg-success-bg text-success-text"
                            : "border-border-primary bg-bg-muted text-text-secondary")
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
      )}

      {/* SKUs with nothing in test. Derived from the rows this source
          already returned: a prefix every one of whose assets is still
          unmatched. The pill says how many are waiting behind it. */}
      {showSkuColumns && skusWithNothingInTest.length > 0 && (
        <div className="flex flex-col gap-2 border-t border-border-primary pt-3">
          <div className="flex flex-wrap items-baseline gap-2">
            <h3 className="m-0 text-[13px] font-semibold text-text-primary">SKUs with nothing in test</h3>
            <span className="text-[11px] text-text-tertiary tabular-nums">
              {skusWithNothingInTest.length.toLocaleString("en-IN")} SKUs · every asset the register
              holds for them is still unmatched
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            {skusWithNothingInTest.slice(0, 18).map((s) => (
              <span
                key={s.sku}
                title={`${s.sku} — ${s.waiting.toLocaleString("en-IN")} asset(s) waiting, none of them in an ad`}
                className="flex items-center gap-2 border border-border-primary px-2 py-1 font-mono text-[11.5px]"
              >
                <span className="font-semibold text-text-primary">{s.sku}</span>
                <span className="tabular-nums text-text-tertiary">0 in test · {s.waiting} waiting</span>
              </span>
            ))}
            {skusWithNothingInTest.length > 18 && (
              <span className="px-2 py-1 font-mono text-[11.5px] text-text-tertiary">
                + {skusWithNothingInTest.length - 18} more
              </span>
            )}
          </div>
        </div>
      )}

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
  /** Longest wait among this source's untested assets, in days. */
  oldest: number | null;
};

/** One band of figures for a single source.
 *
 *  Was five bordered tiles. The numbers are the same, and so are their
 *  definitions -- each figure carries its hint on the value's title,
 *  and Tested keeps its share of the source as a basis line.
 *
 *  Influencer reads differently from the other two. There a post with
 *  no link is the dominant state rather than an edge case -- 12,314 of
 *  14,709 -- so it gets its own figure, Pending, and the band drops the
 *  SKU figure, which only ever said "No SKU mapping" because SIF-…
 *  nomenclature carries no product code.
 *
 *      Total = Tested + Not Tested + Pending, always. */
function SourceBand({ title, m, showSkuColumns, loading, ready, showPending }: {
  title: string;
  m: RowMetrics;
  showSkuColumns: boolean;
  loading: boolean;
  ready: boolean;
  showPending?: boolean;
}) {
  const v = (n: number) => (ready ? fmtInt(n) : "—");
  const fig = (value: string, hint: string) => <span title={hint}>{value}</span>;
  const figures = [
    {
      label: "Total assets",
      // Counts assets the register holds a LINK for, because that is
      // the only set anyone can act on -- an asset with no file cannot
      // be put in an ad.
      value: fig(v(m.total), showPending ? "Every post in this source" : "Assets with a link"),
    },
    {
      label: "Tested",
      value: fig(v(m.tested), "The asset id appears in an ad name"),
      basis: ready && m.total ? `${Math.round((m.tested / m.total) * 100)}% of this source` : undefined,
    },
    {
      label: "Not tested",
      value: fig(
        v(m.notTested),
        loading
          ? "Loading…"
          : showPending
            ? "Post link present, but the id matches no ad"
            : "Assets with no matched ads",
      ),
    },
    ...(showPending
      ? [{
          label: "Pending",
          value: fig(v(m.pending), "No post link yet — nothing to test until one is added"),
        }]
      : []),
    { label: "Matched ads", value: fig(v(m.matchedAds), "Ads matched to these assets") },
    ...(showPending
      ? []
      : [
          showSkuColumns
            ? {
                label: "SKU matched",
                value: fig(
                  ready ? `${fmtInt(m.withSku)} / ${fmtInt(m.total)}` : "—",
                  "Assets with a catalog SKU",
                ),
              }
            : {
                label: "SKU matched",
                value: fig(
                  "No SKU mapping",
                  "Influencer nomenclature (SIF-…) doesn't carry a product SKU code",
                ),
              },
        ]),
    {
      label: "Oldest waiting",
      value: fig(
        m.oldest === null ? "—" : `${m.oldest.toLocaleString("en-IN")} d`,
        "Longest any untested asset in this source has waited since its production date",
      ),
    },
  ];
  return (
    <div className="flex flex-col gap-2">
      <FieldLabel>{title}</FieldLabel>
      <FigureBand figures={figures} />
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
