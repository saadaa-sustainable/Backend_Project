-- ---------------------------------------------------------------------
-- Founder-facing last-click snapshots, ported from the legacy
-- Meta_ads_data project's meta_direct_* views.
--
-- Same column names and shape, so an existing Google Sheet keeps
-- working, but rebuilt on THIS database -- which is the point. The
-- legacy views read shopify_ad_attribution from the old matcher; these
-- read shopify_order_attribution, the corrected one.
--
-- Three deliberate departures from the legacy definitions:
--
--  1. The window is anchored on the newest day of DATA, not on
--     CURRENT_DATE. Meta lands insights a day in arrears, so
--     CURRENT_DATE - 29 asks for a 30-day window whose last day does
--     not exist yet and quietly returns 29 days of spend against 30
--     days of orders. Same defect that made an ad set read Rs 10k
--     under Meta Ads Manager on 2026-09-24.
--
--  2. In the two AGGREGATE views the legacy `reach` column summed
--     daily reach. Reach is a count of distinct PEOPLE and is not
--     additive: summing 30 days of it over this account gives
--     107,978,760, which is more than every human the account has
--     ever reached. The column is therefore named `reach_daily_sum`
--     here, and a genuinely de-duplicated `reach_unique_to_date` sits
--     beside it, taken from ad_reach_cumulative. The DAILY views keep
--     plain `reach`, because one day is one de-duplication window and
--     the daily figure is already correct.
--
--  3. `ad_status` comes from ad_lifecycle's current state rather than
--     from the last row inside the window.
-- ---------------------------------------------------------------------

-- IF EXISTS only tolerates an absent object, not the wrong relation kind.
-- The previous DROP VIEW failed on existing materialized views before their
-- definitions could be rebound from insights_daily_by_ad_old to the live table.
DO $snapshot_cleanup$
DECLARE
  snapshot record;
BEGIN
  FOR snapshot IN
    SELECT c.relname, c.relkind
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relname IN (
      'meta_direct_active_30d', 'meta_direct_active_90d',
      'meta_direct_daily_30d', 'meta_direct_daily_90d',
      'meta_direct_adset_30d', 'meta_direct_campaign_30d'
    )
  LOOP
    IF snapshot.relkind = 'm' THEN
      EXECUTE format('DROP MATERIALIZED VIEW public.%I', snapshot.relname);
    ELSIF snapshot.relkind = 'v' THEN
      EXECUTE format('DROP VIEW public.%I', snapshot.relname);
    ELSE
      RAISE EXCEPTION 'Unexpected relation kind for snapshot %: %',
        snapshot.relname, snapshot.relkind;
    END IF;
  END LOOP;
END
$snapshot_cleanup$;

-- The newest day the Meta insights actually cover. Every view below
-- anchors on this so spend and orders always describe the same dates.
CREATE OR REPLACE VIEW public.meta_direct_data_through AS
  SELECT MAX(day) AS data_through FROM public.insights_daily_by_ad;

COMMENT ON VIEW public.meta_direct_data_through IS
  'Newest day of Meta insight data. The meta_direct_* views window on this, not on CURRENT_DATE.';

