import Link from "next/link";

const SECTIONS = [
  {
    href: "/schema",
    title: "Schema Browser",
    description:
      "Every table the pipeline knows about — Bronze, Silver, and legacy — with its columns, types, and row counts. Pick which metrics matter to you.",
    status: "live",
  },
  {
    href: "/build",
    title: "Build Table",
    description:
      "Turn a schema-browser selection into a real table — pure field projection, optionally scoped to one object_type. No aggregation here.",
    status: "live",
  },
  {
    href: "/customize",
    title: "Customise Columns",
    description:
      "Add a formula-based custom metric (ratio, product, sum, difference) to an existing table — modeled on Meta Ads Manager's own custom-metric builder.",
    status: "live",
  },
  {
    href: "/assistant",
    title: "AI Assistant",
    description:
      "Ask about the data in plain language — it explores the schema and runs read-only queries for you. No write access at all.",
    status: "live",
  },
  {
    href: "/fetch",
    title: "Fetch Trigger",
    description:
      "Choose a source (Meta / Shopify / Instagram) and a date range, then run ingestion on demand instead of editing script arguments by hand.",
    status: "live",
  },
  {
    href: "/errors",
    title: "Error Logs",
    description: "Recent ingestion failures across every source, in one place.",
    status: "live",
  },
  {
    href: "/cron",
    title: "Cron / Sync Status",
    description: "Whether the scheduler is running, what's queued next, and recent batch health.",
    status: "live",
  },
];

export default function Home() {
  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">
          Bronze / Silver Admin
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-text-secondary">
          Internal panel for the medallion ingestion pipeline. Reads and triggers go through the
          FastAPI service — nothing here talks to Supabase directly.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {SECTIONS.map((section) => (
          <Link
            key={section.title}
            href={section.href}
            aria-disabled={section.status === "planned"}
            className={`rounded-lg border border-border-primary bg-white p-5 shadow-sm transition-colors ${
              section.status === "planned"
                ? "pointer-events-none opacity-50"
                : "hover:border-accent-yellow hover:shadow-md"
            }`}
          >
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-medium text-text-primary">{section.title}</h2>
              <span
                className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                  section.status === "live"
                    ? "bg-success-bg text-success-text"
                    : "bg-bg-muted text-text-secondary"
                }`}
              >
                {section.status === "live" ? "live" : "planned"}
              </span>
            </div>
            <p className="mt-2 text-sm leading-relaxed text-text-secondary">
              {section.description}
            </p>
          </Link>
        ))}
      </div>
    </div>
  );
}
