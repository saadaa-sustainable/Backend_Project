"""Build the price-change impact views for the 2026-10-28 repricing.

What this answers
-----------------
43 master SKUs changed price at 00:00 IST on 2026-10-28 (234 products in
the first hour, the rest through that morning -- confirmed from each
product's Shopify `updatedAt`). 41 more were reviewed and left alone,
which makes them the control group rather than filler.

The question is whether the new prices moved demand, read one complete
day at a time against three baselines that are all OLD-price days.

Why add-to-cart rate is the headline and "conversion rate" is not
----------------------------------------------------------------
`shopify_landing_page_analysis.sessions_that_completed_checkout` cannot
carry this. Measured against real Shopify orders over ten days it
captured **4.5% to 8.8%** of them -- GoKwik owns the checkout, so Shopify
never sees most conversions. The swing in what it CAPTURES is several
times larger than any price effect, so a day-over-day ratio built on it
would be mostly noise about instrumentation.

Add-to-cart is measured on the same sessions and behaves: 6.9-7.9% over
the same ten days, on 4,000-6,600 adds a day. It is also the step where
the shopper has just seen the price, which is exactly the decision a
repricing is supposed to move.

The true outcome sits in `cpis_by_sku_daily` instead -- `order_units` and
`order_revenue` per master SKU per day, from real orders. So the views
pair a well-measured demand signal with a real outcome and never pretend
the broken column is a conversion rate.

Collection pages are shared, and that is carried, not hidden
------------------------------------------------------------
One collection page sells many SKUs: `/collections/men-cotton-pant`
carries 100,869 sessions and is not any one SKU's traffic. Every
collection row therefore carries `skus_on_page`, and the per-SKU views
keep product-page and collection-page metrics in SEPARATE columns so
nothing adds a shared number to an exclusive one.

Usage:
    ./.venv/bin/python scripts/refresh_sku_price_impact.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from psycopg2.extras import execute_values  # noqa: E402

from scripts.dbq import connect  # noqa: E402

# Deliberately under scripts/data/, which is gitignored: this repo is
# PUBLIC and a full price list across the catalogue is commercially
# sensitive. The prices live in Supabase via sku_price_change; this file
# is only the loader's input and never reaches a commit.
DEFAULT_PRICE_FILE = Path(__file__).parent / "data" / "sku_price_changes_2026_10_28.json"

DDL = """
CREATE TABLE IF NOT EXISTS public.sku_price_change (
    master_sku      text PRIMARY KEY,
    old_price       numeric,
    new_price       numeric,
    price_change    numeric,
    direction       text,        -- Increased | Decreased | Unchanged
    effective_date  date NOT NULL,
    hidden          boolean NOT NULL DEFAULT false,
    loaded_at       timestamptz DEFAULT now()
);
"""

# ── The daily fact, one row per SKU per day ──────────────────────────
#
# Product-page and collection-page columns are kept apart on purpose. A
# product page belongs to its SKU; a collection page is shared with every
# other SKU on it, so the two must never be summed into one "sessions".
DAILY_VIEW = """
CREATE OR REPLACE VIEW public.sku_price_impact_daily AS
WITH pages AS (
    SELECT m.master_sku, m.page_type, a.day,
           SUM(a.sessions)                      AS sessions,
           SUM(a.sessions_with_cart_additions)  AS atc,
           SUM(a.sessions_that_reached_checkout) AS reached
    FROM public.sku_page_map m
    JOIN public.shopify_landing_page_analysis a
      ON a.landing_page_path = m.page_path
    WHERE a.day >= current_date - 120
    GROUP BY 1, 2, 3
),
pivoted AS (
    SELECT master_sku, day,
           SUM(sessions) FILTER (WHERE page_type = 'Product')    AS product_sessions,
           SUM(atc)      FILTER (WHERE page_type = 'Product')    AS product_atc,
           SUM(reached)  FILTER (WHERE page_type = 'Product')    AS product_reached,
           SUM(sessions) FILTER (WHERE page_type = 'Collection') AS collection_sessions,
           SUM(atc)      FILTER (WHERE page_type = 'Collection') AS collection_atc
    FROM pages GROUP BY 1, 2
)
SELECT
    c.master_sku,
    d.day,
    c.old_price, c.new_price, c.price_change, c.direction, c.hidden,
    (d.day >= c.effective_date) AS at_new_price,
    COALESCE(p.product_sessions, 0)    AS product_sessions,
    COALESCE(p.product_atc, 0)         AS product_atc,
    ROUND(100.0 * p.product_atc / NULLIF(p.product_sessions, 0), 3)    AS product_atc_rate,
    ROUND(100.0 * p.product_reached / NULLIF(p.product_sessions, 0), 3) AS product_checkout_rate,
    COALESCE(p.collection_sessions, 0) AS collection_sessions,
    ROUND(100.0 * p.collection_atc / NULLIF(p.collection_sessions, 0), 3) AS collection_atc_rate,
    -- The real outcome. Not from the landing-page table, which sees
    -- under a tenth of actual orders.
    COALESCE(s.order_units, 0)   AS units_sold,
    COALESCE(s.order_revenue, 0) AS revenue,
    -- Units per thousand product-page sessions: the closest thing to a
    -- true conversion rate available, built from real orders over
    -- well-measured sessions rather than the broken checkout column.
    ROUND(1000.0 * s.order_units / NULLIF(p.product_sessions, 0), 2) AS units_per_1k_sessions
