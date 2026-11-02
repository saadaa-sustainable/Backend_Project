# `ad_performance_summary`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~24,115 rows (planner estimate) · 9824 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `ad_id` | `text` | no |  |
| 2 | `ad_name` | `text` | yes |  |
| 3 | `ad_status` | `text` | yes |  |
| 4 | `ad_effective_status` | `text` | yes |  |
| 5 | `adset_id` | `text` | yes |  |
| 6 | `adset_name` | `text` | yes |  |
| 7 | `campaign_id` | `text` | yes |  |
| 8 | `campaign_name` | `text` | yes |  |
| 9 | `account_id` | `text` | yes |  |
| 10 | `account_name` | `text` | yes |  |
| 11 | `category` | `text` | yes |  |
| 12 | `f1_pass` | `boolean` | yes |  |
| 13 | `f2_pass` | `boolean` | yes |  |
| 14 | `f3_pass` | `boolean` | yes |  |
| 15 | `f4_pass` | `boolean` | yes |  |
| 16 | `spend` | `numeric` | yes |  |
| 17 | `impressions` | `numeric` | yes |  |
| 18 | `purchases` | `numeric` | yes |  |
| 19 | `meta_conv_value` | `numeric` | yes |  |
| 20 | `meta_roas` | `numeric` | yes |  |
| 21 | `cost_per_purchase` | `numeric` | yes |  |
| 22 | `ctr_pct` | `numeric` | yes |  |
| 23 | `shopify_orders` | `numeric` | yes |  |
| 24 | `shopify_revenue` | `numeric` | yes |  |
| 25 | `shopify_aov` | `numeric` | yes |  |
| 26 | `shopify_roas` | `numeric` | yes |  |
| 27 | `cost_per_shopify_order` | `numeric` | yes |  |
| 28 | `gold_refreshed_at` | `timestamp with time zone` | yes |  |

## Keys and indexes

- **Primary key** — `ad_performance_summary_pkey`
  - `CREATE UNIQUE INDEX ad_performance_summary_pkey ON public.ad_performance_summary USING btree (ad_id)`
- Index — `ix_ad_performance_summary_account_name`: `CREATE INDEX ix_ad_performance_summary_account_name ON public.ad_performance_summary USING btree (account_name)`
- Index — `ix_ad_performance_summary_campaign_id`: `CREATE INDEX ix_ad_performance_summary_campaign_id ON public.ad_performance_summary USING btree (campaign_id)`
- Index — `ix_ad_performance_summary_category`: `CREATE INDEX ix_ad_performance_summary_category ON public.ad_performance_summary USING btree (category)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `account_id` → `ad_edit_log`, `ad_insights`, `ad_lifecycle`, `ad_product_daily`, `ad_reach_cumulative`, `adset_insights`, `campaign_insights`, `meta_ads`, `meta_adsets`, `meta_campaigns`
- `ad_id` → `ad_asset_map`, `ad_asset_recovered`, `ad_daily_external`, `ad_edit_log`, `ad_history_milestones`, `ad_insights`, `ad_lifecycle`, `ad_media`, `ad_metrics_external`, `ad_name_alias`, `ad_name_override`, `ad_product_daily` … and 16 more
- `adset_id` → `ad_edit_log`, `ad_insights`, `ad_lifecycle`, `ad_metrics_external`, `ad_name_override`, `ad_product_daily`, `adset_insights`, `insights_daily_by_adset`, `meta_ad_attribution`, `meta_ads`, `meta_adsets`, `meta_direct_active_30d` … and 4 more
- `campaign_id` → `ad_insights`, `ad_lifecycle`, `ad_product_daily`, `adset_insights`, `campaign_insights`, `content_influencer_posts`, `google_ad_groups`, `google_ads`, `google_ads_spend_daily`, `google_campaigns`, `insights_daily_by_campaign`, `meta_ads` … and 8 more

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
