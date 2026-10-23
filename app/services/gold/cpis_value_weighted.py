"""Daily revenue-share CPIS, independent of the legacy Equal / Order model.

One spend pool per (IST day, ad OR ad set). When an eligible order cannot
resolve its ad, the whole ad set uses one pool on that day, never both levels.
SKU spend = pool spend * SKU product revenue / pool product revenue.
Zero-revenue pools remain unattributed; no order-count fallback is invented.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable, Mapping

ZERO = Decimal(0)


@dataclass(frozen=True)
class ProductLine:
    day: date
    order_id: str
    ad_id: str | None
    adset_id: str | None
    master_sku: str
    quantity: int
    revenue: Decimal


# Indexable timestamp bounds; SKU parsing and order eligibility follow CPIS.
# Aggregate variants of the same master SKU within an order BEFORE allocating.
LINES_SQL = """
WITH eligible AS (
  SELECT so.order_id, (so.processed_at AT TIME ZONE 'Asia/Kolkata')::date AS day,
         al.ad_id, COALESCE(al.adset_id, s.adset_id) AS adset_id, so.line_items
  FROM public.shopify_orders so
  LEFT JOIN public.ad_lifecycle al
    ON al.ad_id = so.utm_content AND so.utm_content ~ '^[0-9]{10,20}$'
  LEFT JOIN public.meta_adsets s
    ON s.adset_id = so.utm_term AND so.utm_term ~ '^[0-9]{6,20}$'
  WHERE so.processed_at >= (%(since)s::date::timestamp AT TIME ZONE 'Asia/Kolkata')
    AND so.processed_at < ((%(until)s::date + 1)::timestamp AT TIME ZONE 'Asia/Kolkata')
    AND COALESCE(so.financial_status, '') <> 'VOIDED'
    AND jsonb_typeof(so.line_items->'edges') = 'array'
    AND (al.ad_id IS NOT NULL OR s.adset_id IS NOT NULL)
), lines AS (
  SELECT e.day, e.order_id, e.ad_id, e.adset_id,
         regexp_replace(n->>'sku', '_[A-Za-z0-9]+$', '') AS color_sku,
         COALESCE((n->>'quantity')::integer, 0) AS quantity,
         COALESCE((n->'originalUnitPriceSet'->'shopMoney'->>'amount')::numeric, 0) AS price
  FROM eligible e
  CROSS JOIN LATERAL jsonb_array_elements(e.line_items->'edges') edge
  CROSS JOIN LATERAL (SELECT edge->'node' AS n) item
), parsed AS (
  SELECT *, substring(color_sku FROM 1 FOR greatest(1, length(color_sku) - 2)) AS master_sku
  FROM lines
)
SELECT day, order_id, ad_id, adset_id, master_sku,
       SUM(quantity)::integer AS quantity, SUM(quantity * price) AS revenue