FROM public.sku_price_change c
CROSS JOIN LATERAL (
    SELECT generate_series(current_date - 120, current_date, '1 day')::date AS day
) d
LEFT JOIN pivoted p ON p.master_sku = c.master_sku AND p.day = d.day
LEFT JOIN public.cpis_by_sku_daily s ON s.master_sku = c.master_sku AND s.day = d.day
"""

# ── The headline comparison ──────────────────────────────────────────
#
# The anchor is the latest COMPLETE day, never today: the landing-page
# table is rebuilt once by the nightly, so today holds only the hours
# before that run (10,918 sessions against a full day's ~65,000). Reading
# a partial day against full ones would show every SKU down ~80% for
# reasons that have nothing to do with price.
COMPARE_VIEW = """
CREATE OR REPLACE VIEW public.sku_price_impact_compare AS
WITH anchor AS (
    SELECT MAX(day) AS day FROM public.shopify_landing_page_analysis
    WHERE day < current_date
),
d AS (
    SELECT i.*,
           a.day AS anchor_day,
           CASE
             WHEN i.day = a.day                         THEN 'anchor'
             WHEN i.day = a.day - 1                     THEN 'prev_day'
             WHEN i.day = a.day - 7                     THEN 'prev_week'
             WHEN i.day = (a.day - INTERVAL '1 month')::date THEN 'prev_month'
           END AS slot
    FROM public.sku_price_impact_daily i CROSS JOIN anchor a
    WHERE i.day IN (a.day, a.day - 1, a.day - 7, (a.day - INTERVAL '1 month')::date)
)
SELECT
    master_sku, direction, old_price, new_price, price_change, hidden,
    MAX(anchor_day) AS anchor_day,
    BOOL_OR(at_new_price) FILTER (WHERE slot = 'anchor') AS anchor_at_new_price,

    MAX(product_sessions)  FILTER (WHERE slot = 'anchor')     AS sessions_today,
    MAX(product_sessions)  FILTER (WHERE slot = 'prev_day')   AS sessions_prev_day,
    MAX(product_sessions)  FILTER (WHERE slot = 'prev_week')  AS sessions_prev_week,
    MAX(product_sessions)  FILTER (WHERE slot = 'prev_month') AS sessions_prev_month,

    MAX(product_atc_rate)  FILTER (WHERE slot = 'anchor')     AS atc_rate_today,
    MAX(product_atc_rate)  FILTER (WHERE slot = 'prev_day')   AS atc_rate_prev_day,
    MAX(product_atc_rate)  FILTER (WHERE slot = 'prev_week')  AS atc_rate_prev_week,
    MAX(product_atc_rate)  FILTER (WHERE slot = 'prev_month') AS atc_rate_prev_month,


    MAX(units_sold) FILTER (WHERE slot = 'anchor')     AS units_today,
    MAX(units_sold) FILTER (WHERE slot = 'prev_day')   AS units_prev_day,
    MAX(units_sold) FILTER (WHERE slot = 'prev_week')  AS units_prev_week,
    MAX(units_sold) FILTER (WHERE slot = 'prev_month') AS units_prev_month,

    MAX(revenue) FILTER (WHERE slot = 'anchor')     AS revenue_today,
    MAX(revenue) FILTER (WHERE slot = 'prev_day')   AS revenue_prev_day,
    MAX(revenue) FILTER (WHERE slot = 'prev_week')  AS revenue_prev_week,
    MAX(revenue) FILTER (WHERE slot = 'prev_month') AS revenue_prev_month,

    MAX(collection_sessions) FILTER (WHERE slot = 'anchor') AS collection_sessions_today,
    MAX(units_per_1k_sessions) FILTER (WHERE slot = 'anchor')   AS units_per_1k_today,
    MAX(units_per_1k_sessions) FILTER (WHERE slot = 'prev_week') AS units_per_1k_prev_week
