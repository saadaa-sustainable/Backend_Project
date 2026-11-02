# `dump_instagram`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~1,520 rows (planner estimate) · 6352 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `id` | `uuid` | no |  |
| 2 | `source_id` | `character varying(64)` | yes |  |
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

- **Primary key** — `dump_instagram_pkey`
  - `CREATE UNIQUE INDEX dump_instagram_pkey ON public.dump_instagram USING btree (id)`
- Unique — `ux_dump_instagram_object_type_source_id`: `CREATE UNIQUE INDEX ux_dump_instagram_object_type_source_id ON public.dump_instagram USING btree (object_type, source_id) WHERE (source_id IS NOT NULL)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `batch_id` → `failed_jobs`, `meta_dump_ads`, `raw_dump_google_ads`, `raw_dump_instagram`, `raw_dump_meta`, `raw_dump_meta_daily`, `raw_dump_shopify`
- `parent_ids` → `meta_dump_ads`, `raw_dump_google_ads`, `raw_dump_instagram`, `raw_dump_meta`, `raw_dump_meta_daily`, `raw_dump_shopify`
- `source_id` → `insta_data`, `raw_dump_instagram`, `raw_dump_shopify`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
