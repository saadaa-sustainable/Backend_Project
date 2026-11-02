"""Rebuild public.inventory_variant_current from Shopify inventory alone.

WHY SHOPIFY ONLY
----------------
`bq_inventory_daily` carries tidy `Color` and `Size` columns, which makes
it the obvious source -- and it is twelve days stale. Shopify is loaded
daily and every product already carries the codes inside its variant
SKU, so the codes are parsed out of the SKU rather than joined in. One
source, one freshness story.

THE SKU GRAMMAR
---------------
    SMCCPBE_2XL      ->  master SMCCP  · colour BE      · size 2XL
    WCFLKBL-CPWH_M   ->  master WCFLK  · colour BL-CPWH · size M

Everything before `_` is the colour SKU. Within it, everything before a
`-` is the garment; a set names a second garment after the dash and the
master is still the first. The last two characters of the garment part
are the colour code -- unless that would leave fewer than four, which is
how a five-character master with no colour code survives intact.

This is string surgery on a human-typed field and it will not be right
forever. `unparsed_reason` records every row it could not read rather
than dropping it silently, because a product that quietly vanishes from
an inventory tracker is worse than one that shows up flagged.

ONE QUANTITY PER SKU
--------------------
A variant SKU can appear under more than one listing -- the same
garment ACTIVE and ARCHIVED. Counting both double-counts the stock, so
exactly one row per SKU survives, the ACTIVE listing preferred. This is
the same rule CPIS uses for Units in Stock, and the two must agree.

WHICH PRODUCTS APPEAR
---------------------
Masters with at least one ACTIVE listing: 82 of them, against 111 if
drafts and archives were included. A draft is not merchandise anyone can
buy, so its empty sizes are not a stock-out.

Usage:
    ./.venv/bin/python scripts/refresh_inventory_tracker.py
    ./.venv/bin/python scripts/refresh_inventory_tracker.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.dbq import connect  # noqa: E402

TABLE = "public.inventory_variant_current"

DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    variant_sku     text PRIMARY KEY,
    colour_sku      text,
    master_sku      text,
    size            text,
    -- The size as written in the SKU suffix. Garments use XS..6XL;
    -- homeware uses its own vocabulary (KFIT, IN PCS), which is why this
    -- is text and not an enum, and why size_rank orders what it can.
    size_rank       smallint,
    units           integer,
    in_stock        boolean,
    -- Negative stock is real: Shopify lets an order oversell. It is NOT
    -- in stock (the rule is > 0), but it is also not the same as zero,
    -- and a buyer needs to see it.
    oversold        boolean,
    product_status  text,
    product_title   text,
    variant_title   text,
    -- NULL when the SKU parsed cleanly.
    unparsed_reason text,
    as_of_date      date NOT NULL,
    refreshed_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_inv_master ON {TABLE} (master_sku);
CREATE INDEX IF NOT EXISTS ix_inv_colour ON {TABLE} (colour_sku);
"""

#: Garment sizes, smallest first, so a size run reads in order rather
#: than alphabetically -- "2XL, 3XL, L, M, S, XL" is not a size run.
SIZE_ORDER = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "2XL", "3XL", "4XL", "5XL", "6XL"]