FROM d
GROUP BY master_sku, direction, old_price, new_price, price_change, hidden
"""

# ── The control-group read ───────────────────────────────────────────
#
# One row per direction, which is the only way to tell a price effect
# from a Tuesday. The 41 Unchanged SKUs were reviewed in the same
# exercise and deliberately left alone, so they carry every site-wide
# influence the repriced ones do -- weather, campaigns, a slow news day
# -- and none of the price change. If add-to-cart moves the same way on
# Unchanged as on Increased, the move is not about price.
#
# Rates are recomputed from summed numerators and denominators, never
# averaged from the per-SKU rates: a SKU with 94 sessions would
# otherwise weigh as much as one with 1,361.
SUMMARY_VIEW = """
CREATE OR REPLACE VIEW public.sku_price_impact_summary AS
WITH anchor AS (
    SELECT MAX(day) AS day FROM public.shopify_landing_page_analysis
    WHERE day < current_date
),
d AS (
    SELECT i.direction, i.hidden, i.product_sessions, i.product_atc,
           i.units_sold, i.revenue, a.day AS anchor_day,
           CASE
             WHEN i.day = a.day                              THEN 'anchor'
             WHEN i.day = a.day - 1                          THEN 'prev_day'
             WHEN i.day = a.day - 7                          THEN 'prev_week'
             WHEN i.day = (a.day - INTERVAL '1 month')::date THEN 'prev_month'
           END AS slot
    FROM public.sku_price_impact_daily i CROSS JOIN anchor a
    WHERE i.day IN (a.day, a.day - 1, a.day - 7, (a.day - INTERVAL '1 month')::date)
),
agg AS (
    SELECT direction, hidden, MAX(anchor_day) AS anchor_day,
           SUM(product_sessions) FILTER (WHERE slot='anchor')     AS sess_anchor,
           SUM(product_atc)      FILTER (WHERE slot='anchor')     AS atc_anchor,
           SUM(product_sessions) FILTER (WHERE slot='prev_day')   AS sess_prev_day,
           SUM(product_atc)      FILTER (WHERE slot='prev_day')   AS atc_prev_day,
           SUM(product_sessions) FILTER (WHERE slot='prev_week')  AS sess_prev_week,
           SUM(product_atc)      FILTER (WHERE slot='prev_week')  AS atc_prev_week,
           SUM(product_sessions) FILTER (WHERE slot='prev_month') AS sess_prev_month,
           SUM(product_atc)      FILTER (WHERE slot='prev_month') AS atc_prev_month,
           SUM(units_sold) FILTER (WHERE slot='anchor')     AS units_anchor,
           SUM(units_sold) FILTER (WHERE slot='prev_day')   AS units_prev_day,
           SUM(units_sold) FILTER (WHERE slot='prev_week')  AS units_prev_week,
           SUM(units_sold) FILTER (WHERE slot='prev_month') AS units_prev_month,
           SUM(revenue) FILTER (WHERE slot='anchor')     AS revenue_anchor,
           SUM(revenue) FILTER (WHERE slot='prev_day')   AS revenue_prev_day,
           SUM(revenue) FILTER (WHERE slot='prev_week')  AS revenue_prev_week,
           SUM(revenue) FILTER (WHERE slot='prev_month') AS revenue_prev_month
    FROM d GROUP BY direction, hidden
)
SELECT
    a.direction, a.hidden, a.anchor_day,
    (SELECT COUNT(*) FROM public.sku_price_change c
      WHERE c.direction = a.direction AND c.hidden = a.hidden) AS skus,
    a.sess_anchor AS sessions_today,
    a.sess_prev_day AS sessions_prev_day,
    a.sess_prev_week AS sessions_prev_week,
    a.sess_prev_month AS sessions_prev_month,
    ROUND(100.0 * a.atc_anchor     / NULLIF(a.sess_anchor, 0), 3)     AS atc_rate_today,
    ROUND(100.0 * a.atc_prev_day   / NULLIF(a.sess_prev_day, 0), 3)   AS atc_rate_prev_day,
    ROUND(100.0 * a.atc_prev_week  / NULLIF(a.sess_prev_week, 0), 3)  AS atc_rate_prev_week,
    ROUND(100.0 * a.atc_prev_month / NULLIF(a.sess_prev_month, 0), 3) AS atc_rate_prev_month,
    a.units_anchor AS units_today,
    a.units_prev_day, a.units_prev_week, a.units_prev_month,
    a.revenue_anchor AS revenue_today,
    a.revenue_prev_day, a.revenue_prev_week, a.revenue_prev_month
