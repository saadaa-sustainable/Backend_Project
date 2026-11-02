# `meta_dump_ads`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~15,976 rows (planner estimate) · 81 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `id` | `uuid` | no |  |
| 2 | `meta_id` | `character varying(64)` | yes |  |
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

- **Primary key** — `meta_dump_ads_pkey`
  - `CREATE UNIQUE INDEX meta_dump_ads_pkey ON public.meta_dump_ads USING btree (id)`
- Unique — `ux_meta_dump_ads_object_type_meta_id`: `CREATE UNIQUE INDEX ux_meta_dump_ads_object_type_meta_id ON public.meta_dump_ads USING btree (object_type, meta_id) WHERE (meta_id IS NOT NULL)`
- Index — `ix_meta_dump_ads_batch_id`: `CREATE INDEX ix_meta_dump_ads_batch_id ON public.meta_dump_ads USING btree (batch_id)`
- Index — `ix_meta_dump_ads_meta_id`: `CREATE INDEX ix_meta_dump_ads_meta_id ON public.meta_dump_ads USING btree (meta_id)`
- Index — `ix_meta_dump_ads_object_type`: `CREATE INDEX ix_meta_dump_ads_object_type ON public.meta_dump_ads USING btree (object_type)`
- Index — `ix_meta_dump_ads_payload_hash`: `CREATE INDEX ix_meta_dump_ads_payload_hash ON public.meta_dump_ads USING btree (payload_hash)`
- Index — `ix_meta_dump_ads_raw_payload_gin`: `CREATE INDEX ix_meta_dump_ads_raw_payload_gin ON public.meta_dump_ads USING gin (raw_payload)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `batch_id` → `dump_instagram`, `failed_jobs`, `raw_dump_google_ads`, `raw_dump_instagram`, `raw_dump_meta`, `raw_dump_meta_daily`, `raw_dump_shopify`
- `meta_id` → `raw_dump_meta`, `raw_dump_meta_daily`
- `parent_ids` → `dump_instagram`, `raw_dump_google_ads`, `raw_dump_instagram`, `raw_dump_meta`, `raw_dump_meta_daily`, `raw_dump_shopify`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
