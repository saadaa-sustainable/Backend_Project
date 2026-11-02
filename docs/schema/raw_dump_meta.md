# `raw_dump_meta`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~4,123,303 rows (planner estimate) · 11 GB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `object_type` | `character varying(32)` | no |  |
| 2 | `parent_ids` | `jsonb` | yes |  |
| 3 | `is_nested` | `boolean` | no |  |
| 4 | `id` | `uuid` | no |  |
| 5 | `meta_id` | `character varying(64)` | yes |  |
| 6 | `raw_payload` | `jsonb` | no |  |
| 7 | `api_endpoint` | `character varying(255)` | no |  |
| 8 | `api_version` | `character varying(16)` | no |  |
| 9 | `batch_id` | `uuid` | no |  |
| 10 | `request_params` | `jsonb` | yes |  |
| 11 | `extracted_at` | `timestamp with time zone` | no |  |
| 12 | `ingested_at` | `timestamp with time zone` | no | `now()` |
| 13 | `sync_type` | `character varying(32)` | no |  |
| 14 | `payload_hash` | `character varying(64)` | no |  |
| 15 | `processing_status` | `character varying(16)` | no |  |

## Keys and indexes

- **Primary key** — `raw_dump_meta_pkey`
  - `CREATE UNIQUE INDEX raw_dump_meta_pkey ON public.raw_dump_meta USING btree (id)`
- Index — `ix_raw_dump_meta_batch_id`: `CREATE INDEX ix_raw_dump_meta_batch_id ON public.raw_dump_meta USING btree (batch_id)`
- Index — `ix_raw_dump_meta_batch_meta`: `CREATE INDEX ix_raw_dump_meta_batch_meta ON public.raw_dump_meta USING btree (batch_id, meta_id)`
- Index — `ix_raw_dump_meta_extracted_at`: `CREATE INDEX ix_raw_dump_meta_extracted_at ON public.raw_dump_meta USING btree (extracted_at DESC)`
- Index — `ix_raw_dump_meta_insights_level_meta_extracted`: `CREATE INDEX ix_raw_dump_meta_insights_level_meta_extracted ON public.raw_dump_meta USING btree (((parent_ids ->> 'level'::text)), meta_id, extracted_at DESC) WHERE ((object_type)::text = 'insights'::text)`
- Index — `ix_raw_dump_meta_meta_id`: `CREATE INDEX ix_raw_dump_meta_meta_id ON public.raw_dump_meta USING btree (meta_id)`
- Index — `ix_raw_dump_meta_object_type`: `CREATE INDEX ix_raw_dump_meta_object_type ON public.raw_dump_meta USING btree (object_type)`
- Index — `ix_raw_dump_meta_object_type_meta_id`: `CREATE INDEX ix_raw_dump_meta_object_type_meta_id ON public.raw_dump_meta USING btree (object_type, meta_id)`
- Index — `ix_raw_dump_meta_payload_hash`: `CREATE INDEX ix_raw_dump_meta_payload_hash ON public.raw_dump_meta USING btree (payload_hash)`
- Index — `ix_raw_dump_meta_processing_status`: `CREATE INDEX ix_raw_dump_meta_processing_status ON public.raw_dump_meta USING btree (processing_status)`
- Index — `ix_raw_dump_meta_raw_payload_gin`: `CREATE INDEX ix_raw_dump_meta_raw_payload_gin ON public.raw_dump_meta USING gin (raw_payload)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `batch_id` → `dump_instagram`, `failed_jobs`, `meta_dump_ads`, `raw_dump_google_ads`, `raw_dump_instagram`, `raw_dump_meta_daily`, `raw_dump_shopify`
- `meta_id` → `meta_dump_ads`, `raw_dump_meta_daily`
- `parent_ids` → `dump_instagram`, `meta_dump_ads`, `raw_dump_google_ads`, `raw_dump_instagram`, `raw_dump_meta_daily`, `raw_dump_shopify`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
