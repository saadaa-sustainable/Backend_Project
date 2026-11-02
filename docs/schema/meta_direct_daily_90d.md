# `meta_direct_daily_90d`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**materialized view** · ~71,302 rows (planner estimate) · 61 MB

> One row per ad per day over the last 90 days of DATA. Shopify columns come from this project's corrected last-click attribution.

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `date` | `date` | yes |  |
| 2 | `account_name` | `text` | yes |  |
| 3 | `campaign_name` | `text` | yes |  |
| 4 | `campaign_id` | `text` | yes |  |
| 5 | `adset_id` | `text` | yes |  |
| 6 | `adset_name` | `text` | yes |  |
| 7 | `ad_id` | `text` | yes |  |
| 8 | `ad_name` | `text` | yes |  |
| 9 | `impressions` | `numeric` | yes |  |
| 10 | `reach` | `numeric` | yes |  |
| 11 | `frequency` | `numeric` | yes |  |
| 12 | `spend` | `numeric` | yes |  |
| 13 | `link_clicks` | `numeric` | yes |  |
| 14 | `outbound_clicks` | `numeric` | yes |  |
| 15 | `all_clicks` | `bigint` | yes |  |
| 16 | `ctr` | `numeric` | yes |  |
| 17 | `cpc` | `numeric` | yes |  |
| 18 | `cpm` | `numeric` | yes |  |
| 19 | `purchases` | `numeric` | yes |  |
| 20 | `conv_value` | `numeric` | yes |  |
| 21 | `purchase_roas` | `numeric` | yes |  |
| 22 | `ci_count` | `numeric` | yes |  |
| 23 | `atc_count` | `numeric` | yes |  |
| 24 | `thruplays` | `numeric` | yes |  |
| 25 | `p100_plays` | `bigint` | yes |  |
| 26 | `ftewv_count` | `numeric` | yes |  |
| 27 | `ncp_count` | `numeric` | yes |  |
| 28 | `ad_status` | `text` | yes |  |
| 29 | `ad_created` | `date` | yes |  |
| 30 | `shopify_orders` | `integer` | yes |  |
| 31 | `shopify_sales` | `numeric` | yes |  |
| 32 | `shopify_roas` | `numeric` | yes |  |
| 33 | `new_customers` | `integer` | yes |  |
| 34 | `repeat_customer_orders` | `integer` | yes |  |
| 35 | `repeat_customers` | `integer` | yes |  |
| 36 | `new_customer_sales` | `numeric` | yes |  |
| 37 | `repeat_customer_sales` | `numeric` | yes |  |
| 38 | `acq_mer` | `numeric` | yes |  |
| 39 | `matched_tier` | `text` | yes |  |
| 40 | `utm_content` | `text` | yes |  |
| 41 | `utm_term` | `text` | yes |  |
| 42 | `utm_campaign` | `text` | yes |  |
| 43 | `attribution_setting` | `text` | yes |  |

## Keys and indexes

- **No primary key.**
- Unique — `ux_mdir_daily_90d`: `CREATE UNIQUE INDEX ux_mdir_daily_90d ON public.meta_direct_daily_90d USING btree (ad_id, date)`
- Index — `ix_mdir_daily_90d_date`: `CREATE INDEX ix_mdir_daily_90d_date ON public.meta_direct_daily_90d USING btree (date)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `ad_id` → `ad_asset_map`, `ad_asset_recovered`, `ad_daily_external`, `ad_edit_log`, `ad_history_milestones`, `ad_insights`, `ad_lifecycle`, `ad_media`, `ad_metrics_external`, `ad_name_alias`, `ad_name_override`, `ad_performance_summary` … and 16 more
- `adset_id` → `ad_edit_log`, `ad_insights`, `ad_lifecycle`, `ad_metrics_external`, `ad_name_override`, `ad_performance_summary`, `ad_product_daily`, `adset_insights`, `insights_daily_by_adset`, `meta_ad_attribution`, `meta_ads`, `meta_adsets` … and 4 more
- `campaign_id` → `ad_insights`, `ad_lifecycle`, `ad_performance_summary`, `ad_product_daily`, `adset_insights`, `campaign_insights`, `content_influencer_posts`, `google_ad_groups`, `google_ads`, `google_ads_spend_daily`, `google_campaigns`, `insights_daily_by_campaign` … and 8 more

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
