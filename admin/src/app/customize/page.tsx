import { CustomizeColumns } from "./CustomizeColumns";

export default function CustomizePage() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Customise Columns</h1>
        <p className="mt-1 max-w-2xl text-sm text-slate-600">
          Pick an existing table and add a formula-based custom metric to it — a ratio, product,
          sum, or difference of two of its columns (or a column and a constant). Modeled on Meta
          Ads Manager&apos;s own &quot;Create custom metric&quot; panel. The metric is added as a
          real column in that table, not a separate view.
        </p>
      </div>
      <CustomizeColumns />
    </div>
  );
}
