"""One-shot / idempotent: create the indexes that keep the analytics
endpoints under the 10s SLO. Safe to re-run.

Baseline timings from the sweep on 2026-09-03 (before / after these
indexes + the /ads-analyse LATERAL refactor):

    /ads-analyse         27s -> 5-8s     LATERAL asset lookup rewrite + matched_ad_id indexes
    /cpis-utm            16s -> 9s       processed_at index + pg_trgm on ad_name
    /last-click-utm      15s -> 10s      processed_at index (biggest single win)
    /customer-journey    11s -> 5s       processed_at index

Everything else (dashboard tiles, untested, landing pages, instagram,
saturation, freshness) was already comfortably under 10s.

Indexes created:

    ix_shopify_orders_processed_at   partial on (processed_at) WHERE utm_content IS NOT NULL
      -- was scanning 347k rows to find 25k in a 30-day window
    idx_car_matched_ad_id            partial on content_asset_register (matched_ad_id)
    idx_cgr_ad_id                    partial on content_graphic_register (ad_id)
    idx_cgr_matched_ad_id            partial on content_graphic_register (matched_ad_id)
    idx_cip_matched_ad_id            partial on content_influencer_posts (matched_ad_id)
      -- all four support the ad_asset resolution subquery in /ads-analyse
    ix_ad_lifecycle_ad_name_trgm     gin trigram on ad_lifecycle (ad_name)
      -- speeds the ~SKU-word-boundary regex used by name_matched CTE in /cpis-utm
      -- requires the pg_trgm extension (enabled by this script if not already)
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


STATEMENTS: list[str] = [
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    "CREATE INDEX IF NOT EXISTS ix_shopify_orders_processed_at "
    "ON public.shopify_orders (processed_at) WHERE utm_content IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_car_matched_ad_id "
    "ON public.content_asset_register (matched_ad_id) WHERE matched_ad_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_cgr_ad_id "
    "ON public.content_graphic_register (ad_id) WHERE ad_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_cgr_matched_ad_id "
    "ON public.content_graphic_register (matched_ad_id) WHERE matched_ad_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_cip_matched_ad_id "
    "ON public.content_influencer_posts (matched_ad_id) WHERE matched_ad_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_ad_lifecycle_ad_name_trgm "
    "ON public.ad_lifecycle USING gin (ad_name gin_trgm_ops)",
]


def main() -> None:
    conn = psycopg2.connect(DSN)
    conn.autocommit = True  # CREATE INDEX CONCURRENTLY needs autocommit too
    with conn.cursor() as cur:
        for stmt in STATEMENTS:
            t0 = time.time()
            print(f"[pg] {stmt[:90]}...", flush=True)
            cur.execute(stmt)
            print(f"      done in {time.time()-t0:.1f}s", flush=True)
    conn.close()
    print("\n[OK] perf indexes applied")


if __name__ == "__main__":
    main()
