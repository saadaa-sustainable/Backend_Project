# `ad_metrics_external`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~24,114 rows (planner estimate) · 10 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `ad_id` | `text` | no |  |
| 2 | `ad_name` | `text` | yes |  |
| 3 | `ad_status` | `text` | yes |  |
| 4 | `ad_created_time` | `timestamp with time zone` | yes |  |
| 5 | `account_name` | `text` | yes |  |
| 6 | `campaign_name` | `text` | yes |  |
| 7 | `adset_id` | `text` | yes |  |
| 8 | `adset_name` | `text` | yes |  |
| 9 | `spend` | `numeric` | yes |  |
| 10 | `impressions` | `numeric` | yes |  |
| 11 | `reach` | `numeric` | yes |  |
| 12 | `frequency` | `numeric` | yes |  |
| 13 | `conv_value` | `numeric` | yes |  |
| 14 | `purchases` | `numeric` | yes |  |
| 15 | `ncp_count` | `numeric` | yes |  |
| 16 | `ftewv_count` | `numeric` | yes |  |
| 17 | `cost_per_ncp` | `numeric` | yes |  |
| 18 | `cost_per_ftewv` | `numeric` | yes |  |
| 19 | `cpc_link` | `numeric` | yes |  |
| 20 | `ctr_pct` | `numeric` | yes |  |
| 21 | `cpr_1000` | `numeric` | yes |  |
| 22 | `checkout_compl_pct` | `numeric` | yes |  |
| 23 | `cr_lc_pct` | `numeric` | yes |  |
| 24 | `atc_lc_pct` | `numeric` | yes |  |
| 25 | `ci_atc_pct` | `numeric` | yes |  |
| 26 | `contrib_margin_pct` | `numeric` | yes |  |
| 27 | `profit_efficiency` | `numeric` | yes |  |
| 28 | `engagement_count` | `numeric` | yes |  |
| 29 | `inline_link_clicks` | `numeric` | yes |  |
| 30 | `add_to_cart` | `numeric` | yes |  |
| 31 | `checkout_initiate` | `numeric` | yes |  |
| 32 | `ltv_reach` | `numeric` | yes |  |
| 33 | `ltv_frequency` | `numeric` | yes |  |
| 34 | `pct_reach_ftewv` | `numeric` | yes |  |
| 35 | `f1_pass` | `boolean` | yes |  |
| 36 | `f2_pass` | `boolean` | yes |  |
| 37 | `f3_pass` | `boolean` | yes |  |
| 38 | `f4_pass` | `boolean` | yes |  |
| 39 | `category` | `text` | yes |  |
| 40 | `shopify_orders` | `numeric` | yes |  |
| 41 | `shopify_revenue` | `numeric` | yes |  |
| 42 | `shopify_aov` | `numeric` | yes |  |
| 43 | `shopify_roas` | `numeric` | yes |  |
| 44 | `impressions_50k_date` | `date` | yes |  |
| 45 | `days_to_50k` | `integer` | yes |  |
| 46 | `synced_at` | `timestamp with time zone` | yes |  |
| 47 | `first_seen_date` | `date` | yes |  |
| 48 | `date_of_result` | `date` | yes |  |
| 49 | `days_to_result` | `integer` | yes |  |

## Keys and indexes

- **Primary key** — `ad_metrics_external_pkey`
  - `CREATE UNIQUE INDEX ad_metrics_external_pkey ON public.ad_metrics_external USING btree (ad_id)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `ad_id` → `ad_asset_map`, `ad_asset_recovered`, `ad_daily_external`, `ad_edit_log`, `ad_history_milestones`, `ad_insights`, `ad_lifecycle`, `ad_media`, `ad_name_alias`, `ad_name_override`, `ad_performance_summary`, `ad_product_daily` … and 16 more
- `adset_id` → `ad_edit_log`, `ad_insights`, `ad_lifecycle`, `ad_name_override`, `ad_performance_summary`, `ad_product_daily`, `adset_insights`, `insights_daily_by_adset`, `meta_ad_attribution`, `meta_ads`, `meta_adsets`, `meta_direct_active_30d` … and 4 more
- `impressions_50k_date` → `ad_history_milestones`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
