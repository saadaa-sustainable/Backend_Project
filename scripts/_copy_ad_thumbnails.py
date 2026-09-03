"""One-shot: copy public.ad_thumbnails from CTD Supabase to BP Supabase.

The general migrate_asset_register_from_ctd.py script uses executemany,
which is too slow through pgbouncer's transaction pool for the 16k rows
in this table. This script uses psycopg2.extras.execute_values (server-
side batched INSERT) instead.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from dotenv import dotenv_values, load_dotenv
from psycopg2.extras import execute_values

import psycopg2

CTD_ENV = Path("D:/Creative_Testing_Dashboard/backend/.env")
BP_ENV = Path(__file__).resolve().parents[1] / ".env"


def main() -> None:
    src_url = dotenv_values(str(CTD_ENV))["SUPABASE_DB_URL"]
    load_dotenv(str(BP_ENV), override=True)
    tgt_url = os.environ["DATABASE_URL_SYNC"].replace(
        "postgresql+psycopg2://", "postgresql://"
    ).split("?")[0]
    # Force session-mode pool (:5432) instead of transaction-mode (:6543)
    # so SET LOCAL statement_timeout sticks and long-running INSERTs
    # aren't pgbouncer-killed.
    tgt_url = tgt_url.replace(":6543/", ":5432/")

    print("fetching from CTD...", flush=True)
    with psycopg2.connect(src_url) as src:
        with src.cursor() as cur:
            cur.execute("""
                SELECT ad_id, thumbnail_url, image_url, creative_id, object_type,
                       video_id, fetched_at, last_error, instagram_permalink,
                       fb_permalink, video_source_url, video_source_fetched_at,
                       destination_url, linked_urls, destination_fetched_at,
                       destination_error
                FROM public.ad_thumbnails
            """)
            rows = cur.fetchall()
    print(f"  fetched {len(rows):,} rows", flush=True)

    print("upserting into BP (chunked commits to survive pgbouncer)...", flush=True)
    t0 = time.time()
    CHUNK = 100
    tgt = psycopg2.connect(tgt_url)
    tgt.autocommit = False
    # Bump statement timeout for the whole session before any insert runs.
    with tgt.cursor() as cur:
        cur.execute("SET statement_timeout = '600s'")
    tgt.commit()
    inserted = 0
    try:
        for i in range(0, len(rows), CHUNK):
            batch = rows[i:i+CHUNK]
            with tgt.cursor() as cur:
                execute_values(
                    cur,
                    """
                    INSERT INTO public.ad_thumbnails (
                        ad_id, thumbnail_url, image_url, creative_id, object_type,
                        video_id, fetched_at, last_error, instagram_permalink,
                        fb_permalink, video_source_url, video_source_fetched_at,
                        destination_url, linked_urls, destination_fetched_at,
                        destination_error
                    ) VALUES %s
                    ON CONFLICT (ad_id) DO UPDATE SET
                        thumbnail_url          = EXCLUDED.thumbnail_url,
                        image_url              = EXCLUDED.image_url,
                        creative_id            = EXCLUDED.creative_id,
                        object_type            = EXCLUDED.object_type,
                        video_id               = EXCLUDED.video_id,
                        fetched_at             = EXCLUDED.fetched_at,
                        last_error             = EXCLUDED.last_error,
                        instagram_permalink    = EXCLUDED.instagram_permalink,
                        fb_permalink           = EXCLUDED.fb_permalink,
                        video_source_url       = EXCLUDED.video_source_url,
                        video_source_fetched_at = EXCLUDED.video_source_fetched_at,
                        destination_url        = EXCLUDED.destination_url,
                        linked_urls            = EXCLUDED.linked_urls,
                        destination_fetched_at = EXCLUDED.destination_fetched_at,
                        destination_error      = EXCLUDED.destination_error,
                        ingested_from_ctd_at   = now()
                    """,
                    batch,
                    page_size=CHUNK,
                )
            tgt.commit()
            inserted += len(batch)
            if inserted % 2000 == 0 or inserted == len(rows):
                print(f"  {inserted:,} / {len(rows):,}  ({time.time()-t0:.1f}s)", flush=True)
    finally:
        tgt.close()
    print(f"  upsert done in {time.time()-t0:.1f}s", flush=True)

    with psycopg2.connect(tgt_url) as tgt:
        with tgt.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*),
                       COUNT(*) FILTER (WHERE instagram_permalink IS NOT NULL),
                       COUNT(*) FILTER (WHERE video_source_url IS NOT NULL)
                FROM public.ad_thumbnails
            """)
            n, ig, vid = cur.fetchone()
    print(f"\n[OK] ad_thumbnails: {n:,} rows, {ig:,} with IG permalink, {vid:,} with video URL")


if __name__ == "__main__":
    main()
