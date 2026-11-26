"use client";

import { useEffect, useMemo, useState } from "react";

import {
  ApiError,
  CampaignTrackerResponse,
  CampaignTrackerRow,
  fetchCampaignTracker,
} from "@/lib/api";
import { ExportButton } from "@/components/ExportButton";
import {
  FigureBand,
  FilterCell,
  SectionHeader,
  filterControlClass,
} from "./SectionChrome";
import { useDebouncedValue } from "@/lib/useDebouncedValue";
import { CampaignAnalysis } from "./CampaignAnalysis";

/**
 * Is each campaign still being given new creative?
 *
 * Every other section asks how a campaign PERFORMED. This one asks
 * whether anyone has touched it lately: how many ad sets and ads it
 * holds, when the newest ad was created, and whether it is still
 * spending on creative that stopped being refreshed weeks ago.
 *
 * The counts come from the Silver entity tables, so they are as current
 * as the last `silver_meta_entities` run -- not live from Meta.
 */

const STATUS_OPTIONS = ["ACTIVE", "PAUSED", "ARCHIVED", "all"];

/** The analysed campaign plus up to four compared with it. */
const MAX_SELECTED = 5;

const SORT_OPTIONS: { value: string; label: string }[] = [
  { value: "days_since_new_ad", label: "Days since new ad" },
  { value: "spend_7d", label: "Spend (7d)" },
  { value: "ads_added_7d", label: "Ads added (7d)" },
  { value: "ads_added_30d", label: "Ads added (30d)" },
  { value: "ads", label: "Ads" },
  { value: "ads_active", label: "Active ads" },
  { value: "adsets", label: "Ad sets" },
  { value: "newest_ad", label: "Newest ad" },
];

