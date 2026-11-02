# `raw_dump_meta_daily`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~228,184 rows (planner estimate) · 1261 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `id` | `uuid` | no | `gen_random_uuid()` |
| 2 | `meta_id` | `character varying` | yes |  |
| 3 | `raw_payload` | `jsonb` | no |  |
| 4 | `api_endpoint` | `character varying` | yes |  |
| 5 | `api_version` | `character varying` | yes |  |
| 6 | `batch_id` | `uuid` | yes |  |
| 7 | `request_params` | `jsonb` | yes |  |
| 8 | `extracted_at` | `timestamp with time zone` | yes |  |
| 9 | `ingested_at` | `timestamp with time zone` | no | `now()` |
| 10 | `sync_type` | `character varying` | yes |  |
| 11 | `payload_hash` | `character varying` | yes |  |
| 12 | `processing_status` | `character varying` | yes |  |
| 13 | `object_type` | `character varying` | yes |  |
| 14 | `parent_ids` | `jsonb` | yes |  |
| 15 | `is_nested` | `boolean` | no | `false` |

## Keys and indexes

- **Primary key** — `raw_dump_meta_daily_pkey`
  - `CREATE UNIQUE INDEX raw_dump_meta_daily_pkey ON public.raw_dump_meta_daily USING btree (id)`
- Unique — `ux_meta_daily_ad_date`: `CREATE UNIQUE INDEX ux_meta_daily_ad_date ON public.raw_dump_meta_daily USING btree (((raw_payload ->> 'ad_id'::text)), ((raw_payload ->> 'date_start'::text))) WHERE (((raw_payload ->> 'ad_id'::text) IS NOT NULL) AND ((raw_payload ->> 'date_start'::text) IS NOT NULL))`
- Index — `ix_meta_daily_batch_id`: `CREATE INDEX ix_meta_daily_batch_id ON public.raw_dump_meta_daily USING btree (batch_id)`
- Index — `ix_meta_daily_date`: `CREATE INDEX ix_meta_daily_date ON public.raw_dump_meta_daily USING btree (((raw_payload ->> 'date_start'::text)))`
- Index — `ix_meta_daily_meta_id`: `CREATE INDEX ix_meta_daily_meta_id ON public.raw_dump_meta_daily USING btree (meta_id)`
- Index — `ix_meta_daily_parent_account`: `CREATE INDEX ix_meta_daily_parent_account ON public.raw_dump_meta_daily USING btree (((parent_ids ->> 'account_key'::text)))`
- Index — `ix_meta_daily_raw_payload_gin`: `CREATE INDEX ix_meta_daily_raw_payload_gin ON public.raw_dump_meta_daily USING gin (raw_payload)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `batch_id` → `dump_instagram`, `failed_jobs`, `meta_dump_ads`, `raw_dump_google_ads`, `raw_dump_instagram`, `raw_dump_meta`, `raw_dump_shopify`
- `meta_id` → `meta_dump_ads`, `raw_dump_meta`
- `parent_ids` → `dump_instagram`, `meta_dump_ads`, `raw_dump_google_ads`, `raw_dump_instagram`, `raw_dump_meta`, `raw_dump_shopify`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
