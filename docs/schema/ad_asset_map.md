# `ad_asset_map`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~12,932 rows (planner estimate) · 4032 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `ad_id` | `text` | no |  |
| 2 | `ad_name` | `text` | yes |  |
| 3 | `asset_id` | `text` | no |  |
| 4 | `media` | `text` | no |  |
| 5 | `match_source` | `text` | no |  |
| 6 | `match_rank` | `smallint` | no |  |
| 7 | `asset_in_register` | `boolean` | no |  |
| 8 | `name_conflict` | `boolean` | no | `false` |
| 9 | `refreshed_at` | `timestamp with time zone` | no | `now()` |
| 10 | `ad_created_date` | `date` | yes |  |
| 11 | `account_name` | `text` | yes |  |
| 12 | `category` | `text` | yes |  |
| 13 | `spend` | `numeric` | yes |  |
| 14 | `impressions` | `numeric` | yes |  |
| 15 | `purchases` | `numeric` | yes |  |
| 16 | `conv_value` | `numeric` | yes |  |
| 17 | `ncp_count` | `numeric` | yes |  |
| 18 | `ftewv_count` | `numeric` | yes |  |
| 19 | `link_clicks` | `numeric` | yes |  |
| 20 | `thruplays` | `numeric` | yes |  |
| 21 | `three_sec_plays` | `numeric` | yes |  |
| 22 | `outbound_clicks` | `numeric` | yes |  |
| 23 | `post_engagements` | `numeric` | yes |  |

## Keys and indexes

- **Primary key** — `ad_asset_map_pkey`
  - `CREATE UNIQUE INDEX ad_asset_map_pkey ON public.ad_asset_map USING btree (ad_id)`
- Index — `ix_ad_asset_map_asset`: `CREATE INDEX ix_ad_asset_map_asset ON public.ad_asset_map USING btree (asset_id)`
- Index — `ix_ad_asset_map_created`: `CREATE INDEX ix_ad_asset_map_created ON public.ad_asset_map USING btree (ad_created_date)`
- Index — `ix_ad_asset_map_media_source`: `CREATE INDEX ix_ad_asset_map_media_source ON public.ad_asset_map USING btree (media, match_source)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `ad_created_date` → `ad_history_milestones`
- `ad_id` → `ad_asset_recovered`, `ad_daily_external`, `ad_edit_log`, `ad_history_milestones`, `ad_insights`, `ad_lifecycle`, `ad_media`, `ad_metrics_external`, `ad_name_alias`, `ad_name_override`, `ad_performance_summary`, `ad_product_daily` … and 16 more
- `asset_id` → `ad_asset_recovered`, `content_asset_register`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
