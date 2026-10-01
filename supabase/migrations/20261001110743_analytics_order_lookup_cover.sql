-- Date-bounded per-ad order totals and customer-mix lookups. INCLUDE keeps
-- these reads on the index instead of visiting the wide attribution rows.
-- On a live database, prebuild this index CONCURRENTLY before applying the
-- migration so the recorded migration is an idempotent no-op for writers.
CREATE INDEX IF NOT EXISTS ix_soa_ad_created_cover
    ON public.shopify_order_attribution (matched_ad_id, created_at)
    INCLUDE (total_price, order_id)
    WHERE matched_ad_id IS NOT NULL;
