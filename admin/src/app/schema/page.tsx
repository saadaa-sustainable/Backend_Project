import { SchemaBrowser } from "./SchemaBrowser";

export default function SchemaPage() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Schema Browser</h1>
        <p className="mt-1 max-w-2xl text-sm text-text-secondary">
          Every table currently in the target Supabase project, introspected live via{" "}
          <code className="rounded bg-bg-muted px-1 py-0.5 text-xs">GET /admin/tables</code>.
          Select the metrics you care about — the selection is exportable at the bottom.
        </p>
      </div>
      <SchemaBrowser />
    </div>
  );
}