FROM agg a
ORDER BY a.hidden, a.direction
"""

# ── SKU x page, on the same four days ────────────────────────────────
#
# One view behind every per-SKU tab and the Product/Collection tabs:
# filter it by master_sku for a SKU's tab, by page_type for a page tab.
# Building forty-odd tabs from forty-odd different views would be the
# same query written forty times.
PAGE_COMPARE_VIEW = """
CREATE OR REPLACE VIEW public.sku_page_compare AS
WITH anchor AS (
    SELECT MAX(day) AS day FROM public.shopify_landing_page_analysis
    WHERE day < current_date
),
-- Which of the four days the sources actually hold. A page with no row
-- on a day it HAS data for had no sessions, and should read 0; a day
-- the source is missing entirely must stay blank, because 0 would claim
-- a measurement nobody made. Checked rather than assumed: all four are
-- present today, but the anchor rolls forward every morning and the
-- GA4 fetch has run a day late before.
day_present AS (
    SELECT
        bool_or(x.day = an.day)                              AS has_anchor,
        bool_or(x.day = an.day - 1)                          AS has_prev_day,
        bool_or(x.day = an.day - 7)                          AS has_prev_week,
        bool_or(x.day = (an.day - INTERVAL '1 month')::date) AS has_prev_month
    FROM public.shopify_landing_page_analysis x, anchor an
    WHERE x.day IN (an.day, an.day - 1, an.day - 7,
                    (an.day - INTERVAL '1 month')::date)
),
page_revenue AS (
    -- Every order carries the page its converting session started on,
    -- as a full URL with the whole UTM tail attached. Strip scheme,
    -- host and query and it joins straight onto landing_page_path --
    -- verified: 29,280 of 29,280 orders normalise, and the homepage
    -- lands on '/' like every other path.
    --
    -- This is REAL order revenue, not the landing-page table's own
    -- figure, which sees under a tenth of conversions. It is still a
    -- floor: ga4_order_attribution holds ~76% of Shopify orders, so
    -- every revenue number here is roughly a quarter light in absolute
    -- terms. Day-over-day ratios are unaffected, since the same share
    -- is missing from each.
    --
    -- Pivoted to ONE ROW PER PATH here rather than joined per day. The
    -- landing-page table carries several rows per path per day (one per
    -- referrer and matched campaign), so a day-wise join multiplies the
    -- revenue by however many of those there happen to be.
    SELECT COALESCE(NULLIF(regexp_replace(
               regexp_replace(g.last_landing, '^https?://[^/]+', ''),
               '[?].*$', ''), ''), '/') AS path,
           SUM(g.revenue) FILTER (WHERE (g.order_at AT TIME ZONE 'Asia/Kolkata')::date = an.day)     AS rev_anchor,
           SUM(g.revenue) FILTER (WHERE (g.order_at AT TIME ZONE 'Asia/Kolkata')::date = an.day - 1) AS rev_prev_day,
           SUM(g.revenue) FILTER (WHERE (g.order_at AT TIME ZONE 'Asia/Kolkata')::date = an.day - 7) AS rev_prev_week,
           SUM(g.revenue) FILTER (WHERE (g.order_at AT TIME ZONE 'Asia/Kolkata')::date
                                        = (an.day - INTERVAL '1 month')::date)                       AS rev_prev_month,
           COUNT(*) FILTER (WHERE (g.order_at AT TIME ZONE 'Asia/Kolkata')::date = an.day)     AS ord_anchor,
           COUNT(*) FILTER (WHERE (g.order_at AT TIME ZONE 'Asia/Kolkata')::date = an.day - 1) AS ord_prev_day,
           COUNT(*) FILTER (WHERE (g.order_at AT TIME ZONE 'Asia/Kolkata')::date = an.day - 7) AS ord_prev_week,
           COUNT(*) FILTER (WHERE (g.order_at AT TIME ZONE 'Asia/Kolkata')::date
                                  = (an.day - INTERVAL '1 month')::date)                       AS ord_prev_month
    FROM public.ga4_order_attribution g, anchor an
    WHERE (g.order_at AT TIME ZONE 'Asia/Kolkata')::date
          IN (an.day, an.day - 1, an.day - 7, (an.day - INTERVAL '1 month')::date)
    GROUP BY 1
),
slots AS (
    SELECT m.master_sku, m.page_type, m.page_path, m.page_title,
           m.skus_on_page, m.product_status,
           a.sessions, a.sessions_with_cart_additions AS atc,
           CASE
             WHEN a.day = an.day                              THEN 'anchor'
             WHEN a.day = an.day - 1                          THEN 'prev_day'
             WHEN a.day = an.day - 7                          THEN 'prev_week'
             WHEN a.day = (an.day - INTERVAL '1 month')::date THEN 'prev_month'
           END AS slot,
           an.day AS anchor_day
    FROM public.sku_page_map m
    JOIN public.sku_price_change c ON c.master_sku = m.master_sku
    CROSS JOIN anchor an
    JOIN public.shopify_landing_page_analysis a
      ON a.landing_page_path = m.page_path
     AND a.day IN (an.day, an.day - 1, an.day - 7,
                   (an.day - INTERVAL '1 month')::date)
),
agg AS (
    SELECT
        s.master_sku, s.page_type, s.page_path, s.page_title,
        MAX(s.anchor_day) AS anchor_day,
        MAX(s.skus_on_page) AS skus_on_page,
        MAX(s.product_status) AS product_status,
        SUM(s.sessions) FILTER (WHERE s.slot='anchor')     AS sessions_today,
        SUM(s.sessions) FILTER (WHERE s.slot='prev_day')   AS sessions_prev_day,
        SUM(s.sessions) FILTER (WHERE s.slot='prev_week')  AS sessions_prev_week,
        SUM(s.sessions) FILTER (WHERE s.slot='prev_month') AS sessions_prev_month,
        SUM(s.atc) FILTER (WHERE s.slot='anchor')     AS atc_anchor,
        SUM(s.atc) FILTER (WHERE s.slot='prev_day')   AS atc_prev_day,
        SUM(s.atc) FILTER (WHERE s.slot='prev_week')  AS atc_prev_week,
        SUM(s.atc) FILTER (WHERE s.slot='prev_month') AS atc_prev_month
    FROM slots s
    GROUP BY s.master_sku, s.page_type, s.page_path, s.page_title
)
SELECT
    a.master_sku,
    c.direction, c.old_price, c.new_price, c.price_change, c.hidden,
    a.anchor_day, a.page_type, a.page_path, a.page_title,
    -- 1 on a product page; higher on a collection, which is shared. A
    -- collection's sessions and revenue are NOT this SKU's alone.
    a.skus_on_page, a.product_status,
    CASE WHEN dp.has_anchor     THEN COALESCE(a.sessions_today, 0) END     AS sessions_today,
    CASE WHEN dp.has_prev_day   THEN COALESCE(a.sessions_prev_day, 0) END   AS sessions_prev_day,
    CASE WHEN dp.has_prev_week  THEN COALESCE(a.sessions_prev_week, 0) END  AS sessions_prev_week,
    CASE WHEN dp.has_prev_month THEN COALESCE(a.sessions_prev_month, 0) END AS sessions_prev_month,
    ROUND(100.0*a.atc_anchor     / NULLIF(a.sessions_today, 0), 3)      AS atc_rate_today,
    ROUND(100.0*a.atc_prev_day   / NULLIF(a.sessions_prev_day, 0), 3)   AS atc_rate_prev_day,
    ROUND(100.0*a.atc_prev_week  / NULLIF(a.sessions_prev_week, 0), 3)  AS atc_rate_prev_week,
    ROUND(100.0*a.atc_prev_month / NULLIF(a.sessions_prev_month, 0), 3) AS atc_rate_prev_month,
    -- Revenue of orders whose converting session LANDED on this page.
    CASE WHEN dp.has_anchor     THEN ROUND(COALESCE(rv.rev_anchor, 0), 2) END     AS revenue_today,
    CASE WHEN dp.has_prev_day   THEN ROUND(COALESCE(rv.rev_prev_day, 0), 2) END   AS revenue_prev_day,
    CASE WHEN dp.has_prev_week  THEN ROUND(COALESCE(rv.rev_prev_week, 0), 2) END  AS revenue_prev_week,
    CASE WHEN dp.has_prev_month THEN ROUND(COALESCE(rv.rev_prev_month, 0), 2) END AS revenue_prev_month,
    CASE WHEN dp.has_anchor     THEN COALESCE(rv.ord_anchor, 0) END     AS orders_today,
    CASE WHEN dp.has_prev_day   THEN COALESCE(rv.ord_prev_day, 0) END   AS orders_prev_day,
    CASE WHEN dp.has_prev_week  THEN COALESCE(rv.ord_prev_week, 0) END  AS orders_prev_week,
    CASE WHEN dp.has_prev_month THEN COALESCE(rv.ord_prev_month, 0) END AS orders_prev_month,
    -- What the page returned for the traffic it got: the only figure
    -- that compares a 66-session page with a 6,787-session one.
    --
    -- Suppressed under 50 sessions, the same reflex as the ROAS floor
    -- elsewhere in this codebase. /collections/all-whites took ten
    -- sessions and one Rs 4,397 order, which reads as Rs 4,39,700 per
    -- thousand and would top any sort on this column. One order is not
    -- a rate.
    CASE WHEN a.sessions_today >= 50
         THEN ROUND(1000.0 * rv.rev_anchor / a.sessions_today, 2) END     AS revenue_per_1k_today,
    CASE WHEN a.sessions_prev_week >= 50
         THEN ROUND(1000.0 * rv.rev_prev_week / a.sessions_prev_week, 2) END AS revenue_per_1k_prev_week
