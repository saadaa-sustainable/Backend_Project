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

DROP VIEW IF EXISTS public.meta_direct_active_30d;
DROP MATERIALIZED VIEW IF EXISTS public.meta_direct_active_30d;
DROP VIEW IF EXISTS public.meta_direct_active_90d;
DROP MATERIALIZED VIEW IF EXISTS public.meta_direct_active_90d;
DROP VIEW IF EXISTS public.meta_direct_daily_30d;
DROP MATERIALIZED VIEW IF EXISTS public.meta_direct_daily_30d;
DROP VIEW IF EXISTS public.meta_direct_daily_90d;
DROP MATERIALIZED VIEW IF EXISTS public.meta_direct_daily_90d;

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
         MODE() WITHIN GROUP (ORDER BY a.tier)          AS matched_tier,
         MODE() WITHIN GROUP (ORDER BY a.utm_content)   AS utm_content,
         MODE() WITHIN GROUP (ORDER BY a.utm_term)      AS utm_term,
         MODE() WITHIN GROUP (ORDER BY a.utm_campaign)  AS utm_campaign
    FROM public.shopify_order_attribution a, win
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
       shop.matched_tier,
       shop.utm_content,
       shop.utm_term,
       shop.utm_campaign
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
         MODE() WITHIN GROUP (ORDER BY a.tier)          AS matched_tier,
         MODE() WITHIN GROUP (ORDER BY a.utm_content)   AS utm_content,
         MODE() WITHIN GROUP (ORDER BY a.utm_term)      AS utm_term,
         MODE() WITHIN GROUP (ORDER BY a.utm_campaign)  AS utm_campaign
    FROM public.shopify_order_attribution a, win
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
       shop.matched_tier,
       shop.utm_content,
       shop.utm_term,
       shop.utm_campaign
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
         MODE() WITHIN GROUP (ORDER BY a.tier)           AS matched_tier,
         MODE() WITHIN GROUP (ORDER BY a.utm_content)    AS utm_content,
         MODE() WITHIN GROUP (ORDER BY a.utm_term)       AS utm_term,
         MODE() WITHIN GROUP (ORDER BY a.utm_campaign)   AS utm_campaign
    FROM public.shopify_order_attribution a, win
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
       shop.matched_tier,
       shop.utm_content,
       shop.utm_term,
       shop.utm_campaign
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
         MODE() WITHIN GROUP (ORDER BY a.tier)           AS matched_tier,
         MODE() WITHIN GROUP (ORDER BY a.utm_content)    AS utm_content,
         MODE() WITHIN GROUP (ORDER BY a.utm_term)       AS utm_term,
         MODE() WITHIN GROUP (ORDER BY a.utm_campaign)   AS utm_campaign
    FROM public.shopify_order_attribution a, win
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
       shop.matched_tier,
       shop.utm_content,
       shop.utm_term,
       shop.utm_campaign
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
