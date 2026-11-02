# `meta_ads`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~24,978 rows (planner estimate) · 9488 kB

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
| 11 | `conversion_domain` | `text` | yes |  |
| 12 | `bid_amount` | `numeric` | yes |  |
| 13 | `created_time` | `timestamp with time zone` | yes |  |
| 14 | `updated_time` | `timestamp with time zone` | yes |  |
| 15 | `updated_at` | `timestamp with time zone` | yes |  |

## Keys and indexes

- **Primary key** — `meta_ads_pkey`
  - `CREATE UNIQUE INDEX meta_ads_pkey ON public.meta_ads USING btree (ad_id)`
- Index — `ix_meta_ads_account_name`: `CREATE INDEX ix_meta_ads_account_name ON public.meta_ads USING btree (account_name)`
- Index — `ix_meta_ads_adset_id`: `CREATE INDEX ix_meta_ads_adset_id ON public.meta_ads USING btree (adset_id)`
- Index — `ix_meta_ads_campaign_id`: `CREATE INDEX ix_meta_ads_campaign_id ON public.meta_ads USING btree (campaign_id)`
- Index — `ix_meta_ads_status`: `CREATE INDEX ix_meta_ads_status ON public.meta_ads USING btree (ad_status)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `account_id` → `ad_edit_log`, `ad_insights`, `ad_lifecycle`, `ad_performance_summary`, `ad_product_daily`, `ad_reach_cumulative`, `adset_insights`, `campaign_insights`, `meta_adsets`, `meta_campaigns`
- `ad_id` → `ad_asset_map`, `ad_asset_recovered`, `ad_daily_external`, `ad_edit_log`, `ad_history_milestones`, `ad_insights`, `ad_lifecycle`, `ad_media`, `ad_metrics_external`, `ad_name_alias`, `ad_name_override`, `ad_performance_summary` … and 16 more
- `adset_id` → `ad_edit_log`, `ad_insights`, `ad_lifecycle`, `ad_metrics_external`, `ad_name_override`, `ad_performance_summary`, `ad_product_daily`, `adset_insights`, `insights_daily_by_adset`, `meta_ad_attribution`, `meta_adsets`, `meta_direct_active_30d` … and 4 more
- `campaign_id` → `ad_insights`, `ad_lifecycle`, `ad_performance_summary`, `ad_product_daily`, `adset_insights`, `campaign_insights`, `content_influencer_posts`, `google_ad_groups`, `google_ads`, `google_ads_spend_daily`, `google_campaigns`, `insights_daily_by_campaign` … and 8 more

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
