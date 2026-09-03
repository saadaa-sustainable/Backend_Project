"""refresh_cpis_by_sku_daily.py -- true day-scoped CPIS rollup.

Each row is a self-contained daily P&L slice:
    (master_sku, day, attributed_orders, attributed_units,
     attributed_revenue, matched_ad_count, ad_spend, ad_spend_vw)

For each day D:
  1. Attributed metrics = orders processed on D driven by any UTM-tagged
     ad, rolled up per master_sku.
  2. Ad spend on D = Meta's per-ad-per-day spend for ads that drove
     orders on D. Allocated to master_sku by the same equal-per-order
     and value-weighted rules used in refresh_cpis_utm.py, but restricted
     to that day only. Ads that spent on D but drove no order on D
     contribute to a portfolio-wide unattributed bucket (not stored
     per-SKU) -- honest reconciliation without inventing attribution.

Summing daily rows across any picked window is safe and cheap.
Reconciliation across arbitrary date ranges is direct and by design.

Table:
    public.cpis_by_sku_daily(
        master_sku text, day date,
        attributed_orders int, attributed_units int, attributed_revenue numeric,
        matched_ad_count int, ad_spend numeric, ad_spend_vw numeric
    )

Usage:
    ./.venv/Scripts/python.exe scripts/refresh_cpis_by_sku_daily.py
    ./.venv/Scripts/python.exe scripts/refresh_cpis_by_sku_daily.py --since 2026-01-01
"""
from __future__ import annotations

import argparse
import os
from collections import defaultdict
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402


DSN = os.environ["DATABASE_URL_SYNC"].replace("postgresql+psycopg2://", "postgresql://")
DEFAULT_SINCE = date(2026, 1, 1)


DDL = """
CREATE TABLE IF NOT EXISTS cpis_by_sku_daily (
    master_sku          text NOT NULL,
    day                 date NOT NULL,
    attributed_orders   integer,
    attributed_units    integer,
    attributed_revenue  numeric,
    matched_ad_count    integer,
    ad_spend            numeric,
    ad_spend_vw         numeric,
    -- 2026-09-04 halo columns (basket co-occurrence over Meta-family
    -- traffic). Additive across days -- summing halo_* over a date
    -- range gives the correct total for that range.
    halo_orders         integer DEFAULT 0,
    halo_units          integer DEFAULT 0,
    halo_revenue        numeric DEFAULT 0,
    refreshed_at        timestamptz DEFAULT NOW(),
    PRIMARY KEY (master_sku, day)
);
CREATE INDEX IF NOT EXISTS ix_cbsd_day ON cpis_by_sku_daily(day);
CREATE INDEX IF NOT EXISTS ix_cbsd_sku ON cpis_by_sku_daily(master_sku);
"""

# Existing tables may have been created before the halo columns landed;
# add them idempotently so a fresh install and a legacy install both work.
DDL_MIGRATE = """
ALTER TABLE cpis_by_sku_daily
    ADD COLUMN IF NOT EXISTS halo_orders  integer DEFAULT 0,
    ADD COLUMN IF NOT EXISTS halo_units   integer DEFAULT 0,
    ADD COLUMN IF NOT EXISTS halo_revenue numeric DEFAULT 0
"""


