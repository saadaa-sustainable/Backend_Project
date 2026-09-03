"""Materialise raw_dump_meta insights into a flat (ad_id, day, spend,
conv_value, ncp_count) table so CPIS + Creative Testing endpoints can
read windowed metrics without paying the per-row JSONB extraction cost
that made the /cpis-utm endpoint hit 60+ seconds at 50-row pagination.

Refresh cadence: run after every daily meta ingestion. Idempotent
(TRUNCATE + INSERT).

The columns are DERIVED here from Meta's actions[] / action_values[]
JSONB arrays -- ncp_count comes from actions[first_time_customer_purchase]
and conv_value from action_values[omni_purchase], matching what
ad_lifecycle.py extracts for the lifetime rollup.

Usage:
    ./.venv/Scripts/python.exe scripts/refresh_insights_daily_by_ad.py
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

import psycopg2  # noqa: E402


DSN = os.environ["DATABASE_URL_SYNC"].replace("postgresql+psycopg2://", "postgresql://")


DDL = """
CREATE TABLE IF NOT EXISTS public.insights_daily_by_ad (
    ad_id         text NOT NULL,
    day           date NOT NULL,
    spend         numeric,
    conv_value    numeric,
    ncp_count     numeric,
    impressions   numeric,
    clicks        numeric,
    refreshed_at  timestamptz DEFAULT NOW(),
    PRIMARY KEY (ad_id, day)
);
CREATE INDEX IF NOT EXISTS ix_idba_ad_day ON public.insights_daily_by_ad(ad_id, day);
CREATE INDEX IF NOT EXISTS ix_idba_day    ON public.insights_daily_by_ad(day);
"""


# NCP is Saadaa's custom-conversion metric -- looked up from
# raw_dump_meta (object_type='custom_conversion', name='NCP') the same
# way ad_lifecycle.py does the lifetime rollup. conv_value comes from
# action_values[omni_purchase] (falling back to plain purchase) --
# matches Meta Ads Manager's own "Purchases conversion value".
#
# 2026-09-03 fix: raw_dump_meta accumulates duplicate insight rows every
# time we re-fetch (Meta returns the same weekly/daily summary again;
# we ingest it as a fresh row rather than upserting). Before this fix
# the SUM below multiplied by the number of copies -- for one ad we
# observed 13 duplicate copies of the Aug 13-20 weekly row summed to
# Rs 1.59L when the truth was Rs 122k. The dedup CTE keeps ONE canonical
# copy per (ad_id, date_start, date_stop) -- the most-recently-ingested
# one, so a late correction wins over the earlier estimate.
REBUILD_SQL = """
WITH ncp_ids AS (
    SELECT DISTINCT raw_payload ->> 'id' AS id
    FROM raw_dump_meta
    WHERE object_type = 'custom_conversion' AND raw_payload ->> 'name' = 'NCP'
),
raw_dedup AS (
    SELECT DISTINCT ON (
      raw_payload->>'ad_id',
      raw_payload->>'date_start',
      raw_payload->>'date_stop'
    )
      raw_payload
    FROM raw_dump_meta
    WHERE object_type = 'insights'
      AND raw_payload->>'ad_id' IS NOT NULL
      AND raw_payload->>'date_start' IS NOT NULL
    ORDER BY
      raw_payload->>'ad_id',
      raw_payload->>'date_start',
      raw_payload->>'date_stop',
      ingested_at DESC
)
INSERT INTO public.insights_daily_by_ad (
    ad_id, day, spend, conv_value, ncp_count, impressions, clicks
)
SELECT
    r.raw_payload->>'ad_id' AS ad_id,
    (r.raw_payload->>'date_start')::date AS day,
    SUM(NULLIF(r.raw_payload->>'spend', '')::numeric) AS spend,
    -- conv_value: prefer omni_purchase (aggregated web + app + offline),
    -- fall back to plain purchase.
    SUM(COALESCE(
      (
        SELECT (av->>'value')::numeric
        FROM jsonb_array_elements(r.raw_payload->'action_values') av
        WHERE av->>'action_type' = 'omni_purchase'
        LIMIT 1
      ),
      (
        SELECT (av->>'value')::numeric
        FROM jsonb_array_elements(r.raw_payload->'action_values') av
        WHERE av->>'action_type' = 'purchase'
        LIMIT 1
      ),
      0
    )) AS conv_value,
    -- ncp_count: SUM(actions[].value) where action_type matches
    -- 'offsite_conversion.custom.<ncp_id>'. Custom-conversion ids are
    -- Business-Manager-global so we don't scope per-account.
    SUM(COALESCE(
      (
        SELECT SUM((act->>'value')::numeric)
        FROM jsonb_array_elements(r.raw_payload->'actions') act
        WHERE act->>'action_type' = ANY (
          SELECT 'offsite_conversion.custom.' || id FROM ncp_ids
        )
      ),
      0
    )) AS ncp_count,
    SUM(NULLIF(r.raw_payload->>'impressions', '')::numeric) AS impressions,
    SUM(NULLIF(r.raw_payload->>'inline_link_clicks', '')::numeric) AS clicks
FROM raw_dedup r
-- GROUP BY on the same (ad_id, date_start) key -- deliberately kept so
-- weekly summary rows (date_start != date_stop) still collapse under
-- their start-date bucket. Follow-up work: prefer daily rows (start=stop)
-- over weekly for the same ad, and pro-rate weekly-only spans across
-- their date range instead of assigning the whole total to the start day.
GROUP BY r.raw_payload->>'ad_id', (r.raw_payload->>'date_start')::date
"""


def main() -> None:
    t0 = time.time()
    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '1200s'")
            cur.execute(DDL)
            conn.commit()

            print("[pg] TRUNCATE insights_daily_by_ad", flush=True)
            cur.execute("TRUNCATE public.insights_daily_by_ad")

            print("[pg] rebuilding from raw_dump_meta ...", flush=True)
            cur.execute(REBUILD_SQL)
            conn.commit()

            cur.execute(
                "SELECT COUNT(*), COUNT(DISTINCT ad_id), MIN(day), MAX(day) "
                "FROM public.insights_daily_by_ad"
            )
            n, distinct_ads, mn, mx = cur.fetchone()
    finally:
        conn.close()

    dt = time.time() - t0
    print(f"\n[OK] insights_daily_by_ad refreshed in {dt:.1f}s")
    print(f"    rows          : {n:,}")
    print(f"    distinct ads  : {distinct_ads:,}")
    print(f"    date range    : {mn} -> {mx}")


if __name__ == "__main__":
    main()