FROM agg a
CROSS JOIN day_present dp
JOIN public.sku_price_change c ON c.master_sku = a.master_sku
LEFT JOIN page_revenue rv ON rv.path = a.page_path
"""

# ── Everything that is not a product or collection page ──────────────
#
# Site level, with no SKU column, because there is no product-to-page
# link to report. Checked directly: of 111 Shopify custom pages, ZERO
# reference a product or collection anywhere in their HTML body -- they
# are assembled from dynamic blocks, so nothing in the stored page names
# what it merchandises. The homepage is not any one SKU's page either.
#
# The tab exists so the traffic is visible rather than silently dropped,
# and so the reason it cannot be split by SKU is on the page instead of
# in somebody's memory.
OTHER_PAGES_VIEW = """
CREATE OR REPLACE VIEW public.other_page_compare AS
WITH anchor AS (
    SELECT MAX(day) AS day FROM public.shopify_landing_page_analysis
    WHERE day < current_date
),
day_present AS (
    SELECT bool_or(x.day = an.day)                              AS has_anchor,
           bool_or(x.day = an.day - 1)                          AS has_prev_day,
           bool_or(x.day = an.day - 7)                          AS has_prev_week,
           bool_or(x.day = (an.day - INTERVAL '1 month')::date) AS has_prev_month
    FROM public.shopify_landing_page_analysis x, anchor an
    WHERE x.day IN (an.day, an.day - 1, an.day - 7,
                    (an.day - INTERVAL '1 month')::date)
),
page_revenue AS (
    SELECT COALESCE(NULLIF(regexp_replace(
               regexp_replace(g.last_landing, '^https?://[^/]+', ''),
               '[?].*$', ''), ''), '/') AS path,
           SUM(g.revenue) FILTER (WHERE (g.order_at AT TIME ZONE 'Asia/Kolkata')::date = an.day)     AS rev_anchor,
           SUM(g.revenue) FILTER (WHERE (g.order_at AT TIME ZONE 'Asia/Kolkata')::date = an.day - 1) AS rev_prev_day,
           SUM(g.revenue) FILTER (WHERE (g.order_at AT TIME ZONE 'Asia/Kolkata')::date = an.day - 7) AS rev_prev_week,
           SUM(g.revenue) FILTER (WHERE (g.order_at AT TIME ZONE 'Asia/Kolkata')::date
                                        = (an.day - INTERVAL '1 month')::date)                       AS rev_prev_month,
           COUNT(*) FILTER (WHERE (g.order_at AT TIME ZONE 'Asia/Kolkata')::date = an.day)     AS ord_anchor,
           COUNT(*) FILTER (WHERE (g.order_at AT TIME ZONE 'Asia/Kolkata')::date = an.day - 1) AS ord_prev_day,
           COUNT(*) FILTER (WHERE (g.order_at AT TIME ZONE 'Asia/Kolkata')::date = an.day - 7) AS ord_prev_week,
           COUNT(*) FILTER (WHERE (g.order_at AT TIME ZONE 'Asia/Kolkata')::date
                                  = (an.day - INTERVAL '1 month')::date)                       AS ord_prev_month
    FROM public.ga4_order_attribution g, anchor an
    WHERE (g.order_at AT TIME ZONE 'Asia/Kolkata')::date
          IN (an.day, an.day - 1, an.day - 7, (an.day - INTERVAL '1 month')::date)
    GROUP BY 1
),
agg AS (
    SELECT a.landing_page_type AS page_type, a.landing_page_path AS page_path,
           MAX(an.day) AS anchor_day,
           SUM(a.sessions) FILTER (WHERE a.day = an.day)     AS sess_anchor,
           SUM(a.sessions) FILTER (WHERE a.day = an.day - 1) AS sess_prev_day,
           SUM(a.sessions) FILTER (WHERE a.day = an.day - 7) AS sess_prev_week,
           SUM(a.sessions) FILTER (WHERE a.day = (an.day - INTERVAL '1 month')::date) AS sess_prev_month,
           SUM(a.sessions_with_cart_additions) FILTER (WHERE a.day = an.day)     AS atc_anchor,
           SUM(a.sessions_with_cart_additions) FILTER (WHERE a.day = an.day - 1) AS atc_prev_day,
           SUM(a.sessions_with_cart_additions) FILTER (WHERE a.day = an.day - 7) AS atc_prev_week,
           SUM(a.sessions_with_cart_additions) FILTER (WHERE a.day = (an.day - INTERVAL '1 month')::date) AS atc_prev_month
    FROM public.shopify_landing_page_analysis a CROSS JOIN anchor an
    WHERE a.landing_page_type NOT IN ('Product', 'Collection')
      AND a.day IN (an.day, an.day - 1, an.day - 7,
                    (an.day - INTERVAL '1 month')::date)
    GROUP BY 1, 2
)
SELECT
    a.page_type, a.page_path, a.anchor_day,
    'not attributable to a SKU'::text AS sku_note,
    CASE WHEN dp.has_anchor     THEN COALESCE(a.sess_anchor, 0) END     AS sessions_today,
    CASE WHEN dp.has_prev_day   THEN COALESCE(a.sess_prev_day, 0) END   AS sessions_prev_day,
    CASE WHEN dp.has_prev_week  THEN COALESCE(a.sess_prev_week, 0) END  AS sessions_prev_week,
    CASE WHEN dp.has_prev_month THEN COALESCE(a.sess_prev_month, 0) END AS sessions_prev_month,
    ROUND(100.0*a.atc_anchor     / NULLIF(a.sess_anchor, 0), 3)      AS atc_rate_today,
    ROUND(100.0*a.atc_prev_day   / NULLIF(a.sess_prev_day, 0), 3)    AS atc_rate_prev_day,
    ROUND(100.0*a.atc_prev_week  / NULLIF(a.sess_prev_week, 0), 3)   AS atc_rate_prev_week,
    ROUND(100.0*a.atc_prev_month / NULLIF(a.sess_prev_month, 0), 3)  AS atc_rate_prev_month,
    CASE WHEN dp.has_anchor     THEN ROUND(COALESCE(rv.rev_anchor, 0), 2) END     AS revenue_today,
    CASE WHEN dp.has_prev_day   THEN ROUND(COALESCE(rv.rev_prev_day, 0), 2) END   AS revenue_prev_day,
    CASE WHEN dp.has_prev_week  THEN ROUND(COALESCE(rv.rev_prev_week, 0), 2) END  AS revenue_prev_week,
    CASE WHEN dp.has_prev_month THEN ROUND(COALESCE(rv.rev_prev_month, 0), 2) END AS revenue_prev_month,
    CASE WHEN dp.has_anchor     THEN COALESCE(rv.ord_anchor, 0) END     AS orders_today,
    CASE WHEN dp.has_prev_day   THEN COALESCE(rv.ord_prev_day, 0) END   AS orders_prev_day,
    CASE WHEN dp.has_prev_week  THEN COALESCE(rv.ord_prev_week, 0) END  AS orders_prev_week,
    CASE WHEN dp.has_prev_month THEN COALESCE(rv.ord_prev_month, 0) END AS orders_prev_month
