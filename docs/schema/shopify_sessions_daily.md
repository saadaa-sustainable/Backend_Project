# `shopify_sessions_daily`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~306 rows (planner estimate) · 120 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `day` | `date` | no |  |
| 2 | `sessions` | `numeric` | no |  |
| 3 | `flattened_at` | `timestamp with time zone` | no |  |
| 4 | `meta_sessions` | `numeric` | no | `0` |

## Keys and indexes

- **Primary key** — `shopify_sessions_daily_pkey`
  - `CREATE UNIQUE INDEX shopify_sessions_daily_pkey ON public.shopify_sessions_daily USING btree (day)`

## Possible joins

No shared key-like column names with other tables.

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
