import { UserSchemaBrowser } from "./UserSchemaBrowser";

export default function UserSchemaPage() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Schema Browser</h1>
        <p className="mt-1 max-w-2xl text-sm text-text-secondary">
          Every table in the pipeline, its columns, and — where one exists — the formula behind a computed column.
        </p>
      </div>
      <UserSchemaBrowser />
    </div>
  );
}
