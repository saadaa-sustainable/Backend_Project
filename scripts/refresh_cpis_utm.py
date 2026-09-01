"""Populate cpis_by_sku_utm — Option-A revenue-proportional attribution.

For each order driven by an ad (utm_content -> ad_id):

    for each line item L in the basket:
        line_revenue     = qty × unit_price
        share            = line_revenue / SUM(line_revenue for basket)
        L.ad_spend_share = ad_spend_of_ad_in_window × share

    each L contributes its own qty / revenue AT FACE VALUE to L.master_sku
    (no fractional weighting -- if SMCP sold for 899 in the basket, SMCP
    gets +899 attributed_revenue, +qty attributed_units).

Nice property: because spend follows revenue share, ROAS is identical
across every SKU in a given basket. CPIS / cost-per-order absorbs the
absolute-cost difference between higher- and lower-priced SKUs.

Halo columns (halo_orders, halo_units, halo_revenue, halo_spend) remain
in the schema as placeholders — under Option A every line item is
attributed at face value, so halo has no natural definition yet. When
the halo-mapping approach lands (e.g. via product taxonomy / DPA
product_id / landing collection), those columns can be populated
without another migration.

Runs via psycopg2 sync against DATABASE_URL_SYNC (port 5432).

Usage:
    ./.venv/Scripts/python.exe scripts/refresh_cpis_utm.py
"""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402


DSN = os.environ["DATABASE_URL_SYNC"].replace("postgresql+psycopg2://", "postgresql://")
WINDOWS = {"7d": 7, "30d": 30, "90d": 90}


DDL = """
CREATE TABLE IF NOT EXISTS cpis_by_sku_utm (
    master_sku          text NOT NULL,
    window_key          text NOT NULL,
    window_from         date,
    window_to           date,
    attributed_orders   integer,
    attributed_units    integer,
    attributed_revenue  numeric,
    matched_ad_count    integer,
    ad_spend            numeric,
    cost_per_order      numeric,
    cost_per_unit_sold  numeric,
    roas                numeric,
    computed_at         timestamptz,
    PRIMARY KEY (master_sku, window_key)
)
"""

DDL_MIGRATE = """
ALTER TABLE cpis_by_sku_utm
    ADD COLUMN IF NOT EXISTS halo_orders    integer,
    ADD COLUMN IF NOT EXISTS halo_units     numeric,
    ADD COLUMN IF NOT EXISTS halo_revenue   numeric,
    ADD COLUMN IF NOT EXISTS halo_spend     numeric,
    ADD COLUMN IF NOT EXISTS primary_weight numeric,
    -- Value-weighted spend allocation. ad_spend above uses per-order
    -- equal split; ad_spend_vw uses per-order value-weighted split.
    -- Both columns computed in the same refresh pass.
    ADD COLUMN IF NOT EXISTS ad_spend_vw           numeric,
    ADD COLUMN IF NOT EXISTS cost_per_order_vw     numeric,
    ADD COLUMN IF NOT EXISTS cost_per_unit_sold_vw numeric,
    ADD COLUMN IF NOT EXISTS roas_vw               numeric;
"""


