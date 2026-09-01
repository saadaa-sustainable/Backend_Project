"""Gold layer: CPIS via UTM-attributed order → ad_id → SKU (2026-08-31).

Contrast with `cpis.py`, which correlates ads to master SKUs via
substring matching on ad_name and totals against store-wide inventory
sales -- correlation, not attribution.

This module ships the attribution-based CPIS the user actually wants:

    * shopify_orders.utm_content = ad_id      (Meta stamps this on every
                                               click; ~73% match rate on
                                               distinct utm_contents vs.
                                               ad_lifecycle.ad_id)
    * shopify_orders.line_items.edges[].node.sku = variant SKU
    * parse_master_sku(variant_sku)           (from cpis.py)
    * raw_dump_meta insights.spend            (per ad_id per day)

Then per master_sku per window (7d / 30d / 90d):

    attributed_orders   = COUNT(DISTINCT order_id) whose utm_content ties
                          to an ad_id AND whose line_items contain a
                          variant with this master_sku
    attributed_units    = SUM(line_item.quantity) for those line items
    attributed_revenue  = SUM(line_item.quantity * unit_price) same
    ad_spend            = SUM(insights.spend) for those ad_ids in-window
    matched_ad_count    = COUNT DISTINCT ad_ids
    cost_per_order      = ad_spend / attributed_orders
    cost_per_unit_sold  = ad_spend / attributed_units   (the honest CPIS)
    roas                = attributed_revenue / ad_spend

Everything windows cleanly (both sides come from timestamped daily
grains). No lifetime-vs-window mixing like `cpis_by_sku` has.

Limitations kept honest in output columns:
    * ~27% of numeric utm_content values on orders don't match any
      current ad_lifecycle row -- deleted-ad case, or CBO shuffle where
      the ad_id in URL isn't the one that ran. Those orders are still
      counted in attributed_orders but their spend isn't recoverable.
    * Fully non-numeric utm_content (naming-convention strings like
      SDCP_OFF_FL_916_ITE-Feb-25) is skipped -- can't join to a specific
      ad without knowing which campaign named itself that way.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging.setup import get_logger

logger = get_logger(__name__)


# Master-SKU parsing done in SQL here (not Python like cpis.py) because
# we're already aggregating ~20k line-items per refresh in-DB and pulling
# them to Python just to reparse the regex would round-trip a lot of
# data for no gain. Same result as parse_master_sku() in cpis.py:
#   strip trailing _<size>  -> color SKU
#   strip 2-char color code -> master SKU
#   validate against ^(SD|SM|SU)[A-Z]{1,4}$
_WINDOWS = {"7d": 7, "30d": 30, "90d": 90}


_DDL = """
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

_TRUNCATE = "TRUNCATE cpis_by_sku_utm"

