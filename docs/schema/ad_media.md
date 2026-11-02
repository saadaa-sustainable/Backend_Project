# `ad_media`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~24,978 rows (planner estimate) · 8712 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `ad_id` | `text` | no |  |
| 2 | `creative_id` | `text` | yes |  |
| 3 | `thumbnail_url` | `text` | yes |  |
| 4 | `video_url` | `text` | yes |  |
| 5 | `video_id` | `text` | yes |  |
| 6 | `landing_page_url` | `text` | yes |  |
| 7 | `link_display_url` | `text` | yes |  |
| 8 | `is_video` | `boolean` | no | `false` |
| 9 | `refreshed_at` | `timestamp with time zone` | yes | `now()` |
| 10 | `effective_object_story_id` | `text` | yes |  |
| 11 | `landing_page_source` | `text` | yes |  |

## Keys and indexes

- **Primary key** — `ad_media_pkey`
  - `CREATE UNIQUE INDEX ad_media_pkey ON public.ad_media USING btree (ad_id)`
- Index — `ix_ad_media_landing_missing`: `CREATE INDEX ix_ad_media_landing_missing ON public.ad_media USING btree (ad_id) WHERE (landing_page_url IS NULL)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `ad_id` → `ad_asset_map`, `ad_asset_recovered`, `ad_daily_external`, `ad_edit_log`, `ad_history_milestones`, `ad_insights`, `ad_lifecycle`, `ad_metrics_external`, `ad_name_alias`, `ad_name_override`, `ad_performance_summary`, `ad_product_daily` … and 16 more
- `creative_id` → `ad_thumbnails`
- `video_id` → `ad_thumbnails`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
