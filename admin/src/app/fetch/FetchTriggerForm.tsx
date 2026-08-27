"use client";

import { useEffect, useRef, useState } from "react";
import {
  ApiError,
  fetchIngestStatus,
  triggerIngest,
  type IngestRunStatus,
  type IngestSource,
  type IngestSourceStatusValue,
  type LevelStatus,
} from "@/lib/api";
import { SourceLogo } from "@/components/SourceLogo";

// Empty now that meta/instagram/shopify all have dedicated panels above
// this form on the Fetch page (see MetaFetchPanel.tsx/InstagramFetchPanel.tsx/
// ShopifyFetchPanel.tsx) -- kept as a placeholder for the next source that
// needs date-range wiring, not currently rendered (see fetch/page.tsx).
const SOURCES: {
  id: IngestSource;
  label: string;
  supportsDateRange: boolean;
  note: string;
}[] = [];

function todayIso(offsetDays = 0): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return d.toISOString().slice(0, 10);
}

export function ProgressBar({ status }: { status: IngestSourceStatusValue }) {
  const fillClass =
    status === "succeeded"
      ? "bg-success-mid"
      : status === "failed"
        ? "bg-error-bg0"
        : status === "skipped" || status === "stopped"
          ? "bg-border-mid"
          : "bg-accent-yellow";

  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-bg-muted">
      {status === "running" ? (
        <div className={`h-full w-1/3 rounded-full ${fillClass} animate-progress-indeterminate`} />
      ) : (
        <div className={`h-full w-full rounded-full ${fillClass} transition-all duration-500`} />
      )}
    </div>
  );
}

// Per-account, per-(level|edge) pass/fail breakdown shown under a running
// or finished progress bar -- populated live for Instagram (one entry per
// callback as each edge completes) and post-hoc for Meta (reconstructed
// once the whole sync finishes, since Meta has no live callback wired
// through its sync service). A label can legitimately appear twice for
// the same account (once succeeded, once failed) if it partially landed
// data before a later attempt for that same level failed -- shown as two
// separate badges rather than collapsed, since both are true.
export function LevelBadges({ levels }: { levels: LevelStatus[] }) {
  if (levels.length === 0) return null;

  const byAccount = new Map<string, LevelStatus[]>();
  for (const l of levels) {
    const key = l.account_name ?? l.account_key ?? "—";
    byAccount.set(key, [...(byAccount.get(key) ?? []), l]);
  }

  return (
    <div className="mt-2 flex flex-col gap-1.5">
      {[...byAccount.entries()].map(([account, entries]) => (
        <div key={account} className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-text-secondary">{account}:</span>
          {entries.map((l, i) => (
            <span
              key={`${l.label}-${i}`}
              title={l.error ?? undefined}
              className={`rounded-full px-2 py-0.5 font-medium ${
                l.status === "succeeded" ? "bg-success-bg text-success-text" : "bg-error-bg text-error-text"
              }`}
            >
              {l.label}
            </span>
          ))}
        </div>
      ))}
    </div>
  );
}