-- =====================================================================
-- meta_direct_active_30d -- one row per ACTIVE ad, last 30 days
-- =====================================================================
CREATE MATERIALIZED VIEW public.meta_direct_active_30d AS
WITH win AS (
  SELECT (SELECT MAX(day) FROM public.insights_daily_by_ad) - 29 AS since,
         (SELECT MAX(day) FROM public.insights_daily_by_ad)              AS until
),
metrics AS (
  SELECT i.ad_id,
         SUM(i.impressions)                                    AS impressions,
         SUM(i.reach)                                          AS reach_daily_sum,
         CASE WHEN SUM(i.reach) > 0
              THEN ROUND(SUM(i.impressions)::numeric / SUM(i.reach)::numeric, 4)
              ELSE 0 END                                       AS frequency,
         ROUND(SUM(i.spend), 2)                                AS spend,
         SUM(i.clicks)                                         AS link_clicks,
         SUM(i.outbound_clicks)                                AS outbound_clicks,
         COALESCE(SUM(i.clicks), 0) + COALESCE(SUM(i.outbound_clicks), 0) AS all_clicks,
         CASE WHEN SUM(i.impressions) > 0
              THEN ROUND(100.0 * SUM(i.clicks)::numeric / SUM(i.impressions)::numeric, 4)
              ELSE 0 END                                       AS ctr,
         CASE WHEN SUM(i.clicks) > 0
              THEN ROUND(SUM(i.spend) / SUM(i.clicks)::numeric, 4)
              ELSE 0 END                                       AS cpc,
         CASE WHEN SUM(i.impressions) > 0
              THEN ROUND(1000.0 * SUM(i.spend) / SUM(i.impressions)::numeric, 4)
              ELSE 0 END                                       AS cpm,
         SUM(i.purchases)                                      AS purchases,
         SUM(i.conv_value)                                     AS conv_value,
         CASE WHEN SUM(i.spend) > 0
              THEN ROUND(SUM(i.conv_value) / SUM(i.spend), 4)
              ELSE 0 END                                       AS purchase_roas,
         SUM(i.checkout_initiate)                              AS ci_count,
         SUM(i.add_to_cart)                                    AS atc_count,
         SUM(i.thruplays)                                      AS thruplays,
         NULL::bigint                                          AS p100_plays,
         SUM(i.ftewv_count)                                    AS ftewv_count,
         SUM(i.ncp_count)                                      AS ncp_count,
         MIN(i.day)                                            AS date_start,
         MAX(i.day)                                            AS date_stop
    FROM public.insights_daily_by_ad i, win
   WHERE i.day BETWEEN win.since AND win.until
     AND i.impressions IS NOT NULL AND i.impressions > 0
   GROUP BY i.ad_id
),
-- De-duplicated reach, the only unique-person figure available at ad
-- grain. Cumulative since its epoch, NOT scoped to the window: no
-- window-scoped ad-level reach rows exist. Dated so nobody reads it as
-- a 30-day number.
reach_u AS (
  SELECT DISTINCT ON (entity_id) entity_id AS ad_id,
         cumulative_reach AS reach_unique_to_date,
         epoch_date       AS reach_since,
         as_of_date       AS reach_as_of
    FROM public.ad_reach_cumulative
   WHERE level = 'ad'
   ORDER BY entity_id, as_of_date DESC
),
-- OUR last-click attribution, not the legacy matcher.
shop AS (
  SELECT a.matched_ad_id AS ad_id,
         COUNT(*)::int                                  AS shopify_orders,
         COALESCE(SUM(a.total_price), 0)                AS shopify_sales,
         -- New vs repeat, on the same orders the two columns above
         -- count. "New" is the customer's FIRST EVER order, decided
         -- over the whole order history by
         -- scripts/refresh_order_customer_type.py -- not first within
         -- this window.
         COUNT(*) FILTER (WHERE oct.is_new_customer)::int        AS new_customers,
         COUNT(*) FILTER (WHERE NOT oct.is_new_customer)::int    AS repeat_customer_orders,
         COUNT(DISTINCT oct.customer_id)
           FILTER (WHERE NOT oct.is_new_customer)::int           AS repeat_customers_distinct,
         COALESCE(SUM(a.total_price)
           FILTER (WHERE oct.is_new_customer), 0)                AS new_customer_sales,
         COALESCE(SUM(a.total_price)
           FILTER (WHERE NOT oct.is_new_customer), 0)            AS repeat_customer_sales,
         MODE() WITHIN GROUP (ORDER BY a.tier)          AS matched_tier,
         MODE() WITHIN GROUP (ORDER BY a.utm_content)   AS utm_content,
         MODE() WITHIN GROUP (ORDER BY a.utm_term)      AS utm_term,
         MODE() WITHIN GROUP (ORDER BY a.utm_campaign)  AS utm_campaign
    FROM public.shopify_order_attribution a
    LEFT JOIN public.order_customer_type oct ON oct.order_id = a.order_id
    CROSS JOIN win
   WHERE a.matched_ad_id IS NOT NULL
     AND a.created_at::date BETWEEN win.since AND win.until
   GROUP BY a.matched_ad_id
)
SELECT al.account_name,
       al.campaign_name,
       al.campaign_id,
       al.adset_id,
       al.adset_name,
       m.ad_id,
       al.ad_name,
       m.impressions,
       m.reach_daily_sum,
       r.reach_unique_to_date,
       r.reach_since,
       r.reach_as_of,
       m.frequency,
       m.spend,
       m.link_clicks,
       m.outbound_clicks,
       m.all_clicks,
       m.ctr,
       m.cpc,
       m.cpm,
       m.purchases,
       m.conv_value,
       m.purchase_roas,
       m.ci_count,
       m.atc_count,
       m.thruplays,
       m.p100_plays,
       m.ftewv_count,
       m.ncp_count,
       m.date_start,
       m.date_stop,
       al.ad_status,
       al.ad_created_time::date                          AS ad_created,
       COALESCE(shop.shopify_orders, 0)                  AS shopify_orders,
       COALESCE(shop.shopify_sales, 0)                   AS shopify_sales,
       CASE WHEN m.spend > 0
            THEN ROUND(COALESCE(shop.shopify_sales, 0) / m.spend, 4)
            ELSE 0 END                                   AS shopify_roas,
       COALESCE(shop.new_customers, 0)                   AS new_customers,
       -- ADDITIVE: one first order per person, so the order count and
       -- the customer count are the same number.
       COALESCE(shop.repeat_customer_orders, 0)          AS repeat_customer_orders,
       -- NOT ADDITIVE. Distinct people, counted per row. One person who
       -- buys through two ads is one customer and two rows, so a SUM
       -- down this column in a sheet overstates. Same hazard the
       -- reach_daily_sum / reach_unique_to_date pair exists for.
       COALESCE(shop.repeat_customers_distinct, 0)       AS repeat_customers,
       COALESCE(shop.new_customer_sales, 0)              AS new_customer_sales,
       COALESCE(shop.repeat_customer_sales, 0)           AS repeat_customer_sales,
       -- Acquisition MER: revenue from newly acquired customers over
       -- the ad spend that acquired them, both across this row's
       -- window. Money over money, so it reads like the ROAS columns
       -- beside it rather than like a rate.
       --
       -- NULL, not 0, when nothing was spent: a ratio with an empty
       -- denominator has no value, and 0 would sort a paused entity
       -- below one that genuinely acquired badly.
       CASE WHEN m.spend > 0
            THEN ROUND(COALESCE(shop.new_customer_sales, 0) / m.spend, 4)
            END                                          AS acq_mer,
       shop.matched_tier,
       shop.utm_content,
       shop.utm_term,
       shop.utm_campaign,
       -- Meta's attribution window for this ad, so a sheet can split
       -- last-click revenue by the setting that produced it. NULL where
       -- none is recorded: today that is every account but Fourth.
       al.attribution_setting
  FROM metrics m
  JOIN public.ad_lifecycle al USING (ad_id)
  LEFT JOIN reach_u r USING (ad_id)
  LEFT JOIN shop    USING (ad_id)
 WHERE UPPER(COALESCE(al.ad_status, '')) = 'ACTIVE';

COMMENT ON MATERIALIZED VIEW public.meta_direct_active_30d IS
  'One row per ACTIVE ad over the last 30 days of DATA. Shopify columns come from this project''s corrected last-click attribution. reach_daily_sum is a SUM of daily reach and overcounts people; reach_unique_to_date is the de-duplicated figure.';

