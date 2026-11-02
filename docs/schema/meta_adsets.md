# `meta_adsets`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~3,762 rows (planner estimate) · 1416 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `adset_id` | `text` | no |  |
| 2 | `adset_name` | `text` | yes |  |
| 3 | `adset_status` | `text` | yes |  |
| 4 | `adset_effective_status` | `text` | yes |  |
| 5 | `campaign_id` | `text` | yes |  |
| 6 | `campaign_name` | `text` | yes |  |
| 7 | `account_id` | `text` | yes |  |
| 8 | `account_name` | `text` | yes |  |
| 9 | `billing_event` | `text` | yes |  |
| 10 | `optimization_goal` | `text` | yes |  |
| 11 | `destination_type` | `text` | yes |  |
| 12 | `daily_budget` | `numeric` | yes |  |
| 13 | `lifetime_budget` | `numeric` | yes |  |
| 14 | `budget_remaining` | `numeric` | yes |  |
| 15 | `bid_amount` | `numeric` | yes |  |
| 16 | `bid_strategy` | `text` | yes |  |
| 17 | `start_time` | `timestamp with time zone` | yes |  |
| 18 | `end_time` | `timestamp with time zone` | yes |  |
| 19 | `created_time` | `timestamp with time zone` | yes |  |
| 20 | `updated_time` | `timestamp with time zone` | yes |  |
| 21 | `updated_at` | `timestamp with time zone` | yes |  |

## Keys and indexes

- **Primary key** — `meta_adsets_pkey`
  - `CREATE UNIQUE INDEX meta_adsets_pkey ON public.meta_adsets USING btree (adset_id)`
- Index — `ix_meta_adsets_account_name`: `CREATE INDEX ix_meta_adsets_account_name ON public.meta_adsets USING btree (account_name)`
- Index — `ix_meta_adsets_campaign_id`: `CREATE INDEX ix_meta_adsets_campaign_id ON public.meta_adsets USING btree (campaign_id)`
- Index — `ix_meta_adsets_status`: `CREATE INDEX ix_meta_adsets_status ON public.meta_adsets USING btree (adset_status)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `account_id` → `ad_edit_log`, `ad_insights`, `ad_lifecycle`, `ad_performance_summary`, `ad_product_daily`, `ad_reach_cumulative`, `adset_insights`, `campaign_insights`, `meta_ads`, `meta_campaigns`
- `adset_id` → `ad_edit_log`, `ad_insights`, `ad_lifecycle`, `ad_metrics_external`, `ad_name_override`, `ad_performance_summary`, `ad_product_daily`, `adset_insights`, `insights_daily_by_adset`, `meta_ad_attribution`, `meta_ads`, `meta_direct_active_30d` … and 4 more
- `campaign_id` → `ad_insights`, `ad_lifecycle`, `ad_performance_summary`, `ad_product_daily`, `adset_insights`, `campaign_insights`, `content_influencer_posts`, `google_ad_groups`, `google_ads`, `google_ads_spend_daily`, `google_campaigns`, `insights_daily_by_campaign` … and 8 more

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
