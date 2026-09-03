"""Silver flatten: per-ad thumbnail, video, and landing-page URL.

Reads from raw_dump_meta (bronze) and joins four object types to produce
one row per Meta ad_id:

    ad             raw_payload.id, raw_payload.creative.id
      -> asset_feed_spec (via creative_id)
          -> image (via images[0].hash)              first-image thumbnail
          -> video (via videos[0].video_id)          video source + poster
        raw_payload.link_urls[0].website_url         landing page

Output: public.ad_media (PK ad_id) -- ready to LEFT JOIN into /ads-analyse
so the frontend can render an inline thumbnail preview + landing-URL
badge without touching bronze at request time.

Idempotent: TRUNCATE + INSERT. Safe to re-run.

Usage:
    ./.venv/Scripts/python.exe scripts/refresh_ad_media.py
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

import psycopg2  # noqa: E402


DSN = os.environ["DATABASE_URL_SYNC"].replace(
    "postgresql+psycopg2://", "postgresql://"
).split("?")[0]


DDL = """
CREATE TABLE IF NOT EXISTS public.ad_media (
    ad_id             text PRIMARY KEY,
    creative_id       text,
    -- Displayable thumbnail. Prefers the video poster when the creative
    -- is a video (so the user sees the same frame Meta shows in the
    -- Ads Manager preview), else the image's 128px CDN URL, else the
    -- full-size image URL.
    thumbnail_url     text,
    -- Video-only: the source .mp4 URL + Meta video_id (for iframe
    -- embed / Facebook video preview modal). NULL for image ads.
    video_url         text,
    video_id          text,
    -- Landing page: what the ad's CTA points to.
    landing_page_url  text,
    -- The human-readable display URL Meta shows next to the CTA (e.g.
    -- "saadaa.in" even when the click-through is a specific product).
    link_display_url  text,
    is_video          boolean NOT NULL DEFAULT false,
    -- Facebook post identifier in the form <page_id>_<post_id>. Present
    -- on ~78% of ads (much higher coverage than the asset_feed_spec
    -- chain gets us for thumbnails). Used to build the Facebook post
    -- iframe embed on the frontend:
    --   href = https://www.facebook.com/<page_id>/posts/<post_id>
    --   src  = https://www.facebook.com/plugins/post.php?href=<url>...
    -- which renders the ACTUAL post (caption + CTA + interactions +
    -- media) exactly as Meta shows it in Ads Manager Preview.
    effective_object_story_id  text,
    refreshed_at      timestamptz DEFAULT NOW()
);

-- Additive change (2026-09-03): FB post iframe embed source. Add via
-- ALTER because the table may already exist from an earlier build.
ALTER TABLE public.ad_media
    ADD COLUMN IF NOT EXISTS effective_object_story_id text;

CREATE INDEX IF NOT EXISTS ix_ad_media_landing
    ON public.ad_media (landing_page_url);
"""


# raw_dump_meta accumulates duplicate rows (same object_type + meta_id)
# across repeat ingests -- dedupe first by keeping the most-recent copy.
# Then LEFT JOIN the four object types via their FK-like links in JSONB.
REBUILD_SQL = """
WITH dedup AS (
    SELECT DISTINCT ON (object_type, meta_id)
        object_type, meta_id, raw_payload
    FROM raw_dump_meta
    WHERE object_type IN ('ad', 'asset_feed_spec', 'image', 'video')
      AND meta_id IS NOT NULL
    ORDER BY object_type, meta_id, ingested_at DESC
),
-- Meta trimmed effective_object_story_id from its API response at some
-- point in 2026 -- our recent ingests don't carry it any more, but
-- ~78% of ads had it in older ingests. Fish it out of ANY historical
-- ingest so we keep iframe-preview coverage instead of losing it to
-- ingest churn.
ad_story_id AS (
    SELECT DISTINCT ON (meta_id)
        meta_id,
        raw_payload->'creative'->>'effective_object_story_id' AS eos_id
    FROM raw_dump_meta
    WHERE object_type = 'ad'
      AND raw_payload->'creative' ? 'effective_object_story_id'
    ORDER BY meta_id, ingested_at DESC
)
INSERT INTO public.ad_media (
    ad_id, creative_id, thumbnail_url, video_url, video_id,
    landing_page_url, link_display_url, is_video,
    effective_object_story_id
)
SELECT
    ad.meta_id AS ad_id,
    ad.raw_payload->'creative'->>'id' AS creative_id,
    -- Thumbnail preference: video poster > image 128px > image full.
    COALESCE(
        afs.raw_payload->'videos'->0->>'thumbnail_url',
        img.raw_payload->>'url_128',
        img.raw_payload->>'url'
    ) AS thumbnail_url,
    vid.raw_payload->>'source' AS video_url,
    afs.raw_payload->'videos'->0->>'video_id' AS video_id,
    afs.raw_payload->'link_urls'->0->>'website_url' AS landing_page_url,
    afs.raw_payload->'link_urls'->0->>'display_url' AS link_display_url,
    (afs.raw_payload->'videos'->0 IS NOT NULL) AS is_video,
    -- Prefer the field from the latest ingest (via ad.raw_payload), fall
    -- back to any historical ingest (via ad_story_id) if the latest
    -- dropped it. Fixes the mid-2026 Meta-API-response trim.
    COALESCE(
        ad.raw_payload->'creative'->>'effective_object_story_id',
        asi.eos_id
    ) AS effective_object_story_id
FROM dedup ad
LEFT JOIN ad_story_id asi ON asi.meta_id = ad.meta_id
LEFT JOIN dedup afs
    ON afs.object_type = 'asset_feed_spec'
   AND afs.meta_id = ad.raw_payload->'creative'->>'id'
LEFT JOIN dedup img
    ON img.object_type = 'image'
   AND img.meta_id = afs.raw_payload->'images'->0->>'hash'
LEFT JOIN dedup vid
    ON vid.object_type = 'video'
   AND vid.meta_id = afs.raw_payload->'videos'->0->>'video_id'
WHERE ad.object_type = 'ad'
  AND ad.raw_payload->'creative'->>'id' IS NOT NULL
"""


def main() -> None:
    t0 = time.time()
    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '900s'")
            cur.execute(DDL)
            conn.commit()

            print("[pg] TRUNCATE ad_media", flush=True)
            cur.execute("TRUNCATE public.ad_media")

            print("[pg] rebuilding from raw_dump_meta ...", flush=True)
            cur.execute(REBUILD_SQL)
            conn.commit()

            cur.execute("""
                SELECT COUNT(*),
                       COUNT(*) FILTER (WHERE thumbnail_url IS NOT NULL),
                       COUNT(*) FILTER (WHERE landing_page_url IS NOT NULL),
                       COUNT(*) FILTER (WHERE is_video),
                       COUNT(*) FILTER (WHERE effective_object_story_id IS NOT NULL)
                FROM public.ad_media
            """)
            n, has_thumb, has_landing, is_video, has_story = cur.fetchone()
    finally:
        conn.close()

    dt = time.time() - t0
    print(f"\n[OK] ad_media refreshed in {dt:.1f}s")
    print(f"    ads              : {n:,}")
    print(f"    with thumbnail   : {has_thumb:,}  ({has_thumb*100/n:.0f}%)")
    print(f"    with landing URL : {has_landing:,}  ({has_landing*100/n:.0f}%)")
    print(f"    video ads        : {is_video:,}  ({is_video*100/n:.0f}%)")
    print(f"    with FB story_id : {has_story:,}  ({has_story*100/n:.0f}%)  -- iframe-embeddable")


if __name__ == "__main__":
    main()
