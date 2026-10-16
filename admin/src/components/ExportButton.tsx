"use client";

import { useEffect, useRef, useState } from "react";

/**
 * ExportButton — CSV export for any analytics table.
 *
 * Usage:
 *   <ExportButton
 *     rows={rows}
 *     filename="cpis"
 *     window="30d"                 // optional -- appended to filename
 *     disabled={loading || !rows.length}
 *     fetchAll={() => ...}         // optional -- enables "All rows"
 *     totalRows={total}            // optional -- labels the menu
 *   />
 *
 * WHAT GETS EXPORTED
 *
 * These tables are paginated: the rows on screen are the pages the
 * reader has pressed "Load more" for, not the rows the filters match.
 * Exporting only those was quietly wrong -- the file looked complete
 * and was a 50-row slice of a 2,872-row result.
 *
 * So when the caller passes `fetchAll`, the button becomes a choice:
 * the rows on screen, or every row the current filters match, walked
 * out of the API page by page. Without `fetchAll` it stays the single
 * action it was, which is correct for the sections that already hold
 * their whole result set.
 *
 * Behavior:
 *  - CSV headers are Object.keys(rows[0]) unless `columns` is passed
 *    to force order / rename.
 *  - Objects/arrays get JSON.stringify'd so nested jsonb columns
 *    (stock_by_size, thumbnails, etc.) still land in the file.
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
  /** Returns every row the current filters match. Its presence is what
   *  turns the button into a menu; omit it for an unpaginated table. */
  fetchAll?: () => Promise<T[]>;
  /** The server's count of matching rows, for the menu label. */
  totalRows?: number;
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

function DownloadIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  );
}

const BUTTON_CLASS =
  "inline-flex items-center gap-1.5 rounded-md border border-border-primary bg-white " +
  "px-3 py-1.5 text-xs font-medium text-text-primary shadow-sm transition " +
  "hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-50";

export function ExportButton<T extends Record<string, unknown>>({
  rows,
  filename,
  window: windowLabel,
  columns,
  disabled,
  className,
  fetchAll,
  totalRows,
}: Props<T>) {
  const empty = !rows || rows.length === 0;
  const isDisabled = disabled || empty;
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  // A menu that stays open after the pointer leaves is a menu that
  // covers the table underneath it.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  function download(data: T[], suffix: string) {
    const csv = buildCsv(data, columns);
    // Prepend UTF-8 BOM so Excel opens rupee / accented characters
    // in the right encoding without a manual import step.
    const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const winSuffix = windowLabel ? `_${windowLabel}` : "";
    a.href = url;
    // The file says which of the two it is. Two exports of the same
    // table on the same day otherwise overwrite each other in the
    // downloads folder, and nothing in the file distinguishes them.
    a.download = `${filename}_${todayISO()}${winSuffix}_${suffix}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  const exportLoaded = () => {
    if (isDisabled) return;
    setOpen(false);
    setError(null);
    download(rows, `${rows.length}rows`);
  };

  const exportAll = async () => {
    if (!fetchAll || busy) return;
    setOpen(false);
    setError(null);
    setBusy("Fetching…");
    try {
      const all = await fetchAll();
      if (all.length === 0) {
        setError("Nothing matched");
        return;
      }
      download(all, `all_${all.length}rows`);
    } catch {
      // Never a silent no-op: a button that does nothing reads as a
      // bug in the page rather than a failed request.
      setError("Export failed");
    } finally {
      setBusy(null);
    }
  };

  // No way to fetch the rest, so there is no choice to offer.
  if (!fetchAll) {
    return (
      <button
        type="button"
        onClick={exportLoaded}
        disabled={isDisabled}
        title={empty ? "No rows to export" : `Export ${rows.length} rows as CSV`}
        className={className ?? BUTTON_CLASS}
      >
        <DownloadIcon />
        Export CSV
      </button>
    );
  }

  // `totalRows` is the server's count of matching rows; it is unknown
  // until the first response lands, and on a filtered-to-nothing table
  // it is legitimately 0.
  const total = totalRows ?? rows.length;
  const more = total > rows.length;

  return (
    <div className="relative inline-flex flex-col items-end" ref={wrapRef}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={isDisabled || busy !== null}
        aria-haspopup="menu"
        aria-expanded={open}
        title={empty ? "No rows to export" : "Export as CSV"}
        className={className ?? BUTTON_CLASS}
      >
        <DownloadIcon />
        {busy ?? "Export CSV"}
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {open && (
        <div role="menu"
          className="absolute right-0 top-full z-20 mt-1 w-64 overflow-hidden rounded-md border border-border-primary bg-white py-1 shadow-lg">
          <button type="button" role="menuitem" onClick={exportLoaded}
            className="flex w-full flex-col items-start gap-0.5 px-3 py-2 text-left hover:bg-bg-surface">
            <span className="text-xs font-medium text-text-primary">
              Rows loaded ({rows.length.toLocaleString("en-IN")})
            </span>
            <span className="text-[11px] text-text-tertiary">
              Only what the table has fetched so far
            </span>
          </button>
          <button type="button" role="menuitem" onClick={exportAll}
            className="flex w-full flex-col items-start gap-0.5 px-3 py-2 text-left hover:bg-bg-surface">
            <span className="text-xs font-medium text-text-primary">
              All rows{totalRows !== undefined && ` (${total.toLocaleString("en-IN")})`}
            </span>
            <span className="text-[11px] text-text-tertiary">
              {more
                ? "Every row these filters match — fetched now"
                : "Everything matching; the table already has it all"}
            </span>
          </button>
        </div>
      )}

      {error && (
        <span role="alert" className="mt-1 text-[11px] text-error-text">{error}</span>
      )}
    </div>
  );
}
