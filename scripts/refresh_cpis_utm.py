"""Populate cpis_by_sku_utm -- landing-page (URL-pooled) attribution.

    1. Spend of every ad pointing at a page is pooled per page (the ad's
       landing URL in ad_media, normalised by page_path).
    2. Last-click ad orders (utm_content -> a Meta ad) share the spend of
       the page their Shopify full_url landed on: equally per order
       (ad_spend) or by order value (ad_spend_vw).
    3. Inside an order the share goes to its line items by line value,
       each line counted at face value for its master SKU.

So a homepage, collection or campaign page (/collections/diwali-special/men)
needs no product map: the orders say what was bought. Rs 0 lines (free
gifts) are not items. Orders on a page with no ad spend are left out;
spend on a page with no order, or on an ad with no store URL, stays
unattributed. Both are printed per window.

Halo = the rest of the basket (same orders), so per SKU
attributed_revenue + halo_revenue = order_revenue. halo_spend stays 0:
spend is already spread over every line.

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

import sys  # noqa: E402

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.gold.cpis import page_path  # noqa: E402


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
    ADD COLUMN IF NOT EXISTS order_revenue  numeric,
    ADD COLUMN IF NOT EXISTS order_units    integer,
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
  -- Last-click ad orders: utm_content names a Meta ad we know. full_url is
  -- the landing URL GoKwik records at checkout (on every such order); it
  -- decides which URL's spend the order shares.
  SELECT so.order_id, so.utm_content AS ad_id, so.line_items,
         (SELECT a->>'value' FROM jsonb_array_elements(so.custom_attributes) a
           WHERE a->>'key' = 'full_url' LIMIT 1)                  AS full_url
  FROM shopify_orders so
  -- IST, because Meta reports its days in the ad account's timezone
  -- (Asia/Kolkata on all three accounts). Expressed as timestamptz BOUNDS
  -- rather than by transforming every row, so the index on processed_at
  -- is still usable (the cast form took this query to over nine minutes).
  WHERE so.processed_at >= (%(window_from)s::date::timestamp
                              AT TIME ZONE 'Asia/Kolkata')
    AND so.processed_at <  ((%(window_to)s::date + 1)::timestamp
                              AT TIME ZONE 'Asia/Kolkata')
    AND so.utm_content ~ '^[0-9]{10,20}$'
    AND EXISTS (SELECT 1 FROM ad_lifecycle al WHERE al.ad_id = so.utm_content)
    -- Cancelled orders are out, per the CPIS spec. VOIDED is the signal:
    -- every VOIDED order is UNFULFILLED. PENDING is COD awaiting payment
    -- and stays; REFUNDED stays too (gross units).
    AND COALESCE(so.financial_status, '') <> 'VOIDED'
    AND jsonb_typeof(so.line_items->'edges') = 'array'
    AND jsonb_typeof(so.custom_attributes) = 'array'
),
line_items AS (
  SELECT
    ow.order_id, ow.ad_id, ow.full_url,
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
    order_id, ad_id, full_url, variant_sku, qty, unit_price,
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
  -- Free gifts (the silver coin, Rs 0) are not items sold: they would
  -- add units at no cost and pull every cost per item down.
  SELECT * FROM parsed
  WHERE master_sku ~ '^(SD|SM|SU)[A-Z]{1,4}$' AND unit_price > 0
)
-- Basket totals by window function, not a join back to a per-order
-- aggregate: the planner guessed 1 row for each side and nested-looped
-- them, which grew with the square of the window and timed out on 90d.
SELECT
  full_url, ad_id, order_id, master_sku,
  SUM(qty)::int                                       AS qty,
  SUM(line_revenue)                                   AS line_revenue,
  SUM(SUM(line_revenue)) OVER (PARTITION BY order_id) AS order_total_revenue,
  SUM(SUM(qty))          OVER (PARTITION BY order_id) AS order_total_qty
FROM tagged
GROUP BY full_url, ad_id, order_id, master_sku
"""


