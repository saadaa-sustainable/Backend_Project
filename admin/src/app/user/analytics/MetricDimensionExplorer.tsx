"use client";

import { useEffect, useMemo, useState } from "react";
import { ApiError } from "@/lib/api";
import { BarChart } from "./charts/BarChart";
import { LineChart } from "./charts/LineChart";
import { BubbleChart } from "./charts/BubbleChart";

export interface ExplorerField {
  key: string;
  label: string;
}

export interface ExplorerDataset {
  key: string;
  label: string;
  date_dimension: string | null;
  dimensions: ExplorerField[];
  metrics: ExplorerField[];
}

export interface ExplorerSchemaResponse {
  datasets: ExplorerDataset[];
}

export interface ExplorerQueryResponse {
  columns: string[];
  rows: Record<string, string | number | null>[];
}

interface Props {
  intro: string;
  fetchSchema: () => Promise<ExplorerSchemaResponse>;
  runQuery: (params: {
    dataset: string;
    dimensions: string[];
    metrics: string[];
    date_from?: string;
    date_to?: string;
    limit?: number;
  }) => Promise<ExplorerQueryResponse>;
}

function toggle(list: string[], key: string): string[] {
  return list.includes(key) ? list.filter((k) => k !== key) : [...list, key];
}

function formatCell(value: string | number | null): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return value.toLocaleString();
  const asNum = Number(value);
  if (!Number.isNaN(asNum) && value.trim() !== "" && /^-?\d+(\.\d+)?$/.test(value)) {
    return asNum.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  return value;
}

function asNumber(v: string | number | null): number {
  if (v === null || v === undefined) return 0;
  return typeof v === "number" ? v : Number(v) || 0;
}

type ViewMode = "table" | "bar" | "line" | "bubble";

