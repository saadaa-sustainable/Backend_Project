"""Rebuild public.cpis_sku_context -- the per-master-SKU context the
CPIS table needs on every request but that does not depend on the
request at all.

Why this table exists
---------------------
The /cpis-utm endpoint used to compute all of this inline, as CTEs, on
every single call: a JSONB unnest of the whole Shopify products dump for
stock and prices, plus a 30-day slice of shopify_inventory for velocity.
Neither depends on window, search, sort, pagination or date range -- the
same rows came back for every filter change -- yet they dominated the
query. Measured live 2026-09-04 against Supabase:

    30d slice of shopify_inventory  264,613 rows   10,815 ms  (warm)
    products JSONB unnest             7,642 rows      553 ms
    the page itself (cpis_by_sku_utm)     74 rows        6 ms

So the dashboard was spending eleven seconds rebuilding a 97-row answer
that only changes when the silver layer refreshes. Precomputing it here
takes that cost out of the request path entirely; the endpoint joins 97
rows by primary key instead.

It also fixes a second problem. The endpoint's row set came FROM
cpis_by_sku_utm, which by construction only holds SKUs with at least one
UTM-attributed order -- 74 of the catalogue's 97 in the 30d window. SKUs
with real stock but no attributed orders were invisible. This table is
built from the CATALOGUE, so it is the SKU universe: every master SKU
that exists, whether or not an ad ever drove an order for it. Verified
live: every SKU in cpis_by_sku_daily is present in the catalogue, so
nothing is lost by making the catalogue the universe.

is_live
-------
Of the 97, a dozen are archived with zero stock and nothing sold -- real
rows, but dead ones. `is_live` marks the rest: stock on hand, OR at
least one variant still on an ACTIVE listing, OR units sold in the last
30 days. That third clause is not decoration -- SDFAK and SDVSK carry
zero stock on archived listings yet moved 3 and 51 units in the last 30
days, and both are already in today's 74.

Deliberately NOT "appears anywhere in cpis_by_sku_daily". That is
all-time, and it marked SDFLS/SDFWP/SDLWC live -- archived, empty, 1/0/0
units in 30 days -- because an ad drove an order for them once. Showing
a SKU in the window where it actually traded is the endpoint's job: it
unions in whatever the SELECTED window attributes, so a 90d view still
surfaces a SKU that only sold 60 days ago without a 30d view carrying it
as a permanently dead row.

Grain and semantics are kept byte-for-byte identical to the CTEs this
replaces -- same bundle exclusions, same master-SKU parse, same
per-variant MAX dedupe, same 30-day velocity anchor -- so the numbers on
the dashboard do not move. See app/api/routers/analytics.py for the
originals; if you change one, change both.

Usage:
    ./.venv/Scripts/python.exe scripts/refresh_cpis_sku_context.py
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

import psycopg2  # noqa: E402


DSN = (os.environ.get("DATABASE_URL_SYNC") or os.environ.get("DATABASE_URL") or "").replace(
    "postgresql+psycopg2://", "postgresql://"
).replace("postgresql+asyncpg://", "postgresql://")


DDL = """
CREATE TABLE IF NOT EXISTS public.cpis_sku_context (
    master_sku              text PRIMARY KEY,

    -- products_ctx: price ladder + naming. Excludes "price test"
    -- listings so a duplicate listing at a trial price cannot move the
    -- displayed price, while its STOCK still counts below.
    product_name            text,
    product_type_count      integer,
    variant_count           integer,
    available_variant_count integer,
    price_min               numeric,
    price_max               numeric,

    -- stock_ctx: one Shopify grain for units and both breadth rates.
    units_in_stock          numeric,
    variant_total_ct        integer,
    variant_in_stock_ct     integer,
    variant_in_stock_rate   numeric,
    size_total_ct           integer,
    size_in_stock_ct        integer,
    size_in_stock_rate      numeric,
    stock_by_size           jsonb,

    -- velocity_ctx: trailing 30 days of the shopify_inventory daily grain.
    units_sold_30d          numeric,
    avg_daily_units         numeric,
    variant_days            integer,
    oos_variant_days        integer,
    oos_pct                 numeric,

    -- Provenance shown on the dashboard's Units in Stock tile.
    inventory_as_of         timestamptz,
    velocity_anchor_day     date,

    is_live                 boolean NOT NULL DEFAULT true,
    has_active_variant      boolean NOT NULL DEFAULT false,
    computed_at             timestamptz
)
"""

INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_cpis_sku_context_live ON public.cpis_sku_context (is_live)",
]

#: One statement. Mirrors the CTE chain it replaces, in the same order,
#: so a diff against analytics.py stays readable.
REFRESH = """
WITH product_sku_map AS (
    -- A "price test" listing is a DUPLICATE of the same product at a
    -- different price: same variant SKUs, same physical stock. Flagged,
    -- not excluded -- excluding it threw away real inventory (SMCP read
    -- 1,152 units instead of 8,641). variant_stock dedupes per variant
    -- SKU with MAX, so counting both listings cannot double-count.
    --
    -- The rest stay hard filters: combo / set / "buy any 3" listings are
    -- BUNDLES of different products, so their inventory count is a
    -- bundle count, not this SKU's units.
    SELECT
      r.raw_payload->>'productType' AS product_type,
      lower(coalesce(r.raw_payload->>'productType','')) LIKE '%price test%' AS is_price_test,
      upper(coalesce(r.raw_payload->>'status','')) = 'ACTIVE'              AS is_active,
      r.raw_payload AS p
    FROM raw_dump_shopify r
    WHERE r.object_type = 'products'
      AND lower(coalesce(r.raw_payload->>'productType','')) NOT LIKE '%combo%'
      AND lower(coalesce(r.raw_payload->>'productType','')) NOT LIKE '%bedsheet%'
      AND lower(coalesce(r.raw_payload->>'productType','')) NOT LIKE '%co-ord%'
      AND lower(coalesce(r.raw_payload->>'productType','')) NOT LIKE '%comforter%'
      AND lower(coalesce(r.raw_payload->>'productType','')) NOT LIKE '%buy any 3%'
      AND lower(coalesce(r.raw_payload->>'productType','')) NOT LIKE '% set%'
),
product_variants AS (
    -- Master SKU parsed from the variant SKU: strip the trailing
    -- _<size>, then the 2-char colour code. Byte-for-byte the
    -- derivation cpis_utm.py uses on order line items, so a SKU rolls
    -- up identically on both sides of the join.
    SELECT
      SUBSTRING(
        regexp_replace(edge->'node'->>'sku', '_[A-Za-z0-9]+$', '')
        FROM 1
        FOR GREATEST(1, length(regexp_replace(edge->'node'->>'sku','_[A-Za-z0-9]+$','')) - 2)
      )                                                      AS master_sku,
      psm.product_type,
      psm.is_price_test,
      psm.is_active,
      edge->'node'->>'sku'                                   AS variant_sku,
      (edge->'node'->>'price')::numeric                      AS price,
      coalesce((edge->'node'->>'inventoryQuantity')::int, 0)  AS inv,
      NULLIF(upper((regexp_match(edge->'node'->>'sku', '_([A-Za-z0-9]+)$'))[1]), '') AS size
    FROM product_sku_map psm,
         LATERAL jsonb_array_elements(COALESCE(psm.p->'variants'->'edges','[]'::jsonb)) edge
    WHERE edge->'node'->>'sku' IS NOT NULL
      AND SUBSTRING(
            regexp_replace(edge->'node'->>'sku', '_[A-Za-z0-9]+$', '')
            FROM 1
            FOR GREATEST(1, length(regexp_replace(edge->'node'->>'sku','_[A-Za-z0-9]+$','')) - 2)
          ) ~ '^(SD|SM|SU)[A-Z]{1,4}$'
),
variant_stock AS (
    -- MAX per variant SKU, not SUM: the same variant appears under both
    -- the normal and the price-test listing, pointing at ONE physical
    -- stock figure.
    SELECT master_sku, variant_sku,
           MAX(GREATEST(inv, 0))         AS units,
           MAX(size)                     AS size,
           bool_or(is_active)            AS is_active
    FROM product_variants
    GROUP BY master_sku, variant_sku
),
products_ctx AS (
    SELECT
      master_sku,
      (ARRAY_AGG(product_type ORDER BY length(product_type)))[1] AS product_name,
      COUNT(DISTINCT product_type)                              AS product_type_count,
      COUNT(DISTINCT variant_sku)                               AS variant_count,
      COUNT(DISTINCT variant_sku) FILTER (WHERE inv > 0)        AS available_variant_count,
      MIN(price)                                                AS price_min,
      MAX(price)                                                AS price_max
    FROM product_variants
    WHERE NOT is_price_test
    GROUP BY master_sku
),
stock_ctx AS (
    SELECT
      master_sku,
      SUM(units)                                    AS units_in_stock,
      COUNT(*)                                      AS variant_total_ct,
      COUNT(*) FILTER (WHERE units > 0)             AS variant_in_stock_ct,
      CASE WHEN COUNT(*) > 0
           THEN ROUND(100.0 * (COUNT(*) FILTER (WHERE units > 0))::numeric
                      / COUNT(*)::numeric, 1) END   AS variant_in_stock_rate,
      COUNT(DISTINCT size)                          AS size_total_ct,
      COUNT(DISTINCT size) FILTER (WHERE units > 0) AS size_in_stock_ct,
      CASE WHEN COUNT(DISTINCT size) > 0
           THEN ROUND(100.0 * (COUNT(DISTINCT size) FILTER (WHERE units > 0))::numeric
                      / COUNT(DISTINCT size)::numeric, 1) END AS size_in_stock_rate,
      bool_or(is_active)                            AS has_active_variant
    FROM variant_stock
    GROUP BY master_sku
),
stock_by_size_ctx AS (
    SELECT master_sku, jsonb_object_agg(size, units) AS stock_by_size
    FROM (
      SELECT master_sku, size, SUM(units)::int AS units
      FROM variant_stock
      WHERE size IS NOT NULL
      GROUP BY master_sku, size
    ) t
    GROUP BY master_sku
),
inv_window AS (
    SELECT MAX(day) AS anchor_day FROM shopify_inventory
),
products_as_of AS (
    SELECT MAX(extracted_at) AS inventory_as_of
    FROM raw_dump_shopify WHERE object_type = 'products'
),
inv_daily AS (
    SELECT vs.master_sku,
           COALESCE(si.inventory_units_sold, 0)   AS units_sold,
           COALESCE(si.ending_inventory_units, 0) AS ending_units
    FROM shopify_inventory si
    JOIN variant_stock vs ON vs.variant_sku = si.product_variant_sku
    CROSS JOIN inv_window w
    WHERE si.day >= w.anchor_day - 29
      AND si.day <= w.anchor_day
),
velocity_ctx AS (
    SELECT
      master_sku,
      SUM(units_sold)                          AS units_sold_30d,
      SUM(units_sold)::numeric / 30.0          AS avg_daily_units,
      COUNT(*)                                 AS variant_days,
      COUNT(*) FILTER (WHERE ending_units <= 0) AS oos_variant_days,
      CASE WHEN COUNT(*) > 0
           THEN ROUND(100.0 * (COUNT(*) FILTER (WHERE ending_units <= 0))::numeric
                      / COUNT(*)::numeric, 1) END AS oos_pct
    FROM inv_daily
    GROUP BY master_sku
)
INSERT INTO public.cpis_sku_context (
    master_sku, product_name, product_type_count, variant_count,
    available_variant_count, price_min, price_max,
    units_in_stock, variant_total_ct, variant_in_stock_ct, variant_in_stock_rate,
    size_total_ct, size_in_stock_ct, size_in_stock_rate, stock_by_size,
    units_sold_30d, avg_daily_units, variant_days, oos_variant_days, oos_pct,
    inventory_as_of, velocity_anchor_day, is_live, has_active_variant, computed_at
)
SELECT
    sc.master_sku,
    pc.product_name, pc.product_type_count, pc.variant_count,
    pc.available_variant_count, pc.price_min, pc.price_max,
    sc.units_in_stock, sc.variant_total_ct, sc.variant_in_stock_ct, sc.variant_in_stock_rate,
    sc.size_total_ct, sc.size_in_stock_ct, sc.size_in_stock_rate, sbs.stock_by_size,
    vc.units_sold_30d, vc.avg_daily_units, vc.variant_days, vc.oos_variant_days, vc.oos_pct,
    (SELECT inventory_as_of FROM products_as_of),
    (SELECT anchor_day FROM inv_window),
    -- is_live: on hand, still listed, or still selling. The third
    -- clause is what keeps a sold-out-but-trading SKU visible -- SDFAK
    -- and SDVSK carry zero stock on an archived listing yet moved 3 and
    -- 51 units in the last 30 days, and both are already in today's 74.
    --
    -- Deliberately NOT "appears anywhere in cpis_by_sku_daily": that is
    -- all-time, so it resurrected SDFLS/SDFWP/SDLWC -- archived, empty,
    -- and 1/0/0 units in 30 days -- purely because an ad drove an order
    -- for them once. Per-window visibility is the endpoint's job: it
    -- unions in whatever the SELECTED window attributes, so a 90d view
    -- still shows a SKU that only traded 60 days ago without a 30d view
    -- carrying it as a permanently dead row.
    (COALESCE(sc.units_in_stock, 0) > 0
     OR COALESCE(sc.has_active_variant, false)
     OR COALESCE(vc.units_sold_30d, 0) > 0) AS is_live,
    COALESCE(sc.has_active_variant, false) AS has_active_variant,
    now()
