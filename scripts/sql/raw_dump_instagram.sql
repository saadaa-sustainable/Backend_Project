-- One-time setup for scripts/ingest_instagram.py.
--
-- Run this ONCE in the target Supabase project's SQL Editor (Project ->
-- SQL Editor -> New query) before running the script. PostgREST (the
-- REST Data API the script writes through, using the service-role key)
-- cannot execute DDL, so table creation has to happen here instead.
--
-- Same Bronze envelope shape as raw_dump_meta / raw_dump_shopify (see
-- alembic/versions/0001_initial_bronze_schema.py) -- a single
-- consolidated raw-dump table tagged by object_type (ig_user / ig_media /
-- ig_media_insights), keeping the Instagram ingestion path structurally
-- identical to the Meta Marketing API and Shopify ones. Instagram Graph
-- API is the SAME underlying Graph API as the Marketing API (same
-- access token, same graph.facebook.com host, same REST/cursor-pagination
-- shape) -- just different node types -- so this reuses the wider
-- VARCHAR(64) object_type sizing already fixed for Shopify rather than
-- Meta's original narrower one.

CREATE TABLE IF NOT EXISTS raw_dump_instagram (
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

CREATE INDEX IF NOT EXISTS ix_raw_dump_instagram_source_id ON raw_dump_instagram (source_id);
CREATE INDEX IF NOT EXISTS ix_raw_dump_instagram_batch_id ON raw_dump_instagram (batch_id);
CREATE INDEX IF NOT EXISTS ix_raw_dump_instagram_payload_hash ON raw_dump_instagram (payload_hash);
CREATE INDEX IF NOT EXISTS ix_raw_dump_instagram_object_type ON raw_dump_instagram (object_type);
CREATE INDEX IF NOT EXISTS ix_raw_dump_instagram_object_type_source_id ON raw_dump_instagram (object_type, source_id);
CREATE INDEX IF NOT EXISTS ix_raw_dump_instagram_raw_payload_gin ON raw_dump_instagram USING GIN (raw_payload);

-- The script writes via the service-role key, which bypasses Row Level
-- Security entirely -- RLS does not need to be enabled/configured for
-- this table for the script to work. If you also want to query this
-- table from a client using the anon key later, enable RLS and add a
-- policy at that point.
