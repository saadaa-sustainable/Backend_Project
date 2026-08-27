"use client";

import { useEffect, useState } from "react";
import { Dashboard } from "./Dashboard";
import { AnalyticsDashboard } from "./AnalyticsDashboard";
import { AdsAnalyse } from "./AdsAnalyse";
import { LastClickUtm } from "./LastClickUtm";
import { CustomerJourney } from "./CustomerJourney";
import { LandingPageAnalysis } from "./LandingPageAnalysis";
import { ShopifyExplorer } from "./ShopifyExplorer";
import { MetaExplorer } from "./MetaExplorer";
import { Cpis } from "./Cpis";

type Tab =
  | "dashboard"
  | "creative-testing"
  | "ads-analyse"
  | "last-click-utm"
  | "customer-journey"
  | "landing-page"
  | "cpis"
  | "shopify-explorer"
  | "meta-explorer";

const TAB_META: Record<Tab, { label: string; render: () => React.ReactNode }> = {
  dashboard: { label: "Dashboard", render: () => <Dashboard /> },
  "creative-testing": { label: "Creative Testing", render: () => <AnalyticsDashboard /> },
  "ads-analyse": { label: "Ads Analyse", render: () => <AdsAnalyse /> },
  "last-click-utm": { label: "Last Click UTM", render: () => <LastClickUtm /> },
  "customer-journey": { label: "Customer Journey", render: () => <CustomerJourney /> },
  "landing-page": { label: "Landing Page Analysis", render: () => <LandingPageAnalysis /> },
  cpis: { label: "CPIS", render: () => <Cpis /> },
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
  "shopify-explorer",
  "meta-explorer",
];

const STORAGE_KEY = "analytics-tab-order";

function loadTabOrder(): Tab[] {
  if (typeof window === "undefined") return DEFAULT_TAB_ORDER;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_TAB_ORDER;
    const parsed = JSON.parse(raw) as Tab[];
    if (Array.isArray(parsed) && DEFAULT_TAB_ORDER.every((t) => parsed.includes(t)) && parsed.length === DEFAULT_TAB_ORDER.length) {
      return parsed;
    }
    return DEFAULT_TAB_ORDER;
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
  }, []);

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
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-1 border-b border-border-primary">
        {tabOrder.map((t) => (
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
            className={`cursor-grab rounded-t-md border-b-2 px-4 py-2 text-sm font-medium transition-colors active:cursor-grabbing ${
              tab === t
                ? "border-accent-yellow text-accent-yellow"
                : dragOverTab === t
                  ? "border-border-mid text-text-primary"
                  : "border-transparent text-text-secondary hover:text-text-primary"
            } ${draggingTab === t ? "opacity-40" : ""}`}
          >
            {TAB_META[t].label}
          </button>
        ))}
      </div>

      {TAB_META[tab].render()}
    </div>
  );
}
