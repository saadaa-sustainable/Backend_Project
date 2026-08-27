import { ComputationalStatus } from "./ComputationalStatus";

export default function UserComputationalPage() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Computational Layer</h1>
        <p className="mt-1 max-w-2xl text-sm text-text-secondary">
          Status of every Bronze → Silver flatten job — whether it&apos;s up to date with the latest raw data, and
          what it last produced.
        </p>
      </div>
      <ComputationalStatus />
    </div>
  );
}
