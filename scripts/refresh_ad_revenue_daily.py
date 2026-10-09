"""refresh_ad_revenue_daily.py -- per-ad, per-day last-click revenue.

WHY THIS TABLE EXISTS
---------------------
The ad set and campaign rollups count "scalable creatives": ads inside
each entity that clear four gates, one of which is last-click ROAS. That
needs per-ad revenue over the user's chosen window, and the rollup used
to compute it inline -- aggregating shopify_order_attribution, joining
shopify_sales for the new-vs-returning split, then joining the result
against all 21,971 rows of ad_lifecycle.

Measured with EXPLAIN (ANALYZE) on 2026-10-06: that subquery was
11,248ms of a 19,739ms query -- 57% of the whole rollup -- to produce
TEN rows. The cost was never the volume of data. It was rebuilding the
same aggregate from scratch on every request, including for ads that no
gate could possibly admit.

Precomputed, the whole history is 49,501 rows over 3,189 ads and 283
days. Summing thirty days of that is an index range scan.

WHAT "REVENUE" MEANS HERE
-------------------------
Exactly what the inline version meant, so the gates do not shift under
the rollup:

  revenue      every attributed order's total_price, by matched_ad_id
  new_revenue  the subset whose customer was new on that order

The new/returning flag lives in shopify_sales and is joined on the
numeric tail of the attribution row's Shopify GID --
shopify_order_attribution stores "gid://shopify/Order/123" while
shopify_sales stores "123". Measured 2026-09-24: 99.9% of ad-attributed
orders join.

Days are IST calendar days, matching order_customer_type.order_day and
every other analytics table. created_at is UTC, so an order placed at
18:32 UTC belongs to the NEXT IST day; dating by created_at::date put
7.7% of orders in the wrong one.

Usage:
    ./.venv/bin/python scripts/refresh_ad_revenue_daily.py           # last 90 days
    ./.venv/bin/python scripts/refresh_ad_revenue_daily.py --full    # rebuild all
"""
from __future__ import annotations

import argparse
import asyncio
import os
import pathlib
import sys
import time

from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=False)

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

DDL = """
CREATE TABLE IF NOT EXISTS public.ad_revenue_daily (
    ad_id        text  NOT NULL,
    day          date  NOT NULL,
    revenue      numeric NOT NULL DEFAULT 0,
    new_revenue  numeric NOT NULL DEFAULT 0,
    orders       integer NOT NULL DEFAULT 0,
    refreshed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ad_id, day)
);
-- The rollup always filters by day first and then groups by ad, so day
-- leads. Including the two measures makes the window sum an index-only
-- scan that never touches the heap.
CREATE INDEX IF NOT EXISTS ix_ard_day
    ON public.ad_revenue_daily (day) INCLUDE (ad_id, revenue, new_revenue);
"""

#: Rebuilds one slice. The delete-then-insert is deliberate: an order
#: can be REASSIGNED to a different ad by a later attribution pass, so
#: an upsert keyed on (ad_id, day) would leave the old ad's row behind
#: carrying revenue that moved away from it.
UPSERT = """
DELETE FROM public.ad_revenue_daily WHERE day BETWEEN :from_date AND :to_date;

INSERT INTO public.ad_revenue_daily (ad_id, day, revenue, new_revenue, orders)
SELECT a.matched_ad_id,
       (a.created_at AT TIME ZONE 'Asia/Kolkata')::date        AS day,
       COALESCE(SUM(a.total_price), 0)                          AS revenue,
       COALESCE(SUM(a.total_price) FILTER (WHERE ss.kind = 'New'), 0) AS new_revenue,
       COUNT(*)                                                 AS orders
  FROM public.shopify_order_attribution a
  LEFT JOIN (SELECT DISTINCT order_id, new_or_returning_customer AS kind
               FROM public.shopify_sales) ss
    ON ss.order_id = split_part(a.order_id, '/', 5)
 WHERE a.matched_ad_id IS NOT NULL
   AND a.created_at >= (CAST(:from_date AS date)::timestamp AT TIME ZONE 'Asia/Kolkata')
   AND a.created_at <  ((CAST(:to_date AS date) + 1)::timestamp AT TIME ZONE 'Asia/Kolkata')
 GROUP BY 1, 2;
"""


def _dsn() -> str:
    url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_URL_SYNC")
    if not url:
        raise SystemExit("Set DATABASE_URL (asyncpg) or DATABASE_URL_SYNC in the env.")
    # Session-mode pooler: the full rebuild scans the whole attribution
    # table, which the transaction pool times out mid-scan.
    return (url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
               .replace("postgres+psycopg2://", "postgresql+asyncpg://")
               .split("?")[0].replace(":6543/", ":5432/"))


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--full", action="store_true",
                    help="rebuild every day present in the attribution table")
    ap.add_argument("--days", type=int, default=90,
                    help="trailing window to rebuild (default 90)")
    args = ap.parse_args()

    engine = create_async_engine(
        _dsn(), pool_pre_ping=True,
        connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0})
    async with engine.begin() as conn:
        # Supabase's pooler ignores asyncpg server_settings, so the
        # timeout has to be an explicit statement.
        await conn.execute(text("SET statement_timeout = '900s'"))
        # One statement per execute: asyncpg refuses a multi-statement
        # string, and the DDL is a table plus an index.
        for stmt in DDL.split(";"):
            if stmt.strip():
                await conn.execute(text(stmt))

        if args.full:
            bounds = (await conn.execute(text(
                "SELECT MIN((created_at AT TIME ZONE 'Asia/Kolkata')::date),"
                "       MAX((created_at AT TIME ZONE 'Asia/Kolkata')::date)"
                "  FROM public.shopify_order_attribution WHERE matched_ad_id IS NOT NULL"
            ))).one()
            from_d, to_d = bounds[0], bounds[1]
        else:
            row = (await conn.execute(text(
                "SELECT (current_date - :n)::date, current_date"), {"n": args.days})).one()
            from_d, to_d = row[0], row[1]

        t0 = time.time()
        for stmt in UPSERT.strip().split(";"):
            if stmt.strip():
                await conn.execute(text(stmt), {"from_date": from_d, "to_date": to_d})
        n = (await conn.execute(text(
            "SELECT COUNT(*) FROM public.ad_revenue_daily WHERE day BETWEEN :f AND :t"),
            {"f": from_d, "t": to_d})).scalar_one()
        # ANALYZE, not optional: a bulk load leaves the planner with
        # stale statistics, and it then sequentially scans a table the
        # rollup is about to query on every request.
        await conn.execute(text("ANALYZE public.ad_revenue_daily"))
        print(f"[OK] ad_revenue_daily {from_d} .. {to_d}: {n:,} rows in {time.time()-t0:.1f}s")
    await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
