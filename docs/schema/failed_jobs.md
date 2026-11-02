# `failed_jobs`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~866 rows (planner estimate) · 1224 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `id` | `uuid` | no |  |
| 2 | `batch_id` | `uuid` | no |  |
| 3 | `endpoint` | `character varying(64)` | no |  |
| 4 | `account_key` | `character varying(16)` | yes |  |
| 5 | `account_name` | `character varying(128)` | yes |  |
| 6 | `request_params` | `jsonb` | yes |  |
| 7 | `error_message` | `text` | no |  |
| 8 | `attempt_count` | `integer` | no | `1` |
| 9 | `resolved` | `boolean` | no | `false` |
| 10 | `created_at` | `timestamp with time zone` | no | `now()` |
| 11 | `last_attempted_at` | `timestamp with time zone` | no | `now()` |

## Keys and indexes

- **Primary key** — `failed_jobs_pkey`
  - `CREATE UNIQUE INDEX failed_jobs_pkey ON public.failed_jobs USING btree (id)`
- Index — `ix_failed_jobs_account_key`: `CREATE INDEX ix_failed_jobs_account_key ON public.failed_jobs USING btree (account_key)`
- Index — `ix_failed_jobs_batch_id`: `CREATE INDEX ix_failed_jobs_batch_id ON public.failed_jobs USING btree (batch_id)`
- Index — `ix_failed_jobs_endpoint`: `CREATE INDEX ix_failed_jobs_endpoint ON public.failed_jobs USING btree (endpoint)`
- Index — `ix_failed_jobs_resolved`: `CREATE INDEX ix_failed_jobs_resolved ON public.failed_jobs USING btree (resolved)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `account_key` → `insta_data`, `sync_batches`
- `batch_id` → `dump_instagram`, `meta_dump_ads`, `raw_dump_google_ads`, `raw_dump_instagram`, `raw_dump_meta`, `raw_dump_meta_daily`, `raw_dump_shopify`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
