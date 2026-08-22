-- One-time setup for scripts/dump_test_table.py.
--
-- Run this ONCE in the target Supabase project's SQL Editor (Project ->
-- SQL Editor -> New query) before running the script. PostgREST (the
-- REST Data API the script writes through, using the service-role key)
-- cannot execute DDL, so table creation has to happen here instead.
--
-- Mirrors the real Bronze `raw_dump_meta` table shape exactly (see
-- alembic/versions/0001_initial_bronze_schema.py) so this test data is
-- structurally identical to what a real sync would produce -- just
-- landing in its own throwaway table instead of the production one.

CREATE TABLE IF NOT EXISTS test_table (
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

CREATE INDEX IF NOT EXISTS ix_test_table_meta_id ON test_table (meta_id);
CREATE INDEX IF NOT EXISTS ix_test_table_batch_id ON test_table (batch_id);
CREATE INDEX IF NOT EXISTS ix_test_table_payload_hash ON test_table (payload_hash);
CREATE INDEX IF NOT EXISTS ix_test_table_object_type ON test_table (object_type);
CREATE INDEX IF NOT EXISTS ix_test_table_raw_payload_gin ON test_table USING GIN (raw_payload);

-- The script writes via the service-role key, which bypasses Row Level
-- Security entirely -- RLS does not need to be enabled/configured for
-- this table for the script to work. If you also want to query this
-- table from a client using the anon key later, enable RLS and add a
-- policy at that point.
