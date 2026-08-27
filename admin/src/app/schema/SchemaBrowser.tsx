"use client";

import Link from "next/link";
import { Fragment, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  fetchTables,
  type ColumnKind,
  type TableSchema,
} from "@/lib/api";
import { useSelection } from "@/lib/SelectionContext";
import { FlattenPanel } from "./FlattenPanel";
import { JsonbColumnExplorer } from "./JsonbColumnExplorer";

const KIND_STYLES: Record<ColumnKind, string> = {
  identity: "bg-info-bg text-info-text",
  numeric: "bg-warning-bg text-warning-text",
  jsonb: "bg-accent-indigo-bg text-accent-indigo",
  other: "bg-bg-muted text-text-secondary",
};

export function SchemaBrowser() {
  const [tables, setTables] = useState<TableSchema[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [activeTable, setActiveTable] = useState<string | null>(null);
  const [columnSearch, setColumnSearch] = useState("");
  const { selection, toggle: toggleColumn, count: selectionCount } = useSelection();
  const [expandedColumn, setExpandedColumn] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchTables()
      .then((res) => {
        if (cancelled) return;
        setTables(res.tables);
        setActiveTable((prev) => prev ?? res.tables[0]?.name ?? null);
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(
          err instanceof ApiError
            ? err.message
            : "Could not reach the FastAPI backend. Is it running, and is NEXT_PUBLIC_API_BASE_URL correct?",
        );
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  const filteredTables = useMemo(() => {
    if (!tables) return [];
    const q = search.trim().toLowerCase();
    if (!q) return tables;
    return tables.filter((t) => t.name.toLowerCase().includes(q));
  }, [tables, search]);

  const active = tables?.find((t) => t.name === activeTable) ?? null;

  const filteredColumns = useMemo(() => {
    if (!active) return [];
    const q = columnSearch.trim().toLowerCase();
    if (!q) return active.columns;
    return active.columns.filter((c) => c.name.toLowerCase().includes(q));
  }, [active, columnSearch]);

  async function copySelection() {
    const payload = Object.fromEntries(
      Object.entries(selection).map(([table, cols]) => [table, [...cols].sort()]),
    );
    await navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
  }

  if (loading) {
    return <div className="text-sm text-text-secondary">Loading tables…</div>;
  }

  if (error) {
    return (
      <div className="rounded-lg border border-error-mid bg-error-bg p-4 text-sm text-error-text">
        {error}
      </div>
    );
  }

  if (!tables || tables.length === 0) {
    return (
      <div className="rounded-lg border border-border-primary bg-white p-4 text-sm text-text-secondary">
        No tables found in the target Supabase project.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[280px_1fr]">
        {/* Table list */}
        <div className="flex flex-col gap-2">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter tables…"
            className="rounded-md border border-border-primary bg-white px-3 py-2 text-sm text-text-primary placeholder:text-text-tertiary focus:border-accent-yellow focus:outline-none"
          />
          <div className="flex max-h-[560px] flex-col gap-1 overflow-y-auto rounded-md border border-border-primary bg-white p-1">
            {filteredTables.map((t) => (
              <button
                key={t.name}
                onClick={() => {
                  setActiveTable(t.name);
                  setExpandedColumn(null);
                }}
                className={`flex items-center justify-between rounded px-3 py-2 text-left text-sm transition-colors ${
                  t.name === activeTable
                    ? "bg-accent-yellow-bg text-accent-yellow"
                    : "text-text-secondary hover:bg-bg-surface hover:text-text-primary"
                }`}
              >
                <span className="truncate font-mono text-[13px]">{t.name}</span>
                <span className="ml-2 shrink-0 text-[11px] text-text-tertiary">
                  {t.columns.length} cols
                  {selection[t.name] ? ` · ${selection[t.name].size} sel` : ""}
                </span>
              </button>
            ))}
          </div>
        </div>

        {/* Column detail */}
        <div className="flex flex-col gap-3 rounded-md border border-border-primary bg-white p-4">
          {active ? (
            <>
              <FlattenPanel table={active.name} />
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="font-mono text-sm text-text-primary">{active.name}</h2>
                  <p className="mt-0.5 text-xs text-text-secondary">
                    {active.columns.length} columns
                    {active.row_count !== null ? ` · ${active.row_count.toLocaleString()} rows` : ""}
                  </p>
                </div>
                <input
                  value={columnSearch}
                  onChange={(e) => setColumnSearch(e.target.value)}
                  placeholder="Filter metrics…"
                  className="w-52 rounded-md border border-border-primary bg-bg-surface px-3 py-1.5 text-xs text-text-primary placeholder:text-text-tertiary focus:border-accent-yellow focus:outline-none"
                />
              </div>

              <div className="max-h-[480px] overflow-y-auto">
                <table className="w-full border-collapse text-sm">
                  <thead className="sticky top-0 bg-white">
                    <tr className="border-b border-border-primary text-left text-[11px] uppercase tracking-wide text-text-secondary">
                      <th className="w-8 py-2"></th>
                      <th className="py-2 pr-4">Column</th>
                      <th className="py-2 pr-4">Type</th>
                      <th className="py-2 pr-4">Kind</th>
                      <th className="py-2 pr-4">Nullable</th>
                      <th className="py-2">Formula</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredColumns.map((col) => {
                      const checked = selection[active.name]?.has(col.name) ?? false;
                      const isExpanded = expandedColumn === col.name;
                      return (
                        <Fragment key={col.name}>
                          <tr className="border-b border-border-soft hover:bg-bg-surface">
                            <td className="py-1.5">
                              <input
                                type="checkbox"
                                checked={checked}
                                onChange={() => toggleColumn(active.name, col.name)}
                                className="h-3.5 w-3.5 accent-accent-yellow"
                              />
                            </td>
                            <td className="py-1.5 pr-4 font-mono text-[13px] text-text-primary">
                              {col.kind === "jsonb" ? (
                                <button
                                  onClick={() => setExpandedColumn(isExpanded ? null : col.name)}
                                  className="flex items-center gap-1.5 hover:text-text-primary"
                                >
                                  <span className={`transition-transform ${isExpanded ? "rotate-90" : ""}`}>
                                    ›
                                  </span>
                                  {col.name}
                                </button>
                              ) : (
                                col.name
                              )}
                            </td>
                            <td className="py-1.5 pr-4 font-mono text-[12px] text-text-secondary">
                              {col.data_type}
                            </td>
                            <td className="py-1.5 pr-4">
                              <span
                                className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${KIND_STYLES[col.kind]}`}
                              >
                                {col.kind}
                              </span>
                            </td>
                            <td className="py-1.5 pr-4 text-[12px] text-text-secondary">
                              {col.is_nullable ? "yes" : "no"}
                            </td>
                            <td className="py-1.5 text-[12px] text-text-secondary">
                              {col.formula ? (
                                <span title={col.formula} className="cursor-help">
                                  <span className="mr-1 rounded bg-success-bg px-1 py-0.5 text-[10px] font-medium text-success-text">
                                    ƒ
                                  </span>
                                  {col.formula.length > 60
                                    ? `${col.formula.slice(0, 60)}…`
                                    : col.formula}
                                </span>
                              ) : (
                                <span className="text-text-tertiary">—</span>
                              )}
                            </td>
                          </tr>
                          {isExpanded && (
                            <tr className="border-b border-border-soft">
                              <td colSpan={6} className="pb-2">
                                <JsonbColumnExplorer
                                  table={active.name}
                                  column={col.name}
                                  hasObjectType={active.columns.some((c) => c.name === "object_type")}
                                  selectedKeys={selection[active.name] ?? new Set()}
                                  onToggleKey={(key) => toggleColumn(active.name, key)}
                                />
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <p className="text-sm text-text-secondary">Select a table.</p>
          )}
        </div>
      </div>

      {/* Selection summary */}
      <div className="rounded-md border border-border-primary bg-white p-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium text-text-primary">
            Selected metrics ({selectionCount})
          </h3>
          <div className="flex gap-2">
            <button
              onClick={copySelection}
              disabled={selectionCount === 0}
              className="rounded-md bg-bg-muted border border-border-primary px-3 py-1.5 text-xs font-medium text-text-primary transition-colors hover:bg-bg-muted disabled:opacity-40"
            >
              Copy as JSON
            </button>
            <Link
              href="/build"
              aria-disabled={selectionCount === 0}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                selectionCount === 0
                  ? "pointer-events-none bg-bg-muted text-text-tertiary"
                  : "bg-accent-yellow text-white hover:bg-accent-yellow-hover"
              }`}
            >
              Build custom table →
            </Link>
          </div>
        </div>
        {selectionCount === 0 ? (
          <p className="mt-2 text-xs text-text-tertiary">
            Check metrics above to build a selection — useful for scoping a Gold-layer table or a
            new custom metric definition.
          </p>
        ) : (
          <div className="mt-3 flex flex-col gap-2">
            {Object.entries(selection).map(([table, cols]) => (
              <div key={table} className="text-xs">
                <span className="font-mono text-text-primary">{table}</span>
                <span className="text-text-tertiary"> — {[...cols].sort().join(", ")}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