export function FetchTriggerForm() {
  const [selected, setSelected] = useState<Set<IngestSource>>(new Set());
  const [dateStart, setDateStart] = useState(todayIso(-15));
  const [dateEnd, setDateEnd] = useState(todayIso());
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<IngestRunStatus | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  function toggleSource(id: IngestSource) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (selected.size === 0) {
      setError("Pick at least one source.");
      return;
    }
    if (dateStart > dateEnd) {
      setError("Start date must be on or before the end date.");
      return;
    }
    setError(null);
    setSubmitting(true);
    setStatus(null);
    if (pollRef.current) clearInterval(pollRef.current);

    try {
      const run = await triggerIngest({
        sources: [...selected],
        date_start: dateStart,
        date_end: dateEnd,
      });
      pollRef.current = setInterval(async () => {
        try {
          const s = await fetchIngestStatus(run.run_id);
          setStatus(s);
          if (s.finished_at && pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
        } catch (err) {
          if (pollRef.current) clearInterval(pollRef.current);
          setError(err instanceof ApiError ? err.message : "Lost track of the run.");
        }
      }, 2000);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not reach the FastAPI backend. Is it running?",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <form
        onSubmit={handleSubmit}
        className="flex flex-col gap-5 rounded-md border border-border-primary bg-white p-5"
      >
        <div>
          <h3 className="mb-2 text-sm font-medium text-text-primary">Source</h3>
          <div className="flex flex-col gap-2">
            {SOURCES.map((s) => (
              <label
                key={s.id}
                className="flex cursor-pointer items-start gap-3 rounded-md border border-border-primary p-3 hover:border-border-mid"
              >
                <input
                  type="checkbox"
                  checked={selected.has(s.id)}
                  onChange={() => toggleSource(s.id)}
                  className="mt-0.5 h-4 w-4 accent-accent-yellow"
                />
                <div>
                  <div className="flex items-center gap-2">
                    <SourceLogo source={s.id} className="h-5 w-5 shrink-0" />
                    <span className="text-sm text-text-primary">{s.label}</span>
                    <span
                      className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${
                        s.supportsDateRange
                          ? "bg-success-bg text-success-text"
                          : "bg-warning-bg text-warning-text"
                      }`}
                    >
                      {s.supportsDateRange ? "dynamic date range" : "date range not wired yet"}
                    </span>
                  </div>
                  <p className="mt-0.5 text-xs text-text-secondary">{s.note}</p>
                </div>
              </label>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-text-primary">
              Date start
            </label>
            <input
              type="date"
              value={dateStart}
              onChange={(e) => setDateStart(e.target.value)}
              className="w-full rounded-md border border-border-primary bg-white px-3 py-2 text-sm text-text-primary focus:border-accent-yellow focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-text-primary">Date end</label>
            <input
              type="date"
              value={dateEnd}
              onChange={(e) => setDateEnd(e.target.value)}
              className="w-full rounded-md border border-border-primary bg-white px-3 py-2 text-sm text-text-primary focus:border-accent-yellow focus:outline-none"
            />
          </div>
        </div>

        {error && (
          <div className="rounded-md border border-error-mid bg-error-bg p-3 text-sm text-error-text">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="self-start rounded-md bg-accent-yellow px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-yellow-hover disabled:opacity-50"
        >
          {submitting ? "Starting…" : "Run ingestion"}
        </button>
      </form>

      {status && (
        <div className="rounded-md border border-border-primary bg-white p-5">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-text-primary">
              Run <span className="font-mono text-text-secondary">{status.run_id}</span>
            </h3>
            <span className="text-xs text-text-secondary">
              {status.finished_at ? `finished ${status.finished_at}` : "running…"}
            </span>
          </div>
          <div className="mt-3 flex flex-col gap-2">
            {Object.entries(status.sources).map(([source, s]) => (
              <div key={source} className="rounded-md border border-border-primary px-3 py-2">
                <div className="flex items-center justify-between text-sm">
                  <div className="flex items-center gap-2">
                    <SourceLogo source={source as IngestSource} className="h-4 w-4 shrink-0" />
                    <span className="text-text-primary">{source}</span>
                  </div>
                  <div className="flex items-center gap-3 text-xs">
                    {s.rows_ingested !== null && (
                      <span className="text-text-secondary">{s.rows_ingested} rows</span>
                    )}
                    {s.error && <span className="text-error-text">{s.error}</span>}
                    <span
                      className={`rounded-full px-2 py-0.5 font-medium ${
                        s.status === "succeeded"
                          ? "bg-success-bg text-success-text"
                          : s.status === "failed"
                            ? "bg-error-bg text-error-text"
                            : s.status === "skipped"
                              ? "bg-bg-muted text-text-secondary"
                              : "bg-warning-bg text-warning-text"
                      }`}
                    >
                      {s.status}
                    </span>
                  </div>
                </div>
                <div className="mt-2">
                  <ProgressBar status={s.status} />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
