-- One-time setup for the @saadaa_women full-data fetch (IG_USER_ID_3).
--
-- Run this ONCE in the target Supabase project's SQL Editor before
-- inserting into it via the REST Data API (PostgREST can't run DDL).
--
-- Same Bronze envelope shape as raw_dump_instagram / raw_dump_meta /
-- raw_dump_shopify -- object_type distinguishes what was fetched:
--   ig_user                  -- account profile (1 row)
--   ig_media                 -- self-posted media (expected: 0 rows --
--                                confirmed live this account has never
--                                posted independently)
--   ig_collaborative_media   -- posts where this account is an accepted
--                                collaborator (confirmed: ~813 of 815
--                                total posts)
--   ig_collaboration_invites -- pending collaboration requests not yet
--                                accepted (confirmed: ~59)
--
-- object_type is VARCHAR(64) (not Meta's original narrower VARCHAR(32))
-- since Shopify/Instagram object_type values run longer than Meta's --
-- see raw_dump_shopify.sql's note on the same fix.

CREATE TABLE IF NOT EXISTS sdw_tale (
    id UUID PRIMARY KEY,
    source_id VARCHAR(64),
    raw_payload JSONB NOT NULL,
    api_endpoint VARCHAR(255) NOT NULL,
    api_version VARCHAR(16) NOT NULL,
    batch_id UUID NOT NULL,
    request_params JSONB,
    extracted_at TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    sync_type VARCHAR(32) NOT NULL,
    payload_hash VARCHAR(64) NOT NULL,
    processing_status VARCHAR(16) NOT NULL,
    object_type VARCHAR(64) NOT NULL,
    parent_ids JSONB,
    is_nested BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS ix_sdw_tale_source_id ON sdw_tale (source_id);
CREATE INDEX IF NOT EXISTS ix_sdw_tale_batch_id ON sdw_tale (batch_id);
CREATE INDEX IF NOT EXISTS ix_sdw_tale_payload_hash ON sdw_tale (payload_hash);
CREATE INDEX IF NOT EXISTS ix_sdw_tale_object_type ON sdw_tale (object_type);
CREATE INDEX IF NOT EXISTS ix_sdw_tale_raw_payload_gin ON sdw_tale USING GIN (raw_payload);

-- Written via the service-role key, which bypasses Row Level Security --
-- RLS does not need to be enabled/configured for this table for a script
-- to insert into it.