-- =====================================================================
-- meta_direct_active_90d -- one row per ACTIVE ad, last 90 days
-- =====================================================================
CREATE MATERIALIZED VIEW public.meta_direct_active_90d AS
WITH win AS (
  SELECT (SELECT MAX(day) FROM public.insights_daily_by_ad) - 89 AS since,
         (SELECT MAX(day) FROM public.insights_daily_by_ad)              AS until
),
metrics AS (
  SELECT i.ad_id,
         SUM(i.impressions)                                    AS impressions,
         SUM(i.reach)                                          AS reach_daily_sum,
         CASE WHEN SUM(i.reach) > 0
              THEN ROUND(SUM(i.impressions)::numeric / SUM(i.reach)::numeric, 4)
              ELSE 0 END                                       AS frequency,
         ROUND(SUM(i.spend), 2)                                AS spend,
         SUM(i.clicks)                                         AS link_clicks,
         SUM(i.outbound_clicks)                                AS outbound_clicks,
         COALESCE(SUM(i.clicks), 0) + COALESCE(SUM(i.outbound_clicks), 0) AS all_clicks,
         CASE WHEN SUM(i.impressions) > 0
              THEN ROUND(100.0 * SUM(i.clicks)::numeric / SUM(i.impressions)::numeric, 4)
              ELSE 0 END                                       AS ctr,
         CASE WHEN SUM(i.clicks) > 0
              THEN ROUND(SUM(i.spend) / SUM(i.clicks)::numeric, 4)
              ELSE 0 END                                       AS cpc,
         CASE WHEN SUM(i.impressions) > 0
              THEN ROUND(1000.0 * SUM(i.spend) / SUM(i.impressions)::numeric, 4)
              ELSE 0 END                                       AS cpm,
         SUM(i.purchases)                                      AS purchases,
         SUM(i.conv_value)                                     AS conv_value,
         CASE WHEN SUM(i.spend) > 0
              THEN ROUND(SUM(i.conv_value) / SUM(i.spend), 4)
              ELSE 0 END                                       AS purchase_roas,
         SUM(i.checkout_initiate)                              AS ci_count,
         SUM(i.add_to_cart)                                    AS atc_count,
         SUM(i.thruplays)                                      AS thruplays,
         NULL::bigint                                          AS p100_plays,
         SUM(i.ftewv_count)                                    AS ftewv_count,
         SUM(i.ncp_count)                                      AS ncp_count,
         MIN(i.day)                                            AS date_start,
         MAX(i.day)                                            AS date_stop
    FROM public.insights_daily_by_ad i, win
   WHERE i.day BETWEEN win.since AND win.until
     AND i.impressions IS NOT NULL AND i.impressions > 0
   GROUP BY i.ad_id
),
-- De-duplicated reach, the only unique-person figure available at ad
-- grain. Cumulative since its epoch, NOT scoped to the window: no
-- window-scoped ad-level reach rows exist. Dated so nobody reads it as
-- a 90-day number.
reach_u AS (
  SELECT DISTINCT ON (entity_id) entity_id AS ad_id,
         cumulative_reach AS reach_unique_to_date,
         epoch_date       AS reach_since,
         as_of_date       AS reach_as_of
    FROM public.ad_reach_cumulative
   WHERE level = 'ad'
   ORDER BY entity_id, as_of_date DESC
),
-- OUR last-click attribution, not the legacy matcher.
shop AS (
  SELECT a.matched_ad_id AS ad_id,
         COUNT(*)::int                                  AS shopify_orders,
         COALESCE(SUM(a.total_price), 0)                AS shopify_sales,
         -- New vs repeat, on the same orders the two columns above
         -- count. "New" is the customer's FIRST EVER order, decided
         -- over the whole order history by
         -- scripts/refresh_order_customer_type.py -- not first within
         -- this window.
         COUNT(*) FILTER (WHERE oct.is_new_customer)::int        AS new_customers,
         COUNT(*) FILTER (WHERE NOT oct.is_new_customer)::int    AS repeat_customer_orders,
         COUNT(DISTINCT oct.customer_id)
           FILTER (WHERE NOT oct.is_new_customer)::int           AS repeat_customers_distinct,
         COALESCE(SUM(a.total_price)
           FILTER (WHERE oct.is_new_customer), 0)                AS new_customer_sales,
         COALESCE(SUM(a.total_price)
           FILTER (WHERE NOT oct.is_new_customer), 0)            AS repeat_customer_sales,
         MODE() WITHIN GROUP (ORDER BY a.tier)          AS matched_tier,
         MODE() WITHIN GROUP (ORDER BY a.utm_content)   AS utm_content,
         MODE() WITHIN GROUP (ORDER BY a.utm_term)      AS utm_term,
         MODE() WITHIN GROUP (ORDER BY a.utm_campaign)  AS utm_campaign
    FROM public.shopify_order_attribution a
    LEFT JOIN public.order_customer_type oct ON oct.order_id = a.order_id
    CROSS JOIN win
   WHERE a.matched_ad_id IS NOT NULL
     AND a.created_at::date BETWEEN win.since AND win.until
   GROUP BY a.matched_ad_id
)
SELECT al.account_name,
       al.campaign_name,
       al.campaign_id,
       al.adset_id,
       al.adset_name,
       m.ad_id,
       al.ad_name,
       m.impressions,
       m.reach_daily_sum,
       r.reach_unique_to_date,
       r.reach_since,
       r.reach_as_of,
       m.frequency,
       m.spend,
       m.link_clicks,
       m.outbound_clicks,
       m.all_clicks,
       m.ctr,
       m.cpc,
       m.cpm,
       m.purchases,
       m.conv_value,
       m.purchase_roas,
       m.ci_count,
       m.atc_count,
       m.thruplays,
       m.p100_plays,
       m.ftewv_count,
       m.ncp_count,
       m.date_start,
       m.date_stop,
       al.ad_status,
       al.ad_created_time::date                          AS ad_created,
       COALESCE(shop.shopify_orders, 0)                  AS shopify_orders,
       COALESCE(shop.shopify_sales, 0)                   AS shopify_sales,
       CASE WHEN m.spend > 0
            THEN ROUND(COALESCE(shop.shopify_sales, 0) / m.spend, 4)
            ELSE 0 END                                   AS shopify_roas,
       COALESCE(shop.new_customers, 0)                   AS new_customers,
       -- ADDITIVE: one first order per person, so the order count and
       -- the customer count are the same number.
       COALESCE(shop.repeat_customer_orders, 0)          AS repeat_customer_orders,
       -- NOT ADDITIVE. Distinct people, counted per row. One person who
       -- buys through two ads is one customer and two rows, so a SUM
       -- down this column in a sheet overstates. Same hazard the
       -- reach_daily_sum / reach_unique_to_date pair exists for.
       COALESCE(shop.repeat_customers_distinct, 0)       AS repeat_customers,
       COALESCE(shop.new_customer_sales, 0)              AS new_customer_sales,
       COALESCE(shop.repeat_customer_sales, 0)           AS repeat_customer_sales,
       -- Acquisition MER: revenue from newly acquired customers over
       -- the ad spend that acquired them, both across this row's
       -- window. Money over money, so it reads like the ROAS columns
       -- beside it rather than like a rate.
       --
       -- NULL, not 0, when nothing was spent: a ratio with an empty
       -- denominator has no value, and 0 would sort a paused entity
       -- below one that genuinely acquired badly.
       CASE WHEN m.spend > 0
            THEN ROUND(COALESCE(shop.new_customer_sales, 0) / m.spend, 4)
            END                                          AS acq_mer,
       shop.matched_tier,
       shop.utm_content,
       shop.utm_term,
       shop.utm_campaign,
       -- Meta's attribution window for this ad, so a sheet can split
       -- last-click revenue by the setting that produced it. NULL where
       -- none is recorded: today that is every account but Fourth.
       al.attribution_setting
  FROM metrics m
  JOIN public.ad_lifecycle al USING (ad_id)
  LEFT JOIN reach_u r USING (ad_id)
  LEFT JOIN shop    USING (ad_id)
 WHERE UPPER(COALESCE(al.ad_status, '')) = 'ACTIVE';

