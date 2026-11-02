# `google_campaigns`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~192 rows (planner estimate) · 136 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `campaign_id` | `text` | no |  |
| 2 | `campaign_name` | `text` | yes |  |
| 3 | `campaign_status` | `text` | yes |  |
| 4 | `serving_status` | `text` | yes |  |
| 5 | `channel_type` | `text` | yes |  |
| 6 | `bid_strategy` | `text` | yes |  |
| 7 | `start_at` | `timestamp without time zone` | yes |  |
| 8 | `end_at` | `timestamp without time zone` | yes |  |
| 9 | `first_seen` | `timestamp with time zone` | yes |  |
| 10 | `snapshot_at` | `timestamp with time zone` | yes |  |
| 11 | `updated_at` | `timestamp with time zone` | yes |  |

## Keys and indexes

- **Primary key** — `google_campaigns_pkey`
  - `CREATE UNIQUE INDEX google_campaigns_pkey ON public.google_campaigns USING btree (campaign_id)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `campaign_id` → `ad_insights`, `ad_lifecycle`, `ad_performance_summary`, `ad_product_daily`, `adset_insights`, `campaign_insights`, `content_influencer_posts`, `google_ad_groups`, `google_ads`, `google_ads_spend_daily`, `insights_daily_by_campaign`, `meta_ads` … and 8 more

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
