# `cpis_by_sku_utm`

<!-- GENERATED above the NOTES marker. Edits there are lost.
     Regenerate: ./.venv/bin/python scripts/gen_schema_docs.py -->

**table** · ~264 rows (planner estimate) · 112 kB

## Columns

| # | column | type | null | default |
|---|---|---|---|---|
| 1 | `master_sku` | `text` | no |  |
| 2 | `window_key` | `text` | no |  |
| 3 | `window_from` | `date` | yes |  |
| 4 | `window_to` | `date` | yes |  |
| 5 | `attributed_orders` | `integer` | yes |  |
| 6 | `attributed_units` | `integer` | yes |  |
| 7 | `attributed_revenue` | `numeric` | yes |  |
| 8 | `matched_ad_count` | `integer` | yes |  |
| 9 | `ad_spend` | `numeric` | yes |  |
| 10 | `cost_per_order` | `numeric` | yes |  |
| 11 | `cost_per_unit_sold` | `numeric` | yes |  |
| 12 | `roas` | `numeric` | yes |  |
| 13 | `computed_at` | `timestamp with time zone` | yes |  |
| 14 | `halo_orders` | `integer` | yes |  |
| 15 | `halo_units` | `numeric` | yes |  |
| 16 | `halo_revenue` | `numeric` | yes |  |
| 17 | `halo_spend` | `numeric` | yes |  |
| 18 | `primary_weight` | `numeric` | yes |  |
| 19 | `ad_spend_vw` | `numeric` | yes |  |
| 20 | `cost_per_order_vw` | `numeric` | yes |  |
| 21 | `cost_per_unit_sold_vw` | `numeric` | yes |  |
| 22 | `roas_vw` | `numeric` | yes |  |
| 23 | `order_revenue` | `numeric` | yes |  |
| 24 | `order_units` | `integer` | yes |  |

## Keys and indexes

- **Primary key** — `cpis_by_sku_utm_pkey`
  - `CREATE UNIQUE INDEX cpis_by_sku_utm_pkey ON public.cpis_by_sku_utm USING btree (master_sku, window_key)`

## Possible joins

This database defines **no foreign keys**, so the following are
*inferred from shared column names only*. Confirm the grain before
trusting one — a shared name does not prove a valid join.

- `master_sku` → `cpis_by_sku`, `cpis_by_sku_daily`, `cpis_sku_ad_daily`, `cpis_sku_context`, `cpis_value_weighted_daily`, `inventory_variant_current`, `master_sku_inventory_current`, `master_sku_returns`, `production_sheet_oos`, `sku_page_compare`, `sku_page_map`, `sku_price_change` … and 3 more
- `window_key` → `cpis_by_sku`, `master_sku_returns`

<!-- NOTES: hand-written below this line survives regeneration -->

## What a row is

_Not yet written._ One row = ?

## Use it for

_Not yet written._

## Traps

_Not yet written._
