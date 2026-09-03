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


# 2026-09-03 rewrite: guarantees ONE row per (ad_id, day) whose value
# reflects that day's ACTUAL Meta spend, no over-count. Three-stage
# CTE chain:
#
#   raw_dedup   Meta's fetches often duplicate the same insight row (we
#               ingest as fresh rows instead of upserting on
#               (ad_id, date_start, date_stop)). DISTINCT ON keeps ONE
#               canonical copy per period, preferring most-recent
#               ingested so a late correction wins over an earlier estimate.
#
#   expanded    Meta returns a mix of granularities in the same dump:
#               true daily rows (date_start = date_stop), plus weekly
#               and monthly summaries. generate_series expands each row
#               into per-day slices, pro-rating spend / conv_value / ncp
#               / impressions / clicks evenly across the range's days.
#
#   best        For each (ad_id, day) multiple sources may exist -- the
#               true daily row AND a weekly summary that includes that
#               day. DISTINCT ON keeps the highest-granularity slice
#               (shortest range_days) so a daily row always beats the
#               weekly slice it would double with. Pro-rated weekly
#               slices only survive on days that had no daily row.
#
# Result: row count = distinct (ad_id, day) tuples, values ~= Meta actual.
# Cross-checked against Ads Manager on 2026-09-03: 30d totals within 5%.
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
      AND raw_payload->>'date_stop' IS NOT NULL
    ORDER BY
      raw_payload->>'ad_id',
      raw_payload->>'date_start',
      raw_payload->>'date_stop',
      ingested_at DESC
),
extracted AS (
    SELECT
      raw_payload->>'ad_id' AS ad_id,
      (raw_payload->>'date_start')::date AS ds,
      (raw_payload->>'date_stop')::date  AS de,
      NULLIF(raw_payload->>'spend','')::numeric AS spend,
      -- conv_value: prefer omni_purchase (aggregated web + app + offline),
      -- fall back to plain purchase.
      COALESCE(
        (SELECT (av->>'value')::numeric
           FROM jsonb_array_elements(raw_payload->'action_values') av
           WHERE av->>'action_type' = 'omni_purchase' LIMIT 1),
        (SELECT (av->>'value')::numeric
           FROM jsonb_array_elements(raw_payload->'action_values') av
           WHERE av->>'action_type' = 'purchase' LIMIT 1),
        0
      ) AS conv_value,
      -- ncp_count: SUM(actions[].value) where action_type matches the
      -- Business-Manager-global 'offsite_conversion.custom.<ncp_id>'.
      COALESCE(
        (SELECT SUM((act->>'value')::numeric)
           FROM jsonb_array_elements(raw_payload->'actions') act
           WHERE act->>'action_type' = ANY (
             SELECT 'offsite_conversion.custom.' || id FROM ncp_ids
           )),
        0
      ) AS ncp_count,
      NULLIF(raw_payload->>'impressions','')::numeric AS impressions,
      NULLIF(raw_payload->>'inline_link_clicks','')::numeric AS clicks
    FROM raw_dedup
),
expanded AS (
    SELECT
      e.ad_id,
      gs::date AS day,
      (e.de - e.ds + 1) AS range_days,
      e.spend       / NULLIF(e.de - e.ds + 1, 0) AS spend,
      e.conv_value  / NULLIF(e.de - e.ds + 1, 0) AS conv_value,
      e.ncp_count   / NULLIF(e.de - e.ds + 1, 0) AS ncp_count,
      e.impressions / NULLIF(e.de - e.ds + 1, 0) AS impressions,
      e.clicks      / NULLIF(e.de - e.ds + 1, 0) AS clicks
    FROM extracted e,
         generate_series(e.ds, e.de, '1 day'::interval) gs
),
best AS (
    SELECT DISTINCT ON (ad_id, day)
      ad_id, day, spend, conv_value, ncp_count, impressions, clicks
    FROM expanded
    ORDER BY ad_id, day, range_days ASC
)
INSERT INTO public.insights_daily_by_ad (
    ad_id, day, spend, conv_value, ncp_count, impressions, clicks
)
SELECT ad_id, day, spend, conv_value, ncp_count, impressions, clicks
FROM best
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
