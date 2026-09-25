"""Copy GoKwik's order table from the legacy project into this one.

GoKwik is the checkout layer, so it holds three things Shopify does not
give us and that nothing else in this database can answer:

    Payment Method          COD vs prepaid -- which explains why ~50% of
                            orders sit PENDING in Shopify forever
    Order Shipment Status   whether the order actually reached the buyer
    RTO Risk / Score /      return-to-origin, i.e. revenue that was
    Remark, AWB Number      counted at checkout and never landed

Keyed on the Shopify order id, which GoKwik calls "Merchant Order ID".
Verified unique and numeric across all 326,811 rows. order_gid carries
the gid://shopify/Order/<id> form so it joins straight to
shopify_order_attribution.order_id without a SPLIT_PART on every row.

CUSTOMER PII IS DELIBERATELY NOT COPIED. The source carries name,
phone, email, shipping and billing address; none of it is needed to
analyse attribution or RTO, and copying it would widen its exposure to
a second project for no gain. City and state come across because RTO
varies by region; pincode does not, being far closer to identifying.

UTM 'NA' is normalised to NULL on the way in. GoKwik writes the
literal string where there was no UTM, so left alone it counts as
data: 5,650 orders in one month carried utm_term 'NA', every one of
them utm_source=direct.

Built into a side table and swapped, so readers are never blocked for
longer than the rename. Read in chunks because the Supabase pooler
drops long-running statements.

Usage:
    ./.venv/bin/python scripts/ingest_gokwik_orders.py
    ./.venv/bin/python scripts/ingest_gokwik_orders.py --since 2026-01-01
"""
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

import csv  # noqa: E402
import io  # noqa: E402

DEST = os.environ["DATABASE_URL_SYNC"].replace("postgresql+psycopg2://", "postgresql://").split("?")[0]
SRC = os.environ["SUPABASE_DB_URL"]

CHUNK = 20_000

DDL = """
CREATE TABLE public.gokwik_orders_new (
    order_id                text PRIMARY KEY,
    order_gid               text,
    order_name              text,
    order_date              date,
    utm_source              text,
    utm_medium              text,
    utm_campaign            text,
    utm_term                text,
    utm_content             text,
    grand_total             double precision,
    total_discount          double precision,
    cod_charges             numeric,
    mrp_total               numeric,
    payment_method          text,
    payment_status          text,
    merchant_order_status   text,
    order_shipment_status   text,
    rto_risk                text,
    rto_score               text,
    rto_remark              text,
    awb_number              text,
    customer_type_gokwik    text,
    customer_type_merchant  text,
    billing_city            text,
    billing_state           text,
    coupon_code             text,
    landing_page            text,
    ingested_at             timestamptz NOT NULL DEFAULT now()
)
"""

# "Created At" is D/M/YYYY h:mm AM/PM. A plain ::date cast throws
# "date/time field value out of range" on 20/9/2026, so it is parsed
# with an explicit format behind a regex guard.
DATE_EXPR = "TO_DATE(SPLIT_PART(\"Created At\",' ',1),'DD/FMMM/YYYY')"
DATE_OK = "SPLIT_PART(\"Created At\",' ',1) ~ '^\\d{1,2}/\\d{1,2}/\\d{4}$'"

SELECT = f"""
SELECT "Merchant Order ID"                                  AS order_id,
       'gid://shopify/Order/' || "Merchant Order ID"        AS order_gid,
       "Shopify Order Name"                                 AS order_name,
       {DATE_EXPR}                                          AS order_date,
       NULLIF(NULLIF(BTRIM("Utm Source"),   ''), 'NA')      AS utm_source,
       NULLIF(NULLIF(BTRIM("Utm Medium"),   ''), 'NA')      AS utm_medium,
       NULLIF(NULLIF(BTRIM("Utm Campaign"), ''), 'NA')      AS utm_campaign,
       NULLIF(NULLIF(BTRIM("Utm Term"),     ''), 'NA')      AS utm_term,
       NULLIF(NULLIF(BTRIM("Utm Content"),  ''), 'NA')      AS utm_content,
       "Grand Total"             AS grand_total,
       "Total Discount"          AS total_discount,
       "Cod Charges"             AS cod_charges,
       "MRP Total"               AS mrp_total,
       "Payment Method"          AS payment_method,
       "Payment Status"          AS payment_status,
       "Merchant Order Status"   AS merchant_order_status,
       "Order Shipment Status"   AS order_shipment_status,
       "RTO Risk"                AS rto_risk,
       "RTO Score"               AS rto_score,
       "RTO Remark"              AS rto_remark,
       "AWB Number"              AS awb_number,
       "Customer Type - Gokwik"  AS customer_type_gokwik,
       "Customer Type - Merchant" AS customer_type_merchant,
       "Billing City"            AS billing_city,
       "Billing State"           AS billing_state,
       "Coupon Code"             AS coupon_code,
       "Landing Page"            AS landing_page
  FROM "Gokwik_order_data"
 WHERE {DATE_OK}
   AND {DATE_EXPR} BETWEEN %(since)s::date AND %(until)s::date
   AND "Merchant Order ID" ~ '^[0-9]+$'
   AND "Merchant Order ID" > %(after)s
 ORDER BY "Merchant Order ID"
 LIMIT %(lim)s
"""

