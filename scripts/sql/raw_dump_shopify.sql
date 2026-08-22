-- One-time setup for scripts/ingest_shopify.py.
--
-- Run this ONCE in the target Supabase project's SQL Editor (Project ->
-- SQL Editor -> New query) before running the script. PostgREST (the
-- REST Data API the script writes through, using the service-role key)
-- cannot execute DDL, so table creation has to happen here instead.
--
-- Same Bronze envelope shape as raw_dump_meta / test_table (see
-- alembic/versions/0001_initial_bronze_schema.py and
-- scripts/sql/test_table.sql) -- a single consolidated raw-dump table
-- tagged by object_type (shop / product / order / customer), keeping the
-- Shopify ingestion path structurally identical to the Meta one.

-- Safe to re-run: widens an already-created table's object_type column
-- (originally VARCHAR(32), too narrow for Shopify's longer field names --
-- found live when a real insert hit "value too long for type character
-- varying(32)"). A no-op if the table doesn't exist yet or is already
-- VARCHAR(64)+.
ALTER TABLE IF EXISTS raw_dump_shopify ALTER COLUMN object_type TYPE VARCHAR(64);

CREATE TABLE IF NOT EXISTS raw_dump_shopify (
    id UUID PRIMARY KEY,
    source_id VARCHAR(255),
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
    -- 64, not 32: unlike Meta's short object_type tags (campaign/adset/ad/
    -- insights), Shopify's GraphQL root field names are used directly as
    -- object_type and run long -- e.g.
    -- "locationsAvailableForDeliveryProfilesConnection" is 47 chars.
    object_type VARCHAR(64) NOT NULL,
    parent_ids JSONB,
    is_nested BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS ix_raw_dump_shopify_source_id ON raw_dump_shopify (source_id);
CREATE INDEX IF NOT EXISTS ix_raw_dump_shopify_batch_id ON raw_dump_shopify (batch_id);
CREATE INDEX IF NOT EXISTS ix_raw_dump_shopify_payload_hash ON raw_dump_shopify (payload_hash);
CREATE INDEX IF NOT EXISTS ix_raw_dump_shopify_object_type ON raw_dump_shopify (object_type);
CREATE INDEX IF NOT EXISTS ix_raw_dump_shopify_object_type_source_id ON raw_dump_shopify (object_type, source_id);
CREATE INDEX IF NOT EXISTS ix_raw_dump_shopify_raw_payload_gin ON raw_dump_shopify USING GIN (raw_payload);

-- The script writes via the service-role key, which bypasses Row Level
-- Security entirely -- RLS does not need to be enabled/configured for
-- this table for the script to work. If you also want to query this
-- table from a client using the anon key later, enable RLS and add a
-- policy at that point.
