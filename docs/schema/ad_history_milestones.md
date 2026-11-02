# `ad_history_milestones`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~24,115 rows (planner estimate) · 4488 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `ad_id` | `text` | no |  |
| 2 | `ad_created_date` | `date` | yes |  |
| 3 | `category_at_day_14` | `text` | yes |  |
| 4 | `day_14_date` | `date` | yes |  |
| 5 | `impressions_at_day_14` | `numeric` | yes |  |
| 6 | `spend_at_day_14` | `numeric` | yes |  |
| 7 | `conv_value_at_day_14` | `numeric` | yes |  |
| 8 | `ncp_at_day_14` | `numeric` | yes |  |
| 9 | `ftewv_at_day_14` | `numeric` | yes |  |
| 10 | `roas_at_day_14` | `numeric` | yes |  |
| 11 | `f1_at_day_14` | `boolean` | yes |  |
| 12 | `f2_at_day_14` | `boolean` | yes |  |
| 13 | `f3_at_day_14` | `boolean` | yes |  |
| 14 | `f4_at_day_14` | `boolean` | yes |  |
| 15 | `history_status` | `text` | no |  |
| 16 | `impressions_50k_date` | `date` | yes |  |
| 17 | `days_to_50k` | `integer` | yes |  |
| 18 | `computed_at` | `timestamp with time zone` | yes |  |

## Keys and indexes

- **Primary key** — `ad_history_milestones_pkey`
  - `CREATE UNIQUE INDEX ad_history_milestones_pkey ON public.ad_history_milestones USING btree (ad_id)`
- Index — `ix_ahm_50k`: `CREATE INDEX ix_ahm_50k ON public.ad_history_milestones USING btree (impressions_50k_date)`
- Index — `ix_ahm_cat14`: `CREATE INDEX ix_ahm_cat14 ON public.ad_history_milestones USING btree (category_at_day_14)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `ad_created_date` → `ad_asset_map`
- `ad_id` → `ad_asset_map`, `ad_asset_recovered`, `ad_daily_external`, `ad_edit_log`, `ad_insights`, `ad_lifecycle`, `ad_media`, `ad_metrics_external`, `ad_name_alias`, `ad_name_override`, `ad_performance_summary`, `ad_product_daily` … and 16 more
- `impressions_50k_date` → `ad_metrics_external`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
