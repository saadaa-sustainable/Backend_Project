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
      return "bg-emerald-100 text-emerald-700";
    case "failed":
      return "bg-red-100 text-red-700";
    case "partial_failure":
      return "bg-amber-100 text-amber-700";
    default:
      return "bg-slate-100 text-slate-500";
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
    return <p className="text-sm text-slate-500">Loading…</p>;
  }

  if (error) {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
        {error}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-slate-900">Scheduler</h2>
          <div className="flex items-center gap-2">
            <span
              className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                scheduler?.enabled
                  ? "bg-emerald-100 text-emerald-700"
                  : "bg-slate-100 text-slate-500"
              }`}
            >
              {scheduler?.enabled ? "enabled" : "disabled"}
            </span>
            <span
              className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                scheduler?.running
                  ? "bg-emerald-100 text-emerald-700"
                  : "bg-red-100 text-red-700"
              }`}
            >
              {scheduler?.running ? "running" : "stopped"}
            </span>
            <span className="text-xs text-slate-500">{scheduler?.timezone}</span>
          </div>
        </div>

        <div className="mt-4 flex flex-col gap-2">
          {scheduler?.jobs.length === 0 && (
            <p className="text-sm text-slate-600">No jobs registered.</p>
          )}
          {scheduler?.jobs.map((job) => (
            <div
              key={job.id}
              className="flex items-center justify-between rounded-md border border-slate-200 px-3 py-2 text-sm"
            >
              <div>
                <p className="text-slate-800">{job.name}</p>
                <p className="mt-0.5 font-mono text-xs text-slate-500">{job.trigger}</p>
              </div>
              <span className="text-xs text-slate-500">next: {formatDateTime(job.next_run_time)}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-slate-900">Recent sync batches</h2>
          <div className="flex items-center gap-3 text-xs">
            <span className="text-slate-500">{status?.total_batches} total</span>
            <span className="text-emerald-600">{status?.succeeded} ok</span>
            {status && status.partial_failures > 0 && (
              <span className="text-amber-600">{status.partial_failures} partial</span>
            )}
            <span className="text-red-600">{status?.failed} failed</span>
          </div>
        </div>

        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-xs text-slate-500">
                <th className="pb-2 pr-4 font-medium">Endpoint</th>
                <th className="pb-2 pr-4 font-medium">Account</th>
                <th className="pb-2 pr-4 font-medium">Started</th>
                <th className="pb-2 pr-4 font-medium">Records</th>
                <th className="pb-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {status?.recent_batches.map((b) => (
                <tr key={b.batch_id} className="border-b border-slate-100">
                  <td className="py-2 pr-4 text-slate-800">{b.endpoint}</td>
                  <td className="py-2 pr-4 text-slate-600">{b.account_name ?? b.account_key ?? "—"}</td>
                  <td className="py-2 pr-4 text-slate-500">{formatDateTime(b.started_at)}</td>
                  <td className="py-2 pr-4 text-slate-500">
                    {b.records_fetched}
                    {b.records_failed > 0 && <span className="text-red-600"> ({b.records_failed} failed)</span>}
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
                  <td colSpan={5} className="py-4 text-center text-slate-500">
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
