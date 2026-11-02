# `ad_asset_recovered`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~59 rows (planner estimate) · 80 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `ad_id` | `text` | no |  |
| 2 | `asset_id` | `text` | no |  |
| 3 | `media` | `text` | no |  |
| 4 | `ad_name` | `text` | yes |  |
| 5 | `matched_form` | `text` | no |  |
| 6 | `canonical_form` | `text` | no |  |
| 7 | `recovered_at` | `timestamp with time zone` | no | `now()` |

## Keys and indexes

- **Primary key** — `ad_asset_recovered_pkey`
  - `CREATE UNIQUE INDEX ad_asset_recovered_pkey ON public.ad_asset_recovered USING btree (ad_id)`
- Index — `ix_ad_asset_recovered_asset`: `CREATE INDEX ix_ad_asset_recovered_asset ON public.ad_asset_recovered USING btree (asset_id)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `ad_id` → `ad_asset_map`, `ad_daily_external`, `ad_edit_log`, `ad_history_milestones`, `ad_insights`, `ad_lifecycle`, `ad_media`, `ad_metrics_external`, `ad_name_alias`, `ad_name_override`, `ad_performance_summary`, `ad_product_daily` … and 16 more
- `asset_id` → `ad_asset_map`, `content_asset_register`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