FROM parsed
WHERE master_sku ~ '^(SD|SM|SU)[A-Z]{1,4}$' AND quantity > 0 AND price >= 0
GROUP BY day, order_id, ad_id, adset_id, master_sku
"""

SPEND_SQL = """
SELECT day, 'ad:' || ad_id AS entity_id, SUM(spend) AS spend
FROM public.insights_daily_by_ad
WHERE day BETWEEN %(since)s AND %(until)s AND ad_id IS NOT NULL
GROUP BY day, ad_id
UNION ALL
SELECT day, 'adset:' || adset_id AS entity_id, SUM(spend) AS spend
FROM public.insights_daily_by_adset
WHERE day BETWEEN %(since)s AND %(until)s AND adset_id IS NOT NULL
GROUP BY day, adset_id
"""

COLUMNS = (
    "day", "entity_id", "master_sku", "attributed_orders", "attributed_units",
    "attributed_revenue", "order_revenue", "order_units", "entity_orders",
    "entity_spend", "ad_spend", "halo_orders", "halo_units", "halo_revenue",
)


def allocate_daily(
    lines: Iterable[ProductLine],
    spend: Mapping[tuple[date, str], Decimal],
) -> list[dict]:
    """Return one row per day/entity/SKU, with exact-decimal revenue weights.

    Orders and units stay at face value, including days with no spend. Revenue
    share is computed across ALL orders in the same entity-day. Date ranges
    must sum these rows and divide total spend by total units, never average CPIS.
    """
    lines = [line for line in lines if line.quantity > 0 and line.revenue >= 0
             and (line.ad_id or line.adset_id)]
    fallback = {(line.day, line.adset_id) for line in lines
                if line.adset_id and not line.ad_id}
    pools: dict[tuple[date, str], list[ProductLine]] = defaultdict(list)
    for line in lines:
        entity = (f"adset:{line.adset_id}" if (line.day, line.adset_id) in fallback
                  else f"ad:{line.ad_id}")
        pools[line.day, entity].append(line)

    rows = []
    for (day, entity), pool in sorted(pools.items()):
        baskets = defaultdict(lambda: {"revenue": ZERO, "units": 0})
        products = defaultdict(lambda: defaultdict(lambda: {"revenue": ZERO, "units": 0}))
        for line in pool:
            baskets[line.order_id]["revenue"] += line.revenue
            baskets[line.order_id]["units"] += line.quantity
            products[line.master_sku][line.order_id]["revenue"] += line.revenue
            products[line.master_sku][line.order_id]["units"] += line.quantity
        total_revenue = sum((b["revenue"] for b in baskets.values()), ZERO)
        entity_spend = max(ZERO, spend.get((day, entity), ZERO))
        for sku, orders in sorted(products.items()):
            revenue = sum((o["revenue"] for o in orders.values()), ZERO)
            units = sum(o["units"] for o in orders.values())
            order_revenue = sum((baskets[oid]["revenue"] for oid in orders), ZERO)
            order_units = sum(baskets[oid]["units"] for oid in orders)
            rows.append(dict(zip(COLUMNS, (
                day, entity, sku, len(orders), units, revenue, order_revenue,
                order_units, len(baskets), entity_spend,
                entity_spend * revenue / total_revenue if total_revenue > 0 else ZERO,
                sum(baskets[oid]["units"] > o["units"] for oid, o in orders.items()),
                order_units - units, order_revenue - revenue,
            ))))
    return rows


# The API uses this one source for presets AND custom ranges. Matching, sorting,
# CPIS, revenue and order counts therefore all refer to the same population.
RANGE_AGG_SQL = """
SELECT master_sku,
       SUM(attributed_orders)::integer AS attributed_orders,
       SUM(attributed_units)::integer AS attributed_units,
       SUM(attributed_revenue) AS attributed_revenue,
       SUM(order_revenue) AS order_revenue, SUM(order_units)::integer AS order_units,
       COUNT(DISTINCT entity_id)::integer AS matched_ad_count,
       SUM(ad_spend) AS ad_spend, SUM(ad_spend) AS ad_spend_vw,
       SUM(ad_spend) / NULLIF(SUM(attributed_orders), 0) AS cost_per_order,
       SUM(ad_spend) / NULLIF(SUM(attributed_units), 0) AS cost_per_unit_sold,
       SUM(attributed_revenue) / NULLIF(SUM(ad_spend), 0) AS roas,
       SUM(ad_spend) / NULLIF(SUM(attributed_orders), 0) AS cost_per_order_vw,
       SUM(ad_spend) / NULLIF(SUM(attributed_units), 0) AS cost_per_unit_sold_vw,
       SUM(attributed_revenue) / NULLIF(SUM(ad_spend), 0) AS roas_vw,
       SUM(halo_orders)::integer AS halo_orders, SUM(halo_units) AS halo_units,
       SUM(halo_revenue) AS halo_revenue, 0::numeric AS halo_spend,
       NULL::numeric AS primary_weight
FROM public.cpis_value_weighted_daily
WHERE day BETWEEN :from_date AND :to_date
GROUP BY master_sku
"""

TOTALS_SQL = """
WITH entities AS (
  SELECT day, entity_id, MAX(entity_orders) AS orders, SUM(ad_spend) AS allocated
  FROM public.cpis_value_weighted_daily WHERE day BETWEEN :wf AND :wt
  GROUP BY day, entity_id
)
SELECT COALESCE(SUM(orders), 0)::integer AS attributed_orders_distinct,
       COALESCE(SUM(allocated), 0) AS attributed_spend,
       (SELECT COALESCE(SUM(spend), 0) FROM public.insights_daily_by_ad
        WHERE day BETWEEN :wf AND :wt) AS meta_total_spend,
       (SELECT MAX(day) FROM public.insights_daily_by_ad
        WHERE day BETWEEN :wf AND :wt) AS spend_through
FROM entities
"""
