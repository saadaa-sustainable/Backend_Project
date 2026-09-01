"use client";

import { useEffect, useState } from "react";
import { Dashboard } from "./Dashboard";
import { AdsAnalyse } from "./AdsAnalyse";
import { CreativeTesting } from "./CreativeTesting";
import { LastClickUtm } from "./LastClickUtm";
import { CustomerJourney } from "./CustomerJourney";
import { LandingPageAnalysis } from "./LandingPageAnalysis";
import { ShopifyExplorer } from "./ShopifyExplorer";
import { MetaExplorer } from "./MetaExplorer";
import { Cpis } from "./Cpis";
import { Instagram } from "./Instagram";

type Tab =
  | "dashboard"
  | "creative-testing"
  | "ads-analyse"
  | "last-click-utm"
  | "customer-journey"
  | "landing-page"
  | "cpis"
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

export function AnalyticsTabs() {
  const [tabOrder, setTabOrder] = useState<Tab[]>(DEFAULT_TAB_ORDER);
  const [tab, setTab] = useState<Tab>("dashboard");
  const [draggingTab, setDraggingTab] = useState<Tab | null>(null);
  const [dragOverTab, setDragOverTab] = useState<Tab | null>(null);

  useEffect(() => {
    setTabOrder(loadTabOrder());
    // Deep-link support: /user/analytics#creative-testing selects that
    // tab on load. Also listen for browser back/forward (hashchange).
    if (typeof window === "undefined") return;
    const applyHash = () => {
      const hash = window.location.hash.replace(/^#/, "");
      if (hash && (DEFAULT_TAB_ORDER as readonly string[]).includes(hash)) {
        setTab(hash as Tab);
      }
    };
    applyHash();
    window.addEventListener("hashchange", applyHash);
    return () => window.removeEventListener("hashchange", applyHash);
  }, []);

  // Push the tab into the URL hash so a shared / bookmarked link lands
  // on the same view. Use replaceState -- we don't want every tab click
  // to add a browser-history entry (would break the back button).
  useEffect(() => {
    if (typeof window === "undefined") return;
    const current = window.location.hash.replace(/^#/, "");
    if (current !== tab) {
      window.history.replaceState(null, "", `#${tab}`);
    }
  }, [tab]);

  function persistOrder(next: Tab[]) {
    setTabOrder(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      // localStorage unavailable -- reordering still works this session, just doesn't persist.
    }
  }

  function handleDrop(targetTab: Tab) {
    if (!draggingTab || draggingTab === targetTab) {
      setDraggingTab(null);
      setDragOverTab(null);
      return;
    }
    const next = [...tabOrder];
    const fromIdx = next.indexOf(draggingTab);
    const toIdx = next.indexOf(targetTab);
    next.splice(fromIdx, 1);
    next.splice(toIdx, 0, draggingTab);
    persistOrder(next);
    setDraggingTab(null);
    setDragOverTab(null);
  }

  return (
    <div className="flex flex-col gap-5">
      {/* Level-1 tab bar: kwikengage.ai "Marketing Insights" pattern
          (2026-08-31 screenshot). Page title on left, tab strip flush
          right beside it, active tab = text with a 2px blue underline
          (no bg fill). This is the entity-scope switcher — each tab is
          a whole sub-app, not a filter. Level-2 filter pills (e.g.
          CPIS's "By UTM / By ad name", the date presets in Ads Analyse)
          live INSIDE each section so they scope only that section.
          Drag-to-reorder is preserved on the tab buttons. */}
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
                  draggable
                  onClick={() => setTab(t)}
                  onDragStart={() => setDraggingTab(t)}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDragOverTab(t);
                  }}
                  onDragLeave={() => setDragOverTab((prev) => (prev === t ? null : prev))}
                  onDrop={() => handleDrop(t)}
                  onDragEnd={() => {
                    setDraggingTab(null);
                    setDragOverTab(null);
                  }}
                  title="Drag to reorder"
                  className={`relative cursor-grab px-3 pb-3 pt-1 text-[13px] font-medium transition-colors active:cursor-grabbing ${
                    active
                      ? "text-text-primary"
                      : dragOverTab === t
                        ? "text-text-primary"
                        : "text-text-secondary hover:text-text-primary"
                  } ${draggingTab === t ? "opacity-40" : ""}`}
                >
                  {TAB_META[t].label}
                  {active && (
                    <span className="absolute inset-x-2 -bottom-px h-[2px] rounded-full bg-accent-yellow" />
                  )}
                  {!active && dragOverTab === t && (
                    <span className="absolute inset-x-2 -bottom-px h-[2px] rounded-full bg-accent-amber" />
                  )}
                </button>
              );
            })}
          </nav>
        </div>
      </div>

      {TAB_META[tab].render()}
    </div>
  );
}
