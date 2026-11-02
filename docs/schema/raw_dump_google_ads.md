# `raw_dump_google_ads`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~4,836 rows (planner estimate) · 5144 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `id` | `uuid` | no |  |
| 2 | `object_type` | `character varying` | no |  |
| 3 | `google_id` | `character varying` | no |  |
| 4 | `parent_ids` | `jsonb` | yes |  |
| 5 | `raw_payload` | `jsonb` | no |  |
| 6 | `api_endpoint` | `character varying` | yes |  |
| 7 | `api_version` | `character varying` | yes |  |
| 8 | `batch_id` | `uuid` | no |  |
| 9 | `request_params` | `jsonb` | yes |  |
| 10 | `extracted_at` | `timestamp with time zone` | no |  |
| 11 | `ingested_at` | `timestamp with time zone` | no | `now()` |
| 12 | `sync_type` | `character varying` | yes |  |
| 13 | `payload_hash` | `character varying` | yes |  |
| 14 | `processing_status` | `character varying` | yes | `'pending'::character varying` |

## Keys and indexes

- **Primary key** — `raw_dump_google_ads_pkey`
  - `CREATE UNIQUE INDEX raw_dump_google_ads_pkey ON public.raw_dump_google_ads USING btree (id)`
- Index — `ix_raw_dump_google_ads_batch`: `CREATE INDEX ix_raw_dump_google_ads_batch ON public.raw_dump_google_ads USING btree (batch_id)`
- Index — `ix_raw_dump_google_ads_entity`: `CREATE INDEX ix_raw_dump_google_ads_entity ON public.raw_dump_google_ads USING btree (object_type, google_id, extracted_at DESC)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `batch_id` → `dump_instagram`, `failed_jobs`, `meta_dump_ads`, `raw_dump_instagram`, `raw_dump_meta`, `raw_dump_meta_daily`, `raw_dump_shopify`
- `parent_ids` → `dump_instagram`, `meta_dump_ads`, `raw_dump_instagram`, `raw_dump_meta`, `raw_dump_meta_daily`, `raw_dump_shopify`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
