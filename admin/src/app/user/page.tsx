import Link from "next/link";

const SECTIONS = [
  {
    href: "/user/fetch",
    title: "Fetch Status",
    description: "Recent ingestion runs across Meta, Instagram, and Shopify — endpoint, records fetched, and outcome.",
  },
  {
    href: "/user/schema",
    title: "Schema Browser",
    description: "Every table in the pipeline, its columns, and — where one exists — the formula behind a computed column.",
  },
  {
    href: "/user/computational",
    title: "Computational Layer",
    description: "Bronze → Silver flatten jobs: whether each one is up to date, and what it last produced.",
  },
  {
    href: "/user/assistant",
    title: "AI Assistant",
    description: "Ask questions about the data in plain language — read-only, backed by the live database.",
  },
  {
    href: "/user/analytics",
    title: "Analytics",
    description: "Ad performance dashboard — Winner/Loser categories, ROAS, cost per conversion, and AI-generated insights.",
  },
];

export default function UserOverviewPage() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Ads Dashboard</h1>
        <p className="mt-1 max-w-2xl text-sm text-text-secondary">
          A read-only view of the pipeline — fetch status, schema, computed layers, and ad performance analytics.
          Nothing here can trigger a fetch or rebuild anything.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {SECTIONS.map((section) => (
          <Link
            key={section.href}
            href={section.href}
            className="rounded-lg border border-border-primary bg-white p-5 transition-colors hover:border-accent-yellow hover:bg-accent-yellow-bg/30"
          >
            <h2 className="text-sm font-medium text-text-primary">{section.title}</h2>
            <p className="mt-1.5 text-xs text-text-secondary">{section.description}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
