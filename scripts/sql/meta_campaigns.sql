-- Flattened, typed view of raw_dump_meta's object_type='campaign' rows --
-- every key discovered live 2026-08-20 by scanning all 1,030 real
-- campaign rows (not sampled), unioned with app/core/meta_registry.py's
-- CAMPAIGN_FIELDS for fields that are valid but hadn't appeared yet
-- (spend_cap, issues_info) so the table doesn't need a follow-up
-- migration once they do.
--
-- Nested objects/arrays (special_ad_categories, promoted_object,
-- pacing_type, issues_info) kept as JSONB, same convention as
-- insta_data.sql's owner/boost_eligibility_info/boost_ads_list --
-- they're structured data, not flat scalars.
--
-- Run once in the Supabase SQL Editor, or via the direct DSN -- this
-- project's DDL convention throughout (see scripts/sql/insta_data.sql).

DROP TABLE IF EXISTS meta_campaigns;

CREATE TABLE meta_campaigns AS
SELECT
    -- envelope / context
    id,
    meta_id,
    batch_id,
    parent_ids ->> 'account_key' AS account_key,
    parent_ids ->> 'account_name' AS account_name,
    parent_ids ->> 'account_id' AS account_id,
    extracted_at,
    ingested_at,

    -- identity / status
    raw_payload ->> 'name' AS name,
    raw_payload ->> 'status' AS status,
    raw_payload ->> 'effective_status' AS effective_status,
    raw_payload ->> 'objective' AS objective,
    raw_payload ->> 'buying_type' AS buying_type,
    raw_payload ->> 'smart_promotion_type' AS smart_promotion_type,
    raw_payload ->> 'source_campaign_id' AS source_campaign_id,

    -- budget / bidding (Meta returns these as strings -- cast to numeric)
    NULLIF(raw_payload ->> 'daily_budget', '')::numeric AS daily_budget,
    NULLIF(raw_payload ->> 'lifetime_budget', '')::numeric AS lifetime_budget,
    NULLIF(raw_payload ->> 'budget_remaining', '')::numeric AS budget_remaining,
    NULLIF(raw_payload ->> 'spend_cap', '')::numeric AS spend_cap,
    raw_payload ->> 'bid_strategy' AS bid_strategy,

    -- dates
    NULLIF(raw_payload ->> 'start_time', '')::timestamptz AS start_time,
    NULLIF(raw_payload ->> 'stop_time', '')::timestamptz AS stop_time,
    NULLIF(raw_payload ->> 'created_time', '')::timestamptz AS created_time,
    NULLIF(raw_payload ->> 'updated_time', '')::timestamptz AS updated_time,

    -- nested / structured (kept as JSONB, not flattened further)
    raw_payload -> 'special_ad_categories' AS special_ad_categories,
    raw_payload -> 'promoted_object' AS promoted_object,
    raw_payload -> 'pacing_type' AS pacing_type,
    raw_payload -> 'issues_info' AS issues_info
FROM raw_dump_meta
WHERE object_type = 'campaign';

CREATE INDEX IF NOT EXISTS ix_meta_campaigns_meta_id ON meta_campaigns (meta_id);
CREATE INDEX IF NOT EXISTS ix_meta_campaigns_account_key ON meta_campaigns (account_key);
CREATE INDEX IF NOT EXISTS ix_meta_campaigns_status ON meta_campaigns (status);
