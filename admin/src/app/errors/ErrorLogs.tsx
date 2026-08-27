"use client";

import { useEffect, useState } from "react";
import {
  ApiError,
  BatchSummary,
  FailedJobSchema,
  FileErrorEntry,
  FileErrorSource,
  fetchFailedJobs,
  fetchFileErrors,
  fetchLogs,
  retryFailedJobs,
} from "@/lib/api";

const REFRESH_MS = 30_000;

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString();
}

function ErrorMessage({ message }: { message: string }) {
  return (
    <pre className="mt-1 max-h-32 overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-bg-surface border border-border-primary p-2 text-xs text-text-secondary">
      {message}
    </pre>
  );
}

function FailedJobsSection() {
  const [jobs, setJobs] = useState<FailedJobSchema[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [retrying, setRetrying] = useState(false);
  const [retryResult, setRetryResult] = useState<string | null>(null);

  async function load() {
    try {
      const res = await fetchFailedJobs({ limit: 100 });
      setJobs(res);
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

  async function handleRetry() {
    setRetrying(true);
    setRetryResult(null);
    try {
      const res = await retryFailedJobs();
      setRetryResult(`Retried ${res.retried}, resolved ${res.resolved}, still failing ${res.still_failing}.`);
      await load();
    } catch (err) {
      setRetryResult(err instanceof ApiError ? err.message : "Retry failed.");
    } finally {
      setRetrying(false);
    }
  }

  return (
    <div className="rounded-lg border border-border-primary bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-medium text-text-primary">Meta — failed jobs (retryable)</h2>
          <p className="mt-0.5 text-xs text-text-secondary">
            Unresolved rows in <code className="text-text-secondary">failed_jobs</code> — the scheduler also
            retries these automatically every few minutes.
          </p>
        </div>
        <button
          onClick={handleRetry}
          disabled={retrying || jobs.length === 0}
          className="shrink-0 rounded-md bg-accent-yellow px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-accent-yellow-hover disabled:opacity-50"
        >
          {retrying ? "Retrying…" : "Retry all now"}
        </button>
      </div>

      {retryResult && <p className="mt-2 text-xs text-text-secondary">{retryResult}</p>}
      {error && <p className="mt-2 text-xs text-error-text">{error}</p>}

      {!loading && (
        <div className="mt-4 flex flex-col gap-2">
          {jobs.length === 0 && <p className="text-sm text-text-tertiary">No unresolved failed jobs.</p>}
          {jobs.map((job) => (
            <div key={job.id} className="rounded-md border border-border-primary p-3">
              <div className="flex items-center justify-between text-sm">
                <span className="text-text-primary">
                  {job.endpoint} — {job.account_name ?? job.account_key ?? "no account"}
                </span>
                <span className="text-xs text-text-secondary">
                  attempt {job.attempt_count} · last {formatDateTime(job.last_attempted_at)}
                </span>
              </div>
              <ErrorMessage message={job.error_message} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
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

function BatchLogSection() {
  const [batches, setBatches] = useState<BatchSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    try {
      const res = await fetchLogs({ limit: 50 });
      setBatches(res);
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

  return (
    <div className="rounded-lg border border-border-primary bg-white p-5 shadow-sm">
      <h2 className="text-sm font-medium text-text-primary">Meta — recent batch log</h2>
      <p className="mt-0.5 text-xs text-text-secondary">Every sync attempt, most recent first, success and failure alike.</p>

      {error && <p className="mt-2 text-xs text-error-text">{error}</p>}

      {!loading && (
        <div className="mt-4 flex flex-col gap-2">
          {batches.length === 0 && <p className="text-sm text-text-tertiary">No batches logged yet.</p>}
          {batches
            .filter((b) => b.status !== "success")
            .map((b) => (
              <div key={b.batch_id} className="rounded-md border border-border-primary p-3">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-text-primary">
                    {b.endpoint} — {b.account_name ?? b.account_key ?? "no account"}
                  </span>
                  <div className="flex items-center gap-2 text-xs text-text-secondary">
                    <span>{formatDateTime(b.started_at)}</span>
                    <span className={`rounded-full px-2 py-0.5 font-medium ${statusBadgeClass(b.status)}`}>
                      {b.status}
                    </span>
                  </div>
                </div>
                {b.error_message && <ErrorMessage message={b.error_message} />}
              </div>
            ))}
          {batches.length > 0 && batches.every((b) => b.status === "success") && (
            <p className="text-sm text-text-tertiary">Every recent batch succeeded.</p>
          )}
        </div>
      )}
    </div>
  );
}

function FileErrorsSection({ source, title }: { source: FileErrorSource; title: string }) {
  const [entries, setEntries] = useState<FileErrorEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    try {
      const res = await fetchFileErrors(source, 25);
      setEntries(res.errors);
      setTotal(res.total);
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

  return (
    <div className="rounded-lg border border-border-primary bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-medium text-text-primary">{title}</h2>
          <p className="mt-0.5 text-xs text-text-secondary">
            Runs as a standalone script, no DB access — errors come from{" "}
            <code className="text-text-secondary">logs/{source}_ingest_errors.log</code>.
          </p>
        </div>
        <span className="text-xs text-text-secondary">{total} total</span>
      </div>

      {error && <p className="mt-2 text-xs text-error-text">{error}</p>}

      {!loading && (
        <div className="mt-4 flex flex-col gap-2">
          {entries.length === 0 && <p className="text-sm text-text-tertiary">No errors logged.</p>}
          {entries.map((e, i) => (
            <div key={i} className="rounded-md border border-border-primary p-3">
              <div className="flex items-center justify-between text-sm">
                <span className="text-text-primary">
                  {e.object_type} — {e.label}
                </span>
                <span className="text-xs text-text-secondary">{formatDateTime(e.timestamp)}</span>
              </div>
              <ErrorMessage message={e.message} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function ErrorLogs() {
  return (
    <div className="flex flex-col gap-6">
      <FailedJobsSection />
      <BatchLogSection />
      <FileErrorsSection source="shopify" title="Shopify fetch errors" />
      <FileErrorsSection source="instagram" title="Instagram fetch errors" />
    </div>
  );
}
