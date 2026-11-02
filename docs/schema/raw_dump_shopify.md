# `raw_dump_shopify`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~6,766,613 rows (planner estimate) · 15 GB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `id` | `uuid` | no |  |
| 2 | `source_id` | `character varying(255)` | yes |  |
| 3 | `raw_payload` | `jsonb` | no |  |
| 4 | `api_endpoint` | `character varying(255)` | no |  |
| 5 | `api_version` | `character varying(16)` | no |  |
| 6 | `batch_id` | `uuid` | no |  |
| 7 | `request_params` | `jsonb` | yes |  |
| 8 | `extracted_at` | `timestamp with time zone` | no |  |
| 9 | `ingested_at` | `timestamp with time zone` | no | `now()` |
| 10 | `sync_type` | `character varying(32)` | no |  |
| 11 | `payload_hash` | `character varying(64)` | no |  |
| 12 | `processing_status` | `character varying(16)` | no |  |
| 13 | `object_type` | `character varying(64)` | no |  |
| 14 | `parent_ids` | `jsonb` | yes |  |
| 15 | `is_nested` | `boolean` | no | `false` |

## Keys and indexes

- **Primary key** — `raw_dump_shopify_pkey`
  - `CREATE UNIQUE INDEX raw_dump_shopify_pkey ON public.raw_dump_shopify USING btree (id)`
- Unique — `ux_raw_dump_shopify_object_type_source_id`: `CREATE UNIQUE INDEX ux_raw_dump_shopify_object_type_source_id ON public.raw_dump_shopify USING btree (object_type, source_id) WHERE (source_id IS NOT NULL)`
- Index — `ix_raw_dump_shopify_batch_id`: `CREATE INDEX ix_raw_dump_shopify_batch_id ON public.raw_dump_shopify USING btree (batch_id)`
- Index — `ix_raw_dump_shopify_extracted_at`: `CREATE INDEX ix_raw_dump_shopify_extracted_at ON public.raw_dump_shopify USING btree (extracted_at DESC)`
- Index — `ix_raw_dump_shopify_object_type`: `CREATE INDEX ix_raw_dump_shopify_object_type ON public.raw_dump_shopify USING btree (object_type)`
- Index — `ix_raw_dump_shopify_object_type_extracted`: `CREATE INDEX ix_raw_dump_shopify_object_type_extracted ON public.raw_dump_shopify USING btree (object_type, extracted_at DESC)`
- Index — `ix_raw_dump_shopify_object_type_source_extracted`: `CREATE INDEX ix_raw_dump_shopify_object_type_source_extracted ON public.raw_dump_shopify USING btree (object_type, source_id, extracted_at DESC)`
- Index — `ix_raw_dump_shopify_object_type_source_id`: `CREATE INDEX ix_raw_dump_shopify_object_type_source_id ON public.raw_dump_shopify USING btree (object_type, source_id)`
- Index — `ix_raw_dump_shopify_payload_hash`: `CREATE INDEX ix_raw_dump_shopify_payload_hash ON public.raw_dump_shopify USING btree (payload_hash)`
- Index — `ix_raw_dump_shopify_raw_payload_gin`: `CREATE INDEX ix_raw_dump_shopify_raw_payload_gin ON public.raw_dump_shopify USING gin (raw_payload)`
- Index — `ix_raw_dump_shopify_source_id`: `CREATE INDEX ix_raw_dump_shopify_source_id ON public.raw_dump_shopify USING btree (source_id)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `batch_id` → `dump_instagram`, `failed_jobs`, `meta_dump_ads`, `raw_dump_google_ads`, `raw_dump_instagram`, `raw_dump_meta`, `raw_dump_meta_daily`
- `parent_ids` → `dump_instagram`, `meta_dump_ads`, `raw_dump_google_ads`, `raw_dump_instagram`, `raw_dump_meta`, `raw_dump_meta_daily`
- `source_id` → `dump_instagram`, `insta_data`, `raw_dump_instagram`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
