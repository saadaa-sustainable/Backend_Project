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
  TableFrame,
  filterControlClass,
} from "./SectionChrome";

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

  const [data, setData] = useState<CampaignTrackerResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const filters = useMemo(
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
  );

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
        <TableFrame
          footer={
            <>
              <span className="text-[11.5px] text-text-tertiary">
                Showing {num(rows.length)} of {num(data?.matched)} campaigns
                {data && data.matched > rows.length ? " — raise Rows to see the rest" : ""}
              </span>
              <span className="text-[11.5px] text-text-tertiary">
                A tinted row is spending with no new ad in {data?.stale_days ?? staleDays} days
              </span>
            </>
          }
        >
          <table className="w-full border-collapse text-[12.5px]">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-text-tertiary">
                {[
                  ["Campaign", "The campaign's name as Meta holds it."],
                  ["Status", "Effective status, which reflects parent state too."],
                  ["Account", ""],
                  ["Ad sets", "Total ad sets, with active in brackets."],
                  ["Ads", "Total ads, with active in brackets."],
                  ["New 7d", "Ads CREATED in the last 7 days. A creation count, not a delivery count."],
                  ["New 30d", "Ads created in the last 30 days."],
                  ["Newest ad", "Created date of the most recent ad. A dash means the campaign has no ads."],
                  ["Days since", "Days since that newest ad was created."],
                  ["Spend 7d", "Meta spend over the last 7 days, summed from its ads."],
                ].map(([label, title]) => (
                  <th
                    key={label}
                    title={title || undefined}
                    className={`border-b border-border-primary px-3 py-2 font-medium ${
                      label === "Campaign" || label === "Status" || label === "Account"
                        ? "text-left"
                        : "text-right"
                    }`}
                  >
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const stale = isStale(r);
                return (
                  <tr key={r.campaign_id} className={stale ? "bg-warning-bg/40" : undefined}>
                    <td
                      className="max-w-[320px] truncate border-b border-border-soft px-3 py-1.5 text-text-primary"
                      title={`${r.campaign_name} · ${r.campaign_id}`}
                    >
                      {r.campaign_name}
                    </td>
                    <td className="border-b border-border-soft px-3 py-1.5 text-text-secondary">
                      {r.status ?? "—"}
                    </td>
                    <td
                      className="max-w-[140px] truncate border-b border-border-soft px-3 py-1.5 text-text-secondary"
                      title={r.account_name ?? ""}
                    >
                      {r.account_name ?? "—"}
                    </td>
                    <td className="border-b border-border-soft px-3 py-1.5 text-right font-mono text-[11px] text-text-primary">
                      {num(r.adsets)}{" "}
                      <span className="text-text-tertiary">({num(r.adsets_active)})</span>
                    </td>
                    <td className="border-b border-border-soft px-3 py-1.5 text-right font-mono text-[11px] text-text-primary">
                      {num(r.ads)} <span className="text-text-tertiary">({num(r.ads_active)})</span>
                    </td>
                    <td
                      className={`border-b border-border-soft px-3 py-1.5 text-right font-mono text-[11px] ${
                        r.ads_added_7d > 0 ? "font-semibold text-success-text" : "text-text-primary"
                      }`}
                    >
                      {num(r.ads_added_7d)}
                    </td>
                    <td className="border-b border-border-soft px-3 py-1.5 text-right font-mono text-[11px] text-text-primary">
                      {num(r.ads_added_30d)}
                    </td>
                    <td className="border-b border-border-soft px-3 py-1.5 text-right font-mono text-[11px] text-text-secondary">
                      {r.newest_ad ?? "—"}
                    </td>
                    <td
                      className={`border-b border-border-soft px-3 py-1.5 text-right font-mono text-[11px] ${
                        stale ? "font-semibold text-warning-text" : "text-text-primary"
                      }`}
                      title={
                        stale
                          ? `Spending ₹${num(r.spend_7d)} over 7 days on creative last refreshed ${r.days_since_new_ad} days ago`
                          : undefined
                      }
                    >
                      {num(r.days_since_new_ad)}
                    </td>
                    <td className="border-b border-border-soft px-3 py-1.5 text-right font-mono text-[11px] text-text-primary">
                      {num(r.spend_7d)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </TableFrame>
      )}

      <p className="text-[11.5px] text-text-tertiary">
        Counts come from the Meta entity tables and are as current as the last entity refresh,
        not live from Meta. &ldquo;New&rdquo; counts an ad&rsquo;s creation date, so an ad made
        today appears here before it has spent anything.
      </p>
    </div>
  );
}