FROM agg a
CROSS JOIN day_present dp
LEFT JOIN page_revenue rv ON rv.path = a.page_path
WHERE COALESCE(a.sess_anchor, 0) > 0 OR COALESCE(rv.rev_anchor, 0) > 0
"""

# Which exact pages a SKU is on, so a reader can check the mapping
# rather than trust it.
PAGES_VIEW = """
CREATE OR REPLACE VIEW public.sku_price_impact_pages AS
SELECT m.master_sku, c.direction, c.old_price, c.new_price,
       m.page_type, m.page_path, m.page_title, m.skus_on_page,
       m.product_status,
       COALESCE(SUM(a.sessions) FILTER (
           WHERE a.day > (SELECT MAX(day) FROM public.shopify_landing_page_analysis
                          WHERE day < current_date) - 7), 0) AS sessions_7d,
       ROUND(100.0 * SUM(a.sessions_with_cart_additions) FILTER (
               WHERE a.day > (SELECT MAX(day) FROM public.shopify_landing_page_analysis
                              WHERE day < current_date) - 7)
           / NULLIF(SUM(a.sessions) FILTER (
               WHERE a.day > (SELECT MAX(day) FROM public.shopify_landing_page_analysis
                              WHERE day < current_date) - 7), 0), 3) AS atc_rate_7d
