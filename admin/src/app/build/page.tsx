import { TableBuilder } from "./TableBuilder";

export default function BuildPage() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Build Custom Table</h1>
        <p className="mt-1 max-w-2xl text-sm text-slate-600">
          Starts from whatever you checked on the Schema Browser. Pick an entity + time bucket to
          group by, decide which fields are custom metrics (with an aggregation) vs. descriptive,
          preview the generated SQL, then create it as a real Gold table.
        </p>
      </div>
      <TableBuilder />
    </div>
  );
}
