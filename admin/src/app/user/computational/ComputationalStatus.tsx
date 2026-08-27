"use client";

import { useEffect, useState } from "react";
import { ApiError, FlattenJob, fetchFlattenJobs } from "@/lib/api";

const REFRESH_MS = 30_000;

function formatTime(iso: string | null): string {
  if (!iso) return "never";
  return new Date(iso).toLocaleString();
}

function JobCard({ job }: { job: FlattenJob }) {
  return (
    <div className="rounded-md border border-border-primary bg-bg-surface p-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium text-text-primary">{job.label}</h3>
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
    </div>
  );
}

export function ComputationalStatus() {
  const [jobs, setJobs] = useState<FlattenJob[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    try {
      setJobs(await fetchFlattenJobs());
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the FastAPI backend. Is it running?");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    const interval = setInterval(load, REFRESH_MS);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return <p className="text-sm text-text-secondary">Loading…</p>;
  }

  if (error) {
    return (
      <div className="rounded-md border border-error-mid bg-error-bg p-3 text-sm text-error-text">{error}</div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {jobs?.map((job) => <JobCard key={job.key} job={job} />)}
      {jobs?.length === 0 && <p className="text-sm text-text-secondary">No flatten jobs registered.</p>}
    </div>
  );
}
