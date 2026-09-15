"use client";

import { useMemo, useSyncExternalStore } from "react";
import dynamic from "next/dynamic";

function TabLoading() {
  return <div role="status" className="min-h-40 py-8 text-sm text-text-secondary">Loading analytics…</div>;
}

// Only the selected section downloads its components and starts its requests.
const Dashboard = dynamic(() => import("./Dashboard").then((m) => m.Dashboard), { loading: TabLoading });
const AdsAnalyse = dynamic(() => import("./AdsAnalyse").then((m) => m.AdsAnalyse), { loading: TabLoading });
const CreativeTesting = dynamic(() => import("./CreativeTesting").then((m) => m.CreativeTesting), { loading: TabLoading });
const LastClickUtm = dynamic(() => import("./LastClickUtm").then((m) => m.LastClickUtm), { loading: TabLoading });
const CustomerJourney = dynamic(() => import("./CustomerJourney").then((m) => m.CustomerJourney), { loading: TabLoading });
const LandingPageAnalysis = dynamic(() => import("./LandingPageAnalysis").then((m) => m.LandingPageAnalysis), { loading: TabLoading });
const ShopifyExplorer = dynamic(() => import("./ShopifyExplorer").then((m) => m.ShopifyExplorer), { loading: TabLoading });
const MetaExplorer = dynamic(() => import("./MetaExplorer").then((m) => m.MetaExplorer), { loading: TabLoading });
const Cpis = dynamic(() => import("./Cpis").then((m) => m.Cpis), { loading: TabLoading });
const Instagram = dynamic(() => import("./Instagram").then((m) => m.Instagram), { loading: TabLoading });
const UntestedAssets = dynamic(() => import("./UntestedAssets").then((m) => m.UntestedAssets), { loading: TabLoading });

type Tab =
  | "dashboard"
  | "creative-testing"
  | "ads-analyse"
  | "last-click-utm"
  | "customer-journey"
  | "landing-page"
  | "cpis"
  | "untested-assets"
  | "instagram"
  | "shopify-explorer"
  | "meta-explorer";

// Two distinct sections, deliberately split (2026-08-29):
//   * Creative Testing (CreativeTesting.tsx) -- focused view for
//     recently-launched creatives. Always scoped by ad_created_date
//     in a picked window (default: Last 30 Days). Slim table.
//   * Ads Analyse (AdsAnalyse.tsx) -- full CTD-fidelity view over the
//     lifetime table, 68 columns, all filters, all metrics. Windowed
//     overlay is opt-in via the Date field dropdown.
const TAB_META: Record<Tab, { label: string; render: () => React.ReactNode }> = {
  dashboard: { label: "Dashboard", render: () => <Dashboard /> },
  "creative-testing": { label: "Creative Testing", render: () => <CreativeTesting /> },
  "ads-analyse": { label: "Ads Analyse", render: () => <AdsAnalyse /> },
  "last-click-utm": { label: "Last Click UTM", render: () => <LastClickUtm /> },
  "customer-journey": { label: "Customer Journey", render: () => <CustomerJourney /> },
  "landing-page": { label: "Landing Page Analysis", render: () => <LandingPageAnalysis /> },
  cpis: { label: "CPIS", render: () => <Cpis /> },
  "untested-assets": { label: "Untested Assets", render: () => <UntestedAssets /> },
  instagram: { label: "Instagram", render: () => <Instagram /> },
  "shopify-explorer": { label: "Shopify Explorer", render: () => <ShopifyExplorer /> },
  "meta-explorer": { label: "Meta Explorer", render: () => <MetaExplorer /> },
};

const DEFAULT_TAB_ORDER: Tab[] = [
  "dashboard",
  "creative-testing",
  "ads-analyse",
  "last-click-utm",
  "customer-journey",
  "landing-page",
  "cpis",
  "untested-assets",
  "instagram",
  "shopify-explorer",
  "meta-explorer",
];

const STORAGE_KEY = "analytics-tab-order";

function loadTabOrder(): Tab[] {
  if (typeof window === "undefined") return DEFAULT_TAB_ORDER;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_TAB_ORDER;
    const parsed = JSON.parse(raw) as string[];
    if (!Array.isArray(parsed)) return DEFAULT_TAB_ORDER;
    // Filter out any tabs that no longer exist in the schema (e.g. the
    // dropped "ads-analyse" tab -- merged into "creative-testing" on
    // 2026-08-29) and append any tabs that were added since the saved
    // order was written. Robust against schema evolution.
    const known = new Set(DEFAULT_TAB_ORDER as readonly string[]);
    const cleaned = parsed.filter((t): t is Tab => known.has(t));
    const missing = DEFAULT_TAB_ORDER.filter((t) => !cleaned.includes(t));
    return [...cleaned, ...missing];
  } catch {
    return DEFAULT_TAB_ORDER;
  }
}

function subscribeToHash(onChange: () => void) {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

function getCurrentTab(): Tab {
  const hash = window.location.hash.replace(/^#/, "");
  return (DEFAULT_TAB_ORDER as readonly string[]).includes(hash) ? hash as Tab : "dashboard";
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
  const ready = tab !== null;
  const tabOrder = useMemo(() => ready ? loadTabOrder() : DEFAULT_TAB_ORDER, [ready]);


  return (
    <div className="flex flex-col gap-5">
      {/* Kwikengage-style horizontal tab strip. Page title on the left,
          tabs flush right, active tab underlined. URL-hash sync + browser
          back/forward supported. Drag-to-reorder was removed on
          2026-09-01 since the dropdown attempt turned out to be for the
          CPIS-internal analytics view, not this level-1 nav. */}
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-border-primary">
        <div className="flex flex-wrap items-end gap-1">
          <h1 className="mr-4 pb-3 text-[20px] font-semibold tracking-tight text-text-primary">
            Analytics
          </h1>
          <nav className="flex flex-wrap items-end gap-1 pb-0" aria-label="Analytics sections">
            {tabOrder.map((t) => {
              const active = tab === t;
              return (
                <button
                  key={t}
                  onClick={() => selectTab(t)}
                  className={`relative px-3 pb-3 pt-1 text-[13px] font-medium transition-colors ${
                    active
                      ? "text-text-primary"
                      : "text-text-secondary hover:text-text-primary"
                  }`}
                >
                  {TAB_META[t].label}
                  {active && (
                    <span className="absolute inset-x-2 -bottom-px h-[2px] rounded-full bg-accent-yellow" />
                  )}
                </button>
              );
            })}
          </nav>
        </div>
      </div>

      {tab === null ? <TabLoading /> : TAB_META[tab].render()}
    </div>
  );
}
