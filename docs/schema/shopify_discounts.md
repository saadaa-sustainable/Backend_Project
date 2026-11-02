# `shopify_discounts`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~321,631 rows (planner estimate) · 89 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `discount_key` | `text` | no |  |
| 2 | `day` | `date` | yes |  |
| 3 | `order_id` | `text` | yes |  |
| 4 | `discount_code` | `text` | yes |  |
| 5 | `discount_type` | `text` | yes |  |
| 6 | `discount_method` | `text` | yes |  |
| 7 | `discount_class` | `text` | yes |  |
| 8 | `applied_discounts` | `numeric` | yes |  |
| 9 | `discounted_orders` | `numeric` | yes |  |
| 10 | `product_and_order_discounts` | `numeric` | yes |  |
| 11 | `shipping_discounts` | `numeric` | yes |  |
| 12 | `extracted_at` | `timestamp with time zone` | yes |  |
| 13 | `flattened_at` | `timestamp with time zone` | yes |  |

## Keys and indexes

- **Primary key** — `shopify_discounts_pkey`
  - `CREATE UNIQUE INDEX shopify_discounts_pkey ON public.shopify_discounts USING btree (discount_key)`
- Index — `ix_shopify_discounts_day`: `CREATE INDEX ix_shopify_discounts_day ON public.shopify_discounts USING btree (day)`
- Index — `ix_shopify_discounts_order_id`: `CREATE INDEX ix_shopify_discounts_order_id ON public.shopify_discounts USING btree (order_id)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `order_id` → `easyecom_returns`, `easyecom_shipments`, `gokwik_orders`, `order_customer_type`, `shopify_fulfillments`, `shopify_order_attribution`, `shopify_orders`, `shopify_sales`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
