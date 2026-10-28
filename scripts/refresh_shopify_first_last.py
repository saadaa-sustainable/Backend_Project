"""Shopify-anchored first/last click attribution.

Why this replaces the GA4-only model
------------------------------------
The old model took its order universe from `ga4_order_attribution`,
which holds about 76% of Shopify orders -- GoKwik owns the checkout, so
GA4 misses the rest. Every revenue figure was therefore a quarter light
and nothing reconciled to the real order book.

This anchors on Shopify instead and looks back into GA4 by
`transaction_id`, which IS `shopify_orders.name`:

    universe     shopify_orders            the real book, 37,735 / 30d
    revenue      shopify_orders.total_price
    first click  ga4_order_attribution.first_ad_id
    last click   ga4 last_ad_id, else shopify_order_attribution.matched_ad_id

The last click is a fallback chain because neither source is enough
alone. GA4 resolves an ad on 71% of the orders it sees but sees only
76% of them; Shopify sees all of them but resolves an ad on 49%, since
18,357 orders land in tier `unmatched` with no usable UTM. Measured over
30 days the chain reaches 18,963 orders and Rs 2.52 Cr, against 18,383 /
Rs 2.42 Cr for GA4 alone and 15,389 / Rs 1.97 Cr for Shopify alone.

`last_click_source` records which one fired, because the two are not the
same measurement. GA4's is session-scoped -- the ad clicked on the
converting visit. Shopify's is the UTM carried on the order, which
persists from an earlier session: on order #1592954 Shopify's "last"
ad is the same ad GA4 recorded as the FIRST click. Treating them as
interchangeable without saying so would hide that.

An order is attributed only when it has BOTH ends
-------------------------------------------------
So the two totals are identical by construction, and the whole
first-versus-last difference appears per ad rather than as a headline
gap. An order with one end only is not silently dropped -- it is
reported in `shopify_attribution_coverage` so the unattributed
remainder is always on the page.

Both sides take the FULL order value, never a split: an order ad X
opened and ad Y closed counts its whole revenue under X's opened and
again under Y's closed. The columns overlap and must never be added.

Usage:
    ./.venv/bin/python scripts/refresh_shopify_first_last.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.dbq import connect  # noqa: E402

VIEWS = {}

VIEWS["shopify_order_clicks"] = """
CREATE OR REPLACE VIEW public.shopify_order_clicks AS
SELECT
    s.name                                   AS order_no,
    (s.created_at AT TIME ZONE 'Asia/Kolkata')::date AS order_day,
    s.total_price::numeric                   AS revenue,
    s.financial_status,
    g.first_ad_id,
    COALESCE(g.last_ad_id, a.matched_ad_id)  AS last_ad_id,
    CASE WHEN g.last_ad_id IS NOT NULL THEN 'ga4'
         WHEN a.matched_ad_id IS NOT NULL THEN 'shopify'
         END                                 AS last_click_source,
    g.first_source, g.last_source,
    a.utm_source AS shopify_utm_source, a.tier AS shopify_tier,
    g.days_to_convert, g.total_sessions,
    (g.transaction_id IS NOT NULL)           AS seen_by_ga4,
    -- Attributed only when BOTH ends resolve, so the two sides cover
    -- the same orders and their totals agree by construction.
    (g.first_ad_id IS NOT NULL
     AND COALESCE(g.last_ad_id, a.matched_ad_id) IS NOT NULL) AS attributed
FROM public.shopify_orders s
LEFT JOIN public.ga4_order_attribution g   ON g.transaction_id = s.name
LEFT JOIN public.shopify_order_attribution a ON a.name = s.name
"""

VIEWS["shopify_attribution_coverage"] = """
CREATE OR REPLACE VIEW public.shopify_attribution_coverage AS
SELECT
    order_day,
    COUNT(*)                                            AS orders,
    SUM(revenue)                                        AS revenue,
    COUNT(*) FILTER (WHERE attributed)                  AS attributed_orders,
    SUM(revenue) FILTER (WHERE attributed)              AS attributed_revenue,
    COUNT(*) FILTER (WHERE attributed AND last_click_source = 'ga4')     AS last_from_ga4,
    COUNT(*) FILTER (WHERE attributed AND last_click_source = 'shopify') AS last_from_shopify,
    -- Why the rest are not attributed, which is the only honest way to
    -- show a 40%-coverage number.
    COUNT(*) FILTER (WHERE NOT attributed AND NOT seen_by_ga4)           AS unattr_not_in_ga4,
    COUNT(*) FILTER (WHERE NOT attributed AND seen_by_ga4
                       AND first_ad_id IS NULL)                          AS unattr_no_first_click,
    COUNT(*) FILTER (WHERE NOT attributed AND seen_by_ga4
                       AND first_ad_id IS NOT NULL)                      AS unattr_no_last_click
FROM public.shopify_order_clicks
GROUP BY order_day
"""

VIEWS["shopify_first_last_by_ad"] = """
CREATE OR REPLACE VIEW public.shopify_first_last_by_ad AS
WITH sides AS (
    SELECT first_ad_id AS ad_id, order_day, revenue, 'first' AS side
      FROM public.shopify_order_clicks WHERE attributed
    UNION ALL
    SELECT last_ad_id, order_day, revenue, 'last'
      FROM public.shopify_order_clicks WHERE attributed
)
SELECT
    s.ad_id,
    COALESCE(NULLIF(btrim(l.ad_name), ''), s.ad_id) AS ad_name,
    s.order_day,
    -- 0, not NULL, where an ad appears on only one side: an ad that
    -- closed orders but opened none genuinely opened zero, and a blank
    -- there makes every gap calculation downstream return NULL.
    COUNT(*)              FILTER (WHERE side = 'first')     AS first_click_orders,
    COALESCE(SUM(revenue) FILTER (WHERE side = 'first'), 0) AS first_click_revenue,
    COUNT(*)              FILTER (WHERE side = 'last')      AS last_click_orders,
    COALESCE(SUM(revenue) FILTER (WHERE side = 'last'), 0)  AS last_click_revenue,
    -- The point of the section, computed once rather than by every
    -- reader: credit this ad claims as an opener beyond what it is
    -- given as a closer.
    COALESCE(SUM(revenue) FILTER (WHERE side = 'first'), 0)
      - COALESCE(SUM(revenue) FILTER (WHERE side = 'last'), 0) AS first_minus_last
FROM sides s
LEFT JOIN public.ad_lifecycle l ON l.ad_id = s.ad_id
GROUP BY s.ad_id, COALESCE(NULLIF(btrim(l.ad_name), ''), s.ad_id), s.order_day
"""


def main() -> int:
    t0 = time.time()
    with connect(autocommit=False, statement_timeout="600s") as conn:
        with conn.cursor() as cur:
            for name in reversed(list(VIEWS)):
                cur.execute(f"DROP VIEW IF EXISTS public.{name} CASCADE")
            for name, sql in VIEWS.items():
                cur.execute(sql)
                print(f"  view {name} ready")
        conn.commit()
    print(f"  done in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
