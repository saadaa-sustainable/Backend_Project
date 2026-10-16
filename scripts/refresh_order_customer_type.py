"""Classify every Shopify order as a NEW or REPEAT customer purchase.

One row per order. The flag is POINT IN TIME: an order is "new" when it
is that customer's first order ever, judged against the whole order
history, not against a window.

Why this table exists at all, when shopify_customer_analytics already
carries total_number_of_orders: that column is the customer's CURRENT
lifetime count. A customer who has since bought four times reads as
"repeat" on all four orders, including the first one. Asking whether an
ad brought a NEW customer needs the answer AS OF that order, which only
the order history can give.

History runs from 2020-11 and 99.9 percent of orders carry a
customer_id, so the first order of nearly every customer is actually in
the data -- the flag is not guessing from a truncated window.

Grain and additivity, which matter when this is rolled up per ad:

    new_orders        == new_customers, always. A first order is unique
                         to a customer by definition, so counting
                         orders and counting people give the same
                         number and both add up across ads.
    repeat_customers  does NOT add up across ads. One person can buy
                         twice in a window from two different ads and
                         is one customer but two rows. Count them
                         DISTINCT at whatever grain is being displayed;
                         never SUM a per-ad column.

Usage:
    ./.venv/bin/python scripts/refresh_order_customer_type.py
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
CREATE TABLE IF NOT EXISTS public.order_customer_type (
    order_id        text PRIMARY KEY,
    customer_id     text,
    order_seq       integer,
    is_new_customer boolean,
    first_order_at  timestamptz,
    order_at        timestamptz,
    order_day       date,
    total_price     numeric,
    refreshed_at    timestamptz DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_oct_customer ON public.order_customer_type(customer_id);
CREATE INDEX IF NOT EXISTS ix_oct_day      ON public.order_customer_type(order_day);
CREATE INDEX IF NOT EXISTS ix_oct_new      ON public.order_customer_type(is_new_customer);
"""

# Built into a side table and swapped, like the other silver builders,
# so readers never see a half-populated table.
#
# ROW_NUMBER over (customer, time) rather than a correlated NOT EXISTS:
# one sort of 382k rows instead of 382k index probes.
#
# order_day is the IST calendar day, matching every other analytics
# table -- Meta reports in Asia/Kolkata and processed_at::date would
# cast at the session timezone, UTC.
REBUILD = """
INSERT INTO public.order_customer_type_new
    (order_id, customer_id, order_seq, is_new_customer,
     first_order_at, order_at, order_day, total_price)
SELECT order_id, customer_id, seq, seq = 1,
       first_at, processed_at,
       (processed_at AT TIME ZONE 'Asia/Kolkata')::date,
       total_price
FROM (
    SELECT so.order_id, so.customer_id, so.processed_at, so.total_price,
           ROW_NUMBER() OVER (PARTITION BY so.customer_id
                              ORDER BY so.processed_at, so.order_id) AS seq,
           MIN(so.processed_at) OVER (PARTITION BY so.customer_id) AS first_at
    FROM public.shopify_orders so
    WHERE so.customer_id IS NOT NULL
      AND so.processed_at IS NOT NULL
) x
"""


#: The same statement, writing into the live table instead of a side
#: one. Derived rather than copied: two hand-maintained copies of a
#: 20-line classification query is how they come to disagree.
REBUILD_IN_PLACE = REBUILD.replace(
    "public.order_customer_type_new", "public.order_customer_type")

#: No `_new` table, so no second set of index names to collide with the
#: live ones, and nothing to rename during a swap. That removes the two
#: defects this script carried in sequence: `INCLUDING ALL` cloning
#: indexes under server-generated names (72 exact duplicates and 702 MB
#: of index on 114 MB of data by 2026-10-14), and then the sweep that
#: cleaned them up trying to DROP INDEX a constraint-backed primary key.
#: Publishing in place makes both unreachable rather than handled.


def main() -> int:
    t0 = time.time()
    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '1800s'")
            cur.execute(DDL)
            # PUBLISHED IN PLACE, not rename-swapped.
            #
            # The swap this replaced built `_new`, renamed the live table
            # to `_old`, renamed `_new` into its place and dropped
            # `_old`. That works until something depends on the table --
            # and six materialized views now do, because the
            # meta_direct_* snapshots read is_new_customer from here.
            #
            # A materialized view binds to a table by OID, not by name.
            # The rename therefore leaves every view pointing at
            # `order_customer_type_old`, and the final DROP fails:
            #
            #   cannot drop table order_customer_type_old because other
            #   objects depend on it
            #   DETAIL: materialized view meta_direct_active_30d depends
            #   on table order_customer_type_old   (+5 more)
            #
            # The whole step then rolls back, so the table never
            # refreshes -- it failed on the 2026-10-16 nightly and would
            # have failed every night after. refresh_insights_daily_by_ad
            # hit the same wall and solved it the same way.
            #
            # DELETE rather than TRUNCATE: TRUNCATE takes an ACCESS
            # EXCLUSIVE lock and holds it for the whole insert, which
            # would block every dashboard read for the ~100s this takes.
            # DELETE takes ROW EXCLUSIVE, so readers keep seeing the
            # previous committed rows until this transaction commits and
            # then see the new ones -- the same reasoning
            # app/services/dashboard_sessions.py gives for its own
            # DELETE. The cost is dead tuples, which the ANALYZE below
            # and autovacuum deal with.
            print("[pg] classifying orders ...", flush=True)
            cur.execute("DELETE FROM public.order_customer_type")
            removed = cur.rowcount
            cur.execute(REBUILD_IN_PLACE)
            print(f"[pg] replaced {removed:,} rows with {cur.rowcount:,}", flush=True)

            # Fresh table, no statistics -- the planner would read it as
            # empty until autoanalyze happened to visit.
            cur.execute("ANALYZE public.order_customer_type")
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*), COUNT(DISTINCT customer_id),
                       COUNT(*) FILTER (WHERE is_new_customer),
                       MIN(order_day), MAX(order_day)
                FROM public.order_customer_type
            """)
            n, cust, new, lo, hi = cur.fetchone()
            print(f"\n[OK] order_customer_type in {time.time() - t0:.1f}s")
            print(f"     orders        {n:,}")
            print(f"     customers     {cust:,}")
            print(f"     new-customer  {new:,}  ({new / n * 100:.1f} pct)")
            print(f"     day range     {lo} .. {hi}")
            # new_orders must equal distinct customers, or the partition
            # key is wrong somewhere.
            assert new == cust, f"new orders {new} != distinct customers {cust}"
            print("     check: one first order per customer -- OK")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
