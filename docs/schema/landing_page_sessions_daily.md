# `landing_page_sessions_daily`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~409,798 rows (planner estimate) · 112 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `session_date` | `date` | no |  |
| 2 | `landing_page_path` | `text` | no |  |
| 3 | `sessions` | `bigint` | no |  |
| 4 | `online_store_visitors` | `bigint` | no |  |
| 5 | `sessions_with_cart_additions` | `bigint` | no |  |
| 6 | `sessions_that_reached_checkout` | `bigint` | no |  |
| 7 | `bounces` | `bigint` | no |  |
| 8 | `synced_at` | `timestamp with time zone` | no |  |

## Keys and indexes

- **Primary key** — `landing_page_sessions_daily_pkey`
  - `CREATE UNIQUE INDEX landing_page_sessions_daily_pkey ON public.landing_page_sessions_daily USING btree (session_date, landing_page_path)`

## Possible joins

No shared key-like column names with other tables.

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
