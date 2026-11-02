# `content_asset_register`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~1,133 rows (planner estimate) · 1376 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `seq` | `integer` | yes |  |
| 2 | `asset_id` | `text` | no |  |
| 3 | `source_parent` | `text` | yes |  |
| 4 | `asset_type` | `text` | yes |  |
| 5 | `category` | `text` | yes |  |
| 6 | `planning_nomenclature` | `text` | yes |  |
| 7 | `link_to_asset` | `text` | yes |  |
| 8 | `origin` | `text` | yes |  |
| 9 | `creative_effort_type` | `text` | yes |  |
| 10 | `type_of_content` | `text` | yes |  |
| 11 | `date_of_production` | `date` | yes |  |
| 12 | `date_testing_ads` | `date` | yes |  |
| 13 | `date_testing_posting_ig` | `date` | yes |  |
| 14 | `ad_id` | `text` | yes |  |
| 15 | `is_test` | `boolean` | yes |  |
| 16 | `created_at` | `timestamp with time zone` | yes |  |
| 17 | `source` | `text` | yes |  |
| 18 | `ads_name` | `text` | yes |  |
| 19 | `ads_result` | `text` | yes |  |
| 20 | `ads_status` | `text` | yes |  |
| 21 | `ads_count` | `integer` | yes |  |
| 22 | `ads_impressions` | `bigint` | yes |  |
| 23 | `ads_spend` | `numeric` | yes |  |
| 24 | `ads_conv_value` | `numeric` | yes |  |
| 25 | `ads_roas` | `numeric` | yes |  |
| 26 | `ads_ncp` | `integer` | yes |  |
| 27 | `ads_cost_per_ncp` | `numeric` | yes |  |
| 28 | `ads_ftewv` | `integer` | yes |  |
| 29 | `ads_cost_per_ftewv` | `numeric` | yes |  |
| 30 | `ads_purchases` | `integer` | yes |  |
| 31 | `ads_shopify_orders` | `integer` | yes |  |
| 32 | `ads_shopify_sales` | `numeric` | yes |  |
| 33 | `ads_shopify_aov` | `numeric` | yes |  |
| 34 | `ads_shopify_roas` | `numeric` | yes |  |
| 35 | `ads_synced_at` | `timestamp with time zone` | yes |  |
| 36 | `ads_testing_status` | `text` | yes |  |
| 37 | `ads_instagram_posted` | `text` | yes |  |
| 38 | `ads_instagram_permalink` | `text` | yes |  |
| 39 | `ads_reach` | `bigint` | yes |  |
| 40 | `ads_ctr` | `numeric` | yes |  |
| 41 | `ads_hook_rate` | `numeric` | yes |  |
| 42 | `ads_hold_rate` | `numeric` | yes |  |
| 43 | `ads_thruplay_rate` | `numeric` | yes |  |
| 44 | `mirrored_at` | `timestamp with time zone` | yes |  |
| 45 | `brief_shoot_required` | `text` | yes |  |
| 46 | `brief_aspect_ratio` | `text` | yes |  |
| 47 | `computed_is_tested` | `boolean` | yes |  |
| 48 | `matched_ad_id` | `text` | yes |  |
| 49 | `matched_ad_name` | `text` | yes |  |
| 50 | `ingested_from_ctd_at` | `timestamp with time zone` | no | `now()` |
| 51 | `source_ad_id` | `text` | yes |  |
| 52 | `source_ad_name` | `text` | yes |  |
| 53 | `source_testing_status` | `text` | yes |  |

## Keys and indexes

- **Primary key** — `content_asset_register_pkey`
  - `CREATE UNIQUE INDEX content_asset_register_pkey ON public.content_asset_register USING btree (asset_id)`
- Index — `idx_car_ad_id`: `CREATE INDEX idx_car_ad_id ON public.content_asset_register USING btree (ad_id)`
- Index — `idx_car_computed_is_tested`: `CREATE INDEX idx_car_computed_is_tested ON public.content_asset_register USING btree (computed_is_tested)`
- Index — `idx_car_matched_ad_id`: `CREATE INDEX idx_car_matched_ad_id ON public.content_asset_register USING btree (matched_ad_id) WHERE (matched_ad_id IS NOT NULL)`
- Index — `idx_car_planning_prefix`: `CREATE INDEX idx_car_planning_prefix ON public.content_asset_register USING btree (split_part(planning_nomenclature, '_'::text, 1))`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `ad_id` → `ad_asset_map`, `ad_asset_recovered`, `ad_daily_external`, `ad_edit_log`, `ad_history_milestones`, `ad_insights`, `ad_lifecycle`, `ad_media`, `ad_metrics_external`, `ad_name_alias`, `ad_name_override`, `ad_performance_summary` … and 16 more
- `asset_id` → `ad_asset_map`, `ad_asset_recovered`
- `matched_ad_id` → `content_graphic_register`, `content_influencer_posts`, `shopify_order_attribution`
- `source_ad_id` → `content_edited_content`, `content_graphic_register`, `content_iterated_register`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