COMMENT ON MATERIALIZED VIEW public.meta_direct_active_90d IS
  'One row per ACTIVE ad over the last 90 days of DATA. Shopify columns come from this project''s corrected last-click attribution. reach_daily_sum is a SUM of daily reach and overcounts people; reach_unique_to_date is the de-duplicated figure.';

-- =====================================================================
-- meta_direct_daily_30d -- one row per ad per day, last 30 days
-- =====================================================================
CREATE MATERIALIZED VIEW public.meta_direct_daily_30d AS
WITH win AS (
  SELECT (SELECT MAX(day) FROM public.insights_daily_by_ad) - 29 AS since,
         (SELECT MAX(day) FROM public.insights_daily_by_ad)              AS until
),
shop AS (
  SELECT a.matched_ad_id AS ad_id,
         a.created_at::date                              AS day,
         COUNT(*)::int                                   AS shopify_orders,
         COALESCE(SUM(a.total_price), 0)                 AS shopify_sales,
         -- New vs repeat, on the same orders the two columns above
         -- count. "New" is the customer's FIRST EVER order, decided
         -- over the whole order history by
         -- scripts/refresh_order_customer_type.py -- not first within
         -- this window.
         COUNT(*) FILTER (WHERE oct.is_new_customer)::int        AS new_customers,
         COUNT(*) FILTER (WHERE NOT oct.is_new_customer)::int    AS repeat_customer_orders,
         COUNT(DISTINCT oct.customer_id)
           FILTER (WHERE NOT oct.is_new_customer)::int           AS repeat_customers_distinct,
         COALESCE(SUM(a.total_price)
           FILTER (WHERE oct.is_new_customer), 0)                AS new_customer_sales,
         COALESCE(SUM(a.total_price)
           FILTER (WHERE NOT oct.is_new_customer), 0)            AS repeat_customer_sales,
         MODE() WITHIN GROUP (ORDER BY a.tier)           AS matched_tier,
         MODE() WITHIN GROUP (ORDER BY a.utm_content)    AS utm_content,
         MODE() WITHIN GROUP (ORDER BY a.utm_term)       AS utm_term,
         MODE() WITHIN GROUP (ORDER BY a.utm_campaign)   AS utm_campaign
    FROM public.shopify_order_attribution a
    LEFT JOIN public.order_customer_type oct ON oct.order_id = a.order_id
    CROSS JOIN win
   WHERE a.matched_ad_id IS NOT NULL
     AND a.created_at::date BETWEEN win.since AND win.until
   GROUP BY a.matched_ad_id, a.created_at::date
)
SELECT i.day                                             AS date,
       al.account_name,
       al.campaign_name,
       al.campaign_id,
       al.adset_id,
       al.adset_name,
       i.ad_id,
       al.ad_name,
       i.impressions,
       -- One day is one de-duplication window, so the daily figure is
       -- a real unique count and needs no caveat.
       i.reach,
       CASE WHEN i.reach > 0
            THEN ROUND(i.impressions::numeric / i.reach::numeric, 4) END AS frequency,
       ROUND(i.spend, 2)                                  AS spend,
       i.clicks                                           AS link_clicks,
       i.outbound_clicks,
       (COALESCE(i.clicks, 0) + COALESCE(i.outbound_clicks, 0))::bigint AS all_clicks,
       CASE WHEN i.impressions > 0
            THEN ROUND(100.0 * i.clicks::numeric / i.impressions::numeric, 4) END AS ctr,
       CASE WHEN i.clicks > 0
            THEN ROUND(i.spend / i.clicks::numeric, 4) END AS cpc,
       CASE WHEN i.impressions > 0
            THEN ROUND(1000.0 * i.spend / i.impressions::numeric, 4) END AS cpm,
       i.purchases,
       i.conv_value,
       CASE WHEN i.spend > 0
            THEN ROUND(i.conv_value / i.spend, 4) END     AS purchase_roas,
       i.checkout_initiate                                AS ci_count,
       i.add_to_cart                                      AS atc_count,
       i.thruplays,
       NULL::bigint                                       AS p100_plays,
       i.ftewv_count,
       i.ncp_count,
       al.ad_status,
       al.ad_created_time::date                           AS ad_created,
       COALESCE(shop.shopify_orders, 0)                   AS shopify_orders,
       COALESCE(shop.shopify_sales, 0)                    AS shopify_sales,
       CASE WHEN i.spend > 0
            THEN ROUND(COALESCE(shop.shopify_sales, 0) / i.spend, 4)
            ELSE 0 END                                    AS shopify_roas,
       COALESCE(shop.new_customers, 0)                   AS new_customers,
       -- ADDITIVE: one first order per person, so the order count and
       -- the customer count are the same number.
       COALESCE(shop.repeat_customer_orders, 0)          AS repeat_customer_orders,
       -- NOT ADDITIVE. Distinct people, counted per row. One person who
       -- buys through two ads is one customer and two rows, so a SUM
       -- down this column in a sheet overstates. Same hazard the
       -- reach_daily_sum / reach_unique_to_date pair exists for.
       COALESCE(shop.repeat_customers_distinct, 0)       AS repeat_customers,
       COALESCE(shop.new_customer_sales, 0)              AS new_customer_sales,
       COALESCE(shop.repeat_customer_sales, 0)           AS repeat_customer_sales,
       -- Acquisition MER: revenue from newly acquired customers over
       -- the ad spend that acquired them, both across this row's
       -- window. Money over money, so it reads like the ROAS columns
       -- beside it rather than like a rate.
       --
       -- NULL, not 0, when nothing was spent: a ratio with an empty
       -- denominator has no value, and 0 would sort a paused entity
       -- below one that genuinely acquired badly.
       CASE WHEN i.spend > 0
            THEN ROUND(COALESCE(shop.new_customer_sales, 0) / i.spend, 4)
            END                                          AS acq_mer,
       shop.matched_tier,
       shop.utm_content,
       shop.utm_term,
       shop.utm_campaign,
       al.attribution_setting
  FROM public.insights_daily_by_ad i
  CROSS JOIN win
  JOIN public.ad_lifecycle al ON al.ad_id = i.ad_id
  LEFT JOIN shop ON shop.ad_id = i.ad_id AND shop.day = i.day
 WHERE i.day BETWEEN win.since AND win.until
   AND i.impressions IS NOT NULL AND i.impressions > 0;

