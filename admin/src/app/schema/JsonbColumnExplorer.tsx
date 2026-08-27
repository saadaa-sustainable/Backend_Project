"use client";

import { useEffect, useState } from "react";
import {
  ApiError,
  fetchJsonbKeys,
  fetchObjectTypes,
  type JsonbKey,
  type ObjectTypeCount,
} from "@/lib/api";

const TYPE_STYLES: Record<string, string> = {
  string: "bg-success-bg text-success-text",
  number: "bg-warning-bg text-warning-text",
  boolean: "bg-info-bg text-info-text",
  object: "bg-accent-indigo-bg text-accent-indigo",
  array: "bg-fuchsia-100 text-fuchsia-700",
  null: "bg-bg-muted text-text-secondary",
};

interface Props {
  table: string;
  column: string;
  hasObjectType: boolean;
  selectedKeys?: Set<string>;
  onToggleKey?: (key: string) => void;
  // Hides the selection checkbox column entirely -- used by the read-only
  // user-facing Schema Browser, which has no "Build custom table" flow for
  // a selection to feed into.
  showSelection?: boolean;
}

export function JsonbColumnExplorer({
  table,
  column,
  hasObjectType,
  selectedKeys = new Set(),
  onToggleKey,
  showSelection = true,
}: Props) {
  const [objectTypes, setObjectTypes] = useState<ObjectTypeCount[] | null>(null);
  const [selectedObjectType, setSelectedObjectType] = useState<string | null>(null);
  const [objectTypeSearch, setObjectTypeSearch] = useState("");
  const [keys, setKeys] = useState<JsonbKey[] | null>(null);
  const [rowsScanned, setRowsScanned] = useState<number | null>(null);
  const [loadingTypes, setLoadingTypes] = useState(hasObjectType);
  const [loadingKeys, setLoadingKeys] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Step 1: discover distinct object_type values, if this table has one.
  useEffect(() => {
    if (!hasObjectType) return;
    let cancelled = false;
    fetchObjectTypes(table)
      .then((res) => {
        if (cancelled) return;
        setObjectTypes(res.values);
        setSelectedObjectType((prev) => prev ?? res.values[0]?.value ?? null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Could not load object types.");
      })
      .finally(() => !cancelled && setLoadingTypes(false));
    return () => {
      cancelled = true;
    };
  }, [table, hasObjectType]);

  // Step 2: discover keys inside raw_payload for the chosen object_type
  // (or unfiltered, for tables with no object_type column at all). Loading
  // is intentionally flipped true synchronously here (not deferred) --
  // this effect re-runs every time selectedObjectType changes, and the
  // loading indicator needs to reflect that immediately, not just on the
  // first run.
  useEffect(() => {
    if (hasObjectType && !selectedObjectType) return;
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoadingKeys(true);
    fetchJsonbKeys(table, {
      column,
      filterColumn: hasObjectType ? "object_type" : null,
      filterValue: selectedObjectType,
    })
      .then((res) => {
        if (cancelled) return;
        setKeys(res.keys);
        setRowsScanned(res.rows_scanned);
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Could not discover keys.");
      })
      .finally(() => !cancelled && setLoadingKeys(false));
    return () => {
      cancelled = true;
    };
  }, [table, column, hasObjectType, selectedObjectType]);

  const filteredObjectTypes = objectTypes?.filter((o) =>
    o.value.toLowerCase().includes(objectTypeSearch.trim().toLowerCase()),
  );

  return (
    <div className="mt-2 rounded-md border border-border-primary bg-bg-surface p-3">
      {hasObjectType && (
        <div className="mb-3">
          <div className="mb-1.5 flex items-center justify-between">
            <span className="text-xs font-medium text-text-secondary">
              object_type ({objectTypes?.length ?? "…"})
            </span>
            <input
              value={objectTypeSearch}
              onChange={(e) => setObjectTypeSearch(e.target.value)}
              placeholder="Filter…"
              className="w-40 rounded border border-border-primary bg-white px-2 py-1 text-xs text-text-primary placeholder:text-text-tertiary focus:border-accent-yellow focus:outline-none"
            />
          </div>
          {loadingTypes ? (
            <p className="text-xs text-text-tertiary">Loading object types…</p>
          ) : (
            <div className="flex max-h-24 flex-wrap gap-1.5 overflow-y-auto">
              {filteredObjectTypes?.map((o) => (
                <button
                  key={o.value}
                  onClick={() => setSelectedObjectType(o.value)}
                  className={`rounded-full px-2.5 py-1 text-xs transition-colors ${
                    o.value === selectedObjectType
                      ? "bg-accent-yellow text-white"
                      : "bg-bg-muted text-text-secondary hover:bg-bg-muted"
                  }`}
                >
                  {o.value} <span className="opacity-60">({o.row_count})</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {error && (
        <div className="rounded border border-error-mid bg-error-bg p-2 text-xs text-error-text">
          {error}
        </div>
      )}

      {loadingKeys && <p className="text-xs text-text-tertiary">Scanning rows…</p>}

      {!loadingKeys && keys && (
        <>
          <p className="mb-2 text-xs text-text-secondary">
            {keys.length} unique keys found across all {rowsScanned} row{rowsScanned === 1 ? "" : "s"}
            {selectedObjectType ? ` where object_type = '${selectedObjectType}'` : ""} — not a sample.
          </p>
          <div className="max-h-72 overflow-y-auto">
            <table className="w-full border-collapse text-xs">
              <thead className="sticky top-0 bg-bg-surface">
                <tr className="border-b border-border-primary text-left uppercase tracking-wide text-text-tertiary">
                  {showSelection && <th className="w-6 py-1.5"></th>}
                  <th className="py-1.5 pr-3">Key</th>
                  <th className="py-1.5 pr-3">Type(s)</th>
                  <th className="py-1.5">Present</th>
                </tr>
              </thead>
              <tbody>
                {keys.map((k) => {
                  const compositeKey = `${column}.${k.key}`;
                  const checked = selectedKeys.has(compositeKey);
                  return (
                    <tr key={k.key} className="border-b border-border-soft hover:bg-bg-surface">
                      {showSelection && (
                        <td className="py-1">
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => onToggleKey?.(compositeKey)}
                            className="h-3 w-3 accent-accent-yellow"
                          />
                        </td>
                      )}
                      <td className="py-1 pr-3 font-mono text-text-primary">{k.key}</td>
                      <td className="py-1 pr-3">
                        <div className="flex gap-1">
                          {k.types.map((t) => (
                            <span
                              key={t}
                              className={`rounded px-1 py-0.5 text-[9px] font-medium ${TYPE_STYLES[t] ?? "bg-bg-muted text-text-secondary"}`}
                            >
                              {t}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="py-1 text-text-secondary">{k.presence_pct}%</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
