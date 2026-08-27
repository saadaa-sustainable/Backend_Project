"use client";

import { useEffect, useState } from "react";
import {
  ApiError,
  createCustomMetric,
  fetchTableColumns,
  fetchTables,
  type CustomMetricResponse,
  type MetricOperation,
  type OperandBType,
  type TableColumn,
} from "@/lib/api";

const OP_OPTIONS: { value: MetricOperation; label: string; symbol: string }[] = [
  { value: "divide", label: "Divide", symbol: "÷" },
  { value: "multiply", label: "Multiply", symbol: "×" },
  { value: "add", label: "Add", symbol: "+" },
  { value: "subtract", label: "Subtract", symbol: "−" },
];

export function CustomizeColumns() {
  const [tableNames, setTableNames] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedTable, setSelectedTable] = useState<string | null>(null);

  useEffect(() => {
    fetchTables()
      .then((res) => {
        const names = res.tables.map((t) => t.name).sort();
        setTableNames(names);
        setSelectedTable((prev) => prev ?? names[0] ?? null);
      })
      .catch((err: unknown) =>
        setError(err instanceof ApiError ? err.message : "Could not reach the FastAPI backend."),
      );
  }, []);

  if (error) {
    return (
      <div className="rounded-lg border border-error-mid bg-error-bg p-4 text-sm text-error-text">
        {error}
      </div>
    );
  }

  if (!tableNames) {
    return <div className="text-sm text-text-secondary">Loading tables…</div>;
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-md border border-border-primary bg-white p-4">
        <label className="mb-1 block text-xs text-text-secondary">Table</label>
        <select
          value={selectedTable ?? ""}
          onChange={(e) => setSelectedTable(e.target.value)}
          className="w-full max-w-sm rounded-md border border-border-primary bg-bg-surface px-3 py-2 font-mono text-sm text-text-primary focus:border-accent-yellow focus:outline-none"
        >
          {tableNames.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </div>

      {/* Keyed by table: switching tables should reset the form and
          reload that table's own columns, via remount. */}
      {selectedTable && <TableCustomizer key={selectedTable} table={selectedTable} />}
    </div>
  );
}