COMMENT ON MATERIALIZED VIEW public.meta_direct_daily_30d IS
  'One row per ad per day over the last 30 days of DATA. Shopify columns come from this project''s corrected last-click attribution.';

-- =====================================================================
-- meta_direct_daily_90d -- one row per ad per day, last 90 days
-- =====================================================================
CREATE MATERIALIZED VIEW public.meta_direct_daily_90d AS
WITH win AS (
  SELECT (SELECT MAX(day) FROM public.insights_daily_by_ad) - 89 AS since,
         (SELECT MAX(day) FROM public.insights_daily_by_ad)              AS until
),
shop AS (
  SELECT a.matched_ad_id AS ad_id,
         a.created_at::date                              AS day,
         COUNT(*)::int                                   AS shopify_orders,
         COALESCE(SUM(a.total_price), 0)                 AS shopify_sales,
         -- New vs repeat, on the same orders the two columns above
         -- count. "New" is the customer's FIRST EVER order, decided
         -- over the whole order history by
         -- scripts/refresh_order_customer_type.py -- not first within
         -- this window.
         COUNT(*) FILTER (WHERE oct.is_new_customer)::int        AS new_customers,
         COUNT(*) FILTER (WHERE NOT oct.is_new_customer)::int    AS repeat_customer_orders,
         COUNT(DISTINCT oct.customer_id)
           FILTER (WHERE NOT oct.is_new_customer)::int           AS repeat_customers_distinct,
         COALESCE(SUM(a.total_price)
           FILTER (WHERE oct.is_new_customer), 0)                AS new_customer_sales,
         COALESCE(SUM(a.total_price)
           FILTER (WHERE NOT oct.is_new_customer), 0)            AS repeat_customer_sales,
         MODE() WITHIN GROUP (ORDER BY a.tier)           AS matched_tier,
         MODE() WITHIN GROUP (ORDER BY a.utm_content)    AS utm_content,
         MODE() WITHIN GROUP (ORDER BY a.utm_term)       AS utm_term,
         MODE() WITHIN GROUP (ORDER BY a.utm_campaign)   AS utm_campaign
    FROM public.shopify_order_attribution a
    LEFT JOIN public.order_customer_type oct ON oct.order_id = a.order_id
    CROSS JOIN win
   WHERE a.matched_ad_id IS NOT NULL
     AND a.created_at::date BETWEEN win.since AND win.until
   GROUP BY a.matched_ad_id, a.created_at::date
)
SELECT i.day                                             AS date,
       al.account_name,
       al.campaign_name,
       al.campaign_id,
       al.adset_id,
       al.adset_name,
       i.ad_id,
       al.ad_name,
       i.impressions,
       -- One day is one de-duplication window, so the daily figure is
       -- a real unique count and needs no caveat.
       i.reach,
       CASE WHEN i.reach > 0
            THEN ROUND(i.impressions::numeric / i.reach::numeric, 4) END AS frequency,
       ROUND(i.spend, 2)                                  AS spend,
       i.clicks                                           AS link_clicks,
       i.outbound_clicks,
       (COALESCE(i.clicks, 0) + COALESCE(i.outbound_clicks, 0))::bigint AS all_clicks,
       CASE WHEN i.impressions > 0
            THEN ROUND(100.0 * i.clicks::numeric / i.impressions::numeric, 4) END AS ctr,
       CASE WHEN i.clicks > 0
            THEN ROUND(i.spend / i.clicks::numeric, 4) END AS cpc,
       CASE WHEN i.impressions > 0
            THEN ROUND(1000.0 * i.spend / i.impressions::numeric, 4) END AS cpm,
       i.purchases,
       i.conv_value,
       CASE WHEN i.spend > 0
            THEN ROUND(i.conv_value / i.spend, 4) END     AS purchase_roas,
       i.checkout_initiate                                AS ci_count,
       i.add_to_cart                                      AS atc_count,
       i.thruplays,
       NULL::bigint                                       AS p100_plays,
       i.ftewv_count,
       i.ncp_count,
       al.ad_status,
       al.ad_created_time::date                           AS ad_created,
       COALESCE(shop.shopify_orders, 0)                   AS shopify_orders,
       COALESCE(shop.shopify_sales, 0)                    AS shopify_sales,
       CASE WHEN i.spend > 0
            THEN ROUND(COALESCE(shop.shopify_sales, 0) / i.spend, 4)
            ELSE 0 END                                    AS shopify_roas,
       COALESCE(shop.new_customers, 0)                   AS new_customers,
       -- ADDITIVE: one first order per person, so the order count and
       -- the customer count are the same number.
       COALESCE(shop.repeat_customer_orders, 0)          AS repeat_customer_orders,
       -- NOT ADDITIVE. Distinct people, counted per row. One person who
       -- buys through two ads is one customer and two rows, so a SUM
       -- down this column in a sheet overstates. Same hazard the
       -- reach_daily_sum / reach_unique_to_date pair exists for.
       COALESCE(shop.repeat_customers_distinct, 0)       AS repeat_customers,
       COALESCE(shop.new_customer_sales, 0)              AS new_customer_sales,
       COALESCE(shop.repeat_customer_sales, 0)           AS repeat_customer_sales,
       -- Acquisition MER: revenue from newly acquired customers over
       -- the ad spend that acquired them, both across this row's
       -- window. Money over money, so it reads like the ROAS columns
       -- beside it rather than like a rate.
       --
       -- NULL, not 0, when nothing was spent: a ratio with an empty
       -- denominator has no value, and 0 would sort a paused entity
       -- below one that genuinely acquired badly.
       CASE WHEN i.spend > 0
            THEN ROUND(COALESCE(shop.new_customer_sales, 0) / i.spend, 4)
            END                                          AS acq_mer,
       shop.matched_tier,
       shop.utm_content,
       shop.utm_term,
       shop.utm_campaign,
       al.attribution_setting
  FROM public.insights_daily_by_ad i
  CROSS JOIN win
  JOIN public.ad_lifecycle al ON al.ad_id = i.ad_id
  LEFT JOIN shop ON shop.ad_id = i.ad_id AND shop.day = i.day
 WHERE i.day BETWEEN win.since AND win.until
   AND i.impressions IS NOT NULL AND i.impressions > 0;

COMMENT ON MATERIALIZED VIEW public.meta_direct_daily_90d IS
  'One row per ad per day over the last 90 days of DATA. Shopify columns come from this project''s corrected last-click attribution.';

