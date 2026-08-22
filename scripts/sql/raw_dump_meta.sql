-- One-time setup for Meta Marketing API ingestion.
--
-- Run this ONCE in the target Supabase project's SQL Editor (Project ->
-- SQL Editor -> New query). PostgREST (the REST Data API service scripts
-- write through) cannot execute DDL, so table creation has to happen here
-- instead -- same reason raw_dump_shopify.sql / raw_dump_instagram.sql
-- exist as standalone files.
--
-- Mirrors app/models/raw_dump.py::RawDumpMeta / the alembic migration at
-- alembic/versions/0001_initial_bronze_schema.py exactly (object_type
-- kept at VARCHAR(32), unlike Shopify/Instagram's widened VARCHAR(64) --
-- every Meta object_type value is well under 32 chars, so no widening
-- needed here).

CREATE TABLE IF NOT EXISTS raw_dump_meta (
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

CREATE INDEX IF NOT EXISTS ix_raw_dump_meta_meta_id ON raw_dump_meta (meta_id);
CREATE INDEX IF NOT EXISTS ix_raw_dump_meta_batch_id ON raw_dump_meta (batch_id);
CREATE INDEX IF NOT EXISTS ix_raw_dump_meta_payload_hash ON raw_dump_meta (payload_hash);
CREATE INDEX IF NOT EXISTS ix_raw_dump_meta_processing_status ON raw_dump_meta (processing_status);
CREATE INDEX IF NOT EXISTS ix_raw_dump_meta_object_type ON raw_dump_meta (object_type);
CREATE INDEX IF NOT EXISTS ix_raw_dump_meta_batch_meta ON raw_dump_meta (batch_id, meta_id);
CREATE INDEX IF NOT EXISTS ix_raw_dump_meta_object_type_meta_id ON raw_dump_meta (object_type, meta_id);
CREATE INDEX IF NOT EXISTS ix_raw_dump_meta_raw_payload_gin ON raw_dump_meta USING GIN (raw_payload);

-- Written via the service-role key, which bypasses RLS entirely -- RLS
-- does not need to be configured for this table to work with the scripts.
