-- ---------------------------------------------------------------------
--  DOES NOT RUN YET.
--
--  This joins both sides, so it needs them in ONE database. Today
--  Gokwik_order_data lives in the legacy Meta_ads_data project and
--  shopify_order_attribution lives in the main one, and neither has
--  postgres_fdw or dblink installed (both are available in each).
--
--  To use it, first copy Gokwik_order_data into the main project --
--  the same pattern scripts/ingest_ad_edit_log.py uses for the edit
--  log -- then run this there.
--
--  Until then, run file 1 and file 2 separately and join the two
--  exports on order_name.
-- ---------------------------------------------------------------------
-- Per order, whether the two sides agree on utm_term (i.e. the ad set).
--
-- Validated 2026-09-25 by pulling the GoKwik side across and running
-- this CASE in Python over 30 days:
--     agree               18,842
--     in ours only        13,782
--     neither has one     11,534
--     in GoKwik only       2,044
--     DISAGREE                 0
-- ---------------------------------------------------------------------

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