BUILD = f"""
WITH latest AS (SELECT max(day) AS d FROM public.shopify_inventory),
raw AS (
    SELECT product_variant_sku AS variant_sku, product_status, product_title,
           product_variant_title, ending_inventory_units AS units, latest.d AS as_of
      FROM public.shopify_inventory, latest
     WHERE day = latest.d
       AND product_variant_sku IS NOT NULL
       AND product_variant_sku <> ''
       -- The em-dash is how a missing SKU arrives, not a product.
       AND product_variant_sku <> '—'
),
-- One quantity per SKU, ACTIVE preferred. Without this a garment listed
-- twice contributes its stock twice and the in-stock rate drifts up.
dedup AS (
    SELECT DISTINCT ON (variant_sku) *
      FROM raw
     ORDER BY variant_sku,
              CASE product_status WHEN 'ACTIVE' THEN 0 WHEN 'DRAFT' THEN 1 ELSE 2 END,
              units DESC NULLS LAST
),
parsed AS (
    SELECT d.*,
           split_part(variant_sku, '_', 1) AS colour_sku,
           NULLIF(split_part(variant_sku, '_', 2), '') AS size,
           split_part(split_part(variant_sku, '_', 1), '-', 1) AS garment
      FROM dedup d
),
keyed AS (
    SELECT p.*,
           CASE WHEN length(garment) > 5
                THEN left(garment, length(garment) - 2)
                ELSE garment END AS master_sku,
           CASE
             WHEN variant_sku !~ '^(SD|SM|SU|WC)' THEN 'sku does not start SD/SM/SU/WC'
             WHEN position('_' in variant_sku) = 0 THEN 'no _size suffix'
             WHEN length(garment) < 5 THEN 'garment code shorter than a master sku'
           END AS unparsed_reason
      FROM parsed p
),
-- A master earns a place by having something ACTIVE under it.
active_masters AS (
    SELECT DISTINCT master_sku FROM keyed
     WHERE product_status = 'ACTIVE' AND unparsed_reason IS NULL
)
SELECT k.variant_sku, k.colour_sku, k.master_sku, k.size,
       NULLIF(array_position(ARRAY[{','.join(f"'{s}'" for s in SIZE_ORDER)}], k.size), 0)::smallint,
       k.units::int,
       (k.units > 0) AS in_stock,
       (k.units < 0) AS oversold,
       k.product_status, k.product_title, k.product_variant_title,
       k.unparsed_reason, k.as_of
  FROM keyed k
  LEFT JOIN active_masters a USING (master_sku)
 WHERE a.master_sku IS NOT NULL OR k.unparsed_reason IS NOT NULL
"""

SUMMARY = f"""
SELECT count(*) FILTER (WHERE unparsed_reason IS NULL)                      AS variants,
       count(DISTINCT master_sku) FILTER (WHERE unparsed_reason IS NULL)    AS masters,
       count(DISTINCT colour_sku) FILTER (WHERE unparsed_reason IS NULL)    AS colours,
       count(*) FILTER (WHERE in_stock)                                     AS in_stock,
       count(*) FILTER (WHERE oversold)                                     AS oversold,
       count(*) FILTER (WHERE unparsed_reason IS NOT NULL)                  AS unparsed,
       max(as_of_date)                                                      AS as_of
  FROM {TABLE}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with connect(autocommit=False) as conn, conn.cursor() as cur:
        cur.execute(DDL)
        if args.dry_run:
            cur.execute(f"WITH b AS ({BUILD}) SELECT count(*) FROM b")
            print(f"--dry-run: {cur.fetchone()[0]:,} rows would be written")
            conn.rollback()
            return 0
        # Replaced whole, not upserted: a SKU that leaves Shopify must
        # leave this table too, or it lingers as phantom stock.
        cur.execute(f"TRUNCATE {TABLE}")
        cur.execute(f"""
            INSERT INTO {TABLE} (
                variant_sku, colour_sku, master_sku, size, size_rank, units,
                in_stock, oversold, product_status, product_title,
                variant_title, unparsed_reason, as_of_date)
            {BUILD}""")
        written = cur.rowcount
        cur.execute(SUMMARY)
        cols = [d[0] for d in cur.description]
        s = dict(zip(cols, cur.fetchone()))
        conn.commit()

    print(f"[OK] {written:,} rows  (as of {s['as_of']})")
    print(f"     {s['masters']} masters · {s['colours']} colours · {s['variants']:,} variants")
    rate = 100.0 * s["in_stock"] / s["variants"] if s["variants"] else 0
    print(f"     in stock {s['in_stock']:,} ({rate:.1f}%)")
    if s["oversold"]:
        print(f"     [warn] {s['oversold']} variant(s) oversold (negative units)")
    if s["unparsed"]:
        print(f"     [warn] {s['unparsed']} sku(s) could not be parsed; kept and flagged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
