"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchKwikchatStatus,
  uploadKwikchatSpend,
  type KwikchatStatus,
  type KwikchatUploadResult,
} from "@/lib/api";

/**
 * Kwikchat spend, imported from the page.
 *
 * Kwikchat is the only channel in blended spend with no feed: it is a
 * CSV somebody downloads per workspace. This is the same panel the
 * standalone tracker carries, against the same two endpoints, so a file
 * uploaded from either place lands identically.
 *
 * A day's spend is the SUM over workspaces, and the server rebuilds it
 * on every upload. `onUploaded` is how the section around this panel
 * finds out its figures have moved.
 */

const IST_OFFSET_MIN = 330;
function istDay(offsetDays = 0): string {
  const t = Date.now() + IST_OFFSET_MIN * 60000 + offsetDays * 86400000;
  return new Date(t).toISOString().slice(0, 10);
}
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/** 2026-11-09 -> 9 Nov */
const nice = (d: string) => `${+d.slice(8, 10)} ${MONTHS[+d.slice(5, 7) - 1]}`;
const kb = (n: number) => (n < 1024 ? `${n} B` : `${(n / 1024).toFixed(1)} KB`);
const money = (n: number) => n.toLocaleString("en-IN", {
  style: "currency", currency: "INR", maximumFractionDigits: 0 });
/** Only CSVs. A stray screenshot would otherwise be posted and come
 *  back as a parse error that reads like our bug. */
const isCsv = (f: File) => /\.csv$/i.test(f.name) || f.type === "text/csv";