-- ---------------------------------------------------------------------
-- Access.
--
-- Supabase grants every privilege on new objects in `public` to anon,
-- authenticated and service_role by default, so these views were
-- readable by the ANON key the moment they were created. That key is
-- published in client-side code by design, and these views carry full
-- spend and revenue per ad.
--
-- No customer PII is exposed here -- no names, emails, addresses or
-- phone numbers, only ad performance and order aggregates -- but a P&L
-- is not something to serve from a public key.
--
-- anon is revoked. service_role keeps access, which is what a Google
-- Apps Script should authenticate with: the script runs on Google's
-- servers, so the key never reaches whoever opens the sheet.
-- authenticated keeps read access for signed-in project users.
--
-- To deliberately allow anon (only if the data is meant to be public):
--   GRANT SELECT ON public.meta_direct_active_30d TO anon;
-- ---------------------------------------------------------------------
REVOKE ALL ON public.meta_direct_active_30d   FROM anon;
REVOKE ALL ON public.meta_direct_active_90d   FROM anon;
REVOKE ALL ON public.meta_direct_daily_30d    FROM anon;
REVOKE ALL ON public.meta_direct_daily_90d    FROM anon;
REVOKE ALL ON public.meta_direct_data_through FROM anon;

-- A view is not a table: writes make no sense on any of these.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.meta_direct_active_30d   FROM authenticated;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.meta_direct_active_90d   FROM authenticated;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.meta_direct_daily_30d    FROM authenticated;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.meta_direct_daily_90d    FROM authenticated;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.meta_direct_data_through FROM authenticated;


-- =====================================================================
-- meta_direct_adset_30d / meta_direct_campaign_30d
--   one row per ad set / campaign, last 30 days of DATA
--
-- Grain, mapping and additivity all follow the ad-level views above.
-- Three things are specific to this pair:
--
--  1. ATTRIBUTION MAPPING. An order reaches a campaign through
--     `matched_campaign_id` and an ad set through `utm_term`, which is
--     the ad set id Meta writes into the URL. That is deliberately the
--     same mapping app/api/routers/analytics.py uses for its rollup
--     (`_customer_mix_rollup_sql`, `_rolling_lc_sql`), so the sheet and
--     the dashboard can never disagree about which orders belong to an
--     entity. The utm_source guard on the ad set side keeps a non-Meta
--     order whose utm_term happens to collide with an ad set id out.
--
--  2. THE WINDOW IS THIS TABLE'S OWN. Each view anchors on MAX(day) of
--     the entity table it reads, not on insights_daily_by_ad's. The
--     three tables are built by different steps of the nightly and can
--     land a day apart; anchoring each on its own source keeps spend
--     and orders describing the same dates even on a night when one
--     step failed.
--
--  3. ROLLING 3d / 7d. Revenue and spend are each summed over the last
--     3 and 7 days ENDING AT THE SAME `until`, so the ratio is a real
--     window ROAS rather than a short revenue window over a long spend
--     one. A window with no spend yields NULL, not 0 -- "nothing was
--     spent" and "spent and earned nothing" are different findings, and
--     a sheet sorted by ROAS must not put the former at the bottom.
-- =====================================================================
CREATE MATERIALIZED VIEW public.meta_direct_adset_30d AS
WITH win AS (
  SELECT (SELECT MAX(day) FROM public.insights_daily_by_adset) - 29 AS since,
         (SELECT MAX(day) FROM public.insights_daily_by_adset)      AS until
),
metrics AS (
  SELECT i.adset_id,
         SUM(i.impressions)                                     AS impressions,
         SUM(i.reach)                                           AS reach_daily_sum,
         CASE WHEN SUM(i.reach) > 0
              THEN ROUND(SUM(i.impressions)::numeric / SUM(i.reach)::numeric, 4)
              END                                               AS frequency,
         ROUND(SUM(i.spend), 2)                                 AS spend,
         SUM(i.clicks)                                          AS link_clicks,
         SUM(i.all_clicks)                                      AS all_clicks,
         CASE WHEN SUM(i.impressions) > 0
              THEN ROUND(100.0 * SUM(i.clicks)::numeric / SUM(i.impressions)::numeric, 4)
              END                                               AS ctr,
         CASE WHEN SUM(i.clicks) > 0
              THEN ROUND(SUM(i.spend) / SUM(i.clicks)::numeric, 4)
              END                                               AS cpc,
         CASE WHEN SUM(i.impressions) > 0
              THEN ROUND(1000.0 * SUM(i.spend) / SUM(i.impressions)::numeric, 4)
              END                                               AS cpm,
         SUM(i.purchases)                                       AS purchases,
         SUM(i.conv_value)                                      AS conv_value,
         CASE WHEN SUM(i.spend) > 0
              THEN ROUND(SUM(i.conv_value) / SUM(i.spend), 4)
              END                                               AS purchase_roas,
         SUM(i.ftewv_count)                                     AS ftewv_count,
         MIN(i.day)                                             AS date_start,
         MAX(i.day)                                             AS date_stop,
         -- Rolling spend, same `until` as the revenue below.
         ROUND(SUM(i.spend) FILTER (WHERE i.day > (SELECT until FROM win) - 3), 2) AS d3_spend,
         ROUND(SUM(i.spend) FILTER (WHERE i.day > (SELECT until FROM win) - 7), 2) AS d7_spend
    FROM public.insights_daily_by_adset i, win
   WHERE i.day BETWEEN win.since AND win.until
   GROUP BY i.adset_id
),
shop AS (
  SELECT a.utm_term AS adset_id,
         COUNT(*)::int                                          AS shopify_orders,
         COALESCE(SUM(a.total_price), 0)                        AS shopify_sales,
         COUNT(*) FILTER (WHERE oct.is_new_customer)::int       AS new_customers,
         COUNT(*) FILTER (WHERE NOT oct.is_new_customer)::int   AS repeat_customer_orders,
         COUNT(DISTINCT oct.customer_id)
           FILTER (WHERE NOT oct.is_new_customer)::int          AS repeat_customers_distinct,
         COALESCE(SUM(a.total_price)
           FILTER (WHERE oct.is_new_customer), 0)               AS new_customer_sales,
         COALESCE(SUM(a.total_price)
           FILTER (WHERE NOT oct.is_new_customer), 0)           AS repeat_customer_sales,
         COALESCE(SUM(a.total_price)
           FILTER (WHERE a.created_at::date > (SELECT until FROM win) - 3), 0) AS d3_lc_revenue,
         COALESCE(SUM(a.total_price)
           FILTER (WHERE a.created_at::date > (SELECT until FROM win) - 7), 0) AS d7_lc_revenue
    FROM public.shopify_order_attribution a
    LEFT JOIN public.order_customer_type oct ON oct.order_id = a.order_id
    JOIN public.meta_adsets s ON s.adset_id = a.utm_term
    CROSS JOIN win
   WHERE a.utm_term IS NOT NULL AND BTRIM(a.utm_term) <> ''
     AND LOWER(COALESCE(a.utm_source, '')) ~ '(meta|facebook|fb|instagram|ig)'
     AND a.created_at::date BETWEEN win.since AND win.until
   GROUP BY a.utm_term
)
SELECT s.account_name,
       s.campaign_id,
       s.campaign_name,
       m.adset_id,
       s.adset_name,
       s.adset_status,
       m.impressions,
       m.reach_daily_sum,
       m.frequency,
       m.spend,
       m.link_clicks,
       m.all_clicks,
       m.ctr,
       m.cpc,
       m.cpm,
       m.purchases,
       m.conv_value,
       m.purchase_roas,
       m.ftewv_count,
       COALESCE(shop.shopify_orders, 0)                         AS shopify_orders,
       COALESCE(shop.shopify_sales, 0)                          AS shopify_sales,
       CASE WHEN m.spend > 0
            THEN ROUND(COALESCE(shop.shopify_sales, 0) / m.spend, 4)
            END                                                 AS shopify_roas,
       COALESCE(shop.new_customers, 0)                          AS new_customers,
       COALESCE(shop.repeat_customer_orders, 0)                 AS repeat_customer_orders,
       -- NOT ADDITIVE -- distinct people, per row. See the ad views.
       COALESCE(shop.repeat_customers_distinct, 0)              AS repeat_customers,
       COALESCE(shop.new_customer_sales, 0)                     AS new_customer_sales,
       COALESCE(shop.repeat_customer_sales, 0)                  AS repeat_customer_sales,
       -- Revenue from newly acquired customers over the spend that
       -- acquired them. Money over money, like the ROAS columns beside
       -- it; NULL when nothing was spent.
       CASE WHEN m.spend > 0
            THEN ROUND(COALESCE(shop.new_customer_sales, 0) / m.spend, 4)
            END                                                 AS acq_mer,
       m.d3_spend,
       COALESCE(shop.d3_lc_revenue, 0)                          AS d3_lc_revenue,
       CASE WHEN m.d3_spend > 0
            THEN ROUND(COALESCE(shop.d3_lc_revenue, 0) / m.d3_spend, 4)
            END                                                 AS d3_lc_roas,
       m.d7_spend,
       COALESCE(shop.d7_lc_revenue, 0)                          AS d7_lc_revenue,
       CASE WHEN m.d7_spend > 0
            THEN ROUND(COALESCE(shop.d7_lc_revenue, 0) / m.d7_spend, 4)
            END                                                 AS d7_lc_roas,
       m.date_start,
       m.date_stop,
       -- One setting per ad set: measured 2026-10-29, 0 of 502 ad sets
       -- hold ads with more than one. Still aggregated rather than
       -- picked from an arbitrary ad, so the day that stops being true
       -- the column says 'Multiple' instead of silently choosing.
       attr.attribution_setting
  FROM metrics m
  JOIN public.meta_adsets s USING (adset_id)
  LEFT JOIN shop USING (adset_id)
  LEFT JOIN (
    SELECT a.adset_id,
           CASE WHEN COUNT(DISTINCT a.attribution_setting) > 1 THEN 'Multiple'
                ELSE MIN(a.attribution_setting) END AS attribution_setting
      FROM public.meta_ad_attribution a
     WHERE a.adset_id IS NOT NULL
     GROUP BY a.adset_id
  ) attr USING (adset_id);