function num(n: number | null | undefined, digits = 0) {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("en-IN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function CampaignTracker() {
  const [status, setStatus] = useState("ACTIVE");
  const [search, setSearch] = useState("");
  const [staleDays, setStaleDays] = useState(14);
  const [onlyStale, setOnlyStale] = useState(false);
  const [sort, setSort] = useState("days_since_new_ad");
  const [direction, setDirection] = useState<"asc" | "desc">("desc");
  const [limit, setLimit] = useState(200);
  // First id is the campaign analysed; the rest are compared with it.
  const [selected, setSelected] = useState<string[]>([]);
  // Every campaign, by spend, for the pickers -- not just what the table's filters show.
  const [all, setAll] = useState<CampaignTrackerRow[]>([]);
  const [primaryText, setPrimaryText] = useState("");
  const [compareText, setCompareText] = useState("");
  useEffect(() => {
    let cancelled = false;
    fetchCampaignTracker({ status: "all", sort: "spend_7d", direction: "desc", limit: 2000 })
      .then((r) => !cancelled && setAll(r.rows))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);
  // A name shared by two campaigns gets its id appended, so each choice is unambiguous.
  const choices = useMemo(() => {
    const seen = new Map<string, number>();
    all.forEach((r) => seen.set(r.campaign_name, (seen.get(r.campaign_name) ?? 0) + 1));
    return all.map((r) => ({
      id: r.campaign_id,
      value: (seen.get(r.campaign_name) ?? 0) > 1 ? `${r.campaign_name} · ${r.campaign_id}` : r.campaign_name,
      label: `${r.status ?? ""} · ${num(r.spend_7d)} spend in 7d`,
    }));
  }, [all]);
  const idFor = (text: string) => choices.find((c) => c.value === text.trim())?.id;

  const [data, setData] = useState<CampaignTrackerResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Debounced so typing sends one request, not one per keystroke.
  const filters = useDebouncedValue(useMemo(
    () => ({
      status,
      search: search.trim() || undefined,
      stale_days: staleDays,
      only_stale: onlyStale,
      sort,
      direction,
      limit,
    }),
    [status, search, staleDays, onlyStale, sort, direction, limit],
  ));

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchCampaignTracker(filters)
      .then((r) => {
        if (!cancelled) setData(r);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof ApiError ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [filters]);

  const rows: CampaignTrackerRow[] = data?.rows ?? [];

  /** Spending now, but the creative has not been refreshed. The reason
   *  this section exists, so it is tinted rather than left to be found
   *  by reading the days column. */
  function isStale(r: CampaignTrackerRow): boolean {
    return (
      r.spend_7d > 0 &&
      (r.days_since_new_ad === null || r.days_since_new_ad > (data?.stale_days ?? staleDays))
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <SectionHeader title="Campaign Tracker">
        <span className="text-[11.5px] text-text-tertiary">
          Entity counts as of the last Meta entity refresh{data?.as_of ? ` · ${data.as_of}` : ""}
        </span>
      </SectionHeader>

      <FigureBand
        compact
        figures={[
          { label: "Campaigns", value: num(data?.campaigns) },
          { label: "Ads added, 7d", value: num(data?.ads_added_7d) },
          { label: "Ads added, 30d", value: num(data?.ads_added_30d) },
          {
            label: `Spending, no new ad in ${data?.stale_days ?? staleDays}d`,
            value: num(data?.stale_spending),
            title:
              "Campaigns that spent in the last 7 days whose newest ad is older than the staleness window. These are running on creative nobody has refreshed.",
          },
        ]}
      />

      <div className="flex flex-wrap items-end gap-3 rounded-xl border border-border-primary bg-bg-white p-4">
        <FilterCell label="Analyse campaign" className="min-w-[280px] flex-[2]" htmlFor="ct-pick">
          <input
            id="ct-pick"
            list="ct-campaigns"
            value={primaryText}
            placeholder={all.length ? `Search ${all.length} campaigns…` : "Loading campaigns…"}
            onChange={(e) => {
              setPrimaryText(e.target.value);
              const id = idFor(e.target.value);
              if (id) setSelected((s) => [id, ...s.filter((x) => x !== id)].slice(0, MAX_SELECTED));
            }}
            className={filterControlClass}
          />
        </FilterCell>
        <FilterCell label={`Compare with (up to ${MAX_SELECTED - 1})`} className="min-w-[240px] flex-[2]" htmlFor="ct-compare">
          <input
            id="ct-compare"
            list="ct-campaigns"
            value={compareText}
            disabled={!selected.length || selected.length >= MAX_SELECTED}
            placeholder={!selected.length ? "Pick a campaign first" : selected.length >= MAX_SELECTED ? "Comparison is full" : "Add a campaign…"}
            onChange={(e) => {
              const id = idFor(e.target.value);
              if (id) {
                setSelected((s) => (s.includes(id) ? s : [...s, id]));
                setCompareText("");
              } else setCompareText(e.target.value);
            }}
            className={filterControlClass}
          />
        </FilterCell>
        <datalist id="ct-campaigns">
          {choices.map((c) => (
            <option key={c.id} value={c.value} label={c.label} />
          ))}
        </datalist>
      </div>

      {selected.length > 0 && (
        <CampaignAnalysis
          ids={selected}
          onRemove={(id) => setSelected((s) => s.filter((x) => x !== id))}
          onClose={() => {
            setSelected([]);
            setPrimaryText("");
          }}
        />
      )}

      <div className="flex flex-wrap items-end gap-3">
        <FilterCell label="Status" className="w-40" htmlFor="ct-status">
          <select
            id="ct-status"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className={filterControlClass}
          >
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s === "all" ? "All" : s}
              </option>
            ))}
          </select>
        </FilterCell>

        <FilterCell label="Search campaign" className="w-64" htmlFor="ct-search">
          <input
            id="ct-search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="name contains…"
            className={filterControlClass}
          />
        </FilterCell>

        <FilterCell label="Stale after" className="w-36" htmlFor="ct-stale">
          <select
            id="ct-stale"
            value={staleDays}
            onChange={(e) => setStaleDays(Number(e.target.value))}
            className={filterControlClass}
          >
            {[7, 14, 21, 30, 60].map((d) => (
              <option key={d} value={d}>
                {d} days
              </option>
            ))}
          </select>
        </FilterCell>

        <FilterCell label="Sort by" className="w-48" htmlFor="ct-sort">
          <select
            id="ct-sort"
            value={sort}
            onChange={(e) => {
              setSort(e.target.value);
              setDirection("desc");
            }}
            className={filterControlClass}
          >
            {SORT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </FilterCell>

        <FilterCell label="Direction" className="w-32" htmlFor="ct-dir">
          <select
            id="ct-dir"
            value={direction}
            onChange={(e) => setDirection(e.target.value as "asc" | "desc")}
            className={filterControlClass}
          >
            <option value="desc">High → low</option>
            <option value="asc">Low → high</option>
          </select>
        </FilterCell>

        <FilterCell label="Rows" className="w-28" htmlFor="ct-limit">
          <select
            id="ct-limit"
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className={filterControlClass}
          >
            {[50, 200, 500, 2000].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </FilterCell>

        <label className="flex items-center gap-2 pb-1.5 text-[13px] text-text-secondary">
          <input
            type="checkbox"
            checked={onlyStale}
            onChange={(e) => setOnlyStale(e.target.checked)}
          />
          Only spending without new ads
        </label>

        <div className="ml-auto pb-1">
          <ExportButton
            rows={rows as unknown as Record<string, unknown>[]}
            filename="campaign_tracker"
            disabled={loading || !rows.length}
          />
        </div>
      </div>

      {error && (
        <p className="rounded-md border border-warning-border bg-warning-bg px-4 py-3 text-sm text-warning-text">
          {error}
        </p>
      )}

      {loading && !rows.length ? (
        <p className="py-8 text-sm text-text-secondary">Loading campaigns…</p>
      ) : !rows.length ? (
        <p className="py-8 text-sm text-text-secondary">No campaigns match these filters.</p>
      ) : (
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {rows.map((r) => {
              const stale = isStale(r);
              const on = selected[0] === r.campaign_id;
              const stat = (label: string, value: React.ReactNode, title?: string, tone = "text-text-primary") => (
                <div title={title}>
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-text-tertiary">{label}</div>
                  <div className={`font-mono text-[13px] tabular-nums ${tone}`}>{value}</div>
                </div>
              );
              return (
                <button
                  key={r.campaign_id}
                  type="button"
                  aria-pressed={on}
                  onClick={() => {
                    setSelected((s) => [r.campaign_id, ...s.filter((x) => x !== r.campaign_id)].slice(0, MAX_SELECTED));
                    setPrimaryText(r.campaign_name);
                  }}
                  className={`flex flex-col gap-3 rounded-xl border p-4 text-left shadow-sm transition-shadow hover:shadow-md ${
                    on ? "border-accent-yellow ring-1 ring-accent-yellow" : "border-border-primary"
                  } ${stale ? "bg-warning-bg/40" : "bg-bg-white"}`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate text-[13.5px] font-semibold text-text-primary" title={`${r.campaign_name} · ${r.campaign_id}`}>
                        {r.campaign_name}
                      </div>
                      <div className="truncate text-[11.5px] text-text-tertiary" title={r.account_name ?? ""}>
                        {r.account_name ?? "—"}
                      </div>
                    </div>
                    <span
                      className={`shrink-0 rounded-full px-2 py-0.5 text-[10.5px] font-semibold ${
                        r.status === "ACTIVE" ? "bg-success-bg text-success-text" : "bg-bg-muted text-text-secondary"
                      }`}
                    >
                      {r.status ?? "—"}
                    </span>
                  </div>
                  <div className="flex items-end justify-between gap-2 border-y border-border-soft py-2">
                    <div>
                      <div className="text-[10px] font-semibold uppercase tracking-wider text-text-tertiary">Spend, 7d</div>
                      <div className="text-[20px] font-semibold leading-tight tabular-nums text-text-primary">₹{num(r.spend_7d)}</div>
                    </div>
                    {stale && (
                      <span
                        className="rounded-md bg-warning-bg px-2 py-1 text-[11px] font-semibold text-warning-text"
                        title={`Spending ₹${num(r.spend_7d)} over 7 days on creative last refreshed ${r.days_since_new_ad ?? "never"} days ago`}
                      >
                        No new ad in {r.days_since_new_ad ?? "—"}d
                      </span>
                    )}
                  </div>
                  <div className="grid grid-cols-3 gap-x-3 gap-y-2">
                    {stat("Ad sets", <>{num(r.adsets)} <span className="text-text-tertiary">({num(r.adsets_active)})</span></>, "Total ad sets, with active in brackets.")}
                    {stat("Ads", <>{num(r.ads)} <span className="text-text-tertiary">({num(r.ads_active)})</span></>, "Total ads, with active in brackets.")}
                    {stat("New 7d / 30d", <>{num(r.ads_added_7d)} / {num(r.ads_added_30d)}</>, "Ads CREATED in the last 7 and 30 days.", r.ads_added_7d > 0 ? "font-semibold text-success-text" : "text-text-primary")}
                    {stat("Newest ad", r.newest_ad ?? "—", "Created date of the most recent ad.")}
                    {stat("Days since", num(r.days_since_new_ad), "Days since that newest ad was created.", stale ? "font-semibold text-warning-text" : "text-text-primary")}
                  </div>
                </button>
              );
            })}
          </div>
          <div className="flex flex-wrap justify-between gap-2 text-[11.5px] text-text-tertiary">
            <span>
              Showing {num(rows.length)} of {num(data?.matched)} campaigns
              {data && data.matched > rows.length ? " — raise Rows to see the rest" : ""} · click a card to analyse it
            </span>
            <span>A tinted card is spending with no new ad in {data?.stale_days ?? staleDays} days</span>
          </div>
        </div>
      )}

      <p className="text-[11.5px] text-text-tertiary">
        Counts come from the Meta entity tables and are as current as the last entity refresh,
        not live from Meta. &ldquo;New&rdquo; counts an ad&rsquo;s creation date, so an ad made
        today appears here before it has spent anything.
      </p>
    </div>
  );
}
