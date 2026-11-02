# `google_ads`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~440 rows (planner estimate) · 368 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `ad_id` | `text` | no |  |
| 2 | `ad_name` | `text` | yes |  |
| 3 | `ad_label` | `text` | no |  |
| 4 | `ad_status` | `text` | yes |  |
| 5 | `ad_type` | `text` | yes |  |
| 6 | `ad_group_id` | `text` | yes |  |
| 7 | `ad_group_name` | `text` | yes |  |
| 8 | `campaign_id` | `text` | yes |  |
| 9 | `campaign_name` | `text` | yes |  |
| 10 | `first_seen` | `timestamp with time zone` | yes |  |
| 11 | `snapshot_at` | `timestamp with time zone` | yes |  |
| 12 | `updated_at` | `timestamp with time zone` | yes |  |

## Keys and indexes

- **Primary key** — `google_ads_pkey`
  - `CREATE UNIQUE INDEX google_ads_pkey ON public.google_ads USING btree (ad_id)`
- Index — `ix_google_ads_ad_group`: `CREATE INDEX ix_google_ads_ad_group ON public.google_ads USING btree (ad_group_id)`
- Index — `ix_google_ads_campaign`: `CREATE INDEX ix_google_ads_campaign ON public.google_ads USING btree (campaign_id)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `ad_group_id` → `google_ad_groups`
- `ad_id` → `ad_asset_map`, `ad_asset_recovered`, `ad_daily_external`, `ad_edit_log`, `ad_history_milestones`, `ad_insights`, `ad_lifecycle`, `ad_media`, `ad_metrics_external`, `ad_name_alias`, `ad_name_override`, `ad_performance_summary` … and 16 more
- `campaign_id` → `ad_insights`, `ad_lifecycle`, `ad_performance_summary`, `ad_product_daily`, `adset_insights`, `campaign_insights`, `content_influencer_posts`, `google_ad_groups`, `google_ads_spend_daily`, `google_campaigns`, `insights_daily_by_campaign`, `meta_ads` … and 8 more

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
