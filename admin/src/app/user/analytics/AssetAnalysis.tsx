"use client";

/**
 * Asset Analysis — every asset under two results at once.
 *
 * WHY THIS EXISTS, AND WHY IT IS NOT CREATIVE TESTING
 * ---------------------------------------------------
 * An asset runs as a SERIES of ads. Every other screen in this product
 * shows the result of its newest one, which is the right answer to
 * "what is this doing now" and the wrong answer to "is this any good".
 *
 * Measured 2026-10-14 over 3,536 assets: 350 reached winner grade at
 * some iteration and 300 of them have since fallen out of it.
 * SIF-2441-P1 won at iteration 4 of 6 and reads "Discarded" everywhere
 * else; Aug-589 made Rs 46L across three winning iterations and reads
 * "P1 analysis". Those are the assets a buyer most wants back, and
 * nothing surfaced them.
 *
 * So each asset carries BOTH:
 *     current result — the category of its newest iteration
 *     first win      — the first iteration that reached winner grade
 *
 * LANES follow from the pair, and the winner lanes take precedence over
 * the current result, because a win is a fact about the asset that a
 * later bad run does not undo. A win at iteration 1 is a first-time
 * winner; a win at iteration 2+ is a retest that worked, which is a
 * different and more useful thing to know.
 *
 * Each lane's WIDTH is its share of the assets, so the board is itself
 * the distribution: Discarded at 2,179 of 3,536 takes most of the rule
 * and Incremental Winners at 1 is the sliver it is. Lanes nobody is
 * working today collapse to a rail.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  ASSET_LANES,
  fetchAssetAnalysis,
  type AssetAnalysisResponse,
  type AssetAnalysisRow,
  type AssetAnalysisParams,
} from "@/lib/api";
import { DateRangePicker } from "@/components/DateRangePicker";
import { AssetPreviewCell } from "./AssetPreview";
import {
  FilterRule, FilterCell, Segmented, filterControlClass,
} from "./SectionChrome";
import { MarkChevron } from "./Pictograms";
import { AssetAnalysisDrawer } from "./AssetAnalysisDrawer";

/* ── formatting ───────────────────────────────────────────────── */

const nf = new Intl.NumberFormat("en-IN");
const num = (n: number | null | undefined) => (n == null ? "—" : nf.format(Math.round(n)));
const money = (n: number | null | undefined) => {
  if (n == null) return "—";
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)}Cr`;
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(2)}L`;
  return `₹${nf.format(Math.round(n))}`;
};
const day = (s: string | null) =>
  s ? new Date(`${s}T00:00:00`).toLocaleDateString("en-GB",
      { day: "2-digit", month: "short", year: "numeric" }) : "—";
const spanDays = (a: string | null, b: string | null) =>
  a && b ? Math.round((+new Date(b) - +new Date(a)) / 86_400_000) : null;

/** The verdict's own colour, the one place this section spends it. */
const RESULT_CHIP: Record<string, string> = {
  "Incremental Winner": "bg-success-bg text-success-text",
  Winner: "bg-success-bg text-success-text",
  "P0 analysis": "bg-bg-muted text-text-secondary",
  "P1 analysis": "bg-bg-muted text-text-secondary",
  "P2 analysis": "bg-bg-muted text-text-secondary",
  "Result Awaited": "bg-warning-bg text-warning-text",
  Discarded: "bg-error-bg text-error-text",
};
/** Current-result strip, in the framework's own order. */
const RESULT_ORDER = [
  "Incremental Winner", "Winner", "P0 analysis", "P1 analysis",
  "P2 analysis", "Result Awaited", "Discarded",
] as const;

/** What each verdict is CALLED on this section's strip.
 *
 *  The stored values are the framework's own (P0 / P1 / P2 analysis) and
 *  nothing here changes them -- they still drive the filter, the lanes
 *  and every other section. This map is display only, and only on this
 *  section: Ads Analyse and Creative Testing keep the framework names,
 *  because that is the vocabulary their users already have.
 *
 *  The renames say what the bucket is FOR rather than where it sits in
 *  a sequence, which is the thing a number cannot carry. */
