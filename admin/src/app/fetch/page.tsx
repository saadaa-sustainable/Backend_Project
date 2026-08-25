import { FetchTriggerForm } from "./FetchTriggerForm";
import { InstagramFetchPanel } from "./InstagramFetchPanel";
import { MetaFetchPanel } from "./MetaFetchPanel";

export default function FetchPage() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Fetch Trigger</h1>
        <p className="mt-1 max-w-2xl text-sm text-slate-600">
          Meta and Instagram both work from a table: create a new one to backfill from scratch,
          or pick an existing one to resume from where it last left off automatically — a date
          range still applies for Meta, but only to bound how far to fetch, not which table.
          Shopify isn&apos;t wired up as a live trigger yet.
        </p>
      </div>
      <MetaFetchPanel />
      <InstagramFetchPanel />
      <FetchTriggerForm />
    </div>
  );
}
