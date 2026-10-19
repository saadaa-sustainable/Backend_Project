"use client";

import { memo, useMemo, useState, useSyncExternalStore } from "react";
import dynamic from "next/dynamic";
import { AnalyticsSectionVisibility } from "@/lib/analyticsSectionVisibility";
import { GROUPS, HELP_TAB, ALL_TABS, groupOf, type Tab, type GroupKey } from "./sectionGroups";

function TabLoading() {
  return <div role="status" className="min-h-40 py-8 text-sm text-text-secondary">Loading analytics…</div>;
}

// Only the selected section downloads its components and starts its requests.
const Dashboard = dynamic(() => import("./Dashboard").then((m) => m.Dashboard), { loading: TabLoading });
const AdsAnalyse = dynamic(() => import("./AdsAnalyse").then((m) => m.AdsAnalyse), { loading: TabLoading });
const CreativeTesting = dynamic(() => import("./CreativeTesting").then((m) => m.CreativeTesting), { loading: TabLoading });
const LastClickUtm = dynamic(() => import("./LastClickUtm").then((m) => m.LastClickUtm), { loading: TabLoading });
const FirstClick = dynamic(() => import("./FirstClick").then((m) => m.FirstClick), { loading: TabLoading });
const CustomerJourney = dynamic(() => import("./CustomerJourney").then((m) => m.CustomerJourney), { loading: TabLoading });
const LandingPageAnalysis = dynamic(() => import("./LandingPageAnalysis").then((m) => m.LandingPageAnalysis), { loading: TabLoading });
const ShopifyExplorer = dynamic(() => import("./ShopifyExplorer").then((m) => m.ShopifyExplorer), { loading: TabLoading });
const MetaExplorer = dynamic(() => import("./MetaExplorer").then((m) => m.MetaExplorer), { loading: TabLoading });
const Cpis = dynamic(() => import("./Cpis").then((m) => m.Cpis), { loading: TabLoading });
const ComparativeAnalysis = dynamic(
  () => import("./ComparativeAnalysis").then((m) => m.ComparativeAnalysis),
  { loading: TabLoading });
const BlendedMerSection = dynamic(
  () => import("./BlendedMerSection").then((m) => m.BlendedMerSection),
  { loading: TabLoading });
const Instagram = dynamic(() => import("./Instagram").then((m) => m.Instagram), { loading: TabLoading });
const UntestedAssets = dynamic(() => import("./UntestedAssets").then((m) => m.UntestedAssets), { loading: TabLoading });
const ShopifyAnalytics = dynamic(() => import("./ShopifyAnalytics").then((m) => m.ShopifyAnalytics), { loading: TabLoading });
const Help = dynamic(() => import("./Help").then((m) => m.Help), { loading: TabLoading });
const AssetAnalysis = dynamic(() => import("./AssetAnalysis").then((m) => m.AssetAnalysis), { loading: TabLoading });

// Tab and the five groups it hangs under now live in sectionGroups.ts,
// because the nav, the deep-link handler and the Help section all need
// the same list and it must not be restated in three places.

