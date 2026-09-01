"""refresh_ad_product_daily.py — Silver flatten of raw_dump_meta
``object_type='insights_product'`` into a flat per-(ad_id, day, product_id)
table so downstream (CPIS / product-level dashboards) can read windowed
per-product spend without paying the JSONB parse cost each query.

Reads:
    raw_dump_meta WHERE object_type='insights_product'
    raw_dump_meta WHERE object_type='custom_conversion' AND name='NCP'
                                                         AND name='First-time EWV'

Writes:
    public.ad_product_daily(ad_id, day, product_id, product_name,
                            adset_id, campaign_id, account_id,
                            spend, impressions, clicks,
                            conv_value, purchases, ncp_count, ftewv_count,
                            refreshed_at)

Idempotent: TRUNCATE + INSERT. Same pattern as
refresh_insights_daily_by_ad.py.

Product-id field from Meta comes as "<numeric_id>, <human name>" -- we
split on the first comma to store id and name separately.

Usage:
    ./.venv/Scripts/python.exe scripts/refresh_ad_product_daily.py
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
CREATE TABLE IF NOT EXISTS public.ad_product_daily (
    ad_id         text NOT NULL,
    day           date NOT NULL,
    product_id    text NOT NULL,
    product_name  text,
    adset_id      text,
    campaign_id   text,
    account_id    text,
    spend         numeric,
    impressions   numeric,
    clicks        numeric,
    conv_value    numeric,
    purchases     numeric,
    ncp_count     numeric,
    ftewv_count   numeric,
    refreshed_at  timestamptz DEFAULT NOW(),
    PRIMARY KEY (ad_id, day, product_id)
);
CREATE INDEX IF NOT EXISTS ix_apd_ad_day       ON public.ad_product_daily(ad_id, day);
CREATE INDEX IF NOT EXISTS ix_apd_day          ON public.ad_product_daily(day);
CREATE INDEX IF NOT EXISTS ix_apd_product_id   ON public.ad_product_daily(product_id);
CREATE INDEX IF NOT EXISTS ix_apd_account_day  ON public.ad_product_daily(account_id, day);
"""


REBUILD_SQL = """
WITH ncp_ids AS (
    SELECT DISTINCT raw_payload ->> 'id' AS id
    FROM raw_dump_meta
    WHERE object_type = 'custom_conversion' AND raw_payload ->> 'name' = 'NCP'
),
ftewv_ids AS (
    SELECT DISTINCT raw_payload ->> 'id' AS id
    FROM raw_dump_meta
    WHERE object_type = 'custom_conversion' AND raw_payload ->> 'name' = 'First-time EWV'
),
src AS (
    SELECT
        raw_payload ->> 'ad_id'                       AS ad_id,
        (raw_payload ->> 'date_start')::date          AS day,
        split_part(raw_payload ->> 'product_id', ',', 1)                              AS product_id,
        NULLIF(trim(substring(raw_payload ->> 'product_id' FROM position(',' IN raw_payload ->> 'product_id') + 1)), '') AS product_name,
        raw_payload ->> 'adset_id'                    AS adset_id,
        raw_payload ->> 'campaign_id'                 AS campaign_id,
        raw_payload ->> 'account_id'                  AS account_id,
        raw_payload
    FROM raw_dump_meta
    WHERE object_type = 'insights_product'
      AND raw_payload ->> 'ad_id'      IS NOT NULL
      AND raw_payload ->> 'date_start' IS NOT NULL
      AND raw_payload ->> 'product_id' IS NOT NULL
)
INSERT INTO public.ad_product_daily (
    ad_id, day, product_id, product_name,
    adset_id, campaign_id, account_id,
    spend, impressions, clicks,
    conv_value, purchases, ncp_count, ftewv_count
)
SELECT
    ad_id, day, product_id,
    MAX(product_name)                                             AS product_name,
    MAX(adset_id)                                                 AS adset_id,
    MAX(campaign_id)                                              AS campaign_id,
    MAX(account_id)                                               AS account_id,
    SUM(NULLIF(raw_payload ->> 'spend',       '')::numeric)       AS spend,
    SUM(NULLIF(raw_payload ->> 'impressions', '')::numeric)       AS impressions,
    SUM(NULLIF(raw_payload ->> 'clicks',      '')::numeric)       AS clicks,
    -- conv_value: sum(action_values[omni_purchase]) fallback plain purchase
    SUM(COALESCE(
      (
        SELECT (av ->> 'value')::numeric
        FROM jsonb_array_elements(raw_payload -> 'action_values') av
        WHERE av ->> 'action_type' = 'omni_purchase'
        LIMIT 1
      ),
      (
        SELECT (av ->> 'value')::numeric
        FROM jsonb_array_elements(raw_payload -> 'action_values') av
        WHERE av ->> 'action_type' = 'purchase'
        LIMIT 1
      ),
      0
    )) AS conv_value,
    -- purchases: sum(actions[omni_purchase]) fallback plain purchase
    SUM(COALESCE(
      (
        SELECT (a ->> 'value')::numeric
        FROM jsonb_array_elements(raw_payload -> 'actions') a
        WHERE a ->> 'action_type' = 'omni_purchase'
        LIMIT 1
      ),
      (
        SELECT (a ->> 'value')::numeric
        FROM jsonb_array_elements(raw_payload -> 'actions') a
        WHERE a ->> 'action_type' = 'purchase'
        LIMIT 1
      ),
      0
    )) AS purchases,
    -- ncp_count: sum(actions[].value) whose action_type matches offsite_conversion.custom.<ncp_id>
    SUM(COALESCE(
      (
        SELECT SUM((a ->> 'value')::numeric)
        FROM jsonb_array_elements(raw_payload -> 'actions') a
        WHERE a ->> 'action_type' = ANY (SELECT 'offsite_conversion.custom.' || id FROM ncp_ids)
      ),
      0
    )) AS ncp_count,
    SUM(COALESCE(
      (
        SELECT SUM((a ->> 'value')::numeric)
        FROM jsonb_array_elements(raw_payload -> 'actions') a
        WHERE a ->> 'action_type' = ANY (SELECT 'offsite_conversion.custom.' || id FROM ftewv_ids)
      ),
      0
    )) AS ftewv_count
FROM src
GROUP BY ad_id, day, product_id
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

            print("[pg] TRUNCATE ad_product_daily", flush=True)
            cur.execute("TRUNCATE public.ad_product_daily")

            print("[pg] rebuilding from raw_dump_meta (object_type=insights_product) ...", flush=True)
            cur.execute(REBUILD_SQL)
            conn.commit()

            cur.execute("""
                SELECT COUNT(*), COUNT(DISTINCT ad_id), COUNT(DISTINCT product_id),
                       MIN(day), MAX(day), SUM(spend), SUM(purchases)
                FROM public.ad_product_daily
            """)
            n, ads, prods, mn, mx, spend, purch = cur.fetchone()
    finally:
        conn.close()

    dt = time.time() - t0
    print(f"\n[OK] ad_product_daily refreshed in {dt:.1f}s")
    print(f"    rows              : {n:,}")
    print(f"    distinct ads      : {ads:,}")
    print(f"    distinct products : {prods:,}")
    print(f"    date range        : {mn} -> {mx}")
    print(f"    total spend       : {spend}")
    print(f"    total purchases   : {purch}")


if __name__ == "__main__":
    main()
