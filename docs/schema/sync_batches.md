# `sync_batches`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~7,650 rows (planner estimate) · 5040 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `id` | `uuid` | no |  |
| 2 | `endpoint` | `character varying(64)` | no |  |
| 3 | `account_key` | `character varying(16)` | yes |  |
| 4 | `account_name` | `character varying(128)` | yes |  |
| 5 | `sync_type` | `character varying(32)` | no |  |
| 6 | `status` | `character varying(32)` | no |  |
| 7 | `request_params` | `jsonb` | yes |  |
| 8 | `records_fetched` | `integer` | no | `0` |
| 9 | `records_failed` | `integer` | no | `0` |
| 10 | `error_message` | `text` | yes |  |
| 11 | `started_at` | `timestamp with time zone` | no | `now()` |
| 12 | `finished_at` | `timestamp with time zone` | yes |  |
| 13 | `triggered_by` | `character varying(32)` | no | `'manual'::character varying` |

## Keys and indexes

- **Primary key** — `sync_batches_pkey`
  - `CREATE UNIQUE INDEX sync_batches_pkey ON public.sync_batches USING btree (id)`
- Index — `ix_sync_batches_account_key`: `CREATE INDEX ix_sync_batches_account_key ON public.sync_batches USING btree (account_key)`
- Index — `ix_sync_batches_endpoint`: `CREATE INDEX ix_sync_batches_endpoint ON public.sync_batches USING btree (endpoint)`
- Index — `ix_sync_batches_status`: `CREATE INDEX ix_sync_batches_status ON public.sync_batches USING btree (status)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `account_key` → `failed_jobs`, `insta_data`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
