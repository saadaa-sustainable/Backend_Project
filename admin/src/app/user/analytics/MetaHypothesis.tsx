"use client";

import { Fragment, useEffect, useMemo, useState } from "react";

import {
  ApiError,
  HypothesisResponse,
  HypothesisRow,
  fetchMetaHypotheses,
} from "@/lib/api";
import { ExportButton } from "@/components/ExportButton";
import { AddHypothesis } from "./AddHypothesis";
import {
  FigureBand,
  FilterCell,
  SectionHeader,
  TableFrame,
  filterControlClass,
} from "./SectionChrome";

/**
 * The team's hypothesis-testing register, as they record it.
 *
 * Meta has no notion of an experiment, so the sheet IS the register and
 * this section reads it back with the sheet's own headers. Every column
 * is shown; a test is never dropped for failing to resolve to a Meta
 * entity, because an unmatched test is still a real test and hiding it
 * would make the register look smaller than it is.
 *
 * Long free-text fields (hypothesis, insights, outcome) are the point of
 * the register, not noise -- so a row expands rather than truncating
 * them behind a tooltip nobody opens.
 */

const SORT_OPTIONS: { value: string; label: string }[] = [
  { value: "launch_date", label: "Launch date" },
  { value: "test_date", label: "Test date" },
  { value: "completion_date", label: "Completion date" },
  { value: "test_category", label: "Category" },
  { value: "test_status", label: "Status" },
  { value: "test_result", label: "Result" },
  { value: "row_index", label: "Sheet order" },
];

/** Status and result read as judgements, so they carry colour. */
function statusClass(v: string | null): string {
  switch ((v || "").toLowerCase()) {
    case "done": return "text-success-text";
    case "ongoing": return "text-text-primary font-medium";
    case "dropped": return "text-warning-text";
    default: return "text-text-secondary";
  }
}
function resultClass(v: string | null): string {
  const s = (v || "").toLowerCase();
  if (s.startsWith("success")) return "text-success-text font-medium";
  if (s.startsWith("fail")) return "text-warning-text font-medium";
  return "text-text-secondary";
}

/** Every column the sheet has, in the sheet's order.
 *
 *  `w` is a min-width in px. The table scrolls horizontally rather than
 *  squeezing 25 columns into the viewport -- at that count, fitting them
 *  all on screen would leave each one too narrow to read, so the width
 *  is set by what the content needs and the container scrolls. */
const SHEET_COLUMNS: {
  key: keyof HypothesisRow;
  label: string;
  w: number;
  mono?: boolean;
}[] = [
  { key: "test_date",           label: "Date",                        w: 110, mono: true },
  { key: "month_of_testing",    label: "Month of testing",            w: 120 },
  { key: "test_category",       label: "Test Category",               w: 130 },
  { key: "hypothesis_code",     label: "Hypothesis Code",             w: 120, mono: true },
  { key: "hypothesis",          label: "Hypothesis & Objective",      w: 420 },
  { key: "test_status",         label: "Test Status",                 w: 110 },
  { key: "primary_kpi",         label: "Primary KPI",                 w: 140 },
  { key: "success_criteria",    label: "Success Criteria",            w: 280 },
  { key: "test_threshold",      label: "Test Threshold",              w: 120 },
  { key: "confidence_interval", label: "confidence interval",         w: 120 },
  { key: "supporting_metrics",  label: "supp metrics",                w: 220 },
  { key: "budget_per_day",      label: "Budget Allocated/Day",        w: 150 },
  { key: "launch_date",         label: "Launch Date",                 w: 110, mono: true },
  { key: "ad_account",          label: "Ad Account",                  w: 140 },
  { key: "entity_raw",          label: "Campaign/Adset Name/ Ad Name", w: 260 },
  { key: "completion_date",     label: "Completion Date",             w: 120, mono: true },
  { key: "total_ad_spend",      label: "Total Ad Spend",              w: 130, mono: true },
  { key: "performance_summary", label: "Performance Summary",         w: 280 },
  { key: "insight_audience",    label: "Key Insights - Audience",     w: 280 },
  { key: "insight_creative",    label: "Key Insights - Creative",     w: 240 },
  { key: "insight_extra",       label: "Key Insights - Extra",        w: 260 },
  { key: "kpi_change",          label: "KPI Change (Before vs After)", w: 200 },
  { key: "outcome_next_steps",  label: "Outcome & Next Steps",        w: 300 },
  { key: "detail_link",         label: "Test Detail Link",            w: 150 },
  { key: "test_result",         label: "Test Result",                 w: 130 },
];

/** Not in the sheet. The dashboard's own addition: what the typed name
 *  in `Campaign/Adset Name/ Ad Name` actually resolves to in Meta. Kept
 *  last so the sheet's own columns read in their original order. */