# Step 1: per (ad_id, order_id, master_sku) contribution -- qty, revenue,
# and the order's TOTAL revenue so Python can compute the spend share for
# each line as line_revenue / order_total_revenue.
SQL_STEP1 = """
WITH orders_in_window AS (
  SELECT so.order_id, so.utm_content AS ad_id, so.line_items
  FROM shopify_orders so
  WHERE so.processed_at >= %(window_from)s::date
    AND so.processed_at <  (%(window_to)s::date + integer '1')
    AND so.utm_content ~ '^[0-9]{10,20}$'
    AND EXISTS (SELECT 1 FROM ad_lifecycle al WHERE al.ad_id = so.utm_content)
    AND jsonb_typeof(so.line_items->'edges') = 'array'
),
line_items AS (
  SELECT
    ow.order_id, ow.ad_id,
    (edge->'node'->>'sku')                                          AS variant_sku,
    COALESCE((edge->'node'->>'quantity')::int, 0)                   AS qty,
    COALESCE(
      (edge->'node'->'originalUnitPriceSet'->'shopMoney'->>'amount')::numeric,
      0
    )                                                               AS unit_price
  FROM orders_in_window ow,
       LATERAL jsonb_array_elements(ow.line_items->'edges') edge
  WHERE edge->'node'->>'sku' IS NOT NULL
),
parsed AS (
  SELECT
    order_id, ad_id, variant_sku, qty, unit_price,
    (qty * unit_price)                                                AS line_revenue,
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
  SELECT order_id, ad_id,
         SUM(line_revenue) AS order_total_revenue,
         SUM(qty)          AS order_total_qty
  FROM tagged
  GROUP BY order_id, ad_id
)
SELECT
  t.ad_id, t.order_id, t.master_sku,
  SUM(t.qty)::int          AS qty,
  SUM(t.line_revenue)      AS line_revenue,
  ot.order_total_revenue,
  ot.order_total_qty
FROM tagged t
JOIN order_totals ot USING (order_id, ad_id)
GROUP BY t.ad_id, t.order_id, t.master_sku,
         ot.order_total_revenue, ot.order_total_qty
"""


# Step 2 unchanged: total spend per ad_id from raw_dump_meta insights.
SQL_STEP2 = """
SELECT
  r.raw_payload->>'ad_id' AS ad_id,
  SUM(NULLIF(r.raw_payload->>'spend','')::numeric) AS spend
FROM raw_dump_meta r
WHERE r.object_type = 'insights'
  AND (r.raw_payload->>'date_start')::date >= %(window_from)s
  AND (r.raw_payload->>'date_start')::date <= %(window_to)s
  AND r.raw_payload->>'ad_id' IS NOT NULL
GROUP BY r.raw_payload->>'ad_id'
"""