// Two distinct sections, deliberately split (2026-08-29):
//   * Creative Testing (CreativeTesting.tsx) -- focused view for
//     recently-launched creatives. Always scoped by ad_created_date
//     in a picked window (default: Last 30 Days). Slim table.
//   * Ads Analyse (AdsAnalyse.tsx) -- full CTD-fidelity view over the
//     lifetime table, 68 columns, all filters, all metrics. Windowed
//     overlay is opt-in via the Date field dropdown.
const TAB_META: Record<Tab, { label: string; render: () => React.ReactNode }> = {
  dashboard: { label: "Dashboard", render: () => <Dashboard /> },
  comparative: { label: "Comparative Analysis", render: () => <ComparativeAnalysis /> },
  "blended-mer": { label: "Blended MER", render: () => <BlendedMerSection /> },
  "creative-testing": { label: "Creative Testing", render: () => <CreativeTesting /> },
  "asset-analysis": { label: "Asset Analysis", render: () => <AssetAnalysis /> },
  "ads-analyse": { label: "Ads Analyse", render: () => <AdsAnalyse /> },
  "last-click-utm": { label: "Last Click UTM", render: () => <LastClickUtm /> },
  // Beside Last Click, deliberately: the pair is the comparison.
  "first-click": { label: "First Click", render: () => <FirstClick /> },
  "customer-journey": { label: "Customer Journey", render: () => <CustomerJourney /> },
  "landing-page": { label: "Landing Page Analysis", render: () => <LandingPageAnalysis /> },
  cpis: { label: "CPIS", render: () => <Cpis /> },
  "untested-assets": { label: "Untested Assets", render: () => <UntestedAssets /> },
  instagram: { label: "Instagram", render: () => <Instagram /> },
  "shopify-analytics": { label: "Shopify Analytics", render: () => <ShopifyAnalytics /> },
  "shopify-explorer": { label: "Shopify Explorer", render: () => <ShopifyExplorer /> },
  "meta-explorer": { label: "Meta Explorer", render: () => <MetaExplorer /> },
  help: { label: "Help", render: () => <Help /> },
};

// Switching sections must not rerender the retained tables and charts. Their
// own filter/data updates still render normally. Mount only after first use.
const SectionContent = memo(function SectionContent({ tab }: { tab: Tab }) {
  return TAB_META[tab].render();
});

// Grouping replaced the saved per-user tab order. That order existed for
// a drag-to-reorder affordance removed on 2026-09-01, and a flat order
// cannot express a two-level nav; ALL_TABS is now the single list.

