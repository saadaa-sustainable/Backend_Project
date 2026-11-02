# `master_sku_inventory_current`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~107 rows (planner estimate) · 152 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `master_sku` | `text` | no |  |
| 2 | `as_of_date` | `date` | no |  |
| 3 | `variant_ct` | `integer` | yes |  |
| 4 | `current_stock` | `bigint` | yes |  |
| 5 | `total_inprogress` | `bigint` | yes |  |
| 6 | `daily_quantity` | `numeric` | yes |  |
| 7 | `t7_quantity` | `numeric` | yes |  |
| 8 | `t45_quantity` | `numeric` | yes |  |
| 9 | `t730_quantity` | `numeric` | yes |  |
| 10 | `total_sales_45d` | `numeric` | yes |  |
| 11 | `doq_7` | `numeric` | yes |  |
| 12 | `doq_15` | `numeric` | yes |  |
| 13 | `doq_30` | `numeric` | yes |  |
| 14 | `doq_45` | `numeric` | yes |  |
| 15 | `doq_90` | `numeric` | yes |  |
| 16 | `doq_365` | `numeric` | yes |  |
| 17 | `doq_7_30` | `numeric` | yes |  |
| 18 | `doq_30_45` | `numeric` | yes |  |
| 19 | `weighted_doq_45` | `numeric` | yes |  |
| 20 | `weightage_doq` | `numeric` | yes |  |
| 21 | `monthly_doq` | `numeric` | yes |  |
| 22 | `yearly_doq` | `numeric` | yes |  |
| 23 | `v_doq` | `numeric` | yes |  |
| 24 | `oos_days_7` | `integer` | yes |  |
| 25 | `oos_days_15` | `integer` | yes |  |
| 26 | `oos_days_30` | `integer` | yes |  |
| 27 | `oos_days_45` | `integer` | yes |  |
| 28 | `oos_days_90` | `integer` | yes |  |
| 29 | `oos_days_365` | `integer` | yes |  |
| 30 | `lead_time` | `integer` | yes |  |
| 31 | `buffer_days` | `integer` | yes |  |
| 32 | `cost_min` | `numeric` | yes |  |
| 33 | `cost_max` | `numeric` | yes |  |
| 34 | `shopify_sp_min` | `numeric` | yes |  |
| 35 | `shopify_sp_max` | `numeric` | yes |  |
| 36 | `variant_in_stock_ct` | `integer` | yes |  |
| 37 | `variant_in_stock_rate` | `numeric` | yes |  |
| 38 | `size_total_ct` | `integer` | yes |  |
| 39 | `size_in_stock_ct` | `integer` | yes |  |
| 40 | `size_in_stock_rate` | `numeric` | yes |  |
| 41 | `stock_by_size` | `jsonb` | yes |  |
| 42 | `refreshed_at` | `timestamp with time zone` | yes | `now()` |

## Keys and indexes

- **Primary key** — `master_sku_inventory_current_pkey`
  - `CREATE UNIQUE INDEX master_sku_inventory_current_pkey ON public.master_sku_inventory_current USING btree (master_sku)`
- Index — `ix_msi_as_of`: `CREATE INDEX ix_msi_as_of ON public.master_sku_inventory_current USING btree (as_of_date)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `as_of_date` → `ad_reach_cumulative`, `inventory_variant_current`
- `master_sku` → `cpis_by_sku`, `cpis_by_sku_daily`, `cpis_by_sku_utm`, `cpis_sku_ad_daily`, `cpis_sku_context`, `cpis_value_weighted_daily`, `inventory_variant_current`, `master_sku_returns`, `production_sheet_oos`, `sku_page_compare`, `sku_page_map`, `sku_price_change` … and 3 more

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
