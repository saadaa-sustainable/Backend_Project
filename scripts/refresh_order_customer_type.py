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


def main() -> int:
    t0 = time.time()
    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '1800s'")
            cur.execute(DDL)
            cur.execute("DROP TABLE IF EXISTS public.order_customer_type_new")
            cur.execute("CREATE TABLE public.order_customer_type_new "
                        "(LIKE public.order_customer_type INCLUDING ALL)")
            print("[pg] classifying orders ...", flush=True)
            cur.execute(REBUILD)
            print(f"[pg] inserted {cur.rowcount:,} rows", flush=True)

            cur.execute("DROP TABLE IF EXISTS public.order_customer_type_old")
            cur.execute("ALTER TABLE public.order_customer_type "
                        "RENAME TO order_customer_type_old")
            cur.execute("ALTER TABLE public.order_customer_type_new "
                        "RENAME TO order_customer_type")
            cur.execute("DROP TABLE IF EXISTS public.order_customer_type_old")
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
