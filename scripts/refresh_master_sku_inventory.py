"""Rebuild public.master_sku_inventory_current from bq_inventory_daily.

Takes the latest date's snapshot per variant SKU, parses the master SKU
(same regex as app/services/gold/cpis.py: strip trailing _<size>, then
strip 2-char color code, validate ^(SD|SM|SU)[A-Z]{1,4}$), then rolls
metrics up per master SKU using MapleMonk's own aggregation semantics:

    SUM  -- current_stock, total_inprogress, daily_quantity,
            t7/t45/t730/t73015_quantity, total_sales_in_45d
            (physical counts add across variants)
    AVG  -- doq_* (DoQ is a per-variant rate, so mean-across-variants
            is the correct family-level number)
    MAX  -- oos_days_* (worst-case OOS days across variants),
            Lead_Time, Buffer_Days (most conservative)
    MIN/MAX -- cost, shopify_sp (price range across variants)
    COUNT -- variant_ct (distinct SKUs under this master)

These rules mirror CTD's refresh_product_doq.py.

Usage:
    ./.venv/Scripts/python.exe scripts/refresh_master_sku_inventory.py
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)

import psycopg2  # noqa: E402


DDL = """
CREATE TABLE IF NOT EXISTS public.master_sku_inventory_current (
    master_sku      text        NOT NULL PRIMARY KEY,
    as_of_date      date        NOT NULL,
    variant_ct      integer,
    -- Physical stock (sums)
    current_stock   bigint,
    total_inprogress bigint,
    -- Sales velocity (sums)
    daily_quantity  numeric,
    t7_quantity     numeric,
    t45_quantity    numeric,
    t730_quantity   numeric,
    total_sales_45d numeric,
    -- DoQ (avg across variants -- per-variant rate). Every DoQ variant
    -- from MapleMonk is surfaced here so the merchant can pick their
    -- planning horizon: short (7/15 for near-term reactivity), medium
    -- (30/45 for monthly planning), long (90/365 for seasonal). The
    -- 7_30 / 30_45 ratios flag velocity trend changes; v_doq and
    -- weighted variants are MapleMonk's own recommendation signals.
    doq_7           numeric,
    doq_15          numeric,
    doq_30          numeric,
    doq_45          numeric,
    doq_90          numeric,
    doq_365         numeric,
    doq_7_30        numeric,
    doq_30_45       numeric,
    weighted_doq_45 numeric,
    weightage_doq   numeric,
    monthly_doq     numeric,
    yearly_doq      numeric,
    v_doq           numeric,
    -- OOS days (max across variants -- worst case)
    oos_days_7      integer,
    oos_days_15     integer,
    oos_days_30     integer,
    oos_days_45     integer,
    oos_days_90     integer,
    oos_days_365    integer,
    -- Ops (max = most conservative)
    lead_time       integer,
    buffer_days     integer,
    -- Pricing range across variants
    cost_min        numeric,
    cost_max        numeric,
    shopify_sp_min  numeric,
    shopify_sp_max  numeric,
    -- In-stock breadth (2026-09-02). Both are 0-100 percentages so
    -- they render as-is in the UI without extra formatting:
    --   variant_in_stock_rate: fraction of the SKU's variants a
    --     customer can actually buy right now (variants with
    --     current_stock > 0 / total variants).
    --   size_in_stock_rate: fraction of DISTINCT sizes still
    --     available at all -- e.g., pant sizes S/M/L/XL and S+M
    --     out of stock -> 50%. Sensitive to size-run gaps that
    --     variant_in_stock_rate can hide.
    variant_in_stock_ct   integer,
    variant_in_stock_rate numeric,
    size_total_ct         integer,
    size_in_stock_ct      integer,
    size_in_stock_rate    numeric,
    -- Per-size stock breakdown as {"XS":12, "S":65, ..., "5XL":0}.
    -- JSONB keeps this flexible for products with non-standard size
    -- vocabularies (numeric sizes, one-size, etc.) without a schema
    -- change per format. NULL = no size-tagged variants at all.
    stock_by_size   jsonb,
    refreshed_at    timestamptz DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_msi_as_of ON public.master_sku_inventory_current(as_of_date);
"""


# BigQuery column names preserve the source's PascalCase / camelCase, so
# fields like RM_code, Product_Variant, Lead_Time need double-quoting.
# Refer to columns via their BQ names verbatim.
REBUILD_SQL = """
WITH latest_per_variant AS (
    -- One row per variant SKU, using its most recent snapshot within the
    -- window bq_inventory_daily currently holds. If the fetch pulled
    -- last-90-days-only, this is that variant's freshest state.
    SELECT DISTINCT ON (sku)
        sku,
        date_day,
        "current_stock",
        "total_inprogress",
        "daily_quantity",
        "t7_quantity",
        "t45_quantity",
        "t730_quantity",
        "total_sales_in_last_45_inventory_days" AS t45_inv_sales,
        "doq_7", "doq_15", "doq_30", "doq_45", "doq_90", "doq_365",
        "doq_7_30", "doq_30_45",
        "weighted_doq_45", "weightage_doq", "monthly_doq", "yearly_doq", "v_doq",
        "oos_days_7", "oos_days_15", "oos_days_30",
        "oos_days_45", "oos_days_90", "oos_days_365",
        "Lead_Time" AS lead_time,
        "Buffer_Days" AS buffer_days,
        "cost",
        "shopify_sp",
        "Size" AS size
    FROM public.bq_inventory_daily
    WHERE sku IS NOT NULL
    ORDER BY sku, date_day DESC
),
parsed AS (
    -- Parse master SKU. MapleMonk concatenates the size suffix without
    -- an underscore separator (SDCPBL_S in Shopify becomes SDCPBLS in
    -- MapleMonk), so strip an explicit size-alphabet suffix first, then
    -- strip the 2-char color code. Validated against ^(SD|SM|SU)[A-Z]{1,4}$
    -- to drop non-conforming SKUs (fabric side, raw material, etc.).
    -- Size alternation ordered longest-first so PostgreSQL's POSIX ERE
    -- leftmost-longest matching picks 3XL over XL, etc.
    SELECT
        SUBSTRING(
            regexp_replace(sku, '(6XL|5XL|4XL|3XL|2XL|XXL|XXS|XL|XS|S|M|L)$', '')
            FROM 1
            FOR GREATEST(1,
                length(regexp_replace(sku, '(6XL|5XL|4XL|3XL|2XL|XXL|XXS|XL|XS|S|M|L)$', '')) - 2
            )
        ) AS master_sku,
        *
    FROM latest_per_variant
)
INSERT INTO public.master_sku_inventory_current (
    master_sku, as_of_date, variant_ct,
    current_stock, total_inprogress,
    daily_quantity, t7_quantity, t45_quantity, t730_quantity, total_sales_45d,
    doq_7, doq_15, doq_30, doq_45, doq_90, doq_365,
    doq_7_30, doq_30_45,
    weighted_doq_45, weightage_doq, monthly_doq, yearly_doq, v_doq,
    oos_days_7, oos_days_15, oos_days_30,
    oos_days_45, oos_days_90, oos_days_365,
    lead_time, buffer_days,
    cost_min, cost_max, shopify_sp_min, shopify_sp_max,
    variant_in_stock_ct, variant_in_stock_rate,
    size_total_ct, size_in_stock_ct, size_in_stock_rate
)
SELECT
    master_sku,
    MAX(date_day) AS as_of_date,
    COUNT(DISTINCT sku)                AS variant_ct,
    SUM(current_stock)                 AS current_stock,
    SUM(total_inprogress)              AS total_inprogress,
    SUM(daily_quantity)                AS daily_quantity,
    SUM(t7_quantity)                   AS t7_quantity,
    SUM(t45_quantity)                  AS t45_quantity,
    SUM(t730_quantity)                 AS t730_quantity,
    SUM(t45_inv_sales)                 AS total_sales_45d,
    AVG(doq_7)                         AS doq_7,
    AVG(doq_15)                        AS doq_15,
    AVG(doq_30)                        AS doq_30,
    AVG(doq_45)                        AS doq_45,
    AVG(doq_90)                        AS doq_90,
    AVG(doq_365)                       AS doq_365,
    AVG(doq_7_30)                      AS doq_7_30,
    AVG(doq_30_45)                     AS doq_30_45,
    AVG(weighted_doq_45)               AS weighted_doq_45,
    AVG(weightage_doq)                 AS weightage_doq,
    AVG(monthly_doq)                   AS monthly_doq,
    AVG(yearly_doq)                    AS yearly_doq,
    AVG(v_doq)                         AS v_doq,
    MAX(oos_days_7)                    AS oos_days_7,
    MAX(oos_days_15)                   AS oos_days_15,
    MAX(oos_days_30)                   AS oos_days_30,
    MAX(oos_days_45)                   AS oos_days_45,
    MAX(oos_days_90)                   AS oos_days_90,
    MAX(oos_days_365)                  AS oos_days_365,
    MAX(lead_time)                     AS lead_time,
    MAX(buffer_days)                   AS buffer_days,
    MIN(cost)                          AS cost_min,
    MAX(cost)                          AS cost_max,
    MIN(shopify_sp)                    AS shopify_sp_min,
    MAX(shopify_sp)                    AS shopify_sp_max,
    -- In-stock breadth. FILTER (WHERE current_stock > 0) is Postgres's
    -- inline conditional aggregate -- more efficient than a subquery
    -- and reads clearly. Rates are 0-100 percentages rounded to 1dp so
    -- they render without extra frontend formatting.
    COUNT(*) FILTER (WHERE current_stock > 0)::int         AS variant_in_stock_ct,
    CASE WHEN COUNT(*) > 0
         THEN ROUND(100.0 * (COUNT(*) FILTER (WHERE current_stock > 0))::numeric
                    / COUNT(*)::numeric, 1)
         END                                               AS variant_in_stock_rate,
    COUNT(DISTINCT size)::int                              AS size_total_ct,
    COUNT(DISTINCT size) FILTER (WHERE current_stock > 0)::int AS size_in_stock_ct,
    CASE WHEN COUNT(DISTINCT size) > 0
         THEN ROUND(100.0 * (COUNT(DISTINCT size) FILTER (WHERE current_stock > 0))::numeric
                    / COUNT(DISTINCT size)::numeric, 1)
         END                                               AS size_in_stock_rate
FROM parsed
WHERE master_sku ~ '^(SD|SM|SU)[A-Z]{1,4}$'
GROUP BY master_sku
"""


# Second pass: build the per-size stock JSON per master_sku. Done as a
# separate UPDATE because rolling up "per-size sum" is a nested
# aggregation (SUM inside jsonb_object_agg) that fights the main
# INSERT's GROUP BY master_sku. Keeping it a plain follow-up UPDATE
# keeps the main SQL readable and costs nothing at 105 SKUs.
STOCK_BY_SIZE_SQL = """
WITH latest_per_variant AS (
    SELECT DISTINCT ON (sku)
        sku,
        "current_stock" AS current_stock,
        "Size" AS size
    FROM public.bq_inventory_daily
    WHERE sku IS NOT NULL
    ORDER BY sku, date_day DESC
),
parsed AS (
    SELECT
        SUBSTRING(
            regexp_replace(sku, '(6XL|5XL|4XL|3XL|2XL|XXL|XXS|XL|XS|S|M|L)$', '')
            FROM 1
            FOR GREATEST(1,
                length(regexp_replace(sku, '(6XL|5XL|4XL|3XL|2XL|XXL|XXS|XL|XS|S|M|L)$', '')) - 2
            )
        ) AS master_sku,
        current_stock, size
    FROM latest_per_variant
),
size_stock AS (
    SELECT master_sku, size, SUM(current_stock)::int AS stock
    FROM parsed
    WHERE master_sku ~ '^(SD|SM|SU)[A-Z]{1,4}$' AND size IS NOT NULL
    GROUP BY master_sku, size
),
size_agg AS (
    SELECT master_sku, jsonb_object_agg(size, stock) AS agg
    FROM size_stock
    GROUP BY master_sku
)
UPDATE public.master_sku_inventory_current m
SET stock_by_size = sa.agg
FROM size_agg sa
WHERE m.master_sku = sa.master_sku
"""


def _pg_dsn() -> str:
    return os.environ["DATABASE_URL_SYNC"].replace("postgresql+psycopg2://", "postgresql://")


def main() -> None:
    t0 = time.time()
    conn = psycopg2.connect(_pg_dsn())
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL statement_timeout = '600s'")
                # Full recreate so schema changes (e.g. new DoQ columns
                # added over time) apply without a manual migration.
                cur.execute("DROP TABLE IF EXISTS public.master_sku_inventory_current")
                cur.execute(DDL)
                cur.execute(REBUILD_SQL)
                cur.execute(STOCK_BY_SIZE_SQL)
                cur.execute(
                    "SELECT COUNT(*), MIN(as_of_date), MAX(as_of_date), "
                    "SUM(variant_ct), SUM(current_stock) "
                    "FROM public.master_sku_inventory_current"
                )
                n, mn, mx, tot_var, tot_stock = cur.fetchone()
    finally:
        conn.close()

    dt = time.time() - t0
    print(f"[OK] master_sku_inventory_current rebuilt in {dt:.1f}s")
    print(f"    master SKUs      : {n:,}")
    print(f"    as_of range      : {mn} -> {mx}")
    print(f"    total variants   : {tot_var:,}")
    print(f"    total stock (u)  : {tot_stock:,}")


if __name__ == "__main__":
    main()