const RESULT_LABEL: Record<string, string> = {
  "Incremental Winner": "Incremental Winner",
  Winner: "Winner",
  "P0 analysis": "Landing page and funnel audit",
  "P1 analysis": "Creative audit & ITE",
  "P2 analysis": "Retesting",
  "Result Awaited": "Result awaited",
  Discarded: "Discarded result after 14 days",
};

/** The one place this section spends colour on a category: the seven
 *  verdicts are its own vocabulary. Same inks Creative Testing uses. */
const RESULT_ACCENT: Record<string, string> = {
  "Incremental Winner": "#2F6B3A",
  Winner: "#2F6B3A",
  "P0 analysis": "#1D4E89",
  "P1 analysis": "#B45309",
  "P2 analysis": "#8E6608",
  "Result Awaited": "#8E6608",
  Discarded: "#9E0C24",
};

const LANE_RULE: Record<string, string> = {
  "Incremental Winners": "border-success-mid",
  "First Time Ad Winners": "border-success-mid",
  "Retesting Winners": "border-success-mid",
  "Result Awaited": "border-warning-mid",
  Discarded: "border-error-mid",
};

/* ── the card ─────────────────────────────────────────────────── */

function AssetCard({
  r, onOpen, showPreview = false,
}: { r: AssetAnalysisRow; onOpen: () => void; showPreview?: boolean }) {
  const winnerNow = r.current_result === "Winner" || r.current_result === "Incremental Winner";
  const days = spanDays(r.first_tested, r.last_tested);
  return (
    <article data-asset={r.asset_id} className="flex flex-col border border-border-primary bg-bg-white text-left transition-colors hover:border-text-tertiary">
      {showPreview ? <AssetPreviewCell asset={r} variant="card" appearance="standard" /> : (
        <div className="flex items-center gap-3 px-3 pt-3">
          <AssetPreviewCell asset={r} variant="compact" appearance="standard" />
          <div className="min-w-0 break-words font-mono text-[12.5px] font-semibold text-text-primary">{r.asset_id}</div>
        </div>
      )}
      <button type="button" onClick={onOpen} aria-label={`View ads for asset ${r.asset_id}`} className="flex flex-1 flex-col text-left hover:bg-bg-surface focus-visible:outline-2 focus-visible:outline-text-primary">
        <div className="flex flex-col gap-2 px-3 pt-3">
          {showPreview && <div className="break-words font-mono text-[12.5px] font-semibold text-text-primary">{r.asset_id}</div>}
          <div className="flex flex-wrap gap-1">
            <span className={`px-1.5 py-0.5 text-[9.5px] font-semibold uppercase tracking-[0.05em] ${
              RESULT_CHIP[r.current_result ?? ""] ?? "bg-bg-muted text-text-secondary"}`}>
              {r.current_result ?? "—"}
            </span>
            {/* The win, kept whatever the current result says. */}
            {r.first_win_iter != null && (
              <span
                title={`First reached winner grade at iteration ${r.first_win_iter} of ${r.iterations}, on ${day(r.first_win_date)}`}
                className="border border-dashed border-success-text px-1.5 py-0.5 text-[9.5px] font-semibold uppercase tracking-[0.05em] text-success-text"
              >
                ★ Won ITE {r.first_win_iter}
              </span>
            )}
            {r.iterations > 1 && (
              <span className="border border-warning-text px-1.5 py-0.5 text-[9.5px] font-semibold uppercase tracking-[0.05em] text-warning-text">
                ITER ×{r.iterations}
              </span>
            )}
          </div>
          <div className="font-mono text-[11.5px] leading-[1.4] text-text-secondary break-words">
            {r.latest_ad_name ?? "—"}
          </div>
          <div className="text-[11px] text-text-tertiary">{r.account_name ?? "—"}</div>
        </div>

        <div className="mt-2.5 grid w-full grid-cols-3 border-t border-border-soft">
          {([["Spend", money(r.spend)], ["ROAS", r.roas == null ? "—" : `${r.roas.toFixed(2)}x`],
             ["Ads", num(r.ads)]] as const).map(([k, v], i) => (
            <div key={k} className={`px-3 py-2 ${i ? "border-l border-border-soft" : ""}`}>
              <div className="text-[9px] font-semibold uppercase tracking-[0.07em] text-text-tertiary">{k}</div>
              <div className="mt-0.5 font-mono text-[14px] text-text-primary tabular-nums">{v}</div>
            </div>
          ))}
        </div>

        <div className="px-3 pt-2 text-[11px] leading-[1.5] text-text-tertiary">
          First tested {day(r.first_tested)} · last {day(r.last_tested)}
          {days != null ? ` · ran ${days} days` : ""}
        </div>

        {r.first_win_iter != null && !winnerNow && (
          <div className="mx-3 mt-2 bg-success-bg px-2 py-1.5 text-[11.5px] leading-[1.45] text-success-text">
            Won at iteration {r.first_win_iter} of {r.iterations} — the current result does not show it.
          </div>
        )}
        <div className="px-3 pb-3 pt-2 text-[11.5px] text-text-link">View ads</div>
      </button>
    </article>
  );
}