# Meta-family orders since --since -- one row per (order, sku) with
# basket totals so halo_* can be computed per (sku, day). Independent
# of ad attribution (see refresh_cpis_utm.py's SQL_STEP1_HALO for the
# same shape scoped over a fixed window).
SQL_HALO_LINES = """
WITH orders_in_range AS (
  SELECT so.order_id, so.processed_at::date AS order_day, so.line_items
  FROM shopify_orders so
  WHERE so.processed_at >= %(since)s::date
    AND LOWER(TRIM(so.utm_source)) IN (
      'meta','facebook','ig','instagram','fb','igshopping'
    )
    AND jsonb_typeof(so.line_items->'edges') = 'array'
),
line_items AS (
  SELECT
    ow.order_id, ow.order_day,
    (edge->'node'->>'sku') AS variant_sku,
    COALESCE((edge->'node'->>'quantity')::int, 0) AS qty,
    COALESCE(
      (edge->'node'->'originalUnitPriceSet'->'shopMoney'->>'amount')::numeric,
      0
    ) AS unit_price
  FROM orders_in_range ow,
       LATERAL jsonb_array_elements(ow.line_items->'edges') edge
  WHERE edge->'node'->>'sku' IS NOT NULL
),
parsed AS (
  SELECT
    order_id, order_day, variant_sku, qty, unit_price,
    (qty * unit_price) AS line_revenue,
    SUBSTRING(
      regexp_replace(variant_sku, '_[A-Za-z0-9]+$', '')
      FROM 1
      FOR GREATEST(1,
        length(regexp_replace(variant_sku, '_[A-Za-z0-9]+$', '')) - 2
      )
    ) AS master_sku
  FROM line_items
),
tagged AS (
  SELECT * FROM parsed
  WHERE master_sku ~ '^(SD|SM|SU)[A-Z]{1,4}$'
),
order_totals AS (
  SELECT order_id, order_day,
         SUM(line_revenue) AS order_total_revenue,
         SUM(qty)          AS order_total_qty
  FROM tagged GROUP BY order_id, order_day
)
SELECT
  t.order_id, t.order_day, t.master_sku,
  SUM(t.qty)::int      AS qty,
  SUM(t.line_revenue)  AS line_revenue,
  ot.order_total_revenue,
  ot.order_total_qty
FROM tagged t
JOIN order_totals ot USING (order_id, order_day)
GROUP BY t.order_id, t.order_day, t.master_sku,
         ot.order_total_revenue, ot.order_total_qty
"""


# Same shape as refresh_cpis_utm.py but no window filter -- we fetch
# every ad-driven order since --since and bucket by processed_at day.
SQL_LINES = """
WITH orders_in_range AS (
  SELECT so.order_id, so.utm_content AS ad_id,
         so.processed_at::date AS order_day,
         so.line_items
  FROM shopify_orders so
  WHERE so.processed_at >= %(since)s::date
    AND so.utm_content ~ '^[0-9]{10,20}$'
    AND EXISTS (SELECT 1 FROM ad_lifecycle al WHERE al.ad_id = so.utm_content)
    AND jsonb_typeof(so.line_items->'edges') = 'array'
),
line_items AS (
  SELECT
    ow.order_id, ow.ad_id, ow.order_day,
    (edge->'node'->>'sku') AS variant_sku,
    COALESCE((edge->'node'->>'quantity')::int, 0) AS qty,
    COALESCE(
      (edge->'node'->'originalUnitPriceSet'->'shopMoney'->>'amount')::numeric,
      0
    ) AS unit_price
  FROM orders_in_range ow,
       LATERAL jsonb_array_elements(ow.line_items->'edges') edge
  WHERE edge->'node'->>'sku' IS NOT NULL
),
parsed AS (
  SELECT
    order_id, ad_id, order_day, variant_sku, qty, unit_price,
    (qty * unit_price) AS line_revenue,
    SUBSTRING(
      regexp_replace(variant_sku, '_[A-Za-z0-9]+$', '')
      FROM 1
      FOR GREATEST(1,
        length(regexp_replace(variant_sku, '_[A-Za-z0-9]+$', '')) - 2
      )
    ) AS master_sku
  FROM line_items
),
tagged AS (
  SELECT * FROM parsed
  WHERE master_sku ~ '^(SD|SM|SU)[A-Z]{1,4}$'
),
order_totals AS (
  SELECT order_id, ad_id, order_day,
         SUM(line_revenue) AS order_total_revenue,
         SUM(qty)          AS order_total_qty
  FROM tagged GROUP BY order_id, ad_id, order_day
)
SELECT
  t.ad_id, t.order_day, t.order_id, t.master_sku,
  SUM(t.qty)::int      AS qty,
  SUM(t.line_revenue)  AS line_revenue,
  ot.order_total_revenue,
  ot.order_total_qty
FROM tagged t
JOIN order_totals ot USING (order_id, ad_id, order_day)
GROUP BY t.ad_id, t.order_day, t.order_id, t.master_sku,
         ot.order_total_revenue, ot.order_total_qty
"""


