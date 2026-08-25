import { CronStatus } from "./CronStatus";

export default function CronPage() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Cron / Sync Status</h1>
        <p className="mt-1 max-w-2xl text-sm text-slate-600">
          Whether the background scheduler is running, what it has queued next, and the recent
          health of every sync batch it (or a manual trigger) has run.
        </p>
      </div>
      <CronStatus />
    </div>
  );
}