def _refresh_window(cur, window_key: str, window_from: date, window_to: date) -> int:
    cur.execute("SET LOCAL statement_timeout = '600s'")

    print(f"[{window_key}] step1: (ad, order, sku) lines with basket totals "
          f"({window_from}..{window_to}) ...", flush=True)
    cur.execute(SQL_STEP1, {"window_from": window_from, "window_to": window_to})
    lines = cur.fetchall()
    print(f"[{window_key}]   -> {len(lines)} (ad, order, sku) rows", flush=True)

    print(f"[{window_key}] step2: ad_id -> spend map from insights ...", flush=True)
    cur.execute(SQL_STEP2, {"window_from": window_from, "window_to": window_to})
    spend_map: dict[str, float] = {r[0]: float(r[1] or 0) for r in cur.fetchall()}
    print(f"[{window_key}]   -> {len(spend_map)} distinct ad_ids with spend", flush=True)

    # Compute TWO spend allocations in the same pass:
    #
    #   ad_spend    -- equal per order: per_order_share = A.spend / A.n_orders,
    #                  then within-order share by line-item revenue ratio.
    #                  Each conversion event counts equally regardless of value.
    #
    #   ad_spend_vw -- value-weighted per order: line_spend = A.spend ×
    #                  (line_rev / SUM_of_all_line_revs_for_A). Simplifies
    #                  because per_order_share × within_order_share collapses
    #                  to (line_rev / total_ad_rev). Larger baskets absorb
    #                  proportionally more spend.
    #
    # Both sum to A.spend exactly. Frontend toggle picks which to display.
    ad_order_counts: dict[str, set] = defaultdict(set)
    ad_total_rev:    dict[str, float] = defaultdict(float)
    for ad_id, order_id, _sku, _q, line_rev, _otr, _otq in lines:
        ad_order_counts[ad_id].add(order_id)
        ad_total_rev[ad_id] += float(line_rev or 0)

    sku_agg: dict[str, dict] = defaultdict(lambda: {
        "orders": set(), "units": 0, "revenue": 0.0,
        "ad_spend": 0.0, "ad_spend_vw": 0.0, "ad_ids": set(),
    })
    for ad_id, order_id, master_sku, qty, line_rev, order_total_rev, order_total_qty in lines:
        qty      = int(qty or 0)
        line_rev = float(line_rev or 0)
        order_total_rev = float(order_total_rev or 0)
        order_total_qty = int(order_total_qty or 0)
        agg = sku_agg[master_sku]
        agg["orders"].add(order_id)
        agg["units"]   += qty
        agg["revenue"] += line_rev
        agg["ad_ids"].add(ad_id)

        ad_total_spend  = spend_map.get(ad_id, 0.0)

        # --- equal-per-order allocation ---
        n_orders_for_ad = len(ad_order_counts[ad_id]) or 1
        per_order_share = ad_total_spend / n_orders_for_ad
        if order_total_rev > 0:
            within_order_share = line_rev / order_total_rev
        elif order_total_qty > 0:
            within_order_share = qty / order_total_qty
        else:
            within_order_share = 0.0
        agg["ad_spend"] += per_order_share * within_order_share

        # --- value-weighted allocation ---
        ad_rev_total = ad_total_rev[ad_id]
        if ad_rev_total > 0:
            agg["ad_spend_vw"] += ad_total_spend * (line_rev / ad_rev_total)
        else:
            # Whole ad drove zero revenue -- fall back to the equal-split
            # slice so the two columns stay consistent when there's no
            # signal to weight by.
            agg["ad_spend_vw"] += per_order_share * within_order_share

    rows: list[tuple] = []
    for master_sku, agg in sku_agg.items():
        orders      = len(agg["orders"])
        units       = agg["units"]
        revenue     = agg["revenue"]
        ad_spend    = agg["ad_spend"]
        ad_spend_vw = agg["ad_spend_vw"]
        cost_per_order        = (ad_spend    / orders) if orders else None
        cost_per_unit_sold    = (ad_spend    / units)  if units  else None
        roas                  = (revenue     / ad_spend)    if ad_spend    else None
        cost_per_order_vw     = (ad_spend_vw / orders) if orders else None
        cost_per_unit_sold_vw = (ad_spend_vw / units)  if units  else None
        roas_vw               = (revenue     / ad_spend_vw) if ad_spend_vw else None
        rows.append((
            master_sku, window_key, window_from, window_to,
            orders, units, revenue,
            len(agg["ad_ids"]), ad_spend,
            cost_per_order, cost_per_unit_sold, roas,
            # halo_* remain 0 pending a better halo-mapping approach.
            0, 0, 0.0, 0.0,
            None,  # primary_weight NULL under Option A (deterministic revenue split, not weighted)
            ad_spend_vw, cost_per_order_vw, cost_per_unit_sold_vw, roas_vw,
        ))

    if rows:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO cpis_by_sku_utm (
              master_sku, window_key, window_from, window_to,
              attributed_orders, attributed_units, attributed_revenue,
              matched_ad_count, ad_spend,
              cost_per_order, cost_per_unit_sold, roas,
              halo_orders, halo_units, halo_revenue, halo_spend,
              primary_weight,
              ad_spend_vw, cost_per_order_vw, cost_per_unit_sold_vw, roas_vw,
              computed_at
            ) VALUES %s
            """,
            rows,
            template="(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())",
        )
    print(f"[{window_key}]   -> inserted {len(rows)} rows", flush=True)
    return len(rows)


def main() -> None:
    conn = psycopg2.connect(DSN)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(DDL)
                cur.execute(DDL_MIGRATE)
                cur.execute("""
                    SELECT max((raw_payload->>'date_start')::date)
                    FROM raw_dump_meta
                    WHERE object_type = 'insights'
                """)
                anchor = cur.fetchone()[0]
                if anchor is None:
                    raise RuntimeError("no insights rows in raw_dump_meta")
                print(f"anchor date (max insights date_start): {anchor}", flush=True)

                cur.execute("TRUNCATE cpis_by_sku_utm")
                total = 0
                for window_key, days in WINDOWS.items():
                    window_from = anchor - timedelta(days=days - 1)
                    total += _refresh_window(cur, window_key, window_from, anchor)
                print(f"\ntotal rows: {total}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
