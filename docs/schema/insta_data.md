# `insta_data`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~1,522 rows (planner estimate) · 3272 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `id` | `uuid` | yes |  |
| 2 | `source_id` | `character varying(64)` | yes |  |
| 3 | `object_type` | `character varying(64)` | yes |  |
| 4 | `account_key` | `text` | yes |  |
| 5 | `ig_user_id` | `text` | yes |  |
| 6 | `extracted_at` | `timestamp with time zone` | yes |  |
| 7 | `ingested_at` | `timestamp with time zone` | yes |  |
| 8 | `ig_object_id` | `text` | yes |  |
| 9 | `media_id` | `text` | yes |  |
| 10 | `media_owner_username` | `text` | yes |  |
| 11 | `username` | `text` | yes |  |
| 12 | `name` | `text` | yes |  |
| 13 | `caption` | `text` | yes |  |
| 14 | `media_url` | `text` | yes |  |
| 15 | `media_type` | `text` | yes |  |
| 16 | `media_product_type` | `text` | yes |  |
| 17 | `media_audio_type` | `text` | yes |  |
| 18 | `permalink` | `text` | yes |  |
| 19 | `shortcode` | `text` | yes |  |
| 20 | `thumbnail_url` | `text` | yes |  |
| 21 | `legacy_instagram_media_id` | `text` | yes |  |
| 22 | `posted_at` | `timestamp with time zone` | yes |  |
| 23 | `is_comment_enabled` | `boolean` | yes |  |
| 24 | `is_shared_to_feed` | `boolean` | yes |  |
| 25 | `is_ai_generated` | `boolean` | yes |  |
| 26 | `biography` | `text` | yes |  |
| 27 | `website` | `text` | yes |  |
| 28 | `profile_picture_url` | `text` | yes |  |
| 29 | `followers_count` | `numeric` | yes |  |
| 30 | `follows_count` | `numeric` | yes |  |
| 31 | `media_count` | `numeric` | yes |  |
| 32 | `has_profile_pic` | `boolean` | yes |  |
| 33 | `is_published` | `boolean` | yes |  |
| 34 | `like_count` | `numeric` | yes |  |
| 35 | `comments_count` | `numeric` | yes |  |
| 36 | `total_like_count` | `numeric` | yes |  |
| 37 | `total_comments_count` | `numeric` | yes |  |
| 38 | `total_views_count` | `numeric` | yes |  |
| 39 | `saved_count` | `numeric` | yes |  |
| 40 | `shares_count` | `numeric` | yes |  |
| 41 | `reposts_count` | `numeric` | yes |  |
| 42 | `insights_reach` | `numeric` | yes |  |
| 43 | `insights_views` | `numeric` | yes |  |
| 44 | `avg_watch_time_ms` | `numeric` | yes |  |
| 45 | `total_watch_time_ms` | `numeric` | yes |  |
| 46 | `reels_skip_rate_pct` | `numeric` | yes |  |
| 47 | `insights_follows` | `numeric` | yes |  |
| 48 | `insights_profile_visits` | `numeric` | yes |  |
| 49 | `insights_profile_activity` | `numeric` | yes |  |
| 50 | `insights_navigation` | `numeric` | yes |  |
| 51 | `insights_replies` | `numeric` | yes |  |
| 52 | `insights_total_interactions` | `numeric` | yes |  |
| 53 | `owner` | `jsonb` | yes |  |
| 54 | `boost_eligibility_info` | `jsonb` | yes |  |
| 55 | `boost_ads_list` | `jsonb` | yes |  |

## Keys and indexes

- **No primary key.**
- Index — `ix_insta_data_account_key`: `CREATE INDEX ix_insta_data_account_key ON public.insta_data USING btree (account_key)`
- Index — `ix_insta_data_ig_object_id`: `CREATE INDEX ix_insta_data_ig_object_id ON public.insta_data USING btree (ig_object_id)`
- Index — `ix_insta_data_object_type`: `CREATE INDEX ix_insta_data_object_type ON public.insta_data USING btree (object_type)`
- Index — `ix_insta_data_posted_at`: `CREATE INDEX ix_insta_data_posted_at ON public.insta_data USING btree (posted_at)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `account_key` → `failed_jobs`, `sync_batches`
- `source_id` → `dump_instagram`, `raw_dump_instagram`, `raw_dump_shopify`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