export function MetricDimensionExplorer({ intro, fetchSchema, runQuery }: Props) {
  const [schema, setSchema] = useState<ExplorerSchemaResponse | null>(null);
  const [schemaError, setSchemaError] = useState<string | null>(null);

  const [datasetKey, setDatasetKey] = useState<string>("");
  const [dimensions, setDimensions] = useState<string[]>([]);
  const [metrics, setMetrics] = useState<string[]>([]);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [dimensionFilter, setDimensionFilter] = useState("");
  const [metricFilter, setMetricFilter] = useState("");

  const [columns, setColumns] = useState<string[]>([]);
  const [rows, setRows] = useState<Record<string, string | number | null>[]>([]);
  const [loading, setLoading] = useState(false);
  const [queryError, setQueryError] = useState<string | null>(null);
  const [hasRun, setHasRun] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>("table");
  // Which metrics feed the chart, and (for bubble) which act as x/y/size --
  // separate from the query's own metric selection so switching chart type
  // doesn't force re-running the query.
  const [chartMetrics, setChartMetrics] = useState<string[]>([]);
  const [bubbleX, setBubbleX] = useState("");
  const [bubbleY, setBubbleY] = useState("");
  const [bubbleSize, setBubbleSize] = useState("");

  useEffect(() => {
    fetchSchema()
      .then((res) => {
        setSchema(res);
        if (res.datasets.length > 0) setDatasetKey(res.datasets[0].key);
      })
      .catch((err: unknown) =>
        setSchemaError(err instanceof ApiError ? err.message : "Could not reach the FastAPI backend. Is it running?"),
      );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const dataset: ExplorerDataset | undefined = useMemo(
    () => schema?.datasets.find((d) => d.key === datasetKey),
    [schema, datasetKey],
  );

  const visibleDimensions = useMemo(
    () =>
      dataset?.dimensions.filter((d) => d.label.toLowerCase().includes(dimensionFilter.toLowerCase())) ?? [],
    [dataset, dimensionFilter],
  );
  const visibleMetrics = useMemo(
    () => dataset?.metrics.filter((m) => m.label.toLowerCase().includes(metricFilter.toLowerCase())) ?? [],
    [dataset, metricFilter],
  );

  function selectDataset(key: string) {
    setDatasetKey(key);
    setDimensions([]);
    setMetrics([]);
    setColumns([]);
    setRows([]);
    setHasRun(false);
    setDimensionFilter("");
    setMetricFilter("");
  }

  async function generate() {
    if (!dataset || metrics.length === 0) return;
    setLoading(true);
    setQueryError(null);
    try {
      const res = await runQuery({
        dataset: dataset.key,
        dimensions,
        metrics,
        date_from: dataset.date_dimension && dateFrom ? dateFrom : undefined,
        date_to: dataset.date_dimension && dateTo ? dateTo : undefined,
        limit: 200,
      });
      setColumns(res.columns);
      setRows(res.rows);
      setHasRun(true);
      setChartMetrics(metrics);
      setBubbleX(metrics[0] ?? "");
      setBubbleY(metrics[1] ?? metrics[0] ?? "");
      setBubbleSize(metrics[2] ?? metrics[0] ?? "");
    } catch (err) {
      setQueryError(err instanceof ApiError ? err.message : "Could not run this query.");
    } finally {
      setLoading(false);
    }
  }

  // Chart data is a live reshape of the SAME query result rows -- the
  // dimension columns (query's own selection) become categories/labels,
  // the metric columns become series. Re-derives on every rows/metric
  // change, so switching chart type or the metric checklist regenerates
  // instantly with no new request.
  const dimensionKeys = useMemo(() => columns.filter((c) => !metrics.includes(c)), [columns, metrics]);
  const categoryLabel = (row: Record<string, string | number | null>) =>
    dimensionKeys.length > 0 ? dimensionKeys.map((k) => String(row[k] ?? "—")).join(" · ") : "Total";

  const barLineData = useMemo(() => {
    const categories = rows.map((r) => categoryLabel(r));
    const series = chartMetrics.map((m) => ({
      name: dataset?.metrics.find((x) => x.key === m)?.label ?? m,
      values: rows.map((r) => asNumber(r[m])),
    }));
    return { categories, series };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, chartMetrics, dimensionKeys, dataset]);

  const bubbleData = useMemo(() => {
    if (!bubbleX || !bubbleY) return [];
    return rows.map((r) => ({
      label: categoryLabel(r),
      x: asNumber(r[bubbleX]),
      y: asNumber(r[bubbleY]),
      size: bubbleSize ? asNumber(r[bubbleSize]) : 1,
    }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, bubbleX, bubbleY, bubbleSize, dimensionKeys]);

  if (schemaError) {
    return <div className="rounded-md border border-error-mid bg-error-bg p-3 text-sm text-error-text">{schemaError}</div>;
  }
  if (!schema) {
    return <p className="text-sm text-text-secondary">Loading…</p>;
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-text-secondary">{intro}</p>

      {/* Dataset picker */}
      <div className="flex flex-wrap gap-1.5">
        {schema.datasets.map((ds) => (
          <button
            key={ds.key}
            onClick={() => selectDataset(ds.key)}
            className={`rounded-md border px-3 py-1.5 text-sm font-medium transition-colors ${
              datasetKey === ds.key
                ? "border-accent-yellow bg-accent-yellow-bg text-accent-yellow"
                : "border-border-primary bg-white text-text-secondary hover:bg-bg-surface"
            }`}
          >
            {ds.label}
          </button>
        ))}
      </div>

      {dataset && (
        <div className="grid grid-cols-1 gap-4 rounded-lg border border-border-primary bg-white shadow-sm p-4 md:grid-cols-2">
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <p className="text-xs font-medium uppercase tracking-wide text-text-secondary">
                Dimensions <span className="font-normal normal-case text-text-tertiary">(group by · {dataset.dimensions.length})</span>
              </p>
            </div>
            {dataset.dimensions.length > 12 && (
              <input
                value={dimensionFilter}
                onChange={(e) => setDimensionFilter(e.target.value)}
                placeholder="Filter dimensions…"
                className="mb-1.5 w-full rounded-md border border-border-primary px-2 py-1 text-xs text-text-primary placeholder:text-text-tertiary focus:border-accent-yellow focus:outline-none"
              />
            )}
            <div className="flex max-h-56 flex-wrap gap-1.5 overflow-y-auto">
              {visibleDimensions.map((dim) => (
                <button
                  key={dim.key}
                  onClick={() => setDimensions((prev) => toggle(prev, dim.key))}
                  className={`rounded-full border px-2.5 py-1 text-xs font-medium transition-colors ${
                    dimensions.includes(dim.key)
                      ? "border-accent-indigo bg-accent-indigo-bg text-info-text"
                      : "border-border-primary bg-white text-text-secondary hover:bg-bg-surface"
                  }`}
                >
                  {dim.label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <p className="text-xs font-medium uppercase tracking-wide text-text-secondary">
                Metrics <span className="font-normal normal-case text-text-tertiary">(aggregate · {dataset.metrics.length})</span>
              </p>
            </div>
            {dataset.metrics.length > 12 && (
              <input
                value={metricFilter}
                onChange={(e) => setMetricFilter(e.target.value)}
                placeholder="Filter metrics…"
                className="mb-1.5 w-full rounded-md border border-border-primary px-2 py-1 text-xs text-text-primary placeholder:text-text-tertiary focus:border-accent-yellow focus:outline-none"
              />
            )}
            <div className="flex max-h-56 flex-wrap gap-1.5 overflow-y-auto">
              {visibleMetrics.map((m) => (
                <button
                  key={m.key}
                  onClick={() => setMetrics((prev) => toggle(prev, m.key))}
                  className={`rounded-full border px-2.5 py-1 text-xs font-medium transition-colors ${
                    metrics.includes(m.key)
                      ? "border-accent-yellow bg-accent-yellow-bg text-accent-yellow"
                      : "border-border-primary bg-white text-text-secondary hover:bg-bg-surface"
                  }`}
                >
                  {m.label}
                </button>
              ))}
            </div>
          </div>

          {dataset.date_dimension && (
            <div className="flex items-center gap-2 md:col-span-2">
              <label className="text-xs text-text-secondary">From</label>
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                className="rounded-md border border-border-primary px-2 py-1 text-xs text-text-primary focus:border-accent-yellow focus:outline-none"
              />
              <label className="text-xs text-text-secondary">To</label>
              <input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                className="rounded-md border border-border-primary px-2 py-1 text-xs text-text-primary focus:border-accent-yellow focus:outline-none"
              />
            </div>
          )}

          <div className="md:col-span-2">
            <button
              onClick={generate}
              disabled={metrics.length === 0 || loading}
              className="rounded-md bg-accent-yellow px-4 py-1.5 text-sm font-medium text-text-primary transition-colors hover:bg-accent-yellow-hover disabled:opacity-40"
            >
              {loading ? "Generating…" : "Generate"}
            </button>
            {metrics.length === 0 && (
              <span className="ml-2 text-xs text-text-tertiary">Pick at least one metric.</span>
            )}
          </div>
        </div>
      )}

      {queryError && <div className="rounded-md border border-error-mid bg-error-bg p-3 text-sm text-error-text">{queryError}</div>}

      {hasRun && (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex overflow-hidden rounded-md border border-border-primary">
              {(["table", "bar", "line", "bubble"] as ViewMode[]).map((mode) => (
                <button
                  key={mode}
                  onClick={() => setViewMode(mode)}
                  className={`px-3 py-1.5 text-xs font-medium capitalize transition-colors ${
                    viewMode === mode ? "bg-accent-yellow text-text-primary" : "bg-white text-text-secondary hover:bg-bg-surface"
                  }`}
                >
                  {mode}
                </button>
              ))}
            </div>

            {viewMode !== "table" && viewMode !== "bubble" && (
              <div className="flex flex-wrap gap-1.5">
                {metrics.map((m) => (
                  <button
                    key={m}
                    onClick={() => setChartMetrics((prev) => toggle(prev, m))}
                    className={`rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors ${
                      chartMetrics.includes(m)
                        ? "border-accent-indigo bg-accent-indigo-bg text-info-text"
                        : "border-border-primary bg-white text-text-tertiary hover:bg-bg-surface"
                    }`}
                  >
                    {dataset?.metrics.find((x) => x.key === m)?.label ?? m}
                  </button>
                ))}
              </div>
            )}

            {viewMode === "bubble" && (
              <div className="flex flex-wrap items-center gap-2 text-xs text-text-secondary">
                <label>
                  X:
                  <select value={bubbleX} onChange={(e) => setBubbleX(e.target.value)} className="ml-1 rounded border border-border-primary px-1 py-0.5">
                    {metrics.map((m) => (
                      <option key={m} value={m}>
                        {dataset?.metrics.find((x) => x.key === m)?.label ?? m}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Y:
                  <select value={bubbleY} onChange={(e) => setBubbleY(e.target.value)} className="ml-1 rounded border border-border-primary px-1 py-0.5">
                    {metrics.map((m) => (
                      <option key={m} value={m}>
                        {dataset?.metrics.find((x) => x.key === m)?.label ?? m}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Size:
                  <select value={bubbleSize} onChange={(e) => setBubbleSize(e.target.value)} className="ml-1 rounded border border-border-primary px-1 py-0.5">
                    {metrics.map((m) => (
                      <option key={m} value={m}>
                        {dataset?.metrics.find((x) => x.key === m)?.label ?? m}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            )}
          </div>

          {viewMode === "table" && (
            <div className="overflow-x-auto rounded-lg border border-border-primary bg-white shadow-sm">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-border-primary text-xs text-text-secondary">
                    {columns.map((c) => (
                      <th key={c} className="px-4 py-2 font-medium">
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, i) => (
                    <tr key={i} className="border-b border-border-soft hover:bg-bg-surface">
                      {columns.map((c) => (
                        <td key={c} className="px-4 py-2 text-text-primary">
                          {formatCell(row[c])}
                        </td>
                      ))}
                    </tr>
                  ))}
                  {rows.length === 0 && (
                    <tr>
                      <td colSpan={columns.length || 1} className="px-4 py-6 text-center text-text-secondary">
                        No rows for this selection.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}

          {viewMode === "bar" && (
            <div className="rounded-lg border border-border-primary bg-white shadow-sm p-4">
              <BarChart categories={barLineData.categories} series={barLineData.series} />
            </div>
          )}

          {viewMode === "line" && (
            <div className="rounded-lg border border-border-primary bg-white shadow-sm p-4">
              <LineChart categories={barLineData.categories} series={barLineData.series} />
            </div>
          )}

          {viewMode === "bubble" && (
            <div className="rounded-lg border border-border-primary bg-white shadow-sm p-4">
              <BubbleChart
                points={bubbleData}
                xLabel={dataset?.metrics.find((x) => x.key === bubbleX)?.label ?? bubbleX}
                yLabel={dataset?.metrics.find((x) => x.key === bubbleY)?.label ?? bubbleY}
                sizeLabel={dataset?.metrics.find((x) => x.key === bubbleSize)?.label ?? bubbleSize}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
