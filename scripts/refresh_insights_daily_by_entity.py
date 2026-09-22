"""Flatten raw_dump_meta ADSET / CAMPAIGN insights into daily tables.

WHY
---
The Ads Analyse rollup reads its Meta metrics from `adset_insights` /
`campaign_insights`, which hold ONE arbitrary fetched window per entity
-- measured 2026-09-22, ad set 120233707955260431 carried
2026-09-07..09-21, fifteen days -- and present it beside Shopify figures
covering whatever range the user picked. For that ad set the row showed
21.5L of conversion value against a true 3.07 Cr over Jan..Sep, and the
"% Meta vs Shop" column read +923% when the honest answer was -29%.
Numerator and denominator on different windows, which is the same defect
class that has produced wrong headline numbers in this project before.

A daily grain fixes it: the rollup can then sum over exactly the window
requested, so both sides of every ratio describe one period.

Mirrors scripts/refresh_insights_daily_by_ad.py deliberately -- same
three-stage CTE, same pro-rating rules, same swap -- so ad, adset and
campaign grains agree by construction rather than by coincidence.

  raw_dedup  Meta's fetches duplicate rows (we ingest fresh rather than
             upserting), so keep ONE canonical copy per
             (entity, date_start, date_stop), most-recently-ingested
             first so a late correction beats an earlier estimate.
  expanded   Bronze mixes granularities: true daily rows alongside
             weekly/monthly summaries. Expand each into per-day slices,
             pro-rating counts across the range.
  best       Where a day has both a true daily row and a weekly slice
             covering it, keep the shorter range so the daily row wins
             and the two never double.

Reach is pro-rated only because a multi-day slice has no better answer;
it is people, not events, so a spread value is an average day, not a
sum. True daily rows carry their own reach and are always preferred.

Usage:
    ./.venv/bin/python scripts/refresh_insights_daily_by_entity.py
    ./.venv/bin/python scripts/refresh_insights_daily_by_entity.py --level adset
"""
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

import psycopg2  # noqa: E402

DSN = os.environ["DATABASE_URL_SYNC"].replace("postgresql+psycopg2://", "postgresql://").split("?")[0]

#: level -> (table, id column, the id that must be ABSENT so a row is
#: really at this level -- an ad row also carries adset_id).
LEVELS = {
    "adset":    ("insights_daily_by_adset",    "adset_id",    "ad_id"),
    "campaign": ("insights_daily_by_campaign", "campaign_id", "adset_id"),
}


def ddl(table: str, id_col: str) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS public.{table} (
    {id_col}      text NOT NULL,
    day           date NOT NULL,
    spend         numeric,
    impressions   numeric,
    reach         numeric,
    clicks        numeric,
    all_clicks    numeric,
    conv_value    numeric,
    purchases     numeric,
    -- Same Business-Manager-global custom conversion the ad-level
    -- flatten and ad_lifecycle resolve, so the three grains agree on
    -- what an FTEWV is rather than each defining its own.
    ftewv_count   numeric,
    refreshed_at  timestamptz DEFAULT NOW(),
    PRIMARY KEY ({id_col}, day)
);
ALTER TABLE public.{table} ADD COLUMN IF NOT EXISTS ftewv_count numeric;
CREATE INDEX IF NOT EXISTS ix_{table}_day ON public.{table}(day);
"""


def rebuild_sql(table: str, id_col: str, absent_col: str) -> str:
    return f"""
