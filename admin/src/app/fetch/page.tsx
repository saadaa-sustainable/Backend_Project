import { InstagramFetchPanel } from "./InstagramFetchPanel";
import { MetaFetchPanel } from "./MetaFetchPanel";
import { ShopifyFetchPanel } from "./ShopifyFetchPanel";
import { SilverRefreshPanel } from "./SilverRefreshPanel";

export default function FetchPage() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Fetch Trigger</h1>
        <p className="mt-1 max-w-2xl text-sm text-text-secondary">
          Meta, Instagram, and Shopify all work from a table: create a new one to backfill from
          scratch, or pick an existing one to resume from where it last left off automatically —
          a date range still applies for Meta and Shopify, but only to bound how far to fetch,
          not which table.
        </p>
      </div>
      <MetaFetchPanel />
      <InstagramFetchPanel />
      <ShopifyFetchPanel />
      <SilverRefreshPanel />
    </div>
  );
}
