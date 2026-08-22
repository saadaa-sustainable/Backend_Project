-- One-time setup for a "last 15 days" Meta Ads Insights trial table.
--
-- NOTE: "15d_tt" starts with a digit, which is NOT a valid *unquoted*
-- Postgres identifier -- CREATE TABLE 15d_tt (...) would be a syntax
-- error. It must be double-quoted everywhere it's referenced (DDL here,
-- and in any script/SQL that queries it later): "15d_tt", not 15d_tt.
-- Postgres also lower-cases unquoted identifiers by default, so keeping
-- it quoted consistently avoids a second, subtly different table being
-- created by accident.
--
-- Run this ONCE in the target Supabase project's SQL Editor before
-- inserting into it via the REST Data API (PostgREST can't run DDL).
--
-- Same Bronze envelope shape as raw_dump_meta / test_table (see
-- alembic/versions/0001_initial_bronze_schema.py and
-- scripts/sql/test_table.sql) -- object_type will always be "insights"
-- here since this table is scoped to the last-15-days Insights trial.

CREATE TABLE IF NOT EXISTS "15d_tt" (
    id UUID PRIMARY KEY,
    meta_id VARCHAR(64),
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
    object_type VARCHAR(32) NOT NULL,
    parent_ids JSONB,
    is_nested BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS ix_15d_tt_meta_id ON "15d_tt" (meta_id);
CREATE INDEX IF NOT EXISTS ix_15d_tt_batch_id ON "15d_tt" (batch_id);
CREATE INDEX IF NOT EXISTS ix_15d_tt_payload_hash ON "15d_tt" (payload_hash);
CREATE INDEX IF NOT EXISTS ix_15d_tt_object_type ON "15d_tt" (object_type);
CREATE INDEX IF NOT EXISTS ix_15d_tt_raw_payload_gin ON "15d_tt" USING GIN (raw_payload);

-- Written via the service-role key, which bypasses Row Level Security --
-- RLS does not need to be enabled/configured for this table for a script
-- to insert into it.
