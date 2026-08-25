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
  identity: "bg-sky-100 text-sky-700",
  numeric: "bg-amber-100 text-amber-700",
  jsonb: "bg-indigo-100 text-indigo-700",
  other: "bg-slate-100 text-slate-500",
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
    return <div className="text-sm text-slate-500">Loading tables…</div>;
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        {error}
      </div>
    );
  }

  if (!tables || tables.length === 0) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-600">
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
            className="rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-sky-500 focus:outline-none"
          />
          <div className="flex max-h-[560px] flex-col gap-1 overflow-y-auto rounded-md border border-slate-200 bg-white p-1">
            {filteredTables.map((t) => (
              <button
                key={t.name}
                onClick={() => {
                  setActiveTable(t.name);
                  setExpandedColumn(null);
                }}
                className={`flex items-center justify-between rounded px-3 py-2 text-left text-sm transition-colors ${
                  t.name === activeTable
                    ? "bg-sky-50 text-sky-700"
                    : "text-slate-600 hover:bg-slate-50 hover:text-slate-800"
                }`}
              >
                <span className="truncate font-mono text-[13px]">{t.name}</span>
                <span className="ml-2 shrink-0 text-[11px] text-slate-400">
                  {t.columns.length} cols
                  {selection[t.name] ? ` · ${selection[t.name].size} sel` : ""}
                </span>
              </button>
            ))}
          </div>
        </div>

        {/* Column detail */}
        <div className="flex flex-col gap-3 rounded-md border border-slate-200 bg-white p-4">
          {active ? (
            <>
              <FlattenPanel table={active.name} />
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="font-mono text-sm text-slate-900">{active.name}</h2>
                  <p className="mt-0.5 text-xs text-slate-500">
                    {active.columns.length} columns
                    {active.row_count !== null ? ` · ${active.row_count.toLocaleString()} rows` : ""}
                  </p>
                </div>
                <input
                  value={columnSearch}
                  onChange={(e) => setColumnSearch(e.target.value)}
                  placeholder="Filter metrics…"
                  className="w-52 rounded-md border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs text-slate-900 placeholder:text-slate-400 focus:border-sky-500 focus:outline-none"
                />
              </div>

              <div className="max-h-[480px] overflow-y-auto">
                <table className="w-full border-collapse text-sm">
                  <thead className="sticky top-0 bg-white">
                    <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wide text-slate-500">
                      <th className="w-8 py-2"></th>
                      <th className="py-2 pr-4">Column</th>
                      <th className="py-2 pr-4">Type</th>
                      <th className="py-2 pr-4">Kind</th>
                      <th className="py-2">Nullable</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredColumns.map((col) => {
                      const checked = selection[active.name]?.has(col.name) ?? false;
                      const isExpanded = expandedColumn === col.name;
                      return (
                        <Fragment key={col.name}>
                          <tr className="border-b border-slate-100 hover:bg-slate-50">
                            <td className="py-1.5">
                              <input
                                type="checkbox"
                                checked={checked}
                                onChange={() => toggleColumn(active.name, col.name)}
                                className="h-3.5 w-3.5 accent-sky-600"
                              />
                            </td>
                            <td className="py-1.5 pr-4 font-mono text-[13px] text-slate-800">
                              {col.kind === "jsonb" ? (
                                <button
                                  onClick={() => setExpandedColumn(isExpanded ? null : col.name)}
                                  className="flex items-center gap-1.5 hover:text-slate-950"
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
                            <td className="py-1.5 pr-4 font-mono text-[12px] text-slate-500">
                              {col.data_type}
                            </td>
                            <td className="py-1.5 pr-4">
                              <span
                                className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${KIND_STYLES[col.kind]}`}
                              >
                                {col.kind}
                              </span>
                            </td>
                            <td className="py-1.5 text-[12px] text-slate-500">
                              {col.is_nullable ? "yes" : "no"}
                            </td>
                          </tr>
                          {isExpanded && (
                            <tr className="border-b border-slate-100">
                              <td colSpan={5} className="pb-2">
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
            <p className="text-sm text-slate-500">Select a table.</p>
          )}
        </div>
      </div>

      {/* Selection summary */}
      <div className="rounded-md border border-slate-200 bg-white p-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium text-slate-800">
            Selected metrics ({selectionCount})
          </h3>
          <div className="flex gap-2">
            <button
              onClick={copySelection}
              disabled={selectionCount === 0}
              className="rounded-md bg-slate-100 border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-200 disabled:opacity-40"
            >
              Copy as JSON
            </button>
            <Link
              href="/build"
              aria-disabled={selectionCount === 0}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                selectionCount === 0
                  ? "pointer-events-none bg-slate-100 text-slate-400"
                  : "bg-sky-600 text-white hover:bg-sky-500"
              }`}
            >
              Build custom table →
            </Link>
          </div>
        </div>
        {selectionCount === 0 ? (
          <p className="mt-2 text-xs text-slate-400">
            Check metrics above to build a selection — useful for scoping a Gold-layer table or a
            new custom metric definition.
          </p>
        ) : (
          <div className="mt-3 flex flex-col gap-2">
            {Object.entries(selection).map(([table, cols]) => (
              <div key={table} className="text-xs">
                <span className="font-mono text-slate-700">{table}</span>
                <span className="text-slate-400"> — {[...cols].sort().join(", ")}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
