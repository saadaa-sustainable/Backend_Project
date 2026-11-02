# `ad_name_alias`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~2,995 rows (planner estimate) · 976 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `ad_name_lower` | `text` | no |  |
| 2 | `ad_id` | `text` | no |  |
| 3 | `source` | `text` | no |  |
| 4 | `ambiguous` | `boolean` | no | `false` |
| 5 | `refreshed_at` | `timestamp with time zone` | no | `now()` |

## Keys and indexes

- **Primary key** — `ad_name_alias_pkey`
  - `CREATE UNIQUE INDEX ad_name_alias_pkey ON public.ad_name_alias USING btree (ad_name_lower, ad_id)`
- Index — `ix_ad_name_alias_ad_id`: `CREATE INDEX ix_ad_name_alias_ad_id ON public.ad_name_alias USING btree (ad_id)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `ad_id` → `ad_asset_map`, `ad_asset_recovered`, `ad_daily_external`, `ad_edit_log`, `ad_history_milestones`, `ad_insights`, `ad_lifecycle`, `ad_media`, `ad_metrics_external`, `ad_name_override`, `ad_performance_summary`, `ad_product_daily` … and 16 more

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