# The whole refresh is one SQL statement per window. It:
#   1) expands shopify_orders in-window whose utm_content is a numeric
#      ad_id that exists in ad_lifecycle (attributable orders),
#   2) unnests line_items.edges into (order_id, ad_id, variant_sku, qty,
#      unit_price),
#   3) parses master_sku from variant_sku, filters to the SD/SM/SU
#      convention,
#   4) aggregates per master_sku (orders, units, revenue, distinct ads),
#   5) LEFT JOINs windowed spend from raw_dump_meta insights for those
#      ad_ids in-window,
#   6) upserts one row per (master_sku, window_key).
_REFRESH_SQL = """
WITH orders_in_window AS (
  SELECT
    so.order_id,
    so.utm_content    AS ad_id,
    so.line_items
  FROM shopify_orders so
  WHERE so.processed_at::date >= :window_from
    AND so.processed_at::date <= :window_to
    AND so.utm_content ~ '^[0-9]{10,20}$'
    AND EXISTS (
      SELECT 1 FROM ad_lifecycle al WHERE al.ad_id = so.utm_content
    )
    AND jsonb_typeof(so.line_items->'edges') = 'array'
),
line_items AS (
  SELECT
    ow.order_id,
    ow.ad_id,
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
    SUBSTRING(
      regexp_replace(variant_sku, '_[A-Za-z0-9]+$', '')
      FROM 1
      FOR GREATEST(1,
        length(regexp_replace(variant_sku, '_[A-Za-z0-9]+$', '')) - 2
      )
    ) AS master_sku
  FROM line_items
),
per_sku AS (
  SELECT
    master_sku,
    COUNT(DISTINCT order_id)              AS attributed_orders,
    SUM(qty)                              AS attributed_units,
    SUM(qty * unit_price)                 AS attributed_revenue,
    COUNT(DISTINCT ad_id)                 AS matched_ad_count,
    ARRAY_AGG(DISTINCT ad_id)             AS ad_ids
  FROM parsed
  WHERE master_sku ~ '^(SD|SM|SU)[A-Z]{1,4}$'
  GROUP BY master_sku
),
ad_spend_per_sku AS (
  SELECT
    ps.master_sku,
    COALESCE(SUM(NULLIF(r.raw_payload->>'spend','')::numeric), 0) AS ad_spend
  FROM per_sku ps
  LEFT JOIN raw_dump_meta r
    ON r.object_type = 'insights'
   AND r.raw_payload->>'ad_id' = ANY(ps.ad_ids)
   AND (r.raw_payload->>'date_start')::date >= :window_from
   AND (r.raw_payload->>'date_start')::date <= :window_to
  GROUP BY ps.master_sku
)
INSERT INTO cpis_by_sku_utm (
  master_sku, window_key, window_from, window_to,
  attributed_orders, attributed_units, attributed_revenue,
  matched_ad_count, ad_spend,
  cost_per_order, cost_per_unit_sold, roas,
  computed_at
)
SELECT
  ps.master_sku, :window_key, :window_from, :window_to,
  ps.attributed_orders, ps.attributed_units, ps.attributed_revenue,
  ps.matched_ad_count, COALESCE(sp.ad_spend, 0),
  CASE WHEN ps.attributed_orders > 0
       THEN COALESCE(sp.ad_spend, 0) / ps.attributed_orders
       ELSE NULL END,
  CASE WHEN ps.attributed_units > 0
       THEN COALESCE(sp.ad_spend, 0) / ps.attributed_units
       ELSE NULL END,
  CASE WHEN COALESCE(sp.ad_spend, 0) > 0
       THEN ps.attributed_revenue / sp.ad_spend
       ELSE NULL END,
  now()
FROM per_sku ps
LEFT JOIN ad_spend_per_sku sp USING (master_sku)
"""


COLUMN_FORMULAS: dict[str, str] = {
    "master_sku": "parsed from shopify_orders.line_items[].node.sku via SUBSTRING(regexp_replace(sku,'_[A-Za-z0-9]+$','') from 1 for len-2), validated against ^(SD|SM|SU)[A-Z]{1,4}$",
    "attributed_orders": "COUNT(DISTINCT order_id) for orders in-window whose utm_content matches an ad_id in ad_lifecycle AND whose line_items include this master_sku",
    "attributed_units": "SUM(line_item.node.quantity) for those matching line items",
    "attributed_revenue": "SUM(qty * originalUnitPriceSet.shopMoney.amount) for those line items -- gross line-item revenue (pre-discount, pre-shipping, pre-tax)",
    "matched_ad_count": "COUNT(DISTINCT ad_id) of ads that drove those orders",
    "ad_spend": "SUM(raw_dump_meta.insights.spend) for those ad_ids within [window_from..window_to] -- genuinely windowed",
    "cost_per_order": "ad_spend / attributed_orders -- what each attributable order of this SKU cost in ad spend",
    "cost_per_unit_sold": "ad_spend / attributed_units -- true CPIS: cost per item sold, attribution-based",
    "roas": "attributed_revenue / ad_spend -- return on ad spend for this SKU family",
}


async def ensure_cpis_utm_table(session: AsyncSession) -> None:
    await session.execute(text(_DDL))
    await session.commit()


async def refresh_cpis_by_sku_utm(session: AsyncSession) -> dict[str, int]:
    await ensure_cpis_utm_table(session)

    today = date.today()

    await session.execute(text(_TRUNCATE))

    total_rows = 0
    for window_key, days in _WINDOWS.items():
        window_from = today - timedelta(days=days - 1)
        result = await session.execute(
            text(_REFRESH_SQL),
            {
                "window_key": window_key,
                "window_from": window_from,
                "window_to": today,
            },
        )
        total_rows += result.rowcount or 0
        logger.info(
            "cpis_utm_window",
            window=window_key,
            window_from=str(window_from),
            window_to=str(today),
            inserted=result.rowcount,
        )

    await session.commit()
    logger.info("cpis_by_sku_utm_refreshed", cpis_by_sku_utm=total_rows)
    return {"cpis_by_sku_utm": total_rows}
