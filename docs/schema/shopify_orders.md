# `shopify_orders`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~433,058 rows (planner estimate) · 881 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `order_id` | `text` | no |  |
| 2 | `name` | `text` | yes |  |
| 3 | `email` | `text` | yes |  |
| 4 | `financial_status` | `text` | yes |  |
| 5 | `fulfillment_status` | `text` | yes |  |
| 6 | `subtotal_price` | `numeric` | yes |  |
| 7 | `total_price` | `numeric` | yes |  |
| 8 | `currency` | `text` | yes |  |
| 9 | `customer_id` | `text` | yes |  |
| 10 | `customer_email` | `text` | yes |  |
| 11 | `line_items` | `jsonb` | yes |  |
| 12 | `customer_journey` | `jsonb` | yes |  |
| 13 | `created_at` | `timestamp with time zone` | yes |  |
| 14 | `updated_at` | `timestamp with time zone` | yes |  |
| 15 | `processed_at` | `timestamp with time zone` | yes |  |
| 16 | `extracted_at` | `timestamp with time zone` | yes |  |
| 17 | `flattened_at` | `timestamp with time zone` | yes |  |
| 18 | `custom_attributes` | `jsonb` | yes |  |
| 19 | `utm_source` | `text` | yes |  |
| 20 | `utm_medium` | `text` | yes |  |
| 21 | `utm_campaign` | `text` | yes |  |
| 22 | `utm_content` | `text` | yes |  |
| 23 | `utm_term` | `text` | yes |  |
| 24 | `return_status` | `text` | yes |  |
| 25 | `tags` | `jsonb` | yes |  |
| 26 | `cancel_reason` | `text` | yes |  |
| 27 | `cancelled_at` | `timestamp with time zone` | yes |  |
| 28 | `refunds` | `jsonb` | yes |  |
| 29 | `refunded_amount` | `numeric` | yes |  |

## Keys and indexes

- **Primary key** — `shopify_orders_pkey`
  - `CREATE UNIQUE INDEX shopify_orders_pkey ON public.shopify_orders USING btree (order_id)`
- Index — `ix_shopify_orders_created_at`: `CREATE INDEX ix_shopify_orders_created_at ON public.shopify_orders USING btree (created_at)`
- Index — `ix_shopify_orders_customer_id`: `CREATE INDEX ix_shopify_orders_customer_id ON public.shopify_orders USING btree (customer_id)`
- Index — `ix_shopify_orders_extracted_at`: `CREATE INDEX ix_shopify_orders_extracted_at ON public.shopify_orders USING btree (extracted_at DESC)`
- Index — `ix_shopify_orders_processed_at`: `CREATE INDEX ix_shopify_orders_processed_at ON public.shopify_orders USING btree (processed_at) WHERE (utm_content IS NOT NULL)`
- Index — `ix_shopify_orders_processed_at_full`: `CREATE INDEX ix_shopify_orders_processed_at_full ON public.shopify_orders USING btree (processed_at)`
- Index — `ix_shopify_orders_utm_campaign`: `CREATE INDEX ix_shopify_orders_utm_campaign ON public.shopify_orders USING btree (utm_campaign)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `customer_id` → `order_customer_type`, `shopify_customer_analytics`, `shopify_customers`, `shopify_order_attribution`
- `order_id` → `easyecom_returns`, `easyecom_shipments`, `gokwik_orders`, `order_customer_type`, `shopify_discounts`, `shopify_fulfillments`, `shopify_order_attribution`, `shopify_sales`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
