-- Flattened, typed view of raw_dump_meta's object_type='adset' rows --
-- every key discovered live 2026-08-20 by scanning all 4,197 real adset
-- rows (not sampled), unioned with app/core/meta_registry.py's
-- ADSET_FIELDS for fields valid but not yet observed (dsa_beneficiary,
-- dsa_payor).
--
-- Nested objects/arrays (targeting, promoted_object, learning_stage_info,
-- attribution_spec, frequency_control_specs, pacing_type, issues_info)
-- kept as JSONB -- targeting alone can be a deeply nested spec (age
-- ranges, geo, custom audiences, ...), not something worth flattening
-- into columns here.
--
-- Run once in the Supabase SQL Editor, or via the direct DSN -- this
-- project's DDL convention throughout (see scripts/sql/insta_data.sql).

DROP TABLE IF EXISTS meta_adsets;

CREATE TABLE meta_adsets AS
SELECT
    -- envelope / context
    id,
    meta_id,
    batch_id,
    parent_ids ->> 'account_key' AS account_key,
    parent_ids ->> 'account_name' AS account_name,
    parent_ids ->> 'account_id' AS account_id,
    parent_ids ->> 'campaign_id' AS campaign_id,
    extracted_at,
    ingested_at,

    -- identity / status
    raw_payload ->> 'name' AS name,
    raw_payload ->> 'status' AS status,
    raw_payload ->> 'effective_status' AS effective_status,
    raw_payload ->> 'billing_event' AS billing_event,
    raw_payload ->> 'optimization_goal' AS optimization_goal,
    raw_payload ->> 'destination_type' AS destination_type,

    -- budget / bidding (Meta returns these as strings -- cast to numeric)
    NULLIF(raw_payload ->> 'daily_budget', '')::numeric AS daily_budget,
    NULLIF(raw_payload ->> 'lifetime_budget', '')::numeric AS lifetime_budget,
    NULLIF(raw_payload ->> 'budget_remaining', '')::numeric AS budget_remaining,
    (raw_payload ->> 'bid_amount')::numeric AS bid_amount,
    raw_payload ->> 'bid_strategy' AS bid_strategy,

    -- dates
    NULLIF(raw_payload ->> 'start_time', '')::timestamptz AS start_time,
    NULLIF(raw_payload ->> 'end_time', '')::timestamptz AS end_time,
    NULLIF(raw_payload ->> 'created_time', '')::timestamptz AS created_time,
    NULLIF(raw_payload ->> 'updated_time', '')::timestamptz AS updated_time,

    -- nested / structured (kept as JSONB, not flattened further)
    raw_payload -> 'targeting' AS targeting,
    raw_payload -> 'promoted_object' AS promoted_object,
    raw_payload -> 'attribution_spec' AS attribution_spec,
    raw_payload -> 'learning_stage_info' AS learning_stage_info,
    raw_payload -> 'frequency_control_specs' AS frequency_control_specs,
    raw_payload -> 'pacing_type' AS pacing_type,
    raw_payload -> 'issues_info' AS issues_info,
    raw_payload ->> 'dsa_beneficiary' AS dsa_beneficiary,
    raw_payload ->> 'dsa_payor' AS dsa_payor
FROM raw_dump_meta
WHERE object_type = 'adset';

CREATE INDEX IF NOT EXISTS ix_meta_adsets_meta_id ON meta_adsets (meta_id);
CREATE INDEX IF NOT EXISTS ix_meta_adsets_account_key ON meta_adsets (account_key);
CREATE INDEX IF NOT EXISTS ix_meta_adsets_campaign_id ON meta_adsets (campaign_id);
CREATE INDEX IF NOT EXISTS ix_meta_adsets_status ON meta_adsets (status);
