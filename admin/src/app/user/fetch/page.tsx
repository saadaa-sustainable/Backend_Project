import { FetchStatus } from "./FetchStatus";

export default function UserFetchStatusPage() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Fetch Status</h1>
        <p className="mt-1 max-w-2xl text-sm text-text-secondary">
          Recent data ingestion runs across every source and account. Refreshes automatically every 30 seconds.
        </p>
      </div>
      <FetchStatus />
    </div>
  );
}
