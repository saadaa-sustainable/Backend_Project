-- ---------------------------------------------------------------------
-- Matching GoKwik orders to our last-click UTM attribution.
--
-- IMPORTANT: the two tables live in DIFFERENT Supabase projects.
--   Gokwik_order_data          -> the legacy Meta_ads_data project
--   shopify_order_attribution  -> this project
-- so there is no single join until one side is copied to the other.
-- Queries A and B are each self-contained; run each in ITS OWN project.
-- Query C is the join, for once GoKwik has been ingested here.
--
-- Join key: GoKwik's "Shopify Order Name" (#1547544) equals our `name`.
-- GoKwik's "Merchant Order ID" (7330033336566) is the numeric tail of
-- our `order_id` (gid://shopify/Order/7330033336566) -- either works;
-- the name is the simpler one.
-- ---------------------------------------------------------------------


-- =====================================================================
-- A. Run in the LEGACY project (Meta_ads_data).
--    Normalises GoKwik into one row per order, UTM placeholders cleaned.
-- =====================================================================
SELECT
    "Shopify Order Name"                                   AS order_name,
    "Merchant Order ID"                                    AS shopify_order_id,
    TO_DATE(SPLIT_PART("Created At", ' ', 1), 'DD/FMMM/YYYY') AS order_date,
    -- GoKwik writes the literal 'NA' where there was no UTM. Left as-is
    -- it counts as data: 5,650 orders in one month carried utm_term
    -- 'NA', all of them utm_source=direct, i.e. not ad traffic at all.
    NULLIF(NULLIF(BTRIM("Utm Source"),  ''), 'NA')         AS utm_source,
    NULLIF(NULLIF(BTRIM("Utm Medium"),  ''), 'NA')         AS utm_medium,
    NULLIF(NULLIF(BTRIM("Utm Campaign"),''), 'NA')         AS utm_campaign,
    NULLIF(NULLIF(BTRIM("Utm Term"),    ''), 'NA')         AS utm_term,
    NULLIF(NULLIF(BTRIM("Utm Content"), ''), 'NA')         AS utm_content,
    "Grand Total"                                          AS order_total,
    "Payment Method"                                       AS payment_method,
    "Merchant Order Status"                                AS order_status,
    "Order Shipment Status"                                AS shipment_status,
    "RTO Risk"                                             AS rto_risk,
    "RTO Remark"                                           AS rto_remark
FROM "Gokwik_order_data"
WHERE SPLIT_PART("Created At", ' ', 1) ~ '^\d{1,2}/\d{1,2}/\d{4}$'
  AND TO_DATE(SPLIT_PART("Created At", ' ', 1), 'DD/FMMM/YYYY')
      >= CURRENT_DATE - 30
ORDER BY order_date DESC, order_name;


-- =====================================================================
-- B. Run in THIS project. The same orders from our side.
-- =====================================================================
SELECT
    a.name                                                 AS order_name,
    SPLIT_PART(a.order_id, '/', 5)                         AS shopify_order_id,
    a.created_at::date                                     AS order_date,
    a.utm_source, a.utm_medium, a.utm_campaign,
    a.utm_term, a.utm_content,
    a.total_price                                          AS order_total,
    a.tier                                                 AS match_tier,
    a.matched_ad_id, a.matched_ad_name,
    a.matched_campaign_id, a.matched_campaign_name
FROM public.shopify_order_attribution a
WHERE a.created_at::date >= CURRENT_DATE - 30
ORDER BY a.created_at DESC, a.name;


-- =====================================================================
-- C. The reconciliation, for once Gokwik_order_data has been copied
--    into THIS project (see the note at the top).
--
--    Reports, per order, whether the two sides agree on utm_term --
--    which is the ad set. Measured 2026-09-25 over 37,735 shared
--    orders: they agreed on every single one where both held a value,
--    and GoKwik never had a utm_term we lacked except the 'NA'
--    placeholder.
-- =====================================================================
WITH gk AS (
    SELECT
        "Shopify Order Name" AS order_name,
        TO_DATE(SPLIT_PART("Created At", ' ', 1), 'DD/FMMM/YYYY') AS order_date,
        NULLIF(NULLIF(BTRIM("Utm Term"),    ''), 'NA') AS utm_term,
        NULLIF(NULLIF(BTRIM("Utm Content"), ''), 'NA') AS utm_content,
        NULLIF(NULLIF(BTRIM("Utm Source"),  ''), 'NA') AS utm_source,
        "Grand Total"           AS order_total,
        "Payment Method"        AS payment_method,
        "Order Shipment Status" AS shipment_status,
        "RTO Risk"              AS rto_risk
    FROM "Gokwik_order_data"
    WHERE SPLIT_PART("Created At", ' ', 1) ~ '^\d{1,2}/\d{1,2}/\d{4}$'
)
SELECT
    COALESCE(a.name, gk.order_name)                AS order_name,
    COALESCE(a.created_at::date, gk.order_date)    AS order_date,
    a.utm_term                                     AS our_utm_term,
    gk.utm_term                                    AS gokwik_utm_term,
    CASE
        WHEN a.name   IS NULL                      THEN 'in GoKwik only'
        WHEN gk.order_name IS NULL                 THEN 'in ours only'
        WHEN a.utm_term IS NOT DISTINCT FROM gk.utm_term
             AND a.utm_term IS NOT NULL            THEN 'agree'
        WHEN a.utm_term IS NULL AND gk.utm_term IS NULL THEN 'neither has one'
        WHEN a.utm_term IS NULL                    THEN 'only GoKwik has one'
        WHEN gk.utm_term IS NULL                   THEN 'only ours has one'
        ELSE                                            'DISAGREE'
    END                                            AS utm_term_verdict,
    a.tier                                         AS our_match_tier,
    a.matched_ad_id,
    a.total_price                                  AS our_total,
    gk.order_total                                 AS gokwik_total,
    -- The columns Shopify does not give us, and the reason this join is
    -- worth having at all.
    gk.payment_method, gk.shipment_status, gk.rto_risk
FROM public.shopify_order_attribution a
FULL JOIN gk ON gk.order_name = a.name
             AND gk.order_date = a.created_at::date
WHERE COALESCE(a.created_at::date, gk.order_date) >= CURRENT_DATE - 30
ORDER BY order_date DESC, order_name;