const MATCH_COLUMN_WIDTH = 240;

function opts(counts: Record<string, number> | undefined): [string, number][] {
  return Object.entries(counts ?? {}).sort((a, b) => b[1] - a[1]);
}

export function MetaHypothesis() {
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");
  const [result, setResult] = useState("");
  const [search, setSearch] = useState("");
  const [onlyMatched, setOnlyMatched] = useState(false);
  const [sort, setSort] = useState("launch_date");
  const [direction, setDirection] = useState<"asc" | "desc">("desc");

  //: Bumped after a save. Part of the fetch key so a new test appears
  //: without the filters being touched.
  const [reload, setReload] = useState(0);
  const [data, setData] = useState<HypothesisResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const filters = useMemo(
    () => ({
      category: category || undefined,
      status: status || undefined,
      result: result || undefined,
      search: search.trim() || undefined,
      only_matched: onlyMatched,
      sort,
      direction,
      limit: 500,
    }),
    [category, status, result, search, onlyMatched, sort, direction],
  );

  //: Categories and KPIs already in the register, offered to the form so
  //: a new test joins an existing bucket rather than inventing a
  //: near-duplicate of one.
  const categories = useMemo(
    () => Object.keys(data?.by_category ?? {}).filter((k) => k !== "(blank)").sort(),
    [data?.by_category],
  );
  const kpis = useMemo(
    () => [...new Set((data?.rows ?? [])
      .map((r) => r.primary_kpi)
      .filter((k): k is string => !!k))].sort(),
    [data],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchMetaHypotheses(filters)
      .then((r) => { if (!cancelled) setData(r); })
      .catch((e) => { if (!cancelled) setError(e instanceof ApiError ? e.message : String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [filters, reload]);

  const rows: HypothesisRow[] = data?.rows ?? [];

  return (
    <div className="flex flex-col gap-5">
      <SectionHeader title="Meta Hypothesis">
        <span className="text-[11.5px] text-text-tertiary">
          Mirrored from the team&rsquo;s testing sheet
          {data?.ingested_at ? ` · ${data.ingested_at.slice(0, 10)}` : ""}
          {data?.dashboard_rows ? ` · ${data.dashboard_rows} added here` : ""}
        </span>
      </SectionHeader>

      <FigureBand
        compact
        figures={[
          { label: "Tests recorded", value: String(data?.sheet_rows ?? "—") },
          { label: "Showing", value: String(data?.matched ?? "—") },
          { label: "Done", value: String(data?.by_status?.["Done"] ?? 0) },
          { label: "Ongoing", value: String(data?.by_status?.["Ongoing"] ?? 0) },
          {
            label: "Linked to a Meta entity",
            value: String(data?.resolved ?? "—"),
            title:
              "Tests whose typed campaign or ad set name resolves to something in Meta. The name column is hand-typed, so most do not — those tests are still shown, they just carry no Meta metrics.",
          },
        ]}
      />

      <AddHypothesis
        categories={categories}
        kpis={kpis}
        onSaved={() => setReload((n) => n + 1)}
      />

      <div className="flex flex-wrap items-end gap-3">
        <FilterCell label="Category" className="w-48" htmlFor="h-cat">
          <select id="h-cat" value={category} onChange={(e) => setCategory(e.target.value)} className={filterControlClass}>
            <option value="">All</option>
            {opts(data?.by_category).map(([k, n]) => (
              <option key={k} value={k}>{k} ({n})</option>
            ))}
          </select>
        </FilterCell>

        <FilterCell label="Status" className="w-40" htmlFor="h-status">
          <select id="h-status" value={status} onChange={(e) => setStatus(e.target.value)} className={filterControlClass}>
            <option value="">All</option>
            {opts(data?.by_status).map(([k, n]) => (
              <option key={k} value={k}>{k} ({n})</option>
            ))}
          </select>
        </FilterCell>

        <FilterCell label="Result" className="w-44" htmlFor="h-result">
          <select id="h-result" value={result} onChange={(e) => setResult(e.target.value)} className={filterControlClass}>
            <option value="">All</option>
            {opts(data?.by_result).map(([k, n]) => (
              <option key={k} value={k}>{k} ({n})</option>
            ))}
          </select>
        </FilterCell>

        <FilterCell label="Search" className="w-64" htmlFor="h-search">
          <input id="h-search" value={search} onChange={(e) => setSearch(e.target.value)}
                 placeholder="hypothesis, code, entity, KPI…" className={filterControlClass} />
        </FilterCell>

        <FilterCell label="Sort by" className="w-44" htmlFor="h-sort">
          <select id="h-sort" value={sort} onChange={(e) => setSort(e.target.value)} className={filterControlClass}>
            {SORT_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </FilterCell>

        <FilterCell label="Direction" className="w-32" htmlFor="h-dir">
          <select id="h-dir" value={direction} onChange={(e) => setDirection(e.target.value as "asc" | "desc")} className={filterControlClass}>
            <option value="desc">Newest first</option>
            <option value="asc">Oldest first</option>
          </select>
        </FilterCell>

        <label className="flex items-center gap-2 pb-1.5 text-[13px] text-text-secondary">
          <input type="checkbox" checked={onlyMatched} onChange={(e) => setOnlyMatched(e.target.checked)} />
          Only tests linked to Meta
        </label>

        <div className="ml-auto pb-1">
          <ExportButton rows={rows as unknown as Record<string, unknown>[]}
                        filename="meta_hypotheses" disabled={loading || !rows.length} />
        </div>
      </div>

      {error && (
        <p className="rounded-md border border-warning-border bg-warning-bg px-4 py-3 text-sm text-warning-text">{error}</p>
      )}

      {loading && !rows.length ? (
        <p className="py-8 text-sm text-text-secondary">Loading tests…</p>
      ) : !rows.length ? (
        <p className="py-8 text-sm text-text-secondary">No tests match these filters.</p>
      ) : (
        <TableFrame
          footer={
            <>
              <span className="text-[11.5px] text-text-tertiary">
                {rows.length} of {data?.sheet_rows ?? 0} tests · scroll sideways for every sheet column
              </span>
              <span className="text-[11.5px] text-text-tertiary">
                A dash under Meta entity means the typed name matches nothing in Meta
              </span>
            </>
          }
        >
          <div className="overflow-x-auto border border-border-primary bg-bg-white">
          <table className="border-collapse bg-bg-white text-[12.5px]">
            <thead>
              <tr className="bg-bg-white text-left text-[11px] uppercase tracking-wide text-text-tertiary">
                {SHEET_COLUMNS.map((c) => (
                  <th
                    key={c.key}
                    style={{ minWidth: c.w }}
                    className="whitespace-normal border-b border-r border-border-soft px-3 py-2 align-bottom font-medium last:border-r-0"
                  >
                    {c.label}
                  </th>
                ))}
                <th
                  style={{ minWidth: MATCH_COLUMN_WIDTH }}
                  className="whitespace-normal border-b border-border-soft px-3 py-2 align-bottom font-medium"
                  title="Not from the sheet: what the typed name resolves to in Meta. A ~ marks a fuzzy match."
                >
                  Meta entity (linked)
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="bg-bg-white align-top hover:bg-bg-muted/40">
                  {SHEET_COLUMNS.map((c) => {
                    const v = r[c.key] as string | null;
                    const base =
                      "border-b border-r border-border-soft px-3 py-1.5 align-top last:border-r-0 break-words";
                    if (c.key === "detail_link") {
                      return (
                        <td key={c.key} style={{ minWidth: c.w }} className={`${base} text-text-secondary`}>
                          {v ? (
                            <a href={v} target="_blank" rel="noopener noreferrer"
                               className="text-text-link underline underline-offset-2">
                              Open
                            </a>
                          ) : "—"}
                        </td>
                      );
                    }
                    const tone =
                      c.key === "test_status" ? statusClass(v)
                      : c.key === "test_result" ? resultClass(v)
                      : "text-text-primary";
                    return (
                      <td
                        key={c.key}
                        style={{ minWidth: c.w }}
                        className={`${base} ${tone} ${c.mono ? "font-mono text-[11px]" : ""} whitespace-pre-wrap`}
                      >
                        {v ?? "—"}
                        {c.key === "test_date" && r.source === "dashboard" && (
                          <span className="ml-1 rounded bg-bg-muted px-1 py-0.5 font-sans text-[9px] uppercase tracking-wide text-text-tertiary">
                            added here
                          </span>
                        )}
                      </td>
                    );
                  })}
                  <td
                    style={{ minWidth: MATCH_COLUMN_WIDTH }}
                    className="break-words border-b border-border-soft px-3 py-1.5 align-top text-text-secondary"
                  >
                    {r.matched_name
                      ? `${r.matched_name}${r.matched_level?.endsWith("~") ? " ~" : ""}`
                      : <span className="text-text-tertiary">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </TableFrame>
      )}

      <p className="text-[11.5px] text-text-tertiary">
        Meta exposes no experiment object, so this section mirrors the team&rsquo;s own testing
        sheet rather than measuring anything itself. Only {data?.resolved ?? 0} of{" "}
        {data?.sheet_rows ?? 0} tests resolve to a campaign or ad set, because the name column is
        typed by hand; the rest are shown in full but carry no Meta metrics.
      </p>
    </div>
  );
}
