# `ga4_arpu_daily`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~204 rows (planner estimate) · 112 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `day` | `date` | no |  |
| 2 | `device_category` | `text` | no |  |
| 3 | `active_users` | `bigint` | no |  |
| 4 | `total_revenue` | `numeric` | no |  |
| 5 | `sessions` | `bigint` | no |  |
| 6 | `purchases` | `bigint` | no |  |
| 7 | `fetched_at` | `timestamp with time zone` | no |  |

## Keys and indexes

- **Primary key** — `ga4_arpu_daily_pkey`
  - `CREATE UNIQUE INDEX ga4_arpu_daily_pkey ON public.ga4_arpu_daily USING btree (day, device_category)`
- Index — `ix_ga4_arpu_daily_day`: `CREATE INDEX ix_ga4_arpu_daily_day ON public.ga4_arpu_daily USING btree (day)`

## Possible joins

No shared key-like column names with other tables.

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
