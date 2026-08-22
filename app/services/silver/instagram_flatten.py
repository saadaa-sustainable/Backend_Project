"""Silver-layer flatten step for Instagram content (`insta_data`).

One combined table, not one-per-content-type (unlike Meta) — this project's
deliberate choice made when `insta_data` was first built from
`dump_instagram`: most columns are null on any given row depending on
`object_type` (a profile row has no `caption`, a media row has no
`followers_count`).

Rebuilt via TRUNCATE + INSERT (not DROP + CREATE) so the table is never
briefly missing mid-refresh and so `app/services/silver/registry.py` can
treat this the same way as the Meta entity refresh.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging.setup import get_logger

logger = get_logger(__name__)

_DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS insta_data (
        id uuid,
        source_id text,
        object_type text,
        account_key text,
        ig_user_id text,
        extracted_at timestamptz,
        ingested_at timestamptz,
        ig_object_id text,
        media_id text,
        media_owner_username text,
        username text,
        name text,
        caption text,
        media_url text,
        media_type text,
        media_product_type text,
        media_audio_type text,
        permalink text,
        shortcode text,
        thumbnail_url text,
        legacy_instagram_media_id text,
        posted_at timestamptz,
        is_comment_enabled boolean,
        is_shared_to_feed boolean,
        is_ai_generated boolean,
        biography text,
        website text,
        profile_picture_url text,
        followers_count numeric,
        follows_count numeric,
        media_count numeric,
        has_profile_pic boolean,
        is_published boolean,
        like_count numeric,
        comments_count numeric,
        total_like_count numeric,
        total_comments_count numeric,
        total_views_count numeric,
        saved_count numeric,
        shares_count numeric,
        reposts_count numeric,
        insights_reach numeric,
        insights_views numeric,
        avg_watch_time_ms numeric,
        total_watch_time_ms numeric,
        reels_skip_rate_pct numeric,
        insights_follows numeric,
        insights_profile_visits numeric,
        insights_profile_activity numeric,
        insights_navigation numeric,
        insights_replies numeric,
        insights_total_interactions numeric,
        owner jsonb,
        boost_eligibility_info jsonb,
        boost_ads_list jsonb
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_insta_data_object_type ON insta_data (object_type)",
    "CREATE INDEX IF NOT EXISTS ix_insta_data_account_key ON insta_data (account_key)",
    "CREATE INDEX IF NOT EXISTS ix_insta_data_ig_object_id ON insta_data (ig_object_id)",
    "CREATE INDEX IF NOT EXISTS ix_insta_data_posted_at ON insta_data (posted_at)",
]

_TRUNCATE = "TRUNCATE insta_data"
_INSERT = """
INSERT INTO insta_data
SELECT
    id,
    source_id,
    object_type,
    parent_ids ->> 'account_key' AS account_key,
    parent_ids ->> 'ig_user_id' AS ig_user_id,
    extracted_at,
    ingested_at,
    raw_payload ->> 'id' AS ig_object_id,
    raw_payload ->> 'media_id' AS media_id,
    raw_payload ->> 'media_owner_username' AS media_owner_username,
    raw_payload ->> 'username' AS username,
    raw_payload ->> 'name' AS name,
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
    raw_payload ->> 'biography' AS biography,
    raw_payload ->> 'website' AS website,
    raw_payload ->> 'profile_picture_url' AS profile_picture_url,
    (raw_payload ->> 'followers_count')::numeric AS followers_count,
    (raw_payload ->> 'follows_count')::numeric AS follows_count,
    (raw_payload ->> 'media_count')::numeric AS media_count,
    (raw_payload ->> 'has_profile_pic')::boolean AS has_profile_pic,
    (raw_payload ->> 'is_published')::boolean AS is_published,
    (raw_payload ->> 'like_count')::numeric AS like_count,
    (raw_payload ->> 'comments_count')::numeric AS comments_count,
    (raw_payload ->> 'total_like_count')::numeric AS total_like_count,
    (raw_payload ->> 'total_comments_count')::numeric AS total_comments_count,
    (raw_payload ->> 'total_views_count')::numeric AS total_views_count,
    (raw_payload ->> 'saved_count')::numeric AS saved_count,
    (raw_payload ->> 'shares_count')::numeric AS shares_count,
    (raw_payload ->> 'reposts_count')::numeric AS reposts_count,
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
    raw_payload -> 'owner' AS owner,
    raw_payload -> 'boost_eligibility_info' AS boost_eligibility_info,
    raw_payload -> 'boost_ads_list' AS boost_ads_list
FROM dump_instagram
WHERE object_type != '_ingestion_run_status'
"""


async def ensure_insta_data_table(session: AsyncSession) -> None:
    for statement in _DDL_STATEMENTS:
        await session.execute(text(statement))
    await session.commit()


async def refresh_insta_data(session: AsyncSession) -> dict[str, int]:
    await ensure_insta_data_table(session)
    await session.execute(text(_TRUNCATE))
    await session.execute(text(_INSERT))
    await session.commit()

    result = await session.execute(text("SELECT COUNT(*) FROM insta_data"))
    count = result.scalar_one()
    logger.info("insta_data_refreshed", insta_data=count)
    return {"insta_data": count}
