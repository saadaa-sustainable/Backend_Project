-- Prebuild CONCURRENTLY in autocommit mode on a live installation, then
-- apply this migration to record it without blocking ingestion writes.
-- The poller and Schema Browser ask for MAX(extracted_at); without this
-- index each check reads the entire multi-GB bronze heap.
CREATE INDEX IF NOT EXISTS ix_raw_dump_meta_extracted_at
    ON public.raw_dump_meta (extracted_at);

-- DESC NULLS LAST cannot use a backwards scan of the existing ASC index
-- (which yields DESC NULLS FIRST). Last Click must read the newest page
-- directly instead of sorting every order before returning 100 rows.
CREATE INDEX IF NOT EXISTS ix_soa_created_desc_nulls_last
    ON public.shopify_order_attribution (created_at DESC NULLS LAST);