COMMENT ON MATERIALIZED VIEW public.meta_direct_adset_30d IS
  'One row per ad set over the last 30 days of DATA. Orders map through utm_term, the same mapping Ads Analyse uses. repeat_customers is DISTINCT people and must not be summed across rows; repeat_customer_orders is the additive column. d3/d7 ROAS is last-click revenue over spend across the same window, NULL when nothing was spent.';

-- =====================================================================
CREATE MATERIALIZED VIEW public.meta_direct_campaign_30d AS
WITH win AS (
  SELECT (SELECT MAX(day) FROM public.insights_daily_by_campaign) - 29 AS since,
         (SELECT MAX(day) FROM public.insights_daily_by_campaign)      AS until
),
metrics AS (
  SELECT i.campaign_id,
         SUM(i.impressions)                                     AS impressions,
         SUM(i.reach)                                           AS reach_daily_sum,
         CASE WHEN SUM(i.reach) > 0
              THEN ROUND(SUM(i.impressions)::numeric / SUM(i.reach)::numeric, 4)
              END                                               AS frequency,
         ROUND(SUM(i.spend), 2)                                 AS spend,
         SUM(i.clicks)                                          AS link_clicks,
         SUM(i.all_clicks)                                      AS all_clicks,
         CASE WHEN SUM(i.impressions) > 0
              THEN ROUND(100.0 * SUM(i.clicks)::numeric / SUM(i.impressions)::numeric, 4)
              END                                               AS ctr,
         CASE WHEN SUM(i.clicks) > 0
              THEN ROUND(SUM(i.spend) / SUM(i.clicks)::numeric, 4)
              END                                               AS cpc,
         CASE WHEN SUM(i.impressions) > 0
              THEN ROUND(1000.0 * SUM(i.spend) / SUM(i.impressions)::numeric, 4)
              END                                               AS cpm,
         SUM(i.purchases)                                       AS purchases,
         SUM(i.conv_value)                                      AS conv_value,
         CASE WHEN SUM(i.spend) > 0
              THEN ROUND(SUM(i.conv_value) / SUM(i.spend), 4)
              END                                               AS purchase_roas,
         SUM(i.ftewv_count)                                     AS ftewv_count,
         MIN(i.day)                                             AS date_start,
         MAX(i.day)                                             AS date_stop,
         ROUND(SUM(i.spend) FILTER (WHERE i.day > (SELECT until FROM win) - 3), 2) AS d3_spend,
         ROUND(SUM(i.spend) FILTER (WHERE i.day > (SELECT until FROM win) - 7), 2) AS d7_spend
    FROM public.insights_daily_by_campaign i, win
   WHERE i.day BETWEEN win.since AND win.until
   GROUP BY i.campaign_id
),
shop AS (
  SELECT a.matched_campaign_id AS campaign_id,
         COUNT(*)::int                                          AS shopify_orders,
         COALESCE(SUM(a.total_price), 0)                        AS shopify_sales,
         COUNT(*) FILTER (WHERE oct.is_new_customer)::int       AS new_customers,
         COUNT(*) FILTER (WHERE NOT oct.is_new_customer)::int   AS repeat_customer_orders,
         COUNT(DISTINCT oct.customer_id)
           FILTER (WHERE NOT oct.is_new_customer)::int          AS repeat_customers_distinct,
         COALESCE(SUM(a.total_price)
           FILTER (WHERE oct.is_new_customer), 0)               AS new_customer_sales,
         COALESCE(SUM(a.total_price)
           FILTER (WHERE NOT oct.is_new_customer), 0)           AS repeat_customer_sales,
         COALESCE(SUM(a.total_price)
           FILTER (WHERE a.created_at::date > (SELECT until FROM win) - 3), 0) AS d3_lc_revenue,
         COALESCE(SUM(a.total_price)
           FILTER (WHERE a.created_at::date > (SELECT until FROM win) - 7), 0) AS d7_lc_revenue
    FROM public.shopify_order_attribution a
    LEFT JOIN public.order_customer_type oct ON oct.order_id = a.order_id
    CROSS JOIN win
   WHERE a.matched_campaign_id IS NOT NULL
     AND a.created_at::date BETWEEN win.since AND win.until
   GROUP BY a.matched_campaign_id
)
SELECT c.account_name,
       m.campaign_id,
       c.campaign_name,
       c.campaign_status,
       c.objective,
       m.impressions,
       m.reach_daily_sum,
       m.frequency,
       m.spend,
       m.link_clicks,
       m.all_clicks,
       m.ctr,
       m.cpc,
       m.cpm,
       m.purchases,
       m.conv_value,
       m.purchase_roas,
       m.ftewv_count,
       COALESCE(shop.shopify_orders, 0)                         AS shopify_orders,
       COALESCE(shop.shopify_sales, 0)                          AS shopify_sales,
       CASE WHEN m.spend > 0
            THEN ROUND(COALESCE(shop.shopify_sales, 0) / m.spend, 4)
            END                                                 AS shopify_roas,
       COALESCE(shop.new_customers, 0)                          AS new_customers,
       COALESCE(shop.repeat_customer_orders, 0)                 AS repeat_customer_orders,
       COALESCE(shop.repeat_customers_distinct, 0)              AS repeat_customers,
       COALESCE(shop.new_customer_sales, 0)                     AS new_customer_sales,
       COALESCE(shop.repeat_customer_sales, 0)                  AS repeat_customer_sales,
       -- Revenue from newly acquired customers over the spend that
       -- acquired them. Money over money, like the ROAS columns beside
       -- it; NULL when nothing was spent.
       CASE WHEN m.spend > 0
            THEN ROUND(COALESCE(shop.new_customer_sales, 0) / m.spend, 4)
            END                                                 AS acq_mer,
       m.d3_spend,
       COALESCE(shop.d3_lc_revenue, 0)                          AS d3_lc_revenue,
       CASE WHEN m.d3_spend > 0
            THEN ROUND(COALESCE(shop.d3_lc_revenue, 0) / m.d3_spend, 4)
            END                                                 AS d3_lc_roas,
       m.d7_spend,
       COALESCE(shop.d7_lc_revenue, 0)                          AS d7_lc_revenue,
       CASE WHEN m.d7_spend > 0
            THEN ROUND(COALESCE(shop.d7_lc_revenue, 0) / m.d7_spend, 4)
            END                                                 AS d7_lc_roas,
       m.date_start,
       m.date_stop,
       -- 12 of 87 campaigns run ads on more than one setting, so this
       -- cannot be a single value for every row. 'Multiple' is Meta's
       -- own label for the case, and is the honest answer: a campaign
       -- mixing windows has no one window.
       attr.attribution_setting
  FROM metrics m
  JOIN public.meta_campaigns c USING (campaign_id)
  LEFT JOIN shop USING (campaign_id)
  LEFT JOIN (
    SELECT l.campaign_id,
           CASE WHEN COUNT(DISTINCT a.attribution_setting) > 1 THEN 'Multiple'
                ELSE MIN(a.attribution_setting) END AS attribution_setting
      FROM public.meta_ad_attribution a
      JOIN public.ad_lifecycle l ON l.ad_id = a.ad_id
     WHERE l.campaign_id IS NOT NULL
     GROUP BY l.campaign_id
  ) attr USING (campaign_id);

