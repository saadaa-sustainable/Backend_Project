"""Materialise (day, master_sku, ad_id) -- which ad drove orders for
which SKU on which day.

/cpis-utm derived this per request, with

    FROM shopify_orders so,
         LATERAL jsonb_array_elements(so.line_items->'edges') edge

over the whole picked window. That detoasts and explodes the line_items
JSONB of every order in range on every single request: 24s of the
endpoint's 26s, for a mapping that only changes when orders arrive.

Same move that insights_daily_by_ad made for the Meta side, and the
same reason.

The SKU parse is copied verbatim from the endpoint so the two cannot
disagree: take the part of line_items[].node.sku before the first
underscore, then drop its last two characters (the size suffix).

Refresh cadence: after every Shopify ingest. Idempotent. Built into a
side table and swapped in, so readers are never blocked for longer than
the rename.

Usage:
    ./.venv/bin/python scripts/refresh_cpis_sku_ad_daily.py
    ./.venv/bin/python scripts/refresh_cpis_sku_ad_daily.py --since 2026-01-01
"""
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

import psycopg2  # noqa: E402

DSN = os.environ["DATABASE_URL_SYNC"].replace("postgresql+psycopg2://", "postgresql://")

DDL = """
CREATE TABLE public.cpis_sku_ad_daily_new (
    day         date NOT NULL,
    master_sku  text NOT NULL,
    ad_id       text NOT NULL,
    refreshed_at timestamptz NOT NULL DEFAULT now()
)
"""

# The endpoint's own predicate and parse, unchanged. utm_content is
# tested with char_length + a negated character class rather than an
# anchored regex because $ / \Z trips SQLAlchemy text() parameter
# scanning in the endpoint, and the two must stay identical.
BUILD = """
INSERT INTO public.cpis_sku_ad_daily_new (day, master_sku, ad_id)
SELECT DISTINCT
    so.processed_at::date AS day,
    SUBSTRING(
        split_part(edge->'node'->>'sku', '_', 1)
        FROM 1
        FOR GREATEST(1, char_length(split_part(edge->'node'->>'sku', '_', 1)) - 2)
    ) AS master_sku,
    so.utm_content AS ad_id
  FROM public.shopify_orders so,
       LATERAL jsonb_array_elements(so.line_items->'edges') edge
 WHERE char_length(so.utm_content) BETWEEN 10 AND 20
   AND so.utm_content !~ '[^0-9]'
   AND edge->'node'->>'sku' IS NOT NULL
   {since_clause}
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", help="Only orders processed on or after this date. "
                                    "Omitted: every order held.")
    args = ap.parse_args()

    t0 = time.time()
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '3600s'")
            print("[pg] building side table ...", flush=True)
            cur.execute("DROP TABLE IF EXISTS public.cpis_sku_ad_daily_new")
            cur.execute(DDL)

            since_clause = ""
            params: dict[str, object] = {}
            if args.since:
                since_clause = "AND so.processed_at >= %(since)s::date"
                params["since"] = args.since
            cur.execute(BUILD.format(since_clause=since_clause), params)
            print(f"[pg] inserted {cur.rowcount:,} rows", flush=True)

            # Indexes after the insert: building them once over the
            # finished table beats maintaining them row by row.
            print("[pg] indexing ...", flush=True)
            cur.execute("ALTER TABLE public.cpis_sku_ad_daily_new "
                        "ADD PRIMARY KEY (day, master_sku, ad_id)")
            cur.execute("CREATE INDEX ix_csad_sku_day_new "
                        "ON public.cpis_sku_ad_daily_new(master_sku, day)")
            cur.execute("CREATE INDEX ix_csad_ad_day_new "
                        "ON public.cpis_sku_ad_daily_new(ad_id, day)")

            # Renaming a table does NOT rename its indexes, so the old
            # table's keep the canonical names and would collide the
            # moment the new ones claim them. Move them aside first, in
            # the same transaction as the swap.
            print("[pg] swapping ...", flush=True)
            cur.execute("DROP TABLE IF EXISTS public.cpis_sku_ad_daily_old")
            cur.execute("ALTER TABLE IF EXISTS public.cpis_sku_ad_daily "
                        "RENAME TO cpis_sku_ad_daily_old")
            for name in ("ix_csad_sku_day", "ix_csad_ad_day", "cpis_sku_ad_daily_pkey"):
                cur.execute(f"ALTER INDEX IF EXISTS {name} RENAME TO {name}_old")

            cur.execute("ALTER TABLE public.cpis_sku_ad_daily_new "
                        "RENAME TO cpis_sku_ad_daily")
            cur.execute("ALTER INDEX ix_csad_sku_day_new RENAME TO ix_csad_sku_day")
            cur.execute("ALTER INDEX ix_csad_ad_day_new RENAME TO ix_csad_ad_day")
            cur.execute("ALTER INDEX IF EXISTS cpis_sku_ad_daily_new_pkey "
                        "RENAME TO cpis_sku_ad_daily_pkey")
            conn.commit()

            cur.execute("DROP TABLE IF EXISTS public.cpis_sku_ad_daily_old")
            cur.execute("ANALYZE public.cpis_sku_ad_daily")
            conn.commit()

            cur.execute("SELECT COUNT(*), COUNT(DISTINCT master_sku), "
                        "       COUNT(DISTINCT ad_id), MIN(day), MAX(day) "
                        "  FROM public.cpis_sku_ad_daily")
            n, skus, ads, mn, mx = cur.fetchone()
    finally:
        conn.close()

    print(f"\n[OK] cpis_sku_ad_daily refreshed in {time.time() - t0:.1f}s")
    print(f"    rows        : {n:,}")
    print(f"    master SKUs : {skus:,}")
    print(f"    ads         : {ads:,}")
    print(f"    date range  : {mn} -> {mx}")


if __name__ == "__main__":
    main()