export function KwikchatImport({ onUploaded }: { onUploaded?: () => void }) {
  const [status, setStatus] = useState<KwikchatStatus | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [account, setAccount] = useState("");
  const [overwrite, setOverwrite] = useState(false);
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const [result, setResult] = useState<KwikchatUploadResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    fetchKwikchatStatus()
      .then((s) => {
        setStatus(s);
        setAccount((a) => a || s.accounts[0]?.account || "");
      })
      // The panel is an extra: a status that will not load must not
      // take the section's figures down with it.
      .catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);

  const add = (list: FileList | File[]) => {
    // Copied out NOW. A FileList is live: the input is cleared straight
    // after this call, and an updater that read the list later would
    // find it already empty.
    const picked = [...list].filter(isCsv);
    setFiles((prev) => [...prev, ...picked]);
  };

  const upload = async () => {
    if (!files.length || !account) return;
    setBusy(true);
    setError(null);
    try {
      const res = await uploadKwikchatSpend(account, files, overwrite);
      setResult(res);
      setFiles([]);
      if (input.current) input.current.value = "";
      load();
      onUploaded?.();
    } catch (e) {
      setResult(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  if (!status) return null;
  const accounts = status.accounts;
  const missing = accounts.filter((a) => !a.updated_to).length;
  const yesterday = istDay(-1);
  // The weakest workspace bounds the total, so that is the date named.
  // Saying "updated to" the NEWEST would promise a completeness the
  // figures do not have.
  const cover = status.covered_to
    ? `every workspace in to ${nice(status.covered_to)}`
    : missing === accounts.length
      ? "nothing uploaded yet"
      : `${missing} workspace(s) have never uploaded, so day totals read low`;

  return (
    <details className="group rounded-md border border-border-primary bg-bg-white">
      <summary className="flex cursor-pointer flex-wrap items-baseline gap-x-2 gap-y-1 px-4 py-3 text-[13px] font-medium text-text-primary">
        Kwikchat spend · import
        <span className="text-[11.5px] font-normal text-text-tertiary">— {cover}</span>
      </summary>

      <div className="border-t border-border-soft px-4 pb-4 pt-4">
        <div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-border-soft bg-border-soft sm:grid-cols-4 xl:grid-cols-8">
          {accounts.map((a) => {
            const on = !!a.updated_to;
            // Amber once a workspace is more than a day behind: the day
            // total is short by whatever it has not reported.
            const stale = on && a.updated_to! < yesterday;
            return (
              <div key={a.account} className="flex gap-2 bg-bg-white px-3 py-2.5">
                <span aria-hidden="true"
                      className={`text-[13px] leading-tight ${on ? "text-success-text" : "text-text-tertiary"}`}>
                  {on ? "✓" : "○"}
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-[12px] font-semibold text-text-primary">
                    {a.account}
                  </span>
                  <span className={`mt-0.5 block text-[11px] tabular-nums ${
                    stale ? "text-warning-text" : "text-text-tertiary"}`}>
                    {on ? `to ${nice(a.updated_to!)} · ${a.days.toLocaleString("en-IN")}d`
                        : "never uploaded"}
                  </span>
                </span>
              </div>
            );
          })}
        </div>

        <label
          onDragEnter={(e) => { e.preventDefault(); setOver(true); }}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={(e) => { if (e.target === e.currentTarget) setOver(false); }}
          onDrop={(e) => {
            e.preventDefault();
            setOver(false);
            if (e.dataTransfer?.files?.length) add(e.dataTransfer.files);
          }}
          className={`mt-4 flex cursor-pointer items-center gap-3 rounded-md border border-dashed px-4 py-3.5 focus-within:border-solid focus-within:border-text-tertiary hover:border-text-tertiary ${
            over ? "border-info-mid bg-bg-muted" : "border-border-primary"}`}>
          <input ref={input} type="file" accept=".csv,text/csv" multiple className="sr-only"
                 onChange={(e) => {
                   if (e.target.files) add(e.target.files);
                   // Cleared so choosing the same file again still fires.
                   e.target.value = "";
                 }} />
          <span aria-hidden="true"
                className={`flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-lg border text-[14px] ${
                  files.length ? "border-success-text text-success-text"
                               : "border-border-primary text-text-secondary"}`}>
            {files.length ? "✓" : "↑"}
          </span>
          <span>
            <span className="block text-[12.5px] font-semibold text-text-primary">
              {files.length
                ? `${files.length} ${files.length === 1 ? "file ready" : "files ready, summed per day"}`
                : "Drop the daily-spend CSVs here, or click to choose"}
            </span>
            {/* What to do when empty, and WHICH workspace it is about to
                be filed under when not: the one mistake here that is
                tedious to undo. */}
            <span className="mt-0.5 block text-[11.5px] text-text-tertiary">
              {files.length
                ? `Will be filed under ${account}`
                : "One workspace at a time · several files for the same workspace are summed"}
            </span>
          </span>
        </label>

        {files.length > 0 && (
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            {files.map((f, i) => (
              <span key={`${f.name}-${i}`}
                    className="inline-flex items-center gap-1.5 rounded border border-border-soft bg-bg-muted px-2 py-1 text-[11.5px] text-text-primary">
                {f.name}
                <span className="tabular-nums text-text-tertiary">{kb(f.size)}</span>
                <button type="button" aria-label={`Remove ${f.name}`}
                        onClick={() => setFiles((prev) => prev.filter((_, n) => n !== i))}
                        className="rounded px-1 text-[13px] leading-none text-text-tertiary hover:text-error-text">
                  ×
                </button>
              </span>
            ))}
          </div>
        )}

        <div className="mt-3.5 flex flex-wrap items-center gap-3">
          <select value={account} onChange={(e) => setAccount(e.target.value)}
                  aria-label="Which workspace"
                  className="rounded-md border border-border-primary bg-bg-white px-2.5 py-1.5 text-[12.5px] text-text-primary">
            {accounts.map((a) => (
              <option key={a.account} value={a.account}>{a.account}</option>
            ))}
          </select>
          <label className="inline-flex items-center gap-1.5 text-[12.5px] text-text-secondary">
            <input type="checkbox" checked={overwrite}
                   onChange={(e) => setOverwrite(e.target.checked)} />
            Replace days already measured
          </label>
          <button type="button" onClick={upload} disabled={!files.length || busy}
                  className="rounded-md border border-text-primary bg-text-primary px-3.5 py-1.5 text-[12.5px] font-semibold text-bg-white disabled:cursor-default disabled:opacity-40">
            {busy ? "Uploading…" : "Upload"}
          </button>
        </div>

        {error && (
          <p role="alert" className="mt-3 text-[12px] text-error-text">✗ {error}</p>
        )}
        {result && (
          <div className="mt-3 text-[12px] text-text-primary" role="status">
            <p><span className="text-success-text">✓</span> {result.message}</p>
            {result.days.length > 0 && (
              <table className="mt-2 text-[11.5px]">
                <tbody>
                  {result.days.map((r) => (
                    <tr key={r.day}>
                      <td className="py-[3px] pr-4 tabular-nums text-text-secondary">{r.day}</td>
                      <td className="py-[3px] pr-4 text-right tabular-nums">{money(r.spend)}</td>
                      <td className="py-[3px] text-text-tertiary">
                        {r.status}
                        {r.status === "written" && r.was != null ? ` (was ${money(r.was)})` : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        <p className="mt-3.5 max-w-[80ch] text-[11px] leading-snug text-text-tertiary">
          Uploading several files one after another would leave only the last, which
          on a real month is most of the money — so pick a workspace&rsquo;s files
          together. Days it has already measured are left alone unless you tick
          replace, and a day keeps its existing total whenever that total came from
          more workspaces than this upload carries.
        </p>
      </div>
    </details>
  );
}
