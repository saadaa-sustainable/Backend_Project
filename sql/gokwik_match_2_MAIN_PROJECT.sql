-- ---------------------------------------------------------------------
--  RUN THIS IN: the MAIN project  (the one holding the dashboard)
--  It reads public.shopify_order_attribution, which exists ONLY here.
--
--  Do not paste this into the legacy Meta_ads_data project: it will
--  fail with relation "public.shopify_order_attribution" does not
--  exist.
-- ---------------------------------------------------------------------
-- Our last-click attribution for the same orders.
--
-- Join key to GoKwik is `name` (#1552784) against its "Shopify Order
-- Name". shopify_order_id below is the numeric tail of our gid and
-- matches GoKwik's "Merchant Order ID" -- either works.
-- ---------------------------------------------------------------------

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