WITH ftewv_ids AS (
    SELECT DISTINCT raw_payload ->> 'id' AS id
    FROM raw_dump_meta
    WHERE object_type = 'custom_conversion'
      AND raw_payload ->> 'name' = 'First-time EWV'
),
raw_dedup AS (
    SELECT DISTINCT ON (
      raw_payload->>'{id_col}', raw_payload->>'date_start', raw_payload->>'date_stop'
    ) raw_payload
    FROM raw_dump_meta
    WHERE object_type = 'insights'
      AND raw_payload->>'{id_col}' IS NOT NULL
      -- An ad-level row also carries adset_id and campaign_id. Without
      -- this the adset table would be rebuilt from ad rows and every
      -- figure would be one ad's, not the ad set's.
      AND NOT (raw_payload ? '{absent_col}')
      AND raw_payload->>'date_start' IS NOT NULL
      AND raw_payload->>'date_stop' IS NOT NULL
    ORDER BY raw_payload->>'{id_col}', raw_payload->>'date_start',
             raw_payload->>'date_stop', ingested_at DESC
),
extracted AS (
    SELECT
      raw_payload->>'{id_col}' AS entity_id,
      (raw_payload->>'date_start')::date AS ds,
      (raw_payload->>'date_stop')::date  AS de,
      NULLIF(raw_payload->>'spend','')::numeric       AS spend,
      NULLIF(raw_payload->>'impressions','')::numeric AS impressions,
      NULLIF(raw_payload->>'reach','')::numeric       AS reach,
      NULLIF(raw_payload->>'inline_link_clicks','')::numeric AS clicks,
      NULLIF(raw_payload->>'clicks','')::numeric      AS all_clicks,
      -- omni_purchase first, plain purchase second -- the same ordering
      -- ad_lifecycle.py and the ad-level flatten use, so the three
      -- grains agree on what counts as a purchase.
      COALESCE(
        (SELECT (av->>'value')::numeric FROM jsonb_array_elements(raw_payload->'action_values') av
          WHERE av->>'action_type' = 'omni_purchase' LIMIT 1),
        (SELECT (av->>'value')::numeric FROM jsonb_array_elements(raw_payload->'action_values') av
          WHERE av->>'action_type' = 'purchase' LIMIT 1), 0) AS conv_value,
      COALESCE(
        (SELECT (a->>'value')::numeric FROM jsonb_array_elements(raw_payload->'actions') a
          WHERE a->>'action_type' = 'omni_purchase' LIMIT 1),
        (SELECT (a->>'value')::numeric FROM jsonb_array_elements(raw_payload->'actions') a
          WHERE a->>'action_type' = 'purchase' LIMIT 1), 0) AS purchases,
      COALESCE(
        (SELECT SUM((a->>'value')::numeric) FROM jsonb_array_elements(raw_payload->'actions') a
          WHERE a->>'action_type' = ANY (SELECT 'offsite_conversion.custom.' || id FROM ftewv_ids)),
        0) AS ftewv_count
    FROM raw_dedup
),
expanded AS (
    SELECT e.entity_id, gs::date AS day, (e.de - e.ds + 1) AS range_days,
           e.spend       / NULLIF(e.de - e.ds + 1, 0) AS spend,
           e.impressions / NULLIF(e.de - e.ds + 1, 0) AS impressions,
           e.reach       / NULLIF(e.de - e.ds + 1, 0) AS reach,
           e.clicks      / NULLIF(e.de - e.ds + 1, 0) AS clicks,
           e.all_clicks  / NULLIF(e.de - e.ds + 1, 0) AS all_clicks,
           e.conv_value  / NULLIF(e.de - e.ds + 1, 0) AS conv_value,
           e.purchases   / NULLIF(e.de - e.ds + 1, 0) AS purchases,
           e.ftewv_count / NULLIF(e.de - e.ds + 1, 0) AS ftewv_count
      FROM extracted e, generate_series(e.ds, e.de, '1 day'::interval) gs
),
best AS (
    SELECT DISTINCT ON (entity_id, day)
           entity_id, day, spend, impressions, reach, clicks, all_clicks,
           conv_value, purchases, ftewv_count
      FROM expanded ORDER BY entity_id, day, range_days ASC
)
INSERT INTO public.{table}_new
    ({id_col}, day, spend, impressions, reach, clicks, all_clicks, conv_value, purchases, ftewv_count)
SELECT entity_id, day, spend, impressions, reach, clicks, all_clicks, conv_value, purchases, ftewv_count
FROM best
"""


def refresh(cur, level: str) -> int:
    table, id_col, absent = LEVELS[level]
    t0 = time.monotonic()
    print(f"\n=== {level}: rebuilding public.{table}", flush=True)
    cur.execute(ddl(table, id_col))
    # Build into a side table and swap. A TRUNCATE holds ACCESS
    # EXCLUSIVE for the whole transaction and blocks every reader --
    # that took the Creative Testing section down for two minutes once.
    cur.execute(f"DROP TABLE IF EXISTS public.{table}_new")
    cur.execute(f"CREATE TABLE public.{table}_new (LIKE public.{table} INCLUDING ALL)")
    cur.execute(rebuild_sql(table, id_col, absent))
    n = cur.rowcount
    # Old index names have to move aside first: renaming a table does
    # NOT rename its indexes, and the PK name collides otherwise.
    cur.execute(f"ALTER TABLE public.{table} RENAME TO {table}_old")
    cur.execute(f"ALTER INDEX IF EXISTS {table}_pkey RENAME TO {table}_old_pkey")
    cur.execute(f"ALTER INDEX IF EXISTS ix_{table}_day RENAME TO ix_{table}_old_day")
    cur.execute(f"ALTER TABLE public.{table}_new RENAME TO {table}")
    cur.execute(f"DROP TABLE IF EXISTS public.{table}_old")
    print(f"    {n:,} rows in {time.monotonic() - t0:.1f}s", flush=True)
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--level", choices=[*LEVELS, "all"], default="all")
    args = ap.parse_args()
    levels = list(LEVELS) if args.level == "all" else [args.level]

    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '3600s'")
            for lv in levels:
                refresh(cur, lv)
        conn.commit()
        with conn.cursor() as cur:
            for lv in levels:
                table, id_col, _ = LEVELS[lv]
                cur.execute(f"SELECT COUNT(*), COUNT(DISTINCT {id_col}), MIN(day), MAX(day) "
                            f"FROM public.{table}")
                n, ents, lo, hi = cur.fetchone()
                print(f"  {table:<32}{n:>9,} rows  {ents:>6,} entities  {lo} .. {hi}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
