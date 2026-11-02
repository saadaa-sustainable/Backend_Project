# `meta_direct_adset_30d`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**materialized view** · ~384 rows (planner estimate) · 440 kB

> One row per ad set over the last 30 days of DATA. Orders map through utm_term, the same mapping Ads Analyse uses. repeat_customers is DISTINCT people and must not be summed across rows; repeat_customer_orders is the additive column. d3/d7 ROAS is last-click revenue over spend across the same window, NULL when nothing was spent.

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `account_name` | `text` | yes |  |
| 2 | `campaign_id` | `text` | yes |  |
| 3 | `campaign_name` | `text` | yes |  |
| 4 | `adset_id` | `text` | yes |  |
| 5 | `adset_name` | `text` | yes |  |
| 6 | `adset_status` | `text` | yes |  |
| 7 | `impressions` | `numeric` | yes |  |
| 8 | `reach_daily_sum` | `numeric` | yes |  |
| 9 | `frequency` | `numeric` | yes |  |
| 10 | `spend` | `numeric` | yes |  |
| 11 | `link_clicks` | `numeric` | yes |  |
| 12 | `all_clicks` | `numeric` | yes |  |
| 13 | `ctr` | `numeric` | yes |  |
| 14 | `cpc` | `numeric` | yes |  |
| 15 | `cpm` | `numeric` | yes |  |
| 16 | `purchases` | `numeric` | yes |  |
| 17 | `conv_value` | `numeric` | yes |  |
| 18 | `purchase_roas` | `numeric` | yes |  |
| 19 | `ftewv_count` | `numeric` | yes |  |
| 20 | `shopify_orders` | `integer` | yes |  |
| 21 | `shopify_sales` | `numeric` | yes |  |
| 22 | `shopify_roas` | `numeric` | yes |  |
| 23 | `new_customers` | `integer` | yes |  |
| 24 | `repeat_customer_orders` | `integer` | yes |  |
| 25 | `repeat_customers` | `integer` | yes |  |
| 26 | `new_customer_sales` | `numeric` | yes |  |
| 27 | `repeat_customer_sales` | `numeric` | yes |  |
| 28 | `acq_mer` | `numeric` | yes |  |
| 29 | `d3_spend` | `numeric` | yes |  |
| 30 | `d3_lc_revenue` | `numeric` | yes |  |
| 31 | `d3_lc_roas` | `numeric` | yes |  |
| 32 | `d7_spend` | `numeric` | yes |  |
| 33 | `d7_lc_revenue` | `numeric` | yes |  |
| 34 | `d7_lc_roas` | `numeric` | yes |  |
| 35 | `date_start` | `date` | yes |  |
| 36 | `date_stop` | `date` | yes |  |
| 37 | `attribution_setting` | `text` | yes |  |

## Keys and indexes

- **No primary key.**
- Unique — `ux_mdir_adset_30d`: `CREATE UNIQUE INDEX ux_mdir_adset_30d ON public.meta_direct_adset_30d USING btree (adset_id)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `adset_id` → `ad_edit_log`, `ad_insights`, `ad_lifecycle`, `ad_metrics_external`, `ad_name_override`, `ad_performance_summary`, `ad_product_daily`, `adset_insights`, `insights_daily_by_adset`, `meta_ad_attribution`, `meta_ads`, `meta_adsets` … and 4 more
- `campaign_id` → `ad_insights`, `ad_lifecycle`, `ad_performance_summary`, `ad_product_daily`, `adset_insights`, `campaign_insights`, `content_influencer_posts`, `google_ad_groups`, `google_ads`, `google_ads_spend_daily`, `google_campaigns`, `insights_daily_by_campaign` … and 8 more

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
