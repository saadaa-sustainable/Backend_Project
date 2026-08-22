-- Flattened, typed view of dump_instagram's raw_payload JSONB into one
-- combined table -- every key discovered live 2026-08-18 across all 4
-- real content types (ig_user, ig_media, ig_collaborative_media,
-- ig_collaboration_invites), scanning every row, not a sample. The
-- internal `_ingestion_run_status` bookkeeping row is deliberately
-- excluded -- its JSON shape is unrelated to real Instagram content.
--
-- Deliberately ONE combined table, not one-per-content-type (this
-- project's own precedent for Meta Ads data was the opposite -- see
-- project memory) -- explicit user choice, made aware of the tradeoff:
-- most columns are null on any given row depending on object_type -- a
-- user profile row has no caption or like_count, and a media row has
-- no followers_count.
--
-- raw_payload's own "id" key is renamed ig_object_id here to avoid
-- colliding with dump_instagram's own envelope "id" (a UUID primary
-- key, unrelated to Meta's object id). "timestamp" (Meta's post date)
-- is renamed posted_at for the same clash-avoidance reason (also just
-- a clearer name). owner / boost_eligibility_info / boost_ads_list stay
-- JSONB -- they're nested objects/arrays, not flat scalars.
--
-- Run once in the Supabase SQL Editor, or via the direct DSN -- this
-- project's DDL convention throughout (see scripts/sql/raw_dump_instagram.sql).

DROP TABLE IF EXISTS insta_data;

CREATE TABLE insta_data AS
SELECT
    -- envelope / context
    id,
    source_id,
    object_type,
    parent_ids ->> 'account_key' AS account_key,
    parent_ids ->> 'ig_user_id' AS ig_user_id,
    extracted_at,
    ingested_at,

    -- identity
    raw_payload ->> 'id' AS ig_object_id,
    raw_payload ->> 'media_id' AS media_id,
    raw_payload ->> 'media_owner_username' AS media_owner_username,
    raw_payload ->> 'username' AS username,
    raw_payload ->> 'name' AS name,

    -- media content
    raw_payload ->> 'caption' AS caption,
    raw_payload ->> 'media_url' AS media_url,
    raw_payload ->> 'media_type' AS media_type,
    raw_payload ->> 'media_product_type' AS media_product_type,
    raw_payload ->> 'media_audio_type' AS media_audio_type,
    raw_payload ->> 'permalink' AS permalink,
    raw_payload ->> 'shortcode' AS shortcode,
    raw_payload ->> 'thumbnail_url' AS thumbnail_url,
    raw_payload ->> 'legacy_instagram_media_id' AS legacy_instagram_media_id,
    NULLIF(raw_payload ->> 'timestamp', '')::timestamptz AS posted_at,
    (raw_payload ->> 'is_comment_enabled')::boolean AS is_comment_enabled,
    (raw_payload ->> 'is_shared_to_feed')::boolean AS is_shared_to_feed,
    (raw_payload ->> 'is_ai_generated')::boolean AS is_ai_generated,

    -- profile fields (ig_user rows only)
    raw_payload ->> 'biography' AS biography,
    raw_payload ->> 'website' AS website,
    raw_payload ->> 'profile_picture_url' AS profile_picture_url,
    (raw_payload ->> 'followers_count')::numeric AS followers_count,
    (raw_payload ->> 'follows_count')::numeric AS follows_count,
    (raw_payload ->> 'media_count')::numeric AS media_count,
    (raw_payload ->> 'has_profile_pic')::boolean AS has_profile_pic,
    (raw_payload ->> 'is_published')::boolean AS is_published,

    -- engagement metrics
    (raw_payload ->> 'like_count')::numeric AS like_count,
    (raw_payload ->> 'comments_count')::numeric AS comments_count,
    (raw_payload ->> 'total_like_count')::numeric AS total_like_count,
    (raw_payload ->> 'total_comments_count')::numeric AS total_comments_count,
    (raw_payload ->> 'total_views_count')::numeric AS total_views_count,
    (raw_payload ->> 'saved_count')::numeric AS saved_count,
    (raw_payload ->> 'shares_count')::numeric AS shares_count,
    (raw_payload ->> 'reposts_count')::numeric AS reposts_count,

    -- /insights metrics (own content only -- confirmed hard-blocked for
    -- collaborative_media/collaboration_invites regardless of permissions;
    -- added 2026-08-18, only populated where --include-insights was used)
    (raw_payload -> 'insights' ->> 'reach')::numeric AS insights_reach,
    (raw_payload -> 'insights' ->> 'views')::numeric AS insights_views,
    (raw_payload -> 'insights' ->> 'ig_reels_avg_watch_time')::numeric AS avg_watch_time_ms,
    (raw_payload -> 'insights' ->> 'ig_reels_video_view_total_time')::numeric AS total_watch_time_ms,
    (raw_payload -> 'insights' ->> 'reels_skip_rate')::numeric AS reels_skip_rate_pct,
    (raw_payload -> 'insights' ->> 'follows')::numeric AS insights_follows,
    (raw_payload -> 'insights' ->> 'profile_visits')::numeric AS insights_profile_visits,
    (raw_payload -> 'insights' ->> 'profile_activity')::numeric AS insights_profile_activity,
    (raw_payload -> 'insights' ->> 'navigation')::numeric AS insights_navigation,
    (raw_payload -> 'insights' ->> 'replies')::numeric AS insights_replies,
    (raw_payload -> 'insights' ->> 'total_interactions')::numeric AS insights_total_interactions,

    -- nested / structured (kept as JSONB, not flattened further)
    raw_payload -> 'owner' AS owner,
    raw_payload -> 'boost_eligibility_info' AS boost_eligibility_info,
    raw_payload -> 'boost_ads_list' AS boost_ads_list
FROM dump_instagram
WHERE object_type != '_ingestion_run_status';

CREATE INDEX IF NOT EXISTS ix_insta_data_object_type ON insta_data (object_type);
CREATE INDEX IF NOT EXISTS ix_insta_data_account_key ON insta_data (account_key);
CREATE INDEX IF NOT EXISTS ix_insta_data_ig_object_id ON insta_data (ig_object_id);
CREATE INDEX IF NOT EXISTS ix_insta_data_posted_at ON insta_data (posted_at);
