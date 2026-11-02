# `shopify_customers`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~984,156 rows (planner estimate) · 634 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `customer_id` | `text` | no |  |
| 2 | `first_name` | `text` | yes |  |
| 3 | `last_name` | `text` | yes |  |
| 4 | `email` | `text` | yes |  |
| 5 | `phone` | `text` | yes |  |
| 6 | `verified_email` | `boolean` | yes |  |
| 7 | `state` | `text` | yes |  |
| 8 | `number_of_orders` | `numeric` | yes |  |
| 9 | `amount_spent` | `numeric` | yes |  |
| 10 | `currency` | `text` | yes |  |
| 11 | `tax_exempt` | `boolean` | yes |  |
| 12 | `tags` | `jsonb` | yes |  |
| 13 | `created_at` | `timestamp with time zone` | yes |  |
| 14 | `updated_at` | `timestamp with time zone` | yes |  |
| 15 | `extracted_at` | `timestamp with time zone` | yes |  |
| 16 | `flattened_at` | `timestamp with time zone` | yes |  |

## Keys and indexes

- **Primary key** — `shopify_customers_pkey`
  - `CREATE UNIQUE INDEX shopify_customers_pkey ON public.shopify_customers USING btree (customer_id)`
- Index — `ix_shopify_customers_email`: `CREATE INDEX ix_shopify_customers_email ON public.shopify_customers USING btree (email)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `customer_id` → `order_customer_type`, `shopify_customer_analytics`, `shopify_order_attribution`, `shopify_orders`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
