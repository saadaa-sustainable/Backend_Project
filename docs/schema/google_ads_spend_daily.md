# `google_ads_spend_daily`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~9,051 rows (planner estimate) · 3784 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `day` | `date` | no |  |
| 2 | `campaign_id` | `text` | no |  |
| 3 | `campaign_name` | `text` | yes |  |
| 4 | `campaign_status` | `text` | yes |  |
| 5 | `channel_type` | `text` | yes |  |
| 6 | `spend` | `numeric` | no | `0` |
| 7 | `clicks` | `bigint` | no | `0` |
| 8 | `impressions` | `bigint` | no | `0` |
| 9 | `conversions` | `numeric` | no | `0` |
| 10 | `conv_value` | `numeric` | no | `0` |
| 11 | `fetched_at` | `timestamp with time zone` | no |  |
| 12 | `source` | `text` | no | `'maplemonk'::text` |
| 13 | `data_as_of` | `timestamp with time zone` | yes |  |

## Keys and indexes

- **Primary key** — `google_ads_spend_daily_pkey`
  - `CREATE UNIQUE INDEX google_ads_spend_daily_pkey ON public.google_ads_spend_daily USING btree (day, campaign_id)`
- Index — `ix_google_ads_spend_daily_day`: `CREATE INDEX ix_google_ads_spend_daily_day ON public.google_ads_spend_daily USING btree (day)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `campaign_id` → `ad_insights`, `ad_lifecycle`, `ad_performance_summary`, `ad_product_daily`, `adset_insights`, `campaign_insights`, `content_influencer_posts`, `google_ad_groups`, `google_ads`, `google_campaigns`, `insights_daily_by_campaign`, `meta_ads` … and 8 more

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
