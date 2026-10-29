/**
 * The five groups the analytics sections hang under.
 *
 * Thirteen tabs did not fit on one line. Measured 2026-10-14 at 1700px,
 * the strip wrapped onto a second row and "Meta Explorer" fell to it --
 * so which row a section sat on depended on the window width, and the
 * two-row block pushed every section's first figure further down.
 *
 * Five group names fit at any width this product is used at. The second
 * row only ever carries the two to four siblings of where you already
 * are, so it is a list of alternatives rather than a catalogue.
 *
 * Grouped by the QUESTION each section answers, not by data source --
 * the surface brief names three audiences, and a creative never needs
 * adset mechanics while a buyer never needs the asset backlog.
 */
export type Tab =
  | "dashboard"
  | "comparative"
  | "blended-mer"
  | "creative-testing"
  | "asset-analysis"
  | "ads-analyse"
  | "last-click-utm"
  | "first-click"
  | "customer-journey"
  | "landing-page"
  | "cpis"
  | "meta-hypothesis"
  | "untested-assets"
  | "campaign-tracker"
  | "instagram"
  | "shopify-analytics"
  | "shopify-explorer"
  | "meta-explorer"
  | "help";

export type GroupKey = "overview" | "creative" | "attribution" | "product" | "explore";

export interface Group {
  key: GroupKey;
  label: string;
  tabs: Tab[];
}

export const GROUPS: Group[] = [
  { key: "overview", label: "Overview", tabs: ["dashboard", "comparative", "blended-mer"] },
  { key: "creative", label: "Creative", tabs: ["creative-testing", "asset-analysis", "untested-assets", "campaign-tracker", "instagram"] },
  { key: "attribution", label: "Attribution", tabs: ["last-click-utm", "first-click", "customer-journey", "landing-page"] },
  { key: "product", label: "Product", tabs: ["ads-analyse", "cpis", "meta-hypothesis"] },
  { key: "explore", label: "Explore", tabs: ["shopify-analytics", "shopify-explorer", "meta-explorer"] },
];

/** Help sits outside the groups -- it is not a question about the data. */
export const HELP_TAB: Tab = "help";

export const ALL_TABS: Tab[] = [...GROUPS.flatMap((g) => g.tabs), HELP_TAB];

export function groupOf(tab: Tab): GroupKey | null {
  return GROUPS.find((g) => g.tabs.includes(tab))?.key ?? null;
}
