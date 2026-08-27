import { AnalyticsTabs } from "./AnalyticsTabs";

export default function UserAnalyticsPage() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Analytics</h1>
        <p className="mt-1 max-w-2xl text-sm text-text-secondary">
          Creative Testing, Ads Analyse, Last Click UTM, and Landing Page Analysis — ported from the legacy
          dashboard&apos;s sections.
        </p>
      </div>
      <AnalyticsTabs />
    </div>
  );
}
