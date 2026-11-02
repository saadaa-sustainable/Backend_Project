# `kwikchat_spend_daily`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~306 rows (planner estimate) · 144 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `day` | `date` | no |  |
| 2 | `spend` | `numeric` | no | `0` |
| 3 | `is_estimate` | `boolean` | no | `true` |
| 4 | `source` | `text` | yes |  |
| 5 | `fetched_at` | `timestamp with time zone` | no | `now()` |

## Keys and indexes

- **Primary key** — `kwikchat_spend_daily_pkey`
  - `CREATE UNIQUE INDEX kwikchat_spend_daily_pkey ON public.kwikchat_spend_daily USING btree (day)`
- Index — `ix_kwikchat_spend_daily_estimate`: `CREATE INDEX ix_kwikchat_spend_daily_estimate ON public.kwikchat_spend_daily USING btree (is_estimate)`

## Possible joins

No shared key-like column names with other tables.

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
