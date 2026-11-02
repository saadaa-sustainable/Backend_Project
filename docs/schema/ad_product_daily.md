# `ad_product_daily`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · unknown rows (planner estimate) · 48 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `ad_id` | `text` | no |  |
| 2 | `day` | `date` | no |  |
| 3 | `product_id` | `text` | no |  |
| 4 | `product_name` | `text` | yes |  |
| 5 | `adset_id` | `text` | yes |  |
| 6 | `campaign_id` | `text` | yes |  |
| 7 | `account_id` | `text` | yes |  |
| 8 | `spend` | `numeric` | yes |  |
| 9 | `impressions` | `numeric` | yes |  |
| 10 | `clicks` | `numeric` | yes |  |
| 11 | `conv_value` | `numeric` | yes |  |
| 12 | `purchases` | `numeric` | yes |  |
| 13 | `ncp_count` | `numeric` | yes |  |
| 14 | `ftewv_count` | `numeric` | yes |  |
| 15 | `refreshed_at` | `timestamp with time zone` | yes | `now()` |

## Keys and indexes

- **Primary key** — `ad_product_daily_pkey`
  - `CREATE UNIQUE INDEX ad_product_daily_pkey ON public.ad_product_daily USING btree (ad_id, day, product_id)`
- Index — `ix_apd_account_day`: `CREATE INDEX ix_apd_account_day ON public.ad_product_daily USING btree (account_id, day)`
- Index — `ix_apd_ad_day`: `CREATE INDEX ix_apd_ad_day ON public.ad_product_daily USING btree (ad_id, day)`
- Index — `ix_apd_day`: `CREATE INDEX ix_apd_day ON public.ad_product_daily USING btree (day)`
- Index — `ix_apd_product_id`: `CREATE INDEX ix_apd_product_id ON public.ad_product_daily USING btree (product_id)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `account_id` → `ad_edit_log`, `ad_insights`, `ad_lifecycle`, `ad_performance_summary`, `ad_reach_cumulative`, `adset_insights`, `campaign_insights`, `meta_ads`, `meta_adsets`, `meta_campaigns`
- `ad_id` → `ad_asset_map`, `ad_asset_recovered`, `ad_daily_external`, `ad_edit_log`, `ad_history_milestones`, `ad_insights`, `ad_lifecycle`, `ad_media`, `ad_metrics_external`, `ad_name_alias`, `ad_name_override`, `ad_performance_summary` … and 16 more
- `adset_id` → `ad_edit_log`, `ad_insights`, `ad_lifecycle`, `ad_metrics_external`, `ad_name_override`, `ad_performance_summary`, `adset_insights`, `insights_daily_by_adset`, `meta_ad_attribution`, `meta_ads`, `meta_adsets`, `meta_direct_active_30d` … and 4 more
- `campaign_id` → `ad_insights`, `ad_lifecycle`, `ad_performance_summary`, `adset_insights`, `campaign_insights`, `content_influencer_posts`, `google_ad_groups`, `google_ads`, `google_ads_spend_daily`, `google_campaigns`, `insights_daily_by_campaign`, `meta_ads` … and 8 more

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
