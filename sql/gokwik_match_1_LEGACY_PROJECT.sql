-- ---------------------------------------------------------------------
--  RUN THIS IN: the LEGACY project  (Meta_ads_data)
--  It reads Gokwik_order_data, which exists ONLY there.
--
--  Do not paste this into the main project: it will fail with
--  relation "Gokwik_order_data" does not exist.
-- ---------------------------------------------------------------------
-- Normalises GoKwik to one row per order.
--
-- The NULLIF(...,'NA') is the important part. GoKwik writes the literal
-- string 'NA' where there was no UTM, so left alone it counts as data:
-- 5,650 orders in one month carried utm_term 'NA', every one of them
-- utm_source=direct, i.e. not ad traffic at all. Stripped, GoKwik's
-- real utm_term coverage is 62.2% -- against 62.7% on our side.
--
-- "Created At" is D/M/YYYY h:mm AM/PM. A plain ::date cast throws
-- "date/time field value out of range" on 20/9/2026, hence TO_DATE with
-- an explicit format and a regex guard on the rows that are malformed.
-- ---------------------------------------------------------------------

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