function subscribeToHash(onChange: () => void) {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

function getCurrentTab(): Tab {
  const hash = window.location.hash.replace(/^#/, "");
  return (ALL_TABS as readonly string[]).includes(hash) ? hash as Tab : "dashboard";
}

function getServerTab(): null {
  return null;
}

function selectTab(tab: Tab) {
  // Keep browser navigation state and avoid adding a history entry per click.
  window.history.replaceState(window.history.state, "", `#${tab}`);
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}

export function AnalyticsTabs() {
  // A server cannot see URL fragments. Wait for the browser snapshot so a
  // deep link never mounts Dashboard or issues its five unrelated requests.
  const tab = useSyncExternalStore(subscribeToHash, getCurrentTab, getServerTab);
  const [visited, setVisited] = useState<Tab[]>([]);
  // The group whose siblings are listed. Follows the section you are in,
  // but is its own state so opening a group to look around does not
  // unload the section you are reading -- clicking "Attribution" while
  // on CPIS should not throw CPIS's table away before you have chosen.
  const [openGroup, setOpenGroup] = useState<GroupKey | null>(null);
  const activeGroup = groupOf(tab ?? "dashboard");
  const shownGroup = openGroup ?? activeGroup;
  const siblings = useMemo(
    () => GROUPS.find((g) => g.key === shownGroup)?.tabs ?? [],
    [shownGroup],
  );
  // Track newly selected tabs before committing their children, avoiding an
  // extra blank frame. This list is bounded by the known analytics sections.
  if (tab !== null && !visited.includes(tab)) {
    setVisited([...visited, tab]);
  }

  return (
    <div className="flex flex-col gap-5">
      {/* Kwikengage-style horizontal tab strip. Page title on the left,
          tabs flush right, active tab underlined. URL-hash sync + browser
          back/forward supported. Drag-to-reorder was removed on
          2026-09-01 since the dropdown attempt turned out to be for the
          CPIS-internal analytics view, not this level-1 nav. */}
      {/* Two levels, one rule. Thirteen section names did not fit on a
          line -- measured 2026-10-14 at 1700px the strip wrapped and the
          last tab fell to a second row, so which row a section sat on
          depended on the window width. Five group names always fit; the
          row beneath carries only the siblings of where you are.

          "Rules, never boxes" (surface brief): the group strip sits on a
          single full-width hairline, and the active group is marked by a
          rule under the word, not a pill around it. */}
      <div className="flex flex-col">
        <div className="flex flex-wrap items-end justify-between gap-3 border-b border-border-primary">
          <div className="flex flex-wrap items-end gap-1">
            <h1 className="mr-4 pb-3 text-[20px] font-semibold tracking-tight text-text-primary">
              Analytics
            </h1>
            <nav className="flex flex-wrap items-end gap-1 pb-0" aria-label="Analytics groups">
              {GROUPS.map((g) => {
                const isActive = activeGroup === g.key;
                const isShown = shownGroup === g.key;
                return (
                  <button
                    key={g.key}
                    type="button"
                    aria-current={isActive ? "true" : undefined}
                    onClick={() => {
                      // One section in the group: no sibling row is worth
                      // showing, so go straight there.
                      if (g.tabs.length === 1) {
                        setOpenGroup(null);
                        selectTab(g.tabs[0]);
                        return;
                      }
                      setOpenGroup(g.key);
                    }}
                    className={`relative px-3 pb-3 pt-1 text-[13px] font-medium transition-colors ${
                      isActive || isShown
                        ? "text-text-primary"
                        : "text-text-secondary hover:text-text-primary"
                    }`}
                  >
                    {g.label}
                    {isActive && (
                      <span className="absolute inset-x-2 -bottom-px h-[2px] rounded-full bg-accent-yellow" />
                    )}
                    {!isActive && isShown && (
                      <span className="absolute inset-x-2 -bottom-px h-[2px] rounded-full bg-border-mid" />
                    )}
                  </button>
                );
              })}
            </nav>
          </div>
          <div className="flex flex-wrap items-center gap-3 pb-2">
            {/* The approved design puts the siblings on the SAME rule as the
                groups, right-aligned, as pills with the current one filled.
                An earlier pass had them as underlined text on a second row,
                which read as a second navigation rather than as the choice
                within the one you are already in. */}
            {siblings.length > 1 && (
              <nav className="flex flex-wrap items-center gap-1.5" aria-label="Sections">
                {siblings.map((t) => {
                  const on = tab === t;
                  return (
                    <button
                      key={t}
                      type="button"
                      aria-current={on ? "page" : undefined}
                      onClick={() => { setOpenGroup(null); selectTab(t); }}
                      className={`rounded-md border px-3 py-1.5 text-[12.5px] transition-colors ${
                        on
                          ? "border-text-primary bg-text-primary font-medium text-bg-white"
                          : "border-border-primary bg-bg-white text-text-secondary hover:text-text-primary"
                      }`}
                    >
                      {TAB_META[t].label}
                    </button>
                  );
                })}
              </nav>
            )}
            <button
              type="button"
              aria-current={tab === HELP_TAB ? "true" : undefined}
              onClick={() => { setOpenGroup(null); selectTab(HELP_TAB); }}
              className={`relative px-2 pb-1 pt-1 text-[13px] font-medium transition-colors ${
                tab === HELP_TAB ? "text-text-primary" : "text-text-secondary hover:text-text-primary"
              }`}
            >
              Help
              {tab === HELP_TAB && (
                <span className="absolute inset-x-1 -bottom-[9px] h-[2px] rounded-full bg-accent-yellow" />
              )}
            </button>
          </div>
        </div>

        {/* Siblings of the open group. Hidden for a group of one and for
            Help, which has none. */}
      </div>

      {/* The data-floor banner moved to Help ("Why every figure starts
          01 Jan 2026"), and the fact itself moved to where it is acted
          on: the date control now prints the window it resolved to, so
          "Lifetime" states its own lower bound instead of a paragraph
          above the page doing it. It cost ~70px of every section's first
          screen to say something read once. */}

      {tab === null && <TabLoading />}
      {visited.map((section) => (
        <section
          key={section}
          data-analytics-section={section}
          aria-label={`${TAB_META[section].label} section`}
          hidden={section !== tab}
          inert={section !== tab}
        >
          <AnalyticsSectionVisibility.Provider value={section === tab}>
            <SectionContent tab={section} />
          </AnalyticsSectionVisibility.Provider>
        </section>
      ))}
    </div>
  );
}
