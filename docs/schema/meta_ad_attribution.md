# `meta_ad_attribution`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~14,061 rows (planner estimate) · 3936 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `ad_id` | `text` | no |  |
| 2 | `adset_id` | `text` | yes |  |
| 3 | `ad_name` | `text` | yes |  |
| 4 | `adset_name` | `text` | yes |  |
| 5 | `attribution_setting` | `text` | no |  |
| 6 | `attribution_label` | `text` | no |  |
| 7 | `source_file` | `text` | no |  |
| 8 | `loaded_at` | `timestamp with time zone` | no | `now()` |

## Keys and indexes

- **Primary key** — `meta_ad_attribution_pkey`
  - `CREATE UNIQUE INDEX meta_ad_attribution_pkey ON public.meta_ad_attribution USING btree (ad_id)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `ad_id` → `ad_asset_map`, `ad_asset_recovered`, `ad_daily_external`, `ad_edit_log`, `ad_history_milestones`, `ad_insights`, `ad_lifecycle`, `ad_media`, `ad_metrics_external`, `ad_name_alias`, `ad_name_override`, `ad_performance_summary` … and 16 more
- `adset_id` → `ad_edit_log`, `ad_insights`, `ad_lifecycle`, `ad_metrics_external`, `ad_name_override`, `ad_performance_summary`, `ad_product_daily`, `adset_insights`, `insights_daily_by_adset`, `meta_ads`, `meta_adsets`, `meta_direct_active_30d` … and 4 more

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