# Spend per ad landing URL. Python normalises each URL to its page and
# pools the ads that share one.
SQL_STEP2 = """
SELECT m.landing_page_url, SUM(i.spend) AS spend
FROM public.insights_daily_by_ad i
LEFT JOIN public.ad_media m USING (ad_id)
WHERE i.day BETWEEN %(window_from)s AND %(window_to)s
  AND i.spend > 0
GROUP BY 1
"""


def pool_spend_by_page(rows) -> tuple[dict[str, float], float]:
    """(landing_url, spend) rows -> spend per store page, plus the spend
    on ads with no URL or one off the store, which no order can match."""
    pooled: dict[str, float] = defaultdict(float)
    lost = 0.0
    for url, spend in rows:
        page = page_path(url)
        if page in (None, "OFFSITE"):
            lost += float(spend or 0)
        else:
            pooled[page] += float(spend or 0)
    return dict(pooled), lost


def _refresh_window(cur, window_key: str, window_from: date, window_to: date) -> int:
    cur.execute("SET LOCAL statement_timeout = '600s'")

    print(f"[{window_key}] step1: (ad, order, sku) lines with basket totals "
          f"({window_from}..{window_to}) ...", flush=True)
    cur.execute(SQL_STEP1, {"window_from": window_from, "window_to": window_to})
    raw = cur.fetchall()
    print(f"[{window_key}]   -> {len(raw)} (order, sku) rows", flush=True)

    print(f"[{window_key}] step2: landing URL -> spend map from insights ...", flush=True)
    cur.execute(SQL_STEP2, {"window_from": window_from, "window_to": window_to})
    spend_map, lost = pool_spend_by_page(cur.fetchall())
    print(f"[{window_key}]   -> {len(spend_map)} pages with spend; "
          f"Rs {lost:,.0f} on ads with no store URL stays unattributed", flush=True)

    # Each order shares the spend of the page it landed on. An order whose
    # page had no ad spend is left out: counting it would add units at no
    # cost and make its products look cheaper than they are.
    lines = [(page_path(u), *rest) for u, *rest in raw]
    kept = [ln for ln in lines if ln[0] in spend_map]
    sold_on = {ln[0] for ln in kept}
    print(f"[{window_key}]   -> {len({ln[2] for ln in lines}) - len({ln[2] for ln in kept})} "
          f"orders landed on a page with no spend (left out); "
          f"Rs {sum(v for k, v in spend_map.items() if k not in sold_on):,.0f} "
          f"on pages with no order", flush=True)
    lines = kept

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
    for page, _ad, order_id, _sku, _q, line_rev, _otr, _otq in lines:
        ad_order_counts[page].add(order_id)
        ad_total_rev[page] += float(line_rev or 0)

    sku_agg: dict[str, dict] = defaultdict(lambda: {
        "orders": set(), "units": 0, "revenue": 0.0,
        "ad_spend": 0.0, "ad_spend_vw": 0.0, "ad_ids": set(),
        # 2026-09-04 halo columns (basket co-occurrence). For each SKU
        # in a MIXED basket (2+ distinct master SKUs), halo_units and
        # halo_revenue are the units/revenue of the OTHER SKUs in the
        # same order:
        #     halo_units_this_order = order_total_qty - this_sku_qty
        #     halo_rev_this_order   = order_total_revenue - this_sku_line_rev
        # halo_orders counts distinct orders that contributed halo.
        # halo_spend intentionally stays 0 -- spend is already
        # fractionally distributed across the basket by ad_spend /
        # ad_spend_vw, so charging halo_spend on top would double-count.
        "halo_orders": set(), "halo_units": 0, "halo_revenue": 0.0,
        # Basket value of the orders this SKU appeared in, counted ONCE
        # per order. `revenue` above is the SKU's own lines only; this is
        # the whole order, so it is what an average ORDER value must
        # divide. Keyed by order_id because a SKU can appear on several
        # lines of one order and the basket must not be added twice.
        "order_revenue_by_order": {},
        # Total units in those baskets, once per order -- the unit-count
        # twin of order_revenue. attributed_units counts only this SKU.
        "order_units_by_order": {},
    })
    for page, ad_id, order_id, master_sku, qty, line_rev, order_total_rev, order_total_qty in lines:
        qty      = int(qty or 0)
        line_rev = float(line_rev or 0)
        order_total_rev = float(order_total_rev or 0)
        order_total_qty = int(order_total_qty or 0)
        agg = sku_agg[master_sku]
        agg["orders"].add(order_id)
        agg["order_revenue_by_order"][order_id] = order_total_rev
        agg["order_units_by_order"][order_id] = order_total_qty
        agg["units"]   += qty
        agg["revenue"] += line_rev
        agg["ad_ids"].add(ad_id)

        # HALO: the rest of the basket, from these same mapped orders.
        #
        # This briefly ran over all Meta-family traffic instead -- paid
        # and organic IG/FB alike -- on the reasoning that basket
        # co-occurrence is worth knowing wherever it happens. It broke
        # the one identity that makes the row readable:
        #
        #     LC Revenue + Halo Rev = Order Sales
        #
        # because halo was counting orders that carry no ad spend and
        # are not in LC Orders. For SMCP over 30 days it reported
        # Rs 7,91,450 where the real rest-of-basket was Rs 7,10,123.
        #
        # Scoped back to the mapped orders, the two columns now split
        # each order exactly: this SKU's lines, and everything else.
        halo_rev_here   = order_total_rev - line_rev
        halo_units_here = order_total_qty - qty
        if halo_rev_here > 0 or halo_units_here > 0:
            agg["halo_orders"].add(order_id)
            agg["halo_units"]   += halo_units_here
            agg["halo_revenue"] += halo_rev_here

        ad_total_spend  = spend_map[page]

        # --- equal-per-order allocation ---
        n_orders_for_ad = len(ad_order_counts[page]) or 1
        per_order_share = ad_total_spend / n_orders_for_ad
        if order_total_rev > 0:
            within_order_share = line_rev / order_total_rev
        elif order_total_qty > 0:
            within_order_share = qty / order_total_qty
        else:
            within_order_share = 0.0
        agg["ad_spend"] += per_order_share * within_order_share

        # --- value-weighted allocation ---
        ad_rev_total = ad_total_rev[page]
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
        order_revenue = float(sum(agg["order_revenue_by_order"].values()))
        order_units   = int(sum(agg["order_units_by_order"].values()))
        ad_spend    = agg["ad_spend"]
        ad_spend_vw = agg["ad_spend_vw"]
        cost_per_order        = (ad_spend    / orders) if orders else None
        cost_per_unit_sold    = (ad_spend    / units)  if units  else None
        roas                  = (revenue     / ad_spend)    if ad_spend    else None
        cost_per_order_vw     = (ad_spend_vw / orders) if orders else None
        cost_per_unit_sold_vw = (ad_spend_vw / units)  if units  else None
        roas_vw               = (revenue     / ad_spend_vw) if ad_spend_vw else None
        halo_orders  = len(agg["halo_orders"])
        halo_units   = int(agg["halo_units"])
        halo_revenue = float(agg["halo_revenue"])
        rows.append((
            master_sku, window_key, window_from, window_to,
            orders, units, revenue, order_revenue, order_units,
            len(agg["ad_ids"]), ad_spend,
            cost_per_order, cost_per_unit_sold, roas,
            # halo_spend intentionally 0 -- ad_spend is already fully
            # distributed across every SKU in the basket, so a positive
            # halo_spend would double-count the same rupees.
            halo_orders, halo_units, halo_revenue, 0.0,
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
              order_revenue, order_units,
              matched_ad_count, ad_spend,
              cost_per_order, cost_per_unit_sold, roas,
              halo_orders, halo_units, halo_revenue, halo_spend,
              primary_weight,
              ad_spend_vw, cost_per_order_vw, cost_per_unit_sold_vw, roas_vw,
              computed_at
            ) VALUES %s
            """,
            rows,
            template="(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())",
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
