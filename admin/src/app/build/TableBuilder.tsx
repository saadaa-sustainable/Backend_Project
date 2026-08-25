"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  ApiError,
  createCustomTable,
  fetchObjectTypes,
  fetchTables,
  type CustomTableResponse,
  type ObjectTypeCount,
  type TableSchema,
} from "@/lib/api";
import { useSelection } from "@/lib/SelectionContext";
import { JoinTableBuilder } from "./JoinTableBuilder";

type Mode = "single" | "join";

export function TableBuilder() {
  const { selection } = useSelection();
  const sourceTables = useMemo(() => Object.keys(selection).sort(), [selection]);
  const [mode, setMode] = useState<Mode>("single");
  const [sourceTable, setSourceTable] = useState<string | null>(sourceTables[0] ?? null);
  const [allTables, setAllTables] = useState<TableSchema[] | null>(null);

  useEffect(() => {
    fetchTables()
      .then((res) => setAllTables(res.tables))
      .catch(() => setAllTables(null));
  }, []);

  const hasObjectTypeByTable = useMemo(
    () =>
      Object.fromEntries(
        sourceTables.map((t) => [
          t,
          allTables?.find((s) => s.name === t)?.columns.some((c) => c.name === "object_type") ?? false,
        ]),
      ),
    [sourceTables, allTables],
  );

  if (sourceTables.length === 0) {
    return (
      <div className="rounded-md border border-slate-200 bg-white p-6 text-sm text-slate-600">
        Nothing selected yet.{" "}
        <Link href="/schema" className="text-sky-600 hover:text-sky-700 hover:underline">
          Go check some metrics in the Schema Browser
        </Link>{" "}
        first, then come back here.
      </div>
    );
  }

  const active = sourceTable && sourceTables.includes(sourceTable) ? sourceTable : sourceTables[0];
  const sourceSchema = allTables?.find((t) => t.name === active) ?? null;

  return (
    <div className="flex flex-col gap-6">
      {sourceTables.length > 1 && (
        <div className="rounded-md border border-slate-200 bg-white p-4">
          <h3 className="mb-2 text-sm font-medium text-slate-800">
            You have selections on {sourceTables.length} tables
          </h3>
          <div className="mb-3 flex gap-2">
            <button
              onClick={() => setMode("single")}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                mode === "single"
                  ? "bg-sky-600 text-white"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              }`}
            >
              Single table
            </button>
            <button
              onClick={() => setMode("join")}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                mode === "join"
                  ? "bg-sky-600 text-white"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              }`}
            >
              Join tables
            </button>
          </div>

          {mode === "single" ? (
            <div className="flex flex-wrap gap-2">
              {sourceTables.map((t) => (
                <button
                  key={t}
                  onClick={() => setSourceTable(t)}
                  className={`rounded-full px-3 py-1 text-xs font-mono transition-colors ${
                    t === active
                      ? "bg-sky-600 text-white"
                      : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                  }`}
                >
                  {t} ({selection[t].size})
                </button>
              ))}
            </div>
          ) : (
            <p className="text-xs text-slate-500">
              All {sourceTables.length} tables below will be joined into one — pick the anchor and
              how each other table connects to it.
            </p>
          )}
        </div>
      )}

      {mode === "single" ? (
        // Keyed by source table so switching tables resets every
        // downstream choice by remounting, not a manual reset effect.
        <SourceTableBuilder
          key={active}
          sourceTable={active}
          fields={[...(selection[active] ?? [])].sort()}
          hasObjectType={sourceSchema?.columns.some((c) => c.name === "object_type") ?? false}
        />
      ) : (
        <JoinTableBuilder
          key={sourceTables.join(",")}
          tables={sourceTables}
          selection={selection}
          hasObjectType={hasObjectTypeByTable}
        />
      )}
    </div>
  );
}

