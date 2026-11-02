# `shopify_inventory`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~1,802,583 rows (planner estimate) · 545 MB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `inventory_key` | `text` | no |  |
| 2 | `day` | `date` | yes |  |
| 3 | `product_variant_sku` | `text` | yes |  |
| 4 | `product_title` | `text` | yes |  |
| 5 | `product_variant_title` | `text` | yes |  |
| 6 | `product_status` | `text` | yes |  |
| 7 | `product_type` | `text` | yes |  |
| 8 | `product_vendor` | `text` | yes |  |
| 9 | `ending_inventory_units` | `numeric` | yes |  |
| 10 | `ending_inventory_value` | `numeric` | yes |  |
| 11 | `days_of_inventory_remaining` | `numeric` | yes |  |
| 12 | `sell_through_rate` | `numeric` | yes |  |
| 13 | `inventory_units_sold` | `numeric` | yes |  |
| 14 | `starting_inventory_units` | `numeric` | yes |  |
| 15 | `extracted_at` | `timestamp with time zone` | yes |  |
| 16 | `flattened_at` | `timestamp with time zone` | yes |  |

## Keys and indexes

- **Primary key** — `shopify_inventory_pkey`
  - `CREATE UNIQUE INDEX shopify_inventory_pkey ON public.shopify_inventory USING btree (inventory_key)`
- Index — `ix_shopify_inventory_day`: `CREATE INDEX ix_shopify_inventory_day ON public.shopify_inventory USING btree (day)`
- Index — `ix_shopify_inventory_sku`: `CREATE INDEX ix_shopify_inventory_sku ON public.shopify_inventory USING btree (product_variant_sku)`

## Possible joins

No shared key-like column names with other tables.

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
