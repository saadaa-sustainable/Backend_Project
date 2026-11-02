# `meta_direct_active_90d`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**materialized view** · ~1,624 rows (planner estimate) · 1856 kB

> One row per ACTIVE ad over the last 90 days of DATA. Shopify columns come from this project's corrected last-click attribution. reach_daily_sum is a SUM of daily reach and overcounts people; reach_unique_to_date is the de-duplicated figure.

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `account_name` | `text` | yes |  |
| 2 | `campaign_name` | `text` | yes |  |
| 3 | `campaign_id` | `text` | yes |  |
| 4 | `adset_id` | `text` | yes |  |
| 5 | `adset_name` | `text` | yes |  |
| 6 | `ad_id` | `text` | yes |  |
| 7 | `ad_name` | `text` | yes |  |
| 8 | `impressions` | `numeric` | yes |  |
| 9 | `reach_daily_sum` | `numeric` | yes |  |
| 10 | `reach_unique_to_date` | `bigint` | yes |  |
| 11 | `reach_since` | `date` | yes |  |
| 12 | `reach_as_of` | `date` | yes |  |
| 13 | `frequency` | `numeric` | yes |  |
| 14 | `spend` | `numeric` | yes |  |
| 15 | `link_clicks` | `numeric` | yes |  |
| 16 | `outbound_clicks` | `numeric` | yes |  |
| 17 | `all_clicks` | `numeric` | yes |  |
| 18 | `ctr` | `numeric` | yes |  |
| 19 | `cpc` | `numeric` | yes |  |
| 20 | `cpm` | `numeric` | yes |  |
| 21 | `purchases` | `numeric` | yes |  |
| 22 | `conv_value` | `numeric` | yes |  |
| 23 | `purchase_roas` | `numeric` | yes |  |
| 24 | `ci_count` | `numeric` | yes |  |
| 25 | `atc_count` | `numeric` | yes |  |
| 26 | `thruplays` | `numeric` | yes |  |
| 27 | `p100_plays` | `bigint` | yes |  |
| 28 | `ftewv_count` | `numeric` | yes |  |
| 29 | `ncp_count` | `numeric` | yes |  |
| 30 | `date_start` | `date` | yes |  |
| 31 | `date_stop` | `date` | yes |  |
| 32 | `ad_status` | `text` | yes |  |
| 33 | `ad_created` | `date` | yes |  |
| 34 | `shopify_orders` | `integer` | yes |  |
| 35 | `shopify_sales` | `numeric` | yes |  |
| 36 | `shopify_roas` | `numeric` | yes |  |
| 37 | `new_customers` | `integer` | yes |  |
| 38 | `repeat_customer_orders` | `integer` | yes |  |
| 39 | `repeat_customers` | `integer` | yes |  |
| 40 | `new_customer_sales` | `numeric` | yes |  |
| 41 | `repeat_customer_sales` | `numeric` | yes |  |
| 42 | `acq_mer` | `numeric` | yes |  |
| 43 | `matched_tier` | `text` | yes |  |
| 44 | `utm_content` | `text` | yes |  |
| 45 | `utm_term` | `text` | yes |  |
| 46 | `utm_campaign` | `text` | yes |  |
| 47 | `attribution_setting` | `text` | yes |  |

## Keys and indexes

- **No primary key.**
- Unique — `ux_mdir_active_90d`: `CREATE UNIQUE INDEX ux_mdir_active_90d ON public.meta_direct_active_90d USING btree (ad_id)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `ad_id` → `ad_asset_map`, `ad_asset_recovered`, `ad_daily_external`, `ad_edit_log`, `ad_history_milestones`, `ad_insights`, `ad_lifecycle`, `ad_media`, `ad_metrics_external`, `ad_name_alias`, `ad_name_override`, `ad_performance_summary` … and 16 more
- `adset_id` → `ad_edit_log`, `ad_insights`, `ad_lifecycle`, `ad_metrics_external`, `ad_name_override`, `ad_performance_summary`, `ad_product_daily`, `adset_insights`, `insights_daily_by_adset`, `meta_ad_attribution`, `meta_ads`, `meta_adsets` … and 4 more
- `campaign_id` → `ad_insights`, `ad_lifecycle`, `ad_performance_summary`, `ad_product_daily`, `adset_insights`, `campaign_insights`, `content_influencer_posts`, `google_ad_groups`, `google_ads`, `google_ads_spend_daily`, `google_campaigns`, `insights_daily_by_campaign` … and 8 more
- `reach_unique_to_date` → `meta_direct_active_30d`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
