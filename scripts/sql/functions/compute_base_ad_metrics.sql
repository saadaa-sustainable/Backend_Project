-- First concrete Gold-layer function under the "option B" pattern (see
-- scripts/sql/functions/README-shaped comment below): SQL does the join +
-- aggregation + decimal math server-side, Python only calls it via RPC.
--
-- Scope deliberately narrow: base per-ad, per-day metrics that have zero
-- open questions -- spend, impressions, clicks, CTR, and ROAS as Meta's own
-- `purchase_roas` field reports it. Does NOT include the F1-F4 six-category
-- ad scoring (Incremental Winner / Winner / P0-P2 / Discarded) -- that
-- needs the F2 (3 vs 3.2) / F4 (<=12 vs <=25) threshold ruling first (see
-- project memory: ctd-fx-threshold-inconsistency), and NCP/FTEWV cost-per
-- metrics, which need custom-conversion-id resolution per ad account that
-- hasn't been built in this service yet.
--
-- Run this ONCE in the target Supabase project's SQL Editor -- PostgREST
-- can't execute DDL/CREATE FUNCTION, same reason table DDL lives here too.
-- CREATE OR REPLACE makes re-running safe while this is still being tuned.
--
-- Reads raw_dump_meta WHERE object_type = 'insights'. Bronze is
-- append-only and not deduplicated at write time (repeated ingestion runs
-- can leave more than one row for the same ad+date), so this picks the
-- most-recently-ingested row per (ad_id, date_start) rather than summing
-- across duplicates.
--
-- NOT YET LIVE-VERIFIED: the exact shape of the `purchase_roas` array in a
-- real captured raw_dump_meta row (Meta typically returns a single-element
-- array like [{"action_type":"omni_purchase","value":"4.52"}], but this
-- codebase hasn't captured and inspected a real `object_type='insights'`
-- row yet). Takes the first array element's value. Confirm against a real
-- row before trusting the roas column -- this is exactly the kind of
-- assumption this project has otherwise insisted on live-verifying rather
-- than trusting docs for.

CREATE OR REPLACE FUNCTION compute_base_ad_metrics(
    p_account_id text DEFAULT NULL,
    p_date_start date DEFAULT NULL,
    p_date_end date DEFAULT NULL
)
RETURNS TABLE (
    ad_id text,
    ad_name text,
    campaign_id text,
    adset_id text,
    account_id text,
    date_start date,
    date_stop date,
    impressions numeric,
    clicks numeric,
    spend numeric,
    ctr numeric,
    purchase_roas numeric
)
LANGUAGE sql
STABLE
AS $$
    WITH latest AS (
        SELECT DISTINCT ON (raw_payload ->> 'ad_id', raw_payload ->> 'date_start')
            raw_payload
        FROM raw_dump_meta
        WHERE object_type = 'insights'
          AND raw_payload ->> 'ad_id' IS NOT NULL
          AND raw_payload ->> 'date_start' IS NOT NULL
          AND (p_account_id IS NULL OR raw_payload ->> 'account_id' = p_account_id)
          AND (p_date_start IS NULL OR (raw_payload ->> 'date_start')::date >= p_date_start)
          AND (p_date_end IS NULL OR (raw_payload ->> 'date_start')::date <= p_date_end)
        ORDER BY raw_payload ->> 'ad_id', raw_payload ->> 'date_start', ingested_at DESC
    )
    SELECT
        raw_payload ->> 'ad_id',
        raw_payload ->> 'ad_name',
        raw_payload ->> 'campaign_id',
        raw_payload ->> 'adset_id',
        raw_payload ->> 'account_id',
        (raw_payload ->> 'date_start')::date,
        (raw_payload ->> 'date_stop')::date,
        COALESCE((raw_payload ->> 'impressions')::numeric, 0),
        COALESCE((raw_payload ->> 'clicks')::numeric, 0),
        COALESCE((raw_payload ->> 'spend')::numeric, 0),
        CASE
            WHEN COALESCE((raw_payload ->> 'impressions')::numeric, 0) = 0 THEN 0
            ELSE ROUND(
                COALESCE((raw_payload ->> 'clicks')::numeric, 0)
                / (raw_payload ->> 'impressions')::numeric * 100,
                4
            )
        END,
        (
            SELECT (elem ->> 'value')::numeric
            FROM jsonb_array_elements(COALESCE(raw_payload -> 'purchase_roas', '[]'::jsonb)) elem
            LIMIT 1
        )
    FROM latest;
$$;