#: Target columns for COPY, in the SELECT's order. Named explicitly so
#: a change to either list fails loudly instead of silently shifting
#: every value one column left.
COPY_COLS = [
    "order_id", "order_gid", "order_name", "order_date",
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "grand_total", "total_discount", "cod_charges", "mrp_total",
    "payment_method", "payment_status", "merchant_order_status",
    "order_shipment_status", "rto_risk", "rto_score", "rto_remark",
    "awb_number", "customer_type_gokwik", "customer_type_merchant",
    "billing_city", "billing_state", "coupon_code", "landing_page",
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", default="2026-01-01")
    ap.add_argument("--until", default="2026-09-20")
    args = ap.parse_args()

    t0 = time.time()
    dest = psycopg2.connect(DEST)
    try:
        with dest.cursor() as dc:
            dc.execute("SET statement_timeout = '3600s'")
            dc.execute("DROP TABLE IF EXISTS public.gokwik_orders_new")
            dc.execute(DDL)
        dest.commit()

        # KEYSET pagination, one fresh source connection per chunk.
        #
        # Two earlier shapes failed. LIMIT/OFFSET re-scanned and
        # re-sorted all 326k rows for every page and then discarded the
        # first `off` of them, so cost grew per page and it stalled at
        # 160,000. A server-side cursor fixed that but held the source
        # connection open across the whole read, and the Supabase pooler
        # closed it while it sat idle during a write:
        #     psycopg2.OperationalError: SSL connection has been closed
        #
        # Paginating on the key itself is linear AND needs no long-lived
        # connection, so neither failure applies. "Merchant Order ID" is
        # the primary key here and verified unique, so > last_id can
        # never skip or repeat a row.
        total, after = 0, ""
        while True:
            src = psycopg2.connect(SRC)
            try:
                with src.cursor() as sc:
                    sc.execute("SET statement_timeout = '600s'")
                    sc.execute(SELECT, {"since": args.since, "until": args.until,
                                        "after": after, "lim": CHUNK})
                    rows = sc.fetchall()
            finally:
                src.close()
            if not rows:
                break

            buf = io.StringIO()
            w = csv.writer(buf)
            for r in rows:
                w.writerow(["\\N" if v is None else v for v in r])
            buf.seek(0)
            with dest.cursor() as dc:
                dc.copy_expert(
                    "COPY public.gokwik_orders_new (" + ", ".join(COPY_COLS) + ") "
                    "FROM STDIN WITH (FORMAT csv, NULL '\\N')",
                    buf,
                )
            dest.commit()

            total += len(rows)
            after = rows[-1][0]          # order_id, the sort key
            print(f"  {total:>7,} rows  ({time.time() - t0:>5.0f}s)", flush=True)
            if len(rows) < CHUNK:
                break

        with dest.cursor() as dc:
            print("[pg] indexing ...", flush=True)
            dc.execute("CREATE INDEX ix_gokwik_gid  ON public.gokwik_orders_new(order_gid)")
            dc.execute("CREATE INDEX ix_gokwik_name ON public.gokwik_orders_new(order_name)")
            dc.execute("CREATE INDEX ix_gokwik_date ON public.gokwik_orders_new(order_date)")
            dc.execute("CREATE INDEX ix_gokwik_term ON public.gokwik_orders_new(utm_term)")

            print("[pg] swapping ...", flush=True)
            dc.execute("DROP TABLE IF EXISTS public.gokwik_orders_old")
            dc.execute("ALTER TABLE IF EXISTS public.gokwik_orders RENAME TO gokwik_orders_old")
            # Renaming a table does not rename its indexes, so the old
            # names have to move aside before the new ones claim them.
            for n in ("ix_gokwik_gid", "ix_gokwik_name", "ix_gokwik_date",
                      "ix_gokwik_term", "gokwik_orders_pkey"):
                dc.execute(f"ALTER INDEX IF EXISTS {n} RENAME TO {n}_old")
            dc.execute("ALTER TABLE public.gokwik_orders_new RENAME TO gokwik_orders")
            # The new indexes were created under the canonical names
            # already -- only the PRIMARY KEY constraint index takes the
            # _new suffix from the table it was built on.
            dc.execute("ALTER INDEX IF EXISTS gokwik_orders_new_pkey "
                       "RENAME TO gokwik_orders_pkey")
        dest.commit()
        with dest.cursor() as dc:
            dc.execute("DROP TABLE IF EXISTS public.gokwik_orders_old")
            dc.execute("ANALYZE public.gokwik_orders")
        dest.commit()

        with dest.cursor() as dc:
            dc.execute("SELECT COUNT(*), MIN(order_date), MAX(order_date), "
                       "COUNT(utm_term), COUNT(order_shipment_status) "
                       "FROM public.gokwik_orders")
            n, mn, mx, t, s = dc.fetchone()
    finally:
        dest.close()

    print(f"\n[OK] gokwik_orders ingested in {time.time() - t0:.1f}s")
    print(f"    rows                  : {n:,}")
    print(f"    date range            : {mn} -> {mx}")
    print(f"    with a real utm_term  : {t:,}")
    print(f"    with shipment status  : {s:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
