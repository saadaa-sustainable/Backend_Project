# `ad_edit_log`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~114,882 rows (planner estimate) · 105 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `row_hash` | `text` | no |  |
| 2 | `account_id` | `text` | no |  |
| 3 | `account_name` | `text` | yes |  |
| 4 | `ad_id` | `text` | yes |  |
| 5 | `adset_id` | `text` | yes |  |
| 6 | `campaign_name` | `text` | yes |  |
| 7 | `object_name` | `text` | yes |  |
| 8 | `object_type` | `text` | yes |  |
| 9 | `event_time` | `timestamp with time zone` | no |  |
| 10 | `event_type` | `text` | yes |  |
| 11 | `translated_event_type` | `text` | yes |  |
| 12 | `actor_id` | `text` | yes |  |
| 13 | `actor_name` | `text` | yes |  |
| 14 | `extra_data` | `jsonb` | yes |  |
| 15 | `application_name` | `text` | yes |  |
| 16 | `date_time_in_timezone` | `text` | yes |  |
| 17 | `fetched_at` | `timestamp with time zone` | no |  |
| 18 | `ingested_at` | `timestamp with time zone` | no | `now()` |

## Keys and indexes

- **Primary key** — `ad_edit_log_pkey`
  - `CREATE UNIQUE INDEX ad_edit_log_pkey ON public.ad_edit_log USING btree (row_hash)`
- Index — `ix_ael_ad_id`: `CREATE INDEX ix_ael_ad_id ON public.ad_edit_log USING btree (ad_id)`
- Index — `ix_ael_adset_id`: `CREATE INDEX ix_ael_adset_id ON public.ad_edit_log USING btree (adset_id)`
- Index — `ix_ael_event_type`: `CREATE INDEX ix_ael_event_type ON public.ad_edit_log USING btree (event_type, event_time DESC)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `account_id` → `ad_insights`, `ad_lifecycle`, `ad_performance_summary`, `ad_product_daily`, `ad_reach_cumulative`, `adset_insights`, `campaign_insights`, `meta_ads`, `meta_adsets`, `meta_campaigns`
- `ad_id` → `ad_asset_map`, `ad_asset_recovered`, `ad_daily_external`, `ad_history_milestones`, `ad_insights`, `ad_lifecycle`, `ad_media`, `ad_metrics_external`, `ad_name_alias`, `ad_name_override`, `ad_performance_summary`, `ad_product_daily` … and 16 more
- `adset_id` → `ad_insights`, `ad_lifecycle`, `ad_metrics_external`, `ad_name_override`, `ad_performance_summary`, `ad_product_daily`, `adset_insights`, `insights_daily_by_adset`, `meta_ad_attribution`, `meta_ads`, `meta_adsets`, `meta_direct_active_30d` … and 4 more

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