FROM stock_ctx sc
LEFT JOIN products_ctx       pc  USING (master_sku)
LEFT JOIN stock_by_size_ctx  sbs USING (master_sku)
LEFT JOIN velocity_ctx       vc  USING (master_sku)
"""


def main() -> int:
    if not DSN:
        raise SystemExit("Set DATABASE_URL_SYNC (or DATABASE_URL) first.")
    t0 = time.time()
    conn = psycopg2.connect(DSN)
    try:
        with conn, conn.cursor() as cur:
            # The 30-day shopify_inventory join is the expensive half and
            # measured ~11s on live data; the DB default ceiling is 120s,
            # which is enough today but not with room to spare as the
            # table grows. SET LOCAL, not SET -- Supavisor pools in
            # transaction mode.
            cur.execute("SET LOCAL statement_timeout = '600s'")
            cur.execute("SET LOCAL work_mem = '64MB'")
            cur.execute(DDL)
            for statement in INDEXES:
                cur.execute(statement)
            # TRUNCATE + INSERT in ONE transaction: a failure rolls back
            # to the previous good snapshot rather than leaving the
            # dashboard with an empty SKU universe.
            cur.execute("TRUNCATE public.cpis_sku_context")
            cur.execute(REFRESH)
            written = cur.rowcount
            cur.execute("SELECT COUNT(*) FILTER (WHERE is_live), COUNT(*) "
                        "FROM public.cpis_sku_context")
            live, total = cur.fetchone()
        print(f"cpis_sku_context: {written} rows written "
              f"({live} live, {total - live} archived/empty) in {time.time() - t0:.1f}s")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
