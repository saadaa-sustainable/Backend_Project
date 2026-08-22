-- Flattened, typed view of raw_dump_meta's object_type='ad' rows -- every
-- key discovered live 2026-08-20 by scanning all 37,494 real ad rows (not
-- sampled). Matches app/core/meta_registry.py's AD_FIELDS exactly.
--
-- Nested objects/arrays (creative, tracking_specs, issues_info,
-- recommendations) kept as JSONB -- `creative` in particular is its own
-- nested object (id/name/URL tags/link_url/object_story_spec/...), not
-- something worth flattening into columns on the ad row itself.
--
-- Run once in the Supabase SQL Editor, or via the direct DSN -- this
-- project's DDL convention throughout (see scripts/sql/insta_data.sql).

DROP TABLE IF EXISTS meta_ads;

CREATE TABLE meta_ads AS
SELECT
    -- envelope / context
    id,
    meta_id,
    batch_id,
    parent_ids ->> 'account_key' AS account_key,
    parent_ids ->> 'account_name' AS account_name,
    parent_ids ->> 'account_id' AS account_id,
    parent_ids ->> 'campaign_id' AS campaign_id,
    parent_ids ->> 'adset_id' AS adset_id,
    extracted_at,
    ingested_at,

    -- identity / status
    raw_payload ->> 'name' AS name,
    raw_payload ->> 'status' AS status,
    raw_payload ->> 'effective_status' AS effective_status,
    raw_payload ->> 'conversion_domain' AS conversion_domain,
    (raw_payload ->> 'bid_amount')::numeric AS bid_amount,

    -- dates
    NULLIF(raw_payload ->> 'created_time', '')::timestamptz AS created_time,
    NULLIF(raw_payload ->> 'updated_time', '')::timestamptz AS updated_time,

    -- nested / structured (kept as JSONB, not flattened further)
    raw_payload -> 'creative' AS creative,
    raw_payload -> 'tracking_specs' AS tracking_specs,
    raw_payload -> 'issues_info' AS issues_info,
    raw_payload -> 'recommendations' AS recommendations
FROM raw_dump_meta
WHERE object_type = 'ad';

CREATE INDEX IF NOT EXISTS ix_meta_ads_meta_id ON meta_ads (meta_id);
CREATE INDEX IF NOT EXISTS ix_meta_ads_account_key ON meta_ads (account_key);
CREATE INDEX IF NOT EXISTS ix_meta_ads_campaign_id ON meta_ads (campaign_id);
CREATE INDEX IF NOT EXISTS ix_meta_ads_adset_id ON meta_ads (adset_id);
CREATE INDEX IF NOT EXISTS ix_meta_ads_status ON meta_ads (status);
