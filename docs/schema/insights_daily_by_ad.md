# `insights_daily_by_ad`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~229,238 rows (planner estimate) · 386 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `ad_id` | `text` | no |  |
| 2 | `day` | `date` | no |  |
| 3 | `spend` | `numeric` | yes |  |
| 4 | `conv_value` | `numeric` | yes |  |
| 5 | `ncp_count` | `numeric` | yes |  |
| 6 | `impressions` | `numeric` | yes |  |
| 7 | `clicks` | `numeric` | yes |  |
| 8 | `refreshed_at` | `timestamp with time zone` | yes | `now()` |
| 9 | `ftewv_count` | `numeric` | yes |  |
| 10 | `purchases` | `numeric` | yes |  |
| 11 | `add_to_cart` | `numeric` | yes |  |
| 12 | `checkout_initiate` | `numeric` | yes |  |
| 13 | `thruplays` | `numeric` | yes |  |
| 14 | `three_sec_plays` | `numeric` | yes |  |
| 15 | `outbound_clicks` | `numeric` | yes |  |
| 16 | `post_engagements` | `numeric` | yes |  |
| 17 | `video_play_time` | `numeric` | yes |  |
| 18 | `reach` | `numeric` | yes |  |
| 19 | `all_clicks` | `numeric` | yes |  |

## Keys and indexes

- **Primary key** — `insights_daily_by_ad_pkey`
  - `CREATE UNIQUE INDEX insights_daily_by_ad_pkey ON public.insights_daily_by_ad USING btree (ad_id, day)`
- Index — `ix_idba_ad_day`: `CREATE INDEX ix_idba_ad_day ON public.insights_daily_by_ad USING btree (ad_id, day)`
- Index — `ix_idba_day`: `CREATE INDEX ix_idba_day ON public.insights_daily_by_ad USING btree (day)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `ad_id` → `ad_asset_map`, `ad_asset_recovered`, `ad_daily_external`, `ad_edit_log`, `ad_history_milestones`, `ad_insights`, `ad_lifecycle`, `ad_media`, `ad_metrics_external`, `ad_name_alias`, `ad_name_override`, `ad_performance_summary` … and 16 more

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
