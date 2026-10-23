"""Silver flatten: per-ad thumbnail, video, and landing-page URL.

Reads from raw_dump_meta (bronze) and joins four object types to produce
one row per Meta ad_id:

    ad             raw_payload.id, raw_payload.creative.id
      -> asset_feed_spec (via creative_id)
          -> image (via images[0].hash)              first-image thumbnail
          -> video (via videos[0].video_id)          video source + poster
    adcreative     (via parent_ids.ad_id)            landing page

The landing page comes from `adcreative` -- the per-ad creative fetched by
scripts/backfill_ad_landing_urls.py -- and falls back to
asset_feed_spec.link_urls[0].website_url, which is the only place it used
to look. That fallback alone covered 8.6% of creatives (5,110 of 59,226);
everything else is a Degrees-of-Freedom spec whose URL lives in
object_story_spec, a field Meta will not serve on a bulk page.

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

-- Additive change (2026-10-23): which Meta field the landing page came
-- from. Worth storing because the sources are not equally trustworthy --
-- object_story_spec.link_data.link is the URL the ad resolved to, while
-- asset_feed_spec.link_urls[0] is merely the FIRST of several candidates
-- a Degrees-of-Freedom ad may rotate through. A NULL url with a NULL
-- source means Meta had nothing; see scripts/backfill_ad_landing_urls.py
-- for the one case that is a permission gap rather than missing data.
ALTER TABLE public.ad_media
    ADD COLUMN IF NOT EXISTS landing_page_source text;

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
      -- "Newest snapshot that is USABLE", not simply "newest snapshot".
      --
      -- Bronze holds snapshots from several fetchers, and they do not
      -- all request the same fields. The nightly roster fetch asks for
      -- id/name/status and not `creative`; the moment it ran it became
      -- the newest row for all 20,189 ads, every one of them missing
      -- the only key this rebuild keys off. ad_media went to ZERO rows
      -- -- every thumbnail in the dashboard gone in one night, with no
      -- error anywhere, because a LEFT JOIN that matches nothing and a
      -- WHERE that filters everything both look like success.
      --
      -- Ordering the ad rows so creative-bearing snapshots sort first
      -- makes the rebuild depend on the data it needs existing SOMEWHERE
      -- in bronze, rather than on it happening to be in the latest row.
      AND (object_type <> 'ad' OR raw_payload ? 'creative')
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
),
-- The landing page, from the creative fetched per-ad by
-- scripts/backfill_ad_landing_urls.py. This is the PRIMARY source now,
-- with the asset_feed_spec chain below as fallback, because
-- asset_feed_spec.link_urls only ever covered 8.6% of creatives (5,110
-- of 59,226): the rest are optimization_type=DEGREES_OF_FREEDOM specs
-- carrying only bodies/titles/descriptions, whose URL lives in
-- object_story_spec -- a field Meta refuses to serve on a bulk /ads or
-- /adcreatives page at all. See that script's docstring.
--
-- Keyed on parent_ids->>'ad_id', NOT on meta_id: one creative is shared
-- by many ads, so these rows are one per (ad, creative) and would not
-- survive the `dedup` CTE's DISTINCT ON (object_type, meta_id).
ad_landing AS (
    SELECT DISTINCT ON (parent_ids->>'ad_id')
        parent_ids->>'ad_id'                 AS ad_id,
        raw_payload->>'landing_page_url'     AS landing_page_url,
        raw_payload->>'landing_page_source'  AS landing_page_source,
        raw_payload->'asset_feed_spec'->'link_urls'->0->>'display_url'
                                             AS link_display_url
    FROM raw_dump_meta
    WHERE object_type = 'adcreative'
      AND parent_ids->>'ad_id' IS NOT NULL
      AND raw_payload->>'landing_page_url' IS NOT NULL
    ORDER BY parent_ids->>'ad_id', ingested_at DESC
)
INSERT INTO public.ad_media (
    ad_id, creative_id, thumbnail_url, video_url, video_id,
    landing_page_url, link_display_url, is_video,
    effective_object_story_id, landing_page_source
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
    COALESCE(
        alp.landing_page_url,
        afs.raw_payload->'link_urls'->0->>'website_url'
    ) AS landing_page_url,
    COALESCE(
        alp.link_display_url,
        afs.raw_payload->'link_urls'->0->>'display_url'
    ) AS link_display_url,
    (afs.raw_payload->'videos'->0 IS NOT NULL) AS is_video,
    -- Prefer the field from the latest ingest (via ad.raw_payload), fall
    -- back to any historical ingest (via ad_story_id) if the latest
    -- dropped it. Fixes the mid-2026 Meta-API-response trim.
    COALESCE(
        ad.raw_payload->'creative'->>'effective_object_story_id',
        asi.eos_id
    ) AS effective_object_story_id,
    COALESCE(
        alp.landing_page_source,
        CASE WHEN afs.raw_payload->'link_urls'->0->>'website_url' IS NOT NULL
             THEN 'asset_feed_spec.link_urls[0].website_url' END
    ) AS landing_page_source
FROM dedup ad
LEFT JOIN ad_story_id asi ON asi.meta_id = ad.meta_id
LEFT JOIN ad_landing alp ON alp.ad_id = ad.meta_id
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
            cur.execute("""
                SELECT COALESCE(landing_page_source, '(none)'), COUNT(*)
                FROM public.ad_media GROUP BY 1 ORDER BY 2 DESC
            """)
            by_source = cur.fetchall()
    finally:
        conn.close()

    dt = time.time() - t0
    print(f"\n[OK] ad_media refreshed in {dt:.1f}s")
    print(f"    ads              : {n:,}")
    if not n:
        # Louder than a traceback and far louder than the silence this
        # replaced: a rebuild that produces nothing is a failure, not a
        # successful refresh of an empty table.
        print("    [FAIL] 0 ads -- bronze has no 'ad' snapshot carrying a "
              "creative.id. Check that the roster fetch requests "
              "creative{id,effective_object_story_id}.", flush=True)
        raise SystemExit(1)
    print(f"    with thumbnail   : {has_thumb:,}  ({has_thumb*100/n:.0f}%)")
    print(f"    with landing URL : {has_landing:,}  ({has_landing*100/n:.0f}%)")
    print(f"    video ads        : {is_video:,}  ({is_video*100/n:.0f}%)")
    print(f"    with FB story_id : {has_story:,}  ({has_story*100/n:.0f}%)  -- iframe-embeddable")
    print("    landing URL by source:")
    for source, count in by_source:
        print(f"        {count:7,}  {source}")


if __name__ == "__main__":
    main()
