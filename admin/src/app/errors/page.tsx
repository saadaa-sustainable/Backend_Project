import { ErrorLogs } from "./ErrorLogs";

export default function ErrorsPage() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Error Logs</h1>
        <p className="mt-1 max-w-2xl text-sm text-slate-600">
          Recent ingestion failures across every source. Meta errors are DB-backed and
          retryable; Shopify and Instagram run as standalone scripts today and log to flat
          files instead.
        </p>
      </div>
      <ErrorLogs />
    </div>
  );
}
