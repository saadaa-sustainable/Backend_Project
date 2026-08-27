"use client";

import { useEffect, useRef, useState } from "react";
import {
  ApiError,
  createRawTable,
  fetchIngestStatus,
  fetchRawTables,
  stopIngest,
  triggerIngest,
  type IngestRunStatus,
  type RawTableOut,
} from "@/lib/api";
import { SourceLogo } from "@/components/SourceLogo";
import { LevelBadges, ProgressBar } from "./FetchTriggerForm";

type Mode = "existing" | "new";

function formatDateTime(value: string | null): string {
  if (!value) return "never";
  return new Date(value).toLocaleString();
}

export function InstagramFetchPanel() {
  const [tables, setTables] = useState<RawTableOut[] | null>(null);
  const [mode, setMode] = useState<Mode>("existing");
  const [selectedTable, setSelectedTable] = useState("");
  const [newTableName, setNewTableName] = useState("");
  const [creating, setCreating] = useState(false);
  const [createdTable, setCreatedTable] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);

  const [sinceDate, setSinceDate] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<IngestRunStatus | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function loadTables() {
    fetchRawTables("instagram")
      .then((res) => {
        setTables(res);
        setSelectedTable((prev) => prev || res[0]?.name || "");
      })
      .catch(() => setTables(null));
  }

  useEffect(() => {
    loadTables();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  async function handleCreateTable() {
    const name = newTableName.trim();
    if (!name) return;
    setCreating(true);
    setCreateError(null);
    try {
      const res = await createRawTable(name, "instagram");
      if (res.status === "created") {
        setCreatedTable(res.table_name);
        loadTables();
      } else {
        setCreateError(res.error ?? "Could not create the table.");
      }
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : "Could not reach the backend.");
    } finally {
      setCreating(false);
    }
  }

  async function handleStartFetch(targetTable: string) {
    setError(null);
    setSubmitting(true);
    setStatus(null);
    if (pollRef.current) clearInterval(pollRef.current);

    try {
      const run = await triggerIngest({
        sources: ["instagram"],
        target_table: targetTable,
        since: sinceDate || undefined,
      });
      pollRef.current = setInterval(async () => {
        try {
          const s = await fetchIngestStatus(run.run_id);
          setStatus(s);
          if (s.finished_at && pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
            loadTables();
          }
        } catch (err) {
          if (pollRef.current) clearInterval(pollRef.current);
          setError(err instanceof ApiError ? err.message : "Lost track of the run.");
        }
      }, 2000);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the FastAPI backend. Is it running?");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleStop() {
    if (!status) return;
    setStopping(true);
    try {
      const s = await stopIngest(status.run_id);
      setStatus(s);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the backend.");
    } finally {
      setStopping(false);
    }
  }

  const selected = tables?.find((t) => t.name === selectedTable) ?? null;
  const instagramStatus = status?.sources.instagram;
  const isRunning = instagramStatus?.status === "running";

  return (
    <div className="flex flex-col gap-5 rounded-md border border-border-primary bg-white p-5">
      <div className="flex items-center gap-2">
        <SourceLogo source="instagram" className="h-5 w-5 shrink-0" />
        <h3 className="text-sm font-medium text-text-primary">Instagram</h3>
      </div>

      <div className="flex gap-2">
        <button
          onClick={() => setMode("existing")}
          className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
            mode === "existing" ? "bg-accent-yellow text-white" : "bg-bg-muted text-text-secondary hover:bg-bg-muted"
          }`}
        >
          Select existing table
        </button>
        <button
          onClick={() => setMode("new")}
          className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
            mode === "new" ? "bg-accent-yellow text-white" : "bg-bg-muted text-text-secondary hover:bg-bg-muted"
          }`}
        >
          Create new table
        </button>
      </div>

      {mode === "existing" ? (
        <div>
          <label className="mb-1 block text-xs font-medium text-text-secondary">Table</label>
          <select
            value={selectedTable}
            onChange={(e) => setSelectedTable(e.target.value)}
            className="w-full max-w-sm rounded-md border border-border-primary bg-white px-3 py-2 text-sm text-text-primary focus:border-accent-yellow focus:outline-none"
          >
            {tables?.map((t) => (
              <option key={t.name} value={t.name}>
                {t.name} ({t.row_count.toLocaleString()} rows)
              </option>
            ))}
          </select>
          {selected && (
            <p className="mt-1 text-xs text-text-secondary">
              Last updated: {formatDateTime(selected.last_updated)} — leave the date below blank to
              resume from here automatically, per account.
            </p>
          )}

          <label className="mt-3 mb-1 block text-xs font-medium text-text-secondary">
            Start date (optional — overrides auto-resume)
          </label>
          <input
            type="date"
            value={sinceDate}
            onChange={(e) => setSinceDate(e.target.value)}
            className="w-full max-w-[200px] rounded-md border border-border-primary bg-white px-3 py-2 text-sm text-text-primary focus:border-accent-yellow focus:outline-none"
          />

          <div className="mt-3 flex gap-2">
            <button
              onClick={() => selected && handleStartFetch(selected.name)}
              disabled={!selected || submitting || isRunning}
              className="rounded-md bg-accent-yellow px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-yellow-hover disabled:opacity-40"
            >
              {submitting ? "Starting…" : "Update table"}
            </button>
            {isRunning && (
              <button
                onClick={handleStop}
                disabled={stopping}
                className="rounded-md bg-error-bg px-4 py-2 text-sm font-medium text-error-text transition-colors hover:bg-error-mid/10 disabled:opacity-40"
              >
                {stopping ? "Stopping…" : "Stop"}
              </button>
            )}
          </div>
        </div>
      ) : (
        <div>
          <label className="mb-1 block text-xs font-medium text-text-secondary">New table name</label>
          <div className="flex gap-2">
            <input
              value={newTableName}
              onChange={(e) => {
                setNewTableName(e.target.value);
                setCreatedTable(null);
              }}
              placeholder="dump_instagram_2"
              className="w-full max-w-sm rounded-md border border-border-primary bg-white px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-tertiary focus:border-accent-yellow focus:outline-none"
            />
            <button
              onClick={handleCreateTable}
              disabled={creating || !newTableName.trim() || Boolean(createdTable)}
              className="shrink-0 rounded-md bg-bg-muted px-4 py-2 text-sm font-medium text-text-primary transition-colors hover:bg-bg-muted disabled:opacity-40"
            >
              {creating ? "Creating…" : createdTable ? "Created" : "Create table"}
            </button>
          </div>
          {createError && <p className="mt-2 text-xs text-error-text">{createError}</p>}

          {createdTable && (
            <>
              <label className="mt-3 mb-1 block text-xs font-medium text-text-secondary">
                Start date (optional — default: the account's true oldest post)
              </label>
              <input
                type="date"
                value={sinceDate}
                onChange={(e) => setSinceDate(e.target.value)}
                className="w-full max-w-[200px] rounded-md border border-border-primary bg-white px-3 py-2 text-sm text-text-primary focus:border-accent-yellow focus:outline-none"
              />

              <div className="mt-3 flex gap-2">
                <button
                  onClick={() => handleStartFetch(createdTable)}
                  disabled={submitting || isRunning}
                  className="rounded-md bg-accent-yellow px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-yellow-hover disabled:opacity-40"
                >
                  {submitting ? "Starting…" : "Start fetching"}
                </button>
                {isRunning && (
                  <button
                    onClick={handleStop}
                    disabled={stopping}
                    className="rounded-md bg-error-bg px-4 py-2 text-sm font-medium text-error-text transition-colors hover:bg-error-mid/10 disabled:opacity-40"
                  >
                    {stopping ? "Stopping…" : "Stop"}
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      )}

      {error && (
        <div className="rounded-md border border-error-mid bg-error-bg p-3 text-sm text-error-text">{error}</div>
      )}

      {instagramStatus && (
        <div className="rounded-md border border-border-primary px-3 py-2">
          <div className="flex items-center justify-between text-sm">
            <span className="text-text-primary">
              Run <span className="font-mono text-xs text-text-secondary">{status?.run_id}</span>
            </span>
            <div className="flex items-center gap-3 text-xs">
              {instagramStatus.rows_ingested !== null && (
                <span className="text-text-secondary">{instagramStatus.rows_ingested} items fetched</span>
              )}
              {instagramStatus.error && <span className="text-error-text">{instagramStatus.error}</span>}
              <span
                className={`rounded-full px-2 py-0.5 font-medium ${
                  instagramStatus.status === "succeeded"
                    ? "bg-success-bg text-success-text"
                    : instagramStatus.status === "failed"
                      ? "bg-error-bg text-error-text"
                      : instagramStatus.status === "stopped"
                        ? "bg-bg-muted text-text-secondary"
                        : "bg-warning-bg text-warning-text"
                }`}
              >
                {instagramStatus.status}
              </span>
            </div>
          </div>
          <div className="mt-2">
            <ProgressBar status={instagramStatus.status} />
          </div>
          <LevelBadges levels={instagramStatus.levels} />
        </div>
      )}
    </div>
  );
}