function SourceTableBuilder({
  sourceTable,
  fields,
  hasObjectType,
}: {
  sourceTable: string;
  fields: string[];
  hasObjectType: boolean;
}) {
  const [objectTypes, setObjectTypes] = useState<ObjectTypeCount[] | null>(null);
  const [objectType, setObjectType] = useState<string | null>(null);
  const [outputNames, setOutputNames] = useState<Record<string, string>>({});
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [tableName, setTableName] = useState("");
  const [overwrite, setOverwrite] = useState(false);

  const [preview, setPreview] = useState<CustomTableResponse | null>(null);
  const [result, setResult] = useState<CustomTableResponse | null>(null);
  const [busy, setBusy] = useState<"preview" | "create" | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!hasObjectType) return;
    let cancelled = false;
    fetchObjectTypes(sourceTable)
      .then((res) => !cancelled && setObjectTypes(res.values))
      .catch(() => !cancelled && setObjectTypes(null));
    return () => {
      cancelled = true;
    };
  }, [sourceTable, hasObjectType]);

  function toggleExcluded(field: string) {
    setExcluded((prev) => {
      const next = new Set(prev);
      if (next.has(field)) {
        next.delete(field);
      } else {
        next.add(field);
      }
      return next;
    });
    setPreview(null);
    setResult(null);
  }

  const includedFields = fields.filter((f) => !excluded.has(f));
  const canBuild = includedFields.length > 0 && tableName.trim().length > 0;

  function buildRequestBody(dryRun: boolean) {
    return {
      source_table: sourceTable,
      object_type: hasObjectType ? objectType : null,
      fields: includedFields.map((f) => ({
        field: f,
        output_name: outputNames[f]?.trim() || null,
      })),
      table_name: tableName.trim(),
      dry_run: dryRun,
      overwrite,
    };
  }

  async function handlePreview() {
    if (!canBuild) return;
    setError(null);
    setBusy("preview");
    try {
      const res = await createCustomTable(buildRequestBody(true));
      setPreview(res);
      setResult(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the backend.");
    } finally {
      setBusy(null);
    }
  }

  async function handleCreate() {
    if (!canBuild) return;
    setError(null);
    setBusy("create");
    try {
      const res = await createCustomTable(buildRequestBody(false));
      setResult(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the backend.");
    } finally {
      setBusy(null);
    }
  }

  async function copySql(sql: string) {
    await navigator.clipboard.writeText(sql);
  }

  return (
    <>
      {hasObjectType && (
        <div className="rounded-md border border-slate-200 bg-white p-4">
          <label className="mb-1 block text-xs text-slate-600">
            object_type filter (recommended — this table mixes shapes)
          </label>
          <div className="flex max-h-20 flex-wrap gap-1.5 overflow-y-auto">
            <button
              onClick={() => {
                setObjectType(null);
                setPreview(null);
              }}
              className={`rounded-full px-2.5 py-1 text-xs transition-colors ${
                objectType === null
                  ? "bg-sky-600 text-white"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              }`}
            >
              none
            </button>
            {objectTypes?.map((o) => (
              <button
                key={o.value}
                onClick={() => {
                  setObjectType(o.value);
                  setPreview(null);
                }}
                className={`rounded-full px-2.5 py-1 text-xs transition-colors ${
                  o.value === objectType
                    ? "bg-sky-600 text-white"
                    : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                }`}
              >
                {o.value}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Field selection */}
      <div className="rounded-md border border-slate-200 bg-white p-4">
        <h3 className="mb-3 text-sm font-medium text-slate-800">
          Fields ({includedFields.length} of {fields.length})
        </h3>
        <div className="flex flex-col gap-2">
          {fields.map((f) => {
            const isExcluded = excluded.has(f);
            return (
              <div
                key={f}
                className={`flex flex-wrap items-center gap-3 rounded-md border px-3 py-2 ${
                  isExcluded ? "border-slate-100 opacity-50" : "border-slate-200"
                }`}
              >
                <input
                  type="checkbox"
                  checked={!isExcluded}
                  onChange={() => toggleExcluded(f)}
                  className="h-3.5 w-3.5 accent-sky-600"
                />
                <span className="min-w-[160px] font-mono text-xs text-slate-800">{f}</span>
                {!isExcluded && (
                  <input
                    value={outputNames[f] ?? ""}
                    onChange={(e) => {
                      setOutputNames((prev) => ({ ...prev, [f]: e.target.value }));
                      setPreview(null);
                    }}
                    placeholder={f.replace(".", "_")}
                    className="min-w-[140px] flex-1 rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-900 placeholder:text-slate-400 focus:border-sky-500 focus:outline-none"
                  />
                )}
              </div>
            );
          })}
        </div>
        <p className="mt-2 text-xs text-slate-400">
          Just a projection — no averages/sums here. Computed metrics get added later, once this
          table is flattened or viewed.
        </p>
      </div>

      {/* Name + actions */}
      <div className="rounded-md border border-slate-200 bg-white p-4">
        <label className="mb-1 block text-xs text-slate-600">Table name</label>
        <input
          value={tableName}
          onChange={(e) => {
            setTableName(e.target.value);
            setPreview(null);
            setResult(null);
          }}
          placeholder="silver_products_flat"
          className="w-full max-w-sm rounded-md border border-slate-200 bg-slate-50 px-3 py-2 font-mono text-sm text-slate-900 placeholder:text-slate-400 focus:border-sky-500 focus:outline-none"
        />

        <label className="mt-2 flex cursor-pointer items-center gap-2 text-xs text-slate-600">
          <input
            type="checkbox"
            checked={overwrite}
            onChange={(e) => {
              setOverwrite(e.target.checked);
              setPreview(null);
              setResult(null);
            }}
            className="h-3.5 w-3.5 accent-sky-600"
          />
          Update table if it already exists
        </label>

        {error && (
          <div className="mt-3 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <div className="mt-4 flex gap-2">
          <button
            onClick={handlePreview}
            disabled={!canBuild || busy !== null}
            className="rounded-md border border-slate-200 bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-200 disabled:opacity-40"
          >
            {busy === "preview" ? "Generating…" : "Preview SQL"}
          </button>
          <button
            onClick={handleCreate}
            disabled={!canBuild || !preview || busy !== null}
            className="rounded-md bg-sky-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-sky-500 disabled:opacity-40"
          >
            {busy === "create" ? "Saving…" : overwrite ? "Confirm & Update" : "Confirm & Create"}
          </button>
        </div>
        {!preview && canBuild && (
          <p className="mt-2 text-xs text-slate-400">Preview the SQL first to enable creation.</p>
        )}
      </div>

      {/* Schema visualization */}
      {preview && !result && (
        <div className="rounded-md border border-slate-200 bg-white p-4">
          <h3 className="mb-2 text-sm font-medium text-slate-800">
            Preview: {preview.preview_columns.length} columns
          </h3>
          <div className="mb-3 flex flex-wrap gap-1.5">
            {preview.preview_columns.map((c) => (
              <span key={c} className="rounded bg-slate-100 px-2 py-1 font-mono text-xs text-slate-700">
                {c}
              </span>
            ))}
          </div>
          <details className="text-xs">
            <summary className="cursor-pointer text-slate-500 hover:text-slate-700">
              View generated SQL
            </summary>
            <pre className="mt-2 overflow-x-auto rounded-md border border-slate-200 bg-slate-50 p-3 font-mono text-[11px] leading-relaxed text-slate-700">
              {preview.sql}
            </pre>
          </details>
        </div>
      )}

      {/* Result */}
      {result && (
        <div
          className={`rounded-md border p-4 ${
            result.status === "created"
              ? "border-emerald-200 bg-emerald-50"
              : "border-red-200 bg-red-50"
          }`}
        >
          {result.status === "created" ? (
            <p className="text-sm text-emerald-700">
              {overwrite ? "Updated" : "Created"} <span className="font-mono">{result.table_name}</span> —{" "}
              {result.row_count?.toLocaleString()} rows.
            </p>
          ) : (
            <>
              <p className="text-sm text-red-700">Execution failed: {result.error}</p>
              <p className="mt-1 text-xs text-slate-600">
                The SQL is valid enough to have been generated — this is a data-level failure. Run
                it manually in the Supabase SQL Editor to see the full error, or copy it below.
              </p>
            </>
          )}
          <div className="mt-3 flex items-center gap-2">
            <button
              onClick={() => copySql(result.sql)}
              className="rounded-md border border-slate-200 bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-200"
            >
              Copy SQL
            </button>
          </div>
          <pre className="mt-3 overflow-x-auto rounded-md border border-slate-200 bg-slate-50 p-3 font-mono text-[11px] leading-relaxed text-slate-700">
            {result.sql}
          </pre>
        </div>
      )}
    </>
  );
}
