"use client";

import { fetchMetaExplorerSchema, queryMetaExplorer } from "@/lib/api";
import { MetricDimensionExplorer } from "./MetricDimensionExplorer";

export function MetaExplorer() {
  return (
    <MetricDimensionExplorer
      intro={
        "Pick a Meta dataset (ad / adset / campaign), then any of its ~95 non-JSON dimensions and metrics — " +
        "the full Insights registry, not a curated subset. Attribution-setting fields (attribution_setting, " +
        "anchor_event_attribution_setting) are available as dimensions; demographic (age/gender) and " +
        "placement/device breakdowns are not yet fetched from Meta, so they aren't listed here."
      }
      fetchSchema={fetchMetaExplorerSchema}
      runQuery={queryMetaExplorer}
    />
  );
}