/* ── the section ──────────────────────────────────────────────── */

export function AssetAnalysis() {
  // This endpoint filters ad CREATION dates, not daily metrics. Lifetime
  // must include older assets that are still active, as the prototype did.
  const [range, setRange] = useState({ from: "", to: "" });
  const [preset, setPreset] = useState("lifetime");
  const [media, setMedia] = useState<string>("");
  const [account, setAccount] = useState<string>("");
  const [status, setStatus] = useState<"" | "active" | "inactive">("");
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [only, setOnly] = useState<string>("");
  const [sort, setSort] = useState<"spend" | "roas" | "iterations" | "last_tested" | "ncp">("spend");
  const [collapsed, setCollapsed] = useState<Set<string>>(
    () => new Set(["P0 analysis", "P1 analysis", "P2 analysis", "Result Awaited", "Discarded", "Unrated"]),
  );
  const [response, setResponse] = useState<{ params: AssetAnalysisParams; data: AssetAnalysisResponse | null; error: string | null } | null>(null);
  const [open, setOpen] = useState<AssetAnalysisRow | null>(null);
  /* Three readings of one set of assets, because three people use this
     page. A buyer works a BOARD -- the lanes are a queue, and what is
     in Retesting Winners today is the day's work. A founder reads a
     LIST -- ranked by spend, both results on every line, no lane
     structure to learn. An analyst wants a TABLE to sort and export.
     Same rows, same filters, same drawer on click. */
  const [view, setView] = useState<"board" | "cards" | "table">("board");
  const [loadingMoreFor, setLoadingMoreFor] = useState<AssetAnalysisParams | null>(null);
  const requestVersion = useRef(0);
  const closeDrawer = useCallback(() => setOpen(null), []);
  const params = useMemo<AssetAnalysisParams>(() => ({
    from_date: range.from || undefined, to_date: range.to || undefined,
    media: media || undefined, account_name: account || undefined,
    status: status || undefined, search: debounced || undefined,
    only: (only || undefined) as AssetAnalysisParams["only"], sort,
    limit: status ? 1000 : 400,
  }), [range.from, range.to, media, account, status, debounced, only, sort]);
  const data = response?.params === params ? response.data : null;
  const error = response?.params === params ? response.error : null;
  const loading = response?.params !== params;
  const loadingMore = loadingMoreFor === params;

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search.trim()), 400);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    let live = true;
    requestVersion.current += 1;
    fetchAssetAnalysis(params)
      .then((d) => { if (live) setResponse({ params, data: d, error: null }); })
      .catch((e: unknown) => {
        if (live) setResponse({ params, data: null, error: e instanceof ApiError ? e.message : "Could not reach the analytics backend." });
      });
    return () => { live = false; requestVersion.current += 1; };
  }, [params]);

  async function loadMore() {
    if (!data || loading || loadingMore || data.rows.length >= data.total) return;
    const version = requestVersion.current;
    setLoadingMoreFor(params);
    setResponse((previous) => previous ? { ...previous, error: null } : previous);
    try {
      const next = await fetchAssetAnalysis({ ...params, offset: data.rows.length });
      if (version !== requestVersion.current) return;
      setResponse((previous) => ({ params, error: null, data: { ...next, rows: [...(previous?.data?.rows ?? []), ...next.rows] } }));
    } catch (e) {
      if (version === requestVersion.current) setResponse((previous) => previous ? { ...previous, error: e instanceof ApiError ? e.message : "Could not load more assets." } : previous);
    } finally {
      if (version === requestVersion.current) setLoadingMoreFor(null);
    }
  }

  function clearFilters() {
    setRange({ from: "", to: "" }); setPreset("lifetime"); setMedia(""); setAccount("");
    setStatus(""); setSearch(""); setDebounced(""); setOnly(""); setSort("spend");
  }

  const toggleLane = useCallback((k: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k); else next.add(k);
      return next;
    });
  }, []);

  const byLane = useMemo(() => {
    const m: Record<string, AssetAnalysisRow[]> = {};
    ASSET_LANES.forEach((l) => { m[l] = []; });
    (data?.rows ?? []).forEach((r) => { (m[r.lane] ??= []).push(r); });
    return m;
  }, [data]);


  return (
    <div className="flex flex-col gap-3">
      <FilterRule
        actions={
          <div className="flex items-center gap-3">
            <Segmented
              options={[
                { value: "board", label: "Board", title: "Lanes as a queue: what to work on next." },
                { value: "cards", label: "Cards", title: "Every asset as a card, ranked — the Creative Testing grid, with both results." },
                { value: "table", label: "Table", title: "Every figure, sortable and exportable." },
              ]}
              value={view}
              onChange={(v) => setView(v as "board" | "cards" | "table")}
            />
            <button type="button" onClick={clearFilters} className="text-[12px] text-text-secondary hover:text-text-primary">Clear filters</button>
            <span className="font-mono text-[11.5px] text-text-tertiary">
              {loading ? "loading…" : `${nf.format(data?.total ?? 0)} assets`}
            </span>
          </div>
        }
      >
        <FilterCell label="Ad created">
          <DateRangePicker
            value={range}
            preset={preset}
            bare
            align="left"
            onApply={(r, p) => { setRange(p === "lifetime" ? { from: "", to: "" } : r); setPreset(p); }}
          />
        </FilterCell>
        <FilterCell label="Media" htmlFor="aa-media">
          <select id="aa-media" value={media} onChange={(e) => setMedia(e.target.value)} className={filterControlClass}>
            <option value="">All media</option>
            <option value="video">Video</option>
            <option value="graphic">Graphic</option>
            <option value="influencer">Influencer</option>
          </select>
        </FilterCell>
        <FilterCell label="Account" htmlFor="aa-account">
          <select id="aa-account" value={account} onChange={(e) => setAccount(e.target.value)} className={filterControlClass}>
            <option value="">All accounts</option>
            {(data?.accounts ?? []).map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </FilterCell>
        <FilterCell label="Asset" htmlFor="aa-search">
          <input id="aa-search" value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Search…" className={`${filterControlClass} w-36`} />
        </FilterCell>
        <FilterCell label="Status" htmlFor="aa-status">
          <select id="aa-status" value={status} onChange={(e) => setStatus(e.target.value as typeof status)} className={filterControlClass}>
            <option value="">All assets</option>
            <option value="active">Active assets</option>
            {/* The complement of Active, not a list of paused states:
                an asset whose every mapped ad is paused, campaign-paused,
                adset-paused, archived, with issues, or carries no status
                at all. Measured 2026-10-14, 2,330 mapped ads have NO
                status -- enumerating the paused ones would lose them. */}
            <option value="inactive">Inactive assets</option>
          </select>
        </FilterCell>
        <FilterCell label="Show" htmlFor="aa-only">
          <select id="aa-only" value={only} onChange={(e) => setOnly(e.target.value)} className={filterControlClass}>
            <option value="">Every asset</option>
            <option value="won_fell">Won, then fell</option>
            <option value="ever_won">Ever won</option>
            <option value="never">Never won</option>
          </select>
        </FilterCell>
        <FilterCell label="Sort by" htmlFor="aa-sort">
          <select id="aa-sort" value={sort} onChange={(e) => setSort(e.target.value as typeof sort)} className={filterControlClass}>
            <option value="spend">Spend</option>
            <option value="roas">ROAS</option>
            <option value="ncp">NCP</option>
            <option value="iterations">Iterations</option>
            <option value="last_tested">Last tested</option>
          </select>
        </FilterCell>
      </FilterRule>
      <p className="text-[12px] text-text-secondary">Active assets have at least one active mapped ad, including older iterations and zero-spend ads. Ad created filters launch dates; metrics describe the selected ads’ lifetime.</p>

      {error && (
        <div role="alert" className="border border-error-mid bg-error-bg p-3 text-sm text-error-text">{error}</div>
      )}

      {/* The verdict strip, by CURRENT result and carrying the spend
          behind each — the same cards Creative Testing leads with, for
          the same reason: how much money is sitting in Discarded against
          how little is behind the Winners is the decision, and a count
          alone does not say it.

          This is a DIFFERENT cut from the lanes below. The lanes fold
          every winner into First Time / Retesting, so a winner never
          appears under its own verdict there. The strip says where the
          money currently sits; the lanes say what to work on.

          It replaces the asset-count figure band that stood here, which
          repeated numbers the lane headers already carry. */}
      {data && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
          {RESULT_ORDER.map((r) => {
            // A retained/cached response may predate the result breakdown.
            const c = data.result_counts?.[r];
            return (
              <div key={r} className="overflow-hidden border border-border-primary bg-bg-white">
                <div style={{ height: 3, backgroundColor: RESULT_ACCENT[r] }} />
                <div className="px-3 py-2.5">
                  <div
                    title={`${r} — the framework name, still what the filters and lanes use`}
                    className="text-[10px] font-semibold uppercase leading-[1.35] tracking-[0.07em] text-text-tertiary"
                  >
                    {RESULT_LABEL[r] ?? r}
                  </div>
                  <div className="mt-1 text-[24px] font-medium leading-none tabular-nums text-text-primary">
                    {data.result_counts ? nf.format(c?.count ?? 0) : "—"}
                  </div>
                  <div className="mt-1.5 text-[11px] text-text-tertiary">
                    Spend{" "}
                    <span className="tabular-nums" style={{ color: RESULT_ACCENT[r] }}>
                      {money(data.result_counts ? c?.spend ?? 0 : null)}
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {view === "board" && (
        <div className="flex items-start gap-3 overflow-x-auto pb-3">
          {ASSET_LANES.map((l) => {
            const items = byLane[l] ?? [];
            const count = data?.lane_counts[l] ?? 0;
            const isCollapsed = collapsed.has(l);
            const rule = LANE_RULE[l] ?? "border-text-primary";
            if (isCollapsed) {
              return (
                <button
                  key={l}
                  type="button"
                  onClick={() => toggleLane(l)}
                  title={`Expand ${l} (${count})`}
                  className={`flex shrink-0 items-center gap-2.5 border-r-2 px-1.5 py-3 text-[11px] font-semibold uppercase tracking-[0.07em] text-text-secondary transition-colors hover:text-text-primary ${rule}`}
                  style={{ writingMode: "vertical-rl", transform: "rotate(180deg)" }}
                >
                  {l}
                  <span className="font-mono text-text-tertiary">{nf.format(count)}</span>
                </button>
              );
            }
            return (
              <section key={l} className="flex w-[332px] shrink-0 flex-col">
                <div className={`flex items-center gap-2 border-b-2 pb-2 ${rule}`}>
                  <span className="min-w-0 flex-1 truncate text-[11px] font-semibold uppercase tracking-[0.07em] text-text-primary">
                    {l}
                  </span>
                  <span className="font-mono text-[12px] text-text-tertiary">{nf.format(count)}</span>
                  <button type="button" onClick={() => toggleLane(l)} aria-label={`Collapse ${l}`}
                    className="text-text-tertiary transition-colors hover:text-text-primary">
                    <span className="inline-block rotate-90"><MarkChevron /></span>
                  </button>
                </div>
                <div className="flex max-h-[1400px] flex-col gap-2.5 overflow-y-auto pt-2.5">
                  {loading && <p className="py-4 text-[12.5px] text-text-tertiary">Loading…</p>}
                  {!loading && items.length === 0 && (
                    <p className="py-4 text-[12.5px] text-text-tertiary">{count ? "More assets in this lane are available below." : "None in view."}</p>
                  )}
                  {items.map((r) => (
                    <AssetCard key={r.asset_id} r={r} onOpen={() => setOpen(r)} />
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      )}

      {/* Cards, the Creative Testing grid — ranked rather than laned, so
          it reads as "every asset, best first" instead of as a queue.
          Same AssetCard the board uses, so the two never drift: one
          card, one component, both results on it. */}
      {view === "cards" && (
        <div>
          {loading && <p className="py-5 text-[13px] text-text-tertiary">Loading…</p>}
          {!loading && (data?.rows.length ?? 0) === 0 && (
            <p className="py-5 text-[13px] text-text-tertiary">No assets match these filters.</p>
          )}
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-4">
            {(data?.rows ?? []).map((r) => (
              <AssetCard key={r.asset_id} r={r} onOpen={() => setOpen(r)} showPreview />
            ))}
          </div>
        </div>
      )}

      {view === "table" && (
        <div className="-mx-1 overflow-x-auto px-1">
          <table className="w-full min-w-[1040px] border-collapse">
            <thead>
              <tr className="border-b border-border-primary bg-bg-muted">
                {([["Preview", "left"], ["Asset", "left"], ["Current result", "left"], ["First win", "right"],
                   ["Iterations", "right"], ["Lane", "left"], ["Spend", "right"],
                   ["ROAS", "right"], ["NCP", "right"], ["Cost / NCP", "right"],
                   ["Last tested", "right"]] as const).map(([h, a]) => (
                  <th key={h} className={`px-3 py-2.5 text-[10px] font-semibold uppercase tracking-[0.07em] text-text-tertiary ${
                    a === "right" ? "text-right" : "text-left"}`}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(data?.rows ?? []).map((r) => (
                <tr key={r.asset_id} onClick={() => setOpen(r)}
                    className="cursor-pointer border-b border-border-soft hover:bg-bg-surface">
                  <td className="w-20 px-3 py-2"><AssetPreviewCell asset={r} variant="compact" appearance="standard" /></td>
                  <td className="px-3 py-2 font-mono text-[12.5px]"><button type="button" onClick={(event) => { event.stopPropagation(); setOpen(r); }} aria-label={`View ads for asset ${r.asset_id}`} className="text-left hover:underline focus-visible:outline-2">{r.asset_id}</button></td>
                  <td className="px-3 py-2">
                    <span className={`px-1.5 py-0.5 text-[9.5px] font-semibold uppercase tracking-[0.05em] ${
                      RESULT_CHIP[r.current_result ?? ""] ?? "bg-bg-muted text-text-secondary"}`}>
                      {r.current_result ?? "—"}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-[12.5px] tabular-nums">
                    {r.first_win_iter != null
                      ? <span className="text-success-text">ITE {r.first_win_iter}</span>
                      : <span className="text-text-tertiary">—</span>}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-[12.5px] tabular-nums">{r.iterations}</td>
                  <td className="px-3 py-2 text-[12px] text-text-secondary">{r.lane}</td>
                  <td className="px-3 py-2 text-right font-mono text-[12.5px] tabular-nums">{money(r.spend)}</td>
                  <td className="px-3 py-2 text-right font-mono text-[12.5px] tabular-nums">
                    {r.roas == null ? "—" : r.roas.toFixed(2)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-[12.5px] tabular-nums">{num(r.ncp)}</td>
                  <td className="px-3 py-2 text-right font-mono text-[12.5px] tabular-nums">
                    {r.cost_per_ncp == null ? "—" : `₹${nf.format(Math.round(r.cost_per_ncp))}`}
                  </td>
                  <td className="px-3 py-2 text-right text-[12px] text-text-tertiary">{day(r.last_tested)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && !loading && <div className="flex flex-wrap items-center gap-3 text-[12px] text-text-secondary">
        <span>Showing {num(data.rows.length)} of {num(data.total)} matching assets</span>
        {data.rows.length < data.total && <button type="button" disabled={loadingMore} onClick={loadMore} className="border border-border-primary px-3 py-2 hover:bg-bg-surface disabled:cursor-wait">{loadingMore ? "Loading more…" : "Load more assets"}</button>}
      </div>}
      {open && <AssetAnalysisDrawer key={open.asset_id} row={open} onClose={closeDrawer} />}
    </div>
  );
}