# Per-day-per-ad Meta spend, since --since. Anchor for day-scoped allocation.
#
# 2026-09-03 rewrite: reads from public.insights_daily_by_ad (the
# canonical (ad_id, day) silver) instead of re-implementing the
# raw-dedup + range-expansion logic against raw_dump_meta. Single
# source of truth -- when the underlying silver refresh gets fixed,
# this and refresh_cpis_utm.py both pick it up on the next run.
SQL_SPEND_DAILY = """
SELECT ad_id, day, spend
FROM public.insights_daily_by_ad
WHERE day >= %(since)s
  AND ad_id IS NOT NULL
  AND spend > 0
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", default=DEFAULT_SINCE.isoformat(),
                    help=f"Start date (default {DEFAULT_SINCE})")
    args = ap.parse_args()
    since = date.fromisoformat(args.since)

    conn = psycopg2.connect(DSN)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(DDL)
                cur.execute(DDL_MIGRATE)
                cur.execute("SET LOCAL statement_timeout = '900s'")

                print(f"[step 1] pulling (ad, day, order, sku) lines since {since} ...", flush=True)
                cur.execute(SQL_LINES, {"since": since})
                lines = cur.fetchall()
                print(f"          -> {len(lines):,} rows", flush=True)

                print(f"[step 2] pulling (ad, day) -> spend map since {since} ...", flush=True)
                cur.execute(SQL_SPEND_DAILY, {"since": since})
                # spend_map keyed on (ad_id, day) for day-scoped allocation.
                spend_map: dict[tuple[str, date], float] = {}
                for ad_id, day, spend in cur.fetchall():
                    spend_map[(ad_id, day)] = float(spend or 0)
                print(f"          -> {len(spend_map):,} (ad, day) rows", flush=True)

                # Build per-(ad, day) denominators from the SAME lines: number
                # of distinct orders driven that day + total line revenue.
                # This is truly day-scoped: an ad's Wednesday spend is split
                # only across Wednesday's orders.
                ad_day_orders: dict[tuple[str, date], set] = defaultdict(set)
                ad_day_line_rev: dict[tuple[str, date], float] = defaultdict(float)
                for ad_id, order_day, order_id, _sku, _q, line_rev, _otr, _otq in lines:
                    ad_day_orders[(ad_id, order_day)].add(order_id)
                    ad_day_line_rev[(ad_id, order_day)] += float(line_rev or 0)

                # Aggregate by (master_sku, day). Each line's spend
                # allocation lands on its OWN processed_at day.
                agg: dict[tuple[str, date], dict] = defaultdict(lambda: {
                    "orders": set(), "units": 0, "revenue": 0.0,
                    "ad_spend": 0.0, "ad_spend_vw": 0.0, "ad_ids": set(),
                })
                for ad_id, order_day, order_id, master_sku, qty, line_rev, order_total_rev, order_total_qty in lines:
                    qty = int(qty or 0)
                    line_rev = float(line_rev or 0)
                    order_total_rev = float(order_total_rev or 0)
                    order_total_qty = int(order_total_qty or 0)
                    key = (master_sku, order_day)
                    a = agg[key]
                    a["orders"].add(order_id)
                    a["units"]   += qty
                    a["revenue"] += line_rev
                    a["ad_ids"].add(ad_id)

                    # Day-scoped spend: only what this ad spent ON THAT DAY.
                    spend_on_day = spend_map.get((ad_id, order_day), 0.0)
                    if spend_on_day <= 0:
                        # Ad drove an order today but Meta reports no spend
                        # (attribution delay / cross-device). Skip -- no
                        # signal to allocate.
                        continue

                    # equal-per-order (within this ad-day)
                    n_orders_A_D = len(ad_day_orders[(ad_id, order_day)]) or 1
                    per_order_share = spend_on_day / n_orders_A_D
                    if order_total_rev > 0:
                        within_order_share = line_rev / order_total_rev
                    elif order_total_qty > 0:
                        within_order_share = qty / order_total_qty
                    else:
                        within_order_share = 0.0
                    a["ad_spend"] += per_order_share * within_order_share

                    # value-weighted (within this ad-day)
                    ad_day_rev = ad_day_line_rev[(ad_id, order_day)]
                    if ad_day_rev > 0:
                        a["ad_spend_vw"] += spend_on_day * (line_rev / ad_day_rev)
                    else:
                        a["ad_spend_vw"] += per_order_share * within_order_share

                # ─── Halo pass over Meta-family orders (2026-09-04) ────
                # Independent of ad_spend: captures basket co-occurrence
                # over any Meta-sourced order. Aggregated per (sku, day)
                # so summing across a date window is trivial in the
                # endpoint. See refresh_cpis_utm.py SQL_STEP1_HALO for
                # the same shape scoped to a fixed window.
                print(f"[step 2.5] pulling Meta-family basket lines for halo since {since} ...",
                      flush=True)
                cur.execute(SQL_HALO_LINES, {"since": since})
                halo_lines = cur.fetchall()
                print(f"          -> {len(halo_lines):,} (order, sku) rows", flush=True)

                halo_agg: dict[tuple[str, date], dict] = defaultdict(lambda: {
                    "orders": set(), "units": 0, "revenue": 0.0,
                })
                for order_id, order_day, master_sku, qty, line_rev, otr, otq in halo_lines:
                    qty = int(qty or 0)
                    line_rev = float(line_rev or 0)
                    otr = float(otr or 0)
                    otq = int(otq or 0)
                    halo_rev_here   = otr - line_rev
                    halo_units_here = otq - qty
                    if halo_rev_here > 0 or halo_units_here > 0:
                        h = halo_agg[(master_sku, order_day)]
                        h["orders"].add(order_id)
                        h["units"]   += halo_units_here
                        h["revenue"] += halo_rev_here

                rows: list[tuple] = []
                # Union of keys across attributed and halo (a SKU can have
                # halo activity on a day even without attributed orders,
                # and vice versa). Missing side gets zeros.
                all_keys = set(agg.keys()) | set(halo_agg.keys())
                for key in all_keys:
                    master_sku, day = key
                    a = agg.get(key, {
                        "orders": set(), "units": 0, "revenue": 0.0,
                        "ad_spend": 0.0, "ad_spend_vw": 0.0, "ad_ids": set(),
                    })
                    h = halo_agg.get(key, {"orders": set(), "units": 0, "revenue": 0.0})
                    rows.append((
                        master_sku, day,
                        len(a["orders"]), a["units"], a["revenue"],
                        len(a["ad_ids"]), a["ad_spend"], a["ad_spend_vw"],
                        len(h["orders"]), h["units"], h["revenue"],
                    ))

                print(f"[step 3] writing {len(rows):,} (sku, day) rows ...", flush=True)
                cur.execute("TRUNCATE cpis_by_sku_daily")
                psycopg2.extras.execute_values(
                    cur,
                    """
                    INSERT INTO cpis_by_sku_daily (
                      master_sku, day,
                      attributed_orders, attributed_units, attributed_revenue,
                      matched_ad_count, ad_spend, ad_spend_vw,
                      halo_orders, halo_units, halo_revenue
                    ) VALUES %s
                    """,
                    rows,
                    template="(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                )

                cur.execute("SELECT MIN(day), MAX(day), COUNT(DISTINCT master_sku), SUM(ad_spend), SUM(ad_spend_vw) FROM cpis_by_sku_daily")
                mn, mx, n_sku, s_eq, s_vw = cur.fetchone()
                print(f"\n[OK] cpis_by_sku_daily populated")
                print(f"     day range     : {mn} -> {mx}")
                print(f"     distinct SKUs : {n_sku}")
                print(f"     rows          : {len(rows):,}")
                print(f"     total spend eq: Rs {float(s_eq or 0):,.0f}")
                print(f"     total spend vw: Rs {float(s_vw or 0):,.0f}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
