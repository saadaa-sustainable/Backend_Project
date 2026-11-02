# `shopify_sales_daily`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~306 rows (planner estimate) · 136 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `sales_day_id` | `text` | no |  |
| 2 | `day` | `date` | yes |  |
| 3 | `customers` | `numeric` | yes |  |
| 4 | `average_order_value` | `numeric` | yes |  |
| 5 | `total_sales` | `numeric` | yes |  |
| 6 | `quantity_ordered_per_order` | `numeric` | yes |  |
| 7 | `orders` | `numeric` | yes |  |
| 8 | `new_customers` | `numeric` | yes |  |
| 9 | `returning_customers` | `numeric` | yes |  |
| 10 | `returning_customer_rate` | `numeric` | yes |  |
| 11 | `total_sales_returning` | `numeric` | yes |  |
| 12 | `total_sales_first_time` | `numeric` | yes |  |
| 13 | `net_items_sold` | `numeric` | yes |  |
| 14 | `quantity_ordered` | `numeric` | yes |  |
| 15 | `gross_sales` | `numeric` | yes |  |
| 16 | `net_sales` | `numeric` | yes |  |
| 17 | `discounts` | `numeric` | yes |  |
| 18 | `extracted_at` | `timestamp with time zone` | yes |  |
| 19 | `flattened_at` | `timestamp with time zone` | yes |  |

## Keys and indexes

- **Primary key** — `shopify_sales_daily_pkey`
  - `CREATE UNIQUE INDEX shopify_sales_daily_pkey ON public.shopify_sales_daily USING btree (sales_day_id)`

## Possible joins

No shared key-like column names with other tables.

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
