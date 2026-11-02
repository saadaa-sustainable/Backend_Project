# `ad_thumbnails`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~16,583 rows (planner estimate) · 41 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `ad_id` | `text` | no |  |
| 2 | `thumbnail_url` | `text` | yes |  |
| 3 | `image_url` | `text` | yes |  |
| 4 | `creative_id` | `text` | yes |  |
| 5 | `object_type` | `text` | yes |  |
| 6 | `video_id` | `text` | yes |  |
| 7 | `fetched_at` | `timestamp with time zone` | yes |  |
| 8 | `last_error` | `text` | yes |  |
| 9 | `instagram_permalink` | `text` | yes |  |
| 10 | `fb_permalink` | `text` | yes |  |
| 11 | `video_source_url` | `text` | yes |  |
| 12 | `video_source_fetched_at` | `timestamp with time zone` | yes |  |
| 13 | `destination_url` | `text` | yes |  |
| 14 | `linked_urls` | `text[]` | yes |  |
| 15 | `destination_fetched_at` | `timestamp with time zone` | yes |  |
| 16 | `destination_error` | `text` | yes |  |
| 17 | `ingested_from_ctd_at` | `timestamp with time zone` | no | `now()` |

## Keys and indexes

- **Primary key** — `ad_thumbnails_pkey`
  - `CREATE UNIQUE INDEX ad_thumbnails_pkey ON public.ad_thumbnails USING btree (ad_id)`
- Index — `idx_ad_thumbnails_ig`: `CREATE INDEX idx_ad_thumbnails_ig ON public.ad_thumbnails USING btree (ad_id) WHERE (instagram_permalink IS NOT NULL)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `ad_id` → `ad_asset_map`, `ad_asset_recovered`, `ad_daily_external`, `ad_edit_log`, `ad_history_milestones`, `ad_insights`, `ad_lifecycle`, `ad_media`, `ad_metrics_external`, `ad_name_alias`, `ad_name_override`, `ad_performance_summary` … and 16 more
- `creative_id` → `ad_media`
- `video_id` → `ad_media`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