FROM public.sku_page_map m
JOIN public.sku_price_change c ON c.master_sku = m.master_sku
LEFT JOIN public.shopify_landing_page_analysis a
       ON a.landing_page_path = m.page_path AND a.day >= current_date - 14
GROUP BY 1,2,3,4,5,6,7,8,9
"""


#: CREATE OR REPLACE VIEW refuses to change an existing column's type,
#: so a rebuild that narrows numeric to bigint fails on an older copy.
#: Nothing depends on these views but the sheet, which reads them fresh
#: each run, so dropping first is cheaper than versioning the columns.
_VIEW_NAMES = (
    "public.sku_price_impact_daily", "public.sku_price_impact_compare",
    "public.sku_price_impact_summary", "public.sku_price_impact_pages",
    "public.sku_page_compare", "public.other_page_compare",
)


def _rebuild_views(cur) -> None:
    # Reverse order: compare and summary read daily, so they go first.
    for name in reversed(_VIEW_NAMES):
        cur.execute(f"DROP VIEW IF EXISTS {name} CASCADE")
    for name, sql in (("daily", DAILY_VIEW), ("compare", COMPARE_VIEW),
                      ("summary", SUMMARY_VIEW), ("pages", PAGES_VIEW),
                      ("sku_page_compare", PAGE_COMPARE_VIEW),
                      ("other_page_compare", OTHER_PAGES_VIEW)):
        cur.execute(sql)
        label = name if "_compare" in name else f"sku_price_impact_{name}"
        print(f"  view {label} ready")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--prices", type=Path, default=DEFAULT_PRICE_FILE,
                    help="JSON built from the price-change workbook by "
                         "scripts/load_price_change_workbook.py.")
    ap.add_argument("--views-only", action="store_true",
                    help="Rebuild the three views without reloading prices.")
    args = ap.parse_args()

    if args.views_only:
        with connect(autocommit=False, statement_timeout="600s") as conn:
            with conn.cursor() as cur:
                _rebuild_views(cur)
            conn.commit()
        return 0

    if not args.prices.exists():
        raise SystemExit(
            f"{args.prices} not found — build it from the workbook first:\n"
            "  ./.venv/bin/python scripts/load_price_change_workbook.py "
            "<workbook.xlsx> --effective YYYY-MM-DD"
        )
    payload = json.loads(args.prices.read_text())
    eff = payload["effective_date"]
    hide = set(payload["hide"])
    rows = [
        (r["master_sku"], r["old_price"], r["new_price"], r["change"],
         r["status"], eff, r["master_sku"] in hide)
        for r in payload["changes"]
    ]
    # SKUs listed only on the hide tab still deserve a row: they are part
    # of the same decision and somebody will ask what happened to them.
    known = {r[0] for r in rows}
    rows += [(s, None, None, None, "Hidden", eff, True) for s in hide if s not in known]

    t0 = time.time()
    with connect(autocommit=False, statement_timeout="600s") as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)
            cur.execute("TRUNCATE public.sku_price_change")
            execute_values(cur, """
                INSERT INTO public.sku_price_change
                  (master_sku, old_price, new_price, price_change,
                   direction, effective_date, hidden)
                VALUES %s
            """, rows)
            _rebuild_views(cur)
        conn.commit()
    print(f"  loaded {len(rows)} SKUs in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
