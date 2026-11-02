# `google_ad_groups`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~174 rows (planner estimate) · 128 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `ad_group_id` | `text` | no |  |
| 2 | `ad_group_name` | `text` | yes |  |
| 3 | `ad_group_status` | `text` | yes |  |
| 4 | `ad_group_type` | `text` | yes |  |
| 5 | `campaign_id` | `text` | yes |  |
| 6 | `campaign_name` | `text` | yes |  |
| 7 | `first_seen` | `timestamp with time zone` | yes |  |
| 8 | `snapshot_at` | `timestamp with time zone` | yes |  |
| 9 | `updated_at` | `timestamp with time zone` | yes |  |

## Keys and indexes

- **Primary key** — `google_ad_groups_pkey`
  - `CREATE UNIQUE INDEX google_ad_groups_pkey ON public.google_ad_groups USING btree (ad_group_id)`
- Index — `ix_google_ad_groups_campaign`: `CREATE INDEX ix_google_ad_groups_campaign ON public.google_ad_groups USING btree (campaign_id)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `ad_group_id` → `google_ads`
- `campaign_id` → `ad_insights`, `ad_lifecycle`, `ad_performance_summary`, `ad_product_daily`, `adset_insights`, `campaign_insights`, `content_influencer_posts`, `google_ads`, `google_ads_spend_daily`, `google_campaigns`, `insights_daily_by_campaign`, `meta_ads` … and 8 more

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
