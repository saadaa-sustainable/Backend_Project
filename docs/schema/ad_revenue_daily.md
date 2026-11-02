# `ad_revenue_daily`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~50,029 rows (planner estimate) · 11 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `ad_id` | `text` | no |  |
| 2 | `day` | `date` | no |  |
| 3 | `revenue` | `numeric` | no | `0` |
| 4 | `new_revenue` | `numeric` | no | `0` |
| 5 | `orders` | `integer` | no | `0` |
| 6 | `refreshed_at` | `timestamp with time zone` | no | `now()` |

## Keys and indexes

- **Primary key** — `ad_revenue_daily_pkey`
  - `CREATE UNIQUE INDEX ad_revenue_daily_pkey ON public.ad_revenue_daily USING btree (ad_id, day)`
- Index — `ix_ard_day`: `CREATE INDEX ix_ard_day ON public.ad_revenue_daily USING btree (day) INCLUDE (ad_id, revenue, new_revenue)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `ad_id` → `ad_asset_map`, `ad_asset_recovered`, `ad_daily_external`, `ad_edit_log`, `ad_history_milestones`, `ad_insights`, `ad_lifecycle`, `ad_media`, `ad_metrics_external`, `ad_name_alias`, `ad_name_override`, `ad_performance_summary` … and 16 more

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
