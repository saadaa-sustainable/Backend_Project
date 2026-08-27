"use client";

import { useEffect, useState } from "react";
import {
  ApiError,
  BatchSummary,
  SchedulerStatusResponse,
  StatusResponse,
  fetchSchedulerStatus,
  fetchStatus,
} from "@/lib/api";

const REFRESH_MS = 30_000;

function formatDateTime(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}

function statusBadgeClass(status: BatchSummary["status"]): string {
  switch (status) {
    case "success":
      return "bg-success-bg text-success-text";
    case "failed":
      return "bg-error-bg text-error-text";
    case "partial_failure":
      return "bg-warning-bg text-warning-text";
    default:
      return "bg-bg-muted text-text-secondary";
  }
}

export function CronStatus() {
  const [scheduler, setScheduler] = useState<SchedulerStatusResponse | null>(null);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    try {
      const [schedulerRes, statusRes] = await Promise.all([
        fetchSchedulerStatus(),
        fetchStatus({ limit: 20 }),
      ]);
      setScheduler(schedulerRes);
      setStatus(statusRes);
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
      <div className="rounded-md border border-error-mid bg-error-bg p-3 text-sm text-error-text">
        {error}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="rounded-lg border border-border-primary bg-white p-5 shadow-sm">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-text-primary">Scheduler</h2>
          <div className="flex items-center gap-2">
            <span
              className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                scheduler?.enabled
                  ? "bg-success-bg text-success-text"
                  : "bg-bg-muted text-text-secondary"
              }`}
            >
              {scheduler?.enabled ? "enabled" : "disabled"}
            </span>
            <span
              className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                scheduler?.running
                  ? "bg-success-bg text-success-text"
                  : "bg-error-bg text-error-text"
              }`}
            >
              {scheduler?.running ? "running" : "stopped"}
            </span>
            <span className="text-xs text-text-secondary">{scheduler?.timezone}</span>
          </div>
        </div>

        <div className="mt-4 flex flex-col gap-2">
          {scheduler?.jobs.length === 0 && (
            <p className="text-sm text-text-secondary">No jobs registered.</p>
          )}
          {scheduler?.jobs.map((job) => (
            <div
              key={job.id}
              className="flex items-center justify-between rounded-md border border-border-primary px-3 py-2 text-sm"
            >
              <div>
                <p className="text-text-primary">{job.name}</p>
                <p className="mt-0.5 font-mono text-xs text-text-secondary">{job.trigger}</p>
              </div>
              <span className="text-xs text-text-secondary">next: {formatDateTime(job.next_run_time)}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-lg border border-border-primary bg-white p-5 shadow-sm">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-text-primary">Recent sync batches</h2>
          <div className="flex items-center gap-3 text-xs">
            <span className="text-text-secondary">{status?.total_batches} total</span>
            <span className="text-success-mid">{status?.succeeded} ok</span>
            {status && status.partial_failures > 0 && (
              <span className="text-warning-mid">{status.partial_failures} partial</span>
            )}
            <span className="text-error-text">{status?.failed} failed</span>
          </div>
        </div>

        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border-primary text-xs text-text-secondary">
                <th className="pb-2 pr-4 font-medium">Endpoint</th>
                <th className="pb-2 pr-4 font-medium">Account</th>
                <th className="pb-2 pr-4 font-medium">Started</th>
                <th className="pb-2 pr-4 font-medium">Records</th>
                <th className="pb-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {status?.recent_batches.map((b) => (
                <tr key={b.batch_id} className="border-b border-border-soft">
                  <td className="py-2 pr-4 text-text-primary">{b.endpoint}</td>
                  <td className="py-2 pr-4 text-text-secondary">{b.account_name ?? b.account_key ?? "—"}</td>
                  <td className="py-2 pr-4 text-text-secondary">{formatDateTime(b.started_at)}</td>
                  <td className="py-2 pr-4 text-text-secondary">
                    {b.records_fetched}
                    {b.records_failed > 0 && <span className="text-error-text"> ({b.records_failed} failed)</span>}
                  </td>
                  <td className="py-2">
                    <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${statusBadgeClass(b.status)}`}>
                      {b.status}
                    </span>
                  </td>
                </tr>
              ))}
              {status?.recent_batches.length === 0 && (
                <tr>
                  <td colSpan={5} className="py-4 text-center text-text-secondary">
                    No sync batches yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
