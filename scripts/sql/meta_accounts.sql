-- Flattened, typed view of raw_dump_meta's object_type='account' rows.
--
-- UNLIKE meta_campaigns.sql/meta_adsets.sql/meta_ads.sql, this one could
-- NOT be built from real discovered data -- confirmed live 2026-08-20
-- that raw_dump_meta has ZERO object_type='account' rows (only
-- account-LEVEL INSIGHTS rows exist, a different object_type entirely --
-- the account entity itself -- name/currency/timezone/spend caps/etc --
-- has never been fetched). Column list/types instead come from
-- app/core/meta_registry.py's ACCOUNT_FIELDS, cross-checked against
-- Meta's own Marketing API reference for each field's documented type.
-- This table will exist and be correctly shaped, but stay genuinely
-- EMPTY, until an account-entity fetch (GET /act_<id> with these fields)
-- actually runs -- nothing in this ingestion pipeline does that today.
--
-- Run once in the Supabase SQL Editor, or via the direct DSN -- this
-- project's DDL convention throughout (see scripts/sql/insta_data.sql).

DROP TABLE IF EXISTS meta_accounts;

CREATE TABLE meta_accounts AS
SELECT
    -- envelope / context
    id,
    meta_id,
    batch_id,
    parent_ids ->> 'account_key' AS account_key,
    parent_ids ->> 'account_name' AS account_name,
    extracted_at,
    ingested_at,

    -- identity / status
    raw_payload ->> 'account_id' AS account_id,
    raw_payload ->> 'name' AS name,
    (raw_payload ->> 'account_status')::numeric AS account_status,
    (raw_payload ->> 'disable_reason')::numeric AS disable_reason,
    (raw_payload ->> 'age')::numeric AS age,
    raw_payload ->> 'currency' AS currency,
    raw_payload ->> 'business_city' AS business_city,
    raw_payload ->> 'business_country_code' AS business_country_code,
    raw_payload ->> 'end_advertiser' AS end_advertiser,
    raw_payload ->> 'funding_source' AS funding_source,
    raw_payload ->> 'owner' AS owner,
    (raw_payload ->> 'tax_id_status')::numeric AS tax_id_status,

    -- budget / spend (Meta returns these as strings -- cast to numeric)
    (raw_payload ->> 'amount_spent')::numeric AS amount_spent,
    (raw_payload ->> 'balance')::numeric AS balance,
    (raw_payload ->> 'spend_cap')::numeric AS spend_cap,
    (raw_payload ->> 'min_daily_budget')::numeric AS min_daily_budget,
    (raw_payload ->> 'is_prepay_account')::boolean AS is_prepay_account,

    -- timezone
    (raw_payload ->> 'timezone_id')::numeric AS timezone_id,
    raw_payload ->> 'timezone_name' AS timezone_name,
    (raw_payload ->> 'timezone_offset_hours_utc')::numeric AS timezone_offset_hours_utc,

    -- nested / structured (kept as JSONB, not flattened further)
    raw_payload -> 'business' AS business,
    raw_payload -> 'funding_source_details' AS funding_source_details,
    raw_payload -> 'capabilities' AS capabilities,
    raw_payload -> 'attribution_spec' AS attribution_spec
FROM raw_dump_meta
WHERE object_type = 'account';

CREATE INDEX IF NOT EXISTS ix_meta_accounts_meta_id ON meta_accounts (meta_id);
CREATE INDEX IF NOT EXISTS ix_meta_accounts_account_key ON meta_accounts (account_key);
