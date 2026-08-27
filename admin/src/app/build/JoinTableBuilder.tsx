"use client";

import { useEffect, useState } from "react";
import {
  ApiError,
  createJoinedTable,
  fetchObjectTypes,
  type JoinType,
  type JoinedTableResponse,
  type ObjectTypeCount,
} from "@/lib/api";
import type { Selection } from "@/lib/SelectionContext";

const JOIN_OPTIONS: { value: JoinType; label: string; hint: string }[] = [
  { value: "inner", label: "Inner", hint: "only rows with a match on both sides" },
  { value: "left", label: "Left", hint: "every anchor row, matched or not" },
  { value: "right", label: "Right", hint: "every row from this table, matched or not" },
  { value: "full", label: "Full", hint: "every row from either side" },
];

interface TableConfig {
  objectType: string | null;
  excluded: Set<string>;
  outputNames: Record<string, string>;
  joinType: JoinType;
  joinField: string;
  anchorJoinField: string;
}

function emptyConfig(): TableConfig {
  return {
    objectType: null,
    excluded: new Set(),
    outputNames: {},
    joinType: "inner",
    joinField: "",
    anchorJoinField: "",
  };
}

export function JoinTableBuilder({
  tables,
  selection,
  hasObjectType,
}: {
  tables: string[];
  selection: Selection;
  hasObjectType: Record<string, boolean>;
}) {
  const [anchor, setAnchor] = useState(tables[0]);
  const [configs, setConfigs] = useState<Record<string, TableConfig>>(() =>
    Object.fromEntries(tables.map((t) => [t, emptyConfig()])),
  );
  const [tableName, setTableName] = useState("");
  const [preview, setPreview] = useState<JoinedTableResponse | null>(null);
  const [result, setResult] = useState<JoinedTableResponse | null>(null);
  const [busy, setBusy] = useState<"preview" | "create" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const others = tables.filter((t) => t !== anchor);
  const orderedTables = [anchor, ...others];

  function updateConfig(table: string, patch: Partial<TableConfig>) {
    setConfigs((prev) => ({ ...prev, [table]: { ...prev[table], ...patch } }));
    setPreview(null);
    setResult(null);
  }

  function toggleExcluded(table: string, field: string) {
    setConfigs((prev) => {
      const cfg = prev[table];
      const next = new Set(cfg.excluded);
      if (next.has(field)) {
        next.delete(field);
      } else {
        next.add(field);
      }
      return { ...prev, [table]: { ...cfg, excluded: next } };
    });
    setPreview(null);
    setResult(null);
  }

  const canBuild =
    tableName.trim().length > 0 &&
    others.every((t) => configs[t]?.joinField && configs[t]?.anchorJoinField) &&
    orderedTables.some((t) => [...(selection[t] ?? [])].some((f) => !configs[t]?.excluded.has(f)));

  function buildRequestBody(dryRun: boolean) {
    return {
      tables: orderedTables.map((t) => {
        const cfg = configs[t];
        const fields = [...(selection[t] ?? [])]
          .filter((f) => !cfg.excluded.has(f))
          .map((f) => ({ field: f, output_name: cfg.outputNames[f]?.trim() || null }));
        const isAnchor = t === anchor;
        return {
          table: t,
          object_type: hasObjectType[t] ? cfg.objectType : null,
          fields,
          join_type: isAnchor ? undefined : cfg.joinType,
          join_field: isAnchor ? undefined : cfg.joinField,
          anchor_join_field: isAnchor ? undefined : cfg.anchorJoinField,
        };
      }),
      table_name: tableName.trim(),
      dry_run: dryRun,
    };
  }

  async function handlePreview() {
    if (!canBuild) return;
    setError(null);
    setBusy("preview");
    try {
      const res = await createJoinedTable(buildRequestBody(true));
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
      const res = await createJoinedTable(buildRequestBody(false));
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
    <div className="flex flex-col gap-4">
      <div className="rounded-md border border-border-primary bg-white p-4">
        <label className="mb-1 block text-xs text-text-secondary">
          Anchor table — every other table joins directly to this one
        </label>
        <div className="flex flex-wrap gap-2">
          {tables.map((t) => (
            <button
              key={t}
              onClick={() => setAnchor(t)}
              className={`rounded-full px-3 py-1 text-xs font-mono transition-colors ${
                t === anchor
                  ? "bg-accent-yellow text-white"
                  : "bg-bg-muted text-text-secondary hover:bg-bg-muted"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {orderedTables.map((t, i) => (
        <TableJoinSection
          key={t}
          table={t}
          isAnchor={i === 0}
          fields={[...(selection[t] ?? [])].sort()}
          anchorFields={i === 0 ? [] : [...(selection[anchor] ?? [])].sort()}
          hasObjectType={hasObjectType[t] ?? false}
          config={configs[t]}
          onUpdate={(patch) => updateConfig(t, patch)}
          onToggleExcluded={(f) => toggleExcluded(t, f)}
        />
      ))}

      <div className="rounded-md border border-border-primary bg-white p-4">
        <label className="mb-1 block text-xs text-text-secondary">Table name</label>
        <input
          value={tableName}
          onChange={(e) => {
            setTableName(e.target.value);
            setPreview(null);
            setResult(null);
          }}
          placeholder="gold_ads_with_shopify"
          className="w-full max-w-sm rounded-md border border-border-primary bg-bg-surface px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-tertiary focus:border-accent-yellow focus:outline-none"
        />

        {error && (
          <div className="mt-3 rounded-md border border-error-mid bg-error-bg p-3 text-sm text-error-text">
            {error}
          </div>
        )}

        <div className="mt-4 flex gap-2">
          <button
            onClick={handlePreview}
            disabled={!canBuild || busy !== null}
            className="rounded-md border border-border-primary bg-bg-muted px-4 py-2 text-sm font-medium text-text-primary transition-colors hover:bg-bg-muted disabled:opacity-40"
          >
            {busy === "preview" ? "Generating…" : "Preview SQL"}
          </button>
          <button
            onClick={handleCreate}
            disabled={!canBuild || !preview || busy !== null}
            className="rounded-md bg-accent-yellow px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-yellow-hover disabled:opacity-40"
          >
            {busy === "create" ? "Creating…" : "Confirm & Create"}
          </button>
        </div>
        {!preview && canBuild && (
          <p className="mt-2 text-xs text-text-tertiary">Preview the SQL first to enable creation.</p>
        )}
        {!canBuild && others.some((t) => !configs[t]?.joinField || !configs[t]?.anchorJoinField) && (
          <p className="mt-2 text-xs text-warning-text">
            Every non-anchor table needs both a join field on itself and one on the anchor.
          </p>
        )}
      </div>

      {preview && !result && (
        <div className="rounded-md border border-border-primary bg-white p-4">
          <h3 className="mb-2 text-sm font-medium text-text-primary">
            Preview: {preview.preview_columns.length} columns
          </h3>
          <div className="mb-3 flex flex-wrap gap-1.5">
            {preview.preview_columns.map((c) => (
              <span key={c} className="rounded bg-bg-muted px-2 py-1 font-mono text-xs text-text-primary">
                {c}
              </span>
            ))}
          </div>
          <details className="text-xs">
            <summary className="cursor-pointer text-text-secondary hover:text-text-primary">
              View generated SQL
            </summary>
            <pre className="mt-2 overflow-x-auto rounded-md border border-border-primary bg-bg-surface p-3 font-mono text-[11px] leading-relaxed text-text-primary">
              {preview.sql}
            </pre>
          </details>
        </div>
      )}

      {result && (
        <div
          className={`rounded-md border p-4 ${
            result.status === "created"
              ? "border-success-mid bg-success-bg"
              : "border-error-mid bg-error-bg"
          }`}
        >
          {result.status === "created" ? (
            <p className="text-sm text-success-text">
              Created <span className="font-mono">{result.table_name}</span> —{" "}
              {result.row_count?.toLocaleString()} rows.
            </p>
          ) : (
            <>
              <p className="text-sm text-error-text">Execution failed: {result.error}</p>
              <p className="mt-1 text-xs text-text-secondary">
                Run this SQL manually in the Supabase SQL Editor to see the full error, or copy it
                below.
              </p>
            </>
          )}
          <div className="mt-3 flex items-center gap-2">
            <button
              onClick={() => copySql(result.sql)}
              className="rounded-md border border-border-primary bg-bg-muted px-3 py-1.5 text-xs font-medium text-text-primary transition-colors hover:bg-bg-muted"
            >
              Copy SQL
            </button>
          </div>
          <pre className="mt-3 overflow-x-auto rounded-md border border-border-primary bg-bg-surface p-3 font-mono text-[11px] leading-relaxed text-text-primary">
            {result.sql}
          </pre>
        </div>
      )}
    </div>
  );
}

function TableJoinSection({
  table,
  isAnchor,
  fields,
  anchorFields,
  hasObjectType,
  config,
  onUpdate,
  onToggleExcluded,
}: {
  table: string;
  isAnchor: boolean;
  fields: string[];
  anchorFields: string[];
  hasObjectType: boolean;
  config: TableConfig;
  onUpdate: (patch: Partial<TableConfig>) => void;
  onToggleExcluded: (field: string) => void;
}) {
  const [objectTypes, setObjectTypes] = useState<ObjectTypeCount[] | null>(null);

  useEffect(() => {
    if (!hasObjectType) return;
    let cancelled = false;
    fetchObjectTypes(table)
      .then((res) => !cancelled && setObjectTypes(res.values))
      .catch(() => !cancelled && setObjectTypes(null));
    return () => {
      cancelled = true;
    };
  }, [table, hasObjectType]);

  return (
    <div className="rounded-md border border-border-primary bg-white p-4">
      <div className="mb-3 flex items-center gap-2">
        <span className="font-mono text-sm text-text-primary">{table}</span>
        <span
          className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
            isAnchor ? "bg-info-bg text-info-text" : "bg-bg-muted text-text-secondary"
          }`}
        >
          {isAnchor ? "anchor" : "joined"}
        </span>
      </div>

      {!isAnchor && (
        <div className="mb-3 grid grid-cols-1 gap-3 rounded-md border border-border-primary bg-bg-surface p-3 sm:grid-cols-3">
          <div>
            <label className="mb-1 block text-xs text-text-secondary">Join type</label>
            <select
              value={config.joinType}
              onChange={(e) => onUpdate({ joinType: e.target.value as JoinType })}
              className="w-full rounded-md border border-border-primary bg-white px-2 py-1.5 text-sm text-text-primary focus:border-accent-yellow focus:outline-none"
            >
              {JOIN_OPTIONS.map((o) => (
                <option key={o.value} value={o.value} title={o.hint}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs text-text-secondary">Anchor field</label>
            <select
              value={config.anchorJoinField}
              onChange={(e) => onUpdate({ anchorJoinField: e.target.value })}
              className="w-full rounded-md border border-border-primary bg-white px-2 py-1.5 text-sm text-text-primary focus:border-accent-yellow focus:outline-none"
            >
              <option value="">— select —</option>
              {anchorFields.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs text-text-secondary">This table&apos;s field</label>
            <select
              value={config.joinField}
              onChange={(e) => onUpdate({ joinField: e.target.value })}
              className="w-full rounded-md border border-border-primary bg-white px-2 py-1.5 text-sm text-text-primary focus:border-accent-yellow focus:outline-none"
            >
              <option value="">— select —</option>
              {fields.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
          </div>
        </div>
      )}

      {hasObjectType && (
        <div className="mb-3">
          <label className="mb-1 block text-xs text-text-secondary">object_type filter</label>
          <div className="flex max-h-16 flex-wrap gap-1.5 overflow-y-auto">
            <button
              onClick={() => onUpdate({ objectType: null })}
              className={`rounded-full px-2.5 py-1 text-xs transition-colors ${
                config.objectType === null
                  ? "bg-accent-yellow text-white"
                  : "bg-bg-muted text-text-secondary hover:bg-bg-muted"
              }`}
            >
              none
            </button>
            {objectTypes?.map((o) => (
              <button
                key={o.value}
                onClick={() => onUpdate({ objectType: o.value })}
                className={`rounded-full px-2.5 py-1 text-xs transition-colors ${
                  o.value === config.objectType
                    ? "bg-accent-yellow text-white"
                    : "bg-bg-muted text-text-secondary hover:bg-bg-muted"
                }`}
              >
                {o.value}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="flex flex-col gap-1.5">
        {fields.map((f) => {
          const isExcluded = config.excluded.has(f);
          return (
            <div
              key={f}
              className={`flex flex-wrap items-center gap-3 rounded-md border px-3 py-1.5 ${
                isExcluded ? "border-border-soft opacity-50" : "border-border-primary"
              }`}
            >
              <input
                type="checkbox"
                checked={!isExcluded}
                onChange={() => onToggleExcluded(f)}
                className="h-3.5 w-3.5 accent-accent-yellow"
              />
              <span className="min-w-[140px] font-mono text-xs text-text-primary">{f}</span>
              {!isExcluded && (
                <input
                  value={config.outputNames[f] ?? ""}
                  onChange={(e) =>
                    onUpdate({ outputNames: { ...config.outputNames, [f]: e.target.value } })
                  }
                  placeholder={`${table}_${f}`.replace(".", "_")}
                  className="min-w-[120px] flex-1 rounded-md border border-border-primary bg-bg-surface px-2 py-1 text-xs text-text-primary placeholder:text-text-tertiary focus:border-accent-yellow focus:outline-none"
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