COMMENT ON MATERIALIZED VIEW public.meta_direct_campaign_30d IS
  'One row per campaign over the last 30 days of DATA. Orders map through matched_campaign_id, the same mapping Ads Analyse uses. repeat_customers is DISTINCT people and must not be summed across rows. d3/d7 ROAS is last-click revenue over spend across the same window, NULL when nothing was spent.';

-- ---------------------------------------------------------------------
-- Refresh support.
--
-- These are MATERIALIZED views: a plain view recomputes on every read,
-- and meta_direct_daily_90d is 100k rows that take ~9s to build --
-- which a Google Sheet would pay on every page of 1,000 rows it pulls.
--
-- Each carries a UNIQUE index so the nightly job can use REFRESH
-- MATERIALIZED VIEW CONCURRENTLY. Without CONCURRENTLY the refresh
-- holds an ACCESS EXCLUSIVE lock and any sheet pulling at that moment
-- blocks until it finishes.
-- ---------------------------------------------------------------------
CREATE UNIQUE INDEX IF NOT EXISTS ux_mdir_active_30d ON public.meta_direct_active_30d (ad_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_mdir_active_90d ON public.meta_direct_active_90d (ad_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_mdir_daily_30d  ON public.meta_direct_daily_30d  (ad_id, date);
CREATE UNIQUE INDEX IF NOT EXISTS ux_mdir_daily_90d  ON public.meta_direct_daily_90d  (ad_id, date);

-- Sheets filter and sort by date far more than anything else.
CREATE INDEX IF NOT EXISTS ix_mdir_daily_30d_date ON public.meta_direct_daily_30d (date);
CREATE INDEX IF NOT EXISTS ix_mdir_daily_90d_date ON public.meta_direct_daily_90d (date);

CREATE UNIQUE INDEX IF NOT EXISTS ux_mdir_adset_30d    ON public.meta_direct_adset_30d    (adset_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_mdir_campaign_30d ON public.meta_direct_campaign_30d (campaign_id);
