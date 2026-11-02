# `order_customer_type`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~432,676 rows (planner estimate) · 235 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `order_id` | `text` | no |  |
| 2 | `customer_id` | `text` | yes |  |
| 3 | `order_seq` | `integer` | yes |  |
| 4 | `is_new_customer` | `boolean` | yes |  |
| 5 | `first_order_at` | `timestamp with time zone` | yes |  |
| 6 | `order_at` | `timestamp with time zone` | yes |  |
| 7 | `order_day` | `date` | yes |  |
| 8 | `total_price` | `numeric` | yes |  |
| 9 | `refreshed_at` | `timestamp with time zone` | yes | `now()` |

## Keys and indexes

- **Primary key** — `order_customer_type_pkey`
  - `CREATE UNIQUE INDEX order_customer_type_pkey ON public.order_customer_type USING btree (order_id)`
- Index — `ix_oct_customer`: `CREATE INDEX ix_oct_customer ON public.order_customer_type USING btree (customer_id)`
- Index — `ix_oct_day`: `CREATE INDEX ix_oct_day ON public.order_customer_type USING btree (order_day)`
- Index — `ix_oct_new`: `CREATE INDEX ix_oct_new ON public.order_customer_type USING btree (is_new_customer)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `customer_id` → `shopify_customer_analytics`, `shopify_customers`, `shopify_order_attribution`, `shopify_orders`
- `order_id` → `easyecom_returns`, `easyecom_shipments`, `gokwik_orders`, `shopify_discounts`, `shopify_fulfillments`, `shopify_order_attribution`, `shopify_orders`, `shopify_sales`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
