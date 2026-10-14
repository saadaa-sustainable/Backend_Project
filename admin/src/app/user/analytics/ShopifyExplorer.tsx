"use client";

import { fetchShopifyExplorerSchema, queryShopifyExplorer } from "@/lib/api";
import { MetricDimensionExplorer } from "./MetricDimensionExplorer";

export function ShopifyExplorer() {
  return (
    <MetricDimensionExplorer
      title="Shopify Explorer"
      intro="Pick a Shopify dataset, then whichever dimensions and metrics you want — the table below regenerates from that exact selection. Every field here is read directly off the Shopify Silver tables, no pre-built rollup."
      fetchSchema={fetchShopifyExplorerSchema}
      runQuery={queryShopifyExplorer}
    />
  );
}
