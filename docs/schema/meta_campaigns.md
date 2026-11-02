# `meta_campaigns`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~679 rows (planner estimate) · 256 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `campaign_id` | `text` | no |  |
| 2 | `campaign_name` | `text` | yes |  |
| 3 | `campaign_status` | `text` | yes |  |
| 4 | `campaign_effective_status` | `text` | yes |  |
| 5 | `account_id` | `text` | yes |  |
| 6 | `account_name` | `text` | yes |  |
| 7 | `objective` | `text` | yes |  |
| 8 | `buying_type` | `text` | yes |  |
| 9 | `smart_promotion_type` | `text` | yes |  |
| 10 | `daily_budget` | `numeric` | yes |  |
| 11 | `lifetime_budget` | `numeric` | yes |  |
| 12 | `budget_remaining` | `numeric` | yes |  |
| 13 | `spend_cap` | `numeric` | yes |  |
| 14 | `bid_strategy` | `text` | yes |  |
| 15 | `start_time` | `timestamp with time zone` | yes |  |
| 16 | `stop_time` | `timestamp with time zone` | yes |  |
| 17 | `created_time` | `timestamp with time zone` | yes |  |
| 18 | `updated_time` | `timestamp with time zone` | yes |  |
| 19 | `updated_at` | `timestamp with time zone` | yes |  |

## Keys and indexes

- **Primary key** — `meta_campaigns_pkey`
  - `CREATE UNIQUE INDEX meta_campaigns_pkey ON public.meta_campaigns USING btree (campaign_id)`
- Index — `ix_meta_campaigns_account_name`: `CREATE INDEX ix_meta_campaigns_account_name ON public.meta_campaigns USING btree (account_name)`
- Index — `ix_meta_campaigns_status`: `CREATE INDEX ix_meta_campaigns_status ON public.meta_campaigns USING btree (campaign_status)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `account_id` → `ad_edit_log`, `ad_insights`, `ad_lifecycle`, `ad_performance_summary`, `ad_product_daily`, `ad_reach_cumulative`, `adset_insights`, `campaign_insights`, `meta_ads`, `meta_adsets`
- `campaign_id` → `ad_insights`, `ad_lifecycle`, `ad_performance_summary`, `ad_product_daily`, `adset_insights`, `campaign_insights`, `content_influencer_posts`, `google_ad_groups`, `google_ads`, `google_ads_spend_daily`, `google_campaigns`, `insights_daily_by_campaign` … and 8 more

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
