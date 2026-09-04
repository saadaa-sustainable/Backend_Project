"use client";

/**
 * ExportButton — one-click CSV export for any analytics table.
 *
 * Usage:
 *   <ExportButton
 *     rows={rows}
 *     filename="cpis"
 *     window="30d"                 // optional -- appended to filename
 *     disabled={loading || !rows.length}
 *   />
 *
 * Behavior:
 *  - CSV headers are Object.keys(rows[0]) unless `columns` is passed
 *    to force order / rename.
 *  - Objects/arrays get JSON.stringify'd so nested jsonb columns
 *    (mm_stock_by_size, thumbnails, etc.) still land in the file.
 *  - Values with commas / quotes / newlines are quoted per RFC 4180.
 *  - null / undefined -> empty cell.
 *  - Filename: `{filename}_{yyyy-mm-dd}[_{window}].csv`.
 *
 * Zero deps — Blob + URL.createObjectURL do the download without any
 * client-side XLSX library. If we ever want formatted Excel output,
 * swap the Blob type + add a xlsx dep here in one place.
 */

interface Column<T> {
  key: keyof T | string;
  label?: string;   // display name for the CSV header
}

interface Props<T> {
  rows: T[];
  filename: string;
  window?: string;
  columns?: Column<T>[];
  disabled?: boolean;
  className?: string;
}

const CELL_NEEDS_QUOTE = /[",\r\n]/;

function serializeCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (typeof value === "object") {
    // jsonb columns land here (dicts, arrays). Stringify so the row
    // still opens in Excel; downstream analysts can eval the cell.
    return JSON.stringify(value);
  }
  const s = String(value);
  if (CELL_NEEDS_QUOTE.test(s)) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

function buildCsv<T extends Record<string, unknown>>(
  rows: T[],
  columns?: Column<T>[],
): string {
  if (!rows.length) return "";
  const cols: Column<T>[] = columns ?? Object.keys(rows[0]).map((k) => ({ key: k }));
  const header = cols.map((c) => serializeCell(c.label ?? String(c.key))).join(",");
  const body = rows
    .map((row) => cols.map((c) => serializeCell((row as Record<string, unknown>)[String(c.key)])).join(","))
    .join("\n");
  return `${header}\n${body}`;
}

function todayISO(): string {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

export function ExportButton<T extends Record<string, unknown>>({
  rows,
  filename,
  window,
  columns,
  disabled,
  className,
}: Props<T>) {
  const empty = !rows || rows.length === 0;
  const isDisabled = disabled || empty;

  const handleClick = () => {
    if (isDisabled) return;
    const csv = buildCsv(rows, columns);
    // Prepend UTF-8 BOM so Excel opens rupee / accented characters
    // in the right encoding without a manual import step.
    const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const winSuffix = window ? `_${window}` : "";
    a.href = url;
    a.download = `${filename}_${todayISO()}${winSuffix}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={isDisabled}
      title={empty ? "No rows to export" : `Export ${rows.length} rows as CSV`}
      className={
        className ??
        "inline-flex items-center gap-1.5 rounded-md border border-border-primary bg-white px-3 py-1.5 text-xs font-medium text-text-primary shadow-sm transition hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-50"
      }
    >
      <svg
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
        <polyline points="7 10 12 15 17 10" />
        <line x1="12" y1="15" x2="12" y2="3" />
      </svg>
      Export CSV
    </button>
  );
}