function TableCustomizer({ table }: { table: string }) {
  const [columns, setColumns] = useState<TableColumn[] | null>(null);
  const [columnsError, setColumnsError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [operation, setOperation] = useState<MetricOperation>("divide");
  const [columnA, setColumnA] = useState("");
  const [operandBType, setOperandBType] = useState<OperandBType>("column");
  const [operandBColumn, setOperandBColumn] = useState("");
  const [operandBConstant, setOperandBConstant] = useState("");
  const [asPercentage, setAsPercentage] = useState(false);

  const [preview, setPreview] = useState<CustomMetricResponse | null>(null);
  const [result, setResult] = useState<CustomMetricResponse | null>(null);
  const [busy, setBusy] = useState<"preview" | "create" | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  function loadColumns() {
    fetchTableColumns(table)
      .then((cols) => {
        setColumns(cols);
        setColumnsError(null);
        setColumnA((prev) => prev || cols.find((c) => c.kind === "numeric")?.name || "");
      })
      .catch((err: unknown) =>
        setColumnsError(err instanceof ApiError ? err.message : "Could not load columns."),
      );
  }

  useEffect(loadColumns, [table]);

  const numericColumns = columns?.filter((c) => c.kind === "numeric" || c.kind === "other") ?? [];

  const canBuild =
    name.trim().length > 0 &&
    columnA &&
    (operandBType === "column" ? Boolean(operandBColumn) : operandBConstant.trim().length > 0);

  function buildRequest(dryRun: boolean) {
    return {
      name: name.trim(),
      operation,
      column_a: columnA,
      operand_b_type: operandBType,
      operand_b_column: operandBType === "column" ? operandBColumn : null,
      operand_b_constant: operandBType === "constant" ? Number(operandBConstant) : null,
      as_percentage: operation === "divide" && asPercentage,
      dry_run: dryRun,
    };
  }

  async function handlePreview() {
    if (!canBuild) return;
    setFormError(null);
    setBusy("preview");
    try {
      const res = await createCustomMetric(table, buildRequest(true));
      setPreview(res);
      setResult(null);
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Could not reach the backend.");
    } finally {
      setBusy(null);
    }
  }

  async function handleCreate() {
    if (!canBuild) return;
    setFormError(null);
    setBusy("create");
    try {
      const res = await createCustomMetric(table, buildRequest(false));
      setResult(res);
      if (res.status === "created") {
        loadColumns(); // new metric should show up in the columns list immediately
      }
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Could not reach the backend.");
    } finally {
      setBusy(null);
    }
  }

  const opLabel = OP_OPTIONS.find((o) => o.value === operation);
  const formulaPreview = columnA
    ? `${name.trim() || "new_metric"} = (${columnA} ${opLabel?.symbol ?? ""} ${
        operandBType === "column" ? operandBColumn || "…" : operandBConstant || "…"
      })${operation === "divide" && asPercentage ? " × 100" : ""}`
    : null;

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
      {/* Create custom metric */}
      <div className="rounded-md border border-border-primary bg-white p-4">
        <h3 className="mb-3 text-sm font-medium text-text-primary">Create custom metric</h3>

        {columnsError && (
          <div className="mb-3 rounded-md border border-error-mid bg-error-bg p-3 text-sm text-error-text">
            {columnsError}
          </div>
        )}

        {columns && (
          <div className="flex flex-col gap-3">
            <div>
              <label className="mb-1 block text-xs text-text-secondary">Metric name</label>
              <input
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                  setPreview(null);
                  setResult(null);
                }}
                placeholder="CTR %"
                className="w-full rounded-md border border-border-primary bg-bg-surface px-3 py-2 text-sm text-text-primary placeholder:text-text-tertiary focus:border-accent-yellow focus:outline-none"
              />
            </div>

            <div className="grid grid-cols-[1fr_auto_1fr] items-end gap-2">
              <div>
                <label className="mb-1 block text-xs text-text-secondary">Column A</label>
                <select
                  value={columnA}
                  onChange={(e) => {
                    setColumnA(e.target.value);
                    setPreview(null);
                  }}
                  className="w-full rounded-md border border-border-primary bg-bg-surface px-2 py-2 text-sm text-text-primary focus:border-accent-yellow focus:outline-none"
                >
                  <option value="">— select —</option>
                  {columns.map((c) => (
                    <option key={c.name} value={c.name}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs text-text-secondary">Op</label>
                <select
                  value={operation}
                  onChange={(e) => {
                    setOperation(e.target.value as MetricOperation);
                    setPreview(null);
                  }}
                  className="rounded-md border border-border-primary bg-bg-surface px-2 py-2 text-sm text-text-primary focus:border-accent-yellow focus:outline-none"
                >
                  {OP_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.symbol}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs text-text-secondary">Column B</label>
                <select
                  value={operandBType === "column" ? operandBColumn : ""}
                  onChange={(e) => {
                    setOperandBType("column");
                    setOperandBColumn(e.target.value);
                    setPreview(null);
                  }}
                  className="w-full rounded-md border border-border-primary bg-bg-surface px-2 py-2 text-sm text-text-primary focus:border-accent-yellow focus:outline-none"
                >
                  <option value="">— select —</option>
                  {columns.map((c) => (
                    <option key={c.name} value={c.name}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <label className="flex items-center gap-1.5 text-xs text-text-secondary">
                <input
                  type="radio"
                  checked={operandBType === "constant"}
                  onChange={() => {
                    setOperandBType("constant");
                    setPreview(null);
                  }}
                  className="accent-accent-yellow"
                />
                or a constant:
              </label>
              <input
                value={operandBConstant}
                onChange={(e) => {
                  setOperandBType("constant");
                  setOperandBConstant(e.target.value);
                  setPreview(null);
                }}
                placeholder="e.g. 1000"
                className="w-32 rounded-md border border-border-primary bg-bg-surface px-2 py-1.5 text-xs text-text-primary placeholder:text-text-tertiary focus:border-accent-yellow focus:outline-none"
              />
              {operation === "divide" && (
                <label className="ml-auto flex items-center gap-1.5 text-xs text-text-secondary">
                  <input
                    type="checkbox"
                    checked={asPercentage}
                    onChange={(e) => {
                      setAsPercentage(e.target.checked);
                      setPreview(null);
                    }}
                    className="accent-accent-yellow"
                  />
                  Show as percentage (× 100)
                </label>
              )}
            </div>

            {formulaPreview && (
              <p className="rounded-md border border-border-primary bg-bg-surface px-3 py-2 font-mono text-xs text-text-secondary">
                {formulaPreview}
              </p>
            )}

            {formError && (
              <div className="rounded-md border border-error-mid bg-error-bg p-3 text-sm text-error-text">
                {formError}
              </div>
            )}

            <div className="flex gap-2">
              <button
                onClick={handlePreview}
                disabled={!canBuild || busy !== null}
                className="rounded-md bg-bg-muted px-4 py-2 text-sm font-medium text-text-primary transition-colors hover:bg-bg-muted border border-border-primary disabled:opacity-40"
              >
                {busy === "preview" ? "Generating…" : "Preview SQL"}
              </button>
              <button
                onClick={handleCreate}
                disabled={!canBuild || !preview || busy !== null}
                className="rounded-md bg-accent-yellow px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-yellow-hover disabled:opacity-40"
              >
                {busy === "create" ? "Adding…" : "Add to table"}
              </button>
            </div>

            {preview && !result && (
              <details className="text-xs" open>
                <summary className="cursor-pointer text-text-secondary hover:text-text-primary">
                  Generated SQL
                </summary>
                <pre className="mt-2 overflow-x-auto rounded-md border border-border-primary bg-bg-surface p-3 font-mono text-[11px] leading-relaxed text-text-primary">
                  {preview.sql}
                </pre>
              </details>
            )}

            {result && (
              <div
                className={`rounded-md border p-3 text-sm ${
                  result.status === "created"
                    ? "border-success-mid bg-success-bg text-success-text"
                    : "border-error-mid bg-error-bg text-error-text"
                }`}
              >
                {result.status === "created" ? (
                  <>Added column &quot;{result.column_name}&quot; to {table}.</>
                ) : (
                  <>Failed: {result.error}</>
                )}
                <pre className="mt-2 overflow-x-auto rounded-md border border-border-primary bg-bg-surface p-2 font-mono text-[11px] leading-relaxed text-text-secondary">
                  {result.sql}
                </pre>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Current columns */}
      <div className="rounded-md border border-border-primary bg-white p-4">
        <h3 className="mb-1 text-sm font-medium text-text-primary">
          {columns ? `${columns.length} columns` : "Columns"}
        </h3>
        <p className="mb-3 text-xs text-text-secondary font-mono">{table}</p>
        <div className="flex max-h-[480px] flex-col gap-1 overflow-y-auto">
          {columns?.map((c) => (
            <div
              key={c.name}
              className="flex items-center justify-between rounded-md border border-border-primary px-2.5 py-1.5"
            >
              <span className="font-mono text-xs text-text-primary">{c.name}</span>
              <span className="text-[10px] text-text-secondary">{c.data_type}</span>
            </div>
          ))}
        </div>
        <p className="mt-2 text-[11px] text-text-tertiary">
          Only {numericColumns.length} of these look numeric — formulas work on any column, but
          non-numeric ones will fail at execution if they don&apos;t cast cleanly.
        </p>
      </div>
    </div>
  );
}
