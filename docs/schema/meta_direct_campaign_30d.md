# `meta_direct_campaign_30d`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**materialized view** · ~112 rows (planner estimate) · 128 kB

> One row per campaign over the last 30 days of DATA. Orders map through matched_campaign_id, the same mapping Ads Analyse uses. repeat_customers is DISTINCT people and must not be summed across rows. d3/d7 ROAS is last-click revenue over spend across the same window, NULL when nothing was spent.

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `account_name` | `text` | yes |  |
| 2 | `campaign_id` | `text` | yes |  |
| 3 | `campaign_name` | `text` | yes |  |
| 4 | `campaign_status` | `text` | yes |  |
| 5 | `objective` | `text` | yes |  |
| 6 | `impressions` | `numeric` | yes |  |
| 7 | `reach_daily_sum` | `numeric` | yes |  |
| 8 | `frequency` | `numeric` | yes |  |
| 9 | `spend` | `numeric` | yes |  |
| 10 | `link_clicks` | `numeric` | yes |  |
| 11 | `all_clicks` | `numeric` | yes |  |
| 12 | `ctr` | `numeric` | yes |  |
| 13 | `cpc` | `numeric` | yes |  |
| 14 | `cpm` | `numeric` | yes |  |
| 15 | `purchases` | `numeric` | yes |  |
| 16 | `conv_value` | `numeric` | yes |  |
| 17 | `purchase_roas` | `numeric` | yes |  |
| 18 | `ftewv_count` | `numeric` | yes |  |
| 19 | `shopify_orders` | `integer` | yes |  |
| 20 | `shopify_sales` | `numeric` | yes |  |
| 21 | `shopify_roas` | `numeric` | yes |  |
| 22 | `new_customers` | `integer` | yes |  |
| 23 | `repeat_customer_orders` | `integer` | yes |  |
| 24 | `repeat_customers` | `integer` | yes |  |
| 25 | `new_customer_sales` | `numeric` | yes |  |
| 26 | `repeat_customer_sales` | `numeric` | yes |  |
| 27 | `acq_mer` | `numeric` | yes |  |
| 28 | `d3_spend` | `numeric` | yes |  |
| 29 | `d3_lc_revenue` | `numeric` | yes |  |
| 30 | `d3_lc_roas` | `numeric` | yes |  |
| 31 | `d7_spend` | `numeric` | yes |  |
| 32 | `d7_lc_revenue` | `numeric` | yes |  |
| 33 | `d7_lc_roas` | `numeric` | yes |  |
| 34 | `date_start` | `date` | yes |  |
| 35 | `date_stop` | `date` | yes |  |
| 36 | `attribution_setting` | `text` | yes |  |

## Keys and indexes

- **No primary key.**
- Unique — `ux_mdir_campaign_30d`: `CREATE UNIQUE INDEX ux_mdir_campaign_30d ON public.meta_direct_campaign_30d USING btree (campaign_id)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `campaign_id` → `ad_insights`, `ad_lifecycle`, `ad_performance_summary`, `ad_product_daily`, `adset_insights`, `campaign_insights`, `content_influencer_posts`, `google_ad_groups`, `google_ads`, `google_ads_spend_daily`, `google_campaigns`, `insights_daily_by_campaign` … and 8 more

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
