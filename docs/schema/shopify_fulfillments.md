# `shopify_fulfillments`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~406,966 rows (planner estimate) · 227 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `fulfillment_id` | `text` | no |  |
| 2 | `day` | `date` | yes |  |
| 3 | `order_id` | `text` | yes |  |
| 4 | `order_name` | `text` | yes |  |
| 5 | `order_fulfillment_status` | `text` | yes |  |
| 6 | `order_payment_status` | `text` | yes |  |
| 7 | `shipping_carrier` | `text` | yes |  |
| 8 | `fulfillment_provider` | `text` | yes |  |
| 9 | `shipping_city` | `text` | yes |  |
| 10 | `shipping_region` | `text` | yes |  |
| 11 | `shipping_country` | `text` | yes |  |
| 12 | `orders_fulfilled` | `numeric` | yes |  |
| 13 | `orders_shipped` | `numeric` | yes |  |
| 14 | `orders_delivered` | `numeric` | yes |  |
| 15 | `orders_with_tracking_included_rate` | `numeric` | yes |  |
| 16 | `median_days_order_to_fulfillment` | `numeric` | yes |  |
| 17 | `median_days_order_to_shipping` | `numeric` | yes |  |
| 18 | `median_days_order_to_delivery` | `numeric` | yes |  |
| 19 | `median_days_fulfillment_to_shipping` | `numeric` | yes |  |
| 20 | `median_days_shipping_to_delivery` | `numeric` | yes |  |
| 21 | `extracted_at` | `timestamp with time zone` | yes |  |
| 22 | `flattened_at` | `timestamp with time zone` | yes |  |
| 23 | `fulfillment_origin_country` | `text` | yes |  |
| 24 | `fulfillment_provider_id` | `text` | yes |  |
| 25 | `inventory_location_id` | `text` | yes |  |
| 26 | `inventory_location_name` | `text` | yes |  |
| 27 | `shop_id` | `text` | yes |  |
| 28 | `shop_name` | `text` | yes |  |
| 29 | `order_checkout_currency` | `text` | yes |  |
| 30 | `order_sales_channel` | `text` | yes |  |
| 31 | `order_sales_channel_id` | `text` | yes |  |
| 32 | `order_landing_page_path` | `text` | yes |  |
| 33 | `order_landing_page_url` | `text` | yes |  |
| 34 | `order_referrer_domain` | `text` | yes |  |
| 35 | `order_referrer_name` | `text` | yes |  |
| 36 | `order_referrer_source` | `text` | yes |  |
| 37 | `order_referrer_url` | `text` | yes |  |
| 38 | `order_utm_source` | `text` | yes |  |
| 39 | `order_utm_campaign` | `text` | yes |  |
| 40 | `order_utm_medium` | `text` | yes |  |
| 41 | `order_utm_content` | `text` | yes |  |
| 42 | `order_utm_term` | `text` | yes |  |
| 43 | `company_id` | `text` | yes |  |
| 44 | `company_name` | `text` | yes |  |
| 45 | `referring_channel` | `text` | yes |  |
| 46 | `referring_medium` | `text` | yes |  |
| 47 | `referring_platform` | `text` | yes |  |
| 48 | `traffic_type` | `text` | yes |  |
| 49 | `market` | `text` | yes |  |
| 50 | `order_cancellation_reason` | `text` | yes |  |
| 51 | `order_risk_level` | `text` | yes |  |
| 52 | `shipping_company` | `text` | yes |  |
| 53 | `shipping_postal_code` | `text` | yes |  |
| 54 | `hour_of_day` | `text` | yes |  |
| 55 | `month_of_year` | `text` | yes |  |
| 56 | `week_of_year` | `text` | yes |  |
| 57 | `shipping_address_id` | `text` | yes |  |
| 58 | `inventory_group_id` | `text` | yes |  |
| 59 | `order_marketing_event_target` | `text` | yes |  |
| 60 | `order_marketing_event_type` | `text` | yes |  |
| 61 | `is_b2b_order` | `boolean` | yes |  |
| 62 | `is_canceled_order` | `boolean` | yes |  |
| 63 | `order_includes_duties` | `boolean` | yes |  |
| 64 | `is_shop_referral_order` | `boolean` | yes |  |
| 65 | `order_is_shopify_protect_covered` | `boolean` | yes |  |
| 66 | `order_is_shopify_protect_eligible` | `boolean` | yes |  |
| 67 | `order_is_shopify_protect_protected` | `boolean` | yes |  |
| 68 | `hour` | `timestamp with time zone` | yes |  |
| 69 | `minute` | `timestamp with time zone` | yes |  |
| 70 | `month` | `timestamp with time zone` | yes |  |
| 71 | `quarter` | `timestamp with time zone` | yes |  |
| 72 | `second` | `timestamp with time zone` | yes |  |
| 73 | `week` | `timestamp with time zone` | yes |  |
| 74 | `year` | `timestamp with time zone` | yes |  |
| 75 | `number_of_products_bought_together` | `numeric` | yes |  |
| 76 | `fulfillment_event_days` | `numeric` | yes |  |
| 77 | `fulfillment_event_hours` | `numeric` | yes |  |
| 78 | `fulfillment_to_shipping_days` | `numeric` | yes |  |
| 79 | `fulfillment_to_shipping_hours` | `numeric` | yes |  |
| 80 | `order_to_delivery_days` | `numeric` | yes |  |
| 81 | `order_to_delivery_hours` | `numeric` | yes |  |
| 82 | `order_to_fulfillment_days` | `numeric` | yes |  |
| 83 | `order_to_fulfillment_hours` | `numeric` | yes |  |
| 84 | `order_to_shipping_days` | `numeric` | yes |  |
| 85 | `order_to_shipping_hours` | `numeric` | yes |  |
| 86 | `shipping_to_delivery_days` | `numeric` | yes |  |
| 87 | `shipping_to_delivery_hours` | `numeric` | yes |  |
| 88 | `median_hours_order_to_fulfillment` | `numeric` | yes |  |
| 89 | `median_hours_order_to_shipping` | `numeric` | yes |  |
| 90 | `median_hours_order_to_delivery` | `numeric` | yes |  |
| 91 | `median_hours_fulfillment_to_shipping` | `numeric` | yes |  |
| 92 | `median_hours_shipping_to_delivery` | `numeric` | yes |  |

## Keys and indexes

- **Primary key** — `shopify_fulfillments_pkey`
  - `CREATE UNIQUE INDEX shopify_fulfillments_pkey ON public.shopify_fulfillments USING btree (fulfillment_id)`
- Index — `ix_shopify_fulfillments_day`: `CREATE INDEX ix_shopify_fulfillments_day ON public.shopify_fulfillments USING btree (day)`
- Index — `ix_shopify_fulfillments_order_id`: `CREATE INDEX ix_shopify_fulfillments_order_id ON public.shopify_fulfillments USING btree (order_id)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `order_id` → `easyecom_returns`, `easyecom_shipments`, `gokwik_orders`, `order_customer_type`, `shopify_discounts`, `shopify_order_attribution`, `shopify_orders`, `shopify_sales`
- `order_name` → `easyecom_delivery_attributed`, `easyecom_returns`, `easyecom_shipments`, `gokwik_orders`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
