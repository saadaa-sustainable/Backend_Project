# `cpis_sku_context`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~100 rows (planner estimate) · 96 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `master_sku` | `text` | no |  |
| 2 | `product_name` | `text` | yes |  |
| 3 | `product_type_count` | `integer` | yes |  |
| 4 | `variant_count` | `integer` | yes |  |
| 5 | `available_variant_count` | `integer` | yes |  |
| 6 | `price_min` | `numeric` | yes |  |
| 7 | `price_max` | `numeric` | yes |  |
| 8 | `units_in_stock` | `numeric` | yes |  |
| 9 | `variant_total_ct` | `integer` | yes |  |
| 10 | `variant_in_stock_ct` | `integer` | yes |  |
| 11 | `variant_in_stock_rate` | `numeric` | yes |  |
| 12 | `size_total_ct` | `integer` | yes |  |
| 13 | `size_in_stock_ct` | `integer` | yes |  |
| 14 | `size_in_stock_rate` | `numeric` | yes |  |
| 15 | `stock_by_size` | `jsonb` | yes |  |
| 16 | `units_sold_30d` | `numeric` | yes |  |
| 17 | `avg_daily_units` | `numeric` | yes |  |
| 18 | `variant_days` | `integer` | yes |  |
| 19 | `oos_variant_days` | `integer` | yes |  |
| 20 | `oos_pct` | `numeric` | yes |  |
| 21 | `inventory_as_of` | `timestamp with time zone` | yes |  |
| 22 | `velocity_anchor_day` | `date` | yes |  |
| 23 | `is_live` | `boolean` | no | `true` |
| 24 | `has_active_variant` | `boolean` | no | `false` |
| 25 | `computed_at` | `timestamp with time zone` | yes |  |
| 26 | `oos_days_30` | `integer` | yes |  |

## Keys and indexes

- **Primary key** — `cpis_sku_context_pkey`
  - `CREATE UNIQUE INDEX cpis_sku_context_pkey ON public.cpis_sku_context USING btree (master_sku)`
- Index — `ix_cpis_sku_context_live`: `CREATE INDEX ix_cpis_sku_context_live ON public.cpis_sku_context USING btree (is_live)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `master_sku` → `cpis_by_sku`, `cpis_by_sku_daily`, `cpis_by_sku_utm`, `cpis_sku_ad_daily`, `cpis_value_weighted_daily`, `inventory_variant_current`, `master_sku_inventory_current`, `master_sku_returns`, `production_sheet_oos`, `sku_page_compare`, `sku_page_map`, `sku_price_change` … and 3 more

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
