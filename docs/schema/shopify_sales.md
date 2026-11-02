# `shopify_sales`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~439,898 rows (planner estimate) · 117 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `sales_row_id` | `text` | no |  |
| 2 | `day` | `date` | yes |  |
| 3 | `order_id` | `text` | yes |  |
| 4 | `new_or_returning_customer` | `text` | yes |  |
| 5 | `sales_channel` | `text` | yes |  |
| 6 | `is_pos_sale` | `boolean` | yes |  |
| 7 | `cost_is_recorded` | `boolean` | yes |  |
| 8 | `gross_sales` | `numeric` | yes |  |
| 9 | `net_sales` | `numeric` | yes |  |
| 10 | `total_sales` | `numeric` | yes |  |
| 11 | `discounts` | `numeric` | yes |  |
| 12 | `shipping_charges` | `numeric` | yes |  |
| 13 | `taxes` | `numeric` | yes |  |
| 14 | `duties` | `numeric` | yes |  |
| 15 | `cost_of_goods_sold` | `numeric` | yes |  |
| 16 | `gross_profit` | `numeric` | yes |  |
| 17 | `gross_margin` | `numeric` | yes |  |
| 18 | `orders` | `numeric` | yes |  |
| 19 | `quantity_ordered` | `numeric` | yes |  |
| 20 | `average_order_value` | `numeric` | yes |  |
| 21 | `extracted_at` | `timestamp with time zone` | yes |  |
| 22 | `flattened_at` | `timestamp with time zone` | yes |  |

## Keys and indexes

- **Primary key** — `shopify_sales_pkey`
  - `CREATE UNIQUE INDEX shopify_sales_pkey ON public.shopify_sales USING btree (sales_row_id)`
- Index — `ix_shopify_sales_day`: `CREATE INDEX ix_shopify_sales_day ON public.shopify_sales USING btree (day)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `order_id` → `easyecom_returns`, `easyecom_shipments`, `gokwik_orders`, `order_customer_type`, `shopify_discounts`, `shopify_fulfillments`, `shopify_order_attribution`, `shopify_orders`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
