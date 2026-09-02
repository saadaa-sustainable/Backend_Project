"use client";

import Link from "next/link";
import { useState } from "react";
import { ApiError, triggerSilverRefresh, type RefreshSilverResponse } from "@/lib/api";

/**
 * One-click cascade of the CPIS silver-layer refreshes. Fires the
 * /admin/refresh/silver-all endpoint which shells out to the three
 * scripts serially:
 *
 *   1. refresh_insights_daily_by_ad.py   (~1 min)
 *   2. refresh_cpis_utm.py               (~1 min)
 *   3. refresh_cpis_by_sku_daily.py      (~30 sec)
 *
 * The endpoint returns a run_id immediately; the actual work runs in
 * an asyncio task on the server and every stdout line is piped into
 * the same live-log ring buffer /logs already tails. Merchant clicks
 * once, then flips to /logs to watch progress.
 */
export function SilverRefreshPanel() {
  const [state, setState] = useState<"idle" | "starting" | "started" | "error">("idle");
  const [run, setRun] = useState<RefreshSilverResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onClick() {
    setState("starting");
    setError(null);
    try {
      const res = await triggerSilverRefresh();
      setRun(res);
      setState("started");
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : String(e));
      setState("error");
    }
  }

  return (
    <div className="rounded-lg border border-border-primary bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-text-primary">Refresh silver tables (CPIS)</h2>
          <p className="mt-1 max-w-xl text-xs text-text-secondary">
            After a fresh Meta fetch above, run this to rebuild the derived tables the CPIS
            dashboard reads from — <code className="font-mono">insights_daily_by_ad</code>,{" "}
            <code className="font-mono">cpis_by_sku_utm</code>,{" "}
            <code className="font-mono">cpis_by_sku_daily</code>. Runs in the background; total
            wall time ~2–3 minutes.
          </p>
        </div>
        <button
          onClick={onClick}
          disabled={state === "starting"}
          className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
            state === "starting"
              ? "cursor-not-allowed bg-bg-muted text-text-tertiary"
              : "bg-slate-900 text-white hover:bg-slate-700"
          }`}
        >
          {state === "starting" ? "Starting…" : "Refresh silver tables"}
        </button>
      </div>

      {state === "started" && run && (
        <div className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">
          <p>
            <strong>Started.</strong> Run id{" "}
            <code className="font-mono text-xs">{run.run_id}</code>. Running{" "}
            {run.scripts.length} scripts in sequence.
          </p>
          <p className="mt-1 text-xs">
            <Link href={`/logs?run_id=${run.run_id}`} className="underline">
              → Tail live logs at /logs?run_id={run.run_id}
            </Link>
          </p>
        </div>
      )}

      {state === "error" && error && (
        <div className="mt-3 rounded-md border border-error-mid bg-error-bg p-3 text-sm text-error-text">
          Failed to start: {error}
        </div>
      )}
    </div>
  );
}
