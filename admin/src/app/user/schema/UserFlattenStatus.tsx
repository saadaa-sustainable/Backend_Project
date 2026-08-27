"use client";

import { useEffect, useState } from "react";
import { ApiError, FlattenJob, fetchFlattenJobsForTable } from "@/lib/api";

function formatTime(iso: string | null): string {
  if (!iso) return "never";
  return new Date(iso).toLocaleString();
}

// Read-only counterpart to admin/src/app/schema/FlattenPanel.tsx -- same
// per-table job status, no "Flatten now" button or auto-flatten toggle.
export function UserFlattenStatus({ table }: { table: string }) {
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

  return (
    <div className="mb-1 flex flex-col gap-2">
      {jobs.map((job) => (
        <div key={job.key} className="rounded-md border border-border-primary bg-bg-surface p-3">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-medium text-text-primary">{job.label}</h3>
            <span
              className={`rounded px-2 py-0.5 text-[10px] font-medium ${
                job.is_stale ? "bg-warning-bg text-warning-text" : "bg-success-bg text-success-text"
              }`}
            >
              {job.is_stale ? "Stale" : "Up to date"}
            </span>
          </div>
          <p className="mt-1 text-[11px] text-text-secondary">
            Last run: {job.last_run_status ?? "never run"}
            {job.last_run_at ? ` at ${formatTime(job.last_run_at)}` : ""}.
          </p>
        </div>
      ))}
    </div>
  );
}
