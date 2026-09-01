import { AnalyticsTabs } from "./AnalyticsTabs";

export default function UserAnalyticsPage() {
  // Kwikengage-style: no page-level h1 or description. The tab bar
  // + each section's own header already tell the user where they
  // are; a wall of introductory text just pushes the useful controls
  // below the fold on smaller screens. 2026-08-29 declutter pass.
  return <AnalyticsTabs />;
}
