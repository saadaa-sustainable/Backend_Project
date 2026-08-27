"use client";

import { useEffect, useState } from "react";
import {
  ApiError,
  fetchFlattenJobsForTable,
  runFlattenJob,
  setFlattenAutoEnabled,
  type FlattenJob,
} from "@/lib/api";

function formatTime(iso: string | null): string {
  if (!iso) return "never";
  return new Date(iso).toLocaleString();
}

function FlattenJobCard({ job, table, onUpdate }: { job: FlattenJob; table: string; onUpdate: (j: FlattenJob) => void }) {
  const [running, setRunning] = useState(false);
  const [togglingAuto, setTogglingAuto] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isSource = job.source_table === table;

  async function handleRun() {
    setRunning(true);
    setError(null);
    try {
      onUpdate(await runFlattenJob(job.key));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Flatten failed.");
    } finally {
      setRunning(false);
    }
  }

  async function handleToggleAuto() {
    setTogglingAuto(true);
    setError(null);
    try {
      onUpdate(await setFlattenAutoEnabled(job.key, !job.auto_enabled));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update auto-flatten.");
    } finally {
      setTogglingAuto(false);
    }
  }

  return (
    <div className="mb-3 rounded-md border border-border-primary bg-bg-surface p-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium text-text-primary">Flatten — {job.label}</h3>
          <p className="mt-0.5 font-mono text-xs text-text-secondary">
            {job.source_table} → {job.target_tables.join(", ")}
          </p>
        </div>
        <span
          className={`rounded px-2 py-0.5 text-[11px] font-medium ${
            job.is_stale ? "bg-warning-bg text-warning-text" : "bg-success-bg text-success-text"
          }`}
        >
          {job.is_stale ? "Stale — raw data has changed" : "Up to date"}
        </span>
      </div>

      <p className="mt-2 text-xs text-text-secondary">
        {isSource
          ? "This is the raw (Bronze) source for this flatten job."
          : "This table is built from the flatten job below."}{" "}
        Last run: {job.last_run_status ?? "never run"}
        {job.last_run_at ? ` at ${formatTime(job.last_run_at)}` : ""}
        {job.last_run_triggered_by ? ` (${job.last_run_triggered_by})` : ""}.
      </p>

      {job.last_rows_written && (
        <p className="mt-1 font-mono text-[11px] text-text-secondary">
          {Object.entries(job.last_rows_written)
            .map(([t, c]) => `${t}: ${c.toLocaleString()} rows`)
            .join(" · ")}
        </p>
      )}

      {job.last_error && <p className="mt-1 text-xs text-error-text">Last error: {job.last_error}</p>}
      {error && <p className="mt-1 text-xs text-error-text">{error}</p>}

      <div className="mt-3 flex items-center gap-3">
        <button
          onClick={handleRun}
          disabled={running}
          className="rounded-md bg-accent-yellow px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-accent-yellow-hover disabled:opacity-40"
        >
          {running ? "Flattening…" : "Flatten now"}
        </button>
        <label className="flex items-center gap-1.5 text-xs text-text-secondary">
          <input
            type="checkbox"
            checked={job.auto_enabled}
            onChange={handleToggleAuto}
            disabled={togglingAuto}
            className="h-3.5 w-3.5 accent-accent-yellow"
          />
          Auto-flatten when raw data updates
        </label>
      </div>
    </div>
  );
}

export function FlattenPanel({ table }: { table: string }) {
  // undefined = still loading; [] = no jobs registered for this table -- render nothing either way
  const [jobs, setJobs] = useState<FlattenJob[] | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setJobs(undefined);
    setError(null);
    fetchFlattenJobsForTable(table)
      .then((res) => !cancelled && setJobs(res))
      .catch((err: unknown) => {
        if (cancelled) return;
        setJobs([]);
        setError(err instanceof ApiError ? err.message : "Could not check flatten status.");
      });
    return () => {
      cancelled = true;
    };
  }, [table]);

  if (!jobs || jobs.length === 0) {
    return error ? <p className="mb-4 text-xs text-error-text">{error}</p> : null;
  }

  function updateJob(updated: FlattenJob) {
    setJobs((prev) => (prev ? prev.map((j) => (j.key === updated.key ? updated : j)) : prev));
  }

  return (
    <div className="mb-1">
      {jobs.map((job) => (
        <FlattenJobCard key={job.key} job={job} table={table} onUpdate={updateJob} />
      ))}
    </div>
  );
}
